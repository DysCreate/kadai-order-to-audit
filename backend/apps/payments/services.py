"""Payments services – the only code that writes payments and allocations.

Invariants protected:
- A payment is positive and may be partly unallocated (an advance); the sum of
  its allocations can never exceed the amount received.
- An allocation can never exceed the invoice's outstanding balance, and the
  invoice rows are locked while it is checked, so two concurrent payments
  cannot both settle the same money.
- A cancelled invoice (fully credited) cannot receive an allocation.
- Outstanding = invoice total - credit notes - allocated payments. Ageing
  buckets that outstanding by invoice date: 0-30, 31-60, 61-90 and 90+ days.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import QuerySet, Sum

from apps.accounts.models import User
from apps.masters.models import Customer
from apps.sales.models import Invoice
from apps.sales.numbering import kolkata_today
from apps.sales.services import invoice_credited_total, invoice_is_cancelled
from core.audit import log_audit
from core.errors import DomainError, InvalidMovement
from core.money import q2

from .models import Payment, PaymentAllocation, PaymentMethod

AGEING_BUCKETS: tuple[tuple[int, int | None, str], ...] = (
    (0, 30, "0-30"),
    (31, 60, "31-60"),
    (61, 90, "61-90"),
    (91, None, "90+"),
)


@dataclass(frozen=True)
class PaymentAllocationInput:
    """One amount to settle against an invoice."""

    invoice_id: int
    amount: Decimal


@dataclass(frozen=True)
class InvoiceOutstanding:
    """One invoice's outstanding balance and its age in days."""

    invoice: Invoice
    credited: Decimal
    paid: Decimal
    outstanding: Decimal
    age_days: int


@dataclass(frozen=True)
class AgeingBucket:
    """Outstanding money in one ageing bucket."""

    label: str
    amount: Decimal


@dataclass(frozen=True)
class CustomerLedger:
    """A customer's invoices, payments, outstanding total and ageing."""

    customer: Customer
    invoices: tuple[InvoiceOutstanding, ...]
    payments: tuple[Payment, ...]
    outstanding: Decimal
    buckets: tuple[AgeingBucket, ...]


def _as_decimal(value: Decimal | str | int, field: str) -> Decimal:
    if isinstance(value, float):
        raise InvalidMovement(f"{field} must be Decimal, str or int, never float.")
    try:
        return Decimal(value)
    except (InvalidOperation, TypeError) as exc:
        raise InvalidMovement(f"{field} is not a valid decimal: {value!r}.") from exc


def invoice_allocated_total(invoice: Invoice) -> Decimal:
    """Total allocated to an invoice across every payment."""
    total = PaymentAllocation.objects.filter(invoice=invoice).aggregate(total=Sum("amount"))[
        "total"
    ]
    return q2(total or Decimal("0.00"))


def invoice_outstanding(invoice: Invoice) -> Decimal:
    """Money still due on one invoice: total - credits - allocations."""
    credited = invoice_credited_total(invoice)
    paid = invoice_allocated_total(invoice)
    outstanding = invoice.total - credited - paid
    return q2(max(outstanding, Decimal("0.00")))


def customer_outstanding(customer: Customer) -> Decimal:
    """Money still due from a customer across every invoice."""
    total = Decimal("0.00")
    for invoice in Invoice.objects.filter(customer=customer).order_by("pk"):
        total += invoice_outstanding(invoice)
    return q2(total)


def _age_days(invoice: Invoice, as_of: date) -> int:
    days = (as_of - invoice.invoice_date).days
    return days if days > 0 else 0


def ageing_bucket_labels() -> list[str]:
    """Return the ageing bucket labels in order (0-30, 31-60, 61-90, 90+)."""
    return [label for _low, _high, label in AGEING_BUCKETS]


def _bucket_for(age_days: int) -> str:
    for low, high, label in AGEING_BUCKETS:
        if high is None and age_days >= low:
            return label
        if high is not None and low <= age_days <= high:
            return label
    return AGEING_BUCKETS[-1][2]


def customer_ageing(customer: Customer, *, as_of: date | None = None) -> list[AgeingBucket]:
    """Bucket a customer's outstanding money by invoice age."""
    business_date = as_of or kolkata_today()
    totals: dict[str, Decimal] = {label: Decimal("0.00") for _low, _high, label in AGEING_BUCKETS}
    for invoice in Invoice.objects.filter(customer=customer).order_by("pk"):
        outstanding = invoice_outstanding(invoice)
        if outstanding == 0:
            continue
        totals[_bucket_for(_age_days(invoice, business_date))] += outstanding
    return [
        AgeingBucket(label=label, amount=q2(totals[label])) for _low, _high, label in AGEING_BUCKETS
    ]


