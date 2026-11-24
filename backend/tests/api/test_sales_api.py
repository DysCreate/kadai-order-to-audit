"""API tests for the Phase 3 sales endpoints.

Requirement: AGENTS.md Section 5 – every endpoint tested for each allowed role
and at least one denied role, plus negative paths, Decimal-as-string output and
a real PDF/signed share link.
"""

import uuid
from decimal import Decimal
from io import StringIO
from urllib.parse import unquote, urlsplit

import pytest
from django.core.management import call_command
from django.urls import reverse

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.inventory.models import MovementType, SourceType, StockBalance, StockLedger
from apps.masters.models import Customer, Item
from apps.sales.models import Dispatch, Invoice, Order, OrderState

pytestmark = pytest.mark.django_db


@pytest.fixture
def seeded(db: None) -> None:
    """Appendix A master data (items, prices, BOM and opening stock)."""
    call_command("seed_benchmark", stdout=StringIO())


def _login(client: object, username: str) -> None:
    client.force_login(User.objects.get(username=username))  # type: ignore[attr-defined]


def _customer(name: str) -> Customer:
    return Customer.objects.get(name=name)


def _fg() -> Item:
    return Item.objects.get(name="Murukku 200 g")


def _payload(*, customer: str = "Retailer A", qty: str = "150", identifier: str) -> dict:
    return {
        "client_uuid": identifier,
        "customer": _customer(customer).pk,
        "lines": [{"item": _fg().pk, "qty": qty}],
    }


def _submit_order(
    client: object,
    *,
    customer: str = "Retailer A",
    salesman: str = "salesman_a",
    qty: str = "150",
) -> dict:
    _login(client, salesman)
    response = client.post(  # type: ignore[attr-defined]
        reverse("sales-order-list"),
        data=_payload(customer=customer, qty=qty, identifier=str(uuid.uuid4())),
        content_type="application/json",
    )
    assert response.status_code == 201, response.json()
    return response.json()


def _invoice_order(
    client: object,
    *,
    customer: str = "Retailer A",
    salesman: str = "salesman_a",
    qty: str = "150",
    invoice_date: str = "2026-05-20",
) -> dict:
    order = _submit_order(client, customer=customer, salesman=salesman, qty=qty)
    _login(client, "admin")
    approved = client.post(  # type: ignore[attr-defined]
        reverse("sales-order-approve", args=[order["id"]]),
        data={},
        content_type="application/json",
    )
    assert approved.status_code == 200, approved.json()
    invoice = client.post(  # type: ignore[attr-defined]
        reverse("sales-order-invoice", args=[order["id"]]),
        data={"invoice_date": invoice_date},
        content_type="application/json",
    )
    assert invoice.status_code == 201, invoice.json()
    return invoice.json()


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------


def test_salesman_submits_an_order_and_retry_returns_it(client: object, seeded: None) -> None:
    """PS 4.13: duplicate client UUID returns the same order, not a second one."""
    _login(client, "salesman_a")
    identifier = str(uuid.uuid4())
    payload = _payload(qty="150", identifier=identifier)

    first = client.post(  # type: ignore[attr-defined]
        reverse("sales-order-list"), data=payload, content_type="application/json"
    )
    retry = client.post(  # type: ignore[attr-defined]
        reverse("sales-order-list"), data=payload, content_type="application/json"
    )

    assert first.status_code == 201
    assert retry.status_code == 200
    assert first.json()["id"] == retry.json()["id"]
    assert first.json()["state"] == "SUBMITTED"
    assert first.json()["lines"][0]["unit_price"] == "50.00"
    assert first.json()["total_value"] == "7500.00"
    assert Order.objects.count() == 1


def test_salesman_cannot_order_for_an_unassigned_customer(client: object, seeded: None) -> None:
    """PS 4.12: Retailer A belongs to salesman_a; salesman_b is refused."""
    _login(client, "salesman_b")

    response = client.post(  # type: ignore[attr-defined]
        reverse("sales-order-list"),
        data=_payload(customer="Retailer A", identifier=str(uuid.uuid4())),
        content_type="application/json",
    )

    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"
    assert Order.objects.count() == 0


def test_salesman_cannot_price_an_unassigned_customers_catalog(
    client: object, seeded: None
) -> None:
    """PS 4.12: the item catalog must not expose another customer's price list."""
    retailer_a = _customer("Retailer A")

    _login(client, "salesman_b")
    denied = client.get(  # type: ignore[attr-defined]
        reverse("masters-item-list"), {"type": "FG", "customer": retailer_a.pk}
    )
    assert denied.status_code == 404

    _login(client, "salesman_a")
    allowed = client.get(  # type: ignore[attr-defined]
        reverse("masters-item-list"), {"type": "FG", "customer": retailer_a.pk}
    )
    assert allowed.status_code == 200


