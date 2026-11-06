# ledger-core — Requirements

## Overview

`ledger-core` is the shared template layer of Ghost Ledger Kit. It provides three things:

1. **An ingestion layer** that parses bank-statement CSVs and invoice files (CSV/JSON) into a canonical, normalised ledger.
2. **A detector interface and registry** that allows pure-function detectors to be discovered automatically and run against the ledger.
3. **A minimal Streamlit reference page** that runs all registered detectors and displays resulting alerts with their cited source rows highlighted.

Any app built on the template (e.g. `zombie_subscriptions`, `phantom_invoices`) inherits these three components and does not re-implement them.

---

## Requirements

### 1 — Ingestion layer

#### 1.1 Bank-statement CSV parsing

- **REQ-ING-01** The CSV reader (`ledger_kit/ingestion/csv_reader.py`) must accept a file path or file-like object and return `list[Transaction]`.
- **REQ-ING-02** The reader must parse the following mandatory columns: `date`, `amount`, `currency`, `counterparty`, `description`. Additional columns are silently ignored.
- **REQ-ING-03** `amount` must be stored as `decimal.Decimal`, never `float`. Columns read via pandas must be converted to `Decimal` immediately after reading.
- **REQ-ING-04** `date` must be parsed to `datetime.date`, not a string or `datetime.datetime`.
- **REQ-ING-05** Rows with a missing or unparseable value in any mandatory column must be **quarantined** (collected into a separate `list[dict]` returned alongside the valid rows) and never silently coerced.
- **REQ-ING-06** An empty file must return an empty valid list and an empty quarantine list without raising.

#### 1.1a CSV dialect and format detection

Spanish bank exports and similar European sources use a distinct CSV dialect that differs from plain (Anglo-American) CSVs in three ways: semicolon field separators instead of commas, amounts written with a full-stop thousands separator and a comma decimal separator (e.g. `1.234,56` and `-12,50`), and dates in `DD/MM/YYYY` format instead of `YYYY-MM-DD`. The reader must handle both dialects reliably.

- **REQ-ING-17** The CSV reader must support two named dialects: `"plain"` (comma separator, dot decimal, ISO date `YYYY-MM-DD`) and `"european"` (semicolon separator, comma decimal with optional dot thousands, date `DD/MM/YYYY`).
- **REQ-ING-18** The caller may pass an explicit `dialect: Literal["plain", "european"]` parameter to the reader. When supplied, that dialect is used without further inspection.
- **REQ-ING-19** When no dialect is specified, the reader must attempt **auto-detection** by inspecting the first non-empty line of the file (sniffing the delimiter and checking for a comma decimal pattern in the amount column). Auto-detection is performed once per file before any row is parsed.
- **REQ-ING-20** Auto-detection must follow a strict decision rule with no ambiguity tolerance:
  - If the delimiter is unambiguously `;`, classify as `"european"`.
  - If the delimiter is unambiguously `,` and no amount cell contains a comma decimal pattern, classify as `"plain"`.
  - In any other case (mixed signals, cannot determine, delimiter is ambiguous) the **entire file** must be quarantined with reason `"ambiguous_dialect"`. No rows from that file are emitted as valid transactions.
- **REQ-ING-21** A quarantined-file record for `"ambiguous_dialect"` must include: the filename, the reason string `"ambiguous_dialect"`, and the first line that triggered ambiguity, so the user can identify and fix the source file.
- **REQ-ING-22** European-format amount strings must be parsed by first stripping the thousands separator (`.`) then replacing the decimal separator (`,`) with `.` before converting to `Decimal`. A string that contains both `,` and `.` but does not match either the plain or European pattern must be quarantined at row level with reason `"unparseable_amount"`.
- **REQ-ING-23** Signed amounts (negative values indicating debits) must be accepted in both dialects. A leading minus sign is valid for both `"-12,50"` (European) and `"-12.50"` (plain).

#### 1.2 Invoice parsing

- **REQ-ING-07** The invoice reader (`ledger_kit/ingestion/invoice_reader.py`) must support two formats: delimited CSV and JSON (FATURA-style flat arrays).
- **REQ-ING-08** For JSON invoices, amounts stored as strings (e.g. `"1234.56"`) must be converted to `Decimal`; amounts already numeric must also be converted to `Decimal`.
- **REQ-ING-09** The same quarantine semantics as REQ-ING-05 apply to invoice parsing.

#### 1.3 Normalisation

