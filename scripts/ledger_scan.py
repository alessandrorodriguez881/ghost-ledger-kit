"""Ledger scan: check statements and invoices with the kit from the command line.

Spec: ``.kiro/specs/scan-command/``. Two subcommands, both read-only, both deterministic. No language model is called and nothing
opens a connection (REQ-SCAN-01, REQ-SCAN-15):

* ``scan FILE [FILE ...]`` sniffs each file by content, runs the pipeline of each app exactly as
  its page does and prints one JSON object with the files and every alert.
* ``check --alert-id ID --text TEXT FILE [FILE ...]`` reruns the scan and applies the number
  guard of ``ledger_kit.explainer`` to TEXT for that alert and its cited rows.

Run it with the Python of the kit's own virtual environment, so no other program has to install
the kit's pinned packages: ``python scripts/ledger_scan.py scan statement.csv``.
"""

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from importlib import metadata
from pathlib import Path
from typing import Any, TextIO

# `python scripts/ledger_scan.py` puts only scripts/ on sys.path: add the repository root too.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd  # noqa: E402

import apps.phantom_invoices.action_templates as pi_actions  # noqa: E402
import apps.phantom_invoices.detectors  # noqa: E402,F401  (registers the pi.* detectors)
import apps.phantom_invoices.explain_support as pi_support  # noqa: E402
import apps.phantom_invoices.settings as pi_settings  # noqa: E402
import apps.vampire_fees.action_templates as vf_actions  # noqa: E402
import apps.vampire_fees.detectors  # noqa: E402,F401  (registers the vf.* detectors)
import apps.vampire_fees.explain_support as vf_support  # noqa: E402
import apps.vampire_fees.settings as vf_settings  # noqa: E402
import apps.zombie_subscriptions.action_templates as zs_actions  # noqa: E402
import apps.zombie_subscriptions.detectors  # noqa: E402,F401  (registers the zs.* detectors)
import apps.zombie_subscriptions.explain_support as zs_support  # noqa: E402
import apps.zombie_subscriptions.settings as zs_settings  # noqa: E402
from apps.zombie_subscriptions.detectors.utils import (  # noqa: E402
    normalise_alias_map,
    normalise_date_map,
)
from ledger_kit.actions import LANGUAGES, ActionTemplate, build_draft  # noqa: E402
from ledger_kit.explainer import check_figures, fill_fallback  # noqa: E402
from ledger_kit.ingestion.sniffer import SNIFF_BYTES, UTF8_BOM, sniff_format  # noqa: E402
from ledger_kit.models import Alert  # noqa: E402
from ledger_kit.ui.reference_app import format_for_display, rows_for_refs  # noqa: E402

# Version reported when the kit is not installed as a package (the pyproject fallback).
FALLBACK_VERSION: str = "0.0.0"

# What a file is, as reported in the JSON `kind` field.
KIND_STATEMENT: str = "bank_statement"
KIND_INVOICE: str = "invoice"
KIND_SUPPLIERS: str = "supplier_master"
KIND_PAYMENTS: str = "payments"
KIND_EMPTY: str = "empty"
KIND_UNKNOWN: str = "unknown"

# The `app` field of an alert.
APP_ZOMBIE: str = "zombie_subscriptions"
APP_VAMPIRE: str = "vampire_fees"
APP_PHANTOM: str = "phantom_invoices"

# Alert order in the output: severity first (critical first), then the title (REQ-SCAN-13).
SEVERITY_ORDER: tuple[str, ...] = ("critical", "warning", "info")

# CSV header names that tell an invoice file from a bank statement (exact column names of the
# two readers); the content decides, never the file extension.
INVOICE_COLUMN: str = "invoice_number"
STATEMENT_COLUMN: str = "counterparty"

ZS_CONFIG: Path = REPO_ROOT / "apps" / "zombie_subscriptions" / "config.toml"
VF_CONFIG: Path = REPO_ROOT / "apps" / "vampire_fees" / "config.toml"

MSG_UNRECOGNISED: str = (
    "format not recognised: expected a bank statement (CSV or Norma 43) "
    "or invoices (CSV, JSON or Facturae)"
)
MSG_UNKNOWN_ALERT: str = "unknown alert id: no alert with this id in the files given"

_ISO_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
_HEADER_SEPARATORS = re.compile(r"[,;]")


# --- Records ----------------------------------------------------------------------------------


@dataclass
class FileReport:
    """One input file: what it is, how many rows were read and what went wrong, if anything."""

    path: str
    sha256: str | None = None
    kind: str | None = None
    format: str | None = None
    rows: int = 0
    quarantined: int = 0
    error: str | None = None
    data: bytes = field(default=b"", repr=False)

    def as_json(self) -> dict[str, Any]:
        """Return the fields of the report in their fixed output order."""
        return {
            "path": self.path,
            "sha256": self.sha256,
            "kind": self.kind,
            "format": self.format,
            "rows": self.rows,
            "quarantined": self.quarantined,
            "error": self.error,
        }


