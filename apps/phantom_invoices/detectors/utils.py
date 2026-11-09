"""Shared helpers of the phantom-invoices detectors: typed readers, keys, IBAN check, ordering.

Every helper is pure and never raises on any input value (REQ-PI-06). Nothing here reads the
system clock and nothing performs monetary arithmetic (REQ-MON-03).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd

from ledger_kit.models import Alert

ZERO: Decimal = Decimal("0")
# Hyphen, en dash, em dash: a text cell made only of these characters counts as missing.
DASH_CHARS: str = "-\u2013\u2014"

# --- Missing values and typed readers (REQ-PI-06) ---


def is_missing(value: Any) -> bool:
    """True for None, NaN, pd.NA, NaT, NaN Decimal, blank text and text made only of dashes."""
    if value is None or value is pd.NA or value is pd.NaT:
        return True
    if isinstance(value, (float, np.floating)):
        return bool(value != value)  # NaN
    if isinstance(value, Decimal):
        return value.is_nan()
    if isinstance(value, str):
        text = value.strip()  # str.strip() also strips \u00a0
        return text == "" or all(ch in DASH_CHARS for ch in text)
    return False


def as_text(value: Any) -> str | None:
    """Return the cell as written (unstripped) when it is a non-missing str, else None."""
    if isinstance(value, str) and not is_missing(value):
        return value
    return None


def as_decimal(value: Any) -> Decimal | None:
    """Return the cell when it is a finite Decimal, else None (float, int and str are wrong)."""
    if isinstance(value, Decimal) and not is_missing(value) and value.is_finite():
        return value
    return None


def as_date(value: Any) -> date | None:
    """Return a datetime.date, or the date part of a datetime/pd.Timestamp; None otherwise."""
    if is_missing(value):
        return None
    if isinstance(value, datetime):  # pd.Timestamp is a datetime subclass
        return value.date()
    if isinstance(value, date):
        return value
    return None


def as_bool(value: Any) -> bool:
    """Return True only for the bool True / numpy True; every other cell is False."""
    return bool(value) if isinstance(value, (bool, np.bool_)) else False


# --- Invoice-number keys N1 and N2 (REQ-PI-07) ---

_NON_ALNUM = re.compile(r"[^A-Z0-9]")
_DIGIT_RUN = re.compile(r"[0-9]+")


def n1_key(number: str) -> str:
    """Upper-case and drop every non-alphanumeric character: 'F-2026-0042' -> 'F20260042'."""
    return _NON_ALNUM.sub("", number.upper())


def n2_key(number: str) -> str:
    """Like N1, but every maximal digit run of the ORIGINAL text loses its leading zeros first."""
    stripped = _DIGIT_RUN.sub(lambda m: m.group().lstrip("0") or "0", number.upper())
    return _NON_ALNUM.sub("", stripped)


# --- Identifier keys (REQ-PI-08) ---


def tax_key(value: str) -> str:
    """Upper-case and drop every non-alphanumeric character: 'b-00000001' -> 'B00000001'."""
    return _NON_ALNUM.sub("", value.upper())


def name_key(value: str) -> str:
    """Return the accent-free alphanumeric upper-case key: 'García, S.L.' -> 'GARCIASL'."""
    decomposed = unicodedata.normalize("NFKD", value)
    bare = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _NON_ALNUM.sub("", bare.upper())


def iban_key(value: str) -> str:
    """Remove ALL whitespace (including \\u00a0) and upper-case; hyphens are kept."""
    return re.sub(r"\s", "", value).upper()


# --- IBAN validity (REQ-PI-23) ---

# Structural shape of an IBAN after iban_key().
IBAN_FORMAT_RE: re.Pattern[str] = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}$")
# ISO 13616 checksum: the rearranged IBAN, read as an integer, leaves this remainder modulo 97.
IBAN_MOD97_MODULUS: int = 97
IBAN_MOD97_REMAINDER: int = 1


def iban_problem(key: str) -> str | None:
    """Return None for a valid IBAN, 'format' for a malformed one, 'checksum' for mod-97 failure.

    `key` is an iban_key() result. Never raises.
    """
    if not IBAN_FORMAT_RE.fullmatch(key):
        return "format"
    rearranged = key[4:] + key[:4]
    digits = "".join(str(int(ch, 36)) for ch in rearranged)  # A=10 ... Z=35, digits unchanged
    if int(digits) % IBAN_MOD97_MODULUS != IBAN_MOD97_REMAINDER:
        return "checksum"
    return None


def is_valid_iban(key: str) -> bool:
    """Return True when iban_problem(key) is None."""
    return iban_problem(key) is None


# --- Deterministic order, rows, as_of and alert hygiene (REQ-PI-10 to REQ-PI-13) ---

_SOURCE_REF_ROW = re.compile(r"[0-9]+")


def source_ref_key(ref: str) -> tuple[str, int]:
    """Return the natural order key of a source_ref: 'f.csv:9' sorts before 'f.csv:10'."""
    file, sep, row = ref.rpartition(":")
    if sep and _SOURCE_REF_ROW.fullmatch(row):
        try:
            return (file, int(row))
        except ValueError:  # a digit run longer than Python's int-conversion limit
            pass
    return (ref, -1)


def sort_refs(refs: list[str]) -> list[str]:
    """Return the distinct refs in natural order (ties on the key are broken by the text)."""
    return sorted(set(refs), key=lambda ref: (source_ref_key(ref), ref))


def _tiebreak(record: Mapping[str, Any]) -> str:
    """Return a string form of a record that makes the order total for conflicting duplicates.

    The type name of every cell is part of the key, so `1` and `"1"` never tie (DN-5).
    """
    return repr(sorted((str(k), type(v).__name__, str(v)) for k, v in record.items()))


def load_rows(frame: Any, date_col: str | None) -> list[dict]:
    """Return the records of `frame` in deterministic order, one per source_ref (REQ-PI-10/11).

    Sorted by (date, source_ref natural order, tiebreak); a missing date sorts last. A frame that
    is not a DataFrame, is empty, or has no source_ref column yields []. A row without a
    source_ref cannot be cited and is dropped. For duplicate source_refs the first in sort order
    is kept.
    """
    if not isinstance(frame, pd.DataFrame) or frame.empty or "source_ref" not in frame.columns:
        return []

    def key(record: dict) -> tuple[date, tuple[str, int], str]:
        """Sort key of one record."""
        day = as_date(record.get(date_col)) if date_col else None
        return (
            day or date.max,
            source_ref_key(as_text(record.get("source_ref")) or ""),
            _tiebreak(record),
        )

    rows: list[dict] = []
    seen: set[str] = set()
    for record in sorted(frame.to_dict("records"), key=key):
        ref = as_text(record.get("source_ref"))
        if ref is None or ref in seen:
            continue
        seen.add(ref)
        rows.append(record)
    return rows


def _column(frame: Any, name: str) -> list[Any]:
    """Return the cells of a column, or [] when `frame` is not a DataFrame or lacks the column."""
    if isinstance(frame, pd.DataFrame) and name in frame.columns:
        return list(frame[name])
    return []


def resolve_as_of(ledger: Any, context: Mapping[str, Any]) -> date | None:
    """Return the context `as_of` when it is a date, else the latest date in the loaded data.

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


def text_or_ref(value: Any, ref: str) -> str:
    """Return the cell text, or the row's own source_ref when the cell is missing."""
    return as_text(value) or ref


def supplier_label(row: Mapping[str, Any], ref: str) -> str:
    """Return supplier_name, else the tax id as written, else the source_ref."""
    return as_text(row.get("supplier_name")) or as_text(row.get("supplier_tax_id")) or ref


def finish(alerts: list[Alert]) -> list[Alert]:
    """Return alerts ordered by (first source_ref natural order, variant, id): a total order."""
    return sorted(
        alerts,
        key=lambda a: (source_ref_key(a.source_refs[0]), str(a.data.get("variant", "")), a.id),
    )
