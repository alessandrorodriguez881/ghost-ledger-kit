# app-signatures — Requirements

## Overview

A fresh jury found that the three apps look the same below their mastheads: every alert card is a
title, a detector line, a text, a badge, the refs as inline code and two expanders. Zombie and
Vampire even read the same kind of statement, so their cards are hard to tell apart.

`app-signatures` gives each app its own **visual signature** on every alert card, drawn **only from
the cited rows**:

- **Zombie Subscriptions**: a *heartbeat*. One dot per cited row on a time line drawn like a slow
  pulse. When the alert has a cancellation date, a small tombstone stands at that date and the dots
  after it are brighter: those are the zombie charges.
- **Vampire Fees**: *bites*. One fang-shaped bar per cited fee row on a time line, the height
  proportional to the amount.
- **Phantom Invoices**: a *lantern*. A compact table of the cited rows where the fields the
  detector compares are lit and the other cells are dimmed.
- **All three**: the `Source refs:` line shows one *chip* per ref (`file · row N`) instead of
  inline code.

The promise of the kit does not change: every figure on screen comes from a cited row. A signature
shows **no sum, no average, no count and no other computed figure**. Its text is the text of the
cited rows, nothing else, and a test runs the number guard (`check_figures`) over the signature of
every demo alert.

It changes no detector, no alert, no number-guard rule, no replay, no text of the README and no
text of the Home page.

Ids are `REQ-AS-nn` (requirements) and `AE-AS-nn` (acceptance examples). EARS keywords: *shall*,
*when*, *while*, *where*, *if ... then*. All data in examples is **(synthetic)**: the three demo
statements and invoice sets of `data/samples/`.

## Shared vocabulary

- **Cited rows**: the rows of the user's files named by `Alert.source_refs`, in the form the card
  already uses: the ledger rows for Zombie and Vampire, the invoice, supplier-master and payment
  rows for Phantom.
- **Signature**: the `div` of class `gl-signature` that holds one drawing and one caption line.
- **Mark**: one dot, one bar or one table row of a signature; one mark is one cited row.
- **Row label**: the text `<date> · <amount>` of one row, with the date as ISO text and the amount
  in European format with its currency, exactly as the `Source rows` expander writes them.
- **Chip**: a `span` of class `gl-ref-chip` that shows one source ref.

---

## 1 — The place of the signature

- **REQ-AS-01** The card of every alert of the three apps shall contain exactly one signature,
  drawn right after the guard badge and before the `Source refs:` line, built from the same cited
  rows that the card shows. *If* an alert has no cited row that can be drawn, *then* its card shall
  contain no signature (an empty drawing is never shown).
  - AE-AS-01 Zombie demo: 19 alerts → 19 `gl-signature` blocks. Phantom demo: 9 → 9. Vampire demo:
    6 → 6. In each card the order is title, detector line, text, badge, signature, `Source refs:`.

- **REQ-AS-02** Every signature shall end with one caption line that holds no digit and no figure.
  The caption is the one of its app (REQ-AS-24).
  - AE-AS-02 The caption of the 45-bar signature of `vf.fee_summary` is `Each bite is one cited
    fee.`

## 2 — The chips

- **REQ-AS-03** *When* a ref has the form `<file>:<N>` with `N` a whole number, the chip shall
  read `<file> · row <N>` and carry the full ref in its `title` attribute. *When* a ref has no
  row, the chip shall read the raw ref. Every text and attribute shall be HTML-escaped.
  - AE-AS-03 `zombie_demo_statement.csv:12` → `zombie_demo_statement.csv · row 12`, title
    `zombie_demo_statement.csv:12`.
  - AE-AS-04 `plain-ref` → `plain-ref`. `a<b>.csv:3` → text `a&lt;b&gt;.csv · row 3`, no raw `<b>`.

