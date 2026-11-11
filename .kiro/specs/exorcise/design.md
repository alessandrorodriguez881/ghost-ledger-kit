# exorcise — Design

Section references (§) are used by `tasks.md`; REQ ids are in `requirements.md`.

## 1 — Overview

```
Alert (data, source_refs) + cited rows
        │
        ▼   apps/<app>/action_templates.py : action_for(alert) -> ActionTemplate | None
ActionTemplate(name, texts{en,es}, extras(alert, rows, language) -> {placeholder: text})
        │
        ▼   ledger_kit/actions.py : build_draft(alert, rows, template, language)
fill the template ──► check_figures(draft, alert, rows)   (ledger_kit/explainer.py, the number guard)
        │                      │ rejected / cannot fill: log a warning, return None
        ▼                      ▼
ledger_kit/ui/exorcise.py : render_exorcise(...)      message instead of the draft
   expander "Exorcise: prepare the action"
     radio Language · text area (disabled) · download button · caption (draft, not legal advice)
```

No model is involved at any step. The draft is a pure function of the alert, the cited rows and the
chosen language, so the same alert gives the same draft on every run.

## 2 — `ledger_kit/actions.py` (pure; DN-EX-01 to DN-EX-04)

```python
LANGUAGES = (("en", "English"), ("es", "Español"));  DEFAULT_LANGUAGE = "en"
MAX_DRAFT_WORDS = 150

@dataclass(frozen=True)
class ActionTemplate:
    name: str                                   # e.g. "refund_after_cancellation"
    texts: Mapping[str, str]                    # language code -> text with {placeholders}
    extras: Callable[[Alert, DataFrame, str], Mapping[str, str]] | None = None

def fill(template, alert, language, extras=None) -> str        # raises KeyError / ValueError
def build_draft(alert, rows, template, language, *, row_columns=None) -> str | None
def row_lines(rows) -> str                                     # "2026-08-09: 8,99 EUR" per row
def file_name(alert, language) -> str
def word_count(text) -> int
```

- **DN-EX-01 Placeholders.** A subclass of `string.Formatter` resolves `{key}` first from the
  `extras` the app computed (already text), then from `Alert.data`; an unknown key raises
  `KeyError`. Format specs: `:money` (`format_amount`), `:pct` (`format_percent`), `:times`
  (`1 time` / `3 times`, or `1 vez` / `3 veces` in Spanish). A value that is not a number under
  one of these specs raises `ValueError` (never shown as text). Formatting uses
  `ledger_kit/utils/money.py` only, so there is no arithmetic and the figures read as on the card.
- **DN-EX-02 Rows.** `row_lines(rows)` writes one `date: amount` line per cited row in date order
  (the order of the frame breaks ties), the amount with `format_amount` and the row's currency.
  It is the only place that reads cell values; the amounts stay `Decimal`.
- **DN-EX-03 Run-time check.** `build_draft` fills the text, strips it, runs
  `check_figures(text, alert, rows, row_columns)` and returns the text, or `None` after
  `logging.getLogger(__name__).warning("Exorcise draft rejected for alert %s: %s", ...)`. A
  `KeyError`, `ValueError` or `ArithmeticError` from the fill is logged the same way. No other
  exception is caught.
- **DN-EX-04 `check_figures`.** A four-line public function in `ledger_kit/explainer.py`:
  `narrow = _select_llm_columns(rows, row_columns)` then
  `_passes_number_guard(text, alert, narrow, row_columns)`. It is what `explain_with_meta` does
  after the model answered; no rule changes. Because the draft is judged on the same narrowed rows
  as a model answer, **a draft can cite only what a model could cite**: dates and amounts of the
  cited rows, and the fields of `Alert.data`.

## 3 — The widget: `ledger_kit/ui/exorcise.py` (DN-EX-05)

`render_exorcise(alert, rows, template, *, prefix, row_columns=None)` draws nothing when `template`
is `None`. Otherwise `with st.expander("Exorcise: prepare the action", expanded=False)`:
`st.radio("Language", ["English", "Español"], horizontal=True, key=f"{prefix}_ex_lang_{alert.id}")`,
then `build_draft`; on a draft: `st.text_area(..., disabled=True, key=f"{prefix}_ex_text_{id}_{lang}")`,
`st.download_button(..., file_name=..., mime="text/plain", on_click="ignore",
key=f"{prefix}_ex_dl_{id}_{lang}")` and `st.caption(DISCLAIMER[lang])`; on `None`: `st.info(message)`
only. The language is in the text-area key so a changed language is a new widget with the new text.
The radio lives in the library module, not in the app files, because the app tests pin the sidebar
radio as the only `st.radio` call of an app file.

