"""Sales services – the only code that writes orders, invoices and dispatches.

Invariants protected:
- An order is idempotent per ``client_uuid``: a retried submit returns the
  existing order and never creates a second one (AGENTS.md 4.13).
- An order follows SUBMITTED -> APPROVED -> INVOICED -> DISPATCHED, or
  SUBMITTED -> REJECTED; illegal transitions raise InvalidOrderState and every
  transition writes an audit row in the same transaction (AGENTS.md 4.10).
- A salesman may only order for a customer assigned to them; the scope is
  enforced here, not in the UI (AGENTS.md 4.12).
- Order lines snapshot the resolved price (customer list, then default list);
  a later price change cannot rewrite an existing order or invoice.
- Tax is computed per line to paise, CGST + SGST intra-state and IGST
  inter-state, from the customer's state code versus the factory setting.
- Invoices are numbered from a locked per-financial-year counter and are never
  edited: the database trigger rejects UPDATE and DELETE, and corrections are
  credit notes with their own CN series.
- Dispatch posts finished-goods ISSUE rows through ``inventory.services`` and
  is hard-blocked beyond on-hand stock and beyond the undispatched quantity.
- Credited and dispatched quantities are derived from append-only documents,
  so the immutable invoice never needs to be updated.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.db.models import QuerySet, Sum
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.inventory.models import MovementType, SourceType, StockBalance
from apps.inventory.services import Movement, post_movements
from apps.masters.models import Customer, Item, ItemType
from apps.masters.services import get_setting, resolve_price
from apps.production.loop_closer import LoopCloserPlan, RequirementInput, plan_batches
from apps.production.services import get_active_bom, trailing_yield_factor
from core.audit import log_audit
from core.errors import (
    DomainError,
    DuplicateOrder,
    InvalidMovement,
    InvalidOrderState,
    PriceNotFound,
)
from core.money import q2, q4
from core.permissions import PermissionDenied
from core.quantity import q3

from .gst import TaxLineInput, TaxSummary, compute_tax
from .models import (
    CreditNote,
    CreditNoteLine,
    Dispatch,
    DispatchLine,
    DocumentType,
    Invoice,
    InvoiceLine,
    Order,
    OrderLine,
    OrderState,
)
from .numbering import KOLKATA, allocate_document_number, kolkata_today


@dataclass(frozen=True)
class OrderLineInput:
    """One item requested on a new order, before pricing."""

    item_id: int
    qty: Decimal


@dataclass(frozen=True)
class DispatchLineInput:
    """One invoice line quantity leaving the factory."""

    invoice_line_id: int
    qty: Decimal


@dataclass(frozen=True)
class CreditNoteLineInput:
    """One invoice line quantity being credited back."""

    invoice_line_id: int
    qty: Decimal


@dataclass(frozen=True)
class OrderSubmission:
    """Result of an idempotent submit: the order and whether it is new."""

    order: Order
    created: bool


@dataclass(frozen=True)
class CustomerSalesRow:
    """One customer's sales this month, computed on the server."""

    customer: Customer
    order_count: int
    total_qty: Decimal
    total_value: Decimal


@dataclass
class _SalesAccumulator:
    """Mutable per-customer accumulator while summarising orders."""

    customer: Customer
    order_count: int = 0
    total_qty: Decimal = Decimal("0.000")
    total_value: Decimal = Decimal("0.00")


@dataclass(frozen=True)
class CoverageLine:
    """Stock coverage for one order line, net of other commitments."""

    line: OrderLine
    on_hand_qty: Decimal
    committed_qty: Decimal
    available_qty: Decimal
    shortage_qty: Decimal


@dataclass(frozen=True)
class OrderCoverage:
    """Per-line stock coverage plus the tax the order would carry.

    ``loop_closers`` carries one batch plan per finished-goods line that is
    short, so the admin can see whether production (or a purchase) can close
    the gap before approving.
    """

    lines: tuple[CoverageLine, ...]
    total_shortage_qty: Decimal
    tax_preview: TaxSummary
    is_interstate: bool
    loop_closers: tuple[LoopCloserPlan, ...] = ()


