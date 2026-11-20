"""API tests for session authentication: login, CSRF handshake and logout.

Requirement: AGENTS.md Section 2 (Django session auth + CSRF) and Section 5
(API endpoints cover allowed and denied paths).
"""

import json

import pytest
from django.test import Client

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
