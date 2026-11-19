"""Accounts services – business logic for user management.

Invariants protected: role changes are authorised server-side; salesman scope
is enforced; no direct model writes outside this module.
"""

from __future__ import annotations

from django.db import transaction

from .models import User


@transaction.atomic
def create_user(
    username: str,
    password: str,
    role: str,
    email: str = "",
) -> User:
    """Create and return a new User.

    Invariants: role must be a valid Role choice; password is hashed by Django.
    """
    user = User(username=username, email=email, role=role)
    user.set_password(password)
    user.full_clean()
    user.save()
    return user
