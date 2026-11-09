# benchmark — Design

Section numbers are referenced by `tasks.md`. Decisions carry an id `D-BM-nn` and a reason (§7).
Facts below were read from the code and specs at the start of this work; nothing was run. Where
a behaviour is only inferred it is marked *(inferred)*.

## 1 Layout and data flow

```
scripts/generate_benchmark.py   seeded scenarios + labels (stdlib + ledger_kit.utils.money only)
scripts/benchmark.py            runner: pipelines, matching, metrics, results.json, benchmark.md, CLI
data/benchmark/results.json     committed output (generated)
docs/benchmark.md               committed output (generated from results.json)
streamlit_app.py                + Benchmark page (reads results.json)
tests/test_benchmark_generator.py   tests/test_benchmark_matching.py
tests/test_benchmark_runner.py      tests/test_benchmark_page.py
```

```
build_scenario(seed, app, i) ──► files (CSV text) + labels + negatives + context
        │
        ▼  bytes
zombie: zombie settings.run_pipeline(name, data, aliases, cancellation_dates, cpi) → results
phantom: phantom settings.run_pipeline(invoices, suppliers, payments, as_of) → results
        │
        ▼  AlertRecord(scenario, type, refs, detector)
match(alerts, labels) ──► tp / fp / fn ──► metrics ──► results.json ──► benchmark.md, page
```

`scripts/` is not a package: tests load both files by path (`importlib.util.spec_from_file_location`,
as `test_generate_samples.py` does). `benchmark.py` inserts the repository root and its own folder
into `sys.path` (the same bootstrap `generate_samples.py` uses) and imports `generate_benchmark`.

## 2 Generator (`scripts/generate_benchmark.py`)

### 2.1 Model

```python
@dataclass(frozen=True)
class Label:      id: str; scenario: str; type: str; rows: tuple[str, ...]; context_rows: tuple[str, ...]
@dataclass(frozen=True)
class Negative:   id: str; scenario: str; kind: str; rows: tuple[str, ...]
@dataclass(frozen=True)
class Scenario:   id: str; app: str; noise_only: bool; files: Mapping[str, str];
                  context: Mapping[str, Any]   # aliases, cancellation_dates / as_of (JSON-able)
                  labels: tuple[Label, ...]; negatives: tuple[Negative, ...]
                  row_facts: Mapping[str, tuple[str, str, str]]  # ref -> (date, amount, name/number)
```

Label ids are `f"{scenario}/L{k}"`, negative ids `f"{scenario}/N{k}"`, both in creation order.

A `RowTable` collects rows as dicts with a unique **tag**. Cases and negatives hand out tags and
keep them; after all rows exist the table is ordered (bank/payments: by `(date, insertion
index)`; invoices: by `(issue_date, insertion index)`; suppliers: insertion order), the 0-based
index of each row becomes its ref `f"{file}:{index}"`, and labels/negatives are resolved with
`ref_of(tag)`. A tag that was never added raises, so a label cannot cite a row that does not
exist (REQ-BM-09). `row_facts` is filled in the same pass and is what the tests compare with the
rows read back through the real readers.

### 2.2 Randomness and schedule (REQ-BM-03, 04, 06, 07)

`rng = random.Random(f"{seed}:{app}:{index}")` (D-BM-08). Planted scenarios are numbered
`p = index - index // 5 - 1` (indices 1,2,3,4,6,… → 0,1,2,3,4,…); noise-only scenarios `q = index // 5`.

| Scenario | Cases | Hard negatives |
|---|---|---|
| planted (160 of 200) | `CASES[(3p + j) % 17]` for `j = 0,1,2` | `NEGATIVES[(2p + j) % 14]` for `j = 0,1` |
| noise-only (40 of 200) | none | `FREE[(4q + j) % len(FREE)]` for `j = 0..3` (label-free kinds only) |

At n = 200 each case gets 480 / 17 ≈ 28 instances (≥ `MIN_LABELS_PER_CASE` 20), each hard-negative
kind ≈ 22 from planted scenarios (≥ `MIN_INSTANCES_PER_NEGATIVE` 15) plus noise-only ones for the
label-free kinds. Round-robin, not random, so coverage is guaranteed rather than probable (D-BM-14).
Coverage is asserted by a test; if a schedule edit breaks it, the test names the type or kind.

Every case and hard negative draws a fresh merchant or supplier from the pools (§2.8) without
replacement inside a scenario, so cases never touch each other's rows.

### 2.3 Windows

- Zombie: `WINDOW_START = 2025-01-01`, 455 days (last day 2026-03-31). 455 days hold two yearly
  charges (365 days apart) with room to spare. A case picks its start with
  `rng.randrange(0, window - span)`.
- Zombie, duplicate pairs (D-BM-20): REQ-ZS-13a and REQ-ZS-17 count only **active** series, and a
  monthly series is active when its last charge is within 30 + 3 days of the latest date of the
  ledger. Every row of a scenario lies in the window, so the pair cases (Z11, Z12, Z13) and the
  hard negative NZ14 start with `Builder.late_start(span, slack=15)`: the earlier series ends
  `ACTIVE_TAIL_DAYS` (30) to 15 days before the last day of the window (`ZOMBIE_END`), the later
  one 15 days after it. Both are active whatever else the scenario holds. The 30 and 33 are
  literals from the requirement, not read from a detector. A pair placed at a random date, as
  the first version did, is only active by luck.
- Phantom: `as_of = 2025-10-01 + rng.randrange(0, 30)` days. Clean invoices are issued in
  `[2025-01-01, as_of - 45 days]`, so a payment at issue + 10..40 days is never after `as_of`.
  Cases that need a late date (P13, P14, NP10) derive it backwards from `as_of`
  (`due = as_of - 16 days`, `issue = due - 30 days`).

