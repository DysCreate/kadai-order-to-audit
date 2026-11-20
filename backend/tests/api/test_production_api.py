"""API tests for the Phase 2 production and purchase endpoints.

Requirement: AGENTS.md Section 5 – every endpoint tested for each allowed role
and at least one denied role, plus negative paths and Decimal-as-string output.
"""

from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.inventory.models import MovementType, StockBalance, StockLedger
from apps.masters.models import Item, Supplier
from apps.production.models import ProductionRun, RunState

pytestmark = pytest.mark.django_db


def _login(client: object, user: User) -> None:
    client.force_login(user)  # type: ignore[attr-defined]


@pytest.fixture
def seeded(db: None) -> None:
    """Appendix A master data (items, prices, BOM and opening stock)."""
    call_command("seed_benchmark", stdout=StringIO())


def _create_run(client: object) -> dict[str, object]:
    product = Item.objects.get(name="Murukku 200 g")
    response = client.post(  # type: ignore[attr-defined]
        reverse("production-run-list"),
        data={"product": product.pk, "batches": "1"},
        content_type="application/json",
    )
    assert response.status_code == 201, response.json()
    return response.json()


# ---------------------------------------------------------------------------
# BOM
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role", [Role.PRODUCTION, Role.ADMIN, Role.ACCOUNTANT, Role.OWNER])
def test_bom_list_allowed_for_read_roles(
    client: object, role_users: dict[str, User], seeded: None, role: str
) -> None:
    """PS 12 RBAC: production, admin, accountant and owner may read BOMs."""
    _login(client, role_users[role])

    response = client.get(reverse("production-bom-list"))  # type: ignore[attr-defined]

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["product_name"] == "Murukku 200 g"
    assert body[0]["version"] == 1
    assert body[0]["batch_output_qty"] == "200.000"
    assert {line["role"] for line in body[0]["lines"]} == {"material", "pouch", "carton"}


def test_bom_list_denies_salesman(
    client: object, role_users: dict[str, User], seeded: None
) -> None:
    """PS 12 RBAC: a salesman cannot browse the bill of materials."""
    _login(client, role_users[Role.SALESMAN])

    response = client.get(reverse("production-bom-list"))  # type: ignore[attr-defined]

    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"


@pytest.mark.parametrize("role", [Role.PRODUCTION, Role.ADMIN, Role.OWNER])
def test_bom_create_allowed_for_production_roles(
    client: object, role_users: dict[str, User], seeded: None, role: str
) -> None:
    """PS 12 RBAC: production, admin and owner may add a BOM version."""
    _login(client, role_users[role])
    product = Item.objects.get(name="Murukku 200 g")
    flour = Item.objects.get(name="Flour")

    response = client.post(  # type: ignore[attr-defined]
        reverse("production-bom-list"),
        data={
            "product": product.pk,
            "batch_output_qty": "250.000",
            "lines": [{"item": flour.pk, "qty_per_batch": "50.000"}],
        },
        content_type="application/json",
    )

    assert response.status_code == 201
    assert response.json()["version"] == 2
    assert response.json()["batch_output_qty"] == "250.000"
    assert response.json()["lines"][0]["qty_per_batch"] == "50.000"


def test_bom_create_denied_for_accountant(
    client: object, role_users: dict[str, User], seeded: None
) -> None:
    """PS 12 RBAC: the accountant is read-only and cannot add a BOM version."""
    _login(client, role_users[Role.ACCOUNTANT])
    product = Item.objects.get(name="Murukku 200 g")

    response = client.post(  # type: ignore[attr-defined]
        reverse("production-bom-list"),
        data={"product": product.pk, "batch_output_qty": "250", "lines": []},
        content_type="application/json",
    )

    assert response.status_code == 403


def test_bom_create_validates_input(
    client: object, role_users: dict[str, User], seeded: None
) -> None:
    """PS 4.7 negative paths: empty lines and unknown items are 400s."""
    _login(client, role_users[Role.PRODUCTION])
    product = Item.objects.get(name="Murukku 200 g")

    empty = client.post(  # type: ignore[attr-defined]
        reverse("production-bom-list"),
        data={"product": product.pk, "batch_output_qty": "250", "lines": []},
        content_type="application/json",
    )
    assert empty.status_code == 400

    unknown = client.post(  # type: ignore[attr-defined]
        reverse("production-bom-list"),
        data={
            "product": product.pk,
            "batch_output_qty": "250",
            "lines": [{"item": 999_999, "qty_per_batch": "1"}],
        },
        content_type="application/json",
    )
    assert unknown.status_code == 400


# ---------------------------------------------------------------------------
# Production runs
# ---------------------------------------------------------------------------


