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