- **REQ-AS-04** *Where* an app writes the `Source refs:` line of a card, it shall keep the label
  text `Source refs:` and put one chip per ref after it, in the order of `Alert.source_refs`,
  instead of inline code. The other lists of refs (the `Source rows` of a tombstone or a coffin)
  stay as they are.
  - AE-AS-05 The line of an alert with three refs holds three chips and no backtick.

## 3 — The heartbeat (Zombie)

- **REQ-AS-05** The heartbeat shall draw one dot per cited row, placed on a time line by the date
  of the row, from the first to the last cited date, and a line drawn like a slow pulse through
  them. Rows of one date stack vertically so that no dot hides another.
  - AE-AS-06 An alert with five cited rows → five dots, left to right in date order.

- **REQ-AS-06** *Where* the alert data holds a `cancellation_date`, the heartbeat shall draw a
  small tombstone mark at that date, with the word `cancelled`, and shall draw the dots dated
  after it brighter (class `gl-dot-after`). *Where* it holds none, the heartbeat shall draw no
  tombstone and no bright dot. The time line shall reach the cancellation date even when it is
  before the first cited date.
  - AE-AS-07 Zombie demo, GYMPLUS (cancellation_date 2026-07-31): a tombstone, and every cited
    charge is after it, so every dot is bright.

- **REQ-AS-07** The visible text of a heartbeat shall be the first and the last cited date and,
  *where* there is one, the cancellation date with the word `cancelled` (REQ-AS-21). Nothing else
  is visible.
  Each dot shall carry an SVG `title` with the row label of its row.
  - AE-AS-08 Dot of the row dated 2026-08-31 with amount 29,99 EUR → title
    `2026-08-31 · 29,99 EUR`.

## 4 — The bites (Vampire)

- **REQ-AS-08** The bites shall draw one fang-shaped bar per cited row, in date order on a time
  line, with the height proportional to the amount of the row (the largest cited amount reaches
  the full height, a smaller amount a proportional height, never less than a visible minimum).
  The proportion is computed by a helper of `ledger_kit/utils/money.py`.
  - AE-AS-09 Two rows of 10,00 EUR and 5,00 EUR → two bars, the second about half as high.

- **REQ-AS-09** The bites shall stay readable with 45 cited rows (`vf.fee_summary` in the demo):
  45 bars side by side inside the drawing, none outside it, none hidden by another.

- **REQ-AS-10** The visible text of the bites shall be the first and the last cited date only.
  Each bar shall carry an SVG `title` with the row label of its row. The drawing shall show no
  sum, no average, no count and no other computed figure.

## 5 — The lantern (Phantom)

- **REQ-AS-11** The lantern shall be a table with one row per cited row. The cells of the
  columns that the detector compares shall have class `gl-lit` (a soft lantern glow in the Phantom
  colour) and all other cells class `gl-dim`. The compared columns shall come from one mapping
  from detector id to column names in `apps/phantom_invoices` (not in `ledger_kit`), chosen by
  reading each detector module.
  - AE-AS-10 `pi.vat_error`: base, VAT rate, VAT amount, surcharge, withholding and total are lit;
    invoice number, supplier and dates are dimmed.
  - AE-AS-11 `pi.iban_change`: only the IBAN column is lit.

- **REQ-AS-12** *If* a detector is not in the mapping, *then* the lantern shall light the columns
  whose values differ between the cited rows (never the `source_ref` column), and light nothing
  when there is one row or nothing differs.

- **REQ-AS-13** The lantern shall write each value exactly as the cited-row views of the Phantom
  page write them: ISO dates, European amounts with currency, VAT rate as `21 %`, and an IBAN in
  masked form (`****` and the last four characters) only. A full IBAN shall never be in the
  markup. The IBAN column is shown only where the detector compares it (it is in the mapping) or,
  for an unmapped detector, where the IBANs differ.
  - AE-AS-12 No full IBAN of `data/samples/phantom_demo/` is in the lantern of any demo alert.

