"""DRF integration helpers for the core domain.

Maps ``core.errors.DomainError`` subclasses to 4xx responses with a
machine-readable ``code`` so the frontend never parses prose.
"""

from __future__ import annotations

from typing import Any

from rest_framework.exceptions import NotAuthenticated
from rest_framework.exceptions import PermissionDenied as DRFPermissionDenied
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from core.errors import DomainError
from core.permissions import PermissionDenied


def domain_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    """Return a consistent error body for domain errors, else defer to DRF."""
    if isinstance(exc, PermissionDenied):
        return Response({"code": exc.code, "detail": str(exc)}, status=403)
    if isinstance(exc, DRFPermissionDenied | NotAuthenticated):
        # DRF raises these when a RolePermission refuses a request; keep the
        # same machine-readable body as domain-level denials.
        return Response({"code": "permission_denied", "detail": str(exc)}, status=403)
    if isinstance(exc, DomainError):
        return Response({"code": exc.code, "detail": str(exc)}, status=400)
    return drf_exception_handler(exc, context)