def test_run_lifecycle_over_the_api(
    client: object, role_users: dict[str, User], seeded: None
) -> None:
    """PS 5 production: create, issue, complete, and read the variance snapshot."""
    _login(client, role_users[Role.PRODUCTION])
    run = _create_run(client)
    run_id = run["id"]
    assert run["state"] == "DRAFT"
    assert run["tolerance"] == "0.03"
    assert run["planned_output_qty"] == "200.000"

    lines = {line["item_name"]: line for line in run["lines"]}
    issue = client.post(  # type: ignore[attr-defined]
        reverse("production-run-issue", args=[run_id]),
        data={
            "lines": [
                {"line": lines["Flour"]["id"], "qty": "40"},
                {"line": lines["Cooking oil"]["id"], "qty": "10.5"},
                {"line": lines["Salt and spice mix"]["id"], "qty": "1.2"},
            ]
        },
        content_type="application/json",
    )
    assert issue.status_code == 200, issue.json()
    assert issue.json()["state"] == "ISSUED"
    assert issue.json()["lines"][0]["issued_qty"] == "40.000"

    complete = client.post(  # type: ignore[attr-defined]
        reverse("production-run-complete", args=[run_id]),
        data={"good_packets": "188", "damaged_pouches": "6", "cartons_used": "9"},
        content_type="application/json",
    )
    assert complete.status_code == 200, complete.json()

    detail = client.get(reverse("production-run-detail", args=[run_id]))  # type: ignore[attr-defined]
    body = detail.json()
    assert body["state"] == "COMPLETED"
    assert body["good_packets"] == "188.000"

    variance = {row["item_name"]: row for row in body["variance"]}
    assert variance["Murukku 200 g (yield)"]["flagged"] is True
    assert variance["Murukku 200 g (yield)"]["variance_pct"] == "-0.060000"
    assert variance["Cooking oil"]["flagged"] is True
    assert variance["200 g pouch"]["flagged"] is False
    assert variance["200 g pouch"]["variance_pct"] == "-0.030000"
    assert variance["Carton (holds 20 packets)"]["direction"] == "favourable"

    # Decimals are strings, never floats.
    assert isinstance(variance["Cooking oil"]["actual_qty"], str)


@pytest.mark.parametrize("role", [Role.SALESMAN, Role.ACCOUNTANT])
def test_run_write_endpoints_denied_for_read_roles(
    client: object, role_users: dict[str, User], seeded: None, role: str
) -> None:
    """PS 12 RBAC: salesman and accountant cannot create or run production."""
    _login(client, role_users[Role.PRODUCTION])
    run_id = _create_run(client)["id"]
    _login(client, role_users[role])

    create = client.post(  # type: ignore[attr-defined]
        reverse("production-run-list"),
        data={"product": Item.objects.get(name="Murukku 200 g").pk, "batches": "1"},
        content_type="application/json",
    )
    issue = client.post(  # type: ignore[attr-defined]
        reverse("production-run-issue", args=[run_id]),
        data={"lines": []},
        content_type="application/json",
    )
    complete = client.post(  # type: ignore[attr-defined]
        reverse("production-run-complete", args=[run_id]),
        data={"good_packets": "10"},
        content_type="application/json",
    )

    assert [create.status_code, issue.status_code, complete.status_code] == [403, 403, 403]
    assert ProductionRun.objects.get(pk=run_id).state == RunState.DRAFT


def test_run_detail_denies_salesman(
    client: object, role_users: dict[str, User], seeded: None
) -> None:
    """PS 12 RBAC: a salesman cannot read the production floor's runs."""
    _login(client, role_users[Role.PRODUCTION])
    run_id = _create_run(client)["id"]
    _login(client, role_users[Role.SALESMAN])

    response = client.get(reverse("production-run-detail", args=[run_id]))  # type: ignore[attr-defined]

    assert response.status_code == 403


