"""Accounts URL configuration."""

from django.urls import path

from . import views

urlpatterns = [
    path("login/", views.login_view, name="accounts-login"),
    path("logout/", views.logout_view, name="accounts-logout"),
    path("me/", views.me_view, name="accounts-me"),
]
