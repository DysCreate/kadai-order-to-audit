"""Payments integration tests against real PostgreSQL.

Requirement: Phase 3 exit gate step 7 – allocation, outstanding 3,875 and
ageing buckets, with over-allocation and cross-customer allocation refused.
"""

import uuid
from datetime import date
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command

from apps.accounts.models import User
from apps.masters.models import Customer, Item
from apps.payments.models import Payment, PaymentAllocation
from apps.payments.services import (
    PaymentAllocationInput,
    customer_ageing,
    customer_ledger,
    customer_outstanding,
    invoice_outstanding,
    record_payment,
)
from apps.sales.models import Invoice
from apps.sales.services import (
    CreditNoteLineInput,
    OrderLineInput,
    approve_order,
    create_invoice,
    create_order,
    issue_credit_note,
)
from core.errors import DomainError

INVOICE_DATE = date(2026, 5, 20)


@pytest.fixture
def seeded(db: None) -> None:
    """Appendix A master data, prices, BOM and opening stock."""
    call_command("seed_benchmark", stdout=StringIO())


def _user(username: str) -> User:
    return User.objects.get(username=username)


def _invoice(
    *,
    customer: str = "Retailer A",
    qty: str = "150",
    invoice_date: date = INVOICE_DATE,
) -> Invoice:
    salesman = "salesman_b" if customer == "Distributor B" else "salesman_a"
    order = create_order(
        customer=Customer.objects.get(name=customer),
        lines=[
            OrderLineInput(
                item_id=Item.objects.get(name="Murukku 200 g").pk,
                qty=Decimal(qty),
            )
        ],
        client_uuid=uuid.uuid4(),
        salesman=_user(salesman),
    ).order
    approve_order(order=order, user=_user("admin"))
    return create_invoice(order=order, user=_user("admin"), invoice_date=invoice_date)


def test_payment_allocation_leaves_3875_outstanding(seeded: None) -> None:
    """Appendix A step 7: 7,875 invoice - 4,000 payment = 3,875 due."""
    invoice = _invoice()
    customer = invoice.customer

    payment = record_payment(
        customer=customer,
        amount=Decimal("4000"),
        method="upi",
        allocations=[PaymentAllocationInput(invoice_id=invoice.pk, amount=Decimal("4000"))],
        payment_date=date(2026, 5, 25),
        reference="UPI/8891",
        user=_user("admin"),
    )

    assert payment.amount == Decimal("4000.00")
    allocation = PaymentAllocation.objects.get(payment=payment)
    assert allocation.invoice_id == invoice.pk
    assert allocation.amount == Decimal("4000.00")
    assert invoice_outstanding(invoice) == Decimal("3875.00")
    assert customer_outstanding(customer) == Decimal("3875.00")


def test_allocation_cannot_exceed_the_invoice(seeded: None) -> None:
    """PS 3 payments: allocating more than is due is refused."""
    invoice = _invoice()

    with pytest.raises(DomainError):
        record_payment(
            customer=invoice.customer,
            amount=Decimal("8000"),
            allocations=[PaymentAllocationInput(invoice_id=invoice.pk, amount=Decimal("8000"))],
            payment_date=date(2026, 5, 25),
        )

    assert Payment.objects.count() == 0
    assert invoice_outstanding(invoice) == Decimal("7875.00")


def test_allocations_cannot_exceed_the_amount_received(seeded: None) -> None:
    """PS 3 payments: the sum of allocations stays within the payment."""
    invoice = _invoice()

    with pytest.raises(DomainError):
        record_payment(
            customer=invoice.customer,
            amount=Decimal("3000"),
            allocations=[PaymentAllocationInput(invoice_id=invoice.pk, amount=Decimal("4000"))],
            payment_date=date(2026, 5, 25),
        )

    assert Payment.objects.count() == 0


