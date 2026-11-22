"""Reports URL configuration."""

from django.urls import path

from . import views

urlpatterns = [
    path("", views.ReportCatalogView.as_view(), name="reports-catalog"),
    path("reconciliation/", views.ReconciliationView.as_view(), name="reports-reconciliation"),
    path("dashboard/", views.DashboardView.as_view(), name="reports-dashboard"),
    path("<slug:slug>/", views.ReportDetailView.as_view(), name="reports-detail"),
]
