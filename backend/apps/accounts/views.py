"""Accounts views – login, logout, me."""

import hmac
import json
from typing import Any

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.core.cache import cache
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_http_methods


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

    user = authenticate(request, username=username, password=password)
    if user is None:
        for key in (account_key, address_key):
            cache.set(key, cache.get(key, 0) + 1, window)
        return JsonResponse({"detail": "Invalid credentials."}, status=401)

    # Clear the account's counter only; a valid login must not reset the
    # client-wide counter that protects against username spraying.
    cache.delete(account_key)
    login(request, user)
    return JsonResponse(
        {
            "user": {
                "id": user.pk,
                "username": user.username,
                "role": user.role,
            }
        }
    )


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
    user = request.user
    return JsonResponse(
        {
            "user": {
                "id": user.pk,
                "username": user.username,
                "role": user.role,
            }
        }
    )