- **REQ-ING-10** The normaliser (`ledger_kit/ingestion/normaliser.py`) must accept multiple source lists of `Transaction` objects (from different files) and merge them into a single `pd.DataFrame` with the canonical schema.
- **REQ-ING-11** Each `Transaction` must carry a `source_ref` assigned as `"{source_file}:{source_row}"` where `source_row` is the 0-based row index within the originating file.
- **REQ-ING-12** The normaliser must validate that every required field is present and non-null after merging; rows failing validation are quarantined and excluded from the returned DataFrame.
- **REQ-ING-13** The canonical DataFrame schema is:

  | Column | dtype |
  |---|---|
  | `id` | `str` (UUID) |
  | `date` | `object` (`datetime.date`) |
  | `amount` | `object` (`Decimal`) |
  | `flow` | `str` (`"debit"` or `"credit"`) |
  | `currency` | `str` (ISO 4217) |
  | `counterparty` | `str` |
  | `description` | `str` |
  | `iban` | `str` (optional, may be `None`) |
  | `source_file` | `str` |
  | `source_row` | `int` |
  | `source_ref` | `str` |
  | `tags` | `object` (`list[str]`) |

- **REQ-ING-14** `iban` is an optional field; its absence must not trigger quarantine. When present it must be stored verbatim (no reformatting).

#### 1.4 Signed-amount normalisation

Bank-statement CSV files represent transaction direction via sign: negative amounts are debits, positive amounts are credits. The canonical `Transaction` model stores `amount` as always positive and encodes direction in `flow`.

- **REQ-ING-24** When a bank CSV row carries a negative amount, the reader must store `abs(amount)` in `Transaction.amount` and set `Transaction.flow = "debit"`.
- **REQ-ING-25** When a bank CSV row carries a positive amount, the reader must store the amount unchanged in `Transaction.amount` and set `Transaction.flow = "credit"`.
- **REQ-ING-26** A zero amount is valid; it must be stored as `Decimal("0.00")` with `flow = "credit"` (sign-neutral default).

#### 1.5 Round-trip correctness (property-based tests)

- **REQ-ING-15** *(revised)* For any `Decimal` amount with exactly two decimal places in the range `[-1 000 000, 1 000 000]`, parsing and normalising must:
  - Preserve the absolute value exactly (no rounding or truncation, since the value already has exactly two decimal places).
  - Map the sign to `flow` correctly: negative → `"debit"`, positive or zero → `"credit"`.
  - When writing the normalised transaction back to a plain CSV (using the signed convention), reproduce the original signed value exactly.
- **REQ-ING-16** For any valid `datetime.date` in the range [1900-01-01, 2100-12-31], the date must survive a write-to-CSV and read-back cycle with no change.
- **REQ-ING-27** For any amount string formatted in European style (e.g. `"1.234,56"`, `"-0,01"`, `"999.999,99"`) with exactly two decimal places, parsing via the European-dialect amount parser must return the exact same `Decimal` value as parsing the equivalent plain string. This property must be covered by a Hypothesis test with `max_examples=200`.

---

### 2 — Detector interface

#### 2.1 Protocol and base types

- **REQ-DET-01** A detector is a callable (function or callable class instance) with the exact signature:

  ```python
  def detect_*(ledger: pd.DataFrame, context: Mapping[str, Any]) -> list[Alert]:
  ```

  `context` is a read-only `types.MappingProxyType` supplied by the registry runner. Detectors must never mutate it.

- **REQ-DET-02** Detectors must be pure functions: no I/O, no mutation of the input DataFrame, no mutation of `context`, no global state side-effects.
- **REQ-DET-03** Every `Alert` emitted must include:
  - `detector`: the detector's registered name (string).
  - `severity`: one of `"info"`, `"warning"`, `"critical"`.
  - `title`: a short human-readable summary.
  - `source_refs`: a non-empty list of `source_ref` strings, each matching a row in the input ledger.
  - `data`: a dict with at least one key carrying detector-specific structured payload.
- **REQ-DET-04** `Alert.source_refs` must only contain values that exist in the input ledger's `source_ref` column. A detector must never invent a `source_ref`.
- **REQ-DET-05** When the input ledger is an empty DataFrame, every detector must return `[]` without raising.
- **REQ-DET-06** All numeric thresholds used by a detector must be module-level named constants (`UPPER_SNAKE_CASE`) with a docstring comment explaining their business meaning.

#### 2.2 `DetectorResult` helper type

- **REQ-DET-07** `ledger_kit/detectors/base.py` must export a `DetectorResult` named tuple or dataclass suitable for wrapping the `(detector_name, alerts)` pair returned by the registry runner.

---

