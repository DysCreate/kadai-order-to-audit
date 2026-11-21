"""Costing services – the only code that writes overhead entries.

Invariants protected:
- A run overhead is accepted only for a COMPLETED run and is assigned fully to
  that run; a monthly pool is split by standard batch-hours across the runs
  completed in that month (Asia/Kolkata).
- Every rupee of overhead reaches finished goods through
  ``inventory.services.post_value_adjustment``: an append-only, value-only
  ledger row (qty 0) under the balance row lock. No costing code writes stock.
- Allocation is idempotent per (overhead entry, run): re-running it returns the
  existing rows and never posts a second value adjustment.
- Cost per packet divides the run's materials plus overheads by good packets
  only (assumption A5); margin uses the default selling price.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import QuerySet, Sum

from apps.accounts.models import User
from apps.inventory.models import SourceType, StockBalance, StockLedger
from apps.inventory.services import post_value_adjustment
from apps.masters.models import Item, ItemType
from apps.masters.services import resolve_price
from apps.production.models import ProductionRun, RunState
from core.audit import log_audit
from core.errors import DomainError, InvalidMovement, InvalidRunState, PriceNotFound
from core.money import q2, q4
from core.quantity import q3

from .allocation import allocate_amount
from .calculations import packet_cost
from .models import (
    OverheadAllocation,
    OverheadCategory,
    OverheadEntry,
    OverheadScope,
)

INDIA = ZoneInfo("Asia/Kolkata")


def _as_decimal(value: Decimal | str | int, field: str) -> Decimal:
    if isinstance(value, float):
        raise InvalidMovement(f"{field} must be Decimal, str or int, never float.")
    try:
        return Decimal(value)
    except (InvalidOperation, TypeError) as exc:
        raise InvalidMovement(f"{field} is not a valid decimal: {value!r}.") from exc


def normalize_period(period: date) -> date:
    """Return the first day of ``period``'s calendar month."""
    if not isinstance(period, date):
        raise DomainError("An overhead period must be a date.")
    return date(period.year, period.month, 1)


def _month_bounds(period: date) -> tuple[datetime, datetime]:
    """Return the UTC half-open bounds of a month in Asia/Kolkata."""
    if period.month == 12:
        next_month = date(period.year + 1, 1, 1)
    else:
        next_month = date(period.year, period.month + 1, 1)
    start_local = datetime.combine(period, time.min, tzinfo=INDIA)
    end_local = datetime.combine(next_month, time.min, tzinfo=INDIA)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def _lock_run(run: ProductionRun) -> ProductionRun:
    return ProductionRun.objects.select_for_update().select_related("product").get(pk=run.pk)


def _validate_category(category: str) -> None:
    if category not in OverheadCategory.values:
        raise DomainError(f"Invalid overhead category {category!r}.")


def _normalize_amount(amount: Decimal | str | int) -> Decimal:
    value = q2(_as_decimal(amount, "amount"))
    if value <= 0:
        raise InvalidMovement("An overhead amount must be greater than zero.")
    return value


def _price_for(product: Item) -> Decimal | None:
    try:
        return resolve_price(item=product)
    except PriceNotFound:
        # A cost sheet is still useful before a price is configured; margin is
        # then explicitly null rather than invented.
        return None


@transaction.atomic
def record_run_overhead(
    *,
    run: ProductionRun,
    category: str,
    amount: Decimal | str | int,
    description: str = "",
    user: User | None = None,
) -> OverheadEntry:
    """Add an overhead to one completed run and absorb it into FG value.

    Invariants: the run is COMPLETED, the category is valid, the amount is a
    positive Decimal, and the finished-goods balance still holds stock (a
    value-only row cannot create value on a zero quantity). The overhead entry,
    the ledger row and the run's ``ledger_entry_ids`` update commit together.
    """
    locked = _lock_run(run)
    if locked.state != RunState.COMPLETED:
        raise InvalidRunState(
            f"Run {locked.pk} is {locked.state}; overheads apply only to a COMPLETED run."
        )
    _validate_category(category)
    value = _normalize_amount(amount)
    cleaned_description = description.strip()
    if len(cleaned_description) > 255:
        raise InvalidMovement("An overhead description is limited to 255 characters.")

    entry = OverheadEntry.objects.create(
        scope=OverheadScope.RUN,
        run=locked,
        category=category,
        amount=value,
        description=cleaned_description,
        created_by=user,
    )
    ledger_entry = post_value_adjustment(
        item_id=locked.product_id,
        value=value,
        source_type=SourceType.PRODUCTION_RUN,
        source_id=locked.pk,
        user=user,
    )
    locked.ledger_entry_ids = [*locked.ledger_entry_ids, ledger_entry.pk]
    locked.save(update_fields=["ledger_entry_ids"])
    log_audit(
        user,
        "ProductionRun",
        locked.pk,
        "overhead",
        {},
        {
            "overhead_entry_id": entry.pk,
            "category": category,
            "amount": value,
            "ledger_entry_id": ledger_entry.pk,
        },
    )
    return entry


