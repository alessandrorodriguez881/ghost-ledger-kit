"""Bank-statement CSV reader: plain and European dialects, encoding fallback, quarantine."""

from __future__ import annotations

import csv
import io
from decimal import InvalidOperation
from pathlib import Path
from typing import IO, Any, Literal, TypeVar

from ledger_kit.ingestion.dialect import CsvDialect, detect_dialect, parse_amount, parse_date
from ledger_kit.models import Transaction

T = TypeVar("T")
IngestionResult = tuple[list[T], list[dict]]  # (valid models, quarantine records)

# Encodings tried in order when the source is bytes (BOM-aware UTF-8, then Windows-1252).
ENCODINGS_TRIED: tuple[str, ...] = ("utf-8-sig", "cp1252")

# Columns that must hold a non-blank value in every data row.
MANDATORY_COLUMNS: tuple[str, ...] = ("date", "amount", "currency", "counterparty", "description")

_DELIMITERS: dict[CsvDialect, str] = {CsvDialect.PLAIN: ",", CsvDialect.EUROPEAN: ";"}
_DEFAULT_STREAM_NAME = "stream"


def _read_source(source: Path | str | IO[str] | IO[bytes]) -> tuple[str | bytes, str]:
    """Return the raw content (str or bytes) and the default source_file name."""
    if isinstance(source, (str, Path)):
        path = Path(source)
        return path.read_bytes(), path.name
    content = source.read()
    name = getattr(source, "name", None)
    return content, Path(name).name if isinstance(name, str) and name else _DEFAULT_STREAM_NAME


def _decode(content: str | bytes) -> str | None:
    """Decode bytes with the fallback chain; None when no encoding works."""
    if isinstance(content, str):
        return content
    for encoding in ENCODINGS_TRIED:
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None


def _first_non_empty_line(text: str) -> str:
    """Return the first line of `text` that is not blank."""
    for line in text.splitlines():
        if line.strip():
            return line
    return ""


def _blank(value: str | None) -> bool:
    """True when a cell is missing or whitespace-only."""
    return value is None or not value.strip()


def _quarantine(source_file: str, row_index: int, reason: str, raw: dict[str, Any]) -> dict:
    """Build a quarantine record for one data row."""
    return {"source_file": source_file, "source_row": row_index, "reason": reason, "raw": raw}


def _undecodable(file_name: str) -> dict:
    """Build the whole-file quarantine record for an undecodable file."""
    return {
        "source_file": file_name,
        "source_row": None,
        "reason": "undecodable_file",
        "raw": "",
        "encoding_tried": list(ENCODINGS_TRIED),
    }


def parse_csv(
    source: Path | str | IO[str] | IO[bytes],
    *,
    dialect: Literal["plain", "european"] | None = None,
    source_file: str | None = None,
) -> IngestionResult[Transaction]:
    """Parse a bank-statement CSV. Returns (transactions, quarantined)."""
    content, default_name = _read_source(source)
    file_name = source_file or default_name

    text = _decode(content)
    if text is None:
        return [], [_undecodable(file_name)]

    if not text.strip():
        return [], []

    if dialect is None:
        first_line = _first_non_empty_line(text)
        resolved = detect_dialect(first_line)
        if resolved is None:
            return [], [
                {
                    "source_file": file_name,
                    "source_row": None,
                    "reason": "ambiguous_dialect",
                    "raw": first_line,
                    "first_line": first_line,
                }
            ]
    else:
        resolved = CsvDialect(dialect)

    reader = csv.DictReader(io.StringIO(text, newline=""), delimiter=_DELIMITERS[resolved])
    transactions: list[Transaction] = []
    quarantined: list[dict] = []

    for row_index, row in enumerate(reader):
        raw = {k: v for k, v in row.items() if k is not None}

        missing = next((c for c in MANDATORY_COLUMNS if _blank(row.get(c))), None)
        if missing is not None:
            quarantined.append(_quarantine(file_name, row_index, f"missing_field:{missing}", raw))
            continue

        try:
            parsed_date = parse_date(row["date"], resolved)
        except ValueError:
            quarantined.append(_quarantine(file_name, row_index, "unparseable_date", raw))
            continue

        try:
            signed = parse_amount(row["amount"], resolved)
        except InvalidOperation:
            quarantined.append(_quarantine(file_name, row_index, "unparseable_amount", raw))
            continue

        iban_cell = row.get("iban")
        transactions.append(
            Transaction(
                date=parsed_date,
                amount=abs(signed),
                flow="debit" if signed < 0 else "credit",
                currency=row["currency"].strip(),
                counterparty=row["counterparty"].strip(),
                description=row["description"].strip(),
                iban=None if _blank(iban_cell) else iban_cell,
                source_file=file_name,
                source_row=row_index,
                source_ref=f"{file_name}:{row_index}",
            )
        )

    return transactions, quarantined
