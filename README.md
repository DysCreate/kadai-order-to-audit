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
| Sales loop (orders, invoices, dispatch, credit notes, payments) | ✅ Phase 3 |
| Costing (overheads, cost sheet, FG cost and margin) | ✅ Phase 4 |
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

## Phase 3 Sales & Payments API

| Method | Path | Allowed roles |
|--------|------|---------------|
| GET | `/api/masters/customers/` | salesman (assigned only), admin, accountant, owner |
| GET | `/api/masters/items/?type=FG&customer=` | all five roles |
| GET | `/api/sales/orders/?state=&customer=` | salesman (own only), admin, accountant, owner |
| POST | `/api/sales/orders/` | salesman, admin, owner |
| GET | `/api/sales/orders/<id>/` | salesman (own only), admin, accountant, owner |
| GET | `/api/sales/orders/<id>/coverage/` | admin, accountant, owner |
| PATCH | `/api/sales/orders/<id>/lines/<line_id>/` | admin, owner |
| POST | `/api/sales/orders/<id>/approve/` | admin, owner |
| POST | `/api/sales/orders/<id>/reject/` | admin, owner |
| POST | `/api/sales/orders/<id>/invoice/` | admin, owner |
| GET | `/api/sales/invoices/` | salesman (own only), admin, accountant, owner |
| GET | `/api/sales/invoices/<id>/` | salesman (own only), admin, accountant, owner |
| GET | `/api/sales/invoices/<id>/pdf/` | admin, accountant, owner |
| GET | `/api/sales/invoices/pdf/<token>/` | anyone with the signed, expiring link |
| GET | `/api/sales/invoices/<id>/share/` | admin, owner |
| POST | `/api/sales/invoices/<id>/dispatch/` | admin, owner |
| POST | `/api/sales/invoices/<id>/credit-notes/` | admin, owner |
| GET | `/api/payments/payments/?customer=` | admin, accountant, owner |
| POST | `/api/payments/payments/` | admin, owner |
| GET | `/api/payments/outstanding/?customer=` | admin, accountant, owner |
| GET | `/api/payments/ageing/?customer=&as_of=` | admin, accountant, owner |
| GET | `/api/payments/customers/<id>/ledger/` | admin, accountant, owner |

The salesman screens are `/orders/new` and `/orders` (mobile-first, 44 px touch
targets). The admin screens are `/admin/orders` (stock-coverage chips, audited
quantity/price edits, approve/reject, invoice), `/invoices` (PDF, WhatsApp and
mailto share links, dispatch, credit notes) and `/payments` (allocation,
outstanding, ageing and the customer ledger).

## Phase 4 Costing API

| Method | Path | Allowed roles |
|--------|------|---------------|
| GET | `/api/costing/runs/<id>/` | production, admin, accountant, owner |
| POST | `/api/costing/runs/<id>/overheads/` | production, admin, owner |
| GET | `/api/costing/monthly-overheads/?period=` | production, admin, accountant, owner |
| POST | `/api/costing/monthly-overheads/` | production, admin, owner |
| POST | `/api/costing/monthly-overheads/allocate/` | admin, owner |
| GET | `/api/costing/products/<id>/` | production, admin, accountant, owner |

The completed-run screen at `/production/runs/<id>` now carries the cost sheet:
materials by input, overheads, run total, cost per good packet, selling price,
margin and the current finished-goods weighted-average cost. Production, admin
and owner can add labour, gas/power or other overheads from the same screen.

## Sales loop

An order is submitted once per device-generated `client_uuid`; a retry returns
the same order. Prices are resolved from the customer's price list (then the
default list) and snapshotted on the line, so later price changes never rewrite
an existing order or invoice. The state machine is
`SUBMITTED → APPROVED → INVOICED → DISPATCHED`, or `SUBMITTED → REJECTED`, and
every transition writes an `audit_log` row in the same transaction.

Invoices are numbered `INV/26-27/00001` from a row-locked per-financial-year
counter (1 April, Asia/Kolkata), carry CGST + SGST intra-state or IGST
inter-state rounded per line to paise, and show round-off separately. A posted
invoice is immutable: a database trigger rejects UPDATE and DELETE. A credit
note (`CN/26-27/00001`) is the only correction, with an optional restock that
posts a finished-goods `RECEIPT` sourced to the credit note. Dispatch posts
finished-goods `ISSUE` rows and is hard-blocked beyond on-hand stock.

