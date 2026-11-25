"""Request middleware that activates the signed-in user's tenant scope."""

from __future__ import annotations

from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

from core.tenancy import tenant_scope, unscoped


class CurrentOrganizationMiddleware:
    """Filter tenant rows to the authenticated user's organization.

    Anonymous requests run unscoped because the only public tenant reads are
    invitation previews and signed PDF tokens, which look rows up by an
    unguessable token or signed id. Authenticated users always run with an
    active scope, so a user with no organization sees no tenant rows.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            request.organization_id = user.organization_id  # type: ignore[attr-defined]
            request.organization = user.organization  # type: ignore[attr-defined]
            with tenant_scope(user.organization_id):
                return self.get_response(request)
        request.organization_id = None  # type: ignore[attr-defined]
        request.organization = None  # type: ignore[attr-defined]
        with unscoped():
            return self.get_response(request)
