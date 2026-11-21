"""Masters URL configuration."""

from django.urls import path

from . import views

urlpatterns = [
    path("customers/", views.CustomerCollectionView.as_view(), name="masters-customer-list"),
    path("items/", views.ItemCatalogView.as_view(), name="masters-item-list"),
]
