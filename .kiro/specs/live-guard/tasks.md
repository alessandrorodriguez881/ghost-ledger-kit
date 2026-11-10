# live-guard — Implementation Tasks

Every task is test-first: write the tests, see them fail for the right reason, then implement.
Section references (§) point to `design.md`, REQ ids to `requirements.md`. Verification
(`ruff check .`, `ruff format --check .`, `pytest`, a headless start of `streamlit_app.py`, and the
manual Ollama run of `docs/live-guard.md`) is run by the user. Tasks run in order; LG3 to LG5 repeat
one pattern.

## Task LG1 — Library: `question` and `raw_answer`

**Covers**: REQ-LG-01, REQ-LG-02, REQ-LG-03, REQ-LG-20, §4

- [x] Create `tests/test_explainer_question.py` (own small `MockLLMClient`; no edit of
  `tests/test_explainer.py`). Tier 1: with `question=None` and with `""` the recorded `messages`
  equal the request built without the argument; with a question the system message is identical and
  contains the verbatim no-invention sentence, and the user message ends with
  `\n\nQuestion from the user: <question>`; `temperature == 0` and one call. Inventing answer
  (`779.40`) → `source == "fallback"`, `rejected_numbers == ("779.40",)`, `raw_answer` equals the
  answer, and equality with the three-argument `Explanation` holds. Faithful answer
  (`155,88 EUR`) → `source == "llm"`. Raising client → `raw_answer == ""`, no exception. No key and
  no client → `raw_answer == ""`. Tier 2: question `"Is 4242 right?"` with answer `"Yes, 4242."` →
  rejected `("4242",)`; empty model answer → `raw_answer == ""`; IBAN-shaped answer and an invalid
  date answer still rejected with a question. Tier 3 (Hypothesis, `max_examples=200`): for any
  question text, `messages[0]` equals the system message of a call without a question, and
  `source_refs` stay a subset of `loaded_source_refs`.
- [x] Implement §4 in `ledger_kit/explainer.py` (`field` import, `raw_answer`, `question` on
  `explain`, `explain_with_meta`, `_call_llm`; `raw_answer=raw` on the two paths that have it).
- [x] Run the existing `tests/test_explainer.py` and the app explanation tests unchanged; they must
  pass without edits.
- [x] (Answer 1, DN-LG-18) Optional `LEDGER_KIT_LLM_TIMEOUT`: `tests/test_explainer_timeout.py` first,
  then `llm_timeout_seconds` in `ledger_kit/explainer.py`, `live_status`/`no_answer_message` in
  `live_guard.py`, and `tech.md`, `.env.example`, `docs/live-guard.md`.

## Task LG2 — Pure module `live_guard.py`

**Covers**: REQ-LG-04 to REQ-LG-08, §5

- [x] Create `tests/test_live_guard.py`. Tier 1: `TRICK_QUESTIONS` ids, labels and texts exactly as
  REQ-LG-04 and no digit in any text; `live_status` for the three examples of REQ-LG-05 (the object
  repr contains neither the key nor the URL); `probe_result` for the three examples of REQ-LG-06;
  `tally` sequence `(0,0,0) → (1,1,0) → (2,2,1) → (3,2,1)`; `counter_caption(Counts(2,2,1))` ==
  `Answers checked: 2 · rejected: 1`; the four highlight examples of REQ-LG-08 with exact
  segments/HTML. Tier 2: empty `raw`, empty `tokens`, empty-string token, token absent, token at the
  start and end of `raw`, two tokens overlapping, a whitespace-only key counts as set (same as the
  explainer), `LIVE_ASKS_PER_SESSION_LIMIT == 30`. Tier 3 (Hypothesis, `max_examples=200`): segments
  join to `raw`; spans ordered, disjoint, in range; every flagged segment matches a token form;
  `highlight_html` of arbitrary text contains no `<` other than our `<mark ...>`, `</mark>`,
  `<pre ...>`, `</pre>`; `rejected <= checked <= asked` after any sequence of verdicts.
- [x] Implement `ledger_kit/live_guard.py` (§5). Stdlib plus `ledger_kit.explainer` only.
- [x] Add one test that the module imports no Streamlit and that `ledger_kit` still imports no app
  (same style as `test_showcase_requirements.py`).

## Task LG3 — Panel in zombie_subscriptions

**Covers**: REQ-LG-09 to REQ-LG-17 for `zs_`, §6, DN-LG-08

