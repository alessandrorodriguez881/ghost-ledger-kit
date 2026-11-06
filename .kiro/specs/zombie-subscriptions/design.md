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
├── requirements.txt             # pinned deps (app-level)
└── detectors/
    ├── __init__.py              # auto_discover("apps.zombie_subscriptions.detectors")
    ├── utils.py                 # normalise_counterparty, resolve_alias, find_series,
    │                            # compute_zombie_cost, ZombieCostResult, CONSTANTS
    ├── recurring_charge.py      # detect_recurring_charges  → "zs.recurring_charge"
    ├── price_increase.py        # detect_price_increases    → "zs.price_increase"
    ├── duplicate_subscription.py# detect_duplicate_subscriptions → "zs.duplicate_subscription"
    ├── free_trial_to_paid.py    # detect_free_trial_to_paid → "zs.free_trial_to_paid"
    └── charges_after_cancellation.py # detect_charges_after_cancellation → "zs.charges_after_cancellation"
```

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

# Price-step detection
PRICE_INCREASE_MIN_RATIO: Decimal = Decimal("0.05")   # 5%

# Parallel-series / duplicate-subscription matching
AMOUNT_MATCH_RATIO: Decimal = Decimal("0.10")          # 10%

# Free-trial detection
FREE_TRIAL_MAX_TOKEN_AMOUNT: Decimal = Decimal("1.00")
TRIAL_MAX_DAYS_BEFORE_FIRST_CHARGE: int = 35

# Periods per year for yearly_cost computation
PERIODS_PER_YEAR_WEEKLY: int = 52
PERIODS_PER_YEAR_MONTHLY: int = 12
PERIODS_PER_YEAR_QUARTERLY: int = 4
PERIODS_PER_YEAR_YEARLY: int = 1

# Interval descriptor table (used by find_series and detectors)
INTERVAL_TYPES: list[dict] = [
    {"name": "weekly",    "nominal": WEEKLY_NOMINAL_DAYS,    "min": MIN_OCCURRENCES_WEEKLY,    "ppy": PERIODS_PER_YEAR_WEEKLY},
    {"name": "monthly",   "nominal": MONTHLY_NOMINAL_DAYS,   "min": MIN_OCCURRENCES_MONTHLY,   "ppy": PERIODS_PER_YEAR_MONTHLY},
    {"name": "quarterly", "nominal": QUARTERLY_NOMINAL_DAYS, "min": MIN_OCCURRENCES_QUARTERLY, "ppy": PERIODS_PER_YEAR_QUARTERLY},
    {"name": "yearly",    "nominal": YEARLY_NOMINAL_DAYS,    "min": MIN_OCCURRENCES_YEARLY,    "ppy": PERIODS_PER_YEAR_YEARLY},
]
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
    'netflix', 'Netflix', and 'NETFLIX' all produce the same canonical key 'NETFLIX',
    and 'NETFLIX.COM' and 'Netflix.com' both normalise to 'NETFLIXCOM'.

    The canonical name (dict key) is also normalised — user-entered names like
    'Netflix' are stored as 'NETFLIX'.
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
    so 'Spotify', 'SPOTIFY', and 'spotify' all map to the same 'SPOTIFY' key.
    """
    if not raw_map:
        return raw_map
    return {normalise_counterparty(k): v for k, v in raw_map.items()}
```

---

## 4 — OD-ZS-03: Series algorithm (`detectors/utils.py → find_series`)

### 4.1 Problem statement

A single normalised key may have:
- A **stable series**: all charges at the same price (or near-same) at a regular cadence.
- A **step-change series**: charges at one price level, then a sustained shift to a new level.
- **Parallel series**: two simultaneous subscriptions billed under the same key (different prices
  like E3, or same price like E4).
- **Noise**: supermarket visits, one-off purchases — irregular dates and/or highly varying amounts.

The algorithm must distinguish all four cases. It is O(n²) per key (n ≤ ~1000 rows in practice).

### 4.2 Data structures

```python
@dataclass
class Series:
    rows: list[dict]           # ledger rows (dicts) sorted by date ascending
    interval_type: str         # "weekly" | "monthly" | "quarterly" | "yearly"
    nominal_days: int
    current_amount: Decimal    # median of charges since last price step
    price_steps: list[tuple[Decimal, Decimal]]  # [(old, new), ...] — any direction
```

`price_steps` records every step (up or down). `detect_price_increases` only fires for upward
steps exceeding `PRICE_INCREASE_MIN_RATIO`.

### 4.3 `_segment_by_price(run, interval_type) -> Series | None`

Decides whether a cadence-consistent run is a stable or step-change series (returns `Series`),
or is too noisy to be a subscription (returns `None`).

```
def _segment_by_price(run):
    amounts = [Decimal(r["amount"]) for r in run]
    overall_median = median(amounts)

    # Branch 1: stable series — all amounts within AMOUNT_MATCH_RATIO of overall median
    if all(|a - overall_median| / overall_median <= AMOUNT_MATCH_RATIO for a in amounts):
        return Series(..., current_amount=round_to_cents(overall_median), price_steps=[])

    # Branch 2: single sequential step (in either direction)
    for p in range(1, len(run)):
        pre, post = amounts[:p], amounts[p:]
        level_a, level_b = median(pre), median(post)
        pre_ok  = all(|a - level_a| / level_a <= AMOUNT_MATCH_RATIO for a in pre)
        post_ok = all(|a - level_b| / level_b <= AMOUNT_MATCH_RATIO for a in post)
        if pre_ok and post_ok and level_a != level_b:
            return Series(..., current_amount=round_to_cents(level_b),
                          price_steps=[(round_to_cents(level_a), round_to_cents(level_b))])

    return None  # too much variance — not a subscription
```

