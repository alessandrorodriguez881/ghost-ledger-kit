# real-formats — Requirements

## Overview

Today both apps read only our own CSV and JSON files. `real-formats` lets a judge feed them the files
a Spanish bank and a Spanish supplier really produce:

- **Norma 43** (AEB Cuaderno 43, *Serie normas y procedimientos bancarios n.º 43*, June 2012): the
  fixed-width bank statement, for the Zombie Subscriptions statement and the Phantom Invoices payments.
- **Facturae** 3.2 / 3.2.1 / 3.2.2: the official XML e-invoice, for the Phantom Invoices invoices.

It adds two readers, a format sniffer, a format choice for the demos, and the sample files that make
the demo give **the same alerts** whether it is loaded as CSV or as the real formats. It adds no
detector, changes no threshold and no severity, and publishes nothing.

Ids are `REQ-RF-nn`. EARS keywords: *shall*, *when*, *while*, *where*, *if ... then*. Every example
gives a concrete input and the exact expected output. A line of a Norma 43 example is shown with its
trailing spaces removed; every such line is **right-padded with spaces to 80 characters** before the
reader sees it, except where an example says "as written" (REQ-RF-03 tests unpadded lines on purpose).

Layouts verified (session 8b review): the reviewer compared the Norma 43 layouts with the AEB document
itself (Annex 1 records 11, 22, 23, 24, 33 and 88, Annex 2 concept and currency tables, Annex 4
section 2 SEPA direct debits) and the Facturae paths with the official schema `Facturaev3_2_2.xml`
on facturae.gob.es; every position and path matches.

Existing contracts that stay: `IngestionResult = (valid models, quarantine records)`; a quarantine
record is `{"source_file", "source_row", "reason", "raw"}` (`source_row` is `None` for a whole-file
record); readers never raise on bad input.

---

## 1 — Format sniffer and routing

- **REQ-RF-01** The system shall provide `sniff_format(data: bytes) -> str` returning exactly one of
  `"csv"`, `"json"`, `"norma43"`, `"facturae"`, `"empty"`, `"unknown"` from the first 4096 bytes. It
  shall ignore a UTF-8 BOM and leading whitespace, shall never read the file name, and shall never
  raise. It routes; it does not validate.
  - `b"date,amount,currency,counterparty,description,iban\n2026-01-02,..."` → `"csv"`;
    `b"date;amount;currency;..."` → `"csv"`.
  - `b'[\n  {"invoice_number": "A-1"}\n]'` → `"json"`; `b'{"a": 1}'` → `"json"`.
  - A first non-blank line that starts with `11` followed by 18 digits
    (`b"11999900010000000001260105..."`) → `"norma43"`; `b"11,2026-01-02,..."` → `"csv"`.
  - `b'\xef\xbb\xbf<?xml version="1.0" encoding="UTF-8"?>\n<fe:Facturae xmlns:fe="http://www.facturae.gob.es/formato/Versiones/Facturaev3_2_2.xml">'`
    → `"facturae"`; so is a root without prefix (`<Facturae ...>`).
  - `b'<?xml version="1.0"?><Invoice/>'` → `"unknown"`; `b"%PDF-1.7"` → `"unknown"`;
    `b""` and `b" \r\n\t"` → `"empty"`.

- **REQ-RF-02** The system shall provide `read_bank_statement(source, *, source_file=None)` (accepts
  `csv` and `norma43`) and `read_invoices(source, *, source_file=None)` (accepts `csv`, `json` and
  `facturae`). Each shall sniff the content, call the matching reader and return its
  `IngestionResult`. *If* the sniffed kind is not accepted, *then* the function shall return
  `([], [record])` with `record = {"source_file": name, "source_row": None, "reason":
  "unsupported_format:<kind>", "raw": <message>}` and shall not call any reader. An `"empty"` file
  returns `([], [])`, like the existing readers.
  - `read_bank_statement(<Facturae bytes>, source_file="a.xml")` → `([], [{"source_file": "a.xml",
    "source_row": None, "reason": "unsupported_format:facturae", "raw": "a.xml: this looks like
    Facturae XML; this box accepts CSV or Norma 43."}])`.
  - `read_invoices(b"%PDF-1.7 ...", source_file="f.pdf")` → reason `unsupported_format:unknown`, raw
    `"f.pdf: the format is not recognised; this box accepts CSV, JSON or Facturae."`.
  - `read_invoices(<JSON bytes>, source_file="data.txt")` parses as JSON: the content decides, not the
    extension. This replaces the extension rule that `run_pipeline` uses today.

---

## 2 — Norma 43 reader

- **REQ-RF-03** The system shall provide `parse_norma43(source, *, source_file=None) ->
  IngestionResult[Transaction]` in `ledger_kit/ingestion/norma43_reader.py`, accepting the same
  source types as `parse_csv`. It shall:
  1. decode bytes as UTF-8 (BOM allowed) and, if that fails, as ISO-8859-1 (Latin-1, which never fails);
  2. split lines on `\r\n`, `\r` or `\n` only (never on other Unicode separators);
  3. skip blank lines but count physical lines from 1;
  4. right-pad every line to 80 characters before slicing, and treat positions as 1-based, inclusive;
  5. quarantine a line whose content, after removing trailing spaces, exceeds 80 characters
     (`line_too_long`).
  - A file whose lines are `11...` through `88...` with CRLF, the same file with LF, and the same file
    with every trailing space removed give identical results.
  - Bytes `b"2301Taller Ni\xf1o SL"` (Latin-1) decode the complement text to `Taller Niño SL`.
  - An empty file → `([], [])`.

