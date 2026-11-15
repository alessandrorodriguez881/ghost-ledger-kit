# model-computes — Design

Section references (§) in `tasks.md` point here; REQ ids point to `requirements.md`.

## §1 Module map

| File | Change |
|---|---|
| `ledger_kit/calc.py` | **new**: `resolve_calculations`, `CalcOutcome`, `Computation`, `Operand`, `numeric_fields`, `question_integers`, constants |
| `ledger_kit/utils/money.py` | one new helper `combine(operator, left, right)` (the one step of arithmetic) |
| `ledger_kit/explainer.py` | system prompt rule; `explain_with_meta` resolves placeholders first; `Explanation.computed`; `_MONEY_FIELD_RE`; (27b) `find_period_mismatches`, `field_periods`, `REASON_PERIOD_MISMATCH` and the period constants (§7) |
| `ledger_kit/live_guard.py` | `computed_lines`, `VERDICT_REJECTED_CALC_PREFIX`, `SHOWN_LABEL`; `ProbeResult.computed` and `shown_text`; (27b) `VERDICT_REJECTED_PERIOD_PREFIX` |
| `apps/*/app.py` (three) | the caption lines under a card answer; the shown answer in the panel |
| `README.md` | one paragraph, the Specs row, one Decisions row |
| tests (new files only) | `tests/test_calc.py`, `tests/test_explainer_calc.py`; (27b) `tests/test_explainer_period.py` |

`calc.py` imports `number_words` and `utils.money` only; the explainer imports `calc`, never the
other way round. `live_guard.py` imports `calc` for the types. No new module calls a model.

## §2 The flow (REQ-MC-10)

```
raw = _call_llm(...)
calc = resolve_calculations(raw, alert.data, question=question, money_fields=<:money fields of the template>)
if calc.rejected:       fallback, rejected_numbers = calc.rejected, rejected_reason = "calc_not_allowed"
number guard on calc.guard_text      # placeholders read as COMPUTED; same guard, same rows
period check on calc.guard_text      # (27b, §7) a period that contradicts a figure's field
index-as-cause on calc.guard_text
accept: text = calc.text, computed = calc.computed
```

An answer with no placeholder has `guard_text == text == raw`, so the later steps read the answer
as received (REQ-MC-11). The period check (§7, session 27b) is the one step added since.

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

## §7 The period of a figure (session 27b, REQ-MC-17 to REQ-MC-26)

All of it is in `ledger_kit/explainer.py`, section *The period of a figure*:
`find_period_mismatches(text, alert)`, `field_periods(data)`, the constants
`REASON_PERIOD_MISMATCH`, `PERIOD_INTERVAL_TYPES`, `PER_CHARGE_FIELDS`, `YEARLY_FIELD_PARTS` and
`PERIOD_PHRASES`. The panel gets one verdict sentence, `VERDICT_REJECTED_PERIOD_PREFIX` in
`ledger_kit/live_guard.py`. No other module changes.

DN-MC-06 *Where the check runs.* In `explain_with_meta`, after the number guard and before the
index-as-cause check, on the same `calc.guard_text`:

```
calc = resolve_calculations(...)       # a bad placeholder: calc_not_allowed
number guard on calc.guard_text        # an unknown figure: rejected tokens, reason ""
find_period_mismatches(calc.guard_text, alert)   # period_mismatch: figure, phrase
find_index_as_cause(calc.guard_text)   # price_index_as_cause
```

After the number guard, because the period check needs every figure to be a known one: an invented
figure is still reported as a figure, as before, and the period check only judges figures the guard
already let through. Before the index-as-cause check, because both read meaning and the period one
is about a figure, the closer of the two to what the guard has always done. On `guard_text`,
because a computed figure is the marker `COMPUTED` there: it is never checked (REQ-MC-22) but it
still stands where the figure stands, so a phrase next to it is tied to it and not to a farther
figure. `check_figures` (the Exorcise drafts) does not run it: a draft is a fixed template filled
by the kit, not a model answer.

DN-MC-07 *A phrase belongs to the nearest figure of its clause, not to every figure of the
sentence.* The task said "in the sentence that holds the figure". Read literally, that rejects
correct recorded answers: `The total yearly cost of this charge is €107.88, indicating that six
monthly charges have been made.` (record Z11 of `2026-11-11_llama3.2-3b_demo.json`, the same in
Z19) holds the yearly figure and the word `monthly` in one sentence, and `A recurring charge of
€2.99 has been detected for GLOWBILL, with a total yearly cost of €35.88.` (Z09) holds the monthly
figure and the word `yearly`. The rule therefore narrows the sentence twice: to the clause (a comma
or semicolon before a space, or a spaced dash, ends it), and inside the clause to the one figure
nearest to the phrase. A currency written next to a figure (`€10.99`, `10,99 EUR`) counts as part
of the figure, so in `10,99 EUR al mes y 131,88 EUR al año` the phrase `al mes` is one character
from its figure and three from the next one. A tie ties the phrase to nobody. The price: `costs
10.99 EUR, every year` (the phrase alone after a comma) is not caught; see §7 limits.

DN-MC-08 *Which fields carry which period.* Read from the detectors of the three apps on 15 Nov.
The library cannot import the apps, so the rule is by field name (REQ-MC-18) and this table is
what it gives today:

