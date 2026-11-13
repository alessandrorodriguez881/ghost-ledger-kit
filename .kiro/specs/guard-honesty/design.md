# guard-honesty — Design

Section references (§) in `tasks.md` point here; REQ ids point to `requirements.md`.

## §1 Module map

| File | Change |
|---|---|
| `ledger_kit/number_words.py` | **new**, standard library only: `NumberPhrase`, `find_number_phrases` |
| `ledger_kit/explainer.py` | `_passes_number_guard`, `_allowed_decimals`; new helpers `_checked_phrases`, `_beside_money`, `_in_text_order`; constants `NUMBER_WORD_SMALL_MAX`, `NUMBER_WORD_AMBIGUOUS` |
| `ledger_kit/live_guard.py` | `highlight_segments`: whole-word match for letter tokens |
| `docs/live-guard.md` | one item in the list of what the guard checks |
| tests (new files only) | `test_number_words.py`, `test_guard_number_words.py`, `test_recorded_verdicts.py` |

`number_words.py` imports nothing from the project. `explainer.py` imports it; the package rules
of `structure.md` hold (no app import, the explainer stays the only module that calls a model).

## §2 The parser (REQ-GH-01 to REQ-GH-05)

1. **Tokens**: `\w+` runs. A run is a candidate word only when it is made of letters
   (`str.isalpha`), so `seven5` and `ten_twenty` are not words. The word is folded: lower case and
   no accents (NFD without combining marks), so `dieciséis` and `dieciseis` are one entry.
2. **Links**: neighbour tokens `k` and `k+1` are *linked* when the text between them is one or more
   spaces or tabs, or one hyphen. A comma, a line break or an en dash is not a link.
3. **Scan**: from the left, a token in the English word set starts the English parser, a token in
   the Spanish set starts the Spanish parser, anything else is skipped. The phrase ends where the
   grammar stops accepting; the scan resumes after it. The sets share no word, so a phrase is
   never mixed (`five mil` gives 5 and 1000).
4. **Grammar as a state machine.** English states: open (start, after `hundred`, after a scale,
   after `and`), unit, teen, ten, ones, hundred, scale. A unit after an open state starts a group
   (`unit`) or ends it (`ones` when the group already has hundreds or a ten); only a `unit` or
   `teen` takes `hundred`; a scale (`thousand`, `million`) multiplies the group and must be smaller
   than the previous scale; `and` is consumed only in the `hundred` or `scale` state and only when
   the next token is linked and is a unit, teen or ten. A leading `a` is read only when linked to
   `hundred`, `thousand` or `million`. Spanish follows the same shape: hundreds (`cien`,
   `ciento`, `doscientos`...) only at the start of a group; 10 to 29 are single words; a ten
   (30 to 90) takes `y` and a unit only; `mil` multiplies the group, or stands alone as 1000;
   `millón` and `millones` need a group before them.
5. **Value and count**: the value is the sum of the scaled groups; `word_count` counts number
   words, including a leading `a`, but not `and` or `y`.
6. **Ordinals**: after a phrase is read, if the token before it or the token after it (also
   through one `and` or `y`) is an ordinal word and is linked, the whole phrase is dropped
   (`twenty-first`, `one hundred and first`). English ordinals are listed; Spanish ordinals are
   built from stems plus `o` and `a` (plural forms such as `segundos` are *not* ordinals, they are
   seconds).

## §3 The guard (REQ-GH-06 to REQ-GH-11)

In `_passes_number_guard`, `figures_text = _without_non_figures(text, alert)` is the text the digits
are read from; it is also the text the phrases are read from. IBAN and date rejections return
first, as before. After the digit comparison:

```
checked = _checked_phrases(figures_text)
bad_words = [p for p in checked if Decimal(p.value) not in allowed]
if bad_words: rejected = _in_text_order(figures_text, rejected, bad_words)
rejected.extend(foreign currencies)       # unchanged, after the others
```

`_checked_phrases` keeps a phrase when `word_count >= 2`, or when its value is above
`NUMBER_WORD_SMALL_MAX` (10) and it is not an ambiguous word, or when `_beside_money` is true.
`NUMBER_WORD_AMBIGUOUS` holds `once`, which is Spanish for 11 and English for "one time".

