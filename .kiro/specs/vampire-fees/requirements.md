# vampire-fees — Requirements

## Overview

`vampire-fees` is App 3 of Ghost Ledger Kit. It reads a **bank statement** (CSV or Norma 43) of an
individual or a small business and finds the **bank fees that drain the account**: recurring
maintenance, custody and card fees, fees that rise, the cost of an overdraft, and the total.

It exists to **measure the template claim**. The first two apps were built while the library was
still being written. This one is built *only from the finished template*, by the Kiro custom agent
`ghost-ledger-builder`, and it must need **no change** in `ledger_kit/` or in the other apps
(REQ-VF-04). If that turns out to be false, the design lists each change as an explicit decision
(design §11); it is never hidden.

The app is a pure consumer of `ledger_kit`: readers (`read_bank_statement`), `normalise`, the
registry (`register`, `run_all`), `money.py`, the explainer with its number guard, and the UI
helpers of `ledger_kit/ui/reference_app.py`. Everything else is in `apps/vampire_fees/`.

References: steering `finance-rules.md` (Rules 1 to 9), `structure.md`, `tech.md`, `testing.md`.
Section references (§) in this file point to `design.md`.

---

## Guiding principles (app-level)

1. **No invented figure.** Every number in an alert is copied from a source row or computed from
   source rows with `ledger_kit.utils.money` helpers and stored as a named key of `Alert.data`.
2. **Source refs on every alert.** Every alert cites every row that contributed to any of its
   figures. The summary alert cites every fee row of the statement.
3. **Thresholds are named constants** in `detectors/utils.py`, each with its reason (design §2).
   `config.toml` holds the fee **vocabulary** and the demo paths, never a threshold. A vocabulary is
   data, not a threshold: it decides what a row *is*, not how large or how often it must be.
4. **Neutral words.** Titles and templates state facts. No advice such as "close the account"
   (Finance Rule 8).
5. **Gross, not net.** A fee refund is a credit; credits are never fees and never reduce a total
   (REQ-VF-13). The app says so on the page.

---

## 1 — Scope and inputs

- **REQ-VF-01** The app shall read one bank statement per run, as CSV or Norma 43, through
  `ledger_kit.ingestion.sniffer.read_bank_statement`; the content, not the file extension, picks
  the reader. The app shall not contain a reader.
- **REQ-VF-02** When the user clicks **Load demo data**, the app shall load the committed demo
  statement in the format chosen in the **Demo format** radio (`CSV` or `Norma 43`). Both formats
  shall give the same alerts (REQ-VF-53).
- **REQ-VF-03** The app shall pass the whole normalised ledger, debits and credits, to the
  detectors. Each detector shall select its fee rows through one shared helper (`extract_fees`,
  design §4). Reason: the statement period of the summary is the span of *all* rows, and the
  credit rows are what proves that a refund is not a fee.
- **REQ-VF-04** The app, its tests and its demo shall need **no change** in `ledger_kit/`, in
  `apps/zombie_subscriptions/` or in `apps/phantom_invoices/`, and no new dependency. If the
  implementation finds a change to be unavoidable, the agent shall stop, record it as a decision
  `DN-VF-L<n>` in design §11 and ask the human; it shall not edit the library.
- **REQ-VF-05** The detectors shall be registered under the namespace `vf` with exactly these
  names: `vf.recurring_fee`, `vf.fee_increase`, `vf.overdraft_cost`, `vf.fee_summary`.

---

## 2 — Recognising a fee

A **fee row** is a row of the ledger that the classifier (design §4.2) accepts. Terms: *concept
tag* is the string `common_concept:<cc>` that the Norma 43 reader puts in `Transaction.tags`
(`ledger_kit/ingestion/norma43_reader.py`, `_transaction`); `<cc>` is the two-digit common concept
of record 22 (AEB Annex 2). The CSV reader sets no such tag.

- **REQ-VF-06** The classifier shall consider a row only when `flow == "debit"` and
  `currency == STATEMENT_CURRENCY` (`"EUR"`). Rows in another currency shall not be analysed; the
  page shall show how many were skipped. Reason: the explainer's `:money` format is EUR-only, and
  amounts in different currencies are never added.
- **REQ-VF-07** *Concept rule.* When a considered row has the tag `common_concept:17` (interest,
  fees and taxes) or `common_concept:16` (stamp duty and brokerage), the classifier shall accept it
  as a fee, whatever its words. The exclusion vocabulary (REQ-VF-08) shall not overrule a concept.
  The accepted concepts are the constant `FEE_CONCEPTS = ("16", "17")`.
