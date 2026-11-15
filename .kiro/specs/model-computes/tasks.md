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

## Session 28a — the recording script

Decision record: third part of the owner's choice of 15 Nov (improvement A of the adversarial
review of 14 Nov: re-record the answers with the new prompt), drafted by Claude Code. Requirements
group 7 of `requirements.md`, design §8. Session 28a could not run commands either: the hooks lint
each file and run the tests on stop.

### Task MC12 — Tests first

**Covers**: REQ-MC-27 to REQ-MC-33, §8

- [x] Create `tests/test_record_live_run.py` (fake client only, no network). Tier 1: the plan has
  the scope of the 11 Nov file (43 records, the same pairs of alert id and question id, the same
  count per app letter, ids `[ZPV]\d{2}`); the three questions on the first critical card of each
  app, after its cards; the dry run lists 43 records, writes nothing and calls nothing; a run with
  a fixed answer writes the top-level fields of the 11 Nov file in its order and every record with
  its fields plus `observed_reason` and `observed_calcs` (the zombie forecast probe accepted with
  `yearly_cost 107,88 EUR x 5 = 539,40 EUR`, a card rejected with `calc_not_allowed`), the file
  absent while the run goes on, one printed line per record; `--out` on an existing file refused,
  nothing asked or written. Tier 2: a client that raises on the first record gives that record as
  a fallback with an empty raw answer and `no_answer`, and the run continues; no key and no client
  refused before asking; a missing folder refused; `--out` required; `figure_not_found`.

### Task MC13 — The script

**Covers**: REQ-MC-27 to REQ-MC-33, §8

- [x] Create `scripts/record_live_run.py` (§8).

### Task MC14 — Documentation

**Covers**: REQ-MC-34

- [x] `README.md`, the *No key needed, real model output* paragraph: two sentences (how to
  re-record; one run, not a rate). `tests/test_readme.py` read first: both paths named in
  backticks exist.
- [x] `docs/live-guard.md`, end of *The first real run*: the same in two sentences. It names no new
  environment variable and no percentage (`tests/test_live_guard_docs.py`).

### Task MC15 — Record of Kiro calls of session 28a (for the reviewer to fill in)

**Covers**: all of session 28a

Fill in after running the checks. One line per call; do not write what was not run.

## Session 28b — amendments from the first real run

Decision record: the owner recorded `data/live_runs/2026-11-15_llama3.2-3b_calc.json` on 15 Nov
(llama3.2:3b, Ollama, CPU, 22 minutes, 43 records: 30 accepted, 13 fallback, no calculation
accepted) and asked for three amendments. Requirements group 8, design §9. Session 28b could not
run commands either: the hooks lint each file and run the tests on stop, and the pinned set of
MC18 was derived by reading, not by running.

### Task MC16 — Tests first

**Covers**: REQ-MC-35 to REQ-MC-37, §9

- [x] Create `tests/test_calc_amendments.py`. The raw answers of Z03, Z06, Z20, Z21, P32 and V41
  are read from the 15 Nov file and replayed through `explain_with_meta` with the real alert of
  each: Z03 and Z20 accepted with their computed figures and provenance (`yearly_cost 359,76 EUR
  = 359,76 EUR`; `5 x yearly_cost 107,88 EUR = 539,40 EUR` twice); P32 rejected with `2`; V41
  rejected with `total = interest_total + fee_total`; Z06 rejected with `12`; Z21 rejected with
  `8.99` (see MC18, it differs from the expectation of the request). A plain card's system prompt
  equals the old prompt, written out in the test (also with an empty question); a question adds
  `CALC_PROMPT_RULE`; the user message is unchanged. Unit tests on synthetic alerts: one field,
  two fields of the same value (ambiguous, also `100.0`), no field, whole number equal to a field
  not read as one, non-plain literals, negative literal; double counting in any order and
  parentheses, one part only, subtraction, separate sums, three parts, a larger set, zero parts,
  the same field twice, a bad name first, one bad placeholder rejecting the good one. One
  Hypothesis test (`max_examples=200`): any expression of fields, figures and operators computes
  or rejects and never raises.
