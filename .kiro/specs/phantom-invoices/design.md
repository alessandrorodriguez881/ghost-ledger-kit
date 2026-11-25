# phantom-invoices — Design

## Overview

This document translates the requirements in `requirements.md` into concrete module boundaries,
function signatures, algorithms, data flows and test architecture. Implementation tasks (in
`tasks.md`) will reference sections of this document.

The app is a pure consumer of `ledger_kit`. It adds no primitive to the shared library beyond the
ledger-core change request CR-LC-3 (already applied to the ledger-core spec files). Every `Alert`
it produces is the `ledger_kit.models.Alert` type; every figure in an alert is copied from a source
row or computed by a `ledger_kit.utils.money` helper (`percent_of`, `within_tolerance`,
`net_total`, `round_to_cents`). **No file of `apps/phantom_invoices/` performs monetary
arithmetic itself** (REQ-MON-03). Date arithmetic (day counts, `due_date + 15 days`) is not
monetary and is done with `datetime`.

All pseudocode below is written as Python and is meant to be transcribed, not reinterpreted: every
helper it calls is defined in this document, and every threshold is a named constant (section 2).

---

## 1 — Module map

```
apps/phantom_invoices/
├── __init__.py
├── app.py                       # Streamlit entry point (path bootstrap + render loop)
├── config.toml                  # [demo] paths (+ optional as_of); no thresholds
├── settings.py                  # load_config, demo_inputs, run_pipeline (testable without Streamlit)
├── prepare.py                   # quarantine_multi_rate()
├── explain_support.py           # ROW_COLUMNS, TEMPLATES, template_for,
│                                # build_explain_rows, guard_badge, HallucinatingStubClient
├── flashlight.py                # HAUNTED_CSS, render_ledger_html(df, lit_refs) — pure, escapes cells
└── detectors/
    ├── __init__.py              # auto_discover, LABELS, run_pi_detectors
    ├── utils.py                 # as_text/as_decimal/as_date/as_bool, n1_key/n2_key, tax_key/name_key/
    │                            # iban_key, iban_problem/is_valid_iban, source_ref_key, sort_refs,
    │                            # load_rows, supplier_label, text_or_ref, build_master/Master,
    │                            # attribute_payment, resolve_as_of, finish,
    │                            # reconcile/Reconciliation/invoice_view/payment_view
    ├── duplicate_invoice.py     # detect_duplicate_invoices → "pi.duplicate_invoice"
    ├── iban_change.py           # detect_iban_changes       → "pi.iban_change"  (label: Poltergeist IBAN)
    ├── vat_error.py             # detect_vat_errors         → "pi.vat_error"
    └── reconciliation.py        # detect_reconciliation     → "pi.reconciliation"
```

Outside the app folder (owned by other specs, extended here):

```
scripts/generate_samples.py              # ledger-core Task 13; gains --mode phantom-demo (section 15)
data/samples/phantom_demo/               # suppliers.csv, invoices.csv, payments.csv (generated, committed)
.gitattributes                           # data/samples/phantom_demo/*.csv -text  (byte-identical on Windows)
requirements.txt                         # root level, serves both apps
```

There is deliberately **no** `apps/phantom_invoices/requirements.txt`: Streamlit Community Cloud
reads a requirements file next to the entry point first and would hide the root one (section 14).
The same holds for App 1. One task of `tasks.md` rewrites the phantom section of
`.kiro/steering/structure.md` to this file list (OD-PI-14).

### 1.1 Registration (`detectors/__init__.py`)

```python
"""Detector package of App 2: importing it registers the four pi.* detectors."""
from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from ledger_kit.detectors import DetectorResult, auto_discover, run_all

# User-visible label per registered detector name (REQ-PI-14).
LABELS: dict[str, str] = {
    "pi.duplicate_invoice": "Duplicate invoice",
    "pi.iban_change": "Poltergeist IBAN",
    "pi.vat_error": "VAT error",
    "pi.reconciliation": "Reconciliation",
}

auto_discover("apps.phantom_invoices.detectors")   # imports every module, triggering @register


def run_pi_detectors(
    invoices: pd.DataFrame, suppliers: pd.DataFrame, payments: pd.DataFrame,
    as_of: date | None = None,
) -> list[DetectorResult]:
    """Run the four pi.* detectors with the context of REQ-PI-02."""
    ctx: dict[str, Any] = {"suppliers": suppliers, "payments": payments, "as_of": as_of}
    return run_all(invoices, namespace="pi", context=ctx)
```

`auto_discover` imports modules in sorted name order, so the registry order is
`duplicate_invoice`, `iban_change`, `reconciliation`, `vat_error`. Nothing depends on that order:
the UI sorts alerts itself.

---

## 2 — Constants

Every threshold is a module-level constant with a business-meaning comment (REQ-DET-06,
Finance Rule 7). None appears in `config.toml` (REQ-PI-59). Constants used by two modules live in
`utils.py` and are re-exported by the detector module that REQ-PI documents them under
(`from .utils import UNPAID_GRACE_DAYS` in `reconciliation.py`), so tests import them from the
detector module.

| Constant | Value | Module | Business meaning |
|---|---|---|---|
| `DUPLICATE_WINDOW_DAYS` | `7` | `duplicate_invoice.py` | Same supplier, same total, different numbers: suspicious when issued fewer than this many days apart (rule C) |
| `SAME_NUMBER_WINDOW_DAYS` | `180` | `duplicate_invoice.py` | Same supplier, same number: suspicious only when issued fewer than this many days apart (rule A); an annual numbering restart is further apart (OD-PI-07) |
| `DUPLICATE_TOTAL_TOLERANCE` | `Decimal("0.00")` | `duplicate_invoice.py` | "Same total" means equal to the cent |
| `VAT_TOLERANCE` | `Decimal("0.01")` | `vat_error.py` | Largest accepted difference (euros) between stated and computed VAT amount |
| `TOTAL_TOLERANCE` | `Decimal("0.01")` | `vat_error.py` | Same, for the stated and the computed total |
| `ALLOWED_VAT_RATES` | `(21, 10, 4, 0)` as `Decimal` | `vat_error.py` | Spanish general, reduced, super-reduced and exempt rates; IGIC, Ceuta/Melilla, agricultural flat-rate are out of scope |
| `VERIFY_BY_PHONE_MESSAGE` | fixed text, no digit | `iban_change.py` | Deterministic advice shown with the two critical IBAN variants (REQ-PI-26) |
| `IBAN_FORMAT_RE` | `^[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}$` | `utils.py` (re-exported by `iban_change.py`) | Structural shape of an IBAN after `iban_key` |
| `IBAN_MOD97_MODULUS` / `IBAN_MOD97_REMAINDER` | `97` / `1` | `utils.py` (re-exported) | ISO 13616 checksum |
| `PAYMENT_MATCH_WINDOW_DAYS` | `60` | `utils.py` (re-exported by `reconciliation.py`) | A payment may be dated up to this many days after the due date and still match |
| `UNPAID_GRACE_DAYS` | `15` | `utils.py` (re-exported) | Days after the due date before an unmatched invoice is overdue |
| `MATCH_AMOUNT_TOLERANCE` | `Decimal("0.01")` | `utils.py` (re-exported) | Largest accepted difference between payment amount and invoice total |
| `MULTI_RATE_REASON` | `"multi_rate_invoice_out_of_scope"` | `prepare.py` | Quarantine reason for multi-rate invoices |

`DEFAULT_PAYMENT_TERM_DAYS = 30` lives in ledger-core's `invoice_reader.py`. A test asserts
`DUPLICATE_WINDOW_DAYS <= SAME_NUMBER_WINDOW_DAYS` (the structural property that makes equal-`N1`
pairs a rule-A-only matter, REQ-PI-18).

Spanish national IBAN check digits, per-country IBAN lengths and tax-id control characters are
**not** validated by the app (OD-PI-15, REQ-PI-58); only the generator and tests know about them.

---

## 3 — Data flow

```
suppliers.csv ─ parse_suppliers ─┐                                   (ledger_kit.ingestion)
invoices.csv/.json ─ parse_invoice ─┤→ normalise(kind=...) → three canonical DataFrames + quarantine lists
payments.csv ─ parse_csv ────────┘
        │
        ▼
quarantine_multi_rate(invoices_df) → (clean_invoices, multi-rate quarantine records)      (prepare.py)
        │
        ▼
ctx = {"suppliers": suppliers_df, "payments": payments_df, "as_of": as_of | None}
as_of_used = resolve_as_of(clean_invoices, ctx)                                           (section 5.3)
        │
        ├──► run_all(clean_invoices, namespace="pi", context=ctx)
        │       → DetectorResult × 4 → list[Alert]        (run_all wraps ctx in MappingProxyType)
        │
        ├──► reconcile(clean_invoices, suppliers_df, payments_df, as_of_used)
        │       → Reconciliation → status column of the haunted ledger
        │
        ▼
per Alert: rows = build_explain_rows(alert, clean_invoices, suppliers_df, payments_df)
           meta = explain_with_meta(alert, rows, fallback_template=template_for(alert),
                                    client=…, row_columns=ROW_COLUMNS)
        │
        ▼
Streamlit render: severity summary → haunted ledger (+ flashlight) → alert cards → quarantine
```

The three readers and `normalise` are called exactly as documented in ledger-core; the app does
not re-implement CSV parsing or normalisation (REQ-PI-01). `parse_csv` receives the bank file
without a `dialect` argument, so ledger-core's auto-detection applies; the demo files are plain
dialect (OD-PI-13). Payments are passed in full (debits and credits); each detector filters
`flow == "debit"` itself (REQ-PI-03).

`settings.run_pipeline` bundles this flow so it can be tested without Streamlit:

```python
@dataclass(frozen=True)
class Source:
    name: str          # file name, used as source_file → source_ref prefix
    data: bytes

@dataclass(frozen=True)
class Pipeline:
    invoices: pd.DataFrame            # clean (multi-rate rows removed)
    suppliers: pd.DataFrame
    payments: pd.DataFrame
    quarantine: list[dict]            # ingestion quarantine + multi-rate records, with a "file_kind" key
    as_of_used: date | None
    results: list[DetectorResult]
    reconciliation: Reconciliation

def run_pipeline(
    invoices: Source | None, suppliers: Source | None, payments: Source | None,
    as_of: date | None,
) -> Pipeline:
    """Parse, normalise, quarantine multi-rate invoices, run pi.* detectors and reconcile."""
    inv_list, inv_q = ([], []) if invoices is None else parse_invoice(
        io.BytesIO(invoices.data),
        fmt="json" if invoices.name.lower().endswith(".json") else "csv",
        source_file=invoices.name)
    sup_list, sup_q = ([], []) if suppliers is None else parse_suppliers(
        io.BytesIO(suppliers.data), source_file=suppliers.name)
    pay_list, pay_q = ([], []) if payments is None else parse_csv(
        io.BytesIO(payments.data), source_file=payments.name)
    invoices_df, inv_n = normalise(inv_list, kind="invoice")
    suppliers_df, sup_n = normalise(sup_list, kind="supplier")
    payments_df, pay_n = normalise(pay_list)                       # kind defaults to "transaction"
    clean, multi_rate = quarantine_multi_rate(invoices_df)
    ctx = {"suppliers": suppliers_df, "payments": payments_df, "as_of": as_of}
    as_of_used = resolve_as_of(clean, ctx)
    results = run_all(clean, namespace="pi", context=ctx)
    rec = reconcile(clean, suppliers_df, payments_df, as_of_used)
    quarantine = (_tag("invoices", inv_q + inv_n + multi_rate) + _tag("suppliers", sup_q + sup_n)
                  + _tag("payments", pay_q + pay_n))
    return Pipeline(clean, suppliers_df, payments_df, quarantine, as_of_used, results, rec)
```

`_tag(kind, records)` returns copies of the records with `file_kind` added; it never changes the
ledger-core record shape (`source_file`, `source_row`, `reason`, `raw`). Missing files are
treated as empty inputs: `normalise([], kind=…)` returns an empty frame with all canonical
columns (REQ-ING-28), so detectors never see a column-less frame from the app.

---

## 4 — Normalisation and shared helpers (`detectors/utils.py`)

All helpers are pure and never raise on any input value (REQ-PI-06). Imports used throughout:

```python
from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd

from ledger_kit.models import Alert
from ledger_kit.utils.money import within_tolerance

ZERO: Decimal = Decimal("0")
DASH_CHARS: str = "-\u2013\u2014"        # hyphen, en dash, em dash: a cell made only of these is missing
```

### 4.1 Missing values and typed readers (REQ-PI-06)

```python
def is_missing(value: Any) -> bool:
    """True for None, NaN, pd.NA, NaT, NaN Decimal, blank text and text made only of dashes."""
    if value is None or value is pd.NA or value is pd.NaT:
        return True
    if isinstance(value, (float, np.floating)):
        return bool(value != value)                        # NaN
    if isinstance(value, Decimal):
        return value.is_nan()
    if isinstance(value, str):
        text = value.strip()                               # str.strip() also strips \u00a0
        return text == "" or all(ch in DASH_CHARS for ch in text)
    return False


def as_text(value: Any) -> str | None:
    """The cell as written (unstripped) when it is a non-missing str, else None."""
    if isinstance(value, str) and not is_missing(value):
        return value
    return None


def as_decimal(value: Any) -> Decimal | None:
    """The cell when it is a finite Decimal, else None (floats, ints and strings are wrong types)."""
    if isinstance(value, Decimal) and not is_missing(value) and value.is_finite():
        return value
    return None


def as_date(value: Any) -> date | None:
    """A datetime.date, or the date part of a datetime/pd.Timestamp; None otherwise."""
    if is_missing(value):
        return None
    if isinstance(value, datetime):                        # pd.Timestamp is a datetime subclass
        return value.date()
    if isinstance(value, date):
        return value
    return None


def as_bool(value: Any) -> bool:
    """True only for the bool True / numpy True; every other cell is False."""
    return bool(value) if isinstance(value, (bool, np.bool_)) else False
```

