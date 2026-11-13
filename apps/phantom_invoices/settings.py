"""Load config.toml, read the demo inputs and run the whole pipeline (design sections 3 and 14).

Everything here works without Streamlit so it can be tested directly. No money is computed in
this module and nothing reads the system clock.
"""

from __future__ import annotations

import hashlib
import io
import tomllib
from collections.abc import Iterable, MutableMapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from apps.phantom_invoices.detectors.utils import (
    Reconciliation,
    as_bool,
    as_date,
    as_decimal,
    as_text,
    reconcile,
    resolve_as_of,
)
from apps.phantom_invoices.prepare import quarantine_multi_rate
from ledger_kit.detectors import DetectorResult, run_all
from ledger_kit.ingestion.normaliser import normalise
from ledger_kit.ingestion.sniffer import (
    format_label,
    read_bank_statement,
    read_invoices,
    sniff_format,
)
from ledger_kit.ingestion.supplier_reader import parse_suppliers
from ledger_kit.models import Alert
from ledger_kit.utils.anonymise import mask_iban
from ledger_kit.utils.money import format_amount

# Widget placeholder of the as-of date input. It reaches a detector only when the user ticks
# "use_as_of" (DN-11); otherwise the as_of passed to the pipeline is None.
UI_DEFAULT_AS_OF: date = date(2026, 1, 1)

# First option of the flashlight radio: nothing is lit and nothing is dimmed.
NO_FLASHLIGHT: str = "No flashlight (show every row)"

# Alert severities in display order (REQ-PI-49): critical first.
SEVERITY_ORDER: tuple[str, ...] = ("critical", "warning", "info")
SEVERITY_ICONS: dict[str, str] = {"critical": "🔴", "warning": "🟡", "info": "🔵"}

# Status column of the haunted ledger (REQ-PI-49); a row that is not usable has no status.
STATUS_ICONS: dict[str, str] = {"matched": "✅", "open_not_due": "🕯️", "overdue": "💀"}

# The two critical IBAN variants that carry the verify-by-phone message (REQ-PI-26).
VERIFICATION_VARIANTS: frozenset[str] = frozenset(
    {"invoice_iban_differs_from_master", "payment_to_non_master_iban"}
)
LAST4_CAPTION: str = "The last four characters match; the difference is elsewhere in the IBAN."
DEFAULT_DUE_DATE_CAPTION: str = "Due date assumed: issue date plus the default payment term."
DEFAULT_DUE_DATE_MARK: str = " (assumed)"

# Explained to the user next to the quarantine panel (OD-PI-08, DN-RF-08): the CSV reader splits a
# multi-rate invoice into rows and the Facturae reader quarantines the whole invoice.
MULTI_RATE_NOTE: str = (
    "Invoices that mix more than one VAT rate are out of scope (reason "
    "multi_rate_invoice_out_of_scope for CSV rows, multiple_vat_rates for a Facturae invoice): "
    "they are listed here and no check is run on them."
)

# Shown whenever a Facturae file was read (REQ-RF-19, REQ-RF-23, DN-RF-14).
SIGNATURE_NOTE: str = (
    "Facturae digital signatures (.xsig) are read but not verified: this app does not check "
    "who signed a file."
)
# Shown when the payments file is Norma 43 and none of its movements carries an IBAN record
# (REQ-RF-23, DN-RF-03): the standard has no counterparty IBAN field.
NO_PAYMENT_IBAN_NOTE: str = (
    "This Norma 43 file carries no IBAN for its payments, so the payment-side IBAN checks are "
    "skipped for this file."
)
# Quarantine reason of a second invoice file with a name that was already loaded (REQ-RF-21).
DUPLICATE_FILE_REASON: str = "duplicate_file_name"

# Demo format radio (REQ-RF-24): the option shown, and the `fmt` of `demo_inputs` it selects.
DemoFormat = Literal["csv", "real"]
DEMO_FORMATS: dict[str, DemoFormat] = {"CSV": "csv", "Real formats": "real"}

# Kinds each box reads; the format of a file of another kind is not named (it is quarantined).
INVOICE_KINDS: frozenset[str] = frozenset({"csv", "json", "facturae"})
PAYMENT_KINDS: frozenset[str] = frozenset({"csv", "norma43"})

