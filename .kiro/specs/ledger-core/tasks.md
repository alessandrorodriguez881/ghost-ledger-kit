# ledger-core — Implementation Tasks

Tasks are ordered so that each one builds on a stable foundation from the tasks before it. Every task is **test-first**: write or update tests first, then implement until the tests pass.

Within each task the sub-items are ordered: scaffold → tests → implementation → verify (lint + coverage).

---

## Task 1 — Project scaffold and package metadata

**Covers**: REQ-PKG-01, REQ-PKG-02, REQ-PKG-05, REQ-PKG-06, REQ-PKG-07

- [x] Create `pyproject.toml` at the workspace root with:
  - `[build-system]` using `setuptools` and `setuptools-scm` (PEP 517/518, no `setup.py`)
  - `[project]` metadata: name `ledger-kit`, requires-python `>=3.11`
  - `[project.optional-dependencies]` groups: `dev` (pytest, hypothesis, freezegun, pytest-cov, ruff) and `llm` (`openai`, exact pinned version; REQ-PKG-07)
  - `[tool.ruff]` section: `line-length = 100`, `select = ["E","F","I","UP"]`
  - `[tool.ruff.format]` section
  - `[tool.pytest.ini_options]` section: `pythonpath = ["."]` and `testpaths = ["tests", "apps"]` (REQ-PKG-06)
- [x] Create `requirements.txt` with pinned exact versions for all runtime deps (pandas, pydantic, streamlit) and dev deps; list `openai` pinned under an "optional (llm extra)" comment.
- [x] Write `tests/test_packaging.py` (first, before the config is final):
  - `test_pytest_config_sets_pythonpath_and_testpaths` — parse `pyproject.toml` with `tomllib`; assert `pythonpath == ["."]` and `testpaths == ["tests", "apps"]`.
  - `test_ledger_kit_importable_without_editable_install` — `import ledger_kit` succeeds under plain `pytest` (no `pip install -e .`); verify by running `pytest tests/test_packaging.py` in a fresh venv that has only `requirements.txt` installed.
  - `test_openai_is_optional_extra_only` — `openai` is absent from `[project].dependencies`, and present with an `==` pin in `[project.optional-dependencies].llm`.
- [x] Create the top-level package skeleton — empty `__init__.py` files for:
  - `ledger_kit/`
  - `ledger_kit/ingestion/`
  - `ledger_kit/detectors/`
  - `ledger_kit/ui/`
  - `ledger_kit/utils/`
- [x] Create `ledger_kit/defaults.toml` with the content from design §9.
- [x] Create `.env.example` documenting any required environment variables.
- [x] Verify: `ruff check .` and `ruff format --check .` pass with zero warnings.

---

## Task 2 — Canonical data models

**Covers**: REQ-ING-13 (Transaction schema), REQ-DET-03 (Alert schema), REQ-MOD-01 to REQ-MOD-10, design §2

- [x] Write `tests/test_models.py` with:
  - `test_transaction_source_ref_computed` — building a `Transaction` produces correct `source_ref`.
  - `test_transaction_amount_must_be_positive` — constructing with a negative amount raises `ValidationError`.
  - `test_transaction_is_frozen` — attempting to mutate a field raises an error.
  - `test_alert_requires_non_empty_source_refs` — empty `source_refs` list raises `ValidationError`.
  - `test_alert_is_frozen` — attempting to mutate a field raises an error.
  - `test_alert_deterministic_id` — two `Alert` instances with identical `detector`, `source_refs`, and `data` (no explicit `id`) produce the same `id` (REQ-MOD-01).
  - `test_alert_explicit_id_preserved` — passing `id="custom-id"` returns that exact value (REQ-MOD-02).
  - `test_alert_id_with_decimal_and_date_data` — `data={"yearly_cost": Decimal("155.88"), "last": date(2026, 1, 15)}` builds without `TypeError`; `id` is 64 hex chars and identical on a second construction (REQ-MOD-05).
  - `test_alert_id_numpy_scalar_matches_python_value` — `data={"n": numpy.int64(3)}` and `data={"n": 3}` give the same `id` (REQ-MOD-05).
  - `test_alert_missing_source_refs_raises_validation_error` — `Alert(detector="x.y", severity="info", title="t", data={})` raises `pydantic.ValidationError`, not `KeyError` (REQ-MOD-06).
  - `test_quarantine_dict_shape` — document expected quarantine record keys via a helper.
  - *(CR-LC-3a)* `test_invoice_defaults` — an `Invoice` built without `surcharge_amount`, `withholding_amount`, `iban`, `due_date_is_default` has `Decimal("0")`, `Decimal("0")`, `None`, `False`.
  - *(CR-LC-3a)* `test_invoice_vat_rate_is_a_percentage` — `vat_rate=Decimal("21")` is stored as 21 (not 0.21).
  - *(CR-LC-3a)* `test_invoice_negative_amount_raises_validation_error` — each of the six amount fields rejects a negative value.
  - *(CR-LC-3a)* `test_invoice_is_frozen_and_has_no_id_field`.
  - *(CR-LC-3b)* `test_supplier_iban_optional_and_verbatim` — `iban=None` allowed; `" es88 2100 "` stored unchanged (REQ-MOD-10).
  - *(CR-LC-3b)* `test_supplier_is_frozen`.
  - *(CR-LC-3a)* `test_package_reexports_models` — `from ledger_kit import Transaction, Invoice, Supplier, Alert` works.
