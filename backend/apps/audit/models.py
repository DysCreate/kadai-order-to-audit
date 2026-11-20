"""Audit log model – one row per change to a business document.

Invariants protected:
- A row is written in the same transaction as the change it describes
  (AGENTS.md Section 4.10); a rolled-back change leaves no audit row.
- ``before`` and ``after`` hold JSON snapshots, so history survives model
  changes and can be shown in a document history tab.
- The entity id column is ``entity_id`` because ``id`` is this table's primary
  key; it still identifies the document named by ``entity``.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone


class AuditLog(models.Model):
    """Append-only record of who changed what, when, and from/to what."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    ts = models.DateTimeField(default=timezone.now, db_index=True)
    entity = models.CharField(max_length=100)
    entity_id = models.PositiveBigIntegerField()
    action = models.CharField(max_length=50)
    before = models.JSONField(default=dict, blank=True)
    after = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "audit_log"
        ordering = ["-ts", "-id"]
        indexes = [
            models.Index(fields=["entity", "entity_id"], name="idx_audit_entity"),
        ]

    def __str__(self) -> str:
        return f"{self.entity}#{self.entity_id} {self.action}"
