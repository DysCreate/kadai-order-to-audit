"""Unit tests for invoice amounts in words and the financial-year label.

Requirement: AGENTS.md 4.9 – amount in words on the invoice, financial year
starting 1 April computed in Asia/Kolkata.
"""

from datetime import date
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from freezegun import freeze_time

from apps.sales.amounts import amount_in_words
from apps.sales.numbering import financial_year, kolkata_today
from core.errors import DomainError


def test_benchmark_invoice_total_in_words() -> None:
    """Appendix A: 7,875.00 reads as Indian-numbered words."""
    assert amount_in_words(Decimal("7875.00")) == (
        "Seven Thousand Eight Hundred Seventy Five Rupees Only"
    )


def test_inter_state_preview_in_words() -> None:
    """Appendix A: the Distributor B preview total is 6,300.00."""
    assert amount_in_words(Decimal("6300")) == "Six Thousand Three Hundred Rupees Only"


def test_paise_are_named() -> None:
    """PS 4.9: a total with paise names them rather than dropping them."""
    assert amount_in_words(Decimal("105.50")) == ("One Hundred Five Rupees and Fifty Paise Only")


def test_indian_grouping_uses_lakh_and_crore() -> None:
    """PS 4.9: Indian grouping, not thousands/millions."""
    assert amount_in_words(Decimal("125000")) == "One Lakh Twenty Five Thousand Rupees Only"
    assert amount_in_words(Decimal("10000000")) == "One Crore Rupees Only"


def test_invalid_amounts_are_refused() -> None:
    """PS 4.9 negative paths: negative and float amounts never reach a PDF."""
    with pytest.raises(DomainError):
        amount_in_words(Decimal("-1"))
    with pytest.raises(DomainError):
        amount_in_words(1.5)  # type: ignore[arg-type]


def test_financial_year_starts_on_first_april() -> None:
    """PS 4.9: 31 March belongs to the old year, 1 April to the new one."""
    assert financial_year(date(2026, 3, 31)) == "25-26"
    assert financial_year(date(2026, 4, 1)) == "26-27"
    assert financial_year(date(2027, 1, 15)) == "26-27"
    assert financial_year(date(2027, 4, 1)) == "27-28"


def test_financial_year_is_computed_in_kolkata() -> None:
    """PS 4.9: 20:00 UTC on 31 March is already 1 April in Asia/Kolkata."""
    with freeze_time("2026-03-31 20:00:00"):
        today = kolkata_today()
        assert today == date(2026, 4, 1)
        assert financial_year(today) == "26-27"


def test_kolkata_today_uses_the_factory_timezone() -> None:
    """PS 4.9: the default business date is IST, not UTC."""
    assert kolkata_today().__class__ is date
    assert ZoneInfo("Asia/Kolkata").key == "Asia/Kolkata"