- **REQ-VF-08** *Vocabulary rule.* When a considered row has no fee concept, the classifier shall
  accept it as a fee if the counterparty or the description contains a phrase of the `fee` or
  `overdraft` vocabulary, **unless** the counterparty or the description contains a phrase of the
  `exclude` vocabulary. An exclusion shall make the row not a fee.
- **REQ-VF-09** *CSV and other concepts.* A row without any concept tag (every CSV row) shall be
  classified by the vocabulary rule only. A row with a concept other than 16 or 17 (for example
  `12`, card purchase) shall also be classified by the vocabulary rule: a concept never vetoes a
  fee word (banks book fees under other concepts), and never creates a fee unless it is 16 or 17.
  The page shall state which rule applies to the loaded format.
- **REQ-VF-10** *Text matching.* Matching shall be accent-insensitive, case-insensitive and
  **whole-token**: the text is folded (NFKD, combining marks dropped, case-folded), every character
  that is not a letter or digit becomes a space, and the result is split into tokens. A phrase
  matches when its tokens appear consecutively. A fee word shall therefore not match inside another
  word (`fee` does not match `feelgood`, `comision` does not match `comisionista`).
- **REQ-VF-11** *Kind.* A fee row whose counterparty or description matches a phrase of the
  `overdraft` vocabulary shall have kind `overdraft`; every other fee row has kind `other`. An
  overdraft row whose text also matches a phrase of the `interest` vocabulary is an **overdraft
  interest**; any other overdraft row is an **overdraft fee**. The kind applies to rows accepted by
  the concept rule too.
- **REQ-VF-12** *Vocabulary in `config.toml`.* The vocabulary shall be read from the table
  `[vocabulary]` of `apps/vampire_fees/config.toml` with the keys `fee`, `overdraft`, `interest`
  and `exclude`, each a non-empty list of non-empty strings. `settings.load_vocabulary` shall raise
  `ValueError` naming the key when a key is missing, empty, or holds a non-string or a phrase with
  no letter or digit. The detectors receive the folded vocabulary as `context["vocabulary"]`; when
  it is absent they shall classify by concept only.
- **REQ-VF-13** *Credits.* A credit row shall never be a fee, even with concept 17 (a refund of a
  fee or interest paid to the customer). A refund shall not reduce any total, count or yearly cost;
  the app reports gross fees.
- **REQ-VF-14** *Duplicates.* When two rows carry the same `source_ref`, `extract_fees` shall keep
  the first and ignore the others.

**Default vocabulary** (design §2.3; Spanish and English; entries are folded on load):

| Key | Phrases |
|---|---|
| `fee` | comision, comisiones, cuota de mantenimiento, gastos, fee, fees, commission, commissions, maintenance |
| `overdraft` | descubierto, intereses deudores, overdraft |
| `interest` | intereses, interest |
| `exclude` | notaria, notario, notary, gestoria, abogado, lawyer, honorarios |

Why `exclude`: a payment to a notary, a lawyer or a gestor can say "gastos" (expenses) and is a
professional fee, not a bank fee. The decision is explained in design §3, DN-VF-04.

### Acceptance examples — classification

Rows are `(flow, currency, counterparty, description, tags)`. "→ fee" shows `(kind)`.

- **AE-VF-01** `(debit, EUR, "BANCO FICTICIO", "TARJ 0042", ["common_concept:17"])` → fee, kind
  `other` (concept rule). The same row with `tags = []` → **not a fee** (no concept, no word).
- **AE-VF-02** `(debit, EUR, "BANCO FICTICIO", "COMISIÓN MANTENIMIENTO", [])` → fee, kind `other`
  (accent and case folded). `(debit, EUR, "BANCO FICTICIO", "Commission foreign payment", [])` →
  fee, kind `other`.
- **AE-VF-03** `(debit, EUR, "Feelgood Market", "Card purchase", ["common_concept:12"])` → **not a
  fee**: the tokens are `feelgood`, `market`, `card`, `purchase`; `fee` is not a token.
- **AE-VF-04** `(debit, EUR, "Notaría Ana García", "Transferencia gastos escritura",
  ["common_concept:04"])` → **not a fee**: `gastos` matches `fee`, `notaria` matches `exclude`.
  The same row with `tags = ["common_concept:17"]` → fee (a concept is not overruled).
