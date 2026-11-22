"""Production models – versioned BOM, production runs and variance snapshots.

Invariants protected:
- A BOM is versioned per product. A new version is a new row; old versions are
  never edited, and a run stores the version it was built from.
- A run copies planned quantities from its BOM at creation, so later BOM edits
  cannot rewrite a run's plan.
- A run follows DRAFT -> ISSUED -> COMPLETED. Quantities are NUMERIC(14,3) in
  the item's base unit; money never appears here.
- Variance is computed once at completion and stored as a snapshot row per BOM
  line plus one yield row, together with the tolerance used.
"""

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.masters.models import Item


class BOMLineRole(models.TextChoices):
    """What a BOM line contributes to a batch.

    ``POUCH`` and ``CARTON`` are derived from the packing record at run
    completion, so the supervisor does not have to count them twice.
    """

    MATERIAL = "material", "Raw material"
    POUCH = "pouch", "Pouch"
    CARTON = "carton", "Carton"


class RunState(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    ISSUED = "ISSUED", "Issued"
    COMPLETED = "COMPLETED", "Completed"


class VarianceDirection(models.TextChoices):
    FAVOURABLE = "favourable", "Favourable"
    ADVERSE = "adverse", "Adverse"
    NONE = "none", "Not flagged"


class VarianceKind(models.TextChoices):
    USAGE = "usage", "Input usage"
    YIELD = "yield", "Output yield"


class BOM(models.Model):
    """One version of a product's bill of materials.

    ``batch_output_qty`` is the expected good output of one batch in the
    product's base unit (200 packets for Murukku 200 g).
    """

    product = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="boms")
    version = models.PositiveIntegerField()
    batch_output_qty = models.DecimalField(max_digits=14, decimal_places=3)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "production_bom"
        ordering = ["product", "-version"]
        constraints = [
            models.UniqueConstraint(fields=["product", "version"], name="uniq_bom_product_version"),
            models.CheckConstraint(
                check=models.Q(batch_output_qty__gt=0),
                name="chk_bom_batch_output_positive",
            ),
            models.CheckConstraint(check=models.Q(version__gte=1), name="chk_bom_version_positive"),
        ]

    def __str__(self) -> str:
        return f"{self.product.name} v{self.version}"


class BOMLine(models.Model):
    """One input of a BOM version, per batch, in the item's base unit.

    ``standard_rate`` is the standard cost of one base unit at this BOM
    version. It is captured when the version is created, so the Leakage Radar
    compares a run with the standard it was planned against even after a later
    BOM version changes the rate.
    """

    bom = models.ForeignKey(BOM, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="bom_lines")
    role = models.CharField(
        max_length=20,
        choices=BOMLineRole.choices,
        default=BOMLineRole.MATERIAL,
    )
    qty_per_batch = models.DecimalField(max_digits=14, decimal_places=3)
    standard_rate = models.DecimalField(max_digits=14, decimal_places=4, default=Decimal("0.0000"))

    class Meta:
        db_table = "production_bom_line"
        ordering = ["pk"]
        constraints = [
            models.UniqueConstraint(fields=["bom", "item"], name="uniq_bom_line_item"),
            models.CheckConstraint(
                check=models.Q(qty_per_batch__gt=0),
                name="chk_bom_line_qty_positive",
            ),
            models.CheckConstraint(
                check=models.Q(standard_rate__gte=0),
                name="chk_bom_line_standard_rate_non_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.item.name} {self.qty_per_batch} per batch"


class ProductionRun(models.Model):
    """A production run, from planned quantities to a completed batch.

    ``ledger_entry_ids`` records the ledger rows the run currently owns, so an
    amend can reverse exactly those rows and nothing else.
    """

    product = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="production_runs")
    bom = models.ForeignKey(BOM, on_delete=models.PROTECT, related_name="runs")
    bom_version = models.PositiveIntegerField()
    batches = models.DecimalField(max_digits=14, decimal_places=3)
    planned_output_qty = models.DecimalField(max_digits=14, decimal_places=3)
    state = models.CharField(
        max_length=20,
        choices=RunState.choices,
        default=RunState.DRAFT,
        db_index=True,
    )
    good_packets = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    damaged_pouches = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    cartons_used = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    revision = models.PositiveIntegerField(default=1)
    ledger_entry_ids = models.JSONField(default=list, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    issued_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "production_run"
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.CheckConstraint(check=models.Q(batches__gt=0), name="chk_run_batches_positive"),
            models.CheckConstraint(
                check=models.Q(planned_output_qty__gt=0),
                name="chk_run_planned_output_positive",
            ),
        ]

    def __str__(self) -> str:
        return f"Run {self.pk} {self.product.name} ({self.state})"


class ProductionRunLine(models.Model):
    """Planned, issued and actual quantity for one input of a run.

    ``actual_qty`` is recorded at completion; for raw materials it equals what
    was issued, while pouch and carton lines are derived from the packing
    record. ``issued_unit_value`` keeps the value the material left stock at,
    so an unused balance can be returned at the same cost.
    """

    run = models.ForeignKey(ProductionRun, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="run_lines")
    role = models.CharField(
        max_length=20,
        choices=BOMLineRole.choices,
        default=BOMLineRole.MATERIAL,
    )
    planned_qty = models.DecimalField(max_digits=14, decimal_places=3)
    issued_qty = models.DecimalField(max_digits=14, decimal_places=3, default=Decimal("0.000"))
    actual_qty = models.DecimalField(max_digits=14, decimal_places=3, default=Decimal("0.000"))
    issued_unit_value = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)

    class Meta:
        db_table = "production_run_line"
        ordering = ["pk"]
        constraints = [
            models.UniqueConstraint(fields=["run", "item"], name="uniq_run_line_item"),
            models.CheckConstraint(
                check=models.Q(planned_qty__gte=0),
                name="chk_run_line_planned_non_negative",
            ),
            models.CheckConstraint(
                check=models.Q(issued_qty__gte=0),
                name="chk_run_line_issued_non_negative",
            ),
            models.CheckConstraint(
                check=models.Q(actual_qty__gte=0),
                name="chk_run_line_actual_non_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.item.name}: planned {self.planned_qty}"


class RunVarianceSnapshot(models.Model):
    """Stored variance for one line (or the yield) of a completed run.

    Snapshots are written once per completion and are never recalculated from
    a later BOM, so history stays truthful.
    """

    run = models.ForeignKey(
        ProductionRun,
        on_delete=models.CASCADE,
        related_name="variance_snapshots",
    )
    line = models.ForeignKey(
        ProductionRunLine,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="variance_snapshots",
    )
    kind = models.CharField(max_length=20, choices=VarianceKind.choices)
    item_name = models.CharField(max_length=200)
    planned_qty = models.DecimalField(max_digits=14, decimal_places=3)
    actual_qty = models.DecimalField(max_digits=14, decimal_places=3)
    variance_pct = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    flagged = models.BooleanField(default=False)
    direction = models.CharField(
        max_length=20,
        choices=VarianceDirection.choices,
        default=VarianceDirection.NONE,
    )
    tolerance = models.DecimalField(max_digits=6, decimal_places=4)
    revision = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "production_run_variance_snapshot"
        ordering = ["pk"]
        indexes = [
            models.Index(fields=["run", "revision"], name="idx_variance_run_revision"),
        ]

    def __str__(self) -> str:
        return f"{self.item_name}: {self.variance_pct} flagged={self.flagged}"
