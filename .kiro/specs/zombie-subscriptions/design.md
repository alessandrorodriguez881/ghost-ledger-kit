# zombie-subscriptions — Design

## Overview

This document translates the requirements in `requirements.md` into concrete module boundaries,
function signatures, algorithms, data flows, and test architecture. Implementation tasks (in
`tasks.md`) will reference sections of this document.

The app is a pure consumer of `ledger_kit`. It adds no new primitives to the shared library; every
`Alert`, `Transaction`, and `DetectorResult` it produces is of the same types defined in
`ledger_kit/models.py`.

---

## 1 — Module map

```
apps/zombie_subscriptions/
├── __init__.py
├── app.py                       # Streamlit entry point (path bootstrap + render loop)
├── config.toml                  # aliases, [demo] section
├── settings.py                  # load config.toml, demo inputs, sidebar text parse/format
├── explain_support.py           # TEMPLATES (fallback template per detector), HallucinatingStubClient
└── detectors/
    ├── __init__.py              # auto_discover("apps.zombie_subscriptions.detectors")
    ├── utils.py                 # normalise_counterparty, resolve_alias, grouping helpers,
    │                            # find_series, compute_zombie_cost, ZombieCostResult, CONSTANTS
    ├── recurring_charge.py      # detect_recurring_charges  → "zs.recurring_charge"
    ├── price_increase.py        # detect_price_increases    → "zs.price_increase"
    ├── duplicate_subscription.py# detect_duplicate_subscriptions → "zs.duplicate_subscription"
    ├── free_trial_to_paid.py    # detect_free_trial_to_paid → "zs.free_trial_to_paid"
    └── charges_after_cancellation.py # detect_charges_after_cancellation → "zs.charges_after_cancellation"
```

There is deliberately **no** `apps/zombie_subscriptions/requirements.txt`. Streamlit Community Cloud
looks for a requirements file next to the entry point first; an app-level file would hide the
root-level `requirements.txt` that pins the real dependencies (§8).

Shared library dependencies used: `ledger_kit.models`, `ledger_kit.detectors` (registry),
`ledger_kit.utils.money`, `ledger_kit.explainer`.

---

## 2 — Constants

All numeric thresholds live in `detectors/utils.py` and are imported by each detector module.
No threshold appears in `config.toml`.

```python
from decimal import Decimal

# Interval nominal lengths (days)
WEEKLY_NOMINAL_DAYS: int = 7
MONTHLY_NOMINAL_DAYS: int = 30
QUARTERLY_NOMINAL_DAYS: int = 91
YEARLY_NOMINAL_DAYS: int = 365

# Tolerance applied to every interval type
INTERVAL_TOLERANCE_DAYS: int = 3

# Minimum charges to qualify as a recurring series
MIN_OCCURRENCES_WEEKLY: int = 4
MIN_OCCURRENCES_MONTHLY: int = 3
MIN_OCCURRENCES_QUARTERLY: int = 2
MIN_OCCURRENCES_YEARLY: int = 2

# Price levels and steps
STABLE_AMOUNT_RATIO: Decimal = Decimal("0.02")         # a "price level": all amounts within 2% of their median
PRICE_INCREASE_MIN_RATIO: Decimal = Decimal("0.05")    # 5%: smallest upward step that raises an alert
MAX_EDGE_STEP_RATIO: Decimal = Decimal("0.50")         # a 1-row side at either edge counts as a new price only within +/-50%
MIN_SIDE_ROWS: int = 2                                 # rows needed on each side of a recorded step (edge exception above)

# Variable bills / parallel-series / duplicate-subscription matching
AMOUNT_MATCH_RATIO: Decimal = Decimal("0.10")          # 10%

# Free-trial detection
FREE_TRIAL_MIN_TOKEN_AMOUNT: Decimal = Decimal("0.01")
FREE_TRIAL_MAX_TOKEN_AMOUNT: Decimal = Decimal("1.00")
TRIAL_MAX_DAYS_BEFORE_FIRST_CHARGE: int = 35

# Periods per year for yearly_cost computation
PERIODS_PER_YEAR_WEEKLY: int = 52
PERIODS_PER_YEAR_MONTHLY: int = 12
PERIODS_PER_YEAR_QUARTERLY: int = 4
PERIODS_PER_YEAR_YEARLY: int = 1

# Interval descriptor table (used by find_series and detectors); order = Phase 1/3 priority
INTERVAL_TYPES: list[dict] = [
    {"name": "weekly",    "nominal": WEEKLY_NOMINAL_DAYS,    "min": MIN_OCCURRENCES_WEEKLY,    "ppy": PERIODS_PER_YEAR_WEEKLY},
    {"name": "monthly",   "nominal": MONTHLY_NOMINAL_DAYS,   "min": MIN_OCCURRENCES_MONTHLY,   "ppy": PERIODS_PER_YEAR_MONTHLY},
    {"name": "quarterly", "nominal": QUARTERLY_NOMINAL_DAYS, "min": MIN_OCCURRENCES_QUARTERLY, "ppy": PERIODS_PER_YEAR_QUARTERLY},
    {"name": "yearly",    "nominal": YEARLY_NOMINAL_DAYS,    "min": MIN_OCCURRENCES_YEARLY,    "ppy": PERIODS_PER_YEAR_YEARLY},
]
INTERVALS_BY_NAME: dict[str, dict] = {i["name"]: i for i in INTERVAL_TYPES}
```

---

## 3 — Counterparty normalisation (`detectors/utils.py`)

```python
import re

def normalise_counterparty(raw: str) -> str:
    """Return the normalised counterparty key for grouping (REQ-ZS-05).

    Steps:
    1. Strip and uppercase.
    2. Split on whitespace.
    3. Drop tokens that contain any digit.
    4. Remove non-ASCII-letter characters from remaining tokens.
    5. Rejoin with single spaces.
    6. If the result is empty (all tokens had digits), fall back to step 4
       applied to the full original token list (without step 3 filtering).
    """
    stripped = raw.strip().upper()
    tokens = stripped.split()

    def clean_token(t: str) -> str:
        return re.sub(r"[^A-Z ]", "", t).strip()

    digit_free = [clean_token(t) for t in tokens if not re.search(r"\d", t)]
    digit_free = [t for t in digit_free if t]
    if digit_free:
        return " ".join(digit_free)
    # All tokens had digits — fall back without the digit-drop step
    fallback = " ".join(t for t in (clean_token(t) for t in tokens) if t)
    return fallback


def resolve_alias(key: str, aliases: dict[str, list[str]] | None) -> str:
    """Return the canonical name for a normalised key, or the key itself.

    Looks up `key` in the values of `aliases`. The alias dict is assumed to have
    already been normalised via normalise_alias_map() — see below.
    """
    if not aliases:
        return key
    for canonical, keys in aliases.items():
        if key in keys:
            return canonical
    return key


def normalise_alias_map(
    raw_aliases: dict[str, list[str]] | None,
) -> dict[str, list[str]] | None:
    """Normalise all keys and values in the alias map using normalise_counterparty.

    Call this once at startup (when reading config.toml or sidebar input) so that
    'streaming', 'Streaming', and 'STREAMING' all produce the same canonical key 'STREAMING',
    and 'STREAMFLIX.COM' and 'Streamflix.com' both normalise to 'STREAMFLIXCOM'.

    The canonical name (dict key) is also normalised — user-entered names like
    'Streaming' are stored as 'STREAMING'.
    """
    if not raw_aliases:
        return raw_aliases
    return {
        normalise_counterparty(canonical): [normalise_counterparty(k) for k in keys]
        for canonical, keys in raw_aliases.items()
    }


def normalise_date_map(
    raw_map: dict[str, date] | None,
) -> dict[str, date] | None:
    """Normalise the keys of a {service_name: date} dict using normalise_counterparty.

    Used for cancellation_dates and last_used_dates from the sidebar and config.toml,
    so 'BeatStream', 'BEATSTREAM', and 'beatstream' all map to the same 'BEATSTREAM' key.
    """
    if not raw_map:
        return raw_map
    return {normalise_counterparty(k): v for k, v in raw_map.items()}
```