Note: Branch 2 now accepts steps in either direction (upward or downward). The step condition is
`level_a != level_b` after clustering — both `pre_ok` and `post_ok` being true and the two
medians differing more than rounding is sufficient. `detect_price_increases` enforces the
directional and magnitude filter.

### 4.4 `longest_cadence_run(rows, interval) -> list[dict]`

```
def longest_cadence_run(rows, interval):
    """Given a date-sorted list of rows, return the longest subsequence
    whose consecutive gaps all fall within nominal ± INTERVAL_TOLERANCE_DAYS."""
    best = []
    for start_idx, start_row in enumerate(rows):
        run = [start_row]
        for r in rows[start_idx + 1:]:
            gap = (r["date"] - run[-1]["date"]).days
            if |gap - interval.nominal| <= INTERVAL_TOLERANCE_DAYS:
                run.append(r)
            elif gap > interval.nominal + INTERVAL_TOLERANCE_DAYS:
                break   # any later row is even further — stop early
        if len(run) > len(best):
            best = run
    return best
```

O(n²) per key. `break` on large gaps keeps the inner loop short in practice.

### 4.5 `group_by_price_level(rows) -> list[list[dict]]`

Clusters rows into price buckets by greedy sort: sort by amount, start a new bucket whenever
the gap between consecutive sorted amounts exceeds `AMOUNT_MATCH_RATIO × prev_median`.

```python
def group_by_price_level(rows: list[dict]) -> list[list[dict]]:
    if not rows:
        return []
    sorted_by_amount = sorted(rows, key=lambda r: Decimal(r["amount"]))
    buckets: list[list[dict]] = [[sorted_by_amount[0]]]
    for r in sorted_by_amount[1:]:
        prev_median = median([Decimal(x["amount"]) for x in buckets[-1]])
        if abs(Decimal(r["amount"]) - prev_median) / prev_median <= AMOUNT_MATCH_RATIO:
            buckets[-1].append(r)
        else:
            buckets.append([r])
    return buckets
```

### 4.6 `find_series(rows_for_key) -> list[Series]`

**Three-phase algorithm**:

```
Phase 1 — price-bucketed runs (parallel and stable series)
Phase 2 — extend-and-merge (step-change series that cross bucket boundaries)
Phase 3 — leftover cadence runs (any remaining unclaimed rows)
```

```
def find_series(rows_for_key):
    sorted_rows = sort by date ascending
    claimed = set()           # source_refs already in a Series
    found_series = []

    # ─────────── Phase 1: price-bucketed runs ───────────
    buckets = group_by_price_level(sorted_rows)
    # Sort largest bucket first so dominant series are claimed first
    for bucket in sorted(buckets, key=len, reverse=True):
        for interval in INTERVAL_TYPES:
            while True:
                unclaimed_bucket = [r for r in bucket if r["source_ref"] not in claimed]
                run = longest_cadence_run(unclaimed_bucket, interval)
                if len(run) < interval.min:
                    break
                s = _segment_by_price(run)
                if s is not None:
                    found_series.append(s)
                    claimed.update(r["source_ref"] for r in run)
                    # Continue: same bucket may yield another parallel series (E4)
                else:
                    break

    # ─────────── Phase 2: extend-and-merge ───────────────
    # For each pair of series S, T with the same interval type where T.first_date
    # falls within S.last_date + nominal ± tolerance, and S and T are chronologically
    # non-overlapping, attempt to merge them if _segment_by_price accepts the union.
    changed = True
    while changed:
        changed = False
        for i, s_a in enumerate(found_series):
            for j, s_b in enumerate(found_series):
                if j <= i:
                    continue
                if s_a.interval_type != s_b.interval_type:
                    continue
                # Ensure s_a ends before s_b starts
                earlier, later = (s_a, s_b) if s_a.rows[-1]["date"] <= s_b.rows[0]["date"] else (s_b, s_a)
                gap = (later.rows[0]["date"] - earlier.rows[-1]["date"]).days
                nominal = earlier.nominal_days
                if |gap - nominal| > INTERVAL_TOLERANCE_DAYS:
                    continue   # not consecutive — cannot merge
                combined_rows = earlier.rows + later.rows  # already date-sorted
                merged = _segment_by_price(combined_rows)
                if merged is not None:
                    found_series.remove(s_a)
                    found_series.remove(s_b)
                    found_series.append(merged)
                    changed = True
                    break       # restart outer loop after mutation
            if changed:
                break

    # ─────────── Phase 3: leftover cadence runs ──────────
    # Catch any unclaimed rows that did not fit a price bucket but have regular cadence
    # (e.g. a single-row bucket that merges with another after Phase 2 exhausted)
    for interval in INTERVAL_TYPES:
        while True:
            unclaimed = [r for r in sorted_rows if r["source_ref"] not in claimed]
            run = longest_cadence_run(unclaimed, interval)
            if len(run) < interval.min:
                break
            s = _segment_by_price(run)
            if s is not None:
                found_series.append(s)
                claimed.update(r["source_ref"] for r in run)
            else:
                break

    return found_series
```

**Why three phases?**

- Phase 1 alone breaks E1 and E2: the 12.99×5 bucket becomes a stable series and the lone
  15.99 is below `min_occurrences`; similarly 9.99×3 and 12.99×3 become two separate stable
  series with no step recorded.
- Phase 2 (extend-and-merge) fixes this: it detects that the stable 12.99 series and the
  single/short 12.99→15.99 continuation are chronologically consecutive at the right cadence,
  attempts `_segment_by_price` on the union, and succeeds because the union has a clean step.