@dataclass(frozen=True)
class Found:
    """One alert with what the card of its page holds: text, cited rows and Exorcise template."""

    app: str
    alert: Alert
    rows: pd.DataFrame  # the rows the page hands to the guard and to the draft
    row_columns: tuple[str, ...] | None
    shown_rows: list[dict[str, str | None]]  # the visible columns of the cited rows
    text: str | None  # the fixed template text of the card
    action: ActionTemplate | None


@dataclass(frozen=True)
class Scan:
    """The result of one run: a report per file and every alert found."""

    files: list[FileReport]
    found: list[Found]


# --- Small helpers ----------------------------------------------------------------------------


def kit_version() -> str:
    """Return the installed version of the kit, or the pyproject fallback when not installed."""
    try:
        return metadata.version("ledger-kit")
    except metadata.PackageNotFoundError:
        return FALLBACK_VERSION


def _cell(value: Any) -> str | None:
    """Return a table cell as text; a missing value is None."""
    if value is None or isinstance(value, str):
        return value
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return str(value)


def _records(frame: pd.DataFrame) -> list[dict[str, str | None]]:
    """Return the rows of a display frame as dicts of text, in frame order."""
    return [
        {str(key): _cell(value) for key, value in record.items()}
        for record in frame.to_dict("records")
    ]


def _describe(error: Exception) -> str:
    """Return a short, stable description of an exception."""
    return f"{type(error).__name__}: {error}"


def _header_names(data: bytes) -> set[str]:
    """Return the lower-case column names of the first non-blank line of a CSV."""
    head = bytes(data[:SNIFF_BYTES]).removeprefix(UTF8_BOM).decode("utf-8", "replace")
    line = next((text for text in head.splitlines() if text.strip()), "")
    return {cell.strip().strip('"').strip().lower() for cell in _HEADER_SEPARATORS.split(line)}


def classify(data: bytes, sniffed: str) -> str:
    """Return the kind of a file from its sniffed format and, for a CSV, its header."""
    if sniffed == "norma43":
        return KIND_STATEMENT
    if sniffed in ("json", "facturae"):
        return KIND_INVOICE
    if sniffed == "empty":
        return KIND_EMPTY
    if sniffed == "csv":
        names = _header_names(data)
        if INVOICE_COLUMN in names:
            return KIND_INVOICE
        if STATEMENT_COLUMN in names:
            return KIND_STATEMENT
    return KIND_UNKNOWN


def load_file(path: str, kind: str | None = None) -> FileReport:
    """Read one file; an unreadable file gets an error text instead of raising.

    `kind` is fixed for the supplier master and the payments file; for the other files it is
    found from the content.
    """
    report = FileReport(path)
    try:
        data = Path(path).read_bytes()
    except OSError as error:
        report.error = f"cannot read file: {error.strerror or type(error).__name__}"
        return report
    report.data = data
    report.sha256 = hashlib.sha256(data).hexdigest()
    report.format = sniff_format(data)
    report.kind = kind or classify(data, report.format)
    if report.kind == KIND_UNKNOWN:
        report.error = MSG_UNRECOGNISED
    return report


# --- Alerts of the three apps -----------------------------------------------------------------


def _fixed_text(template_for: Any, alert: Alert) -> str | None:
    """Return the text the card shows without a model: the filled fallback template."""
    try:
        return fill_fallback(template_for(alert), alert)
    except (KeyError, ValueError):
        return None


def _statement_found(
    app: str, alerts: Sequence[Alert], ledger: pd.DataFrame, support: Any, actions: Any
) -> list[Found]:
    """Build the Found records of a statement app (zombie or vampire), as its card does."""
    found: list[Found] = []
    for alert in alerts:
        cited, _missing = rows_for_refs(ledger, alert.source_refs)
        found.append(
            Found(
                app=app,
                alert=alert,
                rows=ledger[ledger["source_ref"].isin(alert.source_refs)],
                row_columns=None,
                shown_rows=_records(format_for_display(cited)),
                text=_fixed_text(support.template_for, alert),
                action=actions.action_for(alert),
            )
        )
    return found