A check that needs a cell for which the reader returned `None` is skipped for that row.

### 4.2 Invoice-number keys N1 and N2 (REQ-PI-07)

"Alphanumeric" means ASCII `A–Z`/`0–9` after upper-casing; invoice numbers are ASCII by law and
by every fixture (design note DN-2).

```python
_NON_ALNUM = re.compile(r"[^A-Z0-9]")
_DIGIT_RUN = re.compile(r"[0-9]+")


def n1_key(number: str) -> str:
    """Upper-case and drop every non-alphanumeric character: 'F-2026-0042' -> 'F20260042'."""
    return _NON_ALNUM.sub("", number.upper())


def n2_key(number: str) -> str:
    """Like N1, but every maximal digit run of the ORIGINAL text loses its leading zeros first."""
    stripped = _DIGIT_RUN.sub(lambda m: m.group().lstrip("0") or "0", number.upper())
    return _NON_ALNUM.sub("", stripped)
```

Digit runs are delimited by any non-digit (hyphens and letters included), which is why
`F-2026-0042` and `F2026-042` both give `F202642` while their `N1` values differ. Table of
REQ-PI-07 re-derived with this code: `F-2026-0042` → runs `2026`,`0042` → `F-2026-42` → `F202642`;
`F2026-042` → `F2026-42` → `F202642`; `ALQ-2026-01` → `ALQ-2026-1` → `ALQ20261`; `F-000` →
`F-0` → `F0`. An empty `N1` (`"---"` is missing anyway; `"/ /"` is not) makes the row ineligible
for the duplicate detector.

Equal `N1` does **not** imply equal `N2` (`F0-05` and `F005` both have `N1 = F005`, but `N2` is
`F05` and `F5`); the rule structure of section 7.3 therefore never relies on it.

### 4.3 Identifier keys (REQ-PI-08)

```python
def tax_key(value: str) -> str:
    """Upper-case and drop every non-alphanumeric character: 'b-00000001' -> 'B00000001'."""
    return _NON_ALNUM.sub("", value.upper())


def name_key(value: str) -> str:
    """NFKD, drop combining marks, upper-case, drop non-alphanumerics:
    'Suministros García, S.L.' -> 'SUMINISTROSGARCIASL'."""
    decomposed = unicodedata.normalize("NFKD", value)
    bare = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _NON_ALNUM.sub("", bare.upper())


def iban_key(value: str) -> str:
    """Remove ALL whitespace (including \\u00a0) and upper-case. Hyphens are kept."""
    return re.sub(r"\s", "", value).upper()
```

Callers pass `as_text(cell) or ""`, so a missing cell gives the empty key, and an empty `tax_key`
means "skip this row in supplier-based rules".

### 4.4 Supplier master and payment attribution (REQ-PI-09, REQ-PI-25)

> **Amended by `detector-fixes` (REQ-DF-01 to REQ-DF-07, design §2; session 10d, committed in
> `989789b`).** The code below is the original sketch. `Master` now also carries `rows_by_tax`
> (every row of a tax id in `source_ref` order); `by_tax` is still the first row (it names the
> supplier); `by_iban` maps the `iban_key` of **any** master IBAN to the supplier's first row once;
> `accepted_accounts(master, tax)` returns the valid, deduplicated accounts. `iban_change` compares
> against all accepted accounts and `attribute_payment` counts a supplier once per tax id. With one
> row per tax id the behaviour is identical to the sketch.

```python
@dataclass(frozen=True)
class Master:
    """The supplier master, one row per tax_key (the first in source_ref order)."""
    by_tax: Mapping[str, dict]                 # tax_key -> master row (insertion = source_ref order)
    by_name: Mapping[str, tuple[dict, ...]]    # name_key -> master rows (distinct suppliers)
    by_iban: Mapping[str, tuple[dict, ...]]    # iban_key of the master IBAN -> master rows


def build_master(suppliers: Any) -> Master:
    """Index the supplier master; rows with an empty tax_key are not suppliers; later duplicates ignored."""
    by_tax: dict[str, dict] = {}
    for row in load_rows(suppliers, None):
        tax = tax_key(as_text(row.get("tax_id")) or "")
        if tax and tax not in by_tax:
            by_tax[tax] = row
    names: dict[str, list[dict]] = {}
    ibans: dict[str, list[dict]] = {}
    for row in by_tax.values():
        nk = name_key(as_text(row.get("supplier_name")) or "")
        if nk:
            names.setdefault(nk, []).append(row)
        iban = as_text(row.get("iban"))
        if iban is not None:
            ibans.setdefault(iban_key(iban), []).append(row)
    return Master(by_tax,
                  {k: tuple(v) for k, v in names.items()},
                  {k: tuple(v) for k, v in ibans.items()})


def attribute_payment(payment: Mapping[str, Any], master: Master) -> dict | None:
    """Master row of the supplier a payment belongs to, or None (REQ-PI-25).

    Name first (exactly one master supplier with the same name_key), then IBAN (exactly one
    supplier whose master IBAN has the same iban_key). Zero or several hits fall through; no hit
    at all means the payment is not a supplier payment.
    """
    name = name_key(as_text(payment.get("counterparty")) or "")
    if name:
        hits = master.by_name.get(name, ())
        if len(hits) == 1:
            return hits[0]
    iban = as_text(payment.get("iban"))
    if iban is not None:
        hits = master.by_iban.get(iban_key(iban), ())
        if len(hits) == 1:
            return hits[0]
    return None
```

Name goes first so a payment addressed to a known supplier but sent to another account is still
attributed (and caught by `pi.iban_change`, OD-PI-09). `supplier_label(row, ref)` and
`text_or_ref(value, ref)` (section 5.4) give display strings for dirty rows.

### 4.5 IBAN validity (REQ-PI-23)

```python
IBAN_FORMAT_RE: re.Pattern[str] = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}$")
IBAN_MOD97_MODULUS: int = 97
IBAN_MOD97_REMAINDER: int = 1


def iban_problem(key: str) -> str | None:
    """None for a valid IBAN; 'format' for a malformed one; 'checksum' for a mod-97 failure.

    `key` is an iban_key() result. Never raises.
    """
    if not IBAN_FORMAT_RE.fullmatch(key):
        return "format"
    rearranged = key[4:] + key[:4]
    digits = "".join(str(int(ch, 36)) for ch in rearranged)       # A=10 … Z=35, digits unchanged
    if int(digits) % IBAN_MOD97_MODULUS != IBAN_MOD97_REMAINDER:
        return "checksum"
    return None


def is_valid_iban(key: str) -> bool:
    """True when iban_problem(key) is None."""
    return iban_problem(key) is None
```

Hyphens, dots and other separators fail `IBAN_FORMAT_RE` (reason `format`), which is what makes
the hyphenated IBAN of P12 a `warning` and not a comparison. The documented IBAN of REQ-PI-58 was
checked by running it: remainder 1 (valid), correct Spanish national check digits `45`, the example
carries `56`.

---

## 5 — Ordering, rows, `as_of` and alert hygiene

### 5.1 Deterministic order (REQ-PI-10)

```python
_SOURCE_REF_ROW = re.compile(r"[0-9]+")


def source_ref_key(ref: str) -> tuple[str, int]:
    """Natural order of a source_ref: (file name, integer row). 'f.csv:9' < 'f.csv:10'."""
    file, sep, row = ref.rpartition(":")
    if sep and _SOURCE_REF_ROW.fullmatch(row):
        return (file, int(row))
    return (ref, -1)


def sort_refs(refs: list[str]) -> list[str]:
    """Distinct refs in natural order."""
    return sorted(set(refs), key=source_ref_key)


def _tiebreak(record: Mapping[str, Any]) -> str:
    """String form of a record: makes the order total even for conflicting duplicate source_refs."""
    return repr(sorted((str(k), str(v)) for k, v in record.items()))


def load_rows(frame: Any, date_col: str | None) -> list[dict]:
    """Records of `frame` in deterministic order, one per source_ref (REQ-PI-10, REQ-PI-11).

    Sorted by (date, source_ref natural order, tiebreak); a missing date sorts last. A frame that
    is not a DataFrame, is empty, or has no source_ref column yields []. A row without a
    source_ref cannot be cited and is dropped. For duplicate source_refs the first in sort order
    is kept.
    """
    if not isinstance(frame, pd.DataFrame) or frame.empty or "source_ref" not in frame.columns:
        return []

    def key(record: dict) -> tuple[date, tuple[str, int], str]:
        day = as_date(record.get(date_col)) if date_col else None
        return (day or date.max, source_ref_key(as_text(record.get("source_ref")) or ""),
                _tiebreak(record))

    rows: list[dict] = []
    seen: set[str] = set()
    for record in sorted(frame.to_dict("records"), key=key):
        ref = as_text(record.get("source_ref"))
        if ref is None or ref in seen:
            continue
        seen.add(ref)
        rows.append(record)
    return rows
```

Invoices are loaded with `date_col="issue_date"`, payments with `"date"`, supplier rows with
`None` (so source_ref order). `frame.to_dict("records")` copies the data; no detector mutates an
input frame or the context.

### 5.2 Duplicate `source_ref` (REQ-PI-11)

Handled once, in `load_rows`: after sorting, the first row of a `source_ref` is used and later
ones are ignored by every detector and by `reconcile`. No alert can therefore repeat a ref.

### 5.3 Deterministic `as_of` (REQ-PI-12)

```python
def _column(frame: Any, name: str) -> list[Any]:
    """Cells of a column, or [] when `frame` is not a DataFrame or lacks the column."""
    if isinstance(frame, pd.DataFrame) and name in frame.columns:
        return list(frame[name])
    return []


def resolve_as_of(ledger: Any, context: Mapping[str, Any]) -> date | None:
    """`as_of` of the context when it is a date, else the latest date in the loaded data.

    The latest date is the maximum over ALL issue_date cells of the invoices and ALL date cells of
    the payments (credits and unusable rows included). None when there is no date at all.
    Never reads the system clock.
    """
    explicit = as_date(context.get("as_of"))
    if explicit is not None:
        return explicit
    days = [as_date(v) for v in _column(ledger, "issue_date")]
    days += [as_date(v) for v in _column(context.get("payments"), "date")]
    present = [d for d in days if d is not None]
    return max(present) if present else None
```

No module of `apps/phantom_invoices/` calls `date.today()`, `datetime.now()` or `time.time()`;
`test_pi_utils.py` scans the package sources with `ast` for such calls (section 16.4). Because the
default is a function of the data only, the demo yields the same alerts on every day of judging.
`pi.reconciliation` skips the overdue rule when the result is `None`.

### 5.4 Alert hygiene helpers (REQ-PI-13)

```python
def text_or_ref(value: Any, ref: str) -> str:
    """The cell text, or the row's own source_ref when the cell is missing (a verbatim identifier)."""
    return as_text(value) or ref


def supplier_label(row: Mapping[str, Any], ref: str) -> str:
    """supplier_name, else the tax id as written, else the source_ref."""
    return as_text(row.get("supplier_name")) or as_text(row.get("supplier_tax_id")) or ref


def finish(alerts: list[Alert]) -> list[Alert]:
    """Detector output order: (first source_ref natural order, variant, id) — a total order."""
    return sorted(alerts, key=lambda a: (source_ref_key(a.source_refs[0]),
                                         str(a.data.get("variant", "")), a.id))
```

Rules every alert builder follows: `Alert.data` holds only `str`, `int`, `bool` and `list[str]`;
money is `str(round_to_cents(x))` (always two decimals, e.g. `"121.00"`); dates are
`date.isoformat()`; rates are `str(Decimal)` (`"21"`); IBANs are `mask_iban(raw)` only;
`source_refs` come from `sort_refs`. Every `data` carries `"variant"`.

---

## 6 — Multi-rate quarantine (`prepare.py`, REQ-PI-15)

```python
MULTI_RATE_REASON: str = "multi_rate_invoice_out_of_scope"


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
    for pos, rec in enumerate(records):
        tax = tax_key(as_text(rec.get("supplier_tax_id")) or "")
        n1 = n1_key(as_text(rec.get("invoice_number")) or "")
        if tax and n1:
            groups.setdefault((tax, n1), []).append(pos)
    bad: set[int] = set()
    for positions in groups.values():
        rates = {as_decimal(records[p].get("vat_rate")) for p in positions} - {None}
        if len(rates) > 1:                      # Decimal("21") and Decimal("21.00") are one rate
            bad.update(positions)
    clean = invoices.iloc[[p for p in range(len(records)) if p not in bad]].reset_index(drop=True)
    quarantined = [
        {
            "source_file": records[p].get("source_file"),
            "source_row": records[p].get("source_row"),
            "reason": MULTI_RATE_REASON,
            "raw": {str(k): ("" if is_missing(v) else str(v)) for k, v in records[p].items()},
        }
        for p in sorted(bad, key=lambda p: source_ref_key(str(records[p].get("source_ref"))))
    ]
    return clean, quarantined
```

One record per removed row, in natural `source_ref` order. Known limitation (OD-PI-08, shown in the
quarantine panel): a *duplicated* multi-rate invoice is not detected and its payment appears as
`payment_without_invoice`.

