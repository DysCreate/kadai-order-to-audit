"""Leakage Radar maths – standard cost, price/usage decomposition and drift.

The whole module is pure: it takes stored quantities and values and returns
money. No database access, no floats, no clock, so every rule can be unit
tested and the report card is deterministic.

Invariants protected:
- Standard material value is ``planned qty x the BOM version's standard rate``.
  It never follows a later purchase price or BOM edit.
- Every line's impact splits exactly into a price part and a usage part:
  ``price = actual value - q2(actual qty x standard rate)`` and
  ``usage = q2(actual qty x standard rate) - standard value``. Their sum is the
  actual-minus-standard impact, with no paisa lost to rounding.
- The per-packet bridge is built from rounded cumulative values, so its steps
  add exactly to the run's cost per good packet (Appendix A: 19.85 + 1.27 +
  0.45 + 9.57 = 31.14).
- Drift is raised only when an input is adverse beyond half the tolerance on
  three consecutive completed runs. It is a warning before the hard limit, not
  a second variance flag.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from core.errors import DomainError
from core.money import q2, q4
from core.quantity import q3

ADVERSE = "adverse"
FAVOURABLE = "favourable"
NONE = "none"

DRIFT_RUNS = 3


@dataclass(frozen=True)
class ReportCardLineInput:
    """One input of a completed run, with the standard it was planned against."""

    item_id: int
    item_name: str
    role: str
    planned_qty: Decimal
    actual_qty: Decimal
    actual_value: Decimal
    standard_rate: Decimal


@dataclass(frozen=True)
class ReportCardLine:
    """Standard versus actual for one input, split into price and usage."""

    item_id: int
    item_name: str
    role: str
    planned_qty: Decimal
    actual_qty: Decimal
    standard_rate: Decimal
    actual_rate: Decimal
    standard_value: Decimal
    actual_value: Decimal
    price_impact: Decimal
    usage_impact: Decimal
    total_impact: Decimal


@dataclass(frozen=True)
class BridgeStep:
    """One step of the cost-per-packet bridge, with its running total."""

    key: str
    label: str
    amount: Decimal
    cumulative: Decimal


@dataclass(frozen=True)
class YieldGap:
    """Where the missing packets went: recorded damage versus the unexplained."""

    planned_packets: Decimal
    good_packets: Decimal
    gap_packets: Decimal
    damaged_packets: Decimal
    unexplained_packets: Decimal


@dataclass(frozen=True)
class LeakageReportCard:
    """The full Run Report Card for one completed run."""

    lines: tuple[ReportCardLine, ...]
    standard_materials: Decimal
    actual_materials: Decimal
    price_impact: Decimal
    usage_impact: Decimal
    material_impact: Decimal
    planned_packets: Decimal
    good_packets: Decimal
    overhead_value: Decimal
    standard_per_packet: Decimal
    actual_material_per_packet: Decimal
    overhead_per_packet: Decimal
    cost_per_packet: Decimal
    bridge: tuple[BridgeStep, ...]
    yield_gap: YieldGap
    selling_price: Decimal | None
    margin_per_packet: Decimal | None
    margin_pct: Decimal | None


def _decimal(value: Decimal | str | int, field: str) -> Decimal:
    if isinstance(value, float):
        raise DomainError(f"{field} must be Decimal, str or int, never float.")
    try:
        parsed = Decimal(value)
    except (ArithmeticError, TypeError, ValueError) as exc:
        raise DomainError(f"{field} is not a valid decimal: {value!r}.") from exc
    if parsed < 0:
        raise DomainError(f"{field} cannot be negative.")
    return parsed


def _per_packet(total: Decimal, packets: Decimal, field: str) -> Decimal:
    if packets <= 0:
        raise DomainError(f"{field} needs good packets greater than zero.")
    return q2(total / packets)


def build_report_card(
    *,
    lines: Sequence[ReportCardLineInput],
    planned_output: Decimal | str | int,
    good_packets: Decimal | str | int,
    damaged_pouches: Decimal | str | int,
    overhead_value: Decimal | str | int,
    selling_price: Decimal | str | int | None = None,
) -> LeakageReportCard:
    """Build the Run Report Card from a run's stored quantities and values.

    Args:
        lines: One entry per BOM input, with its actual cost from the ledger.
        planned_output: Packets expected from the batch count.
        good_packets: Good packets actually produced.
        damaged_pouches: Recorded damaged pouches (each one a scrapped packet).
        overhead_value: Labour and power assigned to the run.
        selling_price: Default price per packet, or None when not configured.

    Raises:
        DomainError: a negative quantity, a float, or no good packets.
    """
    planned = q3(_decimal(planned_output, "planned_output"))
    good = q3(_decimal(good_packets, "good_packets"))
    damaged = q3(_decimal(damaged_pouches, "damaged_pouches"))
    overheads = q2(_decimal(overhead_value, "overhead_value"))
    if planned <= 0:
        raise DomainError("Planned output must be greater than zero.")
    if good <= 0:
        raise DomainError("A report card needs at least one good packet.")

    card_lines: list[ReportCardLine] = []
    standard_total = Decimal("0.00")
    actual_total = Decimal("0.00")
    for line in lines:
        planned_qty = q3(_decimal(line.planned_qty, "planned_qty"))
        actual_qty = q3(_decimal(line.actual_qty, "actual_qty"))
        actual_value = q2(_decimal(line.actual_value, "actual_value"))
        standard_rate = q4(_decimal(line.standard_rate, "standard_rate"))

        standard_value = q2(planned_qty * standard_rate)
        actual_at_standard = q2(actual_qty * standard_rate)
        price_impact = q2(actual_value - actual_at_standard)
        usage_impact = q2(actual_at_standard - standard_value)
        actual_rate = q4(actual_value / actual_qty) if actual_qty > 0 else Decimal("0.0000")

        card_lines.append(
            ReportCardLine(
                item_id=line.item_id,
                item_name=line.item_name,
                role=line.role,
                planned_qty=planned_qty,
                actual_qty=actual_qty,
                standard_rate=standard_rate,
                actual_rate=actual_rate,
                standard_value=standard_value,
                actual_value=actual_value,
                price_impact=price_impact,
                usage_impact=usage_impact,
                total_impact=q2(actual_value - standard_value),
            )
        )
        standard_total += standard_value
        actual_total += actual_value

    standard_materials = q2(standard_total)
    actual_materials = q2(actual_total)
    price_impact = q2(sum((line.price_impact for line in card_lines), Decimal("0.00")))
    usage_impact = q2(sum((line.usage_impact for line in card_lines), Decimal("0.00")))
    material_impact = q2(actual_materials - standard_materials)

    standard_per = _per_packet(standard_materials, planned, "planned output")
    standard_per_good = _per_packet(standard_materials, good, "good packets")
    actual_per = _per_packet(actual_materials, good, "good packets")
    total_per = _per_packet(actual_materials + overheads, good, "good packets")

    yield_step = q2(standard_per_good - standard_per)
    variance_step = q2(actual_per - standard_per_good)
    overhead_step = q2(total_per - actual_per)

    bridge = (
        BridgeStep("standard_material", "Standard material", standard_per, standard_per),
        BridgeStep(
            "yield_shortfall",
            "Yield shortfall",
            yield_step,
            q2(standard_per + yield_step),
        ),
        BridgeStep(
            "price_usage",
            "Price and usage variance",
            variance_step,
            q2(standard_per + yield_step + variance_step),
        ),
        BridgeStep(
            "overhead",
            "Overhead",
            overhead_step,
            q2(standard_per + yield_step + variance_step + overhead_step),
        ),
    )

    gap = q3(planned - good)
    if gap < 0:
        gap = Decimal("0.000")
    explained_damage = damaged if damaged <= gap else gap
    yield_gap = YieldGap(
        planned_packets=planned,
        good_packets=good,
        gap_packets=gap,
        damaged_packets=q3(explained_damage),
        unexplained_packets=q3(gap - explained_damage),
    )

    price = None if selling_price is None else q2(_decimal(selling_price, "selling_price"))
    margin = q2(price - total_per) if price is not None else None
    margin_pct = (
        q2(margin / price * 100)
        if margin is not None and price is not None and price != 0
        else None
    )

    return LeakageReportCard(
        lines=tuple(card_lines),
        standard_materials=standard_materials,
        actual_materials=actual_materials,
        price_impact=price_impact,
        usage_impact=usage_impact,
        material_impact=material_impact,
        planned_packets=planned,
        good_packets=good,
        overhead_value=overheads,
        standard_per_packet=standard_per,
        actual_material_per_packet=actual_per,
        overhead_per_packet=overhead_step,
        cost_per_packet=total_per,
        bridge=bridge,
        yield_gap=yield_gap,
        selling_price=price,
        margin_per_packet=margin,
        margin_pct=margin_pct,
    )


@dataclass(frozen=True)
class VariancePoint:
    """One completed run's stored variance for a single input."""

    run_id: int
    variance_pct: Decimal | None
    direction: str


