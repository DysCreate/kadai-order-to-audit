"""Valuation tests for the moving weighted average strategy.

Requirement: AGENTS.md Section 4.5 – issue value = q2(issue_qty * value / qty)
and issuing all remaining quantity leaves value exactly zero.
"""

from decimal import Decimal

import pytest

from apps.inventory.valuation import MovingWeightedAverage
from core.errors import InsufficientStock

VALUATION = MovingWeightedAverage()


def test_receipt_value_is_rounded_half_up_to_paise() -> None:
    """Receipt value uses q2, not float arithmetic."""
    assert VALUATION.receipt_value(Decimal("3"), Decimal("1.005")) == Decimal("3.02")


def test_issue_value_matches_benchmark_flour() -> None:
    """Appendix A: 160 kg worth 6,900 issues 40 kg for 1,725.00."""
    assert VALUATION.issue_value(Decimal("40"), Decimal("160"), Decimal("6900.00")) == Decimal(
        "1725.00"
    )


def test_issue_value_matches_benchmark_packaging() -> None:
    """Appendix A: 194 pouches at 2.50 cost 485.00."""
    assert VALUATION.issue_value(Decimal("194"), Decimal("500"), Decimal("1250.00")) == Decimal(
        "485.00"
    )


def test_issuing_all_quantity_takes_all_remaining_value() -> None:
    """Remainder rule: value never drifts when a balance is emptied."""
    first = VALUATION.issue_value(Decimal("2"), Decimal("3"), Decimal("100.00"))
    assert first == Decimal("66.67")
    remaining_value = Decimal("100.00") - first
    final = VALUATION.issue_value(Decimal("1"), Decimal("1"), remaining_value)
    assert final == Decimal("33.33")
    assert first + final == Decimal("100.00")


def test_issue_beyond_balance_raises_insufficient_stock() -> None:
    """The valuation layer refuses to value stock that does not exist."""
    with pytest.raises(InsufficientStock):
        VALUATION.issue_value(Decimal("5"), Decimal("4"), Decimal("40.00"))


def test_zero_or_negative_issue_is_rejected() -> None:
    """An issue must be strictly positive."""
    with pytest.raises(InsufficientStock):
        VALUATION.issue_value(Decimal("0"), Decimal("10"), Decimal("100.00"))
    with pytest.raises(InsufficientStock):
        VALUATION.issue_value(Decimal("-1"), Decimal("10"), Decimal("100.00"))
