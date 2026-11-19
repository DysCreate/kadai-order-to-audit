"""Development settings – DEBUG on, inherits base."""

from .base import *  # noqa: F401, F403

DEBUG = True

# In development allow all hosts (ALLOWED_HOSTS already defaults to ["*"])
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
