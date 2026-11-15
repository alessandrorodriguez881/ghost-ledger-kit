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

## §9 Amendments from the first real run (session 28b, REQ-MC-35 to REQ-MC-38)

Source: `data/live_runs/2026-11-15_llama3.2-3b_calc.json`, one run of `llama3.2:3b`: 30 accepted,
13 on the template, no calculation accepted. Files: `ledger_kit/calc.py` (A-MC-02, A-MC-03),
`ledger_kit/explainer.py` (A-MC-01: `CALC_PROMPT_RULE` and one `if question:`), tests, no app.

DN-MC-15 *A-MC-01: the rule goes in only with a question.* `_call_llm` builds the prompt it had
before 15 Nov, ending at `...in YYYY-MM-DD form.`, and appends `" " + CALC_PROMPT_RULE` when
`question` is not empty, the same test that adds the question to the user message. The rule text is
the one of 27a, moved into the constant. Z03, Z04 and Z06 show why: given the rule, a 3B model
uses it where nothing needs arithmetic. A card without a question cannot ask for a total, so it
does not need the rule. An answer to a card that still holds a placeholder is read by the same
evaluator as before (the model may write one unprompted), now with A-MC-02 and A-MC-03.

DN-MC-16 *A-MC-02: which numbers are read as a field.* Only a number written with a decimal point
(`[0-9]+\.[0-9]+`, parsed as `Decimal` from its text, never through `float`) is looked up among the
numeric fields. A whole number written without one keeps the question rule, even when a field has
that value. The reason is P32: `[[calc: 484.00 * 2 * 5]]` on the duplicate-invoice alert, which has
`invoice_count` = 2. Read literally, "a number equal to exactly one numeric field is that field"
would accept the invented 2 as `invoice_count`, and the 3B model would get the invoice twice
counted into a forecast. A figure the model copies from an alert is an amount or a percentage and
carries its decimals (`359.76`, `36.00`, `61.00`); a count the model wants has to come from the
question. The cost: an alert field that holds a whole amount (`10`) cannot be written as the
literal `10`, only by name or as `10.00`. The lookup is by value, `Decimal` equality, so `100.0`
equals `100.00`.

Order in `_constant`: an `int` is judged by the question and nothing else; a decimal is looked up
(0 fields: rejected with its text, 1 field: that field, 2 or more: ambiguous, rejected with its
text); anything else (`1e2`, `.5`, `1_0.5`, a string, a `bool`) is rejected with its text. The
operand and the formula use the field's name and its shown value (`5 x yearly_cost 107,88 EUR`),
so the provenance line never repeats the literal as the model wrote it. A field of the same value
written by name keeps working when another field has the same value (`total * 5`).

DN-MC-17 *A-MC-03: double counting.* After a successful walk, `_Evaluator.double_count` visits
every `+` node. For each chain of `+` (parentheses are the same chain: `(a + b) + c`) it keeps the
leaves that were read as fields, by name, once each. For a field `t` of the chain it looks for a
set of two or more other fields of the chain, none of value zero, whose values sum to the value of
`t` (`sum_amounts`, `DOUBLE_COUNT_MIN_PARTS = 2`). The first `t` found, in order of first use, is
the one reported, with the first set of that size, as `t = a + b`. It rejects with
`REASON_CALC_NOT_ALLOWED` and that string as the offending part, so the panel verdict says why in
the kit's own words. A part of value zero is no part (`0 + x = x` would make every field a
"total" of itself).

This catches this one pattern, not every reasoning error. It does not see a total and its parts
in two different sums (`total * (a + b)`), a total minus its parts, a sum over a product
(`(total * 2) + a + b`), a part of a part, or two fields that are the same quantity under
different names. The kit never checks that a formula answers the question; the formula is always
shown under the answer (`computed_lines`), so a reader can check it.

