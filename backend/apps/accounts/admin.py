"""Accounts admin registration."""

from typing import Any

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.http import HttpRequest

from .models import Organization, User


@admin.register(User)
class CustomUserAdmin(UserAdmin):  # type: ignore[type-arg]
    list_display = ("username", "email", "role", "is_staff")
    fieldsets = UserAdmin.fieldsets + (  # type: ignore[operator]
        ("Kadai", {"fields": ("organization", "role", "assigned_customers")}),
    )

    def formfield_for_foreignkey(self, db_field: Any, request: HttpRequest, **kwargs: Any) -> Any:
        """Never let an owner select another organization in the admin."""
        organization = getattr(request, "organization", None)
        if db_field.name == "organization" and organization is not None:
            kwargs["queryset"] = Organization.objects.filter(pk=organization.pk)
            kwargs["initial"] = organization
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request: HttpRequest, obj: User, form: Any, change: bool) -> None:
        if obj.organization_id is None:
            obj.organization_id = getattr(request, "organization_id", None)
        super().save_model(request, obj, form, change)
