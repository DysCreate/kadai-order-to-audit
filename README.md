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
| Masters, units, ledger, stock API | ✅ Phase 1 |
| Production loop (BOM, purchases, runs, variance, amend) | ✅ Phase 2 |
| Sales & invoicing | 🚧 Phase 3 |
| Costing | 🚧 Phase 4 |
| Reports | 🚧 Phase 5 |
| Leakage Radar | 🚧 Phase 6 |
| Offline PWA | 🚧 Phase 7 |

## Phase 1 Inventory API

| Method | Path | Allowed roles |
|--------|------|---------------|
| GET | `/api/inventory/stock/` | all five roles |
| GET | `/api/inventory/ledger/?item=&date_from=&date_to=` | admin, production, accountant, owner |
| POST | `/api/inventory/adjustments/` | admin, production, owner |

The stock ledger is append-only (a PostgreSQL trigger rejects UPDATE and DELETE).
Opening balances are `OPENING` ledger rows, so the stock summary is literally a
sum over the ledger. `make seed` loads the Appendix A opening stock and
`make reconcile` proves every balance equals its ledger sum.

## Phase 2 Production API

| Method | Path | Allowed roles |
|--------|------|---------------|
| GET | `/api/production/boms/?product=` | production, admin, accountant, owner |
| POST | `/api/production/boms/` | production, admin, owner |
| GET | `/api/production/runs/?product=` | production, admin, accountant, owner |
| POST | `/api/production/runs/` | production, admin, owner |
| GET | `/api/production/runs/<id>/` | production, admin, accountant, owner |
| POST | `/api/production/runs/<id>/issue/` | production, admin, owner |
| POST | `/api/production/runs/<id>/complete/` | production, admin, owner |
| POST | `/api/production/runs/<id>/amend/` | production, admin, owner |
| POST | `/api/inventory/purchases/` | production, admin, owner |

The run screen lives at `/production` in the web app (tablet-sized numeric
inputs, live variance chips, stored variance table once completed).

## Production loop

A purchase posts one `RECEIPT` row per line and updates the moving weighted
average. A run moves `DRAFT → ISSUED → COMPLETED`: issuing posts one `ISSUE`
row per raw material, completing records the packing result, posts the derived
pouch and carton issues plus the finished-goods `RECEIPT`, and stores a
variance snapshot (one row per input plus the yield). Every transition writes
an `audit_log` row in the same transaction.

## Assumptions

See [DESIGN.md](docs/DESIGN.md) for full assumptions and design decisions.
Phase 2 adds these readings of Appendix A:

1. **Packaging is consumed at packing, not pre-issued.** Step 2 issues raw
   materials only; step 3 derives pouches (`good + damaged`) and cartons
   (`cartons used`). This is what makes the pouch line 194 against a plan of
   200, and it needs no reversal to reach the 306 and 21 closings.
2. **Issued but unused stock is returned at its issue value.** If a supervisor
   issues the full plan and uses less, completion posts a `RECEIPT` for the
   difference at the original weighted-average value. Raw-material actual
   usage equals what was issued; leftovers are a stock adjustment.
3. **A completed run is a closed cost document.** `amend` is accepted only
   while a run is `ISSUED`: it reverses every issue at its original value,
   returns the run to `DRAFT` and is audited. Correcting a completed run is a
   later-phase reversal document.
4. **The finished-goods receipt is valued at the run's net material cost**, so
   scrap is absorbed by good packets (assumption A5). Overheads are Phase 4
   and will post a value-only adjustment to the run.

## Benchmark Results

`tests/benchmark/test_benchmark_end_to_end.py` replays Appendix A steps 1-3
through the same services the API uses and asserts every closing (flour 120 kg,
oil 19.5 L, spice mix 3.8 kg, pouches 306, cartons 21, FG 238), the 4,055.00
material cost of the 188-packet receipt, and the variance flags (yield -6% and
oil +5% flagged, pouch -3% not flagged, carton -10% favourable). All pass.
`make benchmark` (the Benchmark Console of Phase 6) is not implemented yet.
