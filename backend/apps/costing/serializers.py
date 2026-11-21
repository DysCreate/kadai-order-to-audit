"""Costing serializers – validation and Decimal-safe output only."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from rest_framework import serializers

from .models import OverheadAllocation, OverheadCategory, OverheadEntry


class OverheadEntrySerializer(serializers.ModelSerializer[OverheadEntry]):
    """One run or monthly overhead entry."""

    run_id = serializers.IntegerField(read_only=True, allow_null=True)
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model = OverheadEntry
        fields = (
            "id",
            "scope",
            "run_id",
            "period",
            "category",
            "amount",
            "description",
            "created_at",
        )


class RunOverheadCreateSerializer(serializers.Serializer[Any]):
    """Input for one overhead assigned to a completed run."""

    category = serializers.ChoiceField(choices=OverheadCategory.choices)
    amount = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        min_value=Decimal("0.01"),
    )
    description = serializers.CharField(
        max_length=255, required=False, allow_blank=True, default=""
    )


class MonthlyOverheadCreateSerializer(RunOverheadCreateSerializer):
    """Input for one monthly overhead pool entry."""

    period = serializers.DateField()


class PeriodSerializer(serializers.Serializer[Any]):
    """A required calendar month, expressed as any date inside it."""

    period = serializers.DateField()


class OptionalPeriodSerializer(serializers.Serializer[Any]):
    """An optional calendar month filter."""

    period = serializers.DateField(required=False)


class MaterialLineSerializer(serializers.Serializer[Any]):
    """One input's net quantity and value in a run's cost sheet."""

    item_id = serializers.IntegerField()
    item_name = serializers.CharField()
    uom = serializers.CharField()
    qty = serializers.DecimalField(max_digits=14, decimal_places=3)
    value = serializers.DecimalField(max_digits=14, decimal_places=2)


class OverheadLineSerializer(serializers.Serializer[Any]):
    """One overhead line in a run's cost sheet."""

    entry_id = serializers.IntegerField()
    allocation_id = serializers.IntegerField(allow_null=True)
    scope = serializers.CharField()
    category = serializers.CharField()
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    description = serializers.CharField(allow_blank=True)
    period = serializers.DateField(allow_null=True)


class CostSheetSerializer(serializers.Serializer[Any]):
    """The complete cost view of one completed run."""

    run_id = serializers.IntegerField()
    product_id = serializers.IntegerField()
    product_name = serializers.CharField()
    product_uom = serializers.CharField()
    state = serializers.CharField()
    batches = serializers.DecimalField(max_digits=14, decimal_places=3)
    standard_batch_hours = serializers.DecimalField(max_digits=8, decimal_places=3)
    batch_hours = serializers.DecimalField(max_digits=14, decimal_places=3)
    good_packets = serializers.DecimalField(max_digits=14, decimal_places=3)
    materials = MaterialLineSerializer(many=True)
    materials_value = serializers.DecimalField(max_digits=14, decimal_places=2)
    overheads = OverheadLineSerializer(many=True)
    overhead_value = serializers.DecimalField(max_digits=14, decimal_places=2)
    total_cost = serializers.DecimalField(max_digits=14, decimal_places=2)
    cost_per_packet = serializers.DecimalField(max_digits=14, decimal_places=2)
    selling_price = serializers.DecimalField(max_digits=14, decimal_places=2, allow_null=True)
    margin_per_packet = serializers.DecimalField(max_digits=14, decimal_places=2, allow_null=True)
    margin_pct = serializers.DecimalField(max_digits=14, decimal_places=2, allow_null=True)
    fg_stock_qty = serializers.DecimalField(max_digits=14, decimal_places=3)
    fg_stock_value = serializers.DecimalField(max_digits=14, decimal_places=2)
    fg_avg_cost = serializers.DecimalField(max_digits=14, decimal_places=4)


class ProductCostSerializer(serializers.Serializer[Any]):
    """Current finished-goods weighted-average cost and margin for a product."""

    product_id = serializers.IntegerField()
    product_name = serializers.CharField()
    stock_qty = serializers.DecimalField(max_digits=14, decimal_places=3)
    stock_value = serializers.DecimalField(max_digits=14, decimal_places=2)
    avg_cost = serializers.DecimalField(max_digits=14, decimal_places=4)
    selling_price = serializers.DecimalField(max_digits=14, decimal_places=2, allow_null=True)
    margin_per_packet = serializers.DecimalField(max_digits=14, decimal_places=2, allow_null=True)
    margin_pct = serializers.DecimalField(max_digits=14, decimal_places=2, allow_null=True)


class OverheadAllocationSerializer(serializers.ModelSerializer[OverheadAllocation]):
    """One monthly-pool share assigned to a run."""

    entry_id = serializers.IntegerField(read_only=True)
    run_id = serializers.IntegerField(read_only=True)
    run_product_name = serializers.CharField(source="run.product.name", read_only=True)
    period = serializers.DateField(read_only=True)
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    ledger_entry_id = serializers.IntegerField(read_only=True, allow_null=True)

    class Meta:
        model = OverheadAllocation
        fields = (
            "id",
            "entry_id",
            "run_id",
            "run_product_name",
            "period",
            "amount",
            "ledger_entry_id",
        )
