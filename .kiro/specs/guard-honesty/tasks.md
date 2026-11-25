# guard-honesty — Implementation Tasks

Every task is test-first: write the tests, see them fail for the right reason, then implement.
Section references (§) point to `design.md`, REQ ids to `requirements.md`. Verification
(`ruff check .`, `ruff format --check .`, `pytest`) is run by the user: session 21a could not run
commands. Existing test files are not edited. Tasks run in order.

## Part 1 — session 21a

### Task GH1 — The parser: `ledger_kit/number_words.py`

**Covers**: REQ-GH-01 to REQ-GH-05, §2

- [x] Create `tests/test_number_words.py`. Tier 1: English and Spanish phrases of AE-GH-02 and
  AE-GH-03. Tier 2: joins (`five and six`, `el cinco`, commas, line breaks), `and`/`y` never start
  or end a phrase, offsets, `word_count`, ordinals, `one-off`, whole words, empty text. Tier 3
  (Hypothesis, `max_examples=200`): every integer from 0 to 999999 spelled by a small speller of
  the test parses back as one phrase of that value (hyphen or space, with or without `and`).
- [x] Implement `ledger_kit/number_words.py` (§2), standard library only.

### Task GH2 — The guard reads number words

**Covers**: REQ-GH-06 to REQ-GH-11, REQ-GH-13, §3

- [x] Create `tests/test_guard_number_words.py` through `check_figures` on real demo cases
  (GYMPLUS = `find_case(Z1_ALERT_ID)`; the zombie alert titled `Duplicate subscription: MUSICBOX`):
  the rejected and accepted texts of AE-GH-06 to AE-GH-11, the order of mixed tokens, a number
  phrase in a row, the documented limit named as such, and every Exorcise draft of the three demos
  in both languages (helpers reused from `test_exorcise_demos.py`, not edited).
- [x] In `ledger_kit/explainer.py`: constants, `_checked_phrases`, `_beside_money`,
  `_in_text_order`; `_passes_number_guard` and `_allowed_decimals` (§3). No other rule changes.

### Task GH3 — Highlight

**Covers**: REQ-GH-12, §4

- [x] Highlight tests in `tests/test_guard_number_words.py`: one flagged segment for a rejected
  phrase; `once` does not flag `concession`; `once` flags the whole word; digits unchanged.
- [x] `live_guard.highlight_segments`: whole-word match for letter tokens (`_token_pattern`).

### Task GH4 — Regression net

**Covers**: REQ-GH-14, §5

- [x] Create `tests/test_recorded_verdicts.py`: the four run files, the pinned sets of record ids
  that end on the fixed template, every record's alert found in today's demo, every committed run
  file pinned.

### Task GH5 — Documentation

**Covers**: REQ-GH-15

- [x] `docs/live-guard.md`: one item in the list of what the guard checks (rule and limits). Nothing
  else changed.

### Task GH6 — Record of Kiro calls (for the reviewer to fill in)

**Covers**: all of part 1

Fill in after running the checks. One line per call; do not write what was not run.

| # | Command or action | Result | Date | By |
|---|---|---|---|---|
| 1 | `ruff check .` | F401 (unused import) | — | reviewer |
| 2 | `ruff format --check .` | | | |
| 3 | `pytest tests/test_number_words.py` | | | |
| 4 | `pytest tests/test_guard_number_words.py` | | | |
| 5 | `pytest tests/test_recorded_verdicts.py` (if a set differs: explain it in §5 of the design, per record) | | | |
| 6 | `pytest` (all) | 3 failed, 3767 passed | — | reviewer |
| 7 | Session 21a2: fixes after the user's full run (3 failed, ruff 1 error); edited files only, no command run by Kiro | not run by Kiro; reviewer: 3784 passed, 1 skipped, ruff I001 fixed with `ruff check --fix`, committed as eb94102 | — | Kiro / reviewer |
| 8 | Session 21b: Home example, labels, README; edited files only, no command run by Kiro | not run by Kiro; reviewer: full suite 6 failed, 3829 passed, 1 skipped; ruff clean | — | Kiro / reviewer |
| 9 | Session 21b2: fixes after the user's full run of 21b (6 failed); edited files only, no command run by Kiro | not run | — | Kiro |
| 10 | Session 21b3: Home example quotes the conclusion sentence for 617.51 (`Recording.last_sentence_with`, `landing.py`, two tests, REQ-GH-20 line); edited files only, no command run by Kiro | not run | — | Kiro |

