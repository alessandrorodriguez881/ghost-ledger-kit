# phantom-invoices — Requirements

## Overview

`phantom-invoices` is App 2 of Ghost Ledger Kit. It targets **small Spanish businesses and their
accountants** who want to audit supplier invoices before (and after) paying them: invoices that
arrive twice, suppliers whose bank account suddenly changes, VAT arithmetic that does not add up,
invoices that were never paid and payments that match no invoice.

The app is a **deterministic detector layer** built on top of `ledger-core`. It imports
`ledger_kit` (models, ingestion, registry, money helpers, explainer) and changes nothing in that
package except through the ledger-core change request **CR-LC-3** (section 14), which this spec
raises and which has already been applied to the ledger-core spec files. All user-facing output
is produced by `apps/phantom_invoices/`.

Detector namespace: `pi` (registered names `pi.duplicate_invoice`, `pi.iban_change`,
`pi.vat_error`, `pi.reconciliation`). Test files are prefixed `test_pi_`.

This document contains requirements only. `design.md` follows it; `tasks.md` follows after review
of the design. All open decisions of section 16 are resolved.

---

## Guiding principles (app-level)

1. **Deterministic, no model.** Every alert is produced by plain Python rules with named
   thresholds. No fuzzy matching, no edit distance, no scoring. Spanish law requires consecutive
   invoice numbers, so two numbers that differ by one character are *not* evidence of a duplicate.
2. **No invented figures.** Every number, date and name in an alert or explanation is copied
   verbatim from a source row or computed deterministically from source rows with
   `ledger_kit.utils.money` helpers only (`percent_of`, `within_tolerance`, `net_total`,
   `round_to_cents`). No detector performs monetary arithmetic itself (REQ-MON-03).
3. **Same result on every day.** "Today" is never read from the clock. `as_of` defaults to the
   latest date present in the loaded invoices and payments (REQ-PI-12), so the demo gives the same
   result on every day of judging.
4. **Row order never matters.** Rows are processed sorted by `(date, source_ref)` and the members
   of any pair or group are stored in `Alert.data` ordered by `source_ref` (REQ-PI-10), so
   shuffling the input never changes any result.
5. **A detector never raises on dirty data.** Empty cells read as `NaN`, hyphens, non-breaking
   spaces and wrong types are skipped (or flagged by the rule that is about them). `run_all` would
   otherwise drop every alert of a detector that raised (REQ-REG-04).
6. **Source refs on every alert**, and they may point to any loaded input: an invoice, a
   supplier-master row or a bank payment (CR-LC-3d, REQ-DET-04).
7. **Everything a template may say is in `Alert.data`** (REQ-DET-09): days apart, rates, counts,
   expected and stated amounts. IBANs appear in `Alert.data` only masked to the last 4 characters,
   never in full (REQ-PII-03/04).
8. **The LLM explains; it never decides.** It cannot raise, dismiss or re-rank an alert, and
   Finance Rule 8 applies in full.

---

## 1 — Scope and inputs

- **REQ-PI-01** The app works on three inputs, all file-based:

  | Input | Reader (ledger-core) | Canonical frame | Role |
  |---|---|---|---|
  | `invoices.csv` (or `.json`) | `parse_invoice` → `Invoice` (REQ-ING-30/31) | `normalise(..., kind="invoice")` | **The ledger** passed to every detector |
  | `suppliers.csv` | `parse_suppliers` → `Supplier` (REQ-ING-32) | `normalise(..., kind="supplier")` | The supplier master (`context["suppliers"]`) |
  | `payments.csv` | `parse_csv` → `Transaction` incl. `iban` (REQ-ING-29) | `normalise(...)` | Bank payments (`context["payments"]`) |

  Ingestion is delegated entirely to `ledger_kit.ingestion`; the app must not re-implement CSV
  parsing or normalisation.
- **REQ-PI-02** The detector call is
  `run_all(invoices, namespace="pi", context=ctx)` with
  `ctx = {"suppliers": DataFrame, "payments": DataFrame, "as_of": date | None}`.
  `run_all` wraps `ctx` in a read-only `MappingProxyType`; detectors never mutate it or the
  frames inside it. `suppliers` and `payments` are always DataFrames with their canonical columns
  (possibly empty); `as_of` may be `None` (REQ-PI-12). A detector must also accept a context with
  missing keys (for example `MappingProxyType({})`, as in the `testing.md` empty-ledger case): a
  missing `suppliers` or `payments` key is treated as an empty frame, a missing `as_of` as `None`.
- **REQ-PI-03** Payments: the app passes the full normalised bank frame; each detector filters it
  to `flow == "debit"` itself (credits are ignored). A payment's amount is `Transaction.amount`
  (always positive, REQ-ING-24) and is compared with `Invoice.total`.
- **REQ-PI-04** All three inputs may be supplied by upload, or by the **Load demo data** button
  (REQ-PI-52). Suppliers and payments are optional: without a supplier master `pi.iban_change`
  can only report malformed IBANs and `pi.reconciliation` treats every invoice as unpaid-so-far
  (see REQ-PI-37); the UI shows a notice saying which checks need which file.
- **REQ-PI-05** Currency: only rows with equal `currency` values are ever compared or matched
  (amount matching in REQ-PI-37). No currency conversion exists.

---

## 2 — Shared conventions (all four detectors)

### 2.1 Normalisation helpers

All helpers are pure functions in `apps/phantom_invoices/detectors/utils.py` and are covered by
`test_pi_utils.py`.

- **REQ-PI-06** **Missing value.** A cell is *missing* when it is `None`, `NaN`, `pd.NA`, or a
  string that is empty after removing all whitespace (including non-breaking spaces `\u00a0`) or
  that consists only of hyphen/dash characters (`-`, `–`, `—`). Every reader helper
  (`as_text`, `as_decimal`, `as_date`) returns `None` for a missing or wrongly typed cell and
  **never raises**. `as_decimal` accepts only a finite `Decimal`; `as_date` accepts `datetime.date`
  and `pd.Timestamp` (converted to a date). A check that needs a cell that is `None` is skipped
  for that row.
- **REQ-PI-07** **Invoice-number keys.**
  - `N1(number)` = uppercase the text and remove every non-alphanumeric character.
  - `N2(number)` = uppercase the text; replace every maximal run of digits **of the original
    text** by the same run without its leading zeros (a run of only zeros becomes `"0"`); then
    remove every non-alphanumeric character. Digit runs are delimited by any non-digit character,
    including hyphens and letters, which is why `F-2026-0042` and `F2026-042` both give `F202642`
    while their `N1` values (`F20260042`, `F2026042`) differ.
  - An empty `N1` (for example the number `"---"`) makes the row ineligible for the duplicate
    detector (skipped).

  | Number | N1 | N2 |
  |---|---|---|
  | `F-2026-0042` | `F20260042` | `F202642` |
  | `F2026-042` | `F2026042` | `F202642` |
  | `f-2026-0042` | `F20260042` | `F202642` |
  | `ALQ-2026-01` | `ALQ202601` | `ALQ20261` |
  | `ALQ-2026-02` | `ALQ202602` | `ALQ20262` |
  | `F-000` | `F000` | `F0` |

- **REQ-PI-08** **Identifier keys.**
  - `tax_key(x)` = uppercase, remove every non-alphanumeric character (`"b-00000001"` →
    `B00000001`). Two rows are *the same supplier* when their `tax_key` is equal and non-empty;
    rows with an empty `tax_key` are skipped by the supplier-based rules.
  - `name_key(x)` = uppercase, Unicode NFKD, drop combining marks, remove every non-alphanumeric
    character (`"Suministros García, S.L."` → `SUMINISTROSGARCIASL`).
  - `iban_key(x)` = remove **all** whitespace (including `\u00a0`) and uppercase. Hyphens are not
    removed.
- **REQ-PI-09** **Supplier master lookup.** The master is keyed by `tax_key(tax_id)`. When several
  master rows share a key, the first in `source_ref` order is used and the others are ignored.
  An invoice maps to the master through `tax_key(supplier_tax_id)`; an invoice whose supplier is
  not in the master has no master (checks that need it are skipped; reconciliation still treats
  the invoice, REQ-PI-37).
