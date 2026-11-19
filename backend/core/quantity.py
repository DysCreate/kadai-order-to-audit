"""Quantity rounding utilities for Kadai.

Rule: ALL stock quantities must be rounded with q3(). Never use round() or float.
"""

from decimal import ROUND_HALF_UP, Decimal


def q3(val: Decimal | str | int) -> Decimal:
    """Round to 3 decimal places (item base unit). Always use this, never round() or float."""
    return Decimal(val).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
