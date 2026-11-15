# model-computes — Requirements

## Overview

**Decision record.** The owner chose this change on 15 Nov (session 27a). It is improvement A of
the adversarial review of 14 Nov: today the explanation is decorative, and a judge asks why the kit
keeps the LLM at all. The change was drafted by Claude Code and decided by the owner (also in the
Decisions table of `README.md`).

**The problem, from the recordings.** Asked `If nothing changes, what will this cost me in total
five years from now?`, `llama3.2:3b` wrote `539.40` (5 x 107.88, right arithmetic) and the number
guard rejected it, because 539.40 is in no row. Another time it assumed a 5% interest rate found
nowhere and built `617.51` on it. Today the guard can only reject; a correct total is impossible.

**The new behaviour: the model asks, the kit computes.** The model never does arithmetic. When the
question needs it (a total over several periods, a sum, a difference, a share) it names the
calculation as a placeholder `[[calc: EXPRESSION]]`. The kit evaluates the expression from the
numeric fields of the alert, in `Decimal`, shows the result marked, and shows the formula it used.
A correct total becomes possible; an invented assumption still cannot get in, because every name
in the expression must be a field of the alert and every number must be one the user wrote in the
question.

It changes no detector, no threshold, no rule of the number guard for figures the model writes
itself, and no recorded verdict. Ids are `REQ-MC-nn`; acceptance examples are `AE-MC-nn`. EARS
keywords: *shall*, *when*, *while*, *where*, *if ... then*. All data is synthetic.

## Shared vocabulary

- **Placeholder**: the text `[[calc: EXPRESSION]]` in a model answer (`calc` in any case, white
  space free around it).
- **Numeric field**: a key of `Alert.data` whose value is a `Decimal`, an `int` (not a `bool`) or
  text that is a plain number (`107.88`, `-3`).
- **Question number**: a whole number of the user's question, in digits (`5`) or in English or
  Spanish words (`five`, `cinco`), read with `ledger_kit/number_words.py`.
- **Computation**: what the kit records for one placeholder: the expression, each operand with its
  field name and value, and the result.

---

## 1 — The prompt

- **REQ-MC-01** The system prompt of the explainer shall keep every existing rule (the no-invention
  sentence verbatim, the citation rule, the length rule, the date rule) and shall add one rule:
  when the question needs arithmetic the model must not compute it but write
  `[[calc: EXPRESSION]]`, where EXPRESSION uses only the names of numeric fields of the alert as
  given in the Alert JSON, the operators `+ - * /`, parentheses, and whole numbers that appear in
  the user's question (in digits or words); and it must not write the result or assume a number.
  - AE-MC-01: the system message sent to the client contains the no-invention sentence and
    `[[calc: EXPRESSION]]`.

## 2 — The module `ledger_kit/calc.py`

- **REQ-MC-02** The system shall provide `ledger_kit/calc.py` (pure: no model, no Streamlit, no
  I/O) with `resolve_calculations(answer, data, *, question, money_fields)`, which finds every
  placeholder of `answer`, evaluates it and returns a `CalcOutcome(guard_text, text, computed,
  rejected)`. It shall never raise, whatever the text.
  - AE-MC-02: Hypothesis, any text inside a placeholder, any answer: no exception.
- **REQ-MC-03** The expression shall be read with a whitelist over Python's `ast`: `BinOp` with
  `Add`, `Sub`, `Mult` or `Div`; `UnaryOp` with `USub`; `Name`; `Constant` of type `int`. Nothing
  else is read: no call, no attribute, no power, no modulo, no floor division, no comparison, no
  conditional, no string, no float, no `bool`, no list. An expression over 200 characters, an empty
  one and one that does not parse are not read.
  - AE-MC-03

    | Expression | Result |
    |---|---|
    | `yearly_cost * 5` (question has `five`) | computed |
    | `yearly_cost ** 5` | rejected, part `yearly_cost ** 5` |
    | `round(yearly_cost)` | rejected, part `round(yearly_cost)` |
    | `yearly_cost * 1.05` | rejected, part `1.05` |
    | `yearly_cost x 5` | rejected (does not parse) |
- **REQ-MC-04** A `Name` shall be a numeric field of this alert; any other name (an unknown field, a
  text field, a `bool`) rejects the answer, with the name as the offending part.
