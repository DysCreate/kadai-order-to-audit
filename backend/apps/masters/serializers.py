"""Masters serializers – read-only catalog output for the sales screens."""

from __future__ import annotations

from rest_framework import serializers

from core.errors import PriceNotFound

from .models import Customer, Item
from .services import resolve_price


class CustomerSerializer(serializers.ModelSerializer[Customer]):
    """A customer with the state code that drives the GST place of supply."""

    price_list_id = serializers.IntegerField(read_only=True)
    assigned_salesman = serializers.SerializerMethodField()

    class Meta:
        model = Customer
        fields = (
            "id",
            "name",
            "gstin",
            "state_code",
            "customer_type",
            "price_list_id",
            "assigned_salesman",
        )

    def get_assigned_salesman(self, obj: Customer) -> str | None:
        salesman = obj.assigned_salesman
        return salesman.username if salesman is not None else None


class ItemCatalogSerializer(serializers.ModelSerializer[Item]):
    """A sellable item, with the price resolved for the requesting customer."""

    uom = serializers.CharField(source="uom.symbol", read_only=True)
    price = serializers.SerializerMethodField()

    class Meta:
        model = Item
        fields = ("id", "name", "item_type", "uom", "hsn_code", "gst_rate", "price")

    def get_price(self, obj: Item) -> str | None:
        customer = self.context.get("customer")
        try:
            return str(resolve_price(item=obj, customer=customer))
        except PriceNotFound:
            # An item with no price is not sellable; the screen omits it rather
            # than inventing a price.
            return None
