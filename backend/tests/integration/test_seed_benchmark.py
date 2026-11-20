"""Seed and reconciliation integration tests.

Requirement: AGENTS.md Section 4.15 (seed is idempotent, supports --reset) and
Section 6.7 (make reconcile passes).
"""

from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command

from apps.accounts.models import Role, User
from apps.benchmark.services import seed_benchmark
from apps.inventory.models import StockLedger
from apps.inventory.services import adjust_stock
from apps.masters.models import Customer, Item, PriceList, Setting
from apps.masters.services import convert_quantity, resolve_price


@pytest.mark.django_db
def test_seed_users_roles_and_customer_assignments() -> None:
    """PS 1 roles: all five roles exist; customer assignment follows Appendix A."""
    seed_benchmark()

    users = {user.username: user for user in User.objects.all()}
    assert users["salesman_a"].role == Role.SALESMAN
    assert users["salesman_b"].role == Role.SALESMAN
    assert users["admin"].role == Role.ADMIN
    assert users["production"].role == Role.PRODUCTION
    assert users["accountant"].role == Role.ACCOUNTANT
    assert users["owner"].role == Role.OWNER

    retailer = Customer.objects.get(name="Retailer A")
    distributor = Customer.objects.get(name="Distributor B")
    assert retailer.state_code == "33"
    assert distributor.state_code == "29"
    assert retailer.assigned_salesman_id == users["salesman_a"].pk
    assert distributor.assigned_salesman_id == users["salesman_b"].pk
    assert retailer in users["salesman_a"].assigned_customers.all()


@pytest.mark.django_db
def test_seed_master_data_and_prices() -> None:
    """PS 1 price list: seeded selling price is 50 before tax; carton is 20 packets."""
    seed_benchmark()

    murukku = Item.objects.get(name="Murukku 200 g")
    assert murukku.item_type == "FG"
    assert murukku.gst_rate == Decimal("5.00")
    assert resolve_price(item=murukku) == Decimal("50.00")
    assert convert_quantity(item=murukku, qty="1", from_symbol="ctn", to_symbol="pkt") == Decimal(
        "20.000"
    )

    assert Setting.objects.get(key="variance_tolerance").value == "0.03"
    assert PriceList.objects.get(name="Standard 2026-27").is_default


@pytest.mark.django_db
def test_seed_is_idempotent() -> None:
    """PS 4.15: running the seed twice creates no duplicates."""
    seed_benchmark()
    counts = (
        User.objects.count(),
        Item.objects.count(),
        Customer.objects.count(),
        PriceList.objects.count(),
        StockLedger.objects.count(),
        Setting.objects.count(),
    )

    report = seed_benchmark()

    assert report.opening_balances == 0
    assert (
        User.objects.count(),
        Item.objects.count(),
        Customer.objects.count(),
        PriceList.objects.count(),
        StockLedger.objects.count(),
        Setting.objects.count(),
    ) == counts


@pytest.mark.django_db(transaction=True)
def test_seed_reset_restores_benchmark_state() -> None:
    """PS 4.15: --reset wipes business data and replays the opening balances."""
    seed_benchmark()
    flour = Item.objects.get(name="Flour")
    adjust_stock(
        item_id=flour.pk,
        qty_delta="-5",
        reason="Test spillage",
    )
    assert StockLedger.objects.count() == 7

    call_command("seed_benchmark", "--reset", stdout=StringIO())

    # Identity restarts on reset, so re-fetch by natural key.
    flour = Item.objects.get(name="Flour")
    assert StockLedger.objects.count() == 6
    assert StockLedger.objects.filter(item=flour, movement_type="ADJUSTMENT").count() == 0
    assert StockLedger.objects.get(item=flour).qty == Decimal("100.000")


@pytest.mark.django_db
def test_reconcile_command_passes_after_seed() -> None:
    """PS 6.7: reconcile proves every balance equals its ledger sum."""
    seed_benchmark()
    stdout = StringIO()
    call_command("reconcile", stdout=stdout)
    assert "Reconciliation OK" in stdout.getvalue()
