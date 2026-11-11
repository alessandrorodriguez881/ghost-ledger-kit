# judge-path — Requirements

## Overview

An adversarial jury scored the kit and found one big gap: a judge who opens the public URL has no
API key, so the *Provoke the LLM* panel is off and the only proof left is the stub that always
answers `99999.99`, which looks staged. The pages also read like a developer tool: *Load demo data*
first, alias and date inputs in the sidebar, a Deploy button, a precision of `0.9980` as the first
figure of Home, and texts such as `3 time(s)`.

`judge-path` makes a **60-second path that works without a key**:

- a **replay** of a recorded real run (`data/live_runs/2026-11-11_llama3.2-3b_demo.json`): the
  recorded raw answers of a real model go through *today's* number guard, with no model and no
  network call, and every page says so;
- the demo **loads by itself** on the first run of a session;
- developer inputs sit in one collapsed **Advanced inputs** expander;
- the **Deploy button is gone** (`client.toolbarMode = "viewer"`);
- Home starts with **the story**, one **recorded example read from the run file**, a **Start here**
  link, and then the proof strip with **percentages**;
- fixed templates say `1 time` and `3 times`.

It changes no detector, no figure, no threshold, no number-guard rule, no widget key that exists
today and no line of the live call. One new module, `ledger_kit/replay.py`, is the only new code of
the library that touches the run file.

Ids are `REQ-JP-nn`. EARS keywords: *shall*, *when*, *while*, *where*, *if ... then*. All data in
examples is **(synthetic)** or a recorded answer of a real model on synthetic demo data.

## Shared vocabulary

- **Run file**: the JSON file at `REPLAY_RUN_PATH`. Fields used: top level `model`, `date`,
  `records`; per record `alert_id`, `raw_answer`, `kind` (`card` or `probe`), `question_id`,
  `question`. Fields of older files (`observed_source`, `observed_rejected`, `seconds`, ...) are
  ignored by the loader.
- **Recording**: one record that has a non-empty `raw_answer`.
- **Replay active**: no `OPENAI_API_KEY` is set, a valid run file is loaded and (for a card) the
  *Simulate a hallucinating LLM* switch is off.

---

## 1 — Library: `ledger_kit/replay.py`

- **REQ-JP-01** The system shall provide `ledger_kit/replay.py` with the constant
  `REPLAY_RUN_PATH` (a `pathlib.Path`, the only place the file name is written) and
  `load_run(path=None)`; `path=None` shall read the constant **at call time**, so a test can patch it.
  - Example: `REPLAY_RUN_PATH.name == "2026-11-11_llama3.2-3b_demo.json"`.
  - Example: `load_run(fixture)` on a small fixture file → a run whose `model_name` is
    `llama3.2:3b` (the model text up to the first ` (`) and whose `date` is `2026-11-11`.

- **REQ-JP-02** *If* the run file is missing, unreadable, not JSON, not an object, has no `records`
  list, or has no non-empty `model` or no ISO `date`, *then* `load_run` shall return `None` and
  shall not raise, and every page shall behave exactly as it does today, with no message. *If* a
  single record is malformed (not an object, no `alert_id`, empty `raw_answer`, a probe whose
  question cannot be resolved), *then* only that record shall be skipped.
  - Example: a file with the text `not json` → `None`. A file with `"records": []` → a run with no
    recording. A file whose second record has `raw_answer: ""` → one recording.

- **REQ-JP-03** The run shall return the recorded raw answer **for an alert id** (a card) or **for
  an alert id and a question id** (a probe) through `recorded_answer(alert_id, question_id=None)`,
  and the whole `Recording` through `card_recording` and `probe_recording`. A record is a probe when
  its `kind` is `probe`, or when it has no `kind` and has a question; a record with no question
  is a card (older files have no `kind`). A probe's question id is `question_id`, else the id of the
  preset question whose id or text equals `question`. The first record for a key wins.
  - Example: record `{alert_id: "a1", question_id: null, question: null, raw_answer: "T"}` →
    `recorded_answer("a1") == "T"` and `recorded_answer("a1", "forecast") is None`.
  - Example: record `{alert_id: "a1", kind: "probe", question_id: "forecast", raw_answer: "P"}` →
    `recorded_answer("a1", "forecast") == "P"` and `recorded_answer("a1") is None`.
  - Example: on `2026-11-10_llama3.2-3b.json` the card of alert
    `896d26e24ef956ad447d2c6e871526b92856a6eb6c67bc2f6649e757399fb6c0` has a recording.

