# live-guard — Requirements

## Overview

An adversarial review said the number guard is only ever shown catching a *simulated* hallucination:
the stub behind "Simulate a hallucinating LLM" always answers `99999.99`, so the proof is scripted.
`live-guard` adds a **Provoke the LLM** panel so a judge, or the demo video, can watch a *real* model
try to state a figure that is not in the data and watch the guard catch it.

The explainer already calls a real model when `OPENAI_API_KEY` is set, and `OPENAI_BASE_URL` lets it
use any OpenAI-compatible server, including a local model served by Ollama at
`http://localhost:11434/v1`. The feature adds:

- an optional `question` argument and a `raw_answer` field in `ledger_kit/explainer.py`;
- one small pure module, `ledger_kit/live_guard.py` (questions, status, verdict, counter, highlight);
- one expander under every alert card in the three apps, with three preset trick questions;
- `docs/live-guard.md`, a README paragraph and `.env.example` lines.

It adds no detector, changes no threshold, no alert, no template and no existing test. The panel is a
**demonstration of the guard**, not a feature of the product: a probe answer never replaces the text
of a card and never feeds back into an alert (Finance Rule 8, product non-goals).

Ids are `REQ-LG-nn`. EARS keywords: *shall*, *when*, *while*, *where*, *if ... then*. Every example
gives a concrete input and the exact expected output. All data in examples is **(synthetic)**.

## Shared fixture of the examples

Alert `A` (detector `zs.recurring_charge`, `source_refs = ["bank.csv:0"]`,
`data = {"current_amount": "12.99", "yearly_cost": "155.88"}`) and one cited row
`{date: 2026-10-01, amount: 12.99, flow: debit, currency: EUR, counterparty: STREAMBOX,
source_ref: bank.csv:0}`.

---

## 1 — Library: the question and the raw answer

- **REQ-LG-01** The functions `explain` and `explain_with_meta` of `ledger_kit/explainer.py` shall
  accept an optional keyword `question: str | None = None`. *When* `question` is `None` or `""`, the
  request sent to the model shall be **identical to today's** (same system message, same user
  message, `temperature=0`, one attempt). *When* it is a non-empty string, the system message shall
  be unchanged and the user message shall be today's user message followed by
  `"\n\nQuestion from the user: " + question`.
  - Example: `question=None` → `client.calls[0]["messages"]` equal to the messages captured before
    this change (pinned by a test that builds the expected strings from the old code path).
  - Example: `question="What amount will be charged next month?"` →
    `messages[0]["content"]` is the same string as without a question and contains, verbatim,
    `You must not invent any number, date, name, or amount.`;
    `messages[1]["content"]` starts with `Alert: ` and ends with
    `\n\nQuestion from the user: What amount will be charged next month?`.

- **REQ-LG-02** `Explanation` shall gain a field `raw_answer: str = field(default="", compare=False,
  repr=False)` holding the model's text exactly as received. It shall be set when the model answered
  (accepted **or** rejected by the guard) and be `""` when there was no key and no client, when the
  call failed or timed out, and when the model returned an empty answer. Because it is excluded from
  comparison, `Explanation("t", "fallback", ()) == explain_with_meta(...)` keeps holding for every
  existing test, and positional construction with three arguments keeps working.
  - Example: client answers `"You will pay 779.40 EUR. Source: bank.csv:0."` for alert `A` →
    result `== Explanation(fill_fallback(T, A), "fallback", ("779.40",))` is `True` and
    `result.raw_answer == "You will pay 779.40 EUR. Source: bank.csv:0."`.
  - Example: client raises `RuntimeError("down")` → `result.raw_answer == ""`,
    `result.source == "fallback"`, `result.rejected_numbers == ()`.
  - Example: `OPENAI_API_KEY` unset and `client=None` → `result.raw_answer == ""`.

- **REQ-LG-03** *When* a question is given, the answer shall go through the **same** number guard
  with the **same** allowed figures as without a question. The figures, dates and names of the
  question text shall **not** be added to what the guard allows, and no guard rule shall be relaxed
  or special-cased for a question.
  - Example: `question="Is 4242 right?"`, client answers `"Yes, 4242."` → `source == "fallback"`,
    `rejected_numbers == ("4242",)`.
  - Example: `question="What is the yearly cost?"`, client answers
    `"The alert gives a yearly cost of 155,88 EUR. Source: bank.csv:0."` → `source == "llm"`,
    `rejected_numbers == ()`.

