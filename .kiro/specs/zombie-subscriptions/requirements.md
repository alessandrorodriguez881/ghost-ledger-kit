# zombie-subscriptions — Requirements

## Overview

`zombie-subscriptions` is App 1 of Ghost Ledger Kit. It targets **individuals** who want to audit
their personal bank-statement CSV for subscription charges they have forgotten, no longer use, or
are being charged for after cancellation.

The app is a **deterministic detector layer** built on top of `ledger-core`. It imports
`ledger_kit` (models, ingestion, registry, money helpers) without modifying any file in that
package. All user-facing output is produced by `apps/zombie_subscriptions/`.

---

## Guiding principles (app-level)

1. **Debit transactions only.** All five detectors operate exclusively on rows where
   `Transaction.flow == "debit"`. Credit rows are silently ignored by every detector.
2. **No invented figures.** Every number that appears in an alert or explanation is either copied
   verbatim from a source row or computed deterministically from source rows using
   `ledger_kit.utils.money` helpers only.
3. **Named constants, not magic numbers.** Every numeric threshold used by any detector is a
   module-level constant (`UPPER_SNAKE_CASE`) with a comment stating its business meaning.
4. **Source refs on every alert.** Every `Alert.source_refs` list must be non-empty and contain
   only `source_ref` values that exist in the input ledger.
5. **Yearly cost in every alert.** Every alert emitted by this app must include
   `Alert.data["yearly_cost"]` — a `Decimal` computed as `round_to_cents(median_amount × periods_per_year)` — plus the complete list of contributing `source_ref` values.

---

## 1 — Scope and inputs

- **REQ-ZS-01** The app accepts one bank-statement CSV file at a time via a Streamlit file-uploader
  or a synthetic demo fixture. It must also expose a **Load demo data** button that loads a
  bundled synthetic CSV from `data/samples/` so the app is fully usable without uploading a real
  file.
- **REQ-ZS-02** Ingestion is delegated entirely to `ledger_kit.ingestion`; the app must not
  re-implement CSV parsing or normalisation.
- **REQ-ZS-03** After ingestion, the app filters the ledger to `flow == "debit"` rows before
  passing it to any detector. Detectors receive only debit rows.
- **REQ-ZS-04** The app supports all dialects handled by `ledger_kit.ingestion.csv_reader`
  (plain and European) without additional dialect-specific code.

---

## 2 — Counterparty normalisation

- **REQ-ZS-05** Before grouping transactions into recurring series, each counterparty name is
  **normalised** to produce the **normalised counterparty key** used for grouping. The algorithm:
  1. Strip leading/trailing whitespace.
  2. Uppercase.
  3. Split into whitespace-separated tokens.
  4. Drop any token that contains a digit (removes per-charge reference numbers, card digits, phone
     numbers appended by the bank).
  5. From remaining tokens, remove all characters that are not ASCII letters or spaces.
  6. Collapse multiple spaces to a single space and strip again.
  7. If the result is non-empty, use it; otherwise use the string produced after step 5 applied to
     the original tokens (before step 4) to avoid discarding the entire key.

  Examples:
  - `"Streamflix Intl."` → `"STREAMFLIX INTL"`
  - `"STREAMFLIX.COM"` → `"STREAMFLIXCOM"`
  - `"BEATSTREAM P2A3B4C5"` → `"BEATSTREAM"` (token `P2A3B4C5` contains digits, dropped)
- **REQ-ZS-06** Normalisation is a pure helper function
  (`apps.zombie_subscriptions.detectors.normalise_counterparty`) with no side-effects.
- **REQ-ZS-07** An **alias list** maps one or more normalised counterparty keys to a single
  canonical service name. The alias list is user-editable at runtime (stored in the app's
  `config.toml` under `[aliases]` as `service_name = ["KEY1", "KEY2", …]`).
  - **Series grouping uses the normalised key only.** Alias resolution is applied *after* series
    are identified — it is used exclusively for display names, duplicate-subscription detection,
    cancellation-date lookups, and last-used-date lookups. Grouping by alias before series
    identification would merge two separately billed accounts (e.g. two streaming logins) into one
    irregular group, making duplicate detection impossible.
  - Example alias definition: `streaming = ["STREAMFLIX INTL", "STREAMFLIXCOM", "STREAMFLIX"]`

---

## 3 — Recurring-charge detector

### 3.1 Series identification

- **REQ-ZS-08** A **recurring series** is identified per normalised counterparty key (series grouping
  never uses aliases — see REQ-ZS-07). Within all debit rows for the same key, the detector finds
  the largest subset of rows whose **consecutive date gaps** all fall within the tolerance of exactly
  one supported interval type:

  | Interval type | Nominal days | Tolerance (±) | Module constant |
  |---|---|---|---|
  | Weekly | 7 | 3 days | `WEEKLY_NOMINAL_DAYS`, `INTERVAL_TOLERANCE_DAYS` |
  | Monthly | 30 | 3 days | `MONTHLY_NOMINAL_DAYS`, `INTERVAL_TOLERANCE_DAYS` |
  | Quarterly | 91 | 3 days | `QUARTERLY_NOMINAL_DAYS`, `INTERVAL_TOLERANCE_DAYS` |
  | Yearly | 365 | 3 days | `YEARLY_NOMINAL_DAYS`, `INTERVAL_TOLERANCE_DAYS` |

  `INTERVAL_TOLERANCE_DAYS: int = 3` is the single shared tolerance constant for all interval types.

