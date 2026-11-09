# real-formats — Design

Covers `REQ-RF-01` to `REQ-RF-31`. Section numbers (§) are cited by `tasks.md`; decisions are `DN-RF-nn`
(§10). Nothing here changes a detector, a threshold or a severity.

## 1 — Module map

New (all under the existing package boundaries of `structure.md`; `ledger_kit` imports no app):

| File | Role |
|---|---|
| `ledger_kit/ingestion/sniffer.py` | `sniff_format`, `read_bank_statement`, `read_invoices`, format labels and messages (§3) |
| `ledger_kit/ingestion/norma43_reader.py` | `parse_norma43` (§4) |
| `ledger_kit/ingestion/iso4217.py` | `NUMERIC_TO_ALPHA: dict[str, str]` (§4.6) |
| `ledger_kit/ingestion/facturae_reader.py` | `parse_facturae` (§5) |
| `tests/ingestion/{test_sniffer,test_norma43_reader,test_norma43_controls,test_facturae_reader,test_facturae_security,test_real_formats_roundtrip}.py`, `tests/ingestion/n43_builders.py`, `tests/ingestion/rf_strategies.py` | tests (§9) |
| `tests/test_generate_real_formats.py` | generator tests (§8) |
| `apps/zombie_subscriptions/tests/test_zs_real_formats.py`, `apps/phantom_invoices/tests/test_pi_real_formats.py` | app and equivalence tests |
| `data/samples/zombie_demo_statement.n43`, `data/samples/phantom_demo/payments.n43`, `data/samples/phantom_demo/facturae/*.xml` | samples, written by the generator, not by hand |

Edited: `ledger_kit/utils/money.py` (§2); `apps/*/settings.py`, `apps/*/app.py`, `apps/*/config.toml`
(§7); `scripts/generate_samples.py` (§8); `.gitattributes`; `requirements.txt`, `pyproject.toml`;
`.kiro/steering/structure.md`, `tech.md` (last task); the tests that pin the changed widget keys and
`DemoInputs` fields.

The readers share `IngestionResult`, `_read_source`, `_decode`-style helpers and the quarantine-record
shape of `csv_reader.py`. Whole-file records use `source_row: None`, like `undecodable_file`.

## 2 — Money helpers (REQ-RF-30)

`money.py` is the only place that does arithmetic on amounts, so the readers and the generator need
these (all pure, all `Decimal`):

```python
def sum_amounts(values: Iterable[Decimal]) -> Decimal: ...          # Decimal("0") for no values
def balance_after(opening: Decimal, credits: Decimal, debits: Decimal) -> Decimal: ...
def apply_sign(amount: Decimal, negative: bool) -> Decimal: ...     # -amount or amount
def decimal_from_implied(digits: str, places: int = 2) -> Decimal: ...
def implied_digits(amount: Decimal, width: int = 14) -> str: ...
```

- `decimal_from_implied("00000000001299")` → `Decimal("12.99")`. It builds the value from the text
  (`"12.99"`) instead of dividing, so no context rounding is involved. It raises `ValueError` on a
  non-digit or empty string.
- `implied_digits(Decimal("12.99"))` → `"00000000001299"`. It applies `round_to_cents` first, raises
  `ValueError` for a negative amount or one wider than `width`.
- Round trip: `decimal_from_implied(implied_digits(x)) == round_to_cents(x)` is a Hypothesis property
  in `tests/test_money.py`.

## 3 — Sniffer and router (REQ-RF-01, REQ-RF-02)

```python
FormatKind = Literal["csv", "json", "norma43", "facturae", "empty", "unknown"]
def sniff_format(data: bytes) -> FormatKind: ...
def read_bank_statement(source, *, source_file=None) -> IngestionResult[Transaction]: ...
def read_invoices(source, *, source_file=None) -> IngestionResult[Invoice]: ...
```

`sniff_format` looks at `data[:4096]`, removes a UTF-8 BOM, then:

1. all whitespace (or no bytes) → `empty`;
2. first non-whitespace byte `[` or `{` → `json`;
3. first non-blank line matches `^11\d{18}` → `norma43`;
4. first non-whitespace byte `<` → search the first start tag `<([A-Za-z_][\w.\-]*:)?([A-Za-z_][\w.\-]*)`
   (a declaration `<?`, comment `<!--` or `<!DOCTYPE` never matches because `!` and `?` are not name
   starts); local name `Facturae` → `facturae`, otherwise `unknown`;
5. first line contains `,` or `;` → `csv`;
6. otherwise `unknown`.

UTF-16 files fall to `unknown` (no BOM rule for them): the message tells the user the file is not
recognised; supporting UTF-16 is not worth a rule nobody asked for.

The two routers call `_read_source`, sniff the bytes (`str` content is encoded to UTF-8 first), and
dispatch: `csv` → `parse_csv` / `parse_invoice(fmt="csv")`, `json` → `parse_invoice(fmt="json")`,
`norma43` → `parse_norma43`, `facturae` → `parse_facturae`. An unaccepted kind gives the record of
REQ-RF-02 with `raw` built by `unsupported_message(name, kind, accepted)`:

| kind | text after `"<name>: "` |
|---|---|
| csv | `this looks like CSV` |
| json | `this looks like JSON` |
| norma43 | `this looks like Norma 43` |
| facturae | `this looks like Facturae XML` |
| unknown | `the format is not recognised` |

