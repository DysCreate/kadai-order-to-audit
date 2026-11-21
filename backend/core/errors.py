"""Domain errors for Kadai.

All business-rule violations raise a subclass of DomainError.
``core.api.domain_exception_handler`` maps these to 4xx responses with a
machine-readable code.
"""


class DomainError(Exception):
    """Base class for all Kadai domain errors."""

    code: str = "domain_error"

    def __init__(self, message: str = "") -> None:
        super().__init__(message)
        self.message = message


class InsufficientStock(DomainError):
    """Raised when a dispatch or issue would take stock below zero."""

    code = "insufficient_stock"


class InvalidUnit(DomainError):
    """Raised when a unit conversion is not defined or a unit is wrong."""

    code = "invalid_unit"


class InvalidMovement(DomainError):
    """Raised when a ledger movement violates the movement rules."""

    code = "invalid_movement"


class OpeningBalanceExists(DomainError):
    """Raised when an opening balance is posted for an item that already moved."""

    code = "opening_balance_exists"


class PriceNotFound(DomainError):
    """Raised when no price list line can resolve a price for an item."""

    code = "price_not_found"


class InvoiceImmutable(DomainError):
    """Raised when an edit is attempted on a posted invoice."""

    code = "invoice_immutable"


class BOMVersionMismatch(DomainError):
    """Raised when a production run references a stale BOM version."""

    code = "bom_version_mismatch"


class InvalidRunState(DomainError):
    """Raised when a production run is asked to make an illegal transition."""

    code = "invalid_run_state"


class DuplicateOrder(DomainError):
    """Raised when a client UUID is reused for a new order."""

    code = "duplicate_order"


class InvalidOrderState(DomainError):
    """Raised when an order is asked to make an illegal state transition."""

    code = "invalid_order_state"