def test_salesman_sees_only_their_own_orders(client: object, seeded: None) -> None:
    """PS 4.12: order lists are scoped per salesman."""
    _submit_order(client, salesman="salesman_a")

    _login(client, "salesman_b")
    other = client.get(reverse("sales-order-list"))  # type: ignore[attr-defined]
    _login(client, "salesman_a")
    own = client.get(reverse("sales-order-list"))  # type: ignore[attr-defined]
    _login(client, "admin")
    admin = client.get(reverse("sales-order-list"))  # type: ignore[attr-defined]

    assert other.json() == []
    assert len(own.json()) == 1
    assert len(admin.json()) == 1


def test_customer_sales_summary_counts_only_real_sales(client: object, seeded: None) -> None:
    """PS 3 salesman UI: customer-wise sales this month, scoped per salesman."""
    approved = _submit_order(client, qty="150")
    _submit_order(client, qty="10")  # still submitted, so not a sale
    _login(client, "admin")
    response = client.post(  # type: ignore[attr-defined]
        reverse("sales-order-approve", args=[approved["id"]]),
        data={},
        content_type="application/json",
    )
    assert response.status_code == 200

    summary = client.get(reverse("sales-order-summary"))  # type: ignore[attr-defined]

    assert summary.status_code == 200
    body = summary.json()
    assert len(body) == 1
    assert body[0]["customer_name"] == "Retailer A"
    assert body[0]["order_count"] == 1
    assert body[0]["total_qty"] == "150.000"
    assert body[0]["total_value"] == "7500.00"

    bad_month = client.get(reverse("sales-order-summary"), {"month": "2026-13"})  # type: ignore[attr-defined]
    assert bad_month.status_code == 400

    _login(client, "salesman_b")
    other = client.get(reverse("sales-order-summary"))  # type: ignore[attr-defined]
    assert other.json() == []


def test_order_endpoints_deny_production(client: object, seeded: None) -> None:
    """PS 4.12: the production role has no access to the sales loop."""
    _login(client, "production")

    listing = client.get(reverse("sales-order-list"))  # type: ignore[attr-defined]
    submit = client.post(  # type: ignore[attr-defined]
        reverse("sales-order-list"),
        data=_payload(identifier=str(uuid.uuid4())),
        content_type="application/json",
    )

    assert listing.status_code == 403
    assert submit.status_code == 403


def test_accountant_is_read_only(client: object, seeded: None) -> None:
    """PS 4.12: the accountant may read orders but never approve or submit."""
    order = _submit_order(client, salesman="salesman_a")
    _login(client, "accountant")

    listing = client.get(reverse("sales-order-list"))  # type: ignore[attr-defined]
    approve = client.post(  # type: ignore[attr-defined]
        reverse("sales-order-approve", args=[order["id"]]),
        data={},
        content_type="application/json",
    )
    submit = client.post(  # type: ignore[attr-defined]
        reverse("sales-order-list"),
        data=_payload(identifier=str(uuid.uuid4())),
        content_type="application/json",
    )

    assert listing.status_code == 200
    assert approve.status_code == 403
    assert submit.status_code == 403


def test_admin_edit_and_approve_are_audited(client: object, seeded: None) -> None:
    """PS 4.10 / Phase 3: admin verification edits quantity and price, audited."""
    order = _submit_order(client)
    line = order["lines"][0]
    _login(client, "admin")

    edited = client.patch(  # type: ignore[attr-defined]
        reverse("sales-order-line-edit", args=[order["id"], line["id"]]),
        data={"qty": "140", "unit_price": "49.50"},
        content_type="application/json",
    )
    approved = client.post(  # type: ignore[attr-defined]
        reverse("sales-order-approve", args=[order["id"]]),
        data={},
        content_type="application/json",
    )

    assert edited.status_code == 200, edited.json()
    assert edited.json()["lines"][0]["qty"] == "140.000"
    assert edited.json()["lines"][0]["unit_price"] == "49.50"
    assert AuditLog.objects.filter(entity="Order", entity_id=order["id"], action="update").exists()
    assert approved.status_code == 200
    assert approved.json()["state"] == "APPROVED"

    edit_after_approval = client.patch(  # type: ignore[attr-defined]
        reverse("sales-order-line-edit", args=[order["id"], line["id"]]),
        data={"qty": "1"},
        content_type="application/json",
    )
    assert edit_after_approval.status_code == 400
    assert edit_after_approval.json()["code"] == "invalid_order_state"