- **REQ-PI-10** **Deterministic order.**
  - Invoices are processed sorted by `(issue_date, source_ref)`, payments by `(date, source_ref)`,
    supplier rows by `source_ref`.
  - `source_ref` order is the *natural* order of `source_ref_key(ref)` = `(file name, row number
    as an integer)` (so `f.csv:9` precedes `f.csv:10`; text order would not). A ref whose row part
    is not an integer sorts by `(ref, -1)`.
  - `Alert.source_refs` is sorted by that key. Every list stored in `Alert.data` that names the
    members of a pair or group is ordered by `source_ref` too.
  - A detector returns its alerts sorted by `(first source_ref, variant)`. Consequently, shuffling
    the rows of any input frame produces an identical list of alerts (same alerts, same order, same
    ids).
- **REQ-PI-11** **Duplicate `source_ref`.** If a frame contains two rows with the same
  `source_ref`, the first one in sort order is used and the others are ignored by every detector
  (no crash, no repeated reference in `Alert.source_refs`).
- **REQ-PI-12** **`as_of`.** `resolve_as_of(invoices, context) -> date | None` returns
  `context["as_of"]` when it is a date; otherwise the latest date among all `issue_date` values of
  the invoices and all `date` values of the payments (all rows, credits included); `None` when
  there is no date at all. It never calls `date.today()`, `datetime.now()` or reads the system
  clock; a test makes `date.today` raise to prove it. `pi.reconciliation` skips the overdue rule
  when `as_of` is `None`.
- **REQ-PI-13** **Alert data hygiene.** `Alert.data` contains only JSON-native values: `str`,
  `int`, `bool` and `list[str]`. Money is a 2-decimal string (`round_to_cents`, e.g. `"121.00"`),
  dates are ISO strings, rates are the cell text of the `Decimal` (`"21"`), IBANs are
  `mask_iban(...)` output. Every `Alert.data` carries `variant` (a string, per detector, listed in
  the alert contracts) which also selects the fallback template (REQ-PI-45).
- **REQ-PI-14** **Registration.** Each detector module registers itself with
  `@register("pi.<name>")`; `apps/phantom_invoices/detectors/__init__.py` calls
  `auto_discover("apps.phantom_invoices.detectors")`. A user-visible label (`LABELS`) maps each
  registered name to a display string; `pi.iban_change` is labelled **Poltergeist IBAN**.

### 2.2 Multi-rate invoices (quarantine)

- **REQ-PI-15** Rows of the same supplier (`tax_key`) and the same `N1` invoice number but with
  **different `vat_rate`** are *one multi-rate invoice* split over several rows. They are out of
  scope: the pre-processing function
  `quarantine_multi_rate(invoices) -> (clean_invoices, quarantine_records)` removes **all** rows
  of such a group from the frame handed to the detectors and returns one quarantine record per
  removed row in the ledger-core shape (`source_file`, `source_row`, `reason`, `raw`) with
  `reason="multi_rate_invoice_out_of_scope"`. The UI lists them in the quarantine panel
  (REQ-PI-50). Rows with a missing `vat_rate` are not counted as a different rate.
- **REQ-PI-16** As a second line of defence `pi.duplicate_invoice` itself skips any group of the
  same supplier and `N1` that holds more than one distinct `vat_rate`, so a caller who bypasses
  `quarantine_multi_rate` still gets no duplicate alert for a multi-rate invoice.

---

## 3 — Duplicate-invoice detector (`pi.duplicate_invoice`)

Constants (module level, each with a business-meaning comment): `DUPLICATE_WINDOW_DAYS: int = 7`
(two invoices of one supplier with the same total are suspicious when issued fewer than this many
days apart); `SAME_NUMBER_WINDOW_DAYS: int = 180` (two invoices of one supplier with the same
invoice number are suspicious only when issued fewer than this many days apart, so a numbering
series that restarts every year does not fire; OD-PI-07);
`DUPLICATE_TOTAL_TOLERANCE: Decimal = Decimal("0.00")` ("same total" means equal to the cent;
compared with `within_tolerance`).

- **REQ-PI-17** The detector signature is
  `detect_duplicate_invoices(ledger: pd.DataFrame, context: Mapping[str, Any]) -> list[Alert]`.
  It reads only the ledger (context is ignored). It returns `[]` for an empty ledger,
  `pd.DataFrame()` without columns, and a ledger whose usable rows are fewer than two.
  *Usable row*: non-missing `invoice_number` with non-empty `N1`, non-missing supplier `tax_key`,
  `issue_date` and `total`.
- **REQ-PI-18** **Pair rules.** Within one supplier, for two usable invoices `a`, `b`:

  | Rule | Condition | Severity | `variant` |
  |---|---|---|---|
  | A | `N1(a) == N1(b)` and `abs(issue_date(a) - issue_date(b)).days < SAME_NUMBER_WINDOW_DAYS` | `critical` | `same_number` |
  | B | `N1(a) != N1(b)`, `N2(a) == N2(b)` and totals equal | `warning` | `near_identical_number` |
  | C | `N2(a) != N2(b)`, totals equal and `abs(issue_date(a) - issue_date(b)).days < DUPLICATE_WINDOW_DAYS` | `warning` | `same_total_close_dates` |

  Totals are equal when `within_tolerance(a.total, b.total, DUPLICATE_TOTAL_TOLERANCE)`. Rule B has
  no date window. Two invoices with equal `N1` are related by rule A alone: rule B needs different
  `N1`, and a gap of `SAME_NUMBER_WINDOW_DAYS` or more days exceeds `DUPLICATE_WINDOW_DAYS`, so
  rule C cannot apply either (a test asserts `DUPLICATE_WINDOW_DAYS <= SAME_NUMBER_WINDOW_DAYS`).
  The same number `SAME_NUMBER_WINDOW_DAYS` or more days apart is therefore **not related** at all
  (OD-PI-07). Only invoices with equal `currency` are ever paired (REQ-PI-05). Rule C applies to
  any numbers with different `N2`, including consecutive numbers
  that happen to carry the same total (OD-PI-06). **No rule uses edit distance or any similarity
  score.**
- **REQ-PI-19** **One alert per group.** The pair relations of REQ-PI-18 are closed transitively;
  each connected group of two or more invoices yields **exactly one** `Alert`, whose severity and
  `variant` are those of the most severe rule present in the group (A over B over C). A group
  never produces a second alert from a weaker rule.
- **REQ-PI-20** **Alert contract.**
  - `detector`: `"pi.duplicate_invoice"`.
  - `title`: `"Duplicate invoice: <invoice_number of the first member> (<supplier_name>)"` for rule A,
    `"Possible duplicate invoice: <invoice_number of the first member> (<supplier_name>)"` for B and C.
  - `source_refs`: the `source_ref` of every member, in natural order.
  - `data`:
    ```python
    {
        "variant": str,               # same_number | near_identical_number | same_total_close_dates
        "supplier_name": str,         # of the first member (source_ref order)
        "invoice_count": int,         # members in the group (>= 2)
        "invoice_numbers": list[str], # as written, ordered by source_ref
        "totals": list[str],          # 2 d.p., same order
        "total": str,                 # total of the first member; equal for all members under B and C
        "first_issue_date": str,      # ISO 8601, earliest issue date in the group
        "last_issue_date": str,       # ISO 8601, latest issue date in the group
        "days_apart": int,            # (last_issue_date - first_issue_date).days
    }
    ```
- **REQ-PI-21** Edge behaviour required (each a named Tier 2 test): `N1` empty → row skipped;
  non-string or missing invoice numbers → skipped; a missing `issue_date` or `total` → row skipped;
  two rows with identical `source_ref` → one used (REQ-PI-11); multi-rate group → no alert
  (REQ-PI-16); same number for **different** suppliers → no alert; boundaries: rule C 6 days
  apart alerts, 7 days apart does not; rule A 179 days apart alerts, 180 days apart does not;
  totals differing by 0.01 are not equal.
- **REQ-PI-21a** *(OD-PI-07)* Two further Tier 1 tests, with minimal fixtures (same supplier and
  same invoice number, any totals): `test_pi_same_number_2_days_apart_is_critical` → exactly
  one `critical` alert, `variant="same_number"`; `test_pi_same_number_200_days_apart_no_alert` →
  no alert (an annual numbering restart is not a duplicate).