- Phase 3 catches any remaining rows that had only one representative in their bucket (too few
  for Phase 1) but form a valid cadence run when considered together.
- For E4 (same-price parallel), Phase 1's inner `while True` loop naturally finds both runs:
  after claiming the first every-other-row run, `longest_cadence_run` on the remaining rows
  in the same bucket finds the second run. No special deinterleaving is needed.

### 4.7 Active series

```python
def is_active(series: Series, ledger_max_date: date) -> bool:
    """True if the last charge is within one nominal interval + tolerance of ledger_max_date."""
    last_date = series.rows[-1]["date"]  # rows are sorted
    return (ledger_max_date - last_date).days <= series.nominal_days + INTERVAL_TOLERANCE_DAYS
```

`ledger_max_date` is always `ledger["date"].max()` — never `date.today()`.

### 4.8 Walk-through: acceptance examples E1–E7 on the final algorithm

Each walk-through is a required Tier 1 test. Dates are illustrative monthly steps (~30 days).

---

**E1** — Step change: 5 × 12.99 then 1 × 15.99 for key `"STREAMFLEX"`.

```
rows (date-sorted): [12.99, 12.99, 12.99, 12.99, 12.99, 15.99]
gaps:               [30,    30,    30,    30,    30]    ← all monthly-consistent
```

*Phase 1*:
- `group_by_price_level` → bucket A = [12.99×5], bucket B = [15.99×1] (gap > 10%).
- Bucket A: `longest_cadence_run` → 5-row monthly run. `_segment_by_price([12.99×5])` →
  all within 10% of 12.99 → **stable series S_A**, `current_amount=12.99`, claimed = rows 1–5.
- Bucket B: 1 row. 1 < `MIN_OCCURRENCES_MONTHLY=3` → skip.

*Phase 2 (extend-and-merge)*:
- Only one series exists → no pairs to try. No merge happens.

  Wait: Bucket B's row is **unclaimed**. The merge loop iterates over `found_series` pairs —
  it cannot merge a series with an unclaimed row. We need Phase 3 to give bucket B's row a
  chance to join S_A.

*Phase 3*:
- Unclaimed = [15.99 row].
- `longest_cadence_run([15.99], monthly)` → run length 1 < 3. No new series.

  **Problem**: the 15.99 row is never added to S_A. The step is not detected.

**Correction**: Phase 2 must also try to extend existing series with **unclaimed rows**, not
only merge two series. The revised extend-and-merge step:

```
Phase 2 (revised) — extend-and-merge:
    changed = True
    while changed:
        changed = False
        for series S in found_series:
            unclaimed = [r for r in sorted_rows if r["source_ref"] not in claimed]
            # Try appending unclaimed rows that arrive at the next expected date
            candidates = [r for r in unclaimed
                          if |( r["date"] - S.rows[-1]["date"] ).days - S.nominal_days|
                             <= INTERVAL_TOLERANCE_DAYS]
            if not candidates:
                continue
            next_row = the candidate with date closest to S.rows[-1]["date"] + nominal
            extended_rows = S.rows + [next_row]
            merged = _segment_by_price(extended_rows)
            if merged is not None:
                found_series.remove(S)
                found_series.append(merged)
                claimed.add(next_row["source_ref"])
                changed = True
                break

        # Also try merging two existing series (original logic)
        if not changed:
            for each (S_a, S_b) pair ...  [as before]
```

*Revised E1 trace with extend-and-merge including unclaimed rows*:

*Phase 1*: S_A = stable [12.99×5]. Claimed = rows 1–5. Row 6 (15.99) unclaimed.

*Phase 2 (revised)*:
- Try extending S_A: next expected date ≈ S_A.last + 30 days. Row 6 is 30 days after row 5 →
  within tolerance. `_segment_by_price([12.99×5, 15.99])`:
  - overall_median = 12.99. 15.99 fails stable check.
  - `for p=5`: pre=[12.99×5], post=[15.99]. `level_a=12.99`, `level_b=15.99`.
    pre_ok ✓, post_ok ✓ (single row). `level_b ≠ level_a` ✓ → returns merged Series.
- `found_series` now contains one merged Series with rows 1–6, `price_steps=[(12.99, 15.99)]`,
  `current_amount=15.99`. Changed=True → loop repeats.
- Next iteration: no more unclaimed rows, no mergeable pairs → changed=False → stop.

*Result*: **one series, all 6 rows**, `current_amount=15.99`,
`yearly_cost = round_to_cents(15.99 × 12) = 191.88`. ✓

`detect_price_increases` sees `price_steps=[(12.99, 15.99)]`. Step is upward,
ratio = `(15.99 - 12.99) / 12.99 ≈ 0.231 > 0.05`. Fires alert:
`old=12.99`, `new=15.99`, `extra=round_to_cents(3.00 × 12)=36.00`. ✓

---

**E2** — Step change: 3 × 9.99 then 3 × 12.99 for key `"CLOUDVAULT"`.

```
rows: [9.99, 9.99, 9.99, 12.99, 12.99, 12.99], all gaps ~30 days
```

*Phase 1*:
- Buckets: A=[9.99×3], B=[12.99×3].
- Bucket B (size 3, first by tie-break): `longest_cadence_run([12.99×3])` → 3-row monthly run.
  `_segment_by_price` → stable S_B, `current_amount=12.99`. Claimed = rows 4–6.
- Bucket A (size 3): `longest_cadence_run([9.99×3])` → 3-row monthly run.
  `_segment_by_price` → stable S_A, `current_amount=9.99`. Claimed = rows 1–3.

