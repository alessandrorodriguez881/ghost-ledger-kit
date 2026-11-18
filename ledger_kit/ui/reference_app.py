"""Streamlit reference page: upload bank CSVs, ingest, run detectors, show cited rows.

Run with: ``streamlit run ledger_kit/ui/reference_app.py`` (no configuration needed).

The template library registers no detectors of its own, so this page shows an empty alert
list until an app package is discovered. App pages (e.g. ``apps/phantom_invoices/app.py``)
call ``auto_discover("apps.<name>.detectors")`` before rendering; see ``DETECTOR_PACKAGES``.
Everything except ``main`` is plain Python so it can be tested without a Streamlit runtime.
"""

from __future__ import annotations

import hashlib
import io
import sys
from collections.abc import Iterable, MutableMapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

# `streamlit run ledger_kit/ui/reference_app.py` puts only this folder on sys.path, so make the
# repository root importable when the package is not installed (REQ-UI-08: no configuration).
_ROOT = str(Path(__file__).resolve().parents[2])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from ledger_kit.detectors import auto_discover, run_all  # noqa: E402
from ledger_kit.ingestion.csv_reader import ENCODINGS_TRIED, parse_csv  # noqa: E402
from ledger_kit.ingestion.normaliser import normalise  # noqa: E402
from ledger_kit.models import Alert, Transaction  # noqa: E402
from ledger_kit.ui.signatures import ref_with_line_markdown, source_lines_of  # noqa: E402
from ledger_kit.utils.anonymise import mask_iban  # noqa: E402
from ledger_kit.utils.money import format_amount  # noqa: E402

# Packages scanned for detectors before the run. Library level: none register anything.
DETECTOR_PACKAGES: tuple[str, ...] = ("ledger_kit.detectors",)

# Highlight colour of the rows cited by an alert (Bootstrap warning yellow).
HIGHLIGHT_STYLE: str = "background-color: #fff3cd"

SEVERITY_ORDER: tuple[str, ...] = ("critical", "warning", "info")
SEVERITY_BADGES: dict[str, str] = {"critical": "🔴", "warning": "🟡", "info": "🔵"}

# Ledger columns shown to the user, in order (never `id` or `tags`).
DISPLAY_COLUMNS: tuple[str, ...] = (
    "source_ref",
    "source_line",
    "date",
    "amount",
    "flow",
    "counterparty",
    "description",
    "iban",
)

_SESSION_PREFIX = "ledger_kit.ref"


@dataclass(frozen=True)
class FileSummary:
    """Per-file ingestion outcome shown above the results."""

    name: str
    rows_read: int
    rows_quarantined: int
    encoding: str | None


@dataclass(frozen=True)
class Analysis:
    """Everything the page renders for one set of uploaded files."""

    ledger: pd.DataFrame
    quarantine: list[dict]
    alerts: list[Alert]
    files: list[FileSummary]


def detect_encoding(data: bytes) -> str | None:
    """Return the first encoding of ENCODINGS_TRIED that decodes `data`, else None."""
    for encoding in ENCODINGS_TRIED:
        try:
            data.decode(encoding)
        except UnicodeDecodeError:
            continue
        return encoding
    return None


def _file_key(name: str, data: bytes) -> str:
    """Session-state key of one file: SHA-256 of its bytes plus its name (source_ref prefix)."""
    return f"{_SESSION_PREFIX}.file:{hashlib.sha256(data).hexdigest()}:{name}"


def _set_key(keys: Iterable[str]) -> str:
    """Session-state key of a whole upload set, derived from the per-file keys."""
    joined = "\n".join(keys)
    return f"{_SESSION_PREFIX}.set:{hashlib.sha256(joined.encode()).hexdigest()}"


def _ingest_file(
    name: str, data: bytes, cache: MutableMapping[str, Any]
) -> tuple[list[Transaction], list[dict], FileSummary]:
    """Parse one file (cached by content hash) and summarise the outcome."""
    key = _file_key(name, data)
    if key not in cache:
        transactions, quarantined = parse_csv(io.BytesIO(data), source_file=name)
        summary = FileSummary(
            name=name,
            rows_read=len(transactions),
            rows_quarantined=len(quarantined),
            encoding=detect_encoding(data),
        )
        cache[key] = (transactions, quarantined, summary)
    return cache[key]


def analyse(files: Sequence[tuple[str, bytes]], cache: MutableMapping[str, Any]) -> Analysis:
    """Ingest, normalise and run all registered detectors; cached per upload set."""
    keys = [_file_key(name, data) for name, data in files]
    set_key = _set_key(keys)
    if set_key in cache:
        return cache[set_key]

    all_transactions: list[Transaction] = []
    quarantine: list[dict] = []
    summaries: list[FileSummary] = []
    for name, data in files:
        transactions, quarantined, summary = _ingest_file(name, data, cache)
        all_transactions.extend(transactions)
        quarantine.extend(quarantined)
        summaries.append(summary)

    ledger, normalise_quarantine = normalise(all_transactions)
    quarantine.extend(normalise_quarantine)

    for package in DETECTOR_PACKAGES:
        auto_discover(package)
    results = run_all(ledger)
    alerts = [alert for result in results for alert in result.alerts]

    analysis = Analysis(ledger=ledger, quarantine=quarantine, alerts=alerts, files=summaries)
    cache[set_key] = analysis
    return analysis


def count_by_severity(alerts: Iterable[Alert]) -> dict[str, int]:
    """Count alerts per severity; every severity is present, even with a zero count."""
    counts = {severity: 0 for severity in SEVERITY_ORDER}
    for alert in alerts:
        counts[alert.severity] += 1
    return counts


