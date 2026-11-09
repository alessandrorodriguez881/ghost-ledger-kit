# benchmark — Requirements

## Overview

`benchmark` replaces the sentence "the detectors work" with a measured number a judge can
re-run. A seeded generator builds many independent synthetic scenarios per app. Each scenario
holds planted problems with a ground-truth label, plus realistic noise and hard negatives that
must not fire. A runner sends every scenario through the same public pipeline the apps use,
matches alerts to labels with one rule, and writes `data/benchmark/results.json`,
`docs/benchmark.md` and a Benchmark page.

The benchmark **reports**; it never passes or fails on a score, and it never changes a detector.
Errors it finds are listed as follow-ups (REQ-BM-22).

Ids are `REQ-BM-nn`. EARS keywords: *shall*, *when*, *while*, *where*, *if ... then*. Every
requirement ends with acceptance examples: a concrete input and the exact expected output.
Section references (§) point to `design.md`. Dates are ISO, amounts have a dot decimal.

Terms. **Scenario**: one bank statement (zombie) or one invoice set (phantom) with its labels.
**Case**: a planted problem pattern (§2.4). **Hard negative (HN)**: a pattern that looks like a
problem and must not fire (§2.5). **Noise-only scenario**: a scenario with no label at all.
**Problem type**: `detector` or `detector/variant` (REQ-BM-05).

---

## 1 — What is measured

- **REQ-BM-01** The benchmark shall measure, per registered detector and per app: how many
  planted problems were found (true positives), how many were missed (false negatives), how many
  alerts matched no label (false positives), precision, recall, and the alerts raised on
  noise-only scenarios. It shall state every published number from `results.json` only, and shall
  contain no threshold of its own: no run, test or command fails because a score is low.

  *Acceptance.* A run in which `pi.vat_error` finds 0 of 30 labels still exits with code 0 and
  writes `"recall": "0.0000"` for it. A run where a detector raises exits with code 1
  (REQ-BM-14); that is an error, not a score.

---

## 2 — The generator

- **REQ-BM-02** *(independence)* The generator shall be the file `scripts/generate_benchmark.py`,
  separate from `scripts/generate_samples.py`. It shall import only the standard library and
  `ledger_kit.utils.money`. It shall not import `apps`, `ledger_kit.detectors`,
  `ledger_kit.ingestion`, `scripts.generate_samples` or any detector module, and it shall define
  no name that is also a module-level `UPPER_CASE` constant of a registered detector module.
  Every boundary value is a literal written from the requirements text (§2.6), not from code.

  *Acceptance.*
  - A generator containing `from apps.phantom_invoices.detectors.duplicate_invoice import
    DUPLICATE_WINDOW_DAYS` fails the independence test with a message naming
    `apps.phantom_invoices.detectors.duplicate_invoice`.
  - A generator containing the line `PRICE_INCREASE_MIN_RATIO = 0.05` fails the test with a
    message naming `PRICE_INCREASE_MIN_RATIO`.
  - A generator importing only `random`, `datetime`, `decimal`, `json` and
    `ledger_kit.utils.money` passes.

