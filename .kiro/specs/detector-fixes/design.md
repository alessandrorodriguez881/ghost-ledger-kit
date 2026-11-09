# detector-fixes — Design

Section numbers are referenced by `tasks.md`. Decisions carry an id `D-DF-nn` (§6). Facts were
read from the code and specs in session 10d; **nothing was run**. Where a behaviour is inferred
it is marked *(inferred)*.

## 1 Findings that lead to this spec

| Finding | Detector | First measurement (seed 2026, 200 scenarios) | Cause | Fix |
|---|---|---|---|---|
| F3 | `pi.iban_change` | 140 false alarms, all on `two_legit_ibans` (35 of 35 instances, 4 alarms each); precision `0.5000` | `build_master` keeps the first master row per tax id (REQ-PI-09) | §2 |
| F2 | `zs.recurring_charge` | 29 false alarms, all on `fuel_irregular` (12 of 43 instances) and `weekly_groceries_irregular` (13 of 43) | the variable-bill branch (REQ-ZS-10a(3)) accepts amounts within 10 % of the median from any cadence run picked out of a stream; the span guard of REQ-ZS-10b covers quarterly and yearly series only | §3 |

F1 (`zs.duplicate_subscription`, 75 of 84 missed) was a generator error; D-BM-20 of the benchmark
spec. It is not repeated here. Because D-BM-20 changes the zombie scenarios, the "first
measurement" of F2 is re-measured after it (task DF0); the numbers above are the committed ones
before that.

## 2 Phantom: several accounts per supplier

### 2.1 Where the code is

- `apps/phantom_invoices/detectors/utils.py`: `Master` (`by_tax`, `by_name`, `by_iban`),
  `build_master`, `attribute_payment`.
- `apps/phantom_invoices/detectors/iban_change.py`: `_valid_master_key`, `_invoice_differs`,
  `_payment_differs`, `detect_iban_changes` (step 1 master rows, 2 invoices, 3 payments).
- `apps/phantom_invoices/detectors/reconciliation.py` reads `master.by_tax[...]` and
  `attribute_payment`; nothing else reads the master.
- `Alert.data` keys of the two critical variants are pinned by `test_pi_iban_change.py`
  (`master_iban_masked`, `last4_identical`, ...). They stay.

### 2.2 Change

```python
@dataclass(frozen=True)
class Master:
    by_tax: Mapping[str, dict]              # first row per tax_key: names the supplier (unchanged)
    by_name: Mapping[str, tuple[dict, ...]] # distinct suppliers by name_key (unchanged: first rows)
    by_iban: Mapping[str, tuple[dict, ...]] # iban_key of ANY master IBAN -> the supplier's first row
    rows_by_tax: Mapping[str, tuple[dict, ...]] = field(default_factory=dict)  # NEW: all rows, source_ref order
```

`build_master`:

1. `load_rows(suppliers, None)` already returns rows in `source_ref` order; group them by
   `tax_key` into `rows_by_tax`; `by_tax[tax] = rows_by_tax[tax][0]` (same as today).
2. `by_name` is built from `by_tax.values()` as today (a second row's differing name is not
   indexed, as the existing edge test pins; see OD-DF-03).
3. `by_iban`: for every tax and every row of `rows_by_tax[tax]` with a present IBAN, add the
   **first row** of that tax under `iban_key(row IBAN)` once (no repeat of one supplier under
   one key). Two suppliers sharing an IBAN still give two hits, so attribution falls through as
   today.

New helper, in `utils.py` next to `build_master`:

```python
def accepted_accounts(master: Master, tax: str) -> tuple[tuple[str, dict], ...]:
    """(iban_key, master row) for every row of the tax id with a present, valid IBAN, deduplicated
    by key, in source_ref order."""
```

Validity is `iban_problem(iban_key(text)) is None` (the same function `iban_change` uses).

`iban_change.py`:

- Step 1 loops over `row in rows` for every tax in `rows_by_tax` (REQ-DF-06).
- Invoice: `accounts = accepted_accounts(master, tax_key(supplier_tax_id))`; skip when there is no
  supplier or no account, or when the invoice `key` is among the account keys; otherwise
  `_invoice_differs(row, ref, number, sup, raw_iban, accounts)`.
- Payment: `sup = attribute_payment(row, master)` returns the supplier's first row; the tax is
  `tax_key(sup["tax_id"])`; the same test; `_payment_differs(..., accounts)`.
