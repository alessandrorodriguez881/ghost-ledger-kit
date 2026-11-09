"""Constants, counterparty normalisation and ledger helpers for the zombie-subscriptions app."""

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pandas as pd

from ledger_kit.public_data import month_key
from ledger_kit.utils.money import percent_change, round_percent, round_to_cents

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


def unique_rows(rows: list[dict]) -> list[dict]:
    """Return `rows` ordered by date_key, keeping the first row of each source_ref."""
    seen: set[str] = set()
    unique: list[dict] = []
    for row in sorted(rows, key=date_key):
        if row["source_ref"] not in seen:
            seen.add(row["source_ref"])
            unique.append(row)
    return unique


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


# --- Series (design §4) ------------------------------------------------------------------------


@dataclass
class Series:
    """A recurring series of charges under one normalised key (design §4.2)."""

    rows: list[dict]  # ledger rows sorted by date_key ascending
    interval_type: str  # "weekly" | "monthly" | "quarterly" | "yearly"
    nominal_days: int
    current_amount: Decimal  # rounded median of the charges since the last price step
    price_steps: list[tuple[Decimal, Decimal]]  # [(old, new), ...] rounded medians, any direction
    step_index: int | None = None  # index in `rows` of the first charge of the new price level


def is_level(amounts: list[Decimal]) -> bool:
    """Return True when every amount lies within STABLE_AMOUNT_RATIO of the median."""
    m = median(amounts)
    return all(abs(a - m) <= STABLE_AMOUNT_RATIO * m for a in amounts)


def _within_match_ratio(amounts: list[Decimal]) -> bool:
    """Return True when every amount lies within AMOUNT_MATCH_RATIO of the median."""
    m = median(amounts)
    return all(abs(a - m) <= AMOUNT_MATCH_RATIO * m for a in amounts)


def _gap_ok(days: int, nominal: int) -> bool:
    """Return True when a gap in days equals the nominal interval within the tolerance."""
    return abs(days - nominal) <= INTERVAL_TOLERANCE_DAYS


def _make_series(
    run: list[dict],
    interval: dict,
    current_amount: Decimal,
    price_steps: list[tuple[Decimal, Decimal]],
    step_index: int | None = None,
) -> Series:
    """Build a Series for `run` (assumed date-sorted) and an interval descriptor."""
    return Series(
        rows=list(run),
        interval_type=interval["name"],
        nominal_days=interval["nominal"],
        current_amount=current_amount,
        price_steps=price_steps,
        step_index=step_index,
    )


def _segment_by_price(run: list[dict], interval: dict) -> Series | None:
    """Classify a cadence-consistent run as stable, step-change or variable; else None."""
    amounts = [Decimal(r["amount"]) for r in run]
    n = len(amounts)

    # Branch 1 - stable: the whole run is one price level.
    if is_level(amounts):
        return _make_series(run, interval, round_to_cents(median(amounts)), [])

    # A 2-row run must be a single stable level.
    if n == 2:
        return None

    # Branch 2 - exactly one split where both sides are price levels (either direction).
    splits: list[tuple[Decimal, Decimal, int]] = []
    for p in range(1, n):
        pre, post = amounts[:p], amounts[p:]
        if not (is_level(pre) and is_level(post)):
            continue
        a, b = round_to_cents(median(pre)), round_to_cents(median(post))
        if a == b:
            continue
        both_sides_big = len(pre) >= MIN_SIDE_ROWS and len(post) >= MIN_SIDE_ROWS
        final_single = len(post) == 1 and len(pre) >= interval["min"]
        first_single = len(pre) == 1 and len(post) >= interval["min"]
        plausible_step = abs(b - a) <= MAX_EDGE_STEP_RATIO * a
        edge_ok = (final_single or first_single) and plausible_step
        if both_sides_big or edge_ok:
            splits.append((a, b, p))
    if len(splits) == 1:
        a, b, p = splits[0]
        return _make_series(run, interval, b, [(a, b)], step_index=p)

    # Branch 3 - variable bill: no step, every amount within AMOUNT_MATCH_RATIO of the median.
    if _within_match_ratio(amounts):
        return _make_series(run, interval, round_to_cents(median(amounts)), [])

    return None


def longest_cadence_run(rows: list[dict], interval: dict) -> list[dict]:
    """Return the longest date-ordered subsequence whose gaps all fit nominal +/- tolerance."""
    nominal = interval["nominal"]
    best: list[dict] = []
    for start_idx, start_row in enumerate(rows):
        run = [start_row]
        for r in rows[start_idx + 1 :]:
            gap = (r["date"] - run[-1]["date"]).days
            if _gap_ok(gap, nominal):
                run.append(r)
            elif gap > nominal + INTERVAL_TOLERANCE_DAYS:
                break  # every later row is even further away
        if len(run) > len(best):
            best = run
    return best


