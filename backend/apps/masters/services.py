"""Masters services – all writes to master data go through here.

Invariants protected:
- Units, conversion factors and prices are positive Decimals (never float).
- Global conversions are unique per (from, to); item conversions per (item, uom).
- Prices resolve customer price list -> default price list, never silently.
- Business constants (tolerance, factory state) live in the Setting table.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.db import transaction

from apps.accounts.models import User
from core.errors import DomainError, InvalidUnit, PriceNotFound
from core.money import q2
from core.quantity import q3
from core.units import UnitConverter

from .models import (
    Customer,
    CustomerType,
    Item,
    ItemType,
    ItemUoMConversion,
    PriceList,
    PriceListLine,
    Setting,
    Supplier,
    UoM,
    UoMConversion,
)

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

DEFAULT_SETTINGS: dict[str, tuple[str, str]] = {
    "factory_name": ("Kadai Snacks", "Factory display name used on invoices."),
    "factory_state_code": ("33", "Factory GST state code (Tamil Nadu = 33)."),
    "factory_gstin": ("33AABCK1234K1Z5", "Factory GSTIN printed on invoices."),
    "factory_address": ("Trichy, Tamil Nadu", "Factory address printed on invoices."),
    "variance_tolerance": ("0.03", "Variance flag threshold as a fraction (3%)."),
    "currency": ("INR", "Display currency code."),
}


@transaction.atomic
def set_setting(*, key: str, value: str, description: str = "") -> Setting:
    """Create or update one setting.

    Invariant: ``key`` is the unique natural key; the latest write wins and is
    visible to every subsequent calculation.
    """
    setting, _created = Setting.objects.update_or_create(
        key=key,
        defaults={"value": value, "description": description},
    )
    return setting


def get_setting(key: str, default: str | None = None) -> str | None:
    """Return a setting value or ``default`` when the key is absent."""
    setting = Setting.objects.filter(key=key).first()
    if setting is None:
        return default
    return str(setting.value)


def get_decimal_setting(key: str, default: Decimal | None = None) -> Decimal:
    """Return a setting parsed as Decimal, falling back to ``default``.

    Raises DomainError if the stored value is not a valid Decimal; a corrupt
    setting must never be silently ignored in a numbers path.
    """
    raw = get_setting(key)
    if raw is None:
        if default is None:
            raise DomainError(f"Setting {key!r} is not configured.")
        return default
    try:
        return Decimal(raw)
    except (InvalidOperation, TypeError) as exc:
        raise DomainError(f"Setting {key!r} is not a valid decimal: {raw!r}.") from exc


@transaction.atomic
def ensure_default_settings() -> None:
    """Load the default settings without overwriting values already set."""
    for key, (value, description) in DEFAULT_SETTINGS.items():
        Setting.objects.get_or_create(
            key=key,
            defaults={"value": value, "description": description},
        )


# ---------------------------------------------------------------------------
# Units and conversions
# ---------------------------------------------------------------------------


def get_uom(symbol: str) -> UoM:
    """Return the UoM with ``symbol`` or raise InvalidUnit."""
    try:
        return UoM.objects.get(symbol=symbol)
    except UoM.DoesNotExist as exc:
        raise InvalidUnit(f"Unknown unit of measure {symbol!r}.") from exc


@transaction.atomic
def create_uom(*, name: str, symbol: str) -> UoM:
    """Create (or return) a unit of measure by unique symbol."""
    uom, _created = UoM.objects.get_or_create(symbol=symbol, defaults={"name": name})
    return uom


@transaction.atomic
def add_uom_conversion(
    *,
    from_symbol: str,
    to_symbol: str,
    factor: Decimal | str | int,
) -> UoMConversion:
    """Register a global conversion ``1 from_symbol = factor to_symbol``.

    Invariants: the two units differ and the factor is strictly positive.
    """
    from_uom = get_uom(from_symbol)
    to_uom = get_uom(to_symbol)
    if from_uom.pk == to_uom.pk:
        raise InvalidUnit("A unit cannot be converted to itself.")

    try:
        decimal_factor = Decimal(factor)
    except (InvalidOperation, TypeError) as exc:
        raise InvalidUnit(f"Invalid conversion factor {factor!r}.") from exc
    if decimal_factor <= 0:
        raise InvalidUnit("A conversion factor must be greater than zero.")

    conversion, _created = UoMConversion.objects.update_or_create(
        from_uom=from_uom,
        to_uom=to_uom,
        defaults={"factor": decimal_factor},
    )
    return conversion


@transaction.atomic
def add_item_conversion(
    *,
    item: Item,
    uom_symbol: str,
    factor: Decimal | str | int,
) -> ItemUoMConversion:
    """Register an item-specific conversion ``1 uom = factor item.uom``.

    Example: carton -> packets for one finished-goods item.
    """
    uom = get_uom(uom_symbol)
    if uom.pk == item.uom_id:
        raise InvalidUnit("An item conversion must use a unit other than the base unit.")

    try:
        decimal_factor = Decimal(factor)
    except (InvalidOperation, TypeError) as exc:
        raise InvalidUnit(f"Invalid conversion factor {factor!r}.") from exc
    if decimal_factor <= 0:
        raise InvalidUnit("A conversion factor must be greater than zero.")

    conversion, _created = ItemUoMConversion.objects.update_or_create(
        item=item,
        uom=uom,
        defaults={"factor": decimal_factor},
    )
    return conversion


def convert_quantity(
    *,
    item: Item | None,
    qty: Decimal | str | int,
    from_symbol: str,
    to_symbol: str,
) -> Decimal:
    """Convert ``qty`` between units, using item conversions before global ones.

    Invariants: the result is rounded once to 3 decimals; an undefined
    conversion raises InvalidUnit instead of guessing.
    """
    quantity = q3(qty)
    if from_symbol == to_symbol:
        return quantity

    if item is not None:
        base_symbol = item.uom.symbol
        item_factors = {
            conversion.uom.symbol: conversion.factor
            for conversion in item.uom_conversions.select_related("uom")
        }

        def to_base(value: Decimal, symbol: str) -> Decimal | None:
            if symbol == base_symbol:
                return value
            factor = item_factors.get(symbol)
            return None if factor is None else q3(value * factor)

        def from_base(value: Decimal, symbol: str) -> Decimal | None:
            if symbol == base_symbol:
                return value
            factor = item_factors.get(symbol)
            return None if factor is None else q3(value / factor)

        in_base = to_base(quantity, from_symbol)
        if in_base is not None:
            converted = from_base(in_base, to_symbol)
            if converted is not None:
                return converted

    factors: dict[tuple[str, str], Decimal] = {
        (conversion.from_uom.symbol, conversion.to_uom.symbol): conversion.factor
        for conversion in UoMConversion.objects.select_related("from_uom", "to_uom")
    }
    return UnitConverter(factors).convert(quantity, from_symbol, to_symbol)


# ---------------------------------------------------------------------------
# Items, suppliers, customers
# ---------------------------------------------------------------------------


@transaction.atomic
def set_item_standard_batch_hours(*, item: Item, hours: Decimal | str | int) -> Item:
    """Set a finished good's standard batch-hours for overhead allocation.

    Invariant: the value is a positive Decimal rounded to three places; the
    product's existing runs are unaffected because allocation uses the value
    at allocation time.
    """
    value = q3(hours)
    if value <= 0:
        raise DomainError("Standard batch-hours must be greater than zero.")
    item.standard_batch_hours = value
    item.save(update_fields=["standard_batch_hours"])
    return item


@transaction.atomic
def create_item(
    *,
    name: str,
    item_type: str,
    uom_symbol: str,
    hsn_code: str = "",
    gst_rate: Decimal | str | int = Decimal("0.00"),
    reorder_level: Decimal | str | int = Decimal("0.000"),
) -> Item:
    """Create (or return) an item by unique name.

    Invariants: item type is a valid choice, the base UoM exists, GST rate and
    reorder level are non-negative Decimals. Seeding is idempotent and never
    clobbers a reorder level an operator has already set (a level is only
    filled in when the item still has its default zero).
    """
    if item_type not in ItemType.values:
        raise DomainError(f"Invalid item type {item_type!r}.")
    uom = get_uom(uom_symbol)
    rate = Decimal(gst_rate)
    if rate < 0:
        raise DomainError("GST rate cannot be negative.")
    level = q3(reorder_level)
    if level < 0:
        raise DomainError("A reorder level cannot be negative.")

    item, created = Item.objects.get_or_create(
        name=name,
        defaults={
            "item_type": item_type,
            "uom": uom,
            "hsn_code": hsn_code,
            "gst_rate": q2(rate),
            "reorder_level": level,
        },
    )
    if not created and item.reorder_level == 0 and level > 0:
        item.reorder_level = level
        item.save(update_fields=["reorder_level"])
    return item


@transaction.atomic
def create_supplier(*, name: str, gstin: str = "", state_code: str = "33") -> Supplier:
    """Create (or return) a supplier by unique name."""
    supplier, _created = Supplier.objects.get_or_create(
        name=name,
        defaults={"gstin": gstin, "state_code": state_code},
    )
    return supplier


@transaction.atomic
def create_customer(
    *,
    name: str,
    state_code: str,
    customer_type: str = "retailer",
    gstin: str = "",
    assigned_salesman: User | None = None,
    price_list: PriceList | None = None,
) -> Customer:
    """Create (or return) a customer by unique name.

    Invariants: state code is two digits (drives place of supply) and customer
    type is a valid choice.
    """
    if len(state_code) != 2 or not state_code.isdigit():
        raise DomainError("A customer state code must be two digits, e.g. '33'.")

    if customer_type not in CustomerType.values:
        raise DomainError(f"Invalid customer type {customer_type!r}.")

    customer, created = Customer.objects.get_or_create(
        name=name,
        defaults={
            "state_code": state_code,
            "customer_type": customer_type,
            "gstin": gstin,
            "assigned_salesman": assigned_salesman,
            "price_list": price_list,
        },
    )
    if created and assigned_salesman is not None:
        assigned_salesman.assigned_customers.add(customer)
    return customer


# ---------------------------------------------------------------------------
# Price lists
# ---------------------------------------------------------------------------


@transaction.atomic
def create_price_list(*, name: str, is_default: bool = False) -> PriceList:
    """Create (or return) a price list; making one default unsets the others."""
    price_list, _created = PriceList.objects.get_or_create(
        name=name,
        defaults={"is_default": is_default},
    )
    if is_default:
        PriceList.objects.exclude(pk=price_list.pk).update(is_default=False)
        if not price_list.is_default:
            price_list.is_default = True
            price_list.save(update_fields=["is_default"])
    return price_list


@transaction.atomic
def set_price(
    *,
    price_list: PriceList,
    item: Item,
    price: Decimal | str | int,
) -> PriceListLine:
    """Set the pre-tax selling price of ``item`` on ``price_list``.

    Invariant: prices are non-negative and rounded to paise.
    """
    amount = q2(price)
    if amount < 0:
        raise DomainError("A selling price cannot be negative.")
    line, _created = PriceListLine.objects.update_or_create(
        price_list=price_list,
        item=item,
        defaults={"price": amount},
    )
    return line


def resolve_price(*, item: Item, customer: Customer | None = None) -> Decimal:
    """Return the pre-tax selling price: customer price list, then default.

    Raises PriceNotFound when neither list carries the item; callers must not
    invent a price.
    """
    if customer is not None and customer.price_list_id is not None:
        assert customer.price_list is not None
        line = PriceListLine.objects.filter(
            price_list=customer.price_list,
            item=item,
        ).first()
        if line is not None:
            return q2(line.price)

    default_list = PriceList.objects.filter(is_default=True).order_by("pk").first()
    if default_list is not None:
        line = PriceListLine.objects.filter(price_list=default_list, item=item).first()
        if line is not None:
            return q2(line.price)

    raise PriceNotFound(f"No price configured for item {item.name!r}.")
