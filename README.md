# Kadai — Order-to-Audit System

> NIT Tiruchirappalli CDI Winter Internship 2026 · Prototype for a South Indian snack factory

## Quick Start

```bash
cp .env.example .env
make up      # starts db + api + web
make migrate # run migrations
make seed    # load benchmark data
```

Then open http://localhost:3000

## Test Logins

| Role | Username | Password |
|------|----------|----------|
| Salesman A | salesman_a | salesman_a |
| Salesman B | salesman_b | salesman_b |
| Admin | admin | admin |
| Production | production | production |
| Accountant | accountant | accountant |
| Owner | owner | owner |

## Stack

| Layer | Choice |
|-------|--------|
| Backend | Python 3.12, Django 5.2, DRF |
| Database | PostgreSQL 16 |
| Frontend | React 18, TypeScript, Vite |
| Auth | Django session auth |
| PDF | WeasyPrint |
| Tests | pytest-django, Vitest, Playwright |
| Run | Docker Compose |

## Commands

| Command | What it does |
|---------|-------------|
| `make up` | Start all services |
| `make down` | Stop all services |
| `make seed` | Load benchmark data |
| `make seed-reset` | Reset and reload benchmark data |
| `make test` | Run backend tests |
| `make check` | Lint + typecheck + test |
| `make benchmark` | Run benchmark scenario |
| `make reconcile` | Check ledger consistency |
| `make shell` | Django shell |
| `make psql` | PostgreSQL shell |
| `make logs` | Tail service logs |

## Feature Status

| Feature | Status |
|---------|--------|
| Project scaffold | ✅ Phase 0 |
| Inventory ledger | 🚧 Phase 1 |
| Production runs | 🚧 Phase 2 |
| Sales & invoicing | 🚧 Phase 3 |
| Costing | 🚧 Phase 4 |
| Reports | 🚧 Phase 5 |
| Leakage Radar | 🚧 Phase 6 |
| Offline PWA | 🚧 Phase 7 |

## Assumptions

See [DESIGN.md](docs/DESIGN.md) for full assumptions and design decisions.

## Benchmark Results

Run `make benchmark` after `make seed`. All expected values from AGENTS.md Appendix A.