- Both builders: `master_masked = mask_iban(<first account's IBAN text>)`; `last4_identical` is
  true when `invoice_masked` (or `payment_masked`) equals the mask of any account;
  `source_refs = sort_refs([ref, naming row ref, *account row refs])`.
- `_valid_master_key` is replaced by `accepted_accounts`; with one row per tax the result is the
  same single key as before (REQ-DF-09).

### 2.3 Effects on other code

- `pi.reconciliation`: its `reconcile` uses `build_master` and `attribute_payment` *(inferred
  from the grep: `reconcile` is called with `suppliers` and builds its own master at line ~386)*.
  A payment to a supplier's second account whose name does not decide is now attributed to the
  supplier and can match its invoice. This is the intended correction, not a side effect to
  remove. Demo: unique tax ids, no change.
- `test_pi_utils_master.py::test_duplicate_tax_key_first_in_source_ref_order_wins` asserts
  `IBAN_2 not in master.by_iban`. It becomes `IBAN_2 in master.by_iban` with the first row as
  value; the other assertions (by_tax, by_name) stay.
- The explanation templates (`explain_support.py`) are untouched: the key set is the same
  (OD-DF-02).

### 2.4 What this does not do

- It does not accept an IBAN because an earlier invoice used it (REQ-DF-08).
- It does not compare names of rows of one tax id (OD-DF-03).
- It does not change the `iban_invalid` rule for invoices and payments.

## 3 Zombie: stable amounts as well as regular dates

### 3.1 Where the code is

All in `apps/zombie_subscriptions/detectors/utils.py`:

- `_segment_by_price(run, interval)`: branch 1 stable, branch 2 one step, branch 3 variable bill
  (`_within_match_ratio`).
- `_accept(series, key_rows)`: today only quarterly and yearly series are checked with
  `_other_rows_in_span`.
- `longest_cadence_run`: keeps rows whose gap fits nominal ± 3 days and **skips** rows that are
  closer than that; this is why three charges 28 days apart are found among weekly purchases.
  It is not changed: skipping is what lets parallel series (E4) be found.
- `find_series` phases 1 (price buckets), 2 (`_extend_once`, `_merge_once`), 3 (leftover runs)
  all call `_segment_by_price` and `_accept`, so one change at those two places covers all three.

### 3.2 Change

```python
# Intervals whose cadence run may be accepted as a variable bill (amounts within AMOUNT_MATCH_RATIO
# of the median but not one price level). Weekly runs are excluded: variable weekly spending is
# ordinary shopping (REQ-DF-10).
VARIABLE_BILL_INTERVALS: tuple[str, ...] = ("monthly", "quarterly", "yearly")

@dataclass
class Series:
    ...
    step_index: int | None = None
    variable: bool = False   # accepted as a variable bill (branch 3); needs an exclusive span

# _segment_by_price, branch 3
if interval["name"] in VARIABLE_BILL_INTERVALS and _within_match_ratio(amounts):
    return _make_series(run, interval, round_to_cents(median(amounts)), [], variable=True)

# _accept
long_interval = series.interval_type in ("quarterly", "yearly")
if (long_interval or series.variable) and _other_rows_in_span(series.rows, key_rows):
    return None
```

`_make_series` gets a keyword `variable: bool = False`. The constant sits in the constants block
of `utils.py` after `AMOUNT_MATCH_RATIO`, with the comment above (Finance Rule 7). Nothing else
changes: no threshold, no interval table.

### 3.3 Why exactly these two rules

Three facts decide it.

1. REQ-ZS-09 E7 and E7b already say that weekly charges with varying amounts at one shop give no
   alert. E7b is a *deterministic* fixture of 13 price levels more than 10 % apart; it proves the
   rule only for amounts chosen to pass. Random amounts expose the branch (finding F2).
2. The variable-bill branch is the only branch whose amount test is loose (10 % of the median,
   five times the 2 % of a price level). Everything else needs equal amounts or one clean step.
   The looser the amount test, the more the finder must know about the cadence. A shop that is
   visited every week has a cadence of its own, so the monthly or weekly subsequence picked out of
   it proves nothing: the other visits are right there between the charges.
3. REQ-ZS-10b already uses this idea for quarterly and yearly series, where the same coincidence
   would otherwise appear. DF-11 extends it to the branch that needs it, instead of to every
   series: a subscription at a shop that sells other things (a stable 20.00 every month and a
   12.50 purchase between) must still be found (REQ-DF-12).