- **REQ-MC-05** A `Constant` shall be a whole number found in the question text, in digits or in
  English or Spanish words. A question number is not part of a decimal, a date or a longer number.
  With no question there are no constants.
  - AE-MC-05: `five years`, `5 years` and `cinco años` each allow `5`; `1.05` and `2026-11-10`
    allow nothing.
- **REQ-MC-06** The arithmetic shall be done in `Decimal` through `money.combine` (the one place of
  monetary arithmetic), with intermediate precision kept and the result rounded to two places half
  up at the end only (Finance Rule 3). A division by zero, an overflow or any other arithmetic
  error rejects the answer, with the offending part.
- **REQ-MC-07** The reason of every rejection of REQ-MC-03 to REQ-MC-06 shall be
  `REASON_CALC_NOT_ALLOWED = "calc_not_allowed"`, recorded in `Explanation.rejected_reason` as
  `price_index_as_cause` is, with the offending parts as `rejected_numbers`. One bad placeholder
  rejects the whole answer, also when another placeholder of it is valid. A placeholder that is not
  closed (`[[calc: ...` with no `]]`) is rejected with the token `[[calc`.
- **REQ-MC-08** The result shall replace the placeholder in the text, written like the alert
  amounts (Finance Rule 4): an amount as `539,40 EUR` (the currency of `Alert.data["currency"]` when
  it names one, else `EUR`), any other number with a decimal comma, and followed by the mark `†`.
  A result is an amount when one operand is an amount and the other is not a count (an amount times
  a count, an amount over a count, a sum or difference with an amount); a share of two amounts is a
  plain number. A field is an amount when the fallback template formats it `:money`, or when a word
  of its name says amount (`cost`, `amount`, `total`, `charged`, `price`, `fee`) and no word says
  count, percent or index.
- **REQ-MC-09** The kit shall record each computation: the expression, each operand with its field
  name, its value and how it is shown, the result, and the formula line
  `yearly_cost 107,88 EUR x 5 = 539,40 EUR`.

## 3 — The guard

- **REQ-MC-10** Order of checks in `explain_with_meta`: (1) the placeholders are resolved, and an
  answer with a rejected placeholder falls back; (2) the number guard runs on the answer with every
  valid placeholder replaced by the neutral marker `COMPUTED`, so a figure the model wrote itself
  is checked exactly as today; (3) the index-as-cause check runs on the same text; (4) the text
  with the computed figures is the accepted answer. Computed results are not checked against the
  rows: the kit made them from listed fields.
- **REQ-MC-11** An answer with no placeholder shall go through steps 2 to 4 unchanged, so every
  verdict of today is today's verdict.
  - AE-MC-11: `tests/test_recorded_verdicts.py` is not edited and its pinned sets do not change.
- **REQ-MC-12** An answer that writes a computed figure by hand (no placeholder) is rejected as
  today. A figure the model writes by hand next to a valid placeholder is rejected too.
  - AE-MC-12: `GYMPLUS over five years: 539.40 (bank.csv:0).` is rejected with `539.40`.

## 4 — The result and the display

- **REQ-MC-13** `Explanation` shall have a new field `computed: tuple[Computation, ...] = ()`, so
  every existing construction keeps working. `raw_answer` stays the answer as received, with the
  placeholder in it.
- **REQ-MC-14** Wherever an accepted LLM answer is shown (the alert cards of the three apps, also
  when the answer is a replayed recording, and the Provoke the LLM panel), the computed figure is
  marked with `†` and followed by one line of small text:
  `† computed by the kit: yearly_cost 107,88 EUR x 5 = 539,40 EUR, from the alert fields.`
  The panel shows the answer as the card would show it, under the label `Answer as shown, with the
  figures the kit computed:`, after the raw answer and the verdict. A rejected calculation gets its
  own verdict sentence in the panel.
- **REQ-MC-15** The text of `Explanation` that is shown on a card never contains a placeholder:
  when it is not replaced, the answer is rejected.

## 5 — Documentation

- **REQ-MC-16** `README.md` shall say, in one short paragraph next to the explanation layer, what
  changed and what did not; the Kiro table shall count 18 specs and name this one; the Decisions
  table shall have the row of 15 Nov. `tests/test_readme.py` keeps passing.

## Not in this spec

- No change to a detector, a threshold, the templates or the Exorcise drafts.
- No change to `tests/test_recorded_verdicts.py`, to a recorded run file or to the Home example.
- The model is not told the result, and the kit does not ask it again: one attempt as ever.
- Percent signs, powers, rounding functions and any constant the question does not contain stay
  unavailable by design.
