"""Audit logging for Kadai.

Every mutation to business documents writes an audit log row in the same
database transaction (AGENTS.md Section 4.10). The row itself lives in
``apps.audit``; this module is the stable import path used by services and
tests, mirroring the layout in AGENTS.md Section 3.
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
        entity: Model name, e.g. "Order", "Invoice", "ProductionRun".
        entity_id: Primary key of the affected row.
        action: One of "create", "update", "issue", "complete", "amend", ...
        before: Snapshot of the record before the change (empty dict for creates).
        after: Snapshot of the record after the change.

    Invariants: the row joins the caller's transaction (a failed change leaves
    no audit trail) and Decimals are stored as strings, never floats.
    """
    from apps.audit.services import record_audit

    record_audit(
        user=user,
        entity=entity,
        entity_id=entity_id,
        action=action,
        before=before,
        after=after,
    )
