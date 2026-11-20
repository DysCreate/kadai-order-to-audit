"""Production integration tests against real PostgreSQL.

Requirement: AGENTS.md Section 4.6, 4.7, 4.10 and Section 5 – versioned BOM,
run state machine, derived packaging issues, FG receipt, variance snapshot and
the audited amend flow.
"""

from decimal import Decimal

import pytest

from apps.audit.models import AuditLog
from apps.inventory.models import MovementType, SourceType, StockBalance, StockLedger
from apps.inventory.services import post_opening_balance, reconcile_stock
from apps.masters.models import Item, ItemType
from apps.masters.services import create_item, create_uom
from apps.production.models import (
    BOM,
    BOMLineRole,
    ProductionRun,
    RunState,
    RunVarianceSnapshot,
)
from apps.production.services import (
    BOMLineInput,
    amend_run,
    complete_run,
    create_bom_version,
    create_run,
    get_active_bom,
    issue_run,
    run_variance,
)
from core.errors import BOMVersionMismatch, InsufficientStock, InvalidMovement, InvalidRunState


@pytest.fixture
def scenario(make_item: object, db: None) -> dict[str, Item]:
    """A small BOM with opening stock: 10 kg flour -> 94 packets in a full run."""
    flour = make_item()  # type: ignore[operator]
    oil = make_item(name="Cooking oil", uom_symbol="L")  # type: ignore[operator]
    pouch = make_item(name="200 g pouch", item_type="PACKAGING", uom_symbol="pc")  # type: ignore[operator]
    carton = make_item(name="Carton", item_type="PACKAGING", uom_symbol="pc")  # type: ignore[operator]
    create_uom(name="Packet", symbol="pkt")
    product = create_item(name="Murukku 200 g", item_type=ItemType.FG, uom_symbol="pkt")

    post_opening_balance(item_id=flour.pk, qty="20", unit_cost="40")
    post_opening_balance(item_id=oil.pk, qty="5", unit_cost="100")
    post_opening_balance(item_id=pouch.pk, qty="200", unit_cost="2")
    post_opening_balance(item_id=carton.pk, qty="10", unit_cost="10")

    create_bom_version(
        product=product,
        batch_output_qty=Decimal("100"),
        lines=[
            BOMLineInput(item_id=flour.pk, qty_per_batch=Decimal("10")),
            BOMLineInput(item_id=oil.pk, qty_per_batch=Decimal("2")),
            BOMLineInput(item_id=pouch.pk, qty_per_batch=Decimal("100"), role=BOMLineRole.POUCH),
            BOMLineInput(item_id=carton.pk, qty_per_batch=Decimal("5"), role=BOMLineRole.CARTON),
        ],
    )
    return {
        "flour": flour,
        "oil": oil,
        "pouch": pouch,
        "carton": carton,
        "product": product,
    }


def _qty(item: Item) -> Decimal:
    return StockBalance.objects.get(item=item).qty


def _issue_then_complete(run: ProductionRun, items: dict[str, Item]) -> ProductionRun:
    issue_run(
        run=run,
        issued={
            run.lines.get(item=items["flour"]).pk: Decimal("10"),
            run.lines.get(item=items["oil"]).pk: Decimal("2.5"),
        },
    )
    assert complete_run(run=run, good_packets="94", damaged_pouches="3", cartons_used="4")
    return run


def test_bom_versions_are_additive_and_runs_keep_their_plan(scenario: dict[str, Item]) -> None:
    """PS 4.7 BOM versioning: a new version never rewrites an existing run."""
    product = scenario["product"]
    first_version = get_active_bom(product)
    run = create_run(product=product, batches="1")

    create_bom_version(
        product=product,
        batch_output_qty=Decimal("80"),
        lines=[BOMLineInput(item_id=scenario["flour"].pk, qty_per_batch=Decimal("12"))],
    )

    assert BOM.objects.filter(product=product).count() == 2
    assert get_active_bom(product).version == first_version.version + 1
    assert run.bom_version == first_version.version
    assert run.lines.get(item=scenario["flour"]).planned_qty == Decimal("10.000")

    with pytest.raises(BOMVersionMismatch):
        create_run(product=product, batches="1", bom=first_version)


