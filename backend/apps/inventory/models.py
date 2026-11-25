"""Inventory models – append-only stock ledger and its balance cache.

Invariants protected:
- ``stock_ledger`` is append-only. A database trigger (migration 0002) rejects
  UPDATE and DELETE, so history can never be rewritten.
- Every ledger row is traceable: ``source_type`` and ``source_id`` are non-null.
- ``stock_balance`` carries ``CHECK (qty >= 0)`` and must always equal the sum
  of the ledger rows for its item.
- Quantities are NUMERIC(14,3); values NUMERIC(14,2); unit rates NUMERIC(14,4).
"""

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.masters.models import Item
from core.tenancy import OrganizationScopedModel


class MovementType(models.TextChoices):
    OPENING = "OPENING", "Opening balance"
    RECEIPT = "RECEIPT", "Receipt"
    ISSUE = "ISSUE", "Issue"
    ADJUSTMENT = "ADJUSTMENT", "Adjustment"


class SourceType(models.TextChoices):
    OPENING = "opening", "Opening balance"
    PURCHASE = "purchase", "Purchase"
    PRODUCTION_RUN = "production_run", "Production run"
    DISPATCH = "dispatch", "Dispatch"
    ADJUSTMENT = "adjustment", "Adjustment"
    CREDIT_NOTE = "credit_note", "Credit note"


class StockLedger(OrganizationScopedModel):
    """One append-only stock movement for one item.

    ``qty`` is signed: positive for stock in (OPENING, RECEIPT), negative for
    stock out (ISSUE). ``value`` is the signed money movement in the same
    direction. ``unit_value`` snapshots the rate used, for audit.
    """

    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="ledger_entries")
    batch_id = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        help_text="Reserved for batch/expiry tracking; nullable from day one.",
    )
    movement_type = models.CharField(max_length=20, choices=MovementType.choices, db_index=True)
    qty = models.DecimalField(max_digits=14, decimal_places=3)
    value = models.DecimalField(max_digits=14, decimal_places=2)
    unit_value = models.DecimalField(max_digits=14, decimal_places=4)
    source_type = models.CharField(max_length=20, choices=SourceType.choices)
    source_id = models.PositiveBigIntegerField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "inventory_stock_ledger"
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["item", "created_at"], name="idx_ledger_item_created"),
            models.Index(fields=["source_type", "source_id"], name="idx_ledger_source"),
        ]

    def __str__(self) -> str:
        return f"{self.item.name} {self.qty} ({self.movement_type})"


class StockBalance(OrganizationScopedModel):
    """Denormalised per-item balance, always equal to SUM(stock_ledger).

    Rows are locked with SELECT ... FOR UPDATE by the services layer, in
    ascending item-id order, before any movement is posted.
    """

    item = models.OneToOneField(
        Item,
        on_delete=models.PROTECT,
        primary_key=True,
        related_name="stock_balance",
    )
    qty = models.DecimalField(max_digits=14, decimal_places=3, default=Decimal("0.000"))
    value = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "inventory_stock_balance"
        verbose_name_plural = "stock balances"
        constraints = [
            models.CheckConstraint(
                check=models.Q(qty__gte=0),
                name="chk_stock_balance_qty_non_negative",
            ),
            models.CheckConstraint(
                check=models.Q(qty__gt=0) | models.Q(value=0),
                name="chk_stock_balance_zero_qty_zero_value",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.item.name}: {self.qty} @ {self.value}"


class Purchase(OrganizationScopedModel):
    """Goods received from a supplier.

    The purchase is the source document for its RECEIPT ledger rows
    (source_type = purchase, source_id = this row's pk). Purchases are never
    edited or deleted once posted; a mistake is corrected with a stock
    adjustment that cites the reason.
    """

    supplier = models.ForeignKey(
        "masters.Supplier",
        on_delete=models.PROTECT,
        related_name="purchases",
    )
    reference = models.CharField(max_length=64, blank=True, help_text="Supplier bill number.")
    purchase_date = models.DateField(default=timezone.localdate)
    total_value = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
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
        db_table = "inventory_purchase"
        ordering = ["-created_at", "-pk"]

    def __str__(self) -> str:
        return f"Purchase {self.pk} from {self.supplier.name}"


class PurchaseLine(OrganizationScopedModel):
    """One item received on a purchase, at its purchase rate."""

    purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="purchase_lines")
    qty = models.DecimalField(max_digits=14, decimal_places=3)
    unit_cost = models.DecimalField(max_digits=14, decimal_places=4)
    value = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        db_table = "inventory_purchase_line"
        ordering = ["pk"]
        constraints = [
            models.CheckConstraint(
                check=models.Q(qty__gt=0),
                name="chk_purchase_line_qty_positive",
            ),
            models.CheckConstraint(
                check=models.Q(unit_cost__gte=0),
                name="chk_purchase_line_cost_non_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.item.name} {self.qty} @ {self.unit_cost}"


class StockAdjustment(OrganizationScopedModel):
    """Manual stock correction with a mandatory reason.

    The adjustment row is the source document for the ledger movement it
    creates (source_type = adjustment, source_id = this row's pk).
    """

    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="adjustments")
    qty_delta = models.DecimalField(max_digits=14, decimal_places=3)
    reason = models.CharField(max_length=255)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "inventory_stock_adjustment"
        ordering = ["-created_at", "-pk"]

    def __str__(self) -> str:
        return f"{self.item.name} {self.qty_delta}: {self.reason}"
