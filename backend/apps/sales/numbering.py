"""Document numbering and the Indian financial year.

Invariants protected (AGENTS.md 4.9):
- The financial year starts on 1 April and is computed in Asia/Kolkata, while
  timestamps stay in UTC.
- Numbers follow ``INV/26-27/00001`` and ``CN/26-27/00001``, are allocated from
  a row-locked per-financial-year counter, and never exceed 16 characters.
- A number is only ever handed out inside the caller's transaction, so a
  rolled-back invoice does not consume a number visible to anyone else.
"""

from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo

from django.db import IntegrityError, transaction
from django.utils import timezone

from core.errors import DomainError

from .models import DocumentSequence, DocumentType

KOLKATA = ZoneInfo("Asia/Kolkata")
FINANCIAL_YEAR_START_MONTH = 4
MAX_DOCUMENT_NUMBER_LENGTH = 16


def kolkata_today() -> date:
    """Return today's date in the factory timezone (Asia/Kolkata)."""
    return timezone.localtime(timezone.now(), KOLKATA).date()


def financial_year(on_date: date) -> str:
    """Return the Indian financial year label for a business date, e.g. ``26-27``."""
    start_year = on_date.year if on_date.month >= FINANCIAL_YEAR_START_MONTH else on_date.year - 1
    return f"{start_year % 100:02d}-{(start_year + 1) % 100:02d}"


def _locked_sequence(doc_type: str, year: str) -> DocumentSequence:
    """Lock (or create) the counter row, tolerating a concurrent create."""
    try:
        with transaction.atomic():
            sequence, _created = DocumentSequence.objects.select_for_update().get_or_create(
                doc_type=doc_type,
                financial_year=year,
            )
            return sequence
    except IntegrityError:
        return DocumentSequence.objects.select_for_update().get(
            doc_type=doc_type,
            financial_year=year,
        )


def allocate_document_number(doc_type: str, on_date: date) -> str:
    """Reserve the next number of ``doc_type`` for the financial year of ``on_date``.

    Invariants: the counter row is locked for the duration of the caller's
    transaction, the number fits the 16-character GST limit, and an unknown
    document type is refused.
    """
    if doc_type not in DocumentType.values:
        raise DomainError(f"Unknown document type {doc_type!r}.")

    year = financial_year(on_date)
    sequence = _locked_sequence(doc_type, year)
    sequence.last_number += 1
    sequence.save(update_fields=["last_number"])

    number = f"{doc_type}/{year}/{sequence.last_number:05d}"
    if len(number) > MAX_DOCUMENT_NUMBER_LENGTH:
        raise DomainError(
            f"Document number {number!r} exceeds the {MAX_DOCUMENT_NUMBER_LENGTH}-character limit."
        )
    return number