---

## 4 — Poltergeist IBAN detector (`pi.iban_change`)

Constants: `IBAN_FORMAT_RE = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}$")` (structural shape of
an IBAN after `iban_key`); `IBAN_MOD97_MODULUS: int = 97` and `IBAN_MOD97_REMAINDER: int = 1`
(ISO 13616 checksum); `VERIFY_BY_PHONE_MESSAGE: str` (REQ-PI-24). The Spanish national check
digits and per-country lengths are **not** validated (OD-PI-15).

- **REQ-PI-22** The detector signature is
  `detect_iban_changes(ledger, context) -> list[Alert]`. It reads `context["suppliers"]` and
  `context["payments"]`. Per REQ-DET-05 (CR-LC-3f) it **may return alerts when the ledger is
  empty** (a payment to a non-master IBAN needs no invoice) and returns `[]` when the ledger,
  the supplier master and the payments are all empty; it never raises.
- **REQ-PI-23** **IBAN validity.** An IBAN cell is *missing* (REQ-PI-06) → the row is skipped for
  every IBAN rule. Otherwise `iban_key` is applied; the IBAN is **valid** when it matches
  `IBAN_FORMAT_RE` **and** its ISO 13616 mod-97 check holds (move the first four characters to the
  end, replace letters by `A=10 … Z=35`, the integer mod 97 equals 1). A malformed or
  checksum-failing value never raises. An IBAN containing hyphens, dots or other non-alphanumeric
  characters is malformed (`reason="format"`); a well-formed one with a bad checksum has
  `reason="checksum"`.
- **REQ-PI-24** **Rules.** Per row, at most one alert is produced; a *valid* IBAN is compared with
  the master, an *invalid* one is only flagged:

  | Subject | Condition | Severity | `variant` |
  |---|---|---|---|
  | Invoice | IBAN valid, the invoice's master row has a **valid** IBAN, and `iban_key` differs | `critical` | `invoice_iban_differs_from_master` |
  | Bank payment | Payment (debit) is attributed to a master supplier (REQ-PI-25), its IBAN is valid, that supplier's master IBAN is valid and `iban_key` differs | `critical` | `payment_to_non_master_iban` |
  | Invoice, supplier payment (REQ-PI-25) or master row | IBAN present but invalid (REQ-PI-23) | `warning` | `iban_invalid` |

  Invoice IBAN equal to the master IBAN after `iban_key` (spaces and case ignored) → no alert
  (acceptance P4). A missing IBAN, a missing master IBAN, or an invoice whose supplier is not in
  the master → skipped for the comparison. If the master IBAN itself is present but invalid, the
  master row is flagged once with `iban_invalid` (subject `supplier`) and no comparison against it
  is made.
- **REQ-PI-25** **Payment attribution.** A debit payment belongs to at most one master supplier:
  first, `name_key(counterparty)` equals `name_key(supplier_name)` of exactly one master supplier;
  otherwise, `iban_key(payment iban)` equals the `iban_key` of the master IBAN of exactly one
  supplier; otherwise the payment is *not a supplier payment*: it is not checked by
  `pi.iban_change`, is in no reconciliation bucket and raises no alert. Name is tried first
  so that a payment addressed to a known supplier but sent to another account is caught (OD-PI-09).
  The same function is used by `pi.reconciliation` (REQ-PI-36).
- **REQ-PI-26** **Fixed deterministic message.** `VERIFY_BY_PHONE_MESSAGE` is the constant text
  `"Verify this change by phone, using a contact you already have for this supplier. Never use a
  phone number or e-mail address printed on the invoice."` (written as one string). It contains no
  digit. Both `critical` variants carry it in `Alert.data["verification_message"]`; the UI shows it
  verbatim below the alert and it is part of the fallback template. It is code, not LLM output:
  the LLM remains forbidden to recommend actions (Finance Rule 8) and the explanation text never
  has to contain it.
- **REQ-PI-27** **Alert contract.** `detector`: `"pi.iban_change"`; `source_refs`: the row and the
  master row it was compared with (natural order), or the single row for `iban_invalid`.

  `invoice_iban_differs_from_master` (critical), title `"Poltergeist IBAN: <supplier_name>"`:
  ```python
  {
      "variant": "invoice_iban_differs_from_master",
      "supplier_name": str,            # from the master row
      "invoice_number": str,
      "invoice_iban_masked": str,      # mask_iban(...), e.g. "****1332"
      "master_iban_masked": str,
      "last4_identical": bool,         # True when both masks are equal: the IBANs differ elsewhere
      "verification_message": str,     # VERIFY_BY_PHONE_MESSAGE
  }
  ```
  `payment_to_non_master_iban` (critical), title `"Payment sent to a non-master IBAN: <supplier_name>"`:
  ```python
  {
      "variant": "payment_to_non_master_iban",
      "supplier_name": str,
      "payment_date": str,             # ISO 8601
      "payment_amount": str,           # 2 d.p.
      "payment_iban_masked": str,
      "master_iban_masked": str,
      "last4_identical": bool,
      "verification_message": str,
  }
  ```
  `iban_invalid` (warning), title `"Invalid IBAN on <subject> <label>"`:
  ```python
  {
      "variant": "iban_invalid",
      "subject": str,                  # "invoice" | "payment" | "supplier"
      "label": str,                    # invoice_number | payment counterparty | supplier_name
      "reason": str,                   # "format" | "checksum"
      "iban_masked": str,
  }
  ```
  No `Alert.data` value anywhere contains a full IBAN (REQ-PII-04); a property test checks it.
- **REQ-PI-28** Edge behaviour required (named Tier 2 tests): IBANs differing only in the part
  before the last 4 characters still alert (`last4_identical` true); a `\u00a0` inside the IBAN is
  removed; an IBAN of only hyphens is missing (skipped); an IBAN with hyphens is `iban_invalid`
  (acceptance P12); a valid-format IBAN with a failing checksum is `iban_invalid` with
  `reason="checksum"`; lowercase is accepted; an invoice and a payment for the same supplier
  produce two independent alerts; empty ledger with a non-master payment alerts (REQ-PI-22); empty
  everything returns `[]`; unknown supplier skipped; `NaN` and `None` IBANs skipped.

---

## 5 — VAT-error detector (`pi.vat_error`)

Constants: `VAT_TOLERANCE: Decimal = Decimal("0.01")` (largest accepted difference, in euros,
between the stated and the computed VAT amount); `TOTAL_TOLERANCE: Decimal = Decimal("0.01")`
(same, for the stated and computed total); `ALLOWED_VAT_RATES: tuple[Decimal, ...] =
(Decimal("21"), Decimal("10"), Decimal("4"), Decimal("0"))` (Spanish general, reduced,
super-reduced and exempt rates, as percentages). A comment on `ALLOWED_VAT_RATES` states that the
Canary Islands IGIC and other special regimes (Ceuta, Melilla, agricultural flat-rate, etc.) are
out of scope.

- **REQ-PI-29** The detector signature is `detect_vat_errors(ledger, context) -> list[Alert]`; it
  reads only the ledger. It returns `[]` for an empty ledger and `pd.DataFrame()`.
- **REQ-PI-30** **Documented assumption:** VAT is checked on the invoice **base**, not line by
  line. An invoice with several VAT rates is a multi-rate invoice and is out of scope (REQ-PI-15).
- **REQ-PI-31** **Checks**, each independent, each producing its own `warning` alert for a row
  when the needed cells are present (a check whose inputs are missing is skipped):

  | Check | Condition to alert | `variant` |
  |---|---|---|
  | VAT amount | `expected = percent_of(base_amount, vat_rate)`; `not within_tolerance(expected, vat_amount, VAT_TOLERANCE)` | `vat_amount_mismatch` |
  | Total | `expected = net_total([base_amount, vat_amount, surcharge_amount], [withholding_amount])`; `not within_tolerance(expected, total, TOTAL_TOLERANCE)` | `total_mismatch` |
  | VAT rate | `vat_rate not in ALLOWED_VAT_RATES` (value comparison: `Decimal("21.00")` is allowed) | `vat_rate_not_allowed` |

  The total check uses the **stated** `vat_amount`, so a wrong VAT amount and a total that is
  consistent with it produce exactly one alert (acceptance P7). Surcharge and withholding are not
  recomputed (their rates are out of scope, OD-PI-16); `surcharge_amount` and `withholding_amount`
  default to `Decimal("0")` when missing. A difference of exactly `0.01` is accepted; `0.02`
  alerts.