- [x] Implement `ledger_kit/models.py`:
  - `Transaction` Pydantic v2 model exactly as in design §2.1.
  - `Alert` Pydantic v2 model with deterministic `id` validator as in design §2.2 (CR-LC-1b).
  - Both with `model_config = {"frozen": True}`.
  - Add a Pydantic validator that enforces `amount >= 0` on `Transaction`.
  - Add a Pydantic validator that enforces `len(source_refs) >= 1` on `Alert`.
  - `_deterministic_alert_id` helper using sha256 of canonical JSON, serialised with `json.dumps(..., default=_json_default)` (numpy scalars → Python types via `.item()`, everything else → `str`; design §2.2).
  - `Alert._set_deterministic_id` imports `model_validator` from `pydantic`, copies the input dict instead of mutating it, and computes the id only when `detector`, `source_refs` and `data` are all present, so a missing field surfaces as `ValidationError`.
  - *(CR-LC-3a/3b)* `Invoice` and `Supplier` Pydantic v2 models exactly as in design §2.1a/§2.1b (frozen; non-negative validator on the six `Invoice` amount fields; no normalisation of identifiers).
- [x] Update `ledger_kit/__init__.py` to re-export `Transaction`, `Invoice`, `Supplier` and `Alert`.
- [x] Verify: all tests pass, `ruff check` clean.

---

## Task 3 — Money utilities

**Covers**: REQ-MON-01, REQ-MON-02, REQ-MON-03, REQ-MON-04, REQ-MON-05, REQ-MON-06, REQ-ING-27 (format_as_european), design §5

- [x] Write `tests/test_money.py` with:
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
  - *(CR-LC-3e)* `test_percent_of_basic` — `percent_of(Decimal("100.00"), Decimal("21"))` → `Decimal("21.00")`; rates 10, 4, 0 → `10.00`, `4.00`, `0.00`.
  - *(CR-LC-3e)* `test_percent_of_rounds_half_up` — `percent_of(Decimal("0.50"), Decimal("21"))` → `Decimal("0.11")` (0.105); `percent_of(Decimal("1000.00"), Decimal("21"))` → `Decimal("210.00")`.
  - *(CR-LC-3e)* `test_percent_of_is_never_float` — result type is `Decimal` with exponent `-2`.
  - *(CR-LC-3e)* `test_within_tolerance_boundaries` — difference `0.01` with `tol=0.01` → `True` (inclusive); `0.02` → `False`; order of `a`, `b` irrelevant.
  - *(CR-LC-3e)* `test_within_tolerance_negative_tol_raises` — `ValueError`.
  - *(CR-LC-3e)* `test_net_total` — `net_total([1000.00, 210.00], [150.00])` → `Decimal("1060.00")`; `net_total([100.00, 21.00, 5.20])` → `Decimal("126.20")`; empty inputs → `Decimal("0")`.
  - *(CR-LC-3e)* Property (`max_examples=200`): `test_percent_of_matches_quantize` — for any base in `[0, 1 000 000]` (2 places) and rate in `{21, 10, 4, 0}`, `percent_of` equals `(base * rate / 100).quantize(Decimal("0.01"), ROUND_HALF_UP)`.
- [x] Implement `ledger_kit/utils/money.py` with `round_to_cents`, `format_amount`, `format_as_european`, `_group_thousands`, and (CR-LC-3e) `percent_of`, `within_tolerance`, `net_total` as in design §5.
- [x] Verify: all tests pass, `ruff check` clean.

---

## Task 4 — Dialect detection and parsers

**Covers**: REQ-ING-17, REQ-ING-18, REQ-ING-19, REQ-ING-20, REQ-ING-21, REQ-ING-22, REQ-ING-23, design §3.1

- [x] Write `tests/ingestion/test_dialect.py` with:
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
  - `test_parse_amount_european_rejects_plain_decimal` — `"12.50"` with `EUROPEAN` → raises `InvalidOperation` (not `Decimal("1250")`).
  - `test_parse_amount_european_rejects_negative_plain_decimal` — `"-12.5"` with `EUROPEAN` → raises `InvalidOperation` (not `Decimal("-125")`).
  - `test_parse_amount_european_rejects_anglo_thousands` — `"1,234.56"` with `EUROPEAN` → raises `InvalidOperation` (not `Decimal("1.23456")`).
  - `test_parse_date_plain` — `"2026-12-31"` → `date(2026, 12, 31)`.
  - `test_parse_date_european` — `"31/12/2026"` → `date(2026, 12, 31)`.
  - `test_parse_date_plain_invalid` — `"31/12/2026"` with `PLAIN` dialect → raises `ValueError`.
  - `test_parse_date_european_invalid` — `"2026-12-31"` with `EUROPEAN` dialect → raises `ValueError`.
- [x] Implement `ledger_kit/ingestion/dialect.py`:
  - `CsvDialect` enum.
  - `detect_dialect(first_line: str) -> CsvDialect | None`.
  - `parse_amount(raw, dialect)`: for `EUROPEAN`, `fullmatch` against `_EUROPEAN_AMOUNT_RE` first and raise `InvalidOperation` when it does not match; only then strip `.`, replace `,`, convert (design §3.1).
  - `parse_date(raw: str, dialect: CsvDialect) -> date`.
- [x] Verify: all tests pass, `ruff check` clean.

---

## Task 5 — PII utilities

**Covers**: REQ-PII-01, REQ-PII-02, REQ-PII-03, REQ-PII-04, design §6