def customer_ledger(customer: Customer, *, as_of: date | None = None) -> CustomerLedger:
    """Return invoices with their balances, payments and the ageing buckets."""
    business_date = as_of or kolkata_today()
    rows: list[InvoiceOutstanding] = []
    for invoice in Invoice.objects.filter(customer=customer).order_by("invoice_date", "pk"):
        rows.append(
            InvoiceOutstanding(
                invoice=invoice,
                credited=invoice_credited_total(invoice),
                paid=invoice_allocated_total(invoice),
                outstanding=invoice_outstanding(invoice),
                age_days=_age_days(invoice, business_date),
            )
        )
    payments = tuple(
        Payment.objects.filter(customer=customer)
        .prefetch_related("allocations__invoice")
        .order_by("-payment_date", "-pk")
    )
    return CustomerLedger(
        customer=customer,
        invoices=tuple(rows),
        payments=payments,
        outstanding=customer_outstanding(customer),
        buckets=tuple(customer_ageing(customer, as_of=business_date)),
    )


def payment_queryset_for(user: User, *, customer: Customer | None = None) -> QuerySet[Payment]:
    """Return payments newest first, optionally for one customer."""
    queryset = Payment.objects.select_related("customer").prefetch_related("allocations__invoice")
    if customer is not None:
        queryset = queryset.filter(customer=customer)
    return queryset.order_by("-payment_date", "-pk")


@transaction.atomic
def record_payment(
    *,
    customer: Customer,
    amount: Decimal | str | int,
    method: str = PaymentMethod.CASH,
    allocations: list[PaymentAllocationInput] | None = None,
    payment_date: date | None = None,
    reference: str = "",
    notes: str = "",
    user: User | None = None,
) -> Payment:
    """Record money received and allocate it against invoices.

    Invariants: amount > 0; method is a valid choice; every allocated invoice
    belongs to the customer and is not cancelled; no allocation exceeds that
    invoice's outstanding balance; allocations never exceed the amount
    received; invoice rows are locked while balances are checked; the payment
    is audited in the same transaction.
    """
    received = q2(_as_decimal(amount, "amount"))
    if received <= 0:
        raise DomainError("A payment amount must be greater than zero.")
    if method not in PaymentMethod.values:
        raise DomainError(f"Invalid payment method {method!r}.")

    requested = allocations or []
    if requested:
        invoice_ids = [row.invoice_id for row in requested]
        if len(invoice_ids) != len(set(invoice_ids)):
            raise DomainError("An invoice can only be allocated once per payment.")

        locked = {
            invoice.pk: invoice
            for invoice in Invoice.objects.select_for_update()
            .filter(pk__in=invoice_ids)
            .order_by("pk")
        }
        missing = sorted(set(invoice_ids) - set(locked))
        if missing:
            raise DomainError(f"Unknown invoice id(s): {missing}.")

        total_allocated = Decimal("0.00")
        normalized: list[tuple[Invoice, Decimal]] = []
        for row in requested:
            invoice = locked[row.invoice_id]
            if invoice.customer_id != customer.pk:
                raise DomainError(f"Invoice {invoice.number} belongs to another customer.")
            if invoice_is_cancelled(invoice):
                raise DomainError(f"Invoice {invoice.number} is cancelled by a credit note.")
            allocated = q2(_as_decimal(row.amount, "allocation"))
            if allocated <= 0:
                raise DomainError("An allocation must be greater than zero.")
            outstanding = invoice_outstanding(invoice)
            if allocated > outstanding:
                raise DomainError(
                    f"Cannot allocate {allocated} to {invoice.number}: only {outstanding} is due."
                )
            total_allocated += allocated
            normalized.append((invoice, allocated))

        if total_allocated > received:
            raise DomainError(
                f"Allocations ({total_allocated}) exceed the payment received ({received})."
            )
    else:
        normalized = []

    payment = Payment.objects.create(
        customer=customer,
        amount=received,
        payment_date=payment_date or kolkata_today(),
        method=method,
        reference=reference.strip(),
        notes=notes.strip(),
        created_by=user,
    )
    PaymentAllocation.objects.bulk_create(
        [
            PaymentAllocation(payment=payment, invoice=invoice, amount=allocated)
            for invoice, allocated in normalized
        ]
    )

    log_audit(
        user,
        "Payment",
        payment.pk,
        "create",
        {},
        {
            "customer": customer.name,
            "amount": payment.amount,
            "method": payment.method,
            "payment_date": payment.payment_date,
            "allocations": [
                {"invoice": invoice.number, "amount": allocated}
                for invoice, allocated in normalized
            ],
        },
    )
    return payment
