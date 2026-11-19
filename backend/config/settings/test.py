"""Test settings – used by pytest-django. Inherits base."""

from .base import *  # noqa: F401, F403

DEBUG = False

# Fast password hashing in tests
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]
