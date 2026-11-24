"""API tests for Phase 6 – Leakage Radar, Loop Closer and Benchmark Console.

Requirement: AGENTS.md Section 5 – every endpoint tested for its allowed roles
and at least one denied role, Decimal output as strings, and the benchmark run
leaving no data behind.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.costing.services import record_run_overhead
from apps.inventory.models import StockBalance
from apps.inventory.services import PurchaseLineInput, create_purchase
from apps.masters.models import Customer, Item, Supplier
from apps.production.models import ProductionRun
from apps.production.services import complete_run, create_run, issue_run
from apps.sales.models import Invoice
from apps.sales.services import (
    DispatchLineInput,
    OrderLineInput,
    approve_order,
    create_invoice,
    create_order,
    dispatch_invoice,
)

pytestmark = pytest.mark.django_db


def _login(client: object, username: str) -> None:
    client.force_login(User.objects.get(username=username))  # type: ignore[attr-defined]


@pytest.fixture
def scenario(db: None) -> dict[str, object]:
    """Appendix A steps 1-6 plus overheads: a completed run, an invoice and a shortage."""
    call_command("seed_benchmark", stdout=StringIO())

    flour = Item.objects.get(name="Flour")
    product = Item.objects.get(name="Murukku 200 g")
    admin = User.objects.get(username="admin")
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
    complete_run(run=run, good_packets="188", damaged_pouches="6", cartons_used="9")
    record_run_overhead(run=run, category="labour", amount="1200", description="Labour")
    record_run_overhead(run=run, category="power", amount="600", description="Gas and power")

    order = create_order(
        customer=Customer.objects.get(name="Retailer A"),
        lines=[OrderLineInput(item_id=product.pk, qty=Decimal("150"))],
        client_uuid=uuid.uuid4(),
        salesman=User.objects.get(username="salesman_a"),
    ).order
    approve_order(order=order, user=admin)
    invoice = create_invoice(order=order, user=admin)
    dispatch_invoice(
        invoice=invoice,
        lines=[DispatchLineInput(invoice_line_id=invoice.lines.get().pk, qty="150")],
        user=admin,
    )

    blocked = create_order(
        customer=Customer.objects.get(name="Distributor B"),
        lines=[OrderLineInput(item_id=product.pk, qty=Decimal("120"))],
        client_uuid=uuid.uuid4(),
        salesman=User.objects.get(username="salesman_b"),
    ).order

    return {
        "run": ProductionRun.objects.get(pk=run.pk),
        "product": product,
        "blocked": blocked,
    }


@pytest.mark.parametrize("role", [Role.PRODUCTION, Role.ADMIN, Role.ACCOUNTANT, Role.OWNER])
def test_report_card_is_readable_by_staff_roles(client: object, scenario: dict, role: str) -> None:
    """PS 12 RBAC: production, admin, accountant and owner read the card."""
    _login(client, role)
    run = scenario["run"]

    response = client.get(reverse("production-run-report-card", args=[run.pk]))  # type: ignore[attr-defined]

    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["standard_materials"] == "3970.00"
    assert body["actual_materials"] == "4055.00"
    assert body["material_impact"] == "85.00"
    assert body["cost_per_packet"] == "31.14"
    assert body["yield_gap"]["unexplained_packets"] == "6.000"
    assert body["bridge"][-1]["cumulative"] == "31.14"
    assert isinstance(body["lines"][0]["actual_rate"], str)


def test_report_card_denies_salesman(client: object, scenario: dict) -> None:
    """PS 12 RBAC: a salesman cannot read the production report card."""
    _login(client, "salesman_a")
    run = scenario["run"]

    response = client.get(reverse("production-run-report-card", args=[run.pk]))  # type: ignore[attr-defined]

    assert response.status_code == 403


def test_report_card_for_a_draft_run_is_a_400(client: object, scenario: dict) -> None:
    """PS 2.1 negative path: a draft run has no report card."""
    _login(client, "admin")
    draft = create_run(product=scenario["product"], batches="1")

    response = client.get(  # type: ignore[attr-defined]
        reverse("production-run-report-card", args=[draft.pk])
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_run_state"


def test_product_leakage_trends_endpoint(client: object, scenario: dict) -> None:
    """PS 2.2: trends and drift alerts are served for the product."""
    _login(client, "admin")
    product = scenario["product"]

    response = client.get(  # type: ignore[attr-defined]
        reverse("production-product-leakage", args=[product.pk])
    )

    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["product_name"] == "Murukku 200 g"
    assert len(body["runs"]) == 1
    assert body["drift_alerts"] == []
    oil = next(row for row in body["ingredients"] if row["item_name"] == "Cooking oil")
    assert oil["points"][0]["variance_pct"] == "0.050000"


def test_product_leakage_denies_salesman_and_404s_unknown(client: object, scenario: dict) -> None:
    """PS 12 / Phase 6 negative paths: salesman denied, unknown product 404."""
    product = scenario["product"]
    _login(client, "salesman_a")
    denied = client.get(  # type: ignore[attr-defined]
        reverse("production-product-leakage", args=[product.pk])
    )
    assert denied.status_code == 403

    _login(client, "admin")
    missing = client.get(  # type: ignore[attr-defined]
        reverse("production-product-leakage", args=[999_999])
    )
    assert missing.status_code == 404


def test_order_coverage_carries_the_loop_closer(client: object, scenario: dict) -> None:
    """PS 2.3: Distributor B shows shortage 32 and one feasible batch."""
    _login(client, "admin")
    blocked = scenario["blocked"]

    response = client.get(reverse("sales-order-coverage", args=[blocked.pk]))  # type: ignore[attr-defined]

    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["total_shortage_qty"] == "32.000"
    assert len(body["loop_closers"]) == 1
    plan = body["loop_closers"][0]
    assert plan["batches_needed"] == 1
    assert plan["batches_allowed"] == 1
    assert plan["feasible"] is True
    assert plan["limiting_item"] == "200 g pouch"
    assert plan["verdict"] == "feasible"
    assert plan["purchase_list"] == []


def test_loop_closer_is_visible_only_to_coverage_roles(client: object, scenario: dict) -> None:
    """PS 12 RBAC: the salesman who placed the order cannot read coverage."""
    _login(client, "salesman_b")
    blocked = scenario["blocked"]

    response = client.get(reverse("sales-order-coverage", args=[blocked.pk]))  # type: ignore[attr-defined]

    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Benchmark Console
# ---------------------------------------------------------------------------


def test_benchmark_console_passes_and_leaves_no_data(client: object, scenario: dict) -> None:
    """Phase 6a: all Appendix A checks pass and the run is rolled back."""
    _login(client, "admin")
    flour_before = StockBalance.objects.get(item=Item.objects.get(name="Flour")).qty
    runs_before = ProductionRun.objects.count()
    invoices_before = Invoice.objects.count()

    response = client.post(reverse("benchmark-run"))  # type: ignore[attr-defined]

    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["ok"] is True
    assert body["failed"] == 0
    assert body["passed"] == len(body["checks"])
    assert len(body["checks"]) >= 40
    assert {check["name"] for check in body["checks"]} >= {
        "Flour closing",
        "Retailer A invoice total",
        "Cost per packet",
        "Bridge yield shortfall",
        "Loop Closer batches needed",
    }

    # The scenario's transaction was rolled back: no benchmark data survives.
    assert StockBalance.objects.get(item=Item.objects.get(name="Flour")).qty == flour_before
    assert ProductionRun.objects.count() == runs_before
    assert Invoice.objects.count() == invoices_before


@pytest.mark.parametrize("role", [Role.OWNER])
def test_benchmark_console_allows_owner(client: object, scenario: dict, role: str) -> None:
    """Phase 6a RBAC: the owner may run the console."""
    _login(client, role)

    response = client.post(reverse("benchmark-run"))  # type: ignore[attr-defined]

    assert response.status_code == 200, response.json()
    assert response.json()["ok"] is True, [
        check for check in response.json()["checks"] if not check["passed"]
    ]


@override_settings(ENABLE_BENCHMARK_TOOLS=False)
def test_benchmark_console_is_absent_in_production(client: object, scenario: dict) -> None:
    """Production hardening: the test console is not a deployed feature."""
    _login(client, "admin")

    response = client.post(reverse("benchmark-run"))  # type: ignore[attr-defined]

    assert response.status_code == 404


@pytest.mark.parametrize("username", ["salesman_a", "production", "accountant"])
def test_benchmark_console_denies_other_roles(
    client: object, scenario: dict, username: str
) -> None:
    """Phase 6a RBAC: only admin and owner can run the console."""
    _login(client, username)

    response = client.post(reverse("benchmark-run"))  # type: ignore[attr-defined]

    assert response.status_code == 403
