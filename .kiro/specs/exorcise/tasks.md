# exorcise — Implementation Tasks

Every task is test-first: write the tests, see them fail for the right reason, then implement.
Section references (§) point to `design.md`, REQ ids to `requirements.md`. Verification
(`ruff check .`, `ruff format --check .`, `pytest`, and a look at every page in a browser with no
key set) is run by the user: this session could not run commands. Tasks run in order.

## Task EX1 — The mechanism: `check_figures` and `ledger_kit/actions.py`

**Covers**: REQ-EX-04, 06 to 11, 21, §2

- [x] Create `tests/test_actions.py`. Tier 1: a template fills from `Alert.data` and extras
  (extras win); `:money`, `:pct`, `:times` in both languages; `row_lines` order and format;
  `file_name`; `word_count`; `check_figures` accepts a figure of a cited row and rejects an
  invented one, an invented date and an IBAN-shaped token, and agrees with
  `explain_with_meta` on the same text. Tier 2: empty rows, one row, two rows with the same
  `source_ref`; an unknown placeholder, a text under `:money`, a template with `99999.99`: each
  gives `None` and one warning that names the alert id and never raises; a missing language.
  Tier 3 (Hypothesis, `max_examples=200`): for any cited rows (amounts, dates) the lines of
  `row_lines` pass `check_figures`; the draft is the same on two runs; an invented figure added to
  any template is always rejected.
- [x] Add `check_figures` to `ledger_kit/explainer.py` (§2, DN-EX-04) and create
  `ledger_kit/actions.py` (§2). Stdlib, pandas, `explainer`, `money` and `models` only.

## Task EX2 — The widget: `ledger_kit/ui/exorcise.py`

**Covers**: REQ-EX-01 to 05, 11, §3

- [x] In `tests/test_actions.py` (AppTest through `AppTest.from_function`): no template draws
  nothing; with a template the expander is collapsed with the exact title, the radio offers
  `English` and `Español` with English first, the text area is disabled and holds the draft,
  switching the language changes the text, the caption and the download; the download spy sees
  the file name `exorcise-...-en-<id8>.txt` and the same text; a failing draft shows the message
  and no text area and no download button; keys carry the prefix and no `_lg_`.
- [x] Create `ledger_kit/ui/exorcise.py` (§3) and add the CSS line for a disabled text area to
  `ledger_kit/ui/theme.py`.

## Task EX3 — Zombie Subscriptions

**Covers**: REQ-EX-13 to 16, §4

- [x] Create `apps/zombie_subscriptions/tests/test_zs_exorcise.py`: `action_for` for the five
  detectors and `None` for an unknown one; the refund draft lists each charge after the
  cancellation; the price-increase draft carries the CPI sentence only with CPI keys, in both
  languages; the AppTest of the demo shows the expander on every card and the draft changes with
  the language; download file name and text.
- [x] Create `apps/zombie_subscriptions/action_templates.py` and call `render_exorcise` from
  `_render_alert` (after the source rows, before `_render_live_panel`).

## Task EX4 — Phantom Invoices

**Covers**: REQ-EX-17 to 19, §4

- [x] Create `apps/phantom_invoices/tests/test_pi_exorcise.py`: `action_for` for the duplicate,
  the two critical IBAN variants and the two VAT mismatch variants, `None` for `iban_invalid`,
  `vat_rate_not_allowed` and `pi.reconciliation`; the IBAN draft holds only masked IBANs and the
  sentence that forbids the contact data of the invoice or the e-mail; AppTest of the demo.
- [x] Create `apps/phantom_invoices/action_templates.py`, call `render_exorcise` from
  `_render_alert` with `build_explain_rows(...)` and `ROW_COLUMNS`.

## Task EX5 — Vampire Fees

**Covers**: REQ-EX-20, §4

- [x] Create `apps/vampire_fees/tests/test_vf_exorcise.py`: `action_for` for the three fee
  detectors and `None` for `vf.fee_summary`; each fee row of the alert is in the draft; the
  addressee, the Banco de España line, no deadline and no article number; AppTest of the demo.
- [x] Create `apps/vampire_fees/action_templates.py` and call `render_exorcise` from
  `_render_alert`.

## Task EX6 — The proof over the three demos

**Covers**: REQ-EX-01, 07 to 09, 12, §5, §6

- [x] Create `tests/test_exorcise_demos.py`: every alert of `cases_of("zs")`, `cases_of("pi")`,
  `cases_of("vf")` in both languages. A draft exists exactly for the alert types of the table in
  §4; the guard passes; under 150 words; the figures that each type lists are in the text as the
  card writes them; no IBAN-shaped token and none of the full IBANs of the phantom demo files; no
  placeholder left unfilled (no `{`), no digit outside a filled figure in the fixed text.
- [x] Create `tests/test_exorcise_boundaries.py` (§6).

## Task EX7 — Steering and existing tests that pin file lists

**Covers**: REQ-EX-22

- [x] `.kiro/steering/structure.md`: list the new modules and tests.
- [x] `apps/phantom_invoices/tests/test_pi_structure_steering.py`: the phantom file list gains
  `action_templates.py` and `test_pi_exorcise.py` (counts 8 + 6 + 5 + 26).
- [x] No other existing test was edited.

## Open for the user to run

- [ ] `ruff check .` and `ruff format --check .`
- [ ] `pytest` (the demo and AppTest files are slow: three apps)
- [ ] Look at one card of each app in a browser: open **Exorcise: prepare the action**, switch to
  Español, download the file and open it.
