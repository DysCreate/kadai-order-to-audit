"""Inventory services – the only code allowed to write the stock ledger.

Invariants protected:
- Every movement is append-only and traceable (source_type + source_id).
- Balance rows are locked in ascending item-id order before any movement, so
  two concurrent issues of the last stock cannot both succeed.
- ``stock_balance`` is updated in the same transaction as the ledger insert and
  always equals SUM(stock_ledger).
- Moving weighted average: issuing all remaining quantity leaves value zero.
- Negative stock is rejected by the service and again by the database CHECK.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.db.models import QuerySet, Sum
from django.utils import timezone

from apps.accounts.models import User
from apps.masters.models import Item, Supplier
from core.errors import DomainError, InsufficientStock, InvalidMovement, OpeningBalanceExists
from core.money import q2, q4
from core.quantity import q3

from .models import (
    MovementType,
    Purchase,
    PurchaseLine,
    SourceType,
    StockAdjustment,
    StockBalance,
    StockLedger,
)
from .valuation import MovingWeightedAverage

VALUATION = MovingWeightedAverage()

_INCOMING_TYPES = frozenset({MovementType.OPENING, MovementType.RECEIPT})


@dataclass(frozen=True)
class Movement:
    """One requested stock movement, before valuation and persistence.

    ``unit_cost`` values a receipt at a rate. ``value`` states the exact total
    to add or remove, and is used by reversal paths (for example returning a
    production run's issues at the value they were taken at).
    """

    item_id: int
    qty: Decimal
    unit_cost: Decimal | None = None
    value: Decimal | None = None


@dataclass(frozen=True)
class PurchaseLineInput:
    """One item received on a purchase, before the purchase is posted."""

    item_id: int
    qty: Decimal
    unit_cost: Decimal


@dataclass(frozen=True)
class StockSummaryRow:
    """Current balance for one item, with its weighted-average rate."""

    item: Item
    qty: Decimal
    value: Decimal

    @property
    def avg_rate(self) -> Decimal:
        if self.qty == 0:
            return Decimal("0.0000")
        return q4(self.value / self.qty)


@dataclass(frozen=True)
class ReconciliationIssue:
    """A balance that disagrees with the ledger, or a ledger without balance."""

    item_id: int
    balance_qty: Decimal
    ledger_qty: Decimal
    balance_value: Decimal
    ledger_value: Decimal


def _as_decimal(value: Decimal | str | int, field: str) -> Decimal:
    if isinstance(value, float):
        raise InvalidMovement(f"{field} must be Decimal, str or int, never float.")
    try:
        return Decimal(value)
    except (InvalidOperation, TypeError) as exc:
        raise InvalidMovement(f"{field} is not a valid decimal: {value!r}.") from exc


def _validate_items(item_ids: list[int]) -> None:
    found = set(Item.objects.filter(pk__in=item_ids).values_list("pk", flat=True))
    missing = [item_id for item_id in item_ids if item_id not in found]
    if missing:
        raise DomainError(f"Unknown item id(s): {missing}.")


def _lock_balances(item_ids: list[int]) -> dict[int, StockBalance]:
    """Lock (or create) balance rows in ascending item-id order.

    Creating a row inside a savepoint keeps the outer transaction usable if a
    concurrent transaction wins the race on the unique item key.
    """
    balances: dict[int, StockBalance] = {}
    locked = (
        StockBalance.objects.select_for_update().filter(item_id__in=item_ids).order_by("item_id")
    )
    for balance in locked:
        balances[balance.item_id] = balance

    for item_id in item_ids:
        if item_id in balances:
            continue
        try:
            with transaction.atomic():
                balances[item_id] = StockBalance.objects.create(item_id=item_id)
        except IntegrityError:
            balances[item_id] = StockBalance.objects.select_for_update().get(item_id=item_id)
    return balances


@transaction.atomic
def post_movements(
    *,
    movements: list[Movement],
    movement_type: str,
    source_type: str,
    source_id: int,
    user: User | None = None,
    batch_id: str | None = None,
) -> list[StockLedger]:
    """Post one or more stock movements atomically and return the ledger rows.

    Invariants: sign matches the movement type, opening rows cite an opening
    source, receipts carry a unit cost (or use the current average when the
    balance is positive), issues are valued by the moving-average strategy,
    and all balance rows are locked in ascending item-id order.
    """
    if not movements:
        raise InvalidMovement("At least one movement is required.")
    if movement_type not in MovementType.values:
        raise InvalidMovement(f"Invalid movement type {movement_type!r}.")
    if source_type not in SourceType.values:
        raise InvalidMovement(f"Invalid source type {source_type!r}.")
    if source_id is None or source_id <= 0:
        raise InvalidMovement("Every ledger row needs a positive source document id.")
    if movement_type == MovementType.OPENING and source_type != SourceType.OPENING:
        raise InvalidMovement("Opening movements must cite the opening source.")

    normalized: list[Movement] = []
    for movement in movements:
        qty = q3(_as_decimal(movement.qty, "qty"))
        if qty == 0:
            raise InvalidMovement("A stock movement quantity cannot be zero.")

        unit_cost: Decimal | None = None
        if movement.unit_cost is not None:
            unit_cost = _as_decimal(movement.unit_cost, "unit_cost")
            if unit_cost < 0:
                raise InvalidMovement("A unit cost cannot be negative.")

        explicit_value: Decimal | None = None
        if movement.value is not None:
            explicit_value = _as_decimal(movement.value, "value")
            if explicit_value <= 0:
                raise InvalidMovement("An explicit movement value must be positive.")
            if unit_cost is not None:
                raise InvalidMovement("Supply either a unit cost or an exact value, not both.")

        if movement_type in _INCOMING_TYPES and qty < 0:
            raise InvalidMovement(f"{movement_type} movements must increase stock.")
        if (
            movement_type in (MovementType.ISSUE, MovementType.ADJUSTMENT)
            and qty < 0
            and unit_cost is not None
        ):
            raise InvalidMovement("Issue value is derived, not supplied.")
        if movement_type == MovementType.ISSUE and qty > 0:
            raise InvalidMovement("ISSUE movements must decrease stock.")
        if explicit_value is not None and movement_type not in _INCOMING_TYPES:
            raise InvalidMovement("Only incoming movements may state an exact value.")
        if movement_type in _INCOMING_TYPES and unit_cost is None and explicit_value is None:
            raise InvalidMovement(f"{movement_type} movements require a unit cost.")

        normalized.append(
            Movement(
                item_id=movement.item_id,
                qty=qty,
                unit_cost=unit_cost,
                value=explicit_value,
            )
        )

    item_ids = sorted({movement.item_id for movement in normalized})
    _validate_items(item_ids)
    balances = _lock_balances(item_ids)

    grouped: dict[int, list[Movement]] = {item_id: [] for item_id in item_ids}
    for movement in normalized:
        grouped[movement.item_id].append(movement)

    entries: list[StockLedger] = []
    for item_id in item_ids:
        balance = balances[item_id]
        for movement in grouped[item_id]:
            qty = movement.qty
            if qty > 0:
                if movement.value is not None:
                    # Reversal path: the exact value is known, so derive the
                    # unit value instead of recomputing it from a rate.
                    value = q2(movement.value)
                    unit_cost = q4(value / qty)
                elif movement.unit_cost is not None:
                    unit_cost = q4(movement.unit_cost)
                elif balance.qty > 0:
                    unit_cost = balance.value / balance.qty
                else:
                    raise InvalidMovement(
                        "A unit cost is required to increase an empty stock balance."
                    )
                if movement.value is None:
                    value = VALUATION.receipt_value(qty, unit_cost)
            else:
                issue_qty = -qty
                value = -VALUATION.issue_value(issue_qty, balance.qty, balance.value)
                unit_cost = q4(abs(value) / issue_qty)

            new_qty = q3(balance.qty + qty)
            new_value = q2(balance.value + value)
            if new_qty == 0:
                # Remainder rule: no value may survive a zero balance.
                value = q2(-balance.value)
                new_value = Decimal("0.00")

            entry = StockLedger.objects.create(
                item_id=item_id,
                batch_id=batch_id,
                movement_type=movement_type,
                qty=qty,
                value=value,
                unit_value=unit_cost,
                source_type=source_type,
                source_id=source_id,
                created_by=user,
            )
            entries.append(entry)

            balance.qty = new_qty
            balance.value = new_value
            balance.save(update_fields=["qty", "value", "updated_at"])

    return entries


@transaction.atomic
def post_movement(
    *,
    item_id: int,
    qty: Decimal | str | int,
    movement_type: str,
    source_type: str,
    source_id: int,
    unit_cost: Decimal | str | int | None = None,
    value: Decimal | str | int | None = None,
    user: User | None = None,
    batch_id: str | None = None,
) -> StockLedger:
    """Post a single stock movement; see ``post_movements`` for invariants."""
    entries = post_movements(
        movements=[
            Movement(
                item_id=item_id,
                qty=_as_decimal(qty, "qty"),
                unit_cost=None if unit_cost is None else _as_decimal(unit_cost, "unit_cost"),
                value=None if value is None else _as_decimal(value, "value"),
            )
        ],
        movement_type=movement_type,
        source_type=source_type,
        source_id=source_id,
        user=user,
        batch_id=batch_id,
    )
    return entries[0]


@transaction.atomic
def post_value_adjustment(
    *,
    item_id: int,
    value: Decimal | str | int,
    source_type: str,
    source_id: int,
    user: User | None = None,
) -> StockLedger:
    """Add value to an existing stock balance without changing its quantity.

    Used by costing to absorb overheads into finished goods after the run's
    material receipt. Invariants: the amount is a positive Decimal, the item
    already holds stock (a value-only row must never create a zero-quantity
    balance with value), the balance row is locked, and the append-only ledger
    row and balance update commit together.
    """
    amount = q2(_as_decimal(value, "value"))
    if amount <= 0:
        raise InvalidMovement("A value-only adjustment must be greater than zero.")
    if source_type not in SourceType.values:
        raise InvalidMovement(f"Invalid source type {source_type!r}.")
    if source_id is None or source_id <= 0:
        raise InvalidMovement("Every ledger row needs a positive source document id.")

    _validate_items([item_id])
    balance = _lock_balances([item_id])[item_id]
    if balance.qty <= 0:
        raise InsufficientStock(
            "Cannot add overhead value to an item with no stock; "
            "the finished-goods balance is already zero."
        )

    entry = StockLedger.objects.create(
        item_id=item_id,
        movement_type=MovementType.ADJUSTMENT,
        qty=Decimal("0.000"),
        value=amount,
        unit_value=Decimal("0.0000"),
        source_type=source_type,
        source_id=source_id,
        created_by=user,
    )
    balance.value = q2(balance.value + amount)
    balance.save(update_fields=["value", "updated_at"])
    return entry


@transaction.atomic
def post_opening_balance(
    *,
    item_id: int,
    qty: Decimal | str | int,
    unit_cost: Decimal | str | int,
    user: User | None = None,
) -> StockLedger:
    """Post an opening balance as an OPENING ledger row.

    Invariants: the quantity is positive, the cost is non-negative, and an item
    that already has any ledger history cannot receive a second opening row.
    The source id is the item id, because the item itself is the opening source.
    """
    quantity = q3(_as_decimal(qty, "qty"))
    if quantity <= 0:
        raise InvalidMovement("An opening balance must be greater than zero.")

    _validate_items([item_id])
    balance = _lock_balances([item_id])[item_id]
    if balance.qty != 0 or StockLedger.objects.filter(item_id=item_id).exists():
        raise OpeningBalanceExists(
            f"Item {item_id} already has stock history; use an adjustment instead."
        )

    return post_movement(
        item_id=item_id,
        qty=quantity,
        movement_type=MovementType.OPENING,
        source_type=SourceType.OPENING,
        source_id=item_id,
        unit_cost=unit_cost,
        user=user,
    )


@transaction.atomic
def adjust_stock(
    *,
    item_id: int,
    qty_delta: Decimal | str | int,
    reason: str,
    user: User | None = None,
    unit_cost: Decimal | str | int | None = None,
) -> StockAdjustment:
    """Create a stock adjustment document and post its ledger movement.

    Invariants: the quantity is non-zero, the reason is mandatory, and an
    increase from an empty balance needs an explicit unit cost.
    """
    quantity = q3(_as_decimal(qty_delta, "qty_delta"))
    if quantity == 0:
        raise InvalidMovement("An adjustment quantity cannot be zero.")
    cleaned_reason = reason.strip()
    if not cleaned_reason:
        raise InvalidMovement("A stock adjustment requires a reason.")
    _validate_items([item_id])

    adjustment = StockAdjustment.objects.create(
        item_id=item_id,
        qty_delta=quantity,
        reason=cleaned_reason,
        created_by=user,
    )
    post_movement(
        item_id=item_id,
        qty=quantity,
        movement_type=MovementType.ADJUSTMENT,
        source_type=SourceType.ADJUSTMENT,
        source_id=adjustment.pk,
        unit_cost=unit_cost,
        user=user,
    )
    return adjustment


@transaction.atomic
def create_purchase(
    *,
    supplier: Supplier,
    lines: list[PurchaseLineInput],
    user: User | None = None,
    reference: str = "",
    purchase_date: date | None = None,
    notes: str = "",
) -> Purchase:
    """Record a purchase and post one RECEIPT ledger row per line.

    Invariants: every line has a positive quantity, a non-negative rate and an
    existing item; the purchase total is the sum of ``q2(qty * rate)``; all
    receipts post in one transaction, so a bad line posts nothing and the
    weighted average is updated exactly once per receipt.
    """
    if not lines:
        raise InvalidMovement("A purchase needs at least one line.")

    purchase = Purchase.objects.create(
        supplier=supplier,
        reference=reference.strip(),
        purchase_date=purchase_date or timezone.localdate(),
        notes=notes.strip(),
        created_by=user,
    )

    movements: list[Movement] = []
    total = Decimal("0.00")
    for line in lines:
        qty = q3(_as_decimal(line.qty, "qty"))
        if qty <= 0:
            raise InvalidMovement("A purchase quantity must be greater than zero.")
        unit_cost = q4(_as_decimal(line.unit_cost, "unit_cost"))
        if unit_cost < 0:
            raise InvalidMovement("A purchase rate cannot be negative.")

        value = q2(qty * unit_cost)
        PurchaseLine.objects.create(
            purchase=purchase,
            item_id=line.item_id,
            qty=qty,
            unit_cost=unit_cost,
            value=value,
        )
        movements.append(Movement(item_id=line.item_id, qty=qty, unit_cost=unit_cost))
        total += value

    purchase.total_value = q2(total)
    purchase.save(update_fields=["total_value"])

    post_movements(
        movements=movements,
        movement_type=MovementType.RECEIPT,
        source_type=SourceType.PURCHASE,
        source_id=purchase.pk,
        user=user,
    )
    return purchase


def stock_summary() -> list[StockSummaryRow]:
    """Return the current balance for every item, including zero balances."""
    balances = StockBalance.objects.in_bulk(field_name="item_id")
    rows: list[StockSummaryRow] = []
    for item in Item.objects.select_related("uom").order_by("name"):
        balance = balances.get(item.pk)
        rows.append(
            StockSummaryRow(
                item=item,
                qty=balance.qty if balance is not None else Decimal("0.000"),
                value=balance.value if balance is not None else Decimal("0.00"),
            )
        )
    return rows


def ledger_entries(
    *,
    item_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> QuerySet[StockLedger]:
    """Return ledger rows for the given filters, oldest first."""
    queryset = StockLedger.objects.select_related("item", "created_by").order_by("created_at", "id")
    if item_id is not None:
        queryset = queryset.filter(item_id=item_id)
    if date_from is not None:
        queryset = queryset.filter(created_at__date__gte=date_from)
    if date_to is not None:
        queryset = queryset.filter(created_at__date__lte=date_to)
    return queryset


def reconcile_stock() -> list[ReconciliationIssue]:
    """Compare every balance with the ledger sums; return all disagreements."""
    raw_totals = StockLedger.objects.values("item_id").annotate(
        qty_sum=Sum("qty"),
        value_sum=Sum("value"),
    )
    totals: dict[int, tuple[Decimal, Decimal]] = {}
    for row in raw_totals:
        totals[int(row["item_id"])] = (
            row["qty_sum"] or Decimal("0.000"),
            row["value_sum"] or Decimal("0.00"),
        )

    issues: list[ReconciliationIssue] = []
    for balance in StockBalance.objects.order_by("item_id"):
        ledger_qty, ledger_value = totals.pop(balance.item_id, (Decimal("0.000"), Decimal("0.00")))
        if balance.qty != ledger_qty or balance.value != ledger_value:
            issues.append(
                ReconciliationIssue(
                    item_id=balance.item_id,
                    balance_qty=balance.qty,
                    ledger_qty=ledger_qty,
                    balance_value=balance.value,
                    ledger_value=ledger_value,
                )
            )

    for item_id, (ledger_qty, ledger_value) in sorted(totals.items()):
        issues.append(
            ReconciliationIssue(
                item_id=item_id,
                balance_qty=Decimal("0.000"),
                ledger_qty=ledger_qty,
                balance_value=Decimal("0.00"),
                ledger_value=ledger_value,
            )
        )
    return issues
