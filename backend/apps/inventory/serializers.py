"""Inventory serializers – validation and Decimal-safe output only.

No business logic lives here: views validate input, call a service and
serialise the result. Decimals are rendered as strings by DRF
(COERCE_DECIMAL_TO_STRING), never floats.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from rest_framework import serializers

from apps.masters.models import Item

from .models import StockAdjustment, StockLedger


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