### 3.1 Ledger helpers (`detectors/utils.py`)

Every helper that the pseudocode in §4–§6 uses is defined here. Ledger rows are plain `dict`s
(`ledger.to_dict("records")`) with at least the keys `date` (`datetime.date`), `amount`
(`Decimal`), `counterparty`, `source_ref`, `source_file`, `source_row` (`int`).

```python
def date_key(row: dict) -> tuple[date, int]:
    """Sort key: (date, source_row). Never sort by source_ref text ('f.csv:10' < 'f.csv:9')."""
    return (row["date"], row["source_row"])


def sorted_source_refs(rows: list[dict]) -> list[str]:
    """source_ref values of `rows` ordered by date_key, duplicates removed (first one kept)."""
    seen: set[str] = set()
    refs: list[str] = []
    for r in sorted(rows, key=date_key):
        if r["source_ref"] not in seen:
            seen.add(r["source_ref"])
            refs.append(r["source_ref"])
    return refs


def group_by_normalised_key(ledger: pd.DataFrame) -> list[tuple[str, list[dict]]]:
    """Return [(normalised_key, rows)] ordered by key; rows ordered by date_key. Empty ledger → []."""
    if ledger.empty:
        return []
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in ledger.to_dict("records"):
        groups[normalise_counterparty(row["counterparty"])].append(row)
    return [(k, sorted(rows, key=date_key)) for k, rows in sorted(groups.items())]


def group_by_canonical(
    ledger: pd.DataFrame, aliases: dict[str, list[str]] | None
) -> dict[str, list[tuple[str, list[dict]]]]:
    """Return {canonical_name: [(normalised_key, rows), ...]}.

    Series are still found per normalised key (REQ-ZS-07); this only collects the keys that
    belong to one service, so a service with two aliased keys is processed once.
    """
    out: dict[str, list[tuple[str, list[dict]]]] = defaultdict(list)
    for key, rows in group_by_normalised_key(ledger):
        out[resolve_alias(key, aliases)].append((key, rows))
    return dict(out)


def ppy_for(interval_type: str) -> int:
    """Periods per year for an interval type name."""
    return INTERVALS_BY_NAME[interval_type]["ppy"]


def ledger_max_date(ledger: pd.DataFrame) -> date | None:
    """Latest `date` in the ledger, or None for an empty ledger. Never reads the clock."""
    return None if ledger.empty else max(ledger["date"])


def service_yearly_cost(
    key_groups: list[tuple[str, list[dict]]], max_date: date | None
) -> Decimal:
    """Sum of round_to_cents(current_amount × ppy) over the ACTIVE series of every key of a service."""
    if max_date is None:
        return Decimal("0.00")
    total = Decimal("0.00")
    for _key, rows in key_groups:
        for s in find_series(rows):
            if is_active(s, max_date):
                total += round_to_cents(s.current_amount * ppy_for(s.interval_type))
    return round_to_cents(total)
```

`median(values: list[Decimal]) -> Decimal` is the usual median (mean of the two middle values for
an even count) at full `Decimal` precision. Rounding to cents happens only when a value is stored
in a `Series` or an `Alert`.

---

## 4 — OD-ZS-03: Series algorithm (`detectors/utils.py → find_series`)

### 4.1 Problem statement

A single normalised key may have:
- A **stable series**: all charges at the same price (or near-same) at a regular cadence.
- A **step-change series**: charges at one price level, then a sustained shift to a new level.
- **Parallel series**: two simultaneous subscriptions billed under the same key (different prices
  like E3, or same price like E4).
- **Noise**: supermarket visits, one-off purchases — irregular dates and/or highly varying amounts,
  including *regular dates with varying amounts* (weekly shopping, E7/E7b).

The algorithm must distinguish all four cases and must never turn ordinary shopping into a
subscription. It is O(n²) per key (n ≤ ~1000 rows in practice).

### 4.2 Data structures

```python
@dataclass
class Series:
    rows: list[dict]           # ledger rows (dicts) sorted by date_key ascending
    interval_type: str         # "weekly" | "monthly" | "quarterly" | "yearly"
    nominal_days: int
    current_amount: Decimal    # rounded median of the charges since the last price step
    price_steps: list[tuple[Decimal, Decimal]]  # [(old, new), ...] rounded medians, any direction
```

`price_steps` records every step (up or down). `detect_price_increases` only fires for upward
steps whose ratio, computed from the stored rounded medians, is at least `PRICE_INCREASE_MIN_RATIO`.

### 4.3 `_segment_by_price(run, interval) -> Series | None`

Decides whether a cadence-consistent run is a stable series, a step-change series, or a variable
bill (returns a `Series`), or is not a subscription (returns `None`).

A **price level** is a list of amounts that all lie within `STABLE_AMOUNT_RATIO` (2%) of their own
median:

```
def is_level(amounts):
    m = median(amounts)
    return all(abs(a - m) / m <= STABLE_AMOUNT_RATIO for a in amounts)
```

```
def _segment_by_price(run, interval):
    amounts = [Decimal(r["amount"]) for r in run]
    n = len(amounts)

    # Branch 1 — stable: the whole run is one price level
    if is_level(amounts):
        return Series(run, interval, current_amount=round_to_cents(median(amounts)), price_steps=[])

    # A 2-row run must be a single stable level (quarterly / yearly minimum is 2 rows)
    if n == 2:
        return None

    # Branch 2 — exactly one split where both sides are price levels (step in either direction)
    splits = []
    for p in range(1, n):
        pre, post = amounts[:p], amounts[p:]
        if not (is_level(pre) and is_level(post)):
            continue
        a, b = round_to_cents(median(pre)), round_to_cents(median(post))   # step uses ROUNDED medians
        if a == b:
            continue
        step = (b - a) / a
        both_sides_big = len(pre) >= MIN_SIDE_ROWS and len(post) >= MIN_SIDE_ROWS
        # Edge exception: one single-row side at either end of the run, when the other side
        # alone already satisfies the interval minimum and the step is plausible (|step| <= 50%).
        final_single = len(post) == 1 and len(pre) >= interval["min"]
        first_single = len(pre) == 1 and len(post) >= interval["min"]
        edge_ok = (final_single or first_single) and abs(step) <= MAX_EDGE_STEP_RATIO
        if both_sides_big or edge_ok:
            splits.append((a, b))
    if len(splits) == 1:
        a, b = splits[0]
        return Series(run, interval, current_amount=b, price_steps=[(a, b)])

    # Branch 3 — variable bill: no step, but every amount within AMOUNT_MATCH_RATIO of the median
    # (amended by REQ-DF-10: only for the intervals of VARIABLE_BILL_INTERVALS; the run is flagged
    # variable=True and _accept rejects it when the key has a foreign row in its span, REQ-DF-11)
    m = median(amounts)
    if all(abs(x - m) / m <= AMOUNT_MATCH_RATIO for x in amounts):
        return Series(run, interval, current_amount=round_to_cents(m), price_steps=[])

    return None
```

