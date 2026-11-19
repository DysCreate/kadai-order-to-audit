# Kadai – Code Conventions

## The Golden Rules

1. **Decimal only.** No `float` in money or stock code. Use `core.money.q2()` for paise rounding and `core.quantity.q3()` for quantities.
2. **Services own mutations.** Every write to stock, ledger, invoices, payments or production goes through a `services.py` function decorated `@transaction.atomic`. Views and serializers call services; they never write those tables directly.
3. **Ledger is append-only.** Never UPDATE or DELETE `stock_ledger` rows. Corrections are reversing entries.
4. **Thin views.** Views validate input (via serializers), call a service, and return the result. No business logic in views.

## Backend

- Python 3.12, Django 5.2 LTS, DRF
- Type hints on all service functions; docstring states the invariants it protects
- Raise `core.errors.DomainError` subclasses; map to 4xx with machine-readable codes
- Conventional commits: `feat(app): …`, `fix(app): …`, `test(app): …`

## Frontend

- TypeScript strict mode; no implicit `any`
- Server state in TanStack Query; no manual fetch in components
- All user-visible strings through `react-i18next`
- Touch targets ≥ 44 px on mobile

## Git

- Branches: `feature/<slug>` → `dev` → `main`
- Commit small and often (~300 lines or fewer), tests included
- Never squash, never force-push, never commit to `main` or `dev` directly
