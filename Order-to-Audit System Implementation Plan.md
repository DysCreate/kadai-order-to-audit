# Order-to-Audit System: Implementation Plan

NIT Tiruchirappalli, Centre for Digital Infrastructure · Winter Internship 2026 shortlisting task · Prepared for Pranav · Working name: **Kadai** (Tamil for both 'shop' and the frying pan)

## 1. Strategy

| Criterion | Weight | How this plan wins it | Phase |
| --- | --- | --- | --- |
| Benchmark correctness | 30% | Section 5 encoded as an automated end-to-end test and a one-click in-app console; every number reproduced, any difference explained | 2–6 |
| Production and inventory design | 20% | Append-only stock ledger, versioned BOM, Decimal base-unit conversion, variance engine as a pure tested function | 1–2 |
| Sales-to-invoice flow | 15% | Order state machine, live stock check, database-enforced no-negative stock | 3 |
| Data model and code quality | 15% | Service layer owns every mutation; tests for stock, tax and variance maths | 0–8 |
| Usability | 10% | Role-specific screens; salesman order in under 60 seconds, checked by a timed test | 3, 7 |
| Reports and documentation | 10% | One report framework to Excel, CSV and PDF; reconciliation ticks; README and design note | 5, 8 |
| Stretch | up to +10% | USP, offline PWA, low-stock alerts, Tamil UI | 6–7 |

Three rules that run through every phase:

1. **Ledger first.** No code path writes a stock number. Every change is an append-only movement with a source document; balances are derived and reconciled.
2. **Benchmark first.** Write `test_benchmark_end_to_end` in Phase 2 (it starts red) and let it go green step by step.
3. **Gate the extras.** The USP and stretch goals start only after tag `v0.1` exists (all must-haves, the should-haves and the benchmark). The PDF says a smaller system that runs the benchmark correctly beats a larger one that does not.

## 2. The USP: Leakage Radar

**Pitch.** Most submissions will show variance as a red percentage. Kadai turns every deviation into rupees, explains where it came from, and shows when it is becoming a habit. That answers the client's actual pain point in the PDF: 'wastage goes unnoticed'. It also sits on the heaviest-weighted part of the evaluation (production, variance, costing).

### 2.1 Run Report Card (generated on every production run)

Benchmark run, standard = BOM rates, actual = what the ledger recorded (weighted-average flour):

| Line | Standard | Actual | ₹ impact |
| --- | --- | --- | --- |
| Flour 40 kg | @42 = 1,680 | @43.125 = 1,725 | +45 (price) |
| Cooking oil | 10 L = 1,400 | 10.5 L = 1,470 | +70 (usage) |
| Salt and spice mix | 1.2 kg = 240 | 1.2 kg = 240 | 0 |
| Pouches | 200 = 500 | 194 = 485 | −15 (usage) |
| Cartons | 10 = 150 | 9 = 135 | −15 (usage) |
| **Materials** | **3,970** | **4,055** | **+85** |

**Cost-per-packet bridge** (a waterfall chart): standard material ₹19.85 → **+₹1.27 yield shortfall** (188 good packets vs 200) → +₹0.45 net price and usage variances → actual material ₹21.57 → +₹9.57 overhead → **₹31.14 per packet**.

**Yield-gap explainer:** 12 packets missing = 6 recorded as damaged pouches (explained scrap) + 6 unexplained process loss. Showing 'unexplained' as its own number is the insight most teams will not have.

### 2.2 Trend and drift

- Per-ingredient variance sparkline across the last N runs of each product.
- Drift rule: the same input is adverse beyond half the tolerance on 3 consecutive runs, so raise a 'drift' alert before it breaches the hard 3% limit.
- Owner dashboard tile: **Leakage this month (₹)** = sum of adverse usage, price and yield variances, with the top 3 culprits.
- Everything is deterministic and unit-tested. No LLM in the numbers path. An optional plain-English summary of a card is a last-day extra, never a dependency.

### 2.3 Two supporting differentiators (cheap, high return)

- **Self-verifying Benchmark Console.** An admin page and `make benchmark` replay steps 1–9 through the same service functions the API uses, then print a table of every Section 5 check: expected, actual, pass or fail. The same run is a CI job. The evaluator sees green ticks in 30 seconds, which protects the 30% criterion.
- **Loop Closer (shortage to production to purchase).** At step 6 (Distributor B, shortage of 32 packets) the order screen shows: batches needed = ceil(shortage ÷ (BOM yield × trailing average yield factor)); how many batches current raw and packaging stock allows and the limiting item; a draft purchase list for any gap; one click to create a planned production run. For the benchmark: 1 batch needed, stock allows 1 (oil allows 1.95 and pouches 1.53 batches), so it is feasible. This visibly joins the sales loop and the production loop, which is the core of the problem.

