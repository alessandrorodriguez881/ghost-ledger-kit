"""Load config.toml, build the demo inputs and parse/format the sidebar text (design §7).

Also holds the pure view-model helpers of the app (demo pre-fill, guard badge, tombstone and
severity grouping). Everything here works without Streamlit so it can be tested directly.
"""

from __future__ import annotations

import tomllib
from collections.abc import Iterable, MutableMapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import pandas as pd

from apps.zombie_subscriptions.explain_support import (
    cpi_sentence_template,
    cpi_uses_lag,
    has_cpi_context,
)
from ledger_kit.explainer import fill_fallback
from ledger_kit.ingestion.sniffer import format_label
from ledger_kit.models import Alert
from ledger_kit.public_data import CpiSeries, SnapshotError, load_snapshot
from ledger_kit.utils.money import format_amount, format_index

if TYPE_CHECKING:
    from apps.zombie_subscriptions.detectors.utils import ZombieCostResult
    from ledger_kit.explainer import Explanation

# Alert severities in display order (REQ-ZS-37).
SEVERITY_ORDER: tuple[str, ...] = ("critical", "warning", "info")

# Currency shown when the ledger has no currency column or no rows.
DEFAULT_CURRENCY: str = "EUR"

# Demo format radio (REQ-RF-24): the option shown, and the `fmt` of `demo_inputs` it selects.
DemoFormat = Literal["csv", "real"]
DEMO_FORMATS: dict[str, DemoFormat] = {"CSV": "csv", "Real formats": "real"}

# Guard-badge labels (REQ-ZS-37). `{numbers}` is replaced by the rejected tokens.
BADGE_LLM: str = "🤖 ✓ LLM text verified by number guard"
BADGE_TEMPLATE: str = "📋 Template (no API key)"
BADGE_UNAVAILABLE: str = "📋 Template (LLM unavailable)"
BADGE_REJECTED: str = "⚠️ LLM answer rejected: invented number {numbers}"


@dataclass(frozen=True)
class DemoInputs:
    """The demo statement and the user inputs that go with it (keys as in config.toml)."""

    statement_bytes: bytes
    statement_name: str
    aliases: dict[str, list[str]] = field(default_factory=dict)
    last_used_dates: dict[str, date] = field(default_factory=dict)
    cancellation_dates: dict[str, date] = field(default_factory=dict)


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


def _date_table(table: dict[str, Any]) -> dict[str, date]:
    """Convert every value of a {name: date-or-string} table with to_date."""
    return {str(name): to_date(value) for name, value in table.items()}


def _alias_table(table: dict[str, Any]) -> dict[str, list[str]]:
    """Convert every value of a {service: [keys]} table to a list of strings."""
    return {str(name): [str(key) for key in keys] for name, keys in table.items()}


def demo_inputs(config: dict[str, Any], root: Path, fmt: DemoFormat = "csv") -> DemoInputs:
    """Read the demo statement named by [demo] (relative to `root`) and its user inputs.

    `csv` reads `csv_path`, `real` reads `n43_path`. The aliases and the dates are the same for
    both: they are keyed by counterparty, which is identical in both files (REQ-RF-25).
    """
    demo = config["demo"]
    if fmt == "csv":
        path = Path(root) / demo["csv_path"]
    elif fmt == "real":
        path = Path(root) / demo["n43_path"]
    else:
        raise ValueError(f"unknown demo format {fmt!r}")
    return DemoInputs(
        statement_bytes=path.read_bytes(),
        statement_name=path.name,
        aliases=_alias_table(demo.get("aliases", {})),
        last_used_dates=_date_table(demo.get("last_used_dates", {})),
        cancellation_dates=_date_table(demo.get("cancellation_dates", {})),
    )


def _split_line(line: str) -> tuple[str, str]:
    """Split 'name = value' at the first '='; ValueError naming the line when it is missing."""
    name, sep, value = line.partition("=")
    if not sep or not name.strip():
        raise ValueError(f"cannot read line {line.strip()!r}: expected 'name = value'")
    return name.strip(), value.strip()


