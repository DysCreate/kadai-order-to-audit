"""Benchmark URL configuration."""

from django.urls import path

from . import views

urlpatterns = [
    path("run/", views.BenchmarkRunView.as_view(), name="benchmark-run"),
]