- [x] Write `tests/test_anonymise.py` with:
  - `test_scrub_replaces_counterparty` — counterparty field becomes placeholder.
  - `test_scrub_replaces_iban_when_present` — IBAN replaced with `DE00000000000000000000`.
  - `test_scrub_iban_none_stays_none` — when `iban=None`, result `iban` is still `None`.
  - `test_scrub_returns_new_instance` — result is not the same object as input.
  - `test_scrub_other_fields_unchanged` — all fields except `counterparty` and `iban` are identical.
  - *(CR-LC-3g)* `test_mask_iban_last_four` — `"ES88 2100 0418 5602 0005 1332"` → `"****1332"`.
  - *(CR-LC-3g)* `test_mask_iban_cleans_spaces_case_and_nbsp` — `"es88\u00a02100 0418 5602 0005 1332"` → `"****1332"`.
  - *(CR-LC-3g)* `test_mask_iban_short_value_reveals_nothing` — `""`, `"AB"`, `"1234"` → `"****"`.
  - *(CR-LC-3g)* `test_mask_iban_never_contains_full_value_and_is_not_iban_shaped` — property (`max_examples=200`) over random strings of length 5–34: result has length 8 and does not match the explainer `_IBAN_RE`.
- [x] Implement `ledger_kit/utils/anonymise.py` with `scrub(transaction: Transaction) -> Transaction` and `mask_iban(iban: str) -> str` as in design §6.
- [x] Verify: all tests pass, `ruff check` clean.

---

## Task 6 — Bank-statement CSV reader (plain dialect + encoding)

**Covers**: REQ-ING-01, REQ-ING-02, REQ-ING-03, REQ-ING-04, REQ-ING-05, REQ-ING-06, REQ-ING-11, REQ-ING-14, REQ-ING-23, REQ-ING-24, REQ-ING-25, REQ-ING-26, REQ-ING-29, design §3.2

This task covers plain-dialect parsing and the encoding detection strategy. European dialect is added in Task 7.

- [x] Write `tests/ingestion/test_csv_reader.py` normal-case and edge-case tests:
  - `test_parse_csv_plain_valid` — well-formed plain CSV with 3 rows → 3 `Transaction` objects, zero quarantine.
  - `test_parse_csv_empty_file_returns_empty` — empty file → `([], [])`.
  - `test_parse_csv_whitespace_only_file_returns_empty` — file containing only `"  \n\n\t\n"` → `([], [])` (not quarantined as `ambiguous_dialect`; REQ-ING-06).
  - `test_parse_csv_empty_bytes_stream_returns_empty` — `io.BytesIO(b"")` → `([], [])`.
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
  - *(CR-LC-3c)* `test_parse_csv_iban_column_read_verbatim` — header with an `iban` column and the cell `" es88 2100 0418 5602 0005 1332"` (leading space, lowercase, spaces) → `Transaction.iban` equals that exact string.
  - *(CR-LC-3c)* `test_parse_csv_iban_column_absent_is_none` — no `iban` column → `iban is None`, no quarantine.
  - *(CR-LC-3c)* `test_parse_csv_iban_empty_or_blank_cell_is_none` — empty cell and whitespace-only cell → `iban is None`, row not quarantined.
  - *(CR-LC-3c)* `test_parse_csv_iban_column_european_dialect` — the same verbatim behaviour in a semicolon file.
- [x] Implement `ledger_kit/ingestion/csv_reader.py`:
  - `IngestionResult` type alias.
  - `parse_csv(source, *, dialect=None, source_file=None) -> IngestionResult`.
  - Encoding detection: try `utf-8-sig`, then `cp1252`, else quarantine whole file.
  - After decoding, if the text is empty or whitespace-only, return `([], [])` **before** `detect_dialect` is called (REQ-ING-06).
  - Uses `csv.DictReader` with appropriate separator.
  - Calls `dialect.parse_amount` and `dialect.parse_date`; quarantines on parse errors.
  - Applies sign-to-flow mapping (REQ-ING-24/25/26).
  - *(CR-LC-3c)* Reads the optional `iban` cell verbatim into `Transaction.iban` (`None` when the column is absent or the cell is empty/whitespace-only).
  - For this task: only plain dialect. Dialect detection and European parsing are wired up fully in Task 7.
- [x] Verify: all tests pass, `ruff check` clean.

---

## Task 7 — CSV reader: European dialect and dialect auto-detection

**Covers**: REQ-ING-17, REQ-ING-18, REQ-ING-19, REQ-ING-20, REQ-ING-21, REQ-ING-22, design §3.1 + §3.2

- [x] Extend `tests/ingestion/test_csv_reader.py` with:
  - `test_parse_csv_single_row_european` — semicolon-separated file, European amount/date → parsed correctly.
  - `test_parse_csv_european_thousands_separator` — `"1.234,56"` → `Decimal("1234.56")`.
  - `test_parse_csv_european_negative_amount` — `"-12,50"` → `flow="debit"`, `amount=Decimal("12.50")`.
  - `test_parse_csv_european_date` — `"31/12/2026"` → `date(2026, 12, 31)`.
  - `test_parse_csv_ambiguous_dialect_quarantines_file` — header with `,;` → `([], [quarantine])`.
  - `test_parse_csv_european_plain_decimal_amount_quarantined` — semicolon file with amount `"12.50"` (and, in a second row, `"1,234.56"`) → each row quarantined with `reason="unparseable_amount"`; no transaction with amount `1250` or `1.23456` is emitted (REQ-ING-22).
  - `test_parse_csv_ambiguous_quarantine_includes_first_line` — quarantine record has `first_line` key.
  - `test_parse_csv_explicit_dialect_overrides_sniff` — `dialect="european"` passed explicitly → no auto-detection attempted.
  - `test_parse_csv_auto_detect_plain` — comma-header file with no explicit dialect → detected as plain.
  - `test_parse_csv_auto_detect_european` — semicolon-header file with no explicit dialect → detected as European.
