# app-signatures — Implementation Tasks

Every task is test-first: write the tests, see them fail for the right reason, then implement.
Section references (§) point to `design.md`, REQ ids to `requirements.md`. Verification
(`ruff check .`, `ruff format --check .`, `pytest`, and a look at every page in a browser at 1400
and at 800 pixels wide) is run by the user: this session could not run commands, so a box ticked
here means the file is written, not that it was run. Tasks run in order.

## Task AS1 — Chips, caption, CSS and `scale_to`

**Covers**: REQ-AS-02 to 04, 17, 18, §2.1, §4

- [x] Create `tests/test_signatures.py`. Chips: the `file · row N` form with the full ref in
  `title`; a ref without a row stays raw; escaping of text and `title` (a `<b>` and a quote);
  order and count; no refs gives "". `signature_block`: wraps in `gl-signature`, ends with the
  caption, gives "" for an empty drawing. `scale_to`: the largest value gives the size, half gives
  half, zero maximum gives 0, the result is an `int`. CSS: `theme_css` holds the signature,
  chip, lit and wrap rules and an `@media (max-width: 800px)` rule; the module imports no
  Streamlit.
- [x] Add `scale_to` to `ledger_kit/utils/money.py`; create `ledger_kit/ui/signatures.py` (chips,
  `row_label`, `signature_block`); add the CSS to `BASE_CSS` in `ledger_kit/ui/theme.py`.

## Task AS2 — The heartbeat

**Covers**: REQ-AS-05 to 07, 15, §2.2

- [x] In `tests/test_signatures.py`: dots equal the cited rows (also two rows on one date and a
  single row); dots left to right in date order; the tombstone and the word `cancelled` appear only
  with a `cancellation_date`; the dots after it carry `gl-dot-after`, a dot on the date itself does
  not; a cancellation date before the first cited date still draws the tombstone; the visible text
  is the first and last date (and the cancellation date); each `title` equals the row label and
  equals what `format_for_display` writes for the row; `role="img"` and an `aria-label` with no
  digit; no rows gives "".
- [x] Implement `heartbeat_svg`.

## Task AS3 — The bites

**Covers**: REQ-AS-08 to 10, 15, §2.3

- [x] In `tests/test_signatures.py`: bars equal the cited rows, also for 45 rows; every bar lies
  inside the viewBox and no two bars overlap (45 rows); a larger amount gives a taller bar; the
  visible text is the first and last date only; titles equal the row labels; `role`/`aria-label`.
- [x] Implement `bites_svg`.

## Task AS4 — The lantern and the Phantom mapping

**Covers**: REQ-AS-11 to 14, §2.4, §3

- [x] In `tests/test_signatures.py`: the mapped columns are `gl-lit` and the others `gl-dim`; a
  mapped name that is not in the table is ignored; an unmapped detector lights the differing
  columns and `source_ref` never; one row lights nothing; cells and headers are escaped; the
  wrapper scrolls (`gl-lantern-wrap`); the mapping covers the four `pi.*` detectors and names only
  columns of the views; no full IBAN of the Phantom demo files is in the lantern of any demo alert
  and the masked form is where the IBAN is compared; `lantern_view` follows the order of
  `source_refs`.
- [x] Implement `lantern_html`; add `LANTERN_COLUMNS`, `lantern_lit_columns` and `lantern_view` to
  `apps/phantom_invoices/settings.py`.

## Task AS5 — The honesty test over the three demos

**Covers**: REQ-AS-16, §5

- [x] In `tests/test_signatures.py`: for every case of `cases_of("zs")`, `cases_of("pi")` and
  `cases_of("vf")`, the text of the signature passes `check_figures`; every alert has a signature;
  the self-checks fail as designed (an invented amount; the sum of the cited amounts).

## Task AS6 — The three pages

**Covers**: REQ-AS-01, 04, §1

- [x] Create `tests/test_signatures_pages.py` (new file, helpers of `judge_path_support`): one
  `AppTest` per app. After the demo loads, the number of `gl-signature` blocks equals the number of
  alert cards, each card has badge, signature, `Source refs:` in that order, the kind of drawing is
  the one of the app, and the refs show as chips in the order of `source_refs`, with no backtick.
- [x] Call `signature_block(...)` and `refs_chips_html(...)` from `_render_alert` in
  `apps/zombie_subscriptions/app.py`, `apps/vampire_fees/app.py` and
  `apps/phantom_invoices/app.py`.
- Existing tests edited: **none**. Every existing test that reads the `Source refs:` line only
  checks `startswith("**Source refs:**")` or `"<file>:" in value`, and both still hold (the chip
  keeps the full ref in its `title`). Searched in `apps/*/tests/` and `tests/`.

## Task AS7 — Record of Kiro calls (for the reviewer to fill in)

