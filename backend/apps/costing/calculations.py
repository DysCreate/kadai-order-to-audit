"""Pure run-cost maths: cost per good packet and margin.

No database access and no floats. The run total is divided by good packets
only, so scrap is absorbed by saleable output (assumption A5).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from core.errors import DomainError
from core.money import q2


@dataclass(frozen=True)
class PacketCost:
    """Cost per good packet and its margin against a selling price."""

    total_cost: Decimal
    good_packets: Decimal
    cost_per_packet: Decimal
    selling_price: Decimal | None
    margin_per_packet: Decimal | None
    margin_pct: Decimal | None


def packet_cost(
    *,
    total_cost: Decimal | str | int,
    good_packets: Decimal | str | int,
    selling_price: Decimal | str | int | None = None,
) -> PacketCost:
    """Return cost per good packet and margin, rounded with ``q2``.

    Invariants: total cost is non-negative, good packets are positive, and a
    selling price (when supplied) is non-negative. A zero selling price leaves
    the percentage undefined rather than dividing by zero.
    """
    total = q2(total_cost)
    if total < 0:
        raise DomainError("A run's total cost cannot be negative.")
    good = Decimal(good_packets)
    if good <= 0:
        raise DomainError("Cost per packet needs at least one good packet.")

    per_packet = q2(total / good)
    if selling_price is None:
        return PacketCost(
            total_cost=total,
            good_packets=good,
            cost_per_packet=per_packet,
            selling_price=None,
            margin_per_packet=None,
            margin_pct=None,
        )

    price = q2(selling_price)
    if price < 0:
        raise DomainError("A selling price cannot be negative.")
    margin = q2(price - per_packet)
    margin_pct = None if price == 0 else q2(margin / price * 100)
    return PacketCost(
        total_cost=total,
        good_packets=good,
        cost_per_packet=per_packet,
        selling_price=price,
        margin_per_packet=margin,
        margin_pct=margin_pct,
    )