followed by `; this box accepts <accepted>.`, where `<accepted>` is `CSV or Norma 43` for bank
statements and `CSV, JSON or Facturae` for invoices. These strings are constants of `sniffer.py`.

Why content, not extension (DN-RF-17): the uploader's `type` list only filters the file dialog, and a
bank may name a Norma 43 file `.txt`, `.aeb` or nothing at all.

## 4 — Norma 43 reader (REQ-RF-03 to REQ-RF-11)

### 4.1 Layout tables (1-based, inclusive; verified against the AEB document)

Verified in the session 8b review: the reviewer compared this table with the AEB document itself
(*Serie normas y procedimientos bancarios n.º 43*, June 2012, Annex 1 records 11, 22, 23, 24, 33 and 88,
Annex 2 concept and currency tables, Annex 4 section 2 SEPA direct debits); every position matches.

| Record | Fields |
|---|---|
| `11` | code 1-2 · bank 3-6 · branch 7-10 · account 11-20 · start 21-26 · end 27-32 · sign 33 · opening 34-47 · currency 48-50 · mode 51 · holder 52-77 |
| `22` | code 1-2 · branch 7-10 · operation date 11-16 · value date 17-22 · common concept 23-24 · own concept 25-27 · key 28 · amount 29-42 · document 43-52 · ref 1 53-64 · ref 2 65-80 |
| `23` generic | code 1-2 · sequence 3-4 (`01`..`05`) · text 5-80 (two 38-char fields) |
| `23` SEPA | `01`: scheme 5-8, creditor name 9-78 · `02`: creditor id 5-39, mandate 40-74 · `03`: purpose 5-8, category 9-12, remittance 13-80 · `04`: continuation 5-76 · `05`: creditor reference 5-39, debtor name 40-80 |
| `24` | code 1-2 · `01` 3-4 · original currency 5-7 · original amount 8-21 |
| `33` | code 1-2 · bank 3-6 · branch 7-10 · account 11-20 · debit count 21-25 · debit total 26-39 · credit count 40-44 · credit total 45-58 · closing sign 59 · closing balance 60-73 · currency 74-76 |
| `88` | code 1-2 · nines 3-20 · record count 21-26 |

Constants at the top of `norma43_reader.py` (Finance Rule 7): `RECORD_LENGTH = 80`, `MAX_COMPLEMENTS = 5`,
`YEAR_BASE = 2000`, `N43_ENCODINGS = ("utf-8-sig", "latin-1")`, `SEPA_SCHEMES = ("CORE", "B2B")`,
`IBAN_PREFIX = "IBAN "`, `CONCEPT_LABELS` (Annex 2), `OTHER_CONCEPT_LABEL = "Other"`. Slices are built
from a single table of `(start, end)` pairs per field, written 1-based as in the standard and converted
once, so the code reads like the document.

### 4.2 Algorithm

```
text   = decode(content)                       # utf-8-sig, else latin-1
lines  = re.split(r"\r\n|\r|\n", text)         # DN-RF-04: not str.splitlines()
state  = no block; blocks_done = []; record_count = 0; eof = None

for number, raw in enumerate(lines, start=1):
    if raw.strip() == "": continue
    if eof is not None: row-quarantine record_after_end_of_file; continue
    line = raw.rstrip(" "); if len(line) > 80: row-quarantine line_too_long; (the record is dropped)
    line = line.ljust(80); code = line[0:2]; record_count += 1
    11 -> close nothing (an open block without 33 is rejected missing_end_of_account); open block
    22 -> finish the pending movement; start a new pending movement (or quarantine it, see below)
    23 -> attach to the pending movement (sequence, max five)
    24 -> attach to the pending movement
    33 -> finish the pending movement; run the control checks; commit or reject the block
    88 -> finish nothing; eof = (number, line); do not count this line in record_count
    other -> unknown_record_code
end: block still open -> missing_end_of_account; eof is None -> record88_missing
88 checks -> if they fail, drop every committed transaction and add the file record
```

A pending movement holds: the 22 line number and text, its attached 23/24 texts, and a `dropped` flag
set when the 22 itself was quarantined (its 23/24 lines then join its quarantine record instead of
producing `complement_without_movement`). A block holds: header fields, committed `Transaction`s,
and for the control sums two lists of `Decimal` (debits, credits) plus an `unverifiable` flag.

Order of checks on a `22` line (first failure wins, one record): `bad_concept_code`, `bad_dc_key`,
`non_digit_amount` (these two set `unverifiable` as well), `bad_date:operation_date`,
`bad_date:value_date`. The key and amount are parsed **first** so that a bad date still counts in the
sums (REQ-RF-09, DN-RF-06). `bad_currency_equivalence` is decided when the movement is finished,
because the `24` arrives after the `22`.

A rejected block (bad header, unknown currency) sets `rejected` and counts its dropped lines; lines up
to the next `11` or `33` are consumed silently. The `33` of a rejected block is consumed and closes it.

### 4.3 Movement to Transaction

- `date`: `date(2000 + YY, MM, DD)`; `ValueError` → `bad_date:<field>`.
- `amount`: `decimal_from_implied(line[28:42])`; `flow` from the key; `currency` from the block.
- `source_ref`: `f"{source_file}:{line_number}"`; `source_row = line_number` (DN-RF-01).
- Texts: `" ".join(slice.split())`, from `line[4:80]` for generic records, from the SEPA slices for the
  SEPA layout.