`_beside_money` matches `_MONEY_AFTER_RE` at the end of the phrase (only spaces, tabs or a hyphen
before the money word, so a comma blocks it) and `_MONEY_BEFORE_RE` in the 40 characters before the
phrase. Words are whole words, case-insensitive; the symbols `€ $ £ %` need no boundary.

`_allowed_decimals._add` also adds `Decimal(p.value)` for every phrase found by `find_number_phrases`
in the alert data and in the visible row cells, so the allowed set stays the one source of truth.

**Order (REQ-GH-10).** Digit tokens come out of `_tokenise` by pattern, not by position. Only when a
phrase is rejected, `_in_text_order` finds each digit token in `figures_text` (the n-th occurrence
for the n-th repeat, never inside a longer number) and sorts digits and phrases by position. With no
rejected phrase the list is untouched, so no existing digit verdict or order changes.

**Why a rule of "checked when above ten or two words, small only beside money".** The recorded
answers say `five years`, `six charges`, `three months`, `one of them`, `two separate invoices`; a
guard that rejected them would turn correct answers into templates (the failure that LG9 to LG12
fixed for digits). A figure is dangerous when it is a price or a rate: that is when a money word is
beside it, or when it has more than ten in it. Limits are in REQ-GH-11 and `docs/live-guard.md`.

## §4 Highlight (REQ-GH-12)

`_token_pattern(form)`: when the form fullmatches letters, spaces and hyphens, the pattern is
`(?<!\w)form(?!\w)`; otherwise it is the digit pattern of today. So `once` never marks
`concession`, and `five hundred and forty` is one span. Overlapping spans merge as before.

## §5 Regression net (REQ-GH-14)

`tests/test_recorded_verdicts.py` replays every record of the four files in `data/live_runs` with
`explain_with_meta`, a `ReplayClient`, the template of the case, the case's row columns and the
question of the record, and pins the set of record ids on the fixed template. The test file says in
its docstring that a change must be explained in this spec. A file added to `data/live_runs`
without an entry fails `test_every_committed_run_file_is_pinned`.

### Verdict log (fill when a set changes)

| Date | File | Change of the set | Reason |
|---|---|---|---|
| session 21a | all four | none expected: the pinned sets are those of the guard before number words | part 1 |

## §6 Part 2 (session 21b)

| File | Change |
|---|---|
| `ledger_kit/replay.py` | `DEFAULT_HOME_EXAMPLE_PATH`, `HOME_EXAMPLE_PATH` (read at call time), `HOME_EXAMPLE_ID`, `HOME_EXAMPLE_MARKS`, `home_example(path=None)` (cached, never raises); `BADGE_ACCEPTED` text. `first_rejected_probe` and the rest unchanged |
| `ledger_kit/ui/landing.py` | `example_html(recording)`: the P3 example, one block `gl-example`, one note line `gl-example-note` |
| `ledger_kit/ui/theme.py` | `.gl-example-note` styled like `.gl-example-label` |
| `streamlit_app.py` | `landing.example_html(replay.home_example())` |
| `ledger_kit/live_guard.py` | `VERDICT_ACCEPTED`, `NOTE_GUARD_SCOPE` |
| three apps | `BADGE_LLM` |
| `README.md`, `docs/live-guard.md` | REQ-GH-22 |

**Why P3 and not the GYMPLUS answer.** The GYMPLUS answer (`107.88 * 5 = 539.40`) is right
arithmetic that the guard rejects because 539.40 is in no cited row. P3 assumes an interest rate
found in no row and builds 617.51 on it: a real invention. The Home note says both, so the page
does not teach that the guard does arithmetic. `home_example` reads the 2026-11-10 file only;
the cards and the Provoke panel keep the 2026-11-11 file (`REPLAY_RUN_PATH`).

**Sentences.** The Home block quotes `Recording.sentence_with` for each mark (`5%`, `617.51`), so
for 617.51 it quotes the first line of the answer that holds it (`A = 617.51`).