- **REQ-RF-04** *When* a record `11` is read, the system shall open an account block. It shall read
  bank (3-6), branch (7-10), account (11-20), start date (21-26), end date (27-32), opening-balance
  sign (33: `1` debtor, `2` creditor), opening balance (34-47, 14 digits, 2 implied decimals),
  currency (48-50, ISO 4217 numeric), information mode (51: `1`, `2` or `3`) and holder (52-77).
  Dates are `YYMMDD` and the year is `2000 + YY`. The numeric currency is mapped to its alphabetic code
  by `ledger_kit/ingestion/iso4217.py`, which holds exactly the eleven codes of Annex 2 (no code from
  memory). A file may hold several blocks; each is processed alone.
  *If* a field is malformed, *then* the whole block shall be rejected with one block record
  `{"source_row": <line of the 11>, "reason": "bad_account_header:<field>"}` where `<field>` is one of
  `account`, `start_date`, `end_date`, `balance_sign`, `opening_balance`, `information_mode`; *if* the
  currency code is not in the table, *then* the reason is `unknown_currency_code`. The lines of a
  rejected block up to its record `33` are consumed without further row records; the block record's
  `raw` carries `"dropped_lines": <n>`, the number of non-blank lines after the `11` up to and
  including its `33` (or up to the next `11`, the `88` or the end of the file when there is no `33`).
  - Line 1 `119999000100000000012601052601312000000005000009781TITULAR FICTICIO DEMO` opens the
    account `999900010000000001`, EUR, mode 1, opening balance +5000.00.
  - The same line with `000` at positions 48-50 → block record reason `unknown_currency_code`,
    `source_row` 1.
  - The same line with `3` at position 33 → reason `bad_account_header:balance_sign`.

- **REQ-RF-05** *When* a record `22` is read inside an open block, the system shall produce one
  `Transaction`: `date` from the operation date (11-16), `amount` from the 14 digits at 29-42 divided
  by 100 as an exact `Decimal` (`implied_digits` rule, no float), `flow` from position 28 (`1` →
  `"debit"`, `2` → `"credit"`), `currency` from the block's record 11, `source_file` the file name,
  `source_row` the 1-based line of the `22`, `source_ref = f"{source_file}:{source_row}"`, and
  `iban = None` unless REQ-RF-06 finds one. The value date (17-22) and the document and reference
  fields are validated or ignored as REQ-RF-09 says and never become a figure.
  - Line 2 `22    0001260105260105040001` + `00000000001299` + 22 zeros, in file `acct.n43`, gives
    `Transaction(date=2026-01-05, amount=Decimal("12.99"), flow="debit", currency="EUR",
    source_file="acct.n43", source_row=2, source_ref="acct.n43:2", ...)`.
  - Digits `00000000245000` with key `2` give `amount=Decimal("2450.00")`, `flow="credit"`.
  - Digits `00000000000000` give `amount=Decimal("0.00")` and a valid transaction.

- **REQ-RF-06** *When* a movement has no SEPA layout (REQ-RF-07), the system shall build
  `counterparty` and `description` from its record `23` lines as follows. Each 23's text is positions
  5-80 (two 38-character fields read as one 76-character slice), whitespace runs collapsed to one space
  and trimmed. A text that starts with `IBAN ` is the **IBAN record**: `iban` is the rest of that text,
  verbatim, and the record takes no part in the next two rules. The first remaining text is the
  `counterparty`; the other remaining texts, joined with one space, are the `description`. *If* there
  is no remaining text, *then* both fall back to the common-concept label (REQ-RF-08); *if* there is
  only one remaining text, *then* `description` is the label.
  - `22` (concept `04`, debit 12.99) + `2301Taller Norte SL` + `2302Car repair` → counterparty
    `Taller Norte SL`, description `Car repair`.
  - `22` (concept `15`, credit 2450.00) with no `23` → counterparty `Payroll and social security`,
    description `Payroll and social security`.
  - `22` + `2301Streamly Plus` only → counterparty `Streamly Plus`, description = the label of its
    concept code.
  - `22` + `2301Transportes Hermanos Lage, S.L.` + `2302Supplier payment` +
    `2303IBAN ES88 2100 0418 5602 0005 1332` → counterparty `Transportes Hermanos Lage, S.L.`,
    description `Supplier payment`, iban `ES88 2100 0418 5602 0005 1332`.
  - `2301Ana   García` (three spaces) → counterparty `Ana García`.

