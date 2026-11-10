# vampire-fees — Design

## Overview

This document turns `requirements.md` into modules, signatures, algorithms, data keys, templates,
demo tables and test architecture. `tasks.md` refers to its sections.

The app is a pure consumer of `ledger_kit`. Every `Alert` it produces is the type of
`ledger_kit/models.py`; every reader, the registry, `money.py`, the explainer and the UI helpers
are used as they are. **Nothing in `ledger_kit/` or in the other apps changes** (§11 explains how
this was checked at design time and what to do if it stops being true).

Facts about the library that this design relies on, with the file that proves each. The
implementing agent shall re-read these before coding and stop if one is false (§11, rule L):

| # | Fact | Where |
|---|---|---|
| F1 | `read_bank_statement(source, *, source_file=...)` returns `(transactions, quarantined)` for CSV and Norma 43, picked by content. | `ledger_kit/ingestion/sniffer.py` |
| F2 | The Norma 43 reader puts `common_concept:<cc>` and `own_concept:<nnn>` in `Transaction.tags`; the CSV reader sets no tags (`[]`). | `norma43_reader.py` `_transaction`; `csv_reader.py` |
| F3 | `normalise(transactions)` returns a frame with `CANONICAL_COLUMNS` including `tags` (a list, optional) and `date` as `datetime.date`, `amount` as `Decimal`. | `ledger_kit/ingestion/normaliser.py` |
| F4 | `register("vf.name")` accepts `<namespace>.<detector>`; `run_all(ledger, namespace="vf", context=...)` passes a read-only mapping. | `ledger_kit/detectors/registry.py` |
| F5 | `explain_with_meta(alert, rows, fallback_template=..., client=...)`; placeholders `{key}`, `{key:money}`, `{key:pct}`, `{source_refs}`; `:money` formats as EUR. | `ledger_kit/explainer.py` |
| F6 | `money.py` offers `round_to_cents`, `sum_amounts`, `percent_change`, `round_percent`, `format_amount`, `format_percent`. | `ledger_kit/utils/money.py` |
| F7 | `reference_app.py` offers `SEVERITY_BADGES`, `count_by_severity`, `format_for_display`, `quarantine_table`, `rows_for_refs`. | `ledger_kit/ui/reference_app.py` |
| F8 | `control_check_messages(records)` and `sniff_format(data)` / `format_label(kind)` are public. | `norma43_reader.py`, `sniffer.py` |
| F9 | The explainer sends the LLM only `date, amount, flow, currency, counterparty, source_ref` of the cited rows; never `description`. | `ledger_kit/explainer.py` `_LLM_ROW_COLUMNS` |
| F10 | The generator offers `BankRow`, `render_bank_csv`, `render_norma43`, `N43_CONCEPT_BY_DESCRIPTION`, `MODE_HANDLERS`. | `scripts/generate_samples.py` |

---

## 1 — Module map

```
apps/vampire_fees/
├── __init__.py
├── app.py                     # Streamlit entry (sys.path bootstrap, CSS, render loop)
├── config.toml                # [vocabulary] fee/overdraft/interest/exclude, [demo] paths
├── settings.py                # load_config, load_vocabulary, demo inputs, run_pipeline, view models
├── explain_support.py         # TEMPLATES, template_for, HallucinatingStubClient
├── detectors/
│   ├── __init__.py            # auto_discover("apps.vampire_fees.detectors")
│   ├── utils.py               # CONSTANTS, FeeVocabulary, fold_tokens, classify_fee, extract_fees,
│   │                          # series_key, find_run, ppy_for, sorted refs, statement span
│   ├── recurring_fee.py       # detect_recurring_fees        -> "vf.recurring_fee"
│   ├── fee_increase.py        # detect_fee_increases         -> "vf.fee_increase"
│   ├── overdraft_cost.py      # detect_overdraft_cost        -> "vf.overdraft_cost"
│   └── fee_summary.py         # detect_fee_summary           -> "vf.fee_summary"
└── tests/                     # §9
```

No `requirements.txt` in the app. Test and session prefix: `vf`. Shared library names used:
`ledger_kit.models.Alert`, `ledger_kit.detectors.{register, auto_discover, run_all,
DetectorResult, loaded_source_refs}`, `ledger_kit.utils.money`, `ledger_kit.explainer`,
`ledger_kit.ingestion.{sniffer, normaliser, norma43_reader}`, `ledger_kit.ui.reference_app`.
No private (`_name`) library name is imported.

---

## 2 — Constants, vocabulary and their reasons

### 2.1 Constants (`detectors/utils.py`)

```python
from decimal import Decimal

# --- What is considered -------------------------------------------------------------------
STATEMENT_CURRENCY: str = "EUR"            # explainer ':money' is EUR-only; no mixed sums (DN-VF-07)
FEE_CONCEPTS: tuple[str, ...] = ("16", "17")  # Norma 43 common concepts accepted as fees (REQ-VF-07)
CONCEPT_TAG_PREFIX: str = "common_concept:"   # tag written by the Norma 43 reader

# --- Recurring interval (days) -------------------------------------------------------------
MONTHLY_NOMINAL_DAYS: int = 30
QUARTERLY_NOMINAL_DAYS: int = 91
YEARLY_NOMINAL_DAYS: int = 365
MONTHLY_TOLERANCE_DAYS: int = 3
QUARTERLY_TOLERANCE_DAYS: int = 3
YEARLY_TOLERANCE_DAYS: int = 5
MIN_CHARGES_MONTHLY: int = 3
MIN_CHARGES_QUARTERLY: int = 2
MIN_CHARGES_YEARLY: int = 2
PERIODS_PER_YEAR_MONTHLY: int = 12
PERIODS_PER_YEAR_QUARTERLY: int = 4
PERIODS_PER_YEAR_YEARLY: int = 1

# --- Severities and rises -------------------------------------------------------------------
RECURRING_FEE_WARNING_YEARLY_COST: Decimal = Decimal("60.00")
FEE_INCREASE_MIN_RATIO: Decimal = Decimal("0.05")
FEE_STABLE_RATIO: Decimal = Decimal("0.02")
FEE_INCREASE_CRITICAL_RATIO: Decimal = Decimal("0.50")
OVERDRAFT_CRITICAL_TOTAL: Decimal = Decimal("100.00")

# --- Summary ---------------------------------------------------------------------------------
DAYS_PER_YEAR: int = 365
SUMMARY_MIN_SPAN_DAYS: int = 90
SUMMARY_WARNING_YEARLY_EQUIVALENT: Decimal = Decimal("200.00")
```

