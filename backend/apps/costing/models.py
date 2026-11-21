"""Costing models – overhead entries and their allocation to production runs.

Invariants protected:
- A run overhead belongs to exactly one completed run and is assigned fully to
  that run. A monthly pool has no run; it is split across completed runs in its
  month by standard batch-hours.
- Amounts are NUMERIC(14,2) Decimals and strictly positive.
- An allocation row is unique per (overhead entry, run), so re-running an
  allocation cannot double-charge a run.
- Overhead value reaches finished goods only through a value-only ledger
  adjustment (qty 0); this table never writes stock directly.
"""

from datetime import date

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.inventory.models import StockLedger
from apps.production.models import ProductionRun


class OverheadScope(models.TextChoices):
    """Whether an overhead belongs to one run or to a monthly pool."""

    RUN = "RUN", "Run"
    MONTH = "MONTH", "Monthly pool"


class OverheadCategory(models.TextChoices):
    LABOUR = "labour", "Labour"
    POWER = "power", "Gas and power"
    OTHER = "other", "Other"


class OverheadEntry(models.Model):
    """One overhead amount entered against a run or a calendar month."""

    scope = models.CharField(max_length=10, choices=OverheadScope.choices, db_index=True)
    run = models.ForeignKey(
        ProductionRun,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="overhead_entries",
    )
    period = models.DateField(
        null=True,
        blank=True,
        db_index=True,
        help_text="First day of the month for a monthly pool.",
    )
    category = models.CharField(max_length=20, choices=OverheadCategory.choices)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    description = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "costing_overhead_entry"
        ordering = ["created_at", "pk"]
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(scope="RUN", run__isnull=False, period__isnull=True)
                    | models.Q(scope="MONTH", run__isnull=True, period__isnull=False)
                ),
                name="chk_overhead_scope_owner",
            ),
            models.CheckConstraint(
                check=models.Q(amount__gt=0),
                name="chk_overhead_amount_positive",
            ),
        ]

    def __str__(self) -> str:
        target = f"run {self.run_id}" if self.run_id else f"{self.period:%Y-%m}"
        return f"{self.category} {self.amount} ({target})"


class OverheadAllocation(models.Model):
    """The share of a monthly pool assigned to one completed run.

    ``ledger_entry`` points at the value-only stock ledger row that carried the
    share into finished-goods value, so the cost sheet and the ledger can be
    reconciled line by line.
    """

    entry = models.ForeignKey(
        OverheadEntry,
        on_delete=models.PROTECT,
        related_name="allocations",
    )
    run = models.ForeignKey(
        ProductionRun,
        on_delete=models.PROTECT,
        related_name="overhead_allocations",
    )
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    ledger_entry = models.ForeignKey(
        StockLedger,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "costing_overhead_allocation"
        ordering = ["entry", "run"]
        constraints = [
            models.UniqueConstraint(
                fields=["entry", "run"],
                name="uniq_overhead_allocation_entry_run",
            ),
            models.CheckConstraint(
                check=models.Q(amount__gt=0),
                name="chk_overhead_allocation_amount_positive",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.entry.category} {self.amount} -> run {self.run_id}"

    @property
    def period(self) -> date | None:
        """The month this allocation belongs to, for display."""
        return self.entry.period
