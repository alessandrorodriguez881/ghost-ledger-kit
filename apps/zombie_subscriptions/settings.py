"""Load config.toml, build the demo inputs and parse/format the sidebar text (design §7).

Everything here works without Streamlit so it can be tested directly.
"""

import tomllib
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any


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