def sort_alerts(alerts: Iterable[Alert]) -> list[Alert]:
    """Order alerts critical first, then warning, then info (stable within a severity)."""
    return sorted(alerts, key=lambda a: SEVERITY_ORDER.index(a.severity))


def rows_for_refs(ledger: pd.DataFrame, refs: Iterable[str]) -> tuple[pd.DataFrame, list[str]]:
    """Return the ledger rows cited by `refs` (ledger order) and the refs not found in it."""
    wanted = list(refs)
    if "source_ref" not in ledger.columns:
        return ledger.iloc[0:0], wanted
    present = set(ledger["source_ref"])
    cited = ledger[ledger["source_ref"].isin(wanted)]
    return cited, [ref for ref in wanted if ref not in present]


def format_for_display(rows: pd.DataFrame) -> pd.DataFrame:
    """Return display strings: European amounts (Finance Rule 4) and masked IBANs (Rule 5)."""
    shown = rows[[c for c in DISPLAY_COLUMNS if c in rows.columns]].copy()
    if "amount" in shown.columns:
        currencies = rows["currency"] if "currency" in rows.columns else ["EUR"] * len(rows)
        shown["amount"] = [
            format_amount(Decimal(str(amount)), str(currency))
            for amount, currency in zip(rows["amount"], currencies, strict=True)
        ]
    if "iban" in shown.columns:
        shown["iban"] = [mask_iban(v) if isinstance(v, str) and v else "" for v in shown["iban"]]
    if "date" in shown.columns:
        shown["date"] = [d.isoformat() for d in shown["date"]]
    if "source_line" in shown.columns:
        shown["source_line"] = [_line_text(v) for v in shown["source_line"]]
    return shown


def _line_text(value: Any) -> str:
    """Return a source_line cell as text; a record without a line is an empty cell."""
    if value is None or value is pd.NA or value is pd.NaT:
        return ""
    if isinstance(value, float) and value != value:
        return ""
    return str(int(value))


def highlight_rows(shown: pd.DataFrame) -> Any:
    """Return a pandas Styler painting every row with the highlight colour (REQ-UI-04)."""
    return shown.style.apply(lambda row: [HIGHLIGHT_STYLE] * len(row), axis=1)


def quarantine_table(quarantine: Sequence[dict]) -> pd.DataFrame:
    """Flatten quarantine records into a displayable table.

    `line` is the line of the file where the bad record starts (`source_line`); it is empty for
    a record about the whole file or an XML invoice.
    """
    return pd.DataFrame(
        [
            {
                "file": q.get("source_file"),
                "line": _line_text(q.get("source_line")),
                "reason": q.get("reason"),
                "raw": str(q.get("raw", "")),
            }
            for q in quarantine
        ],
        columns=["file", "line", "reason", "raw"],
    )


def _render_summary(alerts: Sequence[Alert]) -> None:
    """Severity counts row at the top of the results."""
    counts = count_by_severity(alerts)
    for column, severity in zip(st.columns(len(SEVERITY_ORDER)), SEVERITY_ORDER, strict=True):
        column.metric(f"{SEVERITY_BADGES[severity]} {severity}", counts[severity])


def _render_quarantine(quarantine: Sequence[dict]) -> None:
    """Collapsible warning section; only rendered when something was quarantined."""
    if not quarantine:
        return
    with st.expander(f"⚠ Quarantined rows ({len(quarantine)})"):
        st.warning("These rows were not loaded. Fix them in the source file and upload it again.")
        st.dataframe(quarantine_table(quarantine), hide_index=True, width="stretch")


def _render_alert(alert: Alert, ledger: pd.DataFrame) -> None:
    """One expandable alert card with its cited, highlighted ledger rows."""
    badge = SEVERITY_BADGES[alert.severity]
    with st.expander(f"{badge} [{alert.severity}] {alert.title}"):
        st.markdown(f"**Detector:** `{alert.detector}`")
        lines = source_lines_of(ledger)
        refs = ", ".join(ref_with_line_markdown(ref, lines) for ref in alert.source_refs)
        st.markdown("**Source refs:** " + refs)
        if alert.explanation:
            st.write(alert.explanation)
        cited, missing = rows_for_refs(ledger, alert.source_refs)
        if not cited.empty:
            styled = highlight_rows(format_for_display(cited))
            st.dataframe(styled, hide_index=True, width="stretch")
        if missing:
            st.caption("Cited rows from other loaded inputs: " + ", ".join(missing))


def main() -> None:
    """Render the reference page."""
    st.set_page_config(page_title="Ghost Ledger Kit", layout="wide")
    st.title("Ghost Ledger Kit — Ledger Analyser")

    uploaded = st.file_uploader("Upload bank CSV files", type=["csv"], accept_multiple_files=True)
    if not uploaded:
        st.info("Upload one or more bank-statement CSV files to start.")
        return

    files = [(f.name, f.getvalue()) for f in uploaded]
    analysis = analyse(files, st.session_state)

    for summary in analysis.files:
        encoding = summary.encoding or "undecodable"
        st.caption(
            f"{summary.name}: {summary.rows_read} rows read, "
            f"{summary.rows_quarantined} quarantined",
            help=f"Encoding used: {encoding}",
        )

    st.subheader("Summary")
    _render_summary(analysis.alerts)
    _render_quarantine(analysis.quarantine)

    st.subheader("Alerts")
    if not analysis.alerts:
        st.write("No alerts. (The template registers no detectors; apps add their own.)")
    for alert in sort_alerts(analysis.alerts):
        _render_alert(alert, analysis.ledger)


# Streamlit executes the script as __main__; importing the module (tests) renders nothing.
if __name__ == "__main__":
    main()