### 2a — Alert model: deterministic id (CR-LC-1b)

- **REQ-MOD-01** When no `id` value is provided to `Alert`, the model must compute a **deterministic id** as the hex sha256 of the canonical JSON of `{"detector": ..., "source_refs": sorted(...), "data": ...}` (keys sorted, compact separators). This ensures the same alert data always produces the same `id` across process restarts and Streamlit reruns, enabling stable explanation caching.
- **REQ-MOD-02** When an explicit `id` is passed to `Alert`, it is used as-is (backward-compatible). The deterministic default applies only when `id` is absent or empty.
- **REQ-MOD-03** The `test_alert_deterministic_id` test must verify that two `Alert` instances constructed with identical `detector`, `source_refs`, and `data` fields (and no explicit `id`) produce the same `id`.
- **REQ-MOD-04** The `test_alert_explicit_id_preserved` test must verify that passing `id="custom-id"` returns that exact value without hashing.

### 3 — Detector registry

- **REQ-REG-01** The registry (`ledger_kit/detectors/__init__.py` or a dedicated `registry.py`) must expose a `register(name: str)` decorator that marks a function as a detector and stores it under the given name. The `name` must follow the pattern `<namespace>.<detector>` where both parts are non-empty lowercase `snake_case`; otherwise `register` raises `ValueError` at decoration time.
- **REQ-REG-02** The registry must expose an `auto_discover(package: str)` function that imports all modules in the given package path and thereby triggers `@register` decorators, requiring no manual registration call.
- **REQ-REG-03** The registry must expose a `run_all(ledger: pd.DataFrame, *, namespace: str | None = None, context: Mapping[str, Any] | None = None) -> list[DetectorResult]` function that runs registered detectors and collects results. When `namespace` is given, only detectors whose registered name starts with `namespace + "."` are run. `context` is wrapped in `types.MappingProxyType` before being passed to each detector; when `None`, an empty `MappingProxyType({})` is passed.
- **REQ-REG-04** If a detector raises an unhandled exception, `run_all` must catch it, log a warning, and continue running the remaining detectors. The failed detector's result must be represented as an empty alert list (not propagated as an exception).
- **REQ-REG-05** Registering two detectors under the same name must raise a `ValueError` at import time.
- **REQ-REG-06** The registry must be importable without any app-level dependencies.
- **REQ-REG-07** `registered_names(namespace: str | None = None) -> list[str]` must return the names of all registered detectors in insertion order. When `namespace` is given, only names starting with `namespace + "."` are returned.

---

### 4a — Explanation layer (`ledger_kit/explainer.py`)

- **REQ-EXP-01** `ledger_kit/explainer.py` must export two public functions:

  ```python
  def explain(
      alert: Alert,
      rows: pd.DataFrame,
      *,
      fallback_template: str,
      client=None,          # injectable OpenAI-compatible client; None = auto-create
  ) -> str:
      """Return the guarded explanation text (delegates to explain_with_meta)."""

  def explain_with_meta(
      alert: Alert,
      rows: pd.DataFrame,
      *,
      fallback_template: str,
      client=None,
  ) -> Explanation:
      """Return an Explanation(text, source, rejected_numbers)."""
  ```

  `rows` is the slice of the ledger containing exactly the rows referenced by `alert.source_refs`.
  `Explanation` is a frozen dataclass:
  ```python
  @dataclass(frozen=True)
  class Explanation:
      text: str
      source: Literal["llm", "fallback"]
      rejected_numbers: tuple[str, ...]
  ```

- **REQ-EXP-02** When `OPENAI_API_KEY` is absent/empty **and** no `client` is injected, both functions return the filled fallback immediately. No network call is made. `source="fallback"`, `rejected_numbers=()`.
- **REQ-EXP-03** Fallback template formatting uses a custom `string.Formatter` subclass (`_AlertFormatter`). Two placeholder types are supported:
  - `{key:money}` — `alert.data[key]` formatted with `format_amount`. This is the correct way to format monetary values; a plain `{key}` for a Decimal value inserts it as-is (e.g. `"12.99"`), which is intentional for non-display use.
  - `{key}` — `alert.data[key]` as a plain string.
  - `{source_refs}` — special placeholder replaced with the comma-joined `alert.source_refs`.
  Unknown placeholders are left unchanged.