REQ-DF-10 is needed in addition because a weekly run of consecutive visits has **no foreign
row** in its span, so DF-11 alone would not stop four consecutive similar groceries. Weekly is
the interval where "similar by chance" is the norm and "variable bill" is not a real pattern.

Alternatives considered and rejected (D-DF-03): lowering `AMOUNT_MATCH_RATIO` (a threshold
change, forbidden by REQ-DF-18, and it would break E4/Z13 duplicates within 10 %); requiring more
occurrences for variable bills (a threshold again, and it still accepts a long coincidence in a
long stream); rejecting any series that has a foreign row in its span (breaks E3, E4, Z11 to Z13
and every subscription at a shop that also sells other things).

### 3.4 Expected effect, and what stays *(inferred, not measured)*

- F2 mechanism 1 (a monthly triple picked out of a weekly stream, `zs-0000`) is removed because
  six foreign rows lie in its span. Mechanism 2 (four consecutive similar weekly charges,
  `zs-0036`) is removed for variable amounts. If the four weekly amounts of `zs-0036` are within
  2 % of their median, the run is a *stable* level and is still accepted: that is limit 2 of
  REQ-DF-20, not a bug of the fix. The benchmark will say how often it happens; the expected
  number is small because two random amounts must agree within a few percent four times in a row.
- Hard negatives `weekly_groceries_irregular` and `fuel_irregular` are not "all clean" by
  construction after the fix. Any remaining false alarm is read and classified (REQ-DF-16).
- Demo: all recurring charges are stable or one step; `GLOWBILL` 2.99 and 0.99 are two stable
  levels in separate price buckets; the groceries are not series today and cannot become series
  because the fix only removes acceptances. Alerts that depend on a removed series would drop;
  there is none *(inferred from reading the demo statement, confirmed by the demo tests the user
  runs)*.
- Detectors that use `find_series` (`recurring_charge`, `price_increase`, `duplicate_subscription`,
  `free_trial_to_paid`, `charges_after_cancellation`, `service_yearly_cost`) see the same smaller
  set of series. A duplicate-subscription pair made of variable bills with foreign rows
  disappears with them; the benchmark pairs (Z11 to Z13, NZ14) are stable.

## 4 Tests (test first; every new test extends an existing file)

New test files under `apps/phantom_invoices/` must be added to `test_pi_structure_steering.py`
and `structure.md`; to avoid that, every test below goes into an existing module.

| Fix | File | Tests |
|---|---|---|
| DF-01 | `apps/phantom_invoices/tests/test_pi_utils_master.py` | `rows_by_tax` keeps every row in `source_ref` order whatever the frame order; `by_tax` still the first row; `by_iban` maps the second account to the first row once; `accepted_accounts` skips invalid and missing IBANs and deduplicates keys; the amended `test_duplicate_tax_key…` |
| DF-02..05, 08 | `…/test_pi_iban_change.py` | the acceptance examples of REQ-DF-02, 03, 04, 05, 08 with exact `source_refs`, `master_iban_masked`, `last4_identical` and the unchanged key sets; a debit to the second account with an unmatched name |
| DF-06 | `…/test_pi_iban_change.py` | second master row with a broken checksum raises one `iban_invalid` citing that row |
| DF-07 | `…/test_pi_utils_master.py`, `…/test_pi_reconciliation.py` | two rows of one tax id are one name hit; attribution by the second account; two suppliers with one name still fall through; a payment to the second account now matches its invoice |
| DF-09 | existing `test_pi_demo_e2e.py`, `tests/test_showcase_app.py` | unchanged; they must pass |
| Property (phantom) | `…/test_pi_iban_change.py` | Hypothesis: for any master of 1 to 4 rows with one tax id and valid distinct IBANs, an invoice or payment on any of them gives no alert, and on any other valid IBAN gives exactly one critical alert citing the invoice and all the rows; `source_refs` always a subset of `loaded_source_refs(ledger, context)` (testing.md). `max_examples=200`. |
| DF-10 | `apps/zombie_subscriptions/tests/test_zs_segment_by_price.py` | weekly 100.00, 104.50, 109.00, 113.50 → `None`; the same amounts monthly → a series with `variable=True`; stable and step series have `variable=False`; an ambiguous split (no step recorded) is accepted only by branch 3 and has `variable=True` (`test_ambiguous_split_is_a_variable_bill`); weekly stable and weekly step still accepted |
| DF-11, 12, 13 | `…/test_zs_find_series.py` | E7c, E7d, the stable-with-purchase case, the extension and merge examples of REQ-DF-13, limit tests of REQ-DF-20 |
| DF-10, 11 | `…/test_zs_recurring_charge.py` | the same examples at alert level: no `zs.recurring_charge` alert for E7c and E7d |
| Property (zombie) | `…/test_zs_find_series.py` | Hypothesis, two properties. (1) Weekly: for 4 to 5 charges whose amounts are spaced by more than 4 % of the base and are within 10 % of their median, `find_series` returns `[]`. (2) Foreign row: for a monthly variable triple (amounts within 10 % of the median, not one level) plus one other row under the key inside the span, `find_series` returns `[]`; without the other row it returns one series. `max_examples=200`, dates built from a fixed start. |
| Constants | `…/test_zs_utils_normalise.py` | `VARIABLE_BILL_INTERVALS == ("monthly", "quarterly", "yearly")`; all other pinned constants unchanged (REQ-DF-18) |
| Demo | existing `test_zs_demo_e2e.py`, `tests/test_showcase_app.py` | unchanged; 3 tombstones, 19 alerts |

