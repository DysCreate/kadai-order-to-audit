"""Sales models – orders, GST invoices, dispatches and credit notes.

Invariants protected:
- An order is submitted once per ``client_uuid``; the unique constraint makes a
  retried submit idempotent at the database level.
- An order follows SUBMITTED -> APPROVED -> INVOICED -> DISPATCHED, or
  SUBMITTED -> REJECTED. Quantities are NUMERIC(14,3), money NUMERIC(14,2).
- A posted invoice is immutable: a database trigger (migration 0002) rejects
  UPDATE and DELETE. Corrections are credit notes, never edits or deletes.
- Document numbers (INV/CN/ORD) are allocated from a per-financial-year counter
  row locked with SELECT ... FOR UPDATE, and fit the 16-character GST limit.
- Invoice and credit-note lines snapshot HSN, rate, quantity and price, so a
  later product edit cannot rewrite an issued tax document.
- Dispatches and credit notes are append-only business documents; dispatched
  and credited quantities are derived by summing their lines, which keeps the
  invoice itself untouched.
"""

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone


class OrderState(models.TextChoices):
    SUBMITTED = "SUBMITTED", "Submitted"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"
    INVOICED = "INVOICED", "Invoiced"
    DISPATCHED = "DISPATCHED", "Dispatched"


class DocumentType(models.TextChoices):
    ORDER = "ORD", "Sales order"
    INVOICE = "INV", "GST invoice"
    CREDIT_NOTE = "CN", "Credit note"


class DocumentSequence(models.Model):
    """Per-financial-year counter for one document type.

    Rows are locked with SELECT ... FOR UPDATE before a number is taken, so two
    concurrent invoices can never share a number.
    """

    doc_type = models.CharField(max_length=3, choices=DocumentType.choices)
    financial_year = models.CharField(max_length=5, help_text="Indian financial year, e.g. 26-27.")
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "sales_document_sequence"
        ordering = ["doc_type", "financial_year"]
        constraints = [
            models.UniqueConstraint(
                fields=["doc_type", "financial_year"],
                name="uniq_document_sequence",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.doc_type}/{self.financial_year}: {self.last_number}"


class Order(models.Model):
    """A salesman's sales order, from submit to dispatch.

    ``client_uuid`` is generated on the device before the request, so a retry
    after a dropped connection returns the same order instead of duplicating it.
    ``number`` is allocated under a row lock from ``DocumentSequence``.
    """

    number = models.CharField(max_length=16, unique=True)
    client_uuid = models.UUIDField(unique=True)
    customer = models.ForeignKey(
        "masters.Customer",
        on_delete=models.PROTECT,
        related_name="orders",
    )
    salesman = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="orders",
    )
    state = models.CharField(
        max_length=20,
        choices=OrderState.choices,
        default=OrderState.SUBMITTED,
        db_index=True,
    )
    notes = models.CharField(max_length=255, blank=True)
    rejection_reason = models.CharField(max_length=255, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "sales_order"
        ordering = ["-created_at", "-pk"]
        indexes = [
            models.Index(fields=["state", "created_at"], name="idx_order_state_created"),
            models.Index(fields=["customer", "created_at"], name="idx_order_customer_created"),
        ]

    def __str__(self) -> str:
        return f"{self.number} ({self.state})"


class OrderLine(models.Model):
    """One requested item, with the price resolved at submit time.

    ``unit_price`` is a snapshot: a later price-list edit does not change an
    order that has already been taken (or an invoice raised from it).
    """

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey("masters.Item", on_delete=models.PROTECT, related_name="order_lines")
    qty = models.DecimalField(max_digits=14, decimal_places=3)
    unit_price = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        db_table = "sales_order_line"
        ordering = ["pk"]
        constraints = [
            models.UniqueConstraint(fields=["order", "item"], name="uniq_order_line_item"),
            models.CheckConstraint(check=models.Q(qty__gt=0), name="chk_order_line_qty_positive"),
            models.CheckConstraint(
                check=models.Q(unit_price__gte=0),
                name="chk_order_line_price_non_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.item.name} {self.qty} @ {self.unit_price}"


class Invoice(models.Model):
    """A posted GST invoice. Immutable once written (trigger enforced).

    ``place_of_supply_state_code`` is the customer's state; ``is_interstate``
    records whether IGST or CGST+SGST was applied, so the tax split is auditable
    even if the customer's state is corrected later.
    """

    number = models.CharField(max_length=16, unique=True)
    order = models.OneToOneField(
        Order,
        on_delete=models.PROTECT,
        related_name="invoice",
    )
    customer = models.ForeignKey(
        "masters.Customer",
        on_delete=models.PROTECT,
        related_name="invoices",
    )
    invoice_date = models.DateField()
    place_of_supply_state_code = models.CharField(max_length=2)
    is_interstate = models.BooleanField(default=False)
    taxable_total = models.DecimalField(max_digits=14, decimal_places=2)
    cgst_total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    sgst_total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    igst_total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    round_off = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    total = models.DecimalField(max_digits=14, decimal_places=2)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "sales_invoice"
        ordering = ["-created_at", "-pk"]
        indexes = [
            models.Index(fields=["customer", "invoice_date"], name="idx_invoice_customer_date"),
        ]

    def __str__(self) -> str:
        return self.number


class InvoiceLine(models.Model):
    """One taxable line, with its HSN, rate and per-line tax rounded to paise."""

    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="lines")
    item = models.ForeignKey("masters.Item", on_delete=models.PROTECT, related_name="invoice_lines")
    description = models.CharField(max_length=200)
    hsn_code = models.CharField(max_length=20, blank=True)
    qty = models.DecimalField(max_digits=14, decimal_places=3)
    unit_price = models.DecimalField(max_digits=14, decimal_places=2)
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2)
    taxable_value = models.DecimalField(max_digits=14, decimal_places=2)
    cgst = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    sgst = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    igst = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    line_total = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        db_table = "sales_invoice_line"
        ordering = ["pk"]
        constraints = [
            models.UniqueConstraint(fields=["invoice", "item"], name="uniq_invoice_line_item"),
            models.CheckConstraint(check=models.Q(qty__gt=0), name="chk_invoice_line_qty_positive"),
        ]

    def __str__(self) -> str:
        return f"{self.description} {self.qty}"


class Dispatch(models.Model):
    """A finished-goods dispatch against an invoice.

    The dispatch document is the ledger source (source_type = dispatch,
    source_id = this row's pk). It is append-only: a partial dispatch is a new
    dispatch row, never an edit of an old one.
    """

    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="dispatches")
    dispatch_date = models.DateField()
    notes = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "sales_dispatch"
        ordering = ["-created_at", "-pk"]

    def __str__(self) -> str:
        return f"Dispatch {self.pk} for {self.invoice.number}"


