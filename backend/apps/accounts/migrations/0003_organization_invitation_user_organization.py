from typing import Any

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


def create_default_organization(apps: Any, schema_editor: Any) -> None:
    Organization = apps.get_model("accounts", "Organization")
    Organization.objects.create(pk=1, name="Kadai Snacks", slug="kadai-snacks")
    schema_editor.execute(
        "SELECT setval(pg_get_serial_sequence('accounts_organization', 'id'), 1, true)"
    )


def delete_default_organization(apps: Any, schema_editor: Any) -> None:
    Organization = apps.get_model("accounts", "Organization")
    Organization.objects.filter(pk=1).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Organization",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=200)),
                ("slug", models.SlugField(max_length=100, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "accounts_organization",
                "ordering": ["name"],
            },
        ),
        migrations.RunPython(create_default_organization, delete_default_organization),
        migrations.AddField(
            model_name="user",
            name="organization",
            field=models.ForeignKey(
                default=1,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="members",
                to="accounts.organization",
            ),
            preserve_default=False,
        ),
        migrations.CreateModel(
            name="Invitation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("email", models.EmailField(max_length=254)),
                ("role", models.CharField(choices=[("salesman", "Salesman"), ("admin", "Admin"), ("production", "Production"), ("accountant", "Accountant"), ("owner", "Owner")], max_length=20)),
                ("token_hash", models.CharField(max_length=64, unique=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("expires_at", models.DateTimeField()),
                ("accepted_at", models.DateTimeField(blank=True, null=True)),
                ("invited_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="sent_invitations", to=settings.AUTH_USER_MODEL)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="invitations", to="accounts.organization")),
            ],
            options={
                "db_table": "accounts_invitation",
                "ordering": ["-created_at", "-pk"],
            },
        ),
        migrations.AddConstraint(
            model_name="invitation",
            constraint=models.UniqueConstraint(
                condition=models.Q(("accepted_at__isnull", True)),
                fields=("organization", "email"),
                name="uniq_pending_invitation_email",
            ),
        ),
        migrations.AddIndex(
            model_name="invitation",
            index=models.Index(fields=["organization", "accepted_at"], name="idx_invite_org_state"),
        ),
    ]