- [x] Update `parse_csv` to wire `detect_dialect` into the auto-detection path and use the resulting `CsvDialect` value when calling `parse_amount` and `parse_date`.
- [x] Verify: full `test_csv_reader.py` passes, `ruff check` clean.

---

## Task 8 — Shared test fixtures and property-based tests for the normaliser

**Covers**: REQ-TST-01, REQ-TST-02, REQ-TST-03, REQ-TST-04, REQ-ING-10, REQ-ING-15, REQ-ING-16, REQ-ING-27, REQ-ING-28, REQ-ING-33, REQ-ING-34, design §8.2 + §8.3

- [x] Implement `tests/conftest.py` with `empty_ledger`, `single_row_ledger`, and `clean_ledger_10` fixtures using synthetic PII-safe data (Finance Rule 5 names and IBANs).
- [x] Write `tests/ingestion/test_normaliser.py` with:
  - **Tier 1**: `test_normalise_returns_dataframe`, `test_normalise_schema_columns_present`, `test_normalise_empty_source_returns_empty_df`.
  - **Tier 2**: `test_normalise_all_quarantined_returns_empty_df_with_columns` — every input transaction fails validation → empty DataFrame whose columns equal `CANONICAL_COLUMNS`, and `ledger["source_ref"]` does not raise `KeyError` (REQ-ING-28). `test_normalise_no_sources_returns_empty_df_with_columns` — `normalise()` with no arguments, same assertions.
  - **Tier 2**: `test_normalise_single_transaction`, `test_normalise_multiple_sources_merged`, `test_normalise_quarantines_null_required_field`, `test_normalise_amount_dtype_is_object_decimal`, `test_normalise_date_dtype_is_object_date`, `test_normalise_source_row_dtype_is_int`.
  - *(CR-LC-3a/3b)* **Tier 1**: `test_normalise_invoices_returns_invoice_columns` (columns equal `INVOICE_COLUMNS`, REQ-ING-34); `test_normalise_suppliers_returns_supplier_columns`.
  - *(CR-LC-3a/3b)* **Tier 2**: `test_normalise_empty_invoice_kind_returns_empty_df_with_invoice_columns` (`normalise(kind="invoice")` and `normalise([], kind="supplier")`); `test_normalise_all_invoices_quarantined_keeps_columns`; `test_normalise_mixed_kinds_raises_value_error`; `test_normalise_kind_disagreeing_with_inferred_kind_raises_value_error`; `test_normalise_invoice_decimal_and_date_dtypes` (`base_amount`, `vat_rate`, `total` hold `Decimal`; `issue_date`, `due_date` hold `datetime.date`; `source_row` is `int64`); `test_normalise_no_sources_defaults_to_transaction_columns`.
  - **Tier 3 — Property 1** (REQ-ING-15): `test_signed_amount_round_trip` — `@settings(max_examples=200)`.
  - **Tier 3 — Property 2** (REQ-ING-16): `test_date_round_trip_plain` — `@settings(max_examples=200)`.
  - **Tier 3 — Property 3** (REQ-ING-27): `test_european_amount_round_trip` — `@settings(max_examples=200)`, uses `format_as_european` from `money.py` as inverse.
- [x] Implement `ledger_kit/ingestion/normaliser.py` with `normalise(*sources, kind=None) -> NormaliseResult` as in design §3.4, including the module-level `CANONICAL_COLUMNS`, `INVOICE_COLUMNS` and `SUPPLIER_COLUMNS` tuples and `pd.DataFrame(rows, columns=COLUMNS[kind])`.
- [x] Verify: all three property tests pass with 200 examples each, `ruff check` clean.

---

## Task 9 — Invoice reader and supplier-master reader

**Covers**: REQ-ING-07, REQ-ING-08, REQ-ING-09, REQ-ING-30, REQ-ING-31, REQ-ING-32, design §3.3 + §3.3a (revised by CR-LC-3a/3b)

- [x] Write `tests/ingestion/test_invoice_reader.py` with:
  - **Tier 1**: `test_parse_invoice_csv_valid` — well-formed plain CSV with all columns → `Invoice` objects (not `Transaction`), zero quarantine; every field of the first invoice asserted, including `vat_rate == Decimal("21")` and `source_ref == "inv.csv:0"`.
  - **Tier 1**: `test_parse_invoice_json_valid` — well-formed JSON array → `Invoice` objects.
  - **Tier 1**: `test_parse_invoice_optional_columns_default` — CSV without `due_date`, `surcharge_amount`, `withholding_amount`, `iban` → `surcharge_amount == Decimal("0")`, `withholding_amount == Decimal("0")`, `iban is None`, `due_date == issue_date + 30 days`, `due_date_is_default is True`.
  - **Tier 1**: `test_parse_invoice_explicit_due_date_not_defaulted` — a given `due_date` is kept and `due_date_is_default is False`.
  - **Tier 2**: `test_parse_invoice_csv_empty` — empty CSV → `([], [])`.
  - **Tier 2**: `test_parse_invoice_csv_whitespace_only` — whitespace-only CSV → `([], [])`.
  - **Tier 2**: `test_parse_invoice_json_empty_array` — `[]` JSON → `([], [])`.
  - **Tier 2**: `test_parse_invoice_json_amount_as_string` — `"base_amount": "123.45"` → `Decimal("123.45")`.
  - **Tier 2**: `test_parse_invoice_json_amount_as_float` — `"base_amount": 123.45` → `Decimal("123.45")` (exact, not float noise).
  - **Tier 2**: `test_parse_invoice_csv_missing_field_quarantined` — each of the nine mandatory columns blank in turn → quarantined with `reason == "missing_field:<name>"`; record has `source_file`, `source_row`, `reason`, `raw`.
  - **Tier 2**: `test_parse_invoice_negative_amount_quarantined` — a negative `total` (and negative `base_amount`, `vat_rate`) → `reason="negative_amount"`.
  - **Tier 2**: `test_parse_invoice_percent_sign_vat_rate_quarantined` — `"21%"` → `reason="unparseable_amount"`.
  - **Tier 2**: `test_parse_invoice_unparseable_issue_date_quarantined`.
  - **Tier 2**: `test_parse_invoice_iban_kept_verbatim` — `"es88 2100 0418 5602 0005 1332"` and a hyphenated IBAN are stored unchanged.
  - **Tier 2**: `test_parse_invoice_format_auto_detect_json` — `.json` extension → JSON path.
  - **Tier 2**: `test_parse_invoice_format_auto_detect_csv` — `.csv` extension → CSV path.
  - **Tier 2**: `test_parse_invoice_utf8_bom_decoded` — same encoding strategy as csv_reader.
  - **Tier 2**: `test_parse_invoice_cp1252_decoded`.