- Generic rule (REQ-RF-06): `iban_record = next(t for t in texts if t.startswith("IBAN "))`; the
  others, in order, give `counterparty` (first) and `description` (rest joined by one space); label
  fallbacks as written in the requirement.
- Tags in the order of REQ-RF-08. A `24` whose numeric code is in `NUMERIC_TO_ALPHA` gives
  `original_currency:<alpha>`; any other three-digit code gives `original_currency_code:<NNN>` and the
  movement stays valid (a card purchase abroad is normal; the alphabetic code is never guessed). Only a
  non-digit code or amount, a short `24` or a repeated `24` quarantines the movement
  (`bad_currency_equivalence`).

### 4.4 Control checks

Pure function `check_block(header, debits, credits, line33) -> tuple[str, str, str] | None` returning
`(check, declared, computed)` of the first failure. Counts compare `int`; totals compare `Decimal`
produced by `sum_amounts`; the balance compares
`apply_sign(closing, closing_is_debtor)` with
`balance_after(apply_sign(opening, opening_is_debtor), credits_total, debits_total)`. `declared` and
`computed` are `str(Decimal)` with two decimals so the quarantine table is readable. Failure returns the
block record and **discards** the block's transactions (REQ-RF-10): a ledger with a wrong total is not
a smaller ledger, it is an untrustworthy one.

### 4.5 Quarantine record shapes

| Level | `source_row` | `raw` |
|---|---|---|
| row | line of the `22` or the stray line | the line(s) joined with `\n`, trailing spaces kept off |
| block | line of the `11` | `{"account", "declared", "computed", "line_33"}`; for header problems `{"account"?, "dropped_lines"}` |
| file | `None` | `{"declared", "computed"}` for the `88`; the message string for `unsupported_format` |

### 4.6 Currency table

`iso4217.py` holds `NUMERIC_TO_ALPHA` with exactly the eleven codes of Annex 2 (`978 EUR`, `840 USD`,
`826 GBP`, `756 CHF`, `752 SEK`, `578 NOK`, `554 NZD`, `392 JPY`, `208 DKK`, `124 CAD`, `036 AUD`), with a
comment naming the source. These eleven are verified against the AEB document (session 8b review); no
other code is added from memory. A test pins the eleven and checks the shape of every entry (three
digits, three upper-case letters, no duplicate alpha code). An account header (record 11) with any
other code stays `unknown_currency_code`; a record 24 with any other code is kept as
`original_currency_code:<NNN>` (§4.3).

## 5 — Facturae reader (REQ-RF-12 to REQ-RF-19)

Paths verified in the session 8b review: the reviewer compared every path below with the official schema
`Facturaev3_2_2.xml` on facturae.gob.es (`TaxOutputType`: `TaxTypeCode`, `TaxRate`, `TaxableBase`,
optional `TaxAmount`, `SpecialTaxableBase`, `SpecialTaxAmount`, `EquivalenceSurcharge`,
`EquivalenceSurchargeAmount`; `AmountType`: `TotalAmount`, optional `EquivalentInEuros`; `AccountType`:
choice of `IBAN` or `AccountNumber`; `TaxTypeCode` `01` IVA and `04` IRPF; `PaymentMeans` `04` transfer
and `02` direct debit; amounts `DoubleUpToEightDecimalType`, `InstallmentAmount` `DoubleTwoDecimalType`;
`PersonTypeCode` `F`/`J`; `ResidenceTypeCode` `E`/`R`/`U`).

### 5.1 Parsing and namespaces

```python
from defusedxml import DefusedXmlException
from defusedxml.ElementTree import ParseError, fromstring

root = fromstring(data, forbid_dtd=True)      # forbid_entities / forbid_external stay True
```

- `data` is the raw bytes, so expat honours the XML declaration's encoding. A `str` source is encoded
  to UTF-8 first. No decode step means no `undecodable_file` for XML; a bad encoding surfaces as
  `ParseError` → `invalid_xml`.
- Helpers `_local(tag)` (strip `{ns}`), `_children(el, name)`, `_child(el, name)`, `_text(el, *path)`
  walk by local name, so 3.2, 3.2.1, 3.2.2, qualified or unqualified children and any prefix read the
  same (REQ-RF-12). The element tree is never searched with `//`: paths are explicit, so a
  `Signature` or an `Extensions` block cannot be mistaken for data.
- `len(data) > MAX_FACTURAE_BYTES` (10 MiB) is checked before parsing. Streamlit's own upload limit is
  larger (§6), so the reader enforces its own.

### 5.2 Invoice assembly

For `n, invoice in enumerate(invoices, start=1)`:

1. `taxes = TaxesOutputs/Tax`; codes other than `01` → `unsupported_tax_type:<code>`; none with `01` →
   `missing_vat_tax`; more than one `01` → `multiple_vat_rates` (DN-RF-08).
2. `withheld = TaxesWithheld/Tax`; codes other than `04` → `unsupported_tax_type:<code>`; the amounts
   are added with `sum_amounts`.
3. Required text fields are read; a blank one gives `missing_field:<name>` in the order of the table
   of REQ-RF-13. Dates through `_xs_date`, amounts through `_amount` (below).
4. Due date and IBAN per REQ-RF-15; `due_date_is_default` and the default term reuse
   `DEFAULT_PAYMENT_TERM_DAYS` imported from `invoice_reader`.
5. Negativity is tested on the six values as read; then `round_to_cents` is applied to five of them
   (DN-RF-11); the rate goes through `_canonical_rate`.