## 2 — Pure helpers in `ledger_kit/live_guard.py`

The module is stdlib plus `ledger_kit.explainer` types only. It imports no Streamlit, calls no model
and does no I/O. All its public names have annotations and a one-line docstring.

- **REQ-LG-04** The module shall define `TRICK_QUESTIONS`, a tuple of exactly three frozen
  `TrickQuestion(id, label, text)` in this order, and no digit shall appear in any `text`:

  | id | label | text |
  |---|---|---|
  | `forecast` | Forecast: the cost five years from now | `If nothing changes, what will this cost me in total five years from now? Give the amount.` |
  | `next_month` | Next month: the amount of the next charge | `What amount will be charged next month? Give the amount.` |
  | `with_fees` | Total including what the rows do not show | `What is the total cost including any fees, taxes or interest that these rows do not show? Give the amount.` |

  - Example: `[q.id for q in TRICK_QUESTIONS] == ["forecast", "next_month", "with_fees"]` and
    `any(ch.isdigit() for q in TRICK_QUESTIONS for ch in q.text)` is `False`.

- **REQ-LG-05** The module shall define `live_status(env: Mapping[str, str]) -> LiveStatus` with
  fields `enabled: bool`, `model: str`, `caption: str`. It reads only `OPENAI_API_KEY`,
  `OPENAI_BASE_URL` and `LEDGER_KIT_LLM_MODEL` from the mapping it is given. `enabled` is
  `bool(env.get("OPENAI_API_KEY", ""))`, the same test the explainer applies, because without a key
  the explainer does not call the model. `model` is `env.get("LEDGER_KIT_LLM_MODEL") or
  "gpt-4o-mini"`. `caption` is `""` when enabled and otherwise exactly one of:
  - `CAPTION_OFF` (no key, no base URL):
    `Live model off. To try a real model set OPENAI_API_KEY; for a local model with Ollama also set OPENAI_BASE_URL=http://localhost:11434/v1 and LEDGER_KIT_LLM_MODEL to the model you pulled. Steps: docs/live-guard.md. The "Simulate a hallucinating LLM" switch in the sidebar works without any of this.`
  - `CAPTION_URL_WITHOUT_KEY` (base URL set, key not):
    `OPENAI_BASE_URL is set but OPENAI_API_KEY is not. Set OPENAI_API_KEY to any value (Ollama ignores it) to turn the live model on. Steps: docs/live-guard.md.`
  - Example: `live_status({})` → `LiveStatus(False, "gpt-4o-mini", CAPTION_OFF)`.
  - Example: `live_status({"OPENAI_API_KEY": "ollama", "OPENAI_BASE_URL": "http://localhost:11434/v1",
    "LEDGER_KIT_LLM_MODEL": "llama3.2:1b"})` → `LiveStatus(True, "llama3.2:1b", "")`.
  - Example: `live_status({"OPENAI_BASE_URL": "http://localhost:11434/v1"})` →
    `LiveStatus(False, "gpt-4o-mini", CAPTION_URL_WITHOUT_KEY)`.
  - The returned object never contains the key or the base URL.

- **REQ-LG-06** The module shall define `probe_result(question: TrickQuestion, meta: Explanation,
  template_text: str) -> ProbeResult` with fields `question_id`, `raw_answer`, `verdict`
  (`"accepted"`, `"rejected"` or `"unavailable"`), `rejected_numbers: tuple[str, ...]` and
  `template_text`. Rules, in order: `meta.raw_answer == ""` → `unavailable`; `meta.source == "llm"` →
  `accepted`; otherwise `rejected`.
  - Example: `Explanation("T", "fallback", ("779.40",), raw_answer="Pay 779.40")` →
    `verdict == "rejected"`, `rejected_numbers == ("779.40",)`.
  - Example: `Explanation("ok", "llm", (), raw_answer="ok")` → `verdict == "accepted"`.
  - Example: `Explanation("T", "fallback", ())` → `verdict == "unavailable"`.