def test_reject_requires_a_reason(client: object, seeded: None) -> None:
    """PS 3 negative path: rejection stores a reason and is audited."""
    order = _submit_order(client)
    _login(client, "admin")

    blank = client.post(  # type: ignore[attr-defined]
        reverse("sales-order-reject", args=[order["id"]]),
        data={"reason": ""},
        content_type="application/json",
    )
    rejected = client.post(  # type: ignore[attr-defined]
        reverse("sales-order-reject", args=[order["id"]]),
        data={"reason": "Out of season"},
        content_type="application/json",
    )

    assert blank.status_code == 400
    assert rejected.status_code == 200
    assert rejected.json()["state"] == "REJECTED"
    assert rejected.json()["rejection_reason"] == "Out of season"


def test_coverage_endpoint_shows_shortage_and_igst_preview(client: object, seeded: None) -> None:
    """Appendix A step 6: shortage, inter-state preview and available stock."""
    order = _submit_order(client, customer="Distributor B", salesman="salesman_b", qty="120")
    _login(client, "admin")

    response = client.get(reverse("sales-order-coverage", args=[order["id"]]))  # type: ignore[attr-defined]

    assert response.status_code == 200
    body = response.json()
    assert body["is_interstate"] is True
    assert body["total_shortage_qty"] == "70.000"
    assert body["lines"][0]["on_hand_qty"] == "50.000"
    assert body["lines"][0]["available_qty"] == "50.000"
    assert body["tax_preview"]["taxable_total"] == "6000.00"
    assert body["tax_preview"]["igst_total"] == "300.00"
    assert body["tax_preview"]["total"] == "6300.00"


def test_coverage_denies_salesman(client: object, seeded: None) -> None:
    """PS 4.12: coverage is an admin verification tool, not a salesman screen."""
    order = _submit_order(client)

    response = client.get(reverse("sales-order-coverage", args=[order["id"]]))  # type: ignore[attr-defined]

    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------


def test_invoice_endpoint_totals_number_and_single_use(client: object, seeded: None) -> None:
    """Appendix A step 5: 7,875 invoice, INV/26-27/00001, raised once."""
    invoice = _invoice_order(client, qty="150")

    assert invoice["number"] == "INV/26-27/00001"
    assert invoice["taxable_total"] == "7500.00"
    assert invoice["cgst_total"] == "187.50"
    assert invoice["sgst_total"] == "187.50"
    assert invoice["total"] == "7875.00"
    assert invoice["amount_in_words"] == ("Seven Thousand Eight Hundred Seventy Five Rupees Only")
    assert invoice["lines"][0]["hsn_code"] == "2106"
    assert invoice["lines"][0]["gst_rate"] == "5.00"
    assert invoice["is_cancelled"] is False

    second = client.post(  # type: ignore[attr-defined]
        reverse("sales-order-invoice", args=[invoice["order_id"]]),
        data={"invoice_date": "2026-05-20"},
        content_type="application/json",
    )
    assert second.status_code == 400
    assert second.json()["code"] == "invalid_order_state"
    assert Invoice.objects.count() == 1


def test_invoice_list_and_detail_are_scoped(client: object, seeded: None) -> None:
    """PS 4.12: a salesman cannot read another salesman's invoice."""
    invoice = _invoice_order(client, customer="Distributor B", salesman="salesman_b", qty="120")

    _login(client, "salesman_a")
    detail = client.get(reverse("sales-invoice-detail", args=[invoice["id"]]))  # type: ignore[attr-defined]
    listing = client.get(reverse("sales-invoice-list"))  # type: ignore[attr-defined]

    assert detail.status_code == 404
    assert listing.json() == []

    _login(client, "accountant")
    allowed = client.get(reverse("sales-invoice-detail", args=[invoice["id"]]))  # type: ignore[attr-defined]
    assert allowed.status_code == 200
    assert allowed.json()["total"] == "6300.00"
    assert allowed.json()["igst_total"] == "300.00"


def test_invoice_pdf_and_signed_share_link(client: object, seeded: None) -> None:
    """PS 4.9: the PDF renders and a signed link opens without a session."""
    invoice = _invoice_order(client)

    pdf = client.get(reverse("sales-invoice-pdf", args=[invoice["id"]]))  # type: ignore[attr-defined]
    assert pdf.status_code == 200
    assert pdf["Content-Type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")

    share = client.get(reverse("sales-invoice-share", args=[invoice["id"]]))  # type: ignore[attr-defined]
    assert share.status_code == 200
    body = share.json()
    assert body["whatsapp"].startswith("https://wa.me/?text=")
    assert body["mailto"].startswith("mailto:?subject=")
    assert invoice["number"] in unquote(body["whatsapp"])
    assert "/api/sales/invoices/pdf/" in body["pdf_url"]

    client.logout()  # type: ignore[attr-defined]
    token_pdf = client.get(urlsplit(body["pdf_url"]).path)  # type: ignore[attr-defined]
    assert token_pdf.status_code == 200
    assert token_pdf.content.startswith(b"%PDF")


