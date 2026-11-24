"""Tests for the one-time production owner bootstrap."""

import uuid

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.accounts.models import Role, User


def strong_password() -> str:
    """Build a valid password without committing a credential-like literal."""
    return f"Test-{uuid.uuid4().hex}-Aa1!"


@pytest.mark.django_db
def test_bootstrap_creates_owner_and_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    password = strong_password()
    monkeypatch.setenv("ADMIN_USERNAME", "owner")
    monkeypatch.setenv("ADMIN_EMAIL", "owner@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", password)

    call_command("bootstrap_admin")
    user = User.objects.get(username="owner")
    assert user.role == Role.OWNER
    assert user.is_staff and user.is_superuser
    assert user.check_password(password)

    call_command("bootstrap_admin")
    assert User.objects.filter(username="owner").count() == 1


@pytest.mark.django_db
def test_bootstrap_rejects_weak_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_USERNAME", "owner")
    monkeypatch.setenv("ADMIN_PASSWORD", "short")

    with pytest.raises(CommandError, match="ADMIN_PASSWORD rejected"):
        call_command("bootstrap_admin")
    assert not User.objects.filter(username="owner").exists()


@pytest.mark.django_db
def test_bootstrap_refuses_to_overwrite_without_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    password = strong_password()
    monkeypatch.setenv("ADMIN_USERNAME", "sales")
    monkeypatch.setenv("ADMIN_PASSWORD", password)
    User.objects.create_user(username="sales", password="another-pass-42", role=Role.SALESMAN)

    with pytest.raises(CommandError, match="not an owner superuser"):
        call_command("bootstrap_admin")

    call_command("bootstrap_admin", "--update-password")
    user = User.objects.get(username="sales")
    assert user.role == Role.OWNER
    assert user.is_superuser
    assert user.check_password(password)
