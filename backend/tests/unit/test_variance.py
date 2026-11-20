"""Unit tests for the variance engine (pure function, no database).

Requirement: AGENTS.md Section 4.6 and 5 – the strict-greater-than boundary,
both directions, output yield inversion and the zero-planned case.
"""

from decimal import Decimal

import pytest

from apps.production.variance import compute_variance
from core.errors import DomainError

TOLERANCE = Decimal("0.03")


@pytest.mark.parametrize(
    ("planned", "actual", "expected_pct", "flagged", "direction"),
    [
        # Appendix A lines: 3% tolerance, strictly greater than flags.
        ("200", "194", Decimal("-0.030000"), False, "favourable"),
        ("10", "9", Decimal("-0.100000"), True, "favourable"),
        ("10", "10.5", Decimal("0.050000"), True, "adverse"),
        ("40", "40", Decimal("0.000000"), False, "none"),
        ("1.2", "1.2", Decimal("0.000000"), False, "none"),
    ],
)
def test_usage_variance_flags_only_beyond_tolerance(
    planned: str, actual: str, expected_pct: Decimal, flagged: bool, direction: str
) -> None:
    """PS 4.6 variance flag: pouches at exactly -3% are not flagged."""
    result = compute_variance(planned, actual, TOLERANCE)

    assert result.variance_pct == expected_pct
    assert result.flagged is flagged
    assert result.direction == direction


def test_exactly_at_tolerance_is_not_flagged_but_just_over_is() -> None:
    """PS 4.6 boundary: 3% is quiet, a hair more is flagged."""
    at_limit = compute_variance("100", "103", TOLERANCE)
    over_limit = compute_variance("100", "103.001", TOLERANCE)
    under_limit = compute_variance("100", "97", TOLERANCE)

    assert at_limit.flagged is False
    assert over_limit.flagged is True
    assert under_limit.flagged is False


def test_yield_variance_inverts_direction() -> None:
    """Appendix A: 188 good packets against 200 planned is adverse, not favourable."""
    result = compute_variance("200", "188", TOLERANCE, higher_is_better=True)

    assert result.variance_pct == Decimal("-0.060000")
    assert result.flagged is True
    assert result.direction == "adverse"


def test_output_above_plan_is_favourable() -> None:
    """PS 4.6: producing more than planned is a favourable yield variance."""
    result = compute_variance("200", "210", TOLERANCE, higher_is_better=True)

    assert result.flagged is True
    assert result.direction == "favourable"


def test_zero_planned_with_zero_actual_is_quiet() -> None:
    """PS 4.6: no plan and no usage is not a variance."""
    result = compute_variance("0", "0", TOLERANCE)

    assert result.variance_pct == Decimal("0.000000")
    assert result.flagged is False
    assert result.direction == "none"


def test_zero_planned_with_any_actual_is_flagged_adverse() -> None:
    """PS 4.6: a booked quantity against a zero plan is always flagged."""
    result = compute_variance("0", "0.5", TOLERANCE)

    assert result.variance_pct is None
    assert result.flagged is True
    assert result.direction == "adverse"


def test_float_and_negative_inputs_are_rejected() -> None:
    """PS 1 Decimal only: floats never enter the numbers path."""
    with pytest.raises(DomainError):
        compute_variance(Decimal("1"), 1.5, TOLERANCE)  # type: ignore[arg-type]

    with pytest.raises(DomainError):
        compute_variance("-5", "1", TOLERANCE)

    with pytest.raises(DomainError):
        compute_variance("5", "1", "-0.03")