---

## 7 — `pi.duplicate_invoice` (`detectors/duplicate_invoice.py`)

### 7.1 Constants and row view

```python
DUPLICATE_WINDOW_DAYS: int = 7
SAME_NUMBER_WINDOW_DAYS: int = 180
DUPLICATE_TOTAL_TOLERANCE: Decimal = Decimal("0.00")

VARIANT_RANK: dict[str, int] = {"same_number": 3, "near_identical_number": 2,
                                "same_total_close_dates": 1}      # A > B > C
VARIANT_BY_RANK: dict[int, str] = {v: k for k, v in VARIANT_RANK.items()}


@dataclass(frozen=True)
class _Inv:
    ref: str
    number: str            # as written
    n1: str
    n2: str
    tax: str               # tax_key of the supplier
    name: str              # supplier label
    issue: date
    total: Decimal
    currency: str | None
    rate: Decimal | None   # vat_rate; None when missing


def _usable(row: dict) -> _Inv | None:
    """The row as an _Inv, or None when it is not usable (REQ-PI-17)."""
    ref = as_text(row.get("source_ref"))
    number = as_text(row.get("invoice_number"))
    tax = tax_key(as_text(row.get("supplier_tax_id")) or "")
    issue = as_date(row.get("issue_date"))
    total = as_decimal(row.get("total"))
    if ref is None or number is None or not tax or issue is None or total is None:
        return None
    n1 = n1_key(number)
    if not n1:
        return None
    return _Inv(ref, number, n1, n2_key(number), tax, supplier_label(row, ref), issue, total,
                as_text(row.get("currency")), as_decimal(row.get("vat_rate")))
```

### 7.2 Multi-rate second line of defence (REQ-PI-16)

```python
def _drop_multi_rate(members: list[_Inv]) -> list[_Inv]:
    """Drop every row of a supplier+N1 group that holds more than one distinct vat_rate."""
    rates: dict[str, set[Decimal]] = {}
    for m in members:
        if m.rate is not None:
            rates.setdefault(m.n1, set()).add(m.rate)
    return [m for m in members if len(rates.get(m.n1, ())) <= 1]
```

### 7.3 Pair rule (REQ-PI-18)

```python
def _pair_variant(a: _Inv, b: _Inv) -> str | None:
    """Rule that relates two invoices of one supplier, or None. No similarity score is used."""
    if a.currency != b.currency:                               # REQ-PI-05
        return None
    days = abs((a.issue - b.issue).days)
    if a.n1 == b.n1:                                           # rule A is the only rule for equal N1
        return "same_number" if days < SAME_NUMBER_WINDOW_DAYS else None
    if not within_tolerance(a.total, b.total, DUPLICATE_TOTAL_TOLERANCE):
        return None
    if a.n2 == b.n2:                                           # rule B: no date window
        return "near_identical_number"
    return "same_total_close_dates" if days < DUPLICATE_WINDOW_DAYS else None   # rule C
```

For equal `N1`, rule B cannot apply (needs different `N1`) and rule C cannot apply when
`days < SAME_NUMBER_WINDOW_DAYS` already gave rule A (C needs `days < 7 <= 180`); at
`days >= 180` C's window is exceeded. Hence returning from the `n1` branch loses nothing.

### 7.4 Grouping (REQ-PI-19)

Pair relations are closed transitively with a union-find; each root keeps the highest rank seen:

```python
def _groups(members: list[_Inv]) -> list[tuple[list[_Inv], int]]:
    """Connected groups of two or more related invoices, each with its highest rule rank."""
    n = len(members)
    parent = list(range(n))
    top = [0] * n                                   # highest rank per root

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        for j in range(i + 1, n):
            rank = VARIANT_RANK.get(_pair_variant(members[i], members[j]) or "", 0)
            if rank == 0:
                continue
            ri, rj = find(i), find(j)
            best = max(rank, top[ri], top[rj])
            parent[rj] = ri
            top[ri] = best
    by_root: dict[int, list[_Inv]] = {}
    for i in range(n):
        by_root.setdefault(find(i), []).append(members[i])
    return [(g, top[root]) for root, g in by_root.items() if len(g) > 1]
```

A group never produces a second alert from a weaker rule: one component, one alert, with the
variant of the highest rank in it.

### 7.5 Detector and alert (REQ-PI-17, REQ-PI-20)

```python
@register("pi.duplicate_invoice")
def detect_duplicate_invoices(ledger: pd.DataFrame, context: Mapping[str, Any]) -> list[Alert]:
    """Flag invoices that look like the same invoice sent twice."""
    usable = [u for u in (_usable(r) for r in load_rows(ledger, "issue_date")) if u is not None]
    by_supplier: dict[str, list[_Inv]] = {}
    for inv in usable:
        by_supplier.setdefault(inv.tax, []).append(inv)
    alerts: list[Alert] = []
    for tax in sorted(by_supplier):
        members = _drop_multi_rate(by_supplier[tax])
        if len(members) < 2:
            continue
        for group, rank in _groups(members):
            alerts.append(_alert(group, rank))
    return finish(alerts)


def _alert(group: list[_Inv], rank: int) -> Alert:
    """Build the single alert of one group (members in natural source_ref order)."""
    members = sorted(group, key=lambda m: source_ref_key(m.ref))
    first = members[0]
    variant = VARIANT_BY_RANK[rank]
    first_day = min(m.issue for m in members)
    last_day = max(m.issue for m in members)
    prefix = "Duplicate invoice" if variant == "same_number" else "Possible duplicate invoice"
    return Alert(
        detector="pi.duplicate_invoice",
        severity="critical" if variant == "same_number" else "warning",
        title=f"{prefix}: {first.number} ({first.name})",
        source_refs=[m.ref for m in members],
        data={
            "variant": variant,
            "supplier_name": first.name,
            "invoice_count": len(members),
            "invoice_numbers": [m.number for m in members],
            "totals": [str(round_to_cents(m.total)) for m in members],
            "total": str(round_to_cents(first.total)),
            "first_issue_date": first_day.isoformat(),
            "last_issue_date": last_day.isoformat(),
            "days_apart": (last_day - first_day).days,
        },
    )
```

`ledger` may be `pd.DataFrame()` or empty: `load_rows` returns `[]`, so the result is `[]`.
`context` is ignored. `finish` guarantees the same list for any row order.

### 7.6 Edge behaviour (REQ-PI-21)

| Case | Mechanism |
|---|---|
| `N1` empty, non-string or missing number, missing date or total | `_usable` returns `None` |
| identical `source_ref` twice | `load_rows` keeps the first |
| multi-rate group | `_drop_multi_rate` |
| same number, different suppliers | grouped per `tax_key` |
| rule C: 6 days alerts, 7 does not | `days < DUPLICATE_WINDOW_DAYS` |
| rule A: 179 days alerts, 180 does not | `days < SAME_NUMBER_WINDOW_DAYS` |
| totals differing by 0.01 | `within_tolerance(…, Decimal("0.00"))` is `False` |

---

## 8 — `pi.iban_change` — Poltergeist IBAN (`detectors/iban_change.py`)

### 8.1 Constants and IBAN state

```python
from .utils import (IBAN_FORMAT_RE, IBAN_MOD97_MODULUS, IBAN_MOD97_REMAINDER,   # re-exported
                    attribute_payment, build_master, iban_key, iban_problem, ...)

VERIFY_BY_PHONE_MESSAGE: str = (
    "Verify this change by phone, using a contact you already have for this supplier. "
    "Never use a phone number or e-mail address printed on the invoice."
)                                                         # one string, no digit (REQ-PI-26)


def _iban_state(cell: Any) -> tuple[str, str | None] | None:
    """(iban_key, problem) for a present IBAN cell; None when the cell is missing (skipped)."""
    text = as_text(cell)
    if text is None:
        return None
    key = iban_key(text)
    return key, iban_problem(key)
```

### 8.2 Detector (REQ-PI-22, REQ-PI-24)

At most one alert per row. A *valid* IBAN is compared with the master; an *invalid* one is only
flagged. The master row is flagged once when its own IBAN is present and invalid, and nothing is
compared against an invalid master IBAN.

```python
@register("pi.iban_change")
def detect_iban_changes(ledger: pd.DataFrame, context: Mapping[str, Any]) -> list[Alert]:
    """Flag invoice or payment IBANs that differ from the supplier master, and invalid IBANs."""
    master = build_master(context.get("suppliers"))
    alerts: list[Alert] = []

    # 1 — master rows whose own IBAN is present but invalid
    for row in master.by_tax.values():
        state = _iban_state(row.get("iban"))
        if state is not None and state[1] is not None:
            ref = as_text(row.get("source_ref")) or ""
            alerts.append(_invalid("supplier", text_or_ref(row.get("supplier_name"), ref),
                                   state[1], row.get("iban"), [ref]))

    # 2 — invoices
    for row in load_rows(ledger, "issue_date"):
        ref = as_text(row.get("source_ref")) or ""
        state = _iban_state(row.get("iban"))
        if state is None:
            continue                                            # missing IBAN: skipped (P12b)
        key, problem = state
        number = text_or_ref(row.get("invoice_number"), ref)
        if problem is not None:
            alerts.append(_invalid("invoice", number, problem, row.get("iban"), [ref]))
            continue
        sup = master.by_tax.get(tax_key(as_text(row.get("supplier_tax_id")) or ""))
        master_key = _valid_master_key(sup)
        if sup is None or master_key is None or master_key == key:
            continue                                            # unknown supplier / no usable master IBAN / equal
        alerts.append(_invoice_differs(row, ref, number, sup, row.get("iban")))

    # 3 — bank payments (debits attributed to a master supplier)
    for row in load_rows(context.get("payments"), "date"):
        if as_text(row.get("flow")) != "debit":
            continue
        sup = attribute_payment(row, master)
        state = _iban_state(row.get("iban"))
        if sup is None or state is None:
            continue
        ref = as_text(row.get("source_ref")) or ""
        key, problem = state
        if problem is not None:
            alerts.append(_invalid("payment", text_or_ref(row.get("counterparty"), ref),
                                   problem, row.get("iban"), [ref]))
            continue
        master_key = _valid_master_key(sup)
        day, amount = as_date(row.get("date")), as_decimal(row.get("amount"))
        if master_key is None or master_key == key or day is None or amount is None:
            continue
        alerts.append(_payment_differs(row, ref, sup, day, amount))
    return finish(alerts)


def _valid_master_key(sup: dict | None) -> str | None:
    """iban_key of the master IBAN when it is present and valid, else None."""
    if sup is None:
        return None
    state = _iban_state(sup.get("iban"))
    return state[0] if state is not None and state[1] is None else None
```

With empty ledger, empty master and empty payments no loop body runs and the result is `[]`; with
an empty ledger and a non-master payment the third loop alerts (REQ-DET-05, REQ-PI-22). `ledger` is
only read through `load_rows`, so `pd.DataFrame()` is safe.

### 8.3 Alert builders (REQ-PI-27)

```python
from ledger_kit.utils.anonymise import mask_iban


def _invalid(subject: str, label: str, problem: str, raw_iban: Any, refs: list[str]) -> Alert:
    """warning / iban_invalid; the full IBAN never reaches Alert.data."""
    return Alert(
        detector="pi.iban_change", severity="warning",
        title=f"Invalid IBAN on {subject} {label}", source_refs=sort_refs(refs),
        data={"variant": "iban_invalid", "subject": subject, "label": label,
              "reason": problem, "iban_masked": mask_iban(as_text(raw_iban) or "")},
    )


def _invoice_differs(row: dict, ref: str, number: str, sup: dict, raw_iban: Any) -> Alert:
    """critical / invoice_iban_differs_from_master."""
    sup_ref = as_text(sup.get("source_ref")) or ""
    a, b = mask_iban(as_text(raw_iban) or ""), mask_iban(as_text(sup.get("iban")) or "")
    name = text_or_ref(sup.get("supplier_name"), sup_ref)
    return Alert(
        detector="pi.iban_change", severity="critical",
        title=f"Poltergeist IBAN: {name}", source_refs=sort_refs([ref, sup_ref]),
        data={"variant": "invoice_iban_differs_from_master", "supplier_name": name,
              "invoice_number": number, "invoice_iban_masked": a, "master_iban_masked": b,
              "last4_identical": a == b, "verification_message": VERIFY_BY_PHONE_MESSAGE},
    )


def _payment_differs(row: dict, ref: str, sup: dict, day: date, amount: Decimal) -> Alert:
    """critical / payment_to_non_master_iban."""
    sup_ref = as_text(sup.get("source_ref")) or ""
    a, b = mask_iban(as_text(row.get("iban")) or ""), mask_iban(as_text(sup.get("iban")) or "")
    name = text_or_ref(sup.get("supplier_name"), sup_ref)
    return Alert(
        detector="pi.iban_change", severity="critical",
        title=f"Payment sent to a non-master IBAN: {name}", source_refs=sort_refs([ref, sup_ref]),
        data={"variant": "payment_to_non_master_iban", "supplier_name": name,
              "payment_date": day.isoformat(), "payment_amount": str(round_to_cents(amount)),
              "payment_iban_masked": a, "master_iban_masked": b, "last4_identical": a == b,
              "verification_message": VERIFY_BY_PHONE_MESSAGE},
    )
```

`mask_iban` removes whitespace, upper-cases and keeps the last four characters
(`****1332`); a value of four characters or fewer yields `****`. No `Alert.data` value anywhere
contains a full IBAN (REQ-PII-04). `VERIFY_BY_PHONE_MESSAGE` is code, not LLM output.

