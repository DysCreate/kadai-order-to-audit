"""Benchmark Console API – admin/owner only, always rolled back.

The scenario writes through the real services inside one transaction and then
rolls it back, so pressing Run never leaves benchmark data in the live books.
"""

from __future__ import annotations

from typing import ClassVar

from django.conf import settings
from django.http import Http404
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Role
from core.permissions import RolePermission

from .scenario import run_benchmark_scenario, serialize_result


class BenchmarkRunView(APIView):
    """POST /api/benchmark/run/ – replay Appendix A and return the check table."""

    permission_classes: ClassVar[tuple[type[RolePermission], ...]] = (RolePermission,)
    allowed_roles: ClassVar[tuple[str, ...]] = (Role.ADMIN, Role.OWNER)

    def post(self, request: Request) -> Response:
        if not settings.ENABLE_BENCHMARK_TOOLS:
            raise Http404("Not found.")
        return Response(serialize_result(run_benchmark_scenario()))
