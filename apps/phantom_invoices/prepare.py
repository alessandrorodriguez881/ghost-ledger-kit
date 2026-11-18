"""Pre-processing of the invoice frame before the detectors run (multi-rate quarantine).

Pure functions: the input frame is never modified and nothing reads the clock.
"""

from __future__ import annotations

import pandas as pd

from apps.phantom_invoices.detectors.utils import (
    as_decimal,
    as_text,
    is_missing,
    n1_key,
    source_ref_key,
    tax_key,
)

# Quarantine reason of an invoice that mixes VAT rates (out of scope, OD-PI-08).
MULTI_RATE_REASON: str = "multi_rate_invoice_out_of_scope"


def _raw_text(value: object) -> str:
    """Return a cell as text for the quarantine record; a missing cell becomes ''."""
    if is_missing(value):
        return ""
    return str(value)


def _line_or_none(value: object) -> int | None:
    """Return the source_line cell as an int, or None when the row has no line (XML invoice)."""
    if value is None or value is pd.NA or is_missing(value):
        return None
    try:
        return int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return None


def quarantine_multi_rate(invoices: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    """Remove every row of a multi-rate invoice; return (clean_frame, quarantine_records).

    A multi-rate invoice is a group of rows with the same supplier tax_key and the same N1 invoice
    number but more than one distinct vat_rate. Rows with a missing vat_rate do not count as a
    different rate. The input frame is not modified; the clean frame has a fresh RangeIndex.
    """
    if not isinstance(invoices, pd.DataFrame) or invoices.empty:
        return invoices, []
    records = invoices.to_dict("records")
    groups: dict[tuple[str, str], list[int]] = {}
    for pos, record in enumerate(records):
        tax = tax_key(as_text(record.get("supplier_tax_id")) or "")
        n1 = n1_key(as_text(record.get("invoice_number")) or "")
        if tax and n1:
            groups.setdefault((tax, n1), []).append(pos)
    bad: set[int] = set()
    for positions in groups.values():
        rates = {as_decimal(records[p].get("vat_rate")) for p in positions} - {None}
        if len(rates) > 1:  # Decimal("21") and Decimal("21.00") are one rate
            bad.update(positions)
    keep = [pos for pos in range(len(records)) if pos not in bad]
    clean = invoices.iloc[keep].reset_index(drop=True)
    refs = {pos: str(records[pos].get("source_ref")) for pos in bad}
    quarantined = [
        {
            "source_file": records[pos].get("source_file"),
            "source_row": records[pos].get("source_row"),
            "source_line": _line_or_none(records[pos].get("source_line")),
            "reason": MULTI_RATE_REASON,
            "raw": {str(k): _raw_text(v) for k, v in records[pos].items()},
        }
        for pos in sorted(bad, key=lambda p: (source_ref_key(refs[p]), p))
    ]
    return clean, quarantined