> **Amended by `detector-fixes` (REQ-DF-10 to REQ-DF-14, design `detector-fixes` §3; committed in
> `989789b`).** Branch 3 is reached only when `interval["name"] in VARIABLE_BILL_INTERVALS`
> (`("monthly", "quarterly", "yearly")`), so a weekly run is a stable or step-change series or
> nothing. `Series` has a field `variable: bool = False`, true for every run accepted by branch 3
> (including an ambiguous split, which records no step and has no other way in). `_accept` rejects
> a series with `variable` true, or with a quarterly or yearly interval, when the key has a foreign
> row between the first and last charge. The sketch above is the original; the code is the
> authority.

Notes:

- Zero or two-or-more valid splits fall through to Branch 3: an ambiguous step is never recorded.
- The final-single exception keeps E1 (5 × 12.99 then 15.99) and the first-single exception keeps
  an early step (one old charge, then five new ones) findable by backward extension (§4.6 Phase 2).
  Both are bounded by ±50%, so `12.99 × 4` followed by a stray `4.99` (−62%) or a `0.49` trial charge
  followed by `14.99 × 3` is never read as a new price.
- A 4% step with 5 + 1 rows is recorded as a step (the lone row is more than 2% from the median) but
  never fires: `detect_price_increases` requires 5%.

### 4.4 `longest_cadence_run(rows, interval) -> list[dict]`

`rows` must be date-sorted (callers guarantee it).

```
def longest_cadence_run(rows, interval):
    """Return the longest subsequence whose consecutive gaps all fall within
    nominal ± INTERVAL_TOLERANCE_DAYS. Rows that do not fit are skipped, not fatal."""
    best = []
    for start_idx, start_row in enumerate(rows):
        run = [start_row]
        for r in rows[start_idx + 1:]:
            gap = (r["date"] - run[-1]["date"]).days
            if abs(gap - interval["nominal"]) <= INTERVAL_TOLERANCE_DAYS:
                run.append(r)
            elif gap > interval["nominal"] + INTERVAL_TOLERANCE_DAYS:
                break   # every later row is even further away
        if len(run) > len(best):
            best = run
    return best
```

The first-longest run wins ties (strict `>`). The earliest matching row is taken greedily.

### 4.5 `group_by_price_level(rows) -> list[list[dict]]`

Clusters rows into price buckets: sort by amount, start a new bucket whenever the next amount is
more than `AMOUNT_MATCH_RATIO` away from the median of the current bucket. **Every bucket is
returned sorted by `date_key`**, because `longest_cadence_run` needs date order.

```python
def group_by_price_level(rows: list[dict]) -> list[list[dict]]:
    if not rows:
        return []
    by_amount = sorted(rows, key=lambda r: (Decimal(r["amount"]), date_key(r)))
    buckets: list[list[dict]] = [[by_amount[0]]]
    for r in by_amount[1:]:
        m = median([Decimal(x["amount"]) for x in buckets[-1]])
        if abs(Decimal(r["amount"]) - m) / m <= AMOUNT_MATCH_RATIO:
            buckets[-1].append(r)
        else:
            buckets.append([r])
    return [sorted(b, key=date_key) for b in buckets]
```

### 4.6 `find_series(rows_for_key) -> list[Series]`

Phases:

```
Phase 1 — per price bucket: cadence runs, segmented by price (stable, parallel, step inside a bucket)
Phase 2 — extend each series forward and backward with unclaimed rows, then merge consecutive series
Phase 3 — leftover cadence runs over all unclaimed rows
```

Shared acceptance guard. A candidate series is only kept if `_accept` returns it:

```
def _other_rows_in_span(series_rows, key_rows):
    first, last = series_rows[0]["date"], series_rows[-1]["date"]
    refs = {r["source_ref"] for r in series_rows}
    return any(first <= r["date"] <= last and r["source_ref"] not in refs for r in key_rows)

def _accept(series, key_rows):
    if series is None:
        return None
    # A quarterly or yearly series needs only 2 rows, so on its own it would turn two purchases
    # 91 or 365 days apart into a subscription. Require that the key has no other debit rows
    # between the first and the last charge of the series.
    if series.interval_type in ("quarterly", "yearly") and _other_rows_in_span(series.rows, key_rows):
        return None
    return series
```

```
def find_series(rows_for_key):
    key_rows = sorted(rows_for_key, key=date_key)
    claimed = set()                 # source_refs already in a Series
    found = []

    # ───────── Phase 1: price-bucketed runs ─────────
    buckets = group_by_price_level(key_rows)          # each bucket is date-sorted
    for bucket in sorted(buckets, key=len, reverse=True):   # stable: ties keep amount order
        for interval in INTERVAL_TYPES:
            while True:                                # a bucket may hold several parallel series (E4)
                unclaimed_bucket = sorted(
                    (r for r in bucket if r["source_ref"] not in claimed), key=date_key)
                run = longest_cadence_run(unclaimed_bucket, interval)
                if len(run) < interval["min"]:
                    break
                s = _accept(_segment_by_price(run, interval), key_rows)
                if s is None:
                    break
                found.append(s)
                claimed.update(r["source_ref"] for r in run)

    # ───────── Phase 2: extend, then merge ─────────
    changed = True
    while changed:
        changed = False
        # 2a — extend one series by one unclaimed row, forward or backward
        for s in found:
            unclaimed = [r for r in key_rows if r["source_ref"] not in claimed]
            nominal = s.nominal_days
            interval = INTERVALS_BY_NAME[s.interval_type]
            forward = [r for r in unclaimed
                       if abs((r["date"] - s.rows[-1]["date"]).days - nominal) <= INTERVAL_TOLERANCE_DAYS]
            backward = [r for r in unclaimed
                        if abs((s.rows[0]["date"] - r["date"]).days - nominal) <= INTERVAL_TOLERANCE_DAYS]
            for row in (
                _closest(forward, s.rows[-1]["date"] + timedelta(days=nominal)),
                _closest(backward, s.rows[0]["date"] - timedelta(days=nominal)),
            ):
                if row is None:
                    continue
                rows = sorted(s.rows + [row], key=date_key)
                t = _accept(_segment_by_price(rows, interval), key_rows)   # re-segment the whole series
                if t is not None:
                    found[found.index(s)] = t
                    claimed.add(row["source_ref"])
                    changed = True
                    break
            if changed:
                break
        if changed:
            continue
        # 2b — merge two consecutive, non-overlapping series of the same key and interval
        for i, a in enumerate(found):
            for b in found[i + 1:]:
                if a.interval_type != b.interval_type:
                    continue
                earlier, later = (a, b) if a.rows[-1]["date"] < b.rows[0]["date"] else (b, a)
                if not earlier.rows[-1]["date"] < later.rows[0]["date"]:
                    continue                           # calendar-overlapping (E3, E4): never merge
                gap = (later.rows[0]["date"] - earlier.rows[-1]["date"]).days
                if abs(gap - a.nominal_days) > INTERVAL_TOLERANCE_DAYS:
                    continue
                t = _accept(_segment_by_price(earlier.rows + later.rows,
                                              INTERVALS_BY_NAME[a.interval_type]), key_rows)
                if t is not None:
                    found.remove(a); found.remove(b); found.append(t)
                    changed = True
                    break
            if changed:
                break

    # ───────── Phase 3: leftovers ─────────
    for interval in INTERVAL_TYPES:
        while True:
            unclaimed = [r for r in key_rows if r["source_ref"] not in claimed]
            run = longest_cadence_run(unclaimed, interval)
            if len(run) < interval["min"]:
                break
            s = _accept(_segment_by_price(run, interval), key_rows)
            if s is None:
                break
            found.append(s)
            claimed.update(r["source_ref"] for r in run)

    return sorted(found, key=lambda s: (date_key(s.rows[0]), s.interval_type))


def _closest(candidates, expected_date):
    """Candidate whose date is nearest to expected_date (ties: earlier date_key); None if empty."""
    return min(candidates, key=lambda r: (abs((r["date"] - expected_date).days), date_key(r)),
               default=None)
```

