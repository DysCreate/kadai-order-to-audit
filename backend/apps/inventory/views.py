"""Inventory API views.

Thin: validate input, call a service, serialise the result. Role checks are
server-side and deny-by-default through ``RolePermission``.
"""

from __future__ import annotations

from typing import ClassVar

from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Role
from core.permissions import RolePermission

from .serializers import (
    PurchaseInputSerializer,
    PurchaseSerializer,
    StockAdjustmentInputSerializer,
    StockAdjustmentSerializer,
    StockLedgerEntrySerializer,
    StockLedgerQuerySerializer,
    StockSummaryRowSerializer,
)
from .services import (
    PurchaseLineInput,
    adjust_stock,
    create_purchase,
    ledger_entries,
    stock_summary,
)


class InventoryAPIView(APIView):
    """Base view: every inventory endpoint must declare its allowed roles."""

    permission_classes: ClassVar[tuple[type[RolePermission], ...]] = (RolePermission,)
    allowed_roles: ClassVar[tuple[str, ...]] = ()


class StockSummaryView(InventoryAPIView):
    """GET /api/inventory/stock/ – current balance for every item."""

    allowed_roles = tuple(Role.values)

    def get(self, request: Request) -> Response:
        return Response(StockSummaryRowSerializer(stock_summary(), many=True).data)


class StockLedgerView(InventoryAPIView):
    """GET /api/inventory/ledger/ – append-only movements, filterable."""

    allowed_roles = (Role.ADMIN, Role.PRODUCTION, Role.ACCOUNTANT, Role.OWNER)

    def get(self, request: Request) -> Response:
        query = StockLedgerQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        entries = ledger_entries(
            item_id=query.validated_data.get("item"),
            date_from=query.validated_data.get("date_from"),
            date_to=query.validated_data.get("date_to"),
        )
        return Response(StockLedgerEntrySerializer(entries, many=True).data)


class PurchaseCreateView(InventoryAPIView):
    """POST /api/inventory/purchases/ – receive goods and post RECEIPT rows."""

    allowed_roles = (Role.ADMIN, Role.PRODUCTION, Role.OWNER)

    def post(self, request: Request) -> Response:
        serializer = PurchaseInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        purchase = create_purchase(
            supplier=serializer.validated_data["supplier"],
            reference=serializer.validated_data.get("reference", ""),
            purchase_date=serializer.validated_data.get("purchase_date"),
            notes=serializer.validated_data.get("notes", ""),
            lines=[
                PurchaseLineInput(
                    item_id=line["item"].pk,
                    qty=line["qty"],
                    unit_cost=line["unit_cost"],
                )
                for line in serializer.validated_data["lines"]
            ],
            user=request.user,
        )
        return Response(PurchaseSerializer(purchase).data, status=201)


class StockAdjustmentView(InventoryAPIView):
    """POST /api/inventory/adjustments/ – post a reasoned stock adjustment."""

    allowed_roles = (Role.ADMIN, Role.PRODUCTION, Role.OWNER)

    def post(self, request: Request) -> Response:
        serializer = StockAdjustmentInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        adjustment = adjust_stock(
            item_id=serializer.validated_data["item"].pk,
            qty_delta=serializer.validated_data["qty_delta"],
            reason=serializer.validated_data["reason"],
            unit_cost=serializer.validated_data.get("unit_cost"),
            user=request.user,
        )
        return Response(StockAdjustmentSerializer(adjustment).data, status=201)
