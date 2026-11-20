"""Ledger integration tests against real PostgreSQL.

Requirement: AGENTS.md Section 4.3–4.5, 4.11, 4.14 and 5 (ledger invariants,
append-only trigger, negative-stock rejection, traceability).
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.db.models import Sum
from hypothesis import given, settings
from hypothesis import strategies as st

from apps.inventory.models import (
    MovementType,
    SourceType,
    StockAdjustment,
    StockBalance,
    StockLedger,
)
from apps.inventory.services import (
    adjust_stock,
    ledger_entries,
    post_movement,
    post_movements,
    post_opening_balance,
    reconcile_stock,
    stock_summary,
)
from apps.masters.services import create_item, create_uom
from core.errors import (
    DomainError,
    InsufficientStock,
    InvalidMovement,
    OpeningBalanceExists,
)


def _balance(item_id: int) -> StockBalance:
    return StockBalance.objects.get(item_id=item_id)


def _ledger_totals(item_id: int) -> tuple[Decimal, Decimal]:
    totals = StockLedger.objects.filter(item_id=item_id).aggregate(
        qty=Sum("qty"), value=Sum("value")
    )
    return totals["qty"] or Decimal("0.000"), totals["value"] or Decimal("0.00")


def test_opening_balance_is_a_traceable_ledger_row(make_item: object) -> None:
    """PS 1 ledger: opening stock is an OPENING row sourced to the item."""
    item = make_item()  # type: ignore[operator]
    entry = post_opening_balance(item_id=item.pk, qty="100", unit_cost="42")

    assert entry.movement_type == MovementType.OPENING
    assert entry.source_type == SourceType.OPENING
    assert entry.source_id == item.pk
    assert entry.qty == Decimal("100.000")
    assert entry.value == Decimal("4200.00")
    assert entry.unit_value == Decimal("42.0000")

    balance = _balance(item.pk)
    assert (balance.qty, balance.value) == (Decimal("100.000"), Decimal("4200.00"))
    assert reconcile_stock() == []


def test_receipt_and_issue_use_moving_weighted_average(make_item: object) -> None:
    """Appendix A: 100 kg @42 + 60 kg @45 = 160 kg @43.125; 40 kg issues 1,725."""
    item = make_item()  # type: ignore[operator]
    post_opening_balance(item_id=item.pk, qty="100", unit_cost="42")

    post_movement(
        item_id=item.pk,
        qty="60",
        movement_type=MovementType.RECEIPT,
        source_type=SourceType.PURCHASE,
        source_id=1,
        unit_cost="45",
    )
    balance = _balance(item.pk)
    assert balance.qty == Decimal("160.000")
    assert balance.value == Decimal("6900.00")

    issue = post_movement(
        item_id=item.pk,
        qty="-40",
        movement_type=MovementType.ISSUE,
        source_type=SourceType.PRODUCTION_RUN,
        source_id=1,
    )
    assert issue.value == Decimal("-1725.00")
    assert issue.unit_value == Decimal("43.1250")

    balance = _balance(item.pk)
    assert balance.qty == Decimal("120.000")
    assert balance.value == Decimal("5175.00")
    assert reconcile_stock() == []


def test_insufficient_stock_raises_and_writes_nothing(make_item: object) -> None:
    """PS 4.11: an issue beyond stock is refused; no ledger row is written."""
    item = make_item()  # type: ignore[operator]
    post_opening_balance(item_id=item.pk, qty="10", unit_cost="5")
    ledger_count = StockLedger.objects.count()

    with pytest.raises(InsufficientStock):
        post_movement(
            item_id=item.pk,
            qty="-11",
            movement_type=MovementType.ISSUE,
            source_type=SourceType.DISPATCH,
            source_id=7,
        )

    assert StockLedger.objects.count() == ledger_count
    balance = _balance(item.pk)
    assert (balance.qty, balance.value) == (Decimal("10.000"), Decimal("50.00"))


def test_issuing_all_stock_leaves_zero_value(make_item: object) -> None:
    """PS 4.5: the balance keeps the remainder; value is exactly zero at zero qty."""
    item = make_item(item_type="RAW", uom_symbol="pc")  # type: ignore[operator]
    post_opening_balance(item_id=item.pk, qty="3", unit_cost="33.333")

    first = post_movement(
        item_id=item.pk,
        qty="-2",
        movement_type=MovementType.ISSUE,
        source_type=SourceType.PRODUCTION_RUN,
        source_id=1,
    )
    assert first.value == Decimal("-66.67")

    last = post_movement(
        item_id=item.pk,
        qty="-1",
        movement_type=MovementType.ISSUE,
        source_type=SourceType.PRODUCTION_RUN,
        source_id=1,
    )
    assert last.value == Decimal("-33.33")

    balance = _balance(item.pk)
    assert balance.qty == Decimal("0.000")
    assert balance.value == Decimal("0.00")
    assert reconcile_stock() == []


def test_ledger_update_is_rejected_by_database_trigger(make_item: object) -> None:
    """PS 4.3: UPDATE on stock_ledger raises at the database level."""
    item = make_item()  # type: ignore[operator]
    entry = post_opening_balance(item_id=item.pk, qty="10", unit_cost="2")

    with pytest.raises(IntegrityError), transaction.atomic():
        StockLedger.objects.filter(pk=entry.pk).update(qty=Decimal("99"))

    entry.refresh_from_db()
    assert entry.qty == Decimal("10.000")


def test_ledger_delete_is_rejected_by_database_trigger(make_item: object) -> None:
    """PS 4.3 / 4.14: DELETE on stock_ledger raises at the database level."""
    item = make_item()  # type: ignore[operator]
    entry = post_opening_balance(item_id=item.pk, qty="10", unit_cost="2")

    with pytest.raises(IntegrityError), transaction.atomic():
        StockLedger.objects.filter(pk=entry.pk).delete()

    assert StockLedger.objects.filter(pk=entry.pk).exists()


def test_negative_balance_is_rejected_by_database_check(make_item: object) -> None:
    """PS 4.3: CHECK (qty >= 0) rejects negative stock even below the service."""
    item = make_item()  # type: ignore[operator]
    post_opening_balance(item_id=item.pk, qty="1", unit_cost="1")

    with pytest.raises(IntegrityError), transaction.atomic():
        StockBalance.objects.filter(item_id=item.pk).update(qty=Decimal("-1"))


def test_movement_requires_source_and_correct_sign(make_item: object) -> None:
    """PS 4.4: every movement needs a source and a sign matching its type."""
    item = make_item()  # type: ignore[operator]
    post_opening_balance(item_id=item.pk, qty="10", unit_cost="2")

    with pytest.raises(InvalidMovement):
        post_movement(
            item_id=item.pk,
            qty="-1",
            movement_type=MovementType.RECEIPT,
            source_type=SourceType.PURCHASE,
            source_id=1,
            unit_cost="2",
        )

    with pytest.raises(InvalidMovement):
        post_movement(
            item_id=item.pk,
            qty="1",
            movement_type=MovementType.RECEIPT,
            source_type=SourceType.PURCHASE,
            source_id=0,
            unit_cost="2",
        )

    with pytest.raises(InvalidMovement):
        post_movement(
            item_id=item.pk,
            qty="1",
            movement_type=MovementType.RECEIPT,
            source_type="made_up_source",
            source_id=3,
            unit_cost="2",
        )

    with pytest.raises(InvalidMovement):
        post_movement(
            item_id=item.pk,
            qty="0",
            movement_type=MovementType.RECEIPT,
            source_type=SourceType.PURCHASE,
            source_id=3,
            unit_cost="2",
        )


def test_movement_validation_rejects_bad_input(make_item: object) -> None:
    """PS 4.4: malformed movements are refused before any row is written."""
    item = make_item()  # type: ignore[operator]
    post_opening_balance(item_id=item.pk, qty="10", unit_cost="2")
    ledger_count = StockLedger.objects.count()

    def receipt(**overrides: object) -> None:
        payload: dict[str, object] = {
            "item_id": item.pk,
            "qty": "1",
            "movement_type": MovementType.RECEIPT,
            "source_type": SourceType.PURCHASE,
            "source_id": 1,
            "unit_cost": "2",
        }
        payload.update(overrides)
        post_movement(**payload)  # type: ignore[arg-type]

    with pytest.raises(InvalidMovement):
        receipt(qty=1.5)
    with pytest.raises(InvalidMovement):
        receipt(qty="not-a-number")
    with pytest.raises(InvalidMovement):
        receipt(unit_cost="-1")
    with pytest.raises(InvalidMovement):
        receipt(unit_cost=None)
    with pytest.raises(InvalidMovement):
        receipt(movement_type="BOGUS")
    with pytest.raises(InvalidMovement):
        receipt(movement_type=MovementType.OPENING, source_type=SourceType.PURCHASE)
    with pytest.raises(InvalidMovement):
        post_movement(
            item_id=item.pk,
            qty="-1",
            movement_type=MovementType.ISSUE,
            source_type=SourceType.DISPATCH,
            source_id=1,
            unit_cost="2",
        )
    with pytest.raises(InvalidMovement):
        post_movement(
            item_id=item.pk,
            qty="1",
            movement_type=MovementType.ISSUE,
            source_type=SourceType.DISPATCH,
            source_id=1,
        )
    with pytest.raises(InvalidMovement):
        post_movements(
            movements=[],
            movement_type=MovementType.RECEIPT,
            source_type=SourceType.PURCHASE,
            source_id=1,
        )
    with pytest.raises(DomainError):
        receipt(item_id=999_999)

    assert StockLedger.objects.count() == ledger_count


def test_opening_balance_requires_positive_quantity(make_item: object) -> None:
    """PS 4.3: an opening balance must be greater than zero."""
    item = make_item()  # type: ignore[operator]
    with pytest.raises(InvalidMovement):
        post_opening_balance(item_id=item.pk, qty="0", unit_cost="2")


def test_adjustment_increase_uses_current_average(make_item: object) -> None:
    """PS 4.5: a positive adjustment without a cost uses the running average."""
    item = make_item()  # type: ignore[operator]
    post_opening_balance(item_id=item.pk, qty="10", unit_cost="4")

    adjustment = adjust_stock(item_id=item.pk, qty_delta="5", reason="Found in store")
    assert adjustment.qty_delta == Decimal("5.000")
    balance = _balance(item.pk)
    assert (balance.qty, balance.value) == (Decimal("15.000"), Decimal("60.00"))

    empty = make_item(name="Empty item", uom_symbol="pc")  # type: ignore[operator]
    with pytest.raises(InvalidMovement):
        adjust_stock(item_id=empty.pk, qty_delta="1", reason="Found in store")


def test_opening_balance_cannot_be_posted_twice(make_item: object) -> None:
    """PS 4.3: opening balances are posted once; later stock is an adjustment."""
    item = make_item()  # type: ignore[operator]
    post_opening_balance(item_id=item.pk, qty="10", unit_cost="2")

    with pytest.raises(OpeningBalanceExists):
        post_opening_balance(item_id=item.pk, qty="10", unit_cost="2")


def test_adjustment_requires_a_reason(make_item: object) -> None:
    """PS 1 adjustments: every manual correction carries a reason."""
    item = make_item()  # type: ignore[operator]
    post_opening_balance(item_id=item.pk, qty="10", unit_cost="2")

    with pytest.raises(InvalidMovement):
        adjust_stock(item_id=item.pk, qty_delta="-1", reason="   ")

    assert StockAdjustment.objects.count() == 0


def test_adjustment_posts_a_traceable_ledger_row(make_item: object) -> None:
    """PS 4.4: the adjustment document is the ledger row's source."""
    item = make_item()  # type: ignore[operator]
    post_opening_balance(item_id=item.pk, qty="10", unit_cost="2")

    adjustment = adjust_stock(
        item_id=item.pk,
        qty_delta="-2",
        reason="Damaged in storage",
    )
    entry = StockLedger.objects.get(
        movement_type=MovementType.ADJUSTMENT,
        source_type=SourceType.ADJUSTMENT,
    )
    assert entry.source_id == adjustment.pk
    assert entry.qty == Decimal("-2.000")
    assert entry.value == Decimal("-4.00")
    assert _balance(item.pk).qty == Decimal("8.000")


