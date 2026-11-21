"""Unit tests for GST computation.

Requirement: AGENTS.md 4.8 and 5 – intra-state CGST + SGST, inter-state IGST,
per-line paise rounding, and no paisa lost in the totals.
"""

from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from apps.sales.gst import TaxLineInput, compute_tax
from core.errors import DomainError


def test_intra_state_splits_gst_into_cgst_and_sgst() -> None:
    """PS 4.8: Retailer A, 150 packets at 50, 5% -> 7,875.00 intra-state."""
    summary = compute_tax(
        [
            TaxLineInput(
                key=1,
                qty=Decimal("150"),
                unit_price=Decimal("50"),
                gst_rate=Decimal("5"),
            )
        ],
        interstate=False,
    )

    assert summary.taxable_total == Decimal("7500.00")
    assert summary.cgst_total == Decimal("187.50")
    assert summary.sgst_total == Decimal("187.50")
    assert summary.igst_total == Decimal("0.00")
    assert summary.round_off == Decimal("0.00")
    assert summary.total == Decimal("7875.00")
    assert summary.taxable_total + summary.cgst_total + summary.sgst_total == summary.total


def test_inter_state_uses_igst() -> None:
    """PS 4.8: Distributor B, 120 packets at 50, 5% -> 6,300.00 inter-state."""
    summary = compute_tax(
        [
            TaxLineInput(
                key=1,
                qty=Decimal("120"),
                unit_price=Decimal("50"),
                gst_rate=Decimal("5"),
            )
        ],
        interstate=True,
    )

    assert summary.is_interstate is True
    assert summary.taxable_total == Decimal("6000.00")
    assert summary.igst_total == Decimal("300.00")
    assert summary.cgst_total == Decimal("0.00")
    assert summary.sgst_total == Decimal("0.00")
    assert summary.total == Decimal("6300.00")
    assert summary.taxable_total + summary.igst_total == summary.total


def test_tax_is_rounded_per_line_and_round_off_is_shown_separately() -> None:
    """PS 4.8: ten 1-paise lines lose half a paisa; round_off explains it."""
    summary = compute_tax(
        [
            TaxLineInput(
                key=index,
                qty=Decimal("1"),
                unit_price=Decimal("0.01"),
                gst_rate=Decimal("5"),
            )
            for index in range(10)
        ],
        interstate=False,
    )

    assert summary.taxable_total == Decimal("0.10")
    assert summary.cgst_total == Decimal("0.00")
    assert summary.sgst_total == Decimal("0.00")
    assert summary.total == Decimal("0.10")
    # 10 x 0.01 x 1.05 = 0.105 exactly; the invoice total keeps 0.10.
    assert summary.round_off == Decimal("-0.01")


def test_rounding_edge_uses_round_half_up() -> None:
    """PS 4.8: a half-paisa tax rounds up, never down and never to a float."""
    summary = compute_tax(
        [
            TaxLineInput(
                key=1,
                qty=Decimal("1"),
                unit_price=Decimal("0.20"),
                gst_rate=Decimal("5"),
            )
        ],
        interstate=False,
    )

    # 0.20 x 2.5% = 0.005 exactly; ROUND_HALF_UP gives one paisa each.
    assert summary.lines[0].taxable_value == Decimal("0.20")
    assert summary.lines[0].cgst == Decimal("0.01")
    assert summary.lines[0].sgst == Decimal("0.01")
    assert summary.lines[0].line_total == Decimal("0.22")
    assert summary.total == Decimal("0.22")


def test_zero_rate_produces_no_tax() -> None:
    """PS 4.8: a zero-rated line still totals correctly."""
    summary = compute_tax(
        [
            TaxLineInput(
                key=1,
                qty=Decimal("2"),
                unit_price=Decimal("10"),
                gst_rate=Decimal("0"),
            )
        ],
        interstate=False,
    )

    assert summary.taxable_total == Decimal("20.00")
    assert summary.total == Decimal("20.00")
    assert summary.cgst_total == summary.sgst_total == Decimal("0.00")


def test_invalid_tax_input_is_rejected() -> None:
    """PS 4.8 negative paths: empty, negative and float inputs are refused."""
    with pytest.raises(DomainError):
        compute_tax([], interstate=False)

    with pytest.raises(DomainError):
        compute_tax(
            [
                TaxLineInput(
                    key=1,
                    qty=Decimal("0"),
                    unit_price=Decimal("10"),
                    gst_rate=Decimal("5"),
                )
            ],
            interstate=False,
        )

    with pytest.raises(DomainError):
        compute_tax(
            [
                TaxLineInput(
                    key=1,
                    qty=Decimal("1"),
                    unit_price=Decimal("-1"),
                    gst_rate=Decimal("5"),
                )
            ],
            interstate=False,
        )

    with pytest.raises(DomainError):
        compute_tax(
            [TaxLineInput(key=1, qty=1.5, unit_price=Decimal("10"), gst_rate=Decimal("5"))],
            interstate=False,
        )


@settings(max_examples=50, deadline=None)
@given(
    qty=st.decimals(min_value=Decimal("0.001"), max_value=Decimal("1000"), places=3),
    price=st.decimals(min_value=Decimal("0"), max_value=Decimal("5000"), places=2),
    rate=st.sampled_from([Decimal("0"), Decimal("5"), Decimal("12"), Decimal("18")]),
    interstate=st.booleans(),
)
def test_taxable_plus_tax_equals_total_without_losing_paise(
    qty: Decimal, price: Decimal, rate: Decimal, interstate: bool
) -> None:
    """PS 5 hypothesis: taxable + tax == total, with the right split."""
    summary = compute_tax(
        [TaxLineInput(key=1, qty=qty, unit_price=price, gst_rate=rate)],
        interstate=interstate,
    )

    assert (
        summary.taxable_total + summary.cgst_total + summary.sgst_total + summary.igst_total
        == summary.total
    )
    if interstate:
        assert summary.cgst_total == Decimal("0.00")
        assert summary.sgst_total == Decimal("0.00")
    else:
        assert summary.igst_total == Decimal("0.00")
        assert summary.cgst_total == summary.sgst_total
