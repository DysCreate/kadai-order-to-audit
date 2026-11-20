"""Pure valuation maths for the stock ledger.

The chosen method is moving weighted average, behind a strategy interface so
FIFO can be substituted without touching callers.

Invariants protected:
- Issue value is ``q2(issue_qty * running_value / running_qty)``.
- Issuing the entire remaining quantity takes the entire remaining value, so
  the balance is exactly zero when the quantity is zero (no rounding drift).
- Floats are rejected by ``q2``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from core.errors import InsufficientStock
from core.money import q2


class ValuationStrategy(Protocol):
    """Interface every valuation method must implement."""

    def receipt_value(self, qty: Decimal, unit_cost: Decimal) -> Decimal:
        """Return the value received for ``qty`` at ``unit_cost``."""
        ...

    def issue_value(
        self,
        issue_qty: Decimal,
        running_qty: Decimal,
        running_value: Decimal,
    ) -> Decimal:
        """Return the (positive) value of issuing ``issue_qty`` from a balance."""
        ...


class MovingWeightedAverage:
    """Moving weighted average (the chosen method for Kadai)."""

    name = "moving_weighted_average"

    def receipt_value(self, qty: Decimal, unit_cost: Decimal) -> Decimal:
        return q2(qty * unit_cost)

    def issue_value(
        self,
        issue_qty: Decimal,
        running_qty: Decimal,
        running_value: Decimal,
    ) -> Decimal:
        if issue_qty <= 0:
            raise InsufficientStock("An issue quantity must be greater than zero.")
        if issue_qty > running_qty:
            raise InsufficientStock(f"Cannot issue {issue_qty}; only {running_qty} in stock.")
        if issue_qty == running_qty:
            return q2(running_value)
        return q2(issue_qty * running_value / running_qty)
