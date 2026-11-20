"""URL configuration for Kadai backend."""

from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def health(request):  # type: ignore[type-arg]
    """Health check endpoint."""
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", health, name="health"),
    path("api/accounts/", include("apps.accounts.urls")),
    path("api/masters/", include("apps.masters.urls")),
    path("api/inventory/", include("apps.inventory.urls")),
    path("api/production/", include("apps.production.urls")),
    path("api/sales/", include("apps.sales.urls")),
    path("api/payments/", include("apps.payments.urls")),
    path("api/costing/", include("apps.costing.urls")),
    path("api/reports/", include("apps.reports.urls")),
]
