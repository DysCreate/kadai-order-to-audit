"""Accounts views – login, logout, me."""

import json
from typing import Any

from django.contrib.auth import authenticate, login, logout
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_http_methods


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

    user = authenticate(request, username=username, password=password)
    if user is None:
        return JsonResponse({"detail": "Invalid credentials."}, status=401)

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