### 8.4 Edge behaviour (REQ-PI-28)

| Case | Mechanism |
|---|---|
| differ only before the last four characters | `last4_identical = True`, alert still raised |
| `\u00a0` inside the IBAN | `iban_key` removes `\s` |
| IBAN of only hyphens, `NaN`, `None` | `as_text` is `None` → skipped |
| IBAN with hyphens | `iban_problem` → `"format"` → `iban_invalid` (P12a) |
| valid shape, bad checksum | `"checksum"` |
| lowercase | upper-cased by `iban_key` |
| invoice and payment of one supplier | independent loops, two alerts |
| empty ledger + non-master payment | third loop alerts |
| everything empty | `[]` |
| supplier not in master | `by_tax.get(...)` is `None` → skipped |

---

## 9 — `pi.vat_error` (`detectors/vat_error.py`)

### 9.1 Constants and checks (REQ-PI-29 to REQ-PI-31)

```python
VAT_TOLERANCE: Decimal = Decimal("0.01")
TOTAL_TOLERANCE: Decimal = Decimal("0.01")
# Spanish general, reduced, super-reduced and exempt rates (percent). Canary Islands IGIC and other
# special regimes (Ceuta, Melilla, agricultural flat-rate, …) are out of scope.
ALLOWED_VAT_RATES: tuple[Decimal, ...] = (Decimal("21"), Decimal("10"), Decimal("4"), Decimal("0"))


@register("pi.vat_error")
def detect_vat_errors(ledger: pd.DataFrame, context: Mapping[str, Any]) -> list[Alert]:
    """Check VAT amount, total and VAT rate of each invoice on its base (not line by line)."""
    alerts: list[Alert] = []
    for row in load_rows(ledger, "issue_date"):
        ref = as_text(row.get("source_ref")) or ""
        base, rate = as_decimal(row.get("base_amount")), as_decimal(row.get("vat_rate"))
        vat, total = as_decimal(row.get("vat_amount")), as_decimal(row.get("total"))
        surcharge = as_decimal(row.get("surcharge_amount"))
        withholding = as_decimal(row.get("withholding_amount"))
        surcharge = ZERO if surcharge is None else surcharge        # missing → 0 (REQ-PI-31)
        withholding = ZERO if withholding is None else withholding
        common = {"supplier_name": supplier_label(row, ref),
                  "invoice_number": text_or_ref(row.get("invoice_number"), ref)}

        if base is not None and rate is not None and vat is not None:           # VAT amount
            expected = percent_of(base, rate)
            if not within_tolerance(expected, vat, VAT_TOLERANCE):
                alerts.append(_alert(ref, "vat_amount_mismatch",
                                     f"VAT amount mismatch: {common['invoice_number']}",
                                     {**common, "base_amount": _m(base), "vat_rate": str(rate),
                                      "expected_vat_amount": _m(expected), "vat_amount": _m(vat)}))
        if base is not None and vat is not None and total is not None:          # total
            expected_total = net_total([base, vat, surcharge], [withholding])    # uses the STATED VAT
            if not within_tolerance(expected_total, total, TOTAL_TOLERANCE):
                alerts.append(_alert(ref, "total_mismatch",
                                     f"Invoice total mismatch: {common['invoice_number']}",
                                     {**common, "base_amount": _m(base), "vat_amount": _m(vat),
                                      "surcharge_amount": _m(surcharge),
                                      "withholding_amount": _m(withholding),
                                      "expected_total": _m(expected_total), "total": _m(total)}))
        if rate is not None and rate not in ALLOWED_VAT_RATES:                  # rate
            alerts.append(_alert(ref, "vat_rate_not_allowed",
                                 f"Unexpected VAT rate: {common['invoice_number']}",
                                 {**common, "vat_rate": str(rate),
                                  "allowed_vat_rates": ", ".join(str(r) for r in ALLOWED_VAT_RATES)}))
    return finish(alerts)


def _m(amount: Decimal) -> str:
    """Money as a two-decimal string (Finance Rule 3)."""
    return str(round_to_cents(amount))


def _alert(ref: str, variant: str, title: str, data: dict) -> Alert:
    """warning alert citing the invoice row."""
    return Alert(detector="pi.vat_error", severity="warning", title=title,
                 source_refs=[ref], data={"variant": variant, **data})
```

`rate not in ALLOWED_VAT_RATES` is a value comparison, so `Decimal("21.00")` is allowed. The
`allowed_vat_rates` string uses `", "` as separator so the number guard tokenises `21, 10, 4, 0`
as four plain numbers (a bare `21,10` would read as one European number). A wrong VAT amount with a
total consistent with that stated VAT gives exactly one alert (P7): the total check is computed
from the stated `vat_amount`. Surcharge and withholding are never recomputed (OD-PI-16).

### 9.2 Edge behaviour (REQ-PI-33)

0.01 accepted / 0.02 alerts is `within_tolerance(…, Decimal("0.01"))` inclusive; strings and
floats are wrong types → `as_decimal` is `None` → that check skipped; `NaN`/`None` likewise;
`percent_of(Decimal("0.50"), Decimal("21"))` is `0.11` (half-up), so a stated `0.11` is clean and
`0.09` alerts; withholding larger than base + VAT gives a negative `expected_total`, compared with
`within_tolerance` like any other value (a `total_mismatch`, never an error).

---

## 10 — `pi.reconciliation` (`reconcile` in `utils.py`, detector in `reconciliation.py`)

### 10.1 Constants, usable rows and views (REQ-PI-35)

```python
PAYMENT_MATCH_WINDOW_DAYS: int = 60
UNPAID_GRACE_DAYS: int = 15
MATCH_AMOUNT_TOLERANCE: Decimal = Decimal("0.01")


@dataclass(frozen=True)
class InvoiceView:
    ref: str
    tax: str
    issue: date
    due: date
    total: Decimal
    currency: str


@dataclass(frozen=True)
class PaymentView:
    ref: str
    day: date
    amount: Decimal
    currency: str


def invoice_view(row: Mapping[str, Any]) -> InvoiceView | None:
    """Usable invoice: issue_date, due_date, total, currency and supplier tax_key present."""
    ref = as_text(row.get("source_ref"))
    tax = tax_key(as_text(row.get("supplier_tax_id")) or "")
    issue, due = as_date(row.get("issue_date")), as_date(row.get("due_date"))
    total, currency = as_decimal(row.get("total")), as_text(row.get("currency"))
    if ref is None or not tax or issue is None or due is None or total is None or currency is None:
        return None
    return InvoiceView(ref, tax, issue, due, total, currency)


def payment_view(row: Mapping[str, Any]) -> PaymentView | None:
    """Usable payment: a debit with date, amount and currency present."""
    ref = as_text(row.get("source_ref"))
    day, amount = as_date(row.get("date")), as_decimal(row.get("amount"))
    currency = as_text(row.get("currency"))
    if ref is None or as_text(row.get("flow")) != "debit" or day is None or amount is None \
            or currency is None:
        return None
    return PaymentView(ref, day, amount, currency)
```

Rows that are not usable belong to no bucket and never raise.

### 10.2 Supplier payments (REQ-PI-36)

Supplier payments are the usable payments that `attribute_payment` assigns to a master supplier;
`payment_supplier[ref]` records the supplier's `tax_key`. Every other debit is "not a supplier
payment": no bucket, no alert.

### 10.3 One-to-one greedy matching (REQ-PI-37)

```python
@dataclass(frozen=True)
class Reconciliation:
    invoice_buckets: dict[str, str]          # source_ref -> "matched" | "open_not_due" | "overdue"
    payment_buckets: dict[str, str]          # source_ref -> "matched" | "unmatched"
    matches: list[tuple[str, str]]           # (invoice ref, payment ref), in matching order
    payment_supplier: dict[str, str]         # payment ref -> tax_key of the attributed supplier


def reconcile(invoices: Any, suppliers: Any, payments: Any, as_of: date | None) -> Reconciliation:
    """Match invoices to supplier payments one-to-one and bucket everything. Pure; never raises."""
    master = build_master(suppliers)

    invoice_views = [v for v in (invoice_view(r) for r in load_rows(invoices, "issue_date"))
                     if v is not None]                      # already in (issue_date, ref) order

    supplier_payments: list[PaymentView] = []
    payment_supplier: dict[str, str] = {}
    for row in load_rows(payments, "date"):
        view = payment_view(row)
        if view is None:
            continue
        sup = attribute_payment(row, master)
        if sup is None:
            continue                                        # not a supplier payment
        supplier_payments.append(view)
        payment_supplier[view.ref] = tax_key(as_text(sup.get("tax_id")) or "")
    free = sorted(supplier_payments, key=lambda p: (p.day, source_ref_key(p.ref)))

    matched_payments: set[str] = set()
    matches: list[tuple[str, str]] = []
    for inv in invoice_views:
        if inv.tax not in master.by_tax:
            continue                                        # unknown supplier: never matched (OD-PI-11)
        last_day = inv.due + timedelta(days=PAYMENT_MATCH_WINDOW_DAYS)
        for pay in free:                                    # (date, ref) order: first fit = smallest
            if (pay.ref in matched_payments
                    or payment_supplier[pay.ref] != inv.tax
                    or pay.currency != inv.currency
                    or not within_tolerance(pay.amount, inv.total, MATCH_AMOUNT_TOLERANCE)
                    or not (inv.issue <= pay.day <= last_day)):
                continue
            matched_payments.add(pay.ref)
            matches.append((inv.ref, pay.ref))
            break
```

The matching is greedy: invoices are visited in `(issue_date, source_ref)` order, and each takes the
candidate payment smallest by `(date, source_ref)`. Candidates are not-yet-matched payments of the
same supplier and currency, within `MATCH_AMOUNT_TOLERANCE` of the total, dated from the issue date
to `due_date + PAYMENT_MATCH_WINDOW_DAYS`, both ends inclusive. Partial payments, overpayments and
payments before the issue date are not candidates (OD-PI-17).

### 10.4 Buckets (REQ-PI-38)

```python
    paid_invoices = {inv_ref for inv_ref, _ in matches}
    invoice_buckets: dict[str, str] = {}
    for inv in invoice_views:
        if inv.ref in paid_invoices:
            invoice_buckets[inv.ref] = "matched"
        elif as_of is not None and as_of > inv.due + timedelta(days=UNPAID_GRACE_DAYS):
            invoice_buckets[inv.ref] = "overdue"            # strictly later: due+15 is still open
        else:
            invoice_buckets[inv.ref] = "open_not_due"
    payment_buckets = {p.ref: ("matched" if p.ref in matched_payments else "unmatched")
                       for p in supplier_payments}
    return Reconciliation(invoice_buckets, payment_buckets, matches, payment_supplier)
```

Every usable invoice is in exactly one bucket (`matched`, `open_not_due`, `overdue`); every supplier
payment is in exactly one of `matched`, `unmatched`; `matches` is one-to-one by construction
(`matched_payments` and the single `break`). An invoice of a supplier absent from the master is
never matched, so it ends `open_not_due` or `overdue` (OD-PI-11). With `as_of = None` nothing is
overdue.

### 10.5 Detector and alerts (REQ-PI-34, REQ-PI-39)

```python
@register("pi.reconciliation")
def detect_reconciliation(ledger: pd.DataFrame, context: Mapping[str, Any]) -> list[Alert]:
    """Report overdue invoices and supplier payments that match no invoice."""
    suppliers, payments = context.get("suppliers"), context.get("payments")
    as_of = resolve_as_of(ledger, context)
    rec = reconcile(ledger, suppliers, payments, as_of)
    master = build_master(suppliers)
    alerts: list[Alert] = []

    for row in load_rows(ledger, "issue_date"):
        view = invoice_view(row)
        if view is None or rec.invoice_buckets.get(view.ref) != "overdue" or as_of is None:
            continue
        number = text_or_ref(row.get("invoice_number"), view.ref)
        name = supplier_label(row, view.ref)
        alerts.append(Alert(
            detector="pi.reconciliation", severity="warning",
            title=f"Unpaid invoice: {number} ({name})", source_refs=[view.ref],
            data={"variant": "invoice_overdue", "supplier_name": name, "invoice_number": number,
                  "total": str(round_to_cents(view.total)), "due_date": view.due.isoformat(),
                  "due_date_is_default": as_bool(row.get("due_date_is_default")),
                  "as_of": as_of.isoformat(), "days_past_due": (as_of - view.due).days}))

    for row in load_rows(payments, "date"):
        view = payment_view(row)
        if view is None or rec.payment_buckets.get(view.ref) != "unmatched":
            continue
        sup = master.by_tax[rec.payment_supplier[view.ref]]
        sup_ref = as_text(sup.get("source_ref")) or ""
        name = text_or_ref(sup.get("supplier_name"), sup_ref)
        alerts.append(Alert(
            detector="pi.reconciliation", severity="warning",
            title=f"Payment without invoice: {name}", source_refs=sort_refs([view.ref, sup_ref]),
            data={"variant": "payment_without_invoice", "supplier_name": name,
                  "payment_date": view.day.isoformat(),
                  "payment_amount": str(round_to_cents(view.amount)), "currency": view.currency}))
    return finish(alerts)
```

With an empty ledger, a non-empty master and an unmatched supplier payment the second loop alerts;
with everything empty both loops are empty and the result is `[]` (REQ-DET-05, REQ-PI-34). The
UI status column uses the same `Reconciliation` object (✅ `matched`, 🕯️ `open_not_due`,
💀 `overdue`, blank when the row is not usable).

### 10.6 Edge behaviour (REQ-PI-40)