def parse_aliases_text(text: str) -> dict[str, list[str]]:
    """Parse lines 'service = KEY1, KEY2' into {service: [KEY1, KEY2]}; skips blank lines."""
    aliases: dict[str, list[str]] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        name, value = _split_line(line)
        aliases[name] = [member.strip() for member in value.split(",") if member.strip()]
    return aliases


def parse_dates_text(text: str) -> dict[str, date]:
    """Parse lines 'NAME = YYYY-MM-DD' into {NAME: date}; blank lines are skipped."""
    dates: dict[str, date] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        name, value = _split_line(line)
        try:
            dates[name] = date.fromisoformat(value)
        except ValueError:
            message = f"invalid date for {name!r}: {value!r} (expected YYYY-MM-DD)"
            raise ValueError(message) from None
    return dates


def format_aliases_text(aliases: dict[str, list[str]]) -> str:
    """Format an alias map as the sidebar text read by parse_aliases_text."""
    return "\n".join(f"{name} = {', '.join(keys)}" for name, keys in aliases.items())


def format_dates_text(dates: dict[str, date]) -> str:
    """Format a {name: date} map as the sidebar text read by parse_dates_text."""
    return "\n".join(f"{name} = {day.isoformat()}" for name, day in dates.items())


# --- View-model helpers for app.py (no Streamlit) ----------------------------------------------


def apply_demo(state: MutableMapping[str, Any], demo: DemoInputs) -> None:
    """Pre-fill the widget keys and the source for the Load demo data button (design §7).

    Must run inside an `on_click` callback: assigning a widget key after its widget exists in
    the same script run raises StreamlitWidgetAlreadyInstantiatedError.
    """
    state["source"] = ("demo", demo.statement_bytes, demo.statement_name)
    state["aliases_text"] = format_aliases_text(demo.aliases)
    state["last_used_text"] = format_dates_text(demo.last_used_dates)
    state["cancel_text"] = format_dates_text(demo.cancellation_dates)
    state["demo_loaded"] = True


def markdown_safe(text: str) -> str:
    """Backslash-escape the markdown characters of `text` so it is shown literally."""
    return "".join(f"\\{char}" if char in "\\`*_~$<>[]" else char for char in text)


def statement_caption(name: str, kind: str, debit_rows: int, quarantined: int) -> str:
    """Return the line under the title: the file, its detected format and the row counts."""
    label = format_label(kind)
    shown = name if label is None else f"{name} ({label})"
    return f"{shown}: {debit_rows} debit rows analysed, {quarantined} quarantined"


def ledger_currency(ledger: pd.DataFrame) -> str:
    """Return the currency of the first ledger row, or DEFAULT_CURRENCY for an empty ledger."""
    if ledger.empty or "currency" not in ledger.columns:
        return DEFAULT_CURRENCY
    return str(ledger["currency"].iloc[0])


@dataclass(frozen=True)
class GuardBadge:
    """What the guard badge under an explanation says; `kind` selects its colour."""

    kind: str  # "llm", "template", "unavailable" or "rejected"
    label: str


def guard_badge(explanation: Explanation, *, has_api_key: bool) -> GuardBadge:
    """Choose the guard badge of one explanation (REQ-ZS-37)."""
    if explanation.source == "llm":
        return GuardBadge("llm", BADGE_LLM)
    if explanation.rejected_numbers:
        numbers = ", ".join(explanation.rejected_numbers)
        return GuardBadge("rejected", BADGE_REJECTED.format(numbers=numbers))
    if has_api_key:
        return GuardBadge("unavailable", BADGE_UNAVAILABLE)
    return GuardBadge("template", BADGE_TEMPLATE)


def group_alerts_by_severity(alerts: Iterable[Alert]) -> dict[str, list[Alert]]:
    """Group alerts critical, warning, info; every severity is present, input order kept."""
    groups: dict[str, list[Alert]] = {severity: [] for severity in SEVERITY_ORDER}
    for alert in alerts:
        groups[alert.severity].append(alert)
    return groups


@dataclass(frozen=True)
class TombstoneView:
    """Display strings of one tombstone; every amount is formatted by format_amount."""

    name: str
    died_on: str
    cost_since: str
    yearly_cost: str
    source_refs: tuple[str, ...]