- [x] Two assertions of `tests/test_explainer_question.py` and the system-message assertion of the
  three `test_*_live_guard.py` files follow A-MC-01 (DN-MC-19); nothing else in them changed.

### Task MC17 — The amendments

**Covers**: REQ-MC-35 to REQ-MC-37, §9

- [x] `ledger_kit/explainer.py`: `CALC_PROMPT_RULE`; `_call_llm` appends it only when a question is
  asked (DN-MC-15).
- [x] `ledger_kit/calc.py`: `_constant`, `_use_field`, `double_count` and its helpers,
  `DOUBLE_COUNT_MIN_PARTS`, the call in `_compute` (DN-MC-16, DN-MC-17).

### Task MC18 — Record of the recorded verdicts of the 15 Nov file (REQ-MC-38)

`tests/test_recorded_verdicts.py` pins the new file:

| Run file | Pinned fallback ids |
|---|---|
| `2026-11-15_llama3.2-3b_calc.json` | Z06, Z08, Z21, Z22, P32, V37, V38, V41, V42 |

**Superseded by session 28c (task MC21):** Z04 and V43 join the set; read the rows below with that.

Derived by reading each raw answer against the alert of today's demo (no shell). 43 records:
34 end on the model's text, 9 on the template. A record whose answer holds no placeholder keeps
the verdict the guard of the recording gave it (`observed_source`), because A-MC-01 changes the
prompt and A-MC-02 and A-MC-03 only read placeholders.

On the template (nine):

| Record | What the answer holds | Verdict after the amendments |
|---|---|---|
| Z06 | `[[calc: 179.88 * 12]]`, a card with no question | 179.88 is `yearly_cost`; the `12` is a whole number and the card has no question: `calc_not_allowed`, part `12` (was `179.88`) |
| Z08 | no placeholder; `between May 2026 and October 2026` | unchanged: `2026` twice is in no row or field, figure not found |
| Z21 | `[[calc: 8.99 + (amount - 8.99)]]` | `calc_not_allowed`, part `8.99`: the cancellation alert has no numeric field equal to 8.99 (its numeric fields are `post_cancellation_count`, `total_charged_after`, `yearly_cost`) and no field `amount`. **Not accepted, unlike the request expected.** Same part as recorded |
| Z22 | `[[calc: 8.99 + 8.99 + 8.99]]` | `calc_not_allowed`, part `8.99`, same reason as Z21 |
| P32 | `[[calc: 484.00 * 2 * 5]]` | 484.00 is `total` (read as the field); `2` is a whole number not in the question, although `invoice_count` is 2 (DN-MC-16): `calc_not_allowed`, part `2` (was `484.00`) |
| V37 | empty answer after 122.1 s | unchanged: no answer, the template |
| V38 | no placeholder; `January 5, 2025 ... January 2025` | unchanged: the bare `2025` is in no row or field, figure not found |
| V41 | `[[calc: (106.00 + 61.00 + 45.00) * 5]]` | 106.00 `total`, 61.00 `interest_total`, 45.00 `fee_total`, 5 from the question; `total` is added to the two fields that make it: `calc_not_allowed`, part `total = interest_total + fee_total` (was `106.00`) |
| V42 | `[[calc: 12.40 + 18.65]]` | neither figure is a field of the overdraft alert: `calc_not_allowed`, part `12.40` |

Four records that were on the template in the file now end on the model's text:

