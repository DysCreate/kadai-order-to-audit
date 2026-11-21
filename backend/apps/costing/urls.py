"""Costing URL configuration."""

from django.urls import path

from . import views

urlpatterns = [
    path(
        "runs/<int:pk>/",
        views.RunCostSheetView.as_view(),
        name="costing-run-cost-sheet",
    ),
    path(
        "runs/<int:pk>/overheads/",
        views.RunOverheadView.as_view(),
        name="costing-run-overhead",
    ),
    path(
        "monthly-overheads/",
        views.MonthlyOverheadCollectionView.as_view(),
        name="costing-monthly-overheads",
    ),
    path(
        "monthly-overheads/allocate/",
        views.MonthlyOverheadAllocateView.as_view(),
        name="costing-monthly-overheads-allocate",
    ),
    path(
        "products/<int:pk>/",
        views.ProductCostView.as_view(),
        name="costing-product-cost",
    ),
]