- **REQ-ZS-09** *(OD-ZS-03 — series amount algorithm)* The amount criterion for including a row in
  a series is **not** a fixed ±10% envelope around the series median (that rule breaks on
  step-change price increases). The algorithm is deferred to `design.md` (OD-ZS-03) and must
  satisfy all of the following acceptance examples, each of which is a required test:

  | ID | Input | Expected output |
  |---|---|---|
  | E1 | 5 monthly charges of 12.99, then 1 charge of 15.99 for the same counterparty | One recurring series (all 6 rows). `yearly_cost` = 191,88 EUR (15.99 × 12). One price-increase alert: old 12.99, new 15.99, extra 36.00 per year. |
  | E2 | 3 monthly charges of 9.99, then 3 charges of 12.99 for the same counterparty | One series (all 6 rows). One price-increase alert: old 9.99, new 12.99. |
  | E3 | Same normalised key, two interleaved monthly series at 2.99 and 0.99 (like a billing platform charging two family members separately) | Two separate recurring series; no duplicate-subscription alert. |
  | E4 | Same normalised key, two interleaved monthly series each at 10.99 | Two separate recurring series; one duplicate-subscription alert (no aliases needed). |
  | E5 | STREAMFLIX INTL monthly + STREAMFLIXCOM monthly, alias `streaming = ["STREAMFLIX INTL","STREAMFLIXCOM"]` | Two separate series (one per key); one duplicate-subscription alert resolved via alias. |
  | E6 | Two charges 30 days apart from a supermarket, mixed varying amounts | No recurring-charge alert. |
  | E7 | Weekly charges from the same shop with varying amounts (e.g. grocery shopping) | No recurring-charge alert. |
  | E7b | 26 weekly supermarket charges between 40.00 and 150.00 over 6 months (deterministic fixture in design §4.8, including pairs of equal amounts 91 days apart) | No alerts of any kind. |

- **REQ-ZS-10** A group qualifies as a recurring series only if it meets the **minimum occurrence
  count** for its interval type:

  | Interval type | Minimum occurrences | Module constant |
  |---|---|---|
  | Weekly | 4 | `MIN_OCCURRENCES_WEEKLY` |
  | Monthly | 3 | `MIN_OCCURRENCES_MONTHLY` |
  | Quarterly | 2 | `MIN_OCCURRENCES_QUARTERLY` |
  | Yearly | 2 | `MIN_OCCURRENCES_YEARLY` |

  `MIN_OCCURRENCES_MONTHLY = 3` (not 2): with only 2 occurrences, any two similar card payments
  a month apart would qualify as a subscription.

- **REQ-ZS-10a** *(price levels and steps)* A **price level** is a set of amounts that all lie within
  `STABLE_AMOUNT_RATIO: Decimal = Decimal("0.02")` (2%) of their median. A cadence run is accepted as
  (1) a stable series (the whole run is one level), (2) a step-change series (exactly one split into
  two levels with different rounded medians; the step is recorded in either direction and its ratio
  is computed from the rounded medians), or (3) a variable bill (no step, every amount within
  `AMOUNT_MATCH_RATIO` of the median; `current_amount` is the median). Otherwise it is not a
  subscription. A 2-row run must be a single stable level. A step needs at least 2 rows on each
  side, except one single-row side at either end of the run when the other side has at least the
  interval minimum and the step lies within ±50% (`MAX_EDGE_STEP_RATIO`).
- **REQ-ZS-10b** *(no subscriptions from ordinary shopping)* A quarterly or yearly series is accepted
  only if its normalised key has no other debit rows between the series' first and last charge.
- **REQ-ZS-10c** An early or late step must be found wherever it falls: a step of 5–50% after any of
  the first 1–5 of 6 monthly charges yields exactly one series with one recorded step.

- **REQ-ZS-11** Multiple distinct series may exist under the same normalised key (see acceptance
  examples E3 and E4). For each identified series, the detector independently selects the interval
  type whose nominal gap best matches the series' median consecutive gap. The interval type
  is chosen per series, not per key.
- **REQ-ZS-12** The detector function signature is:
  ```python
  def detect_recurring_charges(
      ledger: pd.DataFrame,
      context: Mapping[str, Any],
  ) -> list[Alert]:
  ```
  User context keys read by this detector: `context.get("aliases")` → `dict[str, list[str]] | None`.
  Via CR-LC-1, the registry passes a `MappingProxyType`; the detector reads it but never mutates it.

### 3.2 Alert contract