Termination: every change in Phase 2 either claims one more row or reduces the number of series.

**Why three phases**

- Phase 1 alone leaves a lone 15.99 (E1) or a lone early 9.99 outside any series, and leaves a step
  across a bucket boundary (E2) as two separate stable series. Phase 2 repairs both: it extends a
  series with a row that arrives exactly one nominal interval after its last charge (or before its
  first charge) and re-runs `_segment_by_price` on the whole series, so the step is recorded; it
  merges consecutive series the same way.
- Backward extension is what finds an early step. With a step above 10% at the 1st or 2nd of 6
  charges, the first one or two rows sit in a different price bucket that is below the interval
  minimum, so Phase 1 never sees them.
- E4 (same-price parallel series) needs no special deinterleaving: `longest_cadence_run` skips the
  rows that do not fit, so the first pass returns one account's rows and the `while` loop then finds
  the other account's rows.
- Phase 3 catches rows that never shared a bucket with enough rows but form a cadence run together
  (variable bills spread over several buckets).

### 4.7 Active series

```python
def is_active(series: Series, max_date: date) -> bool:
    """True if the last charge is within one nominal interval + tolerance of max_date."""
    last_date = series.rows[-1]["date"]  # rows are sorted
    return (max_date - last_date).days <= series.nominal_days + INTERVAL_TOLERANCE_DAYS
```

`max_date` is always `ledger_max_date(ledger)` — never `date.today()`.

### 4.8 Walk-through: acceptance examples E1–E7b on the final algorithm

Each walk-through is a required Tier 1 test. Dates are illustrative monthly steps (~30 days).

---

**E1** — Step change: 5 × 12.99 then 1 × 15.99 for key `"STREAMFLEX INTL"`.

```
amounts: [12.99, 12.99, 12.99, 12.99, 12.99, 15.99]    gaps: 30 each
```

*Phase 1*: buckets A = [12.99 × 5], B = [15.99] (+23% apart). Bucket A, monthly: run of 5, all one
level → stable series S (`current_amount=12.99`). Bucket B: run of 1 < 3 → nothing.

*Phase 2a*: unclaimed = [15.99]; it is 30 days after S's last charge → forward candidate.
`_segment_by_price([12.99 × 5, 15.99])`: not one level (15.99 is 23% from the median); n = 6; the
only split with two levels is p = 5 (pre 5 rows, post 1 row). Final-single exception: pre has 5 ≥ 3
rows and the step is +23.1% ≤ 50% → one split → Series with `price_steps=[(12.99, 15.99)]`,
`current_amount=15.99`.

*Result*: one series, six rows. `yearly_cost = round_to_cents(15.99 × 12) = 191.88`.
`detect_price_increases`: ratio 3.00 / 12.99 ≈ 0.231 ≥ 0.05 → one alert: old 12.99, new 15.99,
`extra = round_to_cents(3.00 × 12) = 36.00`. ✓

---

**E2** — Step change: 3 × 9.99 then 3 × 12.99 for key `"CLOUDVAULT"`.

*Phase 1*: buckets A = [9.99 × 3], B = [12.99 × 3] (+30% apart). Each yields a stable monthly series.

*Phase 2a*: no unclaimed rows. *Phase 2b*: A ends, B starts 30 days later, non-overlapping → union
`[9.99 × 3, 12.99 × 3]`: not one level (median 11.49, 9.99 is 13% away); only p = 3 splits it into
two levels, both sides have 3 rows → `price_steps=[(9.99, 12.99)]`.

*Result*: one series, six rows, `yearly_cost = 155.88`. Price-increase alert: ratio ≈ 0.30,
`extra = 36.00`. ✓

---

**E3** — Parallel series, different amounts: interleaved 2.99 / 0.99 monthly for `"GLOWBILL"`.

```
Jan-01 2.99 | Jan-15 0.99 | Feb-01 2.99 | Feb-15 0.99 | Mar-01 2.99 | Mar-15 0.99
```

*Phase 1*: buckets [2.99 × 3] and [0.99 × 3]; gaps 31, 28 → each is a stable monthly series.
*Phase 2b*: the series overlap in calendar time (Mar-01 is after Jan-15) → never merged.

*Result*: two series. `detect_duplicate_subscriptions`: same key, ratio
`|2.99 − 0.99| / 2.99 ≈ 0.67 > 0.10` → no alert. ✓

---

**E4** — Parallel series, same amount: interleaved 10.99 / 10.99 monthly for `"MUSICBOX"`.

```
Jan-01 | Jan-15 | Feb-01 | Feb-15 | Mar-01 | Mar-15    (all 10.99)
```

*Phase 1*: one bucket of 6. `longest_cadence_run` (monthly) starts at Jan-01: Jan-15 is 14 days
later (not a monthly gap, not beyond the window, so skipped); Feb-01 is 31 days later ✓; Feb-15 is
skipped; Mar-01 is 28 days after Feb-01 ✓; Mar-15 is skipped. Run = [Jan-01, Feb-01, Mar-01],
length 3 ≥ 3, one level → stable series S_A. The `while` loop runs again on the remaining
[Jan-15, Feb-15, Mar-15] → run of 3 → stable series S_B.

*Phase 2*: nothing unclaimed; S_A and S_B overlap in calendar time → no merge.

*Result*: two monthly series at 10.99. `detect_duplicate_subscriptions`: same key, both active,
ratio 0 ≤ 0.10 → one duplicate alert. ✓

---

**E5** — Aliased duplicate: `"STREAMFLIX INTL"` monthly + `"STREAMFLIXCOM"` monthly, alias
`streaming = ["STREAMFLIX INTL", "STREAMFLIXCOM"]`.

`find_series` runs once per key; each has 3+ monthly rows at ~14.99 → one stable series each.
`detect_duplicate_subscriptions` resolves both keys to `"STREAMING"`; different keys that share a
canonical name are a duplicate regardless of amount. ✓

---

**E6** — Two supermarket charges 30 days apart: 87.50 and 143.20 for `"SUPERMART"`.

*Phase 1*: two 1-row buckets → runs of 1. *Phase 3*: `longest_cadence_run` monthly = both rows
(gap 30), length 2 < 3. Quarterly/yearly: runs of 1. *Result*: no alerts. ✓

---

**E7** — Weekly grocery shopping: 6 charges 7 days apart, amounts 35.00, 90.00, 210.00, 60.00,
150.00, 120.00 for `"FRESHCO"`.

*Phase 1*: six 1-row buckets → runs of 1 < 4. *Phase 3*: weekly run = all 6 rows (≥ 4).
`_segment_by_price`: not a level; no split has two levels; Branch 3 fails (amounts far from the
median 105.00) → `None` → stop. Monthly run: gap 28 gives rows 1 and 5 → length 2 < 3.
*Result*: no alerts. ✓

---

**E7b** — 26 weekly supermarket charges between 40.00 and 150.00 over 6 months for `"FRESHCO"`.

Fixture (deterministic): charge `i = 0..25` is dated `2026-05-04 + 7·i` days and has amount
`round_to_cents(40.00 × 1.11^k)` with `k = (5·i) mod 13`. The 13 price levels (40.00 … 139.94) are
each more than 10% apart, so each level is its own bucket and holds exactly two rows, `i` and
`i + 13`, which are 91 days apart.