- **REQ-AS-14** The lantern shall sit in a box of class `gl-lantern-wrap` that scrolls sideways on
  a narrow screen, so the card does not grow wider than the page.

## 6 — Accessibility, honesty and look

- **REQ-AS-15** Every SVG shall have `role="img"` and an `aria-label` in words with no figure.
  - AE-AS-13 `Charges of this alert over time, one dot per cited row` (heartbeat),
    `Fees of this alert over time, one bar per cited row` (bites).

- **REQ-AS-16** The text of a signature (the visible text and the SVG titles, without tags or
  attributes) shall pass `ledger_kit.explainer.check_figures` with the alert, its rows and its row
  columns, for every alert of the three demos. *If* a computed figure (a sum, an average) is added
  to a signature, *then* that test shall fail.

- **REQ-AS-17** The colours of the signatures shall come from the accent of each app
  (`Accent` in `ledger_kit/ui/theme.py`, through its CSS variables) and the CSS shall sit in
  `theme.py` next to the card styles. The signatures shall be legible on the dark theme at 1400
  and at 800 pixels wide. Nothing shall animate.

## 7 — Boundaries

- **REQ-AS-18** `ledger_kit/ui/signatures.py` shall not import Streamlit, shall call no model and
  open no connection, and shall do no arithmetic on an amount (the only amount arithmetic is the
  helper of `money.py`). It shall return strings only; every inserted text is escaped.

- **REQ-AS-19** The feature shall change nothing else: no detector, no alert, no guard, no replay,
  no README, no Home page. The only existing tests edited are those that pin the old inline-code
  refs after `Source refs:`; each one is listed in `tasks.md`.

## 8 — Polish after session 22a (session 22b)

- **REQ-AS-20** *Where* the heartbeat joins two dots, the line shall make one spike before each
  dot (when there is room for it): it jumps up about 28 viewBox units above the line, falls about
  14 units below the line, and comes back to the line at the dot. The spike is static and adds no
  text.
  - AE-AS-14 A heartbeat of five dates on five different days has five spikes, each `l5,-28
    l6,42 l7,-14` (up 28, down 42 to 14 below the line, up 14 back to it).

- **REQ-AS-21** *Where* the heartbeat has a cancellation date, the tombstone shall be about twice
  its first size (28 units wide, 50 units high) and the word `cancelled` with the cancellation
  date shall stand above it, centred on it and kept inside the drawing. The first and last cited
  dates and the row titles shall not change.
  - AE-AS-15 Cancellation 2026-07-31 (GYMPLUS): tombstone 28 × 50, the text `cancelled 2026-07-31`
    above its top edge.

- **REQ-AS-22** The drawing of a signature shall fill the width of its card, with no maximum
  width. *Where* the card is narrower than the minimum width of the drawing, the drawing shall
  keep that minimum width and the box shall scroll sideways instead of squashing it.

- **REQ-AS-23** The lantern shall show only the `source_ref` column, the `invoice_number` column
  (it names a row, lit or not; left out when no cited row has one) and the lit columns, in the
  order of the mapping. *If* a detector is not in the mapping, *then* the lantern shall show the
  `source_ref`, the `invoice_number` and the columns whose values differ. A column in which no
  cited row has a value shall not be shown. The mapping and its fallback (REQ-AS-11, 12) do not
  change.
  - AE-AS-16 `pi.duplicate_invoice`: `source_ref`, supplier, invoice number, issue date, total
    (the lit total is next to the invoice number, not off screen). `pi.vat_error`: `source_ref`,
    invoice number, base, VAT rate, VAT amount, surcharge, withholding, total.

- **REQ-AS-24** Each signature shall end with the caption of its app, with no figure:
  Zombie `Each dot is one cited charge.`; Vampire `Each bite is one cited fee.`; Phantom `Lit: the
  fields the detector compares. Each line is one cited row.`
  - AE-AS-17 The Phantom caption names the lit fields and the rows; the Zombie and Vampire
    captions name the mark.

