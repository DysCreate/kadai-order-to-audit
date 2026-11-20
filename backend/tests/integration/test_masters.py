"""Masters integration tests: units, conversions, items, price lists, settings.

Requirement: Phase 1 masters, units and settings (AGENTS.md Section 4.15 for
idempotent seed data; Section 8 for settings-driven constants).
"""

from decimal import Decimal

import pytest

from apps.masters.services import (
    add_item_conversion,
    add_uom_conversion,
    convert_quantity,
    create_customer,
    create_item,
    create_price_list,
    create_uom,
    ensure_default_settings,
    get_decimal_setting,
    get_setting,
    resolve_price,
    set_price,
    set_setting,
)
from core.errors import DomainError, InvalidUnit, PriceNotFound


@pytest.fixture
def units(db: None) -> None:
    create_uom(name="Kilogram", symbol="kg")
    create_uom(name="Gram", symbol="g")
    create_uom(name="Litre", symbol="L")
    create_uom(name="Packet", symbol="pkt")
    create_uom(name="Carton", symbol="ctn")


def test_global_and_reverse_conversion(units: None) -> None:
    """PS 1 units: kg -> g and g -> kg convert exactly."""
    add_uom_conversion(from_symbol="kg", to_symbol="g", factor=Decimal("1000"))

    assert convert_quantity(item=None, qty="1.234", from_symbol="kg", to_symbol="g") == Decimal(
        "1234.000"
    )
    assert convert_quantity(item=None, qty="1234", from_symbol="g", to_symbol="kg") == Decimal(
        "1.234"
    )


def test_item_specific_carton_conversion(units: None) -> None:
    """PS 1 units: a carton is 20 packets for the finished-goods item."""
    item = create_item(name="Murukku 200 g", item_type="FG", uom_symbol="pkt")
    add_item_conversion(item=item, uom_symbol="ctn", factor=Decimal("20"))

    assert convert_quantity(item=item, qty="7.5", from_symbol="ctn", to_symbol="pkt") == Decimal(
        "150.000"
    )
    assert convert_quantity(item=item, qty="150", from_symbol="pkt", to_symbol="ctn") == Decimal(
        "7.500"
    )


def test_undefined_conversion_raises(units: None) -> None:
    """PS 1 negative path: an undefined unit conversion is a domain error."""
    with pytest.raises(InvalidUnit):
        convert_quantity(item=None, qty="1", from_symbol="kg", to_symbol="L")


def test_conversion_factor_validation(units: None) -> None:
    """PS 1 negative path: bad conversion factors are refused."""
    with pytest.raises(InvalidUnit):
        add_uom_conversion(from_symbol="kg", to_symbol="kg", factor="1000")
    with pytest.raises(InvalidUnit):
        add_uom_conversion(from_symbol="kg", to_symbol="g", factor="not-a-number")
    with pytest.raises(InvalidUnit):
        add_uom_conversion(from_symbol="kg", to_symbol="g", factor="0")

    item = create_item(name="Murukku 200 g", item_type="FG", uom_symbol="pkt")
    with pytest.raises(InvalidUnit):
        add_item_conversion(item=item, uom_symbol="pkt", factor="20")
    with pytest.raises(InvalidUnit):
        add_item_conversion(item=item, uom_symbol="ctn", factor="bad")
    with pytest.raises(InvalidUnit):
        add_item_conversion(item=item, uom_symbol="ctn", factor="-1")

    assert convert_quantity(item=item, qty="1.234", from_symbol="pkt", to_symbol="pkt") == Decimal(
        "1.234"
    )


def test_invalid_uom_and_negative_gst_are_rejected(units: None) -> None:
    """PS 1 negative path: invalid unit, type and negative GST are refused."""
    with pytest.raises(InvalidUnit):
        create_item(name="Mystery", item_type="RAW", uom_symbol="tonne")
    with pytest.raises(DomainError):
        create_item(name="Bad GST", item_type="RAW", uom_symbol="kg", gst_rate="-1")
    with pytest.raises(DomainError):
        create_item(name="Bad type", item_type="BOGUS", uom_symbol="kg")


def test_price_resolution_prefers_customer_list_then_default(units: None) -> None:
    """PS 1 price list: customer list wins; otherwise the default list is used."""
    item = create_item(name="Murukku 200 g", item_type="FG", uom_symbol="pkt")
    default_list = create_price_list(name="Standard", is_default=True)
    special_list = create_price_list(name="Retailer A special")
    set_price(price_list=default_list, item=item, price="50")
    set_price(price_list=special_list, item=item, price="48.50")

    customer = create_customer(
        name="Retailer A",
        state_code="33",
        price_list=special_list,
    )
    unlisted = create_customer(name="Walk-in", state_code="33")

    assert resolve_price(item=item, customer=customer) == Decimal("48.50")
    assert resolve_price(item=item, customer=unlisted) == Decimal("50.00")
    assert resolve_price(item=item) == Decimal("50.00")


def test_price_not_found_is_explicit(units: None) -> None:
    """PS 1 price list: a missing price never silently becomes zero."""
    item = create_item(name="Murukku 200 g", item_type="FG", uom_symbol="pkt")
    create_price_list(name="Standard", is_default=True)

    with pytest.raises(PriceNotFound):
        resolve_price(item=item)


def test_customer_state_code_is_validated(units: None) -> None:
    """PS 8.8: the state code drives GST and must be two digits."""
    with pytest.raises(DomainError):
        create_customer(name="Bad State", state_code="TN")
    with pytest.raises(DomainError):
        create_customer(name="Bad Type", state_code="33", customer_type="bogus")


def test_price_must_be_non_negative(units: None) -> None:
    """PS 1 price list: a negative price is refused."""
    item = create_item(name="Murukku 200 g", item_type="FG", uom_symbol="pkt")
    price_list = create_price_list(name="Standard", is_default=True)
    with pytest.raises(DomainError):
        set_price(price_list=price_list, item=item, price="-1")


def test_only_one_default_price_list(units: None) -> None:
    """PS 1 price list: promoting a list to default clears the previous one."""
    first = create_price_list(name="First", is_default=True)
    create_price_list(name="Second")
    second = create_price_list(name="Second", is_default=True)

    first.refresh_from_db()
    assert first.is_default is False
    assert second.is_default is True


def test_settings_defaults_and_overrides(db: None) -> None:
    """PS 8: tolerance and factory state come from settings, not magic numbers."""
    ensure_default_settings()
    assert get_decimal_setting("variance_tolerance") == Decimal("0.03")
    assert get_setting("factory_state_code") == "33"

    set_setting(key="variance_tolerance", value="0.05")
    assert get_decimal_setting("variance_tolerance") == Decimal("0.05")

    assert get_setting("missing_key") is None
    assert get_decimal_setting("missing_key", Decimal("0.03")) == Decimal("0.03")
    with pytest.raises(DomainError):
        get_decimal_setting("missing_key")


def test_invalid_decimal_setting_raises(db: None) -> None:
    """PS 8: a corrupt setting is a domain error, never a silent zero."""
    set_setting(key="variance_tolerance", value="three percent")
    with pytest.raises(DomainError):
        get_decimal_setting("variance_tolerance")
