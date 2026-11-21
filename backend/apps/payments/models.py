"""Payments models – money received from customers and its allocation.

Invariants protected:
- A payment is a positive NUMERIC(14,2) amount; money is never a float.
- An allocation points at one invoice and is unique per (payment, invoice), so
  a payment cannot be counted twice against the same invoice.
- Payments and allocations are business documents: they are never deleted, and
  a correction is a new document, not an edit.
"""

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone


class PaymentMethod(models.TextChoices):
    CASH = "cash", "Cash"
    UPI = "upi", "UPI"
    BANK = "bank", "Bank transfer"
    CHEQUE = "cheque", "Cheque"


class Payment(models.Model):
    """Money received from a customer, with optional allocations to invoices."""

    customer = models.ForeignKey(
        "masters.Customer",
        on_delete=models.PROTECT,
        related_name="payments",
    )
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    payment_date = models.DateField()
    method = models.CharField(
        max_length=20,
        choices=PaymentMethod.choices,
        default=PaymentMethod.CASH,
    )
    reference = models.CharField(max_length=64, blank=True)
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
        db_table = "payments_payment"
        ordering = ["-payment_date", "-pk"]
        indexes = [
            models.Index(fields=["customer", "payment_date"], name="idx_payment_customer_date"),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(amount__gt=0),
                name="chk_payment_amount_positive",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.customer.name} {self.amount} on {self.payment_date}"


class PaymentAllocation(models.Model):
    """How much of a payment settles one invoice."""

    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="allocations")
    invoice = models.ForeignKey(
        "sales.Invoice",
        on_delete=models.PROTECT,
        related_name="allocations",
    )
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        db_table = "payments_payment_allocation"
        ordering = ["pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["payment", "invoice"],
                name="uniq_payment_allocation_invoice",
            ),
            models.CheckConstraint(
                check=models.Q(amount__gt=0),
                name="chk_allocation_amount_positive",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.payment_id} -> {self.invoice.number}: {self.amount}"