- **REQ-ZS-13** For each identified series, the detector emits one `Alert` with:
  - `detector`: `"zs.recurring_charge"`
  - `severity`: `"info"`
  - `title`: `"Recurring charge detected: <canonical_name>"`
  - `source_refs`: all `source_ref` values for the transactions that form the series, sorted
    ascending by date.
  - `data`:
    ```python
    {
        "counterparty": str,            # canonical (alias-resolved if alias exists) display name
        "normalised_key": str,          # the normalised counterparty key used for grouping
        "interval_type": str,           # "weekly" | "monthly" | "quarterly" | "yearly"
        "current_amount": str,          # median of charges since the last price change, 2 d.p.
        "charge_count": int,            # number of transactions in the series
        "yearly_cost": str,             # round_to_cents(current_amount × periods_per_year), as str
        "first_charge_date": str,       # ISO 8601, YYYY-MM-DD
        "last_charge_date": str,        # ISO 8601, YYYY-MM-DD
        "is_active": bool,              # True if last_charge_date is within one nominal interval
                                        # + tolerance of the latest date in the ledger
    }
    ```

  **`yearly_cost` definition**: `round_to_cents(current_amount × periods_per_year)` where
  `current_amount` is the median of the charges **since the last price change** (or the median
  of all charges if no price change was detected). This ensures the yearly cost reflects what the
  user is *currently* paying, not a historical average.

  The `periods_per_year` multiplier:

  | Interval | Multiplier | Constant |
  |---|---|---|
  | Weekly | 52 | `PERIODS_PER_YEAR_WEEKLY` |
  | Monthly | 12 | `PERIODS_PER_YEAR_MONTHLY` |
  | Quarterly | 4 | `PERIODS_PER_YEAR_QUARTERLY` |
  | Yearly | 1 | `PERIODS_PER_YEAR_YEARLY` |

### 3.3 Active series definition

- **REQ-ZS-13a** A series is **active** if its `last_charge_date` is within
  `nominal_days + INTERVAL_TOLERANCE_DAYS` of the **latest date present in the ledger**. Detectors
  never read the system clock; "today" is always the maximum `date` value in the ledger DataFrame.

---

## 4 — Price-increase detector

- **REQ-ZS-14** The price-increase detector operates on each identified recurring series. It detects
  a **step change** in the series: a sustained shift to a new price level where the new level exceeds
  the previous level by more than `PRICE_INCREASE_MIN_RATIO: Decimal = Decimal("0.05")` (5%). The
  exact step-detection algorithm is defined in `design.md` (OD-ZS-03) and must satisfy acceptance
  examples E1 and E2 from REQ-ZS-09.
  - A step below 5% must never fire this detector (required Hypothesis property).
  - A single upward step of ≥ 5% at any position in the series must always fire it (required
    Hypothesis property; position includes the 1st and 2nd charge, see REQ-ZS-10c). With amount
    noise of ±0.5% the guaranteed bounds are ≥ 7% fires and ≤ 3.9% never fires; a noise-free
    step of exactly 5% fires.
- **REQ-ZS-15** The detector function signature:
  ```python
  def detect_price_increases(
      ledger: pd.DataFrame,
      context: Mapping[str, Any],
  ) -> list[Alert]:
  ```
  User context keys read: `context.get("aliases")`.
- **REQ-ZS-16** For each series with a detected price step, one `Alert` is emitted with:
  - `detector`: `"zs.price_increase"`
  - `severity`: `"warning"`
  - `title`: `"Price increase detected: <canonical_name>"`
  - `source_refs`: all `source_ref` values in the series, sorted ascending by date.
  - `data`:
    ```python
    {
        "counterparty": str,
        "old_median_amount": str,       # median of charges before the step, 2 d.p.
        "new_amount": str,              # median of charges after the step, 2 d.p.
        "extra_cost_per_year": str,     # round_to_cents((new – old) × periods_per_year), 2 d.p.
        "yearly_cost": str,             # round_to_cents(new_amount × periods_per_year), 2 d.p.
        "interval_type": str,
    }
    ```

---

## 5 — Duplicated-subscriptions detector

- **REQ-ZS-17** A **duplicated subscription** exists when **two or more distinct active recurring
  series** share the same canonical service name. Two series share a canonical name when:
  - Their normalised keys **resolve to the same canonical name via the alias list** (acceptance
    example E5), **regardless of their current amounts**, **or**
  - Their normalised keys are identical **and** their `current_amount` values are within
    `AMOUNT_MATCH_RATIO: Decimal = Decimal("0.10")` (10%) of each other (acceptance example E4:
    same key, two series at 10.99 each). Acceptance example E3 (same key, two series at 2.99
    and 0.99) does **not** fire the detector because the amounts differ by more than 10%.
  Only **active** series (per REQ-ZS-13a) count. A dormant series is not a duplicate.
- **REQ-ZS-18** The detector function signature:
  ```python
  def detect_duplicate_subscriptions(
      ledger: pd.DataFrame,
      context: Mapping[str, Any],
  ) -> list[Alert]:
  ```
  User context keys read: `context.get("aliases")`.
- **REQ-ZS-19** For each set of duplicated series, one `Alert` is emitted per group with:
  - `detector`: `"zs.duplicate_subscription"`
  - `severity`: `"warning"`
  - `title`: `"Duplicate subscription: <canonical_name>"`
  - `source_refs`: all `source_ref` values from all series in the group, sorted ascending by
    date.
  - `data`:
    ```python
    {
        "canonical_name": str,
        "series_count": int,                    # number of distinct series (≥ 2)
        "series_counterparties": list[str],     # normalised key per series
        "yearly_cost": str,                     # sum of yearly_cost of each series, 2 d.p.
    }
    ```