- **REQ-RF-07** *Where* the account's information mode is `3` **and** the movement's common concept is
  `03` **and** its record `23-01` carries `CORE` or `B2B` at positions 5-8, the system shall read the
  Annex 4 SEPA direct-debit layout: creditor name (23-01, 9-78) → `counterparty`; remittance concept
  (23-03, 13-80) followed by the continuation (23-04, 5-76), read as one text → `description`. It shall
  add the tags `scheme:<CORE|B2B>`, `creditor_id:<23-02, 5-39>` and `mandate:<23-02, 40-74>`, each
  trimmed and only when non-blank. *If* the creditor name is blank, *then* the counterparty falls back
  to the label; *if* the remittance is blank, *then* the description does. *If* any of the three
  conditions fails, *then* the movement is read as REQ-RF-06.
  - Mode 3, concept `03`, key `1`, amount `00000000001299`, lines
    `2301CORESTREAMFLEX INTL 4412`, `2302ES00ZZZB00000001` + 19 spaces + `MND0001` (so the mandate
    starts at position 40), `2303` + 8 spaces + `Monthly subscription` → counterparty
    `STREAMFLEX INTL 4412`, description `Monthly subscription`, tags include `scheme:CORE`,
    `creditor_id:ES00ZZZB00000001`, `mandate:MND0001`.
  - The same lines under an account with mode `1` → counterparty `CORESTREAMFLEX INTL 4412`
    (generic reading), no `scheme:` tag.
  - `2301B2B ` + name → `scheme:B2B`.

- **REQ-RF-08** Every `Transaction` shall carry these tags, in this order: `account:<bank><branch>
  <account>` (18 digits), `common_concept:<NN>` (positions 23-24), `own_concept:<NNN>` (25-27); then,
  for SEPA, the tags of REQ-RF-07; then, for a record `24`, `original_currency:<alpha>` when the
  numeric code is in the Annex 2 table, else `original_currency_code:<NNN>` (the three digits as read;
  the alphabetic code is never guessed), followed by `original_amount:<amount>`. A record `24` is
  `2401` + original numeric currency (5-7) + amount (8-21, 2 implied decimals); the
  `Transaction.amount` stays the account-currency amount of the `22` and nothing is converted. A code
  outside the table does **not** quarantine the movement: a card purchase abroad is normal. The common-concept label comes from Annex 2: `01` Cheques and withdrawals,
  `02` Deposits, `03` Direct debits and bills, `04` Transfers, `05` Loan repayments, `06` Bill
  remittances, `07` Securities subscriptions, `08` Dividends and coupons, `09` Stock operations, `10`
  Fuel cheques, `11` ATM, `12` Credit and debit cards, `13` Foreign operations, `14` Returns and unpaid
  items, `15` Payroll and social security, `16` Stamp duty and brokerage, `17` Interest, fees and taxes,
  `98` Cancellations and corrections, `99` Other; any other two digits are accepted with the label
  `Other`.
  - Movement `22 ... 12 000 1 00000000001378` in account `999900010000000001` + `2401840` +
    `00000000001500` → tags `["account:999900010000000001", "common_concept:12", "own_concept:000",
    "original_currency:USD", "original_amount:15.00"]`, amount `13.78`.
  - A `24` with `999` at 5-7 and `00000000001500` → a valid movement whose last two tags are
    `original_currency_code:999` and `original_amount:15.00`.
  - A `24` with `8A0` at 5-7, a `24` shorter than its amount field or with a non-digit amount, or a
    second `24` after the first → quarantine `bad_currency_equivalence` for the movement (REQ-RF-09).

- **REQ-RF-09** The system shall quarantine at **row level** — one record with `source_row` the
  1-based line of the offending `22` (or of the stray line) and `raw` the line(s) joined with `\n`, and
  keep reading — in these cases:

  | reason | case |
  |---|---|
  | `line_too_long` | content beyond position 80 |
  | `unknown_record_code:<cc>` | first two characters not `11 22 23 24 33 88` |
  | `movement_without_account_header` | a `22` before any `11`, or after the block's `33` |
  | `complement_without_movement` | a `23` or `24` with no open `22` |
  | `too_many_complements` | a sixth `23` (only that line; the movement stays valid) |
  | `bad_complement_sequence` | a `23` whose positions 3-4 are not the next of `01`..`05` |
  | `bad_date:operation_date`, `bad_date:value_date` | not `YYMMDD`, or an impossible date |
  | `bad_dc_key` | position 28 not `1` or `2` |
  | `non_digit_amount` | positions 29-42 not 14 digits |
  | `bad_concept_code` | positions 23-24 or 25-27 not digits |
  | `bad_currency_equivalence` | a malformed (non-digit currency or amount) or repeated `24`; a well-formed `24` with a numeric code outside the table is **valid** (REQ-RF-08) |
| `trailer_without_account_header` | a `33` with no open account block |
  | `record_after_end_of_file` | a non-blank line after the `88` |

  A quarantined `22` takes its `23` and `24` lines with it. *If* the key and amount of a quarantined
  `22` are valid, *then* it still counts in the control sums of REQ-RF-10 (a bad date shall not
  reject the whole account).
  - File A with the operation date of line 2 changed to `261340`: transactions = only the line-5
    movement; quarantine = one record `{"source_file": "acct.n43", "source_row": 2, "reason":
    "bad_date:operation_date", "raw": <lines 2-4 joined with "\n">}`; the control checks still pass.
  - A `22` with amount `0000000000A299` → `non_digit_amount`, and the block then fails (REQ-RF-10): with
    `debit_count` when the `33` still counts that record (Fixture A with the amount spoiled), with
    `unverifiable_movement` when the `33` counts only the readable records, because the checks run in
    the REQ-RF-10 order and name the first failure.
  - A file starting with `55 anything` → `unknown_record_code:55`, `source_row` 1.
  - A file starting with a `22` line → `movement_without_account_header`, `source_row` 1.
  - Six `23` lines after one `22` → five used; the sixth quarantined `too_many_complements`.