class DispatchLine(models.Model):
    """Quantity of one invoice line that left the factory."""

    dispatch = models.ForeignKey(Dispatch, on_delete=models.PROTECT, related_name="lines")
    invoice_line = models.ForeignKey(
        InvoiceLine,
        on_delete=models.PROTECT,
        related_name="dispatch_lines",
    )
    qty = models.DecimalField(max_digits=14, decimal_places=3)

    class Meta:
        db_table = "sales_dispatch_line"
        ordering = ["pk"]
        constraints = [
            models.CheckConstraint(
                check=models.Q(qty__gt=0),
                name="chk_dispatch_line_qty_positive",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.invoice_line.description} {self.qty}"


class CreditNote(models.Model):
    """A credit note that cancels part or all of an invoice.

    Issuing a credit note never edits the invoice. When the credited quantity
    covers every invoice line, the invoice is treated as cancelled (derived,
    not stored), and an optional restock returns the goods to finished stock.
    """

    number = models.CharField(max_length=16, unique=True)
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="credit_notes")
    reason = models.CharField(max_length=255)
    restock = models.BooleanField(default=False)
    taxable_total = models.DecimalField(max_digits=14, decimal_places=2)
    cgst_total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    sgst_total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    igst_total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    round_off = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    total = models.DecimalField(max_digits=14, decimal_places=2)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "sales_credit_note"
        ordering = ["-created_at", "-pk"]

    def __str__(self) -> str:
        return self.number


class CreditNoteLine(models.Model):
    """Credited quantity and tax for one invoice line."""

    credit_note = models.ForeignKey(CreditNote, on_delete=models.PROTECT, related_name="lines")
    invoice_line = models.ForeignKey(
        InvoiceLine,
        on_delete=models.PROTECT,
        related_name="credit_note_lines",
    )
    qty = models.DecimalField(max_digits=14, decimal_places=3)
    taxable_value = models.DecimalField(max_digits=14, decimal_places=2)
    cgst = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    sgst = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    igst = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    line_total = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        db_table = "sales_credit_note_line"
        ordering = ["pk"]
        constraints = [
            models.CheckConstraint(check=models.Q(qty__gt=0), name="chk_credit_line_qty_positive"),
        ]

    def __str__(self) -> str:
        return f"{self.invoice_line.description} -{self.qty}"