def _as_decimal(value: Decimal | str | int, field: str) -> Decimal:
    if isinstance(value, float):
        raise InvalidMovement(f"{field} must be Decimal, str or int, never float.")
    try:
        return Decimal(value)
    except (InvalidOperation, TypeError) as exc:
        raise InvalidMovement(f"{field} is not a valid decimal: {value!r}.") from exc


def _parse_client_uuid(value: uuid.UUID | str) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError) as exc:
        raise InvalidMovement("client_uuid must be a UUID.") from exc


def _factory_state_code() -> str:
    return get_setting("factory_state_code", "33") or "33"


def _lock_order(order: Order) -> Order:
    return Order.objects.select_for_update().get(pk=order.pk)


def _lock_invoice(invoice: Invoice) -> Invoice:
    # Invoices are immutable, but locking the row serialises dispatch/credit
    # note calculations so two requests cannot both take the last quantity.
    return Invoice.objects.select_for_update().get(pk=invoice.pk)


def _order_snapshot(order: Order) -> dict[str, object]:
    lines = order.lines.select_related("item").order_by("pk")
    return {
        "number": order.number,
        "state": order.state,
        "customer": order.customer.name,
        "salesman": order.salesman.username,
        "rejection_reason": order.rejection_reason,
        "lines": [
            {
                "item": line.item.name,
                "qty": line.qty,
                "unit_price": line.unit_price,
            }
            for line in lines
        ],
    }


def _invoice_snapshot(invoice: Invoice) -> dict[str, object]:
    return {
        "number": invoice.number,
        "customer": invoice.customer.name,
        "invoice_date": invoice.invoice_date,
        "place_of_supply_state_code": invoice.place_of_supply_state_code,
        "is_interstate": invoice.is_interstate,
        "taxable_total": invoice.taxable_total,
        "cgst_total": invoice.cgst_total,
        "sgst_total": invoice.sgst_total,
        "igst_total": invoice.igst_total,
        "round_off": invoice.round_off,
        "total": invoice.total,
        "lines": [
            {
                "item": line.description,
                "qty": line.qty,
                "unit_price": line.unit_price,
                "gst_rate": line.gst_rate,
                "line_total": line.line_total,
            }
            for line in invoice.lines.order_by("pk")
        ],
    }


def _assert_salesman_scope(user: User | None, customer: Customer) -> None:
    if user is None or user.role != Role.SALESMAN:
        return
    if not customer.assigned_salesmen.filter(pk=user.pk).exists():
        raise PermissionDenied(
            f"Customer {customer.name!r} is not assigned to salesman {user.username!r}."
        )


def order_queryset_for(user: User) -> QuerySet[Order]:
    """Return the orders a user may see: a salesman sees only their own."""
    queryset = Order.objects.select_related("customer", "salesman").prefetch_related(
        "lines__item__uom"
    )
    if user.role == Role.SALESMAN:
        return queryset.filter(salesman=user)
    return queryset


def customer_sales_summary(*, user: User, month: date | None = None) -> list[CustomerSalesRow]:
    """Return customer-wise sales for one month, newest money first.

    Invariants: only orders that were approved or beyond count (a submitted or
    rejected order is not a sale); the month is a business month in
    Asia/Kolkata; the total is server-computed with ``q2`` so the frontend never
    does money arithmetic.
    """
    business_date = month or kolkata_today()
    start = business_date.replace(day=1)
    next_start = (
        date(start.year + 1, 1, 1) if start.month == 12 else date(start.year, start.month + 1, 1)
    )

    accumulated: dict[int, _SalesAccumulator] = {}
    orders = order_queryset_for(user).filter(
        state__in=[OrderState.APPROVED, OrderState.INVOICED, OrderState.DISPATCHED]
    )
    for order in orders:
        local_date = timezone.localtime(order.created_at, KOLKATA).date()
        if not (start <= local_date < next_start):
            continue
        bucket = accumulated.setdefault(
            order.customer_id,
            _SalesAccumulator(customer=order.customer),
        )
        bucket.order_count += 1
        for line in order.lines.all():
            bucket.total_qty += line.qty
            bucket.total_value += q2(line.qty * line.unit_price)

    rows = [
        CustomerSalesRow(
            customer=bucket.customer,
            order_count=bucket.order_count,
            total_qty=q3(bucket.total_qty),
            total_value=q2(bucket.total_value),
        )
        for bucket in accumulated.values()
    ]
    return sorted(rows, key=lambda row: row.total_value, reverse=True)


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------


