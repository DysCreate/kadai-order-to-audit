"""Sales serializers – validation and Decimal-safe output only.

No business logic lives here: views validate input, call a service and
serialise the result. Decimals are rendered as strings by DRF
(COERCE_DECIMAL_TO_STRING), never floats.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from rest_framework import serializers

from apps.masters.models import Customer, Item
from core.money import q2

from .amounts import amount_in_words
from .models import (
    CreditNote,
    CreditNoteLine,
    Dispatch,
    DispatchLine,
    Invoice,
    InvoiceLine,
    Order,
    OrderLine,
    OrderState,
)
from .services import (
    OrderCoverage,
    credited_qty_by_line,
    dispatched_qty_by_line,
    invoice_credited_total,
    invoice_dispatched_total,
    invoice_is_cancelled,
)


class OrderLineSerializer(serializers.ModelSerializer[OrderLine]):
    """One order line with its snapshotted price."""

    item_id = serializers.IntegerField(read_only=True)
    item_name = serializers.CharField(source="item.name", read_only=True)
    uom = serializers.CharField(source="item.uom.symbol", read_only=True)
    gst_rate = serializers.DecimalField(
        source="item.gst_rate",
        max_digits=5,
        decimal_places=2,
        read_only=True,
    )
    line_value = serializers.SerializerMethodField()

    class Meta:
        model = OrderLine
        fields = (
            "id",
            "item_id",
            "item_name",
            "uom",
            "qty",
            "unit_price",
            "gst_rate",
            "line_value",
        )

    def get_line_value(self, obj: OrderLine) -> str:
        return str(q2(obj.qty * obj.unit_price))


class OrderSerializer(serializers.ModelSerializer[Order]):
    """An order with its lines and snapshotted prices."""

    client_uuid = serializers.UUIDField(read_only=True)
    customer_id = serializers.IntegerField(read_only=True)
    customer_name = serializers.CharField(source="customer.name", read_only=True)
    customer_state_code = serializers.CharField(source="customer.state_code", read_only=True)
    salesman_username = serializers.CharField(source="salesman.username", read_only=True)
    lines = OrderLineSerializer(many=True, read_only=True)
    total_value = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = (
            "id",
            "number",
            "client_uuid",
            "customer_id",
            "customer_name",
            "customer_state_code",
            "salesman_username",
            "state",
            "notes",
            "rejection_reason",
            "created_at",
            "updated_at",
            "approved_at",
            "lines",
            "total_value",
        )

    def get_total_value(self, obj: Order) -> str:
        total = sum(
            (q2(line.qty * line.unit_price) for line in obj.lines.all()),
            Decimal("0.00"),
        )
        return str(q2(total))


class CustomerSalesRowSerializer(serializers.Serializer[Any]):
    """One customer's sales this month, computed on the server."""

    customer_id = serializers.IntegerField(source="customer.pk")
    customer_name = serializers.CharField(source="customer.name")
    order_count = serializers.IntegerField()
    total_qty = serializers.DecimalField(max_digits=14, decimal_places=3)
    total_value = serializers.DecimalField(max_digits=14, decimal_places=2)


class CoverageLineSerializer(serializers.Serializer[Any]):
    """Stock coverage for one order line."""

    line_id = serializers.IntegerField(source="line.pk")
    item_id = serializers.IntegerField(source="line.item_id")
    item_name = serializers.CharField(source="line.item.name")
    uom = serializers.CharField(source="line.item.uom.symbol")
    ordered_qty = serializers.DecimalField(source="line.qty", max_digits=14, decimal_places=3)
    on_hand_qty = serializers.DecimalField(max_digits=14, decimal_places=3)
    committed_qty = serializers.DecimalField(max_digits=14, decimal_places=3)
    available_qty = serializers.DecimalField(max_digits=14, decimal_places=3)
    shortage_qty = serializers.DecimalField(max_digits=14, decimal_places=3)
    current_price = serializers.DecimalField(max_digits=14, decimal_places=2, allow_null=True)
    price_changed = serializers.BooleanField()