def test_run_state_machine_rejects_illegal_transitions(scenario: dict[str, Item]) -> None:
    """PS 4.7 state machine: DRAFT -> ISSUED -> COMPLETED, and nothing else."""
    product = scenario["product"]
    draft = create_run(product=product, batches="1")

    with pytest.raises(InvalidRunState):
        complete_run(run=draft, good_packets="10")
    with pytest.raises(InvalidRunState):
        amend_run(run=draft, reason="Too early")

    issued = issue_run(run=draft)
    with pytest.raises(InvalidRunState):
        issue_run(run=issued)

    completed = complete_run(run=issued, good_packets="94", damaged_pouches="3", cartons_used="4")
    with pytest.raises(InvalidRunState):
        amend_run(run=completed, reason="Completed runs are closed")


def test_issuing_beyond_stock_writes_nothing(scenario: dict[str, Item]) -> None:
    """PS 4.11: a shortage leaves the run in DRAFT and posts no ledger rows."""
    run = create_run(product=scenario["product"], batches="1")
    ledger_count = StockLedger.objects.count()

    with pytest.raises(InsufficientStock):
        issue_run(run=run, issued={run.lines.get(item=scenario["flour"]).pk: Decimal("21")})

    run.refresh_from_db()
    assert run.state == RunState.DRAFT
    assert StockLedger.objects.count() == ledger_count
    assert run.ledger_entry_ids == []


def test_completion_posts_packaging_issues_and_valued_fg_receipt(
    scenario: dict[str, Item],
) -> None:
    """PS 5 production run: four ISSUE rows, one FG RECEIPT, exact material value."""
    run = create_run(product=scenario["product"], batches="1")
    _issue_then_complete(run, scenario)

    run.refresh_from_db()
    assert run.state == RunState.COMPLETED

    issue_rows = StockLedger.objects.filter(
        source_type=SourceType.PRODUCTION_RUN,
        source_id=run.pk,
        movement_type=MovementType.ISSUE,
    )
    assert set(issue_rows.values_list("item__name", "qty")) == {
        ("Flour", Decimal("-10.000")),
        ("Cooking oil", Decimal("-2.500")),
        ("200 g pouch", Decimal("-97.000")),
        ("Carton", Decimal("-4.000")),
    }

    # Flour 10@40 + oil 2.5@100 + pouches 97@2 + cartons 4@10 = 884.00.
    receipt = StockLedger.objects.get(
        source_type=SourceType.PRODUCTION_RUN,
        source_id=run.pk,
        item=scenario["product"],
        movement_type=MovementType.RECEIPT,
    )
    assert receipt.qty == Decimal("94.000")
    assert receipt.value == Decimal("884.00")

    assert _qty(scenario["flour"]) == Decimal("10.000")
    assert _qty(scenario["oil"]) == Decimal("2.500")
    assert _qty(scenario["pouch"]) == Decimal("103.000")
    assert _qty(scenario["carton"]) == Decimal("6.000")
    assert _qty(scenario["product"]) == Decimal("94.000")
    assert reconcile_stock() == []


def test_variance_snapshot_uses_tolerance_and_direction(scenario: dict[str, Item]) -> None:
    """PS 4.6: -3% is not flagged, +25% adverse, -20% favourable, yield adverse."""
    run = create_run(product=scenario["product"], batches="1")
    _issue_then_complete(run, scenario)

    rows = {row.item_name: row for row in run_variance(run)}

    assert rows["200 g pouch"].variance_pct == Decimal("-0.030000")
    assert rows["200 g pouch"].flagged is False
    assert rows["200 g pouch"].direction == "favourable"

    assert rows["Cooking oil"].variance_pct == Decimal("0.250000")
    assert rows["Cooking oil"].flagged is True
    assert rows["Cooking oil"].direction == "adverse"

    assert rows["Carton"].flagged is True
    assert rows["Carton"].direction == "favourable"

    yield_row = rows["Murukku 200 g (yield)"]
    assert yield_row.variance_pct == Decimal("-0.060000")
    assert yield_row.flagged is True
    assert yield_row.direction == "adverse"
    assert yield_row.line_id is None

    assert RunVarianceSnapshot.objects.filter(run=run).count() == 5


def test_completion_returns_unused_issued_material(scenario: dict[str, Item]) -> None:
    """PS 4.3 corrections: issuing the plan but using less returns the difference."""
    run = create_run(product=scenario["product"], batches="1")
    # Issue the full planned pouch quantity, then consume 94 good + 3 damaged.
    issue_run(
        run=run,
        issued={run.lines.get(item=scenario["pouch"]).pk: Decimal("100")},
    )
    complete_run(run=run, good_packets="94", damaged_pouches="3", cartons_used="4")

    assert _qty(scenario["pouch"]) == Decimal("103.000")
    returns = StockLedger.objects.filter(
        source_type=SourceType.PRODUCTION_RUN,
        source_id=run.pk,
        movement_type=MovementType.RECEIPT,
        item=scenario["pouch"],
    )
    assert returns.count() == 1
    assert returns.get().qty == Decimal("3.000")
    assert returns.get().value == Decimal("6.00")


