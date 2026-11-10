# live-guard — Design

Section numbers (§) are referenced by `tasks.md`. Requirement ids are in `requirements.md`.

## §1 What was read

- `ledger_kit/explainer.py`: `explain_with_meta` returns the fallback when there is no key and no
  client, calls `_call_llm` (system prompt with the verbatim no-invention sentence, user message
  `Alert: <json>\n\nSource rows:\n<json>`, `temperature=0`, one attempt, `openai.OpenAI(base_url=
  os.environ.get("OPENAI_BASE_URL") or None, api_key=os.environ["OPENAI_API_KEY"], timeout=10,
  max_retries=0)`), then `_passes_number_guard`. The model comes from `LEDGER_KIT_LLM_MODEL`
  (default `gpt-4o-mini`). The result is a frozen `Explanation(text, source, rejected_numbers)`.
  Rejected tokens are numbers as written, IBAN-shaped tokens, malformed dates as written, and valid
  dates in **ISO form** whatever the model wrote.
- The three apps: each has `_explain(alert, ledger_or_pipeline, hallucinate)` cached in
  `*_explanations` by `(alert.id, mode)`, a `_render_alert` that draws a bordered container with the
  title, text, badge, refs and a source-rows expander, and an `explain_support.py` with `TEMPLATES`,
  `template_for` and a `HallucinatingStubClient` (copied per app, because apps may not import each
  other). Phantom goes through `explain_alert(alert, invoices, suppliers, payments, client=)`, which
  passes `row_columns=ROW_COLUMNS`.
- Tests: `tests/test_explainer.py` has `MockLLMClient` and a fake `openai` module through
  `monkeypatch.setitem(sys.modules, "openai", ...)`; app tests use `AppTest.from_file` and set
  `st.session_state` before `run()`. `Explanation(...)` is built positionally in app tests.
- Rules: `structure.md` (package boundaries, key prefixes), `testing.md` (three tiers, fakes, no
  network), `finance-rules.md` (Rule 1, 7, 8), `tech.md` (LLM constraints: `LLM_TIMEOUT_SECONDS = 10`,
  single attempt, never an exception out of the explainer).

## §2 Architecture

```
 radio + Ask (app)                      ledger_kit/live_guard.py (pure)
        |                                 TRICK_QUESTIONS, live_status, probe_result,
        v                                 tally, highlight_segments / highlight_html
 explain_with_meta(question=...)  --->   (no Streamlit, no model, no I/O)
  ledger_kit/explainer.py
        |  same _call_llm, same guard
        v
 Explanation(text, source, rejected_numbers, raw_answer)
```

The explainer stays the only module that calls a model. `live_guard.py` sits next to it, takes
`Explanation` objects and strings, and returns plain data. Each app renders; the render function is
a thin copy per app (about 45 lines) around the shared pure parts.

## §3 Decisions

