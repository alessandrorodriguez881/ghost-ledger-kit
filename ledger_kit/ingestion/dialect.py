"""CSV dialect detection and locale-aware amount/date parsing."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum


class CsvDialect(StrEnum):
    """Supported CSV dialects."""

    PLAIN = "plain"  # comma separator, dot decimal, YYYY-MM-DD dates
    EUROPEAN = "european"  # semicolon separator, comma decimal, DD/MM/YYYY dates


# Optional minus, dot-grouped thousands or plain digits, then a comma and digits.
# Anything else (12.50, -12.5, 1,234.56, 1,2,3) does not match.
_EUROPEAN_AMOUNT_RE = re.compile(r"-?(?:\d{1,3}(?:\.\d{3})+|\d+),\d+")


def detect_dialect(first_line: str) -> CsvDialect | None:
    """Return the dialect implied by a header line, or None when ambiguous."""
    semicolons = first_line.count(";")
    commas = first_line.count(",")
    if semicolons > 0 and commas == 0:
        return CsvDialect.EUROPEAN
    if commas > 0 and semicolons == 0:
        return CsvDialect.PLAIN
    return None


def parse_amount(raw: str, dialect: CsvDialect) -> Decimal:
    """Parse an amount string; raises InvalidOperation when it is malformed."""
    text = raw.strip()
    if dialect == CsvDialect.EUROPEAN:
        if _EUROPEAN_AMOUNT_RE.fullmatch(text) is None:
            raise InvalidOperation(f"not a European amount: {raw!r}")
        text = text.replace(".", "").replace(",", ".")
    value = Decimal(text)
    if not value.is_finite():
        raise InvalidOperation(f"not a finite amount: {raw!r}")
    return value


def parse_date(raw: str, dialect: CsvDialect) -> date:
    """Parse a date string; raises ValueError when it does not match the dialect."""
    fmt = "%d/%m/%Y" if dialect == CsvDialect.EUROPEAN else "%Y-%m-%d"
    return datetime.strptime(raw.strip(), fmt).date()