### 2.4 Cases (planted; labelled)

Every planted recurring series carries a `zs.recurring_charge` label (it is a series by
definition, D-BM-06). `R` below means that label.

| Id | Name | Content | Labels |
|---|---|---|---|
| Z01 | monthly_clear | 6 monthly debits of one amount, gaps 30 days | R |
| Z02 | weekly_clear | 8 weekly debits, gaps 7 days | R |
| Z03 | quarterly_clear | 3 debits, gaps 91 days | R |
| Z04 | annual_pair | 2 debits, 365 days apart | R (yearly) |
| Z05 | monthly_min | exactly 3 monthly debits | R |
| Z06 | weekly_min | exactly 4 weekly debits | R |
| Z07 | monthly_gaps_27_33 | 5 debits, gaps alternating 33 and 27 days | R |
| Z08 | price_clear | 3 × A then 3 × (A + 20 %) monthly | R, `price_increase` |
| Z09 | price_plus7 | 3 × A then 3 × (A + 7 %) | R, `price_increase` |
| Z10 | price_plus5 | 3 × 20.00 then 3 × 21.00 (exactly +5.00 %) | R, `price_increase` |
| Z11 | duplicate_same_key | two interleaved monthly series, one counterparty, same amount | 2 R, `duplicate_subscription` |
| Z12 | duplicate_alias | `NAME INTL 4412` and `NAMECOM`, same amount; context alias `NAME = [NAME INTL, NAMECOM]` | 2 R, `duplicate_subscription` |
| Z13 | duplicate_within_ratio | two interleaved series, one counterparty, 10.00 and 10.80 | 2 R, `duplicate_subscription` |
| Z14 | trial_clear | token 0.49, 14 days before six monthly charges | R, `free_trial_to_paid` (trial row + series) |
| Z15 | trial_edge | token 1.00, 35 days before six monthly charges | R, `free_trial_to_paid` |
| Z16 | cancel_clear | 6 monthly charges, cancellation date after the 3rd | R, `charges_after_cancellation` (rows after the date) |
| Z17 | cancel_edge | 5 monthly charges, cancellation date the day before the last | R, `charges_after_cancellation` (the last row only) |

| Id | Name | Content | Labels |
|---|---|---|---|
| P01 | dup_same_number_clear | same supplier, same number, 2 days apart, same total; both paid | `duplicate_invoice/same_number` (both rows) |
| P02 | dup_same_number_179 | same number, 179 days apart; both paid | `same_number` |
| P03 | dup_near_identical | `F-2026-0042` / `F2026-042`, 20 days apart, same total | `near_identical_number` |
| P04 | dup_total_6_days | different numbers, same total, 6 days apart | `same_total_close_dates` |
| P05 | iban_invoice_differs | invoice IBAN = a different valid account; paid to the master | `iban_change/invoice_iban_differs_from_master` (invoice row; `context_rows` = master row) |
| P06 | iban_payment_non_master | normal invoice; payment to a different valid account, supplier's name | `payment_to_non_master_iban` (payment row; context = master row) |
| P07 | iban_invalid_format | invoice IBAN with hyphens (REQ-PI-28 / acceptance P12) | `iban_invalid` (invoice row) |
| P08 | iban_invalid_checksum | invoice IBAN well formed, mod-97 broken | `iban_invalid` (invoice row) |
| P09 | iban_invalid_master | master row IBAN mod-97 broken | `iban_invalid` (master row) |
| P10a | vat_clear | stated VAT 12.10 instead of 21.00 (total consistent with it) | `vat_amount_mismatch` |
| P10b | vat_off_2_cents | base 100.00, rate 21, VAT 21.02, total 121.02 | `vat_amount_mismatch` |
| P11a | total_clear | stated total 10.00 above base + VAT | `total_mismatch` |
| P11b | total_off_2_cents | stated total 0.02 above base + VAT | `total_mismatch` |
| P12 | rate_not_allowed | rate 20, VAT and total consistent with 20 % | `vat_rate_not_allowed` |
| P13 | overdue_clear | due = `as_of - 40`, unpaid | `reconciliation/invoice_overdue` |
| P14 | overdue_16 | due = `as_of - 16`, unpaid | `invoice_overdue` |
| P15 | payment_without_invoice | debit to a master supplier's name, no invoice | `payment_without_invoice` (payment row) |

17 zombie cases, 17 phantom cases. `NEGATIVES`/`CASES` are literal tuples in the generator.

### 2.5 Hard negatives (unlabelled; the owner-named ones marked ★)

Label-free = no label of any type; such kinds fill noise-only scenarios. Series-bearing kinds
carry an `R` label for their series and only occur in planted scenarios.