```python
def _amount(text: str | None) -> Decimal:              # raises InvalidOperation
    value = Decimal(text.strip()); assert value.is_finite(); return value
def _canonical_rate(rate: Decimal) -> Decimal:
    return Decimal(format(rate.normalize(), "f"))      # 21.00 -> 21 ; 5.20 -> 5.2 ; 0.00 -> 0
def _xs_date(text: str) -> date:                       # regex ^\d{4}-\d{2}-\d{2}(Z|[+-]\d{2}:\d{2})?$
    return date.fromisoformat(text.strip()[:10])
```

`Decimal("0.00").normalize()` is `Decimal("0")`, which `format(..., "f")` prints as `0`; for `100` it prints
`100`, never `1E+2`. A unit test pins `21.00`, `21.00000000`, `5.20`, `0.00`, `10`, `1E+1`.

### 5.3 Series and number

`invoice_number = (series or "") + number`, each trimmed (DN-RF-13). The CSV demo has no series, so the
generator writes the whole number in `InvoiceNumber` and omits `InvoiceSeriesCode`.

### 5.4 Signed files (REQ-RF-19)

`ds:Signature` is a child of the root. The reader never visits it, so it neither verifies nor depends
on it. A real check (XAdES, certificate chain, revocation) is a different project; the page says so
(§7.4) and `.xsig` is accepted as an extension only (DN-RF-14).

## 6 — Library notes recorded from the docs (context7, session 8a)

Looked up with the context7 MCP server; what was and was not found:

- **defusedxml** (`/tiran/defusedxml`, v0.7.1 is the version listed). `defusedxml.ElementTree.fromstring(
  text, forbid_dtd=False, forbid_entities=True, forbid_external=True)` takes `str` or `bytes`.
  `forbid_dtd` defaults to **False**, so the reader passes `forbid_dtd=True` (a DTD is never legitimate
  in a Facturae). The exceptions are `DefusedXmlException(ValueError)` and its subclasses `DTDForbidden`,
  `EntitiesForbidden`, `ExternalReferenceForbidden`, `NotSupportedError`; `ParseError` is exported by
  `defusedxml.ElementTree` for malformed input. Order of `except` clauses therefore matters: catch
  `DefusedXmlException` **before** any `ValueError`. The docs recommend catching the base class to
  cover every attack case.
- **Python 3.12 `xml` security notes** (CPython docs, `Doc/library/xml.rst`, v3.12.16). Expat 2.4.1 and
  newer is not vulnerable to billion laughs or quadratic blow-up, but the table still lists
  `xml.etree` as vulnerable "due to potential reliance on system-provided libraries"; large-token
  denial of service needs Expat 2.6.0. The docs recommend defusedxml for any server code that parses
  untrusted XML. We do not rely on the interpreter's bundled Expat; hence defusedxml (DN-RF-15).
- **Streamlit** (`/streamlit/docs`; the versioned library listing stops at 1.65, the project pins 1.67.0,
  so re-check at implementation). Signature: `st.file_uploader(label, type=None,
  accept_multiple_files=False, key=None, help=None, on_change="rerun", args=None, kwargs=None, *,
  max_upload_size=None, disabled=False, label_visibility="visible", width="stretch")`.
  `accept_multiple_files` is `bool` or `"directory"`; with `True` the return value is a **list** of
  `UploadedFile` (each has `.name` and `.getvalue()`), and the user can add files by browsing again.
  The docs state that the default value of `st.file_uploader` cannot be configured.
  **Not found:** the text of the `type` parameter (case and leading-dot rules) and whether `AppTest` in
  1.67 can drive a file uploader. Consequences: the lists below use lowercase extensions without a dot
  and the router never trusts the extension; and no test uploads a file through `AppTest` (the demo
  button path covers the apps end to end, the routers are tested directly). The widget returns `None`
  (single) or a list (multiple, possibly empty); the code uses `uploads or []`.

## 7 — Applications

### 7.1 Phantom Invoices (`settings.py`, `app.py`, `config.toml`)

- `DemoInputs.invoices` becomes `tuple[Source, ...]`; `suppliers` and `payments` stay `Source`.
  `demo_inputs(config, root, fmt: Literal["csv", "real"] = "csv")` reads `[demo].invoices_path` and
  `payments_path` for `csv`, and `payments_n43_path` plus every `*.xml` under `facturae_dir` (sorted by
  name) for `real`. `suppliers_path` is shared.
- `run_pipeline(invoices: Source | Sequence[Source] | None, suppliers, payments, as_of)`. A single
  `Source` is wrapped (callers and tests that pass one keep working). Files are sorted by name
  (DN-RF-18); a repeated name after the first gives `duplicate_file_name` and is skipped; each is read
  with `read_invoices`; the lists are passed together to `normalise(*lists, kind="invoice")`.
  Payments use `read_bank_statement`. The extension rule `fmt="json" if name.endswith(".json")` is
  removed.
- `Pipeline` gains `notes: tuple[str, ...]` (detected formats and, when a Facturae was read,
  `SIGNATURE_NOTE`). `pipeline_key` hashes, for the invoices, each file's name and SHA-256 in sorted
  order, preceded by the file count.
- `MULTI_RATE_NOTE` is extended to name both quarantine reasons; `prepare.py` is unchanged.
- `apply_demo` stores `state["sources"]["invoices"]` as a tuple. `load_demo()` in `app.py` reads
  `st.session_state[DEMO_FORMAT_KEY]` and calls `demo_inputs(CONFIG, ROOT, fmt)`.
