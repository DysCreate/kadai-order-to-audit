"""Payments URL configuration."""

from django.urls import path

from . import views

urlpatterns = [
    path("payments/", views.PaymentCollectionView.as_view(), name="payments-payment-list"),
    path("outstanding/", views.CustomerOutstandingView.as_view(), name="payments-outstanding"),
    path("ageing/", views.CustomerAgeingView.as_view(), name="payments-ageing"),
    path(
        "customers/<int:pk>/ledger/",
        views.CustomerLedgerView.as_view(),
        name="payments-customer-ledger",
    ),
]