| Id | Kind | Content | Kind class |
|---|---|---|---|
| NZ01 | weekly_groceries_irregular ★ | 26 weekly debits at one merchant, amounts uniform in 15.00–120.00 | label-free |
| NZ02 | fuel_irregular ★ | 20 debits at one station, gaps 5–12 days, amounts 20.00–75.00 | label-free |
| NZ03 | single_annual_charge ★ | one debit of 99.00, no other row of the merchant | label-free |
| NZ04 | one_off_price_change ★ | two purchases at one shop 120 days apart: 129.00 then 149.00 | label-free |
| NZ05 | salary_credits ★ | 6 monthly credits of one amount from one employer | label-free |
| NZ06 | refunds ★ | 2–3 one-off credits from shops | label-free |
| NZ07 | two_charges_only | exactly 2 monthly debits (below the minimum of 3) | label-free |
| NZ08 | gap_34_days | 4 debits 34 days apart (outside 30 ± 3, not quarterly) | label-free |
| NZ09 | price_below_threshold | 100.00 × 4 then 103.90 × 2 (+3.90 %) | series-bearing (R) |
| NZ10 | price_decrease | 15.99 × 3 then 12.99 × 3 | series-bearing (R) |
| NZ11 | trial_too_early | token 1.00, 36 days before a 6-charge series | series-bearing (R) |
| NZ12 | trial_amount_above | token 1.01, 14 days before a 6-charge series | series-bearing (R) |
| NZ13 | cancel_same_day | cancellation date = date of the last charge | series-bearing (R) |
| NZ14 | parallel_amounts_differ | one counterparty, two interleaved series 10.00 and 11.50 (placed late like Z11–Z13, D-BM-20, so that "silent" means "judged and not a duplicate", not "inactive") | series-bearing (2 R) |

| Id | Kind | Content |
|---|---|---|
| NP01 | same_number_two_suppliers ★ | two suppliers, same invoice number, same month; each paid |
| NP02 | same_amount_other_months ★ | one supplier, same total, numbers `X-01`/`X-02`, 28–35 days apart; paid |
| NP03 | two_legit_ibans ★ | master has two rows with one tax id and two valid IBANs; invoices and payments use the second one from the start |
| NP04 | paid_late_in_full ★ | paid 30 days after the due date, as_of later |
| NP05 | paid_on_last_matching_day | paid exactly 60 days after the due date |
| NP06 | rounding_half_cent ★ | golden table §2.7; one row written with rate `21.00` |
| NP07 | numbering_restart_180 | same number 180 days apart; both paid |
| NP08 | same_total_7_days_apart | different numbers, same total, 7 days apart; both paid |
| NP09 | vat_off_by_one_cent | VAT and total off by 0.01 |
| NP10 | open_at_due_plus_15 | unpaid, `as_of = due + 15` |
| NP11 | near_number_totals_differ | `F-2026-0042` / `F2026-042`, totals 0.01 apart; both paid |
| NP12 | iban_spelling_variant | invoice IBAN = master IBAN in lower case with spaces |
| NP13 | non_supplier_payments | customer credits and debits to non-suppliers (IBANs outside the master) |
| NP14 | missing_iban | invoice without IBAN |

All phantom hard negatives are label-free. NP10 and the overdue cases share one `as_of`; the
unpaid invoice of NP10 has `due = as_of - 15`, that of P14 `due = as_of - 16`, so both can sit in
one scenario.

### 2.6 Boundary values (literals from the requirements, not from code; REQ-BM-02, 06)

| Threshold (requirement) | Inside, labelled | Just outside, not labelled |
|---|---|---|
| Minimum monthly charges 3 (REQ-ZS-10) | Z05: 3 charges | NZ07: 2 charges |
| Minimum weekly charges 4 (REQ-ZS-10) | Z06: 4 charges | (none) |
| Gap tolerance ±3 days (zombie §3.1) | Z07: gaps 33 and 27 | NZ08: gaps 34 |
| Price step ≥ 5 % (REQ-ZS-14: ≥ 7 % fires, exactly 5 % noise-free fires, ≤ 3.9 % never) | Z09: +7 %; Z10: exactly +5.00 % | NZ09: +3.90 %; NZ10: decrease |
| Parallel amounts within 10 % (REQ-ZS-20) | Z13: 10.00 / 10.80 | NZ14: 10.00 / 11.50 |
| Trial token 0.01–1.00, 1–35 days before (REQ-ZS-21) | Z15: 1.00, 35 days; Z14: 0.49, 14 days | NZ11: 36 days; NZ12: 1.01 |
| Strictly after the cancellation date (REQ-ZS-24) | Z17: 1 day after | NZ13: same day |
| Same number < 180 days (REQ-PI-18, 21) | P01: 2 days; P02: 179 days | NP07: 180 days |
| Rule C < 7 days (REQ-PI-21) | P04: 6 days | NP08: 7 days |
| Rule B equal totals (REQ-PI-18, 21) | P03: equal | NP11: 0.01 apart |
| VAT and total tolerance 0.01 (REQ-PI-31, 33) | P10b, P11b: 0.02 off | NP09: 0.01 off |
| Allowed rates 21/10/4/0, `21.00` equal to 21 (REQ-PI-31, 33) | P12: rate 20 | NP06: rate `21.00` |
| Overdue only after due + 15 (REQ-PI-38) | P14: due + 16; P13: due + 40 | NP10: due + 15 |
| Match window to due + 60 (REQ-PI-37) | — | NP05: due + 60 silent; later payments are not benchmarked (§8, limits) |

Each value above is a literal in the generator. A reviewer can read the requirement id, find the
literal and see that it does not come from a detector module.

### 2.7 Golden rounding table (NP06)

Hand-checked, written as literals, not computed (D-BM-01: the generator otherwise uses
`percent_of` / `net_total`, the same helpers as the detector, so a bug there would be invisible):

| base | rate | VAT (half-up) | total |
|---|---|---|---|
| 12.50 | 21 | 2.63 (2.625) | 15.13 |
| 7.50 | 21 | 1.58 (1.575) | 9.08 |
| 2.50 | 21 | 0.53 (0.525) | 3.03 |
| 33.33 | 21 | 7.00 (6.9993) | 40.33 |
| 1250.10 | 21.00 | 262.52 (262.521) | 1512.62 |
| 0.50 | 21 | 0.11 (0.105) | 0.61 |
| 0.25 | 10 | 0.03 (0.025) | 0.28 |