**Covers**: REQ-AS-19

Fill in after the review. One line per call that touched this feature.

| # | Date | Tool or agent | Input (short) | Result / decision | Reviewer |
|---|---|---|---|---|---|
| 1 | | Kiro, session 22a | Build the signatures: chips, heartbeat, bites, lantern, CSS, three pages, honesty test | Full suite green: 3917 passed, 1 skipped; `ruff check` and `ruff format --check` clean. Looked at in a browser at 1400 px: heartbeat read as a flat line, drawing covered half the card, lantern showed every column | |
| 2 | | Kiro, session 22b | Polish after the 1400 px look: spike and larger tombstone, full width, short lantern, one caption per app, structure.md, `_refs_markdown` | Files written, not run (no commands in this session); the hooks lint and test on stop. See Task AS8 | |
| 3 | | Kiro, session 22c | README: Specs row now lists 17 specs, a Decisions row for the signatures and a clause in step 3 of the judge steps | Full suite: 1 failed (`test_readme_has_the_decisions_row_of_13_nov`, which expected one `13 Nov` row), 3926 passed, 1 skipped; ruff clean | |
| 4 | | Kiro, session 22d | Fix that test: pick the `13 Nov` row that mentions number words, keep its assertions, assert the other `13 Nov` row mentions the drawing per app | Test file edited, not run (no commands in this session); the hooks run the tests on stop | |

- [ ] Run `ruff check .`, `ruff format --check .` and `pytest`; paste the result here.
- [ ] Look at the three pages at 1400 and 800 pixels wide; note anything that must change.
- [x] List the new files in `.kiro/steering/structure.md` (done in session 22b; DN-AS-07 is superseded).

## Task AS8 — Polish after session 22a (session 22b)

**Covers**: REQ-AS-20 to 24, §2.2, §3, §4

Requirements first (`requirements.md` §8), then the tests, then the code.

- [x] Heartbeat: a spike before each dot (up 28, down to 14 below the line, back), the tombstone
  twice its size with `cancelled <date>` above it; the viewBox is 166 high (`HEART_HEIGHT`); dates
  and row titles unchanged. `tests/test_signatures.py`: spike path, tombstone size, word above it,
  both ends of the axis.
- [x] `ledger_kit/ui/theme.py`: no `max-width` on the signature SVG, `min-width: 30rem` kept.
- [x] Lantern: `lantern_view` keeps `source_ref`, `invoice_number` and the lit columns in mapping
  order (`LANTERN_NAMING` in `settings.py`); the mapping and its fallback are unchanged.
- [x] Captions: `signature_block(inner, caption)`; `ZOMBIE_CAPTION`, `VAMPIRE_CAPTION`,
  `PHANTOM_CAPTION`; the three apps pass theirs. `tests/test_signatures_pages.py` checks the caption
  of each page. The honesty test is unchanged in what it checks and still runs over every demo alert.
- [x] `.kiro/steering/structure.md` lists `signatures.py`, `test_signatures.py` and
  `test_signatures_pages.py`.
- [x] `apps/phantom_invoices/app.py`: `_refs_markdown` removed (the Phantom card has used
  `refs_chips_html` since 22a); the unused `Iterable` import went with it. The same-named helpers
  of the other apps are separate and untouched. The repo-wide search could not be run in this
  session; checked by reading `apps/phantom_invoices/app.py` and `test_pi_app_logic.py`.
- Existing tests edited: only `tests/test_signatures.py` and `tests/test_signatures_pages.py`
  (the tombstone position and the `end` anchor, the one-argument `signature_block`, `CAPTION`).

## Task AS9 — The line of the file on every page (session 32)

**Covers**: REQ-AS-25 to 32 (and REQ-LN-01 to 11 of `ledger-core`)

Requirements first (`requirements.md` section 9), then the tests, then the code. This session
could not run commands and could not search the repository: a box ticked here means the file is
written, not that it was run, and the list of edited tests comes from reading the files that can
pin a key, a column or a chip, not from a search. The hooks lint each file and run the tests on
stop.

- [x] `tests/test_signatures.py`: the chip tests of the `file · row N` form are replaced one by
  one: a known line reads `file · line N` with the raw ref and the line in the title; a CSV ref
  without a line reads raw and never `row`; an `.xml` ref reads `file · invoice N`; escaping with a
  map; `source_lines_of` and `ref_with_line_markdown`. The lantern tests allow `source_line` right
  after `source_ref`. The honesty test hands the guard the `source_line` of the cited rows of a
  lantern (`with_lines`), in the test only (REQ-AS-31).
