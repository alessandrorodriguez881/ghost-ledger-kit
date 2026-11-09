# real-formats — Implementation Tasks

Every task is test-first: write the tests named in the task, see them fail, then implement. Section
references (§) point to `design.md`, REQ ids to `requirements.md`. Hypothesis tests use
`settings(max_examples=200)`. Nothing here reads the clock. Verification (`ruff check .`,
`ruff format --check .`, `pytest`, a headless run of both apps and of `streamlit_app.py`) is run by the
user; the author of the spec could not run anything.

Order matters: RF1 to RF6 are library work that needs no app; RF7 writes the samples the app tasks load;
RF9 and RF10 are where the demo equivalence (the main risk, design §11 Q1) is first checked.

## Task RF1 — Money helpers, currency table, dependency pin

**Covers**: REQ-RF-29, REQ-RF-30, §2, §4.6

- [x] Tests in `tests/test_money.py`: `sum_amounts` (empty → `Decimal("0")`, order-independent),
  `balance_after`, `apply_sign`, `decimal_from_implied` (`"00000000001299"` → `12.99`, `"0"`, non-digit and
  empty raise `ValueError`), `implied_digits` (`12.99` → `"00000000001299"`, rounds half-up, negative and
  too wide raise), Hypothesis round trip `decimal_from_implied(implied_digits(x)) == round_to_cents(x)`.
  New `tests/ingestion/test_iso4217.py`: exactly the eleven Annex 2 codes (no more, no fewer), shape of
  every entry, unique alpha codes.
- [x] Add the helpers to `ledger_kit/utils/money.py`; create `ledger_kit/ingestion/iso4217.py` with
  exactly the eleven Annex 2 codes and a comment naming the source (no code from memory).
- [x] Pin `defusedxml==0.7.1` in `requirements.txt` (runtime block) and in `pyproject.toml`
  `dependencies` (checked by `tests/test_packaging.py`). Extending
  `tests/test_showcase_requirements.py` so `defusedxml` is among the checked runtime imports moves to
  RF4, where the first import appears.

## Task RF2 — Norma 43 reader: records and mapping

**Covers**: REQ-RF-03, REQ-RF-04, REQ-RF-05, REQ-RF-06, REQ-RF-07, REQ-RF-08, §4.1 to §4.3

- [x] `tests/ingestion/n43_builders.py` (`n43_line`, `fixture_a`) and `tests/ingestion/test_norma43_reader.py`:
  Fixture A gives the two expected transactions (every field and tag); LF, CRLF and CR give the same
  result; trailing spaces removed (and lines as written, unpadded) give the same result; a Latin-1
  name and the same name in UTF-8 both decode; blank lines keep the physical numbering; empty file;
  a single `11` line; zero amount; the generic-text examples of REQ-RF-06 (counterparty/description
  split, label fallbacks, collapsed blanks, IBAN record); SEPA direct debit (REQ-RF-07 including the
  mode-1 and `B2B` variants); record 24 tags (a known code gives `original_currency:<alpha>`, code `999` gives
  `original_currency_code:999` on a valid movement); two accounts in one file with distinct `account:` tags;
  `source_ref` is `file:line` of the `22`; amounts are `Decimal`, dates `datetime.date`.
- [x] Implement `parse_norma43` up to the point where valid files parse (reading, header, `22`, `23`,
  `24`, tags) with the control checks stubbed to "pass"; no quarantine yet beyond what these tests need.
  (Written together with RF3: the control checks and quarantine paths are in place.)

## Task RF3 — Norma 43 reader: quarantine and control checks

**Covers**: REQ-RF-04, REQ-RF-09, REQ-RF-10, REQ-RF-11, REQ-RF-31, §4.2, §4.4, §4.5

- [x] `tests/ingestion/test_norma43_reader.py`: one test per row reason of REQ-RF-09 (each with
  `source_row`, `reason`, `raw`), the header reasons and `unknown_currency_code` of REQ-RF-04 with
  `dropped_lines`, a bad date that is still counted in the sums, a sixth `23`, a quarantined `22`
  carrying its `23`/`24` lines.