## 3. Stack (tailored to what you have already shipped)

| Layer | Choice | Why |
| --- | --- | --- |
| Backend | Django 5 + Django REST Framework | Native Decimal, ACID transactions, `select_for_update` row locks, migrations |
| Database | PostgreSQL 16 | NUMERIC types, CHECK constraints, triggers for append-only tables |
| Frontend | React + Vite + TypeScript, installable PWA (vite-plugin-pwa, Dexie for IndexedDB) | One codebase for the salesman's phone and staff desktops; offline outbox |
| Auth | Django auth (session or SimpleJWT) with a Role model | No external tenant, so the evaluator can run it with one command |
| PDF and Excel | WeasyPrint (HTML to PDF), openpyxl, csv | Invoice is an HTML template; no headless Chrome |
| Tests | pytest-django, Vitest, Playwright | Stock, tax, variance and the timed order test |
| Run | Docker Compose (db, api, web) + Makefile | `make up`, `make seed`, `make test`, `make benchmark` |
| CI | GitHub Actions: ruff, pytest, tsc, plus Gitleaks, Bandit, pip-audit | Same layered checks you already use |

**README-ready justification:** Django and PostgreSQL because stock and money need ACID transactions, row-level locking and exact Decimal arithmetic. A React PWA because salesmen need an installable, offline-capable phone UI and staff need a desktop UI from the same codebase. Docker Compose so the whole system, seeded with the benchmark data, starts with one command.

## 4. Design decisions to defend in the interview

- **Numbers.** Quantities are NUMERIC(14,3) in the item's base unit (kg, L, piece, packet), so grams and millilitres are exact. Money NUMERIC(14,2), rates NUMERIC(14,4). Python Decimal with explicit ROUND\_HALF\_UP. No floats in money or stock code (add a test that fails if one appears).
- **Units.** Global conversions (kg and g, L and mL) plus item-specific ones (carton = 20 packets). Finished goods are held in packets; cartons are a packaging item consumed per run and a display unit on dispatch (150 packets = 7.5 cartons).
- **Ledger.** `stock_ledger(item, batch_id nullable, qty_delta, value_delta, source_type, source_id, user, ts)` is append-only (a trigger blocks UPDATE and DELETE). `stock_balance(item, qty, value)` is updated in the same transaction under a row lock with CHECK qty >= 0. Opening balances are OPENING ledger rows, so opening + receipts − issues ± adjustments = closing is literally a SUM. A `reconcile` command and a test assert balance = SUM(ledger). Keep the nullable batch\_id from day 1 so batch and expiry are cheap later.
- **Valuation: moving weighted average.** Flour and oil lots are interchangeable, it is simple to audit, and it needs no lot tracking. Issue value = round(issue qty × running value ÷ running qty); the balance keeps the remainder so value never drifts. Benchmark: 100 kg @42 + 60 kg @45 = 160 kg, ₹6,900, so ₹43.125/kg and 40 kg costs ₹1,725. Implement valuation as a strategy class so FIFO can be swapped in live.
- **Overheads.** Labour and gas or power entered against a run are assigned fully to that run. A monthly pool is allocated across runs by standard batch-hours (per-product field, default 1 per batch). Cost per packet = (materials + overheads) ÷ good packets, so scrap cost is absorbed by good output. Finished-goods value is posted at run completion with materials; overheads later post a value-only ledger adjustment (qty 0).
- **Variance.** Flag when |actual − planned| ÷ planned > tolerance (default 3%, a setting). Strictly greater matters: pouches are exactly −3.0% (194 vs 200) and should not flag. Show direction (favourable or adverse). Computed once at run completion and stored as a snapshot, so later BOM edits do not rewrite history.
- **BOM.** Versioned header plus lines (raw and packaging, quantity per batch, unit). Runs reference a version and copy planned quantities.
- **GST.** Place of supply = customer state vs factory state (Tamil Nadu, code 33). Same state gives CGST + SGST (half each); different gives IGST. Tax rounded half-up per line to paise; round-off shown separately. HSN and rate live on the product. Invoice number `INV/26-27/00001` (15 characters, inside the 16-character GST limit) from a row-locked per-financial-year counter (FY starts 1 April). Credit notes use `CN/26-27/00001`.
- **Immutability and audit.** Posted invoices cannot be edited or deleted (trigger); cancel with a credit note, with an optional restock. `audit_log(user, ts, entity, id, action, before JSON, after JSON)` is written in the service layer inside the same transaction. History tab on orders, invoices and runs.
- **Concurrency.** Every mutating service is `@transaction.atomic`; lock stock\_balance rows in item-id order. Test that two simultaneous dispatches of the last packets cannot both succeed.
- **RBAC.** Server-side policy per endpoint, tested as a role × endpoint matrix. Salesman: own orders and assigned customers. Admin: orders, invoices, dispatch, payments, customers, prices. Production: purchases, issues, runs, adjustments, stock views. Accountant: read-only reports and exports. Owner: dashboard and read-all.
- **Interview-proofing (a 500 g pack on the same BOM).** BOM header holds `batch_output_qty` (assumption: 40 kg of bulk product) and recipe lines; a pack spec (pack size, pouch item, carton item, packets per carton) converts bulk to packets. A 500 g product is then one new pack-spec row. Rehearse this exact change.

