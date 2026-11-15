# model-computes — Design

Section references (§) in `tasks.md` point here; REQ ids point to `requirements.md`.

## §1 Module map

| File | Change |
|---|---|
| `ledger_kit/calc.py` | **new**: `resolve_calculations`, `CalcOutcome`, `Computation`, `Operand`, `numeric_fields`, `question_integers`, constants |
| `ledger_kit/utils/money.py` | one new helper `combine(operator, left, right)` (the one step of arithmetic) |
| `ledger_kit/explainer.py` | system prompt rule; `explain_with_meta` resolves placeholders first; `Explanation.computed`; `_MONEY_FIELD_RE` |
| `ledger_kit/live_guard.py` | `computed_lines`, `VERDICT_REJECTED_CALC_PREFIX`, `SHOWN_LABEL`; `ProbeResult.computed` and `shown_text` |
| `apps/*/app.py` (three) | the caption lines under a card answer; the shown answer in the panel |
| `README.md` | one paragraph, the Specs row, one Decisions row |
| tests (new files only) | `tests/test_calc.py`, `tests/test_explainer_calc.py` |

`calc.py` imports `number_words` and `utils.money` only; the explainer imports `calc`, never the
other way round. `live_guard.py` imports `calc` for the types. No new module calls a model.

## §2 The flow (REQ-MC-10)

```
raw = _call_llm(...)
calc = resolve_calculations(raw, alert.data, question=question, money_fields=<:money fields of the template>)
if calc.rejected:       fallback, rejected_numbers = calc.rejected, rejected_reason = "calc_not_allowed"
number guard on calc.guard_text      # placeholders read as COMPUTED; same guard, same rows
index-as-cause on calc.guard_text
accept: text = calc.text, computed = calc.computed
```

An answer with no placeholder has `guard_text == text == raw`, so the three later steps are the
steps of today (REQ-MC-11).

DN-MC-01 *Why the calculation is resolved before the number guard.* The guard must not read the
digits inside a placeholder (`5`, `1.05`) as figures of the model. A rejected placeholder is
reported with its own reason and its offending part, not as a figure. The price is that an answer
with a bad placeholder and an invented figure reports only the placeholder.

DN-MC-02 *The marker.* `COMPUTED` has letters only, so neither the digit, the date, the IBAN nor the
number-word passes read it, and `find_index_as_cause` splits sentences around it as around a word.

## §3 The evaluator (REQ-MC-03 to REQ-MC-09)

1. **Placeholder**: `\[\[\s*calc\s*:(expression)\]\]`, case-insensitive; the expression holds no
   square bracket. After the matches are removed, any `[[calc` left is a malformed placeholder and
   rejects the answer (token `[[calc`).
2. **Parse**: `ast.parse(expression.strip(), mode="eval")`. `SyntaxError`, `ValueError`,
   `RecursionError` and `MemoryError` reject; the 200-character limit keeps the parser away from
   absurd input.
3. **Walk**: one method per allowed node; any other node raises the internal `_Reject(part)` with
   the source text of the node (`ast.get_source_segment`). An operator outside `+ - * /` rejects
   before its operands are read, so `yearly_cost ** 2` is reported whole.
4. **Constants**: `type(value) is int` (so `True` and `1.05` are not constants) and the value in
   `question_integers(question)`: the digit runs that are whole numbers (not inside a decimal, a
   date or a longer number) plus the `value` of every phrase of `find_number_phrases`.
5. **Arithmetic**: `decimal.localcontext()` with `prec = 40`; each step is `money.combine`; the
   division checks the divisor for zero first. The result goes through `round_to_cents` once.
   `ArithmeticError` (overflow, an undefined operation) rejects with the whole expression.
6. **Amount or number** (DN-MC-03): the evaluator carries a flag with every value. A field is an
   amount when the fallback template shows it `{name:money}` (the explainer reads the template),
   or when its name has a word of `MONEY_NAME_PARTS` and none of `NOT_MONEY_NAME_PARTS`. `+` and
   `-`: amount if either side is; `*`: amount if exactly one side is; `/`: amount if the numerator
   is and the denominator is not. Constants are never amounts.
7. **Display**: an amount through `format_amount(rounded, currency)`; any other number through a
   decimal-comma writer with no trailing zeros (`60`, `0,42`). The formula puts parentheses around
   a nested operation and writes `*` as `x`.

DN-MC-04 *European format in the formula line.* The task text gave `107.88 x 5 = 539.40` as an
example of the line. Finance Rule 4 is binding for every displayed amount, so the line is
`107,88 EUR x 5 = 539,40 EUR`. The stored `Computation.operands[].value` and `.result` stay exact
`Decimal` values (`107.88`, `539.40`), for any consumer that needs them.

DN-MC-05 *`money.py` stays the only place of monetary arithmetic.* `calc.py` calls
`money.combine`, `money.apply_sign`, `round_to_cents` and `format_amount`; it writes no `+`, `-`,
`*` or `/` on amounts itself.

## §4 The display (REQ-MC-14)

- `Explanation.text` holds the figure and the mark (`539,40 EUR†`), so any consumer of the text
  (the cards, the replay, the command line) shows it marked without a change.
- `live_guard.computed_lines(computed)` gives one line per computation:
  `† computed by the kit: <formula>, from the alert fields.` Each app card writes the lines with
  `st.caption` right under the answer; with no computation nothing is written, so a card of today
  is unchanged.
- `ProbeResult` has two new fields with defaults (`computed`, `shown_text`). In the panel an
  accepted answer with a computation shows, after the verdict, `SHOWN_LABEL`, the answer as the
  card shows it and the lines. A rejected calculation shows `VERDICT_REJECTED_CALC_PREFIX` and the
  offending parts, highlighted in the raw answer like any rejected token.
- The replay needs no change: `ReplayClient` hands the recorded text to `explain_with_meta`, which
  resolves placeholders as for a live answer.

## §5 What did not change

- `_passes_number_guard`, `check_figures`, `find_index_as_cause`, the fallback and the badges.
- `docs/live-guard.md` and the Home page: no recorded answer holds a placeholder.
- `tests/test_recorded_verdicts.py` (see the record in `tasks.md`).

## §6 Limits (stated in the README and here)

- The kit checks that a calculation uses only alert fields and question numbers; it does not check
  that the formula answers the question. `yearly_cost * 5` for "ten years" is not caught if the
  question also says five.
- A question number can be any number of the question, also one that is not a period count.
- The currency is that of `Alert.data["currency"]` or `EUR`; there is no conversion.
- The model may also fail to use the placeholder; then the answer is judged as today.