- **AE-VF-05** `(credit, EUR, "BANCO FICTICIO", "Devolución comisión transferencia",
  ["common_concept:17"])` → **not a fee** (credit).
- **AE-VF-06** `"Intereses deudores"` → fee, `overdraft` interest. `"Comisión por descubierto"` →
  fee, `overdraft` fee. `"Comisión mantenimiento cuenta"` → fee, kind `other`.
- **AE-VF-07** `(debit, EUR, "Gestoría Luigi Rossi", "Honorarios comisión", [])` → **not a fee**
  (`exclude` wins over `comision`). `(debit, USD, "BANCO FICTICIO", "Comisión", [])` → not
  considered (currency), counted as skipped.
- **AE-VF-08** `series_key("BANCO FICTICIO", "Comisión mantenimiento cuenta 05/26")` →
  `"banco ficticio|comision mantenimiento cuenta"` (tokens that contain a digit are dropped, so the
  month number does not split a series).

---

## 3 — `vf.recurring_fee`

- **REQ-VF-15** The detector shall group the fee rows of kind `other` by `series_key`
  (counterparty tokens, a vertical bar, description tokens; tokens containing a digit dropped).
  Overdraft rows shall not take part (they belong to `vf.overdraft_cost`, REQ-VF-24).
- **REQ-VF-16** Within a group ordered by `(date, source_row)`, the detector shall find the **run**:
  the longest suffix of consecutive rows whose date gaps all match one interval type. An interval
  type matches a gap when `abs(gap - nominal) <= tolerance`:

  | Interval | Nominal days | Tolerance | Periods per year |
  |---|---|---|---|
  | monthly | 30 | 3 | 12 |
  | quarterly | 91 | 3 | 4 |
  | yearly | 365 | 5 | 1 |

  The type is the one that matches the last gap of the group. A group whose last gap matches no
  type has no run.
- **REQ-VF-17** A run shall be reported only if it has at least `MIN_CHARGES[interval]` rows:
  monthly 3, quarterly 2, yearly 2. Reason: two monthly charges can be a coincidence; a quarterly
  or yearly fee can only be seen once or twice in a statement of normal length.
- **REQ-VF-18** For each run the detector shall emit one alert with `severity` per REQ-VF-19, the
  `source_refs` of **every row of the run**, and the `data` keys of design §5.1 including
  `yearly_cost = round_to_cents(current_amount * periods_per_year)`, where `current_amount` is the
  amount of the last row of the run.
- **REQ-VF-19** The severity shall be `warning` when `yearly_cost >= RECURRING_FEE_WARNING_YEARLY_COST`
  (60.00) and `info` otherwise.
- **REQ-VF-20** A row earlier than the run (for example one outlier) shall not be cited and shall
  not change the figures; it still counts in the summary (REQ-VF-27).

### Acceptance examples — recurring fee

Each uses counterparty `BANCO FICTICIO`, description `Comisión mantenimiento cuenta`, file `s.csv`.

- **AE-VF-09** Debits of 5.00 on 2026-01-05, 2026-02-05, 2026-03-05 (gaps 31 and 28): one alert;
  `severity = "warning"` (5.00 × 12 = 60.00, the boundary is inclusive); `data`:
  `interval_type "monthly"`, `charge_count 3`, `current_amount "5.00"`, `yearly_cost "60.00"`,
  `first_charge_date "2026-01-05"`, `last_charge_date "2026-03-05"`.
- **AE-VF-10** Same dates with 4.99: `yearly_cost "59.88"`, `severity "info"`.
- **AE-VF-11** Only 2026-01-05 and 2026-02-05 (two monthly charges): **no alert**. Add 2026-03-05:
  one alert.
- **AE-VF-12** Gaps of 33 days (2026-01-01, 2026-02-03, 2026-03-06 → 33 and 31): monthly run of 3.
  Gaps of 34 days (2026-01-01, 2026-02-04, 2026-03-07): **no alert** (34 is outside 30 ± 3).
- **AE-VF-13** An outlier 2025-10-01 followed by 2026-01-05, 2026-02-05, 2026-03-05 (first gap 96
  days, outside every interval): one alert citing the three later rows only.
