"""Unit tests for the Leakage Radar report card and drift rule.

Requirement: implementation plan Section 2.1 – standard versus actual per input,
the price/usage split, the per-packet bridge and the unexplained yield gap must
reproduce Appendix A exactly. Pure functions, no database.
"""

from decimal import Decimal

import pytest

from apps.production.leakage import (
    ReportCardLineInput,
    VariancePoint,
    build_report_card,
    detect_drift,
)
from core.errors import DomainError

TOLERANCE = Decimal("0.03")


def _benchmark_lines() -> list[ReportCardLineInput]:
    return [
        ReportCardLineInput(
            item_id=1,
            item_name="Flour",
            role="material",
            planned_qty=Decimal("40"),
            actual_qty=Decimal("40"),
            actual_value=Decimal("1725.00"),
            standard_rate=Decimal("42"),
        ),
        ReportCardLineInput(
            item_id=2,
            item_name="Cooking oil",
            role="material",
            planned_qty=Decimal("10"),
            actual_qty=Decimal("10.5"),
            actual_value=Decimal("1470.00"),
            standard_rate=Decimal("140"),
        ),
        ReportCardLineInput(
            item_id=3,
            item_name="Salt and spice mix",
            role="material",
            planned_qty=Decimal("1.2"),
            actual_qty=Decimal("1.2"),
            actual_value=Decimal("240.00"),
            standard_rate=Decimal("200"),
        ),
        ReportCardLineInput(
            item_id=4,
            item_name="200 g pouch",
            role="pouch",
            planned_qty=Decimal("200"),
            actual_qty=Decimal("194"),
            actual_value=Decimal("485.00"),
            standard_rate=Decimal("2.50"),
        ),
        ReportCardLineInput(
            item_id=5,
            item_name="Carton (holds 20 packets)",
            role="carton",
            planned_qty=Decimal("10"),
            actual_qty=Decimal("9"),
            actual_value=Decimal("135.00"),
            standard_rate=Decimal("15"),
        ),
    ]


def _benchmark_card():
    return build_report_card(
        lines=_benchmark_lines(),
        planned_output="200",
        good_packets="188",
        damaged_pouches="6",
        overhead_value="1800",
        selling_price="50",
    )


def test_report_card_reproduces_appendix_a() -> None:
    """PS 2.1: every line, total, bridge and yield-gap value from Appendix A."""
    card = _benchmark_card()

    lines = {line.item_name: line for line in card.lines}
    assert lines["Flour"].standard_value == Decimal("1680.00")
    assert lines["Flour"].actual_value == Decimal("1725.00")
    assert lines["Flour"].price_impact == Decimal("45.00")
    assert lines["Flour"].usage_impact == Decimal("0.00")

    assert lines["Cooking oil"].usage_impact == Decimal("70.00")
    assert lines["Cooking oil"].price_impact == Decimal("0.00")

    assert lines["Salt and spice mix"].total_impact == Decimal("0.00")
    assert lines["200 g pouch"].usage_impact == Decimal("-15.00")
    assert lines["Carton (holds 20 packets)"].usage_impact == Decimal("-15.00")

    assert card.standard_materials == Decimal("3970.00")
    assert card.actual_materials == Decimal("4055.00")
    assert card.material_impact == Decimal("85.00")
    assert card.price_impact == Decimal("45.00")
    assert card.usage_impact == Decimal("40.00")

    assert card.standard_per_packet == Decimal("19.85")
    assert card.actual_material_per_packet == Decimal("21.57")
    assert card.overhead_per_packet == Decimal("9.57")
    assert card.cost_per_packet == Decimal("31.14")
    assert card.selling_price == Decimal("50.00")
    assert card.margin_per_packet == Decimal("18.86")
    assert card.margin_pct == Decimal("37.72")

    bridge = {step.key: step.amount for step in card.bridge}
    assert bridge["standard_material"] == Decimal("19.85")
    assert bridge["yield_shortfall"] == Decimal("1.27")
    assert bridge["price_usage"] == Decimal("0.45")
    assert bridge["overhead"] == Decimal("9.57")
    assert card.bridge[-1].cumulative == Decimal("31.14")

    assert card.yield_gap.gap_packets == Decimal("12.000")
    assert card.yield_gap.damaged_packets == Decimal("6.000")
    assert card.yield_gap.unexplained_packets == Decimal("6.000")