# Columns of the haunted ledger, in order. No tax-id column (REQ-PI-49).
LEDGER_COLUMNS: tuple[str, ...] = (
    "source_ref",
    "status",
    "invoice_number",
    "supplier_name",
    "issue_date",
    "due_date",
    "base_amount",
    "vat_rate",
    "vat_amount",
    "surcharge_amount",
    "withholding_amount",
    "total",
    "iban",
)
_AMOUNT_COLUMNS: tuple[str, ...] = (
    "base_amount",
    "vat_amount",
    "surcharge_amount",
    "withholding_amount",
    "total",
)
MASTER_COLUMNS: tuple[str, ...] = ("source_ref", "supplier_name", "iban")
PAYMENT_COLUMNS: tuple[str, ...] = (
    "source_ref",
    "date",
    "flow",
    "amount",
    "counterparty",
    "iban",
)


@dataclass(frozen=True)
class Source:
    """One input file: `name` becomes source_file (and so the source_ref prefix)."""

    name: str
    data: bytes


@dataclass(frozen=True)
class DemoInputs:
    """The demo files (one or more invoice files) and the optional demo `as_of` date."""

    invoices: tuple[Source, ...]
    suppliers: Source
    payments: Source
    as_of: date | None = None


@dataclass(frozen=True)
class Pipeline:
    """Everything the UI shows, computed once from the three inputs."""

    invoices: pd.DataFrame  # clean (multi-rate rows removed)
    suppliers: pd.DataFrame
    payments: pd.DataFrame
    quarantine: list[dict]  # ingestion quarantine + multi-rate records, each with "file_kind"
    as_of_used: date | None
    results: list[DetectorResult]
    reconciliation: Reconciliation
    notes: tuple[str, ...] = ()  # detected formats, signature note, no-payment-IBAN note


def load_config(path: Path) -> dict[str, Any]:
    """Read a TOML configuration file into a dict."""
    with Path(path).open("rb") as handle:
        return tomllib.load(handle)