@transaction.atomic
def create_order(
    *,
    customer: Customer,
    lines: list[OrderLineInput],
    client_uuid: uuid.UUID | str,
    salesman: User,
    notes: str = "",
) -> OrderSubmission:
    """Submit a sales order once per client UUID.

    Invariants: the customer is assigned to the salesman; at least one line;
    every item is finished goods with a resolvable price; the price is
    snapshotted on the line; a retry with the same UUID and the same
    customer/salesman returns the existing order instead of duplicating it.
    """
    _assert_salesman_scope(salesman, customer)
    identifier = _parse_client_uuid(client_uuid)

    existing = Order.objects.filter(client_uuid=identifier).select_related("customer").first()
    if existing is not None:
        if existing.customer_id != customer.pk or existing.salesman_id != salesman.pk:
            raise DuplicateOrder("That client UUID already belongs to a different order.")
        return OrderSubmission(order=existing, created=False)

    if not lines:
        raise DomainError("An order needs at least one line.")

    seen: set[int] = set()
    normalized: list[OrderLineInput] = []
    for line in lines:
        if line.item_id in seen:
            raise DomainError(f"Item {line.item_id} appears twice on the order.")
        seen.add(line.item_id)
        qty = q3(_as_decimal(line.qty, "qty"))
        if qty <= 0:
            raise DomainError("An order quantity must be greater than zero.")
        normalized.append(OrderLineInput(item_id=line.item_id, qty=qty))

    items = {item.pk: item for item in Item.objects.filter(pk__in=seen).select_related("uom")}
    missing = sorted(seen - set(items))
    if missing:
        raise DomainError(f"Unknown item id(s): {missing}.")

    priced: list[tuple[Item, Decimal, Decimal]] = []
    for line in normalized:
        item = items[line.item_id]
        if item.item_type != ItemType.FG:
            raise DomainError(f"Only finished goods can be sold; {item.name!r} is not.")
        try:
            price = resolve_price(item=item, customer=customer)
        except PriceNotFound as exc:
            raise DomainError(f"No selling price is configured for {item.name!r}.") from exc
        priced.append((item, line.qty, price))

    business_date = kolkata_today()
    try:
        # A savepoint lets two simultaneous retries of the same UUID settle on
        # one order: the loser rolls back and returns the winner's row.
        with transaction.atomic():
            order = Order.objects.create(
                number=allocate_document_number(DocumentType.ORDER, business_date),
                client_uuid=identifier,
                customer=customer,
                salesman=salesman,
                notes=notes.strip(),
            )
            OrderLine.objects.bulk_create(
                [
                    OrderLine(order=order, item=item, qty=qty, unit_price=price)
                    for item, qty, price in priced
                ]
            )
            log_audit(salesman, "Order", order.pk, "create", {}, _order_snapshot(order))
    except IntegrityError:
        existing = Order.objects.filter(client_uuid=identifier).first()
        if existing is None:
            raise
        if existing.customer_id != customer.pk or existing.salesman_id != salesman.pk:
            raise DuplicateOrder("That client UUID already belongs to a different order.") from None
        return OrderSubmission(order=existing, created=False)

    return OrderSubmission(order=order, created=True)


@transaction.atomic
def edit_order_line(
    *,
    order: Order,
    line: OrderLine,
    user: User | None,
    qty: Decimal | str | int | None = None,
    unit_price: Decimal | str | int | None = None,
) -> OrderLine:
    """Edit an order line's quantity or price while the order is SUBMITTED.

    Invariants: only a submitted order may change; the line belongs to the
    order; quantity stays positive and price non-negative; before/after
    snapshots are audited in the same transaction.
    """
    order = _lock_order(order)
    if order.state != OrderState.SUBMITTED:
        raise InvalidOrderState(
            f"Order {order.number} is {order.state}; only a submitted order can be edited."
        )
    if line.order_id != order.pk:
        raise DomainError("That line does not belong to this order.")

    before = _order_snapshot(order)

    if qty is not None:
        quantity = q3(_as_decimal(qty, "qty"))
        if quantity <= 0:
            raise DomainError("An order quantity must be greater than zero.")
        line.qty = quantity
    if unit_price is not None:
        price = q2(_as_decimal(unit_price, "unit_price"))
        if price < 0:
            raise DomainError("An order price cannot be negative.")
        line.unit_price = price
    line.save(update_fields=["qty", "unit_price"])

    log_audit(user, "Order", order.pk, "update", before, _order_snapshot(order))
    return line


