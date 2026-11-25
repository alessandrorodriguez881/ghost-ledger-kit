"""Load config.toml, build the demo inputs, run the pipeline and shape the view models (design 8).

Everything here works without Streamlit so it can be tested directly. Items marked "copied" are
written again from zombie_subscriptions because the library does not offer them (design 11.3).
"""

from __future__ import annotations

import hashlib
import io
import tomllib
from collections.abc import Iterable, Mapping, MutableMapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import pandas as pd

import apps.vampire_fees.detectors  # noqa: F401  (registers the vf.* detectors)
from apps.vampire_fees.detectors.utils import (
    VOCABULARY_KEYS,
    FeeVocabulary,
    PeerContext,
    PeerService,
    build_peer_services,
    build_vocabulary,
    skipped_currency_rows,
)
from apps.vampire_fees.explain_support import PEER_MARKER_KEY, PEER_SENTENCE
from ledger_kit.detectors import DetectorResult, run_all
from ledger_kit.explainer import fill_fallback
from ledger_kit.ingestion.normaliser import normalise
from ledger_kit.ingestion.sniffer import format_label, read_bank_statement, sniff_format
from ledger_kit.live_guard import rejection_reason_text
from ledger_kit.models import ALERT_ID_EXCLUDED_PREFIX, Alert
from ledger_kit.public_data import (
    ACCOUNT_TYPE_ORDER,
    ACCOUNT_TYPES,
    FeeSnapshot,
    FeeSnapshotError,
    load_fee_snapshot,
)
from ledger_kit.utils.money import format_amount

if TYPE_CHECKING:
    from ledger_kit.explainer import Explanation

# Alert severities in display order.
SEVERITY_ORDER: tuple[str, ...] = ("critical", "warning", "info")

# Demo format radio (REQ-VF-02): the option shown, and the `fmt` of `demo_inputs` it selects.
DemoFormat = Literal["csv", "n43"]
DEMO_FORMATS: dict[str, DemoFormat] = {"CSV": "csv", "Norma 43": "n43"}

# Session-state keys all start with vf_ (DN-VF-14).
SOURCE_KEY = "vf_source"
DEMO_LOADED_KEY = "vf_demo_loaded"

# Guard-badge labels (copied, C2). `{numbers}` is replaced by the rejected tokens.
BADGE_LLM: str = "🤖 ✓ LLM text · figures checked by the number guard; wording not checked"
BADGE_TEMPLATE: str = "📋 Template (no API key)"
BADGE_UNAVAILABLE: str = "📋 Template (LLM unavailable)"
BADGE_REJECTED: str = (
    "⚠️ LLM answer rejected: not found in the cited rows or the alert data: {numbers}"
)
# The same badge for any reason; `{reason}` comes from `rejection_reason_text` (a missing figure
# reads exactly as BADGE_REJECTED does).
BADGE_REJECTED_REASON: str = "⚠️ LLM answer rejected: {reason}"

# The rule in force, per detected format (REQ-VF-45).
RULE_CSV: str = "A CSV has no bank concept: fees are recognised by words only."
RULE_NORMA43: str = "Bank concepts 16 and 17 are fees; other rows are recognised by words."
RULE_REFUNDS: str = "Refunds are not subtracted."

INTERVAL_LABELS: dict[str, str] = {
    "monthly": "every month",
    "quarterly": "every quarter",
    "yearly": "every year",
}
NOT_AVAILABLE: str = "n/a"
SUMMARY_DETECTOR = "vf.fee_summary"


@dataclass(frozen=True)
class DemoInputs:
    """The demo statement: its bytes and its file name."""

    statement_bytes: bytes
    statement_name: str


def load_config(path: Path) -> dict[str, Any]:
    """Read a TOML configuration file into a dict."""
    with Path(path).open("rb") as handle:
        return tomllib.load(handle)


def load_vocabulary(config: Mapping[str, Any]) -> FeeVocabulary:
    """Fold the [vocabulary] table of a config; ValueError naming the table or the key."""
    table = config.get("vocabulary")
    if not isinstance(table, Mapping):
        raise ValueError("config has no [vocabulary] table")
    return build_vocabulary(table)


def vocabulary_lines(table: Mapping[str, Any]) -> list[str]:
    """Return one 'key: phrase, phrase' line per vocabulary key, for the read-only expander."""
    return [f"{key}: {', '.join(str(p) for p in table.get(key, []))}" for key in VOCABULARY_KEYS]