class TaxSummarySerializer(serializers.Serializer[Any]):
    """The tax an order would carry if invoiced now."""

    is_interstate = serializers.BooleanField()
    taxable_total = serializers.DecimalField(max_digits=14, decimal_places=2)
    cgst_total = serializers.DecimalField(max_digits=14, decimal_places=2)
    sgst_total = serializers.DecimalField(max_digits=14, decimal_places=2)
    igst_total = serializers.DecimalField(max_digits=14, decimal_places=2)
    round_off = serializers.DecimalField(max_digits=14, decimal_places=2)
    total = serializers.DecimalField(max_digits=14, decimal_places=2)


class CapacityRowSerializer(serializers.Serializer[Any]):
    """How many whole batches one input's stock allows."""

    item_id = serializers.IntegerField()
    item_name = serializers.CharField()
    uom = serializers.CharField()
    qty_per_batch = serializers.DecimalField(max_digits=14, decimal_places=3)
    stock_qty = serializers.DecimalField(max_digits=14, decimal_places=3)
    batches_available = serializers.IntegerField()
    ratio = serializers.DecimalField(max_digits=14, decimal_places=4)
    limiting = serializers.BooleanField()


class PurchaseSuggestionSerializer(serializers.Serializer[Any]):
    """A draft purchase quantity for one short input."""

    item_id = serializers.IntegerField()
    item_name = serializers.CharField()
    uom = serializers.CharField()
    qty = serializers.DecimalField(max_digits=14, decimal_places=3)


class LoopCloserSerializer(serializers.Serializer[Any]):
    """The shortage-to-production plan for one finished-goods line."""

    product_id = serializers.IntegerField()
    product_name = serializers.CharField()
    shortage_qty = serializers.DecimalField(max_digits=14, decimal_places=3)
    batch_output_qty = serializers.DecimalField(max_digits=14, decimal_places=3)
    yield_factor = serializers.DecimalField(max_digits=14, decimal_places=4)
    batches_needed = serializers.IntegerField()
    batches_allowed = serializers.IntegerField()
    feasible = serializers.BooleanField()
    limiting_item = serializers.CharField()
    capacity = CapacityRowSerializer(many=True)
    purchase_list = PurchaseSuggestionSerializer(many=True)
    verdict = serializers.CharField()


class OrderCoverageSerializer(serializers.Serializer[Any]):
    """Per-line stock coverage plus the GST preview for an order."""

    lines = CoverageLineSerializer(many=True)
    total_shortage_qty = serializers.DecimalField(max_digits=14, decimal_places=3)
    is_interstate = serializers.BooleanField()
    tax_preview = TaxSummarySerializer()
    loop_closers = LoopCloserSerializer(many=True)

    def to_representation(self, instance: OrderCoverage) -> dict[str, Any]:
        return {
            "lines": CoverageLineSerializer(instance.lines, many=True).data,
            "total_shortage_qty": str(instance.total_shortage_qty),
            "is_interstate": instance.is_interstate,
            "tax_preview": TaxSummarySerializer(instance.tax_preview).data,
            "loop_closers": LoopCloserSerializer(instance.loop_closers, many=True).data,
        }


class DispatchLineSerializer(serializers.ModelSerializer[DispatchLine]):
    """One dispatched invoice line."""

    invoice_line_id = serializers.IntegerField(read_only=True)
    item_name = serializers.CharField(source="invoice_line.description", read_only=True)

    class Meta:
        model = DispatchLine
        fields = ("id", "invoice_line_id", "item_name", "qty")


class DispatchSerializer(serializers.ModelSerializer[Dispatch]):
    """A dispatch document with its lines."""

    invoice_id = serializers.IntegerField(read_only=True)
    invoice_number = serializers.CharField(source="invoice.number", read_only=True)
    lines = DispatchLineSerializer(many=True, read_only=True)

    class Meta:
        model = Dispatch
        fields = (
            "id",
            "invoice_id",
            "invoice_number",
            "dispatch_date",
            "notes",
            "created_at",
            "lines",
        )