- **REQ-RF-10** *When* a record `33` closes a block, the system shall run these control checks, in this
  order, over the block's `22` records (valid and row-quarantined alike, REQ-RF-09), and shall name the
  first failing check. *If* any check fails, *then* the system shall return **none** of the block's
  transactions and one block record `{"source_row": <line of the 11>, "reason":
  "control_check_failed:<check>", "raw": {"account", "declared", "computed", "line_33"}}`:
  1. `account_mismatch`: bank, branch, account of the `33` (3-20) differ from the `11`;
  2. `debit_count`: positions 21-25 ≠ number of `22` with key `1`;
  3. `debit_total`: 26-39 ≠ sum of their amounts;
  4. `credit_count`: 40-44 ≠ number of `22` with key `2`;
  5. `credit_total`: 45-58 ≠ sum of their amounts;
  6. `balance`: opening balance + credits − debits ≠ closing balance, where a debtor sign (`1`)
     makes the balance negative and a creditor sign (`2`) positive (closing sign at 59, closing
     balance 60-73);
  7. `unverifiable_movement`: a `22` whose key or amount cannot be read, so the sums cannot be trusted.

  *If* a block reaches the end of the file or the next `11` without a `33`, *then* it is rejected as
  `control_check_failed:missing_end_of_account`. Sums use `Decimal` through `money.py` only.
  - File A (Fixture A, below REQ-RF-11) passes: debits 1 × 12.99, credits 1 × 2450.00,
    5000.00 + 2450.00 − 12.99 = 7437.01.
  - Debit total changed to `00000000001300` → transactions `[]`, one record
    `{"source_row": 1, "reason": "control_check_failed:debit_total", "raw": {"account":
    "999900010000000001", "declared": "13.00", "computed": "12.99", "line_33": 6}}`.
  - Closing balance changed to `00000000743700` → reason `control_check_failed:balance`, declared
    `7437.00`, computed `7437.01`.
  - Opening sign `1` (debtor 5000.00) with closing sign `1` and `00000000256299`: −5000.00 + 2450.00 −
    12.99 = −2562.99 → passes. The same closing with sign `2` fails `balance`.
  - Two blocks in one file where only the second has a wrong credit count: the first block's
    transactions are returned, the second block yields one record `control_check_failed:credit_count`.

  The apps shall show every `control_check_failed:*` record with one plain message, the constant
  `CONTROL_CHECK_FAILED_MESSAGE` of `norma43_reader.py` (used by RF9 and RF10): *"This bank file is
  incomplete or was edited: its totals do not match its movements. Download a fresh export from your
  bank and load it again."*

- **REQ-RF-11** *When* the record `88` is read, the system shall check that positions 3-20 are
  eighteen `9`s and that positions 21-26 equal the number of non-blank lines before the `88` (every
  record kind counted, the `88` excluded). *If* the `88` is missing, malformed or its count differs,
  *then* the system shall return **no** transaction at all, keep the row-level and block records
  already produced, and add one file record `{"source_row": None, "reason":
  "control_check_failed:record88_missing" | "control_check_failed:record88_count" |
  "control_check_failed:record88_format", "raw": {"declared", "computed"}}`.
  - File A has 6 record lines before the `88`; `88999999999999999999000006` passes.
  - `88999999999999999999000007` → `record88_count`, declared `7`, computed `6`, transactions `[]`.
  - File A without its last line → `record88_missing`, transactions `[]`.

### Fixture A (used by REQ-RF-04 to REQ-RF-11)

File `acct.n43`, LF line endings, trailing spaces removed:

```
119999000100000000012601052601312000000005000009781TITULAR FICTICIO DEMO
22    0001260105260105040001000000000012990000000000000000000000
2301Taller Norte SL
2302Car repair
22    0001260128260128150002000000002450000000000000000000000000
3399990001000000000100001000000000012990000100000000245000200000000743701978
88999999999999999999000006
```

The file has seven lines: `11` (line 1), `22` (2), `23` (3), `23` (4), `22` (5), `33` (6), `88` (7); the
`88` counts the six lines before it. Field breakdown of the two `22` lines (the tests build them from
fields, so a miscount in this document cannot hide a reader bug): `22`, four blanks, branch `0001`,
operation date, value date (same), common concept (`04` / `15`), own concept `000`, key (`1` / `2`),
14-digit amount (`00000000001299` / `00000000245000`), document number `0000000000`, reference 1
`000000000000`, then sixteen blanks. Record `33`: bank `9999`, branch `0001`, account `0000000001`,
`00001`, `00000000001299`, `00001`, `00000000245000`, sign `2`, `00000000743701`, `978`, four blanks.
Expected transactions: line 2 → `2026-01-05`, `12.99`, debit, EUR, counterparty
`Taller Norte SL`, description `Car repair`, tags `["account:999900010000000001",
"common_concept:04", "own_concept:000"]`, `source_ref` `acct.n43:2`; line 5 → `2026-01-28`, `2450.00`,
credit, EUR, counterparty and description `Payroll and social security`, tags
`["account:999900010000000001", "common_concept:15", "own_concept:000"]`, `source_ref` `acct.n43:5`.