- **REQ-LG-07** The module shall define `LIVE_ASKS_PER_SESSION_LIMIT: int = 30` and
  `tally(counts: Counts, result: ProbeResult) -> Counts` where `Counts(asked, checked, rejected)`
  is a frozen dataclass of non-negative integers. `asked` always increases by 1; `checked` increases
  by 1 unless the verdict is `unavailable`; `rejected` increases by 1 only for `rejected`.
  - Example: `Counts(0,0,0)` + accepted → `Counts(1,1,0)`; + rejected → `Counts(2,2,1)`;
    + unavailable → `Counts(3,2,1)`.
  - Sizing note: the limit is a courtesy so a public deployment with a hosted key is not drained by
    an idle click loop; it is **not** a security control (a reload resets it).

- **REQ-LG-08** The module shall define `highlight_segments(raw: str, tokens: Sequence[str]) ->
  list[Segment]` and `highlight_html(raw: str, tokens: Sequence[str]) -> str`. A `Segment` is
  `(text: str, flagged: bool)`; joined, the segment texts equal `raw` exactly. A token is flagged
  where it occurs in `raw` as a whole figure: not preceded by a digit, `.` or `,`, and not followed
  by a digit. A token that is an ISO date (`YYYY-MM-DD`) is also flagged in its `DD/MM/YYYY` form,
  because the guard reports dates in ISO form whatever the model wrote. Overlaps are merged. A token
  not found in `raw` flags nothing. `highlight_html` HTML-escapes every segment (`& < > " '`), wraps
  each flagged one in `<mark style="...">`, and wraps the whole in
  `<pre style="white-space: pre-wrap; ...">...</pre>`.
  - Example: `raw = "In five years you will have paid 779.40 EUR. Source: bank.csv:0."`,
    `tokens = ("779.40",)` → segments
    `[("In five years you will have paid ", False), ("779.40", True), (" EUR. Source: bank.csv:0.", False)]`.
  - Example: `raw = "It costs 12,99 EUR or 112,99 EUR"`, `tokens = ("12,99",)` → only the first
    `12,99` is flagged (`112,99` is preceded by a digit).
  - Example: `raw = "Renewal on 01/01/2031."`, `tokens = ("2031-01-01",)` → `01/01/2031` flagged.
  - Example: `raw = '<img src=x onerror=alert(1)> 8765.43'`, `tokens = ("8765.43",)` → output contains
    `&lt;img src=x onerror=alert(1)&gt;` and no `<img`; and `<mark` appears exactly once.

## 3 — The panel in each app

The three apps (`zombie_subscriptions`, `vampire_fees`, `phantom_invoices`) each get the same panel
under the alert card. The panel is drawn inside the card container, after the existing source-rows
expander. Widget keys carry the app prefix (`zs_`, `vf_`, `pi_`) so the three apps of the showcase
never share one (REQ-SC-04).

- **REQ-LG-09** Every alert card shall contain an expander titled `🔦 Provoke the LLM`, collapsed by
  default. Inside it, in this order: one short intro line, a `st.radio` with the three labels of
  REQ-LG-04 (first one selected), an `Ask the model` button, then the result area (REQ-LG-11) and the
  counter (REQ-LG-13). The panel shall contain **no** free-text widget (`st.text_input`,
  `st.text_area`, `st.chat_input`) and no widget that accepts a key, a URL or a model name.
  - Example: a demo run of any app → each alert card has exactly one expander with the label
    `🔦 Provoke the LLM`, one radio with `options == [q.label for q in TRICK_QUESTIONS]` and
    `value == TRICK_QUESTIONS[0].label`, one button labelled `Ask the model`, and the page has no
    text input whose key contains `_lg_`.

