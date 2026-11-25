"""Accounts views – onboarding, invitations, login, logout, me."""

import hmac
import json
from typing import Any, ClassVar

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.core.cache import cache
from django.http import HttpRequest, JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_http_methods
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Role, User
from apps.accounts.serializers import (
    AcceptInvitationSerializer,
    InvitationPreviewSerializer,
    InvitationSerializer,
    InviteMemberSerializer,
    RegisterSerializer,
    TeamMemberSerializer,
)
from apps.accounts.services import (
    accept_invitation,
    invitation_for_token,
    invite_member,
    register_organization,
    team_for,
)
from core.errors import DomainError
from core.permissions import RolePermission
from core.tenancy import unscoped


def _client_address(request: HttpRequest) -> str:
    """Return the address used for the per-client login throttle.

    nginx overwrites ``X-Real-IP`` with the address it saw, so it is trusted in
    the self-hosted stack. In the managed deployment the API host is public, so
    a shared secret is required before the Worker's forwarded address is
    trusted; otherwise a direct caller could rotate ``X-Real-IP`` to bypass the
    per-client limit. With no secret configured the previous nginx behaviour is
    preserved.
    """
    forwarded = str(request.META.get("HTTP_X_REAL_IP") or "")
    secret = str(getattr(settings, "TRUSTED_PROXY_SECRET", ""))
    if not secret:
        return forwarded or str(request.META.get("REMOTE_ADDR") or "unknown")

    supplied = str(request.META.get("HTTP_X_KADAI_PROXY_SECRET") or "")
    if forwarded and hmac.compare_digest(supplied, secret):
        return forwarded
    return str(request.META.get("REMOTE_ADDR") or "unknown")


def _login_failure_keys(request: HttpRequest, username: str) -> tuple[str, str]:
    """Return the (account, client-address) throttle keys for this attempt."""
    address = _client_address(request)
    return (
        f"login-fail:{address}:{username.strip().lower()}",
        f"login-fail-ip:{address}",
    )


def _user_data(user: User) -> dict[str, Any]:
    """Serialise the signed-in user, including their organization."""
    return {
        "id": user.pk,
        "username": user.username,
        "role": user.role,
        "organization": {
            "id": user.organization_id,
            "name": user.organization.name,
        },
    }


class PublicAPIView(APIView):
    """Anonymous endpoint: no session authentication and no CSRF pre-check."""

    permission_classes: ClassVar[tuple[type[AllowAny], ...]] = (AllowAny,)
    authentication_classes: ClassVar[tuple[type[object], ...]] = ()


class RegisterView(PublicAPIView):
    """POST /api/accounts/register/ – create an organization and its owner."""

    def post(self, request: Request) -> Response:
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = register_organization(
            organization_name=serializer.validated_data["organization_name"],
            username=serializer.validated_data["username"],
            email=serializer.validated_data["email"],
            password=serializer.validated_data["password"],
        )
        login(request._request, user)
        get_token(request._request)
        return Response({"user": _user_data(user)}, status=201)


class InvitationPreviewView(PublicAPIView):
    """GET /api/accounts/invitations/<token>/ – details for the accept screen."""

    def get(self, request: Request, token: str) -> Response:
        try:
            invitation = invitation_for_token(token)
        except DomainError as exc:
            raise NotFound("This invitation is invalid or has expired.") from exc
        return Response(InvitationPreviewSerializer(invitation).data)


class AcceptInvitationView(PublicAPIView):
    """POST /api/accounts/invitations/<token>/accept/ – join the organization."""

    def post(self, request: Request, token: str) -> Response:
        serializer = AcceptInvitationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = accept_invitation(
            token=token,
            username=serializer.validated_data["username"],
            password=serializer.validated_data["password"],
        )
        login(request._request, user)
        get_token(request._request)
        return Response({"user": _user_data(user)}, status=201)


class TeamView(APIView):
    """GET /api/accounts/team/ – members and pending invites for the org."""

    permission_classes: ClassVar[tuple[type[RolePermission], ...]] = (RolePermission,)
    allowed_roles: ClassVar[tuple[str, ...]] = (Role.OWNER, Role.ADMIN)

    def get(self, request: Request) -> Response:
        members, invitations, roles = team_for(request.user)
        return Response(
            {
                "members": TeamMemberSerializer(members, many=True).data,
                "invitations": InvitationSerializer(invitations, many=True).data,
                "invitable_roles": list(roles),
            }
        )


class TeamInviteView(APIView):
    """POST /api/accounts/team/invitations/ – email one invitation."""

    permission_classes: ClassVar[tuple[type[RolePermission], ...]] = (RolePermission,)
    allowed_roles: ClassVar[tuple[str, ...]] = (Role.OWNER, Role.ADMIN)

    def post(self, request: Request) -> Response:
        serializer = InviteMemberSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        invitation = invite_member(
            inviter=request.user,
            email=serializer.validated_data["email"],
            role=serializer.validated_data["role"],
        )
        return Response(InvitationSerializer(invitation).data, status=201)


@csrf_exempt
@ensure_csrf_cookie
@require_http_methods(["POST"])
def login_view(request: HttpRequest) -> JsonResponse:
    """POST /api/accounts/login/ – authenticate, open session, issue CSRF token.

    Login itself is exempt (the SPA has no token yet), but the response sets the
    csrftoken cookie so subsequent unsafe calls such as logout can present it.
    """
    try:
        data: dict[str, Any] = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"detail": "Invalid JSON."}, status=400)

    username = data.get("username", "")
    password = data.get("password", "")

    account_key, address_key = _login_failure_keys(request, username)
    window = settings.LOGIN_LOCKOUT_SECONDS
    if (
        cache.get(account_key, 0) >= settings.LOGIN_MAX_FAILED_ATTEMPTS
        or cache.get(address_key, 0) >= settings.LOGIN_MAX_FAILED_ATTEMPTS_PER_IP
    ):
        return JsonResponse(
            {
                "code": "login_rate_limited",
                "detail": "Too many failed attempts. Try again later.",
            },
            status=429,
        )

    # Authentication must find a username in any organization; the request's
    # current tenant scope must not hide another account during a switch.
    with unscoped():
        user = authenticate(request, username=username, password=password)
    if user is None:
        for key in (account_key, address_key):
            cache.set(key, cache.get(key, 0) + 1, window)
        return JsonResponse({"detail": "Invalid credentials."}, status=401)

    # Clear the account's counter only; a valid login must not reset the
    # client-wide counter that protects against username spraying.
    cache.delete(account_key)
    login(request, user)
    return JsonResponse({"user": _user_data(user)})


@require_http_methods(["POST"])
def logout_view(request: HttpRequest) -> JsonResponse:
    """POST /api/accounts/logout/ – clear session."""
    logout(request)
    return JsonResponse({"detail": "Logged out."})


@require_http_methods(["GET"])
def me_view(request: HttpRequest) -> JsonResponse:
    """GET /api/accounts/me/ – return current user or 401."""
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Not authenticated."}, status=401)
    return JsonResponse({"user": _user_data(request.user)})