@transaction.atomic
def record_monthly_overhead(
    *,
    period: date,
    category: str,
    amount: Decimal | str | int,
    description: str = "",
    user: User | None = None,
) -> OverheadEntry:
    """Record one monthly pool entry; it is allocated by a separate service."""
    month = normalize_period(period)
    _validate_category(category)
    value = _normalize_amount(amount)
    cleaned_description = description.strip()
    if len(cleaned_description) > 255:
        raise InvalidMovement("An overhead description is limited to 255 characters.")

    entry = OverheadEntry.objects.create(
        scope=OverheadScope.MONTH,
        period=month,
        category=category,
        amount=value,
        description=cleaned_description,
        created_by=user,
    )
    log_audit(
        user,
        "OverheadEntry",
        entry.pk,
        "create",
        {},
        {
            "scope": entry.scope,
            "period": month.isoformat(),
            "category": category,
            "amount": value,
        },
    )
    return entry


def monthly_overheads(period: date | None = None) -> QuerySet[OverheadEntry]:
    """Return monthly pool entries, optionally for one month."""
    queryset = OverheadEntry.objects.filter(scope=OverheadScope.MONTH).order_by(
        "period", "created_at", "pk"
    )
    if period is not None:
        queryset = queryset.filter(period=normalize_period(period))
    return queryset


def _runs_for_month(period: date) -> list[ProductionRun]:
    start, end = _month_bounds(period)
    return list(
        ProductionRun.objects.select_for_update()
        .select_related("product")
        .filter(
            state=RunState.COMPLETED,
            completed_at__gte=start,
            completed_at__lt=end,
        )
        .order_by("pk")
    )


@transaction.atomic
def allocate_monthly_overhead(
    *, period: date, user: User | None = None
) -> list[OverheadAllocation]:
    """Allocate unallocated monthly pool entries across that month's runs.

    Invariants: at least one monthly entry and one completed run exist; each
    unallocated entry is split by ``batches * standard_batch_hours`` and its
    shares sum exactly to the entry amount; each share posts one value-only
    ledger row; already-allocated entries are returned untouched, so a retry
    never double-charges.
    """
    month = normalize_period(period)
    entries = list(
        OverheadEntry.objects.select_for_update()
        .filter(scope=OverheadScope.MONTH, period=month)
        .order_by("pk")
    )
    if not entries:
        raise DomainError(f"No monthly overhead entries exist for {month:%Y-%m}.")

    existing = list(
        OverheadAllocation.objects.filter(entry__in=entries)
        .select_related("entry", "run")
        .order_by("entry_id", "run_id")
    )
    allocated_entry_ids = {allocation.entry_id for allocation in existing}
    pending = [entry for entry in entries if entry.pk not in allocated_entry_ids]
    if not pending:
        return existing

    runs = _runs_for_month(month)
    if not runs:
        raise DomainError(f"No completed production runs exist for {month:%Y-%m}.")

    weights = [(run.pk, q3(run.batches * run.product.standard_batch_hours)) for run in runs]
    run_by_id = {run.pk: run for run in runs}
    ledger_ids: dict[int, list[int]] = {run.pk: list(run.ledger_entry_ids) for run in runs}
    created: list[OverheadAllocation] = []

    for entry in pending:
        for share in allocate_amount(entry.amount, weights):
            run = run_by_id[share.key]
            ledger_entry = post_value_adjustment(
                item_id=run.product_id,
                value=share.amount,
                source_type=SourceType.PRODUCTION_RUN,
                source_id=run.pk,
                user=user,
            )
            allocation = OverheadAllocation.objects.create(
                entry=entry,
                run=run,
                amount=share.amount,
                ledger_entry=ledger_entry,
            )
            ledger_ids[run.pk].append(ledger_entry.pk)
            created.append(allocation)
            log_audit(
                user,
                "ProductionRun",
                run.pk,
                "overhead_allocate",
                {},
                {
                    "overhead_entry_id": entry.pk,
                    "amount": share.amount,
                    "ledger_entry_id": ledger_entry.pk,
                },
            )

    for run_id, ids in ledger_ids.items():
        ProductionRun.objects.filter(pk=run_id).update(ledger_entry_ids=ids)

    return [*existing, *created]