- [x] Write `tests/ingestion/test_supplier_reader.py` (CR-LC-3b) with:
  - **Tier 1**: `test_parse_suppliers_valid` — 3 rows → 3 `Supplier` objects, `source_ref == "sup.csv:0"` for the first.
  - **Tier 2**: `test_parse_suppliers_empty_and_whitespace_only` → `([], [])`; `test_parse_suppliers_missing_name_or_tax_id_quarantined` (`missing_field:supplier_name`, `missing_field:tax_id`); `test_parse_suppliers_iban_optional_and_verbatim`; `test_parse_suppliers_undecodable_file_quarantined`; `test_parse_suppliers_tax_id_and_iban_not_normalised` (REQ-MOD-10).
- [x] Implement `ledger_kit/ingestion/invoice_reader.py` with `DEFAULT_PAYMENT_TERM_DAYS = 30` and `parse_invoice(source, *, fmt=None, source_file=None) -> IngestionResult[Invoice]` as in design §3.3.
- [x] Implement `ledger_kit/ingestion/supplier_reader.py` with `parse_suppliers` as in design §3.3a.
- [x] Verify: all tests pass, `ruff check` clean.

---

## Task 10 — Detector base types and registry

**Covers**: REQ-DET-01, REQ-DET-02, REQ-DET-04, REQ-DET-05, REQ-DET-07, REQ-DET-08, REQ-REG-01, REQ-REG-02, REQ-REG-03, REQ-REG-04, REQ-REG-05, REQ-REG-06, REQ-REG-07, REQ-TST-09, REQ-TST-10, REQ-MOD-05, design §4

- [x] Write `tests/detectors/test_registry.py` with:
  - `test_register_adds_detector` — `@register("ns.foo")` → `"ns.foo"` in `registered_names()`.
  - `test_register_duplicate_name_raises` — second `@register("ns.foo")` on a different function raises `ValueError`.
  - `test_register_invalid_name_no_dot_raises` — `@register("nodot")` raises `ValueError`.
  - `test_register_invalid_name_uppercase_raises` — `@register("NS.foo")` raises `ValueError`.
  - `test_register_invalid_name_empty_part_raises` — `@register(".foo")` and `@register("ns.")` both raise `ValueError`.
  - `test_run_all_empty_registry_returns_empty` — no detectors → `[]`.
  - `test_run_all_calls_registered_detector` — one registered detector returning one alert → result contains that alert.
  - `test_run_all_isolates_failing_detector` — detector that raises does not prevent others from running; its result has empty `alerts`.
  - `test_run_all_order_is_insertion_order` — detectors registered in a given order → results in that same order.
  - `test_run_all_namespace_filter_excludes_other_ns` — register `"zs.a"` and `"pi.b"`; `run_all(ledger, namespace="zs")` returns only the `"zs.a"` result.
  - `test_run_all_namespace_filter_none_runs_all` — `run_all(ledger, namespace=None)` runs both namespaces.
  - `test_run_all_context_passed_as_mapping_proxy` — the `context` argument received by the detector is a `MappingProxyType`; attempting `context["new_key"] = 1` raises `TypeError`.
  - `test_run_all_empty_context_when_none_passed` — calling `run_all(ledger)` with no `context` passes an empty `MappingProxyType` to the detector (detector receives `{}` view).
  - `test_run_all_context_values_accessible` — detector can read `context["aliases"]` when passed via `run_all`.
  - `test_registered_names_namespace_filter` — `registered_names(namespace="zs")` returns only `"zs.*"` names.
  - `test_auto_discover_sorted_order` — create two fake modules in a temp package; `auto_discover` imports them in alphabetical order regardless of `pkgutil` traversal order.
  - `test_auto_discover_does_not_double_register` — calling `auto_discover` twice does not raise.
  - `test_clear_registry_removes_all` — after `_clear_registry()`, `registered_names()` is empty (the test itself restores the registry via the snapshot fixture).
  - `test_snapshot_restore_roundtrip` — register `"ns.tmp"`, take a snapshot, register `"ns.other"`, restore; `registered_names()` equals the snapshot's names and the original function objects are intact.
  - `test_clear_then_restore_keeps_preexisting_detectors` — a detector `"tfix.keep"` is registered at module scope of the test file; snapshot, `_clear_registry()`, restore; `"tfix.keep"` is registered again (this is why fixtures restore instead of clearing; REQ-TST-09).
  - `test_run_all_empty_ledger` — all registered detectors return `[]` for an empty DataFrame **with an empty context** (detector contract enforcement; REQ-DET-05 — a detector documented to read `context` may return alerts for an empty ledger only when its context inputs are non-empty).
  - *(CR-LC-3d)* `test_loaded_source_refs_is_union_of_ledger_and_context_frames` — ledger refs `{"a:0"}`, context `{"payments": df(["p:0"]), "suppliers": df(["s:0"]), "as_of": date}` → `{"a:0", "p:0", "s:0"}`.
  - *(CR-LC-3d)* `test_loaded_source_refs_tolerates_missing_column_and_non_frames` — a frame without `source_ref`, a `None` value and an empty `pd.DataFrame()` ledger contribute nothing and do not raise.
  - *(CR-LC-3f)* `test_context_reading_detector_may_alert_on_empty_ledger` — a detector registered in the test that reads `context["payments"]` returns one alert for `pd.DataFrame()` + non-empty payments, and `[]` when both are empty; `run_all` keeps the alert.
  - `test_run_all_keeps_alerts_with_decimal_and_date_data` — a detector returning an `Alert` whose `data` holds `Decimal` and `date` values is **not** dropped by `run_all` (regression for the id `TypeError`; REQ-MOD-05).
  - A `conftest.py` in `tests/detectors/` providing two function-scoped fixtures:
    - `isolated_registry` (autouse for `test_registry.py`): `snap = _snapshot_registry()`; yield; `_restore_registry(snap)`.
    - `empty_registry`: snapshot, `_clear_registry()`, yield, restore. Used only by tests that need an empty registry (e.g. `test_run_all_empty_registry_returns_empty`).
    Neither fixture is used by the Hypothesis tests (REQ-TST-09).
