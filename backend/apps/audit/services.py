"""Audit services – the only writer for ``audit_log``.

Invariants protected:
- The row is written inside the caller's transaction, so a failed business
  change never leaves an audit trail of something that did not happen.
- Snapshots are stored JSON-safe: Decimals become strings, so no money or
  quantity is silently turned into a float.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db import transaction

from apps.accounts.models import User

from .models import AuditLog


def to_jsonable(value: Any) -> Any:
    """Recursively convert a snapshot into JSON-safe primitives.

    Decimals are rendered as strings (never floats) to match the API contract.
    """
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [to_jsonable(item) for item in value]
    return value


@transaction.atomic
def record_audit(
    *,
    user: User | None,
    entity: str,
    entity_id: int,
    action: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> AuditLog:
    """Write one audit row for a change that is already happening.

    Invariants: ``entity``, ``entity_id`` and ``action`` are mandatory; the row
    joins the caller's transaction rather than opening its own.
    """
    if not entity.strip():
        raise ValueError("An audit row needs an entity name.")
    if entity_id <= 0:
        raise ValueError("An audit row needs a positive entity id.")
    if not action.strip():
        raise ValueError("An audit row needs an action.")

    return AuditLog.objects.create(
        user=user if user is not None and user.pk else None,
        entity=entity,
        entity_id=entity_id,
        action=action.strip(),
        before=to_jsonable(before or {}),
        after=to_jsonable(after or {}),
    )


def audit_trail(*, entity: str, entity_id: int) -> list[AuditLog]:
    """Return the audit rows for one document, newest first."""
    return list(AuditLog.objects.filter(entity=entity, entity_id=entity_id).select_related("user"))