def test_tampered_pdf_token_is_refused(client: object, seeded: None) -> None:
    """PS 4.9 negative path: an unsigned PDF link is a 403, not a leak."""
    response = client.get(reverse("sales-invoice-pdf-token", args=["not-a-real-token"]))  # type: ignore[attr-defined]
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Dispatch and credit notes
# ---------------------------------------------------------------------------


def test_dispatch_posts_fg_issue_and_completes_the_order(client: object, seeded: None) -> None:
    """PS 3 dispatch: FG 50 -> 10, one ISSUE row, order DISPATCHED."""
    invoice = _invoice_order(client, qty="40")
    line = invoice["lines"][0]
    _login(client, "admin")

    response = client.post(  # type: ignore[attr-defined]
        reverse("sales-invoice-dispatch", args=[invoice["id"]]),
        data={
            "dispatch_date": "2026-05-21",
            "lines": [{"invoice_line": line["id"], "qty": "40"}],
        },
        content_type="application/json",
    )

    assert response.status_code == 201, response.json()
    dispatch_id = response.json()["id"]
    assert StockBalance.objects.get(item=_fg()).qty == Decimal("10.000")
    entry = StockLedger.objects.get(
        movement_type=MovementType.ISSUE,
        source_type=SourceType.DISPATCH,
        source_id=dispatch_id,
    )
    assert entry.qty == Decimal("-40.000")
    assert Order.objects.get(pk=invoice["order_id"]).state == OrderState.DISPATCHED


def test_dispatch_beyond_stock_is_a_400_and_writes_nothing(client: object, seeded: None) -> None:
    """PS 4.11: dispatch beyond stock returns insufficient_stock, no rows."""
    invoice = _invoice_order(client, qty="60")
    line = invoice["lines"][0]
    _login(client, "admin")
    ledger_count = StockLedger.objects.count()

    response = client.post(  # type: ignore[attr-defined]
        reverse("sales-invoice-dispatch", args=[invoice["id"]]),
        data={"lines": [{"invoice_line": line["id"], "qty": "60"}]},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["code"] == "insufficient_stock"
    assert Dispatch.objects.count() == 0
    assert StockLedger.objects.count() == ledger_count
    assert StockBalance.objects.get(item=_fg()).qty == Decimal("50.000")


@pytest.mark.parametrize("username", ["salesman_a", "production", "accountant"])
def test_dispatch_denied_for_non_admin_roles(client: object, seeded: None, username: str) -> None:
    """PS 4.12: only admin and owner may dispatch."""
    invoice = _invoice_order(client, qty="10")
    line = invoice["lines"][0]
    _login(client, username)

    response = client.post(  # type: ignore[attr-defined]
        reverse("sales-invoice-dispatch", args=[invoice["id"]]),
        data={"lines": [{"invoice_line": line["id"], "qty": "10"}]},
        content_type="application/json",
    )

    assert response.status_code == 403
    assert Dispatch.objects.count() == 0


def test_credit_note_endpoint_cancels_the_invoice(client: object, seeded: None) -> None:
    """PS 4.9 / 4.14: CN series, derived cancellation and the invoice view."""
    invoice = _invoice_order(client, qty="150")
    line = invoice["lines"][0]
    _login(client, "admin")

    response = client.post(  # type: ignore[attr-defined]
        reverse("sales-invoice-credit-note", args=[invoice["id"]]),
        data={
            "reason": "Goods returned",
            "restock": True,
            "note_date": "2026-05-22",
            "lines": [{"invoice_line": line["id"], "qty": "150"}],
        },
        content_type="application/json",
    )

    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["number"] == "CN/26-27/00001"
    assert body["total"] == "7875.00"

    detail = client.get(reverse("sales-invoice-detail", args=[invoice["id"]]))  # type: ignore[attr-defined]
    assert detail.json()["is_cancelled"] is True
    assert detail.json()["credited_total"] == "7875.00"
    assert StockBalance.objects.get(item=_fg()).qty == Decimal("200.000")


def test_unknown_order_is_a_404(client: object, seeded: None) -> None:
    """PS 3: a missing order is a 404, not a 500."""
    _login(client, "admin")
    response = client.get(reverse("sales-order-detail", args=[999_999]))  # type: ignore[attr-defined]
    assert response.status_code == 404
