"""
Base settings for Kadai – shared across all environments.
"""

import os
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-insecure-secret-key-do-not-use-in-production")

ALLOWED_HOSTS_ENV = os.environ.get("ALLOWED_HOSTS", "")
ALLOWED_HOSTS: list[str] = [h.strip() for h in ALLOWED_HOSTS_ENV.split(",") if h.strip()] or ["*"]

# ---------------------------------------------------------------------------
# Application definition
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "rest_framework",
    "corsheaders",
    # Project apps
    "apps.accounts",
    "apps.audit",
    "apps.masters",
    "apps.inventory",
    "apps.production",
    "apps.sales",
    "apps.payments",
    "apps.costing",
    "apps.reports",
    "apps.benchmark",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# ---------------------------------------------------------------------------
# Database – PostgreSQL 16 only, never SQLite
# ---------------------------------------------------------------------------
_database_url = os.environ.get(
    "DATABASE_URL",
    "postgresql://{user}:{password}@{host}:{port}/{name}".format(
        user=os.environ.get("POSTGRES_USER", "kadai"),
        password=os.environ.get("POSTGRES_PASSWORD", "kadai"),
        host=os.environ.get("POSTGRES_HOST", "db"),
        port=os.environ.get("POSTGRES_PORT", "5432"),
        name=os.environ.get("POSTGRES_DB", "kadai"),
    ),
)

DATABASES = {
    "default": dj_database_url.parse(
        _database_url,
        conn_max_age=600,
        engine="django.db.backends.postgresql",
    )
}

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ---------------------------------------------------------------------------
# Internationalisation
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static & media
# ---------------------------------------------------------------------------
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# ---------------------------------------------------------------------------
# Default primary key
# ---------------------------------------------------------------------------
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Django REST Framework
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "COERCE_DECIMAL_TO_STRING": True,
    # ``?format=`` selects a report export (csv/excel/pdf) in the view; DRF's
    # renderer negotiation must not claim the parameter and 404 on it.
    "URL_FORMAT_OVERRIDE": None,
    "EXCEPTION_HANDLER": "core.api.domain_exception_handler",
}

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOWED_ORIGINS = [
    o.strip()
    for o in os.environ.get("CORS_ALLOWED_ORIGINS", "http://localhost:5173").split(",")
    if o.strip()
]

# ---------------------------------------------------------------------------
# CSRF
# ---------------------------------------------------------------------------
# The SPA is served from the Vite dev server (5173) or the built web image
# (3000) while the API listens on 8000, so the browser's Origin header never
# matches the API host. Trust the dev origins explicitly (both spellings of
# loopback). A production deployment behind nginx is one origin, so it can set
# the env var to an empty string.
CSRF_TRUSTED_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        "CSRF_TRUSTED_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000",
    ).split(",")
    if o.strip()
]

# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"

# ---------------------------------------------------------------------------
# Login throttle
# ---------------------------------------------------------------------------
# Failed logins are counted per (client address, username) in the local cache.
# Production can raise or lower this without a code change.
LOGIN_MAX_FAILED_ATTEMPTS = int(os.environ.get("LOGIN_MAX_FAILED_ATTEMPTS", "5"))
LOGIN_MAX_FAILED_ATTEMPTS_PER_IP = int(os.environ.get("LOGIN_MAX_FAILED_ATTEMPTS_PER_IP", "20"))
LOGIN_LOCKOUT_SECONDS = int(os.environ.get("LOGIN_LOCKOUT_SECONDS", "300"))
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "kadai",
    }
}

# ---------------------------------------------------------------------------
# Test-only tools
# ---------------------------------------------------------------------------
# The Benchmark Console, its API and the seed/run commands are development and
# CI tools. Production settings turn this off so they are not shipped features.
ENABLE_BENCHMARK_TOOLS = True
