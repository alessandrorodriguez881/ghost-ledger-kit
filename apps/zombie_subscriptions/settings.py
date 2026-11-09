"""Load config.toml, build the demo inputs and parse/format the sidebar text (design §7).

Also holds the pure view-model helpers of the app (demo pre-fill, guard badge, tombstone and
severity grouping). Everything here works without Streamlit so it can be tested directly.
"""

from __future__ import annotations

import tomllib
from collections.abc import Iterable, MutableMapping
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd

from ledger_kit.models import Alert
from ledger_kit.utils.money import format_amount

if TYPE_CHECKING:
    from apps.zombie_subscriptions.detectors.utils import ZombieCostResult
    from ledger_kit.explainer import Explanation

# Alert severities in display order (REQ-ZS-37).
SEVERITY_ORDER: tuple[str, ...] = ("critical", "warning", "info")

# Currency shown when the ledger has no currency column or no rows.
DEFAULT_CURRENCY: str = "EUR"

# Guard-badge labels (REQ-ZS-37). `{numbers}` is replaced by the rejected tokens.
BADGE_LLM: str = "🤖 ✓ LLM text verified by number guard"
BADGE_TEMPLATE: str = "📋 Template (no API key)"
BADGE_UNAVAILABLE: str = "📋 Template (LLM unavailable)"
BADGE_REJECTED: str = "⚠️ LLM answer rejected: invented number {numbers}"


@dataclass(frozen=True)
class DemoInputs:
    """The demo CSV and the user inputs that go with it (all keys as written in config.toml)."""

    csv_bytes: bytes
    csv_name: str
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


def demo_inputs(config: dict[str, Any], root: Path) -> DemoInputs:
    """Read the demo CSV named by [demo].csv_path (relative to `root`) and its user inputs."""
    demo = config["demo"]
    csv_path = Path(root) / demo["csv_path"]
    return DemoInputs(
        csv_bytes=csv_path.read_bytes(),
        csv_name=csv_path.name,
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
    state["source"] = ("demo", demo.csv_bytes, demo.csv_name)
    state["aliases_text"] = format_aliases_text(demo.aliases)
    state["last_used_text"] = format_dates_text(demo.last_used_dates)
    state["cancel_text"] = format_dates_text(demo.cancellation_dates)
    state["demo_loaded"] = True


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
