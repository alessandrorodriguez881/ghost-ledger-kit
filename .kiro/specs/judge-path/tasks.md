# judge-path — Implementation Tasks

Every task is test-first: write the tests, see them fail for the right reason, then implement.
Section references (§) point to `design.md`, REQ ids to `requirements.md`. Verification
(`ruff check .`, `ruff format --check .`, `pytest`, and a look at every page in a browser with no key
set) is run by the user: this session could not run commands. Tasks run in order.

## Task JP1 — Isolation: the root `conftest.py`

**Covers**: REQ-JP-19, §8

- [x] Create `conftest.py` at the repository root: an autouse fixture that points
  `ledger_kit.replay.REPLAY_RUN_PATH` at a file that does not exist and sets
  `ledger_kit.ui.first_run.AUTOLOAD_DEMO = False`, so every test written before this spec starts
  from the page it was written for.

## Task JP2 — Library: `ledger_kit/replay.py`

**Covers**: REQ-JP-01 to REQ-JP-04, REQ-JP-07, REQ-JP-08, REQ-JP-18, §2

- [x] Create `tests/judge_path_support.py` (real alert ids from the three demo pipelines, a small
  run file written to `tmp_path`) and `tests/test_judge_path_replay.py`. Tier 1: the constant;
  `load_run` on the fixture and on the three 2026-11-10 files; card and probe lookup; older records
  without `kind`; the re-check (Z1 of 2026-11-10 was stored as rejected for `181, 236, 292` and is
  accepted now; a recording stored as accepted but holding an invented figure is rejected now);
  badge, intro and caption texts. Tier 2: missing file, folder, binary garbage, ten unusable
  documents, malformed records skipped, empty `records`, a changed file read again, the committed
  file's alert ids all raised by the demo, the Home example pinned against today's guard (§6,
  DN-JP-08). Tier 3 (Hypothesis, `max_examples=200`): the client returns exactly the recorded text;
  an invented figure inserted into any recording is rejected and never reaches the text; an
  unrecorded alert has no answer. No network: the SDK made unimportable, one request recorded.
- [x] Implement `ledger_kit/replay.py` (§2). Stdlib plus `explainer` and `live_guard`; no Streamlit,
  no app.

## Task JP3 — Plurals

**Covers**: REQ-JP-17, §7

- [x] Create `tests/test_judge_path_misc.py` (plurals part): `1 time` / `3 times` through
  `fill_fallback`, `format_times` for 0, 1, 2, 12 and non-whole counts, a non-number left as text,
  no `(s)` in any fixed template of the three apps, a Hypothesis property over counts.
- [x] Add `format_times` and the `times` spec to `ledger_kit/explainer.py` (`_FORMAT_SPECS` only;
  the guard is untouched); use it in the zombie template `zs.charges_after_cancellation`; update the
  template in the zombie-subscriptions requirements.

## Task JP4 — First run and Advanced inputs

**Covers**: REQ-JP-11, REQ-JP-12, §5, §6

- [x] Pure part in `tests/test_judge_path_misc.py`: `should_autoload` fires once, never over a
  loaded source, marks the session in every case, the switch is off in tests and on in the source.
  Page part in `tests/test_judge_path_pages.py`: a fresh `AppTest` of each app shows the demo, fills
  the zombie inputs, keeps the button, does not reload on a later run, respects a marked session
  and a preset source; each app has one `Advanced inputs` sidebar expander (collapsed, checked on the
  source) holding exactly the developer inputs, with the same widget keys.
- [x] Add `ledger_kit/ui/first_run.py`; in each app `AUTOLOAD_KEY`, `_autoload_demo()` after
  `_init_state()`, and the `Advanced inputs` expander (zombie: three text areas; phantom: as-of
  checkbox and date; vampire: the vocabulary list, its own expander folded in).

## Task JP5 — Cards and panel with replay

**Covers**: REQ-JP-05 to REQ-JP-10, REQ-JP-18, §3, §4

- [x] In `tests/test_judge_path_pages.py` (parametrised over the three apps): recorded cards show
  the accepted answer and the template for the rejected one, with the badge that names the model and
  the date and says no model was called; the other cards are today's template cards; the
  hallucination switch wins and the replay comes back when it is off; with a key set every card is a
  live call (fake `openai`) and nothing is replayed; an unusable run file leaves the page as it was;
  the panel replays a recorded probe with the token marked, today's verdict, the caption and the
  counter; `next_month` is accepted; `with_fees` and alerts without probes stay disabled with
  today's caption; the session cap; no SDK and no `urlopen`, one request per replay.
- [x] In each app: `_card_recording`, `_explain` mode `replay`, the badge from `replay.card_badge`,
  `_ask_model` with `ReplayClient` when no key is set, and the panel (§4).

## Task JP6 — Toolbar, Home, percentages

**Covers**: REQ-JP-13 to REQ-JP-16, §6

- [x] Tests: `.streamlit/config.toml` has `[client] toolbarMode = "viewer"` and the comment
  (`test_showcase_theme.py`, `test_judge_path_misc.py`); Home order title, promise, story, example,
  link, proof strip; the example from the test run file with its question, figure and the word
  rejected; Home without a run file; percentages in the strip (`test_judge_path_pages.py`,
  `test_judge_path_misc.py`).
- [x] Config; `landing.percent_text`, `landing.story_html`, `landing.example_html`; the Home page
  (`STORY`, example, `st.page_link`, no new section heading); the CSS of `gl-story` and
  `gl-example`; the Home texts that said fixed templates only now say what a card shows.

## Task JP7 — Existing tests that pin changed strings

**Covers**: REQ-JP-19

- [x] `tests/test_ui_landing.py` and `tests/test_ui_pages.py`: precision and recall are percentages.
- [x] `tests/test_showcase_theme.py`: the config holds `theme` and `client`.
- [x] `tests/test_showcase_app.py`: the Home word budget 500 → 650 for the story, the example and
  the link.
- [x] No other existing test was edited; the root `conftest.py` keeps them on their old starting
  point.

## Open for the user to run

- [ ] `ruff check .` and `ruff format --check .`
- [ ] `pytest` (the pages tests are slow: three apps, nineteen alerts in the largest)
- [ ] Look at every page in a browser with no key: Home (story, example, Start here, 99.8 %), each
  app (demo loaded, `Advanced inputs`, recorded badges, the Provoke panel replaying), no Deploy
  button.
