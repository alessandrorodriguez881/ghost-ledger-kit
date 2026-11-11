# exorcise — Requirements

## Overview

The kit finds the leak and explains it. A person or a small business still has to *act*: write to
the merchant, the supplier or the bank. `exorcise` turns each alert into the draft of that real
action, so the kit is a product and not only a proof.

Every alert card of the three apps gets a collapsed expander **Exorcise: prepare the action**. It
holds a language choice (English or Español), the draft in a read-only text area, a download
button for a `.txt` file and one line saying the draft is to be reviewed and is not legal advice.

The draft is **not written by a language model**. It is built only from the alert fields, the
cited source rows and fixed templates, so it works without a key and cannot invent a figure. As a
second line of defence every draft is checked at run time by the **same number guard** that checks
a model answer (`ledger_kit.explainer`); a draft that fails is not shown.

It changes no detector, no figure, no alert text, no number-guard rule, no existing widget key, no
line of the live call or of the replay, and adds no dependency.

Ids are `REQ-EX-nn`. EARS keywords: *shall*, *when*, *while*, *where*, *if ... then*. All data in
examples is **(synthetic)**: the three demo statements and invoice sets of `data/samples/`.

## Shared vocabulary

- **Template**: the fixed texts of one alert type, one per language, with `{placeholders}`.
- **Draft**: a template filled for one alert in one language.
- **Placeholder in square brackets**: text such as `[Your name]` that the user fills in. It holds
  no digit and no personal data.
- **Guard check**: `ledger_kit.explainer.check_figures(draft, alert, rows, row_columns)`, the number
  guard on a text that is not a model answer, with the same narrowing of rows that the card uses.
- **Cited rows**: the rows of the user's files named by `Alert.source_refs`.

---

## 1 — The expander

- **REQ-EX-01** *While* an alert has a template, its card shall show, after the source rows and
  before the *Provoke the LLM* panel, one expander titled `Exorcise: prepare the action`, collapsed
  by default. *While* an alert type has no template, its card shall show no such expander.
  - Example: Zombie demo, alert `zs.charges_after_cancellation` (GYMPLUS) → the expander is there.
  - Example: Phantom demo, an `pi.reconciliation` alert or a `pi.iban_change` alert of variant
    `iban_invalid` → no expander. Vampire demo, `vf.fee_summary` → no expander.

- **REQ-EX-02** Inside the expander the system shall show, in this order: a radio **Language** with
  the options `English` and `Español` (default `English`); the draft in a read-only text area; a
  download button; one caption that says the text is a draft to review and not legal advice, in the
  language chosen.
  - Example: caption `This is a draft to review, not legal advice.` / `Este es un borrador para
    revisar, no es asesoramiento legal.`

- **REQ-EX-03** *When* the user chooses the other language, the draft, the caption and the download
  shall change to that language at once. The choice shall belong to the card: another card keeps
  its own.

- **REQ-EX-04** The download button shall offer the text of the draft shown, as a UTF-8 `.txt` file
  named `exorcise-<detector>-<language>-<alert id, first 8 characters>.txt`, where `<detector>` is
  the detector name with every `.` and `_` written as `-` and `<language>` is `en` or `es`.
  - Example: `exorcise-zs-charges-after-cancellation-en-1a2b3c4d.txt`.

- **REQ-EX-05** The new widgets shall have keys with the app prefix and the alert id:
  `<prefix>_ex_lang_<id>`, `<prefix>_ex_text_<id>_<lang>`, `<prefix>_ex_dl_<id>_<lang>`
  (`zs`, `pi`, `vf`). No key contains `_lg_`.

## 2 — The draft is built, never written by a model

- **REQ-EX-06** The system shall build a draft only from `Alert.data`, the cited rows and the fixed
  templates of the alert type. It shall call no language model, read no API key and open no
  connection, so it works without a key and with the replay off.
  - Example: with `OPENAI_API_KEY` unset and `sys.modules["openai"] = None`, the draft is the same.

- **REQ-EX-07** *Where* a draft cites an amount, a percentage or a count of the alert, it shall
  write it as the card writes it (European format of `ledger_kit/utils/money.py`, `1.234,56 EUR`,
  `5,0 %`), and a date as ISO text (`2026-07-31`), so that the figure can be found on the card.
  The mechanism shall do no monetary arithmetic: it only formats values that are already in the
  alert or in the cited rows.

- **REQ-EX-08** A template shall hold no digit, no month name, no deadline and no legal article
  number. The sender's own details shall be placeholders in square brackets; a draft shall hold no
  personal data and no full IBAN, only the masked IBANs that the alert carries.

- **REQ-EX-09** A draft shall be short: under **150 words** (words are the pieces between spaces)
  for every alert of the three demos, in both languages. A draft grows by three words for each
  cited row it lists, and the templates leave room for twelve.

## 3 — The guard check at run time

