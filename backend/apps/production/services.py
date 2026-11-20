"""Production services – the only code that writes BOMs, runs and variance.

Invariants protected:
- A BOM is versioned per product: a new version is a new row, old versions are
  never edited, and a run copies its planned quantities at creation so later
  BOM edits cannot rewrite an existing plan (AGENTS.md 4.7).
- A run moves DRAFT -> ISSUED -> COMPLETED only; every transition is audited
  in the same transaction (AGENTS.md 4.10).
- Stock only ever changes through ``inventory.services``: issues at ISSUED,
  the derived pouch/carton issues at completion, the finished-goods RECEIPT at
  completion, and exact reversals when an issued run is amended.
- The finished-goods receipt is valued at the material cost of that run, so
  scrap is absorbed by good output (assumption A5) and no value drifts.
- Variance is computed once from stored quantities, with the tolerance read
  from settings, and stored as a snapshot per line plus one yield row.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Max, QuerySet, Sum
from django.utils import timezone

from apps.accounts.models import User
from apps.inventory.models import MovementType, SourceType, StockLedger
from apps.inventory.services import Movement, post_movement, post_movements
from apps.masters.models import Item, ItemType
from apps.masters.services import get_decimal_setting
from core.audit import log_audit
from core.errors import (
    BOMVersionMismatch,
    DomainError,
    InvalidMovement,
    InvalidRunState,
)
from core.money import q2
from core.quantity import q3

from .models import (
    BOM,
    BOMLine,
    BOMLineRole,
    ProductionRun,
    ProductionRunLine,
    RunState,
    RunVarianceSnapshot,
    VarianceKind,
)
from .variance import compute_variance

DEFAULT_TOLERANCE = Decimal("0.03")


@dataclass(frozen=True)
class BOMLineInput:
    """One input of a new BOM version."""

    item_id: int
    qty_per_batch: Decimal
    role: str = BOMLineRole.MATERIAL


def _as_decimal(value: Decimal | str | int, field: str) -> Decimal:
    if isinstance(value, float):
        raise InvalidMovement(f"{field} must be Decimal, str or int, never float.")
    try:
        return Decimal(value)
    except (InvalidOperation, TypeError) as exc:
        raise InvalidMovement(f"{field} is not a valid decimal: {value!r}.") from exc


def variance_tolerance() -> Decimal:
    """Return the variance tolerance from settings (0.03 when unset)."""
    return get_decimal_setting("variance_tolerance", DEFAULT_TOLERANCE)


def _lock_run(run: ProductionRun) -> ProductionRun:
    return ProductionRun.objects.select_for_update().get(pk=run.pk)


def _run_snapshot(run: ProductionRun) -> dict[str, object]:
    """Return the auditable state of a run, for the audit log."""
    lines = run.lines.select_related("item").order_by("pk")
    return {
        "state": run.state,
        "product_id": run.product_id,
        "bom_version": run.bom_version,
        "batches": run.batches,
        "planned_output_qty": run.planned_output_qty,
        "good_packets": run.good_packets,
        "damaged_pouches": run.damaged_pouches,
        "cartons_used": run.cartons_used,
        "revision": run.revision,
        "lines": [
            {
                "item": line.item.name,
                "planned_qty": line.planned_qty,
                "issued_qty": line.issued_qty,
                "actual_qty": line.actual_qty,
            }
            for line in lines
        ],
    }


# ---------------------------------------------------------------------------
# Bill of materials (versioned)
# ---------------------------------------------------------------------------


@transaction.atomic
def create_bom_version(
    *,
    product: Item,
    batch_output_qty: Decimal | str | int,
    lines: list[BOMLineInput],
    user: User | None = None,
) -> BOM:
    """Create the next BOM version for ``product``.

    Invariants: the product is finished goods, the batch output and every line
    quantity are positive, an item appears at most once, and there is at most
    one pouch line and one carton line. Existing versions are untouched.
    """
    if product.item_type != ItemType.FG:
        raise DomainError("A BOM belongs to a finished-goods item.")

    output = q3(_as_decimal(batch_output_qty, "batch_output_qty"))
    if output <= 0:
        raise DomainError("A batch must produce more than zero.")

    if not lines:
        raise DomainError("A BOM needs at least one line.")

    seen_items: set[int] = set()
    seen_roles: dict[str, int] = {}
    normalized: list[BOMLineInput] = []
    for line in lines:
        if line.item_id in seen_items:
            raise DomainError(f"Item {line.item_id} appears twice in the BOM.")
        seen_items.add(line.item_id)

        role = line.role
        if role not in BOMLineRole.values:
            raise DomainError(f"Invalid BOM line role {role!r}.")
        if role != BOMLineRole.MATERIAL:
            seen_roles[role] = seen_roles.get(role, 0) + 1
            if seen_roles[role] > 1:
                raise DomainError(f"A BOM can carry only one {role} line.")

        qty = q3(_as_decimal(line.qty_per_batch, "qty_per_batch"))
        if qty <= 0:
            raise DomainError("A BOM line quantity must be greater than zero.")
        normalized.append(BOMLineInput(item_id=line.item_id, qty_per_batch=qty, role=role))

    known = set(Item.objects.filter(pk__in=seen_items).values_list("pk", flat=True))
    missing = sorted(seen_items - known)
    if missing:
        raise DomainError(f"Unknown item id(s): {missing}.")

    # Serialise version allocation per product; the unique constraint is the
    # final guard against a duplicate version number.
    list(BOM.objects.select_for_update().filter(product=product))
    latest = BOM.objects.filter(product=product).aggregate(version__max=Max("version"))
    version = int(latest["version__max"] or 0) + 1

    bom = BOM.objects.create(
        product=product,
        version=version,
        batch_output_qty=output,
        created_by=user,
    )
    BOMLine.objects.bulk_create(
        [
            BOMLine(
                bom=bom,
                item_id=line.item_id,
                role=line.role,
                qty_per_batch=line.qty_per_batch,
            )
            for line in normalized
        ]
    )
    return bom


def get_active_bom(product: Item) -> BOM:
    """Return the latest version of a product's BOM, or raise."""
    bom = BOM.objects.filter(product=product).order_by("-version").first()
    if bom is None:
        raise DomainError(f"Product {product.name!r} has no BOM yet.")
    return bom


