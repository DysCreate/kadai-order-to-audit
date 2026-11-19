"""Unit tests for the core domain module: money, quantity, errors, and permissions.

Requirement: Domain invariants (AGENTS.md Section 4).
"""

from decimal import Decimal
from unittest.mock import MagicMock
import pytest

from core.audit import log_audit
from core.errors import (
    BOMVersionMismatch,
    DomainError,
    DuplicateOrder,
    InsufficientStock,
    InvalidUnit,
    InvoiceImmutable,
)
from core.money import q2
from core.permissions import PermissionDenied, require_role
from core.quantity import q3


def test_q2_paise_rounding() -> None:
    """Money rounding must strictly use ROUND_HALF_UP to 2 decimal places."""
    assert q2("10.555") == Decimal("10.56")
    assert q2("10.554") == Decimal("10.55")
    assert q2("10.5550") == Decimal("10.56")
    assert q2("0.005") == Decimal("0.01")
    assert q2("0.004") == Decimal("0.00")
    assert q2(10) == Decimal("10.00")
    assert q2(Decimal("123.456")) == Decimal("123.46")


def test_q3_quantity_rounding() -> None:
    """Stock quantities must strictly use ROUND_HALF_UP to 3 decimal places."""
    assert q3("40.1255") == Decimal("40.126")
    assert q3("40.1254") == Decimal("40.125")
    assert q3("0.0005") == Decimal("0.001")
    assert q3("0.0004") == Decimal("0.000")
    assert q3(40) == Decimal("40.000")
    assert q3(Decimal("1.2001")) == Decimal("1.200")


def test_domain_error_hierarchy() -> None:
    """All domain errors must inherit from DomainError and define error codes."""
    errors = [
        (InsufficientStock("out of stock"), "insufficient_stock"),
        (InvalidUnit("unknown uom"), "invalid_unit"),
        (InvoiceImmutable("cannot edit"), "invoice_immutable"),
        (BOMVersionMismatch("stale bom"), "bom_version_mismatch"),
        (DuplicateOrder("uuid exists"), "duplicate_order"),
    ]
    for err, expected_code in errors:
        assert isinstance(err, DomainError)
        assert err.code == expected_code
        assert str(err) == err.message


def test_require_role_decorator_unauthenticated() -> None:
    """require_role raises PermissionDenied when request has no authenticated user."""

    @require_role("admin", "owner")
    def dummy_view(request: MagicMock) -> str:
        return "ok"

    req = MagicMock()
    req.user.is_authenticated = False
    with pytest.raises(PermissionDenied) as exc_info:
        dummy_view(req)
    assert "Authentication required" in str(exc_info.value)


def test_require_role_decorator_unauthorized() -> None:
    """require_role raises PermissionDenied when user role is not permitted."""

    @require_role("admin", "owner")
    def dummy_view(request: MagicMock) -> str:
        return "ok"

    req = MagicMock()
    req.user.is_authenticated = True
    req.user.role = "salesman"
    with pytest.raises(PermissionDenied) as exc_info:
        dummy_view(req)
    assert "salesman" in str(exc_info.value)


def test_require_role_decorator_authorized() -> None:
    """require_role passes through when user role is allowed."""

    @require_role("admin", "owner")
    def dummy_view(request: MagicMock) -> str:
        return "success"

    req = MagicMock()
    req.user.is_authenticated = True
    req.user.role = "admin"
    assert dummy_view(req) == "success"


def test_audit_log_stub() -> None:
    """log_audit stub executes without crashing."""
    user = MagicMock()
    log_audit(user, "Order", 1, "create", {}, {"id": 1})
