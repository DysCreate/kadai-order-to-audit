"""Accounts admin registration."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):  # type: ignore[type-arg]
    list_display = ("username", "email", "role", "is_staff")
    fieldsets = UserAdmin.fieldsets + (  # type: ignore[operator]
        ("Kadai", {"fields": ("role", "assigned_customers")}),
    )