## 4 — Templates per app (DN-EX-06 to DN-EX-08)

Each app has `action_templates.py` with `TEMPLATES: dict[key, ActionTemplate]` and
`action_for(alert)`. The key is `alert.detector` (zombie, vampire) or `(detector, variant)`
(phantom). Every text starts with a subject line, then a salutation; placeholders in square brackets
(`[Your name]`, `[Your customer number]`, `[Bank name]`, `[Company name]`) stand for the sender's
details. No text holds a digit, a month name or a deadline.

| Alert type | Template | Extras |
|---|---|---|
| `zs.charges_after_cancellation` | refund request + bank paragraph | `charge_lines` |
| `zs.duplicate_subscription` | cancel the duplicate | `account_names` |
| `zs.price_increase` | keep the old price or cancel | `interval_text`, `cpi_sentence` |
| `zs.free_trial_to_paid` | cancellation request | none |
| `zs.recurring_charge` | cancellation request | `interval_text` |
| `pi.duplicate_invoice` × 3 variants | supplier e-mail | `invoice_lines`, `date_span` |
| `pi.iban_change` × 2 critical variants | hold note + phone script | none |
| `pi.vat_error` × 2 mismatch variants | corrected-invoice request | none |
| `vf.recurring_fee`, `vf.fee_increase`, `vf.overdraft_cost` | bank complaint | `fee_lines`, `bank`, `summary` |

- **DN-EX-06 CPI.** `zs.price_increase` takes the CPI sentence from `explain_support`
  (`CPI_SENTENCE`, `CPI_SENTENCE_LAG`, chosen by `cpi_uses_lag`) in English, so it is the card's
  sentence; the Spanish form is a translation with the same placeholders. Without
  `has_cpi_context(alert.data)` the extra is the empty string.
- **DN-EX-07 Phantom rows.** The draft is built from `Alert.data` only (`invoice_numbers`,
  `totals`, masked IBANs); the rows are given to the guard as `build_explain_rows(...)` with
  `ROW_COLUMNS`, exactly as the card's explanation does. A full IBAN is never in `Alert.data` (the
  detector masks it, `****` plus four characters), so a draft cannot hold one; the guard rejects
  any IBAN-shaped token besides.
- **DN-EX-08 Vampire.** `bank` is `Alert.data["counterparty"]` when present, else the counterparty
  of the first cited row, else `[Bank name]`. The overdraft alert has no counterparty key, so its
  bank comes from the cited rows (a visible column of the guard). The closing line about the Banco
  de España is fixed text.

## 5 — Words (DN-EX-09)

Counted as `len(text.split())`. Fixed part of the longest template ≈ 105 words; each listed row
adds three (`2026-08-09:`, `8,99`, `EUR`). The demos list at most a dozen rows, so the largest demo
draft stays below 150; the test proves it for every demo alert. A statement with many more cited
rows gives a longer draft: the limit is a property of the demos and the templates, not a
truncation (the requirement says *each* charge), and the test message names the alert if a template
change breaks it.

## 6 — Tests (DN-EX-10)

| File | Covers |
|---|---|
| `tests/test_actions.py` | REQ-EX-04, 06 to 11: the mechanism (formatter, specs, `row_lines`, file name, word count, run-time rejection and its warning, Hypothesis properties, `check_figures`) |
| `tests/test_exorcise_demos.py` | REQ-EX-01, 12 to 20: every alert of the three demos, both languages (existence, guard, words, figures, no IBAN, per-type content) |
| `apps/*/tests/test_<prefix>_exorcise.py` | REQ-EX-01 to 05, 15, 18, 20: `action_for` per type, headless AppTest of the card (expander, radio, text area, download file name and text, no expander without a template, no `_lg_` key) |
| `tests/test_exorcise_boundaries.py` | REQ-EX-06, 21, 22: no import of a model SDK, `ledger_kit` imports no app, app template modules import only `ledger_kit` and their own package |

The download is checked by wrapping `st.download_button` with a spy for the duration of the
AppTest run (AppTest has no typed element for it), which records `file_name`, `data` and `key`.

## 7 — Risks

- The word budget of the bank complaint grows with the number of fee rows (§5). Mitigation: the
  demo test, and a fixed part kept near 100 words.
- A Streamlit text area with a changed `value` under the same key keeps the old text; the language
  is therefore part of the key (§3).
- `st.download_button` reruns the script on click by default; `on_click="ignore"` avoids it (Streamlit
  1.43 and later; the pinned version is 1.67.0).
