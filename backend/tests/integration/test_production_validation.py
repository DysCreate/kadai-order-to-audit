"""Validation and edge-case tests for the production services.

Requirement: AGENTS.md Section 4.7 and 5 – every service rejects invalid state
with a DomainError subclass, and no partially posted stock is left behind.
"""

from decimal import Decimal

import pytest

from apps.inventory.services import post_opening_balance
from apps.masters.models import Item, ItemType
from apps.masters.services import create_item, create_uom
from apps.production.models import BOMLineRole, RunState
from apps.production.services import (
    BOMLineInput,
    complete_run,
    create_bom_version,
    create_run,
    get_active_bom,
    issue_run,
    list_boms,
    production_runs,
)
from core.errors import BOMVersionMismatch, DomainError, InvalidMovement
from core.money import q2


@pytest.fixture
def workshop(make_item: object, db: None) -> dict[str, Item]:
    """Two finished goods and two raw materials, each product with a BOM."""
    create_uom(name="Packet", symbol="pkt")
    flour = make_item()  # type: ignore[operator]
    create_uom(name="Litre", symbol="L")
    oil = make_item(name="Cooking oil", uom_symbol="L")  # type: ignore[operator]
    murukku = create_item(name="Murukku 200 g", item_type=ItemType.FG, uom_symbol="pkt")
    mixture = create_item(name="Mixture 200 g", item_type=ItemType.FG, uom_symbol="pkt")

    post_opening_balance(item_id=flour.pk, qty="50", unit_cost="40")
    post_opening_balance(item_id=oil.pk, qty="20", unit_cost="100")

    create_bom_version(
        product=murukku,
        batch_output_qty=Decimal("100"),
        lines=[
            BOMLineInput(item_id=flour.pk, qty_per_batch=Decimal("10")),
            BOMLineInput(item_id=oil.pk, qty_per_batch=Decimal("1")),
        ],
    )
    create_bom_version(
        product=mixture,
        batch_output_qty=Decimal("100"),
        lines=[BOMLineInput(item_id=flour.pk, qty_per_batch=Decimal("5"))],
    )
    return {"flour": flour, "oil": oil, "murukku": murukku, "mixture": mixture}


def test_bom_line_validation(workshop: dict[str, Item]) -> None:
    """PS 4.7: role, quantity and item validation happen before any write."""
    product = workshop["murukku"]
    flour = workshop["flour"]

    with pytest.raises(DomainError, match="role"):
        create_bom_version(
            product=product,
            batch_output_qty="100",
            lines=[BOMLineInput(item_id=flour.pk, qty_per_batch="1", role="sauce")],
        )

    with pytest.raises(DomainError, match="greater than zero"):
        create_bom_version(
            product=product,
            batch_output_qty="100",
            lines=[BOMLineInput(item_id=flour.pk, qty_per_batch="0")],
        )

    with pytest.raises(DomainError, match="Unknown item"):
        create_bom_version(
            product=product,
            batch_output_qty="100",
            lines=[BOMLineInput(item_id=987_654, qty_per_batch="1")],
        )

    with pytest.raises(DomainError, match="float"):
        create_bom_version(
            product=product,
            batch_output_qty="100",
            lines=[BOMLineInput(item_id=flour.pk, qty_per_batch=1.5)],  # type: ignore[arg-type]
        )


def test_create_run_validation(workshop: dict[str, Item]) -> None:
    """PS 4.7: only finished goods, positive batches, and this product's BOM."""
    with pytest.raises(DomainError, match="finished goods"):
        create_run(product=workshop["flour"], batches="1")

    with pytest.raises(DomainError, match="at least one batch"):
        create_run(product=workshop["murukku"], batches="0")

    with pytest.raises(InvalidMovement, match="float"):
        create_run(product=workshop["murukku"], batches=1.5)  # type: ignore[arg-type]

    foreign_bom = get_active_bom(workshop["mixture"])
    with pytest.raises(BOMVersionMismatch, match="does not belong"):
        create_run(product=workshop["murukku"], batches="1", bom=foreign_bom)


