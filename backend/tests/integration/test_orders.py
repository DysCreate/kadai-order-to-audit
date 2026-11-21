"""Sales loop integration tests against real PostgreSQL.

Requirement: AGENTS.md 4.8–4.13 and Phase 3 exit gate – idempotent order
submit, price snapshots, salesman scope, audited admin edits, GST invoices,
per-FY numbering, invoice immutability, dispatch and credit notes.
"""

import uuid
from datetime import date
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.db.models import Sum
from freezegun import freeze_time

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.inventory.models import MovementType, SourceType, StockBalance, StockLedger
from apps.masters.models import Customer, Item
from apps.sales.models import (
    CreditNote,
    Dispatch,
    DocumentSequence,
    Invoice,
    Order,
    OrderLine,
    OrderState,
)
from apps.sales.services import (
    CreditNoteLineInput,
    DispatchLineInput,
    OrderLineInput,
    approve_order,
    create_invoice,
    create_order,
    dispatch_invoice,
    edit_order_line,
    invoice_is_cancelled,
    issue_credit_note,
    reject_order,
    stock_coverage,
)
from core.errors import (
    DomainError,
    InsufficientStock,
    InvalidMovement,
    InvalidOrderState,
)
from core.permissions import PermissionDenied

INVOICE_DATE = date(2026, 5, 20)


@pytest.fixture
def seeded(db: None) -> None:
    """Appendix A master data, prices, BOM and opening stock."""
    call_command("seed_benchmark", stdout=StringIO())


def _user(username: str) -> User:
    return User.objects.get(username=username)


def _fg() -> Item:
    return Item.objects.get(name="Murukku 200 g")


def _customer(name: str) -> Customer:
    return Customer.objects.get(name=name)


def _submit(
    *,
    customer: str = "Retailer A",
    salesman: str = "salesman_a",
    qty: str = "150",
    client_uuid: uuid.UUID | None = None,
):
    return create_order(
        customer=_customer(customer),
        lines=[OrderLineInput(item_id=_fg().pk, qty=Decimal(qty))],
        client_uuid=client_uuid or uuid.uuid4(),
        salesman=_user(salesman),
    )


def _approved_order(
    *,
    customer: str = "Retailer A",
    salesman: str | None = None,
    qty: str = "150",
) -> Order:
    if salesman is None:
        salesman = "salesman_b" if customer == "Distributor B" else "salesman_a"
    order = _submit(customer=customer, salesman=salesman, qty=qty).order
    approve_order(order=order, user=_user("admin"))
    order.refresh_from_db()
    return order


def _invoice(
    *,
    customer: str = "Retailer A",
    qty: str = "150",
    invoice_date: date = INVOICE_DATE,
) -> Invoice:
    order = _approved_order(customer=customer, qty=qty)
    return create_invoice(order=order, user=_user("admin"), invoice_date=invoice_date)


@freeze_time("2026-05-20 10:00:00")
def test_order_submit_snapshots_price_and_is_idempotent(seeded: None) -> None:
    """PS 4.13: a retried client UUID returns the same order, priced once."""
    identifier = uuid.uuid4()
    first = _submit(qty="150", client_uuid=identifier)

    assert first.created is True
    assert first.order.state == OrderState.SUBMITTED
    assert first.order.number.startswith("ORD/26-27/")
    line = first.order.lines.get()
    assert line.unit_price == Decimal("50.00")
    assert line.qty == Decimal("150.000")

    retry = _submit(qty="150", client_uuid=identifier)

    assert retry.created is False
    assert retry.order.pk == first.order.pk
    assert Order.objects.count() == 1
    assert OrderLine.objects.count() == 1
    assert AuditLog.objects.filter(entity="Order", action="create").count() == 1


def test_duplicate_uuid_for_a_different_order_is_refused(seeded: None) -> None:
    """PS 4.13 negative path: a UUID cannot be reused for another customer."""
    identifier = uuid.uuid4()
    _submit(customer="Retailer A", client_uuid=identifier)

    with pytest.raises(DomainError):
        _submit(customer="Distributor B", salesman="salesman_b", client_uuid=identifier)