*Phase 1*: 13 buckets of 2 rows. Weekly and monthly: runs of 1 < min. Quarterly: run of 2 ≥ 2 and
one level → candidate quarterly series, **rejected by `_accept`**: the key has 12 other debit rows
between the two charges. Yearly: runs of 1.
*Phase 2*: nothing found, nothing to extend.
*Phase 3*: weekly run = all 26 rows (gaps 7) → not a level, no split with two levels, Branch 3 fails
→ `None`. Monthly run = rows `i, i+4, i+8, …` (28-day gaps), 7 rows, levels all different → `None`.
Quarterly run = rows `i, i+13` → rejected by `_accept` again. Yearly: runs of 1.

*Result*: **no series, so no alerts of any kind** (no recurring charge, no price increase, no
duplicate, no free trial; and no cancellation alert unless the user supplies a date). Without the
Branch 2 side-size rule and the quarterly/yearly span guard, this ledger produced about 13 quarterly
series, 9 price-increase alerts and a duplicate alert per statement. ✓

---

**Downgrade** (Tier 1): 3 × 14.99 then 3 × 9.99 monthly.

*Phase 1*: two stable series. *Phase 2b*: merge → p = 3 split → `price_steps=[(14.99, 9.99)]`,
`current_amount=9.99`. `detect_price_increases`: step is downward → no alert.
`detect_recurring_charges` fires once. ✓

---

## 5 — Detector APIs

All five detectors share this pattern:

```python
from collections.abc import Mapping
from typing import Any
import pandas as pd
from ledger_kit.detectors import register
from ledger_kit.models import Alert
from .utils import (find_series, resolve_alias, is_active, group_by_normalised_key,
                    group_by_canonical, sorted_source_refs, ppy_for, ledger_max_date, ...)

@register("zs.<name>")
def detect_<name>(ledger: pd.DataFrame, context: Mapping[str, Any]) -> list[Alert]:
    """One-line docstring."""
    aliases: dict[str, list[str]] | None = context.get("aliases")
    alerts: list[Alert] = []
    if ledger.empty:
        return alerts
    max_date = ledger_max_date(ledger)
    # ... detector logic ...
    return alerts
```

### 5.1 `detect_recurring_charges` (`recurring_charge.py`)

```python
for key, key_rows in group_by_normalised_key(ledger):
    for series in find_series(key_rows):
        canonical = resolve_alias(key, aliases)
        yearly_cost = round_to_cents(series.current_amount * ppy_for(series.interval_type))
        alerts.append(Alert(
            detector="zs.recurring_charge",
            severity="info",
            title=f"Recurring charge detected: {canonical}",
            source_refs=sorted_source_refs(series.rows),
            data={
                "counterparty": canonical,
                "normalised_key": key,
                "interval_type": series.interval_type,
                "current_amount": str(series.current_amount),
                "charge_count": len(series.rows),
                "yearly_cost": str(yearly_cost),
                "first_charge_date": series.rows[0]["date"].isoformat(),
                "last_charge_date": series.rows[-1]["date"].isoformat(),
                "is_active": is_active(series, max_date),
            },
        ))
```

### 5.2 `detect_price_increases` (`price_increase.py`)

```python
for key, key_rows in group_by_normalised_key(ledger):
    for series in find_series(key_rows):
        for (old, new) in series.price_steps:          # stored rounded medians
            if new <= old:
                continue                               # downward or flat: never an alert
            ratio = (new - old) / old                  # computed from the ROUNDED medians
            if ratio < PRICE_INCREASE_MIN_RATIO:
                continue                               # exactly 5% fires
            ppy = ppy_for(series.interval_type)
            canonical = resolve_alias(key, aliases)
            alerts.append(Alert(
                detector="zs.price_increase",
                severity="warning",
                title=f"Price increase detected: {canonical}",
                source_refs=sorted_source_refs(series.rows),
                data={
                    "counterparty": canonical,
                    "old_median_amount": str(old),
                    "new_amount": str(new),
                    "extra_cost_per_year": str(round_to_cents((new - old) * ppy)),
                    "yearly_cost": str(round_to_cents(new * ppy)),
                    "interval_type": series.interval_type,
                },
            ))
```

### 5.3 `detect_duplicate_subscriptions` (`duplicate_subscription.py`)

```python
# Collect all active series; resolve to canonical name
canonical_to_series: dict[str, list[tuple[str, Series]]] = defaultdict(list)

for key, key_rows in group_by_normalised_key(ledger):
    for series in find_series(key_rows):
        if is_active(series, max_date):
            canonical_to_series[resolve_alias(key, aliases)].append((key, series))

for canonical, series_list in canonical_to_series.items():
    if len(series_list) < 2:
        continue

    # Series that take part in at least one qualifying pair.
    # Same-key pairs: current_amounts within AMOUNT_MATCH_RATIO (E4 ✓, E3 ✗).
    # Different-key (alias-resolved) pairs: always qualify when both are active (E5).
    qualifying: list[tuple[str, Series]] = []
    for i, (k_i, s_i) in enumerate(series_list):
        for k_j, s_j in series_list[i + 1:]:
            if k_i == k_j:
                ratio = abs(s_i.current_amount - s_j.current_amount) / max(
                    s_i.current_amount, s_j.current_amount)
                if ratio > AMOUNT_MATCH_RATIO:
                    continue
            for item in ((k_i, s_i), (k_j, s_j)):
                if not any(item[1] is q[1] for q in qualifying):
                    qualifying.append(item)

    if not qualifying:
        continue

    all_rows = [r for _, s in qualifying for r in s.rows]
    total_yearly = sum(
        (round_to_cents(s.current_amount * ppy_for(s.interval_type)) for _, s in qualifying),
        Decimal("0.00"),
    )
    alerts.append(Alert(
        detector="zs.duplicate_subscription",
        severity="warning",
        title=f"Duplicate subscription: {canonical}",
        source_refs=sorted_source_refs(all_rows),
        data={
            "canonical_name": canonical,
            "series_count": len(qualifying),
            "series_counterparties": [k for k, _ in qualifying],
            "yearly_cost": str(round_to_cents(total_yearly)),
        },
    ))
```

### 5.4 `detect_free_trial_to_paid` (`free_trial_to_paid.py`)

```python
# For each key, look for a trial charge 1..TRIAL_MAX_DAYS_BEFORE_FIRST_CHARGE days before a series start.
for key, key_rows in group_by_normalised_key(ledger):
    for series in find_series(key_rows):
        series_start = series.rows[0]["date"]
        series_refs = {r["source_ref"] for r in series.rows}
        trial_candidates = [
            r for r in key_rows
            if r["source_ref"] not in series_refs
            and FREE_TRIAL_MIN_TOKEN_AMOUNT <= Decimal(r["amount"]) <= FREE_TRIAL_MAX_TOKEN_AMOUNT
            and 1 <= (series_start - r["date"]).days <= TRIAL_MAX_DAYS_BEFORE_FIRST_CHARGE
        ]
        if not trial_candidates:
            continue
        trial = min(trial_candidates, key=lambda r: ((series_start - r["date"]).days, date_key(r)))
        canonical = resolve_alias(key, aliases)
        yearly = round_to_cents(series.current_amount * ppy_for(series.interval_type))
        alerts.append(Alert(
            detector="zs.free_trial_to_paid",
            severity="info",
            title=f"Free trial converted to paid: {canonical}",
            # sorted by (date, source_row) — NOT as text: 'f.csv:10' sorts before 'f.csv:9'
            source_refs=sorted_source_refs(series.rows + [trial]),
            data={
                "counterparty": canonical,
                "trial_amount": str(round_to_cents(Decimal(trial["amount"]))),
                "first_paid_amount": str(round_to_cents(Decimal(series.rows[0]["amount"]))),
                "trial_source_ref": trial["source_ref"],
                "days_before_first_charge": (series_start - trial["date"]).days,
                "yearly_cost": str(yearly),
                "interval_type": series.interval_type,
            },
        ))
```