- **AE-VF-14** Debits of 9.00 on 2026-03-31, 2026-06-30, 2026-09-30 (gaps 91 and 92): quarterly
  run of 3; `yearly_cost "36.00"`, `severity "info"`.
- **AE-VF-15** Debits of 30.00 on 2025-02-14 and 2026-02-16 (gap 367): yearly run of 2;
  `yearly_cost "30.00"`.
- **AE-VF-16** Four commissions at gaps of 104, 196 and 205 days: **no alert** (last gap matches
  no interval).

---

## 4 — `vf.fee_increase`

- **REQ-VF-21** For each run of REQ-VF-16, the detector shall look for the **latest rise**: the
  latest position `i` of the run with `amount[i] - amount[i-1] >= amount[i-1] * FEE_INCREASE_MIN_RATIO`
  (0.05) such that every later row of the run has an amount within `FEE_STABLE_RATIO` (0.02) of
  `amount[i]` (the new level holds; a single spike does not count). The detector shall emit one alert
  per run that has a rise.
- **REQ-VF-22** The alert shall cite exactly two rows: the last row at the old level
  (`amount[i-1]`) and the first row at the new level (`amount[i]`). Its `data` keys are in design
  §5.2; `increase_percent` is `str(round_percent(percent_change(old, new)))`, `extra_cost_per_year =
  round_to_cents((new - old) * periods_per_year)` and `yearly_cost = round_to_cents(new *
  periods_per_year)`.
- **REQ-VF-23** The severity shall be `critical` when
  `new - old >= old * FEE_INCREASE_CRITICAL_RATIO` (0.50) and `warning` otherwise.

### Acceptance examples — fee increase

- **AE-VF-17** Monthly debits 5.00 (2025-11-05), 5.00 (2025-12-05), 5.00 (2026-01-05), 5.25
  (2026-02-05): one `vf.fee_increase`, `warning`, `old_amount "5.00"`, `new_amount "5.25"`,
  `increase_percent "5.0"`, `increase_date "2026-02-05"`, `old_charge_date "2026-01-05"`,
  `extra_cost_per_year "3.00"`, `yearly_cost "63.00"`, `interval_type "monthly"`; `source_refs` are
  the rows of 2026-01-05 and 2026-02-05. With 5.24 instead of 5.25: **no** `vf.fee_increase`
  (`vf.recurring_fee` still fires).
- **AE-VF-18** Same series ending in 7.50: `severity "critical"` (7.50 - 5.00 = 2.50 = 5.00 × 0.50);
  ending in 7.49: `warning`.
- **AE-VF-19** Monthly 5.00, 5.00, 9.00, 5.00: **no** `vf.fee_increase` (the new level 9.00 does not
  hold: 5.00 is not within 2 % of 9.00; the step 9.00 → 5.00 is a fall).
- **AE-VF-20** Demo case: 12 charges of 5.00 (2025-01-05 to 2025-12-05) then 10 of 6.50 (2026-01-05
  to 2026-10-05): `old_amount "5.00"`, `new_amount "6.50"`, `increase_percent "30.0"`,
  `increase_date "2026-01-05"`, `old_charge_date "2025-12-05"`, `extra_cost_per_year "18.00"`,
  `yearly_cost "78.00"`, `severity "warning"`.

---

## 5 — `vf.overdraft_cost`

- **REQ-VF-24** The detector shall consider the fee rows of kind `overdraft` (interest and fees)
  and emit **one** alert for the statement when there is at least one.
- **REQ-VF-25** The alert shall cite **every overdraft row** and carry the counts and totals of
  design §5.3: `interest_count`, `interest_total`, `fee_count`, `fee_total`, `total` (equal to
  `interest_total + fee_total`, computed from the rows with `sum_amounts`), `first_charge_date`,
  `last_charge_date`.
- **REQ-VF-26** The severity shall be `critical` when `total >= OVERDRAFT_CRITICAL_TOTAL` (100.00)
  and `warning` otherwise. An overdraft is never `info`: it is the most expensive way to borrow
  from a bank, and its mere presence is worth showing.

### Acceptance examples — overdraft

- **AE-VF-21** Debits "Intereses deudores" 12.40 (2025-06-30) and "Comisión por descubierto" 15.00
  (2025-06-18): one alert, `warning`; `interest_count 1`, `interest_total "12.40"`, `fee_count 1`,
  `fee_total "15.00"`, `total "27.40"`, `first_charge_date "2025-06-18"`,
  `last_charge_date "2025-06-30"`.
