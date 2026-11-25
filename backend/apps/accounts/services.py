"""Accounts services – organization onboarding and user invitations.

Invariants protected:
- Registration creates exactly one organization and its owner in one
  transaction.
- An owner may invite admins only; an admin may invite salesman, accountant
  and production users only. Nobody can invite another owner.
- Invitation tokens are stored as SHA-256 hashes, expire, and are single-use.
- Every created user is attached to the inviting organization.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from core.errors import DomainError
from core.permissions import PermissionDenied
from core.tenancy import default_organization_id, get_tenant_context

from .models import Invitation, Organization, Role, User, managed_roles

INVITATION_TTL_DAYS = 7


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _unique_slug(name: str) -> str:
    base = slugify(name) or "organization"
    slug = base
    suffix = 1
    while Organization.objects.filter(slug=slug).exists():
        suffix += 1
        slug = f"{base}-{suffix}"
    return slug


@transaction.atomic
def create_user(
    username: str,
    password: str,
    role: str,
    email: str = "",
    organization: Organization | None = None,
) -> User:
    """Create and return a new User in ``organization``.

    Invariants: role must be a valid Role choice; the user is attached to an
    organization; password is hashed by Django.
    """
    if role not in Role.values:
        raise DomainError(f"Invalid role {role!r}.")

    context = get_tenant_context()
    if organization is None and context.active and context.organization_id is not None:
        organization = Organization.objects.get(pk=context.organization_id)
    if organization is None:
        organization = Organization.objects.get(pk=default_organization_id())

    user = User(username=username, email=email, role=role, organization=organization)
    user.set_password(password)
    user.full_clean()
    user.save()
    return user


@transaction.atomic
def register_organization(
    *,
    organization_name: str,
    username: str,
    email: str,
    password: str,
) -> User:
    """Create an organization and its first owner, who becomes the owner."""
    name = organization_name.strip()
    login = username.strip()
    address = email.strip().lower()
    if not name:
        raise DomainError("Organization name is required.")
    if not login:
        raise DomainError("Username is required.")

    if User.objects.filter(username__iexact=login).exists():
        raise DomainError("That username is already taken.")

    organization = Organization.objects.create(name=name, slug=_unique_slug(name))
    owner = User(
        username=login,
        email=address,
        role=Role.OWNER,
        organization=organization,
        is_staff=True,
        is_superuser=True,
    )
    owner.set_password(password)
    owner.full_clean()
    owner.save()
    return owner


def invitation_for_token(token: str) -> Invitation:
    """Return the pending, unexpired invitation for a raw token."""
    try:
        invitation = Invitation.objects.select_related("organization").get(
            token_hash=_token_hash(token),
            accepted_at__isnull=True,
        )
    except Invitation.DoesNotExist as exc:
        raise DomainError("This invitation is invalid or has already been used.") from exc

    if invitation.expires_at <= timezone.now():
        raise DomainError("This invitation has expired. Ask your administrator for a new one.")
    return invitation


@transaction.atomic
def accept_invitation(*, token: str, username: str, password: str) -> User:
    """Create the invited user and mark the invitation used."""
    try:
        invitation = Invitation.objects.select_for_update().get(
            token_hash=_token_hash(token)
        )
    except Invitation.DoesNotExist as exc:
        raise DomainError("This invitation is invalid or has already been used.") from exc
    if invitation.accepted_at is not None:
        raise DomainError("This invitation has already been used.")
    if invitation.expires_at <= timezone.now():
        raise DomainError("This invitation has expired. Ask your administrator for a new one.")

    login = username.strip()
    if User.objects.filter(username__iexact=login).exists():
        raise DomainError("That username is already taken.")
    if User.objects.filter(
        organization=invitation.organization,
        email__iexact=invitation.email,
    ).exists():
        raise DomainError("A user with this email already belongs to the organization.")

    user = create_user(
        username=login,
        password=password,
        role=invitation.role,
        email=invitation.email,
        organization=invitation.organization,
    )
    invitation.accepted_at = timezone.now()
    invitation.save(update_fields=["accepted_at"])
    return user


def _send_invitation(invitation: Invitation, token: str) -> None:
    site_url = str(getattr(settings, "SITE_URL", "http://localhost:5173")).rstrip("/")
    accept_url = f"{site_url}/invite/{token}"
    send_mail(
        subject=f"Join {invitation.organization.name} on Kadai",
        message=(
            f"You have been invited to join {invitation.organization.name} "
            f"as {invitation.get_role_display()}.\n\n"
            f"Accept the invitation here:\n{accept_url}\n\n"
            f"This link expires in {INVITATION_TTL_DAYS} days."
        ),
        from_email=str(getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@kadai.local")),
        recipient_list=[invitation.email],
        fail_silently=False,
    )


@transaction.atomic
def invite_member(*, inviter: User, email: str, role: str) -> Invitation:
    """Invite one user with a role the inviter is allowed to manage."""
    allowed = managed_roles(inviter.role)
    if not allowed:
        raise PermissionDenied("Your role cannot invite users.")
    if role not in allowed:
        raise PermissionDenied(f"Your role cannot invite a user with role {role!r}.")

    address = email.strip().lower()
    if not address:
        raise DomainError("Email is required.")
    if inviter.organization_id is None:
        raise DomainError("Your account is not attached to an organization.")

    if User.objects.filter(
        organization_id=inviter.organization_id,
        email__iexact=address,
    ).exists():
        raise DomainError("A user with this email already belongs to the organization.")

    token = secrets.token_urlsafe(32)
    expires_at = timezone.now() + timedelta(days=INVITATION_TTL_DAYS)
    pending = Invitation.objects.filter(
        organization_id=inviter.organization_id,
        email__iexact=address,
        accepted_at__isnull=True,
    ).first()
    if pending is not None:
        if pending.expires_at > timezone.now():
            raise DomainError("An invitation for this email is already pending.")
        # Reuse the expired row: the partial unique constraint allows only one
        # pending invitation per organization and email.
        pending.role = role
        pending.invited_by = inviter
        pending.token_hash = _token_hash(token)
        pending.expires_at = expires_at
        pending.save(update_fields=["role", "invited_by", "token_hash", "expires_at"])
        invitation = pending
    else:
        invitation = Invitation.objects.create(
            organization_id=inviter.organization_id,
            email=address,
            role=role,
            invited_by=inviter,
            token_hash=_token_hash(token),
            expires_at=expires_at,
        )

    try:
        _send_invitation(invitation, token)
    except Exception as exc:  # noqa: BLE001 - report any transport failure to the caller
        raise DomainError("Could not send the invitation email. Try again later.") from exc
    return invitation


def team_for(user: User) -> tuple[list[User], list[Invitation], tuple[str, ...]]:
    """Return members, pending invitations and invitable roles for ``user``.

    Owners see the whole organization. Admins see the employees they manage.
    """
    allowed = managed_roles(user.role)
    if not allowed:
        raise PermissionDenied("Your role cannot manage users.")

    members = User.objects.filter(organization_id=user.organization_id).order_by("username")
    invitations = Invitation.objects.filter(
        organization_id=user.organization_id,
        accepted_at__isnull=True,
        expires_at__gt=timezone.now(),
    ).order_by("-created_at")

    if user.role != Role.OWNER:
        members = members.filter(role__in=allowed)
        invitations = invitations.filter(role__in=allowed)

    return list(members), list(invitations), allowed