The trial charge is never absorbed by backward extension: a `0.49` row 28–33 days before a
`14.99` series would be a +2961% "step", far beyond `MAX_EDGE_STEP_RATIO`.

### 5.5 `detect_charges_after_cancellation` (`charges_after_cancellation.py`)

One tombstone and one alert **per canonical service**, however many normalised keys it has. Series
are still found **per key** (REQ-ZS-07); only rows and yearly costs are aggregated per service.

```python
cancellation_dates: dict[str, date] | None = context.get("cancellation_dates")
if not cancellation_dates or ledger.empty:
    return []
max_date = ledger_max_date(ledger)

for canonical, key_groups in group_by_canonical(ledger, aliases).items():
    if canonical not in cancellation_dates:
        continue
    cancel_date = cancellation_dates[canonical]
    all_rows = [r for _key, rows in key_groups for r in rows]
    post = [r for r in all_rows if r["date"] > cancel_date]       # strictly after
    if not post:
        continue
    total = sum((Decimal(r["amount"]) for r in post), Decimal("0.00"))
    alerts.append(Alert(
        detector="zs.charges_after_cancellation",
        severity="critical",
        title=f"Charge after cancellation: {canonical}",
        source_refs=sorted_source_refs(post),
        data={
            "counterparty": canonical,
            "cancellation_date": cancel_date.isoformat(),
            "post_cancellation_count": len(post),
            "total_charged_after": str(round_to_cents(total)),
            "yearly_cost": str(service_yearly_cost(key_groups, max_date)),   # "0.00" if no active series
        },
    ))
```

---

## 6 — `compute_zombie_cost` (`detectors/utils.py`)

```python
@dataclass
class ZombieCostResult:
    canonical_name: str
    last_used_date: date
    cost_since_last_used: Decimal
    source_refs: list[str]
    yearly_cost: Decimal       # sum of yearly costs of the service's active series


def compute_zombie_cost(
    ledger: pd.DataFrame,
    last_used_dates: dict[str, date] | None,
    *,
    aliases: dict[str, list[str]] | None = None,
) -> list[ZombieCostResult]:
    """Return one ZombieCostResult per service named in last_used_dates.

    Groups by canonical name, so a service with two aliased keys (E5) yields ONE result.
    A service with no rows at all still yields an entry with cost 0.00 (REQ-ZS-30).
    last_used_dates=None or {} → []. Never reads the system clock.
    """
    if not last_used_dates:
        return []
    max_date = ledger_max_date(ledger)
    by_canonical = group_by_canonical(ledger, aliases) if not ledger.empty else {}
    results: list[ZombieCostResult] = []
    for canonical, last_used in last_used_dates.items():       # keys are already normalised
        key_groups = by_canonical.get(canonical, [])
        post = [r for _key, rows in key_groups for r in rows if r["date"] > last_used]
        cost = round_to_cents(sum((Decimal(r["amount"]) for r in post), Decimal("0.00")))
        results.append(ZombieCostResult(
            canonical_name=canonical,
            last_used_date=last_used,
            cost_since_last_used=cost,
            source_refs=sorted_source_refs(post),
            yearly_cost=service_yearly_cost(key_groups, max_date),
        ))
    return results
```

Series are found per key inside `service_yearly_cost`; rows of two aliased keys are never mixed
into one `find_series` call.

---

## 7 — App data flow (`app.py`, `settings.py`)

`settings.py` holds everything that can be tested without Streamlit:

```python
def load_config(path: Path) -> dict: ...                    # tomllib
def demo_inputs(config: dict, root: Path) -> DemoInputs: ... # csv bytes + parsed inputs
def to_date(value: str | date) -> date:                      # TOML strings or TOML dates
    return value if isinstance(value, date) else date.fromisoformat(value)
def parse_aliases_text(text: str) -> dict[str, list[str]]: ...   # "streaming = A, B" per line
def parse_dates_text(text: str) -> dict[str, date]: ...          # "NAME = YYYY-MM-DD" per line
def format_aliases_text(aliases) -> str: ...
def format_dates_text(dates) -> str: ...
```

`[demo]` dates arrive from TOML as strings and are converted with `date.fromisoformat`.

**Amendment A-ZS-01 (session 10b, benchmark D-BM-10).** `settings.py` also holds the pipeline the
page runs, so the benchmark runner can call the same function:

```python
@dataclass(frozen=True)
class Pipeline:
    ledger: pd.DataFrame            # normalised, debit and credit rows
    debit_ledger: pd.DataFrame      # flow == "debit", index reset (what the detectors read)
    quarantine: list[dict]          # reader quarantine + normaliser quarantine
    results: list[DetectorResult]   # run_all(debit_ledger, namespace="zs", context=...)
    @property
    def alerts(self) -> list[Alert]: ...      # all alerts in result order

def ingest_statement(name, data, cache=None) -> tuple[pd.DataFrame, list[dict]]: ...
def run_pipeline(name, data, *, aliases, cancellation_dates, cpi=None, cache=None) -> Pipeline: ...
```

`ingest_statement` is the old `app._ingest` body (read with `read_bank_statement`, parse cached by
sha256 when `cache` is given, then `normalise`); `app._ingest` stays as a thin wrapper so its tests
are unchanged. `aliases` and `cancellation_dates` arrive already normalised
(`normalise_alias_map`, `normalise_date_map`). `app.py` calls `run_pipeline`; nothing else in the
data flow below changes. `compute_zombie_cost` stays in `app.py` (it needs the last-used dates,
which no benchmark scenario has).

```
Path bootstrap (insert repo root into sys.path)
  │
  ▼
config = load_config(config.toml)
  │
  ▼
Callback (defined BEFORE the widgets):
    def load_demo():                       # runs before the next rerun builds any widget
        demo = demo_inputs(config, ROOT)
        st.session_state["source"] = ("demo", demo.csv_bytes, demo.csv_name)
        st.session_state["aliases_text"]   = format_aliases_text(demo.aliases)
        st.session_state["last_used_text"] = format_dates_text(demo.last_used_dates)
        st.session_state["cancel_text"]    = format_dates_text(demo.cancellation_dates)
        st.session_state["demo_loaded"]    = True
  │
  ▼
Sidebar:
    st.sidebar.button("Load demo data", on_click=load_demo)
    aliases_text   = st.sidebar.text_area("Aliases",            key="aliases_text")
    last_used_text = st.sidebar.text_area("Last-used dates",    key="last_used_text")
    cancel_text    = st.sidebar.text_area("Cancellation dates", key="cancel_text")
    hallucinate    = st.sidebar.toggle("Simulate a hallucinating LLM", key="hallucinate")
    uploaded       = st.sidebar.file_uploader("Bank statement CSV", type="csv")
```

**Why `on_click`**: the sidebar widgets are created earlier in the script run than an
`if st.button(...)` body, so assigning `st.session_state["aliases_text"] = ...` there raises
`StreamlitWidgetAlreadyInstantiatedError`. An `on_click` callback runs *before* the script reruns,
so writing the widget keys is allowed. Default values are set once with
`st.session_state.setdefault(key, "")` before the widgets are created; the text areas pass no
`value=` argument.

