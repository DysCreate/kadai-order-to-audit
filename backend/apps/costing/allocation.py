"""Pure allocation maths for monthly overhead pools.

The monthly pool is split across completed runs by standard batch-hours. A
largest-remainder split keeps every share in whole paise and makes the shares
add back to the pool exactly, so no rupee is lost to rounding.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

from core.errors import DomainError
from core.money import q2

PAISE = Decimal("0.01")


@dataclass(frozen=True)
class AllocationShare:
    """One key's share of a pool, rounded to paise."""

    key: int
    amount: Decimal


def allocate_amount(
    total: Decimal | str | int,
    weights: Sequence[tuple[int, Decimal | str | int]],
) -> list[AllocationShare]:
    """Split ``total`` proportionally to positive ``weights``.

    Invariants: the total is positive, at least one weight is positive, and the
    returned amounts sum exactly to ``total``. Zero shares are omitted. Ties in
    the fractional remainder go to the lower key, which keeps the result
    deterministic.
    """
    pool = q2(total)
    if pool <= 0:
        raise DomainError("An overhead pool must be greater than zero.")

    normalized: list[tuple[int, Decimal]] = []
    for key, raw_weight in weights:
        if isinstance(raw_weight, float):
            raise DomainError("Allocation weights must be Decimal, str or int, never float.")
        weight = Decimal(raw_weight)
        if weight < 0:
            raise DomainError("An allocation weight cannot be negative.")
        if weight > 0:
            normalized.append((key, weight))

    if not normalized:
        raise DomainError("At least one run with positive batch-hours is required.")

    total_weight = sum((weight for _, weight in normalized), Decimal("0"))
    raw_shares = [pool * weight / total_weight for _, weight in normalized]
    shares = [raw.quantize(PAISE, rounding=ROUND_DOWN) for raw in raw_shares]
    remainder_paise = int((pool - sum(shares, Decimal("0"))) / PAISE)

    # Largest fractional remainder first; the key breaks ties deterministically.
    order = sorted(
        range(len(normalized)),
        key=lambda index: (
            -(raw_shares[index] - shares[index]),
            normalized[index][0],
        ),
    )
    for index in order[:remainder_paise]:
        shares[index] += PAISE

    return [
        AllocationShare(key=normalized[index][0], amount=shares[index])
        for index in range(len(normalized))
        if shares[index] > 0
    ]