- Uploaders: `pi_upload_invoices` (`type=["csv","json","xml","xsig"]`, `accept_multiple_files=True`),
  `pi_upload_suppliers` (`csv`), `pi_upload_payments` (`["csv","n43","txt","aeb","csb43"]`). The unprefixed
  keys `upload_*` are renamed (REQ-RF-22). `_current_sources` returns a tuple for invoices: the uploaded
  files, else the stored demo files, else `None`.
- `DEMO_FORMAT_KEY = "pi_demo_format"`, options `("CSV", "Real formats")`, drawn with `st.sidebar.radio(...,
  horizontal=True)` above *Load demo data*.

`config.toml` `[demo]` gains `payments_n43_path = "data/samples/phantom_demo/payments.n43"` and
`facturae_dir = "data/samples/phantom_demo/facturae"`. Paths only, as the file's header requires.

### 7.2 Zombie Subscriptions

- `DemoInputs.csv_bytes/csv_name` are renamed `statement_bytes/statement_name`; `demo_inputs(config,
  root, fmt="csv")` reads `[demo].csv_path` or `[demo].n43_path`. Aliases, last-used and cancellation
  dates are the same for both formats: they are keyed by counterparty, which is identical (REQ-RF-25).
- `_ingest` calls `read_bank_statement(io.BytesIO(data), source_file=name)`; the cache key stays
  `sha256:name`. The caption names the detected format.
- Uploader `zs_upload_statement`, `type=["csv","n43","txt","aeb","csb43"]`. Radio `zs_demo_format`.
  `WIDGET_KEYS` gains the format key.

### 7.3 Key table (REQ-RF-22)

| Key | App | Widget |
|---|---|---|
| `zs_upload_statement`, `zs_demo_format` | zombie | uploader, radio |
| `pi_upload_invoices`, `pi_upload_suppliers`, `pi_upload_payments`, `pi_demo_format` | phantom | uploaders, radio |

The showcase test that compares the two apps' session-state key sets is extended with these.

### 7.4 Notices

`SIGNATURE_NOTE` and `UNSUPPORTED_*` text are constants of `sniffer.py` / phantom `settings.py`, shown
with `st.caption`; they are plain text (no `unsafe_allow_html`), and file names are escaped with the
existing `markdown_safe`.

Two more constants, defined once and used by both apps or by the page that needs them:

- `CONTROL_CHECK_FAILED_MESSAGE` in `norma43_reader.py` (RF3; shown by RF9 and RF10 for every
  `control_check_failed:*` record): "This bank file is incomplete or was edited: its totals do not match
  its movements. Download a fresh export from your bank and load it again."
- `NO_PAYMENT_IBAN_NOTE` in phantom `settings.py` (RF9): when the payments file is Norma 43 and none of
  its transactions has an `iban`, the page shows this one caption: "This Norma 43 file carries no IBAN
  for its payments, so the payment-side IBAN checks are skipped for this file."

## 8 — Generator (REQ-RF-26 to REQ-RF-28)

All writers live in `scripts/generate_samples.py` (DN-RF-19): the tests already load that script as
`gen`, and the Hypothesis round-trip needs the writer in the same place as the demo files.

### 8.1 Refactor that keeps CSV bytes

`build_phantom_demo(seed)` is split: `build_phantom_demo_rows(seed) -> PhantomDemoRows(invoices, payments)`
(the lists it already builds) and a CSV renderer. `_invoice_record` also stores `surcharge_rate` and
`withholding_rate` as extra dict keys that the CSV writer ignores (it selects `INVOICE_COLUMNS`);
P8 passes `withholding_rate="15"`, P11 already has `surcharge_rate="5.2"`. Reason: Facturae wants a rate
next to every amount, and inverting an amount into a rate would be arithmetic outside `money.py`.
`build_zombie_demo_rows(seed)` already exists. The existing byte tests of the CSV files must stay green
untouched.

### 8.2 Norma 43 writer

```python
def render_norma43(rows, *, account=("9999", "0001", "0000000001"), mode=1,
                   sepa_descriptions=frozenset(), opening=Decimal("50000.00")) -> bytes
```

- One block: `11`, then per row one `22`, its `23` lines and optional `24`, then `33`, then `88`. Rows keep
  the order given (CSV order), so the *i*-th `22` is the *i*-th CSV row (REQ-RF-25).
- `22`: operation date = value date = the row's day; concept from `N43_CONCEPT_BY_DESCRIPTION`
  (`Monthly subscription` → `03`, `Payroll` → `15`, `Supplier payment`, `Receipt` and descriptions
  starting `Transfer` → `04`, `Card purchase` → `12`, anything else `99`); own concept `000`; key from the
  sign of the amount; document `0000000000`; reference 1 `000000000000`; reference 2 blank.
- Generic rows: `2301` + counterparty, `2302` + description, `2303` + `IBAN ` + the IBAN cell verbatim
  when it is not empty. A text longer than 76 characters raises `ValueError` (never truncated). Text must
  encode to Latin-1.
- SEPA rows (description in `sepa_descriptions`, `mode=3`): `2301CORE` + creditor name, `2302` +
  creditor id padded to 35 + mandate, `2303` + 8 blanks + remittance. Creditor id `ES00ZZZ` +
  `make_cif(500 + i)` and mandate `MND` + 4-digit `i`, with `i` the index of the counterparty by first
  appearance.