- [x] Implement `ledger_kit/detectors/base.py` with `DetectorResult`, `DetectorError` and `loaded_source_refs` (CR-LC-3d) as in design §4.1.
- [x] Implement `ledger_kit/detectors/registry.py` with `register` (name validation), `auto_discover` (sorted), `run_all` (namespace filter + MappingProxyType context), `registered_names` (namespace filter), `_clear_registry`, `_snapshot_registry`, `_restore_registry` as in design §4.2.
- [x] Implement `ledger_kit/detectors/__init__.py` re-exporting all public symbols (including `loaded_source_refs`).
- [x] Verify: all tests pass, `ruff check` clean.

---

## Task 11 — Property-based registry tests (Tier 3)

**Covers**: REQ-TST-01 (detector layer), REQ-TST-09, testing strategy §Tier 3 properties: no invention, idempotency, empty input, source ref coverage

- [x] Create `tests/detectors/test_registry_properties.py`. At **module scope** (executed once at import, never inside a test or `@given` body) register the test detectors with distinct names: `"tprop.trivial"` (one alert citing a real `source_ref` from the input, for any non-empty ledger), `"tprop_zs.a"` and `"tprop_pi.b"` (each appends its name to a module-level `CALLS` list). No function-scoped fixture is used in this file; no `_clear_registry`.
- [x] Add property-based tests using Hypothesis `data_frames` strategy. Each calls `run_all(ledger, namespace=...)` with a `tprop`-prefixed namespace so unrelated registered detectors cannot interfere:
  - `test_source_refs_are_subset_of_input` — for any generated ledger **and any generated context frames** (e.g. a `payments` frame with its own `source_ref` column), every `source_ref` in every alert is in `loaded_source_refs(ledger, context)`, the union of all loaded inputs (CR-LC-3d, REQ-TST-10). `tprop.trivial` is extended to also cite the first `source_ref` of a context frame when one is present (`@settings(max_examples=200)`).
  - `test_run_all_idempotent` — running `run_all` twice on the same ledger returns structurally identical results (`@settings(max_examples=200)`).
  - `test_run_all_empty_input_always_empty` — for all randomly generated DataFrames with zero rows, all detectors return `[]` (`@settings(max_examples=200)`).
  - `test_namespace_filter_never_calls_other_ns` — `CALLS.clear()` then `run_all(ledger, namespace="tprop_zs")`; `CALLS` never contains `"tprop_pi.b"` for any generated ledger (`@settings(max_examples=200)`).
  - `test_context_is_immutable_proxy` — for any generated `context` dict, the `MappingProxyType` received by the detector raises `TypeError` on any attempted mutation (`@settings(max_examples=200)`).
  - `test_module_scope_registration_is_not_duplicated` — (plain test) `registered_names("tprop")` contains each `tprop*` name exactly once after the Hypothesis tests have run many examples.
- [x] Verify: the Hypothesis tests run without a `function_scoped_fixture` health-check failure and without a duplicate-name `ValueError`; all pass with 200 examples, `ruff check` clean.

---

## Task 11a — Explainer layer (test-first)

**Covers**: REQ-EXP-01 through REQ-EXP-11, REQ-TST-08, REQ-PKG-07, design §4a