### 2.2 Reason for each value

The values are decisions of the design, not facts of the law. The reviewer may change any of them
in one line; the tests name the boundaries, so a change updates the test first (`testing.md`).

| Constant | Value | Reason |
|---|---|---|
| `STATEMENT_CURRENCY` | `"EUR"` | `:money` and the display rules are EUR; a USD fee would be shown as EUR. Skipping is honest, converting would invent a figure. |
| `FEE_CONCEPTS` | 16, 17 | Given by the product brief: AEB Annex 2 concepts 16 (stamp duty and brokerage) and 17 (interest, fees and taxes). |
| `*_NOMINAL_DAYS` | 30 / 91 / 365 | A month, a quarter and a year in days; same nominal values as `zombie_subscriptions`, chosen independently here (apps do not import each other). |
| `MONTHLY_TOLERANCE_DAYS` | 3 | Calendar months are 28 to 31 days; weekends and bank holidays move a booking by up to three days. 27 to 33 holds every real month (28 included). |
| `QUARTERLY_TOLERANCE_DAYS` | 3 | A quarter is 90 to 92 days; 88 to 94 holds them with the same booking slack. The ranges of monthly (27–33), quarterly (88–94) and yearly (360–370) never overlap, so the type is unambiguous. |
| `YEARLY_TOLERANCE_DAYS` | 5 | A year is 365 or 366 days and annual fees are often charged "in the month of the anniversary"; five days of slack covers a weekend plus a leap day. |
| `MIN_CHARGES_MONTHLY` | 3 | Two monthly charges can be two one-off commissions a month apart (the demo plants that case). |
| `MIN_CHARGES_QUARTERLY/YEARLY` | 2 | A statement of one to two years shows one or two such charges; requiring three would hide every annual fee. The gap check (91 ± 3, 365 ± 5) is the guard against coincidence. |
| `PERIODS_PER_YEAR_*` | 12 / 4 / 1 | Definition of the interval; `yearly_cost = current_amount × periods`. |
| `RECURRING_FEE_WARNING_YEARLY_COST` | 60.00 | 5.00 EUR a month: a fee that costs more than a coffee a week is worth a second look; below it the alert is information. Boundary inclusive (5.00 × 12 = 60.00 → warning). |
| `FEE_INCREASE_MIN_RATIO` | 0.05 | Rounding of a percentage fee or an index-linked fee moves a charge by a few cents. A 5 % step is the smallest rise that is not rounding noise (the same step is used by `zs.price_increase`; chosen independently). |
| `FEE_STABLE_RATIO` | 0.02 | The new level "holds" when later charges stay within 2 % of it; a single spike (AE-VF-19) is not a new price. |
| `FEE_INCREASE_CRITICAL_RATIO` | 0.50 | A fee that rises by half or more is out of line with any inflation-linked update. |
| `OVERDRAFT_CRITICAL_TOTAL` | 100.00 | More than a year of a typical maintenance fee (about 60 to 80 EUR); at that point the overdraft is the biggest bank cost of the statement. |
| `DAYS_PER_YEAR` | 365 | Plain year; no leap-year correction (the equivalent is an annualisation, labelled as such). |
| `SUMMARY_MIN_SPAN_DAYS` | 90 | Under a quarter, one bank fee cycle can be missing or doubled; a yearly figure would be a guess (Finance Rule 1). |
| `SUMMARY_WARNING_YEARLY_EQUIVALENT` | 200.00 | About 16.67 EUR a month in bank fees. Above that the total is heavier than the largest single recurring fee a normal account carries. |

### 2.3 `config.toml`

```toml
# vampire-fees configuration: the fee vocabulary and the demo paths. No threshold lives here
# (detectors/utils.py holds them as named constants). Phrases are folded on load: accents and
# case do not matter, and a phrase matches whole words only.

[vocabulary]
# A debit whose counterparty or description holds one of these phrases is a fee.
fee = ["comision", "comisiones", "cuota de mantenimiento", "gastos", "fee", "fees",
       "commission", "commissions", "maintenance"]
# Overdraft words: also a fee; the row gets kind "overdraft".
overdraft = ["descubierto", "intereses deudores", "overdraft"]
# Inside an overdraft row, these words make it an overdraft interest (otherwise an overdraft fee).
interest = ["intereses", "interest"]
# A row with one of these words is not a bank fee (professional fees); a concept 16/17 still wins.
exclude = ["notaria", "notario", "notary", "gestoria", "abogado", "lawyer", "honorarios"]

[demo]
csv_path = "data/samples/vampire_demo_statement.csv"
n43_path = "data/samples/vampire_demo_statement.n43"
```

---

## 3 — Decisions