def test_price_and_usage_split_always_equals_the_total_impact() -> None:
    """PS 2.1: no paisa is lost when an impact is split into price and usage."""
    for line in _benchmark_card().lines:
        assert line.price_impact + line.usage_impact == line.total_impact
        assert line.actual_value - line.standard_value == line.total_impact


def test_bridge_steps_add_to_cost_per_packet() -> None:
    """PS 2.1: the bridge is additive at two decimal places."""
    card = _benchmark_card()
    assert sum((step.amount for step in card.bridge), Decimal("0.00")) == card.cost_per_packet
    for step in card.bridge:
        assert step.cumulative <= card.cost_per_packet


def test_damage_cannot_exceed_the_yield_gap() -> None:
    """PS 2.1: recorded damage is capped by the missing packets, not double counted."""
    card = build_report_card(
        lines=_benchmark_lines(),
        planned_output="200",
        good_packets="198",
        damaged_pouches="9",
        overhead_value="0",
    )

    assert card.yield_gap.gap_packets == Decimal("2.000")
    assert card.yield_gap.damaged_packets == Decimal("2.000")
    assert card.yield_gap.unexplained_packets == Decimal("0.000")


def test_no_good_packets_is_refused() -> None:
    """PS 2.1 negative path: a card cannot divide by zero good packets."""
    with pytest.raises(DomainError):
        build_report_card(
            lines=_benchmark_lines(),
            planned_output="200",
            good_packets="0",
            damaged_pouches="0",
            overhead_value="0",
        )


def test_floats_are_refused() -> None:
    """PS 4.1: money and quantities never pass through float."""
    with pytest.raises(DomainError):
        build_report_card(
            lines=_benchmark_lines(),
            planned_output=200.0,  # type: ignore[arg-type]
            good_packets="188",
            damaged_pouches="6",
            overhead_value="0",
        )


def _points(*values: str, direction: str = "adverse") -> list[VariancePoint]:
    return [
        VariancePoint(
            run_id=index + 1,
            variance_pct=Decimal(value),
            direction=direction,
        )
        for index, value in enumerate(values)
    ]


def test_drift_alerts_after_three_consecutive_half_tolerance_runs() -> None:
    """PS 2.2: an adverse input above 1.5% for three runs is drifting."""
    alert = detect_drift("Cooking oil", _points("0.02", "0.021", "0.025"), TOLERANCE)

    assert alert is not None
    assert alert.item_name == "Cooking oil"
    assert alert.consecutive_runs == 3
    assert alert.threshold == Decimal("0.015")


def test_exactly_half_tolerance_does_not_drift() -> None:
    """PS 2.2: the drift boundary mirrors the strict hard limit."""
    alert = detect_drift("Cooking oil", _points("0.015", "0.015", "0.015"), TOLERANCE)
    assert alert is None


def test_drift_needs_the_trailing_streak_to_be_unbroken() -> None:
    """PS 2.2: an on-plan run resets the streak."""
    series = [
        *_points("0.03", "0.03"),
        VariancePoint(run_id=3, variance_pct=Decimal("0.00"), direction="none"),
        *_points("0.03", "0.03"),
    ]
    # The last two are adverse but there are only two in the trailing streak.
    assert detect_drift("Flour", series, TOLERANCE) is None


def test_favourable_points_do_not_drift() -> None:
    """PS 2.2: drift is about adverse creep, not savings."""
    alert = detect_drift(
        "200 g pouch",
        _points("-0.02", "-0.03", "-0.04", direction="favourable"),
        TOLERANCE,
    )
    assert alert is None
