"""API tests for Phase 7 – offline order review and low-stock alerts.

Requirement: AGENTS.md Section 5 (role matrix, Decimal output as strings) and
the Phase 7 exit gate. These cover the two server-side pieces the offline
salesman screen relies on: the price-list-change flag on order coverage and
the master reorder level behind the dashboard's low-stock widget.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.inventory.services import post_opening_balance
from apps.masters.models import Customer, Item, PriceList
from apps.masters.services import create_item, set_price
from apps.sales.services import OrderLineInput, create_order

pytestmark = pytest.mark.django_db


def _login(client: object, username: str) -> None:
    client.force_login(User.objects.get(username=username))  # type: ignore[attr-defined]


@pytest.fixture
def submitted_order(db: None) -> dict[str, object]:
    """Seed the benchmark and take Retailer A's 150-packet order."""
    call_command("seed_benchmark", stdout=StringIO())
    product = Item.objects.get(name="Murukku 200 g")
    order = create_order(
        customer=Customer.objects.get(name="Retailer A"),
        lines=[OrderLineInput(item_id=product.pk, qty=Decimal("150"))],
        client_uuid=uuid.uuid4(),
        salesman=User.objects.get(username="salesman_a"),
    ).order
    return {"order": order, "product": product}


def test_coverage_reports_no_price_change_at_the_snapshotted_price(
    client: object, submitted_order: dict
) -> None:
    """PS 3 offline: an order priced from today's list is not flagged."""
    _login(client, "admin")
    order = submitted_order["order"]

    response = client.get(reverse("sales-order-coverage", args=[order.pk]))  # type: ignore[attr-defined]

    assert response.status_code == 200, response.json()
    line = response.json()["lines"][0]
    assert line["current_price"] == "50.00"
    assert line["price_changed"] is False


def test_coverage_flags_a_price_list_change_after_the_order(
    client: object, submitted_order: dict
) -> None:
    """PS 3 offline: the admin sees that the price list moved since the order."""
    _login(client, "admin")
    order = submitted_order["order"]
    product = submitted_order["product"]
    set_price(
        price_list=PriceList.objects.get(name="Standard 2026-27"),
        item=product,
        price=Decimal("55.00"),
    )

    response = client.get(reverse("sales-order-coverage", args=[order.pk]))  # type: ignore[attr-defined]

    assert response.status_code == 200, response.json()
    line = response.json()["lines"][0]
    assert line["price_changed"] is True
    assert line["current_price"] == "55.00"
    # The order keeps the price it was taken at; nothing repricing silently.
    assert line["ordered_qty"] == "150.000"
    assert str(order.lines.get().unit_price) == "50.00"


def test_price_change_flag_is_readable_by_staff_and_denied_to_the_salesman(
    client: object, submitted_order: dict
) -> None:
    """PS 12 RBAC: coverage is an admin review screen, not a salesman one."""
    order = submitted_order["order"]

    url = reverse("sales-order-coverage", args=[order.pk])

    _login(client, "accountant")
    assert client.get(url).status_code == 200  # type: ignore[attr-defined]

    _login(client, "salesman_a")
    assert client.get(url).status_code == 403  # type: ignore[attr-defined]


def test_dashboard_uses_the_master_reorder_level(client: object, db: None) -> None:
    """PS 9 low stock: an explicit reorder level drives the alert and quantity."""
    call_command("seed_benchmark", stdout=StringIO())
    create_item(
        name="Chilli powder",
        item_type="RAW",
        uom_symbol="kg",
        hsn_code="0904",
        gst_rate="5.00",
        reorder_level=Decimal("5"),
    )
    chilli = Item.objects.get(name="Chilli powder")
    post_opening_balance(item_id=chilli.pk, qty=Decimal("2"), unit_cost=Decimal("300"))

    _login(client, "admin")
    response = client.get(reverse("reports-dashboard"))  # type: ignore[attr-defined]

    assert response.status_code == 200, response.json()
    row = next(row for row in response.json()["stock"] if row["item_name"] == "Chilli powder")
    assert row["reorder_level"] == "5.000"
    assert row["reorder"] is True
    assert row["reorder_qty"] == "3.000"
    assert response.json()["reorder_count"] == 1


def test_dashboard_seeded_reorder_levels_do_not_flag_benchmark_stock(
    client: object, db: None
) -> None:
    """PS 9 low stock: every Appendix A closing is above its one-batch level."""
    call_command("seed_benchmark", stdout=StringIO())

    _login(client, "owner")
    response = client.get(reverse("reports-dashboard"))  # type: ignore[attr-defined]

    assert response.status_code == 200
    body = response.json()
    assert body["reorder_count"] == 0
    flour = next(row for row in body["stock"] if row["item_name"] == "Flour")
    assert flour["reorder_level"] == "40.000"
    assert isinstance(flour["reorder_level"], str)


@pytest.mark.parametrize("role", [Role.ADMIN, Role.ACCOUNTANT, Role.OWNER])
def test_low_stock_dashboard_is_staff_only(client: object, db: None, role: str) -> None:
    """PS 12 RBAC: the dashboard stays with admin, accountant and owner."""
    call_command("seed_benchmark", stdout=StringIO())
    _login(client, role)
    assert client.get(reverse("reports-dashboard")).status_code == 200  # type: ignore[attr-defined]

    _login(client, "salesman_a")
    assert client.get(reverse("reports-dashboard")).status_code == 403  # type: ignore[attr-defined]