## 5. Data model (for the ER diagram)

- **Identity:** user, role
- **Masters:** item (type RAW, PACKAGING, FG), uom, uom\_conversion, supplier, customer (GSTIN, state code, type, assigned salesman), price\_list, price\_list\_line, setting (tolerance, factory GSTIN and state)
- **Production:** bom, bom\_line, production\_run, run\_line (planned, issued, actual), run\_output, run\_overhead, run\_variance\_snapshot
- **Inventory:** stock\_ledger, stock\_balance, stock\_adjustment, purchase, purchase\_line
- **Sales:** order, order\_line (client\_uuid for idempotency), invoice, invoice\_line, invoice\_sequence, credit\_note, dispatch, dispatch\_line
- **Money:** payment, payment\_allocation
- **Cross-cutting:** audit\_log

## 6. Benchmark ground truth and traps

| Check | Expected | Note |
| --- | --- | --- |
| Flour closing | 120 kg | 100 + 60 − 40 |
| Oil closing | 19.5 L | 30 − 10.5 |
| Spice mix closing | 3.8 kg | not in the PDF table |
| Pouches closing | 306 | 500 − 188 − 6 |
| Cartons closing | 21 | 30 − 9 |
| Finished goods after run | 238 | 50 + 188 |
| Finished goods after Retailer A | 88 | 238 − 150 |
| Yield variance | −6%, flagged | 188 vs 200 |
| Oil variance | +5%, flagged | 10.5 vs 10 |
| Pouch variance | −3%, not flagged | boundary case, state your rule |
| Carton variance | −10%, flagged (favourable) | 9 vs 10 |
| Retailer A invoice | 7,500 + 187.50 + 187.50 = 7,875 | CGST + SGST |
| Retailer A outstanding | 3,875 | 7,875 − 4,000 |
| Distributor B | shortage 32 (88 available vs 120) | IGST on 6,000 = 300, total 6,300 if invoiced |

**Cost per packet depends on the valuation method** (overheads ₹1,800, 188 good packets, selling price ₹50):

| Method | Flour cost | Run total | Per packet | Margin |
| --- | --- | --- | --- | --- |
| Weighted average (chosen) | 1,725 | 5,855 | ₹31.14 | ₹18.86 (37.7%) |
| FIFO | 1,680 | 5,810 | ₹30.90 | ₹19.10 (38.2%) |
| Last price | 1,800 | 5,930 | ₹31.54 | ₹18.46 (36.9%) |

**Assumptions to write in the README:**

1. A damaged pouch means one scrapped packet; the 12-packet yield gap is 6 damaged plus 6 unexplained.
2. Cartons: 9 used holds 180 packets, 8 stay loose. FG is tracked in packets.
3. Variance flags use strictly greater than the tolerance, both directions.
4. Purchase is recorded before the issue, so weighted-average flour is ₹43.125 at issue.
5. HSN code for murukku and namkeen is an assumption (verify the code you use); GST fixed at 5% for the exercise.
6. Financial year 2026-27; invoice dates default to today.
7. Overheads are absorbed by good packets only.

## 7. Phased plan (about 21 working days; scale to the real deadline, which the PDF leaves blank)

### Phase 0: Foundations (Day 1)

