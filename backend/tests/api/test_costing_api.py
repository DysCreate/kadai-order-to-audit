"""API tests for Phase 4 costing endpoints.

Requirement: AGENTS.md Section 5 – every endpoint tested for each allowed role
and at least one denied role, with Decimal values serialised as strings.
"""

from datetime import date
from io import StringIO

import pytest
from django.core.management import call_command
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.inventory.services import PurchaseLineInput, create_purchase
from apps.masters.models import Item, Supplier
from apps.production.services import complete_run, create_run, issue_run

pytestmark = pytest.mark.django_db


def _login(client: object, user: User) -> None:
    client.force_login(user)  # type: ignore[attr-defined]


@pytest.fixture
def completed(db: None) -> dict[str, Item]:
    """Seed Appendix A and complete the benchmark run."""
    call_command("seed_benchmark", stdout=StringIO())
    flour = Item.objects.get(name="Flour")
    product = Item.objects.get(name="Murukku 200 g")
    create_purchase(
        supplier=Supplier.objects.get(name="Sri Lakshmi Flour Mills"),
        lines=[PurchaseLineInput(item_id=flour.pk, qty="60", unit_cost="45")],
    )
    run = create_run(product=product, batches="1")
    lines = {line.item.name: line for line in run.lines.select_related("item")}
    issue_run(
        run=run,
        issued={
            lines["Flour"].pk: "40",
            lines["Cooking oil"].pk: "10.5",
            lines["Salt and spice mix"].pk: "1.2",
        },
    )
    run = complete_run(run=run, good_packets="188", damaged_pouches="6", cartons_used="9")
    return {"run": run, "product": product}


@pytest.mark.parametrize("role", [Role.PRODUCTION, Role.ADMIN, Role.ACCOUNTANT, Role.OWNER])
def test_cost_sheet_allowed_for_read_roles(
    client: object,
    role_users: dict[str, User],
    completed: dict[str, Item],
    role: str,
) -> None:
    """PS 12 RBAC: production, admin, accountant and owner may read a cost sheet."""
    _login(client, role_users[role])
    run = completed["run"]

    response = client.get(reverse("costing-run-cost-sheet", args=[run.pk]))  # type: ignore[attr-defined]

    assert response.status_code == 200
    body = response.json()
    assert body["materials_value"] == "4055.00"
    assert body["overhead_value"] == "0.00"
    assert body["cost_per_packet"] == "21.57"
    assert body["margin_per_packet"] == "28.43"
    assert isinstance(body["materials_value"], str)


def test_cost_sheet_denied_for_salesman(
    client: object, role_users: dict[str, User], completed: dict[str, Item]
) -> None:
    """PS 12 RBAC: a salesman cannot read production costs."""
    _login(client, role_users[Role.SALESMAN])
    run = completed["run"]

    response = client.get(reverse("costing-run-cost-sheet", args=[run.pk]))  # type: ignore[attr-defined]

    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"


@pytest.mark.parametrize("role", [Role.PRODUCTION, Role.ADMIN, Role.OWNER])
def test_run_overhead_allowed_for_production_roles(
    client: object,
    role_users: dict[str, User],
    completed: dict[str, Item],
    role: str,
) -> None:
    """PS 12 RBAC: production, admin and owner may add a run overhead."""
    _login(client, role_users[role])
    run = completed["run"]

    response = client.post(  # type: ignore[attr-defined]
        reverse("costing-run-overhead", args=[run.pk]),
        data={"category": "labour", "amount": "1200", "description": "Labour"},
        content_type="application/json",
    )

    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["overhead_value"] == "1200.00"
    assert body["total_cost"] == "5255.00"
    assert body["cost_per_packet"] == "27.95"


@pytest.mark.parametrize("role", [Role.ACCOUNTANT, Role.SALESMAN])
def test_run_overhead_denied_for_read_roles(
    client: object,
    role_users: dict[str, User],
    completed: dict[str, Item],
    role: str,
) -> None:
    """PS 12 RBAC: accountant and salesman cannot write overheads."""
    _login(client, role_users[role])
    run = completed["run"]

    response = client.post(  # type: ignore[attr-defined]
        reverse("costing-run-overhead", args=[run.pk]),
        data={"category": "labour", "amount": "1200"},
        content_type="application/json",
    )

    assert response.status_code == 403


def test_run_overhead_validates_amount_and_state(
    client: object, role_users: dict[str, User], completed: dict[str, Item]
) -> None:
    """PS 4.3 negative paths: zero amount and a draft run are rejected."""
    _login(client, role_users[Role.PRODUCTION])
    run = completed["run"]

    zero = client.post(  # type: ignore[attr-defined]
        reverse("costing-run-overhead", args=[run.pk]),
        data={"category": "labour", "amount": "0"},
        content_type="application/json",
    )
    assert zero.status_code == 400

    draft = create_run(product=completed["product"], batches="1")
    wrong_state = client.post(  # type: ignore[attr-defined]
        reverse("costing-run-overhead", args=[draft.pk]),
        data={"category": "labour", "amount": "100"},
        content_type="application/json",
    )
    assert wrong_state.status_code == 400
    assert wrong_state.json()["code"] == "invalid_run_state"

    no_sheet = client.get(reverse("costing-run-cost-sheet", args=[draft.pk]))  # type: ignore[attr-defined]
    assert no_sheet.status_code == 400
    assert no_sheet.json()["code"] == "invalid_run_state"