---

## 3 — Facturae reader

- **REQ-RF-12** The system shall provide `parse_facturae(source, *, source_file=None) ->
  IngestionResult[Invoice]` in `ledger_kit/ingestion/facturae_reader.py`. It shall match elements by
  **local name** (any or no namespace) and read `FileHeader/SchemaVersion`; versions `3.2`, `3.2.1`
  and `3.2.2` are supported. It shall return a whole-file record (`source_row` `None`) when:
  - the content is not well-formed XML → `invalid_xml`;
  - the document is larger than `MAX_FACTURAE_BYTES` (10 MiB) → `file_too_large`;
  - the root is not `Facturae` → `not_facturae`;
  - the version is missing or not supported → `unsupported_version:<text>` (`unsupported_version:` when
    missing);
  - there is no `Invoices/Invoice` → `no_invoices`.
  - `<fe:Facturae xmlns:fe="http://www.facturae.gob.es/formato/Versiones/Facturaev3_2_2.xml">` with
    unqualified children, and the same document with every element qualified, read the same.
  - `<Facturae><FileHeader><SchemaVersion>3.1</SchemaVersion>...` → `unsupported_version:3.1`.
  - `<Order/>` → `not_facturae`; `<Facturae><unclosed>` → `invalid_xml`.

- **REQ-RF-13** For each `Invoices/Invoice` (1-based position `n`), the system shall build one
  `Invoice` with `source_file` the file name, `source_row = n` and `source_ref = f"{source_file}:{n}"`.
  A file has one seller (`Parties/SellerParty`) and may hold several invoices. Field mapping:

  | Invoice field | Facturae path (from `Facturae`) |
  |---|---|
  | `supplier_tax_id` | `Parties/SellerParty/TaxIdentification/TaxIdentificationNumber`, trimmed, verbatim |
  | `supplier_name` | `SellerParty/LegalEntity/CorporateName`, else `SellerParty/Individual/Name`, `FirstSurname`, `SecondSurname` (present, non-blank parts joined by one space) |
  | `invoice_number` | `InvoiceHeader/InvoiceSeriesCode` + `InvoiceHeader/InvoiceNumber` (series first, no separator) |
  | `issue_date` | `InvoiceIssueData/IssueDate` |
  | `currency` | `InvoiceIssueData/InvoiceCurrencyCode` |
  | `base_amount`, `vat_rate`, `vat_amount` | the one `TaxesOutputs/Tax` with `TaxTypeCode` `01`: `TaxableBase/TotalAmount`, `TaxRate`, `TaxAmount/TotalAmount` |
  | `surcharge_amount` | that Tax's `EquivalenceSurchargeAmount/TotalAmount`; `Decimal("0")` when the Tax has no `EquivalenceSurcharge` |
  | `withholding_amount` | sum of `TaxesWithheld/Tax[TaxTypeCode=04]/TaxAmount/TotalAmount`; `Decimal("0")` when absent |
  | `total` | `InvoiceTotals/InvoiceTotal` |

  `TotalGrossAmountBeforeTaxes`, `TotalTaxOutputs`, `TotalOutstandingAmount`, `PersonTypeCode`,
  `ResidenceTypeCode`, `PaymentMeans`, items and batch totals are not read: the detectors, not the
  reader, check arithmetic. *If* `TaxAmount` is absent the reader shall not compute it; it quarantines
  (REQ-RF-17).
  - Series `A`, number `0042` → `invoice_number` `A0042`; no series, number `F-2026-0310` →
    `F-2026-0310`.
  - `Individual` with Name `Ana`, FirstSurname `García (Asesoría Fiscal)`, no SecondSurname →
    `Ana García (Asesoría Fiscal)`.
  - Example A below: second invoice of a file gets `source_ref` `aurora.xml:2`.

- **REQ-RF-14** Amounts are `xs:double` text with up to eight decimals. The system shall read every
  amount with `Decimal(text)` (never `float`), reject non-finite values, and then:
  - the five money amounts (`base`, `vat`, `surcharge`, `withholding`, `total`) are rounded to cents
    with `round_to_cents` (half-up, Finance Rule 3) **at ingestion**, the only place the reader rounds;
  - the negativity check of REQ-RF-17 is made on the value as read, before rounding;
  - `vat_rate` is not money: it is kept exact, written without trailing zeros and without exponent
    (`Decimal(format(rate.normalize(), "f"))`), so `21.00` and `21.00000000` both give `Decimal("21")`
    and `5.20` gives `Decimal("5.2")`, the same value the CSV reader yields for `21` and `5.2`.
  - `400.004` → `Decimal("400.00")`; `400.005` → `Decimal("400.01")`; `0.125` → `Decimal("0.13")`;
    `1.0E2` → `Decimal("100.00")`; `84` → `Decimal("84.00")`.
  - `12,5`, `NaN`, `INF`, `abc` → `unparseable_amount`.