def group_by_price_level(rows: list[dict]) -> list[list[dict]]:
    """Cluster rows into price buckets (10% of the bucket median); each bucket is date-sorted."""
    if not rows:
        return []
    by_amount = sorted(rows, key=lambda r: (Decimal(r["amount"]), date_key(r)))
    buckets: list[list[dict]] = [[by_amount[0]]]
    for r in by_amount[1:]:
        m = median([Decimal(x["amount"]) for x in buckets[-1]])
        if abs(Decimal(r["amount"]) - m) <= AMOUNT_MATCH_RATIO * m:
            buckets[-1].append(r)
        else:
            buckets.append([r])
    return [sorted(b, key=date_key) for b in buckets]


def _other_rows_in_span(series_rows: list[dict], key_rows: list[dict]) -> bool:
    """Return True when the key has rows between the series' first and last charge not in it."""
    first, last = series_rows[0]["date"], series_rows[-1]["date"]
    refs = {r["source_ref"] for r in series_rows}
    return any(first <= r["date"] <= last and r["source_ref"] not in refs for r in key_rows)


def _accept(series: Series | None, key_rows: list[dict]) -> Series | None:
    """Acceptance guard: a quarterly/yearly series may not span other rows of the same key."""
    if series is None:
        return None
    long_interval = series.interval_type in ("quarterly", "yearly")
    if long_interval and _other_rows_in_span(series.rows, key_rows):
        return None
    return series


def _closest(candidates: list[dict], expected_date: date) -> dict | None:
    """Return the candidate nearest to expected_date (ties: earlier date_key), or None."""
    return min(
        candidates,
        key=lambda r: (abs((r["date"] - expected_date).days), date_key(r)),
        default=None,
    )


def _unclaimed_rows(rows: list[dict], claimed: set[str]) -> list[dict]:
    """Return the rows whose source_ref is not yet in a series, keeping their order."""
    return [r for r in rows if r["source_ref"] not in claimed]


def _extend_once(found: list[Series], key_rows: list[dict], claimed: set[str]) -> bool:
    """Phase 2a: extend one series by one unclaimed row, forward or backward; True if changed."""
    for idx, s in enumerate(found):
        unclaimed = _unclaimed_rows(key_rows, claimed)
        nominal = s.nominal_days
        interval = INTERVALS_BY_NAME[s.interval_type]
        last_date, first_date = s.rows[-1]["date"], s.rows[0]["date"]
        forward = [r for r in unclaimed if _gap_ok((r["date"] - last_date).days, nominal)]
        backward = [r for r in unclaimed if _gap_ok((first_date - r["date"]).days, nominal)]
        for row in (
            _closest(forward, last_date + timedelta(days=nominal)),
            _closest(backward, first_date - timedelta(days=nominal)),
        ):
            if row is None:
                continue
            rows = sorted([*s.rows, row], key=date_key)
            t = _accept(_segment_by_price(rows, interval), key_rows)
            if t is not None:
                found[idx] = t
                claimed.add(row["source_ref"])
                return True
    return False


def _merge_once(found: list[Series], key_rows: list[dict]) -> list[Series] | None:
    """Phase 2b: merge two consecutive non-overlapping series; None when nothing merges."""
    for i, a in enumerate(found):
        for j in range(i + 1, len(found)):
            b = found[j]
            if a.interval_type != b.interval_type:
                continue
            earlier, later = (a, b) if a.rows[-1]["date"] < b.rows[0]["date"] else (b, a)
            if not earlier.rows[-1]["date"] < later.rows[0]["date"]:
                continue  # calendar-overlapping (E3, E4): never merge
            gap = (later.rows[0]["date"] - earlier.rows[-1]["date"]).days
            if not _gap_ok(gap, a.nominal_days):
                continue
            interval = INTERVALS_BY_NAME[a.interval_type]
            t = _accept(_segment_by_price(earlier.rows + later.rows, interval), key_rows)
            if t is not None:
                rest = [s for k, s in enumerate(found) if k not in (i, j)]
                return [*rest, t]
    return None


def find_series(rows_for_key: list[dict]) -> list[Series]:
    """Find the recurring series of one normalised key (design §4.6, three phases)."""
    key_rows = sorted(rows_for_key, key=date_key)
    claimed: set[str] = set()
    found: list[Series] = []

    # Phase 1: price-bucketed cadence runs.
    buckets = group_by_price_level(key_rows)
    for bucket in sorted(buckets, key=len, reverse=True):
        for interval in INTERVAL_TYPES:
            while True:  # a bucket may hold several parallel series (E4)
                run = longest_cadence_run(_unclaimed_rows(bucket, claimed), interval)
                if len(run) < interval["min"]:
                    break
                s = _accept(_segment_by_price(run, interval), key_rows)
                if s is None:
                    break
                found.append(s)
                claimed.update(r["source_ref"] for r in run)

    # Phase 2: extend, then merge, until nothing changes.
    while True:
        if _extend_once(found, key_rows, claimed):
            continue
        merged = _merge_once(found, key_rows)
        if merged is None:
            break
        found = merged

    # Phase 3: leftover cadence runs over all unclaimed rows.
    for interval in INTERVAL_TYPES:
        while True:
            run = longest_cadence_run(_unclaimed_rows(key_rows, claimed), interval)
            if len(run) < interval["min"]:
                break
            s = _accept(_segment_by_price(run, interval), key_rows)
            if s is None:
                break
            found.append(s)
            claimed.update(r["source_ref"] for r in run)

    return sorted(found, key=lambda s: (date_key(s.rows[0]), s.interval_type))