def test_completing_a_draft_run_is_a_domain_error(
    client: object, role_users: dict[str, User], seeded: None
) -> None:
    """PS 4.7 negative path: illegal transitions return 400 invalid_run_state."""
    _login(client, role_users[Role.PRODUCTION])
    run_id = _create_run(client)["id"]

    response = client.post(  # type: ignore[attr-defined]
        reverse("production-run-complete", args=[run_id]),
        data={"good_packets": "10"},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_run_state"


def test_issue_beyond_stock_is_a_400(
    client: object, role_users: dict[str, User], seeded: None
) -> None:
    """PS 4.11 negative path: over-issue returns insufficient_stock, no rows."""
    _login(client, role_users[Role.PRODUCTION])
    run = _create_run(client)
    flour_line = next(line for line in run["lines"] if line["item_name"] == "Flour")
    ledger_count = StockLedger.objects.count()

    response = client.post(  # type: ignore[attr-defined]
        reverse("production-run-issue", args=[run["id"]]),
        data={"lines": [{"line": flour_line["id"], "qty": "500"}]},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["code"] == "insufficient_stock"
    assert StockLedger.objects.count() == ledger_count


def test_amend_endpoint_reverses_and_returns_to_draft(
    client: object, role_users: dict[str, User], seeded: None
) -> None:
    """PS 4.10: amend reverses the issues and is audited; empty reason is a 400."""
    _login(client, role_users[Role.PRODUCTION])
    run = _create_run(client)
    client.post(  # type: ignore[attr-defined]
        reverse("production-run-issue", args=[run["id"]]),
        data={"lines": []},
        content_type="application/json",
    )
    issued_flour = StockBalance.objects.get(item=Item.objects.get(name="Flour")).qty
    assert issued_flour == Decimal("60.000")

    blank = client.post(  # type: ignore[attr-defined]
        reverse("production-run-amend", args=[run["id"]]),
        data={"reason": ""},
        content_type="application/json",
    )
    assert blank.status_code == 400

    response = client.post(  # type: ignore[attr-defined]
        reverse("production-run-amend", args=[run["id"]]),
        data={"reason": "Issued the wrong batch count"},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json()["state"] == "DRAFT"
    assert StockBalance.objects.get(item=Item.objects.get(name="Flour")).qty == Decimal("100.000")


def test_unknown_run_is_404(client: object, role_users: dict[str, User], seeded: None) -> None:
    """PS 5: a missing run is a 404, not a 500."""
    _login(client, role_users[Role.PRODUCTION])
    response = client.get(reverse("production-run-detail", args=[999_999]))  # type: ignore[attr-defined]
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Purchases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role", [Role.PRODUCTION, Role.ADMIN, Role.OWNER])
def test_purchase_allowed_for_stock_roles(
    client: object, role_users: dict[str, User], seeded: None, role: str
) -> None:
    """PS 12 RBAC: production, admin and owner may receive stock."""
    _login(client, role_users[role])
    flour = Item.objects.get(name="Flour")

    response = client.post(  # type: ignore[attr-defined]
        reverse("inventory-purchase-create"),
        data={
            "supplier": Supplier.objects.get(name="Sri Lakshmi Flour Mills").pk,
            "reference": "SLFM/0187",
            "lines": [{"item": flour.pk, "qty": "60", "unit_cost": "45"}],
        },
        content_type="application/json",
    )

    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["total_value"] == "2700.00"
    assert body["lines"][0]["qty"] == "60.000"
    assert body["lines"][0]["unit_cost"] == "45.0000"

    balance = StockBalance.objects.get(item=flour)
    assert balance.qty == Decimal("160.000")
    assert balance.value == Decimal("6900.00")
    assert StockLedger.objects.get(
        source_type="purchase", source_id=body["id"], movement_type=MovementType.RECEIPT
    ).qty == Decimal("60.000")


@pytest.mark.parametrize("role", [Role.SALESMAN, Role.ACCOUNTANT])
def test_purchase_denied_for_read_roles(
    client: object, role_users: dict[str, User], seeded: None, role: str
) -> None:
    """PS 12 RBAC: salesman and accountant cannot receive stock."""
    _login(client, role_users[role])
    flour = Item.objects.get(name="Flour")

    response = client.post(  # type: ignore[attr-defined]
        reverse("inventory-purchase-create"),
        data={
            "supplier": Supplier.objects.get(name="Sri Lakshmi Flour Mills").pk,
            "lines": [{"item": flour.pk, "qty": "1", "unit_cost": "1"}],
        },
        content_type="application/json",
    )

    assert response.status_code == 403


def test_purchase_validates_lines(
    client: object, role_users: dict[str, User], seeded: None
) -> None:
    """PS 5 negative paths: empty lines and zero quantity are 400s."""
    _login(client, role_users[Role.PRODUCTION])
    supplier = Supplier.objects.get(name="Sri Lakshmi Flour Mills").pk
    flour = Item.objects.get(name="Flour")

    empty = client.post(  # type: ignore[attr-defined]
        reverse("inventory-purchase-create"),
        data={"supplier": supplier, "lines": []},
        content_type="application/json",
    )
    zero = client.post(  # type: ignore[attr-defined]
        reverse("inventory-purchase-create"),
        data={"supplier": supplier, "lines": [{"item": flour.pk, "qty": "0", "unit_cost": "1"}]},
        content_type="application/json",
    )

    assert empty.status_code == 400
    assert zero.status_code == 400
