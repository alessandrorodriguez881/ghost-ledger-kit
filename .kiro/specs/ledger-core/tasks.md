# ledger-core — Implementation Tasks

Tasks are ordered so that each one builds on a stable foundation from the tasks before it. Every task is **test-first**: write or update tests first, then implement until the tests pass.

Within each task the sub-items are ordered: scaffold → tests → implementation → verify (lint + coverage).

---

## Task 1 — Project scaffold and package metadata

**Covers**: REQ-PKG-01, REQ-PKG-02, REQ-PKG-05

- [ ] Create `pyproject.toml` at the workspace root with:
  - `[build-system]` using `setuptools` and `setuptools-scm` (PEP 517/518, no `setup.py`)
  - `[project]` metadata: name `ledger-kit`, requires-python `>=3.11`
  - `[project.optional-dependencies]` groups: `dev` (pytest, hypothesis, freezegun, pytest-cov, ruff)
  - `[tool.ruff]` section: `line-length = 100`, `select = ["E","F","I","UP"]`
  - `[tool.ruff.format]` section
  - `[tool.pytest.ini_options]` section: `testpaths = ["tests"]`
- [ ] Create `requirements.txt` with pinned exact versions for all runtime deps (pandas, pydantic, streamlit) and dev deps.
- [ ] Create the top-level package skeleton — empty `__init__.py` files for:
  - `ledger_kit/`
  - `ledger_kit/ingestion/`
  - `ledger_kit/detectors/`
  - `ledger_kit/ui/`
  - `ledger_kit/utils/`
- [ ] Create `ledger_kit/defaults.toml` with the content from design §9.
- [ ] Create `.env.example` documenting any required environment variables.
- [ ] Verify: `ruff check .` and `ruff format --check .` pass with zero warnings.

---

## Task 2 — Canonical data models

**Covers**: REQ-ING-13 (Transaction schema), REQ-DET-03 (Alert schema), design §2

- [ ] Write `tests/test_models.py` with:
  - `test_transaction_source_ref_computed` — building a `Transaction` produces correct `source_ref`.
  - `test_transaction_amount_must_be_positive` — constructing with a negative amount raises `ValidationError`.
  - `test_transaction_is_frozen` — attempting to mutate a field raises an error.
  - `test_alert_requires_non_empty_source_refs` — empty `source_refs` list raises `ValidationError`.
  - `test_alert_is_frozen` — attempting to mutate a field raises an error.
  - `test_quarantine_dict_shape` — document expected quarantine record keys via a helper.
- [ ] Implement `ledger_kit/models.py`:
  - `Transaction` Pydantic v2 model exactly as in design §2.1.
  - `Alert` Pydantic v2 model exactly as in design §2.2.
  - Both with `model_config = {"frozen": True}`.
  - Add a Pydantic validator that enforces `amount >= 0` on `Transaction`.
  - Add a Pydantic validator that enforces `len(source_refs) >= 1` on `Alert`.
- [ ] Update `ledger_kit/__init__.py` to re-export `Transaction` and `Alert`.
- [ ] Verify: all tests pass, `ruff check` clean.

---

## Task 3 — Money utilities

**Covers**: REQ-MON-01, REQ-MON-02, REQ-MON-03, REQ-ING-27 (format_as_european), design §5

- [ ] Write `tests/test_money.py` with:
  - `test_round_to_cents_half_up` — `Decimal("2.345")` → `Decimal("2.35")`.
  - `test_round_to_cents_half_up_negative` — `Decimal("-2.345")` → `Decimal("-2.35")`.
  - `test_round_to_cents_already_exact` — `Decimal("1.23")` → unchanged.
  - `test_format_amount_thousands` — `Decimal("1234567.89")` → `"1.234.567,89 EUR"`.
  - `test_format_amount_no_thousands` — `Decimal("99.00")` → `"99,00 EUR"`.
  - `test_format_amount_negative` — `Decimal("-12.50")` → `"-12,50 EUR"`.
  - `test_format_amount_zero` — `Decimal("0")` → `"0,00 EUR"`.
  - `test_format_amount_custom_currency` — currency code appears after amount.
  - `test_format_as_european_no_currency_code` — result contains no space or currency suffix.
  - `test_format_as_european_thousands` — `Decimal("1234.56")` → `"1.234,56"`.
  - `test_format_as_european_negative` — `Decimal("-12.50")` → `"-12,50"`.
- [ ] Implement `ledger_kit/utils/money.py` with `round_to_cents`, `format_amount`, `format_as_european`, and `_group_thousands` as in design §5.
- [ ] Verify: all tests pass, `ruff check` clean.

