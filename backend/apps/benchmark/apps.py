"""Benchmark app configuration."""

from django.apps import AppConfig


class BenchmarkConfig(AppConfig):
    name = "apps.benchmark"
    label = "benchmark"
    default_auto_field = "django.db.models.BigAutoField"
