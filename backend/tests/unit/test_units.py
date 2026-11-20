"""Unit conversion tests.

Requirement: Phase 1 masters/units – conversions are exact for 3-decimal
quantities and an undefined conversion never guesses.
"""

from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from core.errors import InvalidUnit
from core.units import UnitConverter


def test_global_conversion_kg_to_g_and_back() -> None:
    """kg <-> g conversions are exact for 3-decimal quantities."""
    converter = UnitConverter({("kg", "g"): Decimal("1000")})
    assert converter.convert("40.125", "kg", "g") == Decimal("40125.000")
    assert converter.convert("40125", "g", "kg") == Decimal("40.125")


def test_item_conversion_carton_to_packets() -> None:
    """A carton of Murukku is 20 packets (item-specific factor)."""
    converter = UnitConverter({("ctn", "pkt"): Decimal("20")})
    assert converter.convert("7.5", "ctn", "pkt") == Decimal("150.000")
    assert converter.convert("150", "pkt", "ctn") == Decimal("7.500")


def test_same_unit_is_identity() -> None:
    """Converting a unit to itself returns the quantity unchanged."""
    converter = UnitConverter()
    assert converter.convert("1.234", "kg", "kg") == Decimal("1.234")


def test_undefined_conversion_raises_invalid_unit() -> None:
    """An undefined conversion raises InvalidUnit instead of guessing."""
    converter = UnitConverter({("kg", "g"): Decimal("1000")})
    with pytest.raises(InvalidUnit):
        converter.convert("1", "kg", "L")


def test_invalid_factor_is_rejected() -> None:
    """Conversion factors must be strictly positive and units must differ."""
    converter = UnitConverter()
    with pytest.raises(InvalidUnit):
        converter.add("kg", "kg", Decimal("1"))
    with pytest.raises(InvalidUnit):
        converter.add("kg", "g", Decimal("0"))
    with pytest.raises(InvalidUnit):
        converter.add("kg", "g", Decimal("-2"))
    with pytest.raises(InvalidUnit):
        converter.add("kg", "g", "not-a-number")


def test_added_factor_is_used_by_convert() -> None:
    """Registering a factor makes it immediately convertible in both directions."""
    converter = UnitConverter()
    converter.add("L", "mL", Decimal("1000"))
    assert converter.convert("1.5", "L", "mL") == Decimal("1500.000")
    assert converter.convert("1500", "mL", "L") == Decimal("1.500")


@settings(max_examples=50, deadline=None)
@given(qty=st.decimals(min_value=Decimal("0"), max_value=Decimal("100000"), places=3))
def test_round_trip_is_exact_for_three_decimals(qty: Decimal) -> None:
    """PS 1 unit conversion: kg -> g -> kg round trips exactly at 3 dp."""
    converter = UnitConverter({("kg", "g"): Decimal("1000")})
    grams = converter.convert(qty, "kg", "g")
    assert converter.convert(grams, "g", "kg") == qty
