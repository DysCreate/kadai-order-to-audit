"""Inventory URL configuration."""

from django.urls import path

from . import views

urlpatterns = [
    path("stock/", views.StockSummaryView.as_view(), name="inventory-stock-summary"),
    path("ledger/", views.StockLedgerView.as_view(), name="inventory-ledger"),
    path(
        "adjustments/",
        views.StockAdjustmentView.as_view(),
        name="inventory-adjustment-create",
    ),
    path("purchases/", views.PurchaseCreateView.as_view(), name="inventory-purchase-create"),
]