def to_date(value: str | date) -> date:
    """Convert a TOML date string or a TOML date value to a datetime.date."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def _read_source(root: Path, relative: str) -> Source:
    """Read one demo file (path relative to `root`) as bytes."""
    path = Path(root) / relative
    return Source(name=path.name, data=path.read_bytes())


def demo_inputs(config: dict[str, Any], root: Path, fmt: DemoFormat = "csv") -> DemoInputs:
    """Read the demo files named by [demo] (relative to `root`) and the optional as_of.

    `csv`: invoices.csv and payments.csv. `real`: every `*.xml` of `facturae_dir` (in file-name
    order) and the Norma 43 payments file. The supplier master is the same for both.
    """
    demo = config["demo"]
    as_of = demo.get("as_of")
    if fmt == "csv":
        invoices = (_read_source(root, demo["invoices_path"]),)
        payments = _read_source(root, demo["payments_path"])
    elif fmt == "real":
        folder = Path(root) / demo["facturae_dir"]
        invoices = tuple(
            Source(path.name, path.read_bytes())
            for path in sorted(folder.glob("*.xml"), key=lambda path: path.name)
        )
        payments = _read_source(root, demo["payments_n43_path"])
    else:
        raise ValueError(f"unknown demo format {fmt!r}")
    return DemoInputs(
        invoices=invoices,
        suppliers=_read_source(root, demo["suppliers_path"]),
        payments=payments,
        as_of=None if as_of is None else to_date(as_of),
    )


def _tag(kind: str, records: list[dict]) -> list[dict]:
    """Return copies of the quarantine records with `file_kind` added; other keys unchanged."""
    return [{**record, "file_kind": kind} for record in records]


InvoiceInput = Source | Sequence[Source] | None


def invoice_files(invoices: InvoiceInput) -> tuple[Source, ...]:
    """Return the invoice files in file-name order (DN-RF-18); one Source or None is accepted.

    The sort is stable, so of two files with one name the one given first stays first.
    """
    if invoices is None:
        return ()
    files = (invoices,) if isinstance(invoices, Source) else tuple(invoices)
    return tuple(sorted(files, key=lambda source: source.name))


def _read_invoice_files(
    files: tuple[Source, ...],
) -> tuple[list[list], list[dict], list[tuple[str, str]]]:
    """Read each invoice file once; return the model lists, the quarantine and (name, kind) read.

    A second file with a name already read is not read: it gives one `duplicate_file_name`
    record (REQ-RF-21).
    """
    lists: list[list] = []
    quarantine: list[dict] = []
    read: list[tuple[str, str]] = []
    seen: set[str] = set()
    for source in files:
        if source.name in seen:
            quarantine.append(
                {
                    "source_file": source.name,
                    "source_row": None,
                    "reason": DUPLICATE_FILE_REASON,
                    "raw": f"{source.name}: a file with this name was already loaded; not read.",
                }
            )
            continue
        seen.add(source.name)
        invoices, rejected = read_invoices(io.BytesIO(source.data), source_file=source.name)
        lists.append(invoices)
        quarantine.extend(rejected)
        read.append((source.name, sniff_format(source.data)))
    return lists, quarantine, read


def _format_notes(
    read: Sequence[tuple[str, str]], payments: Source | None, payments_kind: str
) -> list[str]:
    """Name the detected format of the invoice files and of the payments file (REQ-RF-23)."""
    notes: list[str] = []
    accepted = [(name, kind) for name, kind in read if kind in INVOICE_KINDS]
    for kind in dict.fromkeys(kind for _, kind in accepted):
        names = [name for name, other in accepted if other == kind]
        label = format_label(kind)
        notes.append(f"{names[0]}: {label}" if len(names) == 1 else f"{len(names)} files: {label}")
    if payments is not None and payments_kind in PAYMENT_KINDS:
        notes.append(f"{payments.name}: {format_label(payments_kind)}")
    return notes


def run_pipeline(
    invoices: InvoiceInput,
    suppliers: Source | None,
    payments: Source | None,
    as_of: date | None,
) -> Pipeline:
    """Parse, normalise, quarantine multi-rate invoices, run pi.* detectors and reconcile.

    `invoices` is one Source, a sequence of them (read in file-name order) or None. The format
    of every file is found from its content, never from its extension (REQ-RF-20).
    """
    files = invoice_files(invoices)
    inv_lists, inv_q, inv_read = _read_invoice_files(files)
    sup_list, sup_q = (
        ([], [])
        if suppliers is None
        else parse_suppliers(io.BytesIO(suppliers.data), source_file=suppliers.name)
    )
    pay_list, pay_q = (
        ([], [])
        if payments is None
        else read_bank_statement(io.BytesIO(payments.data), source_file=payments.name)
    )
    payments_kind = "empty" if payments is None else sniff_format(payments.data)
    invoices_df, inv_n = normalise(*inv_lists, kind="invoice")
    suppliers_df, sup_n = normalise(sup_list, kind="supplier")
    payments_df, pay_n = normalise(pay_list, kind="transaction")
    clean, multi_rate = quarantine_multi_rate(invoices_df)

    context = {"suppliers": suppliers_df, "payments": payments_df, "as_of": as_of}
    as_of_used = resolve_as_of(clean, context)
    results = run_all(clean, namespace="pi", context=context)
    rec = reconcile(clean, suppliers_df, payments_df, as_of_used)
    quarantine = (
        _tag("invoices", inv_q + inv_n + multi_rate)
        + _tag("suppliers", sup_q + sup_n)
        + _tag("payments", pay_q + pay_n)
    )
    notes = _format_notes(inv_read, payments, payments_kind)
    if any(kind == "facturae" for _, kind in inv_read):
        notes.append(SIGNATURE_NOTE)
    if payments_kind == "norma43" and _carries_no_iban(payments_df):
        notes.append(NO_PAYMENT_IBAN_NOTE)
    return Pipeline(
        clean, suppliers_df, payments_df, quarantine, as_of_used, results, rec, tuple(notes)
    )


def _carries_no_iban(payments: pd.DataFrame) -> bool:
    """True when the frame has movements and none of them carries an IBAN."""
    return not payments.empty and all(as_text(value) is None for value in payments["iban"])


# --- View-model helpers for app.py (no Streamlit, no clock) ---------------------------------


def apply_demo(state: MutableMapping[str, Any], demo: DemoInputs) -> None:
    """Pre-fill the widget keys and the sources for the Load demo data button (REQ-PI-52).

    Must run inside an `on_click` callback: assigning a widget key after its widget exists in
    the same script run raises StreamlitWidgetAlreadyInstantiatedError.
    """
    state["sources"] = {
        "invoices": tuple(demo.invoices),
        "suppliers": demo.suppliers,
        "payments": demo.payments,
    }
    state["use_as_of"] = demo.as_of is not None
    if demo.as_of is not None:
        state["as_of_date"] = demo.as_of
    state["pi_hallucinate"] = False
    state["selected_alert"] = NO_FLASHLIGHT


def _hash_source(digest: Any, source: Source) -> None:
    """Add a file's name and content hash to a running digest."""
    digest.update(source.name.encode("utf-8") + b"\x00")
    digest.update(hashlib.sha256(source.data).hexdigest().encode("ascii") + b"\x01")


