"""Unit tests for the Loop Closer batch and purchase maths.

Requirement: implementation plan Section 2.3 – 32 packets short, a 0.94
trailing yield, one batch needed, one allowed, pouches limiting. Pure
functions, no database.
"""

from decimal import Decimal

import pytest

from apps.production.loop_closer import RequirementInput, plan_batches
from core.errors import DomainError


def _requirements(
    *,
    flour: str = "120",
    oil: str = "19.5",
    spice: str = "3.8",
    pouches: str = "306",
    cartons: str = "21",
) -> list[RequirementInput]:
    return [
        RequirementInput(1, "Flour", "kg", Decimal("40"), Decimal(flour)),
        RequirementInput(2, "Cooking oil", "L", Decimal("10"), Decimal(oil)),
        RequirementInput(3, "Salt and spice mix", "kg", Decimal("1.2"), Decimal(spice)),
        RequirementInput(4, "200 g pouch", "pc", Decimal("200"), Decimal(pouches)),
        RequirementInput(5, "Carton (holds 20 packets)", "pc", Decimal("10"), Decimal(cartons)),
    ]


def _plan(**kwargs: object):
    return plan_batches(
        product_id=1,
        product_name="Murukku 200 g",
        shortage_qty=kwargs.pop("shortage_qty", "32"),
        batch_output_qty="200",
        yield_factor="0.94",
        requirements=kwargs.pop("requirements", _requirements()),
    )


def test_benchmark_shortage_is_one_feasible_batch() -> None:
    """PS 2.3: 32 / (200 x 0.94) rounds up to one batch, stock allows one."""
    plan = _plan()

    assert plan.batches_needed == 1
    assert plan.batches_allowed == 1
    assert plan.feasible is True
    assert plan.verdict == "feasible"
    assert plan.limiting_item == "200 g pouch"
    assert plan.purchase_list == ()
    assert plan.yield_factor == Decimal("0.9400")


def test_capacity_ratios_match_appendix_a() -> None:
    """PS 2.3: pouches 1.53, oil 1.95, cartons 2.10, flour 3.00, spice 3.17."""
    plan = _plan()
    ratios = {row.item_name: row.ratio for row in plan.capacity}

    assert ratios["200 g pouch"] == Decimal("1.5300")
    assert ratios["Cooking oil"] == Decimal("1.9500")
    assert ratios["Carton (holds 20 packets)"] == Decimal("2.1000")
    assert ratios["Flour"] == Decimal("3.0000")
    assert ratios["Salt and spice mix"] == Decimal("3.1667")
    assert [row.item_name for row in plan.capacity if row.limiting] == ["200 g pouch"]


def test_gap_produces_a_ceiling_rounded_purchase_list() -> None:
    """PS 2.3: three batches needed and one allowed yields a draft purchase list."""
    plan = _plan(
        shortage_qty="400",
        requirements=_requirements(flour="0", pouches="100", cartons="5", oil="5"),
    )

    assert plan.batches_needed == 3  # ceil(400 / 188)
    assert plan.batches_allowed == 0
    assert plan.feasible is False
    assert plan.verdict == "purchase_needed"

    purchases = {row.item_name: row.qty for row in plan.purchase_list}
    assert purchases["Flour"] == Decimal("120.000")  # 3 x 40 - 120
    assert purchases["Cooking oil"] == Decimal("25.000")
    assert purchases["200 g pouch"] == Decimal("500.000")
    assert purchases["Carton (holds 20 packets)"] == Decimal("25.000")


def test_no_shortage_needs_no_batches() -> None:
    """PS 2.3: a covered order produces a clear nothing-to-produce verdict."""
    plan = _plan(shortage_qty="0")

    assert plan.batches_needed == 0
    assert plan.feasible is True
    assert plan.verdict == "nothing_to_produce"
    assert plan.purchase_list == ()


def test_zero_yield_factor_is_refused() -> None:
    """PS 2.3 negative path: a zero trailing yield cannot size a batch."""
    with pytest.raises(DomainError):
        plan_batches(
            product_id=1,
            product_name="Murukku 200 g",
            shortage_qty="32",
            batch_output_qty="200",
            yield_factor="0",
            requirements=_requirements(),
        )


def test_no_requirements_is_refused() -> None:
    """PS 2.3 negative path: a BOM-less product has no feasibility answer."""
    with pytest.raises(DomainError):
        plan_batches(
            product_id=1,
            product_name="Murukku 200 g",
            shortage_qty="32",
            batch_output_qty="200",
            yield_factor="0.94",
            requirements=[],
        )
