"""API tests for session authentication: login, CSRF handshake and logout.

Requirement: AGENTS.md Section 2 (Django session auth + CSRF) and Section 5
(API endpoints cover allowed and denied paths).
"""

import json

import pytest
from django.core.cache import cache
from django.test import Client, override_settings

from apps.accounts.models import Role, User

pytestmark = pytest.mark.django_db


def _login(client: Client, user: User) -> None:
    response = client.post(
        "/api/accounts/login/",
        data=json.dumps({"username": user.username, "password": "test-pass"}),
        content_type="application/json",
    )
    assert response.status_code == 200


def test_login_opens_session_and_sets_csrf_cookie(role_users: dict[str, User]) -> None:
    """PS 12 session auth: login returns the user and a csrftoken cookie."""
    client = Client(enforce_csrf_checks=True)

    _login(client, role_users[Role.ADMIN])

    assert "csrftoken" in client.cookies
    me = client.get("/api/accounts/me/")
    assert me.status_code == 200
    assert me.json()["user"]["role"] == Role.ADMIN


def test_login_with_bad_credentials_is_401(role_users: dict[str, User]) -> None:
    """PS 12 negative path: wrong password never opens a session."""
    client = Client(enforce_csrf_checks=True)

    response = client.post(
        "/api/accounts/login/",
        data=json.dumps({"username": role_users[Role.ADMIN].username, "password": "wrong"}),
        content_type="application/json",
    )

    assert response.status_code == 401
    assert client.get("/api/accounts/me/").status_code == 401


def test_login_is_rate_limited_after_repeated_failures(
    role_users: dict[str, User],
) -> None:
    """PS 12 hardening: repeated bad passwords are refused with 429."""
    cache.clear()
    client = Client(enforce_csrf_checks=True)
    payload = json.dumps({"username": role_users[Role.ADMIN].username, "password": "wrong"})

    with override_settings(LOGIN_MAX_FAILED_ATTEMPTS=3, LOGIN_MAX_FAILED_ATTEMPTS_PER_IP=100):
        for _ in range(3):
            assert (
                client.post(
                    "/api/accounts/login/", data=payload, content_type="application/json"
                ).status_code
                == 401
            )
        limited = client.post("/api/accounts/login/", data=payload, content_type="application/json")

    assert limited.status_code == 429
    assert limited.json()["code"] == "login_rate_limited"
    cache.clear()


def test_direct_callers_cannot_spoof_the_forwarded_address(
    role_users: dict[str, User],
) -> None:
    """A forged X-Real-IP without the Worker secret cannot evade the IP limit."""
    cache.clear()
    client = Client(enforce_csrf_checks=True)
    payload = json.dumps({"username": role_users[Role.ADMIN].username, "password": "wrong"})

    with override_settings(
        TRUSTED_PROXY_SECRET="shared-proxy-secret",
        LOGIN_MAX_FAILED_ATTEMPTS=100,
        LOGIN_MAX_FAILED_ATTEMPTS_PER_IP=2,
    ):
        for address in ("203.0.113.1", "203.0.113.2"):
            assert (
                client.post(
                    "/api/accounts/login/",
                    data=payload,
                    content_type="application/json",
                    HTTP_X_REAL_IP=address,
                    HTTP_X_KADAI_PROXY_SECRET="wrong",
                ).status_code
                == 401
            )
        limited = client.post(
            "/api/accounts/login/",
            data=payload,
            content_type="application/json",
            HTTP_X_REAL_IP="203.0.113.3",
            HTTP_X_KADAI_PROXY_SECRET="wrong",
        )

    assert limited.status_code == 429
    cache.clear()


def test_logout_requires_csrf_token(role_users: dict[str, User]) -> None:
    """PS 12 CSRF: logout without the token is refused and keeps the session."""
    client = Client(enforce_csrf_checks=True)
    _login(client, role_users[Role.SALESMAN])

    response = client.post("/api/accounts/logout/")

    assert response.status_code == 403
    assert client.get("/api/accounts/me/").status_code == 200


def test_logout_with_csrf_token_clears_session(role_users: dict[str, User]) -> None:
    """PS 12 CSRF: the SPA's logout path (cookie echoed as header) works."""
    client = Client(enforce_csrf_checks=True)
    _login(client, role_users[Role.SALESMAN])
    token = client.cookies["csrftoken"].value

    response = client.post("/api/accounts/logout/", HTTP_X_CSRFTOKEN=token)

    assert response.status_code == 200
    assert client.get("/api/accounts/me/").status_code == 401


def test_csrf_accepts_the_loopback_dev_origin(role_users: dict[str, User]) -> None:
    """PS 12 CSRF: the Vite origin 127.0.0.1:5173 is trusted, not only localhost."""
    client = Client(enforce_csrf_checks=True)
    _login(client, role_users[Role.SALESMAN])
    token = client.cookies["csrftoken"].value

    response = client.post(
        "/api/accounts/logout/",
        HTTP_X_CSRFTOKEN=token,
        HTTP_ORIGIN="http://127.0.0.1:5173",
    )

    assert response.status_code == 200


def test_csrf_rejects_an_untrusted_origin(role_users: dict[str, User]) -> None:
    """PS 12 CSRF: an origin outside the trusted list is still refused."""
    client = Client(enforce_csrf_checks=True)
    _login(client, role_users[Role.SALESMAN])
    token = client.cookies["csrftoken"].value

    response = client.post(
        "/api/accounts/logout/",
        HTTP_X_CSRFTOKEN=token,
        HTTP_ORIGIN="http://evil.example",
    )

    assert response.status_code == 403
    assert client.get("/api/accounts/me/").status_code == 200