| Case | Mechanism |
|---|---|
| payment on the issue date / on `due + 60` matches; one day outside does not | inclusive bounds in `inv.issue <= pay.day <= last_day` |
| `due + 15` open, `due + 16` overdue | `as_of > due + timedelta(15)` |
| amount differs by 0.01 matches, 0.02 does not | `within_tolerance` inclusive |
| different currency | `pay.currency != inv.currency` |
| two equal invoices, two payments | each invoice takes the earliest free payment |
| invoice paid twice | second payment stays free → `unmatched` (P9) |
| credits | `payment_view` requires `flow == "debit"` |
| attributed by name / by IBAN | `attribute_payment` |
| unknown counterparty and IBAN | no attribution → no bucket |
| `as_of = None` | overdue branch false |
| defaulted due date | `due_date_is_default` copied into the alert |
| duplicate `source_ref` | `load_rows` |

---

## 11 — Acceptance walk-throughs P1–P12

Each walk-through is a required Tier 1 test `test_pi_acceptance_pNN_<slug>` built from the minimal
fixture below. Notation: `inv.csv:i`, `sup.csv:i`, `pay.csv:i` are `source_ref`s; `M(x)` is
`str(round_to_cents(x))`; "tax" is the supplier's `tax_key`. Fixture suppliers use Finance Rule 5
identifiers: `SUP_A` = "Suministros Aurora, S.L." with tax id `B00000001`; `IBAN_A` =
`ES88 2100 0418 5602 0005 1332` (valid mod-97, national digits `56`); `IBAN_B` =
`make_test_iban("0049", "1500", "0510012345")` (valid, wrong national digits, different from
`IBAN_A`). Unless stated, invoices are `EUR`, base 100.00, rate 21, VAT 21.00, total 121.00.

**P1 — the same invoice twice.** Rows `inv.csv:0`, `inv.csv:1`: `SUP_A`, number `F-2026-0042`,
issued 2026-03-02, due missing → defaulted 2026-04-01 (`due_date_is_default`). No suppliers, no
payments, `as_of` not given.
- `pi.duplicate_invoice`: both usable (`n1 = F20260042`, tax `B00000001`); the pair has equal
  currency, equal `N1`, `days = 0 < 180` → `same_number`, rank 3. One component of two → one alert:
  `critical`, title `Duplicate invoice: F-2026-0042 (Suministros Aurora, S.L.)`, `source_refs`
  `[inv.csv:0, inv.csv:1]`, `invoice_count 2`, `totals ["121.00","121.00"]`, `days_apart 0`.
- `pi.iban_change`: master empty; both IBAN cells missing → `[]`.
- `pi.vat_error`: `percent_of(100.00, 21) = 21.00` equals the stated VAT; `net_total([100.00,
  21.00, 0], [0]) = 121.00` equals the total; 21 ∈ `ALLOWED_VAT_RATES` → `[]`.
- `pi.reconciliation`: `as_of` = latest of the issue dates = 2026-03-02; the supplier is not in the
  master, so neither invoice is matched; `2026-03-02 > 2026-04-01 + 15 days` is false → both
  `open_not_due`; no payments → `[]`.
- Result: exactly one alert in total, `critical`, `variant="same_number"`. ✓

**P2 — monthly rent.** `ALQ-2026-01/02/03`, issued 2026-01-05, 2026-02-04, 2026-03-06 (30 days
apart), same total 726.00, same supplier.
- `n1` values `ALQ202601/02/03` differ; totals equal; `n2` values `ALQ20261/2/3` differ; the day gaps
  are 30, 30 and 60, all `>= 7` → every `_pair_variant` is `None`. No component of two → `[]`. ✓

**P3 — near-identical numbers.** `F-2026-0042` issued 2026-03-02 and `F2026-042` issued 2026-03-05,
same supplier, total 242.00.
- `n1`: `F20260042` ≠ `F2026042`; totals equal; `n2`: `F202642` = `F202642` → `near_identical_number`
  (rank 2, no date window). One alert: `warning`, title `Possible duplicate invoice: F-2026-0042
  (Suministros Aurora, S.L.)`, `days_apart 3`, `total "242.00"`. ✓

**P4 — IBAN written with spaces and lowercase.** Master `sup.csv:0` (`SUP_A`, `IBAN_A`); invoice
`inv.csv:0` with IBAN cell `es88 2100 0418 5602 0005 1332`.
- Master loop: `iban_key = ES8821000418560200051332`, `iban_problem = None` → no alert.
- Invoice: `iban_key` is the same string, `problem = None`; `sup = by_tax["B00000001"]`;
  `_valid_master_key(sup)` is that same key → `master_key == key` → `continue`. No payments.
- Result: `[]`. ✓

**P5 — a new valid IBAN.** Same master; invoice IBAN cell `IBAN_B`.
- Invoice: `problem = None`, `master_key` = key of `IBAN_A` ≠ key of `IBAN_B` → `_invoice_differs`.
  One alert: `critical`, title `Poltergeist IBAN: Suministros Aurora, S.L.`, `source_refs
  [inv.csv:0, sup.csv:0]`, `invoice_iban_masked "****2345"`, `master_iban_masked "****1332"`,
  `last4_identical False`, `verification_message == VERIFY_BY_PHONE_MESSAGE`. ✓

**P6 — correct VAT.** base 100.00, rate 21, VAT 21.00, total 121.00. VAT check: expected 21.00 vs
21.00 → within tolerance. Total check: `net_total([100.00, 21.00, 0], [0]) = 121.00` → within
tolerance. Rate 21 allowed. `[]`. ✓

**P7 — wrong VAT, consistent total.** base 100.00, rate 21, VAT 12.10, total 112.10.
- VAT check: expected 21.00, stated 12.10, difference 8.90 > 0.01 → `vat_amount_mismatch`.
- Total check: `net_total([100.00, 12.10, 0], [0]) = 112.10` equals the stated total → silent.
- Rate check: 21 allowed → silent.
- Result: exactly one `warning`, `variant="vat_amount_mismatch"`, `expected_vat_amount "21.00"`,
  `vat_amount "12.10"`. ✓

**P8 — withholding (IRPF).** base 1000.00, rate 21, VAT 210.00, withholding 150.00, total 1060.00.
VAT: `percent_of(1000.00, 21) = 210.00` ✓. Total: `net_total([1000.00, 210.00, 0], [150.00]) =
1060.00` ✓. `[]`. ✓

**P9 — one invoice paid twice.** Master `sup.csv:0` = "Luigi Rossi", tax `00000001T`, `IBAN_A`.
Invoice `inv.csv:0`: number `R-2026-009`, issued 2026-03-02, due 2026-04-01 (explicit), total 605.00.
Payments (debits, 605.00, counterparty "Luigi Rossi", IBAN `IBAN_A`): `pay.csv:0` on 2026-03-30,
`pay.csv:1` on 2026-04-02.
- `as_of` = latest issue/payment date = 2026-04-02.
- `reconcile`: both payments attribute by name (`LUIGIROSSI`, one master hit) to tax `00000001T`.
  Invoice `inv.csv:0` (tax in master) has window `[2026-03-02, 2026-04-01 + 60 days]`; both payments
  fit date, amount and currency; `free` is ordered `(2026-03-30, pay.csv:0)`, `(2026-04-02,
  pay.csv:1)` → the first fit `pay.csv:0` is matched, then `break`.
- Buckets: `inv.csv:0` → `matched`; `pay.csv:0` → `matched`; `pay.csv:1` → `unmatched`.
- Alerts: no overdue (the only invoice is matched); `pay.csv:1` is `unmatched` → one
  `payment_without_invoice`, `source_refs [pay.csv:1, sup.csv:0]`, `payment_date "2026-04-02"`,
  `payment_amount "605.00"`. ✓ (`pi.iban_change` is silent: both payment IBANs equal the master.)

**P10 — same total, different numbers (3 gaps).** Same supplier and total 90.75; numbers
`FAC-0101` and `FAC-0102` (`n2` `FAC101` ≠ `FAC102`, `n1` differ).
- 6 days apart (2026-03-02, 2026-03-08): totals equal, `n2` differ, `6 < 7` → `same_total_close_dates`;
  one `warning`, `days_apart 6`.
- 7 days apart: `7 < 7` is false → `None` → `[]`.
- 8 days apart: `[]`. ✓ (parametrised test over 6, 7, 8.)

**P11 — surcharge (recargo de equivalencia).** base 100.00, rate 21, VAT 21.00, surcharge 5.20,
total 126.20. `net_total([100.00, 21.00, 5.20], [0]) = 126.20` ✓ → `[]`. ✓

**P12 — hyphenated and empty IBANs.** Master as in P4.
- (a) Invoice IBAN `ES88-2100-0418-5602-0005-1332`: `as_text` ok; `iban_key` keeps the hyphens;
  `IBAN_FORMAT_RE.fullmatch` fails (hyphen is outside the class) → `problem = "format"`. One alert:
  `warning`, `variant="iban_invalid"`, `subject "invoice"`, `reason "format"`, `iban_masked
  "****1332"`, `source_refs [inv.csv:0]`; the loop `continue`s, so nothing is compared with the
  master and nothing raises.
- (b) Invoice IBAN `NaN`: `as_text` is `None` → `_iban_state` is `None` → skipped. `[]`. ✓

**REQ-PI-21a — annual restart.** Same supplier and number `F-2026-0042`; totals arbitrary.
- Issued 2026-03-02 and 2026-03-04: equal `N1`, `days = 2 < 180` → `same_number`;
  `test_pi_same_number_2_days_apart_is_critical`: one `critical` alert.
- Issued 2026-03-02 and 2026-09-18: `days = 200 >= 180` → `_pair_variant` returns `None`; the branch
  for equal `N1` returns before B/C → `[]`. `test_pi_same_number_200_days_apart_no_alert`. ✓
- Boundary: 2026-08-28 (179 days) alerts, 2026-08-29 (180 days) does not.

---

## 12 — Explanation layer (`explain_support.py`)

### 12.1 Calling the explainer (REQ-PI-41, REQ-PI-44)

```python
ROW_COLUMNS: tuple[str, ...] = (
    "invoice_number", "supplier_name", "issue_date", "due_date", "base_amount", "vat_rate",
    "vat_amount", "surcharge_amount", "withholding_amount", "total", "currency", "source_ref",
)   # never iban, supplier_tax_id, tax_id, id or description


def explain_alert(alert, invoices, suppliers, payments, *, client=None) -> Explanation:
    rows = build_explain_rows(alert, invoices, suppliers, payments)
    return explain_with_meta(alert, rows, fallback_template=template_for(alert),
                             client=client, row_columns=ROW_COLUMNS)
```

The app builds no prompt (REQ-EXP-06/07 hold inside the explainer). With no `OPENAI_API_KEY` and no
client, `explain_with_meta` returns the filled fallback without a network call (REQ-EXP-02); the
app has no special handling.

### 12.2 `build_explain_rows` (REQ-PI-42)

```python
def build_explain_rows(alert: Alert, invoices: pd.DataFrame, suppliers: pd.DataFrame,
                       payments: pd.DataFrame) -> pd.DataFrame:
    """Rows cited by the alert, from whichever frame holds them, reduced to ROW_COLUMNS."""
    found: dict[str, dict] = {}
    for frame in (invoices, suppliers, payments):
        if not isinstance(frame, pd.DataFrame) or "source_ref" not in frame.columns:
            continue
        cols = [c for c in ROW_COLUMNS if c in frame.columns]
        for rec in frame[frame["source_ref"].isin(alert.source_refs)][cols].to_dict("records"):
            found.setdefault(rec["source_ref"], rec)
    records = [found[ref] for ref in alert.source_refs if ref in found]
    return pd.DataFrame(records, columns=list(ROW_COLUMNS))      # absent cells stay missing
```

Payment rows therefore contribute only `currency` and `source_ref`, master rows only
`supplier_name` and `source_ref`: every payment amount, payment date and counterparty an
explanation may mention comes from `Alert.data` (REQ-DET-09).

### 12.3 Template completeness (REQ-PI-43)

The app has no wrapper of its own: the stub client and the tests call ledger-core's public
`ledger_kit.explainer.fill_fallback(template, alert)` directly (design note DN-9; an app never
imports a private name). `test_pi_explain_support.py` builds one real
alert of each of the 11 variants, fills its template, asserts that no `{` or `}` remains, and
asserts that a sentence restating only `Alert.data` values and cited cells passes the number guard.

### 12.4 Templates (REQ-PI-45)

`TEMPLATES: dict[tuple[str, str], str]` is keyed by `(alert.detector, alert.data["variant"])`;
`template_for(alert)` looks it up. `{key:money}` formats with `format_amount`; `{key}` is plain;
`{source_refs}` is the comma-joined refs. Templates state facts and recommend nothing
(Finance Rule 8). `SAME_DAY_TEMPLATES` (showcase REQ-SC-07) holds the wording of the three
duplicate variants for invoices that share one issue date; `template_for` returns it when
`first_issue_date == last_issue_date`. The two critical IBAN templates do not contain
`{verification_message}`: the phone box shows it once (REQ-SC-08).

