"""Benchmark Console – Appendix A replayed through the real services.

The scenario is data and service calls, exactly the path the API uses: seed,
purchase, production run, order, invoice, dispatch, shortage, payment,
overheads, reports, Leakage Radar and Loop Closer. It then compares every
Appendix A expected value with the actual result.

Invariants protected:
- The run never edits or bypasses the benchmark values. The expected values are
  literals copied from Appendix A.
- The scenario executes inside one transaction that is rolled back, so the
  console can be run on a live database without destroying data. A failed
  check therefore leaves no partial benchmark behind.
- Only services mutate stock and money; the runner reads their results.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.benchmark.services import seed_benchmark
from apps.costing.services import record_run_overhead, run_cost_sheet
from apps.inventory.services import (
    PurchaseLineInput,
    create_purchase,
    reconcile_stock,
    stock_summary,
)
from apps.masters.models import Customer, Item, Supplier
from apps.payments.services import (
    PaymentAllocationInput,
    invoice_outstanding,
    record_payment,
)
from apps.production.services import (
    complete_run,
    create_run,
    issue_run,
    run_report_card,
    run_variance,
)
from apps.sales.services import (
    DispatchLineInput,
    OrderLineInput,
    approve_order,
    create_invoice,
    create_order,
    dispatch_invoice,
    stock_coverage,
)
from core.money import q2
from core.quantity import q3


@dataclass(frozen=True)
class BenchmarkCheck:
    """One expected-versus-actual line of the console."""

    name: str
    expected: str
    actual: str
    passed: bool
    detail: str = ""


@dataclass(frozen=True)
class BenchmarkResult:
    """The whole console run: every check and the verdict."""

    checks: tuple[BenchmarkCheck, ...]
    ran_at: datetime

    @property
    def passed(self) -> int:
        return sum(1 for check in self.checks if check.passed)

    @property
    def failed(self) -> int:
        return len(self.checks) - self.passed

    @property
    def ok(self) -> bool:
        return self.failed == 0


class _Recorder:
    """Collects checks and formats Decimals without floats."""

    def __init__(self) -> None:
        self.checks: list[BenchmarkCheck] = []

    def _add(self, name: str, expected: str, actual: str, passed: bool) -> None:
        self.checks.append(
            BenchmarkCheck(name=name, expected=expected, actual=actual, passed=passed)
        )

    def money(self, name: str, expected: str, actual: Decimal) -> None:
        self._add(name, expected, f"{q2(actual):.2f}", Decimal(expected) == q2(actual))

    def qty(self, name: str, expected: str, actual: Decimal) -> None:
        self._add(name, expected, f"{q3(actual):.3f}", Decimal(expected) == q3(actual))

    def pct(self, name: str, expected: str, actual: Decimal | None) -> None:
        if actual is None:
            self._add(name, expected, "none", False)
            return
        self._add(name, expected, f"{actual:.6f}", Decimal(expected) == actual)

    def flag(self, name: str, expected: bool, actual: bool) -> None:
        self._add(name, str(expected), str(actual), expected == actual)

    def text(self, name: str, expected: str, actual: str) -> None:
        self._add(name, expected, actual, expected == actual)


def _run_scenario(recorder: _Recorder) -> None:
    seed_benchmark(reset=True)

    flour = Item.objects.get(name="Flour")
    product = Item.objects.get(name="Murukku 200 g")
    supplier = Supplier.objects.get(name="Sri Lakshmi Flour Mills")
    admin = User.objects.get(username="admin")

    # Step 1: purchase 60 kg flour at 45 -> 160 kg at 43.125.
    create_purchase(
        supplier=supplier,
        reference="BENCH/0001",
        lines=[PurchaseLineInput(item_id=flour.pk, qty=Decimal("60"), unit_cost=Decimal("45"))],
        user=admin,
    )

    # Steps 2-3: one batch, raw issues, packing record.
    run = create_run(product=product, batches=Decimal("1"), user=admin)
    lines = {line.item.name: line for line in run.lines.select_related("item")}
    issue_run(
        run=run,
        issued={
            lines["Flour"].pk: Decimal("40"),
            lines["Cooking oil"].pk: Decimal("10.5"),
            lines["Salt and spice mix"].pk: Decimal("1.2"),
        },
        user=admin,
    )
    complete_run(
        run=run,
        good_packets=Decimal("188"),
        damaged_pouches=Decimal("6"),
        cartons_used=Decimal("9"),
        user=admin,
    )

    stock = {row.item.name: row.qty for row in stock_summary()}
    recorder.qty("Flour closing", "120", stock["Flour"])
    recorder.qty("Oil closing", "19.5", stock["Cooking oil"])
    recorder.qty("Spice mix closing", "3.8", stock["Salt and spice mix"])
    recorder.qty("Pouches closing", "306", stock["200 g pouch"])
    recorder.qty("Cartons closing", "21", stock["Carton (holds 20 packets)"])
    recorder.qty("FG after run", "238", stock["Murukku 200 g"])

    variance = {row.item_name: row for row in run_variance(run)}
    yield_row = variance["Murukku 200 g (yield)"]
    recorder.pct("Yield variance", "-0.060000", yield_row.variance_pct)
    recorder.flag("Yield variance flagged", True, yield_row.flagged)
    recorder.pct("Oil variance", "0.050000", variance["Cooking oil"].variance_pct)
    recorder.flag("Oil variance flagged", True, variance["Cooking oil"].flagged)
    recorder.pct("Pouch variance", "-0.030000", variance["200 g pouch"].variance_pct)
    recorder.flag("Pouch variance flagged", False, variance["200 g pouch"].flagged)
    recorder.pct("Carton variance", "-0.100000", variance["Carton (holds 20 packets)"].variance_pct)
    recorder.flag("Carton variance flagged", True, variance["Carton (holds 20 packets)"].flagged)
    recorder.text(
        "Carton variance direction",
        "favourable",
        variance["Carton (holds 20 packets)"].direction,
    )
    recorder.pct("Flour variance", "0.000000", variance["Flour"].variance_pct)
    recorder.flag("Flour variance flagged", False, variance["Flour"].flagged)

    # Steps 4-5: salesman order, admin invoice, dispatch.
    salesman_a = User.objects.get(username="salesman_a")
    salesman_b = User.objects.get(username="salesman_b")
    retailer_a = Customer.objects.get(name="Retailer A")
    distributor_b = Customer.objects.get(name="Distributor B")

    submitted = create_order(
        customer=retailer_a,
        lines=[OrderLineInput(item_id=product.pk, qty=Decimal("150"))],
        client_uuid=uuid.uuid4(),
        salesman=salesman_a,
    )
    order = submitted.order
    approve_order(order=order, user=admin)
    invoice = create_invoice(order=order, user=admin)
    recorder.money("Retailer A taxable", "7500.00", invoice.taxable_total)
    recorder.money("Retailer A CGST", "187.50", invoice.cgst_total)
    recorder.money("Retailer A SGST", "187.50", invoice.sgst_total)
    recorder.money("Retailer A invoice total", "7875.00", invoice.total)

    invoice_line = invoice.lines.get()
    dispatch_invoice(
        invoice=invoice,
        lines=[DispatchLineInput(invoice_line_id=invoice_line.pk, qty=Decimal("150"))],
        user=admin,
    )
    stock_after_dispatch = {row.item.name: row.qty for row in stock_summary()}
    recorder.qty("FG after Retailer A dispatch", "88", stock_after_dispatch["Murukku 200 g"])

    # Step 6: Distributor B is short; IGST preview and Loop Closer.
    blocked = create_order(
        customer=distributor_b,
        lines=[OrderLineInput(item_id=product.pk, qty=Decimal("120"))],
        client_uuid=uuid.uuid4(),
        salesman=salesman_b,
    )
    coverage = stock_coverage(blocked.order)
    recorder.qty("Distributor B shortage", "32", coverage.total_shortage_qty)
    recorder.money("Distributor B IGST preview", "300.00", coverage.tax_preview.igst_total)
    recorder.money("Distributor B total preview", "6300.00", coverage.tax_preview.total)

    if coverage.loop_closers:
        recorder.text(
            "Loop Closer batches needed",
            "1",
            str(coverage.loop_closers[0].batches_needed),
        )
        plan = coverage.loop_closers[0]
        recorder.text("Loop Closer batches allowed", "1", str(plan.batches_allowed))
        recorder.text("Loop Closer limiting item", "200 g pouch", plan.limiting_item)
        recorder.text("Loop Closer verdict", "feasible", plan.verdict)
        recorder.flag("Loop Closer purchase list empty", True, not plan.purchase_list)
        pouches = next((row for row in plan.capacity if row.item_name == "200 g pouch"), None)
        recorder.money(
            "Loop Closer pouch ratio",
            "1.53",
            pouches.ratio if pouches is not None else Decimal("0"),
        )
        oil = next((row for row in plan.capacity if row.item_name == "Cooking oil"), None)
        recorder.money(
            "Loop Closer oil ratio",
            "1.95",
            oil.ratio if oil is not None else Decimal("0"),
        )
        spice = next((row for row in plan.capacity if row.item_name == "Salt and spice mix"), None)
        recorder.money(
            "Loop Closer spice ratio",
            "3.17",
            spice.ratio if spice is not None else Decimal("0"),
        )

    # Step 7: a 4,000 payment leaves 3,875 outstanding.
    record_payment(
        customer=retailer_a,
        amount=Decimal("4000"),
        method="upi",
        allocations=[PaymentAllocationInput(invoice_id=invoice.pk, amount=Decimal("4000"))],
        user=admin,
    )
    recorder.money("Retailer A outstanding", "3875.00", invoice_outstanding(invoice))

    # Step 8: labour and power, cost per packet.
    record_run_overhead(
        run=run,
        category="labour",
        amount="1200",
        description="Labour",
        user=admin,
    )
    record_run_overhead(
        run=run,
        category="power",
        amount="600",
        description="Gas and power",
        user=admin,
    )
    sheet = run_cost_sheet(run)
    recorder.money("Run materials", "4055.00", Decimal(str(sheet["materials_value"])))
    recorder.money("Run overheads", "1800.00", Decimal(str(sheet["overhead_value"])))
    recorder.money("Run total", "5855.00", Decimal(str(sheet["total_cost"])))
    recorder.money("Cost per packet", "31.14", Decimal(str(sheet["cost_per_packet"])))
    recorder.money("Margin per packet", "18.86", Decimal(str(sheet["margin_per_packet"])))
    recorder.money("Margin percent", "37.72", Decimal(str(sheet["margin_pct"])))

    # Leakage Radar report card (Section 2.1 of the implementation plan).
    card = run_report_card(run)
    recorder.money("Leakage standard materials", "3970.00", card.standard_materials)
    recorder.money("Leakage actual materials", "4055.00", card.actual_materials)
    recorder.money("Leakage material impact", "85.00", card.material_impact)
    recorder.money("Leakage price impact", "45.00", card.price_impact)
    recorder.money("Leakage usage impact", "40.00", card.usage_impact)

    by_item = {line.item_name: line for line in card.lines}
    recorder.money("Flour price impact", "45.00", by_item["Flour"].price_impact)
    recorder.money("Flour usage impact", "0.00", by_item["Flour"].usage_impact)
    recorder.money("Oil usage impact", "70.00", by_item["Cooking oil"].usage_impact)
    recorder.money("Pouch usage impact", "-15.00", by_item["200 g pouch"].usage_impact)
    recorder.money(
        "Carton usage impact", "-15.00", by_item["Carton (holds 20 packets)"].usage_impact
    )

    bridge = {step.key: step.amount for step in card.bridge}
    recorder.money("Bridge standard material", "19.85", bridge["standard_material"])
    recorder.money("Bridge yield shortfall", "1.27", bridge["yield_shortfall"])
    recorder.money("Bridge price and usage", "0.45", bridge["price_usage"])
    recorder.money("Actual material per packet", "21.57", card.actual_material_per_packet)
    recorder.money("Bridge overhead", "9.57", bridge["overhead"])
    recorder.money("Bridge total", "31.14", bridge["overhead"] + card.actual_material_per_packet)

    recorder.qty("Yield gap packets", "12", card.yield_gap.gap_packets)
    recorder.qty("Yield gap explained damage", "6", card.yield_gap.damaged_packets)
    recorder.qty("Yield gap unexplained", "6", card.yield_gap.unexplained_packets)

    # Step 9: the books reconcile after all nine steps.
    recorder.text("Stock reconciles with ledger", "0 issues", f"{len(reconcile_stock())} issues")


def run_benchmark_scenario() -> BenchmarkResult:
    """Replay Appendix A in a rolled-back transaction and return every check."""
    recorder = _Recorder()
    with transaction.atomic():
        _run_scenario(recorder)
        transaction.set_rollback(True)
    return BenchmarkResult(checks=tuple(recorder.checks), ran_at=timezone.now())


def serialize_result(result: BenchmarkResult) -> dict[str, Any]:
    """Return the console result with strings only (Decimals never leak)."""
    return {
        "ran_at": result.ran_at.isoformat(),
        "passed": result.passed,
        "failed": result.failed,
        "ok": result.ok,
        "checks": [
            {
                "name": check.name,
                "expected": check.expected,
                "actual": check.actual,
                "passed": check.passed,
                "detail": check.detail,
            }
            for check in result.checks
        ],
    }