| # | Decision | Reason |
|---|---|---|
| DN-LG-01 | The three question texts contain **no digit** ("five years from now", not "by 2030"). | The guard rejects any number not in the data. A question with `2030` would make a faithful echo of `2030` look like an invention, and a judge would see a false catch. Without digits in the question, every digit in the answer is the model's own. REQ-LG-03 also forbids whitelisting question figures. |
| DN-LG-02 | The question goes in the **user** message, after the rows; the system prompt is untouched. | The user asked not to weaken the prompt, and the verbatim no-invention sentence is a binding rule (Finance Rule 1). The test compares the system message with and without a question. |
| DN-LG-03 | `Explanation.raw_answer` is a new field with `compare=False, repr=False`, default `""`. | The panel must show the raw answer, which `explain_with_meta` currently discards on rejection. A new return type or a second function would duplicate the call path. `compare=False` keeps every existing equality assertion true; `repr=False` keeps a raw answer out of any accidental log line. |
| DN-LG-04 | Shared pure code in a new `ledger_kit/live_guard.py`; rendering per app. | Questions, caption text, tally and highlight must be identical in three apps; copying them three times invites drift. The earlier stub was copied only because the library had no such code. `ledger_kit` has no Streamlit dependency and the boundary rules keep it that way, so the widgets stay in each app. The user asked for the explainer change in `explainer.py`; that is where the argument lives, the new module holds no LLM call. |
| DN-LG-05 | `enabled` means `OPENAI_API_KEY` is non-empty. A base URL alone leaves the panel off, with its own caption. | The brief says "no key and no base URL" is the off state. But `explain_with_meta` returns the fallback without calling when there is no key, so a base URL alone would give an enabled panel that never calls anything. Changing the explainer to invent a dummy key would alter today's behaviour. The caption for the base-URL-only case tells the user to set any key. Answered in DN-LG-19. |
| DN-LG-06 | The panel ignores the "Simulate a hallucinating LLM" switch and always uses the configured real model. | The switch is the offline proof; the panel is the live proof. Mixing them would let the stub pose as a live model. |
| DN-LG-07 | A probe answer never replaces the card text and never goes into `*_explanations`. | A trick-question answer is not an explanation of the alert. Keeping it apart protects Finance Rule 8 and the existing cache key `(alert.id, mode)`. |
| DN-LG-08 | App tests install a fake `openai` module in `sys.modules` plus a dummy key in the environment, instead of a test seam in the app (a client stored in `st.session_state`). | `AppTest` runs in the same process, so the patch works, and the real path is exercised: key read, `base_url` and `timeout=10`, `max_retries=0` passed to `OpenAI(...)`, request built by `_call_llm`. No test-only branch in production code. |
| DN-LG-09 | Counter: `asked` counts presses, `checked` counts answers that reached the guard, `rejected` counts guard rejections. The display shows checked and rejected; `asked` only drives the limit. | An error is not a check; counting it would flatter or hide the guard. `asked` makes the courtesy limit honest. |
| DN-LG-10 | `LIVE_ASKS_PER_SESSION_LIMIT = 30`, a named constant, labelled a courtesy. | If a deployer puts a hosted key in the environment of a public deployment, every visitor can press Ask. Presets and a 10 s cap bound one click; the limit bounds an idle loop. A reload resets it, so it is not security, and the docs say so. Finance Rule 7 asks for named constants. |
| DN-LG-11 | The error message never includes the exception text, URL or key. | Provider exceptions often carry the endpoint and sometimes more. A fixed sentence is enough for the viewer and cannot leak. |
| DN-LG-12 | `LLM_TIMEOUT_SECONDS` stays 10 as the default (see DN-LG-18 for the optional override). The docs tell the user to warm the model up. | The constant is a binding part of `tech.md` and Streamlit renders synchronously. A cold local model can exceed it; that is a known demo risk, now with a documented way out, not hidden. |
| DN-LG-13 | The raw answer is shown as `html.escape`d text inside `<pre style="white-space: pre-wrap">` with `<mark>` for flagged tokens, rendered with `unsafe_allow_html=True`. | Model output is untrusted. Escaping first and adding only our own `<mark>` tags makes injection impossible; an HTML block of type `<pre>` keeps Markdown in the answer literal, so the viewer sees exactly what the model wrote. The mark carries its colours inline, so no per-app CSS is needed. The mark is also bold and underlined so it does not rely on colour. |
| DN-LG-14 | Dates are highlighted in both ISO and `DD/MM/YYYY` form. | The guard reports a bad date as ISO whatever the model wrote; highlighting only the ISO form would show a rejection with nothing marked. |
| DN-LG-15 | The guard is not touched. | The aim is to show the existing guard against a real model. A model that writes `1.` as a list number will be rejected; the panel shows the exact token and the docs say why (REQ-LG-19). Loosening it for the demo would defeat the demo. |
| DN-LG-16 | App tests carry their own small fake-`openai` helper per app (`*_live_fakes.py`), not one shared helper under `tests/`. | `structure.md`: app tests do not import helpers of the library test folder; apps are self-contained and the existing stubs are copied per app. |
| DN-LG-17 | The result is stored per `(alert.id, question.id)` and the call happens only on the Ask press. | Streamlit reruns the script on every interaction; without this, every rerun would call the model. |
| DN-LG-18 | **Answer 1 (session 14b).** An optional environment variable `LEDGER_KIT_LLM_TIMEOUT` sets the call timeout: a whole number of seconds from 1 to 120 (`LLM_TIMEOUT_MIN_SECONDS`, `LLM_TIMEOUT_MAX_SECONDS`); no value, a non-integer, or a number outside the range falls back to 10 (`LLM_TIMEOUT_SECONDS`, the value `tech.md` fixes) with no error. `llm_timeout_seconds(env=None)` in `explainer.py` reads it at call time; `live_status` reports it in `LiveStatus.timeout_seconds`; the panel prints the effective value through `no_answer_message(seconds)`. `tech.md`, `.env.example` and `docs/live-guard.md` are updated. | A cold local model can exceed 10 s on a slow CPU; a viewer needs a documented way out that does not edit code. The default and the one-attempt rule are unchanged, and a bad value never raises. |
| DN-LG-19 | **Answer 2.** The panel is on only when `OPENAI_API_KEY` is non-empty. A base URL alone leaves it off with its own caption (`CAPTION_URL_WITHOUT_KEY`), which says that local servers such as Ollama accept any non-empty key. The explainer does not invent a key. | Same reasoning as DN-LG-05; the caption now explains why any key will do. |
| DN-LG-20 | **Answer 3.** The `winget` id `Ollama.Ollama`, the model tag `llama3.2:1b` and the `AppTest` property names (`disabled` on `st.radio` and `st.button`, `options`, `session_state.filtered_state`) stay unverified by the author. Task LG8 is the manual run; the AppTest tests will show the property names. | The author cannot run commands. The names are read from `streamlit/testing/v1/element_tree.py` of the pinned 1.67.0 (`Widget.disabled`, `Widget.key`), but nothing was executed. |
| DN-LG-21 | **Answer 4.** The guard is left unchanged. `docs/live-guard.md` and the README say plainly that a real answer can be rejected for a harmless count such as `3 months`, because the guard checks figures, not meaning; the panel already shows the exact rejected tokens, so a viewer can judge. | Same as DN-LG-15: loosening the guard for the demo would defeat the demo. |
| DN-LG-22 | Implementation note: the Ask button uses `on_click=_ask_model` (a callback with `args=(alert, ledger_or_pipeline, question)`), not an `if st.button(...)` body. | A callback runs before the script reruns, so the session counter is already updated when the first card is drawn; with an `if` body the cards above the pressed one would show the old counter, against REQ-LG-13 ("the same value in every card"). It also keeps `test_zs_app_logic` and `test_pi_app_logic` true: no `if <button>` body writes session state. |
| DN-LG-23 | Implementation note: in `zombie_subscriptions/app.py` the radio is called through the local alias `pick_question = st.radio`. | `test_zs_real_formats.py` unpacks `[radio] = _calls(tree, "st.radio")`, i.e. it requires exactly one `st.radio(` call in the file (the demo-format radio). The alias keeps that test unchanged. The other two apps have no such test and call `st.radio` directly. |
| DN-LG-24 | Implementation note: `test_pi_structure_steering.py` was extended by two names and its count (41 to 43 files): `live_guard` in `TEST_MODULES` and `pi_live_fakes.py` in `TEST_HELPERS`. | That test pins the exact file set of `apps/phantom_invoices/` and fails on any new `.py` file there, so LG5 cannot be done without it. No assertion was loosened. |