- [x] Write `tests/test_explainer.py` — all tests inject `MockLLMClient` via `client=` parameter; no network calls, no patching of `openai.OpenAI`:
  - `test_explain_fallback_when_no_api_key` — `OPENAI_API_KEY` unset, no client → filled fallback, `source="fallback"`.
  - `test_explain_money_placeholder_formats_amount` — `{yearly_cost:money}` with `"155.88"` → `"155,88 EUR"`.
  - `test_explain_plain_placeholder_inserts_as_string` — `{charge_count}` with `"12"` → `"12"` (not `"12,00 EUR"`).
  - `test_explain_source_refs_placeholder` — `{source_refs}` → comma-joined refs string.
  - `test_explain_unknown_placeholder_left_as_is` — unknown key left unchanged.
  - `test_build_prompt_includes_source_refs` — system message in `client.calls[0]["messages"]` contains all `alert.source_refs` values.
  - `test_build_prompt_includes_no_invention_instruction` — that system message contains Finance Rule 1 phrase verbatim.
  - `test_mock_client_chat_completions_create_resolves` — `MockLLMClient(["x"]).chat.completions.create(model="m")` returns a response and appends its kwargs to `client.calls` (`chat` is a property).
  - `test_explain_with_meta_returns_explanation_dataclass` — result is `Explanation` with correct fields.
  - `test_explain_with_meta_llm_source_on_success` — valid mock response → `source="llm"`, `rejected_numbers=()`.
  - `test_explain_number_guard_european_format_passes` — `"12,99 EUR"` in response passes when `alert.data` has `"12.99"` (not split into `12` and `99`).
  - `test_explain_number_guard_european_thousands_passes` — `"1.060,00 EUR"` passes when `alert.data` has `"1060.00"`.
  - `test_explain_number_guard_two_amounts_in_one_sentence_pass` — `"15,99 EUR monthly, 191,88 EUR yearly"` passes when both values are allowed.
  - `test_explain_number_guard_glued_allowed_number_passes` — `"15.99EUR"` passes when `15.99` is allowed.
  - `test_explain_number_guard_rejects_made_up_number_equal_to_row_index` — cited ref `bank.csv:3`; response with a made-up `3 EUR` plus `(bank.csv:3)`, and no value 3 in `alert.data` or cited cells → fallback, `rejected_numbers=("3",)`; the same response without the made-up `3 EUR` passes.
  - `test_explain_number_guard_rejects_invented_number_glued_to_letters` — `"invoice F2026099"` (not allowed) → fallback, `"2026099"` in `rejected_numbers`.
  - `test_explain_number_guard_rejects_iban_shaped_token` — response containing `"DE00 0000 0000 0000 0000 00"` → fallback.
  - `test_explain_number_guard_rejects_malformed_date` — response containing `"31/02/2026"` → fallback.
  - `test_tokenise_removes_dates_then_refs_then_numbers` — `_tokenise("on 2026-01-15, see bank.csv:3: 12,99 EUR and 15.99EUR", ["bank.csv:3"])` → dates `{date(2026,1,15)}`, numbers `("12,99", "15.99")`; unit test of the shared tokeniser.
  - `test_allowed_decimals_excludes_row_numbers_and_date_parts` — for cited row `bank.csv:3` dated 2026-01-15 with amount `12.99`, `_allowed_decimals` is exactly `{Decimal("12.99")}` plus any `Alert.data` values; it contains none of `3`, `2026`, `1`, `15`.
  - `test_explain_number_guard_rejects_hallucinated_number` — response with `"999.99"` (not in alert/rows) → `source="fallback"`.
  - `test_explain_number_guard_passes_valid_response` — response with only known figures → `source="llm"`.
  - `test_explain_date_guard_rejects_hallucinated_date` — response mentions a date not in cited rows → fallback.
  - `test_explain_date_guard_passes_row_date` — response mentions an ISO date matching a row → passes; its parts are not treated as numbers.
  - `test_explain_fallback_on_api_error` — mock raises `RuntimeError` → fallback, no re-raise.
  - `test_explain_openai_import_error_falls_back` — `OPENAI_API_KEY` set, no client, `monkeypatch.setitem(sys.modules, "openai", None)` → fallback, no exception.
  - `test_fill_fallback_is_public` — `from ledger_kit.explainer import fill_fallback` works; `fill_fallback("{yearly_cost:money} ({n})", alert)` returns the European-formatted amount and the plain value; `ledger_kit.explainer` has no attribute `_fill_fallback` (DN-9).
  - `test_explain_openai_client_built_with_no_sdk_retries` — fake `openai` module in `sys.modules` whose `OpenAI` records kwargs: `timeout == LLM_TIMEOUT_SECONDS` and `max_retries == 0`.
  - `test_explain_rows_json_has_iso_dates` — user message in `client.calls[0]["messages"]` contains `"2026-01-15"` and does not contain `"T00:00"` (plain assertion; the implementation maps the `date` column through `date.isoformat` before `to_json`, design §4a.5).
  - `test_explain_only_safe_columns_sent` — user message in `client.calls[0]["messages"]` has no `id` or `description` key for the rows.
  - *(CR-LC-3g)* `test_explain_row_columns_parameter_selects_columns`, `test_explain_default_row_columns_unchanged`, `test_explain_invoice_date_columns_sent_as_iso_and_guarded`, `test_explain_iban_column_never_sent_even_if_listed`, `test_explain_masked_iban_in_alert_data_passes_guard` — exactly as specified in REQ-TST-08 (CR-LC-3g bullets).
  - *(CR-LC-3g)* `test_allowed_dates_collects_every_date_column` — rows with `issue_date` and `due_date` cells give both dates in `_allowed_dates`; `_allowed_decimals` adds none of their parts.
  - **Property** `test_number_guard_any_foreign_decimal_triggers_fallback` — `@settings(max_examples=200)`: generate foreign Decimal values in `[10000, 99999]` range (well outside alert data); always rejected.
  - **Property** `test_number_guard_all_data_values_pass` — `@settings(max_examples=200)`: LLM answer repeating only `alert.data` Decimal strings always passes.
