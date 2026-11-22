"""Production URL configuration."""

from django.urls import path

from . import views

urlpatterns = [
    path("boms/", views.BOMCollectionView.as_view(), name="production-bom-list"),
    path("runs/", views.RunCollectionView.as_view(), name="production-run-list"),
    path("runs/<int:pk>/", views.RunDetailView.as_view(), name="production-run-detail"),
    path("runs/<int:pk>/issue/", views.RunIssueView.as_view(), name="production-run-issue"),
    path(
        "runs/<int:pk>/complete/",
        views.RunCompleteView.as_view(),
        name="production-run-complete",
    ),
    path("runs/<int:pk>/amend/", views.RunAmendView.as_view(), name="production-run-amend"),
    path(
        "runs/<int:pk>/report-card/",
        views.RunReportCardView.as_view(),
        name="production-run-report-card",
    ),
    path(
        "products/<int:pk>/leakage/",
        views.ProductLeakageView.as_view(),
        name="production-product-leakage",
    ),
]
