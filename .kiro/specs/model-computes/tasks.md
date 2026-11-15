# model-computes — Implementation Tasks

Every task is test-first: write the tests, see them fail for the right reason, then implement.
Section references (§) point to `design.md`, REQ ids to `requirements.md`. Verification
(`ruff check .`, `ruff format --check .`, `pytest`) is run by the user and by the hooks: session 27a
could not run commands. Existing test files are not edited. Tasks run in order.

Decision record: chosen by the owner on 15 Nov (improvement A of the adversarial review of 14 Nov),
drafted by Claude Code. See the overview of `requirements.md`.

## Session 27a

### Task MC1 — The helper in `money.py` and the module `calc.py`

**Covers**: REQ-MC-02 to REQ-MC-09, §3

- [x] Create `tests/test_calc.py`. Tier 1: the 539.40 computation with its formula line and
  operands, subtraction with parentheses, a share, unary minus, the currency of the data, several
  placeholders. Tier 2: every part that is not allowed (a decimal constant, a constant not in the
  question, an unknown field, a text field, a `bool`, a power, a modulo, a floor division, a call,
  an attribute, a unary plus, a division by zero by a constant and by a field, a syntax error, an
  empty expression, a string, an unclosed placeholder, an expression over the length limit, an
  overflow), half-up rounding, intermediate precision, `money.combine`. Tier 3 (Hypothesis,
  `max_examples=200`): any expression built from allowed fields, question numbers, operators and
  parentheses either computes or rejects; any text in a placeholder and any answer never raise.
- [x] Add `combine` to `ledger_kit/utils/money.py`; create `ledger_kit/calc.py` (§3).

### Task MC2 — The explainer

**Covers**: REQ-MC-01, REQ-MC-10 to REQ-MC-13, REQ-MC-15, §2

- [x] Create `tests/test_explainer_calc.py` with a mock client only: the 539.40 case accepted with
  its provenance line; the same figure written by hand rejected as today; `yearly_cost * 1.05`
  rejected; an unknown field, a power, a call and a division by zero rejected; digits and Spanish
  question words; no question; the index-as-cause check still runs; a wrong citation still
  rejected; the system prompt keeps the no-invention sentence verbatim and adds the placeholder
  rule; a Hypothesis test that no answer makes the explainer raise or leaves a placeholder in an
  accepted text.
- [x] In `ledger_kit/explainer.py`: the prompt rule, `Explanation.computed`, `_MONEY_FIELD_RE`, and
  `explain_with_meta` in the order of §2.

### Task MC3 — The display

**Covers**: REQ-MC-14, §4

- [x] Panel tests in `tests/test_explainer_calc.py`: `probe_result` keeps `computed` and
  `shown_text`; `computed_lines`; the verdict sentence of a rejected calculation; the verdict of a
  rejected figure unchanged.
- [x] `ledger_kit/live_guard.py` (helpers and `ProbeResult` fields) and the three `app.py` files
  (caption lines under the card answer; shown answer in the panel).

### Task MC4 — Documentation

**Covers**: REQ-MC-16

- [x] `README.md`: one paragraph after *The explanation is decorative*, the Specs row (18 specs),
  one row in the Decisions table. `tests/test_readme.py` read first; the paths named exist.

### Task MC5 — Record of the recorded verdicts (REQ-MC-11)

`tests/test_recorded_verdicts.py` pins, per run file, the record ids that end on the fixed
template. It is not edited and its sets are not changed.

| Run file | Pinned fallback ids | Change |
|---|---|---|
| `2026-11-10_llama3.2-3b.json` | Z4, Z6, P3, V1, V2 | none expected |
| `2026-11-10_llama3.2-3b_run2.json` | Z4b, Z6b | none expected |
| `2026-11-10_llama3.2-3b_run3.json` | Z3c, Z4c | none expected |
| `2026-11-11_llama3.2-3b_demo.json` | Z03, Z04, Z05, Z20, P27, V37 | none expected |

Why none can change: the files were recorded before the placeholder rule existed, so an answer in
them is plain prose. For a text without `[[calc` the function `resolve_calculations` returns it
unchanged (`guard_text == text == answer`, no computation, no rejection), and every later step is
the step of before. A record would change only if its raw answer contained `[[calc`; that was not
checked by running the suite in 27a (no shell), so **this record is an expectation until the first
`pytest` run**. If a set changes, write here, record by record, the record id, its raw answer's
placeholder, and why the new verdict is right; do not just edit the pinned set.

### Task MC6 — Record of Kiro calls (for the reviewer to fill in)

**Covers**: all of session 27a

Fill in after running the checks. One line per call; do not write what was not run.

## Session 27b — the period of a figure

Decision record: second part of the owner's choice of 15 Nov (improvement A of the adversarial
review of 14 Nov), drafted by Claude Code. Requirements group 6 of `requirements.md`, design §7.
Session 27b could not run commands either: the hooks lint each file and run the tests on stop.

### Task MC7 — Tests first

**Covers**: REQ-MC-17 to REQ-MC-24, §7

