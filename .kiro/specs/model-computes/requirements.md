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

## 6 — The period of a figure (session 27b)

**Decision record.** Second part of the owner's choice of 15 Nov (improvement A of the adversarial
review of 14 Nov): each figure is tied to its field, so a monthly charge cannot be called yearly.
Drafted by Claude Code, decided by the owner.

**The problem.** The README section *What the guard does not check* said: `MUSICBOX costs 10.99
EUR every year` passes on a monthly 10.99 charge, because the guard only checks that 10.99 is in
the cited rows or the alert data. It never asks what the sentence says the figure is.

Vocabulary of this group:

- **Stated period** of a field: the period the alert itself gives it (REQ-MC-18). A field with no
  stated period is never checked by this group.
- **Period phrase**: one of the phrases of REQ-MC-19, read as whole words in any case.
- **Clause**: a part of a sentence between commas or semicolons followed by a space, or dashes
  between spaces. A sentence ends at `.`, `!` or `?` followed by white space, or at a line break.

- **REQ-MC-17** When the number guard has accepted an answer, the explainer shall check, before the
  index-as-cause check, that no period phrase contradicts the stated period of the field its figure
  matches. If one does, then the answer shall be rejected: the card shows the filled fallback
  template, `Explanation.rejected_reason` is `REASON_PERIOD_MISMATCH = "period_mismatch"`, and
  `rejected_numbers` holds, for each contradiction, the figure and then the phrase as written.
  - AE-MC-17: `MUSICBOX costs 10.99 EUR every year (bank.csv:0).` on a `zs.recurring_charge`
    alert with `interval_type` `monthly` and `current_amount` `10.99` is rejected with
    `("10.99", "every year")` and reason `period_mismatch`.
- **REQ-MC-18** The stated periods shall be: the per-charge amount fields (`current_amount`,
  `old_median_amount`, `new_amount`, `old_amount`, `first_paid_amount`) carry the alert's
  `interval_type` when it is `weekly`, `monthly`, `quarterly` or `yearly`; `yearly_cost` and any
  other field whose name contains `yearly` or `per_year` carry `yearly`. Every other field has no
  stated period. The full list per detector is in design §7.
- **REQ-MC-19** The period phrases shall be: English `per week`, `weekly`, `every week` (weekly);
  `per month`, `a month`, `monthly`, `every month` (monthly); `per quarter`, `quarterly`
  (quarterly); `per year`, `a year`, `yearly`, `annually`, `every year` (yearly). Spanish
  `a la semana`, `semanal` (weekly); `al mes`, `mensual`, `cada mes` (monthly); `trimestral`,
  `al trimestre` (quarterly); `al año`, `anual`, `cada año` (yearly). A phrase inside a longer
  word or identifier (`yearly_cost`, `monthlyfee`) is not a phrase.
- **REQ-MC-20** A period phrase shall be tied to the one figure nearest to it in its clause,
  counted in characters between the two, with a currency symbol or code written next to the figure
  counted as part of it. A phrase in a clause with no figure, or as near to two figures, is not
  checked.
  - AE-MC-20: `€10.99 per month and €131.88 per year` passes; `A recurring charge of €10.99 has
    been detected, with a yearly cost of €131.88.` passes; `The total yearly cost is €131.88,
    indicating that six monthly charges have been made` passes.
- **REQ-MC-21** A figure shall be checked only when the fields it matches (equal `Decimal` value)
  all have stated periods and those periods are one and the same. A figure that matches fields of
  two different periods (for example a monthly `new_amount` of 12.00 and an `extra_cost_per_year`
  of 12.00), or also a numeric field with no stated period, or no field at all (a figure only in
  the cited rows), is not checked.
- **REQ-MC-22** A sentence with no period phrase shall not be checked. A computed figure
  (`[[calc: ...]]`, read as the marker `COMPUTED`) and a number written in words shall never be
  checked by this rule; a computed figure still takes part in REQ-MC-20 as the nearest figure.
- **REQ-MC-23** The check shall be pure and shall never raise, whatever the text. It shall not
  change the number guard, `check_figures` (the Exorcise drafts) or the index-as-cause check.
- **REQ-MC-24** The *Provoke the LLM* panel shall name a period rejection with its own verdict
  sentence (`VERDICT_REJECTED_PERIOD_PREFIX`), so it is not called a figure that was not found.
- **REQ-MC-25** No recorded verdict shall change silently. `tests/test_recorded_verdicts.py` is not
  edited; if a recorded answer now ends on the template, the record is added to its pinned set and
  explained record by record in `tasks.md` (task MC10).
- **REQ-MC-26** `README.md`, *What the guard does not check*: the MUSICBOX example shall be
  rewritten so it stays true: a period that contradicts the field is now rejected, other meaning is
  still not checked, with one example from the tests that still passes. `docs/live-guard.md` is
  changed only if it repeats the example.

## 7 — Re-recording the real-model runs (session 28a)