def pipeline_key(
    invoices: InvoiceInput,
    suppliers: Source | None,
    payments: Source | None,
    as_of: date | None,
) -> str:
    """Return the cache key of a pipeline run (REQ-RF-21).

    SHA-256 of the number of invoice files, then each invoice file's name and content hash in
    file-name order, then the supplier and payments files and the as_of value. The selection
    order of the invoice files does not change the key.
    """
    digest = hashlib.sha256()
    files = invoice_files(invoices)
    digest.update(f"{len(files)}\x02".encode("ascii"))
    for source in files:
        _hash_source(digest, source)
    for source in (suppliers, payments):
        if source is None:
            digest.update(b"-\x01")
        else:
            _hash_source(digest, source)
    digest.update(b"none" if as_of is None else as_of.isoformat().encode("ascii"))
    return digest.hexdigest()


def input_notice(has_suppliers: bool, has_payments: bool) -> str:
    """Say which check needs which file, and which inputs are missing now (REQ-PI-04)."""
    text = (
        "Which file feeds which check. Invoices: duplicate-invoice and VAT checks. "
        "Supplier master: the Poltergeist IBAN check; without it only malformed IBANs are "
        "reported. Bank payments: reconciliation; without them no invoice can be matched and "
        "every invoice counts as unpaid so far."
    )
    missing = [
        label
        for label, present in (("supplier master", has_suppliers), ("bank payments", has_payments))
        if not present
    ]
    if missing:
        text += " Not loaded: " + " and ".join(missing) + "."
    return text


def as_of_note(as_of_used: date | None, fixed_by_user: bool) -> str:
    """Return the line that states the as-of date in use (REQ-PI-49 part 4)."""
    if as_of_used is None:
        return "No as-of date: the data holds no usable date, so no invoice can be overdue."
    if fixed_by_user:
        return f"As-of date in use: {as_of_used.isoformat()} (fixed in the sidebar)."
    return (
        f"As-of date in use: {as_of_used.isoformat()}. It defaults to the latest date in the data."
    )


def severity_counts(alerts: Iterable[Alert]) -> dict[str, int]:
    """Count alerts per severity; every severity is present, even with a zero count."""
    counts = {severity: 0 for severity in SEVERITY_ORDER}
    for alert in alerts:
        counts[alert.severity] += 1
    return counts


def group_alerts(alerts: Iterable[Alert]) -> dict[str, list[Alert]]:
    """Group alerts critical, warning, info; every severity is present, input order kept."""
    groups: dict[str, list[Alert]] = {severity: [] for severity in SEVERITY_ORDER}
    for alert in alerts:
        groups[alert.severity].append(alert)
    return groups


def ordered_alerts(alerts: Iterable[Alert]) -> list[Alert]:
    """Return the alerts critical first, then warning, then info (stable within a severity)."""
    return [alert for group in group_alerts(alerts).values() for alert in group]


def alert_option_label(alert: Alert) -> str:
    """Return the radio label of an alert: its severity icon and title."""
    return f"{SEVERITY_ICONS[alert.severity]} {alert.title}"


def flashlight_options(alerts: Iterable[Alert]) -> list[str]:
    """Return the radio options: NO_FLASHLIGHT, then every distinct alert id in order."""
    return [NO_FLASHLIGHT, *dict.fromkeys(alert.id for alert in alerts)]


def reset_selected(selected: Any, options: Sequence[str]) -> str:
    """Return `selected` when it is one of the options, else NO_FLASHLIGHT (design 13.3)."""
    return selected if isinstance(selected, str) and selected in options else NO_FLASHLIGHT


def lit_refs_for(selected: str, alerts: Iterable[Alert]) -> tuple[str, ...]:
    """Return the source_refs the flashlight lights for the selected option (none by default)."""
    for alert in alerts:
        if alert.id == selected:
            return tuple(alert.source_refs)
    return ()


def alert_captions(alert: Alert) -> list[str]:
    """Return the captions of REQ-PI-49 that apply to this alert."""
    captions: list[str] = []
    if alert.data.get("last4_identical") is True:
        captions.append(LAST4_CAPTION)
    if alert.data.get("due_date_is_default") is True:
        captions.append(DEFAULT_DUE_DATE_CAPTION)
    return captions