def test_salesman_cannot_order_for_another_salesmans_customer(seeded: None) -> None:
    """PS 4.12: Retailer A belongs to salesman_a, not salesman_b."""
    with pytest.raises(PermissionDenied):
        _submit(customer="Retailer A", salesman="salesman_b")

    assert Order.objects.count() == 0


def test_order_state_machine_and_rejection(seeded: None) -> None:
    """PS 3 sales loop: approve or reject once; invoicing needs approval."""
    order = _submit().order
    with pytest.raises(InvalidOrderState):
        create_invoice(order=order, user=_user("admin"), invoice_date=INVOICE_DATE)

    approve_order(order=order, user=_user("admin"))
    order.refresh_from_db()
    assert order.state == OrderState.APPROVED
    assert order.approved_by_id == _user("admin").pk

    with pytest.raises(InvalidOrderState):
        approve_order(order=order, user=_user("admin"))

    rejected = _submit().order
    with pytest.raises(InvalidMovement):
        reject_order(order=rejected, reason="   ", user=_user("admin"))
    reject_order(order=rejected, reason="Customer cancelled", user=_user("admin"))
    rejected.refresh_from_db()
    assert rejected.state == OrderState.REJECTED
    assert rejected.rejection_reason == "Customer cancelled"

    with pytest.raises(InvalidOrderState):
        approve_order(order=rejected, user=_user("admin"))
    with pytest.raises(InvalidOrderState):
        create_invoice(order=rejected, user=_user("admin"), invoice_date=INVOICE_DATE)


def test_admin_line_edit_is_audited(seeded: None) -> None:
    """PS 4.10: a verified quantity/price edit writes a before/after audit row."""
    order = _submit().order
    line = order.lines.get()

    edit_order_line(
        order=order,
        line=line,
        user=_user("admin"),
        qty=Decimal("140"),
        unit_price=Decimal("49.50"),
    )

    line.refresh_from_db()
    assert line.qty == Decimal("140.000")
    assert line.unit_price == Decimal("49.50")

    audit = AuditLog.objects.get(entity="Order", entity_id=order.pk, action="update")
    assert audit.before["lines"][0]["qty"] == "150.000"
    assert audit.after["lines"][0]["qty"] == "140.000"
    assert audit.after["lines"][0]["unit_price"] == "49.50"

    approve_order(order=order, user=_user("admin"))
    with pytest.raises(InvalidOrderState):
        edit_order_line(order=order, line=line, user=_user("admin"), qty=Decimal("1"))


def test_stock_coverage_and_igst_preview(seeded: None) -> None:
    """Appendix A step 6: 50 on hand, 120 ordered -> shortage 70, IGST 300."""
    order = _submit(customer="Distributor B", salesman="salesman_b", qty="120").order

    coverage = stock_coverage(order)

    assert coverage.lines[0].on_hand_qty == Decimal("50.000")
    assert coverage.lines[0].available_qty == Decimal("50.000")
    assert coverage.lines[0].shortage_qty == Decimal("70.000")
    assert coverage.total_shortage_qty == Decimal("70.000")
    assert coverage.is_interstate is True
    assert coverage.tax_preview.taxable_total == Decimal("6000.00")
    assert coverage.tax_preview.igst_total == Decimal("300.00")
    assert coverage.tax_preview.total == Decimal("6300.00")


