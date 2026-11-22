"""Reports API views – read-only, date-filtered and role-checked.

The accountant is read-only by role and may read every report. A salesman has
no access: reports aggregate other salesmen's orders, so they are denied at the
server, not hidden in the UI.
"""

from __future__ import annotations

from datetime import date
from typing import ClassVar

from django.http import HttpResponse
from django.utils.dateparse import parse_date
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Role
from core.errors import DomainError
from core.permissions import RolePermission

from .dashboard import dashboard
from .queries import reconciliation_checks
from .serializers import (
    ReconciliationCheckSerializer,
    ReportCatalogSerializer,
    ReportSerializer,
    serialize_dashboard,
)
from .services import export_report, report_catalog, run_report


class ReportsAPIView(APIView):
    """Base view: deny-by-default report roles."""

    permission_classes: ClassVar[tuple[type[RolePermission], ...]] = (RolePermission,)
    allowed_roles: ClassVar[tuple[str, ...]] = (
        Role.ADMIN,
        Role.ACCOUNTANT,
        Role.OWNER,
        Role.PRODUCTION,
    )


def _date_param(request: Request, name: str) -> date | None:
    raw = request.query_params.get(name)
    if raw in (None, ""):
        return None
    value = parse_date(raw)
    if value is None:
        raise DomainError(f"{name} must be a valid date (YYYY-MM-DD).")
    return value


class ReportCatalogView(ReportsAPIView):
    """GET /api/reports/ – the registered reports and their columns."""

    def get(self, request: Request) -> Response:
        return Response(ReportCatalogSerializer(report_catalog(), many=True).data)


class ReportDetailView(ReportsAPIView):
    """GET /api/reports/<slug>/ – JSON, or a CSV, Excel or PDF download."""

    def get(self, request: Request, slug: str) -> Response | HttpResponse:
        date_from = _date_param(request, "date_from")
        date_to = _date_param(request, "date_to")
        result = run_report(slug, date_from, date_to)

        fmt = (request.query_params.get("format") or "json").lower()
        if fmt == "json":
            return Response(ReportSerializer(result).data)

        content, content_type, filename = export_report(result, fmt)
        response = HttpResponse(content, content_type=content_type)
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


class ReconciliationView(ReportsAPIView):
    """GET /api/reports/reconciliation/ – stock, invoice and GST reconciliations."""

    def get(self, request: Request) -> Response:
        checks = reconciliation_checks(
            _date_param(request, "date_from"),
            _date_param(request, "date_to"),
        )
        return Response(ReconciliationCheckSerializer(checks, many=True).data)


class DashboardView(ReportsAPIView):
    """GET /api/reports/dashboard/ – the owner's day-at-a-glance."""

    allowed_roles = (Role.ADMIN, Role.ACCOUNTANT, Role.OWNER)

    def get(self, request: Request) -> Response:
        return Response(serialize_dashboard(dashboard()))