@transaction.atomic
def approve_order(*, order: Order, user: User | None) -> Order:
    """Approve a submitted order (admin verification).

    Invariants: only a SUBMITTED order can be approved; approval records the
    approver and time and is audited. Stock is not hard-blocked here, because
    the admin may hold the order for production; dispatch is the hard gate.
    """
    order = _lock_order(order)
    if order.state != OrderState.SUBMITTED:
        raise InvalidOrderState(
            f"Order {order.number} is {order.state}; only a submitted order can be approved."
        )

    before = _order_snapshot(order)
    order.state = OrderState.APPROVED
    order.approved_by = user
    order.approved_at = timezone.now()
    order.save(update_fields=["state", "approved_by", "approved_at", "updated_at"])
    log_audit(user, "Order", order.pk, "approve", before, _order_snapshot(order))
    return order


@transaction.atomic
def reject_order(*, order: Order, reason: str, user: User | None) -> Order:
    """Reject a submitted order with a mandatory reason.

    Invariants: only a SUBMITTED order can be rejected; the reason is stored
    and audited; a rejected order can never be invoiced.
    """
    order = _lock_order(order)
    if order.state != OrderState.SUBMITTED:
        raise InvalidOrderState(
            f"Order {order.number} is {order.state}; only a submitted order can be rejected."
        )
    cleaned_reason = reason.strip()
    if not cleaned_reason:
        raise InvalidMovement("A rejection requires a reason.")

    before = _order_snapshot(order)
    order.state = OrderState.REJECTED
    order.rejection_reason = cleaned_reason
    order.save(update_fields=["state", "rejection_reason", "updated_at"])
    log_audit(user, "Order", order.pk, "reject", before, _order_snapshot(order))
    return order


# ---------------------------------------------------------------------------
# Stock coverage and tax preview
# ---------------------------------------------------------------------------


def _on_hand_qty(item_id: int) -> Decimal:
    balance = StockBalance.objects.filter(item_id=item_id).first()
    return balance.qty if balance is not None else Decimal("0.000")


def _committed_qty(item_id: int, *, exclude_order_id: int | None = None) -> Decimal:
    """Quantity already promised to other documents for one item.

    Approved orders not yet invoiced count, and every invoice's undispatched,
    uncredited quantity counts. The order being checked is excluded so its own
    quantity is not counted against itself.
    """
    approved = OrderLine.objects.filter(order__state=OrderState.APPROVED, item_id=item_id)
    if exclude_order_id is not None:
        approved = approved.exclude(order_id=exclude_order_id)
    approved_qty = approved.aggregate(total=Sum("qty"))["total"] or Decimal("0.000")

    dispatched = dispatched_qty_by_invoice_line_for_item(item_id)
    credited = credited_qty_by_invoice_line_for_item(item_id)
    invoiced_qty = Decimal("0.000")
    for line in InvoiceLine.objects.filter(item_id=item_id).only("pk", "qty"):
        remaining = (
            line.qty
            - dispatched.get(line.pk, Decimal("0.000"))
            - credited.get(line.pk, Decimal("0.000"))
        )
        if remaining > 0:
            invoiced_qty += remaining

    return q3(approved_qty + invoiced_qty)


def dispatched_qty_by_invoice_line_for_item(item_id: int) -> dict[int, Decimal]:
    rows = (
        DispatchLine.objects.filter(invoice_line__item_id=item_id)
        .values("invoice_line_id")
        .annotate(total=Sum("qty"))
    )
    return {int(row["invoice_line_id"]): row["total"] for row in rows}


def credited_qty_by_invoice_line_for_item(item_id: int) -> dict[int, Decimal]:
    rows = (
        CreditNoteLine.objects.filter(invoice_line__item_id=item_id)
        .values("invoice_line_id")
        .annotate(total=Sum("qty"))
    )
    return {int(row["invoice_line_id"]): row["total"] for row in rows}


