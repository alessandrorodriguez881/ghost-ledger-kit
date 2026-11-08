"""Supplier-master reader: plain-dialect CSV into Supplier models, with quarantine."""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import IO

from ledger_kit.ingestion.csv_reader import (
    IngestionResult,
    _blank,
    _decode,
    _quarantine,
    _read_source,
    _undecodable,
)
from ledger_kit.models import Supplier

# Columns that must hold a non-blank value in every supplier row (REQ-ING-32).
MANDATORY_COLUMNS: tuple[str, ...] = ("supplier_name", "tax_id")


def parse_suppliers(
    source: Path | str | IO[str] | IO[bytes],
    *,
    source_file: str | None = None,
) -> IngestionResult[Supplier]:
    """Parse a supplier-master CSV (supplier_name, tax_id, optional iban)."""
    content, default_name = _read_source(source)
    file_name = source_file or default_name

    text = _decode(content)
    if text is None:
        return [], [_undecodable(file_name)]
    if not text.strip():
        return [], []

    suppliers: list[Supplier] = []
    quarantined: list[dict] = []
    reader = csv.DictReader(io.StringIO(text, newline=""), delimiter=",")
    for row_index, row in enumerate(reader):
        raw = {k: v for k, v in row.items() if k is not None}

        missing = next((c for c in MANDATORY_COLUMNS if _blank(row.get(c))), None)
        if missing is not None:
            quarantined.append(_quarantine(file_name, row_index, f"missing_field:{missing}", raw))
            continue

        iban_cell = row.get("iban")
        suppliers.append(
            Supplier(
                supplier_name=row["supplier_name"],
                tax_id=row["tax_id"],
                iban=None if _blank(iban_cell) else iban_cell,
                source_file=file_name,
                source_row=row_index,
                source_ref=f"{file_name}:{row_index}",
            )
        )

    return suppliers, quarantined