| Id | Decision | Reason |
|---|---|---|
| DN-VF-01 | Detectors receive the full ledger, not only debits (unlike `zs`). | The statement span (summary) uses every row; a refund is a credit and must be seen to be ignored. `extract_fees` filters. |
| DN-VF-02 | A fee is `concept in {16, 17}` **or** a vocabulary match. A concept other than 16/17 never vetoes a vocabulary match. | Banks book fees under many concepts (a custody fee under 03 "direct debit"); vetoing would lose them. The cost is that a card purchase at a shop whose name is a fee word is a false positive, accepted and documented. |
| DN-VF-03 | Matching is whole-token, not substring. | `fee` in `Feelgood`, `comision` in `comisionista`. Substring matching would turn the vocabulary into a source of false alarms. Cost: no stemming, so plurals are listed. |
| DN-VF-04 | An `exclude` vocabulary beats the fee vocabulary but not a concept. | A notary, lawyer or gestor invoice says "gastos" and is not a bank fee. A concept 16/17 is the bank's own classification, so it is not overruled. Whether it recurs is irrelevant: the payer is not a bank. |
| DN-VF-05 | Refunds are not netted; totals are gross. | Matching a refund to the fee it cancels needs a rule that can be wrong. The page says "Refunds are not subtracted." (REQ-VF-45). Open question Q1 in the hand-over. |
| DN-VF-06 | A recurring **run** is the longest regular suffix, not the whole group. | One irregular early row must not hide a fee that has been regular for a year (AE-VF-13). A fee that stopped long before the end of the statement still alerts, with its `last_charge_date`. |
| DN-VF-07 | Only EUR rows are analysed; others are counted and reported. | F5: `:money` is EUR-only. |
| DN-VF-08 | Overdraft rows go to `vf.overdraft_cost` only, never to `vf.recurring_fee` or `vf.fee_increase`. | Overdraft interest changes every period by design; reporting it as a "rising recurring fee" is noise and double counting. The summary still counts them once. |
| DN-VF-09 | `Alert.data` does not record how a row was recognised (concept or words). | Otherwise the CSV and Norma 43 alerts of the same statement would differ (REQ-VF-53). |
| DN-VF-10 | `yearly_equivalent` is absent for statements shorter than 90 days. | REQ-VF-29, Finance Rule 1. The template has a variant without it. |
| DN-VF-11 | The vocabulary is in `config.toml`; thresholds are not. | `structure.md` says app config holds aliases and demo inputs, no thresholds. A vocabulary is data (it says what a row is), and it must be editable without code. A test checks that `config.toml` has no constant name. |
| DN-VF-12 | One alert per recurring run, per rise, and one each for the overdraft and the summary. | The page shows one coffin per recurring run; the summary is the single "total" alert the brief asks for. |
| DN-VF-13 | The benchmark (`scripts/benchmark.py`, `data/benchmark/`) is not extended. | Out of scope for the template-speed measurement; the Benchmark page keeps showing two apps. |
| DN-VF-14 | Session-state keys all start with `vf_`, including the source and the caches. | `zombie_subscriptions` uses the bare keys `source` and `ingestion_cache`; sharing them in a showcase would mix the apps. |
| DN-VF-15 | Review answer 1: the agent keeps `@context7` in `tools`; it gets no shell and no web tool. | Library documentation is useful and read-only; commands stay a human step and the open web is not needed. |
| DN-VF-16 | Review answer 2: running `scripts/generate_samples.py` is a human step, as written. | The agent cannot run commands; it ends with the exact command for the human. |
| DN-VF-17 | Review answer 3: totals stay gross and the page says so. | Same as DN-VF-05: no netting rule that can be wrong; the page shows "Refunds are not subtracted." |
| DN-VF-18 | Review answer 4: the severity constants are accepted with the reasons given in §2.2. | They are named constants (Rule 7), changeable in one line, and the tests name the boundaries. |
| DN-VF-19 | Review answer 5: vocabulary false positives are handled by editing `config.toml`, as written. | The vocabulary is data (DN-VF-11); no code change is needed to add or remove a word. |
| DN-VF-20 | Review answer 6: accepted as written in the design. | No change to the design text. |
| DN-VF-21 | Review answer 7: accepted as written in the design. | No change to the design text. |

---

## 4 — Algorithms (`detectors/utils.py`)

### 4.1 Text folding and vocabulary

```python
def fold_tokens(text: object) -> tuple[str, ...]:
    """NFKD, drop combining marks, casefold, non-alphanumerics -> spaces, split."""

@dataclass(frozen=True)
class FeeVocabulary:
    fee: tuple[tuple[str, ...], ...]
    overdraft: tuple[tuple[str, ...], ...]
    interest: tuple[tuple[str, ...], ...]
    exclude: tuple[tuple[str, ...], ...]

EMPTY_VOCABULARY = FeeVocabulary((), (), (), ())

def build_vocabulary(table: Mapping[str, Any]) -> FeeVocabulary:
    """Fold every phrase of the four keys; ValueError naming the key if missing/empty/invalid."""

def contains_phrase(tokens: tuple[str, ...], phrases) -> bool:
    """True when any phrase appears as consecutive tokens."""
```

`fold_tokens(None)` and NaN give `()`. `settings.load_vocabulary(config)` reads
`config["vocabulary"]` and calls `build_vocabulary`.

### 4.2 Classification and extraction

```python
@dataclass(frozen=True)
class Fee:
    source_ref: str
    source_row: int
    date: date
    amount: Decimal
    counterparty: str          # raw text of the row
    description: str           # raw text of the row
    kind: Literal["overdraft", "other"]
    overdraft_interest: bool   # only meaningful when kind == "overdraft"
    key: str                   # series_key(counterparty, description)

def concept_of(tags: object) -> str | None:
    """The cc of the first 'common_concept:<cc>' tag; None for no tags, None or NaN."""

def classify_fee(row: Mapping, vocabulary: FeeVocabulary) -> Fee | None:
    # 1. flow != "debit" or currency != STATEMENT_CURRENCY -> None
    # 2. cc in FEE_CONCEPTS -> fee
    # 3. exclude phrase in counterparty or description tokens -> None
    # 4. fee or overdraft phrase in counterparty or description tokens -> fee
    # 5. otherwise None
    # kind: overdraft when an overdraft phrase matches (counterparty or description); the
    # interest flag when an interest phrase matches in the same row.

def extract_fees(ledger: pd.DataFrame, vocabulary: FeeVocabulary) -> list[Fee]:
    """Fee rows ordered by (date, source_row); duplicate source_ref: first wins; empty frame: []."""

def skipped_currency_rows(ledger: pd.DataFrame) -> int:
    """Rows whose currency is not STATEMENT_CURRENCY (REQ-VF-06)."""

def statement_span(ledger: pd.DataFrame) -> tuple[date, date] | None:
    """First and last date of the EUR rows (all flows); None when there are none."""
```