**Decision record.** Third part of the owner's choice of 15 Nov (improvement A of the adversarial
review of 14 Nov: re-record the answers with the new prompt). Drafted by Claude Code, decided by
the owner. Today `data/live_runs/2026-11-11_llama3.2-3b_demo.json` was recorded with a script that
is not in the repository; this group puts one in, so anyone can re-record.

- **REQ-MC-27** The system shall provide `scripts/record_live_run.py`, run with the kit's own
  Python. Its scope shall be the scope of the 11 Nov file: the three CSV demos (Zombie
  Subscriptions with the CPI context of its page), every alert card once, in page order, plus the
  three trick questions of `ledger_kit/live_guard.py` on the first critical card of each app. The
  docstring shall say so.
  - AE-MC-27: the planned records are 43, and their pairs (alert id, question id) are the pairs of
    the 11 Nov file.
- **REQ-MC-28** Each record shall be asked exactly as the apps ask it: `explain_with_meta` with the
  real client of the explainer, the app's fallback template, its row columns and, for a probe, the
  question text. Endpoint, key, model and timeout shall come from `OPENAI_BASE_URL`,
  `OPENAI_API_KEY`, `LEDGER_KIT_LLM_MODEL` and `LEDGER_KIT_LLM_TIMEOUT`; temperature 0 and no retry,
  as in the explainer. If `OPENAI_API_KEY` is not set, then the script shall refuse and ask nothing.
- **REQ-MC-29** The file shall keep the top-level fields of the 11 Nov file, in its order (`what`,
  `date`, `model`, `machine`, `settings`, `guard_version`, `note`, `python`, `records`), and the
  fields of each of its records, with two new fields before `raw_answer`: `observed_reason` (the
  rejection reason; empty when accepted) and `observed_calcs` (the kit's calculations, each with
  expression, formula and result; empty when none). `raw_answer` is the answer exactly as received,
  `seconds` the time of the call.
- **REQ-MC-30** Record ids shall be the app letter (`Z`, `P`, `V`) and a two-digit number counted
  over the whole run; `question_id` and `question` as in the 11 Nov file (`null` for a card).
- **REQ-MC-31** Arguments: `--out` (required); `--machine` (free text written into `machine`);
  `--tag` (free text written into `guard_version`); `--dry-run`, which lists every record it would
  ask (id, app, alert id, title, question) and calls nothing.
- **REQ-MC-32** If `--out` names an existing file, then the script shall refuse, ask nothing and
  write nothing. It shall print one line per record while it runs and write the file only at the
  end, so a failed run leaves nothing half-written.
- **REQ-MC-33** When the call of one record fails (an error, a timeout, an empty answer), the
  record shall be written as a fallback with an empty `raw_answer` and the reason `no_answer`, and
  the run shall continue.
- **REQ-MC-34** `README.md` (the *No key needed, real model output* paragraph) and
  `docs/live-guard.md` (the section on the first real run) shall say in one or two sentences how to
  re-record with the script and a local model, and that a recording is the raw answers of one run,
  not a rate. `tests/test_readme.py` and `tests/test_live_guard_docs.py` keep passing.

## 8 — Amendments from the first real run (session 28b)

**Decision record.** The owner ran `scripts/record_live_run.py` on 15 Nov with `llama3.2:3b` on
Ollama (CPU, 22 minutes, 43 records) and committed the file as
`data/live_runs/2026-11-15_llama3.2-3b_calc.json`: 30 answers accepted, 13 on the fixed template,
and no calculation accepted at all. The amendments below are numbered like A-LG-01 to A-LG-03 of
live-guard and cite the records of that file by id (`observed_reason` of each is `calc_not_allowed`
unless said otherwise). They change what the kit does with a placeholder and what the prompt says;
they change no detector, no template and no rule of the number guard.

- **REQ-MC-35 (A-MC-01, the prompt).** The system prompt shall hold the placeholder rule of
  REQ-MC-01 only when a question is asked. A card with no question (or an empty one) shall get the
  prompt it had before 15 Nov, word for word. The user message is unchanged.
  - Records: Z03, Z04 and Z06 are plain cards, asked with no question. Given the rule in the
    prompt, the model wrapped a figure of the alert in a placeholder (`[[calc: 359.76]]`) or made up
    arithmetic (`[[calc: 179.88 * 12]]`), and the whole answer was rejected. Those cards were
    accepted before the rule existed.
  - AE-MC-35: with `question=None` and with `""` the system message equals the old prompt; with a
    question it is the old prompt, a space and `CALC_PROMPT_RULE`.