def test_invoice_totals_number_and_immutability(seeded: None) -> None:
    """Appendix A step 5: 7,500 + 187.50 + 187.50 = 7,875; then locked."""
    invoice = _invoice()

    assert invoice.number == "INV/26-27/00001"
    assert len(invoice.number) <= 16
    assert invoice.is_interstate is False
    assert invoice.place_of_supply_state_code == "33"
    assert invoice.taxable_total == Decimal("7500.00")
    assert invoice.cgst_total == Decimal("187.50")
    assert invoice.sgst_total == Decimal("187.50")
    assert invoice.igst_total == Decimal("0.00")
    assert invoice.total == Decimal("7875.00")

    line = invoice.lines.get()
    assert line.hsn_code == "2106"
    assert line.gst_rate == Decimal("5.00")
    assert line.taxable_value == Decimal("7500.00")
    assert line.cgst == Decimal("187.50")

    with pytest.raises(IntegrityError), transaction.atomic():
        Invoice.objects.filter(pk=invoice.pk).update(total=Decimal("1.00"))

    with pytest.raises(IntegrityError), transaction.atomic():
        Invoice.objects.filter(pk=invoice.pk).delete()

    with pytest.raises(IntegrityError), transaction.atomic():
        invoice.lines.filter(pk=line.pk).update(qty=Decimal("1"))

    invoice.refresh_from_db()
    assert invoice.total == Decimal("7875.00")


def test_inter_state_invoice_uses_igst(seeded: None) -> None:
    """Appendix A step 6 preview: 6,000 taxable + 300 IGST = 6,300."""
    invoice = _invoice(customer="Distributor B", qty="120")

    assert invoice.is_interstate is True
    assert invoice.place_of_supply_state_code == "29"
    assert invoice.taxable_total == Decimal("6000.00")
    assert invoice.igst_total == Decimal("300.00")
    assert invoice.cgst_total == Decimal("0.00")
    assert invoice.sgst_total == Decimal("0.00")
    assert invoice.total == Decimal("6300.00")


def test_financial_year_rollover_uses_a_new_counter(seeded: None) -> None:
    """PS 4.9: 31 March and 1 April draw from different FY counters."""
    march = _invoice(qty="10", invoice_date=date(2026, 3, 31))
    april = _invoice(qty="10", invoice_date=date(2026, 4, 1))

    assert march.number == "INV/25-26/00001"
    assert april.number == "INV/26-27/00001"
    assert DocumentSequence.objects.filter(doc_type="INV").count() == 2


def test_dispatch_posts_fg_issue_and_completes_the_order(seeded: None) -> None:
    """PS 3 dispatch: FG goes down by 40, traceable to the dispatch document."""
    invoice = _invoice(qty="40")
    line = invoice.lines.get()

    dispatch = dispatch_invoice(
        invoice=invoice,
        lines=[DispatchLineInput(invoice_line_id=line.pk, qty=Decimal("40"))],
        user=_user("admin"),
        dispatch_date=date(2026, 5, 21),
    )

    assert Dispatch.objects.count() == 1
    assert StockBalance.objects.get(item=_fg()).qty == Decimal("10.000")

    entry = StockLedger.objects.get(
        movement_type=MovementType.ISSUE,
        source_type=SourceType.DISPATCH,
        source_id=dispatch.pk,
    )
    assert entry.item_id == _fg().pk
    assert entry.qty == Decimal("-40.000")

    order = Order.objects.get(pk=invoice.order_id)
    assert order.state == OrderState.DISPATCHED

    with pytest.raises(DomainError):
        dispatch_invoice(
            invoice=invoice,
            lines=[DispatchLineInput(invoice_line_id=line.pk, qty=Decimal("1"))],
            user=_user("admin"),
        )


def test_partial_dispatch_keeps_the_order_invoiced(seeded: None) -> None:
    """PS 3 partial dispatch: the order completes only when every line is out."""
    invoice = _invoice(qty="40")
    line = invoice.lines.get()

    dispatch_invoice(
        invoice=invoice,
        lines=[DispatchLineInput(invoice_line_id=line.pk, qty=Decimal("15"))],
        user=_user("admin"),
    )
    order = Order.objects.get(pk=invoice.order_id)
    assert order.state == OrderState.INVOICED
    assert StockBalance.objects.get(item=_fg()).qty == Decimal("35.000")

    dispatch_invoice(
        invoice=invoice,
        lines=[DispatchLineInput(invoice_line_id=line.pk, qty=Decimal("25"))],
        user=_user("admin"),
    )
    order.refresh_from_db()
    assert order.state == OrderState.DISPATCHED
    assert StockBalance.objects.get(item=_fg()).qty == Decimal("10.000")


