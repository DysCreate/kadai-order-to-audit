"""Admin – inspection of BOMs and production runs.

Writes belong to ``production.services``; the admin is for looking, so the
run and variance models are read-only here.
"""

from django.contrib import admin

from .models import BOM, BOMLine, ProductionRun, ProductionRunLine, RunVarianceSnapshot


class BOMLineInline(admin.TabularInline):  # type: ignore[type-arg]
    model = BOMLine
    extra = 0


@admin.register(BOM)
class BOMAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("product", "version", "batch_output_qty", "created_at")
    list_filter = ("product",)
    inlines = (BOMLineInline,)


class ProductionRunLineInline(admin.TabularInline):  # type: ignore[type-arg]
    model = ProductionRunLine
    extra = 0
    readonly_fields = ("item", "role", "planned_qty", "issued_qty", "actual_qty")


class RunVarianceInline(admin.TabularInline):  # type: ignore[type-arg]
    model = RunVarianceSnapshot
    extra = 0
    readonly_fields = (
        "line",
        "kind",
        "item_name",
        "planned_qty",
        "actual_qty",
        "variance_pct",
        "flagged",
        "direction",
    )


@admin.register(ProductionRun)
class ProductionRunAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("id", "product", "state", "batches", "good_packets", "created_at")
    list_filter = ("state", "product")
    readonly_fields = ("ledger_entry_ids", "issued_at", "completed_at", "revision")
    inlines = (ProductionRunLineInline, RunVarianceInline)