def verification_message(alert: Alert) -> str | None:
    """Return the verify-by-phone message verbatim for the two critical IBAN variants."""
    if alert.data.get("variant") not in VERIFICATION_VARIANTS:
        return None
    message = alert.data.get("verification_message")
    return message if isinstance(message, str) else None


def status_icon(bucket: str | None) -> str:
    """Return the status icon of an invoice bucket; blank when the row is not usable."""
    return STATUS_ICONS.get(bucket or "", "")


def _plain(value: Any) -> str:
    """Return a text cell on one line (blank runs collapsed), safe inside a markdown block."""
    text = as_text(value)
    return "" if text is None else " ".join(text.split())


def _day(value: Any) -> str:
    """Return an ISO date for a date cell, else an empty string."""
    day = as_date(value)
    return "" if day is None else day.isoformat()


def _money(value: Any, currency: str) -> str:
    """Return a Decimal cell as a European amount (Finance Rule 4); empty if it is no Decimal."""
    amount = as_decimal(value)
    if amount is None:
        return ""
    try:
        return format_amount(amount, currency).strip()
    except ArithmeticError:  # an amount too large to round to cents is shown as written
        return str(amount)


def _rate(value: Any) -> str:
    """Return a VAT rate cell such as '21 %'; empty when the cell is no Decimal."""
    rate: Decimal | None = as_decimal(value)
    return "" if rate is None else f"{rate.normalize():f} %"


def _masked(value: Any) -> str:
    """Return the masked IBAN of a cell (Finance Rule 5); empty when there is none."""
    text = as_text(value)
    return "" if text is None else mask_iban(text)


def ledger_view(invoices: pd.DataFrame, reconciliation: Reconciliation) -> pd.DataFrame:
    """Return the display strings of the haunted ledger: every invoice, one row each.

    Amounts use format_amount, the IBAN is masked, there is no tax-id column and the status
    comes from the reconciliation (blank when the row is not usable).
    """
    rows: list[dict[str, str]] = []
    for rec in invoices.to_dict("records"):
        ref = as_text(rec.get("source_ref")) or ""
        currency = as_text(rec.get("currency")) or ""
        due = _day(rec.get("due_date"))
        if due and as_bool(rec.get("due_date_is_default")):
            due += DEFAULT_DUE_DATE_MARK
        row = {
            "source_ref": ref,
            "status": status_icon(reconciliation.invoice_buckets.get(ref)),
            "invoice_number": _plain(rec.get("invoice_number")),
            "supplier_name": _plain(rec.get("supplier_name")),
            "issue_date": _day(rec.get("issue_date")),
            "due_date": due,
            "vat_rate": _rate(rec.get("vat_rate")),
            "iban": _masked(rec.get("iban")),
        }
        for column in _AMOUNT_COLUMNS:
            row[column] = _money(rec.get(column), currency)
        rows.append(row)
    return pd.DataFrame(rows, columns=list(LEDGER_COLUMNS))


def _cited(frame: Any, refs: Iterable[str]) -> list[dict]:
    """Return the records of `frame` whose source_ref is in `refs`, in frame order."""
    if not isinstance(frame, pd.DataFrame) or "source_ref" not in frame.columns:
        return []
    wanted = frozenset(refs)
    return [rec for rec in frame.to_dict("records") if rec.get("source_ref") in wanted]


def cited_master_view(suppliers: pd.DataFrame, refs: Iterable[str]) -> pd.DataFrame:
    """Return the cited supplier-master rows for display: name and masked IBAN, no tax id."""
    rows = [
        {
            "source_ref": as_text(rec.get("source_ref")) or "",
            "supplier_name": _plain(rec.get("supplier_name")),
            "iban": _masked(rec.get("iban")),
        }
        for rec in _cited(suppliers, refs)
    ]
    return pd.DataFrame(rows, columns=list(MASTER_COLUMNS))


def cited_payments_view(payments: pd.DataFrame, refs: Iterable[str]) -> pd.DataFrame:
    """Return the cited bank-payment rows for display: European amounts, masked IBAN."""
    rows = [
        {
            "source_ref": as_text(rec.get("source_ref")) or "",
            "date": _day(rec.get("date")),
            "flow": _plain(rec.get("flow")),
            "amount": _money(rec.get("amount"), as_text(rec.get("currency")) or ""),
            "counterparty": _plain(rec.get("counterparty")),
            "iban": _masked(rec.get("iban")),
        }
        for rec in _cited(payments, refs)
    ]
    return pd.DataFrame(rows, columns=list(PAYMENT_COLUMNS))


