"""Accounts URL configuration."""

from django.urls import path

from . import views

urlpatterns = [
    path("register/", views.RegisterView.as_view(), name="accounts-register"),
    path("login/", views.login_view, name="accounts-login"),
    path("logout/", views.logout_view, name="accounts-logout"),
    path("me/", views.me_view, name="accounts-me"),
    path("team/", views.TeamView.as_view(), name="accounts-team"),
    path(
        "team/invitations/",
        views.TeamInviteView.as_view(),
        name="accounts-team-invite",
    ),
    path(
        "invitations/<str:token>/",
        views.InvitationPreviewView.as_view(),
        name="accounts-invitation",
    ),
    path(
        "invitations/<str:token>/accept/",
        views.AcceptInvitationView.as_view(),
        name="accounts-invitation-accept",
    ),
]