- **REQ-PI-32** **Alert contract.** `detector`: `"pi.vat_error"`; `source_refs`: `[invoice
  source_ref]`.

  `vat_amount_mismatch`, title `"VAT amount mismatch: <invoice_number>"`:
  ```python
  {"variant": "vat_amount_mismatch", "supplier_name": str, "invoice_number": str,
   "base_amount": str, "vat_rate": str, "expected_vat_amount": str, "vat_amount": str}
  ```
  `total_mismatch`, title `"Invoice total mismatch: <invoice_number>"`:
  ```python
  {"variant": "total_mismatch", "supplier_name": str, "invoice_number": str,
   "base_amount": str, "vat_amount": str, "surcharge_amount": str,
   "withholding_amount": str, "expected_total": str, "total": str}
  ```
  `vat_rate_not_allowed`, title `"Unexpected VAT rate: <invoice_number>"`:
  ```python
  {"variant": "vat_rate_not_allowed", "supplier_name": str, "invoice_number": str,
   "vat_rate": str, "allowed_vat_rates": str}   # allowed_vat_rates e.g. "21, 10, 4, 0"
  ```
- **REQ-PI-33** Edge behaviour required (named Tier 2 tests): boundaries 0.01 (no alert) and 0.02
  (alert) for both amount checks; rate `Decimal("21.00")` accepted, `Decimal("20")` and `Decimal("5")`
  alert; rate `0` with VAT `0.00` is clean; `NaN`/`None` base, rate, VAT or total → that check
  skipped without error; non-`Decimal` cells (strings, floats) are treated as missing; the
  half-up case (`percent_of(Decimal("0.50"), Decimal("21"))` = `0.11`) does not alert for a stated
  `0.11` and does for `0.09`; withholding larger than base+VAT yields a total check, not an error.

---

## 6 — Reconciliation detector (`pi.reconciliation`)

Constants: `PAYMENT_MATCH_WINDOW_DAYS: int = 60` (a payment may be dated up to this many days after
the due date and still be matched); `UNPAID_GRACE_DAYS: int = 15` (days after the due date before
an unmatched invoice is reported as overdue); `MATCH_AMOUNT_TOLERANCE: Decimal = Decimal("0.01")`
(largest accepted difference between payment amount and invoice total).

- **REQ-PI-34** The detector signature is `detect_reconciliation(ledger, context) -> list[Alert]`.
  It is a thin wrapper over the pure function `reconcile(invoices, suppliers, payments, as_of) ->
  Reconciliation` (REQ-PI-38) so that tests, the UI status column and the partition property use
  the same logic. It reads `context["suppliers"]`, `context["payments"]` and `context["as_of"]`
  (REQ-PI-12). Per REQ-DET-05 (CR-LC-3f) it **may return alerts when the ledger is empty**
  (payments with no invoice) and returns `[]` when ledger and payments are both empty.
- **REQ-PI-35** **Usable rows.** A *usable invoice* has non-missing `issue_date`, `due_date`,
  `total`, `currency` and supplier `tax_key`. A *usable payment* is a debit row with non-missing
  `date`, `amount` and `currency`. Rows that are not usable are ignored by reconciliation (they
  belong to no bucket) and never raise.
- **REQ-PI-36** **Supplier payments** are the usable payments attributed to a master supplier by
  the function of REQ-PI-25. Invoices map to the master by `tax_key(supplier_tax_id)` (REQ-PI-09).
- **REQ-PI-37** **Matching.** Invoices are visited in `(issue_date, source_ref)` order. For each
  invoice whose supplier is in the master, the candidate payments are the not-yet-matched supplier
  payments of **the same supplier** and **same currency** with
  `within_tolerance(payment.amount, invoice.total, MATCH_AMOUNT_TOLERANCE)` and
  `invoice.issue_date <= payment.date <= invoice.due_date + PAYMENT_MATCH_WINDOW_DAYS` (both ends
  inclusive); the candidate smallest by `(date, source_ref)` is matched to the invoice. The
  matching is **one-to-one** (a payment is matched at most once) and greedy. Partial payments,
  overpayments and payments dated before the issue date are not matched (OD-PI-17). An invoice
  whose supplier is not in the master can never be matched.
- **REQ-PI-38** **Buckets.** Every usable invoice ends in exactly one of `matched`,
  `open_not_due`, `overdue`; every supplier payment ends in exactly one of `matched`,
  `unmatched`:
  - An invoice with a matched payment is `matched`.
  - An unmatched invoice is `overdue` when `as_of` is not `None` and
    `as_of > due_date + UNPAID_GRACE_DAYS` (strictly later: `due_date + 15` itself is
    `open_not_due`, `due_date + 16` is `overdue`); otherwise `open_not_due`.
  - A supplier payment that was matched is `matched`; otherwise `unmatched`.

  `Reconciliation` exposes `invoice_buckets: dict[str, str]` and `payment_buckets: dict[str, str]`
  (keyed by `source_ref`), `matches: list[tuple[str, str]]` (invoice ref, payment ref) and
  `payment_supplier: dict[str, str]` (payment ref → `tax_key` of the master supplier it is
  attributed to, REQ-PI-25), so the alert builder never repeats the attribution.
- **REQ-PI-39** **Alerts.** Only two bucket outcomes alert; `matched` and `open_not_due` are silent.
  `detector`: `"pi.reconciliation"`, severity `warning` for both.

  `invoice_overdue`, title `"Unpaid invoice: <invoice_number> (<supplier_name>)"`,
  `source_refs`: `[invoice source_ref]`:
  ```python
  {
      "variant": "invoice_overdue",
      "supplier_name": str,
      "invoice_number": str,
      "total": str,                  # 2 d.p.
      "due_date": str,               # ISO 8601
      "due_date_is_default": bool,   # True when due_date = issue_date + 30 days (not read from the file)
      "as_of": str,                  # ISO 8601, the date used (REQ-PI-12)
      "days_past_due": int,          # (as_of - due_date).days
  }
  ```
  `payment_without_invoice`, title `"Payment without invoice: <supplier_name>"`,
  `source_refs`: `[payment source_ref, supplier master source_ref]` (natural order):
  ```python
  {
      "variant": "payment_without_invoice",
      "supplier_name": str,          # from the master
      "payment_date": str,           # ISO 8601
      "payment_amount": str,         # 2 d.p.
      "currency": str,
  }
  ```
- **REQ-PI-40** Edge behaviour required (named Tier 2 tests): payment on the issue date and on
  `due_date + 60` matches, one day later does not; `due_date + 15` is not overdue, `+16` is;
  amount difference `0.01` matches, `0.02` does not; same amount, different currency does not
  match; two invoices with equal totals and two payments pair one-to-one in `(date, source_ref)`
  order; one invoice paid twice → second payment `unmatched` (acceptance P9); credits are ignored;
  payment attributed by name and by IBAN; payment of an unknown counterparty with an unknown IBAN
  is not a supplier payment and is in no bucket; `as_of=None` → no overdue alert and every
  unmatched invoice `open_not_due`; duplicate `source_ref`; empty ledger with an unmatched
  supplier payment alerts; everything empty returns `[]`; a defaulted due date is flagged in
  `due_date_is_default`.

---

## 7 — Acceptance examples

Each example is a required **Tier 1** test (named `test_pi_acceptance_pNN_<slug>`), built from a
minimal fixture, asserting the exact number and severity of the alerts of the named detector and,
for P1, that **no other pi detector** fires either. Invoices use fictional suppliers, tax ids and
IBANs as defined in Finance Rule 5 as revised by CR-LC-3h (REQ-PI-58).