- **AE-VF-22** Interest 60.00 + fee 40.00 → `total "100.00"`, `critical`; interest 60.00 + fee
  39.99 → `total "99.99"`, `warning`.
- **AE-VF-23** A statement with no overdraft row → no `vf.overdraft_cost` alert.

---

## 6 — `vf.fee_summary`

- **REQ-VF-27** The detector shall emit **one** alert when the statement has at least one fee row,
  with `total_fees` = the sum of all fee rows (every kind, recurring or not) and `fee_count`.
- **REQ-VF-28** The alert shall cite **every fee row**, ordered by `(date, source_row)`.
- **REQ-VF-29** `first_date`, `last_date` and `span_days` describe the statement period: the first
  and last date of **all** considered (EUR) rows, credits included, and
  `span_days = (last_date - first_date).days + 1`. When `span_days >= SUMMARY_MIN_SPAN_DAYS` (90),
  the alert shall carry `yearly_equivalent = round_to_cents(total_fees * DAYS_PER_YEAR / span_days)`
  with `DAYS_PER_YEAR = 365`. Otherwise it shall carry **no** `yearly_equivalent` key (Finance
  Rule 1: a yearly figure from a few weeks of data would be an estimate).
- **REQ-VF-30** The severity shall be `warning` when `yearly_equivalent` is present and
  `>= SUMMARY_WARNING_YEARLY_EQUIVALENT` (200.00) and `info` otherwise.

### Acceptance examples — summary

- **AE-VF-24** Fees 10.00 (2026-01-10) and 20.00 (2026-03-10); other rows make the statement run
  2026-01-01 to 2026-03-31: `fee_count 2`, `total_fees "30.00"`, `first_date "2026-01-01"`,
  `last_date "2026-03-31"`, `span_days 90`, `yearly_equivalent "121.67"` (30.00 × 365 / 90 =
  121.666…), `severity "info"`.
- **AE-VF-25** Same fees, statement 2026-01-01 to 2026-03-30: `span_days 89`, **no**
  `yearly_equivalent`, `severity "info"`.
- **AE-VF-26** One fee of 200.00 and a statement of exactly 365 days: `yearly_equivalent
  "200.00"`, `severity "warning"`; fee 199.99: `"199.99"`, `info`.

---

## 7 — Alert contract

- **REQ-VF-31** Every alert shall have a non-empty `source_refs` list with unique entries, each the
  `source_ref` of a loaded row, ordered by `(date, source_row)` (never by text).
- **REQ-VF-32** `Alert.data` shall hold only `str`, `int` and `list[str]` values. Money and rates
  are `str(Decimal)` with two decimals (`str(round_to_cents(x))`), dates are ISO strings, counts
  are `int`. A key that cannot be stated honestly (REQ-VF-29) is absent, not `None`.
- **REQ-VF-33** All money arithmetic shall use `Decimal` and `ledger_kit.utils.money`
  (`round_to_cents`, `sum_amounts`, `percent_change`, `round_percent`). No `float`.
- **REQ-VF-34** A detector shall return `[]` for an empty ledger, a ledger without fee rows and a
  ledger whose only rows are credits; it shall never raise on a one-row ledger, a missing `tags`
  value (`None` or NaN) or a duplicate `source_ref`. Two runs on the same input shall return equal
  alerts.
- **REQ-VF-35** Detectors shall be pure functions `(ledger, context) -> list[Alert]` with no I/O
  and no clock.

---

## 8 — Explanation

- **REQ-VF-36** `explain_support.TEMPLATES` shall hold a fallback template for every detector and
  `template_for(alert)` shall choose the summary variant by the presence of `yearly_equivalent`.
  Every placeholder of every template shall be a key of the alert's `data` (or `source_refs`).
- **REQ-VF-37** The app shall explain each alert with `explain_with_meta(alert, rows,
  fallback_template=template_for(alert), client=client)`, cached per `(alert.id, client mode)`.
  Without an API key the filled template is shown.
- **REQ-VF-38** *Hallucinating switch.* The sidebar toggle **Simulate a hallucinating LLM** shall
  replace the client with `HallucinatingStubClient`, whose answer states `99999.99 EUR`. The number
  guard shall reject it, the card shall show the filled template and the badge
  `⚠️ LLM answer rejected: invented number 99999.99`. Badge labels are those of the other apps.
