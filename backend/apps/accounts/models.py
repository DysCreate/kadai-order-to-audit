"""Accounts models – organizations, users, roles and invitations."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, ClassVar

from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models
from django.utils import timezone

from core.tenancy import TenantManager, _assign_organization


class Organization(models.Model):
    """A tenant. Every business row belongs to exactly one organization."""

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "accounts_organization"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Role(models.TextChoices):
    SALESMAN = "salesman", "Salesman"
    ADMIN = "admin", "Admin"
    PRODUCTION = "production", "Production"
    ACCOUNTANT = "accountant", "Accountant"
    OWNER = "owner", "Owner"


# Strict hierarchy: an owner may add admins; an admin may add employees.
MANAGED_ROLES: dict[str, tuple[str, ...]] = {
    Role.OWNER: (Role.ADMIN,),
    Role.ADMIN: (Role.SALESMAN, Role.ACCOUNTANT, Role.PRODUCTION),
}


def managed_roles(role: str) -> tuple[str, ...]:
    """Return the roles ``role`` is allowed to invite."""
    return MANAGED_ROLES.get(role, ())


class TenantUserManager(UserManager):  # type: ignore[type-arg]
    """User manager that keeps authentication and tenant reads scoped."""

    def get_queryset(self) -> models.QuerySet[User]:
        queryset = super().get_queryset()
        from core.tenancy import get_tenant_context

        context = get_tenant_context()
        if not context.active:
            return queryset
        if context.organization_id is None:
            return queryset.none()
        return queryset.filter(organization_id=context.organization_id)


class User(AbstractUser):
    """Custom user with an organization and a factory role."""

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="members",
    )
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.SALESMAN,
    )
    # Circular reference resolved by string "masters.Customer"
    assigned_customers = models.ManyToManyField(
        "masters.Customer",
        blank=True,
        related_name="assigned_salesmen",
    )

    objects: ClassVar[TenantUserManager] = TenantUserManager()

    class Meta:
        db_table = "accounts_user"

    def save(self, *args: Any, **kwargs: Any) -> None:
        _assign_organization(self)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.username} ({self.role})"


class Invitation(models.Model):
    """A pending email invitation to join an organization with one role."""

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="invitations",
    )
    email = models.EmailField()
    role = models.CharField(max_length=20, choices=Role.choices)
    invited_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sent_invitations",
    )
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)

    objects = TenantManager()

    class Meta:
        db_table = "accounts_invitation"
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "email"],
                condition=models.Q(accepted_at__isnull=True),
                name="uniq_pending_invitation_email",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "accepted_at"], name="idx_invite_org_state"),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.expires_at is None:  # pragma: no cover - populated in service
            self.expires_at = timezone.now() + timedelta(days=7)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.email} -> {self.role}"