- **REQ-ZS-20** When no aliases are configured, this detector can still fire if the same
  normalised key has two or more active recurring series whose `current_amount` values are within
  `AMOUNT_MATCH_RATIO` of each other (acceptance example E4). It must not raise when aliases are
  `None` or empty.

---

## 6 — Free-trial-to-paid detector

- **REQ-ZS-21** A **free-trial-turned-paid** pattern is detected when a debit charge with an amount
  between `Decimal("0.01")` and `FREE_TRIAL_MAX_TOKEN_AMOUNT: Decimal = Decimal("1.00")` (inclusive)
  from a normalised key appears **1 to `TRIAL_MAX_DAYS_BEFORE_FIRST_CHARGE: int = 35` days before**
  the first full-price charge of a recognised recurring series for the same key.

  - The trial charge is **not** a member of the recurring series (it falls outside the regular
    interval cadence and has a sub-threshold amount).
  - Because ledger-core maps a `0.00` amount to `flow=credit`, zero-amount rows never appear in
    the debit-only ledger passed to this detector. Detecting free trials with no charge at all is
    **out of scope** (see §15 Non-goals).
- **REQ-ZS-22** The detector function signature:
  ```python
  def detect_free_trial_to_paid(
      ledger: pd.DataFrame,
      context: Mapping[str, Any],
  ) -> list[Alert]:
  ```
  User context keys read: `context.get("aliases")`.
- **REQ-ZS-23** For each qualifying (trial charge, series) pair, one `Alert` is emitted with:
  - `detector`: `"zs.free_trial_to_paid"`
  - `severity`: `"info"`
  - `title`: `"Free trial converted to paid: <canonical_name>"`
  - `source_refs`: the trial charge `source_ref` plus all `source_ref` values of the series,
    sorted ascending by date.
  - `data`:
    ```python
    {
        "counterparty": str,
        "trial_amount": str,           # trial charge amount, 2 d.p.
        "first_paid_amount": str,      # first series charge amount, 2 d.p.
        "trial_source_ref": str,       # source_ref of the trial charge
        "days_before_first_charge": int,  # gap between trial date and first series charge date
        "yearly_cost": str,            # round_to_cents(current_amount × periods_per_year), 2 d.p.
        "interval_type": str,
    }
    ```
  `yearly_cost` uses `current_amount` from the series (median of charges since last price change,
  per REQ-ZS-13).

---

## 7 — Charges-after-cancellation detector

- **REQ-ZS-24** The user may supply a **cancellation date** for one or more subscriptions. Any
  debit transaction whose normalised key resolves to that service (via alias or exact match) and
  whose date is strictly **after** the cancellation date is a post-cancellation charge. This
  includes rows that are **not** part of an active recurring series (after a cancellation, the
  cadence is often broken, so the series may no longer be detected).
- **REQ-ZS-25** The detector function signature:
  ```python
  def detect_charges_after_cancellation(
      ledger: pd.DataFrame,
      context: Mapping[str, Any],
  ) -> list[Alert]:
  ```
  User context keys read: `context.get("cancellation_dates")` → `dict[str, date] | None` mapping
  canonical service names to `datetime.date` objects; `context.get("aliases")`.
  When `cancellation_dates` is `None` or empty, the detector returns `[]`.
- **REQ-ZS-26** For each service with post-cancellation charges, one `Alert` is emitted with:
  - `detector`: `"zs.charges_after_cancellation"`
  - `severity`: `"critical"`
  - `title`: `"Charge after cancellation: <canonical_name>"`
  - `source_refs`: the `source_ref` values of all post-cancellation rows for that service, sorted
    ascending by date.
  - `data`:
    ```python
    {
        "counterparty": str,
        "cancellation_date": str,      # ISO 8601
        "post_cancellation_count": int,
        "total_charged_after": str,    # sum of the actual charge amounts, 2 d.p. — never estimated
        "yearly_cost": str,            # yearly_cost from the recurring-charge alert for this
                                       # service, or "0.00" if no active series
    }
    ```
  `total_charged_after` is the **sum of the actual `amount` fields** of the source rows after the
  cancellation date — never estimated.

---

## 8 — Zombie-status view (cost-since-last-used)

- **REQ-ZS-27** The user may supply a **last-used date** for one or more subscriptions. The app
  then computes the **cost since last used** for each such subscription: the sum of all actual
  debit charges from that counterparty/canonical service that occurred **strictly after** the
  last-used date.
- **REQ-ZS-28** Cost-since-last-used is a **view computation**, not a registered detector. It is
  computed by a helper function in `detectors/utils.py`:
  ```python
  def compute_zombie_cost(
      ledger: pd.DataFrame,
      last_used_dates: dict[str, date] | None,
      *,
      aliases: dict[str, list[str]] | None = None,
  ) -> list[ZombieCostResult]:
  ```
  where `ZombieCostResult` is:
  ```python
  @dataclass
  class ZombieCostResult:
      canonical_name: str
      last_used_date: date
      cost_since_last_used: Decimal    # sum of actual charge amounts from source rows
      source_refs: list[str]           # source_refs of every charge after last_used_date
      yearly_cost: Decimal             # current_amount × periods_per_year from the series alert
  ```
  The function never reads the system clock; it operates only on data present in the ledger.
