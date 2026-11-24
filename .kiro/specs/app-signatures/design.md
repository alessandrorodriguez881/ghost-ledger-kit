# app-signatures — Design

Requirement ids (`REQ-AS-nn`) are in `requirements.md`. Decisions are `DN-AS-nn`.

## 1 — Files

| File | Change |
|---|---|
| `ledger_kit/ui/signatures.py` | new, pure: chips, heartbeat, bites, lantern, block |
| `ledger_kit/ui/theme.py` | CSS of the signatures and the chips in `BASE_CSS`, next to the card rules |
| `ledger_kit/utils/money.py` | one helper, `scale_to`, for the proportional bar height |
| `apps/phantom_invoices/settings.py` | `LANTERN_COLUMNS` (detector id → compared columns), `lantern_view`, `lantern_lit_columns` |
| `apps/*/app.py` (three) | draw the signature after the badge; chips on the `Source refs:` line |
| `tests/test_signatures.py` | new: chips, geometry, lantern, CSS, `scale_to`, the honesty test |
| `tests/test_signatures_pages.py` | new: one `AppTest` per app |

No new file in `apps/phantom_invoices/`: `test_pi_structure_steering.py` pins the exact file list
of that folder, so the mapping lives in `settings.py` (DN-AS-02).

## 2 — `ledger_kit/ui/signatures.py`

Imports: `html`, `re`, `datetime`, `decimal`, `pandas`, `ledger_kit.utils.money`. No Streamlit
(and so not `theme.py`, which imports it; colours reach the markup as CSS variables, DN-AS-03).

```python
ZOMBIE_CAPTION = "Each dot is one cited charge."          # REQ-AS-24
VAMPIRE_CAPTION = "Each bite is one cited fee."
PHANTOM_CAPTION = "Lit: the fields the detector compares. Each line is one cited row."
def row_label(day, amount, currency="EUR") -> str          # "2026-08-31 · 29,99 EUR"
def refs_chips_html(refs) -> str                            # REQ-AS-03
def signature_block(inner: str, caption: str) -> str       # div.gl-signature + caption; "" if inner is ""
def heartbeat_svg(rows, cancellation_date=None) -> str      # REQ-AS-05 to 07
def bites_svg(rows) -> str                                  # REQ-AS-08 to 10
def lantern_html(rows, lit_columns=None) -> str             # REQ-AS-11 to 14
```

`rows` of the two SVG functions is the cited-rows DataFrame the card already has (`date`,
`amount`, optional `currency`). `rows` of the lantern is a DataFrame of display strings. Rows
whose date or amount cannot be read are left out of the drawing; the ledger the apps pass in has
validated rows, so none is left out in practice.

`row_label` uses `format_amount` and `date.isoformat()`, the two calls `format_for_display` makes
for the `Source rows` expander, so a test can compare them cell by cell (REQ-AS-07).

### 2.1 Chips

`^(?P<file>.+):(?P<row>\d+)$` on the ref. Match → `<file> · row <N>`; no match → the raw ref.
`html.escape(..., quote=True)` on text and on `title`. Chips are joined by one space. No refs → "".

### 2.2 Heartbeat

`viewBox="0 0 640 166"`, line at `y = 110`, side margins 28 (session 22b: taller than the bites so the
tombstone and its word fit above the line). The domain is the first to the last cited
date, widened to the cancellation date when that falls outside (DN-AS-04); one date gives the
middle. `x = left + (right - left) × (day - first) / (last - first)` in whole days (no money).
Rows of one date take the vertical offsets `0, -9, +9, -18, +18 ...`.

The pulse is one path: flat, with a spike (18 units wide) before each dot where there is room:
`l5,-28 l6,42 l7,-14`, that is up 28, down to 14 below the line, back on the line (REQ-AS-20). It is
static (nothing animates, `theme.py`).

Marks: `<circle class="gl-dot">` with `<title>row label</title>`; after the cancellation date
`class="gl-dot gl-dot-after"`. Tombstone (REQ-AS-21): a `<path class="gl-tomb">` (arch on a base,
28 wide, 50 high, top 17, base 67) at the cancel x, and `<text>cancelled <ISO date></text>` centred
above it at `y = 11`, clamped so the text stays inside. Date labels: first at its x, last at
its x, a second row when they would touch; one centred label when both dates are equal.

### 2.3 Bites

`viewBox="0 0 640 114"`, baseline `y = 84`, full height 64, side margins 12. Rows sorted by date
(stable). `n` slots of equal width `slot = 616 / n`; the bar is `min(0.8 × slot, 18)` wide, at least
2. Height `scale_to(amount, largest, 64)`, at least 4. Shape of a bar: a fang, two quadratic curves
from the base to the tip, `<g class="gl-bite"><title>row label</title><path class="gl-fang" .../></g>`.
With 45 rows a slot is about 13.7 px and a bar about 11 px: readable (REQ-AS-09). Labels: first and
last date under the baseline.

### 2.4 Lantern

```html
<div class="gl-lantern-wrap"><table class="gl-lantern" aria-label="...">
<thead><tr><th scope="col" class="gl-lit|gl-dim">invoice number</th> ...
<tbody><tr><td class="gl-lit|gl-dim">F-2026-0310</td> ...
```

Lit columns: the `lit_columns` argument when it is not `None` (names not in the table are
ignored); otherwise the columns whose values differ between rows, `source_ref` excluded (REQ-AS-12).
Headers are the column names with `_` written as a space. Every cell is escaped; a missing value is
an empty cell.

