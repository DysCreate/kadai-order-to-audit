# Kadai – System Design

## Overview

Kadai models the operations of a small South Indian snack factory. Two business loops share a single finished-goods (FG) stock ledger as their meeting point.

---

## Two-Loop Architecture

```
  PRODUCTION LOOP                    SALES LOOP
  ─────────────                      ──────────
  Purchase raw materials             Salesman creates order
       │                                   │
  Raw-material stock ledger          Admin approves + verifies stock
       │                                   │
  Issue against BOM                  Raise GST invoice
       │                                   │
  Production run                     Dispatch (FG out)
       │                                   │
  FG stock ledger ◄──────────────────────► FG stock ledger
  (RECEIPT: FG goes up)              (ISSUE: FG goes down)
       │                                   │
  Variance snapshot                  Payment / outstanding
  Cost per packet                    Credit note if needed
```

The two loops are independent except at FG stock. All stock movements — purchases, issues, production receipts, dispatches, adjustments, and opening balances — pass through the same `stock_ledger` table.

---

## Ledger-First Design

### Why append-only?

Mutable stock records allow silent history rewriting. An append-only ledger:

- Provides a complete, tamper-evident audit trail.
- Lets any balance be recomputed at any point in time by summing rows.
- Makes concurrency simple: inserts never conflict with reads of past rows.
- Enables reversals (credit notes, adjustments) without destroying evidence.

A database trigger enforces the constraint: `UPDATE` and `DELETE` on `stock_ledger` raise an exception at the database level, not just the application level.

`stock_balance` is a denormalised cache. It is updated in the same transaction as the ledger insert, under a row-level lock (selected in ascending `item_id` order to prevent deadlocks), and carries a `CHECK (qty >= 0)` constraint. The invariant `stock_balance.qty == SUM(stock_ledger.qty WHERE item_id = ?)` is verified by `make reconcile`.

Every ledger row carries:

| Column | Purpose |
|--------|---------|
| `item_id` | Which item |
| `movement_type` | OPENING / RECEIPT / ISSUE / ADJUSTMENT |
| `source_type` | purchase / production_run / dispatch / credit_note / adjustment / opening |
| `source_id` | FK to the source document |
| `qty` | Positive for in, negative for out (base UoM) |
| `unit_value` | Weighted-average value at the time of movement |
| `created_at` | UTC timestamp |

---

## Valuation: Moving Weighted Average

The default valuation method is **moving weighted average (MWA)**:

```
new_avg = (old_qty * old_avg + receipt_qty * receipt_price) / (old_qty + receipt_qty)
issue_value = q2(issue_qty * current_avg)
```

The remainder invariant: when all stock is issued, value is exactly zero (the last issue takes the full remaining value, not `issue_qty * avg` which could leave a rounding residual).

The valuation logic lives in a strategy class so FIFO can be substituted without changing callers:

```python
class ValuationStrategy(Protocol):
    def on_receipt(self, item_id, qty, unit_price, tx): ...
    def on_issue(self, item_id, qty, tx) -> Decimal: ...

class MovingWeightedAverage(ValuationStrategy): ...
class FIFO(ValuationStrategy): ...  # future
```

---

## Variance Engine

Variance is computed **once** at production run completion and stored as a snapshot. Later BOM edits do not alter past runs.

For each BOM line:

```
variance_pct = (actual - planned) / planned   (planned must be non-zero)
flagged = abs(variance_pct) > tolerance        # strictly greater than
direction = "favourable" if actual < planned (for costs) else "adverse"
```

Tolerance is loaded from settings (default 3 %). Zero planned quantity is a special case: any non-zero actual is flagged with direction `adverse`.

**Appendix A boundary cases:**

| Input | Planned | Actual | % | Flagged? |
|-------|---------|--------|---|---------|
| Pouch | 200 | 194 | −3% | **No** (not strictly > 3%) |
| Carton | 10 | 9 | −10% | Yes (favourable) |
| Oil | 10 L | 10.5 L | +5% | Yes (adverse) |
| Yield | 200 | 188 | −6% | Yes (adverse) |

