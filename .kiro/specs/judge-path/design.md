# judge-path — Design

Section references (§) are used by `tasks.md`; REQ ids are in `requirements.md`.

## 1 — Overview

```
data/live_runs/2026-11-11_llama3.2-3b_demo.json        (recorded by hand, never edited by code)
        │ load_run()  – cached by (path, mtime, size); None when missing or invalid
        ▼
ledger_kit/replay.py ──► Recording(raw_answer, kind, question_id, model_name, date)
        │                 ReplayClient(text)  – OpenAI-shaped, no network, keeps .calls
        ▼
app._explain / app._ask_model ──► explain_with_meta(..., client=ReplayClient(text))
        │                                   (unchanged explainer = TODAY'S number guard)
        ▼
card text / probe result  +  badge and caption written by replay.py (name model and date)
```

Nothing in `ledger_kit/explainer.py` changes except one new template format spec (§7). The guard
never learns that a text is a replay.

## 2 — `ledger_kit/replay.py` (DN-JP-01 to DN-JP-04)

```python
REPLAY_RUN_PATH: Path = ROOT / "data" / "live_runs" / "2026-11-11_llama3.2-3b_demo.json"

@dataclass(frozen=True)
class Recording:  alert_id, kind ("card"|"probe"), question_id | None, raw_answer, observed_rejected
@dataclass(frozen=True)
class ReplayRun:  model, model_name, date, cards: Mapping[str, Recording],
                  probes: Mapping[tuple[str, str], Recording]
                  .card(alert_id) / .probe(alert_id, question_id) / .has_probe(alert_id)
                  .first_rejected_probe() -> Recording | None

def load_run(path: Path | None = None) -> ReplayRun | None
def recorded_answer(alert_id, question_id=None, *, path=None) -> str | None
def card_recording(alert_id, *, path=None) -> Recording | None
def probe_recording(alert_id, question_id, *, path=None) -> Recording | None

class ReplayClient:  chat / completions properties, create(**kwargs) -> response; .calls

def card_badge(run, explanation) -> tuple[str, str]      # (css kind, label)
def panel_intro(run) -> str
def panel_caption(run) -> str
```

- **DN-JP-01 Path read at call time.** `load_run(None)` reads the module global, so the shared test
  fixture (§8) can patch it. The parse is cached by `(str(path), mtime_ns, size)` in an
  `lru_cache`, so a rerun of a page does not read the file again and a changed file is picked up.
- **DN-JP-02 Kind and question resolution.** `kind` wins; without `kind` a record with a falsy
  `question` is a card and any other is a probe. A probe's question id is `question_id`, else the
  preset question whose `id` or `text` equals `question` (the 2026-11-10 files hold the text).
  Unresolvable probes are skipped. `ledger_kit.replay` imports `TRICK_QUESTIONS` from
  `live_guard` and `explain` nothing; it imports no Streamlit and no app.
- **DN-JP-03 Re-check by construction.** The apps pass `ReplayClient(recording.raw_answer)` as the
  `client` of the call they already make (`explain_with_meta`, or `explain_alert` for phantom).
  `explain_with_meta` runs `_call_llm` with that client and then `_passes_number_guard`: the same
  path a live answer takes. `observed_source` and `observed_rejected` are never read for a verdict.
- **DN-JP-04 Model name.** `model_name = model.split(" (", 1)[0].strip()` (`llama3.2:3b`); the full
  text stays in `ReplayRun.model`. Badges and captions use the short name and the date.

### Honest texts

| Where | Text |
|---|---|
| Card badge, accepted | `📼 Recorded answer of {model}, {date}, checked now by the number guard: accepted. No model called.` |
| Card badge, rejected | `📼 Recorded answer of {model}, {date}, checked now by the number guard: rejected (invented number {tokens}). Fixed template shown. No model called.` |
| Panel intro | `Three questions that tempt a model to state a figure that is not in the cited rows. Recorded answers of {model}, {date}: no model is called.` |
| Panel caption | `Replay of a recorded answer of {model}, {date}. No model is called: the guard verdict below is today's number guard on that recorded text.` |

The badge css kind is `llm` when accepted and `rejected` when rejected, so the three apps reuse the
colours they already have; only the label differs.

## 3 — Cards (§ apps, DN-JP-05)

```python
def _card_recording(alert, hallucinate):          # same shape in the three apps
    if hallucinate or os.environ.get("OPENAI_API_KEY", ""):
        return None
    return replay.card_recording(alert.id)
```

`_explain` keeps its signature and its cache. The cache key is `(alert.id, mode)` where `mode` is
`"hallucinate"`, `"replay"` (a card recording exists and replay is active) or `"real"`. With no
recording the call is the one made today. `_render_alert` asks `_card_recording` again to choose the
badge; the explanation itself comes from the cache.

## 4 — The panel (DN-JP-06)

```python
status = live_status(os.environ)
run = None if status.enabled else replay.load_run()
replayable = run is not None and run.has_probe(alert.id)
recorded = None if run is None else run.probe(alert.id, question.id)
```

- radio `disabled = not (status.enabled or replayable)`; the button
  `disabled = not ((status.enabled or recorded is not None) and counts.asked < LIMIT)`.
- intro: `panel_intro(run)` when `replayable` and no key, else today's `intro_line`.
- order under the button: replay caption (if `recorded`), the stored result, then today's
  `status.caption` only when there is neither a key nor a recording.
- `_ask_model` re-reads the environment: no key + recording → `client=ReplayClient(text)`; else
  `client=None`, which is today's call. `probe_result` and `tally` are unchanged, so the counter
  treats a replay like a live press.

