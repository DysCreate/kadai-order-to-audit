"""Unit tests for the report framework renderers.

Requirement: Phase 5 – one ``ReportResult`` feeds JSON, CSV, Excel and PDF, and
an exported file must load back with the same rows and totals. No database is
touched here; the query functions are covered by the API tests.
"""

from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal
from io import BytesIO, StringIO

import pytest
from openpyxl import load_workbook

from apps.reports.framework import (
    KIND_DATE,
    KIND_MONEY,
    KIND_QTY,
    Column,
    ReportResult,
    display_value,
    render_csv,
    render_excel,
    render_pdf,
    report_filename,
    validate_range,
)
from core.errors import DomainError


def _result() -> ReportResult:
    return ReportResult(
        slug="sample-report",
        title="Sample report",
        columns=(
            Column("item", "Item"),
            Column("date", "Date", KIND_DATE),
            Column("qty", "Quantity", KIND_QTY),
            Column("value", "Value", KIND_MONEY),
        ),
        rows=(
            {
                "item": "Flour",
                "date": date(2026, 5, 20),
                "qty": Decimal("40.000"),
                "value": Decimal("1725.00"),
            },
            {
                "item": "Oil",
                "date": date(2026, 5, 21),
                "qty": Decimal("10.500"),
                "value": Decimal("1470.00"),
            },
        ),
        totals={"qty": Decimal("50.500"), "value": Decimal("3195.00")},
        date_from=date(2026, 5, 1),
        date_to=date(2026, 5, 31),
    )


def test_csv_round_trips_rows_and_totals() -> None:
    """Phase 5: the CSV file loads back with the same figures as the table."""
    parsed = list(csv.reader(StringIO(render_csv(_result()).decode("utf-8"))))

    assert parsed[0] == ["Item", "Date", "Quantity", "Value"]
    assert parsed[1] == ["Flour", "2026-05-20", "40.000", "1725.00"]
    assert parsed[2] == ["Oil", "2026-05-21", "10.500", "1470.00"]
    assert parsed[3] == ["Total", "", "50.500", "3195.00"]


def test_excel_round_trips_rows_and_number_formats() -> None:
    """Phase 5: the workbook loads back and keeps Decimal money as numbers."""
    workbook = load_workbook(BytesIO(render_excel(_result())))
    sheet = workbook.active

    assert sheet.title == "sample-report"
    assert [cell.value for cell in sheet[1]] == ["Item", "Date", "Quantity", "Value"]
    assert sheet["A2"].value == "Flour"
    assert float(sheet["D2"].value) == 1725.00
    assert sheet["D2"].number_format == "#,##0.00"
    assert sheet["C2"].number_format == "#,##0.000"
    assert [cell.value for cell in sheet[4]] == ["Total", None, 50.5, 3195.0]


def test_pdf_starts_with_a_pdf_header() -> None:
    """Phase 5: WeasyPrint produces a real PDF, not an HTML page."""
    content = render_pdf(_result())

    assert content.startswith(b"%PDF")


def test_display_value_keeps_decimal_places() -> None:
    """Phase 5: money has two places and quantities three, even for integers."""
    assert display_value(Decimal("50"), KIND_MONEY) == "50.00"
    assert display_value(Decimal("50"), KIND_QTY) == "50.000"
    assert display_value(None, KIND_MONEY) == ""


def test_range_validation_refuses_reversed_dates() -> None:
    """Phase 5 negative path: a start after its end is a domain error."""
    with pytest.raises(DomainError):
        validate_range(date(2026, 5, 31), date(2026, 5, 1))


def test_filename_encodes_the_range() -> None:
    """Phase 5: a download name identifies the report and its period."""
    assert report_filename(_result(), "csv") == "sample-report_2026-05-01_2026-05-31.csv"