- [x] `tests/ingestion/test_norma43_controls.py`: the seven checks of REQ-RF-10 one by one (the
  `declared` and `computed` strings of the examples), both balance signs, `missing_end_of_account`,
  two blocks where only the second fails (first block's transactions returned), the three `88` cases
  (`record88_missing`, `record88_count`, `record88_format`) returning no transaction, a non-blank line
  after the `88`, boundary: a total off by exactly 0.01, `CONTROL_CHECK_FAILED_MESSAGE` says the file is
  incomplete or edited and asks for a fresh export; a `24` with code `999` is not quarantined while a
  `24` with a non-digit code, a short `24` and a repeated `24` give `bad_currency_equivalence`.
- [x] Implement the quarantine paths, `check_block` and the end-of-file check.

## Task RF4 — Facturae reader: mapping

**Covers**: REQ-RF-12, REQ-RF-13, REQ-RF-14, REQ-RF-15, REQ-RF-16, REQ-RF-19, §5.1 to §5.4

- [x] `tests/ingestion/test_facturae_reader.py`, builder `facturae_doc(**overrides)` in `n43_builders.py`
  or a sibling: Example A gives the expected `Invoice`; qualified and unqualified children, any prefix,
  versions 3.2 / 3.2.1 / 3.2.2; series + number; `Individual` names; the rounding table of REQ-RF-14
  and the canonical rate table (`21.00`, `21.00000000`, `5.20`, `0.00`, `10`, `1E+1`); due-date and
  default rules; zone suffix; IBAN rules (first non-blank, `AccountNumber` ignored); surcharge and
  withholding (including two `04` taxes summed); several invoices give `file:1`, `file:2`; a
  `ds:Signature` child changes nothing; no `float` anywhere (the test passes `0.1` + `0.2` style text
  and checks exact `Decimal`s).
  (Builder: the sibling `tests/ingestion/facturae_builders.py`.)
- [x] Implement `parse_facturae` for valid files, importing `defusedxml` as in §5.1. Extend
  `tests/test_showcase_requirements.py` so `defusedxml` is among the checked runtime imports.
  (Written together with RF5: the quarantine paths and the size cap are in place.)

## Task RF5 — Facturae reader: quarantine and security

**Covers**: REQ-RF-12, REQ-RF-16, REQ-RF-17, REQ-RF-18, REQ-RF-31, §5.1, §5.2, §6

- [x] `tests/ingestion/test_facturae_reader.py`: every invoice-level reason of REQ-RF-17 (including
  `multiple_vat_rates`, `missing_vat_tax`, `unsupported_tax_type:03`, `conflicting_iban`,
  `negative_amount` before rounding, `missing_field:vat_amount` when `TaxAmount` is absent), a file of
  three invoices whose middle one is bad, every file-level reason of REQ-RF-12, empty file.
- [x] `tests/ingestion/test_facturae_security.py`: the billion-laughs document (nine nested entities),
  an external DTD `SYSTEM "http://127.0.0.1/x.dtd"`, an entity-only DTD, a `file:///` external entity,
  a malformed document, a document over `MAX_FACTURAE_BYTES`; each returns `([], [record])` with the
  reason of REQ-RF-18 and does not expand or fetch anything (the test patches nothing and relies on the
  result being immediate); a source-text test that `facturae_reader.py` imports XML only from
  `defusedxml`.
- [x] Implement the quarantine paths and the size cap.

## Task RF6 — Sniffer and routers

**Covers**: REQ-RF-01, REQ-RF-02, REQ-RF-31, §3

- [x] `tests/ingestion/test_sniffer.py`: every example of REQ-RF-01 (BOM, leading blank lines, prefix and
  unprefixed root, `11,` CSV line, PDF, empty), arbitrary bytes never raise (Hypothesis); routers: a
  Facturae in `read_bank_statement`, a PDF in `read_invoices`, a JSON named `.txt`, a Norma 43 named
  `.csv`, `str` content, the exact `raw` messages, an empty file.
- [x] Implement `sniffer.py`.

## Task RF7 — Generator, samples, git attributes

**Covers**: REQ-RF-26, REQ-RF-27, REQ-RF-28, §8

- [x] `tests/test_generate_real_formats.py`: the existing CSV byte tests stay green untouched; the three
  builders are deterministic for a seed and differ for another; `.n43` bytes decode as Latin-1, every
  line has 80 characters and ends in CRLF; counts and totals of `33` equal the rows; the closing
  balance is creditor; the zombie file is mode 3 and its `Monthly subscription` rows are SEPA with
  `ES00ZZZ` creditor ids; 25 Facturae files named per REQ-RF-26; only the file of P8 has a
  `TaxesWithheld`; only the MULTI_RATE file has two `Tax` entries; no real-looking data (all tax ids
  and IBANs come from the generator's own functions); the committed files equal the generator output
  byte for byte, compared without `\r\n` normalisation. Extend `test_pi_gitattributes.py` with the
  three lines and `git check-attr text` for one file of each kind.
  (The committed-files tests, `test_committed_real_format_files_equal_the_generator_output_byte_for_byte`
  and `test_the_committed_facturae_folder_holds_exactly_the_generated_files`, fail until the user has
  run the generator. `tests/test_generate_samples.py` and `test_pi_gitattributes.py` had two
  assertions that pinned the old output folder / the only `phantom_demo` line; they now allow the new
  files and lines.)
- [x] Refactor `build_phantom_demo` into rows + renderers (§8.1), add `render_norma43`,
  `render_facturae` (`Modality` `I` for one invoice, `L` for a batch of several; Batch totals via
  `sum_amounts`; tests for both), the `build_*_real` functions and their wiring in the `zombie-demo` and
  `phantom-demo` modes; add the `.gitattributes` lines.
- [ ] The user runs `python scripts/generate_samples.py --mode zombie-demo --seed 42` and
  `--mode phantom-demo --seed 42` and commits the new files (a command the author could not run).

## Task RF8 — Round-trip and tamper properties

**Covers**: REQ-RF-31, §9.1

- [x] `tests/ingestion/rf_strategies.py` and `tests/ingestion/test_real_formats_roundtrip.py`: properties
  1 to 6 of §9.1 (round trip N43 under every layout, round trip Facturae, no invention including the
  zombie detectors over an N43 ledger with `loaded_source_refs`, tamper detection, never raises,
  idempotency).
- [ ] Fix whatever the properties find in the readers or the writers. No new feature code is expected.
  (Open: the properties have not been run yet; the user's `pytest` run decides.)

## Task RF9 — Phantom Invoices: uploaders, demo format, equivalence

**Covers**: REQ-RF-20 to REQ-RF-25, §7.1, §7.3, §7.4, §9.2

- [ ] Update the tests that pin `DemoInputs.invoices`, `upload_*` keys and the extension rule
  (`test_pi_settings.py`, `test_pi_app_logic.py`).
- [ ] `test_pi_real_formats.py`: `run_pipeline` with one `Source` and with a tuple; file-name ordering
  (two selection orders, same alerts and same cache key); `duplicate_file_name`; a Facturae in the
  payments slot and a Norma 43 in the invoices slot show their `unsupported_format` records; the signature
  caption appears with a Facturae and not with CSV; `AppTest`: the radio defaults to `CSV`, the CSV demo
  still gives 9 alerts (3 critical, 6 warning), the `Real formats` demo gives the same, and the mapped
  comparison of §9.2 passes element for element; the quarantine panel lists one `multiple_vat_rates`
  record instead of two `multi_rate_invoice_out_of_scope` records.
- [ ] Implement §7.1 in `settings.py`, `app.py`, `config.toml`; rename the upload keys. Show every
  `control_check_failed:*` record with `CONTROL_CHECK_FAILED_MESSAGE`; show `NO_PAYMENT_IBAN_NOTE` when
  the payments file is Norma 43 and no transaction has an `iban` (tests for both).
- [ ] If the equivalence test fails, stop and report: the likely cause is DN-RF-20 (§11 Q1); do not weaken
  the comparison.

## Task RF10 — Zombie Subscriptions: uploader, demo format, equivalence

**Covers**: REQ-RF-20, REQ-RF-22, REQ-RF-24, REQ-RF-25, §7.2, §7.3, §9.2

- [ ] Update the tests that pin `DemoInputs.csv_bytes/csv_name` and the uploader
  (`test_zs_settings.py`, `test_zs_app.py`, `test_zs_demo_e2e.py`).
- [ ] `test_zs_real_formats.py`: `_ingest` of a Norma 43 and of a CSV; a Norma 43 named `.txt`; a
  Facturae in the statement slot gives `unsupported_format:facturae`; `AppTest`: both demos give 3
  tombstones and 19 alerts (1 critical, 4 warning, 14 info), the same tombstone figures, and the
  mapped comparison of §9.2; the aliases, last-used and cancellation texts are the same for both.
- [ ] Implement §7.2 in `settings.py`, `app.py`, `config.toml`. Show every `control_check_failed:*`
  record with `CONTROL_CHECK_FAILED_MESSAGE` (a test feeds a tampered Norma 43).

## Task RF11 — Showcase keys, steering and layout

**Covers**: REQ-RF-22, REQ-RF-29, §1, §7.3, §10 (DN-RF-01)

- [ ] Extend the showcase tests (`tests/test_showcase_app.py`, `tests/test_showcase_requirements.py`) with the
  new disjoint key sets and the `defusedxml` pin; `AppTest` of `streamlit_app.py` loads both apps with
  `Real formats` selected.
- [ ] Update `.kiro/steering/structure.md` (new modules, tests, sample files, naming of the new
  tests) and `.kiro/steering/tech.md` (a `defusedxml` row; the invoice-parsing row now lists Facturae;
  `source_row` of Norma 43 and Facturae is 1-based, DN-RF-01). Do not touch the README (session 7).

## Not verified by the author

The spec was written without running a command. The layouts of Norma 43 and Facturae were verified in
the session 8b review (the reviewer compared design §4.1 with the AEB document and the Facturae paths
with `Facturaev3_2_2.xml`, and the eleven currency codes are the Annex 2 ones). Still unverified: the
Streamlit 1.67 `type` rules and `AppTest` support for file uploaders (design §6, §11).
The user runs `ruff check .`, `ruff format --check .`, `pytest`, the generator commands of RF7 and a
headless start of both apps, and reports failures.
