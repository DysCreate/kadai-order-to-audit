"""Production settings.

Every deployment value comes from the environment: the container refuses to
start without a strong ``SECRET_KEY``, an explicit ``ALLOWED_HOSTS`` and a
``DATABASE_URL``. Development conveniences (DEBUG, the Benchmark Console, the
seed users and the Vite origins) are off.
"""

from __future__ import annotations

import os

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401, F403

DEBUG = False

# ---------------------------------------------------------------------------
# Required deployment configuration
# ---------------------------------------------------------------------------
SECRET_KEY = os.environ.get("SECRET_KEY", "")
if len(SECRET_KEY) < 32 or SECRET_KEY.startswith("dev-") or SECRET_KEY == "change-me":
    raise ImproperlyConfigured("SECRET_KEY must be a unique value of at least 32 characters.")

_hosts = [host.strip() for host in os.environ.get("ALLOWED_HOSTS", "").split(",") if host.strip()]
# Render injects its public hostname; accept it without making the operator
# repeat it in ALLOWED_HOSTS.
_render_host = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "").strip()
if _render_host:
    _hosts.append(_render_host)
if not _hosts:
    raise ImproperlyConfigured("ALLOWED_HOSTS must list the deployment hostnames.")
if "*" in _hosts:
    raise ImproperlyConfigured("ALLOWED_HOSTS must not contain '*' in production.")
ALLOWED_HOSTS = _hosts

if not os.environ.get("DATABASE_URL"):
    raise ImproperlyConfigured("DATABASE_URL must point at the production PostgreSQL database.")

# Neon (and poolers in front of it) may suspend idle connections; check before
# use instead of surfacing a dead-connection error, and skip prepared
# statements when the connection string goes through a transaction pooler.
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True  # noqa: F405
DATABASES["default"].setdefault("OPTIONS", {})["prepare_threshold"] = None  # noqa: F405

# ---------------------------------------------------------------------------
# Origin and transport security
# ---------------------------------------------------------------------------
# The SPA and API share one origin (nginx or the Cloudflare Worker), so
# cross-origin access is off unless an operator names trusted origins.
CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = os.environ.get("SECURE_SSL_REDIRECT", "true").lower() != "false"
# Render's health check reaches the container over plain HTTP from its internal
# network. Keep every other route HTTPS-only, but let /api/health/ answer so
# the service is not marked unhealthy for correctly redirecting.
SECURE_REDIRECT_EXEMPT = [r"^api/health/?$"]

# Set on both the Cloudflare Worker and Render to a shared random value. The
# login throttle only trusts X-Real-IP when the Worker proves it set it, so a
# direct caller cannot rotate that header to evade the per-client limit.
TRUSTED_PROXY_SECRET = os.environ.get("TRUSTED_PROXY_SECRET", "")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_AGE = int(os.environ.get("SESSION_COOKIE_AGE", str(12 * 60 * 60)))
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "31536000"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# ---------------------------------------------------------------------------
# Static files (WhiteNoise) and test tools
# ---------------------------------------------------------------------------
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
WHITENOISE_MAX_AGE = 60 * 60 * 24 * 365

# Gunicorn workers do not share LocMem, so the login throttle uses a file
# cache on the container's local disk. A multi-host deployment should point
# this at a shared cache instead.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
        "LOCATION": "/tmp/kadai-cache",
    }
}

ENABLE_BENCHMARK_TOOLS = os.environ.get("ENABLE_BENCHMARK_TOOLS", "false").lower() == "true"

# ---------------------------------------------------------------------------
# Logging: one line per request/error on stdout, which the platform collects.
# ---------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "plain"},
    },
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}