- **REQ-ZS-29** `cost_since_last_used` must be the **sum of the `amount` fields of the actual
  rows** identified in `source_refs`. It must never be estimated, projected, or derived from a rate.
  All arithmetic uses `ledger_kit.utils.money` helpers.
- **REQ-ZS-30** If no charges exist after the last-used date — or the service has no rows in the
  ledger at all — `cost_since_last_used` is `Decimal("0.00")` and `source_refs` is an empty list.
  This result is still returned (not omitted) so the UI can display the tombstone with a zero cost.
  `last_used_dates=None` or empty returns `[]`. Results are grouped by canonical name: a service with
  two aliased keys yields one result (and `detect_charges_after_cancellation` one alert), while
  series are still found per normalised key.

---

## 9 — Resolved design decisions

### OD-ZS-01 — Resolved via CR-LC-1: context-aware detectors

All five detectors use the ledger-core registry signature
`(ledger: pd.DataFrame, context: Mapping[str, Any]) -> list[Alert]`
introduced by CR-LC-1. The registry wraps the context in `types.MappingProxyType` before dispatch,
so detectors can read but never mutate it. The app passes user input through context keys:

| Context key | Type | Used by |
|---|---|---|
| `"aliases"` | `dict[str, list[str]] \| None` | All five detectors |
| `"cancellation_dates"` | `dict[str, date] \| None` | `zs.charges_after_cancellation` |
| `"last_used_dates"` | `dict[str, date] \| None` | `compute_zombie_cost` (view helper, not a registered detector) |

The app builds a context dict from `st.session_state` and calls:
```python
results = run_all(debit_ledger, namespace="zs", context=ctx)
```
No `ledger_kit` file needs to know about app-specific context keys.

### OD-ZS-02 — Resolved via CR-LC-1: namespace filtering

The registry's `run_all(ledger, namespace="zs", context=ctx)` runs only detectors whose names
start with `"zs."`. The app calls `auto_discover("apps.zombie_subscriptions.detectors")` at
startup, populating only the `zs.*` namespace. A future shared Streamlit process can call
`run_all(ledger, namespace="zs")` or `run_all(ledger, namespace="pi")` independently, with no
structural change to the registry.

### OD-ZS-03 — Series amount algorithm (to be designed in design.md)

The amount criterion for including a row in a series and detecting price changes must satisfy
acceptance examples E1–E7 from REQ-ZS-09. The algorithm must handle:
- Stable series (same price throughout): all rows included.
- Single step-change (E1: 12.99 → 15.99, E2: 9.99 → 12.99): series spans the step; the step is
  detected as a price increase.
- Parallel series at different amounts (E3, E4): two separate series, not one irregular series.
- Noisy series (varying amounts, E6, E7): not detected as recurring unless the variance is
  consistent with the interval tolerance.

The design document must specify the algorithm precisely (e.g. a segmentation approach, a
run-length encoding of price levels, or a clustering approach) and prove it satisfies each
acceptance example.

---

## 10 — Explanation layer

- **REQ-ZS-31** The app uses `ledger_kit.explainer.explain(alert, rows, fallback_template=…)` to
  produce a plain-English explanation for each alert, quoting only figures that appear in
  `Alert.data` or in the referenced source rows (as required by Finance Rule 1 and CR-LC-2).
- **REQ-ZS-32** `explainer.explain` handles the system-prompt construction, the no-invention
  constraint, and the number guard internally (CR-LC-2). The app passes only the alert, the cited
  rows, and the per-detector fallback template string; it does not construct prompts itself.
- **REQ-ZS-33** When no `OPENAI_API_KEY` is present, `explainer.explain` returns the filled
  fallback template (monetary values formatted with `format_amount`) without any network call.
  The app requires no special handling for the no-key case; it is transparent.
- **REQ-ZS-34** The fallback template for each detector (passed to `explain_with_meta` as `fallback_template`).
  Monetary placeholders use the `{key:money}` syntax (formatted via `format_amount`); non-monetary
  values use `{key}` (plain string); `{source_refs}` is the special comma-joined refs placeholder.

  | Detector | Template |
  |---|---|
  | `zs.recurring_charge` | `"You have been charged {charge_count} times by {counterparty} at a current price of {current_amount:money} ({interval_type}), totalling approximately {yearly_cost:money} per year. Source: {source_refs}."` |
  | `zs.price_increase` | `"The {counterparty} charge increased from {old_median_amount:money} to {new_amount:money}, adding {extra_cost_per_year:money} to your yearly cost. Source: {source_refs}."` |
  | `zs.duplicate_subscription` | `"You are paying for {canonical_name} through {series_count} separate accounts, totalling {yearly_cost:money} per year. Source: {source_refs}."` |
  | `zs.free_trial_to_paid` | `"Your {counterparty} free trial ({trial_amount:money}) converted to a paid subscription at {first_paid_amount:money}. Yearly cost: {yearly_cost:money}. Source: {source_refs}."` |
  | `zs.charges_after_cancellation` | `"{counterparty} charged you {post_cancellation_count} time(s) totalling {total_charged_after:money} after your cancellation on {cancellation_date}. Source: {source_refs}."` |

---

## 11 — Streamlit UI