@dataclass(frozen=True)
class DriftAlert:
    """An input that is creeping adverse before it breaches the hard tolerance."""

    item_name: str
    consecutive_runs: int
    latest_variance_pct: Decimal | None
    threshold: Decimal
    direction: str


def detect_drift(
    item_name: str,
    series: Sequence[VariancePoint],
    tolerance: Decimal | str | int,
) -> DriftAlert | None:
    """Return a drift alert when the latest runs are all adverse beyond half tolerance.

    Args:
        item_name: The input being checked.
        series: Stored variance points, oldest first.
        tolerance: The variance tolerance from settings (0.03 for 3%).

    Invariants: only the trailing streak counts, the rule needs
    ``DRIFT_RUNS`` consecutive points, and a point exactly at half the
    tolerance does not count (strictly greater, mirroring the hard limit).
    """
    limit = _decimal(tolerance, "tolerance")
    if limit == 0:
        return None
    threshold = limit / 2

    streak = 0
    latest: VariancePoint | None = None
    for point in reversed(series):
        pct = point.variance_pct
        if point.direction != ADVERSE or pct is None or abs(pct) <= threshold:
            break
        streak += 1
        if latest is None:
            latest = point

    if streak < DRIFT_RUNS or latest is None:
        return None
    return DriftAlert(
        item_name=item_name,
        consecutive_runs=streak,
        latest_variance_pct=latest.variance_pct,
        threshold=threshold,
        direction=ADVERSE,
    )
