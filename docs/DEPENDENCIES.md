# Kadai – Runtime Dependencies

All versions are pinned in `backend/requirements/base.txt` and `frontend/package.json`.

## Backend (Python)

| Package | Version | Justification |
|---------|---------|---------------|
| Django | 5.2.1 | LTS web framework; session auth, ORM, migrations, admin. |
| djangorestframework | 3.16.0 | REST API layer; serializers, viewsets, authentication. |
| psycopg[binary] | 3.2.6 | psycopg 3 PostgreSQL adapter (binary wheels for speed). |
| dj-database-url | 2.3.0 | Parses `DATABASE_URL` env var into Django `DATABASES` dict. |
| django-cors-headers | 4.7.0 | CORS headers for the Vite dev server origin during development. |
| WeasyPrint | 64.1 | HTML-to-PDF for GST invoices and reports (no headless browser). |
| openpyxl | 3.1.5 | Excel export for monthly reports. |

## Backend (dev / test only — not in base.txt)

| Package | Version | Justification |
|---------|---------|---------------|
| ruff | 0.11.11 | Lint and format (replaces flake8 + isort + black). |
| mypy | 1.15.0 | Static type checking for `services.py` and `core/`. |
| django-stubs | 5.2.0 | Mypy stubs for Django internals. |
| pytest | 8.3.5 | Test runner. |
| pytest-django | 4.11.1 | Django integration for pytest (database fixtures, settings). |
| pytest-cov | 6.1.0 | Coverage reporting with fail-under gate. |
| factory-boy | 3.3.3 | Model factories for test data. |
| hypothesis | 6.131.14 | Property-based testing for ledger invariants and tax. |
| freezegun | 1.5.1 | Freeze time for FY-rollover and invoice-number tests. |
| bandit | latest | Static security analysis (run in CI, not installed in base). |
| pip-audit | latest | Dependency vulnerability scan (run in CI, not installed in base). |

## Frontend (Node / npm)

| Package | Version | Justification |
|---------|---------|---------------|
| react | 18.x | UI library. |
| react-dom | 18.x | DOM renderer. |
| react-router-dom | 6.x | Client-side routing. |
| @tanstack/react-query | 5.x | Server-state management; avoids manual fetch boilerplate. |
| react-i18next | 14.x | Internationalisation (en + ta). |
| recharts | 2.x | Charts for Leakage Radar and Loop Closer. |
| tailwindcss | 3.x | Utility-first CSS; no external component library needed. |
| vite | 5.x | Fast dev server and bundler. |
| vite-plugin-pwa | 0.x | Service worker and manifest for offline PWA. |
| dexie | 3.x | IndexedDB wrapper for offline order queue. |
| typescript | 5.x | Strict type checking. |
| eslint | 8.x | Frontend lint. |
| prettier | 3.x | Code formatting. |
| vitest | 1.x | Unit test runner (Vite-native, replaces Jest). |
| @testing-library/react | 14.x | Component testing utilities. |
| @playwright/test | 1.x | End-to-end browser tests. |

## Explicitly excluded dependencies

| Excluded | Reason |
|----------|--------|
| SQLite | PostgreSQL-only by design; SQLite masks concurrency bugs. |
| Redis / Celery | No background workers; all work is synchronous or in management commands. |
| Auth0 / external SaaS | App must run offline from a clean clone. |
| Next.js / FastAPI | Locked stack per AGENTS.md §2. |
| Redux | TanStack Query covers server state; no client-side global store needed. |
| Any headless browser | WeasyPrint generates PDFs server-side. |
