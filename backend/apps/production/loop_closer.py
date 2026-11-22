"""Loop Closer maths – from a sales shortage to batches and a purchase list.

Pure functions only: the caller supplies the product's active BOM requirements
and current stock. This is the arithmetic behind the order-screen panel that
joins the sales loop to the production loop.

Invariants protected:
- The batch need uses realised yield, not the BOM's optimistic output:
  ``ceil(shortage / (batch_output x trailing yield factor))``. The benchmark's
  0.94 factor turns a 32-packet shortage into one batch, not a fraction of one.
- Stock capacity is the minimum whole batch count across every BOM input, and
  capacity ratios are ``stock / qty per batch``. The item with the smallest
  ratio is the limiting item (pouches in Appendix A).
- A purchase list is only produced for a genuine gap, rounded up to three
  decimal places so it can never under-order.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from core.errors import DomainError
from core.money import q4
from core.quantity import q3


@dataclass(frozen=True)
class RequirementInput:
    """One BOM input per batch and the stock currently on hand."""

    item_id: int
    item_name: str
    uom: str
    qty_per_batch: Decimal
    stock_qty: Decimal


@dataclass(frozen=True)
class CapacityRow:
    """How many whole batches one input's stock allows."""

    item_id: int
    item_name: str
    uom: str
    qty_per_batch: Decimal
    stock_qty: Decimal
    batches_available: int
    ratio: Decimal
    limiting: bool


@dataclass(frozen=True)
class PurchaseSuggestion:
    """A draft purchase quantity for one input that cannot cover the batches."""

    item_id: int
    item_name: str
    uom: str
    qty: Decimal


@dataclass(frozen=True)
class LoopCloserPlan:
    """Batch need, stock feasibility, limiting item and any draft purchase."""

    product_id: int
    product_name: str
    shortage_qty: Decimal
    batch_output_qty: Decimal
    yield_factor: Decimal
    batches_needed: int
    batches_allowed: int
    feasible: bool
    limiting_item: str
    capacity: tuple[CapacityRow, ...]
    purchase_list: tuple[PurchaseSuggestion, ...]
    verdict: str


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


def plan_batches(
    *,
    product_id: int,
    product_name: str,
    shortage_qty: Decimal | str | int,
    batch_output_qty: Decimal | str | int,
    yield_factor: Decimal | str | int,
    requirements: Sequence[RequirementInput],
) -> LoopCloserPlan:
    """Turn a packet shortage into batches, feasibility and a purchase list.

    Raises:
        DomainError: no requirements, a non-positive batch output or yield
        factor, or a negative quantity.
    """
    shortage = q3(_decimal(shortage_qty, "shortage_qty"))
    output = q3(_decimal(batch_output_qty, "batch_output_qty"))
    factor = _decimal(yield_factor, "yield_factor")
    if not requirements:
        raise DomainError("A loop-closer plan needs at least one BOM requirement.")
    if output <= 0:
        raise DomainError("Batch output must be greater than zero.")
    if factor <= 0:
        raise DomainError("The trailing yield factor must be greater than zero.")

    effective_output = output * factor
    raw_batches = shortage / effective_output if shortage > 0 else Decimal("0")
    batches_needed = int(raw_batches.to_integral_value(rounding=ROUND_CEILING))
    if batches_needed < 0:
        batches_needed = 0

    rows: list[CapacityRow] = []
    limiting_ratio: Decimal | None = None
    limiting_item: CapacityRow | None = None
    for requirement in requirements:
        per_batch = q3(_decimal(requirement.qty_per_batch, "qty_per_batch"))
        stock = q3(_decimal(requirement.stock_qty, "stock_qty"))
        if per_batch <= 0:
            raise DomainError(f"{requirement.item_name!r} must require more than zero per batch.")
        ratio = q4(stock / per_batch)
        batches_available = int(ratio.to_integral_value(rounding=ROUND_FLOOR))
        row = CapacityRow(
            item_id=requirement.item_id,
            item_name=requirement.item_name,
            uom=requirement.uom,
            qty_per_batch=per_batch,
            stock_qty=stock,
            batches_available=batches_available,
            ratio=ratio,
            limiting=False,
        )
        rows.append(row)
        if limiting_ratio is None or ratio < limiting_ratio:
            limiting_ratio = ratio
            limiting_item = row

    if limiting_item is not None:
        rows = [
            CapacityRow(
                item_id=row.item_id,
                item_name=row.item_name,
                uom=row.uom,
                qty_per_batch=row.qty_per_batch,
                stock_qty=row.stock_qty,
                batches_available=row.batches_available,
                ratio=row.ratio,
                limiting=row.item_id == limiting_item.item_id,
            )
            for row in rows
        ]

    batches_allowed = min(row.batches_available for row in rows)
    purchase: list[PurchaseSuggestion] = []
    for row in rows:
        required = row.qty_per_batch * batches_needed
        gap = required - row.stock_qty
        if gap > 0:
            purchase.append(
                PurchaseSuggestion(
                    item_id=row.item_id,
                    item_name=row.item_name,
                    uom=row.uom,
                    qty=q3(gap.to_integral_value(rounding=ROUND_CEILING)),
                )
            )

    feasible = batches_allowed >= batches_needed
    if batches_needed == 0:
        verdict = "nothing_to_produce"
    elif feasible:
        verdict = "feasible"
    else:
        verdict = "purchase_needed" if purchase else "insufficient_stock"

    return LoopCloserPlan(
        product_id=product_id,
        product_name=product_name,
        shortage_qty=shortage,
        batch_output_qty=output,
        yield_factor=q4(factor),
        batches_needed=batches_needed,
        batches_allowed=batches_allowed,
        feasible=feasible,
        limiting_item=limiting_item.item_name if limiting_item is not None else "",
        capacity=tuple(rows),
        purchase_list=tuple(purchase),
        verdict=verdict,
    )