| ID | Input | Expected |
|---|---|---|
| P1 | The same invoice (same supplier, same number, same vat_rate) present twice | Exactly one `pi.duplicate_invoice` alert, `critical`, `variant="same_number"`, and no alert from the other three detectors (invoices with correct VAT and no IBAN, no payments, `as_of` = latest data date) |
| P2 | Monthly rent invoices from one landlord, same total, 30 days apart, numbered `ALQ-2026-01`, `ALQ-2026-02`, `ALQ-2026-03` | No `pi.duplicate_invoice` alert |
| P3 | `F-2026-0042` and `F2026-042`, same supplier and total, 3 days apart | Exactly one `pi.duplicate_invoice` alert, `warning`, `variant="near_identical_number"` |
| P4 | Invoice IBAN with spaces and lowercase, equal to the master IBAN after cleaning | No `pi.iban_change` alert |
| P5 | Invoice carries a new (valid) IBAN different from the master | Exactly one `pi.iban_change` alert, `critical`, `variant="invoice_iban_differs_from_master"`, `verification_message == VERIFY_BY_PHONE_MESSAGE` |
| P6 | base 100.00, rate 21, VAT 21.00, total 121.00 | No `pi.vat_error` alert |
| P7 | base 100.00, rate 21, VAT 12.10, total 112.10 (consistent with the stated VAT) | Exactly one `pi.vat_error` alert, `warning`, `variant="vat_amount_mismatch"` |
| P8 | base 1000.00, rate 21, VAT 210.00, withholding 150.00, total 1060.00 | No `pi.vat_error` alert |
| P9 | One invoice (total X) paid twice by two debit payments of X within the window | `pi.reconciliation`: the invoice and one payment are `matched`, the other payment is `unmatched`; exactly one `payment_without_invoice` alert and no `invoice_overdue` alert |
| P10 | Same supplier and total, different numbers (different `N2`) | 6 days apart → exactly one `warning` (`same_total_close_dates`); 7 days apart → no alert; 8 days apart → no alert |
| P11 | base 100.00, rate 21, VAT 21.00, surcharge 5.20, total 126.20 | No `pi.vat_error` alert |
| P12 | (a) an invoice IBAN written with hyphens (`ES88-2100-0418-5602-0005-1332`); (b) an empty IBAN cell (`NaN`) | (a) exactly one `warning`, `variant="iban_invalid"`, `reason="format"`, no exception; (b) no alert, no exception |

---

## 8 — Explanation layer

- **REQ-PI-41** The app explains each alert with
  `ledger_kit.explainer.explain_with_meta(alert, rows, fallback_template=…, client=…,
  row_columns=ROW_COLUMNS)`. It builds no prompt itself (REQ-EXP-06/07 hold). `ROW_COLUMNS` is the
  tuple (CR-LC-3g): `invoice_number, supplier_name, issue_date, due_date, base_amount, vat_rate,
  vat_amount, surcharge_amount, withholding_amount, total, currency, source_ref`. The `iban`
  columns, `supplier_tax_id` and `tax_id` are never in it.
- **REQ-PI-42** `rows` is built by `build_explain_rows(alert, invoices, suppliers, payments)`: the
  rows whose `source_ref` is in `alert.source_refs`, taken from whichever of the three frames holds
  them, each reduced to the columns of `ROW_COLUMNS` that exist in that frame, concatenated (cells
  absent from a frame stay missing). Consequently payment and master rows contribute only
  `currency`/`source_ref` (payments) or `source_ref` (master): every payment amount, payment date
  and counterparty an explanation may mention comes from `Alert.data`.
- **REQ-PI-43** Because the guard reads `Alert.data`, every figure of the fallback templates
  (REQ-PI-45) is a named field (REQ-DET-09). A test fills every template from a real alert of every
  variant and asserts that no placeholder is left unresolved and that the guard accepts a sentence
  that restates only values of `Alert.data` and the cited rows.
- **REQ-PI-44** When no `OPENAI_API_KEY` is present, the filled fallback is returned without a
  network call (REQ-EXP-02); the app needs no special handling.
- **REQ-PI-45** **Fallback templates** (passed as `fallback_template`; `{key:money}` uses
  `format_amount`, `{key}` is plain, `{source_refs}` is the comma-joined refs). The template is
  selected by `(alert.detector, alert.data["variant"])`:

  | Detector / variant | Template |
  |---|---|
  | `pi.duplicate_invoice` / `same_number` | `"Supplier {supplier_name} sent {invoice_count} invoices with the same invoice number, issued between {first_issue_date} and {last_issue_date}. Source: {source_refs}."` |
  | `pi.duplicate_invoice` / `near_identical_number` | `"Supplier {supplier_name} has {invoice_count} invoices with near-identical numbers and the same total of {total:money}, issued {days_apart} days apart. Source: {source_refs}."` |
  | `pi.duplicate_invoice` / `same_total_close_dates` | `"Supplier {supplier_name} has {invoice_count} invoices with the same total of {total:money}, issued {days_apart} days apart. Source: {source_refs}."` |
  | `pi.iban_change` / `invoice_iban_differs_from_master` | `"Invoice {invoice_number} from {supplier_name} names the account {invoice_iban_masked}, which differs from the account {master_iban_masked} in the supplier master. {verification_message} Source: {source_refs}."` |
  | `pi.iban_change` / `payment_to_non_master_iban` | `"A payment of {payment_amount:money} on {payment_date} to {supplier_name} went to the account {payment_iban_masked}, which differs from the account {master_iban_masked} in the supplier master. {verification_message} Source: {source_refs}."` |
  | `pi.iban_change` / `iban_invalid` | `"The IBAN {iban_masked} on the {subject} {label} is not a valid IBAN (failed {reason} check). Source: {source_refs}."` |
  | `pi.vat_error` / `vat_amount_mismatch` | `"Invoice {invoice_number} from {supplier_name} states VAT of {vat_amount:money}; {vat_rate} % of the base {base_amount:money} is {expected_vat_amount:money}. Source: {source_refs}."` |
  | `pi.vat_error` / `total_mismatch` | `"Invoice {invoice_number} from {supplier_name} states a total of {total:money}; base {base_amount:money} plus VAT {vat_amount:money} plus surcharge {surcharge_amount:money} minus withholding {withholding_amount:money} is {expected_total:money}. Source: {source_refs}."` |
  | `pi.vat_error` / `vat_rate_not_allowed` | `"Invoice {invoice_number} from {supplier_name} uses a VAT rate of {vat_rate} %, which is not one of the supported rates ({allowed_vat_rates}). Source: {source_refs}."` |
  | `pi.reconciliation` / `invoice_overdue` | `"Invoice {invoice_number} from {supplier_name} for {total:money} was due on {due_date} and no matching payment was found as of {as_of}. Source: {source_refs}."` |
  | `pi.reconciliation` / `payment_without_invoice` | `"A payment of {payment_amount:money} to {supplier_name} on {payment_date} could not be matched to any invoice. Source: {source_refs}."` |

  Templates state facts only and recommend no action (Finance Rule 8). The `critical` IBAN
  variants additionally show `verification_message` through the template and the UI (REQ-PI-26).
- **REQ-PI-46** **Guard badge** (identical semantics to REQ-ZS-37), shown on every alert:
  - 🤖 ✓ *LLM text verified by number guard* — `Explanation.source == "llm"`.
  - 📋 *Template (no API key)* — `source == "fallback"`, no `OPENAI_API_KEY`, and no `rejected_numbers`.
  - ⚠️ *LLM answer rejected: invented number {X}* — `source == "fallback"` and `rejected_numbers`
    non-empty.
- **REQ-PI-47** The sidebar has the same **Simulate a hallucinating LLM** toggle as App 1
  (REQ-ZS-37a). When on, the app injects a `HallucinatingStubClient` defined in
  `apps/phantom_invoices/explain_support.py` (a client whose answer is the filled fallback text of
  the alert with the known-foreign number `99999.99` appended), so the guard rejects the answer and the ⚠️
  badge appears without an API key. Apps must not import each other, so the stub is a separate
  copy (OD-PI-12). Explanations are cached in `st.session_state` by `(alert.id, client_mode)`.

---

## 9 — Streamlit UI

- **REQ-PI-48** Theme: **the haunted ledger** — a candle-lit, dark study (background `#12101a`,
  parchment-toned text, ghost-green `#7cffb2` and amber accents), styled only with CSS injected via
  `st.markdown(..., unsafe_allow_html=True)`; no external CSS framework. Severity badges:
  🔴 critical, 🟡 warning.