class CreditNoteLineSerializer(serializers.ModelSerializer[CreditNoteLine]):
    """One credited invoice line."""

    invoice_line_id = serializers.IntegerField(read_only=True)
    item_name = serializers.CharField(source="invoice_line.description", read_only=True)

    class Meta:
        model = CreditNoteLine
        fields = (
            "id",
            "invoice_line_id",
            "item_name",
            "qty",
            "taxable_value",
            "cgst",
            "sgst",
            "igst",
            "line_total",
        )


class CreditNoteSerializer(serializers.ModelSerializer[CreditNote]):
    """A credit note with its lines."""

    invoice_id = serializers.IntegerField(read_only=True)
    invoice_number = serializers.CharField(source="invoice.number", read_only=True)
    lines = CreditNoteLineSerializer(many=True, read_only=True)

    class Meta:
        model = CreditNote
        fields = (
            "id",
            "number",
            "invoice_id",
            "invoice_number",
            "reason",
            "restock",
            "taxable_total",
            "cgst_total",
            "sgst_total",
            "igst_total",
            "round_off",
            "total",
            "created_at",
            "lines",
        )


class InvoiceLineSerializer(serializers.ModelSerializer[InvoiceLine]):
    """One invoice line, with how much is dispatched, credited and remaining."""

    item_id = serializers.IntegerField(read_only=True)
    item_name = serializers.CharField(source="item.name", read_only=True)
    uom = serializers.CharField(source="item.uom.symbol", read_only=True)
    dispatched_qty = serializers.SerializerMethodField()
    credited_qty = serializers.SerializerMethodField()
    remaining_qty = serializers.SerializerMethodField()

    class Meta:
        model = InvoiceLine
        fields = (
            "id",
            "item_id",
            "item_name",
            "uom",
            "description",
            "hsn_code",
            "qty",
            "unit_price",
            "gst_rate",
            "taxable_value",
            "cgst",
            "sgst",
            "igst",
            "line_total",
            "dispatched_qty",
            "credited_qty",
            "remaining_qty",
        )

    def _map(self, invoice: Invoice, key: str) -> dict[int, Decimal]:
        cache: dict[str, dict[int, dict[int, Decimal]]] = self.context.setdefault(
            "_sales_qty_cache", {}
        )
        per_invoice = cache.setdefault(key, {})
        if invoice.pk not in per_invoice:
            per_invoice[invoice.pk] = (
                dispatched_qty_by_line(invoice)
                if key == "dispatched"
                else credited_qty_by_line(invoice)
            )
        return per_invoice[invoice.pk]

    def get_dispatched_qty(self, obj: InvoiceLine) -> str:
        return str(self._map(obj.invoice, "dispatched").get(obj.pk, Decimal("0.000")))

    def get_credited_qty(self, obj: InvoiceLine) -> str:
        return str(self._map(obj.invoice, "credited").get(obj.pk, Decimal("0.000")))

    def get_remaining_qty(self, obj: InvoiceLine) -> str:
        dispatched = self._map(obj.invoice, "dispatched").get(obj.pk, Decimal("0.000"))
        credited = self._map(obj.invoice, "credited").get(obj.pk, Decimal("0.000"))
        remaining = obj.qty - dispatched - credited
        return str(max(remaining, Decimal("0.000")))


class InvoiceSerializer(serializers.ModelSerializer[Invoice]):
    """A GST invoice with its lines, derived status and amount in words."""

    order_id = serializers.IntegerField(read_only=True)
    customer_id = serializers.IntegerField(read_only=True)
    customer_name = serializers.CharField(source="customer.name", read_only=True)
    customer_gstin = serializers.CharField(source="customer.gstin", read_only=True)
    customer_state_code = serializers.CharField(source="customer.state_code", read_only=True)
    lines = InvoiceLineSerializer(many=True, read_only=True)
    credit_notes = CreditNoteSerializer(many=True, read_only=True)
    dispatches = DispatchSerializer(many=True, read_only=True)
    amount_in_words = serializers.SerializerMethodField()
    is_cancelled = serializers.SerializerMethodField()
    credited_total = serializers.SerializerMethodField()
    dispatched_total = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = (
            "id",
            "number",
            "order_id",
            "customer_id",
            "customer_name",
            "customer_gstin",
            "customer_state_code",
            "invoice_date",
            "place_of_supply_state_code",
            "is_interstate",
            "taxable_total",
            "cgst_total",
            "sgst_total",
            "igst_total",
            "round_off",
            "total",
            "amount_in_words",
            "is_cancelled",
            "credited_total",
            "dispatched_total",
            "created_at",
            "lines",
            "credit_notes",
            "dispatches",
        )

    def get_amount_in_words(self, obj: Invoice) -> str:
        return amount_in_words(obj.total)

    def get_is_cancelled(self, obj: Invoice) -> bool:
        return invoice_is_cancelled(obj)

    def get_credited_total(self, obj: Invoice) -> str:
        return str(invoice_credited_total(obj))

    def get_dispatched_total(self, obj: Invoice) -> str:
        return str(invoice_dispatched_total(obj))