```
  ▼ source = uploaded file if present, else st.session_state.get("source")
  ▼ normalise all user-entered keys once:
  aliases            = normalise_alias_map(parse_aliases_text(aliases_text))
  last_used_dates    = normalise_date_map(parse_dates_text(last_used_text))
  cancellation_dates = normalise_date_map(parse_dates_text(cancel_text))
  │
  ▼
parse_csv(source, source_file=...) → normalise(transactions) → ledger
debit_ledger = ledger[ledger["flow"] == "debit"].reset_index(drop=True)
(cached in st.session_state["ingestion_cache"] by sha256 of the file bytes)
  │
  ▼
ctx = {"aliases": aliases, "cancellation_dates": cancellation_dates}
results = run_all(debit_ledger, namespace="zs", context=ctx)
zombie_results = compute_zombie_cost(debit_ledger, last_used_dates, aliases=aliases)
  │
  ▼
client_mode = "hallucinate" if hallucinate else "real"

For each alert in [a for r in results for a in r.alerts]:
    cache_key = (alert.id, client_mode)   # alert.id is deterministic (CR-LC-1b)
    if cache_key not in st.session_state["explanations"]:
        rows = debit_ledger[debit_ledger["source_ref"].isin(alert.source_refs)]
        client = HallucinatingStubClient() if hallucinate else None
        meta = explain_with_meta(alert, rows,
                                 fallback_template=TEMPLATES[alert.detector], client=client)
        st.session_state["explanations"][cache_key] = meta
    meta = st.session_state["explanations"][cache_key]
  │
  ▼
Render:
  • Tombstone graveyard (zombie_results)
  • Alert list grouped by severity, each with guard badge
  • Quarantine section (if any)
```

Key session-state keys:
- widget keys: `"aliases_text"`, `"last_used_text"`, `"cancel_text"`, `"hallucinate"`
- `"source"`: `("demo", bytes, filename)` set by `load_demo`
- `"ingestion_cache"`: `dict[sha256_hex, (list[Transaction], list[dict])]`
- `"explanations"`: `dict[tuple[str, str], Explanation]` — key is `(alert.id, client_mode)`
- `"demo_loaded"`: `bool`

**Why `(alert.id, client_mode)` as cache key**: `Alert.id` is a deterministic sha256 (CR-LC-1b), so
the same alert data always produces the same id across Streamlit reruns. The `client_mode`
dimension lets the user toggle the hallucination simulator without losing the cached real
explanation.

---

## 7a — CR-LC-1b: Deterministic `Alert.id` (ledger-core change)

Implemented in ledger-core (`ledger_kit/models.py`, ledger-core design §2.2, task 2). When no `id`
is supplied, `Alert.id` is the sha256 of canonical JSON of `detector`, sorted `source_refs`, and
`data`; an explicit `id` is preserved. The app relies on this for its explanation cache.

---

## 8 — Path bootstrap and deployment

The first executable lines of `app.py` (before any `import ledger_kit`):

```python
import sys, pathlib
_ROOT = pathlib.Path(__file__).resolve().parents[2]  # ghost-ledger-kit/
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
```

The **root-level** `requirements.txt` lists all runtime dependencies for Streamlit Community Cloud.
No `-e .` entry, no `setup.py`. There is **no** requirements file in `apps/zombie_subscriptions/`:
Community Cloud reads the file next to the entry point first and would ignore the root one.

---

## 9 — Hallucinating stub client and fallback templates (`explain_support.py`)

`TEMPLATES: dict[str, str]` maps each detector name to its REQ-ZS-34 fallback template.

```python
class HallucinatingStubClient:
    """Injects a foreign number into every LLM response.
    Used in the UI toggle 'Simulate a hallucinating LLM'."""

    INJECTED_NUMBER: str = "99999.99"  # known to be absent from any real alert

    @property
    def chat(self):
        return self

    @property
    def completions(self):
        return self

    def create(self, *, messages, **_kwargs):
        fake_text = f"This subscription costs you {self.INJECTED_NUMBER} EUR per year."
        from types import SimpleNamespace
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=fake_text))]
        )
```

When the toggle is on, `app.py` passes `client=HallucinatingStubClient()` to `explain_with_meta`.
The number guard always rejects the injected value; the badge shows ⚠️ with `99999.99`.

---

## 10 — Demo generator and demo configuration

`scripts/generate_samples.py --mode zombie-demo --seed 42` produces
`data/samples/zombie_demo_statement.csv`. **All counterparty names are fictional brands**; none
may be, or imply, a real company (no Spotify, Adobe, Dropbox, Netflix, …). Finance Rule 5 person
names apply to salary/transfer counterparties only.

| Pattern | Fictional counterparty (raw CSV text) | Normalised key | Description |
|---|---|---|---|
| E1 (step change) | `STREAMFLEX INTL 4412` | `STREAMFLEX INTL` | 5 × 12.99 + 1 × 15.99 monthly |
| E2 (step change) | `CLOUDVAULT` | `CLOUDVAULT` | 3 × 9.99 + 3 × 12.99 monthly |
| E3 (parallel, different amounts) | `GLOWBILL` | `GLOWBILL` | Interleaved 2.99 + 0.99 monthly |
| E4 (parallel, same amount) | `MUSICBOX` | `MUSICBOX` | Two interleaved 10.99 monthly |
| E5 (alias duplicate) | `STREAMFLIX INTL 7731` + `STREAMFLIXCOM` | `STREAMFLIX INTL`, `STREAMFLIXCOM` | Monthly, aliased to `streaming` |
| Free trial | `SECUREPASS` | `SECUREPASS` | 0.49 debit 14 days before first monthly 14.99 |
| Post-cancellation | `GYMPLUS` | `GYMPLUS` | monthly 8.99; 3 charges after the cancellation date |
| Zombie candidates | `BEATSTREAM`, `PHOTOBOX`, `STASHCRATE` | same | Monthly; have `last_used_date` entries |
| Noise | `FRESHCO` and other fictional merchants | — | Salary credit, weekly groceries built like E7b (no series can form), transfers, one-off shops |

Total: ~320 rows over 6 months (2026-05-01 to 2026-10-31), plain dialect. The generator uses
`random.seed(42)`; output is fully deterministic.

### 10.1 `[demo]` section of `config.toml`

Every alias member and every key of `last_used_dates` / `cancellation_dates` must equal a
**normalised key present in the demo CSV** (the alias *name* `streaming` is a canonical name, not a
CSV key). Dates are TOML strings and are converted with `date.fromisoformat`.

```toml
[demo]
csv_path = "data/samples/zombie_demo_statement.csv"

[demo.aliases]
streaming = ["STREAMFLIX INTL", "STREAMFLIXCOM"]

[demo.last_used_dates]
"BEATSTREAM" = "2026-07-15"
"PHOTOBOX"   = "2026-06-20"
"STASHCRATE" = "2026-08-10"

[demo.cancellation_dates]
"GYMPLUS" = "2026-07-31"
```

`test_zs_demo_e2e.py` asserts (a) every alias member and every date-map key of the `[demo]` section
is in `{normalise_counterparty(c) for c in demo_csv["counterparty"]}` (after
`normalise_counterparty` is applied to the config value), (b) every date parses with
`date.fromisoformat`, (c) at least one alert of each of the five detector types, (d) at least 3
`ZombieCostResult` entries with non-zero `cost_since_last_used`, and (e) no alert cites a row of
the grocery/noise merchants.

---

## 11 — Test architecture