def test_create_run_needs_a_bom(make_item: object, db: None) -> None:
    """PS 4.7: a product without a BOM cannot be produced."""
    create_uom(name="Packet", symbol="pkt")
    orphan = create_item(name="Unplanned snack", item_type=ItemType.FG, uom_symbol="pkt")

    with pytest.raises(DomainError, match="has no BOM"):
        create_run(product=orphan, batches="1")


def test_issue_rejects_unknown_lines_negatives_and_empty_issues(
    workshop: dict[str, Item],
) -> None:
    """PS 4.7: issuing is all-or-nothing and rejects nonsense input."""
    run = create_run(product=workshop["murukku"], batches="1")
    first_line = run.lines.first()
    assert first_line is not None

    with pytest.raises(InvalidMovement, match="Unknown run line"):
        issue_run(run=run, issued={first_line.pk + 500: "1"})
    with pytest.raises(InvalidMovement, match="cannot be negative"):
        issue_run(run=run, issued={first_line.pk: "-1"})
    with pytest.raises(InvalidMovement, match="at least one input"):
        issue_run(run=run, issued={line.pk: "0" for line in run.lines.all()})

    run.refresh_from_db()
    assert run.state == RunState.DRAFT


def test_complete_requires_matching_packaging_lines(workshop: dict[str, Item]) -> None:
    """PS 4.7: damaged pouches or used cartons need a pouch/carton BOM line."""
    run = create_run(product=workshop["murukku"], batches="1")
    issued = issue_run(run=run)

    with pytest.raises(InvalidMovement, match="no pouch line"):
        complete_run(run=issued, good_packets="90", damaged_pouches="1")

    with pytest.raises(InvalidMovement, match="no carton line"):
        complete_run(run=issued, good_packets="90", cartons_used="1")

    # Nothing was half-completed: the run is still ISSUED and completes with
    # no packaging counts on a BOM that has no packaging lines.
    completed = complete_run(run=issued, good_packets="90")
    assert completed.state == RunState.COMPLETED


def test_zero_cost_run_posts_a_zero_value_receipt(make_item: object, db: None) -> None:
    """PS 4.5: material supplied free still completes, with value exactly zero."""
    create_uom(name="Packet", symbol="pkt")
    free_flour = make_item(name="Donated flour", uom_symbol="kg")  # type: ignore[operator]
    product = create_item(name="Free snack", item_type=ItemType.FG, uom_symbol="pkt")
    post_opening_balance(item_id=free_flour.pk, qty="10", unit_cost="0")

    create_bom_version(
        product=product,
        batch_output_qty="50",
        lines=[BOMLineInput(item_id=free_flour.pk, qty_per_batch="5")],
    )
    run = issue_run(run=create_run(product=product, batches="1"))
    complete_run(run=run, good_packets="50")

    run.refresh_from_db()
    assert run.state == RunState.COMPLETED

    from apps.inventory.models import SourceType, StockLedger

    receipt = StockLedger.objects.get(
        source_type=SourceType.PRODUCTION_RUN,
        source_id=run.pk,
        item=product,
    )
    assert receipt.qty == Decimal("50.000")
    assert q2(receipt.value) == Decimal("0.00")


def test_listing_can_be_filtered_by_product(workshop: dict[str, Item]) -> None:
    """PS 4.7: BOM and run listings filter by product without leaking others."""
    murukku = workshop["murukku"]
    create_run(product=murukku, batches="1")
    create_run(product=workshop["mixture"], batches="1")

    assert [bom.product_id for bom in list_boms(murukku)] == [murukku.pk]
    assert list_boms().count() == 2

    murukku_runs = production_runs(product=murukku)
    assert murukku_runs.count() == 1
    assert murukku_runs.get().product_id == murukku.pk
    assert production_runs().count() == 2
    assert {line.role for line in get_active_bom(murukku).lines.all()} == {BOMLineRole.MATERIAL}
