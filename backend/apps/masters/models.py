"""Masters models – units, items, suppliers, customers, price lists, settings.

Invariants protected at the database level:
- Quantities and rates are NUMERIC Decimals, never floats.
- UoM conversion factors are strictly positive.
- Price list lines are unique per (price list, item).
- Item and customer names are unique natural keys so seeding is idempotent.
"""

from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models


class UoM(models.Model):
    """Unit of Measure (kg, g, L, mL, piece, packet, carton)."""

    name = models.CharField(max_length=50, unique=True)
    symbol = models.CharField(max_length=10, unique=True)

    class Meta:
        db_table = "masters_uom"
        verbose_name = "Unit of Measure"
        ordering = ["symbol"]

    def __str__(self) -> str:
        return self.symbol


class UoMConversion(models.Model):
    """Global conversion factor: ``1 from_uom = factor to_uom``.

    Only one direction needs to be stored (kg -> g); ``UnitConverter``
    supports the reverse.
    """

    from_uom = models.ForeignKey(UoM, on_delete=models.CASCADE, related_name="conversions_from")
    to_uom = models.ForeignKey(UoM, on_delete=models.CASCADE, related_name="conversions_to")
    factor = models.DecimalField(max_digits=18, decimal_places=6)

    class Meta:
        db_table = "masters_uom_conversion"
        constraints = [
            models.UniqueConstraint(
                fields=["from_uom", "to_uom"],
                name="uniq_uom_conversion",
            ),
            models.CheckConstraint(
                check=models.Q(factor__gt=0),
                name="chk_uom_conversion_factor_positive",
            ),
        ]

    def __str__(self) -> str:
        return f"1 {self.from_uom.symbol} = {self.factor} {self.to_uom.symbol}"


class ItemType(models.TextChoices):
    RAW = "RAW", "Raw Material"
    PACKAGING = "PACKAGING", "Packaging"
    FG = "FG", "Finished Goods"


class Item(models.Model):
    """Stock-keeping unit.

    ``uom`` is the item's base unit. Every ledger quantity for the item is
    stored in this unit.
    """

    name = models.CharField(max_length=200, unique=True)
    item_type = models.CharField(max_length=20, choices=ItemType.choices)
    uom = models.ForeignKey(UoM, on_delete=models.PROTECT, related_name="items")
    hsn_code = models.CharField(max_length=20, blank=True)
    gst_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0"))],
        help_text="GST rate as a percentage, e.g. 5.00 for 5%.",
    )
    standard_batch_hours = models.DecimalField(
        max_digits=8,
        decimal_places=3,
        default=Decimal("1.000"),
        validators=[MinValueValidator(Decimal("0.001"))],
        help_text="Standard batch-hours per batch, used to allocate monthly overheads.",
    )

    class Meta:
        db_table = "masters_item"
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                check=models.Q(gst_rate__gte=0),
                name="chk_item_gst_rate_non_negative",
            ),
            models.CheckConstraint(
                check=models.Q(standard_batch_hours__gt=0),
                name="chk_item_standard_batch_hours_positive",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class ItemUoMConversion(models.Model):
    """Item-specific conversion: ``1 uom = factor * item.uom``.

    Example: for the Murukku 200 g item (base unit packet), one carton is
    20 packets.
    """

    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="uom_conversions")
    uom = models.ForeignKey(UoM, on_delete=models.CASCADE, related_name="item_conversions")
    factor = models.DecimalField(max_digits=18, decimal_places=6)

    class Meta:
        db_table = "masters_item_uom_conversion"
        constraints = [
            models.UniqueConstraint(
                fields=["item", "uom"],
                name="uniq_item_uom_conversion",
            ),
            models.CheckConstraint(
                check=models.Q(factor__gt=0),
                name="chk_item_uom_conversion_factor_positive",
            ),
        ]

    def __str__(self) -> str:
        return f"1 {self.uom.symbol} = {self.factor} {self.item.uom.symbol} ({self.item.name})"


class Supplier(models.Model):
    """Raw-material supplier."""

    name = models.CharField(max_length=200, unique=True)
    gstin = models.CharField(max_length=15, blank=True)
    state_code = models.CharField(max_length=2, default="33")

    class Meta:
        db_table = "masters_supplier"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class CustomerType(models.TextChoices):
    RETAILER = "retailer", "Retailer"
    DISTRIBUTOR = "distributor", "Distributor"
    WHOLESALE = "wholesale", "Wholesale"


class PriceList(models.Model):
    """Named set of selling prices. Exactly one list may be the default."""

    name = models.CharField(max_length=100, unique=True)
    is_default = models.BooleanField(default=False)

    class Meta:
        db_table = "masters_price_list"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class PriceListLine(models.Model):
    """Selling price for one item on one price list (before GST)."""

    price_list = models.ForeignKey(
        PriceList,
        on_delete=models.CASCADE,
        related_name="lines",
    )
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="price_lines")
    price = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
    )

    class Meta:
        db_table = "masters_price_list_line"
        constraints = [
            models.UniqueConstraint(
                fields=["price_list", "item"],
                name="uniq_price_list_item",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.item.name} @ {self.price} ({self.price_list.name})"


class Customer(models.Model):
    """Sales customer. State code drives the GST place of supply."""

    name = models.CharField(max_length=200, unique=True)
    gstin = models.CharField(max_length=15, blank=True)
    state_code = models.CharField(max_length=2)
    customer_type = models.CharField(
        max_length=20,
        choices=CustomerType.choices,
        default=CustomerType.RETAILER,
    )
    assigned_salesman = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="customers",
    )
    price_list = models.ForeignKey(
        PriceList,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="customers",
    )

    class Meta:
        db_table = "masters_customer"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Setting(models.Model):
    """Key/value business setting (variance tolerance, factory state, ...).

    Settings are read through ``masters.services.get_decimal_setting`` so no
    magic numbers are hard-coded in business logic.
    """

    key = models.CharField(max_length=100, unique=True)
    value = models.TextField()
    description = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "masters_setting"
        ordering = ["key"]

    def __str__(self) -> str:
        return f"{self.key}={self.value}"
