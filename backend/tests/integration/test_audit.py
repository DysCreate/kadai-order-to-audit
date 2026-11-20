"""Audit log integration tests.

Requirement: AGENTS.md Section 4.10 – the audit row is written in the caller's
transaction, snapshots are JSON-safe, and the trail is queryable per document.
"""

from decimal import Decimal

import pytest
from django.db import transaction

from apps.accounts.models import User
from apps.accounts.services import create_user
from apps.audit.models import AuditLog
from apps.audit.services import audit_trail, record_audit


@pytest.fixture
def user(db: None) -> User:
    return create_user(username="auditor", password="test-pass", role="admin")


def test_record_audit_stores_json_safe_snapshots(user: User) -> None:
    """PS 4.10: Decimals become strings; user, entity and action are stored."""
    row = record_audit(
        user=user,
        entity="ProductionRun",
        entity_id=12,
        action="amend",
        before={"issued_qty": Decimal("10.500")},
        after={"issued_qty": Decimal("9.000"), "reason": "Wrong issue"},
    )

    assert row.before == {"issued_qty": "10.500"}
    assert row.after == {"issued_qty": "9.000", "reason": "Wrong issue"}
    assert row.user_id == user.pk


def test_record_audit_rejects_incomplete_rows(user: User) -> None:
    """PS 4.10: an audit row always names an entity, an id and an action."""
    with pytest.raises(ValueError):
        record_audit(user=user, entity="  ", entity_id=1, action="create")
    with pytest.raises(ValueError):
        record_audit(user=user, entity="Order", entity_id=0, action="create")
    with pytest.raises(ValueError):
        record_audit(user=user, entity="Order", entity_id=1, action="")


def test_audit_row_rolls_back_with_its_transaction(user: User) -> None:
    """PS 4.10: a failed change leaves no audit trail behind."""
    with pytest.raises(RuntimeError), transaction.atomic():
        record_audit(user=user, entity="Order", entity_id=5, action="create")
        raise RuntimeError("business change failed")

    assert AuditLog.objects.filter(entity="Order", entity_id=5).count() == 0


def test_audit_trail_returns_rows_newest_first(user: User) -> None:
    """PS 4.10: the history tab can read one document's trail."""
    record_audit(user=user, entity="ProductionRun", entity_id=3, action="create")
    record_audit(user=user, entity="ProductionRun", entity_id=3, action="issue")
    record_audit(user=user, entity="ProductionRun", entity_id=4, action="create")

    trail = audit_trail(entity="ProductionRun", entity_id=3)

    assert [row.action for row in trail] == ["issue", "create"]
    assert all(row.entity_id == 3 for row in trail)
