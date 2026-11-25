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

## Task JP8 — Amendment 17c: small fixes

**Covers**: REQ-JP-20 to REQ-JP-23, REQ-JP-15 (amended)

- [x] Tests first: `tests/test_judge_path_replay.py` (money token, longest token, sentence of the
  token, replay badge wording), `tests/test_judge_path_pages.py` (`Replay the recorded answer` with
  replay, `Ask the model` with a key and for an alert without a probe; the Home example with
  `Question:`, the marked sentence and no `You asked`; the Start here icon and CSS size).
- [x] Update only the tests that pinned `invented number`: `test_pi_explain_support.py`,
  `test_vf_app_logic.py`, `test_vf_settings.py`, `test_zs_app.py`, `test_judge_path_replay.py`.
- [x] `replay.Recording.invented_token` / `sentence_with`; `landing.example_html`;
  `live_guard.REPLAY_ASK_LABEL`, `ask_label`, `MARK_STYLE`; the three apps' button label; the three
  `BADGE_REJECTED` constants and `replay.card_badge`; `START_HERE_ICON` and the page-link CSS.

## Task JP9 — Session 30a: statements that match the app, reasons in words

**Covers**: REQ-JP-24 to REQ-JP-28

- [x] Tests first, `tests/test_judge_path_honesty.py`: the Home *Try it* text and the README
  (panel replays only on the first critical card of each app, step 1 and step 5, the formula as the
  app writes it, the amendment, the 10 Nov / 16 Nov clause; the committed run records the three
  questions on exactly three cards; some demo alerts have no Exorcise draft and most have one);
  the reason in words of every rejected-calculation case and of a dollar sign on a euro account;
  the replay badge and the verdict use them; one line per distinct calculation (and none printed
  twice for the committed run); replays never consume the limit. In
  `tests/test_judge_path_pages.py` the test of the session limit now says a replay is counted and
  never refused, and a preset of 30 live calls still is.
- [x] `ledger_kit/calc.py`: `_Reject.why`, `CalcOutcome.reasons`, the sentences `WHY_*`.
  `ledger_kit/explainer.py`: `Explanation.rejected_why` (compare off), `is_currency_token`, the
  currency sentences. `ledger_kit/live_guard.py`: `ProbeResult.why`, `rejection_clause`,
  `computed_lines` without repeats, `Counts.replayed` / `live_asked`, `limit_reached`, the counter
  label. `ledger_kit/replay.py`: `card_badge` through `rejection_clause`. The three apps: the
  button and the limit message use `limit_reached`, `tally(..., replayed=...)`.
- [x] `README.md` and `streamlit_app.py` (`TRY_IT`) reworded.
- [x] Session 30b, the four tests that pinned texts or counts 30a changed on purpose, updated:
  `test_explainer_calc.py` (the rejected-calculation verdict ends with `. Why: ...`),
  `test_home_example.py` (README step 1), `test_replay_calc2.py` (the computed-by-the-kit line is
  shown once), `test_showcase_app.py` kept at 650 words: `TRY_IT` shortened (below 650 words), still
  saying that every card replays a recorded answer and that the panel replays only on the first
  critical card of each app.
- [ ] Open for the user to run: `ruff check .`, `ruff format --check .`, `pytest`. The card badge
  of a live answer (`guard_badge` in each app's `settings.py`, shown only with a key) was not
  changed.

## Task JP10 — One GIF per app in the README

**Covers**: REQ-JP-29, §8b

- [x] `tests/test_readme.py`: the test that allowed only the home moment is now
  `test_exactly_four_images_the_home_moment_and_one_gif_per_app_and_no_badge`.
- [x] `README.md`, *The three apps*: one GIF under each app bullet. `.kiro/steering/structure.md`
  lists the three GIFs next to `home_moment.gif`.

## Task JP11 — Session s51: honesty and documentation fixes of the gate-2 review (25 Nov)

**Covers**: REQ-JP-30, §8c

- [x] Tests first, `tests/test_judge_path_gate2.py`: the README size figures against a recount of
  `ledger_kit/` (10 percent either way) and the files the sentence names; every mention of the six
  calls says first version, none says the agent built the whole app; the Kiro line of *Who did
  what* names `kiro_prompts/` and the four GIFs; `DEMO_FORMAT_CAPTION` sits between the *Demo
  format* radio and the *Load demo data* button in the three apps; README step 3; the
  `docs/developing.md` layout lines; the fee snapshot sentence; the `streamlit_app.py` docstring;
  the scan keys of `docs/developing.md` against the real output of `scripts/ledger_scan.py`.
- [x] `ledger_kit/ui/first_run.py`: `DEMO_FORMAT_CAPTION`. The three `app.py` files: one
  `st.caption` under the selector. No widget key, state key or callback changed.
- [x] Words: `README.md` (glance row, *The three apps* with the size sentence, the Custom agent and
  Spec-driven rows, step 3, the Kiro line, the Banco de España sentence), `docs/how-it-works.md`
  (Template proof), `docs/developing.md` (scan keys, `data/public/` and `docs/` lines),
  `streamlit_app.py` (docstring and the `PageSpec` comment).
- [x] Updated on purpose: `tests/test_public_data_docs.py` (`FEE_SENTENCE`, the README sentence
  on the committed fee snapshot).
- [x] Not touched: `data/live_runs/`, any recorded run, any detector, figure or guard rule.

Record of session s51 (25 Nov): one Kiro IDE session. Line counts of `ledger_kit/` at the time
(physical lines of `.py` files): core 2,483 (`models.py` 175, `detectors/` 164, `explainer.py`
1,081, `calc.py` 478, `number_words.py` 336, `index_cause.py` 70, `utils/money.py` 179), Spanish
format readers 1,074, `public_data/` 762, `ui/` 2,266, the rest 1,835; 8,420 in all. The shell of
this session could not run commands, so `ruff` and `pytest` were not run here; they are in the
list below.

Record of session s51b (25 Nov, follow-up to s51):
`test_no_document_says_the_agent_built_the_whole_app` failed on the README row *Spec-driven
versus vibe coding*, which rightly says *The first version of Vampire Fees was built by the
custom agent*. The test now checks the meaning instead of the
substring: the helper `_unqualified` finds each of the three claims (`which built the Vampire Fees
app`, `It built the Vampire Fees app`, `Vampire Fees was built by the custom agent`) and allows one
only when `first version of ` comes right before it; the check that `normal Kiro sessions` is
present is unchanged. A new test, `test_the_whole_app_claim_check_reads_the_qualifier`, pins that
the qualified phrase passes and the bare phrase, or a `first version` elsewhere in the text, still
fails. `README.md` was not changed. The shell of this session could not run commands either, so
`ruff` and `pytest` were not run here.

## Open for the user to run

- [ ] `ruff check .` and `ruff format --check .`
- [ ] `pytest` (the pages tests are slow: three apps, nineteen alerts in the largest)
- [ ] Look at every page in a browser with no key: Home (story, example, Start here, 99.8 %), each
  app (demo loaded, `Advanced inputs`, recorded badges, the Provoke panel replaying), no Deploy
  button.