- **Build:** monorepo (`backend`, `frontend`, `docs`), Docker Compose, Makefile, CONVENTIONS.md (Decimal only, services own mutations, thin views), Django apps (accounts, masters, inventory, production, sales, billing, payments, costing, reports, audit, benchmark), GitHub Actions with security scans, feature → dev → main branching, conventional commits.
- **Commit discipline:** small commits daily on feature branches, no squash, 60–100 commits total. A single 'final upload' commit counts against you.
- **Exit gate:** `docker compose up` shows a login page; CI is green.

### Phase 1: Masters, units and ledger core (Days 2–3)

- **Build:** item, uom and conversions, supplier, customer, price list, settings; five roles and seed users; `post_movement()` service with locking, CHECK qty >= 0 and the append-only trigger; opening balances as ledger rows; stock adjustments with reason; stock summary and ledger API; `seed_benchmark` command (idempotent, `--reset`) loading the Section 5 master data.
- **Tests:** unit conversion, ledger invariants, balance = SUM(ledger), concurrent issue.
- **Exit gate:** stock summary shows the Section 5 opening balances exactly.

### Phase 2: Production loop (Days 4–6), highest weight

- **Build:** versioned BOM; purchases that create receipts and update the weighted average; production run state machine (DRAFT, ISSUED, COMPLETED) with planned lines auto-computed from batch count; issue editable per line; completion records good packets, damaged pouches and cartons used; ledger issues and FG receipt posted automatically; variance engine (pure function) plus stored snapshot; amend flow that posts reversing entries and is audit-logged.
- **UI:** tablet-friendly run screen with big numeric inputs and live variance chips as the supervisor types.
- **Write now:** `test_benchmark_end_to_end` for steps 1–3 (then extend each phase).
- **Exit gate:** flour 120 kg, oil 19.5 L, pouches 306, FG 238, yield −6% and oil +5% flagged, all in pytest. Deploy a first hosted build now so deployment is never a last-day surprise.

### Phase 3: Sales loop (Days 7–10)

- **Build:** price resolution (customer price, then price list), snapshotted on the order line; order state machine SUBMITTED, APPROVED, REJECTED, INVOICED, DISPATCHED (partial dispatch if cheap); idempotent order POST.
- **Salesman mobile UI:** customer search with recents, product steppers, cart, submit; My Orders with status timeline; customer-wise sales this month. Playwright test that places an order in under 60 seconds.
- **Admin UI:** order inbox, live stock-coverage chip per line, edit quantity or price (audit-logged), approve or reject with reason. Insufficient stock: show shortage (32), show an IGST preview for the interstate order, offer Reduce to available, Hold for production, or Reject; hard-block dispatch beyond stock.
- **Invoice:** place of supply, CGST/SGST or IGST, per-FY numbering, amount in words, PDF via WeasyPrint, WhatsApp link (`wa.me` with a signed expiring PDF URL) and mailto.
- **Dispatch and credit notes:** dispatch posts FG ledger issues; cancellation by credit note with optional restock.
- **Payments:** record and allocate against invoices; customer outstanding; ageing buckets 0–30, 31–60, 61–90, 90+.
- **Exit gate:** steps 4–7 give ₹7,875 invoice, FG 88, shortage 32, outstanding ₹3,875.

### Phase 4: Costing (Day 11)

- **Build:** overhead entries per run and per month; allocation rule from Section 4; run cost sheet; FG weighted-average cost; cost per packet and margin vs selling price.
- **Exit gate:** step 8 shows ₹31.14 and the design note carries the three-method comparison table.

### Phase 5: Reports, exports and dashboard (Days 12–13)

- **Build:** a report framework (query function, column metadata, renderers for JSON, Excel, CSV and PDF, date-range filter). Reports: sales register, customer-wise and product-wise sales, GST summary shaped like GSTR-1 (B2B, B2C, HSN summary, credit notes, documents issued) with a GSTR-3B outward-supply total, purchase register, stock summary and ledger (raw, packaging, FG), production report, collections and outstanding with ageing.
- **Reconciliation ticks:** stock summary closing = ledger sum; sales register taxable total = GST summary taxable total. Auditors will like these.
- **Owner dashboard:** today's orders, stock levels with reorder lines, variance alerts, cost per packet, outstanding dues. Accountant role is strictly read-only.
- **Exit gate (tag `v0.1`):** step 9 complete and the full benchmark test is green. Freeze the must-haves.

### Phase 6: The USP (Days 14–16)