*Phase 2 (extend existing series with unclaimed rows)*: no unclaimed rows remain. Try merging
S_A and S_B. Same interval type (monthly). `earlier=S_A`, `later=S_B`. Gap between S_A.last
and S_B.first ≈ 30 days → within tolerance. `_segment_by_price([9.99×3, 12.99×3])`:
- overall_median ≈ 11.49. 9.99 is 13% below 11.49 → fails stable check.
- `for p=3`: pre=[9.99×3], post=[12.99×3]. `level_a=9.99`, `level_b=12.99`.
  pre_ok ✓, post_ok ✓. `level_b ≠ level_a` ✓ → merged Series.
- `found_series` = [merged], `price_steps=[(9.99, 12.99)]`, `current_amount=12.99`.

*Result*: **one series, all 6 rows**, `yearly_cost=155.88`. ✓

`detect_price_increases`: ratio = `(12.99 - 9.99) / 9.99 ≈ 0.30 > 0.05`. Fires alert:
`old=9.99`, `new=12.99`, `extra=round_to_cents(3.00 × 12)=36.00`. ✓

---

**E3** — Parallel series, different amounts: interleaved 2.99 / 0.99 monthly for `"APPLEBILL"`.

Row layout (each same-amount gap is ~30 days, interleaved with ~15-day offsets):
```
Jan-01  2.99
Jan-15  0.99
Feb-01  2.99
Feb-15  0.99
Mar-01  2.99
Mar-15  0.99   (6 total rows)
```

*Phase 1*:
- Buckets: A=[2.99×3] (dates Jan-01, Feb-01, Mar-01), B=[0.99×3] (dates Jan-15, Feb-15, Mar-15).
- Bucket A: `longest_cadence_run` on [Jan-01, Feb-01, Mar-01] → gaps 31, 28 → both within
  monthly tolerance (±3). Run length 3 ≥ 3. `_segment_by_price` → stable S_A. Claimed.
- Bucket B: `longest_cadence_run` on [Jan-15, Feb-15, Mar-15] → gaps 31, 28 → monthly ✓.
  Run length 3 ≥ 3. Stable S_B. Claimed.

*Phase 2*: S_A last = Mar-01, S_B first = Jan-15. S_B starts before S_A ends → overlapping in
calendar but non-overlapping in rows (different source_refs). The merge condition requires
`earlier.last < later.first` — S_A.last (Mar-01) > S_B.first (Jan-15), so S_A and S_B are
**not** mergeable. No merge attempted.

*Result*: **two separate monthly series**, `current_amount=2.99` and `current_amount=0.99`.
No price-increase alert (separate series, no step within either). ✓

`detect_duplicate_subscriptions`: S_A.current=2.99, S_B.current=0.99. Same key. Ratio
`|2.99 - 0.99| / 2.99 ≈ 0.67 > AMOUNT_MATCH_RATIO=0.10` → **not a duplicate**. ✓

---

**E4** — Parallel series, same amount: interleaved 10.99 / 10.99 monthly for `"MUSICBOX"`.

```
Jan-01  10.99  (account A)
Jan-15  10.99  (account B)
Feb-01  10.99  (account A)
Feb-15  10.99  (account B)
Mar-01  10.99  (account A)
Mar-15  10.99  (account B)
```

*Phase 1*:
- `group_by_price_level` → one bucket [10.99×6] (all amounts identical).
- `longest_cadence_run([all 6 rows], monthly)`: consecutive gaps are 14, 15, 14, 15, 14 days.
  No gap is within monthly tolerance (|14-30|=16 > 3). Best run = 1 row. < 3 → fails.
- Inner `while True` loop: same result on retry → break for monthly.
- Similarly fails for weekly, quarterly, yearly.

*Phase 2*: no series yet → nothing to extend or merge.

*Phase 3*: `unclaimed = all 6 rows`. `longest_cadence_run([all 6], monthly)` → same failure
(consecutive gaps ~15 days). No new series.

**Problem**: E4 yields no series under the current algorithm. The while-loop in Phase 1 does
not deinterleave; it simply retries `longest_cadence_run` on the same unclaimed rows and gets
the same result.

**Resolution (replaces OD-ZS-04)**: Inside Phase 1's while loop, after `longest_cadence_run`
fails to reach `interval.min`, attempt **stride-2 runs** before giving up on this bucket×interval
combination:

```
# Inside Phase 1, after longest_cadence_run fails min_occurrences check:
if len(run) < interval.min:
    # Try stride-2 sub-runs: even-indexed and odd-indexed rows by date order
    for stride_start in (0, 1):
        sub_rows = [r for i, r in enumerate(unclaimed_bucket) if i % 2 == stride_start]
        sub_run = longest_cadence_run(sub_rows, interval)
        if len(sub_run) >= interval.min:
            s = _segment_by_price(sub_run)
            if s is not None:
                found_series.append(s)
                claimed.update(r["source_ref"] for r in sub_run)
                # Do not break — the other stride may also yield a series
    break  # done with this interval for this bucket
```

*Revised E4 trace*:

*Phase 1* (bucket [10.99×6], monthly):
- `longest_cadence_run` → best run length 1 (gaps ~15 days). 1 < 3.
- Stride-2 sub-run, stride_start=0: rows [Jan-01, Feb-01, Mar-01], gaps 31, 28 → monthly ✓.
  `_segment_by_price` → stable S_A (10.99). Claimed = A-account rows.
- Stride-2 sub-run, stride_start=1: rows [Jan-15, Feb-15, Mar-15], gaps 31, 28 → monthly ✓.
  `_segment_by_price` → stable S_B (10.99). Claimed = B-account rows.
- Break.

*Phase 2*: both series start before the other ends (overlapping calendar) → no merge (correct).

