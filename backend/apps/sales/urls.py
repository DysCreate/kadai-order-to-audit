"""Sales URL configuration."""

from django.urls import path

from . import views

urlpatterns = [
    path("orders/", views.OrderCollectionView.as_view(), name="sales-order-list"),
    path(
        "orders/summary/",
        views.OrderSalesSummaryView.as_view(),
        name="sales-order-summary",
    ),
    path("orders/<int:pk>/", views.OrderDetailView.as_view(), name="sales-order-detail"),
    path(
        "orders/<int:pk>/coverage/",
        views.OrderCoverageView.as_view(),
        name="sales-order-coverage",
    ),
    path(
        "orders/<int:pk>/approve/",
        views.OrderApproveView.as_view(),
        name="sales-order-approve",
    ),
    path(
        "orders/<int:pk>/reject/",
        views.OrderRejectView.as_view(),
        name="sales-order-reject",
    ),
    path(
        "orders/<int:pk>/lines/<int:line_pk>/",
        views.OrderLineEditView.as_view(),
        name="sales-order-line-edit",
    ),
    path(
        "orders/<int:pk>/invoice/",
        views.OrderInvoiceView.as_view(),
        name="sales-order-invoice",
    ),
    path("invoices/", views.InvoiceCollectionView.as_view(), name="sales-invoice-list"),
    path(
        "invoices/pdf/<str:token>/",
        views.InvoicePdfTokenView.as_view(),
        name="sales-invoice-pdf-token",
    ),
    path("invoices/<int:pk>/", views.InvoiceDetailView.as_view(), name="sales-invoice-detail"),
    path("invoices/<int:pk>/pdf/", views.InvoicePdfView.as_view(), name="sales-invoice-pdf"),
    path(
        "invoices/<int:pk>/dispatch/",
        views.InvoiceDispatchView.as_view(),
        name="sales-invoice-dispatch",
    ),
    path(
        "invoices/<int:pk>/credit-notes/",
        views.InvoiceCreditNoteView.as_view(),
        name="sales-invoice-credit-note",
    ),
    path(
        "invoices/<int:pk>/share/",
        views.InvoiceShareView.as_view(),
        name="sales-invoice-share",
    ),
]
