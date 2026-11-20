"""Concurrency integration test against real PostgreSQL.

Requirement: AGENTS.md Section 4.11 – two simultaneous dispatches of the last
stock must not both succeed.
"""

import threading

import pytest
from django.db import connection

from apps.inventory.models import MovementType, SourceType, StockBalance, StockLedger
from apps.inventory.services import post_movement, post_opening_balance
from core.errors import InsufficientStock


@pytest.mark.django_db(transaction=True)
def test_two_concurrent_issues_of_last_stock_only_one_succeeds(make_item: object) -> None:
    """PS 4.11: row locking plus CHECK guarantees exactly one issue of the last stock."""
    item = make_item(item_type="FG", uom_symbol="pkt")  # type: ignore[operator]
    post_opening_balance(item_id=item.pk, qty="10", unit_cost="2")

    barrier = threading.Barrier(2)
    results: list[str] = []
    results_lock = threading.Lock()

    def issue(source_id: int) -> None:
        outcome: str
        try:
            barrier.wait(timeout=10)
            post_movement(
                item_id=item.pk,
                qty="-10",
                movement_type=MovementType.ISSUE,
                source_type=SourceType.DISPATCH,
                source_id=source_id,
            )
            outcome = "posted"
        except InsufficientStock:
            outcome = "blocked"
        except Exception as exc:  # noqa: BLE001 - surfaced in the assertion below
            outcome = f"error:{exc!r}"
        finally:
            connection.close()
        with results_lock:
            results.append(outcome)

    threads = [threading.Thread(target=issue, args=(index + 1,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert sorted(results) == ["blocked", "posted"], results

    assert (
        StockLedger.objects.filter(item_id=item.pk, movement_type=MovementType.ISSUE).count() == 1
    )
    balance = StockBalance.objects.get(item_id=item.pk)
    assert balance.qty == 0
    assert balance.value == 0
