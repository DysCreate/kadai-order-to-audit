"""Inventory serializers – validation and Decimal-safe output only.

No business logic lives here: views validate input, call a service and
serialise the result. Decimals are rendered as strings by DRF
(COERCE_DECIMAL_TO_STRING), never floats.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from rest_framework import serializers

from apps.masters.models import Item, Supplier

from .models import Purchase, PurchaseLine, StockAdjustment, StockLedger


class PurchaseLineInputSerializer(serializers.Serializer[Any]):
    """One item received on a new purchase."""

    item = serializers.PrimaryKeyRelatedField(queryset=Item.objects.all())
    qty = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=Decimal("0.001"))
    unit_cost = serializers.DecimalField(max_digits=14, decimal_places=4, min_value=Decimal("0"))


class PurchaseInputSerializer(serializers.Serializer[Any]):
    """Input for recording goods received from a supplier."""

    supplier = serializers.PrimaryKeyRelatedField(queryset=Supplier.objects.all())
    reference = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
    purchase_date = serializers.DateField(required=False)
    notes = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    lines = PurchaseLineInputSerializer(many=True, allow_empty=False)


class PurchaseLineSerializer(serializers.ModelSerializer[PurchaseLine]):
    """One received line, with its exact value."""

    item_id = serializers.IntegerField(read_only=True)
    item_name = serializers.CharField(source="item.name", read_only=True)
    uom = serializers.CharField(source="item.uom.symbol", read_only=True)

    class Meta:
        model = PurchaseLine
        fields = ("id", "item_id", "item_name", "uom", "qty", "unit_cost", "value")


class PurchaseSerializer(serializers.ModelSerializer[Purchase]):
    """A posted purchase with its lines."""

    supplier_id = serializers.IntegerField(read_only=True)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    lines = PurchaseLineSerializer(many=True, read_only=True)

    class Meta:
        model = Purchase
        fields = (
            "id",
            "supplier_id",
            "supplier_name",
            "reference",
            "purchase_date",
            "total_value",
            "created_at",
            "lines",
        )


class StockSummaryRowSerializer(serializers.Serializer[Any]):
    """One row of the stock summary."""

    item_id = serializers.IntegerField(source="item.pk")
    item_name = serializers.CharField(source="item.name")
    item_type = serializers.CharField(source="item.item_type")
    uom = serializers.CharField(source="item.uom.symbol")
    qty = serializers.DecimalField(max_digits=14, decimal_places=3)
    value = serializers.DecimalField(max_digits=14, decimal_places=2)
    avg_rate = serializers.DecimalField(max_digits=14, decimal_places=4, read_only=True)


class StockLedgerEntrySerializer(serializers.ModelSerializer[StockLedger]):
    """One append-only ledger row, traceable to its source document."""

    item_id = serializers.IntegerField(read_only=True)
    item_name = serializers.CharField(source="item.name", read_only=True)
    created_by = serializers.CharField(source="created_by.username", default=None, read_only=True)

    class Meta:
        model = StockLedger
        fields = (
            "id",
            "item_id",
            "item_name",
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


class StockLedgerQuerySerializer(serializers.Serializer[Any]):
    """Query-string validation for the ledger endpoint."""

    item = serializers.IntegerField(required=False, min_value=1)
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        date_from = attrs.get("date_from")
        date_to = attrs.get("date_to")
        if date_from is not None and date_to is not None and date_to < date_from:
            raise serializers.ValidationError({"date_to": "date_to cannot precede date_from."})
        return attrs


class StockAdjustmentInputSerializer(serializers.Serializer[Any]):
    """Input for a manual stock adjustment; the reason is mandatory."""

    item = serializers.PrimaryKeyRelatedField(queryset=Item.objects.all())
    qty_delta = serializers.DecimalField(max_digits=14, decimal_places=3)
    reason = serializers.CharField(max_length=255, allow_blank=False)
    unit_cost = serializers.DecimalField(
        max_digits=14,
        decimal_places=4,
        required=False,
        allow_null=True,
        min_value=Decimal("0"),
    )


class StockAdjustmentSerializer(serializers.ModelSerializer[StockAdjustment]):
    """Output for a posted stock adjustment."""

    class Meta:
        model = StockAdjustment
        fields = ("id", "item_id", "qty_delta", "reason", "created_at")
