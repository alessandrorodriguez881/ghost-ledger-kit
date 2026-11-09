"""Shared helpers of the phantom-invoices detectors: typed readers, keys, IBAN check, ordering.

Every helper is pure and never raises on any input value (REQ-PI-06). Nothing here reads the
system clock and nothing performs monetary arithmetic (REQ-MON-03).
"""

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


# --- Supplier master and payment attribution (REQ-PI-09, REQ-PI-25) ---


@dataclass(frozen=True)
class Master:
    """The supplier master, one row per tax_key (the first in source_ref order)."""

    by_tax: Mapping[str, dict]  # tax_key -> master row (insertion order = source_ref order)
    by_name: Mapping[str, tuple[dict, ...]]  # name_key -> master rows (distinct suppliers)
    by_iban: Mapping[str, tuple[dict, ...]]  # iban_key of the master IBAN -> master rows


def build_master(suppliers: Any) -> Master:
    """Index the supplier master; rows with an empty tax_key are not suppliers (DN-12).

    For a repeated tax_key the first row in source_ref order wins and later ones are ignored.
    A frame that is not a DataFrame, is empty or lacks source_ref gives an empty master.
    """
    by_tax: dict[str, dict] = {}
    for row in load_rows(suppliers, None):
        tax = tax_key(as_text(row.get("tax_id")) or "")
        if tax and tax not in by_tax:
            by_tax[tax] = row
    names: dict[str, list[dict]] = {}
    ibans: dict[str, list[dict]] = {}
    for row in by_tax.values():
        name = name_key(as_text(row.get("supplier_name")) or "")
        if name:
            names.setdefault(name, []).append(row)
        iban = as_text(row.get("iban"))
        if iban is not None:
            ibans.setdefault(iban_key(iban), []).append(row)
    return Master(
        by_tax,
        {key: tuple(rows) for key, rows in names.items()},
        {key: tuple(rows) for key, rows in ibans.items()},
    )