Tests that may need an amendment, to be found when the user runs `pytest` after the zombie code
task, and amended in that task with a comment naming REQ-DF-10 or REQ-DF-11 *(inferred, from a
grep: none is known to encode a weekly variable bill)*: `test_zs_segment_by_price.py`
(`test_variable_bill_within_10pct_uses_median` is monthly and stays), `test_zs_recurring_charge.py`
(`test_amount_boundary_at_match_ratio` is monthly with nothing else under the key and stays).

## 5 Proof by the benchmark (REQ-DF-16)

The benchmark is the second proof, after the unit tests; it is never a pass mark (D-BM-13).

1. **DF0 baseline.** After the D-BM-20 generator fix, the user runs `python scripts/benchmark.py`
   and commits both files. This is the zombie baseline; the phantom block is unchanged because
   the phantom generator did not change.
2. **After the phantom task.** `python scripts/benchmark.py`; compare with the baseline. Expected:
   `pi.iban_change` false alarms on `two_legit_ibans` = 0; every other phantom figure unchanged
   (`1.0000` / `1.0000` for the other detectors). If any other phantom figure moves, that is a
   regression to explain before going on.
3. **After the zombie task.** `python scripts/benchmark.py`. Expected: the 29 false alarms fall;
   the recall of the other zombie detectors does not drop (a drop would mean a stable or step
   series was lost: regression). Remaining false alarms are listed with scenario ids.
4. Each re-run is committed with `docs/benchmark.md`; the figures go into the table of
   `.kiro/specs/benchmark/design.md` §8 and the coverage index there is updated (the test of
   Task BM9 fails until it is).

The seed (2026), the scenario count (200), the generator, the labels and the hard negatives are
the same across steps 2 and 3, so differences are caused by the detector change alone.

## 6 Decisions

- **D-DF-01 Fix on principle, not on the seed.** Each fix is stated as a rule of the domain
  (a supplier may have several accounts; a loose amount rule needs an exclusive cadence) with
  examples that do not come from the benchmark.
- **D-DF-02 The master alone defines accepted accounts** (REQ-DF-08): trust comes from the
  document the user controls, never from traffic.
- **D-DF-03 No threshold is changed** (REQ-DF-18). Lowering `AMOUNT_MATCH_RATIO` or raising
  `MIN_OCCURRENCES_*` was considered and rejected in §3.3.
- **D-DF-04 One guard, at the acceptance point.** `_accept` already runs in all three phases of
  `find_series`; a flag on `Series` is cheaper and clearer than re-running the segmentation.
- **D-DF-05 Weekly variable bills are excluded as a class** (REQ-DF-10), because DF-11 alone does
  not cover consecutive visits. If the owner disagrees, the alternative is a longer minimum for
  weekly variable runs, which is a threshold and needs its own decision (OD-DF-04).
- **D-DF-06 Key set of the iban alerts unchanged** (OD-DF-02), so templates, UI and the pinned
  test do not change.

## 7 Not verified by the author

Written without running a command. Unverified: that the zombie fix removes the false alarms of
F2 (the user's re-run decides); that no existing zombie test encodes a weekly variable bill or a
variable bill with a foreign row; that `reconcile` builds its own master as inferred; that the
demo statement contains no variable-bill series; and the exact numbers of every acceptance
example (the run-through of the 100.00, 104.50, 109.00, 113.50 and 90.00, 95.00, 100.00 examples
was done by hand against `_segment_by_price`, not executed).
