"""Pure variance maths for production runs.

The engine is deliberately free of database access so every rule is unit
tested directly (AGENTS.md Section 5).

Invariants protected:
- ``variance_pct = (actual - planned) / planned`` and a line is flagged only
  when ``abs(variance_pct) > tolerance``: the boundary itself is not flagged
  (pouches at exactly -3% must stay quiet).
- Direction is reported for every deviation, flagged or not: using more input
  than planned is adverse, while producing less output than planned is adverse
  (``higher_is_better`` marks output lines).
- A zero planned quantity cannot be expressed as a percentage. Any non-zero
  actual is then flagged as adverse with ``variance_pct = None`` rather than
  inventing a number.
- Floats are rejected; comparisons stay in Decimal.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from core.errors import DomainError
from core.quantity import q3

FAVOURABLE = "favourable"
ADVERSE = "adverse"
NONE = "none"

_SIX_PLACES = Decimal("0.000001")


@dataclass(frozen=True)
class VarianceResult:
    """The outcome of comparing one actual quantity with its plan."""

    planned: Decimal
    actual: Decimal
    variance_pct: Decimal | None
    flagged: bool
    direction: str


def compute_variance(
    planned: Decimal | str | int,
    actual: Decimal | str | int,
    tolerance: Decimal | str | int,
    *,
    higher_is_better: bool = False,
) -> VarianceResult:
    """Compare ``actual`` with ``planned`` and report the variance.

    Args:
        planned: The planned quantity (BOM quantity x batches, or expected output).
        actual: The recorded quantity.
        tolerance: Fractional tolerance from settings (0.03 for 3%).
        higher_is_better: True for output lines (more is better), False for
            input usage lines (less is better).

    Raises:
        DomainError: negative quantity or tolerance, or a float input.
    """
    planned_qty = _quantity(planned, "planned")
    actual_qty = _quantity(actual, "actual")
    limit = _tolerance(tolerance)

    if planned_qty == 0:
        if actual_qty == 0:
            return VarianceResult(planned_qty, actual_qty, Decimal("0.000000"), False, NONE)
        return VarianceResult(planned_qty, actual_qty, None, True, ADVERSE)

    variance = (actual_qty - planned_qty) / planned_qty
    flagged = abs(variance) > limit
    if actual_qty == planned_qty:
        direction = NONE
    else:
        moving_up = actual_qty > planned_qty
        direction = ADVERSE if moving_up != higher_is_better else FAVOURABLE

    return VarianceResult(
        planned=planned_qty,
        actual=actual_qty,
        variance_pct=variance.quantize(_SIX_PLACES, rounding=ROUND_HALF_UP),
        flagged=flagged,
        direction=direction,
    )


def _quantity(value: Decimal | str | int, field: str) -> Decimal:
    if isinstance(value, float):
        raise DomainError(f"{field} must be Decimal, str or int, never float.")
    try:
        quantity = q3(value)
    except (ArithmeticError, TypeError, ValueError) as exc:
        raise DomainError(f"{field} is not a valid decimal: {value!r}.") from exc
    if quantity < 0:
        raise DomainError(f"{field} cannot be negative.")
    return quantity


def _tolerance(value: Decimal | str | int) -> Decimal:
    if isinstance(value, float):
        raise DomainError("tolerance must be Decimal, str or int, never float.")
    try:
        limit = Decimal(value)
    except (ArithmeticError, TypeError, ValueError) as exc:
        raise DomainError(f"tolerance is not a valid decimal: {value!r}.") from exc
    if limit < 0:
        raise DomainError("tolerance cannot be negative.")
    return limit