```python
TEMPLATES: dict[tuple[str, str], str] = {
    ("pi.duplicate_invoice", "same_number"):
        "Supplier {supplier_name} sent {invoice_count} invoices with the same invoice number, "
        "issued between {first_issue_date} and {last_issue_date}. Source: {source_refs}.",
    ("pi.duplicate_invoice", "near_identical_number"):
        "Supplier {supplier_name} has {invoice_count} invoices with near-identical numbers and the "
        "same total of {total:money}, issued {days_apart} days apart. Source: {source_refs}.",
    ("pi.duplicate_invoice", "same_total_close_dates"):
        "Supplier {supplier_name} has {invoice_count} invoices with the same total of {total:money}, "
        "issued {days_apart} days apart. Source: {source_refs}.",
    ("pi.iban_change", "invoice_iban_differs_from_master"):
        "Invoice {invoice_number} from {supplier_name} names the account {invoice_iban_masked}, "
        "which differs from the account {master_iban_masked} in the supplier master. "
        "Source: {source_refs}.",
    ("pi.iban_change", "payment_to_non_master_iban"):
        "A payment of {payment_amount:money} on {payment_date} to {supplier_name} went to the "
        "account {payment_iban_masked}, which differs from the account {master_iban_masked} in the "
        "supplier master. Source: {source_refs}.",
    ("pi.iban_change", "iban_invalid"):
        "The IBAN {iban_masked} on the {subject} {label} is not a valid IBAN (failed {reason} "
        "check). Source: {source_refs}.",
    ("pi.vat_error", "vat_amount_mismatch"):
        "Invoice {invoice_number} from {supplier_name} states VAT of {vat_amount:money}; "
        "{vat_rate} % of the base {base_amount:money} is {expected_vat_amount:money}. "
        "Source: {source_refs}.",
    ("pi.vat_error", "total_mismatch"):
        "Invoice {invoice_number} from {supplier_name} states a total of {total:money}; base "
        "{base_amount:money} plus VAT {vat_amount:money} plus surcharge {surcharge_amount:money} "
        "minus withholding {withholding_amount:money} is {expected_total:money}. "
        "Source: {source_refs}.",
    ("pi.vat_error", "vat_rate_not_allowed"):
        "Invoice {invoice_number} from {supplier_name} uses a VAT rate of {vat_rate} %, which is "
        "not one of the supported rates ({allowed_vat_rates}). Source: {source_refs}.",
    ("pi.reconciliation", "invoice_overdue"):
        "Invoice {invoice_number} from {supplier_name} for {total:money} was due on {due_date} and "
        "no matching payment was found as of {as_of}. Source: {source_refs}.",
    ("pi.reconciliation", "payment_without_invoice"):
        "A payment of {payment_amount:money} to {supplier_name} on {payment_date} could not be "
        "matched to any invoice. Source: {source_refs}.",
}
```

Every placeholder is a field of `Alert.data` listed in sections 7–10, so the number guard allows
each figure (REQ-DET-09). The two IBAN fields in templates are masked values.

### 12.5 Guard badge (REQ-PI-46)

```python
def guard_badge(meta: Explanation, api_key_present: bool) -> str:
    """Badge text for one explanation (same semantics as App 1, REQ-ZS-37)."""
    if meta.source == "llm":
        return "🤖 ✓ LLM text verified by number guard"
    if meta.rejected_numbers:
        return f"⚠️ LLM answer rejected: invented number {', '.join(meta.rejected_numbers)}"
    return "📋 Template (no API key)" if not api_key_present else "📋 Template (LLM unavailable)"
```

### 12.6 Hallucination simulator (REQ-PI-47, OD-PI-12)

```python
class HallucinatingStubClient:
    """OpenAI-compatible stub whose answer is the filled fallback plus a foreign number."""

    INJECTED_NUMBER: str = "99999.99"      # absent from every real alert

    def __init__(self, filled_fallback: str) -> None:
        self._text = f"{filled_fallback} Total exposure: {self.INJECTED_NUMBER} EUR."

    @property
    def chat(self): return self

    @property
    def completions(self): return self

    def create(self, *, messages, **_kwargs):
        from types import SimpleNamespace
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self._text))])
```

The app builds it per alert: `HallucinatingStubClient(fill_fallback(template_for(alert), alert))`.
The filled fallback passes the guard (all its figures are allowed), so the only rejected token is
`99999.99` and the ⚠️ badge appears without an API key. It is a separate copy of App 1's stub
because apps must not import each other. Explanations are cached in
`st.session_state["explanations"]` by `(alert.id, client_mode)`, `client_mode ∈ {"real",
"hallucinate"}`.

---

## 13 — Streamlit UI (`app.py`, `flashlight.py`)

### 13.1 Theme: the haunted ledger (REQ-PI-48)

`flashlight.HAUNTED_CSS` is injected once with `st.markdown(f"<style>{HAUNTED_CSS}</style>",
unsafe_allow_html=True)`. No external CSS framework.

```css
.stApp { background: #12101a; color: #e8dcc0; }                       /* candle-lit study */
.ledger { width: 100%; border-collapse: separate; border-spacing: 0; font-family: Georgia, serif; }
.ledger th { color: #ffb347; text-align: left; border-bottom: 1px solid #3a3350; }
.ledger td { padding: 4px 8px; border-bottom: 1px solid #241f33; }
.ledger.has-lit tr.dim { opacity: 0.25; }                              /* every other row dimmed */
.ledger tr.lit td { background: radial-gradient(circle at 50% 50%, #1f3d33 0%, #12101a 120%);
                    color: #ffffff; box-shadow: inset 0 0 14px 2px #7cffb2; }
.ledger tr.lit td:first-child { border-left: 3px solid #7cffb2; }
.badge-critical { color: #ff6b6b; }  .badge-warning { color: #ffd166; }
```

`box-shadow` is set on the cells because it is unreliable on `<tr>` elements. Ghost-green is
`#7cffb2`; severity badges are 🔴 critical and 🟡 warning.

### 13.2 Layout (REQ-PI-49)

1. Severity summary row: two `st.metric`s (critical, warning).
2. The haunted ledger: **all** invoices with `source_ref` and a status column from
   `Pipeline.reconciliation.invoice_buckets` (✅ / 🕯️ / 💀, blank when the row is not usable). Amount
   columns are shown with `format_amount` (Finance Rule 4); the IBAN column shows `mask_iban(...)`;
   no tax-id column.
3. Alert cards grouped critical → warning: title, detector `LABELS`, explanation, guard badge,
   `source_refs`; for the two critical IBAN variants `verification_message` verbatim; a caption when
   `last4_identical` ("The last four characters match; the difference is elsewhere in the IBAN.")
   and when `due_date_is_default` ("Due date assumed: issue date plus the default payment term.").
4. The `as_of` date in use (`Pipeline.as_of_used`) with the note that it defaults to the latest date
   in the data.

A notice (REQ-PI-04) states which checks need which file: without the supplier master only malformed
IBANs are reported and every invoice counts as unpaid-so-far; without payments no invoice can be
matched.

### 13.3 Flashlight (REQ-PI-50)

```python
import html

def _esc(value: object) -> str:
    return html.escape("" if is_missing(value) else str(value), quote=True)


def render_ledger_html(df: pd.DataFrame, lit_refs: Collection[str]) -> str:
    """Render `df` as an HTML table; rows in `lit_refs` are lit, all others dimmed.

    Every cell and header is HTML-escaped; only fixed class names reach attributes. An empty
    `lit_refs` dims nothing. Pure: no Streamlit, no I/O.
    """
    lit = frozenset(lit_refs)
    cols = list(df.columns)
    head = "".join(f"<th>{_esc(c)}</th>" for c in cols)
    body = []
    for rec in df.to_dict("records"):
        cls = "" if not lit else ("lit" if rec.get("source_ref") in lit else "dim")
        cells = "".join(f"<td>{_esc(rec.get(c))}</td>" for c in cols)
        body.append(f'<tr class="{cls}">{cells}</tr>')
    table_cls = "ledger has-lit" if lit else "ledger"
    return (f'<table class="{table_cls}"><thead><tr>{head}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table>')
```

The alerts are offered by a single-selection `st.radio(key="selected_alert")` whose options are
`NO_FLASHLIGHT` plus every `alert.id` (`format_func` shows `severity icon + title`). The selected
alert's `source_refs` become `lit_refs`. Cited master and payment rows are rendered below the ledger
by two more calls of `render_ledger_html` over the cited subset of each frame, passing all their
refs as lit (same styling). Quarantined rows are in an `st.expander` warning with file, row, reason
and `raw`; the panel states the multi-rate limitation of OD-PI-08. Before the radio is created:

```python
options = [NO_FLASHLIGHT, *[a.id for a in alerts]]
if st.session_state.get("selected_alert") not in options:
    st.session_state["selected_alert"] = NO_FLASHLIGHT       # allowed: the widget is not yet created
```

**Ledger layout (REQ-PI-71, gate-2 execution review of 25 Nov).** When the frame is the ledger
view (it holds `source_ref` and every key of `flashlight.LEDGER_VISIBLE`), `render_ledger_html`
draws the columns of `LEDGER_VISIBLE` in this order under plain headers: Line, Status, Invoice,
Supplier, Total, Issued, Due, Base, VAT rate, VAT, Surcharge, Withholding, IBAN. The `source_ref`
is no cell: each row carries it as `data-ref`, the Line cell as `title`, both through `_esc`, and
the lit/dim class is still decided by it. The Supplier cell has class `supplier`; `APP_CSS` lets
only that cell wrap (`white-space: normal; max-width: 15em`) and trims the padding to `3px 6px`,
so Line to Total fit a 1360 px window with the sidebar open; `.ledger-wrap` keeps
`overflow-x: auto` as a fallback. Any other frame (the cited master and payment rows) is still
drawn column by column under its own names. `ledger_view` and `LEDGER_COLUMNS` do not change.

### 13.4 Inputs (REQ-PI-51)

Sidebar: three `st.file_uploader`s (invoices `.csv`/`.json`, suppliers `.csv`, payments `.csv`);
a checkbox `use_as_of` and a `date_input` `as_of_date` (off by default); the
**Simulate a hallucinating LLM** toggle `hallucinate`; the **Load demo data** button. Uploaded
files are read as bytes (`Source(name, bytes)`), parsed through `run_pipeline`, and the
`Pipeline` is cached in `st.session_state["pipeline_cache"]` by the SHA-256 of the three byte
strings plus the `as_of` value. `as_of_date` is pre-seeded once with
`st.session_state.setdefault("as_of_date", UI_DEFAULT_AS_OF)` where `UI_DEFAULT_AS_OF =
date(2026, 1, 1)` is only a widget placeholder (it reaches a detector only if the user ticks the
box; DN-11). An uploaded file overrides the demo source for that input.

### 13.5 Load demo data (REQ-PI-52)

As in App 1 (REQ-ZS-40), the demo is loaded by an `on_click` callback that writes the widget keys
**before** the widgets are instantiated; an `if st.button(...)` body would raise
`StreamlitWidgetAlreadyInstantiatedError`:

```python
def load_demo() -> None:
    """Runs before the next rerun builds any widget, so writing widget keys is allowed."""
    demo = demo_inputs(CONFIG, ROOT)                          # reads the three paths of [demo]
    st.session_state["sources"] = {"invoices": demo.invoices, "suppliers": demo.suppliers,
                                   "payments": demo.payments}
    st.session_state["use_as_of"] = demo.as_of is not None
    if demo.as_of is not None:
        st.session_state["as_of_date"] = demo.as_of
    st.session_state["hallucinate"] = False
    st.session_state["selected_alert"] = NO_FLASHLIGHT

st.sidebar.button("Load demo data", on_click=load_demo)
```

Default values are set once with `st.session_state.setdefault(...)` before the widgets are created,
and the widgets pass no `value=`. After the click the next run parses the three demo files and
immediately shows the alerts of all four detectors (REQ-PI-69).

Session-state keys: widget keys `use_as_of`, `as_of_date`, `hallucinate`, `selected_alert`; data
keys `sources` (`dict[str, Source | None]`), `pipeline_cache` (`dict[str, Pipeline]`),
`explanations` (`dict[tuple[str, str], Explanation]`).

---

## 14 — Configuration and deployment

### 14.1 `config.toml` (REQ-PI-59, REQ-PI-60)

```toml
[demo]
suppliers_path = "data/samples/phantom_demo/suppliers.csv"
invoices_path  = "data/samples/phantom_demo/invoices.csv"
payments_path  = "data/samples/phantom_demo/payments.csv"
# as_of = "2026-10-30"     # absent by default: the latest date in the data is used
```

Paths are relative to the repository root. `settings.load_config(path)` uses `tomllib`;
`settings.to_date(value)` accepts a TOML string or date. No threshold, no secret.

### 14.2 Path bootstrap (REQ-PI-53)

The first executable lines of `app.py`, identical to App 1's, run before any `import ledger_kit`:

```python
import sys, pathlib
_ROOT = pathlib.Path(__file__).resolve().parents[2]   # ghost-ledger-kit/
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
```

### 14.3 Dependencies

`streamlit run apps/phantom_invoices/app.py` works on a clean clone, locally and on Community
Cloud, with only the optional `OPENAI_API_KEY`. The **root-level** `requirements.txt` lists all
runtime dependencies (no `-e .`). `apps/phantom_invoices/` contains **no** `requirements.txt`.

---

## 15 — Demo generator plan

### 15.1 Entry point and determinism (REQ-PI-54)

`python scripts/generate_samples.py --mode phantom-demo --seed 42` writes
`data/samples/phantom_demo/{suppliers,invoices,payments}.csv`. The script exposes:

```python
PHANTOM_CASES: dict[str, str]            # case id -> supplier tax id (section 15.3); seed-independent
CLEAN_SUPPLIERS: tuple[str, ...]         # tax ids of the nine clean suppliers
DEMO_LATEST_DATE: date = date(2026, 10, 30)

def build_phantom_demo(seed: int = 42) -> dict[str, str]:
    """{"suppliers.csv": text, "invoices.csv": text, "payments.csv": text}."""
def write_phantom_demo(out_dir: Path, seed: int = 42) -> None: ...
```