A test (not the generator) recomputes the table with `percent_of` / `net_total` and compares.

### 2.8 Names, identifiers and noise

- Merchant pool: 24 stems × 12 suffixes of invented compound words (`CLOUD`+`VAULT`), uppercase,
  letters only, so each normalises to its own key. Supplier pool: invented company names with
  `, S.L.`; a few fictional person names from Finance Rule 5 for NIF suppliers.
- Own copies (~40 lines) of `make_iban` (valid mod-97, national check digits shifted by 11 mod 100),
  `make_cif` and `make_nif` (wrong control character). Not imported from `generate_samples.py`
  (D-BM-01). A test-local checker verifies mod-97, wrong national digits and wrong control
  character.
- Noise: zombie 15–40 one-off debits (each merchant once, amount 5.00–90.00, date uniform) and
  2–4 transfers to fictional people. Phantom 2–5 clean suppliers, 3–5 invoices each (monthly
  issue, base 80–1800 with cents, rate from 21/21/21/10/4/0, due = issue + 30, paid in full 10–40
  days later with name and master IBAN). Noise rows have no tag in any label.
- Money is written from integer cents or from `ledger_kit.utils.money` helpers; no `float`.

### 2.9 Output of one scenario

`files` maps file name to text, CSV with LF line endings. `context` is JSON-able: zombie
`{"aliases": {"NAME": ["NAME INTL", "NAMECOM"]}, "cancellation_dates": {"GYMPLUS": "2025-06-28"}}`,
phantom `{"as_of": "2025-10-14"}`. The runner converts them with the apps' own helpers
(`normalise_alias_map`, `normalise_date_map`, `date.fromisoformat`).

## 3 Runner (`scripts/benchmark.py`)

### 3.1 Pipelines (REQ-BM-11)

```python
def run_zombie(s: Scenario) -> list[AlertRecord]:
    pipe = zombie_run_pipeline("statement.csv", data,
                               aliases=normalise_alias_map(...),
                               cancellation_dates=normalise_date_map(...), cpi=None)
    results = pipe.results
def run_phantom(s: Scenario) -> list[AlertRecord]:
    pipe = run_pipeline((Source("invoices.csv", ...),), Source("suppliers.csv", ...),
                        Source("payments.csv", ...), as_of)
    results = pipe.results
```

`zombie_run_pipeline` is `apps.zombie_subscriptions.settings.run_pipeline`, imported under that
alias because the phantom function has the same name. It holds the read, normalise, debit-filter
and `run_all` steps that `app.py` used to run inline, and `app.py` now calls it too (D-BM-10,
amendment of the zombie spec, behaviour unchanged). The benchmark therefore measures exactly what
the app runs; the demo check of REQ-BM-11 (19 / 9 alerts) pins the counts. `cpi` is `None`
because the CPI context only decorates an alert that already fired (Finance Rule 9).

`AlertRecord = (scenario, type, refs: tuple[str, ...], detector)`. `type` follows REQ-BM-05.

### 3.2 Matching (REQ-BM-12)

```python
def match(alerts, labels) -> MatchResult:   # pure; plain records in, plain records out
    for a in sorted(alerts, key=lambda a: (natural(a.refs[0]), a.type, tuple(map(natural, a.refs)))):
        pool = [l for l in unmatched(labels, a.scenario) if l.type == a.type and set(l.rows) & set(a.refs)]
        best = min(pool, key=lambda l: (-len(set(l.rows) & set(a.refs)), l.id), default=None)
        ...tp if best else fp; consume best
    fn = labels never consumed
```

`natural(ref)` = `(file, int(index))`, so `f.csv:9 < f.csv:10`. The ref list of an alert is read
as given; `context_rows` of a label are never consulted.

### 3.3 Metrics (REQ-BM-13)

`ratio(n, d) = None if d == 0 else str((Decimal(n) / Decimal(d)).quantize(Decimal("0.0001"), ROUND_HALF_UP))`.
Counts per detector use `alert.detector` and the label type's detector prefix (`type.split("/")[0]`).
Noise-only figures use `scenario.noise_only`. Hard-negative attribution runs after matching on the
false-positive alerts only.

### 3.4 Detector errors (REQ-BM-14)

A `logging.Handler` attached to `logging.getLogger("ledger_kit.detectors.registry")` for the run
collects `WARNING` records whose message starts with `Detector '`; `record.args[0]` is the detector
name. The handler is removed in `finally`. The runner counts scenarios per detector, and on any
count exits 1 before writing.

### 3.5 `results.json` (REQ-BM-15)

```jsonc
{
  "apps": {
    "zombie": {
      "detectors": { "zs.price_increase": { "alerts": 0, "false_alarms_per_noise_scenario": "0.0000",
          "fn": 0, "fp": 0, "labels": 0, "noise_only_alerts": 0, "noise_only_scenarios_with_alert": 0,
          "precision": "1.0000", "recall": "1.0000", "seed": 2026, "tp": 0 } },
      "errors": {},
      "false_positives": [ { "hard_negative": "weekly_groceries_irregular|null",
                              "refs": ["statement.csv:12"], "scenario": "zs-0012", "type": "zs.recurring_charge" } ],
      "hard_negatives": { "weekly_groceries_irregular": { "false_alarms": 0, "instances": 0,
                              "instances_with_false_alarm": 0 } },
      "misses": [ { "label": "zs-0007/L1", "rows": ["statement.csv:3"], "scenario": "zs-0007", "type": "zs.price_increase" } ],
      "noise_only_scenarios": 40, "scenarios": 200,
      "scenarios_detail": [ { "alerts": 0, "fn": 0, "fp": 0, "id": "zs-0000", "labels": 0, "noise_only": true, "tp": 0 } ],
      "seed": 2026,
      "totals": { "alerts": 0, "fn": 0, "fp": 0, "labels": 0, "precision": null, "recall": null, "tp": 0 },
      "types": { "zs.price_increase": { "alerts": 0, "fn": 0, "fp": 0, "labels": 0, "precision": null, "recall": null, "tp": 0 } }
    },
    "phantom": { /* same shape */ }
  },
  "limits": ["…"],
  "matching_rule": "…",
  "scenarios_per_app": 200,
  "schema_version": 1,
  "seed": 2026
}
```