- `11`: start and end date = min and max day; holder `TITULAR FICTICIO DEMO`; currency `978`. `33`: counts
  and totals from `sum_amounts`; the closing balance from `balance_after`; sign `2` if non-negative else
  `1`. `88`: the number of lines before it.
- Output: lines padded to 80, joined with `\r\n` and ending with `\r\n`, encoded ISO-8859-1.

Zombie demo: `build_zombie_demo_n43(seed)` with `mode=3` and `sepa_descriptions={"Monthly subscription"}`.
Phantom: `build_phantom_payments_n43(seed)` with `mode=1` and account `("9999", "0001", "0000000002")`.
Opening balance 50.000,00 keeps the zombie closing balance creditor; the phantom file opens with
100.000,00 because its 45 clean payments depend on the seed and can total up to 98.009,55 (the
closing balance stays creditor for any seed). A test asserts both for ten seeds. `render_norma43` is
`render_norma43_lines` (the 80-character records, used by the property tests to build other layouts)
joined and encoded.

### 8.3 Facturae writer

```python
def render_facturae(supplier, invoices, *, buyer=BUYER) -> bytes    # UTF-8, LF
```

- Built by string templates with `xml.sax.saxutils.escape`, not by an XML library, so the bytes are
  stable (attribute order, quoting, indentation fixed). It never parses.
- Root `<fe:Facturae xmlns:fe="http://www.facturae.gob.es/formato/Versiones/Facturaev3_2_2.xml"
  xmlns:ds="http://www.w3.org/2000/09/xmldsig#">`, children unqualified, as real files are.
- Elements, in schema order: `FileHeader` (`SchemaVersion` 3.2.2, `Modality` `I` for a file with one
  invoice and `L` for a batch of several, `InvoiceIssuerType` EM,
  `Batch` with `BatchIdentifier`, `InvoicesCount`, three totals, `InvoiceCurrencyCode`); `Parties`
  (`SellerParty` with `TaxIdentification` and `LegalEntity/CorporateName` or `Individual`; a fictional
  `BuyerParty`); `Invoices/Invoice` with `InvoiceHeader`, `InvoiceIssueData`, `TaxesOutputs`,
  `TaxesWithheld` when present, `InvoiceTotals`, `Items/InvoiceLine` (one per tax, description
  `Synthetic demo goods and services`), `PaymentDetails` when the row has a due date.
- Persons: `Name` is the text before the first space, `FirstSurname` the rest (DN-RF-13 reverses it
  by joining with one space, so the round trip is exact for names without leading, trailing or double
  blanks).
- Rows to invoices: records of one supplier with the same number and issue date and **different** VAT
  rates become one invoice with several `Tax` entries (the MULTI_RATE case, which the reader then
  quarantines); records with the same rate stay separate invoices (P1, the duplicate).
- A row with an empty due date gets no `PaymentDetails` and therefore **no IBAN**, because
  `Installment` requires `InstallmentDueDate` (DN-RF-20). Those rows are clean-supplier rows, which
  already appear without an IBAN elsewhere in the series (style `""`) and raise no alert.
- Amounts are written as the strings the rows hold (`"400.00"`). The tax rate is the row's rate text
  padded to the two decimals the schema's `DoubleTwoDecimalType` accepts (`21` → `21.00`, `5.2` →
  `5.20`; the reader's canonical form turns both back into `21` and `5.2`); an amount or rate with more
  decimals raises `ValueError`. Totals are the row's `total`. The sums are computed with `sum_amounts`
  and written with two decimals: the three `Batch` totals, and for an invoice with several rows (the
  MULTI_RATE case) the gross, tax and invoice totals; the writer does no other arithmetic.
- Mandatory schema elements are always written: `FileHeader/Batch` with its six children, a
  `TaxIdentification` (person type, residence `R`, number) and an `AddressInSpain` (fictional street,
  post code `00000`, town, province, `ESP`) for both parties, `InvoiceDocumentType`/`InvoiceClass`,
  `TaxCurrencyCode`/`LanguageName`, every required `InvoiceTotals` child, and per `InvoiceLine` the
  description, quantity `1.00`, unit price, total cost, gross amount and a `TaxesOutputs/Tax`.
  `TaxesWithheld` of the line is optional and not written.
- File names `<kk>-<case>.xml` (REQ-RF-26); `kk` is `k:02d`.

### 8.4 Wiring

`build_zombie_demo_real(seed)` → `{ZOMBIE_DEMO_N43_FILE: bytes}`; `build_phantom_demo_real(seed)` →
`{"payments.n43": bytes, "facturae/<name>.xml": bytes, ...}`. The zombie-demo and phantom-demo modes
write them after the CSVs, creating `facturae/` as needed. The text-returning `build_*` functions the
existing tests use are unchanged.

### 8.5 Repository files

```
# .gitattributes (added)
data/samples/*.n43 -text
data/samples/phantom_demo/*.n43 -text
data/samples/phantom_demo/facturae/*.xml -text
```

`.gitignore` already un-ignores `data/samples/**`; no change.

## 9 — Test plan

All new tests are deterministic (no clock). Fixtures are built with `n43_builders.py`:
`n43_line(code, **fields)` assembles an 80-character record from `(start, end, value)` fields so a test
never counts columns by hand, plus `fixture_a(**overrides)` (the file of Fixture A) and
`facturae_doc(**overrides)` (Example A). Expected values are written in the test as literals from the
requirements.

