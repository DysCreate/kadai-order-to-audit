"""Costing integration tests against real PostgreSQL.

Requirement: Phase 4 exit gate – overheads absorb into finished goods through a
value-only ledger row, cost per packet is 5,855 / 188 = 31.14, and a monthly
pool is allocated by standard batch-hours without losing a paisa.
"""

from datetime import date
from decimal import Decimal

import pytest

from apps.audit.models import AuditLog
from apps.benchmark.services import seed_benchmark
from apps.costing.models import OverheadAllocation, OverheadEntry
from apps.costing.services import (
    allocate_monthly_overhead,
    product_cost_summary,
    record_monthly_overhead,
    record_run_overhead,
    run_cost_sheet,
)
from apps.inventory.models import MovementType, SourceType, StockBalance, StockLedger
from apps.inventory.services import (
    PurchaseLineInput,
    adjust_stock,
    create_purchase,
    post_opening_balance,
    reconcile_stock,
)
from apps.masters.models import Item, ItemType, Supplier
from apps.masters.services import create_item, create_uom, set_item_standard_batch_hours
from apps.production.services import (
    BOMLineInput,
    complete_run,
    create_bom_version,
    create_run,
    issue_run,
)
from core.errors import DomainError, InsufficientStock, InvalidRunState


@pytest.fixture
def produced_run(db: None) -> dict[str, object]:
    """Appendix A steps 1-3: a completed 188-packet run."""
    seed_benchmark()
    flour = Item.objects.get(name="Flour")
    product = Item.objects.get(name="Murukku 200 g")
    create_purchase(
        supplier=Supplier.objects.get(name="Sri Lakshmi Flour Mills"),
        lines=[PurchaseLineInput(item_id=flour.pk, qty="60", unit_cost="45")],
    )
    run = create_run(product=product, batches="1")
    lines = {line.item.name: line for line in run.lines.select_related("item")}
    issue_run(
        run=run,
        issued={
            lines["Flour"].pk: "40",
            lines["Cooking oil"].pk: "10.5",
            lines["Salt and spice mix"].pk: "1.2",
        },
    )
    run = complete_run(run=run, good_packets="188", damaged_pouches="6", cartons_used="9")
    return {"run": run, "product": product}


def test_run_overheads_absorb_into_fg_and_produce_the_benchmark_cost_sheet(
    produced_run: dict[str, object],
) -> None:
    """PS Appendix A step 8: materials 4,055 + overheads 1,800 = 31.14 per packet."""
    run = produced_run["run"]
    product = produced_run["product"]
    assert isinstance(product, Item)

    balance_before = StockBalance.objects.get(item=product)
    labour = record_run_overhead(run=run, category="labour", amount="1200", description="Labour")
    power = record_run_overhead(
        run=run, category="power", amount="600", description="Gas and power"
    )

    assert labour.scope == "RUN"
    assert labour.run_id == run.pk
    assert power.amount == Decimal("600.00")

    balance_after = StockBalance.objects.get(item=product)
    assert balance_after.qty == balance_before.qty
    assert balance_after.value == balance_before.value + Decimal("1800.00")

    value_rows = StockLedger.objects.filter(
        source_type=SourceType.PRODUCTION_RUN,
        source_id=run.pk,
        qty=0,
    ).order_by("pk")
    assert [(row.movement_type, row.value, row.unit_value) for row in value_rows] == [
        (MovementType.ADJUSTMENT, Decimal("1200.00"), Decimal("0.0000")),
        (MovementType.ADJUSTMENT, Decimal("600.00"), Decimal("0.0000")),
    ]

    sheet = run_cost_sheet(run)
    assert sheet["materials_value"] == Decimal("4055.00")
    assert sheet["overhead_value"] == Decimal("1800.00")
    assert sheet["total_cost"] == Decimal("5855.00")
    assert sheet["good_packets"] == Decimal("188.000")
    assert sheet["cost_per_packet"] == Decimal("31.14")
    assert sheet["selling_price"] == Decimal("50.00")
    assert sheet["margin_per_packet"] == Decimal("18.86")
    assert sheet["margin_pct"] == Decimal("37.72")
    assert sheet["fg_stock_qty"] == Decimal("238.000")
    assert sheet["fg_stock_value"] == Decimal("6847.50")
    assert sheet["fg_avg_cost"] == Decimal("28.7710")
    assert [line["category"] for line in sheet["overheads"]] == ["labour", "power"]

    assert AuditLog.objects.filter(entity="ProductionRun", action="overhead").count() == 2
    assert reconcile_stock() == []

    summary = product_cost_summary(product)
    assert summary["stock_qty"] == Decimal("238.000")
    assert summary["avg_cost"] == Decimal("28.7710")
    assert summary["margin_per_packet"] == Decimal("21.23")