- **REQ-VF-39** A template accepted as a stub "LLM" answer shall pass the guard (`source == "llm"`,
  no rejected numbers) for every alert of the demo.

**Templates** (design §6): each is neutral, cites `{source_refs}` and contains no digit.

### Acceptance example — explanation

- **AE-VF-27** The `vf.fee_summary` alert of AE-VF-24 with refs `s.csv:3` and `s.csv:5` fills to:
  `Between 2026-01-01 and 2026-03-31 (90 days) your statement shows 2 bank fees totalling 30,00 EUR,
  about 121,67 EUR per year. Source: s.csv:3, s.csv:5.`
  The AE-VF-25 alert fills the variant without the yearly sentence:
  `Between 2026-01-01 and 2026-03-30 (89 days) your statement shows 2 bank fees totalling 30,00
  EUR. Source: s.csv:3, s.csv:5.`

---

## 9 — The page

Theme: the shared dark Halloween theme (`.streamlit/config.toml`, not edited) with a **vampire**
accent in the app's own CSS block: dark red `#9b1c31`, brighter `#c2334d`, blood-dark card
background `#2a0f16`. Page title `🧛 Vampire Fees`.

- **REQ-VF-40** The page shall show one **coffin card** per `vf.recurring_fee` alert. A card shows
  the counterparty, the fee description, the interval ("every month", "every quarter", "every
  year"), the current amount and **"Drains <yearly_cost> a year"**, and a collapsible list of its
  source refs. Every figure of a card shall be read from `alert.data` and formatted with
  `format_amount`; the card shall compute nothing. An empty set of coffins shall show a caption.
- **REQ-VF-41** The coffin shape shall be drawn with CSS only (a `clip-path` polygon), every text
  inserted into the HTML shall be escaped with `html.escape`, and the cards shall be laid out three
  per row.
- **REQ-VF-42** The page shall show a metrics row from the `vf.fee_summary` alert data: fees found
  (`fee_count`), total fees (`total_fees`) and the yearly equivalent (`yearly_equivalent`, or "n/a"
  when the key is absent), plus the alert counts per severity (helpers of `reference_app.py`).
- **REQ-VF-43** The alerts shall be listed grouped critical, warning, info. Each alert card shows
  the title, detector, severity, the explanation, the guard badge, the `Source refs:` line, and an
  expander with the cited rows (`rows_for_refs`, `format_for_display`).
- **REQ-VF-44** The sidebar shall hold the **Demo format** radio, the **Load demo data** button
  (an `on_click` callback), the hallucination toggle and one uploader (`.csv`, `.n43`, `.txt`,
  `.aeb`, `.csb43`). A read-only expander shall list the fee vocabulary in use.
- **REQ-VF-45** Under the title the page shall show the statement caption (file, detected format,
  rows analysed, quarantined, skipped for currency) and one sentence on the rule in force: for CSV
  "A CSV has no bank concept: fees are recognised by words only."; for Norma 43 "Bank concepts 16
  and 17 are fees; other rows are recognised by words."; and always "Refunds are not subtracted."
- **REQ-VF-46** Quarantined rows and `control_check_messages` shall be shown as in the other apps.
- **REQ-VF-47** All session-state keys shall start with `vf_`. Widget values shall be kept and
  restored so that a visit to another page of the showcase does not reset them.
- **REQ-VF-48** Without a loaded statement the page shall show an `st.info` explaining how to load
  the demo or upload a file.

---

## 10 — Demo data

- **REQ-VF-49** `scripts/generate_samples.py` shall get a mode `vampire-demo` that writes
  `data/samples/vampire_demo_statement.csv` and `data/samples/vampire_demo_statement.n43` from the
  same rows for `--seed` (default 42), through `render_bank_csv` and `render_norma43`. Same seed,
  same bytes. Existing modes and their output shall not change.
- **REQ-VF-50** The statement shall run from 2025-01-02 to 2026-10-30 and hold the planted cases of
  design §7 as **literal tables** plus seeded noise (six card purchases per month, shops that
  contain no vocabulary phrase). The seed shall drive only the noise.
- **REQ-VF-51** The demo shall plant these **hard negatives**, each of which must raise no fee
  alert and no fee row:
  1. `Feelgood Market`, a card purchase whose name contains `fee` only inside a word;
  2. a credit "Devolución comisión transferencia" (refund of a fee; credit, concept 17);
  3. a credit "Abono intereses" (interest paid to the customer; credit, concept 17);
  4. a transfer to a notary, "Transferencia gastos escritura" (`gastos` matches, `notaria` excludes);
     reason: a notary's fee is a professional fee, not a bank fee, whether or not it recurs;
  5. a monthly "Monthly subscription" debit that is recurring but is not a fee.
  And these **fees that must not become a recurring alert**: four irregular "Comisión
  transferencia inmediata" and two "Comisión emisión cheque" 30 days apart (below the monthly
  minimum). They count in the summary only.
