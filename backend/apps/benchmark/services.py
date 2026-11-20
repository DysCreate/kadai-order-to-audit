"""Benchmark scenario services – seed and reset Appendix A master data.

Invariants protected:
- Seeding is idempotent: running it twice creates no duplicate items, users,
  customers, prices or opening ledger rows.
- Opening stock is posted through ``post_opening_balance`` so every balance is
  a ledger row (OPENING) with a non-null source.
- ``--reset`` wipes only business data, using TRUNCATE (row triggers do not
  fire, so the append-only guarantee is replaced by an explicit, auditable
  reset path).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.db import connection, transaction

from apps.accounts.models import Role, User
from apps.accounts.services import create_user
from apps.inventory.models import StockLedger
from apps.inventory.services import post_opening_balance
from apps.masters.models import Item, ItemType, PriceList
from apps.masters.services import (
    add_item_conversion,
    add_uom_conversion,
    create_customer,
    create_item,
    create_price_list,
    create_supplier,
    create_uom,
    ensure_default_settings,
    set_price,
)
from apps.production.models import BOM
from apps.production.services import BOMLineInput, create_bom_version

UOMS: tuple[tuple[str, str], ...] = (
    ("Kilogram", "kg"),
    ("Gram", "g"),
    ("Litre", "L"),
    ("Millilitre", "mL"),
    ("Piece", "pc"),
    ("Packet", "pkt"),
    ("Carton", "ctn"),
)

GLOBAL_CONVERSIONS: tuple[tuple[str, str, Decimal], ...] = (
    ("kg", "g", Decimal("1000")),
    ("L", "mL", Decimal("1000")),
)

USERS: tuple[tuple[str, str], ...] = (
    ("salesman_a", Role.SALESMAN),
    ("salesman_b", Role.SALESMAN),
    ("admin", Role.ADMIN),
    ("production", Role.PRODUCTION),
    ("accountant", Role.ACCOUNTANT),
    ("owner", Role.OWNER),
)

ITEMS: tuple[tuple[str, str, str, str, str], ...] = (
    ("Flour", ItemType.RAW, "kg", "1101", "5.00"),
    ("Cooking oil", ItemType.RAW, "L", "1507", "5.00"),
    ("Salt and spice mix", ItemType.RAW, "kg", "0910", "5.00"),
    ("200 g pouch", ItemType.PACKAGING, "pc", "3923", "18.00"),
    ("Carton (holds 20 packets)", ItemType.PACKAGING, "pc", "4819", "18.00"),
    ("Murukku 200 g", ItemType.FG, "pkt", "2106", "5.00"),
)

OPENING_STOCK: tuple[tuple[str, Decimal, Decimal], ...] = (
    ("Flour", Decimal("100"), Decimal("42")),
    ("Cooking oil", Decimal("30"), Decimal("140")),
    ("Salt and spice mix", Decimal("5"), Decimal("200")),
    ("200 g pouch", Decimal("500"), Decimal("2.50")),
    ("Carton (holds 20 packets)", Decimal("30"), Decimal("15")),
    ("Murukku 200 g", Decimal("50"), Decimal("19.85")),
)

CUSTOMER_PRICE_LIST_NAME = "Standard 2026-27"
SELLING_PRICE = Decimal("50.00")

# Appendix A BOM for Murukku 200 g: one batch is 40 kg of bulk product, packed
# into 200 packets of 200 g. Roles mark the pouch and carton lines, whose
# consumption is derived from the packing record at run completion.
BOM_BATCH_OUTPUT_QTY = Decimal("200")
BOM_LINES: tuple[tuple[str, Decimal, str], ...] = (
    ("Flour", Decimal("40"), "material"),
    ("Cooking oil", Decimal("10"), "material"),
    ("Salt and spice mix", Decimal("1.2"), "material"),
    ("200 g pouch", Decimal("200"), "pouch"),
    ("Carton (holds 20 packets)", Decimal("10"), "carton"),
)

SUPPLIER = ("Sri Lakshmi Flour Mills", "33AABCS1234F1Z5")

CUSTOMERS: tuple[tuple[str, str, str, str, str], ...] = (
    # name, state code, type, gstin, assigned salesman username
    ("Retailer A", "33", "retailer", "33AABCR1234A1Z5", "salesman_a"),
    ("Distributor B", "29", "distributor", "29AABCD1234B1Z5", "salesman_b"),
)

FINISHED_GOODS_NAME = "Murukku 200 g"

# Tables wiped by --reset. CASCADE covers join tables (user -> customer).
BUSINESS_TABLES: tuple[str, ...] = (
    "production_run_variance_snapshot",
    "production_run_line",
    "production_run",
    "production_bom_line",
    "production_bom",
    "inventory_purchase_line",
    "inventory_purchase",
    "audit_log",
    "inventory_stock_ledger",
    "inventory_stock_balance",
    "inventory_stock_adjustment",
    "masters_price_list_line",
    "masters_price_list",
    "masters_item_uom_conversion",
    "masters_uom_conversion",
    "masters_customer",
    "masters_supplier",
    "masters_item",
    "masters_uom",
    "masters_setting",
    "accounts_user",
)


@dataclass(frozen=True)
class SeedReport:
    """Counts produced by a seed run, for the command summary."""

    users: int
    items: int
    customers: int
    opening_balances: int
    uoms: int
    bom_versions: int = 0


def reset_benchmark_data() -> None:
    """Wipe business data so the benchmark can be replayed from scratch.

    TRUNCATE is used because the stock ledger is append-only under UPDATE and
    DELETE triggers; it restarts identities so invoice/document numbering is
    deterministic for a benchmark run.
    """
    table_list = ", ".join(BUSINESS_TABLES)
    with connection.cursor() as cursor:
        cursor.execute(
            f"TRUNCATE TABLE {table_list} RESTART IDENTITY CASCADE"  # noqa: S608
        )


def _ensure_user(username: str, role: str) -> User:
    """Create the seed user, or align an existing user's role and flags."""
    user = User.objects.filter(username=username).first()
    if user is None:
        return create_user(username=username, password=username, role=role)

    changed = False
    if user.role != role:
        user.role = role
        changed = True
    wants_staff = role in (Role.ADMIN, Role.OWNER)
    if user.is_staff != wants_staff:
        user.is_staff = wants_staff
        changed = True
    if role == Role.ADMIN and not user.is_superuser:
        user.is_superuser = True
        changed = True
    if changed:
        user.save(update_fields=["role", "is_staff", "is_superuser"])
    return user