- **REQ-EX-10** `ledger_kit/explainer.py` shall offer the public function
  `check_figures(text, alert, rows, row_columns=None) -> (passed, rejected_tokens)`. It shall call
  the number guard exactly as `explain_with_meta` does (same narrowing of the rows) and change no
  rule of it.
  - Example: `check_figures("It costs 98765,43 EUR.", alert, rows)` → `(False, ("98765,43",))`.

- **REQ-EX-11** *Before* a draft is shown, the system shall run the guard check on it. *If* the
  check rejects a token, or the template cannot be filled (a missing key, a value that is not a
  number where a number is needed), *then* the expander shall show, instead of the draft and the
  download button, the short message `This draft is not available: a figure in it could not be
  checked against the cited rows.` (or its Spanish form) and the system shall log one warning with
  the alert id and the tokens. The page shall not raise.
  - Example: a template that writes `99999.99` → message, no text area, no download, one warning.

- **REQ-EX-12** A test shall build the draft of **every alert of the three demos** (CSV demos and
  the phantom demo) in **both languages** and prove for each: the draft exists for every alert
  type that has a template and for no other; the guard check passes; the draft is under 150 words;
  it holds the figures that the alert type lists in section 4 as the card writes them; it holds no
  IBAN-shaped token and none of the full IBANs of the demo files.

## 4 — Drafts per alert type

In every case the first lines are a subject and a salutation, then the body, then
`[Your name]` and one more placeholder for the sender's reference.

### Zombie Subscriptions

- **REQ-EX-13** `zs.charges_after_cancellation`: a **refund request** to the merchant that cites
  the cancellation date, the number of charges after it, the total, and **each** charge after it
  (`date: amount`), and asks for a refund and a written confirmation that the subscription is
  closed; then a **one-paragraph request to the bank** to dispute the charges listed.
  - Example (en): `I cancelled my subscription on 2026-07-31. You have charged me 2 times since
    then, totalling 17,98 EUR:` then `2026-08-09: 8,99 EUR` and `2026-09-08: 8,99 EUR`.
- **REQ-EX-14** `zs.duplicate_subscription`: a request to **cancel the duplicate account**, naming
  the service, the number of accounts, the account names found and the yearly cost.
- **REQ-EX-15** `zs.price_increase`: a request to **keep the old price or cancel**, citing the old
  and the new amount and the extra yearly cost; *when* the alert carries the CPI keys, the draft
  shall add the CPI sentence that the card shows (same figures, same months, same series), in the
  language of the draft; without CPI keys it shall add nothing.
- **REQ-EX-16** `zs.free_trial_to_paid` and `zs.recurring_charge`: a **cancellation request**
  citing the amounts of the alert (trial and first paid amount; current amount and yearly cost).

### Phantom Invoices

- **REQ-EX-17** `pi.duplicate_invoice` (all three variants): an **e-mail to the supplier** that
  lists each invoice (`number: total`), gives the issue dates and asks to cancel the duplicate or
  to issue a **credit note (factura rectificativa)**, and to confirm which invoice stays payable.
- **REQ-EX-18** `pi.iban_change`, variants `invoice_iban_differs_from_master` and
  `payment_to_non_master_iban`: an **internal hold note** (what differs, with the masked IBANs only,
  and that nobody pays or releases a payment before the change is verified and approved) and a
  **phone script** to verify the change with a contact **already on file** for the supplier. The
  script shall say never to use a phone number or an e-mail address printed on the invoice or in the
  message that announced the change.
- **REQ-EX-19** `pi.vat_error`, variants `vat_amount_mismatch` and `total_mismatch`: a **request
  for a corrected invoice** that cites the invoice number and the figures of the alert (stated and
  expected VAT; stated and expected total) and asks for a *factura rectificativa*.
  Variant `vat_rate_not_allowed` has no template.

### Vampire Fees

- **REQ-EX-20** `vf.recurring_fee`, `vf.fee_increase` and `vf.overdraft_cost`: a **complaint to the
  bank** that asks to waive or refund the fees, cites **each** fee row (`date: amount`) and the
  figures of the alert, and is addressed to the bank's customer service department
  (`Customer Service Department (Servicio de Atención al Cliente)`). It shall end with **one line**
  saying that, if the bank does not resolve the complaint, the customer can go to the Banco de
  España complaints service. It shall name no deadline and no article of any law.
  `vf.fee_summary` has no template.

## 5 — Boundaries and non-regression

- **REQ-EX-21** The mechanism shall live in `ledger_kit/actions.py` (pure: no Streamlit, no I/O,
  no clock, no model) and the widget in `ledger_kit/ui/exorcise.py`. Each app shall hold its
  templates in one module, `apps/<app>/action_templates.py`, that imports `ledger_kit` public
  names and its own package only. `ledger_kit` shall import no app.
- **REQ-EX-22** The change shall add no dependency and change no detector, figure, threshold,
  number-guard rule, alert text, existing widget key, line of the live call or of the replay, and
  every existing test shall stay green except the tests that pin the file lists of the steering
  structure (listed in `tasks.md`).