- **6a Benchmark Console (0.5 day):** scenario as data, runner through the real services, check table, CLI and CI job, admin-only Reset and Run button.
- **6b Leakage Radar (1.5 days):** standard-cost snapshot, Run Report Card with price, usage and yield decomposition, bridge chart, unexplained-yield metric, sparklines, drift rule, Leakage-this-month tile.
- **6c Loop Closer (1 day):** batch-need maths on realised yield, feasibility and limiting item, draft purchase list, one-click planned run.
- **Exit gate:** console shows all green, the report card numbers match Section 2.1.

### Phase 7: Offline PWA and small wins (Days 17–18)

- **Offline orders:** precache the app shell; cache customers, products and prices in IndexedDB with a version stamp; outbox queue; idempotent retry using `client_uuid`; sync on the `online` event plus Background Sync where supported; 'Pending (n)' badge and Sync now button; admin sees a flag if the price list changed since the order was taken. Test with DevTools offline and a Playwright offline test.
- **Low-stock alerts:** reorder level per raw item, dashboard widget (about 2 hours).
- **Tamil UI for the production screen:** react-i18next, about 40 strings (about 3 hours; you have done English and Malayalam before).
- **Optional if time remains:** batch number and expiry on FG only, with first-expiry-first-out on dispatch.
- **Skip:** GPS check-in, e-invoice mock, Tally export.

### Phase 8: Hardening and submission (Days 19–21)

- Fresh-clone test on a clean machine: `docker compose up`, seed, `make benchmark`, `make test`.
- README (see Section 10), design note of at most 2 pages (Mermaid ER diagram, stock and BOM computation, valuation and overhead rule), benchmark table with explanations.
- Record the demo video in segments (Section 9), rehearse twice, upload as unlisted.
- Final checks: test logins for all five roles in the README, hosted link alive (watch free-tier cold starts), no secrets in the repo.

## 8. Testing strategy

- **Stock maths:** unit conversion, weighted-average rounding remainder, balance = SUM(ledger), no negative stock, concurrent dispatch.
- **Tax maths:** intra vs inter state, per-line rounding, round-off, FY rollover at 1 April, invoice number length, credit-note numbering.
- **Variance:** flagged and unflagged cases, including the exact −3.0% boundary and zero planned quantity.
- **Security:** role × endpoint matrix; salesman cannot read another salesman's orders.
- **Integration:** `test_benchmark_end_to_end` asserts every row of Section 6.
- **End to end:** Playwright, salesman order in under 60 seconds, offline queue and sync.

## 9. Demo video script (8:00 hard cap)

| Time | Content |
| --- | --- |
| 0:00–0:30 | One diagram: two loops meeting at finished goods; the Leakage Radar pitch in one sentence |
| 0:30–1:15 | Seed state: roles, opening stock summary |
| 1:15–2:00 | Step 1: purchase of 60 kg flour; ledger row and new weighted average |
| 2:00–3:20 | Steps 2–3: issue, actual output, flagged chips, Run Report Card with the bridge |
| 3:20–4:50 | Steps 4–5: salesman on phone (flip offline for 5 seconds), admin approves, invoice PDF, dispatch, FG 88 |
| 4:50–5:40 | Step 6: Distributor B shortage, IGST preview, Loop Closer suggests 1 batch |
| 5:40–6:10 | Step 7: payment, outstanding ₹3,875 |
| 6:10–6:50 | Step 8: overheads, cost per packet ₹31.14 and margin |
| 6:50–7:40 | Step 9: reports, ledger trace to source document, GST summary, Excel export, reconciliation ticks |
| 7:40–8:00 | Benchmark Console all green; repo and live link |

## 10. Checklists, interview prep and cut list

**README sections:** overview and screenshots; one-command run; test logins table; stack and why; feature matrix by tier (must, should, stretch) with honest status; assumptions (Section 6); known gaps; benchmark results table (expected, actual, notes); links to design note and video; repo map.

**Design note outline (2 pages):** ER diagram; how stock is computed from the ledger; BOM consumption algorithm; valuation and overhead rule with the benchmark worked example; variance and GST logic.

**Likely live changes and questions:** add a 500 g pack sharing the BOM; switch valuation to FIFO; add a second GST rate; why a ledger and not an overwritten balance; how two dispatches are kept from overselling; what happens to history if the BOM changes mid-month; how a posted invoice is corrected.

**If time runs short, cut in this order:** Tamil UI, drift alerts, Loop Closer purchase list, low-stock alerts, full offline sync (keep the installable PWA with a simple queue). Never cut: the benchmark test, ledger integrity, GST invoice, variance flags, RBAC, seed data, the README and the video.
