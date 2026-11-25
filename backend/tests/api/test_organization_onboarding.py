"""API tests for organization onboarding and the owner -> admin -> employee flow."""

import json
import uuid
from datetime import timedelta

import pytest
from django.core import mail
from django.test import Client, override_settings
from django.utils import timezone

from apps.accounts.models import Invitation, Organization, Role, User

pytestmark = pytest.mark.django_db


def strong_password() -> str:
    return f"Test-{uuid.uuid4().hex}-Aa1!"


def _register(client: Client, organization: str, username: str) -> dict[str, object]:
    response = client.post(
        "/api/accounts/register/",
        data=json.dumps(
            {
                "organization_name": organization,
                "username": username,
                "email": f"{username}@example.com",
                "password": strong_password(),
            }
        ),
        content_type="application/json",
    )
    assert response.status_code == 201, response.content
    return response.json()["user"]


def _login(client: Client, username: str, password: str) -> None:
    response = client.post(
        "/api/accounts/login/",
        data=json.dumps({"username": username, "password": password}),
        content_type="application/json",
    )
    assert response.status_code == 200, response.content


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_registration_creates_the_organization_and_owner() -> None:
    """A new organization's creator is its owner and is signed in."""
    client = Client()
    user = _register(client, "Fresh Foods", "fresh_owner")

    assert user["role"] == Role.OWNER
    assert user["organization"]["name"] == "Fresh Foods"
    owner = User.objects.get(username="fresh_owner")
    assert owner.organization.name == "Fresh Foods"
    assert owner.is_staff and owner.is_superuser
    assert client.get("/api/accounts/me/").status_code == 200


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_owner_invites_admin_but_not_employee() -> None:
    """Owner -> admin only; the owner cannot invite an employee directly."""
    client = Client()
    _register(client, "Owner Org", "owner")
    owner = User.objects.get(username="owner")
    client.force_login(owner)

    allowed = client.post(
        "/api/accounts/team/invitations/",
        data=json.dumps({"email": "admin@example.com", "role": Role.ADMIN}),
        content_type="application/json",
    )
    denied = client.post(
        "/api/accounts/team/invitations/",
        data=json.dumps({"email": "sales@example.com", "role": Role.SALESMAN}),
        content_type="application/json",
    )

    assert allowed.status_code == 201, allowed.content
    assert denied.status_code == 403
    assert len(mail.outbox) == 1
    assert "admin@example.com" in mail.outbox[0].to
    assert "/invite/" in mail.outbox[0].body


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_admin_invites_employee_but_not_another_admin() -> None:
    """Admin -> salesman/accountant/production, never another admin."""
    client = Client()
    _register(client, "Admin Org", "owner")
    owner = User.objects.get(username="owner")
    admin = User.objects.create_user(
        username="admin",
        email="admin@example.com",
        password=strong_password(),
        role=Role.ADMIN,
        organization=owner.organization,
    )
    client.force_login(admin)

    allowed = client.post(
        "/api/accounts/team/invitations/",
        data=json.dumps({"email": "sales@example.com", "role": Role.SALESMAN}),
        content_type="application/json",
    )
    denied = client.post(
        "/api/accounts/team/invitations/",
        data=json.dumps({"email": "other-admin@example.com", "role": Role.ADMIN}),
        content_type="application/json",
    )

    assert allowed.status_code == 201, allowed.content
    assert denied.status_code == 403


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_invitation_acceptance_creates_a_user_in_the_same_organization() -> None:
    """Accepting an invitation attaches the employee to the inviting organization."""
    client = Client()
    _register(client, "Join Org", "owner")
    owner = User.objects.get(username="owner")
    admin = User.objects.create_user(
        username="join_admin",
        email="join_admin@example.com",
        password=strong_password(),
        role=Role.ADMIN,
        organization=owner.organization,
    )
    client.force_login(admin)
    response = client.post(
        "/api/accounts/team/invitations/",
        data=json.dumps({"email": "sales@example.com", "role": Role.SALESMAN}),
        content_type="application/json",
    )
    assert response.status_code == 201, response.content
    invitation = Invitation.objects.get(email="sales@example.com")

    public = Client()
    token = None
    # The raw token is only in the email; extract it from the console message.
    for line in mail.outbox[-1].body.splitlines():
        if "/invite/" in line:
            token = line.rsplit("/", 1)[-1]
    assert token

    preview = public.get(f"/api/accounts/invitations/{token}/")
    accepted = public.post(
        f"/api/accounts/invitations/{token}/accept/",
        data=json.dumps({"username": "joined_sales", "password": strong_password()}),
        content_type="application/json",
    )

    assert preview.status_code == 200
    assert preview.json()["organization_name"] == "Join Org"
    assert accepted.status_code == 201, accepted.content
    user = User.objects.get(username="joined_sales")
    assert user.organization_id == owner.organization_id
    assert user.role == Role.SALESMAN
    assert Invitation.objects.get(pk=invitation.pk).accepted_at is not None


