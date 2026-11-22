"""Reports services – the registry, report execution and export negotiation.

Invariants protected:
- The registry is the single list of report slugs; an unknown slug is a domain
  error, never a silent empty table.
- Every report runs through one date-range validator before it reads rows.
- Exports are rendered from the very ``ReportResult`` the JSON response uses,
  so a downloaded file and an on-screen table always carry the same numbers.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from core.errors import DomainError

from . import queries
from .framework import (
    Column,
    ReportResult,
    render_csv,
    render_excel,
    render_pdf,
    report_filename,
    validate_range,
)


@dataclass(frozen=True)
class ReportDefinition:
    """One registered report: its identity, columns and query function."""

    slug: str
    title: str
    columns: tuple[Column, ...]
    fetch: Callable[[date | None, date | None], ReportResult]


REPORTS: dict[str, ReportDefinition] = {
    definition.slug: definition
    for definition in (
        ReportDefinition(
            "sales-register",
            "Sales register",
            queries.SALES_REGISTER_COLUMNS,
            queries.sales_register,
        ),
        ReportDefinition(
            "sales-by-customer",
            "Sales by customer",
            queries.SALES_BY_CUSTOMER_COLUMNS,
            queries.sales_by_customer,
        ),
        ReportDefinition(
            "sales-by-product",
            "Sales by product",
            queries.SALES_BY_PRODUCT_COLUMNS,
            queries.sales_by_product,
        ),
        ReportDefinition(
            "gst-summary",
            "GST summary (GSTR-1 shaped)",
            queries.GST_SUMMARY_COLUMNS,
            queries.gst_summary,
        ),
        ReportDefinition(
            "purchase-register",
            "Purchase register",
            queries.PURCHASE_REGISTER_COLUMNS,
            queries.purchase_register,
        ),
        ReportDefinition(
            "stock-summary",
            "Stock summary",
            queries.STOCK_SUMMARY_COLUMNS,
            queries.stock_summary_report,
        ),
        ReportDefinition(
            "stock-ledger",
            "Stock ledger",
            queries.STOCK_LEDGER_COLUMNS,
            queries.stock_ledger_report,
        ),
        ReportDefinition(
            "production-report",
            "Production report",
            queries.PRODUCTION_REPORT_COLUMNS,
            queries.production_report,
        ),
        ReportDefinition(
            "collections",
            "Collections",
            queries.COLLECTIONS_COLUMNS,
            queries.collections_report,
        ),
        ReportDefinition(
            "outstanding-ageing",
            "Outstanding and ageing",
            queries.AGEING_COLUMNS,
            queries.outstanding_ageing,
        ),
    )
}


def report_catalog() -> list[ReportDefinition]:
    """Return the registered reports in display order."""
    return list(REPORTS.values())


def get_report(slug: str) -> ReportDefinition:
    """Return one registered report or raise a domain error."""
    try:
        return REPORTS[slug]
    except KeyError as exc:
        raise DomainError(f"Unknown report {slug!r}.") from exc


def run_report(
    slug: str, date_from: date | None = None, date_to: date | None = None
) -> ReportResult:
    """Validate the range and run one report through its query function."""
    validate_range(date_from, date_to)
    return get_report(slug).fetch(date_from, date_to)


def export_report(result: ReportResult, fmt: str) -> tuple[bytes, str, str]:
    """Render a report in a requested format.

    Returns ``(content, content_type, filename)`` for JSON callers, CSV, Excel
    and PDF downloads.
    """
    if fmt == "csv":
        return render_csv(result), "text/csv; charset=utf-8", report_filename(result, "csv")
    if fmt in ("excel", "xlsx"):
        return (
            render_excel(result),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            report_filename(result, "xlsx"),
        )
    if fmt == "pdf":
        return render_pdf(result), "application/pdf", report_filename(result, "pdf")
    raise DomainError(f"Unsupported report format {fmt!r}; use json, csv, excel or pdf.")
