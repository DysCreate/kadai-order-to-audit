"""Audit logging for Kadai.

Every mutation to business documents writes an audit log row in the same
database transaction. This module provides the stub; the real implementation
will write to an AuditLog model once it is created.
"""

from __future__ import annotations

from typing import Any


def log_audit(
    user: Any,
    entity: str,
    entity_id: int,
    action: str,
    before: dict[str, Any],
    after: dict[str, Any],
) -> None:
    """Write an audit log entry in the current transaction.

    Args:
        user: The User performing the action.
        entity: Model name, e.g. "Order", "Invoice".
        entity_id: Primary key of the affected row.
        action: One of "create", "update", "cancel", etc.
        before: Snapshot of the record before the change (empty dict for creates).
        after: Snapshot of the record after the change.
    """
    # TODO: implement once AuditLog model is created
    pass