@pytest.mark.parametrize("role", [Role.SALESMAN, Role.ACCOUNTANT])
def test_employee_cannot_open_team_management(role: str) -> None:
    """Only owner and admin may list or invite team members."""
    client = Client()
    _register(client, "Perm Org", "owner")
    owner = User.objects.get(username="owner")
    employee = User.objects.create_user(
        username=f"employee_{role}",
        email=f"{role}@example.com",
        password=strong_password(),
        role=role,
        organization=owner.organization,
    )
    client.force_login(employee)

    response = client.get("/api/accounts/team/")

    assert response.status_code == 403


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_expired_invitation_can_be_reissued() -> None:
    """An expired invitation does not permanently block the same email."""
    client = Client()
    _register(client, "Expiry Org", "expiry_owner")
    owner = User.objects.get(username="expiry_owner")
    admin = User.objects.create_user(
        username="expiry_admin",
        email="expiry_admin@example.com",
        password=strong_password(),
        role=Role.ADMIN,
        organization=owner.organization,
    )
    client.force_login(admin)
    payload = json.dumps({"email": "expired@example.com", "role": Role.SALESMAN})
    assert (
        client.post(
            "/api/accounts/team/invitations/",
            data=payload,
            content_type="application/json",
        ).status_code
        == 201
    )
    invitation = Invitation.objects.get(email="expired@example.com")
    invitation.expires_at = timezone.now() - timedelta(minutes=1)
    invitation.save(update_fields=["expires_at"])

    response = client.post(
        "/api/accounts/team/invitations/",
        data=payload,
        content_type="application/json",
    )

    assert response.status_code == 201, response.content
    assert Invitation.objects.filter(email="expired@example.com").count() == 1


def test_invalid_invitation_token_is_a_clean_error() -> None:
    """A bad token never reaches a server error."""
    response = Client().post(
        "/api/accounts/invitations/not-a-real-token/accept/",
        data=json.dumps({"username": "nobody", "password": strong_password()}),
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "This invitation is invalid or has already been used."


def test_tenant_manager_hides_other_organizations() -> None:
    """Rows created in one organization are invisible in another."""
    from core.tenancy import tenant_scope

    first = Organization.objects.create(name="First", slug="first")
    second = Organization.objects.create(name="Second", slug="second")

    with tenant_scope(first.pk):
        from apps.masters.models import Item, UoM

        uom = UoM.objects.create(name="Kilogram", symbol="kg")
        Item.objects.create(name="Flour", item_type="RAW", uom=uom)

    with tenant_scope(second.pk):
        from apps.masters.models import Item, UoM

        uom = UoM.objects.create(name="Kilogram", symbol="kg")
        Item.objects.create(name="Flour", item_type="RAW", uom=uom)

    with tenant_scope(first.pk):
        assert list(Item.objects.values_list("name", flat=True)) == ["Flour"]
        assert Item.objects.get(name="Flour").organization_id == first.pk

    with tenant_scope(second.pk):
        assert Item.objects.count() == 1
        assert Item.objects.get(name="Flour").organization_id == second.pk

    assert Item.objects.count() == 2
