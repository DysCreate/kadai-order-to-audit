"""Amount in words for invoices – Indian numbering, pure and deterministic.

Invariants protected: the amount is rounded to paise first and rendered with
the Indian grouping (crore, lakh, thousand), so a printed invoice never
disagrees with its numeric total. Floats are refused.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from core.errors import DomainError
from core.money import q2

_ONES = (
    "",
    "One",
    "Two",
    "Three",
    "Four",
    "Five",
    "Six",
    "Seven",
    "Eight",
    "Nine",
    "Ten",
    "Eleven",
    "Twelve",
    "Thirteen",
    "Fourteen",
    "Fifteen",
    "Sixteen",
    "Seventeen",
    "Eighteen",
    "Nineteen",
)

_TENS = (
    "",
    "",
    "Twenty",
    "Thirty",
    "Forty",
    "Fifty",
    "Sixty",
    "Seventy",
    "Eighty",
    "Ninety",
)


def _two_digits(value: int) -> str:
    if value < 20:
        return _ONES[value]
    tens, ones = divmod(value, 10)
    return f"{_TENS[tens]} {_ONES[ones]}".strip()


def _three_digits(value: int) -> str:
    hundreds, rest = divmod(value, 100)
    parts: list[str] = []
    if hundreds:
        parts.append(f"{_ONES[hundreds]} Hundred")
    if rest:
        parts.append(_two_digits(rest))
    return " ".join(parts)


def _indian_words(value: int) -> str:
    if value == 0:
        return "Zero"
    crore, rest = divmod(value, 10_000_000)
    lakh, rest = divmod(rest, 100_000)
    thousand, hundreds = divmod(rest, 1000)

    parts: list[str] = []
    if crore:
        parts.append(f"{_indian_words(crore)} Crore")
    if lakh:
        parts.append(f"{_two_digits(lakh)} Lakh")
    if thousand:
        parts.append(f"{_two_digits(thousand)} Thousand")
    if hundreds:
        parts.append(_three_digits(hundreds))
    return " ".join(parts)


def amount_in_words(amount: Decimal | str | int) -> str:
    """Return the Indian-English words for a rupee amount.

    Example: ``Decimal("7875")`` -> ``"Seven Thousand Eight Hundred Seventy
    Five Rupees Only"``. Paise are named when present.
    """
    if isinstance(amount, float):
        raise DomainError("An invoice amount must be Decimal, str or int, never float.")
    try:
        value = q2(amount)
    except (InvalidOperation, TypeError) as exc:
        raise DomainError(f"{amount!r} is not a valid amount.") from exc
    if value < 0:
        raise DomainError("An invoice amount cannot be negative.")

    rupees = int(value)
    paise = int((value - rupees) * 100)
    words = f"{_indian_words(rupees)} Rupees"
    if paise:
        return f"{words} and {_two_digits(paise)} Paise Only"
    return f"{words} Only"