What the reviewer saw for the earlier rows:

| Session | What the reviewer saw |
|---|---|
| 21a | Full suite: 3 failed, 3767 passed; ruff F401. `ciento` in `por ciento` was read as 100; one test relied on 3, a value the GYMPLUS data holds. |
| 21a2 | Full suite: 3784 passed, 1 skipped; one ruff I001 fixed by the reviewer with `ruff check --fix`; every recorded verdict and rejected token unchanged; Night Watch 760 passed with this kit; committed as eb94102. |
| 21b | Full suite: 6 failed, 3829 passed, 1 skipped; ruff clean. Four causes: `home_example` returned a P3 record read as a card (question None); `docs/live-guard.md` said 5% (a digit percent the docs test forbids); two old tests pinned the badge texts this spec changed on purpose (the recorded `BADGE_ACCEPTED` and the live `BADGE_LLM`, the second in three parametrized cases). |
| 21b2 | Session 21b2: files edited only, no command run by Kiro (commands unavailable); checks left to the user and the workspace hooks. |

### Task GH5b — Fixes of session 21a2

**Covers**: REQ-GH-16, REQ-GH-17

- [x] `number_words.py`: `cien`/`ciento` right after `por` give no phrase (tests in
  `tests/test_number_words.py`).
- [x] `explainer.py`: `_blank_word_non_figures` reuses the keyword, separators and count words of
  the digit rules (`_CITE_KEYWORD`, `_COUNT_TAIL`); tests in `tests/test_guard_number_words.py`.
- [x] `tests/test_guard_number_words.py`: `Pagas cuatro céntimos.` replaces the case whose value 3
  the GYMPLUS data holds; every checked case asserts its value is not in the allowed set.
- [x] `tests/test_recorded_verdicts.py`: unused `Path` import removed; pinned sets unchanged.
- [x] `docs/live-guard.md`: one item for these two rules (checked against `test_live_guard_docs.py`).

## Part 2 — session 21b

### Task GH7 — The Home example is a real invention

**Covers**: REQ-GH-20

- [x] `tests/test_home_example.py` first, then `replay.home_example` and its constants,
  `landing.example_html(recording)`, `theme.py` (`gl-example-note`) and `streamlit_app.py`.
- [x] Existing tests edited only to follow (root `conftest.py`, the `judge_path` fixture and the
  two Home tests of `test_judge_path_pages.py`, one test of `test_judge_path_replay.py`).

### Task GH8 — Labels of accepted answers

**Covers**: REQ-GH-21

- [x] Label tests in `tests/test_home_example.py`, then `VERDICT_ACCEPTED`, `NOTE_GUARD_SCOPE`,
  `BADGE_ACCEPTED` and the three `BADGE_LLM`.

### Task GH9 — README and docs

**Covers**: REQ-GH-22

- [x] README tests, then the README (line 3, judge steps 1 and 4, the promise sentence, the new
  section, a Decisions row) and the one item of `docs/live-guard.md`.

## Part 3 — session 25

### Task GH10 — The index is context, not a cause

**Covers**: REQ-GH-23, §7