- [x] Implement `ledger_kit/explainer.py` with `Explanation`, `explain`, `explain_with_meta` (both with the keyword-only `row_columns` parameter, CR-LC-3g), `_AlertFormatter`, the **public** `fill_fallback(template, alert)` (DN-9: apps call it directly via `from ledger_kit.explainer import fill_fallback`, never a private name), `_select_llm_columns(rows, row_columns=None)` (drops `id`/`description`/`iban` even when listed), `_parse_decimal`, `_Tokens`, `_tokenise` (IBAN → dates → source_refs → European numbers → plain numbers, digit lookarounds, each match replaced by a space), `_is_date_column`, `_allowed_decimals`, `_allowed_dates` (every date cell of every whitelisted column), `_passes_number_guard`, `_call_llm` as in design §4a. `_call_llm` imports `openai` inside the `try`, builds `OpenAI(timeout=LLM_TIMEOUT_SECONDS, max_retries=0)`, and sends rows via `to_json(orient="records", default_handler=str)` after mapping every date-holding column through `date.isoformat` (missing values stay `None`; design §4a.5).
- [x] `MockLLMClient` (in `tests/test_explainer.py` or `tests/conftest.py`): `chat` and `completions` are properties, `create` appends its kwargs to `self.calls`.
- [x] Verify: all tests pass, `ruff check` clean.

---

## Task 12 — Streamlit reference page

**Covers**: REQ-UI-01, REQ-UI-02, REQ-UI-03, REQ-UI-04, REQ-UI-05, REQ-UI-06, REQ-UI-07, REQ-UI-08, design §7

- [x] Implement `ledger_kit/ui/__init__.py` (empty).
- [x] Implement `ledger_kit/ui/reference_app.py`:
  - [x] File uploader accepting multiple CSVs (`st.file_uploader`).
  - [x] Per-file caching in `st.session_state` keyed by SHA-256 of file bytes.
  - [x] Pass `IO[bytes]` directly to `parse_csv` (no `TextIOWrapper`).
  - [x] Call `normalise` then `run_all`.
  - [x] Severity summary row at the top (🔴/🟡/🔵 counts).
  - [x] Collapsible quarantine section (only shown when quarantine list is non-empty).
  - [x] Alert cards: `st.expander` per alert, severity badge, title, detector name, source refs.
  - [x] For each source ref: display the matching ledger row with `pandas.Styler` yellow highlight (`background-color: #fff3cd`).
  - [x] All `amount` values formatted with `format_amount`.
  - [x] Encoding used surfaced as a tooltip/caption on the file summary.
- [x] Verify: `streamlit run ledger_kit/ui/reference_app.py` starts without import errors (manual smoke test; no automated Streamlit tests at this stage).
- [x] Verify: `ruff check` clean.

---

## Task 13 — Sample data files and generator script

**Covers**: REQ-PKG-04 (data directory), structure rule (data/samples only synthetic or public-domain), Finance Rules 5 + 6, REQ-ING-30 to REQ-ING-32 (invoice and supplier samples; CR-LC-3a/3b)

- [x] Create `scripts/generate_samples.py` — a seeded random generator that produces synthetic bank-statement CSVs, invoice files and supplier-master files with PII-safe data (Finance Rule 5 names, test IBANs, tax ids with a wrong control character). Accepts CLI args for dialect, row count, and seed. Used by ledger-core and the zombie-subscriptions / phantom-invoices demo fixtures (`--mode zombie-demo`, `--mode phantom-demo`; the phantom mode is specified in that spec).
- [x] Create `data/samples/README.md` documenting that all files are synthetically generated and listing the generation script.
- [x] Use `scripts/generate_samples.py` to create:
  - [x] `data/samples/bank_statement_sample.csv` — 10 rows, plain dialect, mix of debits and credits; includes an `iban` column on at least 3 rows (CR-LC-3c).
  - [x] `data/samples/bank_statement_sample_es.csv` — 10 rows, European dialect (semicolon, comma-decimal, DD/MM/YYYY).
  - [x] `data/samples/invoice_sample.csv` — 5 rows, plain format, **the Invoice schema of REQ-ING-30** (including one row without `due_date` and one with `surcharge_amount` and `withholding_amount`; CR-LC-3a).
  - [x] `data/samples/invoice_sample.json` — the same 5 invoices as a JSON array (amounts as strings and as numbers).
  - [x] `data/samples/suppliers_sample.csv` — 3 rows (`supplier_name,tax_id,iban`), one with an empty `iban` (CR-LC-3b).
- [x] Update `.gitignore` to exclude `data/real/` and loose `*.csv` / `*.json` / `*.pdf` outside `data/samples/`.
- [x] Identifier rules (Finance Rule 5, CR-LC-3h): every IBAN in the samples is mod-97 valid with deliberately wrong Spanish national check digits (e.g. `ES88 2100 0418 5602 0005 1332`); every tax id has a wrong control character, one different per supplier (e.g. `B00000001`, `00000001T`).
- [x] Verify: `parse_csv`, `parse_invoice` and `parse_suppliers` successfully ingest all five sample files with zero quarantine, `normalise` accepts each result, and the `iban` values read from the bank sample equal the file text.

---

## Task 14 — Final integration check

**Covers**: REQ-TST-06, REQ-TST-07, REQ-TST-08, all requirements end-to-end

- [ ] Run the full test suite: `pytest --cov=ledger_kit --cov-fail-under=80`.
- [x] Confirm all three test tiers are present for each module (ingestion, detectors, explainer, money, anonymise).
- [ ] Confirm `ruff check .` and `ruff format --check .` pass with zero warnings.
- [x] Confirm all Hypothesis property tests are decorated with `@settings(max_examples=200)`.
- [x] Confirm every "no invention" property test compares `Alert.source_refs` with `loaded_source_refs(ledger, context)` (the union of all loaded inputs), not with the ledger alone (CR-LC-3d, REQ-TST-10).
- [x] Confirm no test uses `datetime.now()` or `date.today()` directly; any time-sensitive test uses fixed literal dates.
- [x] Confirm no test fixture contains real personal data (names, IBANs, phone numbers outside Finance Rule 5 placeholders).
- [ ] Fix any coverage gaps or lint issues found.