- **REQ-RF-15** *When* the invoice has `PaymentDetails/Installment`, the system shall set `due_date` to
  the **latest** `InstallmentDueDate` and `due_date_is_default = False`; the `iban` is the first
  non-blank `AccountToBeCredited/IBAN`, verbatim. *If* there is no installment, *then* `due_date =
  issue_date + DEFAULT_PAYMENT_TERM_DAYS` and `due_date_is_default = True`, exactly as the CSV reader.
  `AccountNumber` is not an IBAN and is ignored (`iban = None`); nothing is invented to turn it into
  one. Dates are `xs:date` and may carry a zone suffix (`Z`, `+01:00`), which is ignored.
  - One installment due `2026-11-05`, IBAN `ES8821000418560200051332` → `due_date=2026-11-05`,
    `due_date_is_default=False`, `iban="ES8821000418560200051332"`.
  - No `PaymentDetails`, issue date `2026-10-06` → `due_date=2026-11-05`, `due_date_is_default=True`,
    `iban=None`.
  - Installments due `2026-11-05` and `2026-12-05` → `due_date=2026-12-05`.
  - `IssueDate` `2026-10-06Z` → `2026-10-06`; `IssueDate` `06/10/2026` → `unparseable_date`.
  - Two installments naming different IBANs (compared after removing spaces and upper-casing) →
    `conflicting_iban`.

- **REQ-RF-16** *If* one invoice has more than one `TaxesOutputs/Tax` with `TaxTypeCode` `01`, *then*
  the reader shall quarantine **that invoice** as `multiple_vat_rates` (the Facturae form of the
  existing multi-rate case; the CSV form is still handled by `prepare.quarantine_multi_rate`).
  - An invoice with Tax `01` at 21.00 (base 800.00) and Tax `01` at 10.00 (base 200.00) → no
    `Invoice`; one record `{"source_row": 3, "reason": "multiple_vat_rates"}` when it is the third
    invoice.

- **REQ-RF-17** The system shall quarantine at **invoice level** (record `source_row = n`, `raw` a
  dict of the strings that were read) for: `missing_field:<name>` with `<name>` one of
  `supplier_tax_id`, `supplier_name`, `invoice_number`, `issue_date`, `currency`, `base_amount`,
  `vat_rate`, `vat_amount`, `surcharge_amount` (surcharge declared without an amount), `total`;
  `missing_vat_tax` (no Tax `01`); `unsupported_tax_type:<code>` (a Tax whose code is not `01` in
  `TaxesOutputs` or not `04` in `TaxesWithheld`: dropping it would make the total irreconcilable);
  `unparseable_date`; `unparseable_amount`; `negative_amount` (any of the six amounts below zero, so
  corrective invoices with negative amounts are quarantined, as in the CSV reader); `multiple_vat_rates`;
  `conflicting_iban`. One bad invoice never stops the others.
  - A file of three invoices whose second has no `InvoiceTotal` → two `Invoice` (`f.xml:1`, `f.xml:3`)
    and one record `{"source_row": 2, "reason": "missing_field:total"}`.
  - An IGIC tax (`TaxTypeCode` `03`) → `unsupported_tax_type:03`.
  - `TaxAmount` absent → `missing_field:vat_amount`.

- **REQ-RF-18** The system shall parse untrusted XML only with `defusedxml.ElementTree.fromstring(data,
  forbid_dtd=True)` (with its default `forbid_entities=True`, `forbid_external=True`). *If*
  `DefusedXmlException` is raised (DTD, entity or external reference), *then* the file is quarantined
  as `forbidden_xml_construct`; *if* `ParseError` is raised, as `invalid_xml`. No other XML parser
  (`xml.etree`, `xml.dom`, `xml.sax`, `lxml`) shall be imported by the reader. The size limit of
  REQ-RF-12 is checked before parsing.
  - The classic billion-laughs document (`<!DOCTYPE lolz [<!ENTITY lol "lol"> <!ENTITY lol2
    "&lol;&lol;..."> ...]><lolz>&lol9;</lolz>`) → `([], [{"reason": "forbidden_xml_construct", ...}])`,
    returned without expanding anything.
  - `<!DOCTYPE x SYSTEM "http://127.0.0.1/x.dtd"><Facturae/>` → `forbidden_xml_construct`; nothing is
    fetched.

- **REQ-RF-19** *Where* the file is a signed Facturae (`.xsig`: an enveloped `ds:Signature` inside the
  root), the reader shall read it exactly like an unsigned file and shall **not** verify the signature;
  the apps shall say so (REQ-RF-23).
  - The Example A document with a `<ds:Signature>` child of the root, whatever its content, gives the
    same `Invoice` as without it.

### Example A (Facturae)