The numbers above are shape placeholders, not results. `limits` (static strings, no digit, so the
document test of REQ-BM-16 holds):

1. All data is synthetic and comes from `scripts/generate_benchmark.py`; real statements and invoices are messier.
2. The labels were written by the project team that also wrote the detector requirements; a pattern nobody thought of is neither planted nor labelled.
3. Boundary values follow our reading of the requirements; where a requirement is ambiguous the benchmark follows the documented behaviour.
4. The shares of clean and planted scenarios and the number of cases per scenario are our choice; precision and recall describe this mix, not another one.
5. Only plain-dialect CSV is benchmarked. Norma 43, Facturae, European CSV and the CPI context are covered by other tests.
6. VAT amounts and totals in the generator use the same money helpers as the detectors; rounding cases therefore also use hand-checked literal values.
7. Payments dated after the matching window of the reconciliation are not benchmarked.

### 3.6 `docs/benchmark.md` (REQ-BM-16)

`render_markdown(results) -> str`. Fixed order: title; generated-file note; "Reproduce"
(`python scripts/benchmark.py`, `--check`, `--export-scenarios`); "Matching rule" (the
`matching_rule` string); per app: `### Zombie Subscriptions` with seed and counts line, the
detector table, the hard-negative table; `## Limits` list; `## Follow-ups` one line pointing to
`.kiro/specs/benchmark/design.md`. All static text carries no digit. Ratios are the stored
strings, `null` → `n/a`.

### 3.7 CLI (REQ-BM-17)

`argparse`: `--check`, `--export-scenarios DIR`, `--seed N`, `--scenarios N`, `--out-dir DIR`.
Exit codes: 0 ok, 1 differs / detector error, 2 usage. Writes use `Path.write_bytes(text.encode("utf-8"))`.

## 4 Determinism and run time (REQ-BM-18, 19)

- Sources of non-determinism removed: string-seeded RNG per scenario; no clock; `sort_keys`;
  alerts sorted by the matcher; ratios as `Decimal`; `uuid4` ids of `Transaction` never reach the
  output (only `source_ref`s do). Alert order is irrelevant because the matcher sorts.
- `.gitattributes` gets `data/benchmark/*.json -text` and `docs/benchmark.md -text`.
- Run time *(inferred, not measured)*: each zombie scenario runs five detectors and each of them
  calls `find_series` for every key, so cost grows with rows per key; hard negatives with 26 rows
  at one key are the heavy ones. Scenario size is capped (a statement has at most 200 data rows,
  asserted by a test). If the first measured full run exceeds 45 s, lower `SCENARIOS_PER_APP`
  (D-BM-17). The committed-results test shares one full run through a module-scoped fixture;
  the other determinism tests use 10 scenarios.

## 5 Benchmark page (REQ-BM-20, 21)

`streamlit_app.py` keeps `PageSpec(title, icon, url_path, script)`. Home and Benchmark are
function pages: `FUNCTION_PAGES = {"home": home, "benchmark": benchmark}` and
`_page(spec)` uses `spec.script or FUNCTION_PAGES[spec.url_path]`; the default page stays the one
with `script is None and url_path == "home"`. New spec:
`PageSpec("Benchmark", "📊", "benchmark", None)`.

`benchmark()` reads `RESULTS_PATH = Path(__file__).parent / "data" / "benchmark" / "results.json"`
with `json.loads`, checks `schema_version == 1`, and renders: caption (seed, scenarios per app),
per app a `st.dataframe` (columns of REQ-BM-16, `n/a` for `null`, `hide_index=True`), the
hard-negative `st.dataframe`, `st.markdown` list of `limits`, and a caption pointing to
`docs/benchmark.md`. Any `OSError`, `ValueError` (includes `JSONDecodeError`) or schema mismatch
→ one `st.error` with the REQ-BM-21 text. The path is a module constant so a test can monkeypatch it.

Test route *(Streamlit 1.67, inferred)*: `AppTest.switch_page` is documented for file pages and
resolves `url_path` hashes, but I did not verify it for function pages. The page tests therefore
run the function directly: `AppTest.from_string("import streamlit_app\nstreamlit_app.benchmark()")`
(the module's `__main__` guard does not fire on import, and `tests/test_showcase_app.py` already
imports `streamlit_app`), with `monkeypatch.setattr(streamlit_app, "RESULTS_PATH", tmp)`. One more
test runs the real entry (`AppTest.from_file(ENTRY).run()`) and checks `PAGES`. Task BM8 tries
`switch_page("benchmark")` first and keeps it as an extra test only if it works.

Amendments: REQ-SC-01 (three → four pages) in `.kiro/specs/showcase/requirements.md` and
`PAGE_TITLES` in `tests/test_showcase_app.py`; the Home text is untouched.

## 6 Test plan

