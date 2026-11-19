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

---

## Security & RBAC

Roles are enforced server-side, deny-by-default:

| Role | Can do |
|------|--------|
| salesman | Create/view own orders and assigned customers only |
| admin | Approve orders, raise invoices, dispatch, view all |
| production | Create/complete production runs, view BOM |
| accountant | Read-only across all modules |
| owner | Full access |

Frontend hiding is cosmetic; every API call is re-validated against the user's role.

---

## Concurrency

- `stock_balance` is locked with `SELECT … FOR UPDATE` before any mutation.
- Locks are acquired in ascending `item_id` order to prevent deadlocks.
- A `CHECK (qty >= 0)` constraint ensures the database rejects any race that would go negative.
- Invoice counters use a dedicated row lock to prevent duplicate numbering.
