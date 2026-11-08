"""Invoice reader: CSV and JSON invoices into Invoice models, with quarantine."""

from __future__ import annotations

import csv
import io
import json
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import IO, Any, Literal

from ledger_kit.ingestion.csv_reader import (
    IngestionResult,
    _blank,
    _decode,
    _quarantine,
    _read_source,
    _undecodable,
)
from ledger_kit.ingestion.dialect import CsvDialect, parse_amount, parse_date
from ledger_kit.models import Invoice

# Spanish default payment term in days; applied when an invoice has no due_date.
DEFAULT_PAYMENT_TERM_DAYS: int = 30

# Columns that must hold a non-blank value in every invoice row (REQ-ING-30).
MANDATORY_COLUMNS: tuple[str, ...] = (
    "invoice_number",
    "supplier_name",
    "supplier_tax_id",
    "issue_date",
    "base_amount",
    "vat_rate",
    "vat_amount",
    "total",
    "currency",
)
# Amount columns that are always parsed; the two optional ones default to zero.
_REQUIRED_AMOUNTS: tuple[str, ...] = ("base_amount", "vat_rate", "vat_amount", "total")
_OPTIONAL_AMOUNTS: tuple[str, ...] = ("surcharge_amount", "withholding_amount")

_Row = dict[str, Any]


def _cell(value: Any) -> str | None:
    """Turn a JSON value into the string form a CSV cell would have."""
    if value is None:
        return None
    return value if isinstance(value, str) else str(value)


def _build_invoice(row: _Row, file_name: str, row_index: int) -> Invoice | dict:
    """Build an Invoice from a string-valued row, or return a quarantine record."""
    cells = {key: _cell(value) for key, value in row.items() if key is not None}

    for column in MANDATORY_COLUMNS:
        if _blank(cells.get(column)):
            return _quarantine(file_name, row_index, f"missing_field:{column}", row)

    try:
        issue_date = parse_date(cells["issue_date"], CsvDialect.PLAIN)
        due_cell = cells.get("due_date")
        due_date = (
            issue_date + timedelta(days=DEFAULT_PAYMENT_TERM_DAYS)
            if _blank(due_cell)
            else parse_date(due_cell, CsvDialect.PLAIN)
        )
    except ValueError:
        return _quarantine(file_name, row_index, "unparseable_date", row)

    amounts: dict[str, Decimal] = {}
    try:
        for column in _REQUIRED_AMOUNTS:
            amounts[column] = parse_amount(cells[column], CsvDialect.PLAIN)
        for column in _OPTIONAL_AMOUNTS:
            cell = cells.get(column)
            amounts[column] = (
                Decimal("0") if _blank(cell) else parse_amount(cell, CsvDialect.PLAIN)
            )
    except InvalidOperation:
        return _quarantine(file_name, row_index, "unparseable_amount", row)

    if any(value < 0 for value in amounts.values()):
        return _quarantine(file_name, row_index, "negative_amount", row)

    iban_cell = cells.get("iban")
    return Invoice(
        invoice_number=cells["invoice_number"],
        supplier_name=cells["supplier_name"],
        supplier_tax_id=cells["supplier_tax_id"],
        issue_date=issue_date,
        due_date=due_date,
        due_date_is_default=_blank(due_cell),
        iban=None if _blank(iban_cell) else iban_cell,
        currency=cells["currency"].strip(),
        source_file=file_name,
        source_row=row_index,
        source_ref=f"{file_name}:{row_index}",
        **amounts,
    )


def _parse_csv_rows(text: str, file_name: str) -> IngestionResult[Invoice]:
    """Parse plain-dialect CSV text into invoices."""
    invoices: list[Invoice] = []
    quarantined: list[dict] = []
    reader = csv.DictReader(io.StringIO(text, newline=""), delimiter=",")
    for row_index, row in enumerate(reader):
        raw = {k: v for k, v in row.items() if k is not None}
        result = _build_invoice(raw, file_name, row_index)
        if isinstance(result, Invoice):
            invoices.append(result)
        else:
            quarantined.append(result)
    return invoices, quarantined


def _parse_json_rows(text: str, file_name: str) -> IngestionResult[Invoice]:
    """Parse a JSON array of invoice objects into invoices."""
    try:
        document = json.loads(text)
    except json.JSONDecodeError:
        return [], [_file_quarantine(file_name, "invalid_json", text)]
    if not isinstance(document, list):
        return [], [_file_quarantine(file_name, "invalid_json", text)]

    invoices: list[Invoice] = []
    quarantined: list[dict] = []
    for row_index, item in enumerate(document):
        if not isinstance(item, dict):
            quarantined.append(_quarantine(file_name, row_index, "invalid_row", {"value": item}))
            continue
        result = _build_invoice(item, file_name, row_index)
        if isinstance(result, Invoice):
            invoices.append(result)
        else:
            quarantined.append(result)
    return invoices, quarantined


def _file_quarantine(file_name: str, reason: str, raw: str) -> dict:
    """Build a whole-file quarantine record (no row index)."""
    return {"source_file": file_name, "source_row": None, "reason": reason, "raw": raw}


def parse_invoice(
    source: Path | str | IO[str] | IO[bytes],
    *,
    fmt: Literal["csv", "json"] | None = None,
    source_file: str | None = None,
) -> IngestionResult[Invoice]:
    """Parse a CSV or JSON invoice file into Invoice objects."""
    content, default_name = _read_source(source)
    file_name = source_file or default_name

    text = _decode(content)
    if text is None:
        return [], [_undecodable(file_name)]
    if not text.strip():
        return [], []

    resolved = fmt or ("json" if file_name.lower().endswith(".json") else "csv")
    if resolved == "json":
        return _parse_json_rows(text, file_name)
    return _parse_csv_rows(text, file_name)
