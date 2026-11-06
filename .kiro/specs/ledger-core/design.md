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
import hashlib, json

def _deterministic_alert_id(detector: str, source_refs: list[str], data: dict) -> str:
    """Compute a deterministic sha256 id from alert identity fields (CR-LC-1b)."""
    payload = json.dumps(
        {"detector": detector, "source_refs": sorted(source_refs), "data": data},
        sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


class Alert(BaseModel):
    id: str = Field(default="")   # filled by validator below if empty
    detector: str
    severity: Literal["info", "warning", "critical"]
    title: str
    source_refs: list[str]   # non-empty; each must exist in the ledger
    data: dict               # detector-specific payload
    explanation: str = ""    # populated only by the explanation layer

    model_config = {"frozen": True}

    @model_validator(mode="before")
    @classmethod
    def _set_deterministic_id(cls, values):
        if not values.get("id"):
            values["id"] = _deterministic_alert_id(
                values["detector"],
                values["source_refs"],
                values["data"],
            )
        return values
```

`id` is deterministic when not supplied: same `detector`, `source_refs`, and `data` always
produce the same sha256 hex string across process restarts and Streamlit reruns. This makes
the explanation cache keyed on `(alert.id, client_mode)` stable.

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
import re
import types
from collections.abc import Callable, Mapping
from typing import Any
import pandas as pd
from ledger_kit.models import Alert
from ledger_kit.detectors.base import DetectorResult

_REGISTRY: dict[str, Callable[[pd.DataFrame, Mapping[str, Any]], list[Alert]]] = {}
_log = logging.getLogger(__name__)

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")

def register(name: str):
    """Decorator that registers a detector function under `name`.

    `name` must follow the pattern '<namespace>.<detector>' where both parts are
    non-empty lowercase snake_case (e.g. 'zs.recurring_charge'). Raises ValueError
    if the name is malformed or already taken.
    """
    if not _NAME_RE.match(name):
        raise ValueError(
            f"Detector name {name!r} must match '<namespace>.<detector>' "
            "with both parts being non-empty lowercase snake_case."
        )
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

def run_all(
    ledger: pd.DataFrame,
    *,
    namespace: str | None = None,
    context: Mapping[str, Any] | None = None,
) -> list[DetectorResult]:
    """Run registered detectors in insertion order; isolate failures per detector.

    When `namespace` is given, only detectors whose name starts with `namespace + '.'`
    are run. `context` is wrapped in MappingProxyType before being passed to each
    detector; when None, an empty MappingProxyType is used.
    """
    proxy: Mapping[str, Any] = types.MappingProxyType(dict(context) if context else {})
    results: list[DetectorResult] = []
    for name, fn in _REGISTRY.items():
        if namespace is not None and not name.startswith(namespace + "."):
            continue
        try:
            alerts = fn(ledger, proxy)
        except Exception as exc:
            _log.warning("Detector '%s' raised %s: %s", name, type(exc).__name__, exc)
            alerts = []
        results.append(DetectorResult(name=name, alerts=alerts))
    return results

def registered_names(namespace: str | None = None) -> list[str]:
    """Return registered detector names in insertion order, optionally filtered by namespace."""
    if namespace is None:
        return list(_REGISTRY.keys())
    prefix = namespace + "."
    return [n for n in _REGISTRY if n.startswith(prefix)]

def _clear_registry() -> None:
    """Remove all registered detectors. For use in tests only."""
    _REGISTRY.clear()
```

**CR-LC-1 resolution**:
- Every detector receives `(ledger, context)` where `context` is always a `MappingProxyType` — immutable by construction. Detectors that need user input (aliases, cancellation dates, last-used dates) read from `context`; context-free detectors simply ignore the second argument.
- `name` validation at decoration time prevents malformed names from ever entering the registry.
- `run_all(ledger, namespace="zs")` runs only `zs.*` detectors, solving the multi-app process problem (OD-ZS-02) without any change to the signature seen by app code.
- No `ledger_kit` file needs to know about app-specific context keys.

**OD-2 resolution** (unchanged): `auto_discover` sorts module names before importing. `run_all` iterates `_REGISTRY` in insertion order (Python 3.7+ dict guarantee).

**OD-4 resolution** (unchanged): `_clear_registry()` is exposed as a private function for test teardown.

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

## 4a — Explanation layer (`ledger_kit/explainer.py`)

This module is the **only** file in `ledger_kit` permitted to make LLM API calls (structure rule).

### 4a.1 Constants and public API

```python
import logging
import os
import re
import string
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from datetime import date
from typing import Literal
import pandas as pd
from ledger_kit.models import Alert
from ledger_kit.utils.money import format_amount

# Streamlit renders alerts synchronously: keep the LLM call short.
LLM_TIMEOUT_SECONDS: int = 10   # seconds before giving up
LLM_MAX_RETRIES: int = 1        # one attempt; callers cache per alert.id

# Columns sent to the LLM (minimum data, Finance Rule 5 / REQ-EXP-xx).
# Never id (UUID adds random digits), never description, never full iban.
_LLM_ROW_COLUMNS = ("date", "amount", "flow", "currency", "counterparty", "source_ref")


@dataclass(frozen=True)
class Explanation:
    """Result of explain_with_meta(). `source` is 'llm' or 'fallback'."""
    text: str
    source: Literal["llm", "fallback"]
    rejected_numbers: tuple[str, ...]   # numbers the guard found and rejected


def explain(
    alert: Alert,
    rows: pd.DataFrame,
    *,
    fallback_template: str,
    client=None,            # injectable: openai.OpenAI-compatible instance or None
) -> str:
    """Return a plain-English explanation for `alert` (guarded text only).

    Delegates entirely to explain_with_meta; returns only the text field.
    """
    return explain_with_meta(
        alert, rows, fallback_template=fallback_template, client=client
    ).text


def explain_with_meta(
    alert: Alert,
    rows: pd.DataFrame,
    *,
    fallback_template: str,
    client=None,
) -> Explanation:
    """Return an Explanation with text, source, and any rejected numbers.

    When OPENAI_API_KEY is absent and no client is injected: returns filled
    fallback immediately, source='fallback', rejected_numbers=().

    When a client is available: calls the LLM, runs the number guard, returns
    source='llm' on success, source='fallback' if the guard fires or on any error.
    """
    _narrow_rows = _select_llm_columns(rows)
    fallback = _fill_fallback(fallback_template, alert)

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key and client is None:
        return Explanation(text=fallback, source="fallback", rejected_numbers=())

    raw = _call_llm(alert, _narrow_rows, client=client)
    if raw is None:
        return Explanation(text=fallback, source="fallback", rejected_numbers=())

    ok, rejected = _passes_number_guard(raw, alert, _narrow_rows)
    if not ok:
        logging.getLogger(__name__).warning(
            "Number guard rejected LLM response for alert %s: %s", alert.id, rejected
        )
        return Explanation(text=fallback, source="fallback", rejected_numbers=rejected)

    return Explanation(text=raw, source="llm", rejected_numbers=())
```

### 4a.2 Column narrowing (Finance Rule 5 / minimum data)

```python
def _select_llm_columns(rows: pd.DataFrame) -> pd.DataFrame:
    """Return only the columns safe to send to the LLM."""
    present = [c for c in _LLM_ROW_COLUMNS if c in rows.columns]
    return rows[present]
```

### 4a.3 Fallback formatter

The template syntax uses two placeholder types:
- `{key:money}` — value from `alert.data[key]` formatted with `format_amount`.
- `{key}` — value from `alert.data[key]` as a plain string.
- `{source_refs}` — special placeholder, replaced with the comma-joined `alert.source_refs`.

```python
class _AlertFormatter(string.Formatter):
    """string.Formatter subclass that resolves {key} and {key:money} from alert.data."""

    def __init__(self, alert: Alert) -> None:
        self._data = alert.data
        self._refs = ", ".join(alert.source_refs)

    def get_value(self, key, args, kwargs):  # noqa: ARG002
        if key == "source_refs":
            return self._refs
        return self._data.get(key, "{" + str(key) + "}")  # leave unknown as-is

    def format_field(self, value, format_spec):
        if format_spec == "money":
            try:
                return format_amount(Decimal(str(value)))
            except (InvalidOperation, TypeError):
                return str(value)
        return str(value)


def _fill_fallback(template: str, alert: Alert) -> str:
    """Fill the fallback template using _AlertFormatter."""
    return _AlertFormatter(alert).vformat(template, [], {})
```

### 4a.4 Number guard (Decimal-value comparison)

The guard compares **parsed Decimal values**, not raw strings. This means a European-formatted
answer (`12,99 EUR`) passes against `"12.99"` in `Alert.data`, and `3` in the text matches `03`
as the day part of a date.

**Algorithm**:
1. Extract whole date strings first (ISO `YYYY-MM-DD` and `DD/MM/YYYY`), check them against
   cited row `date` fields and any date-formatted values in `Alert.data`, then **remove** them
   from the text before the numeric extraction step.
2. Tokenise the remaining text with a regex that matches European (`1.234,56`) and plain
   (`1234.56`, `1234`) number forms.
3. Parse each token to `Decimal` (European: strip `.`, replace `,` with `.`; plain: direct).
4. Build the **allowed Decimal set** from:
   - `Alert.data` values (parsed to Decimal where possible).
   - The `date`, `amount`, `currency`, `counterparty`, `source_ref` cells of the cited `rows`
     (only the `_LLM_ROW_COLUMNS` columns — the row index integers embedded in `source_ref`
     strings are parsed and added automatically because they are substrings of those strings).
   - Do **not** include `id` (UUID), `description`, or full IBAN.
5. For each extracted Decimal, if it is not in the allowed set, record it as rejected.

```python
_DATE_ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DATE_EU_RE  = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")
_NUM_EU_RE   = re.compile(r"\b\d{1,3}(?:\.\d{3})*,\d+\b")
_NUM_PLAIN_RE = re.compile(r"\b\d+(?:\.\d+)?\b")


def _parse_decimal(token: str) -> Decimal | None:
    """Parse a number token (European or plain) to Decimal. Returns None on failure."""
    try:
        if "," in token:
            # European: 1.234,56 → remove dots (thousands sep) → replace comma
            cleaned = token.replace(".", "").replace(",", ".")
        else:
            cleaned = token
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _extract_dates_and_strip(text: str) -> tuple[set[date], str]:
    """Extract date objects from ISO and European date strings, remove them from text."""
    dates: set[date] = set()
    stripped = text
    for m in _DATE_ISO_RE.finditer(text):
        try:
            dates.add(date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
        except ValueError:
            pass
    for m in _DATE_EU_RE.finditer(text):
        try:
            dates.add(date(int(m.group(3)), int(m.group(2)), int(m.group(1))))
        except ValueError:
            pass
    stripped = _DATE_ISO_RE.sub("", stripped)
    stripped = _DATE_EU_RE.sub("", stripped)
    return dates, stripped


def _allowed_decimals(alert: Alert, rows: pd.DataFrame) -> set[Decimal]:
    """Build the set of Decimal values the LLM is permitted to use."""
    allowed: set[Decimal] = set()

    # From alert.data values
    for v in alert.data.values():
        d = _parse_decimal(str(v).replace(",", "."))  # always plain from Alert
        if d is not None:
            allowed.add(d)

    # From cited row cells (only safe columns)
    for col in rows.columns:
        for cell in rows[col]:
            s = str(cell)
            for token in _NUM_EU_RE.findall(s) + _NUM_PLAIN_RE.findall(s):
                d = _parse_decimal(token)
                if d is not None:
                    allowed.add(d)

    return allowed


def _allowed_dates(alert: Alert, rows: pd.DataFrame) -> set[date]:
    """Build the set of date values the LLM is permitted to mention."""
    dates: set[date] = set()
    for col in rows.columns:
        for cell in rows[col]:
            if isinstance(cell, date):
                dates.add(cell)
    # Also parse date-looking strings in alert.data
    for v in alert.data.values():
        s = str(v)
        for m in _DATE_ISO_RE.finditer(s):
            try:
                dates.add(date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
            except ValueError:
                pass
    return dates


def _passes_number_guard(
    text: str, alert: Alert, rows: pd.DataFrame
) -> tuple[bool, tuple[str, ...]]:
    """Check LLM text; return (passed, rejected_tokens).

    Dates are checked first and stripped before number extraction.
    Numbers are compared as Decimal values (so '12,99' matches '12.99').
    """
    found_dates, text_no_dates = _extract_dates_and_strip(text)
    allowed_dates = _allowed_dates(alert, rows)
    bad_dates = found_dates - allowed_dates
    if bad_dates:
        return False, tuple(str(d) for d in bad_dates)

    allowed = _allowed_decimals(alert, rows)
    rejected: list[str] = []
    for token in _NUM_EU_RE.findall(text_no_dates) + _NUM_PLAIN_RE.findall(text_no_dates):
        d = _parse_decimal(token)
        if d is not None and d not in allowed:
            rejected.append(token)
    if rejected:
        return False, tuple(rejected)
    return True, ()
```

### 4a.5 LLM call path

```python
def _call_llm(alert: Alert, rows: pd.DataFrame, *, client=None) -> str | None:
    """Call the LLM with the injectable client. Returns the response text or None."""
    if client is None:
        import openai  # lazy import
        client = openai.OpenAI(
            base_url=os.environ.get("OPENAI_BASE_URL") or None,
            api_key=os.environ["OPENAI_API_KEY"],
            timeout=LLM_TIMEOUT_SECONDS,
        )

    model = os.environ.get("LEDGER_KIT_LLM_MODEL", "gpt-4o-mini")
    system_prompt = (
        "You must not invent any number, date, name, or amount. "
        "Every figure you mention must appear verbatim either in the source rows "
        "provided or in the structured fields of the alert (such as yearly_cost). "
        "Do not derive, round, or estimate any figure not explicitly present in "
        "those inputs. "
        f"Cite at least one source reference from: {alert.source_refs}."
    )
    user_content = (
        f"Alert: {alert.model_dump_json()}\n\n"
        f"Source rows:\n{rows.to_json(orient='records')}"
    )

    for attempt in range(LLM_MAX_RETRIES):
        try:
            response = client.chat.completions.create(
                model=model,
                temperature=0,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
            )
            return response.choices[0].message.content or None
        except Exception as exc:
            logging.getLogger(__name__).warning(
                "LLM call attempt %d/%d failed: %s", attempt + 1, LLM_MAX_RETRIES, exc
            )
    return None
```

### 4a.6 Test architecture (`tests/test_explainer.py`)

Tests inject a `mock_client` directly via the `client=` parameter; no patching of `openai.OpenAI`
is required. The `LLM_MAX_RETRIES = 1` constant means the "retry" test needs only one failure
followed by one success (two calls total).

Key test helpers:

```python
@dataclass
class _MockCompletion:
    content: str

@dataclass
class _MockChoice:
    message: _MockCompletion

@dataclass
class _MockResponse:
    choices: list[_MockChoice]

class MockLLMClient:
    """Configurable mock. Pass responses=["text1", None, "text2"] to simulate failures."""
    def __init__(self, responses):
        self._responses = iter(responses)
    def chat(self):  # attribute access returns self for chaining
        return self
    @property
    def completions(self):
        return self
    def create(self, **kwargs):  # noqa: ARG002
        r = next(self._responses)
        if r is None:
            raise RuntimeError("simulated failure")
        return _MockResponse([_MockChoice(_MockCompletion(r))])
```

Number-guard property tests: generate a valid LLM response (only numbers from `alert.data`),
then inject one random foreign Decimal (not in allowed set), assert guard rejects. Additional
tests confirm European (`12,99`) and plain (`12.99`) forms of the same value both pass.

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
| OD-5 (CR-LC-1) | How do context-aware detectors receive user input without changing the registry signature? | Every detector signature is `(ledger, context)`. The registry wraps `context` in `types.MappingProxyType` before dispatch. Context-free detectors ignore the second argument. App code passes `run_all(ledger, namespace="zs", context={"aliases": …, "cancellation_dates": …})`. No `ledger_kit` file needs to know about app-specific context keys. |
| OD-6 (CR-LC-1) | How does an app run only its own detectors in a shared process? | `run_all(ledger, namespace="zs")` filters the registry to names starting with `"zs."`. Each app calls `auto_discover("apps.<app>.detectors")` at startup, populating only its own namespace. No structural change to the registry is needed beyond the `namespace` parameter. |
