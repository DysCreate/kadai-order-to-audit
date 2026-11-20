"""reconcile management command – prove balance == SUM(ledger) for every item.

Exits non-zero when any balance disagrees with the append-only ledger, so
``make reconcile`` is a real gate rather than a report.
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.inventory.models import StockBalance
from apps.inventory.services import reconcile_stock


class Command(BaseCommand):
    help = "Verify that every stock balance equals the sum of its ledger rows."

    def handle(self, *args: Any, **options: Any) -> str | None:
        issues = reconcile_stock()
        checked = StockBalance.objects.count()
        if issues:
            for issue in issues:
                self.stderr.write(
                    f"MISMATCH item {issue.item_id}: balance qty={issue.balance_qty} "
                    f"value={issue.balance_value}, ledger qty={issue.ledger_qty} "
                    f"value={issue.ledger_value}"
                )
            raise CommandError(f"Reconciliation failed: {len(issues)} issue(s).")

        self.stdout.write(
            self.style.SUCCESS(
                f"Reconciliation OK: {checked} item balance(s) equal the ledger sum."
            )
        )
        return None