# ---------------------------------------------------------------------------
# Input serializers
# ---------------------------------------------------------------------------


class OrderLineInputSerializer(serializers.Serializer[Any]):
    """One requested item."""

    item = serializers.PrimaryKeyRelatedField(queryset=Item.objects.all())
    qty = serializers.DecimalField(
        max_digits=14,
        decimal_places=3,
        min_value=Decimal("0.001"),
    )


class OrderCreateSerializer(serializers.Serializer[Any]):
    """Input for an idempotent order submit."""

    client_uuid = serializers.UUIDField()
    customer = serializers.PrimaryKeyRelatedField(queryset=Customer.objects.all())
    notes = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    lines = OrderLineInputSerializer(many=True, allow_empty=False)

    def validate_lines(self, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        items = [row["item"].pk for row in value]
        if len(items) != len(set(items)):
            raise serializers.ValidationError("An item can only appear once on an order.")
        return value


class OrderLineEditSerializer(serializers.Serializer[Any]):
    """Admin verification: change a line's quantity or price before approval."""

    qty = serializers.DecimalField(
        max_digits=14,
        decimal_places=3,
        min_value=Decimal("0.001"),
        required=False,
    )
    unit_price = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        min_value=Decimal("0"),
        required=False,
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs.get("qty") is None and attrs.get("unit_price") is None:
            raise serializers.ValidationError("Provide a quantity or a price to change.")
        return attrs


class OrderRejectSerializer(serializers.Serializer[Any]):
    """Input for rejecting an order."""

    reason = serializers.CharField(max_length=255, allow_blank=False)


class InvoiceCreateSerializer(serializers.Serializer[Any]):
    """Input for raising an invoice; the date defaults to today in IST."""

    invoice_date = serializers.DateField(required=False)


class DispatchLineInputSerializer(serializers.Serializer[Any]):
    """One invoice line quantity to dispatch."""

    invoice_line = serializers.IntegerField(min_value=1)
    qty = serializers.DecimalField(
        max_digits=14,
        decimal_places=3,
        min_value=Decimal("0.001"),
    )


class DispatchCreateSerializer(serializers.Serializer[Any]):
    """Input for dispatching finished goods against an invoice."""

    dispatch_date = serializers.DateField(required=False)
    notes = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    lines = DispatchLineInputSerializer(many=True, allow_empty=False)


class CreditNoteLineInputSerializer(serializers.Serializer[Any]):
    """One invoice line quantity to credit."""

    invoice_line = serializers.IntegerField(min_value=1)
    qty = serializers.DecimalField(
        max_digits=14,
        decimal_places=3,
        min_value=Decimal("0.001"),
    )


class CreditNoteCreateSerializer(serializers.Serializer[Any]):
    """Input for a credit note, with an optional restock."""

    reason = serializers.CharField(max_length=255, allow_blank=False)
    restock = serializers.BooleanField(required=False, default=False)
    note_date = serializers.DateField(required=False)
    lines = CreditNoteLineInputSerializer(many=True, allow_empty=False)


class OrderQuerySerializer(serializers.Serializer[Any]):
    """Query-string validation for the order inbox."""

    state = serializers.ChoiceField(choices=OrderState.choices, required=False)
    customer = serializers.IntegerField(required=False, min_value=1)