Phrases are searched in the counterparty and in the description **separately** (a phrase never
spans the two fields).

### 4.3 Series and runs

```python
def series_key(counterparty: object, description: object) -> str:
    """'<cp tokens>|<desc tokens>', tokens containing a digit dropped."""

@dataclass(frozen=True)
class Interval:
    name: Literal["monthly", "quarterly", "yearly"]
    nominal_days: int
    tolerance_days: int
    min_charges: int
    periods_per_year: int

INTERVALS: tuple[Interval, ...]          # monthly, quarterly, yearly (in this order)

def classify_gap(days: int) -> Interval | None: ...

def find_run(rows: Sequence[Fee]) -> tuple[Interval, list[Fee]] | None:
    """rows ordered by (date, source_row). Interval of the last gap, then extend backwards while
    gaps match the same interval. None when fewer than 2 rows, no match, or len < min_charges."""

def yearly_cost(amount: Decimal, interval: Interval) -> Decimal:
    """round_to_cents(amount * interval.periods_per_year)."""

def sorted_refs(fees: Iterable[Fee]) -> list[str]:
    """source_refs ordered by (date, source_row), unique."""
```

Gaps use `(later.date - earlier.date).days`; two rows on the same date have gap 0, which matches
no interval and ends the run.

### 4.4 Detector outlines

Every detector: `vocabulary = context.get("vocabulary", EMPTY_VOCABULARY)`; `fees =
extract_fees(ledger, vocabulary)`; empty → `[]`.

- `vf.recurring_fee`: group `kind == "other"` fees by `key` (groups sorted by key for a stable
  order); `find_run`; one `Alert` per run.
- `vf.fee_increase`: same runs; scan `i` from the end down to 1; first `i` with
  `new - old >= old * FEE_INCREASE_MIN_RATIO` and all later rows within
  `abs(a - new) <= new * FEE_STABLE_RATIO`; one `Alert` per run with such an `i`.
- `vf.overdraft_cost`: all `kind == "overdraft"` fees; split by `overdraft_interest`; one `Alert`.
- `vf.fee_summary`: all fees; span from `statement_span(ledger)`; one `Alert`.

Alerts of one detector are returned ordered by their first cited `(date, source_row)`, then by
title (deterministic).

---

## 5 — Alert data

All values are `str`, `int` or `list[str]` (REQ-VF-32). Money is `str(round_to_cents(x))`.
`counterparty` and `description` are the raw text of the **last** row of the run (verbatim).

### 5.1 `vf.recurring_fee`

| Key | Type | Value |
|---|---|---|
| `counterparty`, `description` | str | raw text of the last row |
| `interval_type` | str | `monthly`, `quarterly` or `yearly` |
| `charge_count` | int | rows in the run |
| `current_amount` | str | amount of the last row |
| `yearly_cost` | str | `round_to_cents(current_amount * periods_per_year)` |
| `first_charge_date`, `last_charge_date` | str | ISO dates of the first and last row of the run |

Title: `Recurring <interval_type> fee: <counterparty> · <description>`.
Severity: REQ-VF-19. `source_refs`: every row of the run.

### 5.2 `vf.fee_increase`

| Key | Type | Value |
|---|---|---|
| `counterparty`, `description`, `interval_type` | str | as above |
| `old_amount`, `new_amount` | str | `amount[i-1]`, `amount[i]` |
| `increase_percent` | str | `str(round_percent(percent_change(old, new)))`, e.g. `"30.0"` |
| `increase_date`, `old_charge_date` | str | dates of rows `i` and `i-1` |
| `extra_cost_per_year` | str | `round_to_cents((new - old) * periods_per_year)` |
| `yearly_cost` | str | `round_to_cents(new * periods_per_year)` |

Title: `Fee increase: <counterparty> · <description>`. Severity: REQ-VF-23.
`source_refs`: the two rows `i-1` and `i`.

### 5.3 `vf.overdraft_cost`

| Key | Type | Value |
|---|---|---|
| `interest_count`, `fee_count` | int | overdraft interest rows, overdraft fee rows |
| `interest_total`, `fee_total` | str | `round_to_cents(sum_amounts(...))` of each group (`"0.00"` for an empty group) |
| `total` | str | `round_to_cents(sum_amounts(all overdraft amounts))` |
| `first_charge_date`, `last_charge_date` | str | earliest and latest overdraft row |

Title: `Overdraft cost on this statement`. Severity: REQ-VF-26. `source_refs`: every overdraft row.

### 5.4 `vf.fee_summary`

| Key | Type | Value |
|---|---|---|
| `fee_count` | int | all fee rows |
| `total_fees` | str | `round_to_cents(sum_amounts(all fee amounts))` |
| `first_date`, `last_date` | str | statement period (all EUR rows) |
| `span_days` | int | `(last - first).days + 1` |
| `yearly_equivalent` | str | **only when** `span_days >= SUMMARY_MIN_SPAN_DAYS`: `round_to_cents(total * DAYS_PER_YEAR / span_days)` |

