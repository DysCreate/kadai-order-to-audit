"""Production serializers – validation and Decimal-safe output only.

No business logic lives here: views validate input, call a service and
serialise the result. Decimals are rendered as strings by DRF
(COERCE_DECIMAL_TO_STRING), never floats.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from rest_framework import serializers

from apps.masters.models import Item

from .models import BOM, BOMLine, BOMLineRole, ProductionRun, ProductionRunLine, RunVarianceSnapshot
from .services import run_variance, variance_tolerance


class BOMLineSerializer(serializers.ModelSerializer[BOMLine]):
    """One BOM line as stored."""

    item_id = serializers.IntegerField(read_only=True)
    item_name = serializers.CharField(source="item.name", read_only=True)
    uom = serializers.CharField(source="item.uom.symbol", read_only=True)

    class Meta:
        model = BOMLine
        fields = (
            "id",
            "item_id",
            "item_name",
            "uom",
            "role",
            "qty_per_batch",
            "standard_rate",
        )


class BOMSerializer(serializers.ModelSerializer[BOM]):
    """One BOM version with its lines."""

    product_id = serializers.IntegerField(read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    lines = BOMLineSerializer(many=True, read_only=True)

    class Meta:
        model = BOM
        fields = (
            "id",
            "product_id",
            "product_name",
            "version",
            "batch_output_qty",
            "created_at",
            "lines",
        )


class BOMLineInputSerializer(serializers.Serializer[Any]):
    """Input line for a new BOM version."""

    item = serializers.PrimaryKeyRelatedField(queryset=Item.objects.all())
    qty_per_batch = serializers.DecimalField(max_digits=14, decimal_places=3)
    role = serializers.ChoiceField(choices=BOMLineRole.choices, default=BOMLineRole.MATERIAL)
    standard_rate = serializers.DecimalField(
        max_digits=14,
        decimal_places=4,
        min_value=Decimal("0"),
        required=False,
        default=Decimal("0"),
    )


class BOMCreateSerializer(serializers.Serializer[Any]):
    """Input for creating the next BOM version of a product."""

    product = serializers.PrimaryKeyRelatedField(queryset=Item.objects.all())
    batch_output_qty = serializers.DecimalField(max_digits=14, decimal_places=3)
    lines = BOMLineInputSerializer(many=True, allow_empty=False)


class ProductionRunLineSerializer(serializers.ModelSerializer[ProductionRunLine]):
    """Planned, issued and actual quantity for one input."""

    item_id = serializers.IntegerField(read_only=True)
    item_name = serializers.CharField(source="item.name", read_only=True)
    uom = serializers.CharField(source="item.uom.symbol", read_only=True)

    class Meta:
        model = ProductionRunLine
        fields = (
            "id",
            "item_id",
            "item_name",
            "uom",
            "role",
            "planned_qty",
            "issued_qty",
            "actual_qty",
            "issued_unit_value",
        )


class VarianceSnapshotSerializer(serializers.ModelSerializer[RunVarianceSnapshot]):
    """One stored variance row (a line, or the run's yield)."""

    line_id = serializers.IntegerField(read_only=True, allow_null=True)

    class Meta:
        model = RunVarianceSnapshot
        fields = (
            "line_id",
            "kind",
            "item_name",
            "planned_qty",
            "actual_qty",
            "variance_pct",
            "flagged",
            "direction",
        )


class ProductionRunSerializer(serializers.ModelSerializer[ProductionRun]):
    """A run with its lines, latest variance snapshot and the tolerance used."""

    product_id = serializers.IntegerField(read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    lines = ProductionRunLineSerializer(many=True, read_only=True)
    variance = serializers.SerializerMethodField()
    tolerance = serializers.SerializerMethodField()

    class Meta:
        model = ProductionRun
        fields = (
            "id",
            "product_id",
            "product_name",
            "bom_version",
            "batches",
            "planned_output_qty",
            "state",
            "good_packets",
            "damaged_pouches",
            "cartons_used",
            "revision",
            "created_at",
            "issued_at",
            "completed_at",
            "lines",
            "variance",
            "tolerance",
        )

    def get_variance(self, obj: ProductionRun) -> list[dict[str, Any]]:
        return list(VarianceSnapshotSerializer(run_variance(obj), many=True).data)

    def get_tolerance(self, obj: ProductionRun) -> str:
        # A string, so the frontend never receives a float tolerance.
        return str(variance_tolerance())


class RunCreateSerializer(serializers.Serializer[Any]):
    """Input for a new DRAFT run; planned lines come from the current BOM."""

    product = serializers.PrimaryKeyRelatedField(queryset=Item.objects.all())
    batches = serializers.DecimalField(
        max_digits=14,
        decimal_places=3,
        min_value=Decimal("0.001"),
    )


class RunIssueLineSerializer(serializers.Serializer[Any]):
    """One issued quantity, overriding the plan for that line."""

    line = serializers.IntegerField(min_value=1)
    qty = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=Decimal("0"))


class RunIssueSerializer(serializers.Serializer[Any]):
    """Input for issuing a run; omitted lines fall back to their default."""

    lines = RunIssueLineSerializer(many=True, required=False, default=list)

    def validate_lines(self, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        line_ids = [row["line"] for row in value]
        if len(line_ids) != len(set(line_ids)):
            raise serializers.ValidationError("A run line can only be issued once.")
        return value


class RunCompleteSerializer(serializers.Serializer[Any]):
    """Input for completing a run: the packing record."""

    good_packets = serializers.DecimalField(
        max_digits=14,
        decimal_places=3,
        min_value=Decimal("0.001"),
    )
    damaged_pouches = serializers.DecimalField(
        max_digits=14,
        decimal_places=3,
        min_value=Decimal("0"),
        required=False,
        default=Decimal("0"),
    )
    cartons_used = serializers.DecimalField(
        max_digits=14,
        decimal_places=3,
        min_value=Decimal("0"),
        required=False,
        default=Decimal("0"),
    )


class RunAmendSerializer(serializers.Serializer[Any]):
    """Input for amending an issued run: a mandatory reason."""

    reason = serializers.CharField(max_length=255, allow_blank=False)


class ReportCardLineSerializer(serializers.Serializer[Any]):
    """Standard versus actual for one input, split into price and usage."""

    item_id = serializers.IntegerField()
    item_name = serializers.CharField()
    role = serializers.CharField()
    planned_qty = serializers.DecimalField(max_digits=14, decimal_places=3)
    actual_qty = serializers.DecimalField(max_digits=14, decimal_places=3)
    standard_rate = serializers.DecimalField(max_digits=14, decimal_places=4)
    actual_rate = serializers.DecimalField(max_digits=14, decimal_places=4)
    standard_value = serializers.DecimalField(max_digits=14, decimal_places=2)
    actual_value = serializers.DecimalField(max_digits=14, decimal_places=2)
    price_impact = serializers.DecimalField(max_digits=14, decimal_places=2)
    usage_impact = serializers.DecimalField(max_digits=14, decimal_places=2)
    total_impact = serializers.DecimalField(max_digits=14, decimal_places=2)


class BridgeStepSerializer(serializers.Serializer[Any]):
    """One step of the cost-per-packet bridge."""

    key = serializers.CharField()
    label = serializers.CharField()
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    cumulative = serializers.DecimalField(max_digits=14, decimal_places=2)


class YieldGapSerializer(serializers.Serializer[Any]):
    """The missing packets, split into recorded damage and unexplained loss."""

    planned_packets = serializers.DecimalField(max_digits=14, decimal_places=3)
    good_packets = serializers.DecimalField(max_digits=14, decimal_places=3)
    gap_packets = serializers.DecimalField(max_digits=14, decimal_places=3)
    damaged_packets = serializers.DecimalField(max_digits=14, decimal_places=3)
    unexplained_packets = serializers.DecimalField(max_digits=14, decimal_places=3)


class ReportCardSerializer(serializers.Serializer[Any]):
    """The complete Leakage Radar Run Report Card."""

    lines = ReportCardLineSerializer(many=True)
    standard_materials = serializers.DecimalField(max_digits=14, decimal_places=2)
    actual_materials = serializers.DecimalField(max_digits=14, decimal_places=2)
    price_impact = serializers.DecimalField(max_digits=14, decimal_places=2)
    usage_impact = serializers.DecimalField(max_digits=14, decimal_places=2)
    material_impact = serializers.DecimalField(max_digits=14, decimal_places=2)
    planned_packets = serializers.DecimalField(max_digits=14, decimal_places=3)
    good_packets = serializers.DecimalField(max_digits=14, decimal_places=3)
    overhead_value = serializers.DecimalField(max_digits=14, decimal_places=2)
    standard_per_packet = serializers.DecimalField(max_digits=14, decimal_places=2)
    actual_material_per_packet = serializers.DecimalField(max_digits=14, decimal_places=2)
    overhead_per_packet = serializers.DecimalField(max_digits=14, decimal_places=2)
    cost_per_packet = serializers.DecimalField(max_digits=14, decimal_places=2)
    bridge = BridgeStepSerializer(many=True)
    yield_gap = YieldGapSerializer()
    selling_price = serializers.DecimalField(max_digits=14, decimal_places=2, allow_null=True)
    margin_per_packet = serializers.DecimalField(max_digits=14, decimal_places=2, allow_null=True)
    margin_pct = serializers.DecimalField(max_digits=14, decimal_places=2, allow_null=True)


class VariancePointSerializer(serializers.Serializer[Any]):
    """One run's stored variance for an input."""

    run_id = serializers.IntegerField()
    variance_pct = serializers.DecimalField(max_digits=9, decimal_places=6, allow_null=True)
    direction = serializers.CharField()


class IngredientTrendSerializer(serializers.Serializer[Any]):
    """The variance series for one input, oldest run first."""

    item_name = serializers.CharField()
    points = VariancePointSerializer(many=True)


class DriftAlertSerializer(serializers.Serializer[Any]):
    """An input that has crept adverse for three consecutive runs."""

    item_name = serializers.CharField()
    consecutive_runs = serializers.IntegerField()
    latest_variance_pct = serializers.DecimalField(max_digits=9, decimal_places=6, allow_null=True)
    threshold = serializers.DecimalField(max_digits=9, decimal_places=6)
    direction = serializers.CharField()


class RunTrendRefSerializer(serializers.Serializer[Any]):
    """A completed run's identity for the trend axis."""

    run_id = serializers.IntegerField()
    completed_at = serializers.CharField(allow_null=True)


class LeakageTrendsSerializer(serializers.Serializer[Any]):
    """Per-input variance trends and drift alerts for one product."""

    product_id = serializers.IntegerField()
    product_name = serializers.CharField()
    runs = RunTrendRefSerializer(many=True)
    ingredients = IngredientTrendSerializer(many=True)
    drift_alerts = DriftAlertSerializer(many=True)
    tolerance = serializers.DecimalField(max_digits=9, decimal_places=6)