Randomness comes only from `random.Random(seed)`, consumed in a fixed order, and only the nine
clean suppliers use it; all planted cases are literal. Files are UTF-8 without BOM, written with
`csv.writer(lineterminator="\n")`, and `.gitattributes` marks them `-text` so a Windows checkout
does not rewrite line endings. Tests load the module by path (`importlib.util.spec_from_file_location`),
because `scripts/` is not a package. Running twice gives byte-identical files; the committed files
equal `build_phantom_demo(42)` (tested).

### 15.2 File formats (REQ-PI-55)

All three are plain dialect (comma, dot decimal, ISO dates).

| File | Columns |
|---|---|
| `suppliers.csv` | `supplier_name,tax_id,iban` (IBAN written in groups of four, upper case) |
| `invoices.csv` | `invoice_number,supplier_name,supplier_tax_id,issue_date,due_date,base_amount,vat_rate,vat_amount,surcharge_amount,withholding_amount,total,currency,iban` |
| `payments.csv` | `date,amount,currency,counterparty,description,iban` — **negative amounts** for debits, positive for credits |

Some invoice rows have an empty `due_date`, a `surcharge_amount`, a `withholding_amount`, or an
IBAN in spaced/lower-case/compact variants. The generator builds amounts from strings and the
`ledger_kit.utils.money` helpers (`percent_of`, `net_total`); it does no other money arithmetic.

### 15.3 Suppliers and the identifiers of Finance Rule 5 (REQ-PI-56, REQ-PI-58)

25 suppliers (20–26 required): 16 planted cases and 9 clean. `k` is the 1-based position in the plan
and drives every identifier, so tax ids and IBANs are seed-independent. Persons use fictional,
culturally diverse names.

| k | Case id (`PHANTOM_CASES` key) | Fictional supplier | Kind |
|---|---|---|---|
| 1 | `P1` | Suministros Ibéricos Aurora, S.L. | company |
| 2 | `P2` | Inmuebles Valdemar, S.L. | company |
| 3 | `P3` | Gráficas Montealto, S.L. | company |
| 4 | `P4` | Limpiezas Brillante Norte, S.L. | company |
| 5 | `P5` | Transportes Hermanos Lage, S.L. | company |
| 6 | `P6` | Material de Oficina Sierra Clara, S.L. | company |
| 7 | `P7` | Informática Rioja Sur, S.L. | company |
| 8 | `P8` | Ana García (Asesoría Fiscal) | person |
| 9 | `P9` | Luigi Rossi (Reformas) | person |
| 10 | `P10` | Distribuciones Costa Azul, S.L. | company |
| 11 | `P11` | Comercial Minorista Pérez, S.L. | company |
| 12 | `P12` | Sophie Dupont (Traducciones) | person |
| 13 | `NON_MASTER_PAYMENT` | Mantenimientos Delta Ibérica, S.L. | company |
| 14 | `OVERDUE` | Carpintería Roble Viejo, S.L. | company |
| 15 | `OPEN_NOT_DUE` | Catering Sabores del Sur, S.L. | company |
| 16 | `MULTI_RATE` | Obras y Reformas Atlántico, S.L. | company |
| 17–25 | clean `C1`–`C9` | Electricidad Luminar; Agua y Gas Cantábrico; Yusuf Demir (Mantenimiento); Seguros Faro Mediterráneo; Software Colmena; Papeles del Duero; Mei Chen (Diseño); Gestoría Tres Cantos; Jardinería Verde Mar | 7 companies (S.L.), 2 persons |

```python
# --- IBAN: valid ISO mod-97 checksum, deliberately wrong Spanish national check digits ---------
SPANISH_DC_WEIGHTS = (1, 2, 4, 8, 5, 10, 9, 7, 3, 6)

def _dc_digit(digits: str) -> int:
    total = sum(int(d) * w for d, w in zip(digits, SPANISH_DC_WEIGHTS))
    d = 11 - total % 11
    return {10: 1, 11: 0}.get(d, d)

def correct_national_dc(bank: str, branch: str, account: str) -> str:
    """Correct Spanish control digits; ('2100','0418','0200051332') -> '45'."""
    return f"{_dc_digit('00' + bank + branch)}{_dc_digit(account)}"

def wrong_national_dc(bank: str, branch: str, account: str) -> str:
    """Always different from the correct pair: '45' -> '56' (the example of REQ-PI-58)."""
    return f"{(int(correct_national_dc(bank, branch, account)) + 11) % 100:02d}"

def iban_check_digits(country: str, bban: str) -> str:
    """ISO 13616: 98 - (numeric(bban + country + '00') mod 97), two digits."""
    numeric = "".join(str(int(ch, 36)) for ch in bban + country + "00")
    return f"{98 - int(numeric) % 97:02d}"

def make_iban(bank: str, branch: str, account: str) -> str:
    """Compact Spanish IBAN with valid mod-97 and wrong national check digits."""
    bban = bank + branch + wrong_national_dc(bank, branch, account) + account
    return "ES" + iban_check_digits("ES", bban) + bban

def format_iban(compact: str) -> str:
    return " ".join(compact[i:i + 4] for i in range(0, len(compact), 4))
```

Hand check of the DC code against the documented example: for `2100 0418` the weighted sum of
`0021000418` is 95 → `11 - 95 % 11 = 4`; for account `0200051332` it is 105 → `11 - 105 % 11 = 5`;
correct pair `45`, wrong pair `(45 + 11) % 100 = 56`, matching `ES88 2100 0418 5602 0005 1332`.

Per supplier `k`: `(bank, branch) = BANKS[(k - 1) % 4]` with `BANKS = (("2100","0418"),
("0049","1500"), ("0182","5900"), ("0081","7000"))`; master account `f"{(k * 7_654_321) % 10**10:010d}"`;
the *other* valid account used by P5 and by the non-master payment is
`f"{(k * 7_654_321 + 1_111_111) % 10**10:010d}"`. Unrelated debit counterparties use `k = 100 + i`.

```python
# --- tax ids: wrong control character, a different id per supplier ------------------------------
NIF_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"

def cif_control_digit(body: str) -> int:
    """Correct control digit of a type-B CIF body (7 digits)."""
    total = 0
    for pos, ch in enumerate(body, start=1):
        d = int(ch)
        if pos % 2 == 1:
            d *= 2
            d = d // 10 + d % 10
        total += d
    return (10 - total % 10) % 10

def make_cif(k: int) -> str:
    body = f"{k:07d}"
    return f"B{body}{(cif_control_digit(body) + 1) % 10}"          # always wrong

def make_nif(k: int) -> str:
    n, remaining = 1000, k
    while remaining > 0:                      # k-th number above 1000 that is no multiple of 23
        n += 1
        if n % 23 != 0:                       # their correct letter is 'T'
            remaining -= 1
    return f"{n:08d}{NIF_LETTERS[(n % 23 + 1) % 23]}"             # the letter after the correct one
```

(`make_nif(k)` is the k-th number above 1000 that is not a multiple of 23, so every `k` gets a
distinct number: `1012 = 23 × 44` is skipped, `k = 12` gives `1013` and `k = 13` gives `1014`.) `00000000T` is never produced.
Companies use `make_cif(k)`, persons `make_nif(k)`. No e-mail address or phone number appears in
any file.

### 15.4 Planted rows (REQ-PI-57)

Latest date in the data is `DEMO_LATEST_DATE = 2026-10-30`, the date of one clean payment, so
`as_of` defaults to it. Every planted invoice that must not raise a reconciliation alert is either
paid inside the window or issued on/after 2026-09-15 and unpaid (`issue + 30 + 15 >= 2026-10-30`,
hence `open_not_due`). All amounts are EUR; `b` base, `r` rate, `v` VAT, `T` total.