def demo_inputs(config: Mapping[str, Any], root: Path, fmt: str = "csv") -> DemoInputs:
    """Read the demo statement named by [demo] (relative to `root`) in the chosen format."""
    demo = config["demo"]
    if fmt == "csv":
        path = Path(root) / demo["csv_path"]
    elif fmt == "n43":
        path = Path(root) / demo["n43_path"]
    else:
        raise ValueError(f"unknown demo format {fmt!r}")
    return DemoInputs(statement_bytes=path.read_bytes(), statement_name=path.name)


def apply_demo(state: MutableMapping[str, Any], demo: DemoInputs) -> None:
    """Set the source for the Load demo data button; run it inside an `on_click` callback."""
    state[SOURCE_KEY] = ("demo", demo.statement_bytes, demo.statement_name)
    state[DEMO_LOADED_KEY] = True


# --- Pipeline ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Pipeline:
    """What the page shows, computed once from one statement."""

    ledger: pd.DataFrame  # normalised rows, debits and credits
    quarantine: list[dict]  # reader quarantine followed by normaliser quarantine
    skipped_currency: int  # rows in a currency other than EUR (not analysed)
    kind: str  # sniffed format: "csv", "norma43", ...
    results: list[DetectorResult]  # run_all(ledger, namespace="vf", context=...)

    @property
    def alerts(self) -> list[Alert]:
        """Every alert of every detector, in result order."""
        return [alert for result in self.results for alert in result.alerts]


def ingest_statement(
    name: str, data: bytes, cache: MutableMapping[str, Any] | None = None
) -> tuple[pd.DataFrame, list[dict]]:
    """Read one statement (CSV or Norma 43) and normalise it; return ledger, quarantine (C5).

    The content picks the reader, not the file extension. With a `cache` the parse is kept by
    sha256 of the bytes and the file name, so a rerun does not read the bytes again.
    """
    if cache is None:
        transactions, quarantined = read_bank_statement(io.BytesIO(data), source_file=name)
    else:
        key = f"{hashlib.sha256(data).hexdigest()}:{name}"
        if key not in cache:
            cache[key] = read_bank_statement(io.BytesIO(data), source_file=name)
        transactions, quarantined = cache[key]
    ledger, normalise_quarantine = normalise(transactions)
    return ledger, [*quarantined, *normalise_quarantine]


def run_pipeline(
    name: str,
    data: bytes,
    *,
    vocabulary: FeeVocabulary,
    cache: MutableMapping[str, Any] | None = None,
    peers: PeerContext | None = None,
) -> Pipeline:
    """Read, normalise and run every vf.* detector on the whole ledger, credits included.

    `peers` is the fee comparison context; it is put into the detector context only when it is
    not None, so a call without it runs exactly as before (public-fees design 9).
    """
    ledger, quarantine = ingest_statement(name, data, cache)
    context: dict[str, Any] = {"vocabulary": vocabulary}
    if peers is not None:
        context["peers"] = peers
    results = run_all(ledger, namespace="vf", context=context)
    return Pipeline(
        ledger=ledger,
        quarantine=quarantine,
        skipped_currency=skipped_currency_rows(ledger),
        kind=sniff_format(data),
        results=results,
    )


# --- View-model helpers ------------------------------------------------------------------------


def markdown_safe(text: str) -> str:
    """Backslash-escape the markdown characters of `text` so it is shown literally (copied, C3)."""
    return "".join(f"\\{char}" if char in "\\`*_~$<>[]" else char for char in text)


def statement_caption(
    name: str, kind: str, rows: int, debit_rows: int, quarantined: int, skipped: int
) -> str:
    """Return the line under the title: file, detected format and the row counts."""
    label = format_label(kind)
    shown = name if label is None else f"{name} ({label})"
    return (
        f"{shown}: {rows} rows analysed ({debit_rows} debit rows), "
        f"{quarantined} quarantined, {skipped} skipped for currency"
    )


def rule_sentences(kind: str) -> list[str]:
    """Return the sentences on the rule in force for the format, then the refunds sentence."""
    rule = {"csv": RULE_CSV, "norma43": RULE_NORMA43}.get(kind)
    return [RULE_REFUNDS] if rule is None else [rule, RULE_REFUNDS]


@dataclass(frozen=True)
class GuardBadge:
    """What the guard badge under an explanation says; `kind` selects its colour (copied, C2)."""

    kind: str  # "llm", "template", "unavailable" or "rejected"
    label: str


def guard_badge(explanation: Explanation, *, has_api_key: bool) -> GuardBadge:
    """Choose the guard badge of one explanation."""
    if explanation.source == "llm":
        return GuardBadge("llm", BADGE_LLM)
    if explanation.rejected_numbers:
        reason = rejection_reason_text(
            explanation.rejected_reason,
            explanation.rejected_numbers,
            explanation.rejected_why,
            explanation.raw_answer,
        )
        return GuardBadge("rejected", BADGE_REJECTED_REASON.format(reason=reason))
    if has_api_key:
        return GuardBadge("unavailable", BADGE_UNAVAILABLE)
    return GuardBadge("template", BADGE_TEMPLATE)