- **REQ-ZS-35** The UI theme is a **Halloween graveyard**: dark background (`#1a1a2e`), pale stone
  text, muted green and amber accents. All styling is applied via Streamlit's `st.markdown` with
  inline CSS or a custom `style.css` injected via `st.markdown(..., unsafe_allow_html=True)`.
  No external CSS framework is introduced.
- **REQ-ZS-36** Each **zombie subscription** (a recurring series for which the user has supplied a
  `last_used_date`) is rendered as a **tombstone card** containing:
  - The subscription name (canonical service name).
  - "Died on: {last_used_date}" (the last-used date supplied by the user).
  - "Cost since then: {cost_since_last_used}" (formatted as European locale amount with
    currency).
  - "Yearly cost: {yearly_cost}" (from `Alert.data["yearly_cost"]`).
  - The cited `source_refs`, displayed as a collapsible list.
- **REQ-ZS-37** Other alerts (non-zombie) are displayed below the tombstone section in a flat
  list grouped by severity (critical → warning → info). Each alert shows its title, detector
  name, explanation text, a **guard badge**, and a collapsible row view of the cited source rows.
  The guard badge shows:
  - 🤖 ✓ *LLM text verified by number guard* — when `Explanation.source == "llm"`.
  - 📋 *Template (no API key)* — when `source == "fallback"` and `OPENAI_API_KEY` is absent.
  - ⚠️ *LLM answer rejected: invented number {X}* — when `source == "fallback"` and
    `rejected_numbers` is non-empty (the guard fired).
- **REQ-ZS-37a** The sidebar contains a **Simulate a hallucinating LLM** toggle. When enabled,
  the app injects a `HallucinatingStubClient` (a client that appends a known-foreign number such
  as `99999.99` to every LLM response) instead of the real OpenAI client. This lets judges
  without an API key watch the number guard reject an invented figure in real time. The badge
  then shows ⚠️ with the injected number.
- **REQ-ZS-38** A **Load demo data** button loads `data/samples/zombie_demo_statement.csv`
  (a dedicated synthetic demo CSV produced by `scripts/generate_samples.py` with a fixed seed,
  approximately 300–400 rows spanning 6 months). The `[demo]` section of `config.toml`
  pre-populates the alias, last-used date, and cancellation date fields so that clicking
  **Load demo data** immediately shows:
  - At least 3 tombstones (subscriptions with a `last_used_date`).
  - At least one alert of each type (recurring charge, price increase, duplicate subscription,
    free-trial-to-paid, charges-after-cancellation).
- **REQ-ZS-39** All monetary amounts displayed in the UI use the European locale format from
  `ledger_kit.utils.money.format_amount`.
- **REQ-ZS-40** The UI provides input widgets (text inputs or a sidebar form) for the user to
  enter:
  - Last-used dates per subscription (for zombie status).
  - Cancellation dates per subscription (for the charges-after-cancellation detector).
  - Alias mappings (to detect duplicate subscriptions).
  These inputs are stored in `st.session_state` (widget keys) and passed as the `context` dict to
  `run_all(debit_ledger, namespace="zs", context=ctx)` on each run. The fields are
  pre-populated from the `[demo]` section of `config.toml` by an `on_click` callback of the
  **Load demo data** button (design §7); assigning widget keys after the widgets exist would raise
  `StreamlitWidgetAlreadyInstantiatedError`.
- **REQ-ZS-41** The app must be launchable with:
  ```
  streamlit run apps/zombie_subscriptions/app.py
  ```
  on a clean clone, both locally and on Streamlit Community Cloud, with no mandatory environment
  variables other than optionally `OPENAI_API_KEY`.

  **Path bootstrap** (resolved in design.md): the first lines of `app.py` insert the repository
  root onto `sys.path` if not already present, so that `import ledger_kit` and
  `import apps.zombie_subscriptions` resolve correctly without requiring an editable install:

  ```python
  import sys, pathlib
  _ROOT = pathlib.Path(__file__).resolve().parents[2]
  if str(_ROOT) not in sys.path:
      sys.path.insert(0, str(_ROOT))
  ```

  A root-level `requirements.txt` lists all runtime dependencies (no `-e .` entry) for
  Streamlit Community Cloud, which installs from it at deploy time. The app folder must **not**
  contain its own `requirements.txt`: Community Cloud reads the file next to the entry point first
  and it would hide the root one.

---

## 12 — Configuration (`apps/zombie_subscriptions/config.toml`)

- **REQ-ZS-42** All numeric thresholds (`INTERVAL_TOLERANCE_DAYS`, `MIN_OCCURRENCES_*`,
  `PRICE_INCREASE_MIN_RATIO`, `FREE_TRIAL_MAX_TOKEN_AMOUNT`, `TRIAL_MAX_DAYS_BEFORE_FIRST_CHARGE`,
  etc.) live **only** as named constants in the detector module source code. They are **not**
  duplicated in `config.toml`. Having two sources of truth for thresholds is explicitly
  prohibited; changing a threshold is a one-line code edit.
- **REQ-ZS-43** The `[aliases]` section of `config.toml` maps canonical service names to lists
  of normalised counterparty keys (see REQ-ZS-07). Example:
  ```toml
  [aliases]
  streaming = ["STREAMFLIX INTL", "STREAMFLIXCOM", "STREAMFLIX"]
  music = ["BEATSTREAM", "BEATSTREAM PREMIUM"]
  ```