DN-MC-18 *What the amendments let through, on purpose.* Three recorded answers now come out
accepted and say little. Z04 `155.88 + 36.00` is `yearly_cost + extra_cost_per_year`: two fields
of the alert, added, not a total the model has any reason to want. V43 `interest_total - 61.00`
is the interest total minus itself, `0,00 EUR†`. Z20 writes the same product twice. Each is a
calculation over alert fields with its formula shown, which is what REQ-MC-03 to REQ-MC-09 allow;
none invents a figure. Whether they should be stopped is a separate decision (a field minus itself,
two fields of different periods in one sum); this session adds neither rule.
**Superseded in session 28c for Z04 and V43** (DN-MC-21, DN-MC-22); Z20 stays accepted.

DN-MC-19 *Earlier tests that had to follow A-MC-01.* Five existing assertions said the system
message with a question equals the one without: two in `tests/test_explainer_question.py` and the
`card_system` assertion in each of the three apps' `test_*_live_guard.py` (case 2). They now say:
equal to the card's message plus a space and `CALC_PROMPT_RULE`. Nothing else in them changed.

DN-MC-20 *No re-record here.* `DEFAULT_REPLAY_RUN_PATH`, the 11 Nov file, the Home example and the
docs are untouched. The new file is pinned in `tests/test_recorded_verdicts.py` (task MC18).

## §10 Amendments from the review of 28b (session 28c, REQ-MC-39 to REQ-MC-41)

Files: `ledger_kit/calc.py` only (`_compute` gets `arithmetic`, `_Evaluator` counts uses), tests,
the pinned set. `explain_with_meta` already passes `question`; `resolve_calculations` reads
`bool(question)`, the same test `_call_llm` uses to add the rule and the question.

DN-MC-21 *A-MC-04: a plain card holds no arithmetic.* Given no question, the prompt has no
placeholder rule (A-MC-01), so a placeholder there is unprompted. The only reading worth keeping is
a field the model wraps (Z03 `[[calc: 359.76]]`); everything with an operator is the model
inventing a calculation (Z04: `yearly_cost` already includes the increase, so adding
`extra_cost_per_year` shows a double-counted `191,88 EUR`). The check is on the parsed tree: the
body must be a `Name` or a `Constant`, so a unary minus is an operator too. It runs after the walk
and after the double-count check, so a part rejected earlier (Z06 `12`) keeps the part it had; the
part of this rejection is the expression as written.

DN-MC-22 *A-MC-05: a field once per placeholder.* `_use_field` counts the uses of each field, a
figure read as a field (A-MC-02) included, so `interest_total - 61.00` (V43) and `8.99 + (amount -
8.99)` (the Z21 shape) are a field used twice and three times. `FIELD_MAX_USES = 1`. The part is
`NAME used more than once`, the first field in order of first use. It runs after A-MC-04 and applies
with a question too: `5 * yearly_cost` uses one field once and stays accepted. Counted per
placeholder: the same field in two placeholders of one answer is fine (Z20). Cost: `a * b + a * c`
over fields is rejected; a question that needs a field twice has to be asked in two placeholders.
Z21 on the real alert is rejected earlier, by A-MC-02 (8.99 is no field), so DN-MC-22 does not
change its part; the Z21 shape is tested on a synthetic alert that has the field.

DN-MC-23 *Earlier tests that had to follow.* `test_a_placeholder_with_no_constant_needs_no_question`
of `tests/test_explainer_calc.py` expected arithmetic on a plain card to compute; it is now three
tests (rejected without a question, one field accepted without one, arithmetic computed with one).
`test_the_same_field_twice_is_not_double_counting` of `tests/test_calc_amendments.py` now expects
the A-MC-05 rejection. `test_explain_alert_appends_the_question_and_sends_only_row_columns` of the
phantom app compared system prompts that A-MC-01 made different: it expects the question-mode
prompt (the plain prompt, a space and `CALC_PROMPT_RULE`) and keeps its row-column checks.