def _scan_statement(report: FileReport) -> list[Found]:
    """Run the Zombie and Vampire pipelines on one statement; count its rows on the report.

    The Zombie run has no aliases and no cancellation dates, so a detector that needs them does
    not fire (REQ-SCAN-05). Both pipelines are the ones the pages call.
    """
    name = Path(report.path).name
    zombie = zs_settings.run_pipeline(
        name,
        report.data,
        aliases=normalise_alias_map({}),
        cancellation_dates=normalise_date_map({}),
        cpi=zs_settings.load_cpi(zs_settings.load_config(ZS_CONFIG), REPO_ROOT),
    )
    vampire = vf_settings.run_pipeline(
        name,
        report.data,
        vocabulary=vf_settings.load_vocabulary(vf_settings.load_config(VF_CONFIG)),
    )
    report.rows = len(zombie.ledger)
    report.quarantined = len(zombie.quarantine)
    return [
        *_statement_found(APP_ZOMBIE, zombie.alerts, zombie.debit_ledger, zs_support, zs_actions),
        *_statement_found(APP_VAMPIRE, vampire.alerts, vampire.ledger, vf_support, vf_actions),
    ]


def _phantom_shown(
    alert: Alert, ledger_view: pd.DataFrame, pipeline: pi_settings.Pipeline
) -> list[dict[str, str | None]]:
    """Return the cited rows of a phantom alert as its page shows them, in source_refs order."""
    refs = alert.source_refs
    records = [
        *_records(ledger_view[ledger_view["source_ref"].isin(refs)]),
        *_records(pi_settings.cited_master_view(pipeline.suppliers, refs)),
        *_records(pi_settings.cited_payments_view(pipeline.payments, refs)),
    ]
    position = {ref: index for index, ref in enumerate(refs)}
    records.sort(key=lambda record: position.get(record.get("source_ref") or "", len(refs)))
    return records


def _count_for(frame: pd.DataFrame, name: str) -> int:
    """Count the rows of a normalised frame that come from the file called `name`."""
    if "source_file" not in frame.columns:
        return 0
    return int((frame["source_file"] == name).sum())


def _count_quarantine(pipeline: pi_settings.Pipeline, file_kind: str, name: str | None) -> int:
    """Count the quarantine records of one input box, or of one file of it."""
    return sum(
        1
        for record in pipeline.quarantine
        if record.get("file_kind") == file_kind
        and (name is None or record.get("source_file") == name)
    )


def _scan_invoices(
    invoices: Sequence[FileReport],
    suppliers: FileReport | None,
    payments: FileReport | None,
    as_of: date | None,
) -> list[Found]:
    """Run the Phantom pipeline once on every invoice file, with the optional master and payments.

    One run, so the duplicate-invoice check sees all the invoices together (REQ-SCAN-06).
    """

    def source(report: FileReport | None) -> pi_settings.Source | None:
        if report is None or report.error is not None:
            return None
        return pi_settings.Source(Path(report.path).name, report.data)

    sources = [src for src in (source(report) for report in invoices) if src is not None]
    pipeline = pi_settings.run_pipeline(sources, source(suppliers), source(payments), as_of)
    for report in invoices:
        name = Path(report.path).name
        report.rows = _count_for(pipeline.invoices, name)
        report.quarantined = _count_quarantine(pipeline, "invoices", name)
    if suppliers is not None and suppliers.error is None:
        suppliers.rows = len(pipeline.suppliers)
        suppliers.quarantined = _count_quarantine(pipeline, "suppliers", None)
    if payments is not None and payments.error is None:
        payments.rows = len(pipeline.payments)
        payments.quarantined = _count_quarantine(pipeline, "payments", None)

    ledger_view = pi_settings.ledger_view(pipeline.invoices, pipeline.reconciliation)
    alerts = [alert for result in pipeline.results for alert in result.alerts]
    return [
        Found(
            app=APP_PHANTOM,
            alert=alert,
            rows=pi_support.build_explain_rows(
                alert, pipeline.invoices, pipeline.suppliers, pipeline.payments
            ),
            row_columns=tuple(pi_support.ROW_COLUMNS),
            shown_rows=_phantom_shown(alert, ledger_view, pipeline),
            text=_fixed_text(pi_support.template_for, alert),
            action=pi_actions.action_for(alert),
        )
        for alert in alerts
    ]


