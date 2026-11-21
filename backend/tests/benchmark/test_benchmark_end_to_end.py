"""Benchmark ground truth for the production loop: Appendix A steps 1-3.

Requirement: Phase 2 exit gate – flour 120 kg, oil 19.5 L, spice mix 3.8 kg,
pouches 306, cartons 21, FG 238, yield -6% and oil +5% flagged, pouch -3% not
flagged, all replayed through the same services the API uses.

The expected values come from Appendix A and are never edited to make a test
pass.
"""

import uuid
from datetime import date
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.db.models import Sum

from apps.accounts.models import User
from apps.benchmark.services import seed_benchmark
from apps.costing.services import record_run_overhead, run_cost_sheet
from apps.inventory.models import MovementType, SourceType, StockBalance, StockLedger
from apps.inventory.services import (
    PurchaseLineInput,
    create_purchase,
    reconcile_stock,
    stock_summary,
)
from apps.masters.models import Customer, Item, Supplier
from apps.payments.services import PaymentAllocationInput, invoice_outstanding, record_payment
from apps.production.models import ProductionRun, RunState
from apps.production.services import complete_run, create_run, issue_run, run_variance
from apps.sales.models import OrderState
from apps.sales.services import (
    DispatchLineInput,
    OrderLineInput,
    approve_order,
    create_invoice,
    create_order,
    dispatch_invoice,
    stock_coverage,
)

EXPECTED_CLOSING = {
    "Flour": Decimal("120.000"),
    "Cooking oil": Decimal("19.500"),
    "Salt and spice mix": Decimal("3.800"),
    "200 g pouch": Decimal("306.000"),
    "Carton (holds 20 packets)": Decimal("21.000"),
    "Murukku 200 g": Decimal("238.000"),
}


@pytest.mark.django_db
def test_benchmark_steps_1_to_3_reproduce_appendix_a() -> None:
    """PS Appendix A steps 1-3: purchase, issue, complete, and every closing."""
    seed_benchmark()

    flour = Item.objects.get(name="Flour")
    product = Item.objects.get(name="Murukku 200 g")
    supplier = Supplier.objects.get(name="Sri Lakshmi Flour Mills")

    # --- Step 1: purchase 60 kg flour at 45 -------------------------------
    purchase = create_purchase(
        supplier=supplier,
        reference="SLFM/0187",
        lines=[PurchaseLineInput(item_id=flour.pk, qty=Decimal("60"), unit_cost=Decimal("45"))],
    )
    flour_balance = StockBalance.objects.get(item=flour)
    assert flour_balance.qty == Decimal("160.000")
    assert flour_balance.value == Decimal("6900.00")
    assert flour_balance.value / flour_balance.qty == Decimal("43.125")

    # --- Step 2: production run, 1 batch, issue raw materials --------------
    run = create_run(product=product, batches=Decimal("1"))
    assert run.planned_output_qty == Decimal("200.000")
    assert run.state == RunState.DRAFT

    lines = {line.item.name: line for line in run.lines.select_related("item")}
    issue_run(
        run=run,
        issued={
            lines["Flour"].pk: Decimal("40"),
            lines["Cooking oil"].pk: Decimal("10.5"),
            lines["Salt and spice mix"].pk: Decimal("1.2"),
        },
    )
    assert StockBalance.objects.get(item=flour).qty == Decimal("120.000")
    assert StockBalance.objects.get(item=Item.objects.get(name="Cooking oil")).qty == Decimal(
        "19.500"
    )

    # The 40 kg issue is valued at the weighted average: 40 x 43.125 = 1,725.
    flour_issue = StockLedger.objects.get(
        source_type=SourceType.PRODUCTION_RUN,
        source_id=run.pk,
        item=flour,
        movement_type=MovementType.ISSUE,
    )
    assert flour_issue.value == Decimal("-1725.00")
    assert flour_issue.unit_value == Decimal("43.1250")

    # --- Step 3: 188 good packets, 6 damaged pouches, 9 cartons ------------
    complete_run(run=run, good_packets=Decimal("188"), damaged_pouches="6", cartons_used="9")
    run.refresh_from_db()
    assert run.state == RunState.COMPLETED

    rows = {row.item.name: row for row in stock_summary()}
    for item_name, expected_qty in EXPECTED_CLOSING.items():
        assert rows[item_name].qty == expected_qty, item_name

    # Five inputs left stock; the finished-goods receipt is 188 packets valued
    # at the run's material cost (1,725 + 1,470 + 240 + 485 + 135 = 4,055).
    run_issues = StockLedger.objects.filter(
        source_type=SourceType.PRODUCTION_RUN,
        source_id=run.pk,
        movement_type=MovementType.ISSUE,
    )
    assert run_issues.count() == 5
    assert set(run_issues.values_list("item__name", flat=True)) == {
        "Flour",
        "Cooking oil",
        "Salt and spice mix",
        "200 g pouch",
        "Carton (holds 20 packets)",
    }

    fg_receipt = StockLedger.objects.get(
        source_type=SourceType.PRODUCTION_RUN,
        source_id=run.pk,
        item=product,
        movement_type=MovementType.RECEIPT,
    )
    assert fg_receipt.qty == Decimal("188.000")
    assert fg_receipt.value == Decimal("4055.00")

    materials = StockLedger.objects.filter(
        source_type=SourceType.PRODUCTION_RUN,
        source_id=run.pk,
        movement_type=MovementType.ISSUE,
    ).aggregate(total=Sum("value"))["total"]
    assert materials is not None
    assert -materials == Decimal("4055.00")

    # Purchases and runs stay traceable, and the ledger reconciles.
    assert (
        StockLedger.objects.filter(source_type=SourceType.PURCHASE, source_id=purchase.pk).count()
        == 1
    )
    assert reconcile_stock() == []