- **REQ-BM-03** *(seed and independence of scenarios)* Scenario `i` of app `a` for seed `s` shall
  depend only on `(s, a, i)`: it is drawn from `random.Random(f"{s}:{a}:{i}")` (a string seed, so
  Python's hash randomisation is not involved). The generator shall read neither the clock nor the
  environment. Adding scenarios shall not change the earlier ones.

  *Acceptance.*
  - `build_scenario(2026, "zombie", 7)` built inside a run of 10 scenarios and inside a run of 200
    returns identical file bytes and identical labels.
  - `build_scenario(2027, "zombie", 7)` returns file bytes different from the seed-2026 ones.
  - The RNG seed text for seed 2026, app `zombie`, index 7 is exactly `"2026:zombie:7"`.

- **REQ-BM-04** *(scenario set)* For `n` scenarios per app (default 200) the generator shall
  produce ids `zs-0000`..`zs-{n-1:04d}` and `pi-0000`..`pi-{n-1:04d}`. A scenario is noise-only
  exactly when its index is divisible by 5. Files: zombie `statement.csv`; phantom
  `invoices.csv`, `suppliers.csv`, `payments.csv`. All files are plain-dialect CSV, UTF-8, LF,
  with the column sets of the demo files (bank: `date,amount,currency,counterparty,description,iban`).

  *Acceptance.*
  - n = 200: 200 ids per app, 40 noise-only scenarios per app, first ids `zs-0000`, `zs-0001`.
  - n = 10: noise-only indices are 0 and 5 → 2 scenarios.
  - A noise-only scenario has `labels == []`; every other scenario has at least 1 label.
  - Bank header line: `date,amount,currency,counterparty,description,iban`.

- **REQ-BM-05** *(problem types)* The generator shall plant every problem type below, and the
  runner shall define the type of an alert as `detector` when `data` has no `variant`, otherwise
  `f"{detector}/{variant}"`. The catalogue is a literal in the generator (16 types):

  | App | Types |
  |---|---|
  | zombie (5) | `zs.recurring_charge`, `zs.price_increase`, `zs.duplicate_subscription`, `zs.free_trial_to_paid`, `zs.charges_after_cancellation` |
  | phantom (11) | `pi.duplicate_invoice/same_number`, `/near_identical_number`, `/same_total_close_dates`; `pi.iban_change/invoice_iban_differs_from_master`, `/payment_to_non_master_iban`, `/iban_invalid`; `pi.vat_error/vat_amount_mismatch`, `/total_mismatch`, `/vat_rate_not_allowed`; `pi.reconciliation/invoice_overdue`, `/payment_without_invoice` |

  A test shall check the catalogue against `registered_names()` after importing both detector
  packages. At n = 200 every type shall have at least `MIN_LABELS_PER_TYPE = 20` labels.

  *Acceptance.*
  - Registry `{zs.*: 5 names, pi.*: 4 names}` and the catalogue above → the coverage test passes.
  - A sixth detector `zs.late_fee` registered, catalogue unchanged → the test fails with
    `registered detector zs.late_fee has no benchmark problem type`.
  - An alert `detector="pi.vat_error"`, `data={"variant": "total_mismatch"}` has type
    `pi.vat_error/total_mismatch`; an alert `detector="zs.price_increase"`, `data={}` has type
    `zs.price_increase`.

- **REQ-BM-06** *(planted cases, inside and just outside)* The generator shall plant the 17 zombie
  cases and 17 phantom cases of §2.4. For every numeric threshold that a requirement states, the
  planted cases shall include a value inside it (labelled) and the hard negatives shall include a
  value just outside it (not labelled), as listed in §2.6. Cases are assigned to planted scenarios
  round-robin, 3 per scenario, so that every case has at least `MIN_LABELS_PER_CASE = 20`
  instances at n = 200.

  *Acceptance (price step, zombie).*
  - Case Z08 with counterparty `CLOUDVAULT`, three charges of 20.00 then three of 24.00 (+20.00 %),
    30 days apart from 2025-02-03, as the only content of a statement → rows (indices 0–5)
    `2025-02-03,-20.00,EUR,CLOUDVAULT,Monthly subscription,` · `2025-03-05,-20.00,…` ·
    `2025-04-04,-20.00,…` · `2025-05-04,-24.00,…` · `2025-06-03,-24.00,…` · `2025-07-03,-24.00,…`;
    labels: `zs.recurring_charge` rows `statement.csv:0`–`:5` and `zs.price_increase` rows
    `statement.csv:0`–`:5`.
  - Case Z10 (exactly +5.00 %): 20.00 ×3 then 21.00 ×3 → the same two label types.
  - HN `price_below_threshold`: 100.00 ×4 then 103.90 ×2 (+3.90 %) → label `zs.recurring_charge`
    only; no `zs.price_increase` label.

  *Acceptance (free trial, zombie).* Case Z15: first of six monthly charges of 14.99 on
  2025-03-10 and a trial charge of 1.00 on 2025-02-03 (35 days before) → labels
  `zs.recurring_charge` (the six charges) and `zs.free_trial_to_paid` (trial row + six charges).
  HN `trial_too_early`: trial 1.00 on 2025-02-02 (36 days before) → no trial label.

  *Acceptance (cancellation, zombie).* Case Z17: counterparty `GYMPLUS`, charges 2025-03-01,
  2025-03-31, 2025-04-30, 2025-05-30, 2025-06-29 of 8.99, context cancellation date
  `GYMPLUS = 2025-06-28` → label `zs.charges_after_cancellation` with the single row of
  2025-06-29. HN `cancel_same_day`: cancellation date 2025-06-29 → no such label.

  *Acceptance (VAT, phantom).* Case P10b: base 100.00, rate 21, stated VAT 21.02, total 121.02 →
  label `pi.vat_error/vat_amount_mismatch` on that invoice row only. HN `vat_off_by_one_cent`:
  stated VAT 21.01, total 121.01 → no label.

  *Acceptance (duplicates, phantom).* Case P04: one supplier, invoices `FAC-0201` on 2025-03-03
  and `FAC-0202` on 2025-03-09 (6 days), both total 242.00 → label
  `pi.duplicate_invoice/same_total_close_dates` citing both rows. HN `same_total_7_days_apart`:
  `FAC-0202` on 2025-03-10 → no label. Case P02: the same number on 2025-01-10 and 2025-07-08
  (179 days) → label `/same_number`; HN `numbering_restart_180`: 2025-01-10 and 2025-07-09 (180
  days) → no label.

  *Acceptance (overdue, phantom).* Case P14: invoice due 2025-04-01 unpaid, `as_of` 2025-04-17
  (due + 16) → label `pi.reconciliation/invoice_overdue`. HN `open_at_due_plus_15`: `as_of`
  2025-04-16 → no label.

- **REQ-BM-07** *(hard negatives)* The generator shall plant the 14 zombie and 14 phantom hard
  negatives of §2.5, including the ones the project owner named: weekly groceries and fuel at
  irregular amounts, an annual subscription (single charge), a legitimate price change of a
  one-off purchase, salary and refunds (credits), the same invoice number used by two different
  suppliers, two invoices of one supplier with the same amount in different months, a supplier
  paid to two legitimate IBANs from the start, invoices paid late but in full, and rounding to
  the cent. Each hard negative is a record `{id, kind, rows}`. At n = 200 every kind shall have at
  least `MIN_INSTANCES_PER_NEGATIVE = 15` instances. A **label-free** kind (no problem and no
  recurring series in it) may appear in noise-only scenarios; a **series-bearing** kind carries
  a `zs.recurring_charge` label and appears only in planted scenarios. Random amounts of
  irregular kinds are drawn once and never redrawn to avoid accidental regularity.

  *Acceptance.*
  - Kind `weekly_groceries_irregular` with merchant `FRESHCO` from 2025-02-05: 26 debit rows,
    dates 7 days apart (2025-02-05, 2025-02-12, …, 2025-07-30), amounts in 15.00–120.00; zero
    labels.
  - Kind `rounding_half_cent` uses the golden table of §2.7: base 12.50, rate 21 → VAT 2.63,
    total 15.13 (and rate written `21.00` for one of its rows); zero labels.
  - Kind `two_legit_ibans`: the supplier master has two rows with the same tax id and two
    different valid IBANs; invoices and payments use the second IBAN from the first invoice on;
    zero labels.
  - Salary: debit filter check. A noise-only zombie scenario containing six monthly credits of
    2450.00 yields 0 debit rows from them and 0 labels.

- **REQ-BM-08** *(noise)* Every scenario shall also hold realistic background noise: zombie 15 to
  40 one-off debits, each at a merchant used once, and 2 to 4 transfers to fictional people;
  phantom 2 to 5 clean suppliers (REQ-BM-10), 3 to 5 invoices each. Noise shall not be written to
  create or avoid a pattern.

  *Acceptance.* For the zombie noise-only scenario `zs-0000` built with seed 2026, the number of
  distinct merchants among its one-off rows equals the number of those rows, and it is between 15
  and 40.

- **REQ-BM-09** *(labels and their rows)* A label shall be the record `{id, scenario, type,
  rows, context_rows}`. `rows` are the `source_ref` values (`"{file}:{row_index}"`, row index
  0-based over the data rows, header excluded) of the rows that prove the problem;
  `context_rows` (for example the supplier-master row an IBAN is compared with) are listed but
  never used for matching. Rows are resolved from row tags after the final file order is fixed,
  never from positions computed earlier. The generator shall refuse to create a label whose
  `rows` is empty or whose refs are not rows of the written files.

  *Acceptance.*
  - A label `zs-0003/L2` with `rows == []` makes the build raise
    `ValueError("label zs-0003/L2 cites no row")`.
  - Reading every scenario through the real readers (`read_bank_statement`, `read_invoices`,
    `parse_suppliers`) gives zero quarantined rows, and every ref in every label resolves to a
    loaded row whose date, amount and counterparty (or invoice number) equal the facts the
    generator recorded for that ref.
  - Label rows of a duplicate-invoice label are all the invoice rows of the group.

- **REQ-BM-10** *(cleanliness and synthetic identifiers)* Outside its own labelled types a case
  shall produce no problem: every phantom invoice that is not part of an overdue case is paid in
  full 10 to 40 days after issue (payment date not after `as_of`), with the supplier's name and
  master IBAN, and duplicates are paid twice. Every case uses its own fresh supplier or merchant.
  All identifiers follow Finance Rules 5 and 6: fictional names, IBANs with a valid mod-97
  checksum and wrong Spanish national check digits (the only invalid IBANs are the planted ones
  of cases P07–P09), tax ids with a wrong control character, no e-mail, no phone. The generator
  carries its own small copy of the IBAN and tax-id helpers so a change to the demo generator
  never changes the benchmark bytes.

  *Acceptance.*
  - Case P01 (the same invoice twice) yields 2 invoice rows and 2 payment rows of the same
    amount, so `pi.reconciliation` has nothing to report for them.
  - Every generated tax id differs from the correct control character (checker in the test).
  - A generated IBAN that is not part of cases P07–P09 passes a test-local mod-97 check.

---

## 3 — The runner

- **REQ-BM-11** *(same pipeline)* `scripts/benchmark.py` shall run every scenario through the
  public pipeline of the app, and shall call detectors only through `run_all`.
  - Zombie: `read_bank_statement(io.BytesIO(bytes), source_file="statement.csv")` →
    `normalise(transactions)` → keep `flow == "debit"` → `run_all(debit_ledger, namespace="zs",
    context={"aliases": normalise_alias_map(...), "cancellation_dates": normalise_date_map(...),
    "cpi": None})`.
  - Phantom: `run_pipeline(invoice_sources, suppliers_source, payments_source, as_of)` and the
    alerts of its `results`.
  - The runner shall import `apps.zombie_subscriptions.detectors` and
    `apps.phantom_invoices.detectors` so the registry is filled by the apps' own discovery.

  *Acceptance.*
  - The zombie runner on the committed demo statement `zombie_demo_statement.csv` with the demo
    aliases and dates yields 19 alerts, the number pinned for the demo in
    `tests/test_showcase_app.py` (`ZS_DEMO_ALERTS`).
  - The phantom runner on the committed phantom demo with its `as_of` yields 9 alerts
    (`PI_DEMO_ALERTS`).
  - A statement with a salary credit of 2450.00 each month produces no alert from it.

- **REQ-BM-12** *(one matching rule)* Within one scenario, alerts are visited in ascending order
  of `(natural order of the first source_ref, type, source_refs)`. An alert is a **true positive**
  when a still-unmatched label of the same type exists whose `rows` share at least one
  `source_ref` with the alert; if several labels qualify, the one with the largest overlap wins,
  ties by label id. A matched label is consumed and cannot match a second alert. An alert that
  matches no label is a **false positive**; a label never matched is a **false negative**. Natural
  order sorts `file:9` before `file:10`. The rule is implemented once, as a pure function over plain
  records, and is printed word for word in `results.json` and `docs/benchmark.md`.

  *Acceptance (hand-made sets).* Types shortened; `L` label, `A` alert.
  - `L(t, [inv.csv:3])`, `A(t, [inv.csv:3])` → tp 1, fp 0, fn 0.
  - `L(vat_amount_mismatch, [inv.csv:3])`, `A(total_mismatch, [inv.csv:3])` → tp 0, fp 1, fn 1
    (same rows, different type).
  - `L(dup, [inv.csv:3, inv.csv:4])`, `A(dup, [inv.csv:4])`, `A(dup, [inv.csv:3])` → tp 1, fp 1,
    fn 0 (one label, one alert; the second alert is a false positive).
  - `L(t, rows [x.csv:1])` in scenario A, `A(t, [x.csv:1])` in scenario B → tp 0, fp 1, fn 1.
  - `L(t, rows [x.csv:1], context_rows [s.csv:0])`, `A(t, [s.csv:0])` → tp 0, fp 1, fn 1
    (context rows never match).
  - Two labels `L1(t, [f.csv:1, f.csv:2])`, `L2(t, [f.csv:2])` and one alert `A(t, [f.csv:2])` →
    L1 and L2 both overlap by 1; the lower id `L1` wins → tp 1, fn 1 (L2), fp 0.
  - No alerts, one label → tp 0, fp 0, fn 1. No label, one alert → tp 0, fp 1, fn 0.
  - Natural order: refs `f.csv:10` and `f.csv:9` → `f.csv:9` is visited first.

- **REQ-BM-13** *(metrics)* For a set of labels `L` and alerts `A`: `tp`, `fp = |A| − tp`,
  `fn = |L| − tp`, `precision = tp / |A|`, `recall = tp / |L|`. Ratios are `Decimal` quotients
  rounded half-up to 4 places and written as strings; a ratio with a zero denominator is `null`
  (JSON), shown as `n/a`. No `float` is used. Metrics are reported for each detector, each problem
  type, each app (micro total) and each hard-negative kind. For noise-only scenarios the runner
  also reports per detector `noise_only_alerts`, `noise_only_scenarios_with_alert` and
  `false_alarms_per_noise_scenario = noise_only_alerts / noise_only_scenarios` (4 places). A
  false-positive alert whose `source_refs` share a ref with the rows of a hard negative is
  attributed to the first such hard negative in id order; per kind the runner reports
  `instances`, `instances_with_false_alarm` and `false_alarms`. Alerts of a type missing from the
  catalogue are counted as false positives and listed under `types` with `labels: 0`.

  *Acceptance.*
  - tp 7, alerts 9 → precision `"0.7778"`; tp 7, labels 10 → recall `"0.7000"`; tp 2, labels 3 →
    `"0.6667"`; tp 1, labels 3 → `"0.3333"`; tp 5, alerts 5 → `"1.0000"`.
  - 0 alerts → precision `null`; 0 labels → recall `null`.
  - 6 alerts on 40 noise-only scenarios, raised in 4 of them → `false_alarms_per_noise_scenario`
    `"0.1500"`, `noise_only_scenarios_with_alert` 4.
  - An FP alert citing `statement.csv:12` where hard negative `NZ01` (`weekly_groceries_irregular`)
    has rows 5–30 → `NZ01`'s `false_alarms` 1 and `instances_with_false_alarm` 1.

- **REQ-BM-14** *(detector errors are not hidden)* `run_all` swallows a detector exception and
  returns no alerts. The runner shall capture the warning that `ledger_kit.detectors.registry`
  logs for it (`Detector '<name>' raised <Type>: <message>`), count it per detector and per
  scenario, store the counts as `errors` and, if any is non-zero, print them, write no file and
  exit with code 1.

  *Acceptance.*
  - Detector `pi.vat_error` replaced by a function raising `ValueError("boom")`, 3 phantom
    scenarios → stderr `detector pi.vat_error raised in 3 scenario(s); results not written`,
    exit code 1, files untouched.
  - No detector raises → `errors` is `{}` for every app.

- **REQ-BM-15** *(results.json)* The runner shall write `data/benchmark/results.json` with the
  schema of §3.5: `schema_version`, `seed`, `scenarios_per_app`, `matching_rule`, `limits`, and per
  app: `seed`, `scenarios`, `noise_only_scenarios`, `totals`, `detectors` (each with its own
  `seed`), `types`, `hard_negatives`, `scenarios_detail`, `false_positives`, `misses`, `errors`.
  Every false positive and every miss is listed with its scenario id, type and refs (no cap), so
  a failing scenario can be rebuilt. The file is `json.dumps(..., sort_keys=True, indent=2,
  ensure_ascii=False)` plus one final LF, encoded UTF-8 without BOM. It contains no date, time,
  duration, path or machine name.

  *Acceptance.*
  - Top-level keys in order: `apps`, `limits`, `matching_rule`, `scenarios_per_app`,
    `schema_version`, `seed`.
  - `results["apps"]["zombie"]["detectors"]["zs.price_increase"]["seed"] == results["seed"]`.
  - The text contains no `\r`, no run date or time and no absolute path (a test searches for
    the repository path, `datetime` formats and the machine name).

- **REQ-BM-16** *(docs/benchmark.md)* The runner shall write `docs/benchmark.md` from the
  results dict only: a first line saying it is generated by `python scripts/benchmark.py` and must
  not be edited; how to reproduce; the matching rule; per app the seed, the counts and one table
  `Detector | Planted | Found | Missed | False alarms | Precision | Recall | Clean scenarios with
  an alert`; the hard-negative table; and a **Limits** section with every string of `limits`. It
  contains no date and is UTF-8 with LF.

  *Acceptance.*
  - Rendering the same results dict twice gives identical text.
  - A results dict whose `limits` has 6 strings renders exactly 6 list items under `## Limits`.
  - The doc contains no number that is not in the results dict (test: every integer token of the
    document appears in the dict's values, a rendered ratio equals the stored string).

- **REQ-BM-17** *(command line)* `python scripts/benchmark.py` shall run seed `BENCHMARK_SEED`
  and `SCENARIOS_PER_APP` scenarios per app and write the two files. `--check` shall run the same
  and compare the bytes with the committed files without writing: exit 0 if equal, else exit 1
  with `data/benchmark/results.json differs from a fresh run; run python scripts/benchmark.py`
  (or the same for `docs/benchmark.md`). `--export-scenarios DIR` shall write every scenario (its
  CSV files and `labels.json`) under `DIR/<scenario id>/` for inspection; these files are not
  committed. `--seed N` and `--scenarios N` are allowed only together with `--out-dir DIR`, which
  redirects the two outputs, so a non-default run can never overwrite the committed files.

  *Acceptance.*
  - `python scripts/benchmark.py --seed 7` → exit 2, message `--seed and --scenarios need
    --out-dir`.
  - `python scripts/benchmark.py --seed 7 --scenarios 10 --out-dir out` → `out/results.json` and
    `out/benchmark.md`; the committed files are unchanged.
  - `--check` after editing one digit of `results.json` → exit 1 with the `results.json` message.
  - `--export-scenarios x` with 10 scenarios → `x/zs-0000/statement.csv`, `x/zs-0000/labels.json`,
    `x/pi-0000/invoices.csv`, `…/suppliers.csv`, `…/payments.csv`, `…/labels.json`.

- **REQ-BM-18** *(run time)* The full default run (both apps, all scenarios) shall take less than
  60 seconds on a laptop, so the committed-results test (REQ-BM-19) stays under a minute.
  `SCENARIOS_PER_APP` is the knob: if the measured full run exceeds 45 seconds, the count is
  lowered to the largest multiple of 20 that fits, and the new count is what `results.json` and
  the page state. Runtime is measured by the author, never written to a file.

  *Acceptance.* A measured full run of 52 s → `SCENARIOS_PER_APP` goes from 200 to 160 (or lower),
  results are regenerated, and `scenarios_per_app` in `results.json` reads that number.

---

## 4 — Determinism and committed results

- **REQ-BM-19** The same seed and the same scenario count shall give byte-identical
  `results.json` and `docs/benchmark.md`. A test shall run the benchmark once at the committed
  seed and count and compare the bytes with the committed files. `.gitattributes` shall mark
  `data/benchmark/*.json` and `docs/benchmark.md` as `-text` so Windows line-ending conversion
  cannot break the comparison. A second test shall run a reduced benchmark (10 scenarios per app)
  twice and compare bytes, and once with another seed to show the bytes differ.

  *Acceptance.*
  - Committed `results.json` with one digit edited → the committed-results test fails and names
    the first differing line.
  - Two runs with seed 2026 and 10 scenarios → equal bytes; seed 2027 → different bytes.
  - `git check-attr text data/benchmark/results.json` → `text: unset`.

---

## 5 — The Benchmark page

- **REQ-BM-20** `streamlit_app.py` shall have a fourth page **Benchmark** (icon 📊, `url_path`
  `benchmark`, after Phantom Invoices). It shall read `data/benchmark/results.json` with the
  standard library `json`, once per run, and show: one line with the seed and the scenario counts;
  per app one table with the columns of REQ-BM-16; the hard-negative table; the `Limits` list; and
  the sentence that the numbers come from synthetic data labelled by the project. It shall
  recompute nothing, and shall import neither `scripts`, `apps`, `ledger_kit.detectors` nor
  `pandas` code beyond display. This amends **REQ-SC-01** from three pages to four and
  `PAGE_TITLES` in `tests/test_showcase_app.py` accordingly.

  *Acceptance.*
  - `[spec.title for spec in streamlit_app.PAGES]` equals `["Home", "Zombie Subscriptions",
    "Phantom Invoices", "Benchmark"]`; the Benchmark spec has `url_path == "benchmark"`.
  - A results file with `zs.price_increase` labels 10, tp 7, fn 3, fp 2, precision `"0.7778"`,
    recall `"0.7000"` → the zombie table has the row `zs.price_increase | 10 | 7 | 3 | 2 | 0.7778 |
    0.7000`.
  - A results file whose `limits` is `["a", "b"]` → the page shows exactly two list items `a`, `b`.
  - A detector with `precision: null` → the cell shows `n/a`.

- **REQ-BM-21** *(no recomputation, no crash)* The page shall show the numbers of the file it
  reads and no others. If the file is missing, not JSON, or has another `schema_version`, the page
  shall show one `st.error` with the text `No usable benchmark results. Run: python
  scripts/benchmark.py` and raise no exception.

  *Acceptance.*
  - Replacing the file by a tiny synthetic results file with tp 1 shows tp 1, not the committed
    numbers (proves the page reads the file).
  - File missing → exactly one error element with the text above; `at.exception` is empty.
  - `schema_version: 99` → the same error.
  - The AST of `streamlit_app.py` imports none of `scripts`, `apps`, `ledger_kit.detectors`.

---

## 6 — Findings and hygiene

- **REQ-BM-22** *(no tuning here)* If the benchmark shows a detector error, this spec shall not
  change the detector, a threshold, a label or a hard negative to remove it. Each error is listed
  under **Follow-ups** in `design.md` with the scenario id, the failing input, the observed
  alert (or its absence) and the expected one. A label or hard negative changes only together
  with a change of the requirement it comes from, test first.

  *Acceptance.* After the first full run, every row of `results.json["apps"][*]["false_positives"]`
  and `["misses"]` is either covered by a Follow-up entry that names its scenario id and type, or
  by a Follow-up entry that groups them by hard-negative kind or case with one example id.

- **REQ-BM-23** *(hygiene)* The benchmark shall add no dependency to `requirements.txt`, make no
  network call, read no clock, and commit no real data. The new committed files are
  `data/benchmark/results.json` and `docs/benchmark.md`; `.gitignore` shall not ignore them
  (add `!data/benchmark/` and `!data/benchmark/**` after any `*.json` rule). The steering files
  `structure.md` and `finance-rules.md` (Rule 6) shall list `data/benchmark/` as generated output
  of synthetic data.

  *Acceptance.* `requirements.txt` is byte-identical before and after; `git status` after a run
  shows only the two files; the names `time`, `datetime.now`, `date.today`, `urllib` and `socket`
  do not occur in `scripts/generate_benchmark.py` or `scripts/benchmark.py` (test by AST).