File `aurora.xml` (children unqualified, as real files):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<fe:Facturae xmlns:fe="http://www.facturae.gob.es/formato/Versiones/Facturaev3_2_2.xml">
  <FileHeader><SchemaVersion>3.2.2</SchemaVersion></FileHeader>
  <Parties>
    <SellerParty>
      <TaxIdentification><PersonTypeCode>J</PersonTypeCode><ResidenceTypeCode>R</ResidenceTypeCode>
        <TaxIdentificationNumber>B00000001</TaxIdentificationNumber></TaxIdentification>
      <LegalEntity><CorporateName>Suministros Ibéricos Aurora, S.L.</CorporateName></LegalEntity>
    </SellerParty>
  </Parties>
  <Invoices><Invoice>
    <InvoiceHeader><InvoiceNumber>F-2026-0310</InvoiceNumber></InvoiceHeader>
    <InvoiceIssueData><IssueDate>2026-10-06</IssueDate><InvoiceCurrencyCode>EUR</InvoiceCurrencyCode></InvoiceIssueData>
    <TaxesOutputs><Tax><TaxTypeCode>01</TaxTypeCode><TaxRate>21.00</TaxRate>
      <TaxableBase><TotalAmount>400.00</TotalAmount></TaxableBase>
      <TaxAmount><TotalAmount>84.00</TotalAmount></TaxAmount></Tax></TaxesOutputs>
    <InvoiceTotals><TotalGrossAmountBeforeTaxes>400.00</TotalGrossAmountBeforeTaxes>
      <TotalTaxOutputs>84.00</TotalTaxOutputs><InvoiceTotal>484.00</InvoiceTotal></InvoiceTotals>
    <PaymentDetails><Installment><InstallmentDueDate>2026-11-05</InstallmentDueDate>
      <InstallmentAmount>484.00</InstallmentAmount><PaymentMeans>04</PaymentMeans>
      <AccountToBeCredited><IBAN>ES8821000418560200051332</IBAN></AccountToBeCredited></Installment></PaymentDetails>
  </Invoice></Invoices>
