"""Shared pytest fixtures for Kadai backend tests.

State is always built through services, never by inserting rows directly
(AGENTS.md Section 5).
"""

from collections.abc import Callable
from decimal import Decimal

import pytest

from apps.accounts.models import Role, User
from apps.accounts.services import create_user
from apps.masters.models import Item
from apps.masters.services import create_item, create_uom


@pytest.fixture
def make_item(db: None) -> Callable[..., Item]:
    """Factory that creates a UoM (if needed) and an item through services."""

    def _make_item(
        name: str = "Flour",
        item_type: str = "RAW",
        uom_symbol: str = "kg",
        hsn_code: str = "1101",
        gst_rate: Decimal | str = Decimal("5.00"),
    ) -> Item:
        create_uom(name=f"Unit {uom_symbol}", symbol=uom_symbol)
        return create_item(
            name=name,
            item_type=item_type,
            uom_symbol=uom_symbol,
            hsn_code=hsn_code,
            gst_rate=gst_rate,
        )

    return _make_item


@pytest.fixture
def role_users(db: None) -> dict[str, User]:
    """One user per role, created through the accounts service."""
    return {
        role: create_user(username=f"user_{role}", password="test-pass", role=role)
        for role in Role.values
    }
