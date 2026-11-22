"""API tests for Phase 5 – reports, exports, reconciliation and dashboard.

Requirement: AGENTS.md Section 5 and the Phase 5 exit gate. The report figures
come from the same Appendix A scenario the benchmark uses; exports are loaded
back (csv, openpyxl) and the PDF is checked for its header.
"""

from __future__ import annotations

import csv
import uuid
from datetime import date
from decimal import Decimal
from io import BytesIO, StringIO

import pytest
from django.core.management import call_command
from django.urls import reverse
from openpyxl import load_workbook

from apps.accounts.models import User
from apps.costing.services import record_run_overhead
from apps.inventory.services import PurchaseLineInput, create_purchase
from apps.masters.models import Customer, Item, Supplier
from apps.payments.services import record_payment
from apps.production.models import ProductionRun
from apps.production.services import complete_run, create_run, issue_run
from apps.sales.services import (
    DispatchLineInput,
    OrderLineInput,
    approve_order,
    create_invoice,
    create_order,
    dispatch_invoice,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def scenario(db: None) -> dict[str, object]:
    """Run Appendix A steps 1-8 and return the documents the reports describe."""
    call_command("seed_benchmark", stdout=StringIO())

    flour = Item.objects.get(name="Flour")
    product = Item.objects.get(name="Murukku 200 g")
    create_purchase(
        supplier=Supplier.objects.get(name="Sri Lakshmi Flour Mills"),
        reference="SLFM/0187",
        purchase_date=date(2026, 5, 18),
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

    admin = User.objects.get(username="admin")
    order = create_order(
        customer=Customer.objects.get(name="Retailer A"),
        lines=[OrderLineInput(item_id=product.pk, qty=Decimal("150"))],
        client_uuid=uuid.uuid4(),
        salesman=User.objects.get(username="salesman_a"),
    ).order
    approve_order(order=order, user=admin)
    invoice = create_invoice(order=order, user=admin, invoice_date=date(2026, 5, 20))
    dispatch_invoice(
        invoice=invoice,
        lines=[DispatchLineInput(invoice_line_id=invoice.lines.get().pk, qty="150")],
        user=admin,
        dispatch_date=date(2026, 5, 21),
    )
    record_payment(
        customer=invoice.customer,
        amount="4000",
        method="upi",
        allocations=[],
        payment_date=date(2026, 5, 25),
        user=admin,
    )

    return {
        "invoice": invoice,
        "run": ProductionRun.objects.get(pk=run.pk),
        "flour": flour,
    }


def _login(client: object, username: str) -> None:
    client.force_login(User.objects.get(username=username))  # type: ignore[attr-defined]


DATE_FILTER = {"date_from": "2026-05-01", "date_to": "2026-05-31"}
YEAR_FILTER = {"date_from": "2026-01-01", "date_to": "2026-12-31"}


def test_report_catalog_lists_the_ten_reports_for_admin(client: object, scenario: dict) -> None:
    """Phase 5: the console knows every report slug and its columns."""
    _login(client, "admin")

    response = client.get(reverse("reports-catalog"))  # type: ignore[attr-defined]

    assert response.status_code == 200
    slugs = {row["slug"] for row in response.json()}
    assert slugs == {
        "sales-register",
        "sales-by-customer",
        "sales-by-product",
        "gst-summary",
        "purchase-register",
        "stock-summary",
        "stock-ledger",
        "production-report",
        "collections",
        "outstanding-ageing",
    }
    assert response.json()[0]["columns"][0]["label"] == "Invoice"


def test_sales_register_and_gst_summary_reconcile(client: object, scenario: dict) -> None:
    """PS Appendix A step 5: invoice 7,875 appears in both reports."""
    _login(client, "admin")

    register = client.get(  # type: ignore[attr-defined]
        reverse("reports-detail", args=["sales-register"]), DATE_FILTER
    )
    gst = client.get(reverse("reports-detail", args=["gst-summary"]), DATE_FILTER)  # type: ignore[attr-defined]

    assert register.status_code == 200, register.json()
    body = register.json()
    assert body["rows"][0]["number"] == "INV/26-27/00001"
    assert body["rows"][0]["taxable"] == "7500.00"
    assert body["rows"][0]["cgst"] == "187.50"
    assert body["rows"][0]["sgst"] == "187.50"
    assert body["rows"][0]["total"] == "7875.00"
    assert body["rows"][0]["status"] == "posted"
    assert body["totals"]["total"] == "7875.00"

    assert gst.status_code == 200
    summary = gst.json()
    b2b = next(row for row in summary["rows"] if row["section"] == "B2B")
    assert b2b["documents"] == "1"
    assert b2b["taxable"] == "7500.00"
    assert b2b["total"] == "7875.00"
    assert summary["meta"]["gstr3b_outward_supply"]["taxable"] == "7500.00"
    assert summary["meta"]["gstr3b_outward_supply"]["total"] == "7875.00"


def test_sales_by_customer_and_product_reports(client: object, scenario: dict) -> None:
    """Phase 5: the two sales breakdowns agree with the register."""
    _login(client, "admin")

    by_customer = client.get(  # type: ignore[attr-defined]
        reverse("reports-detail", args=["sales-by-customer"]), DATE_FILTER
    ).json()
    by_product = client.get(  # type: ignore[attr-defined]
        reverse("reports-detail", args=["sales-by-product"]), DATE_FILTER
    ).json()

    assert by_customer["rows"][0]["customer"] == "Retailer A"
    assert by_customer["rows"][0]["invoices"] == "1"
    assert by_customer["totals"]["total"] == "7875.00"

    assert by_product["rows"][0]["item"] == "Murukku 200 g"
    assert by_product["rows"][0]["qty"] == "150.000"
    assert by_product["rows"][0]["taxable"] == "7500.00"
    assert by_product["totals"]["total"] == "7875.00"


def test_date_filter_excludes_other_months(client: object, scenario: dict) -> None:
    """Phase 5: every report filters on its business date."""
    _login(client, "admin")

    response = client.get(  # type: ignore[attr-defined]
        reverse("reports-detail", args=["sales-register"]),
        {"date_from": "2026-06-01", "date_to": "2026-06-30"},
    )

    assert response.status_code == 200
    assert response.json()["rows"] == []
    assert response.json()["totals"]["total"] == "0.00"


def test_reversed_date_range_is_refused(client: object, scenario: dict) -> None:
    """Phase 5 negative path: date_from after date_to is a 400."""
    _login(client, "admin")

    response = client.get(  # type: ignore[attr-defined]
        reverse("reports-detail", args=["sales-register"]),
        {"date_from": "2026-06-30", "date_to": "2026-06-01"},
    )

    assert response.status_code == 400


def test_purchase_stock_and_ledger_reports(client: object, scenario: dict) -> None:
    """PS Appendix A steps 1-3: purchase 2,700, flour 120 kg, ledger rows exist."""
    _login(client, "admin")

    purchases = client.get(  # type: ignore[attr-defined]
        reverse("reports-detail", args=["purchase-register"]), DATE_FILTER
    ).json()
    stock = client.get(reverse("reports-detail", args=["stock-summary"])).json()  # type: ignore[attr-defined]
    ledger = client.get(  # type: ignore[attr-defined]
        reverse("reports-detail", args=["stock-ledger"]), YEAR_FILTER
    ).json()

    assert purchases["rows"][0]["item"] == "Flour"
    assert purchases["rows"][0]["qty"] == "60.000"
    assert purchases["totals"]["value"] == "2700.00"

    flour = next(row for row in stock["rows"] if row["item"] == "Flour")
    assert flour["qty"] == "120.000"
    assert stock["meta"]["as_of"]

    assert any(row["source_type"] == "purchase" for row in ledger["rows"])
    assert any(row["source_type"] == "production_run" for row in ledger["rows"])


def test_production_report_shows_appendix_a_cost(client: object, scenario: dict) -> None:
    """PS Appendix A step 8: one run, -6% yield, 5,855 cost, 31.14 per packet."""
    _login(client, "admin")

    response = client.get(  # type: ignore[attr-defined]
        reverse("reports-detail", args=["production-report"]), YEAR_FILTER
    )

    assert response.status_code == 200, response.json()
    row = response.json()["rows"][0]
    assert row["good_packets"] == "188.000"
    assert row["planned_output"] == "200.000"
    assert row["yield_variance_pct"] == "-0.060000"
    assert row["materials"] == "4055.00"
    assert row["overheads"] == "1800.00"
    assert row["total_cost"] == "5855.00"
    assert row["cost_per_packet"] == "31.14"
    assert row["flagged"] != "0"


def test_collections_and_ageing_reports(client: object, scenario: dict) -> None:
    """PS Appendix A step 7: 4,000 collected, 3,875 outstanding aged 90+."""
    _login(client, "admin")

    collections = client.get(  # type: ignore[attr-defined]
        reverse("reports-detail", args=["collections"]), DATE_FILTER
    ).json()
    ageing = client.get(  # type: ignore[attr-defined]
        reverse("reports-detail", args=["outstanding-ageing"]),
        {"date_to": "2026-12-31"},
    ).json()

    assert collections["rows"][0]["amount"] == "4000.00"
    assert collections["rows"][0]["allocated"] == "0.00"
    assert collections["rows"][0]["unallocated"] == "4000.00"
    assert collections["totals"]["amount"] == "4000.00"

    assert ageing["rows"][0]["customer"] == "Retailer A"
    assert ageing["rows"][0]["outstanding"] == "7875.00"
    assert ageing["rows"][0]["bucket_90_plus"] == "7875.00"


def test_reconciliation_checks_pass(client: object, scenario: dict) -> None:
    """Phase 5 exit gate: stock, invoice and GST reconciliations all tick."""
    _login(client, "admin")

    response = client.get(reverse("reports-reconciliation"), DATE_FILTER)  # type: ignore[attr-defined]

    assert response.status_code == 200, response.json()
    assert len(response.json()) == 3
    assert all(check["passed"] for check in response.json()), response.json()


def test_owner_dashboard_matches_the_day(client: object, scenario: dict) -> None:
    """Phase 5: dashboard reports today's order, dues and 31.14 per packet."""
    _login(client, "owner")

    response = client.get(reverse("reports-dashboard"))  # type: ignore[attr-defined]

    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["today_orders"]["count"] == 1
    assert body["today_orders"]["value"] == "7500.00"
    assert body["outstanding_dues"]["amount"] == "7875.00"
    assert body["cost_per_packet"]["cost_per_packet"] == "31.14"
    assert body["cost_per_packet"]["margin_per_packet"] == "18.86"
    assert len(body["stock"]) == 6
    assert body["reorder_count"] == 0
    assert any(row["item_name"] == "Murukku 200 g" for row in body["stock"])


def test_dashboard_flags_finished_goods_when_empty(client: object, scenario: dict) -> None:
    """Phase 5: finished goods at zero are a reorder line."""
    product = Item.objects.get(name="Murukku 200 g")
    from apps.inventory.models import MovementType, SourceType
    from apps.inventory.services import Movement, post_movements
    from apps.sales.models import Invoice

    invoice = Invoice.objects.get()
    post_movements(
        movements=[Movement(item_id=product.pk, qty=Decimal("-88"))],
        movement_type=MovementType.ISSUE,
        source_type=SourceType.DISPATCH,
        source_id=invoice.pk,
        user=User.objects.get(username="admin"),
    )
    _login(client, "owner")

    response = client.get(reverse("reports-dashboard"))  # type: ignore[attr-defined]

    assert response.status_code == 200
    fg = next(row for row in response.json()["stock"] if row["item_name"] == "Murukku 200 g")
    assert fg["qty"] == "0.000"
    assert fg["reorder"] is True


def test_export_formats_load_back(client: object, scenario: dict) -> None:
    """Phase 5: CSV, Excel and PDF downloads are real files."""
    _login(client, "admin")
    url = reverse("reports-detail", args=["stock-summary"])

    csv_response = client.get(url, {"format": "csv"})  # type: ignore[attr-defined]
    excel_response = client.get(url, {"format": "excel"})  # type: ignore[attr-defined]
    pdf_response = client.get(url, {"format": "pdf"})  # type: ignore[attr-defined]

    assert csv_response.status_code == 200
    assert csv_response["Content-Type"].startswith("text/csv")
    rows = list(csv.reader(StringIO(csv_response.content.decode("utf-8"))))
    assert rows[0][0] == "Item"
    assert any(row[0] == "Flour" for row in rows)

    assert excel_response.status_code == 200
    workbook = load_workbook(BytesIO(excel_response.content))
    assert workbook.active["A1"].value == "Item"

    assert pdf_response.status_code == 200
    assert pdf_response.content.startswith(b"%PDF")


def test_unsupported_format_is_a_domain_error(client: object, scenario: dict) -> None:
    """Phase 5 negative path: an unknown export format is refused."""
    _login(client, "admin")

    response = client.get(  # type: ignore[attr-defined]
        reverse("reports-detail", args=["stock-summary"]), {"format": "docx"}
    )

    assert response.status_code == 400


def test_report_roles_are_deny_by_default(client: object, scenario: dict) -> None:
    """PS 4.12: accountant read-only, production reads reports, salesman denied."""
    _login(client, "salesman_a")
    denied = client.get(reverse("reports-catalog"))  # type: ignore[attr-defined]
    denied_report = client.get(reverse("reports-detail", args=["sales-register"]))  # type: ignore[attr-defined]
    assert denied.status_code == 403
    assert denied_report.status_code == 403

    _login(client, "production")
    allowed = client.get(reverse("reports-catalog"))  # type: ignore[attr-defined]
    dashboard = client.get(reverse("reports-dashboard"))  # type: ignore[attr-defined]
    assert allowed.status_code == 200
    assert dashboard.status_code == 403

    _login(client, "accountant")
    assert client.get(reverse("reports-catalog")).status_code == 200  # type: ignore[attr-defined]
    assert client.get(reverse("reports-dashboard")).status_code == 200  # type: ignore[attr-defined]
