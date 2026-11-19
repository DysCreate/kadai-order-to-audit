"""Masters models – Item, UoM, Supplier, Customer."""

from decimal import Decimal

from django.db import models


class UoM(models.Model):
    """Unit of Measure."""

    name = models.CharField(max_length=50, unique=True)
    symbol = models.CharField(max_length=10, unique=True)

    class Meta:
        db_table = "masters_uom"
        verbose_name = "Unit of Measure"

    def __str__(self) -> str:
        return self.symbol


class ItemType(models.TextChoices):
    RAW = "RAW", "Raw Material"
    PACKAGING = "PACKAGING", "Packaging"
    FG = "FG", "Finished Goods"


class Item(models.Model):
    """Stock-keeping unit."""

    name = models.CharField(max_length=200)
    item_type = models.CharField(max_length=20, choices=ItemType.choices)
    uom = models.ForeignKey(UoM, on_delete=models.PROTECT, related_name="items")
    hsn_code = models.CharField(max_length=20, blank=True)
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        db_table = "masters_item"

    def __str__(self) -> str:
        return self.name


class Supplier(models.Model):
    """Raw-material supplier."""

    name = models.CharField(max_length=200)
    gstin = models.CharField(max_length=15, blank=True)

    class Meta:
        db_table = "masters_supplier"

    def __str__(self) -> str:
        return self.name


class CustomerType(models.TextChoices):
    RETAILER = "retailer", "Retailer"
    DISTRIBUTOR = "distributor", "Distributor"
    WHOLESALE = "wholesale", "Wholesale"


class Customer(models.Model):
    """Sales customer."""

    name = models.CharField(max_length=200)
    gstin = models.CharField(max_length=15, blank=True)
    state_code = models.CharField(max_length=2)
    customer_type = models.CharField(
        max_length=20, choices=CustomerType.choices, default=CustomerType.RETAILER
    )
    assigned_salesman = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="customers",
    )

    class Meta:
        db_table = "masters_customer"

    def __str__(self) -> str:
        return self.name