def tombstone_view(result: ZombieCostResult, currency: str = DEFAULT_CURRENCY) -> TombstoneView:
    """Turn one ZombieCostResult into the strings shown on its tombstone (REQ-ZS-36, 39)."""
    return TombstoneView(
        name=result.canonical_name,
        died_on=result.last_used_date.isoformat(),
        cost_since=format_amount(result.cost_since_last_used, currency),
        yearly_cost=format_amount(result.yearly_cost, currency),
        source_refs=tuple(result.source_refs),
    )


# --- CPI card helpers (public-cpi REQ-CPI-18, REQ-CPI-19) --------------------------------------


def cpi_source_line(alert: Alert) -> str | None:
    """Return the card's CPI source line, or None when the alert has no CPI keys.

    The index values are shown with a decimal comma (Finance Rule 4). When a CPI month differs
    from its price month the line also names the price months (DN-CPI-03).
    """
    data = alert.data
    if not has_cpi_context(data):
        return None
    try:
        start_index = format_index(Decimal(str(data["cpi_start_index"])))
        end_index = format_index(Decimal(str(data["cpi_end_index"])))
    except (KeyError, InvalidOperation, ValueError):
        return None
    line = (
        f"CPI source: INE series {data['cpi_series']} (base {data['cpi_base_year']} = 100), "
        f"{data['cpi_start_month']} = {start_index}, {data['cpi_end_month']} = {end_index}"
    )
    if cpi_uses_lag(data):
        line += (
            "; latest published month used; price months "
            f"{data['price_start_month']} and {data['price_end_month']}"
        )
    return markdown_safe(line)


def cpi_sentence_to_add(alert: Alert, explanation: Explanation) -> str | None:
    """Return the CPI sentence the card must add, or None when the text already has it.

    The comparison is deterministic data, so it is shown whatever the LLM writes; it is never
    shown twice (REQ-CPI-18, DN-CPI-12).
    """
    template = cpi_sentence_template(alert)
    if template is None:
        return None
    sentence = fill_fallback(template, alert)
    if sentence in explanation.text:
        return None
    return markdown_safe(sentence)


def attribution_lines(cpi: CpiSeries) -> list[str]:
    """Return the three footer lines of the INE attribution, escaped for markdown."""
    licence_line = (
        f"Licence: {cpi.licence} · INE series {cpi.series_code} ({cpi.series_name}) · "
        f"retrieved {cpi.retrieved_on}"
    )
    lines = [cpi.attribution, licence_line, cpi.no_endorsement]
    return [markdown_safe(line) for line in lines]


# --- CPI snapshot loading (public-cpi REQ-CPI-19, design §8) -----------------------------------

CPI_UNAVAILABLE_NOT_FOUND: str = "CPI context unavailable: snapshot not found."
CPI_UNAVAILABLE_INVALID: str = "CPI context unavailable: snapshot invalid."


def cpi_snapshot_path(config: dict[str, Any], root: Path) -> Path | None:
    """Return the snapshot path named by [cpi] (relative to `root`), or None when not set."""
    text = config.get("cpi", {}).get("snapshot_path")
    if not text:
        return None
    return Path(root) / str(text)


def read_cpi(path: Path) -> CpiSeries | None:
    """Load the CPI snapshot at `path`; None when it is missing or invalid (never raises).

    A broken snapshot must not take the page down; the snapshot tests fail loudly instead.
    """
    try:
        return load_snapshot(path)
    except SnapshotError:
        return None


def load_cpi(config: dict[str, Any], root: Path) -> CpiSeries | None:
    """Load the snapshot named by [cpi] in `config`; None when absent, missing or invalid."""
    path = cpi_snapshot_path(config, root)
    return None if path is None else read_cpi(path)


def cpi_unavailable_caption(path: Path | None) -> str:
    """Return the caption shown when no CPI snapshot could be loaded from `path`."""
    if path is None or not Path(path).is_file():
        return CPI_UNAVAILABLE_NOT_FOUND
    return CPI_UNAVAILABLE_INVALID