def test_dispatch_beyond_stock_writes_nothing(seeded: None) -> None:
    """PS 4.11: an invoice for 60 against 50 on hand cannot be dispatched."""
    invoice = _invoice(qty="60")
    line = invoice.lines.get()
    ledger_count = StockLedger.objects.count()

    with pytest.raises(InsufficientStock):
        dispatch_invoice(
            invoice=invoice,
            lines=[DispatchLineInput(invoice_line_id=line.pk, qty=Decimal("60"))],
            user=_user("admin"),
        )

    assert Dispatch.objects.count() == 0
    assert StockLedger.objects.count() == ledger_count
    assert StockBalance.objects.get(item=_fg()).qty == Decimal("50.000")
    assert Order.objects.get(pk=invoice.order_id).state == OrderState.INVOICED


def test_credit_note_numbers_cancels_and_restocks(seeded: None) -> None:
    """PS 4.9 / 4.14: CN series, derived cancellation and optional restock."""
    invoice = _invoice(qty="40")
    line = invoice.lines.get()
    dispatch_invoice(
        invoice=invoice,
        lines=[DispatchLineInput(invoice_line_id=line.pk, qty=Decimal("40"))],
        user=_user("admin"),
    )
    assert StockBalance.objects.get(item=_fg()).qty == Decimal("10.000")

    credit = issue_credit_note(
        invoice=invoice,
        reason="Customer returned the goods",
        lines=[CreditNoteLineInput(invoice_line_id=line.pk, qty=Decimal("10"))],
        restock=True,
        user=_user("admin"),
        note_date=date(2026, 5, 22),
    )

    assert credit.number == "CN/26-27/00001"
    assert credit.taxable_total == Decimal("500.00")
    assert credit.cgst_total == Decimal("12.50")
    assert credit.sgst_total == Decimal("12.50")
    assert credit.total == Decimal("525.00")
    assert credit.restock is True

    assert StockBalance.objects.get(item=_fg()).qty == Decimal("20.000")
    restock_entry = StockLedger.objects.get(
        movement_type=MovementType.RECEIPT,
        source_type=SourceType.CREDIT_NOTE,
        source_id=credit.pk,
    )
    assert restock_entry.qty == Decimal("10.000")

    assert invoice_is_cancelled(invoice) is False
    remaining = issue_credit_note(
        invoice=invoice,
        reason="Cancel the rest",
        lines=[CreditNoteLineInput(invoice_line_id=line.pk, qty=Decimal("30"))],
        user=_user("admin"),
        note_date=date(2026, 5, 23),
    )
    assert remaining.number == "CN/26-27/00002"
    assert invoice_is_cancelled(invoice) is True

    with pytest.raises(DomainError):
        issue_credit_note(
            invoice=invoice,
            reason="Too much",
            lines=[CreditNoteLineInput(invoice_line_id=line.pk, qty=Decimal("1"))],
            user=_user("admin"),
        )


def test_credit_note_requires_a_reason(seeded: None) -> None:
    """PS 4.14 negative path: a credit note without a reason is refused."""
    invoice = _invoice(qty="10")
    line = invoice.lines.get()

    with pytest.raises(InvalidMovement):
        issue_credit_note(
            invoice=invoice,
            reason="  ",
            lines=[CreditNoteLineInput(invoice_line_id=line.pk, qty=Decimal("1"))],
            user=_user("admin"),
        )

    assert CreditNote.objects.count() == 0


def test_invoice_total_equals_line_sum(seeded: None) -> None:
    """PS 6.7: invoice header totals equal the sum of their lines."""
    invoice = _invoice(qty="150")

    line_totals = invoice.lines.aggregate(
        taxable=Sum("taxable_value"),
        cgst=Sum("cgst"),
        sgst=Sum("sgst"),
        igst=Sum("igst"),
        total=Sum("line_total"),
    )
    assert line_totals["taxable"] == invoice.taxable_total
    assert line_totals["cgst"] == invoice.cgst_total
    assert line_totals["sgst"] == invoice.sgst_total
    assert line_totals["igst"] == invoice.igst_total
    assert line_totals["total"] == invoice.total