def _order_tax_preview(order: Order) -> TaxSummary:
    lines = list(order.lines.select_related("item").order_by("pk"))
    interstate = order.customer.state_code != _factory_state_code()
    return compute_tax(
        [
            TaxLineInput(
                key=line.pk,
                qty=line.qty,
                unit_price=line.unit_price,
                gst_rate=line.item.gst_rate,
            )
            for line in lines
        ],
        interstate=interstate,
    )


def _loop_closers(coverage: list[CoverageLine]) -> tuple[LoopCloserPlan, ...]:
    """Build a batch plan for each short finished-goods line.

    A line without an active BOM, or without a shortage, contributes nothing:
    the panel is an answer to a shortage, not a second stock check.
    """
    plans: list[LoopCloserPlan] = []
    for row in coverage:
        item = row.line.item
        if row.shortage_qty <= 0 or item.item_type != ItemType.FG:
            continue
        try:
            bom = get_active_bom(item)
        except DomainError:
            continue

        bom_lines = list(bom.lines.select_related("item__uom").order_by("pk"))
        balances = StockBalance.objects.in_bulk(
            [line.item_id for line in bom_lines], field_name="item_id"
        )
        requirements = [
            RequirementInput(
                item_id=line.item_id,
                item_name=line.item.name,
                uom=line.item.uom.symbol,
                qty_per_batch=line.qty_per_batch,
                stock_qty=(
                    balances[line.item_id].qty if line.item_id in balances else Decimal("0.000")
                ),
            )
            for line in bom_lines
        ]
        plans.append(
            plan_batches(
                product_id=item.pk,
                product_name=item.name,
                shortage_qty=row.shortage_qty,
                batch_output_qty=bom.batch_output_qty,
                yield_factor=trailing_yield_factor(item),
                requirements=requirements,
            )
        )
    return tuple(plans)


def stock_coverage(order: Order) -> OrderCoverage:
    """Return per-line stock coverage and the tax preview for an order.

    ``available`` is on-hand stock minus commitments to other orders and
    invoices, so the admin sees what is actually free for this order. When a
    finished-goods line is short, the result also carries a Loop Closer batch
    plan for that product.
    """
    lines = list(order.lines.select_related("item__uom").order_by("pk"))
    coverage: list[CoverageLine] = []
    total_shortage = Decimal("0.000")
    for line in lines:
        on_hand = _on_hand_qty(line.item_id)
        committed = _committed_qty(line.item_id, exclude_order_id=order.pk)
        available = on_hand - committed
        if available < 0:
            available = Decimal("0.000")
        shortage = line.qty - available
        if shortage < 0:
            shortage = Decimal("0.000")
        total_shortage += shortage
        coverage.append(
            CoverageLine(
                line=line,
                on_hand_qty=on_hand,
                committed_qty=committed,
                available_qty=q3(available),
                shortage_qty=q3(shortage),
            )
        )

    return OrderCoverage(
        lines=tuple(coverage),
        total_shortage_qty=q3(total_shortage),
        tax_preview=_order_tax_preview(order),
        is_interstate=order.customer.state_code != _factory_state_code(),
        loop_closers=_loop_closers(coverage),
    )


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------


