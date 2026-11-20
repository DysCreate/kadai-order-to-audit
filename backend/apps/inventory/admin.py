"""Inventory admin registration (read-mostly: services own mutations)."""

from django.contrib import admin

from .models import StockAdjustment, StockBalance, StockLedger


@admin.register(StockLedger)
class StockLedgerAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = (
        "id",
        "item",
        "movement_type",
        "qty",
        "value",
        "source_type",
        "source_id",
        "created_at",
    )
    list_filter = ("movement_type", "source_type")
    search_fields = ("item__name",)
    readonly_fields = (
        "item",
        "batch_id",
        "movement_type",
        "qty",
        "value",
        "unit_value",
        "source_type",
        "source_id",
        "created_by",
        "created_at",
    )

    def has_add_permission(self, request: object) -> bool:
        return False

    def has_delete_permission(self, request: object, obj: object = None) -> bool:
        return False


@admin.register(StockBalance)
class StockBalanceAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("item", "qty", "value", "updated_at")
    readonly_fields = ("item", "qty", "value", "updated_at")


@admin.register(StockAdjustment)
class StockAdjustmentAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("id", "item", "qty_delta", "reason", "created_by", "created_at")
    readonly_fields = ("item", "qty_delta", "reason", "created_by", "created_at")

    def has_add_permission(self, request: object) -> bool:
        return False

    def has_delete_permission(self, request: object, obj: object = None) -> bool:
        return False
