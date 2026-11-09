# detector-fixes — Implementation Tasks

Every task is test-first: write the tests (they fail), then the code. Section references (§)
point to `design.md`, REQ ids to `requirements.md`. Verification (`ruff check .`,
`ruff format --check .`, `pytest`, and where named `python scripts/benchmark.py`) is run by the
user, who sends back the results. No task changes a threshold constant, the benchmark seed, the
scenario count, the generator, a label or a hard negative (REQ-DF-18). New tests go into
existing test modules (design §4) so that no new file has to be listed in the structure steering.

Order: DF0 (baseline) → DF1 (phantom) → DF2 (phantom proof) → DF3 (zombie) → DF4 (zombie proof)
→ DF5 (spec text). The phantom and zombie fixes are independent; the proof steps are in this
order so that each re-run isolates one change (design §5).

## Task DF0 — Baseline after the generator fix

**Covers**: REQ-DF-16, design §5 step 1

- [x] **User action.** The benchmark generator changed in session 10d (D-BM-20), so the committed
  `data/benchmark/results.json` and `docs/benchmark.md` are stale. Run
  `python scripts/benchmark.py`, then `python scripts/benchmark.py --check` (exit 0) and
  `pytest tests/test_benchmark_runner.py`. Commit both files. *(Done, commit `6a3542f`; the 63
  benchmark runner tests pass.)*
- [x] Record in `.kiro/specs/benchmark/design.md` §8, row "After D-BM-20": zombie precision and
  recall, and whether `zs.duplicate_subscription` recall rose (expected, not measured). Update
  the coverage index there if the list of false positives or misses changed. *(Recorded in
  session 11a. The index is unchanged on purpose: a test pins `zs.duplicate_subscription` in it.)*
- [x] Read the zombie `false_positives` again: if the 29 false alarms of F2 moved, write the new
  count here before going on (it is the baseline for DF4). *(Baseline, seed 2026, 200 scenarios:
  zombie planted 1002, alerts 1031, found 1002, missed 0, **false alarms 29** (all
  `zs.recurring_charge` on `fuel_irregular` and `weekly_groceries_irregular`), precision
  `0.9719`, recall `1.0000`; `zs.duplicate_subscription` 84 of 84. Phantom: planted 480, alerts
  620, found 480, **false alarms 140** (all `two_legit_ibans`), precision `0.7742`, recall
  `1.0000`. The F2 count did not move.)*

## Task DF1 — Phantom: several accounts per supplier

**Covers**: REQ-DF-01 to REQ-DF-09, REQ-DF-19, design §2

- [ ] Tests first, in existing modules (design §4):
  - `apps/phantom_invoices/tests/test_pi_utils_master.py`: `rows_by_tax` (all rows, `source_ref`
    order, frame order irrelevant); `by_tax` still the first row; `by_iban` holds the second
    account once, mapped to the first row; `accepted_accounts` (invalid and missing skipped,
    keys deduplicated); name hit counts one supplier for two rows of one tax id; attribution by
    the second account; two suppliers with one name or one account still fall through. Amend
    `test_duplicate_tax_key_first_in_source_ref_order_wins`: `IBAN_2 in master.by_iban` (value:
    the first row), `by_tax` and `by_name` assertions stay; add a comment naming REQ-DF-01.
  - `apps/phantom_invoices/tests/test_pi_iban_change.py`: the acceptance examples of REQ-DF-02,
    03, 04, 05, 06, 08 (exact `source_refs`, `master_iban_masked`, `last4_identical`, unchanged
    key sets `{...}` already pinned in the file); one Hypothesis property (design §4,
    `max_examples=200`) including `source_refs` ⊆ `loaded_source_refs(ledger, context)`.
  - `apps/phantom_invoices/tests/test_pi_reconciliation.py`: a payment to the second account
    with a name that decides nothing matches its invoice (REQ-DF-07).
  - Use only the fictional names, IBANs (valid mod-97, wrong national digits) and tax ids of
    Finance Rule 5; reuse the builders of `pi_builders.py`.
- [ ] Code: `Master.rows_by_tax` (default empty mapping), `build_master`, `accepted_accounts` in
  `apps/phantom_invoices/detectors/utils.py`; replace `_valid_master_key` and extend
  `_invoice_differs` / `_payment_differs` / `detect_iban_changes` in `iban_change.py` (design
  §2.2). Docstrings stay one line; constants none.
- [ ] Verification by the user: `ruff check .`, `ruff format --check .`, `pytest
  apps/phantom_invoices tests/test_showcase_app.py` (demo still 9 alerts, 3 critical and 6
  warning), then the whole `pytest`.

## Task DF2 — Phantom proof by the benchmark

**Covers**: REQ-DF-16, design §5 step 2

- [ ] **User action.** `python scripts/benchmark.py`; compare `data/benchmark/results.json` with
  the DF0 commit: `pi.iban_change` false alarms on `two_legit_ibans` expected **0**; precision of
  `pi.iban_change` and of the phantom app expected `1.0000`; every other figure unchanged. Commit
  both files.