def test_failed_adjustment_rolls_back_its_document(make_item: object) -> None:
    """An over-issue adjustment leaves neither a document nor a ledger row."""
    item = make_item()  # type: ignore[operator]
    post_opening_balance(item_id=item.pk, qty="1", unit_cost="2")
    ledger_count = StockLedger.objects.count()

    with pytest.raises(InsufficientStock):
        adjust_stock(item_id=item.pk, qty_delta="-5", reason="Stock take")

    assert StockAdjustment.objects.count() == 0
    assert StockLedger.objects.count() == ledger_count


def test_summary_and_ledger_filters(make_item: object) -> None:
    """PS 1 API: stock summary lists every item; ledger filters by item and date."""
    flour = make_item()  # type: ignore[operator]
    oil = make_item(name="Cooking oil", uom_symbol="L")  # type: ignore[operator]
    post_opening_balance(item_id=flour.pk, qty="10", unit_cost="42")
    post_opening_balance(item_id=oil.pk, qty="5", unit_cost="140")

    empty = make_item(name="Empty shelf", uom_symbol="pc")  # type: ignore[operator]

    rows = {row.item.pk: row for row in stock_summary()}
    assert rows[flour.pk].qty == Decimal("10.000")
    assert rows[flour.pk].value == Decimal("420.00")
    assert rows[oil.pk].avg_rate == Decimal("140.0000")
    assert rows[empty.pk].qty == Decimal("0.000")
    assert rows[empty.pk].avg_rate == Decimal("0.0000")

    entries = list(ledger_entries(item_id=flour.pk))
    assert len(entries) == 1
    assert entries[0].item_id == flour.pk

    tomorrow = date.today() + timedelta(days=1)
    assert list(ledger_entries(item_id=flour.pk, date_from=tomorrow)) == []
    assert list(ledger_entries(item_id=flour.pk, date_to=date.today()))