### 11.1 Conftest fixtures (`apps/zombie_subscriptions/tests/conftest.py`)

All fixtures use synthetic data. Dates are passed explicitly; no `date.today()`. **Fixture
counterparties are fictional merchants — never person names.**

```python
# Helper: build a debit ledger row
def _debit_row(source_ref, date_val, amount, counterparty, currency="EUR"):
    return {
        "id": str(uuid4()),
        "date": date_val,
        "amount": Decimal(amount),
        "flow": "debit",
        "currency": currency,
        "counterparty": counterparty,
        "description": "synthetic",
        "iban": None,
        "source_file": source_ref.split(":")[0],
        "source_row": int(source_ref.split(":")[1]),
        "source_ref": source_ref,
        "tags": [],
    }
```

| Fixture | Content |
|---|---|
| `empty_ledger` | `pd.DataFrame` with canonical columns, 0 rows |
| `single_row_ledger` | 1 debit row for `"CLOUDVAULT"` |
| `clean_ledger_10` | 10 debit rows; varying fictional merchant counterparties, no recurring pattern |
| `ledger_with_recurring` | 3 × monthly 12.99 rows for `"CLOUDVAULT"` (meets `MIN_OCCURRENCES_MONTHLY`) |
| `ledger_with_price_increase` | E1 fixture: 5 × 12.99 + 1 × 15.99 monthly `"STREAMFLEX INTL"` |
| `ledger_with_duplicate_sub` | E4 fixture: 6 rows, two interleaved 10.99 monthly `"MUSICBOX"` |
| `ledger_with_aliased_duplicate` | E5 fixture: 3 × `"STREAMFLIX INTL"` + 3 × `"STREAMFLIXCOM"` monthly |
| `ledger_with_free_trial` | 1 × 0.49 + 3 × 14.99 monthly for `"SECUREPASS"` |
| `ledger_with_post_cancellation` | 3 × 8.99 monthly + 1 × 8.99 after the cancellation date for `"GYMPLUS"` |
| `ledger_with_zombie` | `ledger_with_recurring` with `last_used_date` before the last 2 charges |
| `ledger_with_weekly_shopping` | E7b fixture: 26 weekly `"FRESHCO"` charges (generator in §4.8) |

### 11.2 Hypothesis strategies

```python
def monthly_series_strategy(n_charges: int, base_amount: Decimal):
    """Monthly series: each gap is 30 + jitter days with jitter in [-3, 3] (so every gap stays
    inside the cadence tolerance); amounts within ±4% of base_amount.

    ±4% is outside a 2% price level, so such a series is accepted through Branch 3 (variable bill)
    or as a step; either way it is ONE series, which is what the detection properties assert.
    """

def noisy_step_series_strategy():
    """6 monthly charges (gaps exactly 30 days). base: whole euros in [20, 500]. The first k
    charges (k in 1..5) are at `base`, the rest at the new level (step 7-45%); every amount is
    multiplied by a noise factor in [0.995, 1.005] and rounded to cents. For the "never fires"
    property the base is restricted to whole euros in [100, 500] and the step to -3.9%..+3.9%."""

def exact_step_series_strategy():
    """Same, but noise-free; base whole euros in [20, 500] and the step an integer percent in
    [5, 50], so the new level is exact to the cent."""
```

Why the step bounds in the table below are not 4% / 6%: with noise `ε = 0.5%` the ratio of the two
medians can be as low as `(1+s)(1−ε)/(1+ε)` and as high as `(1+s)(1+ε)/(1−ε)`. For a step to
fire in the worst case `s ≥ 1.05·1.005/0.995 − 1 ≈ 6.06%`; to never fire in the worst case
`s ≤ 1.05·0.995/1.005 − 1 ≈ 3.95%`. The tests therefore use `s ≥ 7%` and `s ≤ 3.9%`. Between them
the outcome depends on the noise and is not asserted.

Two further bounds keep the noisy properties inside the guarantees of the algorithm:

- **Upper step bound 45%, not 50%.** A lone first or last charge is only read as a new price when
  the step is within `MAX_EDGE_STEP_RATIO` (±50%). With ±0.5% noise a nominal 50% step can measure
  slightly above 50% and be rejected; at 45% the worst case is `1.45·1.005/0.995 − 1 ≈ 46.5%`. The
  noise-free exact-step properties still cover 5–50%.
- **Bases 100–500 for the "never fires" property.** At the worst case `s = 3.9%` the measured ratio
  is about 4.94%, only 0.06 percentage points below the 5% threshold. Rounding each amount to cents
  can move the ratio by up to `2·0.005/base`, i.e. 0.05 points at base 20 but at most 0.01 points
  at base 100, so bases below 100 could cross the threshold for reasons unrelated to the detector.
  The "fires" properties keep bases 20–500: their worst-case margin is about 0.9 points (5.94% at
  a 7% step), far larger than the rounding effect.

Key properties (all `@settings(max_examples=200)`):

| Test | Property |
|---|---|
| `test_monthly_series_always_detected` | Generated monthly series (jitter and ±4% amounts) → exactly 1 recurring-charge alert. |
| `test_insufficient_occurrences_never_detected` | n < MIN_OCCURRENCES_MONTHLY → no alert. |
| `test_row_order_invariant` | Shuffled rows → same alerts (order-agnostic comparison). |
| `test_yearly_cost_equals_current_price_times_12` | `Alert.data["yearly_cost"] == str(round_to_cents(current_amount × 12))`. |
| `test_price_step_above_5pct_always_fires` | Noise within ±0.5% of each level; base 20–500; an upward step of 7–45% after k = 1..5 of 6 charges → exactly one price-increase alert. |
| `test_price_step_exactly_5pct_fires` | Noise-free step of exactly 5% at any k = 1..5 → one price-increase alert. |
| `test_price_step_below_5pct_never_fires` | Noise within ±0.5%; base 100–500; step 0–3.9% (up or down) → no price-increase alert. |
| `test_stable_series_never_fires_price_increase` | Noise within ±0.5% around one level → no price-increase alert. |
| `test_early_step_fires_exactly_once` | Noise-free step of 5–50% at any position k = 1..5 of 6 monthly charges → exactly one price-increase alert and one recurring series. |
| `test_source_refs_subset_of_input` (all detectors) | `Alert.source_refs ⊆ ledger["source_ref"]`. |

---

## 12 — Open decisions

### OD-ZS-03 (resolved)

Resolved in §4: price-level segmentation (`STABLE_AMOUNT_RATIO` 2% levels; stable, single step,
variable-bill branches), three phases (price-bucketed runs; forward/backward extension and merge;
leftover cadence runs), and the shopping guards (side-size rule for steps, quarterly/yearly span
guard).

### OD-ZS-05 — Hypothesis strategy for E3/E4 parallel series

The property test for "two parallel series are always detected separately" is implemented as a
Tier 1 acceptance test (not a Hypothesis property), to avoid the combinatorial complexity of
generating valid interleaved series in Hypothesis. Fixtures `ledger_with_duplicate_sub` (E4) and
`ledger_with_aliased_duplicate` (E5) cover these cases explicitly.

### OD-ZS-06 — `find_series` call cost across detectors

`find_series` is called independently by each of the 5 detectors (and by `service_yearly_cost`).
For a 300-row ledger with ~15 unique keys, this is ~6 × 15 = 90 calls. Each call is O(n²) per key
where n ≤ ~30, so the total is negligible (< 1 ms). No caching for v1. If the ledger grows beyond
~10 000 rows, memoize `find_series` per `(key, ledger_content_hash)` or extract it to a shared
pre-computation step passed via `context`.