def test_run_overhead_rejected_before_completion(db: None) -> None:
    """PS 4.6/Phase 4: overheads apply only to a completed, closed run."""
    seed_benchmark()
    product = Item.objects.get(name="Murukku 200 g")
    run = create_run(product=product, batches="1")

    with pytest.raises(InvalidRunState):
        record_run_overhead(run=run, category="labour", amount="100")

    assert OverheadEntry.objects.count() == 0


def test_run_overhead_rejected_when_fg_stock_is_zero(
    produced_run: dict[str, object],
) -> None:
    """PS 4.3: a value-only row cannot create value on a zero-quantity balance."""
    run = produced_run["run"]
    product = produced_run["product"]
    assert isinstance(product, Item)

    adjust_stock(
        item_id=product.pk,
        qty_delta="-238",
        reason="Stock sold out before overhead entry",
    )
    assert StockBalance.objects.get(item=product).qty == Decimal("0.000")

    with pytest.raises(InsufficientStock):
        record_run_overhead(run=run, category="labour", amount="100")

    assert OverheadEntry.objects.count() == 0
    assert reconcile_stock() == []


def _monthly_scenario() -> dict[str, Item]:
    """Two completed runs of 2 and 1 batches, with standard batch-hours of 2."""
    create_uom(name="Kilogram", symbol="kg")
    create_uom(name="Packet", symbol="pkt")
    raw = create_item(name="Costing flour", item_type="RAW", uom_symbol="kg")
    product = create_item(name="Costing snack", item_type=ItemType.FG, uom_symbol="pkt")
    set_item_standard_batch_hours(item=product, hours="2")
    post_opening_balance(item_id=raw.pk, qty="100", unit_cost="10")
    create_bom_version(
        product=product,
        batch_output_qty="10",
        lines=[BOMLineInput(item_id=raw.pk, qty_per_batch="1")],
    )
    return {"raw": raw, "product": product}


def test_monthly_pool_is_allocated_by_standard_batch_hours(db: None) -> None:
    """Phase 4: a 1,000 pool over 4 and 2 batch-hours splits 666.67 / 333.33."""
    scenario = _monthly_scenario()
    raw = scenario["raw"]
    product = scenario["product"]

    first = create_run(product=product, batches="2")
    issue_run(run=first, issued={first.lines.get(item=raw).pk: "2"})
    complete_run(run=first, good_packets="20")

    second = create_run(product=product, batches="1")
    issue_run(run=second, issued={second.lines.get(item=raw).pk: "1"})
    complete_run(run=second, good_packets="10")

    entry = record_monthly_overhead(
        period=date.today(),
        category="power",
        amount="1000",
        description="Factory power",
    )
    allocations = allocate_monthly_overhead(period=date.today())

    assert len(allocations) == 2
    by_run = {allocation.run_id: allocation for allocation in allocations}
    assert by_run[first.pk].amount == Decimal("666.67")
    assert by_run[second.pk].amount == Decimal("333.33")
    assert sum((allocation.amount for allocation in allocations), Decimal("0")) == Decimal(
        "1000.00"
    )
    assert OverheadAllocation.objects.filter(entry=entry).count() == 2

    first_sheet = run_cost_sheet(first)
    assert first_sheet["standard_batch_hours"] == Decimal("2.000")
    assert first_sheet["batch_hours"] == Decimal("4.000")
    assert first_sheet["overhead_value"] == Decimal("666.67")
    assert first_sheet["cost_per_packet"] == Decimal("34.33")

    value_rows = StockLedger.objects.filter(qty=0, source_id__in=[first.pk, second.pk])
    assert value_rows.count() == 2
    assert set(value_rows.values_list("movement_type", flat=True)) == {MovementType.ADJUSTMENT}
    assert reconcile_stock() == []

    # Re-running allocation is idempotent: no second value row, same shares.
    ledger_count = StockLedger.objects.count()
    again = allocate_monthly_overhead(period=date.today())
    assert len(again) == 2
    assert StockLedger.objects.count() == ledger_count


def test_monthly_pool_without_completed_runs_is_rejected(db: None) -> None:
    """Phase 4 negative path: an empty month has no allocation basis."""
    record_monthly_overhead(
        period=date(2020, 1, 1),
        category="labour",
        amount="500",
    )

    with pytest.raises(DomainError):
        allocate_monthly_overhead(period=date(2020, 1, 1))