- **REQ-PI-49** **Layout.** (1) A severity summary row (critical / warning counts). (2) The
  *haunted ledger*: a table of **all** invoices with their `source_ref`, and a **status** column
  from `reconcile(...)` (✅ matched, 🕯️ open, 💀 overdue; blank when not usable), all amounts in
  European format (`format_amount`, Finance Rule 4). (3) The alert list grouped by severity
  (critical → warning), each alert showing its title, the detector label (REQ-PI-14), the
  explanation, the guard badge, the `source_refs`, and for the two `critical` IBAN variants the
  `verification_message`; plus a caption when `last4_identical` is true ("The last four characters
  match; the difference is elsewhere in the IBAN.") and when `due_date_is_default` is true ("Due
  date assumed: issue date plus the default payment term."). (4) The `as_of` date in use, with
  the note that it defaults to the latest date in the data.
- **REQ-PI-50** **Flashlight.** The alerts are selectable (single selection, `st.radio` or
  equivalent). When an alert is selected, the haunted ledger is rendered so that the rows whose
  `source_ref` is cited by the alert are *lit* (bright text and background, a glow border produced
  by CSS `box-shadow`/`radial-gradient`) and **every other row is dimmed** (`opacity` ≤ 0.3).
  Cited supplier-master and payment rows are shown in two small tables below the ledger with the
  same lit styling. With no alert selected, no row is dimmed. The renderer is a pure function
  `render_ledger_html(df, lit_refs) -> str` that **HTML-escapes every cell value**
  (`html.escape`), so no data can inject markup; it is unit-tested without Streamlit
  (`test_pi_flashlight.py`). Quarantined rows (including `multi_rate_invoice_out_of_scope`) are
  listed in a collapsible warning section with file, row, reason and raw values (REQ-UI-07).
- **REQ-PI-51** **Inputs.** The sidebar has three uploaders (invoices `.csv`/`.json`, suppliers
  `.csv`, payments `.csv`), an optional fixed `as_of` date (checkbox + date input; off by default),
  the hallucination toggle (REQ-PI-47) and the **Load demo data** button. Uploaded files are passed
  as `IO[bytes]` to the readers; parsing is cached in `st.session_state` by the SHA-256 of the
  file bytes.
- **REQ-PI-52** **Load demo data** loads the three files named in `config.toml [demo]`
  (`data/samples/phantom_demo/suppliers.csv`, `invoices.csv`, `payments.csv`) through an
  `on_click` callback that sets the session state before the widgets are instantiated (as in
  App 1, REQ-ZS-40), and then immediately shows alerts from all four detectors (REQ-PI-69).
- **REQ-PI-53** The app launches with `streamlit run apps/phantom_invoices/app.py` on a clean
  clone, locally and on Streamlit Community Cloud, with no mandatory environment variable other
  than the optional `OPENAI_API_KEY`. **Path bootstrap** — the first lines of `app.py` are the same
  as App 1's:

  ```python
  import sys, pathlib
  _ROOT = pathlib.Path(__file__).resolve().parents[2]
  if str(_ROOT) not in sys.path:
      sys.path.insert(0, str(_ROOT))
  ```

  A root-level `requirements.txt` lists all runtime dependencies (no `-e .` line). The app folder
  must **not** contain its own `requirements.txt` (Community Cloud would read it first and hide the
  root one). This supersedes the per-app `requirements.txt` shown in `.kiro/steering/structure.md`;
  one task of `tasks.md` updates the phantom section of that steering file to match (OD-PI-14).

---

## 10 — Data and generator

- **REQ-PI-54** **Synthetic Spanish invoices only; no download.** Demo data is produced by
  `python scripts/generate_samples.py --mode phantom-demo --seed 42` (the script lives in
  ledger-core Task 13 and gains this mode here). The output is written to
  `data/samples/phantom_demo/`: `suppliers.csv`, `invoices.csv`, `payments.csv`. Running the
  generator twice with the same seed produces byte-identical files, and the committed files equal
  the generator's output (tested).
- **REQ-PI-55** **File formats.** All three files use the plain dialect (comma separator, dot
  decimal, ISO dates; OD-PI-13). `payments.csv` has the bank columns of REQ-ING-02 plus `iban`,
  with **negative amounts** (debits). `invoices.csv` has the columns of REQ-ING-30/31 (some rows
  without `due_date`, with `surcharge_amount`, with `withholding_amount`, and with an IBAN written
  with spaces/lowercase). `suppliers.csv` has `supplier_name,tax_id,iban`.
- **REQ-PI-56** **Size and shape.** Roughly 20–26 suppliers (one dedicated supplier per planted
  case plus at least five clean ones) and 60–90 invoices over about six months, all with fictional
  Spanish business names and culturally diverse fictional person names
  (Finance Rule 5). About two thirds of the invoices are **clean** (correct VAT, unique consecutive
  numbers, paid inside the window by a payment to the master IBAN) and must raise **no alert**.
- **REQ-PI-57** **Every acceptance case is planted.** P1–P12 of section 7 each have their own
  dedicated fictional supplier (so they cannot interfere with each other), identified by its tax
  id. In addition the demo plants: (a) a **payment sent to a non-master IBAN** (critical
  `payment_to_non_master_iban`); (b) an **overdue** invoice (its `due_date + UNPAID_GRACE_DAYS + 1`
  is not later than the latest date in the data, ensured by a late clean payment); (c) at least one
  **open_not_due** invoice; (d) a **multi-rate invoice** (two rows, same number, rates 21 and 10)
  that is quarantined; (e) an invoice **without `due_date`** (defaulted). The generator exposes a
  module-level mapping `PHANTOM_CASES` from case id to supplier tax id so tests can assert per
  case.
- **REQ-PI-58** **Identifiers (Finance Rule 5, CR-LC-3h).** Every IBAN in the demo has a valid
  mod-97 checksum and **deliberately wrong Spanish national check digits** (example
  `ES88 2100 0418 5602 0005 1332`: mod-97 valid, national check digits `56` instead of `45`; checked
  by running it: the mod-97 remainder is 1 and the correct Spanish national check digits are `45`),
  so it cannot be a real account; the generator derives the two ISO check digits algorithmically. The
  demo contains no checksum-invalid IBAN (the checksum warning is planted only by unit tests, and
  P12's hyphenated IBAN is derived from a valid one). Every supplier tax id has a **wrong control
  character**, a different one per supplier (examples `B00000001`, `B00000002` for companies;
  `00000001T`, `00000002T` for individuals; never `00000000T`, whose letter is correct, and never a
  multiple of 23 as a NIF number). Tests validate this with test-local checkers (mod-97, Spanish
  IBAN national check digits, NIF letter, CIF control character); neither the app nor `ledger_kit`
  validates tax ids.

---

## 11 — Configuration (`apps/phantom_invoices/config.toml`)

- **REQ-PI-59** All thresholds (`DUPLICATE_WINDOW_DAYS`, `SAME_NUMBER_WINDOW_DAYS`, `VAT_TOLERANCE`,
  `TOTAL_TOLERANCE`,
  `ALLOWED_VAT_RATES`, `PAYMENT_MATCH_WINDOW_DAYS`, `UNPAID_GRACE_DAYS`, `MATCH_AMOUNT_TOLERANCE`,
  `DUPLICATE_TOTAL_TOLERANCE`) live **only** as named constants in the detector modules; they are
  **not** duplicated in `config.toml` (as REQ-ZS-42). `DEFAULT_PAYMENT_TERM_DAYS = 30` lives in
  ledger-core's `invoice_reader.py`.
- **REQ-PI-60** `config.toml` holds only the `[demo]` section (the three file paths relative to the
  repository root and an optional `as_of`, absent by default so the demo uses the latest data date)
  and display labels if any. Secrets never appear in it.

---

## 12 — Package structure

The following list is **definitive** for this app. It supersedes the illustrative phantom section
of `.kiro/steering/structure.md` until the dedicated task of `tasks.md` (OD-PI-14) rewrites that
section to this file list (which has no per-app `requirements.txt`).

```
apps/phantom_invoices/
├── __init__.py
├── app.py                          # Streamlit entry point (path bootstrap at top)
├── config.toml                     # [demo] paths only (no thresholds)
├── settings.py                     # load config.toml, build ctx, demo loading
├── prepare.py                      # quarantine_multi_rate()
├── explain_support.py              # ROW_COLUMNS, TEMPLATES, build_explain_rows, HallucinatingStubClient
├── flashlight.py                   # render_ledger_html(df, lit_refs) — pure, escapes cells
├── detectors/
│   ├── __init__.py                 # auto_discover; LABELS; run_pi_detectors convenience wrapper
│   ├── utils.py                    # as_text/as_decimal/as_date, N1/N2, tax_key/name_key/iban_key,
│   │                               # is_valid_iban, source_ref_key, resolve_as_of, attribute_payment,
│   │                               # reconcile, Reconciliation
│   ├── duplicate_invoice.py        # "pi.duplicate_invoice"
│   ├── iban_change.py              # "pi.iban_change" (UI label: Poltergeist IBAN)
│   ├── vat_error.py                # "pi.vat_error"
│   └── reconciliation.py           # "pi.reconciliation"
└── tests/
    ├── conftest.py
    ├── test_pi_utils.py
    ├── test_pi_prepare.py
    ├── test_pi_duplicate_invoice.py
    ├── test_pi_iban_change.py
    ├── test_pi_vat_error.py
    ├── test_pi_reconciliation.py
    ├── test_pi_explain_support.py
    ├── test_pi_flashlight.py
    ├── test_pi_settings.py
    ├── test_pi_demo_data.py        # generator determinism + identifier rules (REQ-PI-54, 58, 70)
    └── test_pi_demo_e2e.py         # demo triggers every detector (REQ-PI-69)
```

Data files (generated, committed): `data/samples/phantom_demo/{suppliers,invoices,payments}.csv`.
Root-level `requirements.txt` serves both apps; there is no app-level one.

---

## 13 — Testing requirements

- **REQ-PI-61** All three tiers (normal, edge, property) are provided for each of the four
  detectors and for `reconcile`, following `.kiro/steering/testing.md`. Detector tests call the
  detector directly with `MappingProxyType({"suppliers": …, "payments": …, "as_of": …})` and also
  once through `run_all(namespace="pi", context=…)`.
- **REQ-PI-62** Standard fixtures in `apps/phantom_invoices/tests/conftest.py` (all with
  Finance-Rule-5 identifiers, fictional names, fixed literal dates):

  | Fixture | Description |
  |---|---|
  | `empty_ledger` | Invoice-schema DataFrame with zero rows (all `INVOICE_COLUMNS`) |
  | `single_row_ledger` | One clean invoice |
  | `clean_ledger_10` | 10 clean invoices, 10 matching payments and a master: no alert from any detector |
  | `suppliers_master` | Three master suppliers with valid-checksum, wrong-national-digits IBANs |
  | `payments_for_clean` | Payments matching `clean_ledger_10` |
  | `ledger_with_duplicate_invoice` | P1 |
  | `ledger_with_near_duplicate` | P3 |
  | `ledger_with_iban_change` | P5 (invoice + master) |
  | `ledger_with_vat_error` | P7 |
  | `ledger_with_unpaid_invoice` | One overdue invoice and a later payment date to fix `as_of` |
  | `ledger_with_double_payment` | P9 |

- **REQ-PI-63** Acceptance examples P1–P12 are each a named Tier 1 test (section 7); so are the two
  tests of REQ-PI-21a.
- **REQ-PI-64** **Mandatory Hypothesis properties**, all `@settings(max_examples=200)`:

  | Property | File | Description |
  |---|---|---|
  | `test_correct_invoice_never_fires_vat_check` | `test_pi_vat_error.py` | For any base in `[0, 1 000 000]` (2 d.p.) and any rate of `ALLOWED_VAT_RATES`, an invoice with `vat_amount = percent_of(base, rate)` and `total = net_total(...)` raises no `pi.vat_error` alert. |
  | `test_vat_off_by_two_cents_or_more_always_fires` | `test_pi_vat_error.py` | With the VAT amount shifted by any offset of at least `0.02` (either direction, total kept consistent with the stated VAT), exactly one `vat_amount_mismatch` alert is raised. |
  | `test_iban_spacing_and_case_never_fire` | `test_pi_iban_change.py` | Inserting random whitespace (including `\u00a0`) and random case changes into an invoice IBAN equal to the master IBAN never raises `pi.iban_change`. |
  | `test_consecutive_numbers_with_different_totals_never_duplicate` | `test_pi_duplicate_invoice.py` | Consecutive invoice numbers of one supplier (any prefix, year, zero padding, rollover such as `0099`→`0100`) with pairwise different totals and any dates never raise `pi.duplicate_invoice`. |
  | `test_row_order_never_changes_any_detector` | each detector file | Shuffling the rows of the invoices, suppliers and payments frames yields an identical alert list (equal alerts, same order) for all four detectors. |
  | `test_every_invoice_and_supplier_payment_in_exactly_one_bucket` | `test_pi_reconciliation.py` | For random invoices and payments, the keys of `invoice_buckets` equal the usable invoices, the keys of `payment_buckets` equal the supplier payments, each in exactly one bucket, and `matches` is one-to-one. |
  | `test_source_refs_subset_of_loaded_inputs` | each detector file | `Alert.source_refs ⊆ loaded_source_refs(ledger, context)` (REQ-TST-10). |
  | `test_detector_idempotent` | each detector file | Two runs give identical alerts. |
  | `test_alert_data_never_contains_full_iban` | `test_pi_iban_change.py` | For random valid IBANs, no value in any `Alert.data` contains the cleaned full IBAN. |
  | `test_dirty_cells_never_raise` | each detector file | Frames whose cells are drawn from `NaN`, `None`, `""`, `"-"`, `"\u00a0"`, random text, floats and `Decimal` never make any pi detector raise. |
  | `test_empty_input_returns_empty` | each detector file | Empty frames with the right columns, or `pd.DataFrame()`, return `[]`. |

- **REQ-PI-65** Dates are explicit literals; `date.today()` is never read by a detector or test.
  A test proves `as_of` independence from the clock (`freezegun` at two different dates, or
  monkeypatching `date.today` to raise) with identical alert lists (REQ-PI-12).
- **REQ-PI-66** Tier 2 edge cases listed in REQ-PI-21, 28, 33, 40 are named tests; every
  threshold constant is tested on both sides of its boundary (`DUPLICATE_WINDOW_DAYS` 6/7,
  `SAME_NUMBER_WINDOW_DAYS` 179/180,
  `VAT_TOLERANCE` 0.01/0.02, `TOTAL_TOLERANCE` 0.01/0.02, `UNPAID_GRACE_DAYS` 15/16,
  `PAYMENT_MATCH_WINDOW_DAYS` 60/61, `MATCH_AMOUNT_TOLERANCE` 0.01/0.02).
- **REQ-PI-67** Coverage across `apps/phantom_invoices/` must not fall below **80 %**
  (`pytest --cov=apps/phantom_invoices --cov-fail-under=80`); `ruff check` and `ruff format
  --check` pass.
- **REQ-PI-68** Explanation tests (`test_pi_explain_support.py`), all with `MockLLMClient`:
  `row_columns=ROW_COLUMNS` is what reaches the client (no `iban`, no tax id); every template fills
  without leftover braces for a real alert of its variant; a sentence restating only `Alert.data`
  values passes the guard; a hallucinated amount, an uncited date and an IBAN-shaped token fall
  back; `HallucinatingStubClient` yields `source="fallback"` with `rejected_numbers` containing
  `99999.99`; the badge text function returns the three variants of REQ-PI-46.
- **REQ-PI-69** *(end-to-end, `test_pi_demo_e2e.py`)* Loading `data/samples/phantom_demo/*.csv`
  through the same readers and `run_all(namespace="pi")` produces: at least one alert from **each**
  of `pi.duplicate_invoice`, `pi.iban_change`, `pi.vat_error`, `pi.reconciliation`; for every
  planted case of `PHANTOM_CASES` exactly the alerts of section 7 (and none for the "no alert"
  cases); the payment-to-non-master-IBAN, overdue and open_not_due outcomes; the multi-rate rows in
  the quarantine list with `reason="multi_rate_invoice_out_of_scope"` and no alert for them; **no
  alert on any clean supplier**; every `source_refs ⊆ loaded_source_refs`; every explanation
  fallback fills; the result is identical with the clock mocked to two different dates; and every
  alert's `Alert.data` is free of full IBANs.
- **REQ-PI-70** *(demo identifiers)* `test_pi_demo_data.py` asserts REQ-PI-54 (determinism, files
  equal generator output) and REQ-PI-58 (every IBAN mod-97 valid with wrong national check digits;
  every tax id with a wrong control character, all distinct; no real-looking e-mail or phone).

---

## 14 — Dependencies on ledger-core: CR-LC-3 (already applied to the ledger-core spec files)

This spec cannot be implemented without the following ledger-core changes; each is recorded with
its REQs in ledger-core `requirements.md` §9 and mirrored in its `design.md` and `tasks.md`.

| Item | What phantom-invoices needs | Where it is specified |
|---|---|---|
| a | `Invoice` model; `parse_invoice` returns `Invoice`; `IngestionResult` generic; `normalise()` accepts invoices; `due_date` default | REQ-MOD-08, REQ-ING-07/08/30/31/33/34; Tasks 2, 8, 9, 13 |
| b | `Supplier` model and `parse_suppliers` with `source_ref` | REQ-MOD-09, REQ-ING-32/34; Tasks 2, 8, 9, 13 |
| c | `parse_csv` reads optional `iban` verbatim into `Transaction.iban` | REQ-ING-29; Task 6 |
| d | `Alert.source_refs` may cite any loaded input; `loaded_source_refs`; property tests use the union | REQ-DET-03/04/08, REQ-TST-10; Tasks 10, 11, 14 |
| e | `percent_of`, `within_tolerance` (and `net_total`) in `money.py` | REQ-MON-04/05/06; Task 3 |
| f | Context-reading detectors may alert on an empty ledger | REQ-DET-05; Task 10 |
| g | `row_columns` parameter; numbers in `Alert.data`; `mask_iban`; ISO dates in any date column | REQ-EXP-01/08/10/11, REQ-DET-09, REQ-PII-03/04; Tasks 5, 11a |
| h | Finance Rule 5: mod-97-valid IBANs with wrong national digits; tax ids with a wrong control character | `.kiro/steering/finance-rules.md` Rule 5 |

---

## 15 — Non-goals

- No PDF, OCR or image invoice parsing; no download of public invoice datasets (FATURA is not
  used); input is always a file the user provides.
- No live banking, AEAT/SII or VIES connection; tax ids and VAT numbers are never validated.
- No rectifying invoices (*facturas rectificativas*) or credit notes: negative amounts are
  quarantined at ingestion (`negative_amount`).
- No multi-rate or line-level VAT; no IGIC, Ceuta/Melilla, equivalence-surcharge or IRPF *rate*
  checking (the surcharge and withholding amounts are only used in the total).
- No partial payments, instalments, over- or under-payments, payments before the issue date, or
  currency conversion.
- No unknown-supplier alert (an invoice from a supplier absent from the master is simply not
  compared).
- No machine learning, fuzzy matching or probabilistic scoring.
- The LLM layer does not raise, modify or dismiss alerts and does not recommend actions; the only
  advice text is the fixed deterministic `VERIFY_BY_PHONE_MESSAGE` produced by code.

---

## 16 — Open decisions

Every item was reviewed. Items marked **Resolved (accepted)** were accepted as proposed; items
marked **Resolved (changed)** were changed by the review and the affected requirements were edited.

| # | Status | Decision | Resolution |
|---|---|---|---|
| OD-PI-01 | Resolved (accepted) | The brief names two money helpers (`percent_of`, `within_tolerance`) but the total check needs `base + VAT + surcharge − withholding`. | Add a third helper `net_total` to `money.py` (REQ-MON-06) so REQ-MON-03 still holds. |
| OD-PI-02 | Resolved (accepted) | The brief lists no flag for a derived `due_date`. Finance Rule 1 forbids silently filled data. | Add `Invoice.due_date_is_default: bool` (REQ-MOD-08) and carry it into the overdue alert and the UI caption. |
| OD-PI-03 | Resolved (accepted) | Supplier master needs a DataFrame like the other inputs. | `Supplier` model + `normalise(kind="supplier")`; one model kind per `normalise` call, mixing raises `ValueError` (REQ-ING-33). |
| OD-PI-04 | Resolved (accepted) | Registered names. | `pi.duplicate_invoice`, `pi.iban_change`, `pi.vat_error`, `pi.reconciliation`, matching the module names in `structure.md` and the fixture name `ledger_with_iban_change`. "Poltergeist IBAN" is a UI label only. |
| OD-PI-05 | Resolved (accepted) | "Sorted by `(date, source_ref)`": text order puts `f.csv:10` before `f.csv:9`. | Use natural order of `(file, row number)` (REQ-PI-10); still fully deterministic. |
| OD-PI-06 | Resolved (accepted) | Rule C (same total, different numbers, fewer than 7 days) also fires for consecutive numbers that happen to carry equal totals (two identical-price services in one week). | Accept: consecutive numbers prevent only rules A/B, not C, as specified. Tier 2 test documents it. |
| OD-PI-07 | Resolved (changed) | Rule A flags the same number from the same supplier even years apart (annual numbering restart, e.g. `1`). | **Changed:** rule A fires only when the two issue dates are fewer than `SAME_NUMBER_WINDOW_DAYS = 180` apart (REQ-PI-18, REQ-PI-21, REQ-PI-59), so an annual restart does not fire. Tier 1 tests REQ-PI-21a: 2 days apart → `critical`; 200 days apart → no alert. |
| OD-PI-08 | Resolved (accepted) | Multi-rate invoices are quarantined by an app-level step (REQ-PI-15) and also skipped inside the duplicate detector (REQ-PI-16). Limitations: a *duplicated* multi-rate invoice goes unnoticed and its payment shows as `payment_without_invoice`. | Accept; documented in the UI notice for the quarantine panel. |
| OD-PI-09 | Resolved (accepted) | Payment attribution order. | Counterparty name first, then IBAN (REQ-PI-25), so "addressed to a known supplier, sent to another account" is critical. |
| OD-PI-10 | Resolved (accepted) | A malformed IBAN that is not equal to the master. | Validity first: invalid → `warning` only; `critical` only for a valid, different IBAN (REQ-PI-24). |
| OD-PI-11 | Resolved (accepted) | Invoices of suppliers absent from the master. | No IBAN comparison; reconciliation treats them as unpaid (never matched), so they can become `overdue`. |
| OD-PI-12 | Resolved (accepted) | The hallucination stub exists in App 1; apps cannot import each other. | Duplicate it in App 2's `explain_support.py` rather than promote it to `ledger_kit` (which would be a further ledger-core change). |
| OD-PI-13 | Resolved (accepted) | Dialect of the demo files. | Plain dialect for all three, to keep the demo independent of dialect detection. |
| OD-PI-14 | Resolved (changed) | `structure.md` lists a per-app `requirements.txt` and omits `supplier_reader.py`, `reconciliation.py`. | **Changed:** this spec's list (section 12) is definitive, and `tasks.md` will contain **one task** that updates the phantom section of `.kiro/steering/structure.md` (file list, no per-app `requirements.txt`). `structure.md` is not edited by the spec phase. |
| OD-PI-15 | Resolved (accepted) | IBAN validation depth. | Regex + mod-97 only; no per-country length table, no Spanish national check-digit validation. |
| OD-PI-16 | Resolved (accepted) | Surcharge (*recargo de equivalencia*) and withholding (*IRPF*) amounts. | Not recomputed from rates; only used in the total (P8, P11). |
| OD-PI-17 | Resolved (accepted) | Payments dated before the issue date or partial/over-payments. | Not matched; they become `unmatched` and the invoice stays open/overdue. |
| OD-PI-18 | Resolved (accepted) | "Hook 1 test template" in the brief: no hook file exists in the repository. | Interpreted as the Tier 3 property template in `testing.md`, which was updated (CR-LC-3d). |
| OD-PI-19 | Resolved (accepted) | The fixed phone-verification message is advice text. | Allowed because it is deterministic code, shown by the UI and the fallback template; the LLM stays bound by Finance Rule 8. |
