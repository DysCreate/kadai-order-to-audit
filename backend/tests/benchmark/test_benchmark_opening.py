"""Benchmark ground truth for Phase 1: opening stock from Appendix A.

Requirement: Phase 1 exit gate – the stock summary shows the Appendix A
opening balances exactly. Values are never edited to make a test pass.
"""

from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command

from apps.inventory.models import MovementType, SourceType, StockLedger
from apps.inventory.services import stock_summary

EXPECTED_OPENING = {
    "Flour": ("kg", Decimal("100.000"), Decimal("42.0000"), Decimal("4200.00")),
    "Cooking oil": ("L", Decimal("30.000"), Decimal("140.0000"), Decimal("4200.00")),
    "Salt and spice mix": ("kg", Decimal("5.000"), Decimal("200.0000"), Decimal("1000.00")),
    "200 g pouch": ("pc", Decimal("500.000"), Decimal("2.5000"), Decimal("1250.00")),
    "Carton (holds 20 packets)": ("pc", Decimal("30.000"), Decimal("15.0000"), Decimal("450.00")),
    "Murukku 200 g": ("pkt", Decimal("50.000"), Decimal("19.8500"), Decimal("992.50")),
}


@pytest.mark.django_db
def test_seeded_opening_stock_matches_appendix_a() -> None:
    """PS Appendix A: opening quantities, rates and values are exact."""
    call_command("seed_benchmark", stdout=StringIO())

    rows = {row.item.name: row for row in stock_summary()}
    assert set(rows) == set(EXPECTED_OPENING)

    for name, (uom, qty, rate, value) in EXPECTED_OPENING.items():
        row = rows[name]
        assert row.item.uom.symbol == uom, name
        assert row.qty == qty, name
        assert row.avg_rate == rate, name
        assert row.value == value, name

    opening_entries = StockLedger.objects.filter(movement_type=MovementType.OPENING)
    assert opening_entries.count() == len(EXPECTED_OPENING)
    assert all(entry.source_type == SourceType.OPENING for entry in opening_entries)
    assert all(entry.source_id == entry.item_id for entry in opening_entries)

    total_value = sum((row.value for row in rows.values()), Decimal("0.00"))
    assert total_value == Decimal("12092.50")