def test_payment_cannot_settle_another_customers_invoice(seeded: None) -> None:
    """PS 4.12 negative path: allocations are customer-scoped."""
    invoice = _invoice(customer="Retailer A")
    other_customer = Customer.objects.get(name="Distributor B")

    with pytest.raises(DomainError):
        record_payment(
            customer=other_customer,
            amount=Decimal("4000"),
            allocations=[PaymentAllocationInput(invoice_id=invoice.pk, amount=Decimal("4000"))],
            payment_date=date(2026, 5, 25),
        )

    assert PaymentAllocation.objects.count() == 0


def test_cancelled_invoice_cannot_receive_a_payment(seeded: None) -> None:
    """PS 4.9: a fully credited invoice has nothing left to settle."""
    invoice = _invoice(qty="10")
    line = invoice.lines.get()
    issue_credit_note(
        invoice=invoice,
        reason="Order cancelled before dispatch",
        lines=[CreditNoteLineInput(invoice_line_id=line.pk, qty=Decimal("10"))],
        user=_user("admin"),
        note_date=date(2026, 5, 21),
    )

    with pytest.raises(DomainError):
        record_payment(
            customer=invoice.customer,
            amount=Decimal("100"),
            allocations=[PaymentAllocationInput(invoice_id=invoice.pk, amount=Decimal("100"))],
            payment_date=date(2026, 5, 25),
        )


def test_ageing_buckets_follow_the_invoice_date(seeded: None) -> None:
    """PS 3 payments: a January invoice is 90+ days old in November."""
    invoice = _invoice(invoice_date=date(2026, 1, 5))

    buckets = {
        bucket.label: bucket.amount
        for bucket in customer_ageing(invoice.customer, as_of=date(2026, 11, 21))
    }

    assert buckets == {
        "0-30": Decimal("0.00"),
        "31-60": Decimal("0.00"),
        "61-90": Decimal("0.00"),
        "90+": Decimal("7875.00"),
    }

    record_payment(
        customer=invoice.customer,
        amount=Decimal("4000"),
        allocations=[PaymentAllocationInput(invoice_id=invoice.pk, amount=Decimal("4000"))],
        payment_date=date(2026, 11, 20),
        user=_user("admin"),
    )

    buckets = {
        bucket.label: bucket.amount
        for bucket in customer_ageing(invoice.customer, as_of=date(2026, 11, 21))
    }
    assert buckets["90+"] == Decimal("3875.00")


def test_customer_ledger_shows_invoices_payments_and_ageing(seeded: None) -> None:
    """PS 3 payments: the customer ledger screen reads one service result."""
    invoice = _invoice()
    record_payment(
        customer=invoice.customer,
        amount=Decimal("4000"),
        allocations=[PaymentAllocationInput(invoice_id=invoice.pk, amount=Decimal("4000"))],
        payment_date=date(2026, 5, 25),
        user=_user("admin"),
    )

    ledger = customer_ledger(invoice.customer, as_of=date(2026, 5, 31))

    assert ledger.outstanding == Decimal("3875.00")
    assert len(ledger.invoices) == 1
    assert ledger.invoices[0].invoice.number == invoice.number
    assert ledger.invoices[0].paid == Decimal("4000.00")
    assert ledger.invoices[0].outstanding == Decimal("3875.00")
    assert ledger.invoices[0].age_days == 11
    assert len(ledger.payments) == 1
    assert sum(bucket.amount for bucket in ledger.buckets) == Decimal("3875.00")


def test_unallocated_payment_is_allowed_as_an_advance(seeded: None) -> None:
    """PS 3 payments: money can be received before it is allocated."""
    customer = Customer.objects.get(name="Retailer A")

    payment = record_payment(
        customer=customer,
        amount=Decimal("1000"),
        method="cash",
        payment_date=date(2026, 5, 25),
        user=_user("admin"),
    )

    assert payment.allocations.count() == 0
    assert customer_outstanding(customer) == Decimal("0.00")