*Result*: **two separate monthly series**, both `current_amount=10.99`. ✓

`detect_duplicate_subscriptions`: same key, both active. Ratio
`|10.99 - 10.99| / 10.99 = 0 ≤ 0.10` → **duplicate alert**. ✓

---

**E5** — Aliased duplicate: `"STREAMFLIX INTL"` monthly + `"STREAMFLIXCOM"` monthly, alias
`streaming = ["STREAMFLIX INTL", "STREAMFLIXCOM"]`.

Each key has 3+ monthly rows at the same price (~14.99). Two separate keys → `find_series`
called independently per key; each yields one stable monthly series via Phase 1.

`detect_duplicate_subscriptions`: resolves both keys to canonical `"STREAMING"`. Both series
active. Different keys → alias-resolved → **always a duplicate regardless of amount**. ✓

---

**E6** — Two supermarket charges 30 days apart: 87.50 and 143.20 for `"SUPERMART"`.

*Phase 1*:
- Buckets: [87.50], [143.20] — one row each.
- Each bucket: longest cadence run = 1 row < `MIN_OCCURRENCES_MONTHLY=3`. Skip.

*Phase 2*: no series to extend or merge.

*Phase 3*: `unclaimed = [87.50, 143.20]`. `longest_cadence_run` → run=[87.50, 143.20],
gap=30 days → monthly consistent. Run length 2 < 3. No series.

*Result*: **no alerts**. ✓

---

**E7** — Weekly grocery shopping: 6 charges ~7 days apart, amounts 35 to 210 for `"FRESHCO"`.

*Phase 1*:
- `group_by_price_level` → many buckets (amounts vary by >10% from each other) → most buckets
  have 1 row, none ≥ 4 (the weekly minimum).

*Phase 2*: no series → nothing to process.

*Phase 3*: `unclaimed = all 6 rows`. `longest_cadence_run([all 6], weekly)` → gaps ~7 days,
all within tolerance → run length 6 ≥ 4. `_segment_by_price`:
- overall_median ≈ 122. Amounts range 35–210 → most fall outside ±10% → stable check fails.
- `for p` loop: no clean split (amounts are irregular, not two distinct price levels). Returns
  `None`. → No series.

*Result*: **no alerts**. ✓

---

**Downgrade test (new Tier 1 test)**:

Series with a downward step (e.g. 3 × 14.99 monthly → 3 × 9.99 monthly after a plan change):
- Phase 1: bucket [14.99×3] → stable S_A; bucket [9.99×3] → stable S_B.
- Phase 2: S_A.last + 30 days ≈ S_B.first → merge attempted. `_segment_by_price`:
  `for p=3`, `level_a=14.99`, `level_b=9.99`. pre_ok ✓, post_ok ✓. `level_b ≠ level_a` ✓.
  → merged Series, `price_steps=[(14.99, 9.99)]`, `current_amount=9.99`.
- `detect_price_increases`: step is **downward** (`9.99 < 14.99`) → no alert. ✓
- `detect_recurring_charges` still fires (one series found). ✓

---

## 5 — Detector APIs

All five detectors share this pattern:

```python
from collections.abc import Mapping
from typing import Any
import pandas as pd
from ledger_kit.detectors import register
from ledger_kit.models import Alert
from .utils import find_series, resolve_alias, is_active, INTERVAL_TYPES

@register("zs.<name>")
def detect_<name>(ledger: pd.DataFrame, context: Mapping[str, Any]) -> list[Alert]:
    """One-line docstring."""
    aliases: dict[str, list[str]] | None = context.get("aliases")
    alerts: list[Alert] = []
    # ... detector logic ...
    return alerts
```

### 5.1 `detect_recurring_charges` (`recurring_charge.py`)

```python
for key, key_rows in group_by_normalised_key(ledger):
    for series in find_series(key_rows):
        canonical = resolve_alias(key, aliases)
        yearly_cost = round_to_cents(series.current_amount * intervals[series.interval_type]["ppy"])
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
                "first_charge_date": str(series.rows[0]["date"]),
                "last_charge_date": str(series.rows[-1]["date"]),
                "is_active": is_active(series, ledger["date"].max()),
            },
        ))
```

### 5.2 `detect_price_increases` (`price_increase.py`)

