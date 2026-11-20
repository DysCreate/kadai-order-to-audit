"""Pure unit-conversion maths for Kadai.

The converter is deliberately free of database access so it can be unit tested
and reused by any service. Database-backed conversion factors (global UoM
conversions and item-specific factors such as carton = 20 packets) are loaded
by ``apps.masters.services`` and fed into this class.

Invariants protected:
- Factors are strictly positive Decimals.
- Conversions are exact for 3-decimal quantities when the factor is exact
  (kg <-> g, L <-> mL, carton -> packets).
- An undefined conversion raises ``InvalidUnit``; it never guesses.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

from core.errors import InvalidUnit
from core.quantity import q3

ConversionTable = Mapping[tuple[str, str], Decimal]


class UnitConverter:
    """Convert quantities between units using an injected factor table."""

    def __init__(self, factors: ConversionTable | None = None) -> None:
        self._factors: dict[tuple[str, str], Decimal] = dict(factors or {})

    def add(self, from_uom: str, to_uom: str, factor: Decimal | str | int) -> None:
        """Register a conversion ``1 from_uom = factor to_uom``."""
        if from_uom == to_uom:
            raise InvalidUnit("A unit cannot be converted to itself.")
        try:
            decimal_factor = Decimal(factor)
        except (InvalidOperation, TypeError) as exc:
            raise InvalidUnit(f"Invalid conversion factor {factor!r}.") from exc
        if decimal_factor <= 0:
            raise InvalidUnit("A conversion factor must be greater than zero.")
        self._factors[(from_uom, to_uom)] = decimal_factor

    def convert(
        self,
        qty: Decimal | str | int,
        from_uom: str,
        to_uom: str,
    ) -> Decimal:
        """Convert ``qty`` from one UoM symbol to another.

        The result is rounded to 3 decimals (the quantity precision). Reverse
        conversions are supported when only one direction is registered.
        """
        quantity = q3(qty)
        if from_uom == to_uom:
            return quantity

        direct = self._factors.get((from_uom, to_uom))
        if direct is not None:
            return q3(quantity * direct)

        reverse = self._factors.get((to_uom, from_uom))
        if reverse is not None:
            return q3(quantity / reverse)

        raise InvalidUnit(f"No conversion from {from_uom!r} to {to_uom!r}.")