def group_alerts_by_severity(alerts: Iterable[Alert]) -> dict[str, list[Alert]]:
    """Group alerts critical, warning, info; every severity is present, input order kept (C4)."""
    groups: dict[str, list[Alert]] = {severity: [] for severity in SEVERITY_ORDER}
    for alert in alerts:
        groups[alert.severity].append(alert)
    return groups


@dataclass(frozen=True)
class CoffinView:
    """Display strings of one coffin card; every figure is read from Alert.data."""

    counterparty: str
    description: str
    interval: str
    current_amount: str
    yearly_cost: str
    source_refs: tuple[str, ...]


def coffin_view(alert: Alert) -> CoffinView:
    """Turn one vf.recurring_fee alert into the strings of its coffin; computes nothing."""
    data = alert.data
    return CoffinView(
        counterparty=str(data["counterparty"]),
        description=str(data["description"]),
        interval=INTERVAL_LABELS.get(str(data["interval_type"]), str(data["interval_type"])),
        current_amount=format_amount(Decimal(str(data["current_amount"]))),
        yearly_cost=format_amount(Decimal(str(data["yearly_cost"]))),
        source_refs=tuple(alert.source_refs),
    )


@dataclass(frozen=True)
class SummaryView:
    """Display strings of the metrics row, read from the vf.fee_summary alert."""

    fee_count: str
    total_fees: str
    yearly_equivalent: str


def summary_view(alerts: Iterable[Alert]) -> SummaryView | None:
    """Return the metrics of the summary alert, or None when there is no fee."""
    for alert in alerts:
        if alert.detector != SUMMARY_DETECTOR:
            continue
        data = alert.data
        yearly = data.get("yearly_equivalent")
        return SummaryView(
            fee_count=str(data["fee_count"]),
            total_fees=format_amount(Decimal(str(data["total_fees"]))),
            yearly_equivalent=NOT_AVAILABLE
            if yearly is None
            else format_amount(Decimal(str(yearly))),
        )
    return None


# --- Fee comparison card helpers (public-fees PF5, REQ-PF-19) ------------------------------------

# The line under a card that names the source of the comparison; every `{...}` is a peer_ field.
PEER_SOURCE_LINE: str = (
    "Comparison source: {peer_source}, account type {peer_account_type} "
    "({peer_account_type_label}), service {peer_service} ({peer_service_label}), "
    "declared {peer_declaration_date}; {not_offered}."
)
# The licence line of the footer; the two dates are the snapshot's own.
PEER_LICENCE_LINE: str = (
    "Licence: see the Banco de España legal notice · retrieved {retrieved_on} · "
    "declarations of {declaration_date}"
)


def _not_offered_text(count: int) -> str:
    """Return '3 accounts show an asterisk (...)' with the Excel legend (singular for one).

    The asterisk means no fee is charged or the service is not offered; the kit does not guess
    which one applies (decision D6). The character itself is spelled out as a word because the
    page escapes it.
    """
    legend = "(no fee is charged or the service is not offered)"
    if count == 1:
        return f"1 account shows an asterisk {legend}"
    return f"{count} accounts show an asterisk {legend}"


def peer_source_line(alert: Alert) -> str | None:
    """Return the comparison source line of a card, or None when the alert has no peer fields.

    Plain text from the alert's own fields; the page shows it through `markdown_safe`.
    """
    data = alert.data
    if PEER_MARKER_KEY not in data:
        return None
    fields = {key: str(value) for key, value in data.items() if key.startswith("peer_")}
    return PEER_SOURCE_LINE.format(
        **fields, not_offered=_not_offered_text(int(data["peer_not_offered_count"]))
    )


def peer_sentence_to_add(alert: Alert, explanation: Explanation) -> str | None:
    """Return the comparison sentences to add under the explanation, or None.

    None when the alert has no peer fields or the explanation already holds the sentences (the
    fallback template does), so they are shown once; otherwise the sentences filled from the alert.
    """
    if PEER_MARKER_KEY not in alert.data:
        return None
    sentence = fill_fallback(PEER_SENTENCE, alert)
    return None if sentence in explanation.text else sentence


def peer_attribution_lines(snapshot: FeeSnapshot) -> list[str]:
    """Return the footer lines: attribution, licence line, licence note, no-endorsement text.

    The texts are the snapshot's own (decision Q1); they are shown once on the page.
    """
    licence = PEER_LICENCE_LINE.format(
        retrieved_on=snapshot.retrieved_on, declaration_date=snapshot.declaration_date
    )
    return [snapshot.attribution, licence, snapshot.licence_note, snapshot.no_endorsement]