| Case | Rows (number, issue, due) | Amounts | Payments | Expected alert(s) |
|---|---|---|---|---|
| P1 | `F-2026-0310` ×2, 2026-10-06, due 2026-11-05 | b 400.00, r 21, v 84.00, T 484.00 | none | `pi.duplicate_invoice` `critical` `same_number` |
| P2 | `ALQ-2026-01/02/03`, 2026-08-03 / 09-02 / 10-02, due +30 | T 726.00 each (b 600.00, v 126.00) | 08-05, 09-04, 10-05 | none |
| P3 | `F-2026-0042` 10-01 and `F2026-042` 10-04, due +30 | T 242.00 (b 200.00, v 42.00) | none | `warning` `near_identical_number` |
| P4 | `L-2026-118`, 07-06, due 08-05; invoice IBAN lower case with spaces | T 181.50 (b 150.00, v 31.50) | 08-04 to master IBAN | none |
| P5 | `T-2026-077`, 10-09, due 11-08; invoice IBAN = the other valid account | T 363.00 (b 300.00, v 63.00) | none | `pi.iban_change` `critical` `invoice_iban_differs_from_master` |
| P6 | `MO-2026-031`, 06-10, due 07-10 | T 121.00 | 07-08 | none |
| P7 | `IR-2026-044`, 10-13, due 11-12 | b 100.00, v **12.10**, T 112.10 | none | `pi.vat_error` `warning` `vat_amount_mismatch` |
| P8 | `AG-2026-007`, 07-01, due 07-31 | b 1000.00, v 210.00, withholding 150.00, T 1060.00 | 07-30 | none |
| P9 | `R-2026-009`, 07-14, due 08-13 | b 500.00, v 105.00, T 605.00 | 08-10 and 08-12, 605.00 each | `pi.reconciliation` `payment_without_invoice` (08-12) |
| P10 | `FAC-0101…0104`, 09-18 / 09-24 / 10-01 / 10-09, due +30 | T 90.75 each (b 75.00, v 15.75) | none | `warning` `same_total_close_dates` for 0101 + 0102 only (gaps 6, 7, 8) |
| P11 | `CM-2026-052`, 08-12, due 09-11 | b 100.00, v 21.00, surcharge 5.20, T 126.20 | 09-09 | none |
| P12 | `TR-2026-014`, 10-07 (IBAN `ES88-…` hyphenated, derived from the supplier's valid IBAN), `TR-2026-015`, 10-14 (IBAN empty) | T 60.50 and T 121.00 | none | `pi.iban_change` `warning` `iban_invalid` for `TR-2026-014` only |

### 15.5 Further plants (REQ-PI-57 a–e)

| Plant | Rows | Expected |
|---|---|---|
| (a) payment to a non-master IBAN (`NON_MASTER_PAYMENT`) | `MD-2026-210`, 08-18, due 09-17, T 1210.00 (b 1000.00, v 210.00); paid 2026-09-14, counterparty = the supplier name, IBAN = the other valid account | `pi.iban_change` `critical` `payment_to_non_master_iban`; the payment still matches the invoice, so no reconciliation alert |
| (b) overdue (`OVERDUE`) | `CR-2026-051`, 08-20, due 09-19, T 847.00 (b 700.00, v 147.00), unpaid | `invoice_overdue`: `2026-10-30 > 2026-09-19 + 15 days`, `days_past_due 41` |
| (c) open_not_due (`OPEN_NOT_DUE`) | `CS-2026-033`, 10-12, due 11-11, T 302.50 (b 250.00, v 52.50), unpaid | none (`open_not_due`); several planted invoices are also open |
| (d) multi-rate (`MULTI_RATE`) | `OB-2026-008`, 09-30, due 10-30: row 1 b 800.00 r 21 v 168.00 T 968.00; row 2 b 200.00 r 10 v 20.00 T 220.00; no payment | both rows quarantined with `multi_rate_invoice_out_of_scope`; no alert |
| (e) no `due_date` | the clean invoices with `(j + m) % 4 == 0` (section below) leave `due_date` empty | defaulted `issue + 30`, `due_date_is_default` true; no alert |

Clean suppliers `C1`–`C9` (supplier index `j = 0…8`): five monthly invoices `m = 0…4` (May–Sep)
dated `date(2026, 5 + m, 3 + (j * 5 + m * 3) % 20)`, numbers `f"{CODE}-2026-{m + 1:03d}"` (`CODE` a
two-letter code of the supplier), base `Decimal(f"{rng.randrange(80, 1800)}.{rng.randrange(100):02d}")`,
rate from `rng.choice((21, 21, 21, 10, 4, 0))`, `vat = percent_of(base, rate)`, `total =
net_total([base, vat])`; totals are redrawn until distinct within the supplier, so no duplicate
rule can fire. Due date is `issue + 30`, left empty when `(j + m) % 4 == 0`. The IBAN cell cycles
over empty / master format / compact lower case by `(j + m) % 3`. Each invoice is paid by a debit of
exactly its total on `min(issue + rng.randrange(10, 40) days, 2026-10-29)` to the master IBAN with
the supplier name as counterparty; the last invoice of `C9` is paid on `DEMO_LATEST_DATE`.
`payments.csv` also holds three credits (customer receipts, dated ≤ 2026-10-28) and four debits to
unrelated fictional counterparties with IBANs outside the master; the file is sorted by
`(date, counterparty, amount)`.

### 15.6 Size and expected outcome (REQ-PI-56, REQ-PI-69)

70 invoice rows (25 planted + 45 clean; 68 after the multi-rate quarantine; about two thirds are
clean invoices), 25 suppliers, 62 payment rows. `run_all(namespace="pi")` on the loaded demo yields
exactly **9 alerts**: 3 `critical` (P1, P5, non-master payment) and 6 `warning` (P3, P10, P12, P7,
P9, overdue). Every other supplier and every clean invoice is cited by no alert.

---

## 16 — Test plan

### 16.1 Builders and fixtures (`tests/conftest.py`, REQ-PI-62)

All fixtures use Finance-Rule-5 identifiers, fictional names and fixed literal dates; no fixture
reads the clock.

```python
def make_invoices(rows: list[dict]) -> pd.DataFrame:
    """Invoice frame with all INVOICE_COLUMNS; defaults EUR/rate 21; vat_amount and total derived
    with percent_of/net_total unless given; source_ref 'inv.csv:{i}'."""
def make_suppliers(rows: list[dict]) -> pd.DataFrame: ...   # SUPPLIER_COLUMNS, 'sup.csv:{i}'
def make_payments(rows: list[dict]) -> pd.DataFrame: ...    # CANONICAL_COLUMNS, 'pay.csv:{i}'
def ctx(suppliers=None, payments=None, as_of=None) -> MappingProxyType: ...
make_test_iban = generator.make_iban        # loaded by path from scripts/generate_samples.py
```

| Fixture | Content |
|---|---|
| `empty_ledger` | invoice-schema frame, zero rows, all columns |
| `single_row_ledger` | one clean invoice |
| `clean_ledger_10` | 10 clean invoices, with `payments_for_clean` (10 matching debits) and `suppliers_master`: no alert from any detector |
| `suppliers_master` | three suppliers with valid-checksum, wrong-national-digits IBANs |
| `payments_for_clean` | the ten matching payments |
| `ledger_with_duplicate_invoice` | P1 |
| `ledger_with_near_duplicate` | P3 |
| `ledger_with_iban_change` | P5 (invoice + master) |
| `ledger_with_vat_error` | P7 |
| `ledger_with_unpaid_invoice` | one overdue invoice and a later payment date that fixes `as_of` |
| `ledger_with_double_payment` | P9 |

### 16.2 Tiers per file

| File | Tier 1 (normal) | Tier 2 (edge) | Tier 3 (Hypothesis, `max_examples=200`) |
|---|---|---|---|
| `test_pi_utils.py` | N1/N2 table rows of REQ-PI-07; key helpers; `iban_problem` of valid/format/checksum; `source_ref_key` order | `as_*` on every dirty cell kind; `resolve_as_of` explicit/derived/`None`; no clock call (ast scan) | `test_dirty_cells_never_raise_helpers` |
| `test_pi_prepare.py` | multi-rate group removed, records shaped | missing rate not counted; `21` vs `21.00` is one rate; empty frame; input not mutated | `test_quarantine_partitions_rows` (clean + quarantined = input, disjoint) |
| `test_pi_duplicate_invoice.py` | `fires_on_typical_input`, `silent_on_clean_ledger`; P1, P2, P3, P10 (6/7/8); REQ-PI-21a (2 vs 200 days) | all rows of §7.6; groups of three with mixed rules give one alert of the top rule; consecutive numbers with equal totals → rule C (documents OD-PI-06); `DUPLICATE_WINDOW_DAYS <= SAME_NUMBER_WINDOW_DAYS` | `test_consecutive_numbers_with_different_totals_never_duplicate`; row order; subset of loaded refs; idempotency; dirty cells; empty input |
| `test_pi_iban_change.py` | `fires_on_typical_input`, `silent_on_clean_ledger`; P4, P5, P12; payment to non-master IBAN | all rows of §8.4; invalid master flagged once; attribution by name and by IBAN; one alert per row | `test_iban_spacing_and_case_never_fire`; `test_alert_data_never_contains_full_iban`; row order; subset of loaded refs; idempotency; dirty cells; empty input |
| `test_pi_vat_error.py` | `fires_on_typical_input`, `silent_on_clean_ledger`; P6, P7, P8, P11 | 0.01/0.02 on both amount checks; rate `21.00` allowed, `20`/`5` alert; half-up `0.11`/`0.09`; withholding > base + VAT; non-Decimal cells | `test_correct_invoice_never_fires_vat_check`; `test_vat_off_by_two_cents_or_more_always_fires`; row order; subset; idempotency; dirty cells; empty input |
| `test_pi_reconciliation.py` | `fires_on_typical_input`, `silent_on_clean_ledger`; P9; overdue; open_not_due | all rows of §10.6, boundaries 60/61, 15/16, 0.01/0.02; empty ledger + unmatched supplier payment alerts; all empty → `[]` | `test_every_invoice_and_supplier_payment_in_exactly_one_bucket`; row order; subset; idempotency; dirty cells; empty input |
| `test_pi_explain_support.py` | every template fills; `ROW_COLUMNS` reaches the client | guard rejects hallucinated amount, uncited date, IBAN-shaped token; stub yields `rejected_numbers == ("99999.99",)`; three (+1) badge texts | `test_guard_accepts_any_alert_data_sentence` |
| `test_pi_flashlight.py` | lit rows lit, others dimmed; no lit refs → nothing dimmed | `<script>` and quotes in any cell escaped; missing cells empty | `test_render_never_emits_unescaped_markup` |
| `test_pi_settings.py` | `load_config`; `demo_inputs`; `run_pipeline` on the minimal fixtures | missing files treated as empty; `.json` invoices routed to the JSON reader | — |
| `test_pi_demo_data.py` | determinism; committed files equal generator output | every IBAN mod-97 valid with wrong national digits; every tax id with a wrong control character, all distinct; no e-mail/phone | — |
| `test_pi_demo_e2e.py` | the 9 alerts of §15.6, per case via `PHANTOM_CASES`; multi-rate rows quarantined | clock mocked to two dates gives identical results; Load-demo `AppTest` click shows the alerts | — |

Detector tests call the detector directly with `MappingProxyType({"suppliers": …, "payments": …,
"as_of": …})`, and each detector file also has one test through `run_all(namespace="pi",
context=…)` (REQ-PI-61). Every Tier 1 test asserts the exact alert count, a non-empty
`source_refs` pointing at the right rows, and `Alert.detector` equal to the registered name.

### 16.3 Strategies

```python
def dirty_cell(): ...      # one_of(none, nan, "", "-", "\u00a0", text, floats, decimals(nan/inf), ints, dates)
def dirty_frame(columns): ...                   # object-dtype frame of dirty cells, 'source_ref' always text
def valid_iban(): ...                           # builds make_test_iban from 4-digit bank/branch and 10-digit account
def spaced_cased(iban): ...                     # random whitespace (space, \u00a0, tab) and random case
def consecutive_numbers(): ...                  # prefix, year, start, zero padding, rollover (0099 -> 0100)
def reconciliation_inputs(): ...                # few suppliers, totals drawn from a small set (forces collisions),
                                                # dates within 120 days, names from the master or unknown
```

Property tests never use function-scoped fixtures (REQ-TST-09). The VAT properties use
`percent_of`/`net_total` to build the consistent invoice, and `assume` to keep the shifted VAT
non-negative. The "no invention" property compares `Alert.source_refs` with
`loaded_source_refs(ledger, context)`.

### 16.4 Clock independence (REQ-PI-65)

1. `test_no_clock_calls_in_package`: parses every `.py` under `apps/phantom_invoices/` with `ast`
   and asserts there is no call to `today`, `now`, `utcnow` or `time.time`.
2. `test_alerts_identical_under_two_clocks`: runs `run_pi_detectors` on the demo inputs under
   `freeze_time("2020-01-01")` and `freeze_time("2031-12-31")` and asserts equal alert lists.

### 16.5 Gates (REQ-PI-67)

`pytest --cov=apps/phantom_invoices --cov-fail-under=80` passes; `ruff check` and
`ruff format --check` report nothing; every Tier 1–3 test passes before merge (`testing.md`).

---

## 17 — Traceability

| REQ | Design section | REQ | Design section |
|---|---|---|---|
| REQ-PI-01 | §1, §3 | REQ-PI-36 | §10.2 |
| REQ-PI-02 | §1.1, §3 | REQ-PI-37 | §10.3 |
| REQ-PI-03 | §3, §8.2, §10.1 | REQ-PI-38 | §10.4 |
| REQ-PI-04 | §3, §13.2 | REQ-PI-39 | §10.5 |
| REQ-PI-05 | §7.3, §10.3 | REQ-PI-40 | §10.6 |
| REQ-PI-06 | §4.1 | REQ-PI-41 | §12.1 |
| REQ-PI-07 | §4.2 | REQ-PI-42 | §12.2 |
| REQ-PI-08 | §4.3 | REQ-PI-43 | §12.3, §12.4 |
| REQ-PI-09 | §4.4 | REQ-PI-44 | §12.1 |
| REQ-PI-10 | §5.1 | REQ-PI-45 | §12.4 |
| REQ-PI-11 | §5.2 | REQ-PI-46 | §12.5 |
| REQ-PI-12 | §5.3 | REQ-PI-47 | §12.6 |
| REQ-PI-13 | §5.4 | REQ-PI-48 | §13.1 |
| REQ-PI-14 | §1.1 | REQ-PI-49 | §13.2 |
| REQ-PI-15 | §6 | REQ-PI-50 | §13.3 |
| REQ-PI-16 | §7.2 | REQ-PI-51 | §13.4 |
| REQ-PI-17 | §7.1, §7.5 | REQ-PI-52 | §13.5 |
| REQ-PI-18 | §7.3 | REQ-PI-53 | §14.2, §14.3 |
| REQ-PI-19 | §7.4 | REQ-PI-54 | §15.1 |
| REQ-PI-20 | §7.5 | REQ-PI-55 | §15.2 |
| REQ-PI-21 | §7.6, §11 | REQ-PI-56 | §15.3, §15.5, §15.6 |
| REQ-PI-21a | §11 (REQ-PI-21a), §16.2 | REQ-PI-57 | §15.4, §15.5 |
| REQ-PI-22 | §8.2 | REQ-PI-58 | §15.3 |
| REQ-PI-23 | §4.5, §8.1 | REQ-PI-59 | §2, §14.1 |
| REQ-PI-24 | §8.2 | REQ-PI-60 | §14.1 |
| REQ-PI-25 | §4.4 | REQ-PI-61 | §16.2 |
| REQ-PI-26 | §8.1, §8.3 | REQ-PI-62 | §16.1 |
| REQ-PI-27 | §8.3 | REQ-PI-63 | §11, §16.2 |
| REQ-PI-28 | §8.4 | REQ-PI-64 | §16.2, §16.3 |
| REQ-PI-29 | §9.1 | REQ-PI-65 | §5.3, §16.4 |
| REQ-PI-30 | §9.1 | REQ-PI-66 | §2, §7.6, §9.2, §10.6, §16.2 |
| REQ-PI-31 | §9.1 | REQ-PI-67 | §16.5 |
| REQ-PI-32 | §9.1 | REQ-PI-68 | §12, §16.2 |
| REQ-PI-33 | §9.2 | REQ-PI-69 | §15.6, §16.2 |
| REQ-PI-34 | §10.5 | REQ-PI-70 | §15.3, §16.2 |
| REQ-PI-35 | §10.1 | | |

---

## 18 — Design notes

Clarifications made while writing the design; none changes a requirement except where stated.

- **DN-1 (currency).** Duplicate pairs also require equal `currency`, applying REQ-PI-05 to the
  duplicate detector (stated in REQ-PI-18).
- **DN-2 (alphanumeric).** `N1`, `N2`, `tax_key` and `name_key` keep ASCII `A–Z`/`0–9` after
  upper-casing (`name_key` first drops combining marks); other letters and digits are removed.
- **DN-3 (equal N1).** Equal `N1` does not imply equal `N2`; rule A is evaluated first and is the
  only rule for equal `N1` (§7.3). REQ-PI-18 was corrected to say so.
- **DN-4 (constant placement).** The IBAN constants and `iban_problem` live in `utils.py`
  (section 12 of the requirements lists `is_valid_iban` there) and the reconciliation constants live
  next to `reconcile`; the detector modules re-export them.
- **DN-5 (total order).** `load_rows` breaks ties by the string form of the record, so even two
  rows with the same `source_ref` and date but different content give a shuffle-invariant result;
  `finish` adds `Alert.id` as a last key.
- **DN-6 (`payment_supplier`).** `Reconciliation` carries a fourth field (REQ-PI-38 was extended)
  so alert building never repeats the attribution.
- **DN-7 (display fallbacks).** A missing `supplier_name`, `invoice_number` or `counterparty` is
  shown as the tax id as written or the row's own `source_ref`, never as an invented value.
- **DN-8 (badge).** With an API key present and a fallback caused by an error, the 📋 badge reads
  "Template (LLM unavailable)" instead of claiming there is no key.
- **DN-9 (`fill_fallback`).** An app must not import a private function. ledger-core's fallback
  filler is the public `ledger_kit.explainer.fill_fallback`; App 2 calls it directly (no wrapper)
  and `test_pi_scaffold.py` scans the package for imports of underscore-prefixed names from
  `ledger_kit`.
- **DN-10 (line endings).** `.gitattributes` marks the demo CSVs `-text`, otherwise `core.autocrlf`
  on Windows would break the byte-equality test.
- **DN-11 (`as_of` widget).** `UI_DEFAULT_AS_OF` only seeds the date widget; it reaches no detector
  unless the user ticks the checkbox.
- **DN-12 (master rows).** A master row with an empty `tax_key` is not a supplier: it is not
  indexed, not attributed to payments and not checked for IBAN validity.
- **DN-13 (open decisions).** All OD-PI items are resolved; OD-PI-07 and OD-PI-14 were changed by
  review and are reflected in §2, §7 and §1 (the `structure.md` update is a task in `tasks.md`).
