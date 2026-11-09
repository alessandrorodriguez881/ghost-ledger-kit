"""Reader of the committed INE CPI snapshot (series IPC290751, base 2025); stdlib only.

The snapshot is written by `scripts/fetch_ine_cpi.py` and validated here (REQ-CPI-03). The reader
performs no arithmetic on the values: it only compares months and returns the values verbatim
(REQ-CPI-05 to REQ-CPI-07). Percentages are computed by `ledger_kit.utils.money`.
"""

from __future__ import annotations

import json
import re
from bisect import bisect_right
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

DEFAULT_SNAPSHOT_PATH: Path = (
    Path(__file__).resolve().parents[2] / "data" / "public" / "ine_cpi_ipc290751.json"
)
SERIES_CODE: str = "IPC290751"
SERIES_NAME: str = "Nacional. Índice general. Índice"
BASE_YEAR: int = 2025
FIRST_SNAPSHOT_MONTH: str = "2017-01"
LICENCE: str = "CC BY 4.0"
ATTRIBUTION: str = "Elaboración propia con datos extraídos del sitio web del INE: www.ine.es"
NO_ENDORSEMENT: str = "The INE does not take part in, sponsor or support this reuse."
# The old base-2021 series: it stops in 2025-12 and must not be used.
OLD_SERIES_CODE: str = "IPC251852"

# A month this many months after the last published one is answered with the last published
# month, flagged as a fallback (DN-CPI-03); a later month gets no answer.
CPI_MAX_LAG_MONTHS: int = 1

# Top-level keys of the snapshot, in file order (REQ-CPI-02).
SNAPSHOT_KEYS: tuple[str, ...] = (
    "series_code",
    "series_name",
    "table",
    "base_year",
    "classification",
    "periodicity",
    "api_url",
    "retrieved_on",
    "licence",
    "attribution",
    "no_endorsement",
    "first_month",
    "last_month",
    "values",
)
ENTRY_KEYS: tuple[str, ...] = ("month", "value", "status")

_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_VALUE_RE = re.compile(r"^\d+\.\d{3}$")


class SnapshotError(ValueError):
    """The CPI snapshot is missing, unreadable or invalid (one-line message)."""


@dataclass(frozen=True)
class CpiPoint:
    """Answer of CpiSeries.lookup: the month asked for, the month used and its value."""

    requested: str  # "YYYY-MM" asked for
    used: str  # "YYYY-MM" answered
    value: Decimal  # three decimals, verbatim from the snapshot
    status: str
    is_fallback: bool  # used != requested


def month_key(day: date) -> str:
    """Return the 'YYYY-MM' key of a date (a datetime counts as its date)."""
    return f"{day.year:04d}-{day.month:02d}"


def _normalise_month(month: Any) -> str:
    """Return the 'YYYY-MM' key of a month string, date or datetime; ValueError otherwise."""
    if isinstance(month, datetime):
        return month_key(month.date())
    if isinstance(month, date):
        return month_key(month)
    if isinstance(month, str) and _MONTH_RE.match(month):
        return month
    raise ValueError(f"not a month: {month!r} (expected 'YYYY-MM' or a date)")


def _month_index(key: str) -> int:
    """Return a running month number for a valid 'YYYY-MM' key."""
    year, month = key.split("-")
    return int(year) * 12 + int(month) - 1


def _next_month(key: str) -> str:
    """Return the month after a valid 'YYYY-MM' key."""
    index = _month_index(key) + 1
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


