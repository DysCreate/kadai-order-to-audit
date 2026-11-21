"""Masters read API – customers and the priced item catalog.

The salesman only sees the customers assigned to them, and prices are resolved
per customer through ``masters.services.resolve_price`` so the frontend never
computes a price. Writes to master data stay in services and the seed command;
this phase exposes reads only.
"""

from __future__ import annotations

from typing import ClassVar, cast

from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Role, User
from core.permissions import RolePermission

from .models import Customer, Item, ItemType
from .serializers import CustomerSerializer, ItemCatalogSerializer


class MastersAPIView(APIView):
    """Base view: deny-by-default role declaration."""

    permission_classes: ClassVar[tuple[type[RolePermission], ...]] = (RolePermission,)
    allowed_roles: ClassVar[tuple[str, ...]] = ()


def _user(request: Request) -> User:
    return cast(User, request.user)


class CustomerCollectionView(MastersAPIView):
    """GET /api/masters/customers/ – assigned customers for a salesman."""

    allowed_roles = (Role.SALESMAN, Role.ADMIN, Role.ACCOUNTANT, Role.OWNER)

    def get(self, request: Request) -> Response:
        user = _user(request)
        customers = Customer.objects.select_related("price_list", "assigned_salesman")
        if user.role == Role.SALESMAN:
            customers = customers.filter(assigned_salesmen=user)
        return Response(CustomerSerializer(customers.order_by("name"), many=True).data)


class ItemCatalogView(MastersAPIView):
    """GET /api/masters/items/?type=FG&customer=<id> – priced item catalog."""

    allowed_roles = tuple(Role.values)

    def get(self, request: Request) -> Response:
        items = Item.objects.select_related("uom").order_by("name")

        item_type = request.query_params.get("type")
        if item_type not in (None, ""):
            if item_type not in ItemType.values:
                return Response({"detail": "type must be RAW, PACKAGING or FG."}, status=400)
            items = items.filter(item_type=item_type)

        customer = None
        raw_customer = request.query_params.get("customer")
        if raw_customer not in (None, ""):
            try:
                customer_id = int(raw_customer)
            except (TypeError, ValueError) as exc:
                raise Http404("customer must be a customer id.") from exc
            customer = get_object_or_404(Customer, pk=customer_id)

        serializer = ItemCatalogSerializer(items, many=True, context={"customer": customer})
        return Response(serializer.data)
