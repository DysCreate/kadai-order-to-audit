"""Owner dashboard – the day's trading position in one read.

Invariants protected:
- "Today" is the Asia/Kolkata business day, even though timestamps are stored
  in UTC.
- Reorder flags are derived from the active BOM: a raw or packaging item is
  flagged when on-hand stock is below one batch's requirement. Finished goods
  are flagged only when they are out of stock. No new master field is invented.
- Cost per packet comes from the latest completed run's stored cost sheet and
  outstanding dues from the payments service, so the dashboard never keeps a
  second set of books.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import F, QuerySet, Sum

from apps.costing.services import run_cost_sheet
from apps.inventory.services import stock_summary
from apps.masters.models import Customer, Item, ItemType
from apps.payments.services import customer_outstanding
from apps.production.models import BOMLine, ProductionRun, RunState, RunVarianceSnapshot
from apps.sales.models import Order, OrderLine, OrderState
from apps.sales.numbering import KOLKATA, kolkata_today
from core.money import q2
from core.quantity import q3


def _day_bounds(day_today: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day_today, time.min, tzinfo=KOLKATA)
    return start, start + timedelta(days=1)


def _order_value(orders: QuerySet[Order]) -> Decimal:
    total = OrderLine.objects.filter(order__in=orders).aggregate(
        value=Sum(F("qty") * F("unit_price"))
    )["value"]
    return q2(total or Decimal("0.00"))


def _reorder_requirements() -> dict[int, Decimal]:
    """Return one-batch requirements per BOM input, from the latest BOMs."""
    requirements: dict[int, Decimal] = {}
    for line in BOMLine.objects.select_related("bom").order_by("item_id", "-bom__version"):
        current = requirements.get(line.item_id)
        if current is None:
            requirements[line.item_id] = line.qty_per_batch
    return requirements


def dashboard() -> dict[str, Any]:
    """Return today's orders, stock, variance alerts, cost and dues."""
    today = kolkata_today()
    start, end = _day_bounds(today)

    today_orders = Order.objects.filter(created_at__gte=start, created_at__lt=end)
    open_orders = Order.objects.filter(state__in=[OrderState.SUBMITTED, OrderState.APPROVED])
    requirements = _reorder_requirements()

    stock_rows: list[dict[str, Any]] = []
    reorder_count = 0
    for summary in stock_summary():
        item: Item = summary.item
        requirement = requirements.get(item.pk)
        reorder = False
        reorder_qty = Decimal("0.000")
        if item.item_type == ItemType.FG:
            reorder = summary.qty == 0
        elif requirement is not None and summary.qty < requirement:
            reorder = True
            reorder_qty = q3(requirement - summary.qty)
        if reorder:
            reorder_count += 1
        stock_rows.append(
            {
                "item_id": item.pk,
                "item_name": item.name,
                "item_type": item.item_type,
                "uom": item.uom.symbol,
                "qty": summary.qty,
                "value": summary.value,
                "reorder": reorder,
                "reorder_qty": reorder_qty,
                "batch_requirement": requirement,
            }
        )

    alerts = (
        RunVarianceSnapshot.objects.filter(
            flagged=True,
            run__state=RunState.COMPLETED,
            run__completed_at__gte=start - timedelta(days=30),
        )
        .select_related("run__product")
        .order_by("-created_at", "-pk")[:5]
    )
    variance_alerts = [
        {
            "run_id": row.run_id,
            "product": row.run.product.name,
            "item_name": row.item_name,
            "kind": row.kind,
            "variance_pct": row.variance_pct,
            "direction": row.direction,
        }
        for row in alerts
    ]

    latest_run = (
        ProductionRun.objects.select_related("product")
        .filter(state=RunState.COMPLETED)
        .order_by("-completed_at", "-pk")
        .first()
    )
    cost_per_packet = None
    if latest_run is not None:
        sheet = run_cost_sheet(latest_run)
        cost_per_packet = {
            "run_id": latest_run.pk,
            "product": latest_run.product.name,
            "cost_per_packet": sheet["cost_per_packet"],
            "selling_price": sheet["selling_price"],
            "margin_per_packet": sheet["margin_per_packet"],
            "margin_pct": sheet["margin_pct"],
        }

    dues = Decimal("0.00")
    customers_with_dues = 0
    for customer in Customer.objects.order_by("pk"):
        amount = customer_outstanding(customer)
        if amount > 0:
            dues += amount
            customers_with_dues += 1

    return {
        "business_date": today,
        "today_orders": {
            "count": today_orders.count(),
            "value": _order_value(today_orders),
        },
        "open_orders": {
            "count": open_orders.count(),
            "submitted": open_orders.filter(state=OrderState.SUBMITTED).count(),
            "approved": open_orders.filter(state=OrderState.APPROVED).count(),
        },
        "stock": stock_rows,
        "reorder_count": reorder_count,
        "variance_alerts": variance_alerts,
        "cost_per_packet": cost_per_packet,
        "outstanding_dues": {
            "amount": q2(dues),
            "customers": customers_with_dues,
        },
    }