- **REQ-LG-10** *When* the user presses `Ask the model`, the app shall call
  `explain_with_meta` **once** for that alert, with `question=` the text of the selected question,
  `client=None` (the explainer builds the client from the environment), the same cited rows, the same
  `row_columns` whitelist and the same fallback template as the card. The call shall not happen on a
  rerun, on opening the expander, or on changing the radio. The result shall be kept in
  `st.session_state[f"{prefix}_lg_results"]` under `(alert.id, question.id)` and shown again on every
  rerun without a new call.
  - Example: press Ask once, then change an unrelated sidebar widget → the fake client recorded
    exactly 1 call carrying a `Question from the user:` message.

- **REQ-LG-11** The result area shall show, in this order:
  1. `Model answer (raw, before the guard):` and the raw answer from `highlight_html` (REQ-LG-08);
  2. the guard verdict line;
  3. `Fixed template shown on the card when the answer is not trusted:` and the filled fallback
     template of the alert.

  The verdict line is exactly one of:
  - rejected: `🛑 Guard verdict: rejected. Not found in the cited rows or the alert data: ` followed by
    the tokens of `rejected_numbers` as inline code, comma separated; the same tokens are
    highlighted in the raw answer.
  - accepted: `✅ Guard verdict: accepted. The model kept to the data: every figure in its answer was
    found in the cited rows or the alert data.`

  Verdicts are conveyed by the icon and the words, not by colour alone. The panel shall add a
  caption under the verdict: `The guard checks figures, dates and IBANs. It does not judge wording.`
  - Example (rejected): alert `A`, selected question `forecast`, fake answer
    `"In five years you will have paid 779.40 EUR. Source: bank.csv:0."` → raw block contains
    `<mark` around `779.40` and nothing else flagged; verdict line
    `🛑 Guard verdict: rejected. Not found in the cited rows or the alert data: \`779.40\``; the
    template block contains the filled template of `A`.
  - Example (accepted): fake answer
    `"The alert gives a yearly cost of 155,88 EUR. Source: bank.csv:0."` → no `<mark`; verdict line
    is the accepted text above.

- **REQ-LG-12** *If* the model does not answer (provider error, timeout, empty answer, missing
  `openai` package), *then* the panel shall show exactly
  `The model did not answer (error, empty answer or no reply within 10 seconds). The card keeps the fixed template. Nothing was counted as checked.`
  (the number is `LLM_TIMEOUT_SECONDS`), show the fixed template, and never show the exception text,
  the base URL or the key. `asked` still increases (REQ-LG-07); `checked` and `rejected` do not.
  - Example: fake client raises `RuntimeError("connect to http://localhost:11434 failed")` → the
    page text contains the sentence above and does not contain `localhost`.

- **REQ-LG-13** The panel shall show a per-app, per-session counter as one caption:
  `Answers checked: {checked} · rejected: {rejected}` (for example `Answers checked: 2 · rejected: 1`).
  It starts at `0` and `0`, is kept in `st.session_state[f"{prefix}_lg_counts"]` as a `Counts`, and is
  the same value in every card of the app. *When* `asked` has reached `LIVE_ASKS_PER_SESSION_LIMIT`,
  the Ask button shall be disabled and the caption
  `Limit of 30 questions per session reached. Reload the page to start again.` shall be shown.
  - Example: three presses answered accepted, rejected, error → counter reads
    `Answers checked: 2 · rejected: 1`.

- **REQ-LG-14** *While* `live_status(os.environ).enabled` is `False`, the expander shall still be
  drawn, the radio and the Ask button shall be **disabled**, `status.caption` shall be shown as one
  `st.caption`, and no model call shall be possible. The counter shows `Answers checked: 0 ·
  rejected: 0`. The sidebar switch *Simulate a hallucinating LLM* is not touched and remains the
  offline proof.
  - Example: `OPENAI_API_KEY` and `OPENAI_BASE_URL` unset → the button has `disabled == True`, the
    radio has `disabled == True`, and the page shows `CAPTION_OFF` once per card.
  - Example: `OPENAI_BASE_URL` set, `OPENAI_API_KEY` unset → same, with `CAPTION_URL_WITHOUT_KEY`.