| File | Tests | REQ |
|---|---|---|
| `tests/test_benchmark_matching.py` | the eleven hand-made sets of REQ-BM-12; ratio examples of REQ-BM-13; Hypothesis (200 examples): counts conserve (`tp + fn = |L|`, `tp + fp = |A|`), alert/label order does not change counts, matched pairs share scenario and type and a ref, idempotent, empty input gives zeros | 12, 13 |
| `tests/test_benchmark_generator.py` | independence by AST and by detector constant names; seed and index independence; counts and noise-only share; ids and file names; catalogue vs `registered_names()`; coverage of types, cases and hard negatives at n = 200; golden examples of REQ-BM-06 (rows, labels); golden rounding table vs money helpers; label rows non-empty and resolvable; ingestion round trip (zero quarantine, row facts equal); identifier checks; row cap 200; no clock / network names | 2–10, 23 |
| `tests/test_benchmark_runner.py` | pipelines on the two demos (19 / 9 alerts); salary produces nothing; error capture with a raising detector (exit 1, no files); results schema and key order; no date / path in output; docs rendered from a hand-made results dict; document-number test; CLI: usage error, `--out-dir`, `--check`, `--export-scenarios` on 10 scenarios; reduced run twice equal, other seed differs; **committed files equal a fresh full run** | 11, 13–19 |
| `tests/test_benchmark_page.py` | PAGES titles; synthetic results shown; `null` → `n/a`; limits list; missing / bad JSON / bad schema → one error; no forbidden imports in `streamlit_app.py`; entry run without exception | 20, 21 |

Hypothesis tests use `settings(max_examples=200)` (testing.md). Nothing reads the clock, so no
`freezegun`. No test calls a network.

## 7 Decisions

- **D-BM-01 Own generator, own helpers.** A change of the demo generator must not move the
  benchmark bytes, and the generator must not share a code path with what it judges. Cost: about
  40 duplicated lines. Shared `money.py` stays (steering: the only module allowed to do money
  arithmetic) and the shared-oracle risk is covered by the golden table and by limit 6.
- **D-BM-02 Type = `detector/variant`.** A `total_mismatch` alert on a `vat_amount_mismatch`
  label is a wrong answer; matching on the detector alone would hide it.
- **D-BM-03 One alert per label.** A second alert for the same problem is noise for the user, so
  it counts as a false positive.
- **D-BM-04 `context_rows` never match.** Several invoices of one supplier cite the same master
  row; matching on it would let an alert for the wrong invoice take a label.
- **D-BM-05 Hard negatives are just "unlabelled".** No second matching rule: anything unlabelled
  that fires is a false positive; the hard-negative record only attributes it afterwards for the
  report.
- **D-BM-06 Series-bearing negatives carry an `R` label.** `zs.recurring_charge` fires on every
  series by design (REQ-ZS-13), so a series is a true positive for it even when another detector
  must stay silent.
- **D-BM-07 Annual subscription.** The owner listed it as a hard negative. REQ-ZS-10 makes two
  yearly charges a series, so the pair (Z04) is planted as a recurring-charge positive, and the
  hard negative NZ03 is a single annual charge. Every other detector must stay silent for both.
  *Answered by the owner (session 10b): yes, exactly as written. Two yearly charges are a
  recurring-charge positive; a single annual charge is the hard negative; every other detector
  stays silent on both.*
- **D-BM-08 String RNG seed per scenario.** `random.Random(str)` hashes with SHA-512, not with the
  per-process `hash()`; scenarios stay independent of each other and of the scenario count.
- **D-BM-09 Plain CSV only.** Dialects and real formats are tested by their own suites; adding
  them multiplies run time without testing a detector.
- **D-BM-10 The zombie pipeline is one public function, called by the app and by the runner.**
  *Answered by the owner (session 10b), replacing the first draft ("repeated in the runner").* The
  read, normalise, debit-filter and detector steps move out of `app.py` into
  `apps/zombie_subscriptions/settings.py::run_pipeline`, mirroring the phantom app; `app.py` and
  the runner both call it, so the benchmark measures exactly what the app runs. A refactor with
  no behaviour change: every existing test stays green, the demo still shows 3 tombstones and 19
  alerts. Recorded as an amendment in the zombie spec (requirements §8, design §7, tasks ZSA1).
- **D-BM-11 Errors via the registry log.** `run_all` hides exceptions by design; without the
  handler a crashing detector would show as "found nothing".
- **D-BM-12 No caps in `results.json`.** Every false positive and miss is listed, so a judge or a
  follow-up task can rebuild the scenario from `(seed, app, index)` alone.
- **D-BM-13 No score gate.** A gate would invite tuning the benchmark or the detectors to the
  number. The tests check determinism and plumbing only.
- **D-BM-14 Round-robin schedule.** Guaranteed coverage per case and kind; randomness only inside
  a case (dates, amounts, names).
- **D-BM-15 Ratios as `Decimal` strings.** Byte-identical output on every platform; no `float`
  repr question.
- **D-BM-16 Page runs as a function; tests call the function.** See §5. *Answered by the owner
  (session 10b): navigation accepted as written.*
- **D-BM-17 Scenario count is the run-time knob.** 200 is the owner's example, 60 s the hard
  limit; the count in the files is whatever fits. *Answered by the owner (session 10b): accepted.*
- **D-BM-18 Payments after the matching window are not benchmarked.** They are unmatched by
  rule (REQ-PI-37); labelling that pair would test the spec against itself.
- **D-BM-19 Exactly +5.00 % is labelled positive.** REQ-ZS-14's first sentence says "more than
  5 %"; its last bullet says a noise-free step of exactly 5 % fires, and the code fires. The
  benchmark follows the bullet. *Answered by the owner (session 10b): the code fires, so the
  case is labelled positive; FU-P3 keeps the wording fix.*