| Detector | Field | Stated period |
|---|---|---|
| `zs.recurring_charge` | `current_amount` | the alert's `interval_type` (`weekly`, `monthly`, `quarterly`, `yearly`) |
| | `yearly_cost` | yearly |
| | `charge_count`, dates, names, `is_active` | none |
| `zs.price_increase` | `old_median_amount`, `new_amount` | the alert's `interval_type` |
| | `extra_cost_per_year`, `yearly_cost` | yearly |
| | `price_change_percent`, every `cpi_*` field (also `cpi_base_year`, whose name has `year` but neither `yearly` nor `per_year`), the months | none |
| `zs.duplicate_subscription` | `yearly_cost` | yearly |
| | `series_count`, names | none (the alert has no `interval_type`: its series may differ) |
| `zs.free_trial_to_paid` | `first_paid_amount` | the alert's `interval_type` |
| | `yearly_cost` | yearly |
| | `trial_amount` (one token charge, not a charge of the series), `days_before_first_charge` | none |
| `zs.charges_after_cancellation` | `yearly_cost` | yearly |
| | `total_charged_after`, `post_cancellation_count`, `cancellation_date` | none (no `interval_type`) |
| `vf.recurring_fee` | `current_amount` | the alert's `interval_type` (`monthly`, `quarterly`, `yearly`) |
| | `yearly_cost` | yearly |
| | `charge_count`, dates, names | none |
| `vf.fee_increase` | `old_amount`, `new_amount` | the alert's `interval_type` |
| | `extra_cost_per_year`, `yearly_cost` | yearly |
| | `increase_percent`, dates | none |
| `vf.overdraft_cost` | every field (`interest_total`, `fee_total`, `total`, the counts, the dates) | none |
| `vf.fee_summary` | `yearly_equivalent` (only for a span of 90 days or more) | yearly |
| | `total_fees`, `fee_count`, `span_days`, dates | none |
| `pi.duplicate_invoice`, `pi.iban_change`, `pi.vat_error`, `pi.reconciliation` | every field | none: no `interval_type` and no yearly field; `days_apart` and `days_past_due` count days, they are not a period of a cost |

So the check can fire on the zombie and vampire alerts above and never on a phantom alert.

DN-MC-09 *Ambiguous figures are left alone.* A figure is checked only when every field it matches
has a stated period and all of them say the same (REQ-MC-21). A monthly `new_amount` of 12.00 next
to an `extra_cost_per_year` of 12.00 could be either, so neither phrase rejects it. A yearly
interval is not ambiguous: its `current_amount` and `yearly_cost` are both yearly, so `a month`
next to it is rejected. A figure that also equals a numeric field with no stated period (a count
of 12, say) is left alone too: the model may be quoting that field.

DN-MC-10 *The recorded verdicts.* Every committed answer was read against this rule, record by
record, before the code was written (task MC10). None ends on the template because of it, so the
pinned sets of `tests/test_recorded_verdicts.py` are expected to stay as they are; the first
`pytest` run confirms it.

Limits of §7 (the README states the first two):

- It checks the period only, not other meaning: `MUSICBOX raised its price to 10.99 EUR per month`
  passes on an alert where nothing rose.
- A figure that matches no field with a stated period is not checked: on the duplicate-subscription
  card 10.99 is only in the cited rows, so `MUSICBOX costs 10.99 EUR every year` still passes there.
- A phrase separated from its figure by a comma (`10.99 EUR, every year`) is not tied to it, and a
  phrase not in the list (`per annum`, `every quarter`, `anuales`) is not read.
- Numbers written in words are not checked by this rule (the number guard still checks their
  value).

## §8 The recording script (session 28a, REQ-MC-27 to REQ-MC-34)

`scripts/record_live_run.py` imports the three apps' settings, detectors and explain support and
`ledger_kit` (public names), as `scripts/ledger_scan.py` does. It imports no SDK: with no injected
client it passes `client=None` to `explain_with_meta`, so the explainer builds the one real client
(`max_retries=0`, `llm_timeout_seconds()`) exactly as for a page. `main(argv, *, client, clock,
today, out)` takes the client, the clock, the date and the output stream as parameters, so the
tests run it with a fake client and a fake clock.

| Step | What it does |
|---|---|
| cards | each app's `run_pipeline` on its CSV demo (zombie with `load_cpi`), the rows and template its page uses |
| `plan()` | per app (Z, P, V): every card in page order, then the three trick questions on the first critical card |
| `ask()` | `explain_with_meta(alert, rows, fallback_template=..., client=..., row_columns=..., question=...)` |
| `record()` | the record fields of the 11 Nov file plus `observed_reason`, `observed_calcs` |
| write | once, at the end, with `open("x")`: an existing file is never replaced |

DN-MC-11 *Page order.* Cards are sorted by severity (critical, warning, info) with a stable sort,
so ties keep the pipeline order. That is the order of the 11 Nov file as it reads; the tests pin
only the scope (the 43 pairs of alert id and question id, and the count per app letter), so a
different tie order would change ids, never the scope.

DN-MC-12 *`observed_reason`.* It is `Explanation.rejected_reason` when the kit gives one
(`calc_not_allowed`, `period_mismatch`, `price_index_as_cause`). The kit gives `""` for a figure
not found, so the script writes `figure_not_found` there, and `no_answer` when the raw answer is
empty, so an empty `observed_reason` always means accepted. A failed call is written with
`observed_source` `fallback`, the value the explainer returns (the 11 Nov file wrote `no_answer`
there by hand; the replay skips an empty answer either way).

DN-MC-13 *`--tag` goes into `guard_version`.* The script does not run git; the person recording
writes the commit there. `model` is the model name the panel shows (`LEDGER_KIT_LLM_MODEL`, else
the default); a server version or model id can be added to the file by hand after the run.

DN-MC-14 *No new run is committed here.* The script records; the owner runs it with a model and
decides whether a new file replaces the replay file (`DEFAULT_REPLAY_RUN_PATH` in
`ledger_kit/replay.py`). Nothing of the replay changes in this session.
