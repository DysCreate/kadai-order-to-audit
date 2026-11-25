"""Organization tenancy primitives.

Every business model carries an ``organization`` foreign key. The default
manager filters to the organization active for the current request, and the
model's ``save``/``bulk_create`` paths fill the organization automatically.

Security invariants:
- A request authenticated as a user with an organization only sees rows for
  that organization.
- A request authenticated as a user without an organization sees no tenant
  rows at all (never the unscoped set).
- Management commands and tests run outside a request and are unscoped unless
  ``tenant_scope`` is entered explicitly.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Generic, TypeVar, cast

from django.db import models
from django.utils.text import slugify


@dataclass(frozen=True)
class TenantContext:
    """Whether a tenant boundary is active, and which organization it is."""

    active: bool
    organization_id: int | None


_UNSCOPED = TenantContext(active=False, organization_id=None)
_current: ContextVar[TenantContext] = ContextVar("kadai_tenant", default=_UNSCOPED)
_default_organization_id: int | None = None


def get_tenant_context() -> TenantContext:
    """Return the active tenant context."""
    return _current.get()


@contextmanager
def tenant_scope(organization_id: int | None) -> Iterator[None]:
    """Scope queries to ``organization_id`` for the duration of the block.

    ``None`` is an active scope with no organization: tenant managers return
    no rows, which is the safe default for a user whose organization is unset.
    """
    token = _current.set(TenantContext(active=True, organization_id=organization_id))
    try:
        yield
    finally:
        _current.reset(token)


@contextmanager
def unscoped() -> Iterator[None]:
    """Temporarily disable tenant filtering (management commands and tests)."""
    token = _current.set(_UNSCOPED)
    try:
        yield
    finally:
        _current.reset(token)


def default_organization_id() -> int:
    """Return the deployment's default organization, creating it if needed.

    Used by management commands and by model saves that happen outside a
    request (for example the benchmark seed). Requests always carry an explicit
    organization and never fall back to this.
    """
    global _default_organization_id

    from apps.accounts.models import Organization

    if _default_organization_id is not None:
        if Organization.objects.filter(pk=_default_organization_id).exists():
            return _default_organization_id
        _default_organization_id = None

    organization = Organization.objects.order_by("pk").first()
    if organization is None:
        base_slug = slugify("Kadai Snacks") or "kadai"
        slug = base_slug
        suffix = 1
        while Organization.objects.filter(slug=slug).exists():
            suffix += 1
            slug = f"{base_slug}-{suffix}"
        organization = Organization.objects.create(name="Kadai Snacks", slug=slug)

    _default_organization_id = organization.pk
    return organization.pk


def _scoped_organization_id(instance: Any) -> int | None:
    """Organization to assign to a new tenant row, validating the context."""
    context = get_tenant_context()
    if context.active:
        if context.organization_id is None:
            raise ValueError("Cannot write tenant data without an organization.")
        return context.organization_id

    return default_organization_id()


def _assign_organization(instance: Any) -> None:
    context = get_tenant_context()
    if instance.organization_id is None:
        instance.organization_id = _scoped_organization_id(instance)
        return

    if (
        context.active
        and context.organization_id is not None
        and instance.organization_id != context.organization_id
    ):
        raise ValueError("Cannot write a row for another organization.")


_ModelT = TypeVar("_ModelT", bound=models.Model)


class TenantQuerySet(models.QuerySet[_ModelT], Generic[_ModelT]):
    """QuerySet that fills the organization on bulk inserts."""

    def bulk_create(self, objs: Any, *args: Any, **kwargs: Any) -> Any:
        rows = list(objs)
        for row in rows:
            _assign_organization(row)
        return super().bulk_create(rows, *args, **kwargs)


class TenantManager(models.Manager[_ModelT], Generic[_ModelT]):
    """Default manager that hides every other organization's rows."""

    def get_queryset(self) -> TenantQuerySet[_ModelT]:
        queryset = cast(TenantQuerySet[_ModelT], super().get_queryset())
        context = get_tenant_context()
        if not context.active:
            return queryset
        if context.organization_id is None:
            return queryset.none()
        return queryset.filter(organization_id=context.organization_id)

    def bulk_create(self, objs: Any, *args: Any, **kwargs: Any) -> Any:
        rows = list(objs)
        for row in rows:
            _assign_organization(row)
        return super().bulk_create(rows, *args, **kwargs)


class OrganizationScopedModel(models.Model):
    """Abstract base for every row that belongs to one organization."""

    organization = models.ForeignKey(
        "accounts.Organization",
        on_delete=models.CASCADE,
        related_name="+",
    )
    objects = TenantManager()

    class Meta:
        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        _assign_organization(self)
        super().save(*args, **kwargs)
