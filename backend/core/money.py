"""Money rounding utilities for Kadai.

Rule: ALL money values must be rounded with q2(). Never use round() or float.
"""

from decimal import ROUND_HALF_UP, Decimal


def q2(val: Decimal | str | int) -> Decimal:
    """Round to 2 decimal places (paise). Always use this, never round() or float."""
    return Decimal(val).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