@pytest.mark.parametrize("role", [Role.PRODUCTION, Role.ADMIN, Role.ACCOUNTANT, Role.OWNER])
def test_monthly_overheads_read_allowed(
    client: object, role_users: dict[str, User], completed: dict[str, Item], role: str
) -> None:
    """PS 12 RBAC: the monthly pool is readable by all costing read roles."""
    _login(client, role_users[role])

    response = client.get(reverse("costing-monthly-overheads"))  # type: ignore[attr-defined]

    assert response.status_code == 200
    assert response.json()["total"] == "0.00"
    assert response.json()["entries"] == []


@pytest.mark.parametrize("role", [Role.PRODUCTION, Role.ADMIN, Role.OWNER])
def test_monthly_overhead_create_allowed(
    client: object, role_users: dict[str, User], completed: dict[str, Item], role: str
) -> None:
    """PS 12 RBAC: production, admin and owner may add a monthly pool entry."""
    _login(client, role_users[role])

    response = client.post(  # type: ignore[attr-defined]
        reverse("costing-monthly-overheads"),
        data={
            "period": date.today().isoformat(),
            "category": "power",
            "amount": "1000",
            "description": "Factory power",
        },
        content_type="application/json",
    )

    assert response.status_code == 201
    assert response.json()["scope"] == "MONTH"
    assert response.json()["amount"] == "1000.00"
    assert response.json()["period"] == date.today().replace(day=1).isoformat()


def test_monthly_overhead_create_denied_for_accountant(
    client: object, role_users: dict[str, User], completed: dict[str, Item]
) -> None:
    """PS 12 RBAC: the accountant is read-only."""
    _login(client, role_users[Role.ACCOUNTANT])

    response = client.post(  # type: ignore[attr-defined]
        reverse("costing-monthly-overheads"),
        data={"period": date.today().isoformat(), "category": "power", "amount": "1000"},
        content_type="application/json",
    )

    assert response.status_code == 403


@pytest.mark.parametrize("role", [Role.ADMIN, Role.OWNER])
def test_monthly_overhead_allocation_allowed(
    client: object, role_users: dict[str, User], completed: dict[str, Item], role: str
) -> None:
    """PS 12 RBAC: admin and owner may post a monthly allocation."""
    _login(client, role_users[role])
    client.post(  # type: ignore[attr-defined]
        reverse("costing-monthly-overheads"),
        data={"period": date.today().isoformat(), "category": "power", "amount": "1000"},
        content_type="application/json",
    )

    response = client.post(  # type: ignore[attr-defined]
        reverse("costing-monthly-overheads-allocate"),
        data={"period": date.today().isoformat()},
        content_type="application/json",
    )

    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["count"] == 1
    assert body["allocations"][0]["amount"] == "1000.00"
    assert body["allocations"][0]["run_id"] == completed["run"].pk


def test_monthly_overhead_allocation_denied_for_production(
    client: object, role_users: dict[str, User], completed: dict[str, Item]
) -> None:
    """PS 12 RBAC: production cannot post stock value through allocation."""
    _login(client, role_users[Role.PRODUCTION])
    client.post(  # type: ignore[attr-defined]
        reverse("costing-monthly-overheads"),
        data={"period": date.today().isoformat(), "category": "power", "amount": "1000"},
        content_type="application/json",
    )

    response = client.post(  # type: ignore[attr-defined]
        reverse("costing-monthly-overheads-allocate"),
        data={"period": date.today().isoformat()},
        content_type="application/json",
    )

    assert response.status_code == 403


def test_costing_reads_denied_for_salesman(
    client: object, role_users: dict[str, User], completed: dict[str, Item]
) -> None:
    """PS 12 RBAC: a salesman cannot read monthly pools or product costs."""
    _login(client, role_users[Role.SALESMAN])

    monthly = client.get(reverse("costing-monthly-overheads"))  # type: ignore[attr-defined]
    product = client.get(  # type: ignore[attr-defined]
        reverse("costing-product-cost", args=[completed["product"].pk])
    )

    assert monthly.status_code == 403
    assert product.status_code == 403


def test_monthly_allocation_empty_month_is_a_domain_error(
    client: object, role_users: dict[str, User], completed: dict[str, Item]
) -> None:
    """Phase 4 negative path: allocating a month with no pool returns 400."""
    _login(client, role_users[Role.ADMIN])

    response = client.post(  # type: ignore[attr-defined]
        reverse("costing-monthly-overheads-allocate"),
        data={"period": "2020-01-01"},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["code"] == "domain_error"


@pytest.mark.parametrize("role", [Role.PRODUCTION, Role.ADMIN, Role.ACCOUNTANT, Role.OWNER])
def test_product_cost_allowed_for_read_roles(
    client: object, role_users: dict[str, User], completed: dict[str, Item], role: str
) -> None:
    """PS 12 RBAC: FG weighted-average cost is readable by costing roles."""
    _login(client, role_users[role])
    product = completed["product"]

    response = client.get(reverse("costing-product-cost", args=[product.pk]))  # type: ignore[attr-defined]

    assert response.status_code == 200
    body = response.json()
    assert body["stock_qty"] == "238.000"
    assert body["avg_cost"] == "21.2080"
    assert body["selling_price"] == "50.00"
    assert body["margin_per_packet"] == "28.79"
