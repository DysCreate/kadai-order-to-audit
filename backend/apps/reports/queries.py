"""Report queries – every report reads stored rows; none writes anything.

Invariants protected:
- Date filters always apply to the business date of the document (invoice
  date, purchase date, payment date, completion date), never to a request-time
  clock, except the stock and ageing views that are explicitly "as of today".
- Totals are summed from the same rows that are returned, so a report footer
  cannot disagree with its table.
- A cancelled invoice stays visible on the sales register with its status; the
  GST summary reports credit notes separately and its GSTR-3B outward-supply
  figure is net of them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from django.db.models import QuerySet, Sum
from django.utils import timezone

from apps.inventory.models import PurchaseLine, StockLedger
from apps.inventory.services import stock_summary
from apps.masters.models import Customer
from apps.payments.models import Payment
from apps.payments.services import customer_ageing, customer_outstanding
from apps.production.models import ProductionRun, RunState, RunVarianceSnapshot, VarianceKind
from apps.sales.models import CreditNote, Invoice, InvoiceLine
from apps.sales.numbering import kolkata_today
from apps.sales.services import invoice_is_cancelled
from core.money import q2
from core.quantity import q3

from .framework import (
    KIND_DATE,
    KIND_INT,
    KIND_MONEY,
    KIND_QTY,
    KIND_RATE,
    KIND_TEXT,
    KIND_VARIANCE,
    Column,
    ReportResult,
    validate_range,
)

SALES_REGISTER_COLUMNS: tuple[Column, ...] = (
    Column("number", "Invoice", KIND_TEXT),
    Column("invoice_date", "Date", KIND_DATE),
    Column("customer", "Customer", KIND_TEXT),
    Column("gstin", "GSTIN", KIND_TEXT),
    Column("state_code", "State", KIND_TEXT),
    Column("taxable", "Taxable", KIND_MONEY),
    Column("cgst", "CGST", KIND_MONEY),
    Column("sgst", "SGST", KIND_MONEY),
    Column("igst", "IGST", KIND_MONEY),
    Column("total", "Total", KIND_MONEY),
    Column("status", "Status", KIND_TEXT),
)

SALES_BY_CUSTOMER_COLUMNS: tuple[Column, ...] = (
    Column("customer", "Customer", KIND_TEXT),
    Column("state_code", "State", KIND_TEXT),
    Column("invoices", "Invoices", KIND_INT),
    Column("taxable", "Taxable", KIND_MONEY),
    Column("tax", "Tax", KIND_MONEY),
    Column("total", "Total", KIND_MONEY),
)

SALES_BY_PRODUCT_COLUMNS: tuple[Column, ...] = (
    Column("item", "Item", KIND_TEXT),
    Column("hsn_code", "HSN", KIND_TEXT),
    Column("qty", "Quantity", KIND_QTY),
    Column("taxable", "Taxable", KIND_MONEY),
    Column("tax", "Tax", KIND_MONEY),
    Column("total", "Total", KIND_MONEY),
)

GST_SUMMARY_COLUMNS: tuple[Column, ...] = (
    Column("section", "Section", KIND_TEXT),
    Column("description", "Description", KIND_TEXT),
    Column("documents", "Documents", KIND_INT),
    Column("qty", "Quantity", KIND_QTY),
    Column("taxable", "Taxable", KIND_MONEY),
    Column("cgst", "CGST", KIND_MONEY),
    Column("sgst", "SGST", KIND_MONEY),
    Column("igst", "IGST", KIND_MONEY),
    Column("total", "Total", KIND_MONEY),
)

PURCHASE_REGISTER_COLUMNS: tuple[Column, ...] = (
    Column("purchase_date", "Date", KIND_DATE),
    Column("supplier", "Supplier", KIND_TEXT),
    Column("reference", "Reference", KIND_TEXT),
    Column("item", "Item", KIND_TEXT),
    Column("qty", "Quantity", KIND_QTY),
    Column("uom", "Unit", KIND_TEXT),
    Column("unit_cost", "Rate", KIND_RATE),
    Column("value", "Value", KIND_MONEY),
)

STOCK_SUMMARY_COLUMNS: tuple[Column, ...] = (
    Column("item", "Item", KIND_TEXT),
    Column("item_type", "Type", KIND_TEXT),
    Column("uom", "Unit", KIND_TEXT),
    Column("qty", "Quantity", KIND_QTY),
    Column("value", "Value", KIND_MONEY),
    Column("avg_rate", "Average rate", KIND_RATE),
)

STOCK_LEDGER_COLUMNS: tuple[Column, ...] = (
    Column("date", "Date", KIND_DATE),
    Column("item", "Item", KIND_TEXT),
    Column("movement_type", "Movement", KIND_TEXT),
    Column("qty", "Quantity", KIND_QTY),
    Column("value", "Value", KIND_MONEY),
    Column("unit_value", "Unit value", KIND_RATE),
    Column("source_type", "Source", KIND_TEXT),
    Column("source_id", "Source id", KIND_INT),
)

PRODUCTION_REPORT_COLUMNS: tuple[Column, ...] = (
    Column("run_id", "Run", KIND_INT),
    Column("completed_date", "Completed", KIND_DATE),
    Column("product", "Product", KIND_TEXT),
    Column("batches", "Batches", KIND_QTY),
    Column("planned_output", "Planned output", KIND_QTY),
    Column("good_packets", "Good packets", KIND_QTY),
    Column("yield_variance_pct", "Yield variance", KIND_VARIANCE),
    Column("flagged", "Flagged lines", KIND_INT),
    Column("materials", "Materials", KIND_MONEY),
    Column("overheads", "Overheads", KIND_MONEY),
    Column("total_cost", "Total cost", KIND_MONEY),
    Column("cost_per_packet", "Cost/packet", KIND_MONEY),
)

COLLECTIONS_COLUMNS: tuple[Column, ...] = (
    Column("payment_date", "Date", KIND_DATE),
    Column("customer", "Customer", KIND_TEXT),
    Column("amount", "Received", KIND_MONEY),
    Column("allocated", "Allocated", KIND_MONEY),
    Column("unallocated", "Unallocated", KIND_MONEY),
    Column("method", "Method", KIND_TEXT),
    Column("reference", "Reference", KIND_TEXT),
)

AGEING_COLUMNS: tuple[Column, ...] = (
    Column("customer", "Customer", KIND_TEXT),
    Column("outstanding", "Outstanding", KIND_MONEY),
    Column("bucket_0_30", "0-30", KIND_MONEY),
    Column("bucket_31_60", "31-60", KIND_MONEY),
    Column("bucket_61_90", "61-90", KIND_MONEY),
    Column("bucket_90_plus", "90+", KIND_MONEY),
)


def _money(value: object) -> Decimal:
    return q2(Decimal(str(value or 0)))


def _qty(value: object) -> Decimal:
    return q3(Decimal(str(value or 0)))


def _invoices(date_from: date | None, date_to: date | None) -> QuerySet[Invoice]:
    queryset = Invoice.objects.select_related("customer").order_by("invoice_date", "pk")
    if date_from is not None:
        queryset = queryset.filter(invoice_date__gte=date_from)
    if date_to is not None:
        queryset = queryset.filter(invoice_date__lte=date_to)
    return queryset


def sales_register(date_from: date | None = None, date_to: date | None = None) -> ReportResult:
    """Every posted invoice in the range, with its GST split and status."""
    validate_range(date_from, date_to)
    rows: list[dict[str, Any]] = []
    totals = {
        "taxable": Decimal("0.00"),
        "cgst": Decimal("0.00"),
        "sgst": Decimal("0.00"),
        "igst": Decimal("0.00"),
        "total": Decimal("0.00"),
    }
    for invoice in _invoices(date_from, date_to):
        rows.append(
            {
                "number": invoice.number,
                "invoice_date": invoice.invoice_date,
                "customer": invoice.customer.name,
                "gstin": invoice.customer.gstin,
                "state_code": invoice.place_of_supply_state_code,
                "taxable": invoice.taxable_total,
                "cgst": invoice.cgst_total,
                "sgst": invoice.sgst_total,
                "igst": invoice.igst_total,
                "total": invoice.total,
                "status": "cancelled" if invoice_is_cancelled(invoice) else "posted",
            }
        )
        totals["taxable"] += invoice.taxable_total
        totals["cgst"] += invoice.cgst_total
        totals["sgst"] += invoice.sgst_total
        totals["igst"] += invoice.igst_total
        totals["total"] += invoice.total
    return ReportResult(
        slug="sales-register",
        title="Sales register",
        columns=SALES_REGISTER_COLUMNS,
        rows=tuple(rows),
        totals={key: q2(value) for key, value in totals.items()},
        meta={"invoices": len(rows)},
        date_from=date_from,
        date_to=date_to,
    )


def sales_by_customer(date_from: date | None = None, date_to: date | None = None) -> ReportResult:
    """Taxable value and tax per customer for the invoices in the range."""
    validate_range(date_from, date_to)
    accumulated: dict[int, dict[str, Any]] = {}
    for invoice in _invoices(date_from, date_to):
        row = accumulated.setdefault(
            invoice.customer_id,
            {
                "customer": invoice.customer.name,
                "state_code": invoice.customer.state_code,
                "invoices": 0,
                "taxable": Decimal("0.00"),
                "tax": Decimal("0.00"),
                "total": Decimal("0.00"),
            },
        )
        row["invoices"] += 1
        row["taxable"] += invoice.taxable_total
        row["tax"] += invoice.cgst_total + invoice.sgst_total + invoice.igst_total
        row["total"] += invoice.total

    rows = tuple(
        accumulated[key] for key in sorted(accumulated, key=lambda pk: accumulated[pk]["customer"])
    )
    totals = {
        "invoices": sum((int(row["invoices"]) for row in rows), 0),
        "taxable": q2(sum((row["taxable"] for row in rows), Decimal("0.00"))),
        "tax": q2(sum((row["tax"] for row in rows), Decimal("0.00"))),
        "total": q2(sum((row["total"] for row in rows), Decimal("0.00"))),
    }
    return ReportResult(
        slug="sales-by-customer",
        title="Sales by customer",
        columns=SALES_BY_CUSTOMER_COLUMNS,
        rows=rows,
        totals=totals,
        date_from=date_from,
        date_to=date_to,
    )


def sales_by_product(date_from: date | None = None, date_to: date | None = None) -> ReportResult:
    """Quantity and value per sold item, from the invoice lines in the range."""
    validate_range(date_from, date_to)
    lines = InvoiceLine.objects.select_related("invoice").filter(
        invoice__in=_invoices(date_from, date_to)
    )
    accumulated: dict[int, dict[str, Any]] = {}
    for line in lines:
        row = accumulated.setdefault(
            line.item_id,
            {
                "item": line.description,
                "hsn_code": line.hsn_code,
                "qty": Decimal("0.000"),
                "taxable": Decimal("0.00"),
                "tax": Decimal("0.00"),
                "total": Decimal("0.00"),
            },
        )
        row["qty"] += line.qty
        row["taxable"] += line.taxable_value
        row["tax"] += line.cgst + line.sgst + line.igst
        row["total"] += line.line_total

    rows = tuple(
        accumulated[key] for key in sorted(accumulated, key=lambda pk: accumulated[pk]["item"])
    )
    totals = {
        "qty": q3(sum((row["qty"] for row in rows), Decimal("0.000"))),
        "taxable": q2(sum((row["taxable"] for row in rows), Decimal("0.00"))),
        "tax": q2(sum((row["tax"] for row in rows), Decimal("0.00"))),
        "total": q2(sum((row["total"] for row in rows), Decimal("0.00"))),
    }
    return ReportResult(
        slug="sales-by-product",
        title="Sales by product",
        columns=SALES_BY_PRODUCT_COLUMNS,
        rows=rows,
        totals=totals,
        date_from=date_from,
        date_to=date_to,
    )


def _credit_notes(date_from: date | None, date_to: date | None) -> QuerySet[CreditNote]:
    queryset = CreditNote.objects.select_related("invoice__customer").order_by("created_at", "pk")
    if date_from is not None:
        queryset = queryset.filter(created_at__date__gte=date_from)
    if date_to is not None:
        queryset = queryset.filter(created_at__date__lte=date_to)
    return queryset


def gst_summary(date_from: date | None = None, date_to: date | None = None) -> ReportResult:
    """A GSTR-1-shaped summary: B2B, B2C, HSN, credit notes, documents.

    ``meta.gstr3b_outward_supply`` is the net outward supply (invoices minus
    credit notes) that a GSTR-3B return would carry.
    """
    validate_range(date_from, date_to)
    invoices = list(_invoices(date_from, date_to))
    b2b = [invoice for invoice in invoices if invoice.customer.gstin]
    b2c = [invoice for invoice in invoices if not invoice.customer.gstin]

    rows: list[dict[str, Any]] = []

    def add_section(
        section: str,
        description: str,
        documents: int,
        qty: Decimal,
        taxable: Decimal,
        cgst: Decimal,
        sgst: Decimal,
        igst: Decimal,
    ) -> None:
        rows.append(
            {
                "section": section,
                "description": description,
                "documents": documents,
                "qty": qty,
                "taxable": q2(taxable),
                "cgst": q2(cgst),
                "sgst": q2(sgst),
                "igst": q2(igst),
                "total": q2(taxable + cgst + sgst + igst),
            }
        )

    def invoice_totals(subset: list[Invoice]) -> tuple[Decimal, Decimal, Decimal, Decimal]:
        return (
            sum((invoice.taxable_total for invoice in subset), Decimal("0.00")),
            sum((invoice.cgst_total for invoice in subset), Decimal("0.00")),
            sum((invoice.sgst_total for invoice in subset), Decimal("0.00")),
            sum((invoice.igst_total for invoice in subset), Decimal("0.00")),
        )

    def invoice_qty(subset: list[Invoice]) -> Decimal:
        return q3(
            sum(
                (line.qty for invoice in subset for line in invoice.lines.all()),
                Decimal("0.000"),
            )
        )

    billed_qty = invoice_qty(invoices)
    b2b_taxable, b2b_cgst, b2b_sgst, b2b_igst = invoice_totals(b2b)
    add_section(
        "B2B",
        "Invoices with GSTIN",
        len(b2b),
        invoice_qty(b2b),
        b2b_taxable,
        b2b_cgst,
        b2b_sgst,
        b2b_igst,
    )

    b2c_taxable, b2c_cgst, b2c_sgst, b2c_igst = invoice_totals(b2c)
    add_section(
        "B2C",
        "Invoices without GSTIN",
        len(b2c),
        invoice_qty(b2c),
        b2c_taxable,
        b2c_cgst,
        b2c_sgst,
        b2c_igst,
    )

    notes = list(_credit_notes(date_from, date_to))
    add_section(
        "CN",
        "Credit notes issued",
        len(notes),
        Decimal("0.000"),
        sum((note.taxable_total for note in notes), Decimal("0.00")),
        sum((note.cgst_total for note in notes), Decimal("0.00")),
        sum((note.sgst_total for note in notes), Decimal("0.00")),
        sum((note.igst_total for note in notes), Decimal("0.00")),
    )

    hsn_rows = (
        InvoiceLine.objects.filter(invoice__in=invoices)
        .values("hsn_code")
        .annotate(
            qty_sum=Sum("qty"),
            taxable_sum=Sum("taxable_value"),
            cgst_sum=Sum("cgst"),
            sgst_sum=Sum("sgst"),
            igst_sum=Sum("igst"),
        )
        .order_by("hsn_code")
    )
    for hsn in hsn_rows:
        add_section(
            "HSN",
            hsn["hsn_code"] or "(no HSN)",
            0,
            _qty(hsn["qty_sum"]),
            _money(hsn["taxable_sum"]),
            _money(hsn["cgst_sum"]),
            _money(hsn["sgst_sum"]),
            _money(hsn["igst_sum"]),
        )

    numbers = sorted(invoice.number for invoice in invoices)
    add_section(
        "DOCS",
        "Invoices issued" + (f" ({numbers[0]} to {numbers[-1]})" if numbers else ""),
        len(invoices),
        Decimal("0.000"),
        Decimal("0.00"),
        Decimal("0.00"),
        Decimal("0.00"),
        Decimal("0.00"),
    )

    invoice_taxable, invoice_cgst, invoice_sgst, invoice_igst = invoice_totals(invoices)
    note_taxable = sum((note.taxable_total for note in notes), Decimal("0.00"))
    note_cgst = sum((note.cgst_total for note in notes), Decimal("0.00"))
    note_sgst = sum((note.sgst_total for note in notes), Decimal("0.00"))
    note_igst = sum((note.igst_total for note in notes), Decimal("0.00"))

    totals = {
        "documents": len(invoices),
        "qty": billed_qty,
        "taxable": q2(invoice_taxable),
        "cgst": q2(invoice_cgst),
        "sgst": q2(invoice_sgst),
        "igst": q2(invoice_igst),
        "total": q2(invoice_taxable + invoice_cgst + invoice_sgst + invoice_igst),
    }
    meta = {
        "gstr3b_outward_supply": {
            "taxable": str(q2(invoice_taxable - note_taxable)),
            "cgst": str(q2(invoice_cgst - note_cgst)),
            "sgst": str(q2(invoice_sgst - note_sgst)),
            "igst": str(q2(invoice_igst - note_igst)),
            "total": str(
                q2(invoice_taxable + invoice_cgst + invoice_sgst + invoice_igst)
                - q2(note_taxable + note_cgst + note_sgst + note_igst)
            ),
        },
        "credit_note_taxable": str(q2(note_taxable)),
    }
    return ReportResult(
        slug="gst-summary",
        title="GST summary (GSTR-1 shaped)",
        columns=GST_SUMMARY_COLUMNS,
        rows=tuple(rows),
        totals=totals,
        meta=meta,
        date_from=date_from,
        date_to=date_to,
    )


def purchase_register(date_from: date | None = None, date_to: date | None = None) -> ReportResult:
    """Every purchase line in the range, with its supplier and value."""
    validate_range(date_from, date_to)
    lines = PurchaseLine.objects.select_related("purchase__supplier", "item__uom").order_by(
        "purchase__purchase_date", "purchase_id", "pk"
    )
    if date_from is not None:
        lines = lines.filter(purchase__purchase_date__gte=date_from)
    if date_to is not None:
        lines = lines.filter(purchase__purchase_date__lte=date_to)

    rows: list[dict[str, Any]] = []
    total_value = Decimal("0.00")
    for line in lines:
        rows.append(
            {
                "purchase_date": line.purchase.purchase_date,
                "supplier": line.purchase.supplier.name,
                "reference": line.purchase.reference,
                "item": line.item.name,
                "qty": line.qty,
                "uom": line.item.uom.symbol,
                "unit_cost": line.unit_cost,
                "value": line.value,
            }
        )
        total_value += line.value
    return ReportResult(
        slug="purchase-register",
        title="Purchase register",
        columns=PURCHASE_REGISTER_COLUMNS,
        rows=tuple(rows),
        totals={"value": q2(total_value)},
        date_from=date_from,
        date_to=date_to,
    )


def stock_summary_report(
    date_from: date | None = None, date_to: date | None = None
) -> ReportResult:
    """Current stock for every item (the stock summary is a live view)."""
    validate_range(date_from, date_to)
    rows = tuple(
        {
            "item": row.item.name,
            "item_type": row.item.item_type,
            "uom": row.item.uom.symbol,
            "qty": row.qty,
            "value": row.value,
            "avg_rate": row.avg_rate,
        }
        for row in stock_summary()
    )
    return ReportResult(
        slug="stock-summary",
        title="Stock summary",
        columns=STOCK_SUMMARY_COLUMNS,
        rows=rows,
        totals={"value": q2(sum((Decimal(str(row["value"])) for row in rows), Decimal("0.00")))},
        meta={
            "as_of": kolkata_today().isoformat(),
            "note": "Current balances; date filters do not apply.",
        },
    )


def stock_ledger_report(date_from: date | None = None, date_to: date | None = None) -> ReportResult:
    """Every ledger movement in the range, oldest first."""
    validate_range(date_from, date_to)
    entries = StockLedger.objects.select_related("item").order_by("created_at", "id")
    if date_from is not None:
        entries = entries.filter(created_at__date__gte=date_from)
    if date_to is not None:
        entries = entries.filter(created_at__date__lte=date_to)

    rows: list[dict[str, Any]] = []
    qty_total = Decimal("0.000")
    value_total = Decimal("0.00")
    for entry in entries:
        rows.append(
            {
                "date": timezone.localtime(entry.created_at).date(),
                "item": entry.item.name,
                "movement_type": entry.movement_type,
                "qty": entry.qty,
                "value": entry.value,
                "unit_value": entry.unit_value,
                "source_type": entry.source_type,
                "source_id": entry.source_id,
            }
        )
        qty_total += entry.qty
        value_total += entry.value
    return ReportResult(
        slug="stock-ledger",
        title="Stock ledger",
        columns=STOCK_LEDGER_COLUMNS,
        rows=tuple(rows),
        totals={"qty": q3(qty_total), "value": q2(value_total)},
        date_from=date_from,
        date_to=date_to,
    )


def production_report(date_from: date | None = None, date_to: date | None = None) -> ReportResult:
    """Completed runs in the range with their costs and yield variance."""
    validate_range(date_from, date_to)
    runs = (
        ProductionRun.objects.select_related("product")
        .filter(state=RunState.COMPLETED, completed_at__isnull=False)
        .order_by("completed_at", "pk")
    )
    if date_from is not None:
        runs = runs.filter(completed_at__date__gte=date_from)
    if date_to is not None:
        runs = runs.filter(completed_at__date__lte=date_to)

    from apps.costing.services import run_cost_sheet

    rows: list[dict[str, Any]] = []
    totals = {
        "batches": Decimal("0.000"),
        "planned_output": Decimal("0.000"),
        "good_packets": Decimal("0.000"),
        "materials": Decimal("0.00"),
        "overheads": Decimal("0.00"),
        "total_cost": Decimal("0.00"),
    }
    for run in runs:
        sheet = run_cost_sheet(run)
        yield_row = (
            RunVarianceSnapshot.objects.filter(run=run, kind=VarianceKind.YIELD)
            .order_by("pk")
            .first()
        )
        rows.append(
            {
                "run_id": run.pk,
                "completed_date": timezone.localtime(run.completed_at).date()
                if run.completed_at
                else None,
                "product": run.product.name,
                "batches": run.batches,
                "planned_output": run.planned_output_qty,
                "good_packets": run.good_packets,
                "yield_variance_pct": yield_row.variance_pct if yield_row else None,
                "flagged": run.variance_snapshots.filter(flagged=True).count(),
                "materials": sheet["materials_value"],
                "overheads": sheet["overhead_value"],
                "total_cost": sheet["total_cost"],
                "cost_per_packet": sheet["cost_per_packet"],
            }
        )
        totals["batches"] += run.batches
        totals["planned_output"] += run.planned_output_qty
        totals["good_packets"] += run.good_packets or Decimal("0.000")
        totals["materials"] += Decimal(str(sheet["materials_value"]))
        totals["overheads"] += Decimal(str(sheet["overhead_value"]))
        totals["total_cost"] += Decimal(str(sheet["total_cost"]))

    return ReportResult(
        slug="production-report",
        title="Production report",
        columns=PRODUCTION_REPORT_COLUMNS,
        rows=tuple(rows),
        totals={
            "batches": q3(totals["batches"]),
            "planned_output": q3(totals["planned_output"]),
            "good_packets": q3(totals["good_packets"]),
            "materials": q2(totals["materials"]),
            "overheads": q2(totals["overheads"]),
            "total_cost": q2(totals["total_cost"]),
        },
        date_from=date_from,
        date_to=date_to,
    )


def collections_report(date_from: date | None = None, date_to: date | None = None) -> ReportResult:
    """Money received in the range, split into allocated and advance."""
    validate_range(date_from, date_to)
    payments = (
        Payment.objects.select_related("customer")
        .prefetch_related("allocations")
        .order_by("payment_date", "pk")
    )
    if date_from is not None:
        payments = payments.filter(payment_date__gte=date_from)
    if date_to is not None:
        payments = payments.filter(payment_date__lte=date_to)

    rows: list[dict[str, Any]] = []
    totals = {
        "amount": Decimal("0.00"),
        "allocated": Decimal("0.00"),
        "unallocated": Decimal("0.00"),
    }
    for payment in payments:
        allocated = q2(sum((row.amount for row in payment.allocations.all()), Decimal("0.00")))
        rows.append(
            {
                "payment_date": payment.payment_date,
                "customer": payment.customer.name,
                "amount": payment.amount,
                "allocated": allocated,
                "unallocated": q2(payment.amount - allocated),
                "method": payment.method,
                "reference": payment.reference,
            }
        )
        totals["amount"] += payment.amount
        totals["allocated"] += allocated
        totals["unallocated"] += payment.amount - allocated
    return ReportResult(
        slug="collections",
        title="Collections",
        columns=COLLECTIONS_COLUMNS,
        rows=tuple(rows),
        totals={key: q2(value) for key, value in totals.items()},
        date_from=date_from,
        date_to=date_to,
    )


def outstanding_ageing(date_from: date | None = None, date_to: date | None = None) -> ReportResult:
    """Outstanding money per customer, bucketed by invoice age as of the end date."""
    validate_range(date_from, date_to)
    as_of = date_to or kolkata_today()
    customers: list[Customer] = list(Customer.objects.order_by("name"))

    rows: list[dict[str, Any]] = []
    totals = {
        "outstanding": Decimal("0.00"),
        "bucket_0_30": Decimal("0.00"),
        "bucket_31_60": Decimal("0.00"),
        "bucket_61_90": Decimal("0.00"),
        "bucket_90_plus": Decimal("0.00"),
    }
    keys = ("bucket_0_30", "bucket_31_60", "bucket_61_90", "bucket_90_plus")
    for customer in customers:
        outstanding = customer_outstanding(customer)
        if outstanding == 0:
            continue
        buckets = {bucket.label: bucket.amount for bucket in customer_ageing(customer, as_of=as_of)}
        row: dict[str, Any] = {"customer": customer.name, "outstanding": outstanding}
        for key, label in zip(keys, ("0-30", "31-60", "61-90", "90+"), strict=True):
            amount = buckets.get(label, Decimal("0.00"))
            row[key] = amount
            totals[key] += amount
        totals["outstanding"] += outstanding
        rows.append(row)

    return ReportResult(
        slug="outstanding-ageing",
        title="Outstanding and ageing",
        columns=AGEING_COLUMNS,
        rows=tuple(rows),
        totals={key: q2(value) for key, value in totals.items()},
        meta={"as_of": as_of.isoformat()},
        date_from=date_from,
        date_to=date_to,
    )


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReconciliationCheck:
    """One audit check: an expected value, the actual value and the verdict."""

    name: str
    expected: str
    actual: str
    passed: bool
    detail: str = ""


def reconciliation_checks(
    date_from: date | None = None, date_to: date | None = None
) -> tuple[ReconciliationCheck, ...]:
    """Prove the three report-level reconciliations.

    Checks: every stock balance equals its ledger sum; every invoice total
    equals the sum of its lines; the sales register taxable total equals the
    GST summary's taxable total.
    """
    from apps.inventory.services import reconcile_stock

    issues = reconcile_stock()
    stock_check = ReconciliationCheck(
        name="stock balance equals ledger sum",
        expected="0 differences",
        actual=f"{len(issues)} difference(s)",
        passed=not issues,
        detail=", ".join(f"item {issue.item_id}" for issue in issues[:5]),
    )

    invoice_mismatches: list[str] = []
    for invoice in Invoice.objects.prefetch_related("lines").order_by("pk"):
        line_total = sum((line.line_total for line in invoice.lines.all()), Decimal("0.00"))
        if q2(line_total) != invoice.total:
            invoice_mismatches.append(
                f"{invoice.number}: lines {q2(line_total)} vs total {invoice.total}"
            )
    invoice_check = ReconciliationCheck(
        name="invoice total equals line sums",
        expected="0 differences",
        actual=f"{len(invoice_mismatches)} difference(s)",
        passed=not invoice_mismatches,
        detail="; ".join(invoice_mismatches[:5]),
    )

    register = sales_register(date_from, date_to)
    gst = gst_summary(date_from, date_to)
    register_taxable = register.totals.get("taxable", Decimal("0.00"))
    gst_taxable = gst.totals.get("taxable", Decimal("0.00"))
    taxable_check = ReconciliationCheck(
        name="sales register taxable equals GST summary taxable",
        expected=str(q2(register_taxable)),
        actual=str(q2(gst_taxable)),
        passed=q2(register_taxable) == q2(gst_taxable),
    )

    return (stock_check, invoice_check, taxable_check)
