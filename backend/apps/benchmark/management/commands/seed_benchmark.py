"""seed_benchmark management command – skeleton."""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Seed the database with Appendix A benchmark data."

    def add_arguments(self, parser):  # type: ignore[override]
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Wipe existing benchmark data before seeding.",
        )

    def handle(self, *args, **options):  # type: ignore[override]
        self.stdout.write("TODO: implement seed_benchmark")
