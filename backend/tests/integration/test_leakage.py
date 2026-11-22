"""Integration tests for the Leakage Radar services.

Requirement: Phase 6 exit gate – the report card numbers come from real stored
ledger values and the dashboard tile sums only adverse leakage.
"""

from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.costing.services import record_run_overhead
from apps.inventory.services import PurchaseLineInput, create_purchase
from apps.masters.models import Item, Supplier
from apps.production.models import ProductionRun
from apps.production.services import (
    complete_run,
    create_run,
    issue_run,
    leakage_summary,
    leakage_trends,
    run_report_card,
    trailing_yield_factor,
)
from core.errors import InvalidRunState

pytestmark = pytest.mark.django_db


@pytest.fixture
def completed_run(db: None) -> ProductionRun:
    """Appendix A steps 1-3 through the services."""
    call_command("seed_benchmark", stdout=StringIO())

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
    return ProductionRun.objects.get(pk=run.pk)


def test_report_card_uses_the_runs_own_ledger_values(completed_run: ProductionRun) -> None:
    """PS 2.1: standard 3,970, actual 4,055, flour at the weighted average."""
    card = run_report_card(completed_run)

    lines = {line.item_name: line for line in card.lines}
    assert lines["Flour"].actual_rate == Decimal("43.1250")
    assert lines["Flour"].price_impact == Decimal("45.00")
    assert lines["Cooking oil"].usage_impact == Decimal("70.00")
    assert lines["200 g pouch"].actual_value == Decimal("485.00")

    assert card.standard_materials == Decimal("3970.00")
    assert card.actual_materials == Decimal("4055.00")
    assert card.material_impact == Decimal("85.00")
    assert card.cost_per_packet == Decimal("21.57")
    assert card.overhead_per_packet == Decimal("0.00")
    assert card.yield_gap.unexplained_packets == Decimal("6.000")


def test_report_card_includes_overheads_after_completion(completed_run: ProductionRun) -> None:
    """PS 2.1: labour and power move the bridge's total to 31.14."""
    record_run_overhead(
        run=completed_run,
        category="labour",
        amount="1200",
        description="Labour",
    )
    record_run_overhead(
        run=completed_run,
        category="power",
        amount="600",
        description="Gas and power",
    )

    card = run_report_card(completed_run)
    bridge = {step.key: step.amount for step in card.bridge}

    assert card.overhead_value == Decimal("1800.00")
    assert bridge["yield_shortfall"] == Decimal("1.27")
    assert bridge["price_usage"] == Decimal("0.45")
    assert bridge["overhead"] == Decimal("9.57")
    assert card.cost_per_packet == Decimal("31.14")
    assert card.margin_per_packet == Decimal("18.86")


def test_report_card_before_completion_is_refused(db: None) -> None:
    """PS 2.1 negative path: a draft run has no actuals to report."""
    call_command("seed_benchmark", stdout=StringIO())
    run = create_run(product=Item.objects.get(name="Murukku 200 g"), batches="1")

    with pytest.raises(InvalidRunState):
        run_report_card(run)


def test_trailing_yield_is_realised_yield(completed_run: ProductionRun) -> None:
    """PS 2.3: the Loop Closer uses 188 / 200 = 0.94, not the BOM's 1.00."""
    assert trailing_yield_factor(completed_run.product) == Decimal("0.9400")


def test_trends_read_stored_snapshots(completed_run: ProductionRun) -> None:
    """PS 2.2: one completed run gives one point per input and no drift yet."""
    trends = leakage_trends(completed_run.product)

    assert trends["product_name"] == "Murukku 200 g"
    assert len(trends["runs"]) == 1
    oil = next(row for row in trends["ingredients"] if row["item_name"] == "Cooking oil")
    assert len(oil["points"]) == 1
    assert oil["points"][0]["variance_pct"] == Decimal("0.050000")
    assert trends["drift_alerts"] == []


def test_leakage_summary_counts_adverse_money_only(completed_run: ProductionRun) -> None:
    """PS 2.2: adverse material 115 + 12 missing packets at 19.85 = 353.20.

    The favourable pouch and carton usage (-15 each) do not reduce leakage; the
    tile sums adverse variances only, as the plan defines it.
    """
    record_run_overhead(run=completed_run, category="labour", amount="1200")

    business_day = timezone.localdate(completed_run.completed_at)
    summary = leakage_summary(today=business_day)

    assert summary["amount"] == Decimal("353.20")
    assert summary["runs"] == 1
    culprits = {row["label"]: row["amount"] for row in summary["top_culprits"]}
    assert culprits["Yield shortfall"] == Decimal("238.20")
    assert culprits["Cooking oil"] == Decimal("70.00")
    assert culprits["Flour"] == Decimal("45.00")
    assert summary["period"] == business_day.replace(day=1).isoformat()


def test_a_second_bom_version_does_not_rewrite_history(completed_run: ProductionRun) -> None:
    """PS 4.7/2.1: standard cost is snapshotted on the run's BOM version."""
    from apps.production.services import BOMLineInput, create_bom_version

    product = Item.objects.get(name="Murukku 200 g")
    flour = Item.objects.get(name="Flour")
    create_bom_version(
        product=product,
        batch_output_qty="200",
        lines=[BOMLineInput(item_id=flour.pk, qty_per_batch="40", standard_rate="99")],
    )

    card = run_report_card(completed_run)
    lines = {line.item_name: line for line in card.lines}
    assert lines["Flour"].standard_rate == Decimal("42.0000")
    assert lines["Flour"].standard_value == Decimal("1680.00")
    assert completed_run.bom_version == 1
