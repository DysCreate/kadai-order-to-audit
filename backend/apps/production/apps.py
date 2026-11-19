"""Production app configuration."""

from django.apps import AppConfig


class ProductionConfig(AppConfig):
    name = "apps.production"
    label = "production"
    default_auto_field = "django.db.models.BigAutoField"