@transaction.atomic
def create_invoice(
    *,
    order: Order,
    user: User | None = None,
    invoice_date: date | None = None,
) -> Invoice:
    """Raise the GST invoice for an approved order.

    Invariants: the order is APPROVED and has no invoice yet; every line is
    copied with its HSN, rate, quantity and price snapshot; tax follows the
    place of supply; the invoice number comes from the locked per-FY counter;
    the order moves to INVOICED and both changes are audited.
    """
    order = _lock_order(order)
    if order.state != OrderState.APPROVED:
        raise InvalidOrderState(
            f"Order {order.number} is {order.state}; only an approved order can be invoiced."
        )
    if Invoice.objects.filter(order=order).exists():
        raise InvalidOrderState(f"Order {order.number} already has an invoice.")

    order_lines = list(order.lines.select_related("item").order_by("pk"))
    if not order_lines:
        raise DomainError("An order needs at least one line to be invoiced.")

    business_date = invoice_date or kolkata_today()
    customer = order.customer
    interstate = customer.state_code != _factory_state_code()
    summary = compute_tax(
        [
            TaxLineInput(
                key=line.pk,
                qty=line.qty,
                unit_price=line.unit_price,
                gst_rate=line.item.gst_rate,
            )
            for line in order_lines
        ],
        interstate=interstate,
    )

    before = _order_snapshot(order)
    invoice = Invoice.objects.create(
        number=allocate_document_number(DocumentType.INVOICE, business_date),
        order=order,
        customer=customer,
        invoice_date=business_date,
        place_of_supply_state_code=customer.state_code,
        is_interstate=interstate,
        taxable_total=summary.taxable_total,
        cgst_total=summary.cgst_total,
        sgst_total=summary.sgst_total,
        igst_total=summary.igst_total,
        round_off=summary.round_off,
        total=summary.total,
        created_by=user,
    )

    taxed_by_key = {line.key: line for line in summary.lines}
    InvoiceLine.objects.bulk_create(
        [
            InvoiceLine(
                invoice=invoice,
                item=line.item,
                description=line.item.name,
                hsn_code=line.item.hsn_code,
                qty=line.qty,
                unit_price=line.unit_price,
                gst_rate=line.item.gst_rate,
                taxable_value=taxed_by_key[line.pk].taxable_value,
                cgst=taxed_by_key[line.pk].cgst,
                sgst=taxed_by_key[line.pk].sgst,
                igst=taxed_by_key[line.pk].igst,
                line_total=taxed_by_key[line.pk].line_total,
            )
            for line in order_lines
        ]
    )

    order.state = OrderState.INVOICED
    order.save(update_fields=["state", "updated_at"])
    log_audit(user, "Invoice", invoice.pk, "create", {}, _invoice_snapshot(invoice))
    log_audit(user, "Order", order.pk, "invoice", before, _order_snapshot(order))
    return invoice


def dispatched_qty_by_line(invoice: Invoice) -> dict[int, Decimal]:
    """Dispatched quantity per invoice line, derived from dispatch documents."""
    rows = (
        DispatchLine.objects.filter(dispatch__invoice=invoice)
        .values("invoice_line_id")
        .annotate(total=Sum("qty"))
    )
    return {int(row["invoice_line_id"]): row["total"] for row in rows}


def credited_qty_by_line(invoice: Invoice) -> dict[int, Decimal]:
    """Credited quantity per invoice line, derived from credit notes."""
    rows = (
        CreditNoteLine.objects.filter(credit_note__invoice=invoice)
        .values("invoice_line_id")
        .annotate(total=Sum("qty"))
    )
    return {int(row["invoice_line_id"]): row["total"] for row in rows}


def invoice_is_cancelled(invoice: Invoice) -> bool:
    """True when credit notes cover every invoice line.

    Cancellation is derived, never stored, so the immutable invoice is not
    touched when a credit note is issued.
    """
    lines = list(invoice.lines.all())
    if not lines:
        return False
    credited = credited_qty_by_line(invoice)
    return all(credited.get(line.pk, Decimal("0.000")) >= line.qty for line in lines)


def invoice_credited_total(invoice: Invoice) -> Decimal:
    """Total value of every credit note against an invoice."""
    total = CreditNote.objects.filter(invoice=invoice).aggregate(total=Sum("total"))["total"]
    return q2(total or Decimal("0.00"))


def invoice_dispatched_total(invoice: Invoice) -> Decimal:
    """Total invoiced quantity already dispatched (all lines)."""
    total = DispatchLine.objects.filter(dispatch__invoice=invoice).aggregate(total=Sum("qty"))[
        "total"
    ]
    return q3(total or Decimal("0.000"))


def invoice_remaining_qty(invoice: Invoice) -> dict[int, Decimal]:
    """Quantity still dispatchable per invoice line."""
    dispatched = dispatched_qty_by_line(invoice)
    credited = credited_qty_by_line(invoice)
    remaining: dict[int, Decimal] = {}
    for line in invoice.lines.order_by("pk"):
        left = (
            line.qty
            - dispatched.get(line.pk, Decimal("0.000"))
            - credited.get(line.pk, Decimal("0.000"))
        )
        remaining[line.pk] = q3(max(left, Decimal("0.000")))
    return remaining


