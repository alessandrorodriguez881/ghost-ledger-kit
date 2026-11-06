# ledger-core — Design

## Overview

This document describes the internal design of the `ledger_kit` shared template library. It translates the requirements in `requirements.md` into concrete module boundaries, class/function signatures, data-flow decisions, and test architecture. Implementation tasks (in `tasks.md`) will reference sections of this document.

---

## 1 — Module map

```
ledger_kit/
├── __init__.py                  # re-exports Transaction, Alert
├── models.py                    # Pydantic models: Transaction, Alert
├── ingestion/
│   ├── __init__.py
│   ├── csv_reader.py            # parse_csv() — bank-statement CSVs
│   ├── dialect.py               # CsvDialect enum, detect_dialect, parse_amount, parse_date
│   ├── invoice_reader.py        # parse_invoice() — CSV + JSON invoices
│   └── normaliser.py            # normalise() — merge sources → DataFrame
├── detectors/
│   ├── __init__.py              # re-exports register, auto_discover, run_all
│   ├── base.py                  # DetectorResult, DetectorError
│   └── registry.py              # _REGISTRY dict, decorator + runner
├── ui/
│   ├── __init__.py
│   └── reference_app.py         # Streamlit reference page
├── utils/
│   ├── __init__.py
│   ├── money.py                 # round_to_cents, format_amount, format_as_european
│   └── anonymise.py             # scrub()
└── defaults.toml                # shared threshold + format defaults
```

---

## 2 — Data models (`ledger_kit/models.py`)

The two canonical Pydantic v2 models are defined here and nowhere else. All other modules import from this file.

### 2.1 `Transaction`

```python
from __future__ import annotations
from datetime import date
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, Field
import uuid

class Transaction(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    date: date
    amount: Decimal          # always positive; direction in `flow`
    flow: Literal["debit", "credit"]
    currency: str            # ISO 4217
    counterparty: str
    description: str
    iban: str | None = None  # optional; stored verbatim
    source_file: str
    source_row: int          # 0-based
    source_ref: str          # f"{source_file}:{source_row}"
    tags: list[str] = []

    model_config = {"frozen": True}  # immutable after construction
```

`amount` is always positive. Sign is encoded in `flow`. This is enforced by the CSV reader (§3.2) not by the model itself, so the model can also be constructed directly in tests with any positive `Decimal`.

### 2.2 `Alert`

```python
class Alert(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    detector: str
    severity: Literal["info", "warning", "critical"]
    title: str
    source_refs: list[str]   # non-empty; each must exist in the ledger
    data: dict               # detector-specific payload
    explanation: str = ""    # populated only by the explanation layer

    model_config = {"frozen": True}
```

### 2.3 Quarantine record

Quarantined rows and files are represented as plain `dict` objects (not Pydantic models) to avoid validation failures on malformed data. The shape is:

```python
{
    "source_file": str,
    "source_row": int | None,   # None for whole-file quarantine
    "reason": str,              # e.g. "ambiguous_dialect", "missing_field:amount",
                                #       "undecodable_file"
    "raw": dict | str,          # the original row dict or the problematic line
    # whole-file quarantine may also include:
    "encoding_tried": list[str],  # e.g. ["utf-8-sig", "cp1252"]
    "first_line": str,            # first line that triggered ambiguity (dialect quarantine)
}
```

---

## 3 — Ingestion layer

### 3.1 Dialect detection (`ledger_kit/ingestion/dialect.py`)

This module is responsible for the two decisions that differ between plain and European CSVs: the field delimiter and the amount/date format. It is a pure utility module with no side-effects. Amount formatting for test round-trips lives in `money.py` (see §5).

#### `CsvDialect` enum

```python
from enum import Enum

class CsvDialect(str, Enum):
    PLAIN    = "plain"     # comma sep, dot decimal, YYYY-MM-DD dates
    EUROPEAN = "european"  # semicolon sep, comma decimal, DD/MM/YYYY dates
```

#### `detect_dialect(first_line: str) -> CsvDialect | None`

Inspects a single header line (the first non-empty line of the file).

