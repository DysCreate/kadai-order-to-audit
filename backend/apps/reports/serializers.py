"""Reports serializers – Decimal-safe output for reports and the dashboard.

Every Decimal leaves the API as a string, matching the rest of the system; the
frontend never receives a float to do arithmetic on.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, cast

from rest_framework import serializers

from .framework import ReportResult, serialized_row


class ReportSerializer(serializers.Serializer[Any]):
    """A report as columns, stringified rows, totals and context."""

    def to_representation(self, instance: ReportResult) -> dict[str, Any]:
        return {
            "slug": instance.slug,
            "title": instance.title,
            "columns": [
                {"key": column.key, "label": column.label, "kind": column.kind}
                for column in instance.columns
            ],
            "rows": [serialized_row(instance, row) for row in instance.rows],
            "totals": {
                key: _display(instance, key, value) for key, value in instance.totals.items()
            },
            "meta": json_safe(instance.meta),
            "date_from": instance.date_from.isoformat() if instance.date_from else None,
            "date_to": instance.date_to.isoformat() if instance.date_to else None,
        }


def _display(result: ReportResult, key: str, value: Any) -> str:
    column = next((column for column in result.columns if column.key == key), None)
    if column is None:
        return str(value)
    from .framework import display_value

    return display_value(value, column.kind)


class ReportCatalogSerializer(serializers.Serializer[Any]):
    """The list of reports an admin can run."""

    slug = serializers.CharField()
    title = serializers.CharField()
    columns = serializers.SerializerMethodField()

    def get_columns(self, obj: Any) -> list[dict[str, str]]:
        return [
            {"key": column.key, "label": column.label, "kind": column.kind}
            for column in obj.columns
        ]


class ReconciliationCheckSerializer(serializers.Serializer[Any]):
    """One audit check with its verdict."""

    name = serializers.CharField()
    expected = serializers.CharField()
    actual = serializers.CharField()
    passed = serializers.BooleanField()
    detail = serializers.CharField()


def json_safe(value: Any) -> Any:
    """Recursively convert Decimals and dates into JSON-safe strings."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [json_safe(item) for item in value]
    return value


def serialize_dashboard(data: dict[str, Any]) -> dict[str, Any]:
    """Serialise the dashboard payload with every number as a string."""
    return cast(dict[str, Any], json_safe(data))