- **REQ-MC-36 (A-MC-02, a figure of the alert).** *When* a number written with a decimal point in a
  placeholder equals the value of exactly one numeric field of the alert, the kit shall read it as
  that field: the provenance line names the field, not the literal. *If* it equals two or more
  fields with different names, *then* it is ambiguous and the answer shall be rejected as today,
  with the number as written. *If* it equals no field, *then* it shall be rejected as today. A
  whole number written without a decimal point keeps REQ-MC-05: it has to be a whole number of the
  question.
  - Records: Z03 `[[calc: 359.76]]` is `yearly_cost`. Z04 `[[calc: 155.88 + 36.00]]` is
    `yearly_cost + extra_cost_per_year`. Z20 `[[calc: 5 * yearly_cost]]` is right, and
    `[[calc: 5 * 107.88]]` is the same field written as a literal: that second one rejected the
    whole answer. P32 `[[calc: 484.00 * 2 * 5]]`: 484.00 is `total` but the 2 is invented; the
    alert has a field `invoice_count` that is 2, and the 2 must not be read as that field (DN-MC-16).
  - AE-MC-36: Z03 and Z20 are accepted with their computed figures; P32 is rejected with the part
    `2`.
- **REQ-MC-37 (A-MC-03, double counting).** *If*, in one placeholder, a sum adds a field to two or
  more other fields of the same sum whose values add up to it, *then* the answer shall be rejected
  with `calc_not_allowed`, the offending part being `total = part + part` (the field and the
  fields it is made of). This catches this one pattern and not every reasoning error; the formula
  is always shown, so a reader can check it.
  - Records: V41 `[[calc: (106.00 + 61.00 + 45.00) * 5]]` adds `total` (106.00) to its own parts
    `interest_total` (61.00) and `fee_total` (45.00).
  - AE-MC-37: V41 is rejected with `total = interest_total + fee_total`.
- **REQ-MC-38 (the pinned set).** `tests/test_recorded_verdicts.py` shall pin the new file with the
  set of record ids that end on the fixed template under the guard after these amendments, each one
  explained record by record in `tasks.md` (task MC18). The replay's default file
  (`DEFAULT_REPLAY_RUN_PATH`) and `data/live_runs/2026-11-11_llama3.2-3b_demo.json` are not
  changed; the replay switches only after a re-record with these amendments, if it is better.
  - Record Z21 `[[calc: 8.99 + (amount - 8.99)]]` stays rejected: 8.99 is the charge of the rows
    but no numeric field of the cancellation alert, and `amount` is no field either.

## 9 — Amendments from the review of session 28b (session 28c)

**Decision record.** The owner's review of session 28b found that the rule *a literal is read as the
field* lets the small model's nonsense through as a computed figure. Amendments A-MC-04 and
A-MC-05 follow, citing the records of the same file. No detector, template or number-guard rule
changes.

- **REQ-MC-39 (A-MC-04, no arithmetic on a card with no question).** *While* no question (or an
  empty one) is asked, a placeholder shall be accepted only if it is a single numeric field by name
  or a single figure that equals exactly one numeric field, with no operator at all (a minus sign
  included). *If* it holds any arithmetic, *then* the answer shall be rejected with
  `calc_not_allowed`, the offending part being the expression as written. A part rejected by an
  earlier rule (an unknown field, a whole number the question does not give) is reported as before.
  - Records: Z04 `[[calc: 155.88 + 36.00]]` is `yearly_cost + extra_cost_per_year`; `yearly_cost`
    already includes the increase, so the sum shown would be a double-counted total, `191,88 EUR`.
    Z04 is a plain card. Z03 `[[calc: 359.76]]` stays accepted.
  - AE-MC-39: Z04 is rejected with the part `155.88 + 36.00`.
- **REQ-MC-40 (A-MC-05, each field once).** *If*, in one placeholder, a numeric field is used more
  than once, a figure read as that field (REQ-MC-36) counting as a use of it, *then* the answer
  shall be rejected with `calc_not_allowed`, the offending part being `NAME used more than once`.
  Two placeholders of one answer are checked each on its own. This applies with and without a
  question.
  - Records: V43 `[[calc: interest_total - 61.00]]` is the interest total minus itself, `0,00 EUR`.
    Z21 `[[calc: 8.99 + (amount - 8.99)]]` has the shape of one field used three times; on the real
    alert it is already rejected earlier (8.99 is no field, REQ-MC-38), so its part is unchanged.
    Z20 `[[calc: 5 * yearly_cost]]` uses the field once in each placeholder and stays accepted.
  - AE-MC-40: V43 is rejected with the part `interest_total used more than once`; a question-mode
    `5 * yearly_cost` is accepted.
- **REQ-MC-41 (the pinned set).** The pinned set of the 15 Nov file shall gain the records these
  amendments send to the template, explained record by record in `tasks.md` (task MC21).

## Not in this spec

- No change to a detector, a threshold, the templates or the Exorcise drafts.
- No change to `tests/test_recorded_verdicts.py` (except to pin a new run file, REQ-MC-38), to a
  recorded run file or to the Home example.
- The model is not told the result, and the kit does not ask it again: one attempt as ever.
- Percent signs, powers, rounding functions and any constant the question does not contain stay
  unavailable by design.