Decision tree (REQ-ING-20):
1. Count `;` vs `,` occurrences in `first_line`.
2. If `;` count > 0 and `,` count == 0 → return `CsvDialect.EUROPEAN`.
3. If `,` count > 0 and `;` count == 0 → return `CsvDialect.PLAIN`.
4. Otherwise (both present, or neither) → return `None` (caller quarantines the file with `reason="ambiguous_dialect"`).

Note: the header line alone determines the delimiter. Amount-pattern detection (comma-as-decimal) is deferred to `parse_amount` and used only when parsing actual data rows.

#### `parse_amount(raw: str, dialect: CsvDialect) -> Decimal`

- **PLAIN**: strip whitespace, convert directly with `Decimal(raw)`. Raises `InvalidOperation` on failure.
- **EUROPEAN**: strip whitespace, remove all `.` (thousands separator), replace `,` with `.`, then `Decimal(cleaned)`. If the cleaned string cannot be parsed as a `Decimal`, raises `InvalidOperation`.
- A leading `-` is valid for both dialects (REQ-ING-23).
- Callers catch `InvalidOperation` and quarantine the row with `reason="unparseable_amount"`.

#### `parse_date(raw: str, dialect: CsvDialect) -> date`

- **PLAIN**: `datetime.strptime(raw.strip(), "%Y-%m-%d").date()`
- **EUROPEAN**: `datetime.strptime(raw.strip(), "%d/%m/%Y").date()`
- Raises `ValueError` on failure; callers quarantine with `reason="unparseable_date"`.

### 3.2 Bank-statement CSV reader (`ledger_kit/ingestion/csv_reader.py`)

#### Encoding strategy (OD-3 resolution)

Before any parsing occurs the reader decodes the raw bytes into a string. Two encodings are tried in order:

1. `utf-8-sig` (handles UTF-8 with BOM, which some Excel exports produce)
2. `cp1252` (Windows-1252; common in Spanish bank exports; contains the € sign unlike latin-1)

If a `source` argument is already a text stream (`IO[str]`), encoding detection is skipped.

If both encodings fail to decode the file cleanly (`UnicodeDecodeError` on the full content), the **entire file** is quarantined with `reason="undecodable_file"` and `encoding_tried=["utf-8-sig", "cp1252"]`. No rows are emitted.

The resolved encoding is stored in the ingestion result metadata so the Streamlit page can display it.

#### Public API

```python
from pathlib import Path
from typing import IO, Literal

IngestionResult = tuple[list[Transaction], list[dict]]

def parse_csv(
    source: Path | str | IO[str] | IO[bytes],
    *,
    dialect: Literal["plain", "european"] | None = None,
    source_file: str | None = None,
) -> IngestionResult:
    """Parse a bank-statement CSV. Returns (transactions, quarantined)."""
```

#### Processing flow

```
receive source (path, text stream, or bytes stream)
  │
  ├─ if bytes: try utf-8-sig → try cp1252 → fail → quarantine whole file (undecodable_file)
  │
  ├─ read first non-empty line from text content
  │
  ├─ if dialect is None → detect_dialect(first_line)
  │     └─ None returned → quarantine whole file (ambiguous_dialect, includes first_line)
  │
  ├─ use stdlib csv.DictReader with dialect's separator
  │
  └─ for each row (0-based index):
        ├─ extract mandatory fields (date, amount, currency, counterparty, description)
        ├─ any missing/blank field → quarantine row (reason="missing_field:<name>")
        ├─ parse_date() raises ValueError → quarantine row (reason="unparseable_date")
        ├─ parse_amount() raises InvalidOperation → quarantine row (reason="unparseable_amount")
        ├─ apply sign:
        │     amount < 0 → flow="debit",  Transaction.amount = abs(amount)
        │     amount >= 0 → flow="credit", Transaction.amount = amount
        └─ build Transaction(source_ref=f"{source_file}:{row_index}"), append to valid list
```