- [x] `tests/test_source_line_pages.py` (new): the GYMPLUS card shows `zombie_demo_statement.csv ·
  line 183` and its `Source rows` table shows `source_ref` `:181` with `source_line` `183`; no
  chip of the three pages nor of the Home tiles shows `row`; tile chips with the map and the count
  of the rest; the tombstone and coffin lists; the lantern columns; an XML invoice reads `invoice
  N` and has an empty line cell; Norma 43 payments show the line of their record 22; both
  quarantine tables have `line`, not `row`; the Phantom page quarantine lines point at the
  multi-rate rows of `invoices.csv`.
- [x] `ledger_kit/ui/signatures.py`: `_chip(ref, lines)`, `refs_chips_html(refs, lines=None)`,
  `source_lines_of(*frames)`, `ref_with_line_markdown`, `LINE_TITLE`; the lantern never lights
  `source_line` by itself.
- [x] `ledger_kit/ui/reference_app.py`: `DISPLAY_COLUMNS` with `source_line`, the cell as text;
  `quarantine_table` column `line`; the `Source refs` line with the line.
- [x] `apps/zombie_subscriptions/app.py`, `apps/vampire_fees/app.py`,
  `apps/phantom_invoices/app.py`: chips and `_refs_markdown` get the map from the frame the card
  cites from. `apps/home_tiles.py`: `tile_refs_html(refs, lines=None)`, `_tile(..., lines)`, the
  tile lantern keeps the source ref, its line and one compared column.
- [x] `apps/phantom_invoices/settings.py`: `source_line` right after `source_ref` in
  `LEDGER_COLUMNS`, `MASTER_COLUMNS`, `PAYMENT_COLUMNS` and in `lantern_view`; `quarantine_view`
  column `line`; the `duplicate_file_name` record has the key; `prepare.py` copies the line into the
  multi-rate records.
- [x] Existing tests edited, each to pin the new key, column or text and nothing else:
  `tests/test_signatures.py` and `tests/test_signatures_pages.py` (chips, lantern columns),
  `tests/ingestion/test_normaliser.py` (column tuples), `tests/ingestion/test_sniffer.py`,
  `test_norma43_reader.py`, `test_norma43_controls.py`, `test_facturae_reader.py` and
  `test_facturae_security.py` (the exact quarantine records and the model dump gain
  `source_line`), `apps/phantom_invoices/tests/test_pi_settings.py` and `test_pi_app_logic.py`
  (quarantine keys and table), `apps/zombie_subscriptions/tests/test_zs_real_formats.py` (the
  explanations of the two demos are compared up to the line number too).
- Not changed, by design (REQ-LN-02): `source_row`, `source_ref`, `Alert.id`, `source_refs` and
  `data` of every alert, every detector, the number guard, `_LLM_ROW_COLUMNS` and
  `_NEVER_SENT_COLUMNS` in `ledger_kit/explainer.py`, `ledger_kit/replay.py`, `data/live_runs`,
  `tests/test_recorded_verdicts.py`, `docs/benchmark.md`, the 18 folders of `.kiro/specs`, the 6
  files of `.kiro/steering`.
- Seen, not changed: `scripts/ledger_scan.py` prints the cited rows with `format_for_display`, so
  each row of its JSON output now has a `source_line` key.
- [ ] Run `ruff check .`, `ruff format --check .` and `pytest`; paste the result here.
- [ ] Look at the three pages at 1400 and 800 pixels wide; the chips are longer by a few
  characters (`line 183` for `row 181`), the lantern has one more narrow column.

## Task AS10 — The lantern of a Home tile has two columns (session 32b)

**Covers**: REQ-AS-33

Requirements first (`requirements.md` section 10), then the tests, then the code. This session
could not run commands either; the hooks lint and test on stop.

- [x] `tests/test_home_tiles_polish.py`: `tile_lantern_view` gives the first column as the chip
  shows it (line, invoice, raw) and leaves the view of the card alone; `tile_lantern_columns` never
  holds the line column; the demo tile has no `source line` header. The test of the two columns is
  unchanged. `test_a_tile_with_many_refs_shows_three_chips_and_the_computed_rest` now gives its
  rows a `source_line` (data index plus 2) and pins the three chips as `s.csv · line N`.
- [x] `ledger_kit/ui/signatures.py`: `chip_text(ref, lines)` (the text of a chip, plain);
  `_chip` uses it. `apps/home_tiles.py`: `tile_lantern_columns` drops the line column,
  `tile_lantern_view` builds the table of the tile.
- [x] Fixes of the other failures of session 32: `_without_source` of
  `tests/test_generate_samples.py` drops `source_line`; `tests/test_ledger_scan.py` and
  `apps/phantom_invoices/tests/test_pi_prepare.py` allow `source_line` and check it is an `int`
  or `None`; the five section comments of `tests/test_source_line_pages.py` are under 100
  characters.
- [ ] Run `ruff check .`, `ruff format --check .` and `pytest`; paste the result here.