def scan_files(
    paths: Sequence[str],
    *,
    suppliers: str | None = None,
    payments: str | None = None,
    as_of: date | None = None,
) -> Scan:
    """Sniff and run every file; a file that fails is reported and the others still run."""
    reports = [load_file(path) for path in paths]
    suppliers_report = None if suppliers is None else load_file(suppliers, KIND_SUPPLIERS)
    payments_report = None if payments is None else load_file(payments, KIND_PAYMENTS)

    found: list[Found] = []
    for report in reports:
        if report.error is not None or report.kind != KIND_STATEMENT:
            continue
        try:
            found.extend(_scan_statement(report))
        except Exception as error:  # a broken file must not stop the others (REQ-SCAN-09)
            report.error = _describe(error)
            report.rows, report.quarantined = 0, 0

    invoices = [r for r in reports if r.error is None and r.kind == KIND_INVOICE]
    if invoices:
        try:
            found.extend(_scan_invoices(invoices, suppliers_report, payments_report, as_of))
        except Exception as error:  # same: the statements above are already scanned
            for report in invoices:
                report.error = _describe(error)
                report.rows, report.quarantined = 0, 0

    files = [*reports, *(r for r in (suppliers_report, payments_report) if r is not None)]
    severity = {name: index for index, name in enumerate(SEVERITY_ORDER)}
    found.sort(
        key=lambda item: (
            severity[item.alert.severity],
            item.alert.title,
            item.app,
            item.alert.detector,
            item.alert.id,
        )
    )
    return Scan(files, found)


# --- Output -----------------------------------------------------------------------------------


def _drafts(item: Found) -> dict[str, str | None] | None:
    """Return the Exorcise drafts per language, or None when the alert type has no template."""
    if item.action is None:
        return None
    return {
        code: build_draft(item.alert, item.rows, item.action, code, row_columns=item.row_columns)
        for code, _label in LANGUAGES
    }


def alert_json(item: Found) -> dict[str, Any]:
    """Return one alert in the fixed key order of the output (REQ-SCAN-11)."""
    alert = item.alert
    return {
        "alert_id": alert.id,
        "app": item.app,
        "detector": alert.detector,
        "severity": alert.severity,
        "title": alert.title,
        "text": item.text,
        "source_refs": list(alert.source_refs),
        "rows": item.shown_rows,
        "drafts": _drafts(item),
    }


def scan_json(scan: Scan) -> dict[str, Any]:
    """Return the whole result of `scan` in the fixed key order of the output."""
    return {
        "kit_version": kit_version(),
        "files": [report.as_json() for report in scan.files],
        "alerts": [alert_json(item) for item in scan.found],
    }


def check_json(scan: Scan, alert_id: str, text: str) -> dict[str, Any]:
    """Apply the number guard to `text` for the alert called `alert_id`."""
    item = next((found for found in scan.found if found.alert.id == alert_id), None)
    if item is None:
        return {"alert_id": alert_id, "passed": False, "rejected": [], "error": MSG_UNKNOWN_ALERT}
    passed, rejected = check_figures(text, item.alert, item.rows, item.row_columns)
    return {"alert_id": alert_id, "passed": passed, "rejected": list(rejected), "error": None}


def dumps(payload: dict[str, Any]) -> str:
    """Serialise to JSON: keys in the order built, ASCII only, so equal input gives equal bytes."""
    return json.dumps(payload, indent=2, ensure_ascii=True)


# --- Command line -----------------------------------------------------------------------------


def _iso_day(text: str) -> date:
    """Parse YYYY-MM-DD for argparse; anything else is an argument error (exit code 2)."""
    if _ISO_DAY.fullmatch(text) is None:
        raise argparse.ArgumentTypeError(f"{text!r} is not a date in the form YYYY-MM-DD")
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a real date") from None


def _add_inputs(parser: argparse.ArgumentParser) -> None:
    """Add the files and the options both subcommands share."""
    parser.add_argument("files", nargs="+", metavar="FILE", help="statement or invoice file")
    parser.add_argument("--suppliers", metavar="CSV", help="supplier master (invoices only)")
    parser.add_argument("--payments", metavar="FILE", help="bank payments, CSV or Norma 43")
    parser.add_argument(
        "--as-of", metavar="YYYY-MM-DD", type=_iso_day, help="as-of date of the invoice checks"
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the command line: `scan` and `check`."""
    parser = argparse.ArgumentParser(
        prog="ledger_scan.py", description="Check statements and invoices with Ghost Ledger Kit."
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="{scan,check}")
    scan = commands.add_parser("scan", help="print every alert of the files as JSON")
    _add_inputs(scan)
    check = commands.add_parser("check", help="apply the number guard to a text for one alert")
    check.add_argument("--alert-id", required=True, metavar="ID", help="id of the alert")
    check.add_argument("--text", required=True, metavar="TEXT", help="the text to check")
    _add_inputs(check)
    return parser


def main(argv: Sequence[str] | None = None, out: TextIO | None = None) -> int:
    """Run the command; return 0 when it ran (bad arguments exit with 2 through argparse)."""
    args = build_parser().parse_args(argv)
    result = scan_files(
        args.files, suppliers=args.suppliers, payments=args.payments, as_of=args.as_of
    )
    if args.command == "scan":
        payload = scan_json(result)
    else:
        payload = check_json(result, args.alert_id, args.text)
    stream = sys.stdout if out is None else out
    stream.write(dumps(payload) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