- **REQ-ZS-44** The `[demo]` section of `config.toml` holds:
  - `csv_path`: path to the zombie demo CSV (default `"data/samples/zombie_demo_statement.csv"`).
  - `aliases`: alias overrides for the demo dataset (so Load demo data shows duplicate alerts).
  - `last_used_dates`: a table of `canonical_name = "YYYY-MM-DD"` entries (at least 3).
  - `cancellation_dates`: a table of `canonical_name = "YYYY-MM-DD"` entries (at least 1).

  All names are fictional brands. **Every alias member and every key of `last_used_dates` and
  `cancellation_dates` must equal a normalised counterparty key that occurs in the demo CSV** (a
  mismatch such as `GYM PLUS` vs `GYMPLUS`, or a typo like `NETLIXINTL`, silently disables the
  cancellation and duplicate cases). Date strings are converted with `date.fromisoformat`.

  Example:
  ```toml
  [demo]
  csv_path = "data/samples/zombie_demo_statement.csv"

  [demo.aliases]
  streaming = ["STREAMFLIX INTL", "STREAMFLIXCOM"]

  [demo.last_used_dates]
  "BEATSTREAM" = "2026-07-15"
  "PHOTOBOX" = "2026-06-20"
  "STASHCRATE" = "2026-08-10"

  [demo.cancellation_dates]
  "GYMPLUS" = "2026-07-31"
  ```

---

## 13 — Package structure

The following files are the **definitive** list for this app. They supersede the illustrative list
in `.kiro/steering/structure.md` for the `zombie-subscriptions` spec only.

```
apps/zombie_subscriptions/
├── __init__.py
├── app.py                          # Streamlit entry point (path bootstrap at top)
├── config.toml                     # aliases, demo inputs (no thresholds)
├── settings.py                     # load config.toml, demo inputs, sidebar text parse/format
├── explain_support.py              # TEMPLATES (REQ-ZS-34), HallucinatingStubClient (REQ-ZS-37a)
├── detectors/
│   ├── __init__.py                 # auto_discover; exposes run_zs_detectors convenience wrapper
│   ├── utils.py                    # normalise_counterparty, resolve_alias, series helpers,
│   │                               # compute_zombie_cost, ZombieCostResult
│   ├── recurring_charge.py         # detect_recurring_charges — registered as "zs.recurring_charge"
│   ├── price_increase.py           # detect_price_increases — registered as "zs.price_increase"
│   ├── duplicate_subscription.py   # detect_duplicate_subscriptions — "zs.duplicate_subscription"
│   ├── free_trial_to_paid.py       # detect_free_trial_to_paid — "zs.free_trial_to_paid"
│   └── charges_after_cancellation.py  # detect_charges_after_cancellation — "zs.charges_after_cancellation"
└── tests/
    ├── conftest.py                 # shared fixtures
    ├── test_zs_recurring_charge.py
    ├── test_zs_price_increase.py
    ├── test_zs_duplicate_subscription.py
    ├── test_zs_free_trial_to_paid.py
    ├── test_zs_charges_after_cancellation.py
    ├── test_zs_settings.py
    └── test_zs_demo_e2e.py         # end-to-end: demo data triggers all detectors + ≥3 tombstones
```

Additional data file (generated by `scripts/generate_samples.py --mode zombie-demo --seed 42`):
```
data/samples/zombie_demo_statement.csv   # ~300-400 rows, 6 months, planted patterns E1-E7 + demo dates
```

Root-level file for Streamlit Community Cloud:
```
requirements.txt   # pins all deps needed for apps/zombie_subscriptions; no -e . line
```

---

## 14 — Testing requirements

- **REQ-ZS-45** All three test tiers (Tier 1 normal-case, Tier 2 edge-case, Tier 3 property-based)
  must be provided for each of the five detectors and for `compute_zombie_cost`, following the
  strategy in `.kiro/steering/testing.md`.
- **REQ-ZS-46** The standard fixtures must be provided in
  `apps/zombie_subscriptions/tests/conftest.py`:

  | Fixture name | Description |
  |---|---|
  | `empty_ledger` | `pd.DataFrame` with canonical schema, zero rows |
  | `single_row_ledger` | One valid debit `Transaction` row |
  | `clean_ledger_10` | 10 debit rows with no anomalies for any detector |
  | `ledger_with_recurring` | Minimal fixture (≥ `MIN_OCCURRENCES_MONTHLY` rows) triggering `zs.recurring_charge` for a single counterparty |
  | `ledger_with_price_increase` | A series satisfying acceptance example E1 (5 × 12.99 then 1 × 15.99) |
  | `ledger_with_duplicate_sub` | Satisfies acceptance example E4 (same key, two parallel monthly series at 10.99) |
  | `ledger_with_aliased_duplicate` | Satisfies acceptance example E5 (STREAMFLIX INTL + STREAMFLIXCOM with alias) |
  | `ledger_with_free_trial` | A debit of 0.99 followed within 35 days by a monthly recurring series from the same key |
  | `ledger_with_post_cancellation` | A recurring series plus one charge strictly after a supplied cancellation date |
  | `ledger_with_zombie` | A recurring series with a `last_used_date` in the middle of the series |
  | `ledger_with_weekly_shopping` | Acceptance example E7b (26 weekly charges, design §4.8) |

  Fixture counterparties are fictional merchants, never person names.