---

## Task 4 — Dialect detection and parsers

**Covers**: REQ-ING-17, REQ-ING-18, REQ-ING-19, REQ-ING-20, REQ-ING-21, REQ-ING-22, REQ-ING-23, design §3.1

- [ ] Write `tests/ingestion/test_dialect.py` with:
  - `test_detect_dialect_semicolon_only` — `"date;amount;currency"` → `EUROPEAN`.
  - `test_detect_dialect_comma_only` — `"date,amount,currency"` → `PLAIN`.
  - `test_detect_dialect_both_separators` — `"date;amount,currency"` → `None`.
  - `test_detect_dialect_empty_line` — empty string → `None`.
  - `test_parse_amount_plain_positive` — `"123.45"` → `Decimal("123.45")`.
  - `test_parse_amount_plain_negative` — `"-99.00"` → `Decimal("-99.00")`.
  - `test_parse_amount_plain_invalid` — `"abc"` → raises `InvalidOperation`.
  - `test_parse_amount_european_with_thousands` — `"1.234,56"` → `Decimal("1234.56")`.
  - `test_parse_amount_european_no_thousands` — `"12,50"` → `Decimal("12.50")`.
  - `test_parse_amount_european_negative` — `"-12,50"` → `Decimal("-12.50")`.
  - `test_parse_amount_european_invalid` — `"1,2,3"` → raises `InvalidOperation`.
  - `test_parse_date_plain` — `"2026-12-31"` → `date(2026, 12, 31)`.
  - `test_parse_date_european` — `"31/12/2026"` → `date(2026, 12, 31)`.
  - `test_parse_date_plain_invalid` — `"31/12/2026"` with `PLAIN` dialect → raises `ValueError`.
  - `test_parse_date_european_invalid` — `"2026-12-31"` with `EUROPEAN` dialect → raises `ValueError`.
- [ ] Implement `ledger_kit/ingestion/dialect.py`:
  - `CsvDialect` enum.
  - `detect_dialect(first_line: str) -> CsvDialect | None`.
  - `parse_amount(raw: str, dialect: CsvDialect) -> Decimal`.
  - `parse_date(raw: str, dialect: CsvDialect) -> date`.
- [ ] Verify: all tests pass, `ruff check` clean.

---

## Task 5 — PII utilities

**Covers**: REQ-PII-01, REQ-PII-02, design §6

- [ ] Write `tests/test_anonymise.py` with:
  - `test_scrub_replaces_counterparty` — counterparty field becomes placeholder.
  - `test_scrub_replaces_iban_when_present` — IBAN replaced with `DE00000000000000000000`.
  - `test_scrub_iban_none_stays_none` — when `iban=None`, result `iban` is still `None`.
  - `test_scrub_returns_new_instance` — result is not the same object as input.
  - `test_scrub_other_fields_unchanged` — all fields except `counterparty` and `iban` are identical.
- [ ] Implement `ledger_kit/utils/anonymise.py` with `scrub(transaction: Transaction) -> Transaction` as in design §6.
- [ ] Verify: all tests pass, `ruff check` clean.

---

## Task 6 — Bank-statement CSV reader (plain dialect + encoding)

**Covers**: REQ-ING-01, REQ-ING-02, REQ-ING-03, REQ-ING-04, REQ-ING-05, REQ-ING-06, REQ-ING-11, REQ-ING-23, REQ-ING-24, REQ-ING-25, REQ-ING-26, design §3.2

This task covers plain-dialect parsing and the encoding detection strategy. European dialect is added in Task 7.