Payments may be partly unallocated. Allocations are locked and can never exceed
an invoice's outstanding balance. Outstanding = invoice total − credit notes −
allocations; ageing buckets are 0–30, 31–60, 61–90 and 90+ days by invoice date.

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
   scrap is absorbed by good packets (assumption A5). Overheads entered after
   completion post a value-only adjustment to the run, so the FG receipt stays
   at material cost and the cost sheet adds the overheads.

Phase 3 adds these readings:

5. **Approval does not hard-block on stock.** The admin may approve and hold an
   order for production; dispatch is the hard gate and refuses to take stock
   below zero. The inbox shows the shortage so the admin can also reduce or
   reject the order.
6. **Invoice cancellation is derived.** Credit notes are append-only; an
   invoice counts as cancelled when credited quantities cover every line. The
   invoice and its lines are never updated, which is what the trigger enforces.
7. **Round-off is a memo line.** The invoice total is exactly taxable + CGST +
   SGST (or taxable + IGST); `round_off` reports the accumulated per-line paise
   rounding and does not change the total.
8. **Credit-note restock is valued at the current weighted-average cost** of
   the finished good (zero if the item has no stock left), so a return cannot
   inflate finished-goods value above cost.
9. **Payments are explicitly allocated.** An unallocated payment is an advance;
   allocations are checked against each invoice's outstanding balance. Ageing
   buckets by invoice date, not by a FIFO payment waterfall.
10. **Shared invoice links expire.** The WhatsApp/mailto link carries a
    Django-signed invoice id valid for seven days and needs no session, so a
    customer can open the PDF without API access.

Phase 4 adds these costing readings:

11. **Overheads enter finished-goods value without quantity.** A run overhead
    posts an append-only `ADJUSTMENT` ledger row with `qty = 0`, so the stock
    balance keeps its packet count and gains the overhead value. The run's
    cost sheet therefore includes overheads even though they arrive after the
    FG receipt. If the FG balance is already zero, the service refuses the
    entry rather than creating value with no stock.
12. **Monthly pools follow batch-hours.** A monthly overhead is split across
    the runs completed in that month (Asia/Kolkata) by
    `batches × standard_batch_hours`; the default standard is one hour per
    batch. A largest-remainder split keeps every share in whole paise and the
    shares sum exactly to the pool. Allocation is idempotent per entry and run.
13. **Run cost and stock cost are different views.** Cost per packet is
    `(net materials + overheads) / good packets`. FG weighted-average cost is
    the current stock value divided by current packets, so it also reflects
    opening FG valuation, dispatches and the timing of overhead entries.
14. **Margin uses the default price list.** The cost sheet compares cost per
    packet with the default selling price; if no price is configured, the
    margin is null rather than invented.

## Benchmark Results

`tests/benchmark/test_benchmark_end_to_end.py` replays Appendix A steps 1-3
through the same services the API uses and asserts every closing (flour 120 kg,
oil 19.5 L, spice mix 3.8 kg, pouches 306, cartons 21, FG 238), the 4,055.00
material cost of the 188-packet receipt, and the variance flags (yield -6% and
oil +5% flagged, pouch -3% not flagged, carton -10% favourable).

The same file now covers steps 4-8: Retailer A's invoice is 7,500.00 taxable +
187.50 CGST + 187.50 SGST = 7,875.00, the dispatch takes FG to 88, Distributor
B's 120-packet order reports a shortage of 32 with an IGST preview of 300.00 on
6,000.00 (6,300.00 total), and a 4,000 payment leaves 3,875.00 outstanding.
Step 8 adds labour 1,200.00 and gas/power 600.00: materials 4,055.00 + overheads
1,800.00 = 5,855.00, cost per good packet 31.14, margin 18.86 (37.72%) at a
selling price of 50.00. After the overheads the remaining 88 packets carry
3,666.30 of value. `make benchmark` (the Benchmark Console of Phase 6) is not
implemented yet.