## §4 `ledger_kit/explainer.py` change (REQ-LG-01 to REQ-LG-03)

```python
@dataclass(frozen=True)
class Explanation:
    text: str
    source: Literal["llm", "fallback"]
    rejected_numbers: tuple[str, ...]
    raw_answer: str = field(default="", compare=False, repr=False)

def explain(alert, rows, *, fallback_template, client=None, row_columns=None, question=None) -> str: ...
def explain_with_meta(..., question: str | None = None) -> Explanation: ...
def _call_llm(alert, rows, *, client=None, question: str | None = None) -> str | None: ...
```

In `_call_llm`, after `user_content` is built: `if question: user_content += "\n\nQuestion from the user: " + question`.
The system prompt string, `temperature`, the retry loop and the lazy `import openai` are unchanged.
In `explain_with_meta`, the two success paths pass `raw_answer=raw`; the other returns keep the
default. `_passes_number_guard` is not changed and receives no question.

## §5 `ledger_kit/live_guard.py` (REQ-LG-04 to REQ-LG-08)

Public names: `TrickQuestion`, `TRICK_QUESTIONS`, `LiveStatus`, `live_status`, `CAPTION_OFF`,
`CAPTION_URL_WITHOUT_KEY`, `ProbeResult`, `probe_result`, `Counts`, `tally`,
`LIVE_ASKS_PER_SESSION_LIMIT`, `Segment`, `highlight_segments`, `highlight_html`, plus the fixed
sentences the apps print (`VERDICT_ACCEPTED`, `VERDICT_REJECTED_PREFIX`, `MSG_NO_ANSWER`,
`MSG_LIMIT`, `NOTE_GUARD_SCOPE`, `counter_caption(counts)`). Keeping every sentence in the module
means the three apps print identical text and one test pins it.

`highlight_segments` algorithm: for each token build the list of search forms (the token; plus the
`DD/MM/YYYY` form when the token matches `\d{4}-\d{2}-\d{2}`); for each form compile
`(?<![\d.,])` + `re.escape(form)` + `(?!\d)` and collect `(start, end)` spans; sort, merge overlaps,
and cut `raw` along the spans. Empty tokens are ignored. Spans never leave `0..len(raw)`.

`live_status` takes a mapping, so tests pass a dict and apps pass `os.environ`.

## §6 Panel in each app (REQ-LG-09 to REQ-LG-17)

A function `_render_live_panel(alert, rows_source)` in each `app.py`, called at the end of the card
container of `_render_alert`:

