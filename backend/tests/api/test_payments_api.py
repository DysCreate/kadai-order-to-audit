"""API tests for the Phase 3 payments endpoints.

Requirement: AGENTS.md Section 5 – role matrix, allocation, outstanding and
ageing output as Decimal strings.
"""

import uuid
from datetime import date
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.urls import reverse

from apps.accounts.models import User
from apps.masters.models import Customer, Item
from apps.sales.services import (
    OrderLineInput,
    approve_order,
    create_invoice,
    create_order,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def seeded(db: None) -> None:
    """Appendix A master data and opening stock."""
    call_command("seed_benchmark", stdout=StringIO())


def _login(client: object, username: str) -> None:
    client.force_login(User.objects.get(username=username))  # type: ignore[attr-defined]


def _invoice(
    customer_name: str = "Retailer A",
    qty: str = "150",
    invoice_date: date = date(2026, 5, 20),
):
    salesman = "salesman_b" if customer_name == "Distributor B" else "salesman_a"
    order = create_order(
        customer=Customer.objects.get(name=customer_name),
        lines=[
            OrderLineInput(
                item_id=Item.objects.get(name="Murukku 200 g").pk,
                qty=Decimal(qty),
            )
        ],
        client_uuid=uuid.uuid4(),
        salesman=User.objects.get(username=salesman),
    ).order
    approve_order(order=order, user=User.objects.get(username="admin"))
    return create_invoice(
        order=order,
        user=User.objects.get(username="admin"),
        invoice_date=invoice_date,
    )


def _payment_payload(invoice_id: int, customer_id: int, amount: str = "4000") -> dict:
    return {
        "customer": customer_id,
        "amount": amount,
        "method": "upi",
        "payment_date": "2026-05-25",
        "reference": "UPI/8891",
        "allocations": [{"invoice": invoice_id, "amount": amount}],
    }


def test_admin_records_a_payment_and_outstanding_drops(client: object, seeded: None) -> None:
    """Appendix A step 7: 4,000 allocated leaves 3,875 outstanding."""
    invoice = _invoice()
    _login(client, "admin")

    created = client.post(  # type: ignore[attr-defined]
        reverse("payments-payment-list"),
        data=_payment_payload(invoice.pk, invoice.customer_id),
        content_type="application/json",
    )
    outstanding = client.get(  # type: ignore[attr-defined]
        reverse("payments-outstanding"),
        {"customer": invoice.customer_id},
    )

    assert created.status_code == 201, created.json()
    assert created.json()["amount"] == "4000.00"
    assert created.json()["allocations"][0]["invoice_number"] == invoice.number
    assert outstanding.status_code == 200
    assert outstanding.json()["outstanding"] == "3875.00"


def test_accountant_reads_payments_but_cannot_record_them(client: object, seeded: None) -> None:
    """PS 4.12: the accountant is strictly read-only."""
    invoice = _invoice()
    _login(client, "accountant")

    listing = client.get(reverse("payments-payment-list"))  # type: ignore[attr-defined]
    outstanding = client.get(  # type: ignore[attr-defined]
        reverse("payments-outstanding"),
        {"customer": invoice.customer_id},
    )
    created = client.post(  # type: ignore[attr-defined]
        reverse("payments-payment-list"),
        data=_payment_payload(invoice.pk, invoice.customer_id),
        content_type="application/json",
    )

    assert listing.status_code == 200
    assert outstanding.status_code == 200
    assert created.status_code == 403


def test_salesman_is_denied_payments(client: object, seeded: None) -> None:
    """PS 4.12: a salesman has no access to money received."""
    invoice = _invoice()
    _login(client, "salesman_a")

    listing = client.get(reverse("payments-payment-list"))  # type: ignore[attr-defined]
    created = client.post(  # type: ignore[attr-defined]
        reverse("payments-payment-list"),
        data=_payment_payload(invoice.pk, invoice.customer_id),
        content_type="application/json",
    )

    assert listing.status_code == 403
    assert created.status_code == 403


def test_over_allocation_is_a_domain_error(client: object, seeded: None) -> None:
    """PS 3 negative path: an allocation above the invoice is a 400."""
    invoice = _invoice()
    _login(client, "admin")

    response = client.post(  # type: ignore[attr-defined]
        reverse("payments-payment-list"),
        data=_payment_payload(invoice.pk, invoice.customer_id, amount="8000"),
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["code"] == "domain_error"


def test_ageing_endpoint_returns_the_four_buckets(client: object, seeded: None) -> None:
    """PS 3 payments: ageing buckets are 0-30, 31-60, 61-90 and 90+."""
    invoice = _invoice(invoice_date=date(2026, 1, 5))
    _login(client, "admin")

    response = client.get(  # type: ignore[attr-defined]
        reverse("payments-ageing"),
        {"customer": invoice.customer_id, "as_of": "2026-11-21"},
    )

    assert response.status_code == 200
    buckets = {row["label"]: row["amount"] for row in response.json()["buckets"]}
    assert buckets == {
        "0-30": "0.00",
        "31-60": "0.00",
        "61-90": "0.00",
        "90+": "7875.00",
    }


def test_customer_ledger_endpoint(client: object, seeded: None) -> None:
    """PS 3 payments: the ledger screen reads invoices, payments and ageing."""
    invoice = _invoice()
    _login(client, "admin")
    client.post(  # type: ignore[attr-defined]
        reverse("payments-payment-list"),
        data=_payment_payload(invoice.pk, invoice.customer_id),
        content_type="application/json",
    )

    response = client.get(  # type: ignore[attr-defined]
        reverse("payments-customer-ledger", args=[invoice.customer_id])
    )

    assert response.status_code == 200
    body = response.json()
    assert body["outstanding"] == "3875.00"
    assert body["invoices"][0]["number"] == invoice.number
    assert body["invoices"][0]["paid"] == "4000.00"
    assert body["invoices"][0]["outstanding"] == "3875.00"
    assert len(body["payments"]) == 1
    assert {row["label"] for row in body["buckets"]} == {"0-30", "31-60", "61-90", "90+"}


def test_outstanding_requires_a_customer(client: object, seeded: None) -> None:
    """PS 3 negative path: the outstanding endpoint needs a customer id."""
    _login(client, "admin")

    missing = client.get(reverse("payments-outstanding"))  # type: ignore[attr-defined]
    invalid = client.get(reverse("payments-outstanding"), {"customer": "abc"})  # type: ignore[attr-defined]

    assert missing.status_code == 400
    assert invalid.status_code == 404