Key implementation notes:
- Uses stdlib `csv.DictReader`, not pandas, to parse row by row without type coercion.
- `source_row` is the 0-based data-row index (header row does not count).
- `source_file` defaults to `Path(source).name` when `source` is a path; callers may override.
- When given a text stream, the function reads it fully, splits on newlines, and processes from the start; no seek is required.

### 3.3 Invoice reader (`ledger_kit/ingestion/invoice_reader.py`)

#### Public API

```python
def parse_invoice(
    source: Path | str | IO,
    *,
    fmt: Literal["csv", "json"] | None = None,
    source_file: str | None = None,
) -> IngestionResult:
    """Parse a CSV or JSON (FATURA-style) invoice file."""
```

- Format is auto-detected from the file extension when `fmt` is `None`; `.json` → JSON path, otherwise CSV path.
- JSON path: load with `json.load`, iterate array, convert all amount fields to `Decimal` regardless of whether they arrive as `str` or `int/float`.
- CSV path: uses `csv.DictReader` with comma separator (invoices are assumed plain format).
- Same quarantine semantics as the bank-CSV reader.
- Encoding strategy: same two-step `utf-8-sig` → `cp1252` fallback as `parse_csv`.

### 3.4 Normaliser (`ledger_kit/ingestion/normaliser.py`)

#### Public API

```python
NormaliseResult = tuple[pd.DataFrame, list[dict]]

def normalise(
    *sources: list[Transaction],
) -> NormaliseResult:
    """Merge transaction lists into a canonical DataFrame. Returns (ledger, quarantined)."""
```

#### Processing flow

1. Concatenate all source lists into a single flat list.
2. For each `Transaction`, verify required fields are non-null (belt-and-suspenders after Pydantic).
3. Build a `pd.DataFrame` from `[t.model_dump() for t in transactions]`.
4. Ensure column dtypes match the canonical schema (REQ-ING-13): `amount` and `date` remain `object` dtype (Python `Decimal` and `datetime.date`); `source_row` is `int64`.
5. Return `(df, quarantine_list)`.

The normaliser does **not** re-parse anything. Type safety is guaranteed by the Pydantic instances passed in.

---

## 4 — Detector interface and registry

### 4.1 Base types (`ledger_kit/detectors/base.py`)

```python
from dataclasses import dataclass
from ledger_kit.models import Alert

@dataclass(frozen=True)
class DetectorResult:
    name: str
    alerts: list[Alert]

class DetectorError(Exception):
    """Raised internally when a detector fails; caught by run_all."""
    def __init__(self, name: str, cause: Exception) -> None:
        self.name = name
        self.cause = cause
        super().__init__(f"Detector '{name}' failed: {cause}")
```

### 4.2 Registry (`ledger_kit/detectors/registry.py`)

```python
import importlib
import logging
import pkgutil
from collections.abc import Callable
import pandas as pd
from ledger_kit.models import Alert
from ledger_kit.detectors.base import DetectorResult

_REGISTRY: dict[str, Callable[[pd.DataFrame], list[Alert]]] = {}
_log = logging.getLogger(__name__)

def register(name: str):
    """Decorator that registers a detector function under `name`."""
    def decorator(fn: Callable) -> Callable:
        if name in _REGISTRY:
            raise ValueError(f"Detector '{name}' is already registered.")
        _REGISTRY[name] = fn
        return fn
    return decorator

def auto_discover(package: str) -> None:
    """Import all modules in `package` in sorted name order, triggering @register decorators."""
    pkg = importlib.import_module(package)
    modules = sorted(
        (module_name for _, module_name, _ in pkgutil.walk_packages(
            pkg.__path__, prefix=f"{package}."
        ))
    )
    for module_name in modules:
        importlib.import_module(module_name)

def run_all(ledger: pd.DataFrame) -> list[DetectorResult]:
    """Run every registered detector in insertion order; isolate failures per detector."""
    results: list[DetectorResult] = []
    for name, fn in _REGISTRY.items():
        try:
            alerts = fn(ledger)
        except Exception as exc:
            _log.warning("Detector '%s' raised %s: %s", name, type(exc).__name__, exc)
            alerts = []
        results.append(DetectorResult(name=name, alerts=alerts))
    return results

def registered_names() -> list[str]:
    """Return names of all currently registered detectors, in insertion order."""
    return list(_REGISTRY.keys())

def _clear_registry() -> None:
    """Remove all registered detectors. For use in tests only."""
    _REGISTRY.clear()
```