## 9 — The line of the file (session 32)

A citation a person reads shall point to the line they see when they open the file (spec
`ledger-core`, REQ-LN-01 to REQ-LN-11). The internal key (`source_ref`, `source_row`) is not shown
as a row number any more.

- **REQ-AS-25** A chip whose ref has a known line shall read `file · line N`, N being the
  `source_line` of the cited row. A ref of an `.xml` file with no line shall read
  `file · invoice N`, N being the 1-based position after the last colon. Any other ref shall show
  the raw `source_ref`. No chip shall show the word `row` next to a number.
  - AE-AS-18 `zombie_demo_statement.csv:181` with line 183 reads
    `zombie_demo_statement.csv · line 183`.
  - AE-AS-19 `10-duplicate.xml:2` reads `10-duplicate.xml · invoice 2`; `plain-ref` and a CSV ref
    whose line is not known read as written.

- **REQ-AS-26** The `title` of a chip shall keep the raw `source_ref`, and *where* the line is
  known it shall add that it is line N of the file: `zombie_demo_statement.csv:181 (line 183 of
  zombie_demo_statement.csv)`. Text and title are escaped.

- **REQ-AS-27** `refs_chips_html(refs, lines=None)` shall take an optional map from `source_ref`
  to `source_line`. `source_lines_of(*frames)` shall build that map from every frame that has the
  columns `source_ref` and `source_line`; a frame without `source_line`, `None` and an empty frame
  give nothing, and a missing line is left out of the map. `ref_with_line_markdown(ref, lines)`
  shall write a ref as a code span followed by `(line N)` (or `(invoice N)` for an XML ref without
  a line) for the lists that are markdown.

- **REQ-AS-28** Every chip a person sees shall get the map: the alert cards of the three apps
  (the frame the card cites from; for Phantom Invoices the invoices, the supplier master and the
  payments), the Home tiles (`apps/home_tiles.py`, `tile_refs_html(refs, lines=None)`) and every
  other caller of `refs_chips_html`. The line `and N more cited rows` of a tile is a count and
  stays.

- **REQ-AS-29** Wherever a table or a list shows a `source_ref` to the person, the line shall be
  next to it:
  - the `Source rows` expanders: `DISPLAY_COLUMNS` of `ledger_kit/ui/reference_app.py` has
    `source_line` right after `source_ref`; its cell is the line as text, empty when there is none;
  - the lists of refs of the Zombie Subscriptions tombstones and of the Vampire Fees coffins
    (`_refs_markdown`);
  - the `Source refs` line of the reference page;
  - the lantern of Phantom Invoices (`lantern_view`, REQ-AS-23): `source_line` right after
    `source_ref`, never lit; the cell is empty for an XML invoice, and the column is left out when
    no cited row has a line. The haunted ledger and the cited supplier-master and payment tables
    of the Phantom page carry `source_line` right after `source_ref` too, and the lantern of the
    Home tile follows REQ-AS-33 (it has no column of its own for the line).
  - AE-AS-20 The GYMPLUS card of Zombie Subscriptions shows the chip
    `zombie_demo_statement.csv · line 183`, and its `Source rows` table shows `source_ref`
    `zombie_demo_statement.csv:181` with `source_line` `183`.

- **REQ-AS-30** The two quarantine tables (`quarantine_table` in `ledger_kit/ui/reference_app.py`
  and `quarantine_view` in `apps/phantom_invoices/settings.py`) shall rename their column `row` to
  `line` and fill it from `source_line`, empty when there is none. The other columns do not change.

- **REQ-AS-31** A line number is a place in the file, not a figure of the alert. It shall never
  enter an alert, a template, an explanation, a draft or a prompt. The honesty test of REQ-AS-16
  shall allow it only by adding the `source_line` of the cited rows to the rows it hands to the
  guard, in the test; the whitelist of the explainer does not change.

