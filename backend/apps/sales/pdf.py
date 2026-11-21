"""Invoice rendering, signed expiring PDF links and share messages.

Invariants protected:
- The PDF is rendered from the same stored invoice rows the API returns, via
  WeasyPrint and an HTML template (never a headless browser).
- A shared link carries a Django-signed invoice id with a seven-day expiry, so
  a WhatsApp recipient can open the PDF without a session and a leaked link
  stops working.
- Share messages are plain text built from stored totals; they never recompute
  money.
"""

from __future__ import annotations

from urllib.parse import quote

from django.core import signing
from django.template.loader import render_to_string

from apps.masters.services import get_setting

from .amounts import amount_in_words
from .models import Invoice
from .services import invoice_is_cancelled

PDF_SALT = "kadai.invoice.pdf"
PDF_LINK_MAX_AGE_SECONDS = 7 * 24 * 60 * 60


def invoice_pdf_token(invoice: Invoice) -> str:
    """Return a signed, expiring token for an invoice PDF."""
    return signing.dumps(invoice.pk, salt=PDF_SALT)


def invoice_id_from_token(token: str) -> int:
    """Return the invoice id from a signed token, or raise BadSignature."""
    return int(signing.loads(token, salt=PDF_SALT, max_age=PDF_LINK_MAX_AGE_SECONDS))


def render_invoice_html(invoice: Invoice) -> str:
    """Render the invoice as HTML (the same markup the PDF is built from)."""
    context = {
        "invoice": invoice,
        "lines": invoice.lines.select_related("item__uom").order_by("pk"),
        "credit_notes": invoice.credit_notes.order_by("pk"),
        "is_cancelled": invoice_is_cancelled(invoice),
        "amount_in_words": amount_in_words(invoice.total),
        "factory": {
            "name": get_setting("factory_name", "Kadai Snacks"),
            "gstin": get_setting("factory_gstin", ""),
            "address": get_setting("factory_address", ""),
            "state_code": get_setting("factory_state_code", "33"),
        },
    }
    return render_to_string("sales/invoice.html", context)


def render_invoice_pdf(invoice: Invoice) -> bytes:
    """Render the invoice to PDF bytes with WeasyPrint."""
    from weasyprint import HTML

    pdf: bytes = HTML(string=render_invoice_html(invoice)).write_pdf()
    return pdf


def invoice_share_links(*, invoice: Invoice, pdf_url: str) -> dict[str, str]:
    """Return the WhatsApp and mailto share links for an invoice PDF URL."""
    factory_name = get_setting("factory_name", "Kadai Snacks") or "Kadai Snacks"
    message = f"Invoice {invoice.number} from {factory_name}: Rs {invoice.total}. PDF: {pdf_url}"
    subject = f"Invoice {invoice.number} from {factory_name}"
    return {
        "pdf_url": pdf_url,
        "whatsapp": f"https://wa.me/?text={quote(message, safe='')}",
        "mailto": f"mailto:?subject={quote(subject, safe='')}&body={quote(message, safe='')}",
    }