- **REQ-JP-04** *When* a recording is replayed, the system shall hand its text to the existing
  `explain_with_meta` (or the app's own wrapper of it) through `ReplayClient`, an OpenAI-shaped
  client whose `chat.completions.create` returns that text. The verdict shall therefore be
  **today's** number guard on the recorded text; the verdict stored in the file (`observed_*`) shall
  never be read for a verdict. `ReplayClient` shall open no connection, import no SDK and record each
  request in `calls`.
  - Example: the 2026-11-10 record `Z1` was stored as rejected for the row numbers
    `181, 236, 292`; replayed now it is accepted (`source == "llm"`, `rejected_numbers == ()`).
  - Example: with `sys.modules["openai"] = None` and `socket.socket` patched to raise, a replay
    still returns its verdict and `ReplayClient.calls` holds exactly one request.

## 2 — Alert cards without a key

- **REQ-JP-05** *While* replay is active and an alert has a recorded **card** answer, the card shall
  show that answer if the number guard accepts it now, else the fixed template filled from the alert,
  exactly as today. *While* an alert has no recorded card answer, its card shall be today's card.
  - Example: alert `GYMPLUS` (charge after cancellation) with a recorded answer that cites only
    figures of its rows → the card text is the recorded answer. Same alert with a recording that
    states `99999.99` → the card text is the fixed template.

- **REQ-JP-06** *While* a key is set, the cards and the panel shall call the model exactly as
  today and shall never replay. *While* *Simulate a hallucinating LLM* is on, the stub shall answer
  exactly as today and win over the replay.
  - Example: `OPENAI_API_KEY` set + fake `openai` → the fake receives the request and the card shows
    today's `LLM` badge. Switch on → every badge names `99999.99`.

- **REQ-JP-07** The badge of a replayed card shall say plainly that the text is a **recorded answer**
  of the **named model** on the **recorded date**, **checked now by the number guard**, and that
  **no model was called**; it shall say whether the guard accepted the answer, and when it rejected
  it, name the rejected tokens and say that the fixed template is shown. It shall never use the
  words of the live badges (`LLM text verified`, `LLM answer rejected`).
  - Example (accepted): `📼 Recorded answer of llama3.2:3b, 2026-11-11, checked now by the number
    guard: accepted. No model called.`
  - Example (rejected): `📼 Recorded answer of llama3.2:3b, 2026-11-11, checked now by the number
    guard: rejected (invented number 99999.99). Fixed template shown. No model called.`

## 3 — The Provoke panel without a key

- **REQ-JP-08** *While* no key is set and an alert and question have a recorded **probe**, the panel
  shall be enabled for that question, and pressing *Ask the model* shall show, under a caption that
  says it is a replay of a recorded answer of the named model and that no model is called, the
  recorded raw answer with the rejected tokens marked, today's guard verdict, and the fixed template.
  The intro line shall name the recorded model and say that no model is called.
  - Example: recorded probe `forecast` for alert `A`, answer `"Over five years you will pay
    779.40 EUR."` → after the press the panel shows that text with `779.40` marked, the line
    `Guard verdict: rejected. Not found in the cited rows or the alert data: 779.40`, and the caption
    `Replay of a recorded answer of llama3.2:3b, 2026-11-11. No model is called ...`.

- **REQ-JP-09** *While* no key is set and an alert and question have **no** recorded probe, the
  question button shall stay disabled with today's caption (`CAPTION_OFF` or
  `CAPTION_URL_WITHOUT_KEY`). *While* the alert has no recorded probe at all, the whole panel shall
  look as it does today.

- **REQ-JP-10** A replayed press shall count like a live press: it shall add one to *asked* and to
  *checked*, add one to *rejected* when the guard rejects, and be refused after
  `LIVE_ASKS_PER_SESSION_LIMIT` presses with `MSG_LIMIT`.
  - Example: three replayed presses, one rejected → `Answers checked: 3 · rejected: 1`.

## 4 — The demo loads by itself

- **REQ-JP-11** *When* the first run of a session finds nothing loaded (no source in the session
  state), each app shall load its **CSV** demo exactly as the *Load demo data* button does, once per
  session; the button shall stay and shall work as today. A later run, a visit to another page, an
  upload or an already loaded source shall never trigger it again.
  - Example: a fresh `AppTest` of the zombie app → three tombstones, nineteen alerts, the three text
    areas filled, `at.session_state["zs_autoloaded"] is True`, and no info box asking to click.
  - Example: `at.session_state["source"]` preset before the first run → that source is kept.

## 5 — Developer inputs in one expander