| Record | Placeholder | Why the new verdict is right |
|---|---|---|
| Z03 | `[[calc: 359.76]]` | 359.76 is only `yearly_cost` (the other numeric field is `series_count` 2): computed `359,76 EUR†`. The rest of the answer holds `7731` (in the counterparty of the cited rows), the dates `May 10, 2026` and `October 17, 2026` (cited rows) and `monthly basis`, with no figure in its clause: nothing else to reject |
| Z04 | `[[calc: 155.88 + 36.00]]` | 155.88 is `yearly_cost`, 36.00 is `extra_cost_per_year`: computed `191,88 EUR†`; no double counting (one other field). The rest reads like Z05, accepted in the same run: 9.99, 12.99, `36.00 per year`, `1.6%`, `2025`, `2026`, `2026-08` are fields of the alert (`old_median_amount`, `new_amount`, `extra_cost_per_year`, `cpi_change_percent`, `cpi_base_year`, `price_end_month`/`cpi_end_month`). **The least certain of the nine decisions: it rests on `1.6` being the `cpi_change_percent` of CLOUDVAULT, which I could not compute without running the demo** |
| Z20 | `[[calc: 5 * yearly_cost]]`, `[[calc: 5 * 107.88]]` | the question gives five; 107.88 is only `yearly_cost`; both give `539,40 EUR†`. The rest: `€107.88` with `yearly` agrees with `yearly_cost`; `five years` is a lone small number word, not checked |
| V43 | `[[calc: interest_total - 61.00]]` | 61.00 is only `interest_total`; result `0,00 EUR†`. Accepted by the rules as written; see DN-MC-18 |

The other 30 records (all `observed_source` `llm`, no placeholder) keep their verdict.

If the first `pytest` run disagrees, write here, record by record, why, and correct the set.

### Task MC19 — Record of Kiro calls of session 28b (for the reviewer to fill in)

**Covers**: all of session 28b

Fill in after running the checks. One line per call; do not write what was not run.

## Session 28c — amendments from the review of 28b

Decision record: the owner's review of 28b (ruff clean, 4,216 passed, 1 skipped, 1 failed) asked
for two more amendments, because the record-by-record reading of the 15 Nov file showed the
literal-as-field rule letting nonsense through as a computed figure (Z04, V43, Z21), and for the one
failing test to follow A-MC-01. Requirements group 9 (REQ-MC-39 to REQ-MC-41), design §10. Session
28c could not run commands either: the hooks lint each file and run the tests on stop, and the
pinned set of MC21 was derived by reading.

### Task MC20 — Tests first, then the amendments

**Covers**: REQ-MC-39, REQ-MC-40, §10

- [x] `tests/test_calc_amendments.py`: Z04 and V43 replayed from the 15 Nov file and rejected with
  their parts (`155.88 + 36.00`, `interest_total used more than once`); Z21 stays rejected on the
  real alert (part `8.99`) and its shape is rejected on a synthetic alert with a field `amount`;
  Z03 and Z20 still accepted (tests of 28b unchanged); a plain card accepts one field and one
  figure equal to one field, rejects any operator; an empty question is a plain card; a
  question-mode `5 * yearly_cost` accepted; a field used twice (by name, by figure, mixed) rejected;
  the same field in two placeholders accepted; two named fields of equal value accepted. The test
  `test_the_same_field_twice_is_not_double_counting` now expects the A-MC-05 rejection.
- [x] `tests/test_explainer_calc.py`: the test that expected arithmetic on a plain card to compute
  is replaced by three (DN-MC-23).
- [x] `apps/phantom_invoices/tests/test_pi_live_guard.py`: the failing test now expects the
  question-mode prompt (the plain prompt, a space, `CALC_PROMPT_RULE`) and keeps its row-column
  checks.
- [x] `ledger_kit/calc.py`: `FIELD_MAX_USES`, `_Evaluator.uses` and `reused_field`, the `arithmetic`
  parameter of `_compute`, the two checks after the double-count check.

### Task MC21 — Record of the recorded verdicts of the 15 Nov file (REQ-MC-41)

| Run file | Pinned fallback ids |
|---|---|
| `2026-11-15_llama3.2-3b_calc.json` | Z04, Z06, Z08, Z21, Z22, P32, V37, V38, V41, V42, V43 |

