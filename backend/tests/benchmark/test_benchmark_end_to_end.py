"""Benchmark ground truth for the production loop: Appendix A steps 1-3.

Requirement: Phase 2 exit gate – flour 120 kg, oil 19.5 L, spice mix 3.8 kg,
pouches 306, cartons 21, FG 238, yield -6% and oil +5% flagged, pouch -3% not
flagged, all replayed through the same services the API uses.

The expected values come from Appendix A and are never edited to make a test
pass.
"""

from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.db.models import Sum

from apps.benchmark.services import seed_benchmark
from apps.inventory.models import MovementType, SourceType, StockBalance, StockLedger
from apps.inventory.services import (
    PurchaseLineInput,
    create_purchase,
    reconcile_stock,
    stock_summary,
)
from apps.masters.models import Item, Supplier
from apps.production.models import ProductionRun, RunState
from apps.production.services import complete_run, create_run, issue_run, run_variance

EXPECTED_CLOSING = {
    "Flour": Decimal("120.000"),
    "Cooking oil": Decimal("19.500"),
    "Salt and spice mix": Decimal("3.800"),
    "200 g pouch": Decimal("306.000"),
    "Carton (holds 20 packets)": Decimal("21.000"),
    "Murukku 200 g": Decimal("238.000"),
}


@pytest.mark.django_db
def test_benchmark_steps_1_to_3_reproduce_appendix_a() -> None:
    """PS Appendix A steps 1-3: purchase, issue, complete, and every closing."""
    seed_benchmark()

    flour = Item.objects.get(name="Flour")
    product = Item.objects.get(name="Murukku 200 g")
    supplier = Supplier.objects.get(name="Sri Lakshmi Flour Mills")

    # --- Step 1: purchase 60 kg flour at 45 -------------------------------
    purchase = create_purchase(
        supplier=supplier,
        reference="SLFM/0187",
        lines=[PurchaseLineInput(item_id=flour.pk, qty=Decimal("60"), unit_cost=Decimal("45"))],
    )
    flour_balance = StockBalance.objects.get(item=flour)
    assert flour_balance.qty == Decimal("160.000")
    assert flour_balance.value == Decimal("6900.00")
    assert flour_balance.value / flour_balance.qty == Decimal("43.125")

    # --- Step 2: production run, 1 batch, issue raw materials --------------
    run = create_run(product=product, batches=Decimal("1"))
    assert run.planned_output_qty == Decimal("200.000")
    assert run.state == RunState.DRAFT

    lines = {line.item.name: line for line in run.lines.select_related("item")}
    issue_run(
        run=run,
        issued={
            lines["Flour"].pk: Decimal("40"),
            lines["Cooking oil"].pk: Decimal("10.5"),
            lines["Salt and spice mix"].pk: Decimal("1.2"),
        },
    )
    assert StockBalance.objects.get(item=flour).qty == Decimal("120.000")
    assert StockBalance.objects.get(item=Item.objects.get(name="Cooking oil")).qty == Decimal(
        "19.500"
    )

    # The 40 kg issue is valued at the weighted average: 40 x 43.125 = 1,725.
    flour_issue = StockLedger.objects.get(
        source_type=SourceType.PRODUCTION_RUN,
        source_id=run.pk,
        item=flour,
        movement_type=MovementType.ISSUE,
    )
    assert flour_issue.value == Decimal("-1725.00")
    assert flour_issue.unit_value == Decimal("43.1250")

    # --- Step 3: 188 good packets, 6 damaged pouches, 9 cartons ------------
    complete_run(run=run, good_packets=Decimal("188"), damaged_pouches="6", cartons_used="9")
    run.refresh_from_db()
    assert run.state == RunState.COMPLETED

    rows = {row.item.name: row for row in stock_summary()}
    for item_name, expected_qty in EXPECTED_CLOSING.items():
        assert rows[item_name].qty == expected_qty, item_name

    # Five inputs left stock; the finished-goods receipt is 188 packets valued
    # at the run's material cost (1,725 + 1,470 + 240 + 485 + 135 = 4,055).
    run_issues = StockLedger.objects.filter(
        source_type=SourceType.PRODUCTION_RUN,
        source_id=run.pk,
        movement_type=MovementType.ISSUE,
    )
    assert run_issues.count() == 5
    assert set(run_issues.values_list("item__name", flat=True)) == {
        "Flour",
        "Cooking oil",
        "Salt and spice mix",
        "200 g pouch",
        "Carton (holds 20 packets)",
    }

    fg_receipt = StockLedger.objects.get(
        source_type=SourceType.PRODUCTION_RUN,
        source_id=run.pk,
        item=product,
        movement_type=MovementType.RECEIPT,
    )
    assert fg_receipt.qty == Decimal("188.000")
    assert fg_receipt.value == Decimal("4055.00")

    materials = StockLedger.objects.filter(
        source_type=SourceType.PRODUCTION_RUN,
        source_id=run.pk,
        movement_type=MovementType.ISSUE,
    ).aggregate(total=Sum("value"))["total"]
    assert materials is not None
    assert -materials == Decimal("4055.00")

    # Purchases and runs stay traceable, and the ledger reconciles.
    assert (
        StockLedger.objects.filter(source_type=SourceType.PURCHASE, source_id=purchase.pk).count()
        == 1
    )
    assert reconcile_stock() == []


@pytest.mark.django_db
def test_benchmark_steps_1_to_3_variance_snapshot() -> None:
    """PS Appendix A: yield -6% and oil +5% flagged; pouch -3% is not."""
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
    complete_run(run=run, good_packets="188", damaged_pouches="6", cartons_used="9")

    variance = {row.item_name: row for row in run_variance(run)}

    assert variance["Murukku 200 g (yield)"].flagged is True
    assert variance["Murukku 200 g (yield)"].variance_pct == Decimal("-0.060000")
    assert variance["Murukku 200 g (yield)"].direction == "adverse"

    assert variance["Cooking oil"].flagged is True
    assert variance["Cooking oil"].variance_pct == Decimal("0.050000")

    assert variance["200 g pouch"].variance_pct == Decimal("-0.030000")
    assert variance["200 g pouch"].flagged is False

    assert variance["Carton (holds 20 packets)"].flagged is True
    assert variance["Carton (holds 20 packets)"].direction == "favourable"

    assert variance["Flour"].variance_pct == Decimal("0.000000")
    assert variance["Flour"].flagged is False

    assert ProductionRun.objects.filter(pk=run.pk).exists()


@pytest.mark.django_db
def test_benchmark_seed_loads_the_bom() -> None:
    """PS 4.15: the seed loads exactly one BOM version, idempotently."""
    call_command("seed_benchmark", stdout=StringIO())
    seed_benchmark()

    product = Item.objects.get(name="Murukku 200 g")
    assert product.boms.count() == 1
    bom = product.boms.get()
    assert bom.version == 1
    assert bom.batch_output_qty == Decimal("200.000")
    assert {(line.item.name, line.qty_per_batch, line.role) for line in bom.lines.all()} == {
        ("Flour", Decimal("40.000"), "material"),
        ("Cooking oil", Decimal("10.000"), "material"),
        ("Salt and spice mix", Decimal("1.200"), "material"),
        ("200 g pouch", Decimal("200.000"), "pouch"),
        ("Carton (holds 20 packets)", Decimal("10.000"), "carton"),
    }
