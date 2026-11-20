"""API tests for the Phase 1 inventory endpoints.

Requirement: AGENTS.md Section 5 – every endpoint tested for each allowed role
and at least one denied role, plus negative paths and Decimal-as-string output.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.inventory.models import StockAdjustment, StockLedger
from apps.inventory.services import post_opening_balance

pytestmark = pytest.mark.django_db


def _login(client: object, user: User) -> None:
    client.force_login(user)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Stock summary
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role", Role.values)
def test_stock_summary_allowed_for_every_role(
    client: object, role_users: dict[str, User], make_item: object, role: str
) -> None:
    """PS 12 RBAC: all five authenticated roles may read the stock summary."""
    item = make_item()  # type: ignore[operator]
    post_opening_balance(item_id=item.pk, qty="100", unit_cost="42")
    _login(client, role_users[role])

    response = client.get(reverse("inventory-stock-summary"))  # type: ignore[attr-defined]

    assert response.status_code == 200
    row = next(row for row in response.json() if row["item_id"] == item.pk)
    assert row["item_name"] == "Flour"
    assert row["uom"] == "kg"
    assert row["qty"] == "100.000"
    assert row["value"] == "4200.00"
    assert row["avg_rate"] == "42.0000"


def test_stock_summary_denies_anonymous(client: object) -> None:
    """PS 12 RBAC: deny-by-default, unauthenticated reads are refused."""
    response = client.get(reverse("inventory-stock-summary"))  # type: ignore[attr-defined]
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role", [Role.ADMIN, Role.PRODUCTION, Role.ACCOUNTANT, Role.OWNER])
def test_ledger_allowed_for_read_roles(
    client: object, role_users: dict[str, User], make_item: object, role: str
) -> None:
    """PS 12 RBAC: admin, production, accountant and owner may read the ledger."""
    item = make_item()  # type: ignore[operator]
    post_opening_balance(item_id=item.pk, qty="10", unit_cost="2")
    _login(client, role_users[role])

    response = client.get(reverse("inventory-ledger") + f"?item={item.pk}")

    assert response.status_code == 200
    entries = response.json()
    assert len(entries) == 1
    assert entries[0]["movement_type"] == "OPENING"
    assert entries[0]["source_type"] == "opening"
    assert entries[0]["source_id"] == item.pk
    assert entries[0]["qty"] == "10.000"


def test_ledger_denies_salesman(
    client: object, role_users: dict[str, User], make_item: object
) -> None:
    """PS 12 RBAC: a salesman cannot browse the full stock ledger."""
    _login(client, role_users[Role.SALESMAN])
    response = client.get(reverse("inventory-ledger"))
    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"


def test_ledger_filters_by_item_and_date(
    client: object, role_users: dict[str, User], make_item: object
) -> None:
    """PS 1 API: ledger supports item and date-range filters."""
    flour = make_item()  # type: ignore[operator]
    oil = make_item(name="Cooking oil", uom_symbol="L")  # type: ignore[operator]
    post_opening_balance(item_id=flour.pk, qty="10", unit_cost="42")
    post_opening_balance(item_id=oil.pk, qty="5", unit_cost="140")
    _login(client, role_users[Role.ADMIN])

    by_item = client.get(reverse("inventory-ledger") + f"?item={flour.pk}")  # type: ignore[attr-defined]
    assert [entry["item_id"] for entry in by_item.json()] == [flour.pk]

    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    future = client.get(reverse("inventory-ledger") + f"?date_from={tomorrow}")  # type: ignore[attr-defined]
    assert future.json() == []

    invalid = client.get(reverse("inventory-ledger") + "?date_to=not-a-date")  # type: ignore[attr-defined]
    assert invalid.status_code == 400


# ---------------------------------------------------------------------------
# Stock adjustment
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role", [Role.ADMIN, Role.PRODUCTION, Role.OWNER])
def test_adjustment_allowed_for_stock_roles(
    client: object, role_users: dict[str, User], make_item: object, role: str
) -> None:
    """PS 12 RBAC: admin, production and owner may post an adjustment."""
    item = make_item()  # type: ignore[operator]
    post_opening_balance(item_id=item.pk, qty="10", unit_cost="2")
    _login(client, role_users[role])

    response = client.post(  # type: ignore[attr-defined]
        reverse("inventory-adjustment-create"),
        data={"item": item.pk, "qty_delta": "-1", "reason": "Damaged in storage"},
        content_type="application/json",
    )

    assert response.status_code == 201
    body = response.json()
    assert body["qty_delta"] == "-1.000"
    assert body["reason"] == "Damaged in storage"

    adjustment = StockAdjustment.objects.get(pk=body["id"])
    entry = StockLedger.objects.get(source_type="adjustment", source_id=adjustment.pk)
    assert entry.created_by_id == role_users[role].pk
    assert entry.qty == Decimal("-1.000")


@pytest.mark.parametrize("role", [Role.SALESMAN, Role.ACCOUNTANT])
def test_adjustment_denied_for_read_or_sales_roles(
    client: object, role_users: dict[str, User], make_item: object, role: str
) -> None:
    """PS 12 RBAC: salesman and accountant cannot mutate stock."""
    item = make_item()  # type: ignore[operator]
    post_opening_balance(item_id=item.pk, qty="10", unit_cost="2")
    _login(client, role_users[role])

    response = client.post(  # type: ignore[attr-defined]
        reverse("inventory-adjustment-create"),
        data={"item": item.pk, "qty_delta": "-1", "reason": "Sneaky"},
        content_type="application/json",
    )

    assert response.status_code == 403
    assert StockAdjustment.objects.count() == 0


def test_adjustment_over_issue_returns_insufficient_stock(
    client: object, role_users: dict[str, User], make_item: object
) -> None:
    """PS 12 negative path: over-issue is a 400 with a machine-readable code."""
    item = make_item()  # type: ignore[operator]
    post_opening_balance(item_id=item.pk, qty="1", unit_cost="2")
    _login(client, role_users[Role.ADMIN])
    ledger_count = StockLedger.objects.count()

    response = client.post(  # type: ignore[attr-defined]
        reverse("inventory-adjustment-create"),
        data={"item": item.pk, "qty_delta": "-5", "reason": "Stock take"},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["code"] == "insufficient_stock"
    assert StockLedger.objects.count() == ledger_count


def test_adjustment_zero_quantity_and_blank_reason_are_rejected(
    client: object, role_users: dict[str, User], make_item: object
) -> None:
    """PS 12 negative paths: zero quantity and blank reason are 400s."""
    item = make_item()  # type: ignore[operator]
    post_opening_balance(item_id=item.pk, qty="10", unit_cost="2")
    _login(client, role_users[Role.ADMIN])

    zero = client.post(  # type: ignore[attr-defined]
        reverse("inventory-adjustment-create"),
        data={"item": item.pk, "qty_delta": "0", "reason": "No change"},
        content_type="application/json",
    )
    assert zero.status_code == 400
    assert zero.json()["code"] == "invalid_movement"

    blank = client.post(  # type: ignore[attr-defined]
        reverse("inventory-adjustment-create"),
        data={"item": item.pk, "qty_delta": "1", "reason": ""},
        content_type="application/json",
    )
    assert blank.status_code == 400


def test_adjustment_unknown_item_is_rejected(client: object, role_users: dict[str, User]) -> None:
    """PS 12 negative path: an unknown item id is a validation error."""
    _login(client, role_users[Role.ADMIN])

    response = client.post(  # type: ignore[attr-defined]
        reverse("inventory-adjustment-create"),
        data={"item": 999_999, "qty_delta": "1", "reason": "Mystery"},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert "item" in response.json()


def test_adjustment_requires_authentication(client: object, make_item: object) -> None:
    """PS 12 RBAC: anonymous adjustments are refused."""
    item = make_item()  # type: ignore[operator]
    response = client.post(  # type: ignore[attr-defined]
        reverse("inventory-adjustment-create"),
        data={"item": item.pk, "qty_delta": "1", "reason": "Anon"},
        content_type="application/json",
    )
    assert response.status_code == 403
