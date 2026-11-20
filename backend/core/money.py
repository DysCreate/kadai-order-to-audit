"""Money and rate rounding utilities for Kadai.

Rule: ALL money values must be rounded with q2() and rates with q4().
Never use round() or float.
"""

from decimal import ROUND_HALF_UP, Decimal

DecimalInput = Decimal | str | int


def _reject_float(val: object) -> None:
    if isinstance(val, float):
        raise TypeError(
            "float is forbidden in money and stock code; pass Decimal, str or int instead."
        )


def q2(val: DecimalInput) -> Decimal:
    """Round to 2 decimal places (paise). Always use this, never round() or float."""
    _reject_float(val)
    return Decimal(val).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def q4(val: DecimalInput) -> Decimal:
    """Round to 4 decimal places (unit rates). Always use this, never round() or float."""
    _reject_float(val)
    return Decimal(val).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