## 3 — Phantom: mapping and rows (DN-AS-01, DN-AS-02)

Detector modules read (`apps/phantom_invoices/detectors`):

| Detector | What the rules compare | Lit columns |
|---|---|---|
| `pi.duplicate_invoice` | supplier (by tax id), invoice number, issue date, total | `supplier_name`, `invoice_number`, `issue_date`, `total` |
| `pi.iban_change` | the IBAN of the invoice or payment against the master | `iban` |
| `pi.vat_error` | base, rate, VAT, surcharge, withholding, total | those six |
| `pi.reconciliation` | invoice total and due date; payment date, amount and payee | `supplier_name`, `due_date`, `total`, `date`, `amount`, `counterparty` |

`lantern_view(alert, pipeline)` builds one DataFrame of display strings for the cited refs, in the
order of `alert.source_refs`, from the three views the page already uses for its cited rows:
`ledger_view` (invoice rows), `cited_master_view` (supplier master) and `cited_payments_view`
(payments). It keeps only `source_ref`, `invoice_number` (it names the row, lit or not) and the
mapped columns in the order of the mapping (REQ-AS-23); for an unmapped detector, `source_ref`,
`invoice_number` and the columns whose values differ. A column with no value in any row is left
out. The IBAN is shown only where the detector compares it, and masked. **The Phantom card has no `Source rows` expander**; the
formatting the lantern must match is the one of these three views (the haunted ledger and the cited
tables under it), and the IBAN stays masked as it is there.

## 4 — CSS (DN-AS-03)

Added to `BASE_CSS` after the card rules, all under `.stApp`:

- `.gl-signature`: dashed border in `var(--gl-line)`, wash of `rgba(var(--gl-accent-rgb), 0.05)`,
  `overflow-x: auto`; its SVG `width: 100%; min-width: 30rem` (no maximum, REQ-AS-22) so the drawing
  fills the card on a wide screen and scrolls inside the block on a phone.
- `.gl-sig-line`, `.gl-dot`, `.gl-dot-after`, `.gl-tomb`, `.gl-fang`, `.gl-sig-text`: strokes and
  fills from `var(--gl-accent)` and `var(--gl-accent-text)`; text `#b9ae95` (7 to 1 on the panel).
- `.gl-lantern-wrap { overflow-x: auto }`, `.gl-lantern td.gl-lit` with a soft glow
  (`box-shadow: inset` and a radial wash of the accent), `.gl-dim` in the muted bone colour. No
  opacity is used to dim, so the contrast of dim text stays above 4.5 to 1.
- `.gl-ref-chip`: monospace, accent text on a translucent accent fill, rounded border.
- A rule in `@media (max-width: 800px)` for the smaller type.

Each app sets the accent variables through `theme_css`, so each signature wears its own colour.

## 5 — The honesty test (REQ-AS-16)

For each case of `cases_of("zs" | "pi" | "vf")`:

1. build the signature exactly as the app does (Zombie: `heartbeat_svg(case.rows,
   alert.data.get("cancellation_date"))`; Vampire: `bites_svg(case.rows)`; Phantom:
   `lantern_html(lantern_view(alert, pipeline), lantern_lit_columns(alert))`), wrapped by
   `signature_block`;
2. take its text: tags replaced by a space, entities unescaped. That keeps the visible text, the
   caption and the SVG `title` contents, and drops every attribute (`aria-label`, `d`, `cx`);
3. `check_figures(text, alert, case.rows, case.columns)` must return `(True, ())`.

A self-check proves the net is tight: the same text with `98765,43 EUR` appended, and with the sum
of the cited amounts of a case whose sum is in no field, must fail.

## 6 — Decisions

- **DN-AS-01** The amounts reach the lantern only through the page's own view helpers, never
  through a new formatter, so Phantom shows what the haunted ledger already shows.
- **DN-AS-02** The mapping and `lantern_view` live in `settings.py`: an extra module in
  `apps/phantom_invoices/` would break the pinned file list of `test_pi_structure_steering.py`.
- **DN-AS-03** Colours are CSS variables from `Accent`, not literals in the markup. `signatures.py`
  therefore needs no `theme.py` import (which would import Streamlit).
- **DN-AS-04** The heartbeat axis includes the cancellation date: the alert of a cancelled service
  cites only the charges after it, so the tombstone would otherwise fall off the drawing.
- **DN-AS-05** Bars of the bites are evenly spaced in date order, not placed by date: 45 fee rows
  often share or neighbour dates and would hide each other.
- **DN-AS-06** `scale_to` is in `money.py` because a bar height is computed from an amount and
  that module is the only one allowed to do amount arithmetic. It returns a whole number of pixels
  and the number never reaches the text.
- **DN-AS-07** `structure.md` and the README are not edited in this session (REQ-AS-19). The new
  module and tests are for the reviewer to list there.

## 7 — A short Source refs line (REQ-AS-40, session 46)

`signatures.py` gets `CARD_MAX_CHIPS: int = 6` and the pure `card_chips_html(refs, lines=None)`:
`refs_chips_html` of the first six refs and, only when there are more, a
`<div class="gl-card-more">and N more cited rows, all in Source rows below</div>` (`row` when N is
1). The cards of `apps/zombie_subscriptions/app.py` and `apps/vampire_fees/app.py` call it for the
`Source refs:` line; the signature and the `Source rows (n)` expander are untouched. Phantom
Invoices and the Home tiles do not use it. `.gl-card-more` in `theme.py` is styled like
`.gl-tile-more`.