```python
for key, key_rows in group_by_normalised_key(ledger):
    for series in find_series(key_rows):
        if not series.price_steps:
            continue
        for (old, new) in series.price_steps:
            # Only fire for upward steps exceeding PRICE_INCREASE_MIN_RATIO
            if new <= old:
                continue
            ratio = (new - old) / old
            if ratio < PRICE_INCREASE_MIN_RATIO:
                continue
            ppy = intervals[series.interval_type]["ppy"]
            extra = round_to_cents((new - old) * ppy)
            yearly = round_to_cents(new * ppy)
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
                    "extra_cost_per_year": str(extra),
                    "yearly_cost": str(yearly),
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
        if not is_active(series, ledger_max_date):
            continue
        canonical = resolve_alias(key, aliases)
        canonical_to_series[canonical].append((key, series))

for canonical, series_list in canonical_to_series.items():
    if len(series_list) < 2:
        continue

    # Build the list of series that participate in at least one qualifying pair.
    # Same-key pairs: require current_amounts within AMOUNT_MATCH_RATIO.
    # Different-key (alias-resolved) pairs: always qualify if both active.
    qualifying: list[tuple[str, Series]] = []
    for i, (k_i, s_i) in enumerate(series_list):
        for j, (k_j, s_j) in enumerate(series_list):
            if j <= i:
                continue
            if k_i == k_j:
                # Same normalised key: require similar price (E4 ✓, E3 ✗)
                ratio = abs(s_i.current_amount - s_j.current_amount) / max(s_i.current_amount, s_j.current_amount)
                if ratio > AMOUNT_MATCH_RATIO:
                    continue
            # Both series qualify — add each if not already in the list
            if (k_i, s_i) not in qualifying:
                qualifying.append((k_i, s_i))
            if (k_j, s_j) not in qualifying:
                qualifying.append((k_j, s_j))

    if not qualifying:
        continue

    # Use only the qualifying series for source_refs, series_count, and yearly_cost
    all_rows_sorted = sorted(
        [r for _, s in qualifying for r in s.rows],
        key=lambda r: r["date"],
    )
    total_yearly = sum(
        round_to_cents(s.current_amount * ppy_for(s.interval_type))
        for _, s in qualifying
    )
    alerts.append(Alert(
        detector="zs.duplicate_subscription",
        severity="warning",
        title=f"Duplicate subscription: {canonical}",
        source_refs=sorted_source_refs(all_rows_sorted),
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
# For each key, collect its series (if any) and look for a trial charge
# in the 1..TRIAL_MAX_DAYS_BEFORE_FIRST_CHARGE window before the series start.

for key, key_rows in group_by_normalised_key(ledger):
    for series in find_series(key_rows):
        series_start = series.rows[0]["date"]
        series_refs = {r["source_ref"] for r in series.rows}
        # Find trial charges: same key, not in series, amount in (0.01, 1.00]
        # dated 1..35 days before series_start
        trial_candidates = [
            r for r in key_rows
            if r["source_ref"] not in series_refs
            and Decimal("0.01") <= Decimal(r["amount"]) <= FREE_TRIAL_MAX_TOKEN_AMOUNT
            and 1 <= (series_start - r["date"]).days <= TRIAL_MAX_DAYS_BEFORE_FIRST_CHARGE
        ]
        if not trial_candidates:
            continue
        # Pick the closest trial charge to the series start
        trial = min(trial_candidates, key=lambda r: (series_start - r["date"]).days)
        canonical = resolve_alias(key, aliases)
        ppy = intervals[series.interval_type]["ppy"]
        yearly = round_to_cents(series.current_amount * ppy)
        alerts.append(Alert(
            detector="zs.free_trial_to_paid",
            severity="info",
            title=f"Free trial converted to paid: {canonical}",
            source_refs=sorted([trial["source_ref"]] + sorted_source_refs(series.rows)),
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

### 5.5 `detect_charges_after_cancellation` (`charges_after_cancellation.py`)

```python
cancellation_dates: dict[str, date] | None = context.get("cancellation_dates")
if not cancellation_dates:
    return []

# Group ALL debit rows by canonical name across all keys that resolve to the same service.
# A service with two aliased keys (E5) must produce one alert, not two.
canonical_to_rows: dict[str, list[dict]] = defaultdict(list)
canonical_to_key_rows: dict[str, list[dict]] = defaultdict(list)  # all rows for yearly_cost

for key, key_rows in group_by_normalised_key(ledger):
    canonical = resolve_alias(key, aliases)
    if canonical not in cancellation_dates:
        continue
    canonical_to_rows[canonical].extend(key_rows)
    canonical_to_key_rows[canonical].extend(key_rows)