---

## GST Logic

Place of supply is determined by comparing the customer's state code to the factory state code (Tamil Nadu = 33).

| Scenario | Tax applied |
|----------|------------|
| Same state (intra) | CGST + SGST, each = rate / 2 |
| Different state (inter) | IGST = rate |

Tax is calculated **per line**, rounded to the nearest paise using `q2()` (ROUND_HALF_UP). A `round_off` line shows the net rounding difference on the invoice total.

Invoice numbering:
- Format: `INV/YY-YY/00001` (max 16 characters)
- Financial year starts 1 April, computed in `Asia/Kolkata`, stored in UTC
- Counter is taken under a row lock to prevent duplicate numbers under concurrent requests

Invoices are immutable once posted (database trigger). Corrections use credit notes (`CN/YY-YY/00001`).

---

## GST Example (Appendix A)

Retailer A (Tamil Nadu, intra-state), 150 packets at ₹50, GST 5%:

```
Taxable value  = 150 × 50          = 7,500.00
CGST (2.5%)    = q2(7500 × 0.025)  =   187.50
SGST (2.5%)    = q2(7500 × 0.025)  =   187.50
Invoice total                       = 7,875.00
```

Distributor B (Karnataka, inter-state), 120 packets at ₹50, GST 5% (preview only — stock insufficient):

```
Taxable value  = 120 × 50          = 6,000.00
IGST (5%)      = q2(6000 × 0.05)   =   300.00
Invoice total                       = 6,300.00
```

---

## Sales Loop

### Order lifecycle

```
SUBMITTED ──approve──► APPROVED ──invoice──► INVOICED ──dispatch──► DISPATCHED
     └─────reject────► REJECTED
```

- `POST /api/sales/orders/` is idempotent per device-generated `client_uuid`.
  A retry with the same customer and salesman returns the existing order.
- The salesman's price is resolved from the customer's price list, then the
  default list, and snapshotted on the order line. A later price-list change
  never rewrites an existing order or invoice.
- A salesman may only order for a customer assigned to them; the check is in
  the service, so the API refuses even if the UI is bypassed.
- Admin verification may edit a line's quantity or price while the order is
  `SUBMITTED`; the edit writes a before/after `audit_log` row.
- Stock coverage per line = on-hand − commitments to other approved orders and
  undispatched invoices. Approval does not block on a shortage (the admin may
  hold for production); dispatch is the hard gate.

### GST invoice

- Place of supply = customer state vs factory state (`33` from settings).
- Same state: CGST and SGST at half the item's rate each. Different: IGST.
- Each line's taxable value and tax are rounded once to paise with
  `q2()`/ROUND_HALF_UP. The invoice total is exactly `taxable + tax`; the
  `round_off` column reports the accumulated per-line rounding as a memo.
- Numbering: `INV/26-27/00001`, from a per-financial-year counter row locked
  with `SELECT … FOR UPDATE`. The financial year starts 1 April and is computed
  in `Asia/Kolkata`. Credit notes use `CN/26-27/00001`; orders use `ORD/…`.
- A posted invoice and its lines are immutable: migration `sales/0002` installs
  a trigger that rejects UPDATE and DELETE.
- The PDF is rendered by WeasyPrint from `sales/invoice.html`. A shared link is
  a Django-signed invoice id with a seven-day expiry, so the customer needs no
  session. WhatsApp and mailto links wrap that URL.

### Dispatch and credit notes

- Dispatch is append-only: `Dispatch` + `DispatchLine`, then finished-goods
  `ISSUE` ledger rows sourced to the dispatch. Dispatched and credited
  quantities are derived by summing those lines, so the invoice is untouched.
- A partial dispatch leaves the order `INVOICED`; the order becomes
  `DISPATCHED` only when every invoice line is fully dispatched or credited.
