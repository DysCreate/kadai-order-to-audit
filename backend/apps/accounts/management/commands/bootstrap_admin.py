"""Create or update the first owner account from environment variables.

A fresh production database has no users, and the demo seed command is
deliberately disabled in production. Run this once from the platform shell:

    ADMIN_USERNAME=owner ADMIN_PASSWORD='...' python manage.py bootstrap_admin

Re-running it is a no-op unless ``--update-password`` is passed.
"""

from __future__ import annotations

import os
from argparse import ArgumentParser
from typing import Any

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import Organization, Role, User
from core.tenancy import default_organization_id


class Command(BaseCommand):
    help = "Create the owner superuser from ADMIN_USERNAME/ADMIN_PASSWORD/ADMIN_EMAIL."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--update-password",
            action="store_true",
            help="Reset the password and owner flags if the user already exists.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        username = os.environ.get("ADMIN_USERNAME", "").strip()
        password = os.environ.get("ADMIN_PASSWORD", "")
        email = os.environ.get("ADMIN_EMAIL", "").strip()

        if not username or not password:
            raise CommandError("Set ADMIN_USERNAME and ADMIN_PASSWORD.")

        try:
            validate_password(password)
        except ValidationError as exc:
            raise CommandError("ADMIN_PASSWORD rejected: " + " ".join(exc.messages)) from exc

        organization = Organization.objects.get(pk=default_organization_id())
        user = User.objects.filter(username=username).first()
        if user is None:
            User.objects.create_superuser(
                username=username,
                email=email,
                password=password,
                role=Role.OWNER,
                organization=organization,
            )
            self.stdout.write(self.style.SUCCESS(f"Created owner {username}."))
            return

        if not options["update_password"]:
            if user.is_superuser and user.role == Role.OWNER:
                self.stdout.write(f"Owner {username} already exists; nothing to do.")
                return
            raise CommandError(
                f"{username} exists but is not an owner superuser. "
                "Pass --update-password to promote it."
            )

        user.email = email or user.email
        user.role = Role.OWNER
        user.organization = organization
        user.is_staff = True
        user.is_superuser = True
        user.set_password(password)
        user.save()
        self.stdout.write(self.style.SUCCESS(f"Updated owner {username}."))
