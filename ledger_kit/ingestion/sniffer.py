"""Format sniffer and the two routers that pick a reader by content, never by file name.

`sniff_format` looks at the first bytes only and routes; it does not validate. The routers
`read_bank_statement` and `read_invoices` sniff, call the matching reader and return its
result. A format the box does not accept gives one `unsupported_format:<kind>` record and no
reader is called (REQ-RF-01, REQ-RF-02).
"""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import IO, Literal, get_args

from ledger_kit.ingestion.csv_reader import IngestionResult, _read_source, parse_csv
from ledger_kit.ingestion.facturae_reader import parse_facturae
from ledger_kit.ingestion.invoice_reader import parse_invoice
from ledger_kit.ingestion.norma43_reader import parse_norma43
from ledger_kit.models import Invoice, Transaction

FormatKind = Literal["csv", "json", "norma43", "facturae", "empty", "unknown"]
FORMAT_KINDS: tuple[str, ...] = get_args(FormatKind)

# Only this many leading bytes are looked at.
SNIFF_BYTES: int = 4096
UTF8_BOM: bytes = b"\xef\xbb\xbf"
# A Norma 43 file starts with a record 11: code `11` followed by bank, branch and account digits.
NORMA43_START = re.compile(rb"11[0-9]{18}")
# The first XML start tag, with an optional namespace prefix; `<?`, `<!--` and `<!DOCTYPE` never
# match because `?` and `!` cannot start a name.
START_TAG = re.compile(rb"<([A-Za-z_][\w.\-]*:)?([A-Za-z_][\w.\-]*)")
FACTURAE_ROOT = b"Facturae"

# What the boxes accept, as shown in the `unsupported_format` message.
BANK_STATEMENT_ACCEPTED = "CSV or Norma 43"
INVOICES_ACCEPTED = "CSV, JSON or Facturae"
# How each kind is named in the `unsupported_format` message.
KIND_DESCRIPTIONS: dict[str, str] = {
    "csv": "this looks like CSV",
    "json": "this looks like JSON",
    "norma43": "this looks like Norma 43",
    "facturae": "this looks like Facturae XML",
    "unknown": "the format is not recognised",
}

Source = Path | str | IO[str] | IO[bytes]

# How a recognised format is named on the pages (REQ-RF-23); `empty` and `unknown` have no label.
FORMAT_LABELS: dict[str, str] = {
    "csv": "CSV",
    "json": "JSON",
    "norma43": "Norma 43",
    "facturae": "Facturae XML",
}


def format_label(kind: str) -> str | None:
    """Return the page label of a sniffed kind, or None when it is empty or not recognised."""
    return FORMAT_LABELS.get(kind)


def _xml_kind(head: bytes) -> FormatKind:
    """Classify an XML document by the local name of its first start tag."""
    match = START_TAG.search(head)
    if match is not None and match.group(2) == FACTURAE_ROOT:
        return "facturae"
    return "unknown"


def sniff_format(data: bytes) -> FormatKind:
    """Return the kind of file `data` looks like, from its first 4096 bytes; never raises."""
    head = bytes(data[:SNIFF_BYTES]).removeprefix(UTF8_BOM)
    first_line = next((line for line in head.splitlines() if line.strip()), None)
    if first_line is None:
        return "empty"
    opening = first_line.lstrip()[:1]
    if opening in (b"[", b"{"):
        return "json"
    if NORMA43_START.match(first_line) is not None:
        return "norma43"
    if opening == b"<":
        return _xml_kind(head)
    if b"," in first_line or b";" in first_line:
        return "csv"
    return "unknown"


def unsupported_message(name: str, kind: str, accepted: str) -> str:
    """Return the plain message shown when a box receives a format it does not accept."""
    return f"{name}: {KIND_DESCRIPTIONS[kind]}; this box accepts {accepted}."


def _unsupported(name: str, kind: str, accepted: str) -> dict:
    """Build the whole-file quarantine record for a format the box does not accept."""
    return {
        "source_file": name,
        "source_row": None,
        "reason": f"unsupported_format:{kind}",
        "raw": unsupported_message(name, kind, accepted),
    }


def _load(source: Source, source_file: str | None) -> tuple[bytes, str, FormatKind]:
    """Read the source once and return its bytes, its file name and the sniffed kind."""
    content, default_name = _read_source(source)
    data = content.encode("utf-8", "replace") if isinstance(content, str) else content
    return data, source_file or default_name, sniff_format(data)


def read_bank_statement(
    source: Source,
    *,
    source_file: str | None = None,
) -> IngestionResult[Transaction]:
    """Read a bank statement (CSV or Norma 43); the content decides, not the extension."""
    data, name, kind = _load(source, source_file)
    if kind == "empty":
        return [], []
    if kind == "csv":
        return parse_csv(io.BytesIO(data), source_file=name)
    if kind == "norma43":
        return parse_norma43(io.BytesIO(data), source_file=name)
    return [], [_unsupported(name, kind, BANK_STATEMENT_ACCEPTED)]


def read_invoices(
    source: Source,
    *,
    source_file: str | None = None,
) -> IngestionResult[Invoice]:
    """Read invoices (CSV, JSON or Facturae); the content decides, not the extension."""
    data, name, kind = _load(source, source_file)
    if kind == "empty":
        return [], []
    if kind in ("csv", "json"):
        return parse_invoice(io.BytesIO(data), fmt=kind, source_file=name)
    if kind == "facturae":
        return parse_facturae(io.BytesIO(data), source_file=name)
    return [], [_unsupported(name, kind, INVOICES_ACCEPTED)]