```
status = live_status(os.environ)
with st.expander("🔦 Provoke the LLM"):
    st.caption(intro)  # "Three questions that tempt a model to state a figure that is not in the
                       #  cited rows. Model: {status.model}."
    label = st.radio("Trick question", labels, key=f"{P}_lg_q_{alert.id}", disabled=not status.enabled,
                     label_visibility="collapsed")
    counts = st.session_state[f"{P}_lg_counts"]
    can_ask = status.enabled and counts.asked < LIVE_ASKS_PER_SESSION_LIMIT
    if st.button("Ask the model", key=f"{P}_lg_ask_{alert.id}", disabled=not can_ask):
        meta = <call explain_with_meta once, question=selected.text>
        result = probe_result(selected, meta, fill_fallback(template_for(alert), alert))
        store result; counts = tally(counts, result); store counts
    show result for (alert.id, selected.id) if stored  (REQ-LG-11 / REQ-LG-12)
    if not status.enabled: st.caption(status.caption)
    elif limit reached: st.caption(MSG_LIMIT)
    st.caption(counter_caption(counts))
```

The pieces that differ per app are only the call and the keys:

| App | Prefix | How the one call is made |
|---|---|---|
| zombie_subscriptions | `zs` | `rows = ledger[ledger["source_ref"].isin(alert.source_refs)]`; `explain_with_meta(alert, rows, fallback_template=template_for(alert), question=q.text)` |
| vampire_fees | `vf` | same as zombie |
| phantom_invoices | `pi` | `explain_alert(alert, invoices, suppliers, payments, question=q.text)`; `explain_alert` gets the same optional `question` and passes it on, so `ROW_COLUMNS` still applies |

`_init_state` of each app adds `setdefault(f"{P}_lg_results", {})` and
`setdefault(f"{P}_lg_counts", Counts(0, 0, 0))`. The card text still comes from the unchanged
`_explain`. Because the expander body runs on every rerun, the radio and button exist for each
alert; with 19 alerts that is 38 widgets, which Streamlit handles without a measurable cost, and no
model is touched until a press.

Layout note: the stored `ProbeResult` holds the raw answer, so the result area needs no second call
after the user switches the radio and back.

## §7 Test strategy (testing.md tiers)

This feature adds no detector, so the three detector tiers do not apply as such; the rule behind
them (normal, edge, property) is kept for the pure module.

- **Tier 1 normal**: inventing fake rejected with its token reported; faithful fake accepted; raising
  fake gives the fallback; disabled state; AppTest per app.
- **Tier 2 edge**: empty `question` and `None` produce today's request; empty model answer; token
  not in raw; token preceded by a digit; ISO/EU date forms; HTML in the answer; limit reached; base
  URL without key.
- **Tier 3 property (Hypothesis, `max_examples=200`)**: `highlight_segments` joins back to `raw`
  exactly, spans are ordered, disjoint and in range, and each flagged segment contains a token form;
  `highlight_html` never contains an unescaped `<` outside our own `<mark`/`<pre` tags; `tally` keeps
  `rejected <= checked <= asked`; question text never changes the system message.
- **Fakes**: a library `MockLLMClient` already exists in `tests/test_explainer.py`; the new library
  test file defines its own small copy (test modules do not import each other). Each app's
  `*_live_fakes.py` installs a fake `openai` module whose `OpenAI(**kwargs)` records the kwargs and
  whose `chat.completions.create(**kwargs)` answers by request: if the user message contains
  `Question from the user:` it returns the scripted answer for the scenario (`invent`, `faithful`,
  `raise`); otherwise it returns a plain figure-free sentence for the card. The `faithful` scenario
  builds its answer from the request: it cites `source_refs[0]` from the `Alert:` JSON and copies one
  amount verbatim from the `Source rows:` JSON, so the figure is in the data by construction. The
  `invent` answer uses `8765.43`, and the test first asserts that string is in no alert or row.
- **No network, no clock, no real key**: environment values are `monkeypatch.setenv`/`delenv`.

## §8 Files

New: `ledger_kit/live_guard.py`, `tests/test_explainer_question.py`, `tests/test_live_guard.py`,
`tests/test_live_guard_docs.py`, `apps/<app>/tests/<p>_live_fakes.py` and
`apps/<app>/tests/test_<p>_live_guard.py` (three apps), `docs/live-guard.md`.

Edited (additive): `ledger_kit/explainer.py`, the three `app.py`, `apps/phantom_invoices/
explain_support.py` (`question` passthrough), `README.md`, `.env.example`,
`.kiro/steering/structure.md` (layout and boundary line), `tests/test_showcase_app.py` (disjoint
key check extended; see LG6).

Not touched: detectors, templates, thresholds, every existing test body, `requirements.txt`
(`openai==3.46.0` is already pinned there).
