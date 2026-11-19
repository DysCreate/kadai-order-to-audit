"""Unit conversion utilities for Kadai."""

from decimal import Decimal


class UnitConverter:
    """Convert quantities between units of measure.

    Conversion factors are loaded from the masters.UoM table at runtime.
    """

    def convert(self, qty: Decimal, from_uom: str, to_uom: str) -> Decimal:
        """Convert qty from from_uom to to_uom.

        Raises InvalidUnit if the conversion is not defined.
        """
        # TODO: implement using masters.UoM conversion table
        raise NotImplementedError("UnitConverter.convert is not yet implemented")
