"""Unit tests for the core domain module: money, quantity, errors, and permissions.

Requirement: Domain invariants (AGENTS.md Section 4).
"""

from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from rest_framework.exceptions import PermissionDenied as DRFPermissionDenied

from core.api import domain_exception_handler
from core.audit import log_audit
from core.errors import (
    BOMVersionMismatch,
    DomainError,
    DuplicateOrder,
    InsufficientStock,
    InvalidUnit,
    InvoiceImmutable,
)
from core.money import q2, q4
from core.permissions import PermissionDenied, RolePermission, require_role
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


def test_q4_rate_rounding() -> None:
    """Unit rates are rounded half-up to 4 decimal places."""
    assert q4("43.12505") == Decimal("43.1251")
    assert q4("43.12504") == Decimal("43.1250")
    assert q4(Decimal("140")) == Decimal("140.0000")


def test_float_input_is_rejected() -> None:
    """Floats are forbidden in money and stock code, even accidentally."""
    with pytest.raises(TypeError):
        q2(10.5)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        q4(43.125)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        q3(1.5)  # type: ignore[arg-type]


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


def test_domain_exception_handler_maps_errors() -> None:
    """Domain errors become 400s; permission denials become 403s with a code."""
    domain_response = domain_exception_handler(InsufficientStock("only 1 left"), {})
    assert domain_response is not None
    assert domain_response.status_code == 400
    assert domain_response.data == {"code": "insufficient_stock", "detail": "only 1 left"}

    denied_response = domain_exception_handler(DRFPermissionDenied(), {})
    assert denied_response is not None
    assert denied_response.status_code == 403
    assert denied_response.data["code"] == "permission_denied"

    domain_denied = domain_exception_handler(PermissionDenied("no role"), {})
    assert domain_denied is not None
    assert domain_denied.status_code == 403
    assert domain_denied.data["code"] == "permission_denied"

    assert domain_exception_handler(ValueError("not a domain error"), {}) is None


def test_audit_log_stub() -> None:
    """log_audit stub executes without crashing."""
    user = MagicMock()
    log_audit(user, "Order", 1, "create", {}, {"id": 1})


def test_role_permission_is_deny_by_default() -> None:
    """Missing allowed_roles denies every authenticated user."""
    permission = RolePermission()
    request = MagicMock()
    request.user.is_authenticated = True
    request.user.role = "owner"

    view = MagicMock()
    del view.allowed_roles
    assert permission.has_permission(request, view) is False


def test_role_permission_allows_declared_role_only() -> None:
    """RolePermission passes declared roles and refuses everyone else."""
    permission = RolePermission()
    view = MagicMock()
    view.allowed_roles = ("admin", "owner")

    request = MagicMock()
    request.user.is_authenticated = True
    request.user.role = "admin"
    assert permission.has_permission(request, view) is True

    request.user.role = "salesman"
    assert permission.has_permission(request, view) is False

    request.user.is_authenticated = False
    assert permission.has_permission(request, view) is False