- [x] Create `tests/test_guard_index_cause.py`: the exact Z04 and Z05 sentences, English and
  Spanish cases, what must stay accepted (index without a cause, cause without an index, the
  kit's fixed CPI sentences), the reason shown by the panel verdict and the replay badge,
  Hypothesis properties.
- [x] `ledger_kit/index_cause.py`; `Explanation.rejected_reason` and the check in
  `explain_with_meta`; `ProbeResult.reason`, `VERDICT_REJECTED_INDEX_CAUSE_PREFIX` and
  `verdict_line`; `card_badge`.

### Task GH11 — Regression net and documentation

**Covers**: REQ-GH-14, REQ-GH-23

- [x] `tests/test_recorded_verdicts.py`: Z04 and Z05 join the pinned set of
  `2026-11-11_llama3.2-3b_demo.json`; each record is explained in the verdict log of design §5.
- [x] README (section What the guard does not check, one sentence; Hackathon: `three different
  apps (two of them read the same bank statement)`) and `docs/live-guard.md` (one item).
- [x] Run `ruff check .`, `ruff format --check .` and `pytest` (session 25 could not run them;
  the hooks lint and run the tests). If a test or a document states how many recorded demo answers
  are accepted or rejected, update it and say so here.
  Reviewer's run after session 25: ruff clean; 3,973 passed, 1 skipped, 1 failed
  (`tests/ingestion/test_normaliser.py::test_date_round_trip_plain`, Hypothesis DeadlineExceeded,
  447.76 ms against the 200 ms default, while the laptop was busy). The file alone and the two
  test files of this task pass (71 passed). Unrelated to the guard; fixed in 25b by a Hypothesis
  profile with `deadline=None` (root `conftest.py`). AppTest check of the Zombie demo with no key:
  the CLOUDVAULT price-increase card shows the fixed template with the neutral CPI sentence, and
  the badge says the recorded answer was rejected because it names the price index as the cause,
  quoting the sentence, for Z04 and Z05.

## Part 4 — session s50: amendment A-GH-01

### Task GH12 — A year on its own is said as a year

**Covers**: REQ-GH-24, REQ-GH-25, §8

- [x] `tests/test_guard_year_wording.py` first: the date forms of today through `check_figures`
  (ISO, DD/MM/YYYY, `June 18, 2025`, `18 June 2025`, `June 18` accepted when the date is in the
  data; `in 2026`, `June 2025` and `18 de junio de 2025` rejected with the year, and the day for the
  Spanish form, as plain numbers; a lone 2026 passes when an invoice number holds 2026), the year
  test and its constants, the badge clause, the reason text, the Provoke verdict, the V37 and P27
  replay badges, the Vampire live badge, the 43 pinned outcomes of the 16 Nov run, the README
  bullets, and two Hypothesis properties (`max_examples=200`).
- [x] `ledger_kit/live_guard.py`: the constants, `is_year_alone` and the split in
  `rejection_clause`, `verdict_line` and `_currency_verdict` (§8). No change to `explainer.py`,
  `calc.py`, `replay.py`, the apps or `data/live_runs`.
- [x] README: the **Dates** bullet and the V35 example in **Meaning**.

Record of session s50:

- Date handling found by reading `_tokenise` and `_passes_number_guard` (table of REQ-GH-24): a
  date with a day (ISO, DD/MM/YYYY, English month name) is parsed and matched to the date cells
  and the alert dates; `June 18` is matched by month and day; a year alone and `June 2026` leave
  the year as a plain number; Spanish month names are not read, so `18 de junio de 2025` gives the
  plain numbers `18` and `2025`.
- Count: 10 of the 43 records of `2026-11-16_llama3.2-3b_calc2.json` go back to the template
  (Z03, Z04, Z05, Z22, P27, P32, V37, V41, V42, V43), the number the owner gave. Kiro could not run
  commands in this session (every shell call was refused before it ran), so the count is the one
  the run recorded (`observed_source`) and the one `tests/test_recorded_verdicts.py` already pins
  for today's guard; the new test pins it again with the tokens and reasons.
- V35: the alert fields are `interest_total` 61.00 and `total` 106.00 (`fee_total` 45.00), read
  from the detector (`total` is the sum of all overdraft rows, `interest_total` of the interest
  rows) and from the recorded rejections of V41 (`total = interest_total + fee_total`) and V43
  (`interest_total used more than once` for `interest_total - 61.00`); the new test checks them on
  the demo alert.
- Verification (`ruff check .`, `ruff format --check .`, `pytest`): not run by Kiro (no shell);
  left to the reviewer and the workspace hooks.

Record of session s50b (follow-up to s50):

- Conflict: `test_readme_has_the_dates_bullet` (tests/test_guard_year_wording.py) wants the README
  Dates bullet to show `08/05/2026` in backticks, and `test_every_backticked_path_exists`
  (tests/test_readme.py) read that text as a path (`assert not ['08/05/2026']`).
- Fix, narrow, in `tests/test_readme.py` only: `DATE_RE` (`\d{2}/\d{2}/\d{4}`) and one `continue`
  in `_path_candidates` for a backticked text that is a whole date. The README bullet is unchanged.
- New test `test_a_backticked_date_is_not_a_path`: a date is skipped, a missing path with a slash
  is still reported by `_path_candidates` and `_missing_paths`.
- Verification (`ruff check .`, `ruff format --check .`, `pytest`): not run by Kiro (the shell
  refused `ruff` and `pytest` calls before they ran); left to the reviewer and the workspace hooks.