- **REQ-JP-12** Each app shall draw its developer inputs inside one collapsed sidebar expander titled
  `Advanced inputs`, with the same widget keys as today: zombie `aliases_text`, `last_used_text`,
  `cancel_text`; phantom `use_as_of`, `as_of_date`; vampire the fee vocabulary list (its own
  expander is folded into this one, because Streamlit does not nest expanders). The demo-format
  radio, *Load demo data*, the hallucination switch and the uploader stay outside it.
  - Example: `at.sidebar.expander[0].label == "Advanced inputs"` and `at.text_area(key="aliases_text")`
    is a child of that expander.

## 6 — No Deploy button

- **REQ-JP-13** `.streamlit/config.toml` shall hold `[client]` with `toolbarMode = "viewer"` next
  to `[theme]`, and its comment shall say that client settings are neither credentials nor server
  settings.

## 7 — Home

- **REQ-JP-14** Home shall show, in this order: the title, the promise, **the story** (two or three
  short lines: bank statements and invoices hide money leaks; a language model can explain them but
  makes up numbers; here rules find every figure and a guard throws out any figure the model
  invents), **one recorded example**, a **Start here** link to Zombie Subscriptions, and then the
  proof strip. The story and the example shall not add a `gl-section` heading.
- **REQ-JP-15** The example shall be read from the run file, not typed: the first **probe** record
  whose answer the guard rejected and that has an answer, with its question text, the invented
  figure (the first rejected token that holds a digit, else the first token) and the word
  `rejected`, labelled as one recorded answer of the named model on the recorded date. (Amended by
  REQ-JP-21: the figure rule and the wording of the example changed.) *If* the file
  is missing, invalid or has no such record, *then* Home shall omit the example and keep the rest.
  - Example: record `{kind: probe, question_id: forecast, observed_rejected: ["779.40"], ...}` →
    `You asked: ... — it answered with 779.40 — rejected.` and the label
    `One recorded answer of llama3.2:3b, 2026-11-11.`
- **REQ-JP-16** The proof strip shall write precision and recall as percentages with one decimal and
  a space before `%`, rounded half up from the committed ratio text: `0.9980` → `99.8 %`,
  `1.0000` → `100.0 %`. A `null` ratio stays `n/a`.

## 8 — Plurals

- **REQ-JP-17** A fixed template that states a count shall write `1 time` and `3 times`, never
  `time(s)`. The zombie template `zs.charges_after_cancellation` shall use the format spec `:times`
  of the explainer's template formatter.
  - Example: `post_cancellation_count = 1` → `GYMPLUS charged you 1 time totalling ...`;
    `3` → `charged you 3 times totalling ...`.

## 9 — Honesty and non-regression

- **REQ-JP-18** Nothing on a page shall suggest that a model is being called when it is not: the
  replay badge, the panel intro and the panel caption name the recording, its model and its date
  and say that no model is called.
- **REQ-JP-19** The change shall add no dependency, change no detector, figure, number-guard rule,
  existing widget key or line of the live call, and every existing test shall stay green except the
  tests that pin the strings and shapes the requirements above change (listed in `tasks.md`).

## 10 — Amendment 17c (small fixes after the first browser run)

- **REQ-JP-20** *While* replay is active for an alert (no key set and the alert has a recorded
  probe), the button of the Provoke panel shall read `Replay the recorded answer`; *while* a key
  is set, or the alert has no recorded probe, it shall read `Ask the model`. Widget keys and the
  disabled rules do not change.
- **REQ-JP-21** The Home example shall name the invented figure by this rule: among the stored
  rejected tokens, the first that is a **money amount** (ends in a decimal part of one or two
  digits, such as `539.40` or `1.349,40`), else the **longest** token (the first of equal length).
  It shall show the **sentence of the recorded answer** that contains the figure, with the figure
  marked, and the line `Question: ...` (not `You asked:`), because the visitor asked nothing.
  - Example: stored tokens `5`, `539.40` and the answer `Over five years you will pay 5 x 107.88 =
    539.40 EUR. Cancel it.` → figure `539.40`; the sentence shown is the first one, with `539.40`
    marked.
  - Example: stored tokens `5`, `$`, `2030` and no money amount → figure `2030` (the longest).
- **REQ-JP-22** A rejected token is not always a number (a currency sign, a word). The rejected
  badges and verdict lines of cards and of the replay shall therefore not say `invented number`;
  they shall say `not found in the cited rows or the alert data: <tokens>`, the wording of the
  panel verdict, for live and replayed answers alike.
  - Example (card, live): `⚠️ LLM answer rejected: not found in the cited rows or the alert data:
    99999.99`.
  - Example (replay): `... rejected (not found in the cited rows or the alert data: 98765.43).
    Fixed template shown. No model called.`
- **REQ-JP-23** The *Start here* entry on Home shall be a page link to Zombie Subscriptions with
  the tombstone icon, drawn at body text size (1 rem), underlined, inside a bordered box in the
  accent colour; not a small caption.