Title: `Bank fees on this statement`. Severity: REQ-VF-30. `source_refs`: every fee row.

---

## 6 — Explanation support (`explain_support.py`)

```python
TEMPLATES: dict[str, str] = {
    "vf.recurring_fee": (
        "{counterparty} charged you a {interval_type} fee of {current_amount:money} "
        "({description}), {charge_count} times between {first_charge_date} and "
        "{last_charge_date}, about {yearly_cost:money} per year. Source: {source_refs}."
    ),
    "vf.fee_increase": (
        "The {counterparty} fee ({description}) rose from {old_amount:money} to "
        "{new_amount:money} on {increase_date}, an increase of {increase_percent:pct}, "
        "adding {extra_cost_per_year:money} to the yearly cost. Source: {source_refs}."
    ),
    "vf.overdraft_cost": (
        "Your overdraft cost {total:money} between {first_charge_date} and {last_charge_date}: "
        "{interest_count} interest charges totalling {interest_total:money} and {fee_count} fees "
        "totalling {fee_total:money}. Source: {source_refs}."
    ),
    "vf.fee_summary": (
        "Between {first_date} and {last_date} ({span_days} days) your statement shows "
        "{fee_count} bank fees totalling {total_fees:money}, about {yearly_equivalent:money} "
        "per year. Source: {source_refs}."
    ),
}
FEE_SUMMARY_NO_YEARLY_TEMPLATE: str = (
    "Between {first_date} and {last_date} ({span_days} days) your statement shows "
    "{fee_count} bank fees totalling {total_fees:money}. Source: {source_refs}."
)

def template_for(alert: Alert) -> str:
    """TEMPLATES[alert.detector]; the no-yearly variant for a summary without yearly_equivalent."""

class HallucinatingStubClient: ...   # same shape as the other apps; INJECTED_NUMBER = "99999.99"
```

The stub answers `"This fee costs you 99999.99 EUR per year."`. Templates contain no literal digit
and no advice. `description` is quoted from the data of the alert, so it is a named key (Finance
Rule 1); it is not sent to an LLM (F9), which only matters for the guard, not for the template.

---

## 7 — Demo data

### 7.1 Generator (`scripts/generate_samples.py`, new mode `vampire-demo`)

New names, no existing name changes:

```python
VAMPIRE_DEMO_FILE = "vampire_demo_statement.csv"
VAMPIRE_DEMO_N43_FILE = "vampire_demo_statement.n43"
VAMPIRE_DEMO_START = date(2025, 1, 2)          # opening credit
VAMPIRE_DEMO_END = date(2026, 10, 30)          # closing card purchase
VAMPIRE_NOISE_PER_MONTH = 6
VAMPIRE_NOISE_DAYS = (3, 27)                   # inclusive, keeps the span fixed
VAMPIRE_BANK = "BANCO FICTICIO"

def build_vampire_planted_rows() -> list[BankRow]: ...     # literal tables of §7.2
def build_vampire_noise_rows(seed) -> list[BankRow]: ...   # random.Random(seed) only
def build_vampire_demo_rows(seed=DEFAULT_SEED) -> list[BankRow]:
    """sorted(planted + noise, key=lambda r: r.day) — stable, planted first."""
def build_vampire_demo_csv(seed=DEFAULT_SEED) -> str:       # render_bank_csv(rows, "plain")
def build_vampire_demo_n43(seed=DEFAULT_SEED) -> bytes:     # render_norma43(rows, mode=1)
def run_vampire_demo(args) -> int:                          # writes both files, prints "wrote ..."
MODE_HANDLERS["vampire-demo"] = run_vampire_demo            # + the --help text of --seed/--out-dir
```

`N43_CONCEPT_BY_DESCRIPTION` gets these extra entries (the writer picks the concept by exact
description; the existing entries and the SEPA path are untouched):

| Description | Concept |
|---|---|
| `Comisión mantenimiento cuenta`, `Comisión anual tarjeta débito`, `Comisión por descubierto`, `Intereses deudores`, `Comisión transferencia inmediata`, `Comisión emisión cheque`, `Commission foreign payment`, `Devolución comisión transferencia`, `Abono intereses` | `17` |
| `Comisión custodia valores` | `16` |

`Transferencia gastos escritura` and `Transfer from savings` fall to `04` through the existing
"starts with Transfer" rule; `Card purchase` is `12`, `Payroll` `15`, `Monthly subscription` `03`.
Amounts are written as text; no money is computed in the generator except what `render_norma43`
already does through `money.py`. Noise amounts are built from integer cents with `rng.randint`
and written as `f"-{cents // 100}.{cents % 100:02d}"`, never through `float`.

Noise: for each of the 22 months (2025-01 to 2026-10) six rows `Card purchase` at a shop drawn from
`("Mercado Central Demo", "Café del Puerto", "Tienda Luna", "Farmacia Sol", "Gasolinera Norte",
"Papelería Azul", "Librería Poniente")`, day `rng.randint(3, 27)`, amount `rng.randint(300, 9500)`
cents. No shop name contains a vocabulary phrase (a test checks this for seeds 0 to 20).

### 7.2 Planted tables (literal)

All amounts are debits unless marked **credit**. Bank rows use counterparty `BANCO FICTICIO`.

