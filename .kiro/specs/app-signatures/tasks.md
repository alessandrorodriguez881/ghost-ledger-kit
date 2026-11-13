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
| 1 | | | | | |
| 2 | | | | | |
| 3 | | | | | |

- [ ] Run `ruff check .`, `ruff format --check .` and `pytest`; paste the result here.
- [ ] Look at the three pages at 1400 and 800 pixels wide; note anything that must change.
- [ ] List the new files in `.kiro/steering/structure.md` (not done in this session, DN-AS-07).
