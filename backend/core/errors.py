"""Domain errors for Kadai.

All business-rule violations raise a subclass of DomainError.
Views map these to the appropriate 4xx HTTP response with a machine-readable code.
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


class InvoiceImmutable(DomainError):
    """Raised when an edit is attempted on a posted invoice."""

    code = "invoice_immutable"


class BOMVersionMismatch(DomainError):
    """Raised when a production run references a stale BOM version."""

    code = "bom_version_mismatch"


class DuplicateOrder(DomainError):
    """Raised when a client UUID is reused for a new order."""

    code = "duplicate_order"