def test_amend_reverses_issues_exactly_and_is_audited(scenario: dict[str, Item]) -> None:
    """PS 4.10 amend: reversing entries restore the weighted average and audit."""
    run = create_run(product=scenario["product"], batches="1")
    issue_run(
        run=run,
        issued={
            run.lines.get(item=scenario["flour"]).pk: Decimal("10"),
            run.lines.get(item=scenario["oil"]).pk: Decimal("3"),
        },
    )
    flour_value_after_issue = StockBalance.objects.get(item=scenario["flour"]).value

    amended = amend_run(run=run, reason="Supervisor issued the wrong oil quantity")

    assert amended.state == RunState.DRAFT
    assert amended.issued_at is None
    assert amended.ledger_entry_ids == []
    assert all(line.issued_qty == 0 for line in amended.lines.all())

    assert _qty(scenario["flour"]) == Decimal("20.000")
    assert StockBalance.objects.get(item=scenario["flour"]).value == Decimal("800.00")
    assert _qty(scenario["oil"]) == Decimal("5.000")
    assert flour_value_after_issue == Decimal("400.00")
    assert reconcile_stock() == []

    audit = AuditLog.objects.get(entity="ProductionRun", entity_id=run.pk, action="amend")
    assert audit.before["state"] == RunState.ISSUED
    assert audit.after["reason"] == "Supervisor issued the wrong oil quantity"

    # The run can be issued again from DRAFT with corrected quantities.
    reissued = issue_run(run=amended, issued={amended.lines.get(item=scenario["oil"]).pk: "2.5"})
    assert reissued.state == RunState.ISSUED
    assert _qty(scenario["oil"]) == Decimal("2.500")


def test_amend_requires_a_reason(scenario: dict[str, Item]) -> None:
    """PS 4.10: an amendment without a reason is refused."""
    run = create_run(product=scenario["product"], batches="1")
    issued = issue_run(run=run)

    with pytest.raises(InvalidMovement):
        amend_run(run=issued, reason="   ")


def test_completion_validates_packing_record(scenario: dict[str, Item]) -> None:
    """PS 5 negative paths: zero good packets and impossible counters are refused."""
    run = create_run(product=scenario["product"], batches="1")
    issued = issue_run(run=run)

    with pytest.raises(InvalidMovement):
        complete_run(run=issued, good_packets="0")
    with pytest.raises(InvalidMovement):
        complete_run(run=issued, good_packets="10", damaged_pouches="-1")
    with pytest.raises(InvalidMovement):
        complete_run(run=issued, good_packets="10", cartons_used="-2")


def test_bom_validation_rejects_bad_input(scenario: dict[str, Item]) -> None:
    """PS 4.7: BOM lines are positive, unique and at most one pouch/carton."""
    product = scenario["product"]
    with pytest.raises(Exception, match="zero"):
        create_bom_version(product=product, batch_output_qty=Decimal("0"), lines=[])
    with pytest.raises(Exception, match="twice"):
        create_bom_version(
            product=product,
            batch_output_qty=Decimal("100"),
            lines=[
                BOMLineInput(item_id=scenario["flour"].pk, qty_per_batch=Decimal("1")),
                BOMLineInput(item_id=scenario["flour"].pk, qty_per_batch=Decimal("2")),
            ],
        )
    with pytest.raises(Exception, match="pouch"):
        create_bom_version(
            product=product,
            batch_output_qty=Decimal("100"),
            lines=[
                BOMLineInput(
                    item_id=scenario["pouch"].pk,
                    qty_per_batch=Decimal("1"),
                    role=BOMLineRole.POUCH,
                ),
                BOMLineInput(
                    item_id=scenario["carton"].pk,
                    qty_per_batch=Decimal("1"),
                    role=BOMLineRole.POUCH,
                ),
            ],
        )
    with pytest.raises(Exception, match="finished-goods"):
        create_bom_version(
            product=scenario["flour"],
            batch_output_qty=Decimal("100"),
            lines=[BOMLineInput(item_id=scenario["oil"].pk, qty_per_batch=Decimal("1"))],
        )
