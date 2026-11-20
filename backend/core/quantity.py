"""Quantity rounding utilities for Kadai.

Rule: ALL stock quantities must be rounded with q3(). Never use round() or float.
"""

from decimal import ROUND_HALF_UP, Decimal

DecimalInput = Decimal | str | int


def q3(val: DecimalInput) -> Decimal:
    """Round to 3 decimal places (item base unit). Always use this, never round() or float."""
    if isinstance(val, float):
        raise TypeError(
            "float is forbidden in money and stock code; pass Decimal, str or int instead."
        )
    return Decimal(val).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