- [ ] Record the figures in `.kiro/specs/benchmark/design.md` §8 (row "After `detector-fixes`
  phantom task"); remove `two_legit_ibans` from the coverage index only if no false positive
  with that kind remains in the committed results.
- [ ] If any other phantom figure moved, stop and explain it before DF3 (regression).

## Task DF3 — Zombie: stable amounts as well as regular dates

**Covers**: REQ-DF-10 to REQ-DF-15, REQ-DF-19, REQ-DF-20, design §3

- [ ] Tests first, in existing modules (design §4):
  - `apps/zombie_subscriptions/tests/test_zs_segment_by_price.py`: weekly 100.00, 104.50,
    109.00, 113.50 → `None`; the same amounts monthly → series with `variable=True`; stable,
    step-change and ambiguous-split series have `variable=False`; weekly stable (4 × 100.00) and
    weekly step (100.00, 100.00, 108.00, 108.00) still accepted.
  - `apps/zombie_subscriptions/tests/test_zs_find_series.py`: E7c, E7d, the stable-with-purchase
    case (REQ-DF-12), the extension and merge examples (REQ-DF-13), the two limit tests of
    REQ-DF-20, and the two Hypothesis properties of design §4 (`max_examples=200`, dates from a
    fixed start, no clock).
  - `apps/zombie_subscriptions/tests/test_zs_recurring_charge.py`: E7c and E7d at alert level.
  - `apps/zombie_subscriptions/tests/test_zs_utils_normalise.py`: pin
    `VARIABLE_BILL_INTERVALS == ("monthly", "quarterly", "yearly")`.
- [ ] Code in `apps/zombie_subscriptions/detectors/utils.py` only: the constant
  `VARIABLE_BILL_INTERVALS` after `AMOUNT_MATCH_RATIO`; `Series.variable` with default `False`;
  `_make_series(..., variable=False)`; branch 3 of `_segment_by_price`; the condition in
  `_accept` and its docstring (design §3.2).
- [ ] Verification by the user: `ruff check .`, `ruff format --check .`, `pytest
  apps/zombie_subscriptions tests/test_showcase_app.py` (demo 3 tombstones, 19 alerts), then the
  whole `pytest`. If an existing test fails because it encodes a weekly variable bill or a
  variable bill with a foreign row, amend that test in this task with a comment naming REQ-DF-10
  or REQ-DF-11 and list it in the report; do not weaken any other test.

## Task DF4 — Zombie proof by the benchmark

**Covers**: REQ-DF-16, design §5 step 3

- [ ] **User action.** `python scripts/benchmark.py`; compare with the DF2 commit. Expected: the
  false alarms of `zs.recurring_charge` on `fuel_irregular` and `weekly_groceries_irregular` fall
  sharply from the DF0 count; the recall of every zombie detector does not drop. Commit both
  files.
- [ ] For every remaining false alarm: open the exported scenario
  (`python scripts/benchmark.py --export-scenarios bm_export`, a temporary folder, never
  committed or cited), read the rows, and write one line in the Follow-ups of the benchmark
  design: either a new finding (new REQ-DF in this spec, test first) or the accepted limit 2 of
  REQ-DF-20. Update the coverage index. Never change a threshold, label or hard negative.
- [ ] Record the figures in `.kiro/specs/benchmark/design.md` §8 (row "After `detector-fixes`
  zombie task").
- [ ] If the recall of a zombie detector dropped, stop: a stable or step-change series was lost;
  fix the guard before anything else.

## Task DF5 — Spec text and documentation

**Covers**: REQ-DF-17

- [ ] `.kiro/specs/phantom-invoices/requirements.md`: amend REQ-PI-09 (all rows kept, accepted
  accounts), the master row bullet of REQ-PI-24, REQ-PI-25 (one supplier per tax id); add one
  line "Amended by REQ-DF-01 to REQ-DF-07 (session 10d)". Add the matching note to the phantom
  `design.md` where it describes `build_master`.
- [ ] `.kiro/specs/zombie-subscriptions/requirements.md`: amend REQ-ZS-10a(3) (monthly,
  quarterly, yearly only) and REQ-ZS-10b (a variable bill needs an exclusive span); add the
  examples E7c and E7d to the table of REQ-ZS-09; same note. Add the matching note to the zombie
  `design.md` §4.3.
- [ ] `.kiro/specs/benchmark/design.md` §8: mark F2 and F3 "fixed by `detector-fixes` (DF1/DF3),
  measured in DF2/DF4" with the final figures; keep FU-P3 open.
- [ ] Out of scope, noted for the reviewer: the README and Home page sentences that cite the
  benchmark numbers (session 7).

## Not verified by the author

The tasks were written without running a command. The user runs `ruff check .`,
`ruff format --check .`, `pytest` and the benchmark re-runs of DF0, DF2 and DF4, and reports
failures and figures.