def test_reconcile_detects_balance_drift(make_item: object) -> None:
    """PS 6.7: reconcile reports a balance that no longer equals the ledger sum."""
    item = make_item()  # type: ignore[operator]
    post_opening_balance(item_id=item.pk, qty="10", unit_cost="2")
    StockBalance.objects.filter(item_id=item.pk).update(value=Decimal("99.00"))

    issues = reconcile_stock()
    assert len(issues) == 1
    assert issues[0].item_id == item.pk
    assert issues[0].balance_value == Decimal("99.00")
    assert issues[0].ledger_value == Decimal("20.00")


@pytest.mark.django_db
@settings(max_examples=30, deadline=None)
@given(
    ops=st.lists(
        st.tuples(st.integers(min_value=0, max_value=1), st.integers(min_value=1, max_value=20)),
        min_size=1,
        max_size=12,
    )
)
def test_balance_always_equals_ledger_sum(ops: list[tuple[int, int]]) -> None:
    """PS 5 hypothesis: any valid movement sequence keeps balance == SUM(ledger)."""
    create_uom(name="Kilogram", symbol="kg")
    item = create_item(
        name=f"Hypothesis flour {uuid.uuid4().hex}",
        item_type="RAW",
        uom_symbol="kg",
    )
    post_opening_balance(item_id=item.pk, qty="100", unit_cost="10")

    for kind, amount in ops:
        qty = Decimal(amount)
        try:
            if kind == 0:
                post_movement(
                    item_id=item.pk,
                    qty=qty,
                    movement_type=MovementType.RECEIPT,
                    source_type=SourceType.PURCHASE,
                    source_id=1,
                    unit_cost=Decimal("12.5"),
                )
            else:
                post_movement(
                    item_id=item.pk,
                    qty=-qty,
                    movement_type=MovementType.ISSUE,
                    source_type=SourceType.PRODUCTION_RUN,
                    source_id=1,
                )
        except InsufficientStock:
            pass

        balance = _balance(item.pk)
        ledger_qty, ledger_value = _ledger_totals(item.pk)
        assert balance.qty == ledger_qty
        assert balance.value == ledger_value
        assert balance.qty >= 0
        if balance.qty == 0:
            assert balance.value == 0