- [x] Create `tests/test_explainer_period.py` (mock client only). Tier 1: the MUSICBOX case
  (`10.99 EUR every year` on a monthly `current_amount`) rejected with `("10.99", "every year")`
  and reason `period_mismatch`, the card text being the filled template; the same amount `per
  month` passes; `yearly_cost` with `per month` rejected; both figures with their own period pass;
  the `yearly` of the next clause and a `monthly` in a clause with no figure do not bind (the shapes
  of records Z09 and Z11); Spanish cases (`al año`, `cada año`, `al mes`, `mensual` rejected; `al
  mes y ... al año`, `cuota mensual ..., coste anual ...`, `cada mes` pass); a figure with no period
  word passes; the ambiguous case (monthly `new_amount` 12.00 equal to `extra_cost_per_year`
  12.00) passes with either word; a computed figure with a contradicting word passes; the
  duplicate-subscription card (10.99 only in the rows) and other meaning (`raised its price to
  10.99 EUR per month`) still pass. Tier 2: each interval type with a word that agrees and one that
  contradicts; a yearly interval (per-charge and yearly fields agree) is checked; case and whole
  words (`Every Year` rejected, `yearly_cost` not a phrase); an unknown interval states no period;
  an invented figure is still reported by the number guard first; the period check runs before the
  index-as-cause check; the panel verdict sentence; `field_periods` on three detector shapes; an
  alert with no stated period; empty and figure-free texts. Tier 3 (Hypothesis,
  `max_examples=200`): a lone figure is rejected exactly when the phrase contradicts its field;
  any text never raises.

### Task MC8 — The check

**Covers**: REQ-MC-17 to REQ-MC-23, §7

- [x] In `ledger_kit/explainer.py`: the section *The period of a figure* (constants,
  `field_periods`, `find_period_mismatches`) and the step in `explain_with_meta` between the number
  guard and the index-as-cause check (DN-MC-06).

### Task MC9 — The panel and the documentation

**Covers**: REQ-MC-24, REQ-MC-26

- [x] `ledger_kit/live_guard.py`: `VERDICT_REJECTED_PERIOD_PREFIX` and its branch in
  `verdict_line`.
- [x] `README.md`, *What the guard does not check*, the **Meaning** item: rewritten so it stays
  true, with `MUSICBOX raised its price to 10.99 EUR per month` (from
  `test_other_meaning_is_still_not_checked`) as the example that still passes.
  `tests/test_readme.py` read first: it checks headings, paths in backticks, links and the Kiro
  table; the rewritten item names no path and no link. `docs/live-guard.md` does not repeat the
  MUSICBOX example, so it is not changed.

### Task MC10 — Record of the recorded verdicts (REQ-MC-25)

`tests/test_recorded_verdicts.py` is not edited. Every record of the four run files whose answer
holds a period phrase next to a figure was read against §7 (no shell in 27b, so by reading the
rule, not by running it):

| Record(s) | Sentence part with the phrase | Figure and field | Verdict of §7 |
|---|---|---|---|
| Z09 (demo) | `charge of €2.99 ...`, `with a total yearly cost of €35.88` | `yearly` is in the second clause, next to 35.88 (`yearly_cost`) | agrees |
| Z11, Z19 (demo) | `... is €107.88`, `indicating that six monthly charges have been made` | `monthly` stands in a clause with no figure | not checked |
| Z14, Z15, Z17, Z18 (demo), V39 second sentence (demo) | `made monthly`, `interval type being monthly`, `part of a monthly pattern`, `made monthly and has been active for six months`, `charged annually` | clauses with no figure | not checked |
| Z16 (demo) | `six monthly charges of €2.99` | 2.99 (`current_amount`, monthly) | agrees |
| Z04, Z05 (demo) | `€36.00 per year`, `yearly cost of €155.88` / `€191.88` | `extra_cost_per_year`, `yearly_cost` | agrees (both already pinned for the index as cause) |
| V36 (demo), V2b, V2c | `new monthly charge amount increasing from €5.00 to €6.50`, `€18.00 per year`, `yearly cost of/to €78.00` | 5.00 (`old_amount`, monthly), 18.00 (`extra_cost_per_year`), 78.00 (`yearly_cost`) | agrees |
| V38 (demo) | `recurring monthly fee of €6.50`, `total yearly cost of €78.00` | `current_amount` monthly, `yearly_cost` | agrees |
| V39 (demo) | `recurring yearly fee of €30.00` | 30.00 is `current_amount` of a yearly fee and `yearly_cost`, both yearly | agrees |
| V40 (demo) | `recurring quarterly fee of €9.00`, `total yearly cost of €36.00` | `current_amount` quarterly, `yearly_cost` | agrees |
| Z07, Z08, Z10, Z12, Z13, Z22 (demo), Z1, Z3 (run 1), Z1b, Z2b, Z3b (run 2), Z6c (run 3) | `yearly cost ... €N` | `yearly_cost` | agrees |

No other record holds a phrase of REQ-MC-19 (`in the past year`, `each month`, `next month`,
`every quarter`, `per annum` and `in five years` are not phrases). So no record changes verdict and
no pinned set changes:

| Run file | Pinned fallback ids | Change |
|---|---|---|
| `2026-11-10_llama3.2-3b.json` | Z4, Z6, P3, V1, V2 | none expected |
| `2026-11-10_llama3.2-3b_run2.json` | Z4b, Z6b | none expected |
| `2026-11-10_llama3.2-3b_run3.json` | Z3c, Z4c | none expected |
| `2026-11-11_llama3.2-3b_demo.json` | Z03, Z04, Z05, Z20, P27, V37 | none expected |

As in MC5 this is an expectation until the first `pytest` run. If a set changes, write here, record
by record, the record id, the figure and phrase in `rejected_numbers`, and why the new verdict is
right; then add the id to the pinned set.

DN note: a sentence-wide rule (the literal reading of the task) would have flipped Z09, Z11 and
Z19, three correct answers; that is why §7 ties a phrase to the nearest figure of its clause
(DN-MC-07).

### Task MC11 — Record of Kiro calls of session 27b (for the reviewer to fill in)

**Covers**: all of session 27b

Fill in after running the checks. One line per call; do not write what was not run.