- **REQ-EXP-04** When a client is available (injected or auto-created from `OPENAI_API_KEY`), `explain_with_meta` calls the LLM once (`LLM_MAX_RETRIES = 1`; `LLM_TIMEOUT_SECONDS = 10`). The base URL and model come from `OPENAI_BASE_URL` and `LEDGER_KIT_LLM_MODEL` env vars, defaulting to the standard OpenAI endpoint and `"gpt-4o-mini"`.
- **REQ-EXP-05** The LLM call uses `temperature=0`. On any exception (timeout, API error), `explain_with_meta` returns the fallback. No back-off or retry loop. Apps cache `Explanation` objects by `(alert.id, client_mode)` where `alert.id` is the deterministic sha256 from REQ-MOD-01, ensuring the cache survives Streamlit reruns.
- **REQ-EXP-06** The system prompt must include the Finance Rule 1 phrase verbatim.
- **REQ-EXP-07** The system prompt must instruct the model to cite at least one `source_ref` from `alert.source_refs`.
- **REQ-EXP-08** **Number guard** — Decimal-value comparison, not string comparison:
  1. Extract whole dates (ISO `YYYY-MM-DD` and `DD/MM/YYYY`) from the LLM text; check each parsed `datetime.date` against the `date` fields of the cited rows and date-formatted values in `Alert.data`. Remove matched date strings from the text before step 2. Any unrecognised date triggers the fallback.
  2. Tokenise the remaining text with regexes for European (`1.234,56`) and plain (`1234.56`, `1234`) number forms.
  3. Parse each token to `Decimal` (European: strip `.`, replace `,` with `.`; plain: direct).
  4. Build the allowed `Decimal` set from: `Alert.data` values (parsed), and the `date`, `amount`, `flow`, `currency`, `counterparty`, `source_ref` cells of the cited `rows` only. **Never** `id`, `description`, or full IBAN.
  5. If any token's `Decimal` is not in the allowed set, discard the LLM text and return the fallback with `source="fallback"` and `rejected_numbers=(…token…)`.
  6. A European-formatted `12,99` passes against `Decimal("12.99")` in the allowed set. The integer `3` passes against a row index `03` because both parse to `Decimal("3")`.
- **REQ-EXP-09** On any API error or timeout, `explain_with_meta` returns the fallback, logs the reason, and never propagates the exception.

---

### 4 — Streamlit reference page

- **REQ-UI-01** A reference Streamlit page (`ledger_kit/ui/reference_app.py`) must allow a user to upload one or more CSV files via `st.file_uploader`.
- **REQ-UI-02** On upload, the page must ingest the files through the normalisation pipeline and run all registered detectors via `run_all`.
- **REQ-UI-03** The page must display each alert as an expandable card showing: severity badge, title, detector name, and `source_refs`.
- **REQ-UI-04** For each `source_ref` cited in an alert, the page must display the corresponding row from the ledger DataFrame, highlighted (e.g. with `st.dataframe` row-level styling or a yellow background via `pandas.Styler`).
- **REQ-UI-05** The page must show a summary count of alerts by severity (`info`, `warning`, `critical`) at the top.
- **REQ-UI-06** Monetary amounts displayed in the UI must use European locale formatting as defined in Finance Rule 4 (thousands separator `.`, decimal separator `,`, currency symbol after the amount).
- **REQ-UI-07** If ingestion produces quarantined rows, the page must display a collapsible warning section listing them so the user can identify and fix the source file.
- **REQ-UI-08** The page must be runnable with `streamlit run ledger_kit/ui/reference_app.py` with no app-specific configuration required.

---

### 5 — Money utilities

- **REQ-MON-01** `ledger_kit/utils/money.py` must export `round_to_cents(amount: Decimal) -> Decimal` implementing `ROUND_HALF_UP` to two decimal places, as specified in Finance Rule 3.
- **REQ-MON-02** `ledger_kit/utils/money.py` must export `format_amount(amount: Decimal, currency: str = "EUR") -> str` producing European locale output (e.g. `"1.234,56 EUR"`), as specified in Finance Rule 4.
- **REQ-MON-03** `money.py` is the **only** module permitted to perform monetary arithmetic or formatting. All other modules must call its helpers.

---

### 6 — PII and data safety

- **REQ-PII-01** `ledger_kit/utils/anonymise.py` must export a `scrub(transaction: Transaction) -> Transaction` function that replaces known PII fields (counterparty name, IBAN) with placeholder values before any data is passed to the LLM explanation layer.
- **REQ-PII-02** No real personal data may appear in test fixtures, sample files, or committed source. Fixtures must use names and IBANs conforming to Finance Rule 5.

---

### 7 — Package and configuration