- **D-BM-20 Duplicate pairs are planted active.** *(Session 10d, finding F1.)* The first full run
  found only 9 of 84 planted duplicate subscriptions. Cause: the generator placed each pair at a
  random date, while REQ-ZS-13a and REQ-ZS-17 say that only series active at the latest date of
  the ledger count; most pairs ended months before the ledger did, so the labels contradicted the
  requirement. This is a generator error, not a detector error: the detector follows its
  requirement. The generator now places Z11–Z13 and NZ14 in the last days of the window (§2.3).
  The labels, the case catalogue and the detector are unchanged. REQ-BM-22 forbids changing a
  label or hard negative *to remove a detector error*; this change removes a contradiction with
  the requirement the label comes from, which REQ-BM-22a spells out. The committed results
  before this change are kept in §8 as the first measurement.

## 8 Follow-ups

No detector is changed here (REQ-BM-22). This section lists what the first full run found, with the
cause of each finding. Session 10d read the code, the specs and the exported scenarios
`zs-0000`, `zs-0004`, `zs-0006` and `zs-0036` (the other exported scenarios were not opened; the
causes below are the same mechanism, not re-read for each id).

**First measurement** (seed 2026, 200 scenarios per app, committed before D-BM-20; the run took
about 17 s, so `SCENARIOS_PER_APP` stays 200): zombie precision `0.9697`, recall `0.9251`;
phantom precision `0.7742`, recall `1.0000`; no detector raised an error. Every figure not named
below was `1.0000` / `1.0000`.

### 8.1 Predictions of the first draft, confirmed or removed

| Id | Verdict | Note |
|---|---|---|
| FU-P1 | **confirmed** as F3 | `build_master` keeps the first master row per tax id (REQ-PI-09). |
| FU-P2 | **confirmed, cause refined** as F2 | Not a chance weekly series alone: see F2. |
| FU-P3 | **open** | REQ-ZS-14 says "more than 5 %" and also "exactly 5 % fires". Wording fix for the owner; the benchmark follows the bullet (D-BM-19). The benchmark found no error here (`zs.price_increase` 84 of 84). |

### 8.2 Measured findings

| Id | Detector | Scenario id(s) | Input (rows) | Observed | Expected | Cause | Case | Handled in |
|---|---|---|---|---|---|---|---|---|
| F1 | `zs.duplicate_subscription` | misses of type `zs.duplicate_subscription`: 75 of 84 labels, examples `zs-0004/L4`, `zs-0004/L7`, `zs-0006` (CLOUDNEST pair) | Z11–Z13 pairs of four monthly charges each, placed at a random date | no alert; 9 of 84 found | one warning per pair | REQ-ZS-13a and REQ-ZS-17: only series active at the latest date of the ledger count. In `zs-0004` the LUMENBEAT pair ends on 2025-06-13 and the IVORYNEST pair on 2025-06-30; the ledger ends on 2026-02-08, more than 200 days later. In `zs-0006` the CLOUDNEST pair ends on 2025-08-31, the ledger on 2026-03-29. The 9 found are the pairs that happened to end in the last 33 days. | **(b) generator contradicts the requirement.** The detector is right. | D-BM-20, `late_start` in `scripts/generate_benchmark.py`; tests in `tests/test_benchmark_generator.py` (Task BM9). Results must be regenerated once (§9). |
| F2 | `zs.recurring_charge` | false alarms (29) on hard negatives `fuel_irregular` (12 of 43 instances, 14 alarms) and `weekly_groceries_irregular` (13 of 43, 15 alarms); examples `zs-0000` (refs `statement.csv:33`, `:41`, `:51`), `zs-0036` (refs `:34`, `:35`, `:38`, `:40`, `:42`), `zs-0009`, `zs-0062` | one shop, 26 weekly or 20 irregular charges with amounts drawn between 15.00 and 120.00 (fuel 20.00 to 75.00) | an info alert for a "series" | none (REQ-ZS-09 E7: weekly charges of varying amounts at one shop give no alert) | `zs-0000`: NIMBUSBOX groceries of 2025-06-04 (115.63), 2025-07-02 (119.51) and 2025-07-30 (114.75) lie 28 days apart and within 10 % of their median: three monthly charges, accepted as a *variable bill* (REQ-ZS-10a(3)). The six other charges of the shop between the first and the last are ignored: the cadence run skips rows that are too close, and the "no other rows in the span" guard of REQ-ZS-10b applies to quarterly and yearly series only. `zs-0036`: four weekly charges (76.16 to 78.36) form a weekly series by chance, and a fifth charge 17 % lower joins as an edge step. E7b passes only because its fixture was built with 13 price levels more than 10 % apart. | **(a) real detector weakness.** The hard negative is what E7 describes. | `.kiro/specs/detector-fixes/`: REQ-DF-10 to REQ-DF-16. **Fixed (DF3), measured in DF4: 29 → 2 false alarms** (limit 2 of REQ-DF-20) |
| F3 | `pi.iban_change` | false alarms (140) on hard negative `two_legit_ibans`: 35 of 35 instances, 4 alarms each (the 12 noise-only scenarios with an alert carry this kind, which is label-free) | master with two rows for one tax id and two valid IBANs; 2 invoices and 2 payments use the second IBAN | 2 critical `invoice_iban_differs_from_master` and 2 critical `payment_to_non_master_iban` | none: both accounts are in the master | REQ-PI-09 says that when several master rows share a tax id the first is used and the others are ignored; `build_master` does exactly that, so the second legitimate account is a "poltergeist". The generator follows the intent of the detector (flag an account the master does not hold); the requirement text is what is wrong, because suppliers do keep several accounts. | **(a) real weakness, rooted in REQ-PI-09.** NP03 is not changed. | `.kiro/specs/detector-fixes/`: REQ-DF-01 to REQ-DF-09 (amends REQ-PI-09 and REQ-PI-24). **Fixed (DF1), measured in DF2: 140 → 0 false alarms** |