- [ ] Write `tests/ingestion/test_csv_reader.py` normal-case and edge-case tests:
  - `test_parse_csv_plain_valid` — well-formed plain CSV with 3 rows → 3 `Transaction` objects, zero quarantine.
  - `test_parse_csv_empty_file_returns_empty` — empty file → `([], [])`.
  - `test_parse_csv_single_row_plain` — one data row → one transaction.
  - `test_parse_csv_source_ref_assigned` — `source_ref` equals `f"{source_file}:{row_index}"`.
  - `test_parse_csv_source_row_zero_based` — first data row has `source_row=0`.
  - `test_parse_csv_amount_is_decimal` — parsed `amount` type is `Decimal`.
  - `test_parse_csv_date_is_date` — parsed `date` type is `datetime.date`.
  - `test_parse_csv_negative_amount_becomes_debit` — `"-100.00"` → `flow="debit"`, `amount=Decimal("100.00")`.
  - `test_parse_csv_positive_amount_becomes_credit` — `"50.00"` → `flow="credit"`.
  - `test_parse_csv_zero_amount_becomes_credit` — `"0.00"` → `flow="credit"`, `amount=Decimal("0.00")`.
  - `test_parse_csv_missing_field_quarantined` — row missing `amount` → quarantined, reason contains `"missing_field"`.
  - `test_parse_csv_unparseable_date_quarantined` — `"not-a-date"` → quarantined, `reason="unparseable_date"`.
  - `test_parse_csv_unparseable_amount_quarantined` — `"abc"` → quarantined, `reason="unparseable_amount"`.
  - `test_parse_csv_quarantine_record_keys` — quarantine record has `source_file`, `source_row`, `reason`, `raw`.
  - `test_parse_csv_valid_rows_returned_alongside_quarantine` — file with one bad row and two good rows → two transactions + one quarantine entry.
  - `test_parse_csv_utf8_bom_decoded` — file bytes with UTF-8 BOM (`b"\xef\xbb\xbf"` prefix) → decoded correctly, transactions returned.
  - `test_parse_csv_cp1252_decoded` — file bytes containing `0x80` (€ in cp1252) → decoded as cp1252 without error.
  - `test_parse_csv_undecodable_file_quarantined` — bytes that are neither utf-8-sig nor cp1252 → `([], [quarantine])` with `reason="undecodable_file"` and `encoding_tried` key.
- [ ] Implement `ledger_kit/ingestion/csv_reader.py`:
  - `IngestionResult` type alias.
  - `parse_csv(source, *, dialect=None, source_file=None) -> IngestionResult`.
  - Encoding detection: try `utf-8-sig`, then `cp1252`, else quarantine whole file.
  - Uses `csv.DictReader` with appropriate separator.
  - Calls `dialect.parse_amount` and `dialect.parse_date`; quarantines on parse errors.
  - Applies sign-to-flow mapping (REQ-ING-24/25/26).
  - For this task: only plain dialect. Dialect detection and European parsing are wired up fully in Task 7.
- [ ] Verify: all tests pass, `ruff check` clean.

---

## Task 7 — CSV reader: European dialect and dialect auto-detection

**Covers**: REQ-ING-17, REQ-ING-18, REQ-ING-19, REQ-ING-20, REQ-ING-21, REQ-ING-22, design §3.1 + §3.2

- [ ] Extend `tests/ingestion/test_csv_reader.py` with:
  - `test_parse_csv_single_row_european` — semicolon-separated file, European amount/date → parsed correctly.
  - `test_parse_csv_european_thousands_separator` — `"1.234,56"` → `Decimal("1234.56")`.
  - `test_parse_csv_european_negative_amount` — `"-12,50"` → `flow="debit"`, `amount=Decimal("12.50")`.
  - `test_parse_csv_european_date` — `"31/12/2026"` → `date(2026, 12, 31)`.
  - `test_parse_csv_ambiguous_dialect_quarantines_file` — header with `,;` → `([], [quarantine])`.
  - `test_parse_csv_ambiguous_quarantine_includes_first_line` — quarantine record has `first_line` key.
  - `test_parse_csv_explicit_dialect_overrides_sniff` — `dialect="european"` passed explicitly → no auto-detection attempted.
  - `test_parse_csv_auto_detect_plain` — comma-header file with no explicit dialect → detected as plain.
  - `test_parse_csv_auto_detect_european` — semicolon-header file with no explicit dialect → detected as European.
- [ ] Update `parse_csv` to wire `detect_dialect` into the auto-detection path and use the resulting `CsvDialect` value when calling `parse_amount` and `parse_date`.
- [ ] Verify: full `test_csv_reader.py` passes, `ruff check` clean.

---

## Task 8 — Shared test fixtures and property-based tests for the normaliser

**Covers**: REQ-TST-01, REQ-TST-02, REQ-TST-03, REQ-TST-04, REQ-ING-15, REQ-ING-16, REQ-ING-27, design §8.2 + §8.3