- **REQ-PKG-01** `ledger_kit` must be a proper Python package with `pyproject.toml` (PEP 517/518) and no `setup.py`.
- **REQ-PKG-02** All runtime dependencies must be pinned to exact versions in `requirements.txt`.
- **REQ-PKG-03** `ledger_kit` must not import from any app package (`apps.*`).
- **REQ-PKG-04** Shared default configuration lives in `ledger_kit/defaults.toml`; secrets come from environment variables only.
- **REQ-PKG-05** Linting and formatting are enforced by `ruff`; configuration lives in `pyproject.toml` with `max-line-length = 100`.

---

### 8 — Testing requirements

- **REQ-TST-01** All three test tiers (normal-case, edge-case, property-based) must be provided for the ingestion layer in `tests/ingestion/`.
- **REQ-TST-02** Property-based tests for the normaliser must use Hypothesis and cover at least the round-trip properties REQ-ING-15, REQ-ING-16, and REQ-ING-27.
- **REQ-TST-03** Hypothesis `max_examples` must be set to 200 in CI via `settings(max_examples=200)` on each property test decorator.
- **REQ-TST-04** The shared `tests/conftest.py` must provide the standard fixtures: `empty_ledger`, `single_row_ledger`, `clean_ledger_10`.
- **REQ-TST-05** Tests must not use real wall-clock time; any date-sensitive logic must use `freezegun` or accept explicit date parameters.
- **REQ-TST-06** Coverage across `ledger_kit` must not fall below 80% as enforced by `pytest --cov-fail-under=80`.
- **REQ-TST-07** `ruff check` and `ruff format --check` must pass with zero warnings in CI.
- **REQ-TST-08** The explainer layer must be tested in `tests/test_explainer.py` using an injectable `MockLLMClient` — never against the real API in CI. Required tests:
  - `test_explain_fallback_when_no_api_key` — with `OPENAI_API_KEY` unset and no client injected, returns filled fallback; `source="fallback"`.
  - `test_explain_money_placeholder_formats_amount` — `{yearly_cost:money}` with `"155.88"` → `"155,88 EUR"` in fallback output.
  - `test_explain_plain_placeholder_inserts_as_string` — `{charge_count}` with value `"12"` → `"12"` (not `"12,00 EUR"`).
  - `test_explain_source_refs_placeholder` — `{source_refs}` → comma-joined list.
  - `test_explain_unknown_placeholder_left_as_is` — `{unknown}` not in `alert.data` → left unchanged.
  - `test_build_prompt_includes_source_refs` — the system prompt sent to the mock client contains all values from `alert.source_refs`.
  - `test_build_prompt_includes_no_invention_instruction` — the system prompt contains the Finance Rule 1 phrase verbatim.
  - `test_explain_with_meta_returns_explanation_dataclass` — result is an `Explanation` with `.text`, `.source`, `.rejected_numbers`.
  - `test_explain_with_meta_llm_source_on_success` — valid mock response → `source="llm"`, `rejected_numbers=()`.
  - `test_explain_number_guard_european_format_passes` — mock returns `"12,99 EUR"` when `alert.data` has `"12.99"` → guard passes (both parse to `Decimal("12.99")`).
  - `test_explain_number_guard_date_03_passes_for_row_index_3` — `3` in LLM text passes against row index `3` (both `Decimal("3")`).
  - `test_explain_number_guard_rejects_hallucinated_number` — mock returns response with `"999.99"` not in alert data or rows → `source="fallback"`, `rejected_numbers=("999.99",)` (or equivalent token).
  - `test_explain_number_guard_passes_valid_response` — mock returns response repeating only figures from `alert.data` → `source="llm"`.
  - `test_explain_date_guard_rejects_hallucinated_date` — mock returns a date not in cited rows → fallback.
  - `test_explain_date_guard_passes_row_date` — mock mentions an ISO date matching a row → passes.
  - `test_explain_fallback_on_api_error` — mock raises `RuntimeError` → `source="fallback"`, no exception propagated.
  - `test_explain_only_safe_columns_sent` — the DataFrame passed to the LLM never contains `id` or `description` columns.
  - **Property** `test_number_guard_any_foreign_decimal_triggers_fallback` — `@settings(max_examples=200)`: inject a random Decimal (not in allowed set) into a valid answer → guard always rejects. Use a fixed `alert` and rows; generate foreign values via `st.decimals(min_value=Decimal("10000"), max_value=Decimal("99999"), places=2)`.
  - **Property** `test_number_guard_all_data_values_pass` — `@settings(max_examples=200)`: an LLM answer that only uses Decimal strings from `alert.data` always passes the guard.
