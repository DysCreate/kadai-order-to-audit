"""Report framework – column metadata and the JSON, CSV, Excel and PDF renderers.

Invariants protected:
- A report is data, not a screen: the same ``ReportResult`` feeds the JSON API
  and all three export formats, so a downloaded file never disagrees with the
  page it came from.
- Money is formatted from ``Decimal`` values with two places and quantities
  with three; the renderers never convert money through ``float``.
- CSV and Excel files include the report's totals row when the report defines
  one, so an exported ledger can be re-added and match the API.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any
from xml.sax.saxutils import escape

from core.errors import DomainError

KIND_TEXT = "text"
KIND_MONEY = "money"
KIND_QTY = "qty"
KIND_RATE = "rate"
KIND_INT = "int"
KIND_DATE = "date"
KIND_BOOL = "bool"
KIND_PERCENT = "percent"
KIND_VARIANCE = "variance"

_PLACES = {
    KIND_MONEY: 2,
    KIND_QTY: 3,
    KIND_RATE: 4,
    KIND_PERCENT: 2,
    KIND_VARIANCE: 6,
}

_EXCEL_FORMATS = {
    KIND_MONEY: "#,##0.00",
    KIND_QTY: "#,##0.000",
    KIND_RATE: "#,##0.0000",
    KIND_PERCENT: "0.00%",
    KIND_VARIANCE: "0.000000",
}


@dataclass(frozen=True)
class Column:
    """One report column and how its values should be rendered."""

    key: str
    label: str
    kind: str = KIND_TEXT


@dataclass(frozen=True)
class ReportResult:
    """One report's columns, rows, totals and context.

    ``totals`` is a mapping of column key to Decimal for the footer row;
    ``meta`` carries report-specific context such as the GSTR-3B outward
    supply total, which is not a table column.
    """

    slug: str
    title: str
    columns: tuple[Column, ...]
    rows: tuple[dict[str, Any], ...]
    totals: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)
    date_from: date | None = None
    date_to: date | None = None


def validate_range(date_from: date | None, date_to: date | None) -> None:
    """Refuse a range whose start is after its end."""
    if date_from is not None and date_to is not None and date_from > date_to:
        raise DomainError("date_from cannot be after date_to.")


def _format_decimal(value: Decimal, kind: str) -> str:
    places = _PLACES.get(kind)
    if places is None:
        return str(value)
    return f"{value:.{places}f}"


def display_value(value: Any, kind: str) -> str:
    """Return a human- and file-friendly string for one cell."""
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return _format_decimal(value, kind)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def serialized_row(result: ReportResult, row: dict[str, Any]) -> dict[str, str]:
    """Serialise one row with every value as a string (Decimals never floats)."""
    return {
        column.key: display_value(row.get(column.key), column.kind) for column in result.columns
    }


def render_csv(result: ReportResult) -> bytes:
    """Render a report as RFC 4180-style CSV bytes."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow([column.label for column in result.columns])
    for row in result.rows:
        writer.writerow(
            [display_value(row.get(column.key), column.kind) for column in result.columns]
        )
    if result.totals:
        writer.writerow(_totals_row(result))
    return buffer.getvalue().encode("utf-8")


def _totals_row(result: ReportResult) -> list[str]:
    values: list[str] = []
    for index, column in enumerate(result.columns):
        if index == 0:
            values.append("Total")
        else:
            values.append(display_value(result.totals.get(column.key), column.kind))
    return values


def render_excel(result: ReportResult) -> bytes:
    """Render a report as an .xlsx workbook with a bold header and totals row."""
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = result.slug[:31]

    sheet.append([column.label for column in result.columns])
    for cell in sheet[1]:
        cell.font = Font(bold=True)

    for row in result.rows:
        sheet.append([row.get(column.key) for column in result.columns])

    if result.totals:
        sheet.append(["Total"] + [result.totals.get(column.key) for column in result.columns[1:]])
        for cell in sheet[sheet.max_row]:
            cell.font = Font(bold=True)

    for index, column in enumerate(result.columns, start=1):
        letter = get_column_letter(index)
        sheet.column_dimensions[letter].width = max(12, len(column.label) + 4)
        number_format = _EXCEL_FORMATS.get(column.kind)
        if number_format is not None:
            for row_number in range(2, sheet.max_row + 1):
                sheet.cell(row=row_number, column=index).number_format = number_format

    sheet.freeze_panes = "A2"
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def render_pdf(result: ReportResult) -> bytes:
    """Render a report as A4 landscape PDF bytes with WeasyPrint."""
    from weasyprint import HTML

    header = "".join(f"<th>{escape(column.label)}</th>" for column in result.columns)
    body_rows: list[str] = []
    for row in result.rows:
        cells = "".join(
            f"<td>{escape(display_value(row.get(column.key), column.kind))}</td>"
            for column in result.columns
        )
        body_rows.append(f"<tr>{cells}</tr>")
    total_row = ""
    if result.totals:
        cells = "".join(f"<td>{escape(value)}</td>" for value in _totals_row(result))
        total_row = f'<tr class="total">{cells}</tr>'

    period = ""
    if result.date_from is not None or result.date_to is not None:
        period = (
            f"<p>{escape(result.date_from.isoformat() if result.date_from else 'start')}"
            f" to {escape(result.date_to.isoformat() if result.date_to else 'today')}</p>"
        )

    html = f"""
    <html><head><meta charset="utf-8"><style>
      @page {{ size: A4 landscape; margin: 14mm; }}
      body {{ font-family: sans-serif; font-size: 10px; color: #111; }}
      h1 {{ font-size: 18px; margin: 0 0 4px; }}
      p {{ margin: 0 0 10px; color: #555; }}
      table {{ width: 100%; border-collapse: collapse; }}
      th, td {{ border: 1px solid #ccc; padding: 4px 6px; text-align: left; }}
      th {{ background: #eef2f7; }}
      td {{ text-align: right; }}
      th:first-child, td:first-child {{ text-align: left; }}
      tr.total td {{ font-weight: bold; background: #f8fafc; }}
    </style></head><body>
      <h1>{escape(result.title)}</h1>
      {period}
      <table><thead><tr>{header}</tr></thead>
      <tbody>{"".join(body_rows)}{total_row}</tbody></table>
    </body></html>
    """
    return bytes(HTML(string=html).write_pdf())


def report_filename(result: ReportResult, extension: str) -> str:
    """Return a ``slug_from_to.ext`` filename for a download."""
    start = result.date_from.isoformat() if result.date_from else "all"
    end = result.date_to.isoformat() if result.date_to else "all"
    return f"{result.slug}_{start}_{end}.{extension}"
