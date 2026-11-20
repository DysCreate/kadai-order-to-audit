"""Role-based access control for Kadai.

RBAC is server-side and deny-by-default: a view must explicitly declare the
roles it allows, and everyone else is refused. Frontend hiding is cosmetic
only.

Invariants protected:
- No unauthenticated request passes a role check.
- A view with no ``allowed_roles`` declaration denies every request.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any

from rest_framework.permissions import BasePermission

from core.errors import DomainError


class PermissionDenied(DomainError):
    """Raised when a user does not have the required role."""

    code = "permission_denied"


def require_role(*roles: str) -> Callable[..., Any]:
    """Decorator that checks the request user's role.

    Usage::

        @require_role("admin", "owner")
        def my_view(request, ...):
            ...
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(request: Any, *args: Any, **kwargs: Any) -> Any:
            user = getattr(request, "user", None)
            if user is None or not user.is_authenticated:
                raise PermissionDenied("Authentication required.")
            if getattr(user, "role", None) not in roles:
                raise PermissionDenied(f"Role '{user.role}' is not permitted. Required: {roles}")
            return func(request, *args, **kwargs)

        return wrapper

    return decorator


class RolePermission(BasePermission):  # type: ignore[misc]
    """DRF permission that allows only the roles a view declares.

    The view sets ``allowed_roles`` to a tuple of role codes, for example
    ``allowed_roles = (Role.ADMIN, Role.OWNER)``. Missing declaration means
    nobody is allowed.
    """

    def has_permission(self, request: Any, view: Any) -> bool:
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return False
        allowed_roles = getattr(view, "allowed_roles", ())
        if not allowed_roles:
            return False
        return bool(getattr(user, "role", None) in allowed_roles)