def list_boms(product: Item | None = None) -> QuerySet[BOM]:
    """Return BOM versions, newest first, optionally for one product."""
    queryset = BOM.objects.select_related("product").prefetch_related("lines__item")
    if product is not None:
        queryset = queryset.filter(product=product)
    return queryset.order_by("product__name", "-version")


# ---------------------------------------------------------------------------
# Production runs
# ---------------------------------------------------------------------------


def production_runs(*, product: Item | None = None) -> QuerySet[ProductionRun]:
    """Return runs newest first, optionally filtered by product."""
    queryset = ProductionRun.objects.select_related("product", "bom").prefetch_related(
        "lines__item"
    )
    if product is not None:
        queryset = queryset.filter(product=product)
    return queryset.order_by("-created_at", "-pk")


@transaction.atomic
def create_run(
    *,
    product: Item,
    batches: Decimal | str | int,
    user: User | None = None,
    bom: BOM | None = None,
) -> ProductionRun:
    """Create a DRAFT run with planned lines copied from a BOM version.

    Invariants: the product is finished goods, the batch count is positive, the
    BOM belongs to the product and is its current version, and every planned
    quantity is a snapshot (later BOM edits never reach this run).
    """
    if product.item_type != ItemType.FG:
        raise DomainError("Only finished goods can be produced.")

    batch_count = q3(_as_decimal(batches, "batches"))
    if batch_count <= 0:
        raise DomainError("A run needs at least one batch.")

    active = get_active_bom(product)
    selected = bom or active
    if selected.product_id != product.pk:
        raise BOMVersionMismatch("The BOM does not belong to this product.")
    if selected.version != active.version:
        raise BOMVersionMismatch(
            f"BOM version {selected.version} is superseded by version {active.version}; "
            "create the run against the current version."
        )

    planned_output = q3(selected.batch_output_qty * batch_count)
    run = ProductionRun.objects.create(
        product=product,
        bom=selected,
        bom_version=selected.version,
        batches=batch_count,
        planned_output_qty=planned_output,
        created_by=user,
    )
    ProductionRunLine.objects.bulk_create(
        [
            ProductionRunLine(
                run=run,
                item_id=line.item_id,
                role=line.role,
                planned_qty=q3(line.qty_per_batch * batch_count),
            )
            for line in selected.lines.all()
        ]
    )
    log_audit(user, "ProductionRun", run.pk, "create", {}, _run_snapshot(run))
    return run