def invoice_queryset_for(user: User) -> QuerySet[Invoice]:
    """Return invoices visible to a user (salesmen see their own orders')."""
    queryset = Invoice.objects.select_related("customer", "order").prefetch_related(
        "lines__item__uom"
    )
    if user.role == Role.SALESMAN:
        return queryset.filter(order__salesman=user)
    return queryset


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def _invoice_fully_dispatched(invoice: Invoice) -> bool:
    remaining = invoice_remaining_qty(invoice)
    return bool(remaining) and all(qty == 0 for qty in remaining.values())


@transaction.atomic
def dispatch_invoice(
    *,
    invoice: Invoice,
    lines: list[DispatchLineInput],
    user: User | None = None,
    dispatch_date: date | None = None,
    notes: str = "",
) -> Dispatch:
    """Dispatch finished goods against an invoice and post FG ISSUE rows.

    Invariants: the invoice is not cancelled; every dispatched line belongs to
    the invoice; the quantity is positive and does not exceed the undispatched,
    uncredited quantity; stock is checked by the ledger service under a row
    lock, so dispatch beyond on-hand stock is refused; a fully dispatched
    invoice moves its order to DISPATCHED and is audited.
    """
    invoice = _lock_invoice(invoice)
    if invoice_is_cancelled(invoice):
        raise DomainError(f"Invoice {invoice.number} is cancelled by a credit note.")
    if not lines:
        raise InvalidMovement("A dispatch needs at least one line.")

    invoice_lines = {line.pk: line for line in invoice.lines.select_related("item").order_by("pk")}
    remaining = invoice_remaining_qty(invoice)

    normalized: dict[int, Decimal] = {}
    for row in lines:
        line = invoice_lines.get(row.invoice_line_id)
        if line is None:
            raise DomainError(
                f"Invoice line {row.invoice_line_id} does not belong to this invoice."
            )
        if row.invoice_line_id in normalized:
            raise InvalidMovement("An invoice line can only be dispatched once per dispatch.")
        qty = q3(_as_decimal(row.qty, "qty"))
        if qty <= 0:
            raise DomainError("A dispatch quantity must be greater than zero.")
        if qty > remaining[row.invoice_line_id]:
            raise DomainError(
                f"Cannot dispatch {qty} of {line.description}: only "
                f"{remaining[row.invoice_line_id]} remains on invoice {invoice.number}."
            )
        normalized[row.invoice_line_id] = qty

    dispatch = Dispatch.objects.create(
        invoice=invoice,
        dispatch_date=dispatch_date or kolkata_today(),
        notes=notes.strip(),
        created_by=user,
    )
    DispatchLine.objects.bulk_create(
        [
            DispatchLine(dispatch=dispatch, invoice_line_id=line_id, qty=qty)
            for line_id, qty in normalized.items()
        ]
    )

    post_movements(
        movements=[
            Movement(item_id=invoice_lines[line_id].item_id, qty=q3(-qty))
            for line_id, qty in normalized.items()
        ],
        movement_type=MovementType.ISSUE,
        source_type=SourceType.DISPATCH,
        source_id=dispatch.pk,
        user=user,
    )

    log_audit(
        user,
        "Dispatch",
        dispatch.pk,
        "create",
        {},
        {
            "invoice": invoice.number,
            "dispatch_date": dispatch.dispatch_date,
            "lines": [
                {
                    "item": invoice_lines[line_id].description,
                    "qty": qty,
                }
                for line_id, qty in normalized.items()
            ],
        },
    )

    if _invoice_fully_dispatched(invoice):
        order = _lock_order(invoice.order)
        if order.state == OrderState.INVOICED:
            before = _order_snapshot(order)
            order.state = OrderState.DISPATCHED
            order.save(update_fields=["state", "updated_at"])
            log_audit(user, "Order", order.pk, "dispatch", before, _order_snapshot(order))

    return dispatch


# ---------------------------------------------------------------------------
# Credit notes
# ---------------------------------------------------------------------------