for canonical, all_rows in canonical_to_rows.items():
    cancel_date = cancellation_dates[canonical]
    post = [r for r in all_rows if r["date"] > cancel_date]
    if not post:
        continue
    total = sum(Decimal(r["amount"]) for r in post)
    series_list = find_series(sorted(canonical_to_key_rows[canonical], key=lambda r: r["date"]))
    active = [s for s in series_list if is_active(s, ledger_max_date)]
    yearly = str(round_to_cents(active[0].current_amount * ppy_for(active[0].interval_type))) if active else "0.00"
    alerts.append(Alert(
        detector="zs.charges_after_cancellation",
        severity="critical",
        title=f"Charge after cancellation: {canonical}",
        source_refs=sorted_source_refs(post),
        data={
            "counterparty": canonical,
            "cancellation_date": str(cancel_date),
            "post_cancellation_count": len(post),
            "total_charged_after": str(round_to_cents(total)),
            "yearly_cost": yearly,
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
    yearly_cost: Decimal       # current_amount × periods_per_year for the active series


def compute_zombie_cost(
    ledger: pd.DataFrame,
    last_used_dates: dict[str, date],
    *,
    aliases: dict[str, list[str]] | None = None,
) -> list[ZombieCostResult]:
    """Return zombie cost data for every service that has a last-used date entry.

    Groups by canonical name so a service with two aliased keys (E5) produces one
    ZombieCostResult, not two.  Never reads the system clock.
    """
    results: list[ZombieCostResult] = []
    ledger_max_date = ledger["date"].max()

    # Accumulate rows and series per canonical name across all normalised keys
    canonical_rows: dict[str, list[dict]] = defaultdict(list)
    for key, key_rows in group_by_normalised_key(ledger):
        canonical = resolve_alias(key, aliases)
        if canonical in last_used_dates:
            canonical_rows[canonical].extend(key_rows)

    for canonical, all_rows in canonical_rows.items():
        last_used = last_used_dates[canonical]
        post = [r for r in all_rows if r["date"] > last_used]
        cost = round_to_cents(sum((Decimal(r["amount"]) for r in post), Decimal("0.00")))
        all_sorted = sorted(all_rows, key=lambda r: r["date"])
        series_list = find_series(all_sorted)
        active = [s for s in series_list if is_active(s, ledger_max_date)]
        yearly = round_to_cents(
            active[0].current_amount * ppy_for(active[0].interval_type)
        ) if active else Decimal("0.00")
        results.append(ZombieCostResult(
            canonical_name=canonical,
            last_used_date=last_used,
            cost_since_last_used=cost,
            source_refs=[r["source_ref"] for r in post],
            yearly_cost=yearly,
        ))
    return results
```

---

## 7 — App data flow (`app.py`)

```
Path bootstrap (insert repo root into sys.path)
  │
  ▼
Read config.toml → raw aliases, demo.last_used_dates, demo.cancellation_dates
  │
  ▼
Sidebar form → collect user inputs (pre-filled from [demo] when demo loaded):
  • last_used_dates_raw:    dict[str, date]   (user types service names as-is)
  • cancellation_dates_raw: dict[str, date]
  • aliases_raw:            dict[str, list[str]]
  • hallucinate_toggle:     bool
  │
  ▼ normalise all user-entered keys once:
  aliases         = normalise_alias_map(aliases_raw)
  last_used_dates = normalise_date_map(last_used_dates_raw)
  cancellation_dates = normalise_date_map(cancellation_dates_raw)
  │
  ▼
File uploader OR "Load demo data" button
  → parse_csv(source, source_file=...)  [ledger_kit.ingestion]
  → normalise(transactions)
  → debit_ledger = ledger[ledger["flow"] == "debit"].reset_index(drop=True)
  (cached in st.session_state["ingestion_cache"] by sha256 of file bytes)
  │
  ▼
ctx = {
    "aliases": aliases,
    "cancellation_dates": cancellation_dates,
}
results = run_all(debit_ledger, namespace="zs", context=ctx)
  │
  ▼
zombie_results = compute_zombie_cost(
    debit_ledger, last_used_dates, aliases=aliases
)
  │
  ▼
client_mode = "hallucinate" if hallucinate_toggle else "real"

For each alert in [a for r in results for a in r.alerts]:
    cache_key = (alert.id, client_mode)   # alert.id is deterministic (CR-LC-1b)
    if cache_key not in st.session_state["explanations"]:
        rows = debit_ledger[debit_ledger["source_ref"].isin(alert.source_refs)]
        client = HallucinatingStubClient() if hallucinate_toggle else None
        meta = explain_with_meta(
            alert, rows,
            fallback_template=TEMPLATES[alert.detector],
            client=client,
        )
        st.session_state["explanations"][cache_key] = meta
    meta = st.session_state["explanations"][cache_key]
  │
  ▼
Render:
  • Tombstone graveyard (zombie_results with last_used_date)
  • Alert list grouped by severity, each with guard badge
  • Quarantine section (if any)
```

Key session-state keys:
- `"ingestion_cache"`: `dict[sha256_hex, (list[Transaction], list[dict])]`
- `"explanations"`: `dict[tuple[str, str], Explanation]`  — key is `(alert.id, client_mode)`
- `"demo_loaded"`: `bool`

**Why `(alert.id, client_mode)` as cache key**: `Alert.id` is now a deterministic sha256 (see
§CR-LC-1b below), so the same alert data always produces the same id across Streamlit reruns.
The `client_mode` dimension lets the user toggle the hallucination simulator without losing the
cached real explanation.

---

## 7a — CR-LC-1b: Deterministic `Alert.id` (ledger-core change)

**Problem**: `Alert.id` is currently a random `uuid4()`, so every Streamlit rerun regenerates
all alerts with new ids and the explanation cache is always cold.

**Resolution**: When no `id` is supplied to `Alert.__init__`, compute a deterministic sha256 from
the alert's immutable identity fields:

```python
import hashlib, json

def _alert_id(detector: str, source_refs: list[str], data: dict) -> str:
    """Deterministic id: sha256 of detector + sorted source_refs + canonical-JSON data."""
    payload = json.dumps(
        {"detector": detector, "source_refs": sorted(source_refs), "data": data},
        sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()
```

The `Alert` model uses this as its `id` default factory:

```python
class Alert(BaseModel):
    id: str = Field(default_factory=lambda: "")  # overridden by validator
    ...
    @model_validator(mode="before")
    @classmethod
    def _set_deterministic_id(cls, values):
        if not values.get("id"):
            values["id"] = _alert_id(
                values["detector"],
                values["source_refs"],
                values["data"],
            )
        return values
```

**Scope**: this change is in `ledger_kit/models.py` only. It is backward-compatible: callers
that pass an explicit `id` keep it. Tests that construct `Alert` directly without an `id` will
now receive a deterministic value instead of a random uuid.

**Ledger-core files to update**: `requirements.md` (new REQ-MOD-xx), `design.md` §2.2,
`tasks.md` Task 2 (add test for deterministic id).

---

## 8 — Path bootstrap and deployment

The first executable lines of `app.py` (before any `import ledger_kit`):

```python
import sys, pathlib
_ROOT = pathlib.Path(__file__).resolve().parents[2]  # ghost-ledger-kit/
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
```

Root-level `requirements.txt` lists all runtime dependencies for Streamlit Community Cloud.
No `-e .` entry. No `setup.py`. The path bootstrap makes `import ledger_kit` work at runtime.

---

## 9 — Hallucinating stub client

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
        user_msg = messages[-1]["content"] if messages else ""
        fake_text = f"This subscription costs you {self.INJECTED_NUMBER} EUR per year."
        from types import SimpleNamespace
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=fake_text))]
        )
```

When the toggle is on, `app.py` passes `client=HallucinatingStubClient()` to `explain_with_meta`.
The number guard always rejects the injected value; the badge shows ⚠️ with `99999.99`.

---

## 10 — Demo generator (`scripts/generate_samples.py --mode zombie-demo --seed 42`)

The generator produces `data/samples/zombie_demo_statement.csv`. All counterparty names are
**fictional** — they must not imply the prices or existence of real companies. Finance Rule 5
PII-safe person names apply to salary/transfer counterparties only.

| Pattern | Fictional counterparty | Description |
|---|---|---|
| E1 (step change) | `STREAMFLEX INTL` | 5 × 12.99 + 1 × 15.99 monthly |
| E2 (step change) | `CLOUDVAULT` | 3 × 9.99 + 3 × 12.99 monthly |
| E3 (parallel, different amounts) | `APPLEBILL` | Interleaved 2.99 + 0.99 monthly |
| E4 (parallel, same amount) | `MUSICBOX` | Two interleaved 10.99 monthly |
| E5 (alias duplicate) | `STREAMFLIX INTL` + `STREAMFLIXCOM` | Monthly, aliased to `streaming` |
| Free trial | `SECUREPASS` | 0.49 debit 14 days before first monthly 14.99 |
| Post-cancellation | `GYMPLUS` | 3 monthly 8.99 charges after cancellation date |
| Zombie candidates | `BEATSTREAM`, `PHOTOBOX`, `STASHBOX` | Have `last_used_date` entries in `[demo]` |
| Noise | Various fictional merchants | Salary credit, groceries (4×/month varying), transfers, one-off shops |

Total: ~320 rows over 6 months (2026-05-01 to 2026-10-31), plain dialect.

Generator uses `random.seed(42)`; output is fully deterministic. The `[demo]` section of
`config.toml` references these fictional names in `last_used_dates` and `cancellation_dates`.

---

## 11 — Test architecture

### 11.1 Conftest fixtures (`apps/zombie_subscriptions/tests/conftest.py`)

All fixtures use synthetic PII-safe data. Dates are passed explicitly; no `date.today()`.

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

Standard fixtures (counterparties are fictional merchants, not person names; person names only for salary rows):

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
| `ledger_with_post_cancellation` | 3 × 8.99 monthly + 1 × 8.99 after cancellation date for `"GYMPLUS"` |
| `ledger_with_zombie` | `ledger_with_recurring` with `last_used_date` before last 2 charges |

### 11.2 Hypothesis strategies

```python
from hypothesis import given, settings
from hypothesis import strategies as st
from decimal import Decimal
from datetime import date

def monthly_series_strategy(n_charges: int, base_amount: Decimal):
    """Generate a monthly series with date jitter ≤ 3 days and amounts within ±4% of base.

    ±4% is tighter than the ±10% AMOUNT_MATCH_RATIO used by _segment_by_price. This avoids
    flakiness: two amounts each at ±10% of the base can differ by up to 20% from each other,
    which would fail the stable check and may spuriously trigger price-increase detection.
    ±4% keeps every pair within 8% of each other — well inside the 10% cluster tolerance.
    """
    start = st.dates(min_value=date(2025, 1, 1), max_value=date(2026, 1, 1))
    jitters = st.lists(st.integers(-3, 3), min_size=n_charges-1, max_size=n_charges-1)
    amount_ratios = st.lists(
        st.decimals(min_value=Decimal("0.96"), max_value=Decimal("1.04"),
                    places=2, allow_nan=False, allow_infinity=False),
        min_size=n_charges, max_size=n_charges,
    )
    return st.builds(lambda s, j, r: _build_rows(s, j, r, base_amount), start, jitters, amount_ratios)
```

Key properties (all `@settings(max_examples=200)`):

| Test | Property |
|---|---|
| `test_monthly_series_always_detected` | Generated monthly series → exactly 1 recurring-charge alert. |
| `test_insufficient_occurrences_never_detected` | n < MIN_OCCURRENCES_MONTHLY → no alert. |
| `test_row_order_invariant` | Shuffled rows → same alerts (order-agnostic comparison). |
| `test_yearly_cost_equals_current_price_times_12` | `Alert.data["yearly_cost"] == str(round_to_cents(current_amount × 12))`. |
| `test_price_step_above_5pct_always_fires` | Series with one upward step ≥ 5% at any position → price-increase alert. |
| `test_price_step_below_5pct_never_fires` | Step < 5% → no price-increase alert. |
| `test_source_refs_subset_of_input` (all detectors) | `Alert.source_refs ⊆ ledger["source_ref"]`. |

---

## 12 — Open decisions

### OD-ZS-03 (resolved)

Resolved in §4: three-phase algorithm (price-bucketed pre-pass, extend-and-merge, leftover cadence
runs). Phase 1 uses stride-2 sub-runs within a bucket to detect same-price parallel series (E4),
eliminating the need for any separate deinterleaving step. The `_segment_by_price` function handles
stable, step-change (up or down), and noisy series.

### OD-ZS-05 — Hypothesis strategy for E3/E4 parallel series

The property test for "two parallel series are always detected separately" is implemented as a
Tier 1 acceptance test (not a Hypothesis property), to avoid the combinatorial complexity of
generating valid interleaved series in Hypothesis. Fixtures `ledger_with_duplicate_sub` (E4) and
`ledger_with_aliased_duplicate` (E5) cover these cases explicitly.

### OD-ZS-06 — `find_series` call cost across detectors

`find_series` is called independently by each of the 5 detectors. For a 300-row ledger with
~15 unique keys, this is ~5 × 15 = 75 calls. Each call is O(n²) per key where n ≤ ~30, so the
total is negligible (< 1 ms). No caching for v1. If the ledger grows beyond ~10 000 rows,
memoize `find_series` per `(key, ledger_content_hash)` or extract it to a shared pre-computation
step passed via `context`.