Two records join the nine of MC18 (11 on the template, 32 on the model's text); the other nine rows
of the MC18 table keep their verdict, because the new checks run after the walk and the
double-count check and leave the part those rules report unchanged.

| Record | Placeholder | Verdict after A-MC-04 and A-MC-05 |
|---|---|---|
| Z04 | `[[calc: 155.88 + 36.00]]`, a plain card | A-MC-04: arithmetic on a card with no question: `calc_not_allowed`, part `155.88 + 36.00` (was accepted as `191,88 EUR†`, `yearly_cost` plus `extra_cost_per_year`, a double-counted total) |
| V43 | `[[calc: interest_total - 61.00]]`, a question | A-MC-05: 61.00 is only `interest_total`, used twice: `calc_not_allowed`, part `interest_total used more than once` (was accepted as `0,00 EUR†`) |
| Z21 | `[[calc: 8.99 + (amount - 8.99)]]` | unchanged and already pinned: `calc_not_allowed`, part `8.99`, rejected by A-MC-02 before the new checks because 8.99 is no field of the cancellation alert and `amount` is no field either. **The request expected A-MC-05 to be the one that rejects it; on the real alert it is not reached.** The shape itself is covered on a synthetic alert |
| Z03 | `[[calc: 359.76]]` | still accepted: a plain card, one figure equal to one field, no operator, one use |
| Z20 | `[[calc: 5 * yearly_cost]]`, `[[calc: 5 * 107.88]]` | still accepted: a question, each placeholder uses `yearly_cost` once (two placeholders, counted each on its own) |

If the first `pytest` run disagrees, write here, record by record, why, and correct the set.

### Task MC22 — Record of Kiro calls of session 28c (for the reviewer to fill in)

**Covers**: all of session 28c

Fill in after running the checks. One line per call; do not write what was not run.

## Session 28d — the replay switches to the re-recorded run

Decision record: after 28c the owner re-recorded with `scripts/record_live_run.py` (llama3.2:3b on
Ollama, CPU, 43 records, `guard_version` `calc2`) and committed
`data/live_runs/2026-11-16_llama3.2-3b_calc2.json`: 33 accepted, 10 fallback. Its cards without a
question answer as in the 11 Nov file (same prompt, temperature 0); the trick questions show the
new behaviour (Z20 computed, five others refused with `calc_not_allowed`). A visitor without a key
sees that, so it becomes the replay. Session 28d could not run commands either: the hooks lint each
file and run the tests on stop, and the pinned set of MC25 was derived by reading.

### Task MC23 — The replay file

**Covers**: the judge-path replay (`ledger_kit/replay.py`)

- [x] `ledger_kit/replay.py`: `DEFAULT_REPLAY_RUN_PATH` points to the 16 Nov file. The Home example
  (`DEFAULT_HOME_EXAMPLE_PATH`, record P3 of 10 Nov) does not change. No older run file is removed
  or edited.
- [x] `tests/judge_path_support.py`: `REPLAY_RUN` (the 16 Nov file) is added; `COMMITTED_RUN` stays
  the 11 Nov file, named as history. `tests/test_judge_path_replay.py` pins the default against
  `REPLAY_RUN` and checks that the alert ids of both files are raised by the demo;
  `tests/test_home_example.py` checks that the replay is the 16 Nov file and the 11 Nov file is
  still readable. The tests about the 11 Nov file itself (`test_guard_index_cause.py`, the Home
  note test, `test_record_live_run.py`, whose format reference is that file) keep naming it.
- [x] The replay shows a computed figure like a live answer: the three `app.py` files already draw
  `Explanation.computed` and `ProbeResult.computed` (task MC3) and the replay goes through the same
  `explain_with_meta`, so no app changed. `tests/test_replay_calc2.py` proves it for Z20: accepted,
  two computations with the line `† computed by the kit: 5 x yearly_cost 107,88 EUR = 539,40 EUR,
  from the alert fields.`, and the Zombie page shows the figure and both lines after the replay
  press.

### Task MC24 — Documentation

- [x] `README.md`: judge step 4, the *Arithmetic* bullet of *What the guard does not check* and the
  *No key needed, real model output* paragraph (file name, one sentence on the history).
  `tests/test_readme.py` read first; the Decisions rows are untouched. `tests/test_home_example.py`
  pins step 4 and the bullet; it follows the new text.
- [x] `docs/live-guard.md`, end of *The first real run*: the replayed file is the 16 Nov one and
  the older runs stay committed.

### Task MC25 — Record of the recorded verdicts of the 16 Nov file

`tests/test_recorded_verdicts.py` pins the new file:

| Run file | Pinned fallback ids |
|---|---|
| `2026-11-16_llama3.2-3b_calc2.json` | Z03, Z04, Z05, Z22, P27, P32, V37, V41, V42, V43 |

The other four files keep their sets. 43 records: 33 end on the model's text, 10 on the template.
Derived by reading each raw answer and the `observed_*` fields written by the guard of the
recording (`calc2`), which is today's guard. Expectation until the first `pytest` run.

On the template (ten):

| Record | What the answer holds | Verdict |
|---|---|---|
| Z03 | no placeholder; `the yearly cost of the "STREAMING" service is $359.76` | `figure_not_found`, token `$`: the rows name EUR, so the currency sign is rejected. The same as on the 11 Nov file |
| Z04 | no placeholder; `The price change is attributed to the IPC290751 CPI series ...` | `price_index_as_cause`, the sentence is the token. The same as on the 11 Nov file |
| Z05 | no placeholder; `The price change is attributed to the CPI series IPC290751 ...` | `price_index_as_cause`, same as Z04 |
| Z22 | `[[calc: 8.99 + 8.99 + 8.99]]`, question `with_fees` | `calc_not_allowed`, part `8.99`: 8.99 is not a number of the question, and the cancellation alert has no numeric field equal to 8.99 |
| P27 | no placeholder; `September 18th and 24th, 2026` | `figure_not_found`, tokens `24` and `2026`. The same as on the 11 Nov file |
| P32 | `[[calc: 484.00 * 2 * 5]]`, question `forecast` | `calc_not_allowed`, part `2`: a whole number the question does not give, although `invoice_count` is 2 (DN-MC-16) |
| V37 | no placeholder; `from January 2025 to October 2026` | `figure_not_found`, tokens `2025` and `2026`: bare years in no row or field |
| V41 | `[[calc: (106.00 + 61.00 + 45.00) * 5]]`, question `forecast` | `calc_not_allowed`, part `total = interest_total + fee_total`: a total added to its own parts |
| V42 | `[[calc: 12.40 + 18.65]]`, question `next_month` | `calc_not_allowed`, part `12.40`: neither figure is a field of the overdraft alert |
| V43 | `[[calc: interest_total - 61.00]]`, question `with_fees` | `calc_not_allowed`, part `interest_total used more than once`: 61.00 is only `interest_total` |

On the model's text, and different from the 11 Nov pin (Z20 leaves the set, Z22, P32, V41, V42 and
V43 join it):

| Record | What the answer holds | Verdict |
|---|---|---|
| Z20 | `[[calc: 5 * yearly_cost]]`, `[[calc: 5 * 107.88]]`, question `forecast` | accepted: the question gives five, 107.88 is only `yearly_cost`, each placeholder uses it once; both give `539,40 EUR†` with the formula `5 x yearly_cost 107,88 EUR = 539,40 EUR`. Rejected on the 11 Nov file, where the model wrote 539.40 by hand |
| Z21 | `The next charge is expected to be €8.99 ...` | accepted: 8.99 is in the cited rows, no placeholder |

The other 31 records (all `observed_source` `llm`, no placeholder, the same answers as the 11 Nov
file for the cards) keep the verdict they had. Of the pinned ids, Z03, Z04, Z05, P27 and V37 are
the same five that today's guard gives on the 11 Nov file among the cards without a question.

If the first `pytest` run disagrees, write here, record by record, why, and correct the set.

### Task MC26 — Record of Kiro calls of session 28d (for the reviewer to fill in)

**Covers**: all of session 28d

Fill in after running the checks. One line per call; do not write what was not run.