- A credit note carries its own tax split and number series. Crediting every
  line makes the invoice count as cancelled (derived, never stored). Restock is
  optional and posts a finished-goods `RECEIPT` sourced to the credit note at
  the current weighted-average cost.

### Payments and ageing

- A payment is positive and may be partly unallocated (an advance).
- Allocations are unique per (payment, invoice), locked while checked, and can
  never exceed the invoice's outstanding balance. A cancelled invoice cannot
  receive money.
- `outstanding = invoice total − credit notes − allocations`.
- Ageing buckets the outstanding balance by invoice date: 0–30, 31–60, 61–90,
  90+ days. The customer ledger returns invoices, payments, outstanding and the
  buckets in one result.

---

## Costing

### Run and monthly overheads

`costing_overhead_entry` carries either a `RUN` scope with a production-run
foreign key or a `MONTH` scope with a first-of-month `period`; a database check
constraint enforces exactly one owner. Amounts are positive NUMERIC(14,2).

A run overhead is accepted only for a `COMPLETED` run. It is assigned fully to
that run and reaches finished-goods value through
`inventory.services.post_value_adjustment`: an append-only `ADJUSTMENT` ledger
row with `qty = 0` and a positive value, posted under the balance-row lock. The
balance keeps its packet count and gains the overhead value, so the ledger and
balance still reconcile. A zero-quantity FG balance is refused rather than
carrying value with no stock.

### Monthly pool allocation

A monthly pool is allocated once per entry across the runs completed in that
calendar month in `Asia/Kolkata`. Each run's weight is
`batches × product.standard_batch_hours` (default one hour per batch). The split
uses a largest-remainder calculation in paise, so the shares sum exactly to the
entry and no rupee is lost. `costing_overhead_allocation` is unique per
(entry, run), and re-running the allocation returns the existing rows without
posting a second value adjustment.

### Cost sheet

For a completed run:

```
materials = net value of the run's input ledger rows (issues minus returns)
overheads = run overheads + monthly allocations
total = materials + overheads
cost per good packet = total / good packets
margin = default selling price - cost per good packet
```

The cost sheet also reports the current FG balance and its weighted-average
cost. That stock cost can differ from the run cost because opening FG was
valued at standard material cost, dispatches remove value at the running
average, and overheads are added after the FG receipt. Both views are shown
rather than forcing one to equal the other.

### Valuation methods (reference only)

The chosen method is moving weighted average. The other columns document what
the benchmark would show under alternatives; they are not implemented.

| Method | Flour cost | Run total | Per packet | Margin at ₹50 |
| --- | --- | --- | --- | --- |
| Weighted average (chosen) | 1,725.00 | 5,855.00 | 31.14 | 18.86 (37.7%) |
| FIFO | 1,680.00 | 5,810.00 | 30.90 | 19.10 (38.2%) |
| Last price | 1,800.00 | 5,930.00 | 31.54 | 18.46 (36.9%) |

---

## Assumptions (from Appendix A)

