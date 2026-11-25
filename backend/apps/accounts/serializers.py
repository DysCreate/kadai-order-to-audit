"""Serializers for organization onboarding, invitations and team management."""

from __future__ import annotations

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import Invitation, Role, User


def _validate_password(value: str, *, username: str = "", email: str = "") -> str:
    candidate = User(username=username, email=email)
    try:
        validate_password(value, user=candidate)
    except DjangoValidationError as exc:
        raise serializers.ValidationError(list(exc.messages)) from exc
    return value


class RegisterSerializer(serializers.Serializer):
    """Input for creating an organization and its owner."""

    organization_name = serializers.CharField(max_length=200)
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        attrs["password"] = _validate_password(
            str(attrs["password"]),
            username=str(attrs["username"]),
            email=str(attrs["email"]),
        )
        return attrs


class AcceptInvitationSerializer(serializers.Serializer):
    """Input for accepting an invitation and choosing a login."""

    username = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        attrs["password"] = _validate_password(
            str(attrs["password"]),
            username=str(attrs["username"]),
        )
        return attrs


class InviteMemberSerializer(serializers.Serializer):
    """Input for inviting one admin or employee."""

    email = serializers.EmailField()
    role = serializers.ChoiceField(choices=Role.choices)


class TeamMemberSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "username", "email", "role", "date_joined")


class InvitationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invitation
        fields = ("id", "email", "role", "created_at", "expires_at")


class InvitationPreviewSerializer(serializers.ModelSerializer):
    organization_name = serializers.CharField(source="organization.name", read_only=True)

    class Meta:
        model = Invitation
        fields = ("email", "role", "organization_name")
