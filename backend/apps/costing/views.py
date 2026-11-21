"""Costing API views.

Thin: validate input, call a service, serialise the result. Role checks are
server-side and deny-by-default; costing data is visible to production, admin,
accountant and owner, while only production/admin/owner may record overheads.
Allocating a monthly pool posts stock value, so it is restricted to
admin/owner.
"""

from __future__ import annotations

from decimal import Decimal
from typing import ClassVar

from django.shortcuts import get_object_or_404
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Role
from apps.masters.models import Item
from apps.production.models import ProductionRun
from core.money import q2
from core.permissions import RolePermission

from .serializers import (
    CostSheetSerializer,
    MonthlyOverheadCreateSerializer,
    OptionalPeriodSerializer,
    OverheadAllocationSerializer,
    OverheadEntrySerializer,
    PeriodSerializer,
    ProductCostSerializer,
    RunOverheadCreateSerializer,
)
from .services import (
    allocate_monthly_overhead,
    monthly_overheads,
    product_cost_summary,
    record_monthly_overhead,
    record_run_overhead,
    run_cost_sheet,
)

READ_ROLES: tuple[str, ...] = (Role.PRODUCTION, Role.ADMIN, Role.ACCOUNTANT, Role.OWNER)
WRITE_ROLES: tuple[str, ...] = (Role.PRODUCTION, Role.ADMIN, Role.OWNER)
ALLOCATE_ROLES: tuple[str, ...] = (Role.ADMIN, Role.OWNER)


class CostingAPIView(APIView):
    """Base view: GET uses read roles, every write uses write roles."""

    permission_classes: ClassVar[tuple[type[RolePermission], ...]] = (RolePermission,)
    allowed_roles: tuple[str, ...] = ()
    read_roles: ClassVar[tuple[str, ...]] = READ_ROLES
    write_roles: ClassVar[tuple[str, ...]] = WRITE_ROLES

    def initial(self, request: Request, *args: object, **kwargs: object) -> None:
        self.allowed_roles = self.read_roles if request.method == "GET" else self.write_roles
        super().initial(request, *args, **kwargs)

    def _run(self, pk: int) -> ProductionRun:
        return get_object_or_404(ProductionRun, pk=pk)


class RunCostSheetView(CostingAPIView):
    """GET /api/costing/runs/<id>/ – materials, overheads, cost and margin."""

    def get(self, request: Request, pk: int) -> Response:
        return Response(CostSheetSerializer(run_cost_sheet(self._run(pk))).data)


class RunOverheadView(CostingAPIView):
    """POST /api/costing/runs/<id>/overheads/ – add overhead to a completed run."""

    def post(self, request: Request, pk: int) -> Response:
        serializer = RunOverheadCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        run = self._run(pk)
        record_run_overhead(
            run=run,
            category=serializer.validated_data["category"],
            amount=serializer.validated_data["amount"],
            description=serializer.validated_data["description"],
            user=request.user,
        )
        return Response(CostSheetSerializer(run_cost_sheet(run)).data, status=201)


class MonthlyOverheadCollectionView(CostingAPIView):
    """GET/POST /api/costing/monthly-overheads/ – monthly pool entries."""

    def get(self, request: Request) -> Response:
        query = OptionalPeriodSerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        period = query.validated_data.get("period")
        entries = list(monthly_overheads(period))
        total = q2(sum((entry.amount for entry in entries), Decimal("0.00")))
        return Response(
            {
                "period": period.isoformat() if period is not None else None,
                "total": str(total),
                "entries": OverheadEntrySerializer(entries, many=True).data,
            }
        )

    def post(self, request: Request) -> Response:
        serializer = MonthlyOverheadCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        entry = record_monthly_overhead(
            period=serializer.validated_data["period"],
            category=serializer.validated_data["category"],
            amount=serializer.validated_data["amount"],
            description=serializer.validated_data["description"],
            user=request.user,
        )
        return Response(OverheadEntrySerializer(entry).data, status=201)


class MonthlyOverheadAllocateView(CostingAPIView):
    """POST /api/costing/monthly-overheads/allocate/ – split a month's pool."""

    write_roles: ClassVar[tuple[str, ...]] = ALLOCATE_ROLES

    def post(self, request: Request) -> Response:
        serializer = PeriodSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        allocations = allocate_monthly_overhead(
            period=serializer.validated_data["period"],
            user=request.user,
        )
        return Response(
            {
                "allocations": OverheadAllocationSerializer(
                    allocations,
                    many=True,
                ).data,
                "count": len(allocations),
            }
        )


class ProductCostView(CostingAPIView):
    """GET /api/costing/products/<id>/ – FG weighted-average cost and margin."""

    def get(self, request: Request, pk: int) -> Response:
        product = get_object_or_404(Item, pk=pk)
        return Response(ProductCostSerializer(product_cost_summary(product)).data)