def _material_rows(run: ProductionRun) -> list[dict[str, object]]:
    rows = (
        StockLedger.objects.filter(
            source_type=SourceType.PRODUCTION_RUN,
            source_id=run.pk,
        )
        .exclude(item_id=run.product_id)
        .values("item_id", "item__name", "item__uom__symbol")
        .annotate(qty_sum=Sum("qty"), value_sum=Sum("value"))
        .order_by("item_id")
    )
    materials: list[dict[str, object]] = []
    for row in rows:
        qty = q3(-(row["qty_sum"] or Decimal("0.000")))
        value = q2(-(row["value_sum"] or Decimal("0.00")))
        if qty == 0 and value == 0:
            continue
        materials.append(
            {
                "item_id": row["item_id"],
                "item_name": row["item__name"],
                "uom": row["item__uom__symbol"],
                "qty": qty,
                "value": value,
            }
        )
    return materials


def _overhead_rows(run: ProductionRun) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    entries = OverheadEntry.objects.filter(run=run, scope=OverheadScope.RUN).order_by("pk")
    for entry in entries:
        rows.append(
            {
                "entry_id": entry.pk,
                "allocation_id": None,
                "scope": entry.scope,
                "category": entry.category,
                "amount": entry.amount,
                "description": entry.description,
                "period": None,
            }
        )

    allocations = (
        OverheadAllocation.objects.filter(run=run)
        .select_related("entry")
        .order_by("entry__period", "entry_id")
    )
    for allocation in allocations:
        rows.append(
            {
                "entry_id": allocation.entry_id,
                "allocation_id": allocation.pk,
                "scope": allocation.entry.scope,
                "category": allocation.entry.category,
                "amount": allocation.amount,
                "description": allocation.entry.description,
                "period": (
                    allocation.entry.period.isoformat()
                    if allocation.entry.period is not None
                    else None
                ),
            }
        )
    return rows


def run_cost_sheet(run: ProductionRun) -> dict[str, object]:
    """Return the stored-cost view of one completed run.

    Invariants: only a COMPLETED run has a cost sheet; materials are the net
    ledger value of its inputs; overheads are run entries plus monthly
    allocations; cost per packet and margin come from the pure ``packet_cost``
    helper, so the benchmark's 5,855 / 188 = 31.14 is reproduced exactly.
    """
    run = ProductionRun.objects.select_related("product__uom").get(pk=run.pk)
    if run.state != RunState.COMPLETED:
        raise InvalidRunState(
            f"Run {run.pk} is {run.state}; a cost sheet is available only after completion."
        )

    materials = _material_rows(run)
    materials_value = q2(sum((Decimal(str(row["value"])) for row in materials), Decimal("0.00")))
    overheads = _overhead_rows(run)
    overhead_value = q2(sum((Decimal(str(row["amount"])) for row in overheads), Decimal("0.00")))
    good_packets = run.good_packets or Decimal("0.000")
    total_cost = q2(materials_value + overhead_value)
    selling_price = _price_for(run.product)
    cost = packet_cost(
        total_cost=total_cost,
        good_packets=good_packets,
        selling_price=selling_price,
    )

    balance = StockBalance.objects.filter(item_id=run.product_id).first()
    fg_qty = balance.qty if balance is not None else Decimal("0.000")
    fg_value = balance.value if balance is not None else Decimal("0.00")
    fg_avg_cost = q4(fg_value / fg_qty) if fg_qty > 0 else Decimal("0.0000")

    return {
        "run_id": run.pk,
        "product_id": run.product_id,
        "product_name": run.product.name,
        "product_uom": run.product.uom.symbol,
        "state": run.state,
        "batches": run.batches,
        "standard_batch_hours": run.product.standard_batch_hours,
        "batch_hours": q3(run.batches * run.product.standard_batch_hours),
        "good_packets": good_packets,
        "materials": materials,
        "materials_value": materials_value,
        "overheads": overheads,
        "overhead_value": overhead_value,
        "total_cost": total_cost,
        "cost_per_packet": cost.cost_per_packet,
        "selling_price": cost.selling_price,
        "margin_per_packet": cost.margin_per_packet,
        "margin_pct": cost.margin_pct,
        "fg_stock_qty": fg_qty,
        "fg_stock_value": fg_value,
        "fg_avg_cost": fg_avg_cost,
    }


def product_cost_summary(product: Item) -> dict[str, object]:
    """Return current FG weighted-average cost and margin for one product."""
    if product.item_type != ItemType.FG:
        raise DomainError("A product cost summary is available only for finished goods.")

    balance = StockBalance.objects.filter(item_id=product.pk).first()
    qty = balance.qty if balance is not None else Decimal("0.000")
    value = balance.value if balance is not None else Decimal("0.00")
    avg_cost = q4(value / qty) if qty > 0 else Decimal("0.0000")
    price = _price_for(product)
    margin = q2(price - avg_cost) if price is not None else None
    margin_pct = None
    if price is not None and price != 0 and margin is not None:
        margin_pct = q2(margin / price * 100)
    return {
        "product_id": product.pk,
        "product_name": product.name,
        "stock_qty": qty,
        "stock_value": value,
        "avg_cost": avg_cost,
        "selling_price": price,
        "margin_per_packet": margin,
        "margin_pct": margin_pct,
    }