def _default_issue_qty(line: ProductionRunLine) -> Decimal:
    """Default quantity to issue: the plan for materials, nothing for packaging.

    Packaging is consumed at packing, where the completion record derives the
    pouch and carton quantities from good packets, damaged pouches and cartons
    used, so it is not pre-issued with the raw materials (Appendix A step 2).
    """
    if line.role == BOMLineRole.MATERIAL:
        return line.planned_qty
    return Decimal("0.000")


@transaction.atomic
def issue_run(
    *,
    run: ProductionRun,
    issued: dict[int, Decimal | str | int] | None = None,
    user: User | None = None,
) -> ProductionRun:
    """Move a DRAFT run to ISSUED and post one ISSUE per issued input.

    Invariants: only a DRAFT run can be issued; issued quantities are
    non-negative Decimals; anything not named defaults to the plan for raw
    materials and zero for packaging; all issues post atomically, so a shortage
    on any line leaves the run in DRAFT with no ledger rows.
    """
    run = _lock_run(run)
    if run.state != RunState.DRAFT:
        raise InvalidRunState(f"Run {run.pk} is {run.state}; only a DRAFT run can be issued.")

    lines = list(run.lines.select_related("item").order_by("pk"))
    requested = issued or {}
    unknown = set(requested) - {line.pk for line in lines}
    if unknown:
        raise InvalidMovement(f"Unknown run line(s): {sorted(unknown)}.")

    quantities: dict[int, Decimal] = {}
    for line in lines:
        raw = requested[line.pk] if line.pk in requested else _default_issue_qty(line)
        qty = q3(_as_decimal(raw, "issued_qty"))
        if qty < 0:
            raise InvalidMovement("An issued quantity cannot be negative.")
        quantities[line.pk] = qty

    movements = [
        Movement(item_id=line.item_id, qty=q3(-quantities[line.pk]))
        for line in lines
        if quantities[line.pk] > 0
    ]
    if not movements:
        raise InvalidMovement("An issued run must issue at least one input.")

    entries = post_movements(
        movements=movements,
        movement_type=MovementType.ISSUE,
        source_type=SourceType.PRODUCTION_RUN,
        source_id=run.pk,
        user=user,
    )
    by_item = {entry.item_id: entry for entry in entries}

    for line in lines:
        entry = by_item.get(line.item_id)
        line.issued_qty = quantities[line.pk]
        line.issued_unit_value = entry.unit_value if entry is not None else None
        line.save(update_fields=["issued_qty", "issued_unit_value"])

    run.state = RunState.ISSUED
    run.issued_at = timezone.now()
    run.ledger_entry_ids = [entry.pk for entry in entries]
    run.save(update_fields=["state", "issued_at", "ledger_entry_ids"])
    log_audit(user, "ProductionRun", run.pk, "issue", {}, _run_snapshot(run))
    return run