- **REQ-VF-52** The end-to-end test shall pin the demo result **literally** (design §7.3): 6 alerts
  (1 critical, 3 warning, 2 info), the figures of every alert, the 45 fee rows of the summary, and
  227 rows read, 202 debit rows, 0 quarantined, for both formats.
- **REQ-VF-53** The CSV demo and the Norma 43 demo shall give alerts that are equal in detector,
  severity, title and `data`, and equal in the number of `source_refs`. Their `source_refs` differ
  by file name and row index (CSV 0-based data rows, Norma 43 record-22 line numbers) and so do the
  alert ids. Every demo fee row shall be recognised by its words as well as by its concept, which
  is what makes the equality true; the concept-only path is covered by unit tests, not by the demo.
- **REQ-VF-54** All demo data shall be synthetic (Finance Rules 5 and 6): the bank is
  `BANCO FICTICIO`, names are fictional, no IBAN appears.

---

## 11 — Showcase integration

- **REQ-VF-55** `streamlit_app.py` shall list the page "Vampire Fees" (icon 🧛, `url_path`
  `vampire-fees`, script `apps/vampire_fees/app.py`) after Phantom Invoices and before Benchmark,
  and the Home page shall describe three apps. The entry page shall still import no app.
- **REQ-VF-56** The tests that pin the page list and the Home text shall be updated in the same
  change (`tests/test_showcase_app.py`, `tests/test_showcase_requirements.py`).
- **REQ-VF-57** `.kiro/steering/structure.md` (layout tree), `.kiro/steering/testing.md`
  (coverage command), `README.md` (apps table), `data/samples/README.md` and `.gitattributes`
  (byte-compared demo CSV) shall be updated with the new app and demo files, and nothing else in
  them.

---

## 12 — Measuring the template claim

- **REQ-VF-58** The implementation shall touch only these paths outside `apps/vampire_fees/`:
  `scripts/generate_samples.py`, `data/samples/vampire_demo_statement.*`,
  `data/samples/README.md`, `streamlit_app.py`, `tests/test_showcase_app.py`,
  `tests/test_showcase_requirements.py`, `tests/test_generate_samples.py`, `README.md`,
  `.gitattributes`, `.kiro/steering/structure.md`, `.kiro/steering/testing.md` and
  `.kiro/specs/vampire-fees/`. It shall touch nothing under `ledger_kit/`,
  `apps/zombie_subscriptions/` or `apps/phantom_invoices/`, nor `pyproject.toml`,
  `requirements.txt` or `.streamlit/config.toml`.
- **REQ-VF-59** `tasks.md` shall end with a record, filled in by the reviewer, of the number of
  Kiro calls, the elapsed time, the human interventions and the result of the boundary command
  (`git status --short ledger_kit apps/zombie_subscriptions apps/phantom_invoices`, expected: no
  output).
- **REQ-VF-60** Any code the app copies from another app because the library does not offer it
  (the stub client, the guard badge, `markdown_safe`) shall be listed in design §11 as a decision,
  with a note that the library could offer it. Copying is allowed; hiding it is not.

---

## 13 — Testing

- **REQ-VF-61** Every detector shall have the three test tiers of `testing.md`, including a
  Hypothesis `@settings(max_examples=200)` no-invention property with
  `loaded_source_refs(ledger, context)`, an idempotency property, an empty-input property and a
  property that `fee_summary.total_fees` equals the sum of the cited rows.
- **REQ-VF-62** The classifier shall have a property test: a credit row is never a fee, and a
  row whose text has no vocabulary phrase and no concept tag is never a fee.
- **REQ-VF-63** No test shall read the clock or the network; every fixture shall be synthetic.
- **REQ-VF-64** A static test shall prove that no module under `apps/vampire_fees/` imports another
  app or a private (`_name`) name of `ledger_kit`, and that `config.toml` contains none of the
  threshold constant names.
