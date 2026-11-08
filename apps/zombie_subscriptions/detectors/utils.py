"""Constants, counterparty normalisation and ledger helpers for the zombie-subscriptions app."""

import re
from collections import defaultdict
from datetime import date
from decimal import Decimal

import pandas as pd

# --- Constants (design §2); every threshold that influences an alert lives here ----------------

# Nominal interval lengths in days.
WEEKLY_NOMINAL_DAYS: int = 7
MONTHLY_NOMINAL_DAYS: int = 30
QUARTERLY_NOMINAL_DAYS: int = 91
YEARLY_NOMINAL_DAYS: int = 365

# Tolerance in days applied to the gap between two charges, for every interval type.
INTERVAL_TOLERANCE_DAYS: int = 3

# Minimum number of charges that qualifies as a recurring series.
MIN_OCCURRENCES_WEEKLY: int = 4
MIN_OCCURRENCES_MONTHLY: int = 3
MIN_OCCURRENCES_QUARTERLY: int = 2
MIN_OCCURRENCES_YEARLY: int = 2

# A "price level": all amounts lie within 2% of their median.
STABLE_AMOUNT_RATIO: Decimal = Decimal("0.02")
# Smallest upward price step (5%) that raises a price-increase alert.
PRICE_INCREASE_MIN_RATIO: Decimal = Decimal("0.05")
# A single-row side at either edge counts as a new price only within +/-50%.
MAX_EDGE_STEP_RATIO: Decimal = Decimal("0.50")
# Rows needed on each side of a recorded price step (edge exception above).
MIN_SIDE_ROWS: int = 2

# Variable bills, parallel series and duplicate subscriptions match within 10% of the median.
AMOUNT_MATCH_RATIO: Decimal = Decimal("0.10")

# Free-trial detection: a token charge of 0.01 to 1.00 EUR up to 35 days before the first charge.
FREE_TRIAL_MIN_TOKEN_AMOUNT: Decimal = Decimal("0.01")
FREE_TRIAL_MAX_TOKEN_AMOUNT: Decimal = Decimal("1.00")
TRIAL_MAX_DAYS_BEFORE_FIRST_CHARGE: int = 35

# Periods per year used to compute yearly_cost.
PERIODS_PER_YEAR_WEEKLY: int = 52
PERIODS_PER_YEAR_MONTHLY: int = 12
PERIODS_PER_YEAR_QUARTERLY: int = 4
PERIODS_PER_YEAR_YEARLY: int = 1

# Interval descriptor table; the order is the Phase 1 / Phase 3 priority of find_series.
INTERVAL_TYPES: list[dict] = [
    {
        "name": "weekly",
        "nominal": WEEKLY_NOMINAL_DAYS,
        "min": MIN_OCCURRENCES_WEEKLY,
        "ppy": PERIODS_PER_YEAR_WEEKLY,
    },
    {
        "name": "monthly",
        "nominal": MONTHLY_NOMINAL_DAYS,
        "min": MIN_OCCURRENCES_MONTHLY,
        "ppy": PERIODS_PER_YEAR_MONTHLY,
    },
    {
        "name": "quarterly",
        "nominal": QUARTERLY_NOMINAL_DAYS,
        "min": MIN_OCCURRENCES_QUARTERLY,
        "ppy": PERIODS_PER_YEAR_QUARTERLY,
    },
    {
        "name": "yearly",
        "nominal": YEARLY_NOMINAL_DAYS,
        "min": MIN_OCCURRENCES_YEARLY,
        "ppy": PERIODS_PER_YEAR_YEARLY,
    },
]
INTERVALS_BY_NAME: dict[str, dict] = {i["name"]: i for i in INTERVAL_TYPES}


# --- Counterparty normalisation (design §3) ----------------------------------------------------


def normalise_counterparty(raw: str) -> str:
    """Return the normalised counterparty key used for grouping (REQ-ZS-05)."""
    tokens = raw.strip().upper().split()

    def clean_token(token: str) -> str:
        return re.sub(r"[^A-Z ]", "", token).strip()

    digit_free = [clean_token(t) for t in tokens if not re.search(r"\d", t)]
    digit_free = [t for t in digit_free if t]
    if digit_free:
        return " ".join(digit_free)
    # Every token had a digit: fall back to cleaning the full token list.
    return " ".join(t for t in (clean_token(t) for t in tokens) if t)


def resolve_alias(key: str, aliases: dict[str, list[str]] | None) -> str:
    """Return the canonical service name of a normalised key, or the key itself."""
    if not aliases:
        return key
    for canonical, keys in aliases.items():
        if key in keys:
            return canonical
    return key


def normalise_alias_map(
    raw_aliases: dict[str, list[str]] | None,
) -> dict[str, list[str]] | None:
    """Normalise the canonical names and the member keys of an alias map."""
    if not raw_aliases:
        return raw_aliases
    return {
        normalise_counterparty(canonical): [normalise_counterparty(k) for k in keys]
        for canonical, keys in raw_aliases.items()
    }


def normalise_date_map(raw_map: dict[str, date] | None) -> dict[str, date] | None:
    """Normalise the service-name keys of a {service: date} map."""
    if not raw_map:
        return raw_map
    return {normalise_counterparty(k): v for k, v in raw_map.items()}


# --- Ledger helpers (design §3.1) --------------------------------------------------------------


def date_key(row: dict) -> tuple[date, int]:
    """Return the sort key (date, source_row); never sort by source_ref text."""
    return (row["date"], row["source_row"])


def sorted_source_refs(rows: list[dict]) -> list[str]:
    """Return the source_ref values of `rows` ordered by date_key, without duplicates."""
    seen: set[str] = set()
    refs: list[str] = []
    for row in sorted(rows, key=date_key):
        if row["source_ref"] not in seen:
            seen.add(row["source_ref"])
            refs.append(row["source_ref"])
    return refs


def group_by_normalised_key(ledger: pd.DataFrame) -> list[tuple[str, list[dict]]]:
    """Return [(normalised_key, rows)] ordered by key, rows ordered by date_key."""
    if ledger.empty:
        return []
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in ledger.to_dict("records"):
        groups[normalise_counterparty(row["counterparty"])].append(row)
    return [(key, sorted(rows, key=date_key)) for key, rows in sorted(groups.items())]


def group_by_canonical(
    ledger: pd.DataFrame, aliases: dict[str, list[str]] | None
) -> dict[str, list[tuple[str, list[dict]]]]:
    """Return {canonical_name: [(normalised_key, rows), ...]} for the keys of each service."""
    out: dict[str, list[tuple[str, list[dict]]]] = defaultdict(list)
    for key, rows in group_by_normalised_key(ledger):
        out[resolve_alias(key, aliases)].append((key, rows))
    return dict(out)


def ppy_for(interval_type: str) -> int:
    """Return the periods per year of an interval type name."""
    return INTERVALS_BY_NAME[interval_type]["ppy"]


def ledger_max_date(ledger: pd.DataFrame) -> date | None:
    """Return the latest date in the ledger, or None when it is empty (never the clock)."""
    return None if ledger.empty else max(ledger["date"])


def median(values: list[Decimal]) -> Decimal:
    """Return the median at full Decimal precision (mean of the middle pair when even)."""
    if not values:
        raise ValueError("median() requires at least one value")
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / Decimal(2)