@transaction.atomic
def complete_run(
    *,
    run: ProductionRun,
    good_packets: Decimal | str | int,
    damaged_pouches: Decimal | str | int = Decimal("0"),
    cartons_used: Decimal | str | int = Decimal("0"),
    user: User | None = None,
) -> ProductionRun:
    """Complete an ISSUED run: packing record, FG receipt and variance snapshot.

    Invariants: only an ISSUED run can complete; good packets are positive;
    pouch consumption is ``good + damaged`` and carton consumption is the
    recorded count, so the packing record drives the packaging ledger; the
    finished-goods receipt is valued at this run's net material cost; the
    variance snapshot is written once and later BOM edits cannot change it.
    """
    run = _lock_run(run)
    if run.state != RunState.ISSUED:
        raise InvalidRunState(f"Run {run.pk} is {run.state}; only an ISSUED run can be completed.")

    good = q3(_as_decimal(good_packets, "good_packets"))
    damaged = q3(_as_decimal(damaged_pouches, "damaged_pouches"))
    cartons = q3(_as_decimal(cartons_used, "cartons_used"))
    if good <= 0:
        raise InvalidMovement("A completed run must record at least one good packet.")
    if damaged < 0 or cartons < 0:
        raise InvalidMovement("Damaged pouches and cartons used cannot be negative.")

    lines = list(run.lines.select_related("item").order_by("pk"))
    pouch_line = next((line for line in lines if line.role == BOMLineRole.POUCH), None)
    carton_line = next((line for line in lines if line.role == BOMLineRole.CARTON), None)
    if damaged > 0 and pouch_line is None:
        raise InvalidMovement("This BOM has no pouch line, so damaged pouches must be zero.")
    if cartons > 0 and carton_line is None:
        raise InvalidMovement("This BOM has no carton line, so cartons used must be zero.")

    actuals: dict[int, Decimal] = {}
    shortages: list[Movement] = []
    returns: list[Movement] = []
    for line in lines:
        if line.role == BOMLineRole.POUCH:
            actual = q3(good + damaged)
        elif line.role == BOMLineRole.CARTON:
            actual = cartons
        else:
            actual = line.issued_qty
        actuals[line.pk] = actual

        delta = q3(actual - line.issued_qty)
        if delta > 0:
            shortages.append(Movement(item_id=line.item_id, qty=q3(-delta)))
        elif delta < 0:
            if line.issued_unit_value is None:
                raise InvalidMovement(
                    f"Cannot return unused {line.item.name}: it was never issued."
                )
            return_qty = q3(-delta)
            returns.append(
                Movement(
                    item_id=line.item_id,
                    qty=return_qty,
                    value=q2(return_qty * line.issued_unit_value),
                )
            )

    new_entries: list[StockLedger] = []
    if shortages:
        new_entries.extend(
            post_movements(
                movements=shortages,
                movement_type=MovementType.ISSUE,
                source_type=SourceType.PRODUCTION_RUN,
                source_id=run.pk,
                user=user,
            )
        )
    if returns:
        new_entries.extend(
            post_movements(
                movements=returns,
                movement_type=MovementType.RECEIPT,
                source_type=SourceType.PRODUCTION_RUN,
                source_id=run.pk,
                user=user,
            )
        )

    for line in lines:
        line.actual_qty = actuals[line.pk]
        line.save(update_fields=["actual_qty"])

    entry_ids = [*run.ledger_entry_ids, *[entry.pk for entry in new_entries]]
    ledger_total = StockLedger.objects.filter(pk__in=entry_ids).aggregate(total=Sum("value"))[
        "total"
    ]
    materials_value = q2(-(ledger_total or Decimal("0.00")))

    if materials_value > 0:
        fg_entry = post_movement(
            item_id=run.product_id,
            qty=good,
            movement_type=MovementType.RECEIPT,
            source_type=SourceType.PRODUCTION_RUN,
            source_id=run.pk,
            value=materials_value,
            user=user,
        )
    else:
        fg_entry = post_movement(
            item_id=run.product_id,
            qty=good,
            movement_type=MovementType.RECEIPT,
            source_type=SourceType.PRODUCTION_RUN,
            source_id=run.pk,
            unit_cost=Decimal("0"),
            user=user,
        )

    tolerance = variance_tolerance()
    snapshots: list[RunVarianceSnapshot] = []
    for line in lines:
        result = compute_variance(line.planned_qty, actuals[line.pk], tolerance)
        snapshots.append(
            RunVarianceSnapshot(
                run=run,
                line=line,
                kind=VarianceKind.USAGE,
                item_name=line.item.name,
                planned_qty=result.planned,
                actual_qty=result.actual,
                variance_pct=result.variance_pct,
                flagged=result.flagged,
                direction=result.direction,
                tolerance=tolerance,
                revision=run.revision,
            )
        )

    yield_result = compute_variance(
        run.planned_output_qty,
        good,
        tolerance,
        higher_is_better=True,
    )
    snapshots.append(
        RunVarianceSnapshot(
            run=run,
            line=None,
            kind=VarianceKind.YIELD,
            item_name=f"{run.product.name} (yield)",
            planned_qty=yield_result.planned,
            actual_qty=yield_result.actual,
            variance_pct=yield_result.variance_pct,
            flagged=yield_result.flagged,
            direction=yield_result.direction,
            tolerance=tolerance,
            revision=run.revision,
        )
    )
    RunVarianceSnapshot.objects.bulk_create(snapshots)

    run.state = RunState.COMPLETED
    run.good_packets = good
    run.damaged_pouches = damaged
    run.cartons_used = cartons
    run.completed_at = timezone.now()
    run.ledger_entry_ids = [*entry_ids, fg_entry.pk]
    run.save(
        update_fields=[
            "state",
            "good_packets",
            "damaged_pouches",
            "cartons_used",
            "completed_at",
            "ledger_entry_ids",
        ]
    )
    log_audit(user, "ProductionRun", run.pk, "complete", {}, _run_snapshot(run))
    return run