# --- CPI context of a price step (public-cpi design §5.2) ---------------------------------------


def cpi_context_fields(series: Series, old: Decimal, new: Decimal, cpi: Any) -> dict[str, str]:
    """Return the CPI keys of REQ-CPI-11, or {} when REQ-CPI-13 says they cannot be stated.

    `old` and `new` are the rounded medians of the step (the values the detector compares).
    The span runs from the first charge of the old price (`rows[0]`) to the first charge of the
    new price (`rows[step_index]`); both are cited rows of the alert. Decoration only: this
    never decides whether an alert fires.
    """
    lookup = getattr(cpi, "lookup", None)
    code = getattr(cpi, "series_code", None)
    base_year = getattr(cpi, "base_year", None)
    if not callable(lookup) or code is None or base_year is None or series.step_index is None:
        return {}
    price_start = month_key(series.rows[0]["date"])
    price_end = month_key(series.rows[series.step_index]["date"])
    if price_start == price_end:
        return {}  # a zero-length span says nothing
    start, end = lookup(price_start), lookup(price_end)
    if start is None or end is None or start.used == end.used:
        return {}  # out of range, or a fallback collapsed the span
    try:
        price_change = round_percent(percent_change(old, new))
        cpi_change = round_percent(percent_change(start.value, end.value))
    except ValueError:
        return {}
    return {
        "price_start_month": price_start,
        "price_end_month": price_end,
        "price_change_percent": str(price_change),
        "cpi_series": str(code),
        "cpi_base_year": str(base_year),
        "cpi_start_month": start.used,
        "cpi_end_month": end.used,
        "cpi_start_index": str(start.value),
        "cpi_end_index": str(end.value),
        "cpi_change_percent": str(cpi_change),
    }


# --- Active series and service cost (design §3.1, §4.7) ----------------------------------------

KeyGroups = list[tuple[str, list[dict]]]  # [(normalised_key, rows)] of one service


def is_active(series: Series, max_date: date) -> bool:
    """Return True when the last charge is within nominal + tolerance days of max_date."""
    last_date = series.rows[-1]["date"]
    return (max_date - last_date).days <= series.nominal_days + INTERVAL_TOLERANCE_DAYS


def service_yearly_cost(key_groups: KeyGroups, max_date: date | None) -> Decimal:
    """Sum the yearly cost of the active series of every key of one service."""
    if max_date is None:
        return Decimal("0.00")
    total = Decimal("0.00")
    for _key, rows in key_groups:
        for series in find_series(rows):
            if is_active(series, max_date):
                total += round_to_cents(series.current_amount * ppy_for(series.interval_type))
    return round_to_cents(total)


# --- Zombie cost view (design §6) --------------------------------------------------------------


@dataclass
class ZombieCostResult:
    """Cost of one service since its last-used date (a view computation, not an alert)."""

    canonical_name: str
    last_used_date: date
    cost_since_last_used: Decimal  # sum of the actual amounts of the cited rows
    source_refs: list[str]  # source_refs of every charge after last_used_date
    yearly_cost: Decimal  # sum of the yearly costs of the service's active series


def compute_zombie_cost(
    ledger: pd.DataFrame,
    last_used_dates: dict[str, date] | None,
    *,
    aliases: dict[str, list[str]] | None = None,
) -> list[ZombieCostResult]:
    """Return one ZombieCostResult per service named in last_used_dates (REQ-ZS-27..30)."""
    if not last_used_dates:
        return []
    max_date = ledger_max_date(ledger)
    by_canonical = group_by_canonical(ledger, aliases) if not ledger.empty else {}
    results: list[ZombieCostResult] = []
    for canonical, last_used in last_used_dates.items():  # keys are already normalised
        key_groups = by_canonical.get(canonical, [])
        post = unique_rows([r for _key, rows in key_groups for r in rows if r["date"] > last_used])
        cost = round_to_cents(sum((Decimal(r["amount"]) for r in post), Decimal("0.00")))
        results.append(
            ZombieCostResult(
                canonical_name=canonical,
                last_used_date=last_used,
                cost_since_last_used=cost,
                source_refs=sorted_source_refs(post),
                yearly_cost=service_yearly_cost(key_groups, max_date),
            )
        )
    return results