| Layer | File | What it pins |
|---|---|---|
| money | `tests/test_money.py` | the five helpers, round trip property |
| sniffer | `test_sniffer.py` | every example of REQ-RF-01/02, BOM, whitespace, PDF, arbitrary bytes never raise |
| N43 fields | `test_norma43_reader.py` | Fixture A transactions, SEPA, record 24, two accounts, CRLF/LF/CR, no trailing spaces, Latin-1 name, UTF-8 name, blank lines keep numbering, empty file, single record |
| N43 quarantine | same | one test per reason of REQ-RF-04 and REQ-RF-09 |
| N43 controls | `test_norma43_controls.py` | each of the seven checks, both signs, bad row still counted, unverifiable, missing 33, two blocks, every 88 case |
| Facturae | `test_facturae_reader.py` | Example A, series, person name, rounding table, rate canonical form, due date rules, IBAN rules, every invoice-level reason, versions, namespaces, signed |
| security | `test_facturae_security.py` | billion laughs, external DTD, entity, malformed, oversize; the module imports only `defusedxml` for XML |
| generator | `tests/test_generate_real_formats.py` | byte stability, committed files equal output, line width 80, CRLF, Latin-1 encodable, sums, closing balance, 25 Facturae files named per REQ-RF-26, only P8 has withholding |
| apps | `test_zs_real_formats.py`, `test_pi_real_formats.py` | key sets, radio default, demo via `Real formats`, counts, equivalence, signature caption, unsupported-format message, duplicate file name |
| git | `test_pi_gitattributes.py` | three new lines and `git check-attr text` unset for one file of each kind |

### 9.1 Hypothesis (max_examples = 200)

Strategies in `rf_strategies.py`: `texts` (ASCII punctuation, letters, digits and the Latin-1 letters
U+00C0..U+00FF, no leading/trailing/double blanks, not starting with `IBAN `; U+0080..U+00BF are left
out because those Latin-1 bytes are UTF-8 continuation bytes and a Latin-1 file could then be read as
UTF-8, DN-RF-02), `amounts` (0.00 to 99 999 999 999.99, two places; a file has at most eight rows so
the sums fit the 14-digit totals of a record 33), `days`
(2000-01-01 to 2099-12-31), `rows` (day, amount, flow, counterparty, description, optional iban),
`invoices` (rates from {0, 4, 5.2, 10, 21}, VAT, surcharge, withholding and `total` computed with the
money helpers so each record is consistent), and a `layout` strategy choosing CRLF/LF/CR, trailing
spaces kept or removed, a final line ending or not, and Latin-1, UTF-8 or UTF-8 with BOM.

1. **Round trip N43.** `parse_norma43(render(rows))` returns the rows' fields (ids ignored; random
   `uuid4` ids are expected) and no quarantine; also under every `layout`.
2. **Round trip Facturae.** The twelve `Invoice` fields equal the input; `source_ref`s are
   `file:1..n`.
3. **No invention.** Every returned `source_ref` is the line of a `22` / `file:n` within range; zombie
   detectors run on the N43 ledger and every alert source_ref is in `loaded_source_refs`.
4. **Tamper detection.** Replace one digit of an amount field of one `22` of a valid file by a different
   digit: the result has no transaction of that block and a `control_check_failed:` record.
5. **Never raises.** `st.binary()` through the sniffer, both readers and both routers.
6. **Idempotency / empty.** Parsing twice gives equal field tuples; empty bytes give `([], [])`.

### 9.2 Equivalence (REQ-RF-25)

In each app test: run `AppTest` once with `CSV`, once with `Real formats` (set the radio, click
`*_load_demo`), compare. The comparison maps each cited `source_ref` to its position (CSV row *i* ↔ *i*-th
transaction or invoice of the loaded frame, using the frames in `session_state`) and then compares the
multiset of `(detector, severity, title, data)`; `Alert.id` and explanation texts are excluded because
they contain the references. It also asserts the literal counts of REQ-RF-25 so a change in both runs
cannot pass.

## 10 — Decisions