@dataclass(frozen=True)
class CpiSeries:
    """An immutable monthly CPI series; `entries` is (month, value, status), oldest first."""

    entries: tuple[tuple[str, Decimal, str], ...]
    series_code: str = SERIES_CODE
    series_name: str = SERIES_NAME
    base_year: int = BASE_YEAR
    retrieved_on: str = ""
    licence: str = LICENCE
    attribution: str = ATTRIBUTION
    no_endorsement: str = NO_ENDORSEMENT
    _months: tuple[str, ...] = field(init=False, repr=False, compare=False)
    _by_month: Mapping[str, tuple[Decimal, str]] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Check the months are valid, unique and ordered, and build the lookup index."""
        months = tuple(entry[0] for entry in self.entries)
        for month in months:
            _normalise_month(month)
        if any(a >= b for a, b in zip(months, months[1:], strict=False)):
            raise ValueError("CpiSeries months must be unique and in ascending order")
        object.__setattr__(self, "_months", months)
        by_month = {month: (value, status) for month, value, status in self.entries}
        object.__setattr__(self, "_by_month", by_month)

    @classmethod
    def from_mapping(
        cls,
        values: Mapping[str, str | Decimal],
        *,
        status: str = "Definitivo",
        **meta: Any,
    ) -> CpiSeries:
        """Build a series from {month: value}; months need not be contiguous (tests, DN-CPI-04)."""
        entries = tuple(
            (_normalise_month(month), Decimal(str(value)), status)
            for month, value in sorted(values.items())
        )
        return cls(entries=entries, **meta)

    @property
    def first_month(self) -> str | None:
        """The oldest published month, or None for an empty series."""
        return self._months[0] if self._months else None

    @property
    def last_month(self) -> str | None:
        """The newest published month, or None for an empty series."""
        return self._months[-1] if self._months else None

    @property
    def months(self) -> tuple[str, ...]:
        """The published months, oldest first."""
        return self._months

    def lookup(self, month: str | date) -> CpiPoint | None:
        """Return the CPI point for a month (REQ-CPI-06); None when it cannot be answered."""
        key = _normalise_month(month)
        if not self._months or key < self._months[0]:
            return None
        last = self._months[-1]
        if key > last:
            if _month_index(key) - _month_index(last) > CPI_MAX_LAG_MONTHS:
                return None
            used = last
        else:
            used = self._months[bisect_right(self._months, key) - 1]
        value, status = self._by_month[used]
        return CpiPoint(key, used, value, status, used != key)


def _check_entries(values: Any) -> None:
    """Validate the `values` list of a snapshot (REQ-CPI-03)."""
    if not isinstance(values, list) or not values:
        raise SnapshotError("the snapshot has no values")
    previous: str | None = None
    for entry in values:
        if not isinstance(entry, dict) or set(entry) != set(ENTRY_KEYS):
            raise SnapshotError(f"entry after {previous} must have exactly {list(ENTRY_KEYS)}")
        month = entry["month"]
        if not isinstance(month, str) or not _MONTH_RE.match(month):
            raise SnapshotError(f"invalid month {month!r} after {previous}")
        if previous is not None:
            if month == previous:
                raise SnapshotError(f"repeated month {month}")
            if month < previous:
                raise SnapshotError(f"month {month} is out of order after {previous}")
            if month != _next_month(previous):
                raise SnapshotError(f"gap after {previous}: next month is {month}")
        value = entry["value"]
        if not isinstance(value, str) or not _VALUE_RE.match(value):
            raise SnapshotError(f"value at {month} does not have three decimals: {value!r}")
        if Decimal(value) <= 0:
            raise SnapshotError(f"non-positive value at {month}")
        status = entry["status"]
        if not isinstance(status, str) or not status.strip():
            raise SnapshotError(f"empty status at {month}")
        previous = month


def validate_snapshot(data: Any) -> None:
    """Raise SnapshotError unless `data` is a valid snapshot object (REQ-CPI-03)."""
    if not isinstance(data, dict):
        raise SnapshotError("the snapshot is not a JSON object")
    missing = [key for key in SNAPSHOT_KEYS if key not in data]
    if missing:
        raise SnapshotError(f"missing key {missing[0]!r}")
    extra = sorted(key for key in data if key not in SNAPSHOT_KEYS)
    if extra:
        raise SnapshotError(f"unexpected key {extra[0]!r}")
    code = data["series_code"]
    if code == OLD_SERIES_CODE:
        message = f"series {OLD_SERIES_CODE} (base 2021) stops in 2025-12; use {SERIES_CODE}"
        raise SnapshotError(message)
    if code != SERIES_CODE:
        raise SnapshotError(f"unexpected series code {code!r} (expected {SERIES_CODE!r})")
    base_year = data["base_year"]
    if isinstance(base_year, bool) or base_year != BASE_YEAR:
        raise SnapshotError(f"base year {base_year!r} is not {BASE_YEAR}")
    _check_entries(data["values"])
    first, last = data["values"][0]["month"], data["values"][-1]["month"]
    if data["first_month"] != first:
        message = f"first_month {data['first_month']!r} differs from the first entry {first}"
        raise SnapshotError(message)
    if data["last_month"] != last:
        message = f"last_month {data['last_month']!r} differs from the last entry {last}"
        raise SnapshotError(message)


def load_snapshot(path: Path = DEFAULT_SNAPSHOT_PATH) -> CpiSeries:
    """Read, validate and return the snapshot at `path`; SnapshotError naming the file otherwise."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise SnapshotError(f"cannot read {path}: file not found") from None
    except UnicodeDecodeError:
        raise SnapshotError(f"cannot read {path}: not UTF-8 text") from None
    except OSError as exc:
        raise SnapshotError(f"cannot read {path}: {exc.strerror or exc}") from None
    try:
        data = json.loads(text, parse_float=Decimal)
    except json.JSONDecodeError as exc:
        raise SnapshotError(f"cannot read {path}: invalid JSON at line {exc.lineno}") from None
    try:
        validate_snapshot(data)
        entries = tuple((e["month"], Decimal(e["value"]), e["status"]) for e in data["values"])
    except (SnapshotError, InvalidOperation) as exc:
        raise SnapshotError(f"invalid snapshot {path}: {exc}") from None
    return CpiSeries(
        entries=entries,
        series_code=data["series_code"],
        series_name=str(data["series_name"]),
        base_year=data["base_year"],
        retrieved_on=str(data["retrieved_on"]),
        licence=str(data["licence"]),
        attribution=str(data["attribution"]),
        no_endorsement=str(data["no_endorsement"]),
    )