@transaction.atomic
def issue_credit_note(
    *,
    invoice: Invoice,
    reason: str,
    lines: list[CreditNoteLineInput],
    restock: bool = False,
    user: User | None = None,
    note_date: date | None = None,
) -> CreditNote:
    """Credit part or all of an invoice, optionally returning goods to stock.

    Invariants: a reason is mandatory; each credited quantity is positive and
    no more than the invoice line's uncredited quantity; tax mirrors the
    invoice's place of supply; the CN number comes from its own per-FY series;
    restocking posts a finished-goods RECEIPT sourced to this credit note at
    the current weighted-average cost.
    """
    invoice = _lock_invoice(invoice)
    cleaned_reason = reason.strip()
    if not cleaned_reason:
        raise InvalidMovement("A credit note requires a reason.")
    if not lines:
        raise InvalidMovement("A credit note needs at least one line.")

    invoice_lines = {line.pk: line for line in invoice.lines.select_related("item").order_by("pk")}
    already_credited = credited_qty_by_line(invoice)

    normalized: dict[int, Decimal] = {}
    tax_inputs: list[TaxLineInput] = []
    for row in lines:
        line = invoice_lines.get(row.invoice_line_id)
        if line is None:
            raise DomainError(
                f"Invoice line {row.invoice_line_id} does not belong to this invoice."
            )
        if row.invoice_line_id in normalized:
            raise InvalidMovement("An invoice line can only be credited once per credit note.")
        qty = q3(_as_decimal(row.qty, "qty"))
        if qty <= 0:
            raise DomainError("A credited quantity must be greater than zero.")
        remaining = line.qty - already_credited.get(line.pk, Decimal("0.000"))
        if qty > remaining:
            raise DomainError(
                f"Cannot credit {qty} of {line.description}: only {remaining} remains."
            )
        normalized[line.pk] = qty
        tax_inputs.append(
            TaxLineInput(
                key=line.pk,
                qty=qty,
                unit_price=line.unit_price,
                gst_rate=line.gst_rate,
            )
        )

    summary = compute_tax(tax_inputs, interstate=invoice.is_interstate)
    business_date = note_date or kolkata_today()
    credit_note = CreditNote.objects.create(
        number=allocate_document_number(DocumentType.CREDIT_NOTE, business_date),
        invoice=invoice,
        reason=cleaned_reason,
        restock=restock,
        taxable_total=summary.taxable_total,
        cgst_total=summary.cgst_total,
        sgst_total=summary.sgst_total,
        igst_total=summary.igst_total,
        round_off=summary.round_off,
        total=summary.total,
        created_by=user,
    )

    taxed_by_key = {line.key: line for line in summary.lines}
    CreditNoteLine.objects.bulk_create(
        [
            CreditNoteLine(
                credit_note=credit_note,
                invoice_line_id=line_id,
                qty=qty,
                taxable_value=taxed_by_key[line_id].taxable_value,
                cgst=taxed_by_key[line_id].cgst,
                sgst=taxed_by_key[line_id].sgst,
                igst=taxed_by_key[line_id].igst,
                line_total=taxed_by_key[line_id].line_total,
            )
            for line_id, qty in normalized.items()
        ]
    )

    if restock:
        movements: list[Movement] = []
        for line_id, qty in normalized.items():
            line = invoice_lines[line_id]
            balance = StockBalance.objects.filter(item_id=line.item_id).first()
            if balance is not None and balance.qty > 0:
                unit_cost = q4(balance.value / balance.qty)
            else:
                unit_cost = Decimal("0")
            movements.append(Movement(item_id=line.item_id, qty=qty, unit_cost=unit_cost))
        post_movements(
            movements=movements,
            movement_type=MovementType.RECEIPT,
            source_type=SourceType.CREDIT_NOTE,
            source_id=credit_note.pk,
            user=user,
        )

    log_audit(
        user,
        "CreditNote",
        credit_note.pk,
        "create",
        {},
        {
            "invoice": invoice.number,
            "reason": cleaned_reason,
            "restock": restock,
            "total": credit_note.total,
            "lines": [
                {"item": invoice_lines[line_id].description, "qty": qty}
                for line_id, qty in normalized.items()
            ],
        },
    )
    return credit_note