@pytest.mark.django_db
def test_benchmark_steps_1_to_3_variance_snapshot() -> None:
    """PS Appendix A: yield -6% and oil +5% flagged; pouch -3% is not."""
    seed_benchmark()
    flour = Item.objects.get(name="Flour")
    product = Item.objects.get(name="Murukku 200 g")

    create_purchase(
        supplier=Supplier.objects.get(name="Sri Lakshmi Flour Mills"),
        lines=[PurchaseLineInput(item_id=flour.pk, qty="60", unit_cost="45")],
    )

    run = create_run(product=product, batches="1")
    lines = {line.item.name: line for line in run.lines.select_related("item")}
    issue_run(
        run=run,
        issued={
            lines["Flour"].pk: "40",
            lines["Cooking oil"].pk: "10.5",
            lines["Salt and spice mix"].pk: "1.2",
        },
    )
    complete_run(run=run, good_packets="188", damaged_pouches="6", cartons_used="9")

    variance = {row.item_name: row for row in run_variance(run)}

    assert variance["Murukku 200 g (yield)"].flagged is True
    assert variance["Murukku 200 g (yield)"].variance_pct == Decimal("-0.060000")
    assert variance["Murukku 200 g (yield)"].direction == "adverse"

    assert variance["Cooking oil"].flagged is True
    assert variance["Cooking oil"].variance_pct == Decimal("0.050000")

    assert variance["200 g pouch"].variance_pct == Decimal("-0.030000")
    assert variance["200 g pouch"].flagged is False

    assert variance["Carton (holds 20 packets)"].flagged is True
    assert variance["Carton (holds 20 packets)"].direction == "favourable"

    assert variance["Flour"].variance_pct == Decimal("0.000000")
    assert variance["Flour"].flagged is False

    assert ProductionRun.objects.filter(pk=run.pk).exists()


@pytest.mark.django_db
def test_benchmark_seed_loads_the_bom() -> None:
    """PS 4.15: the seed loads exactly one BOM version, idempotently."""
    call_command("seed_benchmark", stdout=StringIO())
    seed_benchmark()

    product = Item.objects.get(name="Murukku 200 g")
    assert product.boms.count() == 1
    bom = product.boms.get()
    assert bom.version == 1
    assert bom.batch_output_qty == Decimal("200.000")
    assert {(line.item.name, line.qty_per_batch, line.role) for line in bom.lines.all()} == {
        ("Flour", Decimal("40.000"), "material"),
        ("Cooking oil", Decimal("10.000"), "material"),
        ("Salt and spice mix", Decimal("1.200"), "material"),
        ("200 g pouch", Decimal("200.000"), "pouch"),
        ("Carton (holds 20 packets)", Decimal("10.000"), "carton"),
    }