## 5 — First run (DN-JP-07)

`ledger_kit/ui/first_run.py` (pure) holds `AUTOLOAD_DEMO: bool = True` and
`should_autoload(state, done_key, has_source)`. Each app, right after `_init_state()` and before any
widget is drawn:

```python
def _autoload_demo() -> None:
    if not first_run.should_autoload(st.session_state, AUTOLOAD_KEY, bool(st.session_state.get(SOURCE))):
        return
    apply_demo(st.session_state, demo_inputs(config, ROOT, "csv"))
```

`should_autoload` sets `done_key` and answers `AUTOLOAD_DEMO and not has_source`. Widget keys may be
written before their widget exists; the button's `on_click` stays. `AUTOLOAD_KEY` is a plain
prefixed session key (`zs_autoloaded`, `pi_autoloaded`, `vf_autoloaded`), not a widget key, so it
survives a visit to another page. `apply_demo` is untouched (its state keys are pinned by tests).

## 6 — Advanced inputs, toolbar, Home

- Sidebar: `with st.expander("Advanced inputs", expanded=False):` around the text areas (zombie),
  the as-of checkbox and date input (phantom: `st.sidebar.*` calls become `st.*` calls inside
  `with st.sidebar:`), and the vocabulary caption and list (vampire; the old expander is removed
  because expanders do not nest). Keys and `help` texts are unchanged.
- `.streamlit/config.toml` gets `[client] toolbarMode = "viewer"`.
- Home (`streamlit_app.home`): title, `gl-promise`, `STORY` (three lines, one markdown block of
  `<div class="gl-story">` paragraphs), `landing.example_html(run)`, the `st.page_link` to
  Zombie Subscriptions (labelled *Start here: Zombie Subscriptions*), then the sections as today.
  `landing.py` gets `percent_text`, so the proof facts print `99.8 %`; `streamlit_app.py` still
  imports no app.
- **DN-JP-08 The example's verdict.** The entry page and `ledger_kit` may not import an app
  (`test_the_entry_page_imports_neither_app`, package boundaries), and the guard needs the alert
  and its rows, which only an app can rebuild. So Home reads the verdict the file stores
  (`observed_source == "fallback"`, non-empty `observed_rejected`, non-empty answer) and
  `tests/test_judge_path_replay.py` pins, with the apps' own pipelines, that **today's guard rejects
  the chosen record with the same token**. If the guard changes, that test fails before Home can
  show a stale example. This is the one place where the file's stored verdict is read, and it is
  never shown as a live result: the label says *one recorded answer*.

## 7 — Plurals

`ledger_kit/explainer._FORMAT_SPECS` gains `"times": format_times`, which prints `1 time` and
`3 times` for an integral count and leaves any other value as text. The number guard is not
touched; the template is the fixed fallback, which the guard does not check. The zombie template
becomes `{counterparty} charged you {post_cancellation_count:times} totalling ...`.

## 8 — Tests and isolation (DN-JP-09)

The root `conftest.py` has an autouse fixture that points `replay.REPLAY_RUN_PATH` at a missing file
and sets `first_run.AUTOLOAD_DEMO = False`. Every existing test therefore runs on today's pages. The
new tests use the fixture `judge_path` (`tests/judge_path_fixtures.py`) to turn one or both on, with a
small run file built in `tmp_path` from the real alert ids of the demo pipelines, or with the
committed file.

| File | Covers |
|---|---|
| `tests/test_judge_path_replay.py` | REQ-JP-01 to 04, 15 (loader, re-check, no network, Home example pinned) |
| `tests/test_judge_path_pages.py` | REQ-JP-05 to 14 (AppTest of the three apps and Home) |
| `tests/test_judge_path_misc.py` | REQ-JP-13, 16, 17 (config, percentages, plurals) |

## 8b — README images (REQ-JP-29)

*The three apps* in `README.md` shows one GIF under each app bullet, written as a markdown image
(indented two spaces so it stays inside the list item). The GIFs are files of `docs/img/`, recorded
by hand from the local apps and never edited by code. `tests/test_readme.py` allows exactly four
images (the Home moment and the three GIFs), checks that each file exists and is under 2 MB, and
still refuses an `img` tag and a badge.

## 8c — Gate-2 honesty fixes (REQ-JP-30, session s51)

Words only, plus one caption. `DEMO_FORMAT_CAPTION` lives in `ledger_kit/ui/first_run.py`, the
module of the demo that loads by itself, because the caption is about the same thing: what loads
and when. Each app draws it with `st.caption` right after the *Demo format* radio and before the
*Load demo data* button; no widget key, state key or callback changes. The size sentence of the
README counts physical lines (`str.splitlines`) of the `.py` files; the core is `models.py`,
`detectors/` (`base.py`, `registry.py`, `__init__.py`), `explainer.py` and the guard helpers it
imports (`calc.py`, `number_words.py`, `index_cause.py`) plus `utils/money.py`, which the guard
uses to format amounts. The Spanish format readers are `norma43_reader.py`, `facturae_reader.py`
and `iso4217.py`; the plain CSV readers stay in *the rest*. `tests/test_judge_path_gate2.py` reads
each figure back from the README sentence, recounts the files and allows 10 percent either way, so
the sentence goes stale only with a failing test.

## 9 — Risks

- The run file is being recorded while this change is built. Tests that need a specific record use
  fixture files; only two tests read the committed file, and they skip the checks that need records
  the file does not have yet.
- `st.page_link` inside `st.navigation` needs the page to be registered; the call is guarded so a
  failure shows a plain sentence, never an exception.
