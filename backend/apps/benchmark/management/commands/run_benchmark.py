"""run_benchmark management command.

Replays Appendix A through the real services and prints every check. Exits
non-zero when any expected value disagrees, so CI can gate on it. The scenario
runs in a transaction that is rolled back, so the command is safe on a live
database.
"""

from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.benchmark.scenario import run_benchmark_scenario


class Command(BaseCommand):
    help = "Run the Appendix A benchmark console and print every check."

    def handle(self, *args: Any, **options: Any) -> str | None:
        if not settings.ENABLE_BENCHMARK_TOOLS:
            raise CommandError("The benchmark harness is disabled in this environment.")
        result = run_benchmark_scenario()
        self.stdout.write(f"Benchmark: {result.passed}/{len(result.checks)} checks passed")
        self.stdout.write(f"{'Check':<44} {'Expected':>14} {'Actual':>14}  Result")
        for check in result.checks:
            verdict = "PASS" if check.passed else "FAIL"
            self.stdout.write(
                f"{check.name:<44} {check.expected:>14} {check.actual:>14}  {verdict}"
            )

        if not result.ok:
            raise CommandError(
                f"{result.failed} benchmark check(s) failed; expected values in Appendix A "
                "are never edited to make a build pass."
            )
        self.stdout.write(self.style.SUCCESS("All benchmark checks passed."))
        return None