@pytest.mark.django_db
def test_benchmark_steps_4_to_8_sales_loop_and_costing() -> None:
    """PS Appendix A steps 4-8: invoice 7,875, FG 88, shortage 32, outstanding
    3,875, then labour and power bring the run cost to 5,855 and 31.14 per packet.

    The production steps run first because the sales loop starts from the
    finished goods the run produced.
    """
    seed_benchmark()

    flour = Item.objects.get(name="Flour")
    product = Item.objects.get(name="Murukku 200 g")
    create_purchase(
        supplier=Supplier.objects.get(name="Sri Lakshmi Flour Mills"),
        lines=[PurchaseLineInput(item_id=flour.pk, qty="60", unit_cost="45")],
    )
    run = create_run(product=product, batches="1")
    lines = {line.item.name: line for line in run.lines.select_related("item")}
    issue_run(
        run=run,
        issued={
            lines["Flour"].pk: "40",
            lines["Cooking oil"].pk: "10.5",
            lines["Salt and spice mix"].pk: "1.2",
        },
    )
    complete_run(run=run, good_packets="188", damaged_pouches="6", cartons_used="9")

    salesman_a = User.objects.get(username="salesman_a")
    salesman_b = User.objects.get(username="salesman_b")
    admin = User.objects.get(username="admin")
    retailer_a = Customer.objects.get(name="Retailer A")
    distributor_b = Customer.objects.get(name="Distributor B")

    # --- Step 4: salesman A orders 150 packets for Retailer A -------------
    submitted = create_order(
        customer=retailer_a,
        lines=[OrderLineInput(item_id=product.pk, qty=Decimal("150"))],
        client_uuid=uuid.uuid4(),
        salesman=salesman_a,
    )
    order = submitted.order
    assert order.state == OrderState.SUBMITTED
    assert order.lines.get().unit_price == Decimal("50.00")

    # --- Step 5: admin approves, invoice 7,875, dispatch, FG 88 ------------
    approve_order(order=order, user=admin)
    invoice = create_invoice(
        order=order,
        user=admin,
        invoice_date=date(2026, 5, 20),
    )
    assert invoice.number == "INV/26-27/00001"
    assert invoice.taxable_total == Decimal("7500.00")
    assert invoice.cgst_total == Decimal("187.50")
    assert invoice.sgst_total == Decimal("187.50")
    assert invoice.total == Decimal("7875.00")

    invoice_line = invoice.lines.get()
    dispatch_invoice(
        invoice=invoice,
        lines=[DispatchLineInput(invoice_line_id=invoice_line.pk, qty=Decimal("150"))],
        user=admin,
        dispatch_date=date(2026, 5, 21),
    )
    assert StockBalance.objects.get(item=product).qty == Decimal("88.000")
    order.refresh_from_db()
    assert order.state == OrderState.DISPATCHED

    # --- Step 6: Distributor B orders 120, shortage 32, IGST 300 ----------
    blocked = create_order(
        customer=distributor_b,
        lines=[OrderLineInput(item_id=product.pk, qty=Decimal("120"))],
        client_uuid=uuid.uuid4(),
        salesman=salesman_b,
    )
    coverage = stock_coverage(blocked.order)
    assert coverage.lines[0].available_qty == Decimal("88.000")
    assert coverage.lines[0].shortage_qty == Decimal("32.000")
    assert coverage.tax_preview.taxable_total == Decimal("6000.00")
    assert coverage.tax_preview.igst_total == Decimal("300.00")
    assert coverage.tax_preview.total == Decimal("6300.00")

    # --- Step 7: payment of 4,000 leaves 3,875 outstanding ----------------
    record_payment(
        customer=retailer_a,
        amount=Decimal("4000"),
        method="upi",
        allocations=[PaymentAllocationInput(invoice_id=invoice.pk, amount=Decimal("4000"))],
        payment_date=date(2026, 5, 25),
        user=admin,
    )
    assert invoice_outstanding(invoice) == Decimal("3875.00")

    # --- Step 8: labour 1,200 + gas/power 600 -> 31.14 per good packet ------
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
    assert sheet["materials_value"] == Decimal("4055.00")
    assert sheet["overhead_value"] == Decimal("1800.00")
    assert sheet["total_cost"] == Decimal("5855.00")
    assert sheet["cost_per_packet"] == Decimal("31.14")
    assert sheet["selling_price"] == Decimal("50.00")
    assert sheet["margin_per_packet"] == Decimal("18.86")
    assert sheet["margin_pct"] == Decimal("37.72")
    assert sheet["fg_stock_qty"] == Decimal("88.000")
    assert sheet["fg_stock_value"] == Decimal("3666.30")
    assert reconcile_stock() == []