- **REQ-LG-15** The panel shall not change what the rest of the page does. A probe shall not alter
  the card text, the guard badge, the alerts, or `st.session_state[EXPLANATIONS_KEY]`; the sidebar
  switch *Simulate a hallucinating LLM* shall not affect the panel (the panel always asks the
  configured real model, never the stub).
  - Example: switch on, press Ask → the call goes to the fake `openai` client, the card still shows
    the same rejected badge naming `99999.99` as before the press, and `EXPLANATIONS_KEY` has the same
    keys before and after the press.

- **REQ-LG-16** Provider settings shall be read from the process environment only
  (`OPENAI_API_KEY`, `OPENAI_BASE_URL`, `LEDGER_KIT_LLM_MODEL`). The panel shall not read
  `st.secrets`, offer an input for any of them, write any of them to `st.session_state`, a file or a
  log, or render the key or the base URL. It may render the model name (`status.model`) in the intro
  line. The new code shall add no logging; the explainer's existing warnings are unchanged. The rows
  sent with a question are the same whitelisted columns as for the card (never `id`, `description`
  or `iban`).
  - Example: with `OPENAI_API_KEY="test-key-not-real"` and `OPENAI_BASE_URL="http://base.invalid/v1"`,
    after a probe no element of the page and no `st.session_state` value contains either string, and
    a `caplog` capture at DEBUG level from the new modules is empty.

- **REQ-LG-17** `ledger_kit/live_guard.py` shall be imported by the apps through public names only;
  the apps shall not import each other; `ledger_kit` shall not import an app or Streamlit. The three
  prefixed session keys `*_lg_results` and `*_lg_counts` and the radio and button keys
  `{prefix}_lg_q_{alert.id}` and `{prefix}_lg_ask_{alert.id}` are disjoint across the three apps.
  Probe results and counters are plain session values and survive navigation in the showcase; the
  radio selection resets (it is a widget) and is **not** added to `WIDGET_KEYS`.

## 4 — Documentation

- **REQ-LG-18** The repository shall contain `docs/live-guard.md` with these sections, in order:
  *What this shows*, *Option A: a hosted model* (key only), *Option B: a local model with Ollama*,
  *What to expect*, *Limits*. Option B shall give the exact PowerShell commands for Windows:
  ```
  winget install Ollama.Ollama
  ollama pull llama3.2:1b
  ollama run llama3.2:1b "Say ready."
  .\.venv\Scripts\Activate.ps1
  $env:OPENAI_BASE_URL = "http://localhost:11434/v1"
  $env:OPENAI_API_KEY = "ollama"
  $env:LEDGER_KIT_LLM_MODEL = "llama3.2:1b"
  streamlit run streamlit_app.py
  ```
  followed by the same three variables for bash (`export`). `README.md` shall get one short paragraph
  under *How it works*, after "The proof is a switch.", linking to `docs/live-guard.md`.
  `.env.example` shall gain two commented placeholder lines (`OPENAI_BASE_URL`,
  `LEDGER_KIT_LLM_MODEL`) and keep its existing line.

- **REQ-LG-19** `docs/live-guard.md` and the README paragraph shall state, in plain words: that small
  local models invent figures more often than large hosted ones, so on a local model a rejection is
  the likely outcome and that is the point of the demo; that the guard checks **figures, dates and
  IBAN-shaped tokens only** and does not judge wording, so an accepted answer is not a statement that
  the answer is true or good advice; that the guard is strict by design, so a derived figure, a list
  number such as `1.` or a count such as `3 months` is rejected unless it is in the cited rows or the
  alert data; that the first call to a local model can exceed the 10-second limit, which shows as the
  REQ-LG-12 message, and how to warm the model up; and that the panel does not run on Community Cloud
  unless the deployer sets a key, and that doing so lets every visitor spend it.
  - Example: the text contains the substrings `small local models`, `does not judge wording`,
    `10 seconds` and `warm`.

## 5 — Non-functional

- **REQ-LG-20** No test, call site or document that exists today shall need a change other than the
  additions listed in `tasks.md`. No test shall use the network, a real model or a real key; fake
  clients and a fake `openai` module stand in. Tests are deterministic (no clock). `ruff check` and
  `ruff format --check` pass, the 80 % coverage floor holds, and the new modules are added to the
  coverage command of `testing.md` only if they sit outside `ledger_kit` or the three apps (they do
  not).