@transaction.atomic
def seed_benchmark(*, reset: bool = False) -> SeedReport:
    """Load (or top up) the Appendix A benchmark master data.

    Idempotent: users, UoMs, items, customers, prices and opening balances are
    looked up by their natural keys; an item with any ledger history never gets
    a second opening row.
    """
    if reset:
        reset_benchmark_data()

    ensure_default_settings()

    users: dict[str, User] = {username: _ensure_user(username, role) for username, role in USERS}

    for name, symbol in UOMS:
        create_uom(name=name, symbol=symbol)
    for from_symbol, to_symbol, factor in GLOBAL_CONVERSIONS:
        add_uom_conversion(from_symbol=from_symbol, to_symbol=to_symbol, factor=factor)

    create_supplier(name=SUPPLIER[0], gstin=SUPPLIER[1])

    price_list = create_price_list(name=CUSTOMER_PRICE_LIST_NAME, is_default=True)

    for name, item_type, uom_symbol, hsn_code, gst_rate in ITEMS:
        create_item(
            name=name,
            item_type=item_type,
            uom_symbol=uom_symbol,
            hsn_code=hsn_code,
            gst_rate=Decimal(gst_rate),
        )

    finished_goods = Item.objects.get(name=FINISHED_GOODS_NAME)
    add_item_conversion(item=finished_goods, uom_symbol="ctn", factor=Decimal("20"))
    set_price(price_list=price_list, item=finished_goods, price=SELLING_PRICE)

    bom_versions = 0
    if not BOM.objects.filter(product=finished_goods).exists():
        create_bom_version(
            product=finished_goods,
            batch_output_qty=BOM_BATCH_OUTPUT_QTY,
            lines=[
                BOMLineInput(
                    item_id=Item.objects.get(name=item_name).pk,
                    qty_per_batch=qty,
                    role=role,
                )
                for item_name, qty, role in BOM_LINES
            ],
        )
        bom_versions = 1

    customers = 0
    for name, state_code, customer_type, gstin, salesman_username in CUSTOMERS:
        create_customer(
            name=name,
            state_code=state_code,
            customer_type=customer_type,
            gstin=gstin,
            assigned_salesman=users[salesman_username],
            price_list=price_list,
        )
        customers += 1

    opening_balances = 0
    for item_name, qty, unit_cost in OPENING_STOCK:
        item = Item.objects.get(name=item_name)
        if not StockLedger.objects.filter(item=item).exists():
            post_opening_balance(item_id=item.pk, qty=qty, unit_cost=unit_cost)
            opening_balances += 1

    return SeedReport(
        users=len(users),
        items=len(ITEMS),
        customers=customers,
        opening_balances=opening_balances,
        uoms=len(UOMS),
        bom_versions=bom_versions,
    )


def benchmark_price_list() -> PriceList:
    """Return the seeded default price list (used by later phases)."""
    return PriceList.objects.get(name=CUSTOMER_PRICE_LIST_NAME)
