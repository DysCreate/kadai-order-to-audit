"""Unit tests for pure costing maths.

Requirement: Phase 4 – overhead allocation preserves every paisa and cost per
packet / margin reproduce the Appendix A values without touching the database.
"""

from decimal import Decimal

import pytest

from apps.costing.allocation import allocate_amount
from apps.costing.calculations import packet_cost
from core.errors import DomainError


def test_allocate_amount_splits_by_weight() -> None:
    """Phase 4: a 1,000 pool over weights 2 and 1 is 666.67 / 333.33."""
    shares = allocate_amount("1000", [(10, "2"), (20, "1")])

    assert [(share.key, share.amount) for share in shares] == [
        (10, Decimal("666.67")),
        (20, Decimal("333.33")),
    ]
    assert sum((share.amount for share in shares), Decimal("0")) == Decimal("1000.00")


def test_allocate_amount_distributes_rounding_remainder_exactly() -> None:
    """Phase 4: 100 over three equal runs becomes 33.34 / 33.33 / 33.33."""
    shares = allocate_amount("100", [(1, "1"), (2, "1"), (3, "1")])

    assert [share.amount for share in shares] == [
        Decimal("33.34"),
        Decimal("33.33"),
        Decimal("33.33"),
    ]
    assert sum((share.amount for share in shares), Decimal("0")) == Decimal("100.00")


def test_allocate_amount_omits_zero_weights_and_zero_shares() -> None:
    """Phase 4: runs with no batch-hours do not receive a share."""
    shares = allocate_amount("10", [(1, "1"), (2, "0"), (3, "1")])

    assert [(share.key, share.amount) for share in shares] == [
        (1, Decimal("5.00")),
        (3, Decimal("5.00")),
    ]


@pytest.mark.parametrize(
    "total,weights",
    [
        ("0", [(1, "1")]),
        ("-1", [(1, "1")]),
        ("10", [(1, "0")]),
        ("10", [(1, "-1")]),
        ("10", [(1, 1.5)]),
    ],
)
def test_allocate_amount_rejects_invalid_inputs(
    total: str, weights: list[tuple[int, object]]
) -> None:
    """Phase 4: pools, weights and float inputs are validated."""
    with pytest.raises((DomainError, TypeError)):
        allocate_amount(total, weights)  # type: ignore[arg-type]


def test_packet_cost_matches_appendix_a() -> None:
    """PS Appendix A step 8: 5,855 / 188 = 31.14, margin 18.86 at 37.72%."""
    result = packet_cost(total_cost="5855", good_packets="188", selling_price="50")

    assert result.cost_per_packet == Decimal("31.14")
    assert result.margin_per_packet == Decimal("18.86")
    assert result.margin_pct == Decimal("37.72")


def test_packet_cost_without_a_price_leaves_margin_empty() -> None:
    """Phase 4: a missing price does not invent a margin."""
    result = packet_cost(total_cost="100", good_packets="10")

    assert result.cost_per_packet == Decimal("10.00")
    assert result.selling_price is None
    assert result.margin_per_packet is None
    assert result.margin_pct is None


def test_packet_cost_rejects_zero_good_packets() -> None:
    """Phase 4: cost per packet cannot divide by zero output."""
    with pytest.raises(DomainError):
        packet_cost(total_cost="100", good_packets="0", selling_price="50")


def test_packet_cost_with_zero_price_has_no_percentage() -> None:
    """Phase 4: a zero selling price leaves the margin percentage undefined."""
    result = packet_cost(total_cost="100", good_packets="10", selling_price="0")

    assert result.margin_per_packet == Decimal("-10.00")
    assert result.margin_pct is None