Per REQ-BM-22 every false positive and miss of `results.json` is covered: the 29 zombie false
alarms by F2 (both kinds named above), the 140 phantom false alarms by F3 (`two_legit_ibans`),
the 75 misses by F1 (`zs.duplicate_subscription`). A test reads the committed results and checks
that every false positive and every miss is named by the index below (a hard-negative kind, a
miss type or a scenario id between backticks); the index is the only part of this section the
test parses.

Coverage index (read by `tests/test_benchmark_runner.py`):

- Hard-negative kinds: `fuel_irregular`, `weekly_groceries_irregular`, `two_legit_ibans`
- Miss types: `zs.duplicate_subscription`
- Scenario ids: none

**After the fixes.** Three regenerations are expected, in this order, each recorded here by the
author (no number is written before it is measured): (1) after D-BM-20, the zombie block changes
because the generator draws other dates; F1 is expected to vanish; (2) after the phantom fix of
`detector-fixes`, `two_legit_ibans` is expected to give zero false alarms; (3) after the zombie
fix, the false alarms of F2 are expected to fall; whatever remains is listed with scenario ids
and judged on its own, never removed by changing the benchmark or a threshold.

| Step | Zombie precision | Zombie recall | Phantom precision | Phantom recall | Remaining findings |
|---|---|---|---|---|---|
| First measurement | `0.9697` | `0.9251` | `0.7742` | `1.0000` | F1, F2, F3 |
| After D-BM-20 | `0.9719` | `1.0000` | `0.7742` (unchanged generator) | `1.0000` | F2, F3 (F1 gone) |
| After `detector-fixes` phantom task (DF1, DF2) | `0.9719` (unchanged) | `1.0000` | `1.0000` | `1.0000` | F3 fixed; F2 open |
| After `detector-fixes` zombie task (DF3, DF4) | `0.9980` | `1.0000` | `1.0000` | `1.0000` | F2 fixed except 2 false alarms (limit 2 of REQ-DF-20) |

Measured by the owner after the fixes (session 12a; seed 2026, 200 scenarios per app, thresholds,
generator, labels and hard negatives unchanged; commit `989789b`): zombie planted 1002, alerts 1004,
found 1002, missed 0, false alarms **29 → 2**, precision `0.9719` → `0.9980`, recall `1.0000`
before and after. Both remaining false alarms are `zs.recurring_charge` on
`weekly_groceries_irregular` (`fuel_irregular` now 0, `weekly_groceries_irregular` 2 of 43
instances); they are recorded as the accepted limit 2 of REQ-DF-20 (charges of one shop that lie
on one price level at a regular cadence are still a series), not as a new finding, and are not
removed by tuning. Phantom planted 480, alerts 480, found 480, missed 0, false alarms **140 → 0**
(`two_legit_ibans` silent), precision `0.7742` → `1.0000`, recall `1.0000` before and after; no
other phantom figure moved. `docs/benchmark.md` and `data/benchmark/results.json` were regenerated
and committed. The demo end-to-end tests are unchanged: zombie 3 tombstones and 19 alerts,
phantom 9 alerts.

The coverage index above still names `fuel_irregular` and `two_legit_ibans` although they now have
no false alarm: `tests/test_benchmark_runner.py` pins all three kinds in it, and the index may
list more than the results need.

**F2 and F3 are fixed by `detector-fixes`** (DF3 and DF1, measured in DF4 and DF2). FU-P3 stays
open.

Baseline measured by the owner after D-BM-20 (seed 2026, 200 scenarios per app, commit `6a3542f`):
zombie planted 1002, alerts 1031, found 1002, missed 0, false alarms 29, precision `0.9719`,
recall `1.0000` (`zs.duplicate_subscription` now 84 of 84; all 29 false alarms are
`zs.recurring_charge` on the hard negatives `fuel_irregular` and `weekly_groceries_irregular`, the
same count as the first measurement); phantom planted 480, alerts 620, found 480, false alarms 140,
precision `0.7742`, recall `1.0000` (all on `two_legit_ibans`). F1 has no miss left. The coverage
index above is left as it is: `tests/test_benchmark_runner.py` pins `zs.duplicate_subscription`
in the "Miss types" line, so removing it would need that test to change too.

## 9 Not verified by the author

Written without running a command. Unverified: the run time of the full benchmark (§4; the user
measured about 17 s on the first full run, session 10d); that every
hard negative truly leaves all detectors silent (the benchmark exists to find out); that the
round-robin schedule reaches the minimum counts (tests assert it); how `AppTest.switch_page`
treats a function page (§5); the exact alert counts 19 and 9 of the demos (taken from
`tests/test_showcase_app.py`, not re-run).

Session 10d, also not run: the causes in §8 were read from the code, the specs and four exported
scenarios, not reproduced by a debugger; the effect of `late_start` on the recall of
`zs.duplicate_subscription` (expected to rise to `1.0000`, not measured; later measured at 84 of
84, §8); and the committed results were stale after D-BM-20 until the owner re-ran the benchmark.
Session 12a: the results are no longer stale. The owner re-ran `python scripts/benchmark.py` after
the D-BM-20 generator fix and after `detector-fixes`, and committed both files; the figures in §8
are theirs. The classification of the 2 remaining zombie false alarms as limit 2 of REQ-DF-20 was
not re-read from the exported scenarios by the author.