# --- Fee comparison: loading the snapshot and the account type (public-fees PF6, design 9) -------

PeerStatus = Literal["ok", "missing", "invalid"]

# The label of the sidebar select box of the account type (REQ-PF-20).
PEER_SELECT_LABEL: str = "Compare my fees with"
# The captions shown instead of the footer when no snapshot can be used (REQ-PF-19).
PEER_UNAVAILABLE_NOT_FOUND: str = "Fee comparison unavailable: snapshot not found."
PEER_UNAVAILABLE_INVALID: str = "Fee comparison unavailable: snapshot invalid."


def _peer_table(config: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return the [peer_fees] table of a config, or an empty mapping when there is none."""
    table = config.get("peer_fees")
    return table if isinstance(table, Mapping) else {}


def peer_snapshot_path(config: Mapping[str, Any], root: Path) -> Path | None:
    """Return the snapshot path of [peer_fees] relative to `root`, or None when none is set."""
    path = _peer_table(config).get("snapshot_path")
    if not isinstance(path, str) or not path.strip():
        return None
    return Path(root) / path


def read_fee_snapshot(path: Path | None) -> FeeSnapshot | None:
    """Load a fee snapshot; None for no path, a missing file or an invalid one (never raises)."""
    if path is None:
        return None
    try:
        return load_fee_snapshot(Path(path))
    except FeeSnapshotError:
        return None


def peer_status(config: Mapping[str, Any], root: Path) -> PeerStatus:
    """Say whether the configured snapshot loads: 'ok', 'missing' (no file) or 'invalid'."""
    path = peer_snapshot_path(config, root)
    if path is None or not path.is_file():
        return "missing"
    return "ok" if read_fee_snapshot(path) is not None else "invalid"


def peer_unavailable_caption(status: PeerStatus) -> str | None:
    """Return the caption that replaces the footer, or None when the snapshot loaded."""
    if status == "missing":
        return PEER_UNAVAILABLE_NOT_FOUND
    if status == "invalid":
        return PEER_UNAVAILABLE_INVALID
    return None


def peer_services_of(config: Mapping[str, Any]) -> tuple[PeerService, ...]:
    """Fold the services of [peer_fees]; no table gives no service (no comparison)."""
    table = _peer_table(config)
    return build_peer_services(table) if table else ()


def configured_peer_type(config: Mapping[str, Any]) -> str | None:
    """Return `default_account_type` of [peer_fees], or None when it is not set."""
    value = _peer_table(config).get("default_account_type")
    return value if isinstance(value, str) else None


def peer_context_for(
    snapshot: FeeSnapshot, account_type: str, config: Mapping[str, Any]
) -> PeerContext:
    """Return the detector context of the comparison: snapshot, account type, config services."""
    return PeerContext(snapshot, account_type, peer_services_of(config))


def load_peers(config: Mapping[str, Any], root: Path, account_type: str) -> PeerContext | None:
    """Load the configured snapshot and return its PeerContext; None when it does not load."""
    snapshot = read_fee_snapshot(peer_snapshot_path(config, root))
    return None if snapshot is None else peer_context_for(snapshot, account_type, config)


def peer_type_options(snapshot: FeeSnapshot) -> tuple[str, ...]:
    """Return the account types present in the snapshot, in the fixed order (REQ-PF-20)."""
    return tuple(code for code in ACCOUNT_TYPE_ORDER if code in snapshot.account_types)


def peer_type_label(code: str) -> str:
    """Return how an account type is shown in the select box: 'CNO · Cuenta Nómina/Pensión'."""
    known = ACCOUNT_TYPES.get(code)
    return code if known is None else f"{code} · {known.label}"


def default_peer_type(snapshot: FeeSnapshot, configured: str | None) -> str:
    """Return the configured type when the snapshot has it, else its first type in order."""
    options = peer_type_options(snapshot)
    if configured is not None and configured in options:
        return configured
    return options[0]


PeerItems = tuple[tuple[str, Any], ...]


def explanation_cache_key(alert: Alert, mode: str) -> tuple[str, str, PeerItems]:
    """Return (alert.id, mode, peer items): the peer_ fields are not in the id (decision Q7).

    The peer items are the (key, value) pairs of the `peer_` keys of `alert.data`, in data order,
    so a new account type or a new snapshot never reuses an explanation of another comparison.
    """
    items = tuple(
        (key, value)
        for key, value in alert.data.items()
        if isinstance(key, str) and key.startswith(ALERT_ID_EXCLUDED_PREFIX)
    )
    return alert.id, mode, items