| Id | Rows | Description | Dates | Amount |
|---|---|---|---|---|
| A1 | 12 | Comisión mantenimiento cuenta | 5th of each month 2025-01 … 2025-12 | 5.00 |
| A2 | 10 | Comisión mantenimiento cuenta | 5th of each month 2026-01 … 2026-10 | 6.50 |
| B | 7 | Comisión custodia valores | 2025-03-31, 2025-06-30, 2025-09-30, 2025-12-31, 2026-03-31, 2026-06-30, 2026-09-30 | 9.00 |
| C | 2 | Comisión anual tarjeta débito | 2025-02-14, 2026-02-16 | 30.00 |
| D1 | 4 | Intereses deudores | 2025-06-30 / 2025-09-30 / 2026-03-31 / 2026-06-30 | 12.40 / 7.85 / 22.10 / 18.65 |
| D2 | 3 | Comisión por descubierto | 2025-06-18, 2026-03-20, 2026-06-15 | 15.00 |
| E1 | 4 | Comisión transferencia inmediata | 2025-04-09, 2025-07-22, 2026-02-03, 2026-08-27 | 1.50 |
| E2 | 2 | Comisión emisión cheque | 2025-05-02, 2025-06-01 | 4.00 |
| F | 1 | Commission foreign payment | 2025-10-14 | 11.25 |
| H1 | 1 | Card purchase, counterparty `Feelgood Market` | 2025-08-19 | 23.40 |
| H2 | 1 | Devolución comisión transferencia, **credit** | 2025-04-10 | 1.50 |
| H3 | 1 | Abono intereses, **credit** | 2026-06-30 | 0.84 |
| H4 | 1 | Transferencia gastos escritura, counterparty `Notaría Ana García` | 2026-04-17 | 412.60 |
| S | 22 | Monthly subscription, counterparty `STREAMFLIX INTL` | 10th of each month 2025-01 … 2026-10 | 9.99 |
| P | 22 | Payroll, counterparty `Luminar Estudio S.L.`, **credit** | 28th of each month 2025-01 … 2026-10 | 1850.00 |
| O | 1 | Transfer from savings, counterparty `Ahorro Ana García`, **credit** | 2025-01-02 | 800.00 |
| Z | 1 | Card purchase, counterparty `Papelería Azul` | 2026-10-30 | 19.90 |

Why each case is there:

- A: a fee that rises 30 % (`vf.recurring_fee` and `vf.fee_increase`), twenty-two months.
- B: a quarterly fee under concept 16 (stamp duty and brokerage in the Norma 43 file).
- C: a yearly fee, two charges 367 days apart.
- D1, D2: the overdraft (interest and fees), kept out of the recurring detector.
- E1: commissions with irregular gaps (104, 196, 205 days): fees, but no series.
- E2: two commissions 30 days apart: below `MIN_CHARGES_MONTHLY`.
- F: an English commission, one-off.
- H1: `fee` inside `Feelgood` (REQ-VF-10). H2: refund of a fee (credit, concept 17). H3: interest
  paid to the customer (credit, concept 17). H4: notary, excluded (DN-VF-04). S: recurring but not
  a fee. P and O are the credits and the first date; Z is the last date.

Row counts: planted 1 + 22 + 22 + (22 + 7 + 2) + 7 + 7 + 4 + 1 = 95 plus noise 132 = **227**;
credits 1 + 22 + 1 + 1 = 25; debits **202**.

### 7.3 Expected result (literal; the e2e test pins it, not recomputed from the detectors)

Statement period: 2025-01-02 to 2026-10-30, `span_days = 667`
(`2025-01-02 → 2026-10-30` is 666 days apart).

| # | Detector | Severity | Key data | Refs |
|---|---|---|---|---|
| 1 | `vf.recurring_fee` (A) | warning | `monthly`, `charge_count 22`, `current_amount "6.50"`, `yearly_cost "78.00"`, `first_charge_date "2025-01-05"`, `last_charge_date "2026-10-05"` | 22 |
| 2 | `vf.recurring_fee` (B) | info | `quarterly`, `7`, `"9.00"`, `yearly_cost "36.00"`, `2025-03-31`, `2026-09-30` | 7 |
| 3 | `vf.recurring_fee` (C) | info | `yearly`, `2`, `"30.00"`, `yearly_cost "30.00"`, `2025-02-14`, `2026-02-16` | 2 |
| 4 | `vf.fee_increase` (A) | warning | `old_amount "5.00"`, `new_amount "6.50"`, `increase_percent "30.0"`, `increase_date "2026-01-05"`, `old_charge_date "2025-12-05"`, `extra_cost_per_year "18.00"`, `yearly_cost "78.00"` | 2 |
| 5 | `vf.overdraft_cost` | critical | `interest_count 4`, `interest_total "61.00"`, `fee_count 3`, `fee_total "45.00"`, `total "106.00"`, `first_charge_date "2025-06-18"`, `last_charge_date "2026-06-30"` | 7 |
| 6 | `vf.fee_summary` | warning | `fee_count 45`, `total_fees "379.25"`, `first_date "2025-01-02"`, `last_date "2026-10-30"`, `span_days 667`, `yearly_equivalent "207.54"` | 45 |

Checks of the arithmetic (also tested as plain `Decimal` sums in the e2e test):
A = 12 × 5.00 + 10 × 6.50 = 125.00; B = 63.00; C = 60.00; D = 61.00 + 45.00 = 106.00;
E1 = 6.00; E2 = 8.00; F = 11.25; total 125.00 + 63.00 + 60.00 + 106.00 + 6.00 + 8.00 + 11.25 =
**379.25**; rows 22 + 7 + 2 + 7 + 4 + 2 + 1 = **45**; yearly equivalent
379.25 × 365 / 667 = 207.5356… → **207.54**. Severities: 1 critical, 3 warning (rows 1, 4, 6),
2 info. The page shows three coffins with yearly costs `78,00 EUR`, `36,00 EUR` and `30,00 EUR`.

The e2e test derives the expected `source_refs` from the generated rows (the index or line of
each planted row found by `(day, description, amount)`), not from detector output.

Both formats: 227 rows read, 0 quarantined; Norma 43 control totals are written by `render_norma43`
(opening balance default), so the reader's control checks pass.

---

## 8 — Settings, pipeline and page

### 8.1 `settings.py` (no Streamlit import)

