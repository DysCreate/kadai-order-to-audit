"""seed_benchmark management command.

Loads the Appendix A master data idempotently. ``--reset`` wipes business data
first so the benchmark scenario can be replayed from scratch.
"""

from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.benchmark.services import seed_benchmark
from apps.inventory.services import stock_summary


class Command(BaseCommand):
    help = "Seed the database with Appendix A benchmark data."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Wipe existing benchmark data before seeding.",
        )

    def handle(self, *args: Any, **options: Any) -> str | None:
        if not settings.ENABLE_BENCHMARK_TOOLS:
            raise CommandError("Benchmark seeding is disabled in this environment.")
        report = seed_benchmark(reset=bool(options["reset"]))
        self.stdout.write(
            self.style.SUCCESS(
                "Seed complete: "
                f"{report.users} users, {report.uoms} UoMs, {report.items} items, "
                f"{report.customers} customers, "
                f"{report.opening_balances} new opening balance(s)."
            )
        )
        self.stdout.write("Stock summary after seed:")
        for row in stock_summary():
            self.stdout.write(
                f"  {row.item.name:<28} {row.qty:>10} {row.item.uom.symbol:<4} "
                f"value {row.value:>10}"
            )
        return None