**OD-2 resolution**: `auto_discover` sorts module names before importing, so the discovery order is deterministic regardless of filesystem traversal order. `run_all` and `registered_names` use insertion order (Python 3.7+ dict guarantee), which is therefore also deterministic.

**OD-4 resolution**: `_clear_registry()` is exposed as a private function. Test fixtures use it in teardown via `autouse` or explicit `yield` fixtures to prevent registry state leaking between tests.

`_REGISTRY` is module-level state initialised once at import time. `auto_discover` is idempotent within a process (Python's import system caches modules); calling it twice does not double-register.

### 4.3 Public re-exports (`ledger_kit/detectors/__init__.py`)

```python
from ledger_kit.detectors.registry import (
    register, auto_discover, run_all, registered_names, _clear_registry,
)
from ledger_kit.detectors.base import DetectorResult, DetectorError

__all__ = [
    "register", "auto_discover", "run_all", "registered_names", "_clear_registry",
    "DetectorResult", "DetectorError",
]
```

---

## 5 — Money utilities (`ledger_kit/utils/money.py`)

This is the **single point of truth** for all monetary arithmetic and formatting (REQ-MON-03, Finance Rule 4). The European-format string helper previously considered for `dialect.py` (OD-1) lives here instead, making it available both to the property tests (as the inverse of `dialect.parse_amount`) and to any future export or display feature.

```python
from decimal import Decimal, ROUND_HALF_UP

def round_to_cents(amount: Decimal) -> Decimal:
    """Round to two decimal places using ROUND_HALF_UP (Finance Rule 3)."""
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def format_amount(amount: Decimal, currency: str = "EUR") -> str:
    """Format to European locale string, e.g. '1.234,56 EUR' (Finance Rule 4)."""
    rounded = round_to_cents(amount)
    sign = "-" if rounded < 0 else ""
    abs_val = abs(rounded)
    integer_part, _, frac_part = f"{abs_val:.2f}".partition(".")
    grouped = _group_thousands(integer_part)
    return f"{sign}{grouped},{frac_part} {currency}"

def format_as_european(amount: Decimal) -> str:
    """Format a Decimal as a bare European amount string without currency code.

    Produces strings like '1.234,56' and '-12,50'. Used as the inverse of
    dialect.parse_amount(CsvDialect.EUROPEAN) in property-based tests (REQ-ING-27).
    """
    rounded = round_to_cents(amount)
    sign = "-" if rounded < 0 else ""
    abs_val = abs(rounded)
    integer_part, _, frac_part = f"{abs_val:.2f}".partition(".")
    grouped = _group_thousands(integer_part)
    return f"{sign}{grouped},{frac_part}"

def _group_thousands(integer_str: str) -> str:
    """Insert European thousands separator (full stop) every three digits."""
    s = integer_str[::-1]
    chunks = [s[i:i + 3] for i in range(0, len(s), 3)]
    return ".".join(chunks)[::-1]
```

---

## 6 — PII utilities (`ledger_kit/utils/anonymise.py`)

```python
from ledger_kit.models import Transaction

_COUNTERPARTY_PLACEHOLDER = "REDACTED"
_IBAN_PLACEHOLDER = "DE00000000000000000000"

def scrub(transaction: Transaction) -> Transaction:
    """Replace PII fields with placeholders before passing to LLM layer."""
    return transaction.model_copy(update={
        "counterparty": _COUNTERPARTY_PLACEHOLDER,
        "iban": _IBAN_PLACEHOLDER if transaction.iban is not None else None,
    })
```

---

## 7 — Streamlit reference page (`ledger_kit/ui/reference_app.py`)

### 7.1 Page layout

```
┌─────────────────────────────────────────────┐
│  Ghost Ledger Kit — Ledger Analyser         │
│  [Upload CSV files]                          │
│                                              │
│  ── Summary ─────────────────────────────── │
│  🔴 critical: N  🟡 warning: N  🔵 info: N  │
│                                              │
│  ── ⚠ Quarantined rows (N) ──  [collapsible] │
│     file:row  reason  raw value             │
│                                              │
│  ── Alerts ─────────────────────────────── │
│  ▶ [critical] Duplicate invoice — INV-42   │
│      Detector: duplicate_invoice            │
│      Source refs: invoice.csv:3             │
│      ┌─────────────────────────────────┐   │
│      │  highlighted ledger row        │   │
│      └─────────────────────────────────┘   │
│  ▶ …                                        │
└─────────────────────────────────────────────┘
```

### 7.2 Key implementation decisions

**Session state**: Streamlit re-runs the script on every interaction. The ingestion result and detector results are cached in `st.session_state` keyed by a hash of the uploaded file bytes, so re-runs do not re-parse unchanged files.

**Highlighted rows**: For each alert, the source rows are displayed using `st.dataframe` with a `pandas.Styler` that applies `background-color: #fff3cd` (Bootstrap warning yellow) to the matching rows. The DataFrame shown is a slice of the full ledger containing only the referenced rows, with `amount` formatted via `format_amount`.

**Severity badge**: Rendered as a coloured emoji prefix: 🔴 critical, 🟡 warning, 🔵 info. No HTML injection; plain Unicode emoji is sufficient for Streamlit.

**Encoding passthrough (OD-3 resolution)**: `parse_csv` accepts `IO[bytes]` directly. Streamlit's `UploadedFile` objects are byte streams; the page passes them straight to `parse_csv` without wrapping in `TextIOWrapper`. The reader tries `utf-8-sig` first (handles BOM), then `cp1252` (Spanish Windows exports with the € sign). If both fail, the whole file is quarantined with `reason="undecodable_file"` and the Streamlit page shows that in the quarantine section. The resolved encoding name is surfaced in a tooltip on the file summary line.

**No app registry pre-loaded**: The reference page calls `auto_discover` on `ledger_kit.detectors` only, which at the template level contains no detectors. App-specific pages (e.g. `apps/phantom_invoices/app.py`) call `auto_discover("apps.phantom_invoices.detectors")` before the render loop.

### 7.3 Streamlit component sketch

```python
import hashlib, io
import streamlit as st
from ledger_kit.ingestion.csv_reader import parse_csv
from ledger_kit.ingestion.normaliser import normalise
from ledger_kit.detectors import run_all, auto_discover
from ledger_kit.utils.money import format_amount

st.set_page_config(page_title="Ghost Ledger Kit", layout="wide")
st.title("Ghost Ledger Kit — Ledger Analyser")

uploaded = st.file_uploader("Upload bank CSV files", type=["csv"], accept_multiple_files=True)

if uploaded:
    all_txns, all_quarantine = [], []
    for f in uploaded:
        file_bytes = f.read()
        cache_key = hashlib.sha256(file_bytes).hexdigest()
        if cache_key not in st.session_state:
            txns, q = parse_csv(io.BytesIO(file_bytes), source_file=f.name)
            st.session_state[cache_key] = (txns, q)
        txns, q = st.session_state[cache_key]
        all_txns.extend(txns)
        all_quarantine.extend(q)

    ledger, norm_quarantine = normalise(all_txns)
    all_quarantine.extend(norm_quarantine)

    results = run_all(ledger)
    all_alerts = [a for r in results for a in r.alerts]

    # ... render summary, quarantine section, alert cards
```

---

## 8 — Test architecture

### 8.1 File layout

```
tests/
├── conftest.py                        # shared fixtures
├── ingestion/
│   ├── test_csv_reader.py             # Tier 1+2 for parse_csv
│   ├── test_dialect.py                # Tier 1+2 for detect_dialect, parse_amount, parse_date
│   ├── test_invoice_reader.py         # Tier 1+2 for parse_invoice
│   └── test_normaliser.py             # Tier 1+2+3 (round-trip properties)
├── test_models.py                     # Pydantic model validation
├── test_money.py                      # round_to_cents, format_amount, format_as_european
├── test_anonymise.py                  # scrub()
└── detectors/
    └── test_registry.py               # register, auto_discover, run_all, _clear_registry
```

### 8.2 Shared fixtures (`tests/conftest.py`)

```python
import pytest
import pandas as pd
from decimal import Decimal
from datetime import date
from ledger_kit.models import Transaction

@pytest.fixture
def empty_ledger() -> pd.DataFrame:
    """Zero-row DataFrame with canonical schema columns."""
    ...

@pytest.fixture
def single_row_ledger() -> pd.DataFrame:
    """One valid Transaction row."""
    ...

@pytest.fixture
def clean_ledger_10() -> pd.DataFrame:
    """Ten rows with no anomalies; uses synthetic PII-safe data."""
    ...
```

Synthetic names follow Finance Rule 5: `Ana García`, `Luigi Rossi`, `Sophie Dupont`.
IBANs use the reserved test prefix `DE00000000000000000000`.

### 8.3 Property-based tests (`tests/ingestion/test_normaliser.py`)

#### Property 1 — Signed-amount round-trip (REQ-ING-15)

```python
from hypothesis import given, settings
from hypothesis import strategies as st
from decimal import Decimal
import csv, io

@settings(max_examples=200)
@given(
    signed=st.decimals(
        min_value=Decimal("-1000000"),
        max_value=Decimal("1000000"),
        places=2,
        allow_nan=False,
        allow_infinity=False,
    )
)
def test_signed_amount_round_trip(signed: Decimal):
    """abs(amount) and flow are preserved through CSV write → parse_csv → normalise."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["date","amount","currency","counterparty","description"])
    writer.writeheader()
    writer.writerow({
        "date": "2026-01-15", "amount": str(signed),
        "currency": "EUR", "counterparty": "Test", "description": "x",
    })
    buf.seek(0)
    txns, q = parse_csv(buf, dialect="plain", source_file="test.csv")
    assert len(q) == 0
    t = txns[0]
    assert t.amount == abs(signed)
    assert t.flow == ("debit" if signed < 0 else "credit")
    reconstructed = -t.amount if t.flow == "debit" else t.amount
    assert reconstructed == signed
```

#### Property 2 — Date round-trip (REQ-ING-16)

```python
@settings(max_examples=200)
@given(d=st.dates(min_value=date(1900, 1, 1), max_value=date(2100, 12, 31)))
def test_date_round_trip_plain(d: date):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["date","amount","currency","counterparty","description"])
    writer.writeheader()
    writer.writerow({"date": d.isoformat(), "amount": "10.00",
                     "currency": "EUR", "counterparty": "Test", "description": "x"})
    buf.seek(0)
    txns, q = parse_csv(buf, dialect="plain", source_file="test.csv")
    assert len(q) == 0
    assert txns[0].date == d
```

#### Property 3 — European amount format round-trip (REQ-ING-27)

The inverse formatter `format_as_european` is imported from `ledger_kit.utils.money` (OD-1 resolution).

```python
from ledger_kit.utils.money import format_as_european
from ledger_kit.ingestion.dialect import CsvDialect, parse_amount

@settings(max_examples=200)
@given(
    amount=st.decimals(
        min_value=Decimal("0"),
        max_value=Decimal("999999.99"),
        places=2,
        allow_nan=False,
        allow_infinity=False,
    ),
    negative=st.booleans(),
)
def test_european_amount_round_trip(amount: Decimal, negative: bool):
    """format_as_european then parse_amount(EUROPEAN) is the identity function."""
    signed = -amount if negative else amount
    european_str = format_as_european(signed)   # lives in money.py
    parsed = parse_amount(european_str, CsvDialect.EUROPEAN)
    assert parsed == signed
```

### 8.4 Tier 2 edge cases for the CSV reader (`tests/ingestion/test_csv_reader.py`)

| Test name | Scenario |
|---|---|
| `test_empty_file_returns_empty` | Empty file → `([], [])` |
| `test_single_row_plain` | One data row, plain dialect |
| `test_single_row_european` | One data row, European dialect |
| `test_missing_amount_quarantined` | Row without `amount` value → quarantine |
| `test_unparseable_date_quarantined` | `"not-a-date"` → quarantine |
| `test_ambiguous_dialect_quarantines_file` | Header with both `,` and `;` → whole file quarantined |
| `test_ambiguous_dialect_record_includes_first_line` | Quarantine record includes `first_line` key |
| `test_explicit_dialect_overrides_sniff` | `dialect="european"` with `;` file → parsed correctly |
| `test_negative_amount_becomes_debit` | `-100.00` → `amount=Decimal("100.00"), flow="debit"` |
| `test_positive_amount_becomes_credit` | `50.00` → `amount=Decimal("50.00"), flow="credit"` |
| `test_zero_amount_becomes_credit` | `0.00` → `amount=Decimal("0.00"), flow="credit"` |
| `test_european_thousands_separator` | `"1.234,56"` → `Decimal("1234.56")` |
| `test_european_negative_amount` | `"-12,50"` → `amount=Decimal("12.50"), flow="debit"` |
| `test_quarantine_record_has_reason` | Quarantine records include `reason` and `raw` keys |
| `test_utf8_bom_decoded` | File with UTF-8 BOM is decoded correctly as `utf-8-sig` |
| `test_cp1252_decoded` | File with Windows-1252 euro sign (byte `0x80`) decoded correctly |
| `test_undecodable_file_quarantined` | Non-decodable bytes → whole file quarantined, `reason="undecodable_file"`, `encoding_tried` present |

---

## 9 — Configuration (`ledger_kit/defaults.toml`)

```toml
[ingestion]
default_currency = "EUR"
encodings = ["utf-8-sig", "cp1252"]  # tried in order; updated from OD-3

[display]
currency = "EUR"
locale = "european"

[detectors]
# no defaults at library level; apps supply their own thresholds
```

Apps override values in their own `config.toml`. Neither file holds secrets.

---

## 10 — Dependency list

All versions pinned (REQ-PKG-02). Runtime dependencies introduced by `ledger_kit`:

| Package | Version | Purpose |
|---|---|---|
| `pandas` | ≥ 2.0 (pin exact) | Ledger DataFrame |
| `pydantic` | ≥ 2.0 (pin exact) | Transaction and Alert models |
| `streamlit` | ≥ 1.35 (pin exact) | Reference UI page |

Dev/test dependencies:

| Package | Version | Purpose |
|---|---|---|
| `pytest` | ≥ 8.0 | Test runner |
| `hypothesis` | ≥ 6.100 | Property-based tests |
| `freezegun` | any recent | Time freezing in tests |
| `pytest-cov` | any recent | Coverage measurement |
| `ruff` | any recent | Lint + format |

---

## 11 — Open decisions (resolved)

| # | Question | Resolution |
|---|---|---|
| OD-1 | Where does the European amount formatter live? | In `ledger_kit/utils/money.py` as `format_as_european`. `money.py` is the single point of truth for money formatting per Finance Rule 4. `dialect.py` exports no formatter. Property tests import `format_as_european` from `money`. |
| OD-2 | Deterministic `run_all` and `auto_discover` ordering? | `auto_discover` sorts module names before importing. `run_all` iterates `_REGISTRY` in insertion order (Python 3.7+ dict). Both are fully deterministic. |
| OD-3 | File encoding strategy? | Try `utf-8-sig` first (handles BOM), then `cp1252` (Spanish Windows exports, has € sign). If both fail → quarantine whole file with `reason="undecodable_file"` and `encoding_tried=["utf-8-sig","cp1252"]`. `parse_csv` accepts `IO[bytes]` directly; no caller-side `TextIOWrapper` needed. |
| OD-4 | Resettable registry for tests? | `_clear_registry()` private function exposed from `registry.py` and re-exported from `detectors/__init__.py`. Test fixtures call it in teardown. |
