"""Payments serializers – validation and Decimal-safe output only."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from rest_framework import serializers

from apps.masters.models import Customer
from apps.sales.models import Invoice

from .models import Payment, PaymentAllocation, PaymentMethod


class PaymentAllocationSerializer(serializers.ModelSerializer[PaymentAllocation]):
    """One allocation of a payment to an invoice."""

    invoice_id = serializers.IntegerField(read_only=True)
    invoice_number = serializers.CharField(source="invoice.number", read_only=True)

    class Meta:
        model = PaymentAllocation
        fields = ("id", "invoice_id", "invoice_number", "amount")


class PaymentSerializer(serializers.ModelSerializer[Payment]):
    """A payment with its allocations."""

    customer_id = serializers.IntegerField(read_only=True)
    customer_name = serializers.CharField(source="customer.name", read_only=True)
    allocations = PaymentAllocationSerializer(many=True, read_only=True)

    class Meta:
        model = Payment
        fields = (
            "id",
            "customer_id",
            "customer_name",
            "amount",
            "payment_date",
            "method",
            "reference",
            "notes",
            "created_at",
            "allocations",
        )


class AllocationInputSerializer(serializers.Serializer[Any]):
    """One invoice to settle."""

    invoice = serializers.PrimaryKeyRelatedField(queryset=Invoice.objects.all())
    amount = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        min_value=Decimal("0.01"),
    )


class PaymentCreateSerializer(serializers.Serializer[Any]):
    """Input for recording money received."""

    customer = serializers.PrimaryKeyRelatedField(queryset=Customer.objects.all())
    amount = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        min_value=Decimal("0.01"),
    )
    method = serializers.ChoiceField(choices=PaymentMethod.choices, default=PaymentMethod.CASH)
    payment_date = serializers.DateField(required=False)
    reference = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
    notes = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    allocations = AllocationInputSerializer(many=True, required=False, default=list)

    def validate_allocations(self, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        invoice_ids = [row["invoice"].pk for row in value]
        if len(invoice_ids) != len(set(invoice_ids)):
            raise serializers.ValidationError("An invoice can only be allocated once.")
        return value


class AgeingBucketSerializer(serializers.Serializer[Any]):
    """One ageing bucket."""

    label = serializers.CharField()
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)


class LedgerInvoiceSerializer(serializers.Serializer[Any]):
    """One invoice row in a customer ledger."""

    invoice_id = serializers.IntegerField(source="invoice.pk")
    number = serializers.CharField(source="invoice.number")
    invoice_date = serializers.DateField(source="invoice.invoice_date")
    total = serializers.DecimalField(source="invoice.total", max_digits=14, decimal_places=2)
    credited = serializers.DecimalField(max_digits=14, decimal_places=2)
    paid = serializers.DecimalField(max_digits=14, decimal_places=2)
    outstanding = serializers.DecimalField(max_digits=14, decimal_places=2)
    age_days = serializers.IntegerField()


class CustomerLedgerSerializer(serializers.Serializer[Any]):
    """A customer's invoices, payments, outstanding total and ageing."""

    customer_id = serializers.IntegerField(source="customer.pk")
    customer_name = serializers.CharField(source="customer.name")
    outstanding = serializers.DecimalField(max_digits=14, decimal_places=2)
    buckets = AgeingBucketSerializer(many=True)
    invoices = LedgerInvoiceSerializer(many=True)
    payments = PaymentSerializer(many=True)
