"""Accounts models – custom User with role and assigned customers."""

from django.contrib.auth.models import AbstractUser
from django.db import models


class Role(models.TextChoices):
    SALESMAN = "salesman", "Salesman"
    ADMIN = "admin", "Admin"
    PRODUCTION = "production", "Production"
    ACCOUNTANT = "accountant", "Accountant"
    OWNER = "owner", "Owner"


class User(AbstractUser):
    """Custom user model with factory role and customer assignment."""

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.SALESMAN,
    )
    # Circular reference resolved by string "masters.Customer"
    assigned_customers = models.ManyToManyField(
        "masters.Customer",
        blank=True,
        related_name="assigned_salesmen",
    )

    class Meta:
        db_table = "accounts_user"

    def __str__(self) -> str:
        return f"{self.username} ({self.role})"