```python
DEMO_FORMATS: dict[str, DemoFormat] = {"CSV": "csv", "Norma 43": "n43"}
def load_config(path) -> dict
def load_vocabulary(config) -> FeeVocabulary
def vocabulary_lines(vocabulary_config) -> list[str]            # for the read-only expander
@dataclass(frozen=True) class DemoInputs: statement_bytes, statement_name
def demo_inputs(config, root, fmt) -> DemoInputs
def apply_demo(state, demo) -> None                             # sets vf_source, vf_demo_loaded
def ingest_statement(name, data, cache=None) -> (ledger, quarantine)   # read_bank_statement + normalise
@dataclass(frozen=True) class Pipeline: ledger, quarantine, skipped_currency, results
    alerts property
def run_pipeline(name, data, *, vocabulary, cache=None) -> Pipeline   # run_all(namespace="vf", ...)
def statement_caption(name, kind, rows, quarantined, skipped) -> str
def rule_sentences(kind) -> list[str]                           # REQ-VF-45
def guard_badge(explanation, *, has_api_key) -> GuardBadge      # labels as in the other apps
def group_alerts_by_severity(alerts) -> dict
def markdown_safe(text) -> str
@dataclass(frozen=True) class CoffinView: counterparty, description, interval, current_amount,
    yearly_cost, source_refs
def coffin_view(alert) -> CoffinView        # reads alert.data only, format_amount for money
@dataclass(frozen=True) class SummaryView: fee_count, total_fees, yearly_equivalent  (str)
def summary_view(alerts) -> SummaryView | None
```

`vocabulary` passed to `run_pipeline` is the `FeeVocabulary`; it reaches the detectors as
`context={"vocabulary": vocabulary}`.

### 8.2 `app.py`

Same skeleton as `apps/zombie_subscriptions/app.py` (bootstrap, CSS, `_init_state`,
`_render_sidebar`, `_keep_widgets`, `main`, `__main__` guard). Keys: `vf_load_demo`,
`vf_hallucinate`, `vf_explanations`, `vf_demo_format`, `vf_upload_statement`, `vf_kept`,
`vf_source`, `vf_ingestion_cache`, `vf_demo_loaded`. `WIDGET_KEYS = (vf_hallucinate,
vf_demo_format)`. `main()` order: set page config, inject CSS, init state, sidebar, title, source
check, pipeline, caption and rule sentences, metrics, quarantine, coffins, alerts.

### 8.3 Theme (page CSS only; `.streamlit/config.toml` is not edited)

```css
.vf-coffin { background: linear-gradient(180deg, #3a1520 0%, #2a0f16 100%);
  border: 2px solid #9b1c31; color: #e8dcc0; padding: 26px 20px 20px 20px; margin-bottom: 8px;
  text-align: center; box-shadow: 0 6px 14px rgba(0,0,0,.55);
  clip-path: polygon(30% 0, 70% 0, 100% 18%, 88% 100%, 12% 100%, 0 18%); }
.vf-title { color: #c2334d; font-weight: 700; letter-spacing: .08em; }
.vf-cost  { color: #c2334d; font-size: 1.25rem; font-weight: 700; }
.vf-line  { font-size: .95rem; margin: 2px 0; }
.vf-badge { display:inline-block; padding:2px 10px; border-radius:12px; font-size:.85rem;
  border:1px solid #9b1c31; }
```
plus the four guard-badge classes (`vf-badge-llm`, `-template`, `-unavailable`, `-rejected`).
`clip-path` is cosmetic: a test asserts that the CSS block holds the red accent and the polygon;
the text of a card is the tested part. Note that `clip-path` also clips the card's border; this is
accepted.

Coffin card text: `🧛 <counterparty>`, `<description>`, `<interval label>`, `Now <current_amount>`,
`Drains <yearly_cost> a year`. Interval labels: `every month`, `every quarter`, `every year`.

---

## 9 — Test architecture

All tests in `apps/vampire_fees/tests/`; app prefix `vf_`; shared `tests/` only for the agent test
and the pinned lists.

| File | Content |
|---|---|
| `conftest.py`, `vf_builders.py` | `make_ledger(rows)` with canonical columns and explicit dates; row builder `fee_row(...)`; fixtures `empty_ledger`, `single_row_ledger`, `clean_ledger_10`, `ledger_with_monthly_fee`, `ledger_with_fee_increase`, `ledger_with_overdraft`, `ledger_with_one_off_fees`, `vocabulary` (the default one), strategies for Hypothesis |
| `test_vf_scaffold.py` | package importable; no `requirements.txt`; no import of another app or of a private `ledger_kit` name (AST); `config.toml` has no threshold constant name; `apps/vampire_fees` has no file reading the clock |
| `test_vf_utils_normalise.py` | `fold_tokens`, `build_vocabulary`, `contains_phrase`, `series_key` (AE-VF-08), `concept_of` |
| `test_vf_classify.py` | AE-VF-01 … 07, `extract_fees` order and duplicate, `skipped_currency_rows`; property: credit never fee, no word and no concept never fee |
| `test_vf_series.py` | `classify_gap` boundaries 27/28, 33/34, 88/89, 94/95, 360/361, 370/371; `find_run` (AE-VF-12, 13, 16); `yearly_cost` |
| `test_vf_recurring_fee.py` | AE-VF-09 … 16 + three tiers |
| `test_vf_fee_increase.py` | AE-VF-17 … 20 + three tiers |
| `test_vf_overdraft_cost.py` | AE-VF-21 … 23 + three tiers |
| `test_vf_fee_summary.py` | AE-VF-24 … 26 + three tiers + total-equals-cited-rows property |
| `test_vf_registry.py` | the four names, in namespace `vf`, `auto_discover` idempotent, `EXPECTED_NAMES` |
| `test_vf_explain_support.py` | a template per detector, placeholders ⊆ data keys, AE-VF-27, stub client accepted/rejected by the guard, 99999.99 rejected |
| `test_vf_settings.py` | `load_config`, `load_vocabulary` errors, `demo_inputs`, `coffin_view`, `summary_view`, `guard_badge`, captions |
| `test_vf_demo_generator.py` | determinism per seed, seed changes only noise, literal tables, no vocabulary phrase in noise (seeds 0 to 20), committed files equal fresh output, existing modes unchanged |
| `test_vf_demo_e2e.py` | §7.3 pinned literally, row counts, expected refs derived from rows |
| `test_vf_real_formats.py` | CSV and Norma 43 demo give equal alerts (REQ-VF-53); concept-only path on a Norma 43 file built by the generator from a row whose words are not fee words |
| `test_vf_app_logic.py` | pure helpers and headless `AppTest` runs of `app.py`: empty state, CSV demo (3 coffins, 6 alerts), Norma 43 demo, hallucination switch shows the rejected badge, uploaded file |

