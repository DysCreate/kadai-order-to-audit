"""Costing app configuration."""

from django.apps import AppConfig


class CostingConfig(AppConfig):
    name = "apps.costing"
    label = "costing"
    default_auto_field = "django.db.models.BigAutoField"