- [ ] Implement `tests/conftest.py` with `empty_ledger`, `single_row_ledger`, and `clean_ledger_10` fixtures using synthetic PII-safe data (Finance Rule 5 names and IBANs).
- [ ] Write `tests/ingestion/test_normaliser.py` with:
  - **Tier 1**: `test_normalise_returns_dataframe`, `test_normalise_schema_columns_present`, `test_normalise_empty_source_returns_empty_df`.
  - **Tier 2**: `test_normalise_single_transaction`, `test_normalise_multiple_sources_merged`, `test_normalise_quarantines_null_required_field`, `test_normalise_amount_dtype_is_object_decimal`, `test_normalise_date_dtype_is_object_date`, `test_normalise_source_row_dtype_is_int`.
  - **Tier 3 — Property 1** (REQ-ING-15): `test_signed_amount_round_trip` — `@settings(max_examples=200)`.
  - **Tier 3 — Property 2** (REQ-ING-16): `test_date_round_trip_plain` — `@settings(max_examples=200)`.
  - **Tier 3 — Property 3** (REQ-ING-27): `test_european_amount_round_trip` — `@settings(max_examples=200)`, uses `format_as_european` from `money.py` as inverse.
- [ ] Implement `ledger_kit/ingestion/normaliser.py` with `normalise(*sources) -> NormaliseResult` as in design §3.4.
- [ ] Verify: all three property tests pass with 200 examples each, `ruff check` clean.

---

## Task 9 — Invoice reader

**Covers**: REQ-ING-07, REQ-ING-08, REQ-ING-09, design §3.3

- [ ] Write `tests/ingestion/test_invoice_reader.py` with:
  - **Tier 1**: `test_parse_invoice_csv_valid` — well-formed plain CSV → transactions, zero quarantine.
  - **Tier 1**: `test_parse_invoice_json_valid` — well-formed FATURA JSON array → transactions.
  - **Tier 2**: `test_parse_invoice_csv_empty` — empty CSV → `([], [])`.
  - **Tier 2**: `test_parse_invoice_json_empty_array` — `[]` JSON → `([], [])`.
  - **Tier 2**: `test_parse_invoice_json_amount_as_string` — `"amount": "123.45"` → `Decimal("123.45")`.
  - **Tier 2**: `test_parse_invoice_json_amount_as_float` — `"amount": 123.45` → `Decimal` (exact, not float).
  - **Tier 2**: `test_parse_invoice_csv_missing_field_quarantined` — quarantine record has expected keys.
  - **Tier 2**: `test_parse_invoice_format_auto_detect_json` — `.json` extension → JSON path.
  - **Tier 2**: `test_parse_invoice_format_auto_detect_csv` — `.csv` extension → CSV path.
  - **Tier 2**: `test_parse_invoice_utf8_bom_decoded` — same encoding strategy as csv_reader.
  - **Tier 2**: `test_parse_invoice_cp1252_decoded`.
- [ ] Implement `ledger_kit/ingestion/invoice_reader.py` with `parse_invoice(source, *, fmt=None, source_file=None) -> IngestionResult` as in design §3.3.
- [ ] Verify: all tests pass, `ruff check` clean.

---

## Task 10 — Detector base types and registry

**Covers**: REQ-DET-01, REQ-DET-02, REQ-DET-05, REQ-DET-07, REQ-REG-01, REQ-REG-02, REQ-REG-03, REQ-REG-04, REQ-REG-05, REQ-REG-06, design §4

- [ ] Write `tests/detectors/test_registry.py` with:
  - `test_register_adds_detector` — `@register("foo")` → `"foo"` in `registered_names()`.
  - `test_register_duplicate_name_raises` — second `@register("foo")` on a different function raises `ValueError`.
  - `test_run_all_empty_registry_returns_empty` — no detectors → `[]`.
  - `test_run_all_calls_registered_detector` — one registered detector returning one alert → result contains that alert.
  - `test_run_all_isolates_failing_detector` — detector that raises does not prevent others from running; its result has empty `alerts`.
  - `test_run_all_order_is_insertion_order` — detectors registered in a given order → results in that same order.
  - `test_auto_discover_sorted_order` — create two fake modules in a temp package; `auto_discover` imports them in alphabetical order regardless of `pkgutil` traversal order.
  - `test_auto_discover_does_not_double_register` — calling `auto_discover` twice does not raise.
  - `test_clear_registry_removes_all` — after `_clear_registry()`, `registered_names()` is empty.
  - `test_run_all_empty_ledger` — all registered detectors return `[]` for an empty DataFrame (detector contract enforcement).
  - A `conftest.py` in `tests/detectors/` that calls `_clear_registry()` in an `autouse` fixture to prevent test pollution.
- [ ] Implement `ledger_kit/detectors/base.py` with `DetectorResult` and `DetectorError` as in design §4.1.
- [ ] Implement `ledger_kit/detectors/registry.py` with `register`, `auto_discover` (sorted), `run_all`, `registered_names`, `_clear_registry` as in design §4.2.
- [ ] Implement `ledger_kit/detectors/__init__.py` re-exporting all public symbols.
- [ ] Verify: all tests pass, `ruff check` clean.

