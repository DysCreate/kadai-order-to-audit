"""GST computation – a pure function, no database, no floats.

Invariants protected (AGENTS.md 4.8):
- Place of supply is decided by the caller (customer state vs factory state):
  same state gives CGST + SGST, half the rate each; different states give IGST.
- Every line's taxable value and tax are rounded once to paise with
  ``core.money.q2`` (ROUND_HALF_UP), never with ``round()`` or float.
- ``taxable_total + cgst_total + sgst_total == total`` (and
  ``taxable_total + igst_total == total`` inter-state): no paisa is lost.
- ``round_off`` is reported separately and is the accumulated difference
  between the per-line rounded totals and the exact unrounded total; it is a
  memo figure, so the invoice total still equals taxable plus tax.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from core.errors import DomainError
from core.money import q2


@dataclass(frozen=True)
class TaxLineInput:
    """One line to tax: quantity, pre-tax unit price and GST rate percent."""

    key: int
    qty: Decimal
    unit_price: Decimal
    gst_rate: Decimal


@dataclass(frozen=True)
class TaxLine:
    """One taxed line, with paise-rounded values."""

    key: int
    gst_rate: Decimal
    taxable_value: Decimal
    cgst: Decimal
    sgst: Decimal
    igst: Decimal
    line_total: Decimal


@dataclass(frozen=True)
class TaxSummary:
    """A taxed document: its lines, totals, round-off and grand total."""

    lines: tuple[TaxLine, ...]
    is_interstate: bool
    taxable_total: Decimal
    cgst_total: Decimal
    sgst_total: Decimal
    igst_total: Decimal
    round_off: Decimal
    total: Decimal


def _decimal(value: Decimal | str | int, field: str) -> Decimal:
    if isinstance(value, float):
        raise DomainError(f"{field} must be Decimal, str or int, never float.")
    try:
        return Decimal(value)
    except (InvalidOperation, TypeError) as exc:
        raise DomainError(f"{field} is not a valid decimal: {value!r}.") from exc


def compute_tax(
    lines: list[TaxLineInput] | tuple[TaxLineInput, ...],
    *,
    interstate: bool,
) -> TaxSummary:
    """Tax each line to paise and total the document.

    Invariants: at least one line; every quantity is positive and every price
    and rate non-negative; the returned totals are exact sums of the rounded
    lines, so ``taxable + tax == total`` with no paisa lost.
    """
    if not lines:
        raise DomainError("A tax document needs at least one line.")

    taxed: list[TaxLine] = []
    exact_total = Decimal("0")
    for line in lines:
        qty = _decimal(line.qty, "qty")
        unit_price = _decimal(line.unit_price, "unit_price")
        rate = _decimal(line.gst_rate, "gst_rate")
        if qty <= 0:
            raise DomainError("A taxed quantity must be greater than zero.")
        if unit_price < 0:
            raise DomainError("A taxed unit price cannot be negative.")
        if rate < 0:
            raise DomainError("A GST rate cannot be negative.")

        taxable = q2(qty * unit_price)
        if interstate:
            cgst = Decimal("0.00")
            sgst = Decimal("0.00")
            igst = q2(taxable * rate / Decimal("100"))
        else:
            cgst = q2(taxable * rate / Decimal("200"))
            sgst = q2(taxable * rate / Decimal("200"))
            igst = Decimal("0.00")

        taxed.append(
            TaxLine(
                key=line.key,
                gst_rate=rate,
                taxable_value=taxable,
                cgst=cgst,
                sgst=sgst,
                igst=igst,
                line_total=q2(taxable + cgst + sgst + igst),
            )
        )
        exact_total += qty * unit_price * (Decimal("1") + rate / Decimal("100"))

    taxable_total = q2(sum((line.taxable_value for line in taxed), Decimal("0")))
    cgst_total = q2(sum((line.cgst for line in taxed), Decimal("0")))
    sgst_total = q2(sum((line.sgst for line in taxed), Decimal("0")))
    igst_total = q2(sum((line.igst for line in taxed), Decimal("0")))
    total = q2(taxable_total + cgst_total + sgst_total + igst_total)

    return TaxSummary(
        lines=tuple(taxed),
        is_interstate=interstate,
        taxable_total=taxable_total,
        cgst_total=cgst_total,
        sgst_total=sgst_total,
        igst_total=igst_total,
        round_off=q2(total - exact_total),
        total=total,
    )