# Columns the lantern lights on an alert card, per detector (spec app-signatures, REQ-AS-11). They
# are the fields each detector module compares: duplicate_invoice groups by supplier and compares
# the invoice number, the issue date and the total; iban_change compares the IBAN of the invoice
# or the payment with the supplier master; vat_error checks the amounts of one invoice against its
# base; reconciliation matches an invoice total and due date with a payment amount and date of the
# same supplier. A detector that is not here lights the columns that differ between the rows.
LANTERN_COLUMNS: dict[str, tuple[str, ...]] = {
    "pi.duplicate_invoice": ("supplier_name", "invoice_number", "issue_date", "total"),
    "pi.iban_change": ("iban",),
    "pi.vat_error": (
        "base_amount",
        "vat_rate",
        "vat_amount",
        "surcharge_amount",
        "withholding_amount",
        "total",
    ),
    "pi.reconciliation": (
        "supplier_name",
        "due_date",
        "total",
        "date",
        "amount",
        "counterparty",
    ),
}
# Columns of the lantern, in order: the invoice fields, then the payment fields, then the IBAN.
LANTERN_ORDER: tuple[str, ...] = (
    "source_ref",
    "invoice_number",
    "supplier_name",
    "issue_date",
    "due_date",
    "date",
    "counterparty",
    "flow",
    "base_amount",
    "vat_rate",
    "vat_amount",
    "surcharge_amount",
    "withholding_amount",
    "total",
    "amount",
    "iban",
)


def lantern_lit_columns(alert: Alert) -> tuple[str, ...] | None:
    """Return the columns to light for the alert's detector; None when it is not in the mapping."""
    return LANTERN_COLUMNS.get(alert.detector)


def lantern_view(alert: Alert, pipeline: Pipeline) -> pd.DataFrame:
    """Return the cited rows of an alert as lantern display strings, in `source_refs` order.

    The values come from the views the page already uses for its cited rows (`ledger_view`,
    `cited_master_view`, `cited_payments_view`), so amounts are European, dates are ISO and an IBAN
    is masked. Only columns that hold a value in some row are kept. The IBAN column is kept only
    where the detector compares it (it is in the mapping) or, for an unmapped detector, where the
    IBANs differ; no other column ever shows an IBAN.
    """
    refs = list(alert.source_refs)
    invoices = pipeline.invoices
    if isinstance(invoices, pd.DataFrame) and "source_ref" in invoices.columns:
        cited_invoices = invoices[invoices["source_ref"].isin(refs)]
        invoice_rows = ledger_view(cited_invoices, pipeline.reconciliation)
    else:
        invoice_rows = pd.DataFrame(columns=list(LEDGER_COLUMNS))
    found: dict[str, dict[str, str]] = {}
    for frame in (
        invoice_rows,
        cited_master_view(pipeline.suppliers, refs),
        cited_payments_view(pipeline.payments, refs),
    ):
        for record in frame.to_dict("records"):
            found.setdefault(record["source_ref"], record)
    records = [found[ref] for ref in refs if ref in found]
    mapped = LANTERN_COLUMNS.get(alert.detector)
    kept: list[str] = []
    for column in LANTERN_ORDER:
        values = [record.get(column, "") for record in records]
        if not any(values):
            continue
        if column == "iban":
            shown = "iban" in mapped if mapped is not None else len(set(values)) > 1
            if not shown:
                continue
        kept.append(column)
    return pd.DataFrame([{c: record.get(c, "") for c in kept} for record in records], columns=kept)


def quarantine_view(records: Iterable[dict]) -> pd.DataFrame:
    """Flatten quarantine records into a table of file, row, reason and raw values."""
    rows = [
        {
            "file": str(rec.get("source_file", "")),
            "row": str(rec.get("source_row", "")),
            "reason": str(rec.get("reason", "")),
            "raw": str(rec.get("raw", "")),
        }
        for rec in records
    ]
    return pd.DataFrame(rows, columns=["file", "row", "reason", "raw"])


def markdown_safe(text: str) -> str:
    """Backslash-escape the markdown characters of `text` so it is shown literally."""
    return "".join(f"\\{char}" if char in "\\`*_~$<>[]" else char for char in text)
