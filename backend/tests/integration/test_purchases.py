"""Purchase integration tests against real PostgreSQL.

Requirement: AGENTS.md Section 5 (purchase creates a RECEIPT row, updates the
weighted average, and a bad line posts nothing) and Appendix A step 1.
"""

from decimal import Decimal

import pytest

from apps.inventory.models import MovementType, Purchase, SourceType, StockBalance, StockLedger
from apps.inventory.services import (
    PurchaseLineInput,
    create_purchase,
    post_opening_balance,
    reconcile_stock,
    stock_summary,
)
from apps.masters.models import Item, Supplier
from apps.masters.services import create_item, create_supplier, create_uom
from core.errors import DomainError, InvalidMovement


@pytest.fixture
def flour(make_item: object, db: None) -> Item:
    """Flour with the Appendix A opening balance of 100 kg at 42."""
    item = make_item()  # type: ignore[operator]
    post_opening_balance(item_id=item.pk, qty="100", unit_cost="42")
    return item


@pytest.fixture
def supplier(db: None) -> Supplier:
    return create_supplier(name="Sri Lakshmi Flour Mills", gstin="33AABCS1234F1Z5")


def test_purchase_posts_receipt_and_updates_weighted_average(
    flour: Item, supplier: Supplier
) -> None:
    """Appendix A step 1: 60 kg at 45 gives 160 kg at 43.125."""
    purchase = create_purchase(
        supplier=supplier,
        reference="SLFM/0187",
        lines=[PurchaseLineInput(item_id=flour.pk, qty=Decimal("60"), unit_cost=Decimal("45"))],
    )

    assert purchase.total_value == Decimal("2700.00")
    assert purchase.lines.count() == 1

    entry = StockLedger.objects.get(source_type=SourceType.PURCHASE, source_id=purchase.pk)
    assert entry.movement_type == MovementType.RECEIPT
    assert entry.qty == Decimal("60.000")
    assert entry.value == Decimal("2700.00")
    assert entry.unit_value == Decimal("45.0000")

    balance = StockBalance.objects.get(item=flour)
    assert balance.qty == Decimal("160.000")
    assert balance.value == Decimal("6900.00")

    row = next(row for row in stock_summary() if row.item.pk == flour.pk)
    assert row.avg_rate == Decimal("43.1250")
    assert reconcile_stock() == []


def test_multi_line_purchase_posts_every_receipt(flour: Item, supplier: Supplier) -> None:
    """PS 5 purchase: each line gets its own traceable RECEIPT row."""
    create_uom(name="Litre", symbol="L")
    oil = create_item(name="Cooking oil", item_type="RAW", uom_symbol="L")
    purchase = create_purchase(
        supplier=supplier,
        lines=[
            PurchaseLineInput(item_id=flour.pk, qty="10", unit_cost="45"),
            PurchaseLineInput(item_id=oil.pk, qty="5", unit_cost="140"),
        ],
    )

    entries = StockLedger.objects.filter(source_type=SourceType.PURCHASE, source_id=purchase.pk)
    assert entries.count() == 2
    assert purchase.total_value == Decimal("1150.00")


def test_bad_line_posts_nothing(flour: Item, supplier: Supplier) -> None:
    """PS 5: validation runs before any ledger write, so nothing is left behind."""
    ledger_count = StockLedger.objects.count()

    with pytest.raises(InvalidMovement):
        create_purchase(
            supplier=supplier,
            lines=[
                PurchaseLineInput(item_id=flour.pk, qty="10", unit_cost="45"),
                PurchaseLineInput(item_id=flour.pk, qty="0", unit_cost="45"),
            ],
        )

    assert StockLedger.objects.count() == ledger_count
    assert Purchase.objects.count() == 0
    assert StockBalance.objects.get(item=flour).qty == Decimal("100.000")


def test_purchase_rejects_unknown_item_and_negative_rate(flour: Item, supplier: Supplier) -> None:
    """PS 5 negative paths: unknown items and negative rates are domain errors."""
    with pytest.raises(DomainError, match="Unknown item"):
        create_purchase(
            supplier=supplier,
            lines=[PurchaseLineInput(item_id=999_999, qty="1", unit_cost="1")],
        )

    with pytest.raises(InvalidMovement):
        create_purchase(
            supplier=supplier,
            lines=[PurchaseLineInput(item_id=flour.pk, qty="1", unit_cost="-1")],
        )

    with pytest.raises(InvalidMovement):
        create_purchase(supplier=supplier, lines=[])
