"""Role-based access control for Kadai.

RBAC is server-side and deny-by-default.
"""

from __future__ import annotations

import functools
from typing import Any, Callable

from core.errors import DomainError

ROLE_PERMISSIONS: dict[str, list[str]] = {}


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
                raise PermissionDenied(
                    f"Role '{user.role}' is not permitted. Required: {roles}"
                )
            return func(request, *args, **kwargs)

        return wrapper

    return decorator