- **REQ-ZS-47** The acceptance examples E1–E7b from REQ-ZS-09 are each required as an explicit
  named test (Tier 1 or Tier 2), e.g. `test_zs_acceptance_e1_step_change_detected`.

- **REQ-ZS-48** Mandatory Hypothesis properties (all with `@settings(max_examples=200)`):

  | Property | File | Description |
  |---|---|---|
  | `test_monthly_series_always_detected` | `test_zs_recurring_charge.py` | A generated monthly series with date jitter ≤ 3 days and amounts consistent with the OD-ZS-03 algorithm is always detected. |
  | `test_insufficient_occurrences_never_detected` | `test_zs_recurring_charge.py` | A series with fewer than `MIN_OCCURRENCES_MONTHLY` charges never produces a recurring-charge alert. |
  | `test_row_order_invariant` | `test_zs_recurring_charge.py` | Shuffling the ledger row order never changes the set of alerts returned. |
  | `test_yearly_cost_equals_current_price_times_12` | `test_zs_recurring_charge.py` | For any detected monthly series, `Alert.data["yearly_cost"]` equals `round_to_cents(current_amount × 12)`. |
  | `test_price_step_above_5pct_always_fires` | `test_zs_price_increase.py` | With amount noise within ±0.5% of each level, an upward step of 7–50% after any of the first 1–5 of 6 charges fires exactly one price-increase alert. |
  | `test_price_step_exactly_5pct_fires` | `test_zs_price_increase.py` | A noise-free step of exactly 5% at any position fires. |
  | `test_price_step_below_5pct_never_fires` | `test_zs_price_increase.py` | With noise within ±0.5%, a step of at most 3.9% never fires. |
  | `test_stable_series_never_fires_price_increase` | `test_zs_price_increase.py` | A series at one level (noise within ±0.5%) never fires. |
  | `test_early_step_fires_exactly_once` | `test_zs_price_increase.py` | A noise-free step of 5–50% at any position k = 1..5 of 6 monthly charges gives exactly one series and one price-increase alert. |
  | `test_source_refs_subset_of_input` | each detector test file | `Alert.source_refs` is always a subset of the input ledger's `source_ref` values. |

- **REQ-ZS-49** Tests must pass dates explicitly (fixed literal dates). The system clock must
  never be read inside a test or detector. `freezegun` is not required; "today" is always derived
  from the maximum `date` in the ledger (REQ-ZS-13a).

- **REQ-ZS-50** All test fixtures use synthetic PII-safe data (Finance Rule 5). No real IBAN,
  real name, or real transaction data may appear in any test file.

- **REQ-ZS-51** Coverage across `apps/zombie_subscriptions/` must not fall below **80%** as
  enforced by `pytest --cov=apps/zombie_subscriptions --cov-fail-under=80`.

- **REQ-ZS-52** An end-to-end test in `test_zs_demo_e2e.py` must assert that loading
  `data/samples/zombie_demo_statement.csv` with the `[demo]` context from `config.toml`
  produces at least one alert of each of the five detector types **and** at least 3
  `ZombieCostResult` entries with non-zero `cost_since_last_used`. It must also assert that every
  alias member and every date-map key of the `[demo]` section equals a normalised counterparty key
  of the demo CSV, that every demo date parses with `date.fromisoformat`, and that no alert cites
  a row of the grocery/noise merchants.

---

## 15 — Non-goals

- This app does not parse PDF bank statements.
- This app does not connect to any live banking API; input is always a CSV file.
- The LLM layer must not raise, modify, or dismiss alerts; it produces explanation text only.
- This app does not recommend specific financial actions to the user.
- Machine-learning or probabilistic scoring is explicitly excluded; all detection is deterministic.
- **Free trials with no charge at all** (i.e. the trial period does not generate any bank debit)
  are out of scope. The free-trial-to-paid detector requires an actual debit row (amount ≥ 0.01)
  as evidence of the trial; a zero-amount "charge" never reaches the debit-only detector because
  ledger-core maps `amount == 0.00` to `flow = credit`.

---

## 16 — Amendments

- **A-ZS-01** *(session 10b, from the benchmark spec, D-BM-10)* The read, normalise, debit-filter
  and detector steps of the page move out of `app.py` into one public function,
  `run_pipeline(source_name, data, *, aliases, cancellation_dates, cpi=None, cache=None)` in
  `apps/zombie_subscriptions/settings.py`, mirroring `run_pipeline` of the phantom app. `app.py`
  and `scripts/benchmark.py` both call it, so the benchmark measures exactly what the app runs.
  **No behaviour change:** REQ-ZS-01 to REQ-ZS-52 hold unchanged, the sha256 parse cache stays
  (it is the optional `cache` argument), and the demo still shows 3 tombstones and 19 alerts.

  *Acceptance.* `run_pipeline("zombie_demo_statement.csv", demo_bytes, aliases=..., cancellation_dates=...)`
  returns `len(alerts) == 19`; the `CSV` and `Real formats` demos give the same alert count; a
  credit row is not in `debit_ledger`; a statement with a quarantined row returns it in
  `quarantine`; with a `cache` dict the second call does not read the bytes again.