</fe:Facturae>
```

Expected: one `Invoice(invoice_number="F-2026-0310", supplier_name="Suministros Ibéricos Aurora, S.L.",
supplier_tax_id="B00000001", issue_date=2026-10-06, due_date=2026-11-05, due_date_is_default=False,
base_amount=Decimal("400.00"), vat_rate=Decimal("21"), vat_amount=Decimal("84.00"),
surcharge_amount=Decimal("0"), withholding_amount=Decimal("0"), total=Decimal("484.00"),
iban="ES8821000418560200051332", currency="EUR", source_file="aurora.xml", source_row=1,
source_ref="aurora.xml:1")`, no quarantine.

---

## 4 — Applications

- **REQ-RF-20** The Zombie Subscriptions statement uploader and the Phantom Invoices payments uploader
  shall accept the extensions `csv`, `n43`, `txt`, `aeb`, `csb43` and route every file through
  `read_bank_statement` (REQ-RF-02). The Phantom Invoices invoices uploader shall accept `csv`, `json`,
  `xml`, `xsig`, with `accept_multiple_files=True`, and route every file through `read_invoices`. The
  supplier master stays a CSV-only uploader. The extension only filters the file dialog; the content
  decides.
  - A `.txt` file holding Norma 43 in the statement uploader is read as Norma 43.
  - A Facturae `.xml` in the payments uploader shows the `unsupported_format:facturae` record in the
    quarantine panel with the message of REQ-RF-02, and the page does not crash.

- **REQ-RF-21** *When* several invoice files are loaded, the Phantom Invoices app shall read them in
  **file-name order** (plain string sort), merge all invoices into one frame, and give every
  invoice the `source_ref` of its own file. *If* two files share a name, *then* the second is not read
  and one record `duplicate_file_name` is quarantined. The pipeline cache key shall cover every file's
  name and content hash in that order.
  - Files `02-b.xml` then `01-a.xml` selected in that order give the same alerts, in the same order, as
    `01-a.xml` then `02-b.xml`.

- **REQ-RF-22** Widget keys shall be unique across the showcase: `zs_upload_statement`,
  `zs_demo_format`, `pi_upload_invoices`, `pi_upload_suppliers`, `pi_upload_payments`,
  `pi_demo_format`. The two demo-format keys shall be in each app's `WIDGET_KEYS` (state survives
  navigation, REQ-SC-05). The demo shall still load through the `on_click` callback of the existing
  *Load demo data* button, which reads the format widget's value.
  - The union of the session-state keys of both apps (in an `AppTest` run of each) has no common member.

- **REQ-RF-23** *When* a loaded invoice source is Facturae, the Phantom Invoices page shall show the
  caption `Facturae digital signatures (.xsig) are read but not verified: this app does not check who
  signed a file.` *When* a file is loaded, the page shall name its detected format (for example
  `payments.n43: Norma 43`).
  *When* the payments file is Norma 43 and none of its movements carries an IBAN record (REQ-RF-06),
  the page shall show one plain caption, the constant `NO_PAYMENT_IBAN_NOTE` (implemented in RF9):
  *"This Norma 43 file carries no IBAN for its payments, so the payment-side IBAN checks are skipped
  for this file."* The standard has no counterparty IBAN field (DN-RF-03), so this is expected for
  real bank files.

- **REQ-RF-24** Each app shall offer a demo format choice, `st.radio` with the options `CSV` and
  `Real formats`. With `CSV` the demo loads exactly the files it loads today. With `Real formats`:
  - Zombie Subscriptions loads `data/samples/zombie_demo_statement.n43`;
  - Phantom Invoices loads `data/samples/phantom_demo/suppliers.csv`,
    `data/samples/phantom_demo/payments.n43` and every `*.xml` in
    `data/samples/phantom_demo/facturae/` (REQ-RF-21 order).
  Paths come from each app's `config.toml` `[demo]` table (no thresholds, no secrets).

- **REQ-RF-25** *When* the demo is loaded as `Real formats`, each app shall show **exactly** the alerts
  it shows today for `CSV`: same detectors, same severities, same titles, same figures in `Alert.data`;
  only the `source_refs` (and therefore `Alert.id` and the cited-row text) differ. Counts:
  - Zombie Subscriptions: 3 tombstones and 19 alerts: 1 critical, 4 warning, 14 info.
  - Phantom Invoices: 9 alerts: 3 critical, 6 warning.
  The multi-rate invoice is quarantined in both: as two CSV rows
  (`multi_rate_invoice_out_of_scope`) and as one Facturae invoice (`multiple_vat_rates`); the app note
  that explains multi-rate quarantine shall cover both reasons.
  - For each alert, mapping every cited `source_ref` to the position of its row in the ordered input
    (CSV row *i* ↔ *i*-th `22` line / *i*-th valid invoice) turns the Norma 43/Facturae alert list into
    the CSV alert list element for element.

---

## 5 — Sample data

- **REQ-RF-26** `scripts/generate_samples.py` shall also write, from the **same seeded rows** as the
  CSV demos and byte-stable for a given `--seed`:
  `data/samples/zombie_demo_statement.n43`, `data/samples/phantom_demo/payments.n43` and one Facturae
  file per supplier, `data/samples/phantom_demo/facturae/<kk>-<case>.xml` (`kk` the two-digit supplier
  position `k`, `case` lower-cased with `_` → `-`, for example `01-p1.xml`, `13-non-master-payment.xml`,
  `17-c1.xml`). Each Facturae file has `FileHeader/Modality` `I` (one invoice) or `L` (a batch of several
  invoices), with the `Batch` totals computed by `sum_amounts`. The `.n43` files are written ISO-8859-1, CRLF, lines padded to 80 characters, one
  account in information mode 1 (zombie: mode 3, see below); the `.xml` files UTF-8, LF, one
  `<?xml ...?>` declaration. The CSV demo files stay byte-identical to today's.
  - Re-running with `--seed 42` leaves every committed byte unchanged.
  - Zombie rows described `Monthly subscription` are written as SEPA direct debits
    (information mode 3, concept `03`) with a fictional creditor identifier `ES00ZZZ` + a wrong-control
    CIF, mandate `MND<nnnn>`; the CSV and the Norma 43 give the same counterparty and description.

- **REQ-RF-27** `.gitattributes` shall mark the new samples `-text` (`data/samples/*.n43`,
  `data/samples/phantom_demo/*.n43`, `data/samples/phantom_demo/facturae/*.xml`), and the existing
  test that the committed samples equal the generator output shall cover them byte for byte, with no
  line-ending normalisation.

- **REQ-RF-28** All sample data shall stay synthetic (Finance Rules 5 and 6): fictional names, IBANs
  with a valid mod-97 checksum and wrong national digits, tax ids with a wrong control character,
  creditor identifiers with check digits `00`, bank code `9999` for the demo account, a fictional
  buyer in every Facturae file, no e-mail and no phone.

---

## 6 — Dependencies and quality

- **REQ-RF-29** `defusedxml==0.7.1` shall be pinned in `requirements.txt` and in the runtime
  `dependencies` of `pyproject.toml`; no other new runtime dependency is allowed. *When* the showcase
  requirements test runs, it shall find `defusedxml` among the pinned imports.

- **REQ-RF-30** Money arithmetic shall stay in `ledger_kit/utils/money.py`. It shall gain
  `sum_amounts`, `balance_after`, `apply_sign`, `decimal_from_implied` and `implied_digits`
  (design §2); the readers and the generator call them and do no arithmetic on amounts themselves.

- **REQ-RF-31** Both readers and the sniffer shall ship with the three test tiers of `testing.md`:
  hand-made field-level fixtures (a SEPA direct debit, a record 24, two accounts in one file, missing
  trailing spaces, CRLF, Latin-1 names, every quarantine reason of REQ-RF-04, -09, -10, -11, -12, -15,
  -16, -17 and every control check); edge cases (empty input, single record, amount and date
  boundaries); Hypothesis properties with `max_examples=200`:
  - **round trip**: rows written as Norma 43 (or as Facturae) and read back equal the canonical rows;
  - **no invention**: every `source_ref` of a returned transaction is the line of a `22` of the input,
    every `source_ref` of a returned invoice is `file:n` with `1 ≤ n ≤` the number of `Invoice`
    elements, and detector alerts over the loaded frames cite only `loaded_source_refs`;
  - **tamper detection**: changing one digit of the amount field of a `22` in a valid file always
    yields no transaction for that block and a `control_check_failed` record;
  - **never raises**: arbitrary bytes give lists from `sniff_format`, `parse_norma43`, `parse_facturae`
    and both routers.
  The demo equivalence (REQ-RF-25) runs end to end through `AppTest` in both apps. A test feeds the
  billion-laughs payload of REQ-RF-18.