- **REQ-AS-32** The tests shall cover: a chip with a known line reads `line` and its title has the
  raw ref and the line; an `.xml` ref reads `invoice`; any other ref reads raw; no chip anywhere on
  the three pages shows `row` next to a number; `source_lines_of`; the lantern columns; the
  quarantine tables. The tests that pinned `file · row N` shall be changed to the new form, one by
  one, and listed in `tasks.md`.

## 10 — The lantern of a Home tile (session 32b)

- **REQ-AS-33** The lantern of a Home tile shall have at most two columns (`TILE_MAX_COMPARED`
  compared column plus one for the source), so it has no `source_line` column. Its first column
  shall show each cited row as the chip of that row shows it (REQ-AS-25): `file · line N` when the
  line is known, `file · invoice N` for an `.xml` ref without a line, the raw `source_ref`
  otherwise; its header says source (`source ref`). The other column and the lit cells do not
  change. The lantern of the Phantom Invoices alert cards keeps its `source_line` column
  (REQ-AS-29).
  - AE-AS-21 Tile of the Phantom demo: two `th`, the first cell of each row reads
    `invoices.csv · line N`, and no header reads `source line`.

## 11 — The row numbers of a model answer (session 33)

The model receives each cited row as `file:N`, N being the internal 0-based data index, so a
recorded or live answer can say `rows 9 to 312` while the chips say `file · line N`. The words of
the model are a real recording and the guard judged them as they are, so they are never changed.
Under the answer the person gets one note that says which line of the file each of those numbers is.

- **REQ-AS-34** *Where* a model answer, recorded or live, is shown to the person, the page shall
  write under it one line of note when the answer names at least one row of a cited ref:
  `The model counts data rows from 0, as the kit names them to it: row 46 is payments.csv · line
  48, row 12 is suppliers.csv · line 14.` The note shall be English, one caption line, in the
  order of the answer, one entry per ref however often the answer writes its number, and each entry
  shall read the file and the line as the chip of that ref reads them (REQ-AS-25). The note shall
  appear in every place where a model answer is shown: the alert cards of the three apps, the
  results of the Provoke the LLM panel of the three apps (under the raw answer), the Home tiles and
  the Home example. It shall never appear under the fixed template, never replace or edit the
  answer, and never enter an alert, a prompt, a guard check or a draft (REQ-AS-31). *If* the answer
  names no row, *then* there is no note.
  - AE-AS-22 The MUSICBOX card of Zombie Subscriptions (answer `... from rows 9 to 312.`) shows
    `The model counts data rows from 0, as the kit names them to it: row 9 is
    zombie_demo_statement.csv · line L9, row 312 is zombie_demo_statement.csv · line L312.`, L9 and
    L312 being the `source_line` of the two cited rows, and the answer above it is the recorded
    text.

- **REQ-AS-35** The mentions shall be found by a pure function, `row_mentions_to_lines(text, refs,
  lines)` in `ledger_kit/ui/signatures.py` (with `row_lines_note` for the text and `answer_row_note`
  for both). A mention is the word `row` or `rows` (not part of another word) followed by one
  number, or by numbers joined with `and`, `to`, a comma or a dash; a number that is part of a
  decimal is not a row number. A number N maps only to a ref of this alert whose `source_ref` ends
  in `:N` and whose line is in `lines`. *If* the refs of two files carry that N, *then* it maps
  only when the name of one of those files is written in the `ROW_FILE_WINDOW` characters before
  the mention (the nearest one wins); otherwise it maps to nothing. A number that no ref carries
  maps to nothing. The module imports no Streamlit and calls no model.
  - AE-AS-23 `payments.csv:46` and `suppliers.csv:12` with the answer `... payments.csv file at
    row 46 and the suppliers.csv file at row 12` give both lines. `a.csv:5` and `b.csv:5` with
    `row 5` give nothing; with `In b.csv ... row 5` they give `b.csv:5`.