---

## Task 11 — Property-based registry tests (Tier 3)

**Covers**: REQ-TST-01 (detector layer), testing strategy §Tier 3 properties: no invention, idempotency, empty input, source ref coverage

- [ ] Extend `tests/detectors/test_registry.py` with a helper `trivial_detector` fixture that registers a detector emitting one alert for any non-empty ledger, using a real `source_ref` from the input.
- [ ] Add property-based tests using Hypothesis `data_frames` strategy:
  - `test_source_refs_are_subset_of_input` — for any generated ledger, every `source_ref` in every alert exists in the ledger's `source_ref` column (`@settings(max_examples=200)`).
  - `test_run_all_idempotent` — running `run_all` twice on the same ledger returns structurally identical results (`@settings(max_examples=200)`).
  - `test_run_all_empty_input_always_empty` — for all randomly generated DataFrames with zero rows, all detectors return `[]` (`@settings(max_examples=200)`).
- [ ] Verify: all Hypothesis tests pass with 200 examples, `ruff check` clean.

---

## Task 12 — Streamlit reference page

**Covers**: REQ-UI-01, REQ-UI-02, REQ-UI-03, REQ-UI-04, REQ-UI-05, REQ-UI-06, REQ-UI-07, REQ-UI-08, design §7

- [ ] Implement `ledger_kit/ui/__init__.py` (empty).
- [ ] Implement `ledger_kit/ui/reference_app.py`:
  - File uploader accepting multiple CSVs (`st.file_uploader`).
  - Per-file caching in `st.session_state` keyed by SHA-256 of file bytes.
  - Pass `IO[bytes]` directly to `parse_csv` (no `TextIOWrapper`).
  - Call `normalise` then `run_all`.
  - Severity summary row at the top (🔴/🟡/🔵 counts).
  - Collapsible quarantine section (only shown when quarantine list is non-empty).
  - Alert cards: `st.expander` per alert, severity badge, title, detector name, source refs.
  - For each source ref: display the matching ledger row with `pandas.Styler` yellow highlight (`background-color: #fff3cd`).
  - All `amount` values formatted with `format_amount`.
  - Encoding used surfaced as a tooltip/caption on the file summary.
- [ ] Verify: `streamlit run ledger_kit/ui/reference_app.py` starts without import errors (manual smoke test; no automated Streamlit tests at this stage).
- [ ] Verify: `ruff check` clean.

---

## Task 13 — Sample data files

**Covers**: REQ-PKG-04 (data directory), structure rule (data/samples only synthetic or public-domain), Finance Rules 5 + 6

- [ ] Create `data/samples/README.md` documenting that all files are synthetically generated and listing the generation script.
- [ ] Create `data/samples/bank_statement_sample.csv` — 10 rows, plain dialect, synthetic PII-safe data (Finance Rule 5 names, test IBANs), mix of debits and credits.
- [ ] Create `data/samples/bank_statement_sample_es.csv` — 10 rows, European dialect (semicolon, comma-decimal, DD/MM/YYYY), same data schema.
- [ ] Create `data/samples/invoice_sample.csv` — 5 rows of invoice data, plain format.
- [ ] Create `data/samples/invoice_sample.json` — 5 rows FATURA-style JSON array.
- [ ] Update `.gitignore` to exclude `data/real/` and loose `*.csv` / `*.json` / `*.pdf` outside `data/samples/`.
- [ ] Verify: `parse_csv` and `parse_invoice` successfully ingest all four sample files with zero quarantine.

---

## Task 14 — Final integration check

**Covers**: REQ-TST-06, REQ-TST-07, all requirements end-to-end

- [ ] Run the full test suite: `pytest --cov=ledger_kit --cov-fail-under=80`.
- [ ] Confirm all three test tiers are present for each module (ingestion, detectors, money, anonymise).
- [ ] Confirm `ruff check .` and `ruff format --check .` pass with zero warnings.
- [ ] Confirm all Hypothesis property tests are decorated with `@settings(max_examples=200)`.
- [ ] Confirm no test uses `datetime.now()` or `date.today()` directly; any time-sensitive test uses `freezegun` or fixed literal dates.
- [ ] Confirm no test fixture contains real personal data (names, IBANs, phone numbers outside Finance Rule 5 placeholders).
- [ ] Fix any coverage gaps or lint issues found.