Property tests use `@settings(max_examples=200)`, no function-scoped fixtures, no `register` in the
body. Registry-sensitive tests use `_snapshot_registry` / `_restore_registry` (tests may; the app
may not import private names). The concept-only unit test of `test_vf_real_formats.py` writes a
statement with `render_norma43` and a row `BankRow(..., "TARJ 0042", ...)` to prove that concept 17
alone makes a fee when read back through `read_bank_statement`; the generator is imported from
`scripts/` the way the other app tests do (`importlib` on the file path).

---

## 10 — Existing files changed

| File | Change |
|---|---|
| `scripts/generate_samples.py` | new mode and builders (§7.1); extra entries in `N43_CONCEPT_BY_DESCRIPTION`; module docstring line |
| `streamlit_app.py` | `PageSpec("Vampire Fees", "🧛", "vampire-fees", "apps/vampire_fees/app.py")`; Home text for three apps and a blurb; the entry page still imports no app |
| `tests/test_showcase_app.py` | `PAGE_TITLES`, page list expectations, Home text, add the Vampire page run |
| `tests/test_showcase_requirements.py` | `APPS` becomes three apps; the "never import each other" test checks every pair |
| `tests/test_generate_samples.py` | the new mode is implemented and writes both files |
| `README.md` | apps table: one row for Vampire Fees |
| `data/samples/README.md` | section for the vampire demo |
| `.gitattributes` | `data/samples/vampire_demo_statement.csv -text` (the `.n43` is covered by `data/samples/*.n43`) |
| `.kiro/steering/structure.md` | layout tree: `apps/vampire_fees/`, test files, demo files, generator mode |
| `.kiro/steering/testing.md` | coverage command adds `--cov=apps/vampire_fees` |

Nothing else. The theme file, `requirements.txt`, `pyproject.toml` and the benchmark are untouched.

---

## 11 — Library decisions (the template claim)

### 11.1 Library gaps found at design time

**None.** Each need was checked against the code (facts F1 to F10): the concept tag exists, the
readers are routed by content, the registry takes any namespace, `money.py` has the percent and
sum helpers (a product of an amount by a count is `Decimal * int` followed by `round_to_cents`,
exactly as `zombie_subscriptions` does), the explainer has `:money` and `:pct`, and the UI helpers
cover severity counts, cited rows and quarantine tables.

**Rule L.** If the implementation finds a gap, the agent stops and records it here as
`DN-VF-L<n>`: what is missing, evidence (file, line), the smallest library change, what the app
does instead, and whether the claim "no library change" still holds. The agent never edits the
library. The reviewer decides.

| Id | Gap | Status |
|---|---|---|
| — | none found | — |

### 11.2 Limits of the library, worked around inside the app (not changes)

| Id | Limit | Workaround |
|---|---|---|
| DN-VF-07 | `:money` formats every amount as EUR | rows in other currencies are not analysed and are counted on the page |

### 11.3 Code copied from another app because the library does not offer it (REQ-VF-60)

These are real duplications. They are the first candidates for a future `ledger_kit` helper; this
app copies them so that the claim "needs no library change" is measured honestly.

| Id | Copied | Source in another app |
|---|---|---|
| C1 | `HallucinatingStubClient` | `apps/zombie_subscriptions/explain_support.py` |
| C2 | `GuardBadge`, `guard_badge`, the four `BADGE_*` labels | `apps/zombie_subscriptions/settings.py` |
| C3 | `markdown_safe` | `apps/zombie_subscriptions/settings.py` |
| C4 | `group_alerts_by_severity` | `apps/zombie_subscriptions/settings.py` |
| C5 | `ingest_statement` with hash cache | `apps/zombie_subscriptions/settings.py` |
| C6 | widget keep/restore (`_keep_widgets`, `_restore_widgets`) | `apps/zombie_subscriptions/app.py` |
| C7 | sorted source refs by `(date, source_row)` | `apps/zombie_subscriptions/detectors/utils.py` |

"Copied" means written again in `apps/vampire_fees/`, not imported (apps must not import each
other). The copy count is part of what the reviewer records in the last task.

---

## 12 — Limits of the app (shown honestly)

- A fee word in a merchant name that is a whole word (`GASTOS GOURMET`, `Garage Maintenance Ltd`)
  is a false positive; the editable vocabulary is the remedy, not code (DN-VF-02, DN-VF-03).
- A bank fee that has none of the words and no concept 16/17 (for example only `TARJ 0042` in a
  CSV) is not seen. A Norma 43 file sees it by its concept.
- Refunds are not netted (DN-VF-05). Statements shorter than 90 days have no yearly equivalent.
- Only EUR is analysed (DN-VF-07).
- The app finds fees; it does not say whether a fee is fair or what to do about it (Finance Rule 8).