| # | Assumption |
|---|-----------|
| A1 | Opening FG (50 packets) is valued at standard material cost: ₹19.85/packet (3,970 / 200). |
| A2 | Flour weighted-average rate: (100 × 42 + 60 × 45) / 160 = 43.125 ₹/kg. |
| A3 | Variance tolerance is 3%. The boundary is strictly greater than — 3% exactly is not flagged. |
| A4 | Production run records 6 damaged pouches as actual usage, contributing to the pouch count. |
| A5 | Cost per good packet = run total cost / good packets (188), not total output. |
| A6 | Leakage Radar uses standard BOM rates (not current weighted-average) as the benchmark. |
| A7 | Loop Closer trailing yield factor = 0.94 (188 / 200). |
| A8 | Financial year starts 1 April; all timestamps stored in UTC, displayed in Asia/Kolkata. |
| A9 | Factory state: Tamil Nadu (code 33). |
| A10 | Approval does not block on stock; dispatch is the hard gate, so an order can be held for production. |
| A11 | Invoice cancellation is derived from credit notes covering every line; invoices are never updated. |
| A12 | Round-off is a memo of per-line paise rounding; the total always equals taxable + tax. |
| A13 | Credit-note restock is valued at the current weighted-average cost (zero when stock is empty). |
| A14 | Payments are explicitly allocated; unallocated money is an advance. Ageing buckets by invoice date. |
| A15 | Shared invoice PDF links are signed and expire after seven days. |
| A16 | Run overheads apply only to completed runs and post a value-only (`qty = 0`) ledger row; a zero FG balance is refused. |
| A17 | Monthly pools are allocated by `batches × standard_batch_hours` across completed runs in the Asia/Kolkata month, using a largest-remainder paise split; allocation is idempotent per entry and run. |
| A18 | Cost per good packet = (net materials + overheads) / good packets. FG weighted-average cost is a separate current-stock view. |
| A19 | Margin uses the default selling price; when no price is configured the margin is null. |
| A20 | Reports filter on business dates; the stock summary is live and ageing is as of the end date (today by default). |
| A21 | The sales register is gross: a fully credited invoice stays listed as cancelled. GST reconciliation compares gross invoice taxable totals; GSTR-3B outward supply is net of credit notes. |
| A22 | Dashboard reorder flags use one batch's BOM requirement for raw/packaging items and zero stock for finished goods, ahead of a reorder-level master field. |
| A23 | Dashboard "today" is the Asia/Kolkata business day; timestamps remain UTC. |
| A24 | Admin, production, accountant and owner may read reports; the salesman may not. The accountant stays read-only. |

---

## Reports and reconciliation

Reports are data first: each query returns a `ReportResult` (columns, rows,
totals, metadata) and the JSON response, CSV, Excel workbook and PDF are all
rendered from that one object. A downloaded file therefore cannot disagree
with the screen it came from. Money is always a `Decimal` formatted with two
places; the Excel renderer writes numeric cells, not strings.

The ten reports are the sales register, sales by customer, sales by product,
GST summary (GSTR-1 shaped: B2B, B2C, HSN, credit notes, documents issued),
purchase register, stock summary, stock ledger, production report, collections
and outstanding/ageing. Sales, purchases, collections, production and the
ledger filter on their business dates; the stock summary is a live balance and
ageing is "as of" a date.

```
GET /api/reports/<slug>/?date_from=2026-05-01&date_to=2026-05-31&format=csv
```

Three audit checks back `make reconcile`:

| Check | Expectation |
|-------|-------------|
| Stock | Every `stock_balance` equals its `SUM(stock_ledger)` |
| Invoice | Every invoice `total` equals the sum of its `line_total` |
| GST | Sales-register taxable total equals the GST summary taxable total |

The owner dashboard reads the same sources, never a second set of books:
today's orders (Asia/Kolkata day bounds), open orders, stock with reorder
flags, the last 30 days' flagged variance, the latest completed run's cost per
packet and total outstanding dues. A reorder flag means raw or packaging stock
is below one batch's BOM requirement; finished goods flag only at zero.

---

## Security & RBAC

Roles are enforced server-side, deny-by-default:

| Role | Can do |
|------|--------|
| salesman | Create/view own orders and assigned customers only |
| admin | Approve orders, raise invoices, dispatch, allocate monthly overheads, view all |
| production | Create/complete production runs, view BOM, record run and monthly overheads |
| accountant | Read-only across all modules |
| owner | Full access |

Frontend hiding is cosmetic; every API call is re-validated against the user's role.

---

## Concurrency

- `stock_balance` is locked with `SELECT … FOR UPDATE` before any mutation.
- Locks are acquired in ascending `item_id` order to prevent deadlocks.
- A `CHECK (qty >= 0)` constraint ensures the database rejects any race that would go negative.
- Invoice counters use a dedicated row lock to prevent duplicate numbering.