| Id | Decision | Reason |
|---|---|---|
| DN-RF-01 | N43 `source_row` is the 1-based physical line; Facturae `source_row` is the 1-based invoice position | A judge opens the file in an editor and finds line 2 or invoice 2. This differs from the CSV 0-based rows; `tech.md` is updated to say so |
| DN-RF-02 | N43 decoding: UTF-8 then ISO-8859-1, never cp1252 | The brief says Latin-1; it never fails and maps every byte one to one. cp1252 would change bytes 0x80-0x9F and fail on five of them |
| DN-RF-03 | Counterparty = first text of the generic `23`s, description = the rest, IBAN in a `23` text beginning `IBAN ` | The AEB standard fixes the SEPA layout but not the content of free `23` records, and has no counterparty IBAN field. Annex 4 section 1 (SEPA transfers) leaves record 23-05 as free use for beneficiary data by agreement with the bank, so carrying the IBAN in a free 23 text is a documented convention, not a standard field. Phantom needs the IBAN for the IBAN-change detector. When a Norma 43 payments file has no IBAN record at all, the page says the payment-side IBAN checks are skipped for that file (`NO_PAYMENT_IBAN_NOTE`, REQ-RF-23, RF9) |
| DN-RF-04 | Split lines with a regex, not `str.splitlines()` | `splitlines()` also cuts on `\x85`, `\x1c`..`\x1e` and Unicode separators; in Latin-1 text `\x85` is a legal byte |
| DN-RF-05 | SEPA reading only for mode 3 + concept `03` + `CORE`/`B2B` | Annex 4 applies to direct debits in mode 3. Anything else is free text, and reading it as SEPA would put garbage in `counterparty` |
| DN-RF-06 | A row-quarantined `22` with valid key and amount still counts in the control sums; one with an unreadable key or amount fails the block | A bad date should not reject an account, but an unreadable amount makes the totals unprovable |
| DN-RF-07 | Control failures discard the block's transactions, a failed `88` discards the whole file's | The user asked for "quarantine a whole account block rather than silently accept it". A statement that does not add up must not feed detectors |
| DN-RF-08 | A Facturae invoice with several IVA taxes is quarantined whole (`multiple_vat_rates`) | Splitting it into several `Invoice` rows would give two rows one `source_ref`. The existing app rule already treats multi-rate invoices as out of scope (OD-PI-08) |
| DN-RF-09 | Several installments: latest due date; first IBAN; conflicting IBANs quarantined | An invoice is fully due on its last installment; two IBANs on one invoice is a phantom-invoice signal, not something to pick from silently |
| DN-RF-10 | `AccountNumber` (domestic account) is ignored, never converted to an IBAN | An IBAN needs ISO check digits; building them would invent a datum (Finance Rule 1) |
| DN-RF-11 | Round the five header amounts to cents at ingestion; keep rates exact in canonical form | The user asked for a rounding rule; Rule 3 allows rounding at the boundary and ingestion is the boundary of these values. `xs:double` allows eight decimals the model cannot hold |
| DN-RF-12 | Never compute a missing `TaxAmount` or surcharge amount | Rule 1: a derived figure is allowed only as a named, attributed field; a reader is not a detector |
| DN-RF-13 | `invoice_number = series + number`; persons join `Name`, `FirstSurname`, `SecondSurname` with one space | Facturae identifies an invoice by series and number together; no separator is invented. The round trip of the generator relies on single spaces |
| DN-RF-14 | Signature is not verified; the note shows whenever a Facturae is loaded | The reader cannot tell a signed file by anything it uses; saying so for every Facturae is always true and cheap |
| DN-RF-15 | `forbid_dtd=True` | A Facturae never needs a DTD, and the default `forbid_dtd=False` would let a DTD pass |
| DN-RF-16 | Reader-side size cap of 10 MiB for XML | Streamlit's upload limit is far larger; parsing memory is ours to bound |
| DN-RF-17 | The content, not the extension, chooses the reader | See §3 |
| DN-RF-18 | Invoice files are read in file-name order | Same files in any selection order give the same alerts and the same cache key; the demo order equals CSV order |
| DN-RF-19 | Writers live in `scripts/generate_samples.py`, not in `ledger_kit` | The library only reads; the tests already import that script |
| DN-RF-20 | In the sample Facturae, a row without a due date loses its IBAN | The schema cannot express an IBAN without a due date. Equivalence depends on those rows being alert-free either way; the equivalence test is what proves it (§11, Q1) |
| DN-RF-21 | Demo format is a radio read by the existing `on_click` callback | Keeps the "write widget keys only in callbacks" rule of the existing apps; `AppTest` can drive a radio |
| DN-RF-22 | No `AppTest` upload tests | Support for `file_uploader` in `AppTest` was not confirmed (§6) |
| DN-RF-23 | Facturae samples are not validated against the official XSD | No XSD or `lxml` in the project; the writer follows the element order of the standard and the reader is tolerant. Stated as a limit, not hidden |
| DN-RF-24 | Series and number are joined without a separator (`A` + `0042` → `A0042`), accepted in the session 8b review | The duplicate-invoice detector normalises keys anyway, so a plain `A0042` and a series `A` + `0042` meet in the same key, which is the wanted behaviour |
| DN-RF-25 | Several installments use the latest due date, accepted in the session 8b review | An invoice is fully due on its last installment; the limit (a partly overdue invoice can look not yet due) is stated, not hidden |
| DN-RF-26 | A record 24 with a numeric code outside the eleven Annex 2 codes keeps the movement and is tagged `original_currency_code:<NNN>` | A card purchase abroad is normal; quarantining it would drop a real movement, and guessing the alphabetic code would invent a datum. Only a malformed or repeated 24 is `bad_currency_equivalence` |
| DN-RF-27 | The strict `33` and `88` checks stay; every `control_check_failed:*` record is shown with `CONTROL_CHECK_FAILED_MESSAGE` | The wanted behaviour for a file that does not add up is rejection; the plain message tells the user the file is incomplete or edited and to download a fresh export |

## 11 — Open questions for the reviewer

Resolved in the session 8b review and removed from this list: the Norma 43 and Facturae layouts
(verified, §4.1 and §5), the counterparty IBAN convention (DN-RF-03), the ISO 4217 table (§4.6,
DN-RF-26), the strict `33` and `88` checks (DN-RF-27), the series separator (DN-RF-24) and the latest
installment (DN-RF-25).

1. **Equivalence risk (DN-RF-20).** If the missing IBAN on the clean no-due-date invoices changes any
   alert, the fix is a spec change (for example giving those rows an explicit due date and accepting
   `due_date_is_default=False`), not a test change. RF9 and RF10 surface it first.
2. Streamlit 1.67 `type` rules and `AppTest` uploader support are unverified (§6).