- [x] Create `apps/zombie_subscriptions/tests/zs_live_fakes.py` (fake `openai` module installer,
  scripted by scenario, §7) and `test_zs_live_guard.py`. Load the demo the way `test_zs_app.py`
  does. Cases:
  1. Structure: every alert card has one `🔦 Provoke the LLM` expander, one radio with the three
     labels, first selected, one `Ask the model` button; no text input with a key containing `_lg_`.
  2. `invent`: press Ask → exactly one question call; its user message ends with the question text
     and its system message equals the card call's system message; the page shows a `<mark` around
     `8765.43`, the rejected verdict line with `` `8765.43` ``, the template block, and
     `Answers checked: 1 · rejected: 1`.
  3. `faithful`: accepted verdict text, no `<mark`, `Answers checked: 1 · rejected: 0`.
  4. `raise` (message contains `localhost`): `MSG_NO_ANSWER` shown, `localhost` shown nowhere,
     `Answers checked: 0 · rejected: 0`, card text and badge unchanged.
  5. Rerun safety: after one press, change a sidebar widget; call count for the question stays 1.
  6. Disabled: key and base URL unset → radio and button `disabled`, `CAPTION_OFF` once per card,
     counter `0 · 0`; base URL only → `CAPTION_URL_WITHOUT_KEY`. The hallucinate switch on in this
     state still produces the rejected badge (offline proof intact).
  7. Isolation (REQ-LG-15, REQ-LG-16): hallucinate switch on + press Ask goes to the fake `openai`,
     `zs_explanations` has the same keys before and after; with key `test-key-not-real` and base URL
     `http://base.invalid/v1`, neither string appears in any page element or session value; the
     fake `OpenAI` received `base_url="http://base.invalid/v1"`, `timeout=10`, `max_retries=0`.
  8. Limit: with `Counts(30, 0, 0)` preset in session state the button is disabled and `MSG_LIMIT`
     shows.
- [x] Implement the panel (§6) in `apps/zombie_subscriptions/app.py`: `_render_live_panel`, the two
  `_init_state` defaults, the call at the end of the card container.

## Task LG4 — Panel in vampire_fees

**Covers**: same requirements for `vf_`, §6

- [x] `apps/vampire_fees/tests/vf_live_fakes.py` and `test_vf_live_guard.py` with the eight cases of
  LG3 (prefix `vf_`, demo loaded the way `test_vf_app_logic.py` does).
- [x] Implement the panel in `apps/vampire_fees/app.py`.

## Task LG5 — Panel in phantom_invoices

**Covers**: same requirements for `pi_`, §6

- [x] `apps/phantom_invoices/tests/pi_live_fakes.py` and `test_pi_live_guard.py` with the eight
  cases of LG3 (prefix `pi_`, demo loaded the way `test_pi_app_logic.py` does). Add to
  `test_pi_explain_support.py`'s new sibling test a check that `explain_alert(..., question=Q)` sends
  only `ROW_COLUMNS` and ends the user message with the question, and that without `question` the
  call is unchanged.
- [x] Add the optional `question` passthrough to `explain_alert` in
  `apps/phantom_invoices/explain_support.py`; implement the panel in
  `apps/phantom_invoices/app.py`.

## Task LG6 — Showcase isolation and layout steering

**Covers**: REQ-LG-17, REQ-LG-20

- [x] Extend the disjoint-key test in `tests/test_showcase_app.py` (additively, new test function)
  so that the `*_lg_results` and `*_lg_counts` keys of the three apps are distinct and none is in
  any `WIDGET_KEYS`; and one headless test of `streamlit_app.py` that, with a fake `openai`, a probe
  in the zombie page does not change the counter of the vampire page after navigation.
- [x] Update `.kiro/steering/structure.md`: add `ledger_kit/live_guard.py`, the new test files, the
  three `*_live_fakes.py`, `docs/live-guard.md`, and the boundary line "`live_guard.py` is pure: no
  Streamlit, no model call; the explainer stays the only module that calls a model".

## Task LG7 — Documentation

**Covers**: REQ-LG-18, REQ-LG-19

- [x] Create `tests/test_live_guard_docs.py`: `docs/live-guard.md` has the five sections in order;
  contains every command line of REQ-LG-18 verbatim; contains `small local models`,
  `does not judge wording`, `10 seconds`, `warm`, `figures, dates and IBAN-shaped tokens`; the three
  env var names in the doc equal the names read by `live_status`; no line of the doc, the README
  paragraph or `.env.example` holds a real-looking key (placeholders only: `ollama`,
  `your-api-key-here`); the README paragraph links to `docs/live-guard.md`; `.env.example` keeps its
  original line and has the two new commented lines.
- [x] Write `docs/live-guard.md`, the README paragraph (under *How it works*, after "The proof is a
  switch."), and the `.env.example` lines.
- [x] In the doc's *What to expect*, give the three presets and what each tempts, and say honestly
  that on a large hosted model the likely outcome is a refusal or an accepted answer, which is also a
  valid result.

## Task LG8 — Manual proof (user, not automated)

**Covers**: REQ-LG-19 claims

- [ ] The user follows `docs/live-guard.md` on Windows with Ollama and the chosen small model, presses
  each preset on one alert in each app, and records what happened (accepted, rejected, timeout). The
  README and the doc must not claim a rejection rate; the doc states only what the commands do and
  that results vary by model. If the first call times out, the warm-up step is confirmed or
  corrected in the doc.

## Not verified by the author

The spec was written without running a command. Unverified on purpose: the `winget` package id
`Ollama.Ollama`, the availability and size of the model tag `llama3.2:1b`, whether a warm 1B model
answers inside 10 seconds on the user's CPU, and the exact `AppTest` property names for `disabled`
on `st.radio` and `st.button` in the pinned `streamlit==1.67.0`. The user runs `ruff check .`,
`ruff format --check .`, `pytest`, and the manual Ollama steps, and reports failures.