@transaction.atomic
def amend_run(
    *,
    run: ProductionRun,
    reason: str,
    user: User | None = None,
) -> ProductionRun:
    """Reverse an ISSUED run's issues and return it to DRAFT.

    Invariants: only an ISSUED run can be amended (a completed run is a closed
    cost document); a reason is mandatory; every reversal is an exact opposite
    movement at the value the material left at, so the weighted average returns
    to what it was; and the amendment is audited with before/after snapshots.
    """
    run = _lock_run(run)
    if run.state != RunState.ISSUED:
        raise InvalidRunState(f"Run {run.pk} is {run.state}; only an ISSUED run can be amended.")

    cleaned_reason = reason.strip()
    if not cleaned_reason:
        raise InvalidMovement("An amendment requires a reason.")

    before = _run_snapshot(run)

    entries = list(StockLedger.objects.filter(pk__in=run.ledger_entry_ids).order_by("id"))
    movements: list[Movement] = []
    for entry in entries:
        if entry.qty >= 0:
            raise InvalidMovement("Only issued material can be reversed by an amendment.")
        movements.append(
            Movement(
                item_id=entry.item_id,
                qty=q3(-entry.qty),
                value=q2(-entry.value),
            )
        )

    if movements:
        post_movements(
            movements=movements,
            movement_type=MovementType.RECEIPT,
            source_type=SourceType.PRODUCTION_RUN,
            source_id=run.pk,
            user=user,
        )

    for line in run.lines.select_related("item").order_by("pk"):
        line.issued_qty = Decimal("0.000")
        line.issued_unit_value = None
        line.actual_qty = Decimal("0.000")
        line.save(update_fields=["issued_qty", "issued_unit_value", "actual_qty"])

    run.state = RunState.DRAFT
    run.issued_at = None
    run.ledger_entry_ids = []
    run.save(update_fields=["state", "issued_at", "ledger_entry_ids"])

    after = {**_run_snapshot(run), "reason": cleaned_reason}
    log_audit(user, "ProductionRun", run.pk, "amend", before, after)
    return run


def run_variance(run: ProductionRun) -> list[RunVarianceSnapshot]:
    """Return the latest variance snapshot for a run (empty until completed)."""
    snapshot = (
        RunVarianceSnapshot.objects.filter(run=run)
        .select_related("line")
        .order_by("revision", "pk")
    )
    rows = list(snapshot)
    if not rows:
        return []
    latest_revision = max(row.revision for row in rows)
    return [row for row in rows if row.revision == latest_revision]