def attribute_payment(payment: Mapping[str, Any], master: Master) -> dict | None:
    """Return the master row of the supplier a payment belongs to, or None (REQ-PI-25).

    Name first (exactly one master supplier with the same name_key), then IBAN (exactly one
    supplier whose master IBAN has the same iban_key). Zero or several hits fall through; no hit
    at all means the payment is not a supplier payment. Name goes first so that a payment
    addressed to a known supplier but sent to another account is still attributed (OD-PI-09).
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


# --- Reconciliation of invoices and payments (REQ-PI-34 to REQ-PI-40) ---

# A payment may be dated up to this many days after the due date and still match the invoice.
PAYMENT_MATCH_WINDOW_DAYS: int = 60
# Days after the due date before an unmatched invoice counts as overdue.
UNPAID_GRACE_DAYS: int = 15
# Largest accepted difference between a payment amount and an invoice total.
MATCH_AMOUNT_TOLERANCE: Decimal = Decimal("0.01")


@dataclass(frozen=True)
class InvoiceView:
    """The fields of one usable invoice that the reconciliation reads."""

    ref: str
    tax: str
    issue: date
    due: date
    total: Decimal
    currency: str


@dataclass(frozen=True)
class PaymentView:
    """The fields of one usable bank debit that the reconciliation reads."""

    ref: str
    day: date
    amount: Decimal
    currency: str


def invoice_view(row: Mapping[str, Any]) -> InvoiceView | None:
    """Return the usable invoice (issue, due, total, currency, supplier tax_key), else None."""
    ref = as_text(row.get("source_ref"))
    tax = tax_key(as_text(row.get("supplier_tax_id")) or "")
    issue, due = as_date(row.get("issue_date")), as_date(row.get("due_date"))
    total, currency = as_decimal(row.get("total")), as_text(row.get("currency"))
    if ref is None or not tax or issue is None or due is None or total is None or currency is None:
        return None
    return InvoiceView(ref, tax, issue, due, total, currency)


def payment_view(row: Mapping[str, Any]) -> PaymentView | None:
    """Return the usable payment (a debit with date, amount and currency present), else None."""
    ref = as_text(row.get("source_ref"))
    day, amount = as_date(row.get("date")), as_decimal(row.get("amount"))
    currency = as_text(row.get("currency"))
    if (
        ref is None
        or as_text(row.get("flow")) != "debit"
        or day is None
        or amount is None
        or currency is None
    ):
        return None
    return PaymentView(ref, day, amount, currency)


@dataclass(frozen=True)
class Reconciliation:
    """Result of matching invoices to supplier payments."""

    invoice_buckets: dict[str, str]  # source_ref -> "matched" | "open_not_due" | "overdue"
    payment_buckets: dict[str, str]  # source_ref -> "matched" | "unmatched"
    matches: list[tuple[str, str]]  # (invoice ref, payment ref), in matching order
    payment_supplier: dict[str, str]  # payment ref -> tax_key of the attributed supplier


def _plus_days(day: date, days: int) -> date:
    """Return `day` plus `days`, saturating at date.max instead of overflowing."""
    try:
        return day + timedelta(days=days)
    except OverflowError:
        return date.max


def reconcile(invoices: Any, suppliers: Any, payments: Any, as_of: date | None) -> Reconciliation:
    """Match invoices to supplier payments one-to-one and bucket everything. Pure; never raises.

    Invoices are visited in (issue_date, source_ref) order and each takes the earliest free
    payment, by (date, source_ref), of the same supplier and currency whose amount is within
    MATCH_AMOUNT_TOLERANCE of the total and whose date lies between the issue date and the due
    date plus PAYMENT_MATCH_WINDOW_DAYS, both ends inclusive. An invoice of a supplier that is
    not in the master is never matched (OD-PI-11).
    """
    master = build_master(suppliers)

    # already in (issue_date, source_ref) order
    invoice_views = [
        v for v in (invoice_view(r) for r in load_rows(invoices, "issue_date")) if v is not None
    ]

    supplier_payments: list[PaymentView] = []
    payment_supplier: dict[str, str] = {}
    for row in load_rows(payments, "date"):
        view = payment_view(row)
        if view is None:
            continue
        sup = attribute_payment(row, master)
        if sup is None:
            continue  # not a supplier payment
        supplier_payments.append(view)
        payment_supplier[view.ref] = tax_key(as_text(sup.get("tax_id")) or "")
    free = sorted(supplier_payments, key=lambda p: (p.day, source_ref_key(p.ref)))

    matched_payments: set[str] = set()
    matches: list[tuple[str, str]] = []
    for inv in invoice_views:
        if inv.tax not in master.by_tax:
            continue  # unknown supplier: never matched (OD-PI-11)
        last_day = _plus_days(inv.due, PAYMENT_MATCH_WINDOW_DAYS)
        for pay in free:  # (date, ref) order: the first fit is the smallest
            if (
                pay.ref in matched_payments
                or payment_supplier[pay.ref] != inv.tax
                or pay.currency != inv.currency
                or not within_tolerance(pay.amount, inv.total, MATCH_AMOUNT_TOLERANCE)
                or not (inv.issue <= pay.day <= last_day)
            ):
                continue
            matched_payments.add(pay.ref)
            matches.append((inv.ref, pay.ref))
            break

    paid_invoices = {inv_ref for inv_ref, _ in matches}
    invoice_buckets: dict[str, str] = {}
    for inv in invoice_views:
        if inv.ref in paid_invoices:
            invoice_buckets[inv.ref] = "matched"
        elif as_of is not None and as_of > _plus_days(inv.due, UNPAID_GRACE_DAYS):
            invoice_buckets[inv.ref] = "overdue"  # strictly later: due + 15 is still open
        else:
            invoice_buckets[inv.ref] = "open_not_due"
    payment_buckets = {
        p.ref: ("matched" if p.ref in matched_payments else "unmatched") for p in supplier_payments
    }
    return Reconciliation(invoice_buckets, payment_buckets, matches, payment_supplier)
