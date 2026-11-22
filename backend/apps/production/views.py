"""Production API views.

Thin: validate input, call a service, serialise the result. Role checks are
server-side and deny-by-default through ``RolePermission``; read and write
roles differ per method, so ``initial`` selects the right set before the
permission check runs.
"""

from __future__ import annotations

from typing import ClassVar

from django.shortcuts import get_object_or_404
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Role
from apps.masters.models import Item
from core.permissions import RolePermission

from .models import ProductionRun
from .serializers import (
    BOMCreateSerializer,
    BOMSerializer,
    LeakageTrendsSerializer,
    ProductionRunSerializer,
    ReportCardSerializer,
    RunAmendSerializer,
    RunCompleteSerializer,
    RunCreateSerializer,
    RunIssueSerializer,
)
from .services import (
    BOMLineInput,
    amend_run,
    complete_run,
    create_bom_version,
    create_run,
    issue_run,
    leakage_trends,
    list_boms,
    production_runs,
    run_report_card,
)

READ_ROLES: tuple[str, ...] = (Role.PRODUCTION, Role.ADMIN, Role.ACCOUNTANT, Role.OWNER)
WRITE_ROLES: tuple[str, ...] = (Role.PRODUCTION, Role.ADMIN, Role.OWNER)


class ProductionAPIView(APIView):
    """Base view: reads and writes declare their own role sets."""

    permission_classes: ClassVar[tuple[type[RolePermission], ...]] = (RolePermission,)
    # ``allowed_roles`` is set per request in ``initial``, so it is an instance
    # attribute: RolePermission reads it from the view instance.
    allowed_roles: tuple[str, ...] = ()
    read_roles: ClassVar[tuple[str, ...]] = READ_ROLES
    write_roles: ClassVar[tuple[str, ...]] = WRITE_ROLES

    def initial(self, request: Request, *args: object, **kwargs: object) -> None:
        self.allowed_roles = self.read_roles if request.method == "GET" else self.write_roles
        super().initial(request, *args, **kwargs)

    def _run(self, pk: int) -> ProductionRun:
        return get_object_or_404(ProductionRun, pk=pk)

    def _product_filter(self, request: Request) -> Item | None:
        """Return the optional ?product= filter, or 404 when it is invalid."""
        raw = request.query_params.get("product")
        if raw in (None, ""):
            return None
        try:
            return Item.objects.get(pk=int(raw))
        except (TypeError, ValueError) as exc:
            raise NotFound("product must be an item id.") from exc
        except Item.DoesNotExist as exc:
            raise NotFound("Unknown product filter.") from exc


class BOMCollectionView(ProductionAPIView):
    """GET /api/production/boms/ – list versions; POST – create a version."""

    def get(self, request: Request) -> Response:
        return Response(BOMSerializer(list_boms(self._product_filter(request)), many=True).data)

    def post(self, request: Request) -> Response:
        serializer = BOMCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        bom = create_bom_version(
            product=serializer.validated_data["product"],
            batch_output_qty=serializer.validated_data["batch_output_qty"],
            lines=[
                BOMLineInput(
                    item_id=line["item"].pk,
                    qty_per_batch=line["qty_per_batch"],
                    role=line["role"],
                    standard_rate=line["standard_rate"],
                )
                for line in serializer.validated_data["lines"]
            ],
            user=request.user,
        )
        return Response(BOMSerializer(bom).data, status=201)


class RunCollectionView(ProductionAPIView):
    """GET /api/production/runs/ – list runs; POST – create a DRAFT run."""

    def get(self, request: Request) -> Response:
        runs = production_runs(product=self._product_filter(request))
        return Response(ProductionRunSerializer(runs, many=True).data)

    def post(self, request: Request) -> Response:
        serializer = RunCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        run = create_run(
            product=serializer.validated_data["product"],
            batches=serializer.validated_data["batches"],
            user=request.user,
        )
        return Response(ProductionRunSerializer(run).data, status=201)


class RunDetailView(ProductionAPIView):
    """GET /api/production/runs/<id>/ – run, lines and stored variance."""

    def get(self, request: Request, pk: int) -> Response:
        return Response(ProductionRunSerializer(self._run(pk)).data)


class RunIssueView(ProductionAPIView):
    """POST /api/production/runs/<id>/issue/ – issue materials (DRAFT -> ISSUED)."""

    def post(self, request: Request, pk: int) -> Response:
        serializer = RunIssueSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        issued = {row["line"]: row["qty"] for row in serializer.validated_data["lines"]}
        run = issue_run(run=self._run(pk), issued=issued, user=request.user)
        return Response(ProductionRunSerializer(run).data)


class RunCompleteView(ProductionAPIView):
    """POST /api/production/runs/<id>/complete/ – packing record and FG receipt."""

    def post(self, request: Request, pk: int) -> Response:
        serializer = RunCompleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        run = complete_run(
            run=self._run(pk),
            good_packets=serializer.validated_data["good_packets"],
            damaged_pouches=serializer.validated_data["damaged_pouches"],
            cartons_used=serializer.validated_data["cartons_used"],
            user=request.user,
        )
        return Response(ProductionRunSerializer(run).data)


class RunAmendView(ProductionAPIView):
    """POST /api/production/runs/<id>/amend/ – reverse issues, back to DRAFT."""

    def post(self, request: Request, pk: int) -> Response:
        serializer = RunAmendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        run = amend_run(
            run=self._run(pk),
            reason=serializer.validated_data["reason"],
            user=request.user,
        )
        return Response(ProductionRunSerializer(run).data)


class RunReportCardView(ProductionAPIView):
    """GET /api/production/runs/<id>/report-card/ – the Leakage Radar card."""

    def get(self, request: Request, pk: int) -> Response:
        return Response(ReportCardSerializer(run_report_card(self._run(pk))).data)


class ProductLeakageView(ProductionAPIView):
    """GET /api/production/products/<id>/leakage/ – trends and drift alerts."""

    def get(self, request: Request, pk: int) -> Response:
        product = get_object_or_404(Item, pk=pk)
        return Response(LeakageTrendsSerializer(leakage_trends(product)).data)
