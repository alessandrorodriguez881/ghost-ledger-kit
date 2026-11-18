# ledger-core — Requirements

## Overview

`ledger-core` is the shared template layer of Ghost Ledger Kit. It provides three things:

1. **An ingestion layer** that parses bank-statement CSVs, invoice files (CSV/JSON) and supplier-master files into canonical, normalised ledgers (transactions, invoices, suppliers; CR-LC-3).
2. **A detector interface and registry** that allows pure-function detectors to be discovered automatically and run against the ledger.
3. **A minimal Streamlit reference page** that runs all registered detectors and displays resulting alerts with their cited source rows highlighted.

Any app built on the template (e.g. `zombie_subscriptions`, `phantom_invoices`) inherits these three components and does not re-implement them.

---

## Requirements

### 1 — Ingestion layer

#### 1.1 Bank-statement CSV parsing

- **REQ-ING-01** The CSV reader (`ledger_kit/ingestion/csv_reader.py`) must accept a file path or file-like object and return `list[Transaction]`.
- **REQ-ING-02** The reader must parse the following mandatory columns: `date`, `amount`, `currency`, `counterparty`, `description`. Additional columns are silently ignored, with one exception: the optional `iban` column is read (REQ-ING-29, CR-LC-3c).
- **REQ-ING-03** `amount` must be stored as `decimal.Decimal`, never `float`. Columns read via pandas must be converted to `Decimal` immediately after reading.
- **REQ-ING-04** `date` must be parsed to `datetime.date`, not a string or `datetime.datetime`.
- **REQ-ING-05** Rows with a missing or unparseable value in any mandatory column must be **quarantined** (collected into a separate `list[dict]` returned alongside the valid rows) and never silently coerced.
- **REQ-ING-06** An empty file, or a file containing only whitespace, must return an empty valid list and an empty quarantine list (`([], [])`) without raising. This check happens **before** dialect detection, so an empty file is never quarantined as `"ambiguous_dialect"`.

#### 1.1b Bank-statement IBAN column (CR-LC-3c)

- **REQ-ING-29** The CSV reader must read an optional `iban` column into `Transaction.iban` **verbatim**: no trimming, no case change, no removal of spaces or hyphens. A missing `iban` column, an empty cell, or a whitespace-only cell yields `Transaction.iban = None`; none of them quarantines the row (REQ-ING-14). Before this requirement the column was ignored, so the payment IBAN of a bank transfer could never be checked by a detector.

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
- **REQ-ING-22** European-format amount strings must first be validated against the European pattern (optional leading `-`, digits optionally grouped with `.` in threes, a `,` decimal separator, then digits). Only a string that matches is converted: strip the thousands separator (`.`), replace `,` with `.`, convert to `Decimal`. A string that does not match (e.g. `12.50`, `-12.5`, `1,234.56`, `1,2,3`) must be quarantined at row level with reason `"unparseable_amount"`; it must never be converted by blind character replacement (which would turn `12.50` into `1250`).
- **REQ-ING-23** Signed amounts (negative values indicating debits) must be accepted in both dialects. A leading minus sign is valid for both `"-12,50"` (European) and `"-12.50"` (plain).

#### 1.2 Invoice and supplier-master parsing (revised by CR-LC-3a/3b)

- **REQ-ING-07** *(revised)* The invoice reader (`ledger_kit/ingestion/invoice_reader.py`) must support two formats: delimited CSV and JSON (flat arrays). `parse_invoice` returns `IngestionResult[Invoice]`, i.e. `(list[Invoice], list[dict])`, never `Transaction` objects. `IngestionResult` is generic over the parsed model.
- **REQ-ING-08** *(revised)* For JSON invoices, every amount field (`base_amount`, `vat_rate`, `vat_amount`, `surcharge_amount`, `withholding_amount`, `total`) stored as a string (e.g. `"1234.56"`) must be converted to `Decimal`; values already numeric must also be converted to `Decimal` through their shortest `str` form, never through `float` arithmetic.
- **REQ-ING-09** The same quarantine semantics as REQ-ING-05 apply to invoice parsing.
- **REQ-ING-30** *(CR-LC-3a)* Mandatory invoice columns: `invoice_number`, `supplier_name`, `supplier_tax_id`, `issue_date`, `base_amount`, `vat_rate`, `vat_amount`, `total`, `currency`. Optional columns: `due_date`, `surcharge_amount`, `withholding_amount`, `iban`. A missing or unparseable mandatory value quarantines the row (`missing_field:<name>`, `unparseable_date`, `unparseable_amount`). Invoices use the plain dialect (comma separator, dot decimal, ISO dates); `vat_rate` is a percentage written without a percent sign (`21`, `10`, `4`, `0`); `21%` is quarantined as `unparseable_amount`. A negative value in any amount field is quarantined with `reason="negative_amount"` (rectifying invoices / credit notes are out of scope for the template).
- **REQ-ING-31** *(CR-LC-3a)* Optional-value rules: an empty or missing `surcharge_amount` or `withholding_amount` becomes `Decimal("0")`; an empty or missing `iban` becomes `None`, stored verbatim otherwise (as in REQ-ING-29). An empty or missing `due_date` becomes `issue_date + DEFAULT_PAYMENT_TERM_DAYS` with `DEFAULT_PAYMENT_TERM_DAYS = 30` (the Spanish default payment term), and the reader sets `Invoice.due_date_is_default = True` so the derived date is never mistaken for a source datum (Finance Rule 1). `source_ref` is `"{source_file}:{source_row}"` with a 0-based data-row index, exactly as for transactions (REQ-ING-11).
- **REQ-ING-32** *(CR-LC-3b)* A supplier-master reader (`ledger_kit/ingestion/supplier_reader.py`, `parse_suppliers`) returns `IngestionResult[Supplier]` from a plain-dialect CSV with mandatory columns `supplier_name`, `tax_id` and an optional `iban` column (empty → `None`, otherwise verbatim). Each `Supplier` carries a `source_ref` (`"{source_file}:{source_row}"`, 0-based) like any other input, so alerts can cite master rows. Encoding strategy and quarantine semantics are those of REQ-ING-05/06 and OD-3.

#### 1.2a Mixed-kind normalisation (CR-LC-3a)

- **REQ-ING-33** `normalise()` accepts lists of `Transaction`, lists of `Invoice`, or lists of `Supplier`. One call handles exactly one kind: mixing kinds in a single call raises `ValueError`. The kind is inferred from the first non-empty list; the keyword-only argument `kind: Literal["transaction", "invoice", "supplier"] | None = None` selects the schema when every list is empty (default `"transaction"`). The return type is unchanged: `(DataFrame, list[dict])`.
- **REQ-ING-34** The canonical invoice DataFrame has the columns `invoice_number`, `supplier_name`, `supplier_tax_id`, `issue_date`, `due_date`, `due_date_is_default`, `base_amount`, `vat_rate`, `vat_amount`, `surcharge_amount`, `withholding_amount`, `total`, `iban`, `currency`, `source_file`, `source_row`, `source_ref` (dates as `datetime.date` objects, amounts and `vat_rate` as `Decimal`, `source_row` as `int64`). The canonical supplier DataFrame has `supplier_name`, `tax_id`, `iban`, `source_file`, `source_row`, `source_ref`. Both always carry all their columns, even when empty (extends REQ-ING-28).

#### 1.3 Normalisation

- **REQ-ING-10** *(revised)* The normaliser (`ledger_kit/ingestion/normaliser.py`) must accept multiple source lists of `Transaction`, `Invoice` or `Supplier` objects (from different files, one kind per call, REQ-ING-33) and merge them into a single `pd.DataFrame` with the canonical schema of that kind.
- **REQ-ING-11** Each `Transaction` must carry a `source_ref` assigned as `"{source_file}:{source_row}"` where `source_row` is the 0-based row index within the originating file.
- **REQ-ING-12** The normaliser must validate that every required field is present and non-null after merging; rows failing validation are quarantined and excluded from the returned DataFrame.
- **REQ-ING-13** The canonical **transaction** DataFrame schema is (the invoice and supplier schemas are in REQ-ING-34):

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

- **REQ-ING-14** `iban` is an optional field; its absence must not trigger quarantine. When present it must be stored verbatim (no reformatting). For bank statements it is populated from the optional `iban` column (REQ-ING-29).
- **REQ-ING-28** `normalise` must always build its DataFrame with the canonical column list of its kind (REQ-ING-13 for transactions, REQ-ING-34 for invoices and suppliers), so that zero input rows, or a run where every row was quarantined, returns an **empty DataFrame that still has all canonical columns** (never a column-less frame that raises `KeyError` on `ledger["source_ref"]`).

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
  - `source_refs`: a non-empty list of `source_ref` strings, each matching a row of a **loaded input** (REQ-DET-04).
  - `data`: a dict with at least one key carrying detector-specific structured payload.
- **REQ-DET-04** *(revised, CR-LC-3d)* `Alert.source_refs` may point to **any loaded input**: a row of the ledger, or a row of any other input handed to the detector through `context` (invoices, supplier-master rows, bank payments, …). The set of **loaded inputs** is the union of the `source_ref` values of the ledger and of every DataFrame in `context` that has a `source_ref` column. A detector must never invent a `source_ref`: every cited value must be in that union.
- **REQ-DET-05** *(revised, CR-LC-3f)* When the input ledger is an empty DataFrame (including `pd.DataFrame()` with no columns), every detector must return `[]` without raising. **Exception:** a detector that is documented to read `context` may return alerts when the ledger is empty, if the facts come from the context inputs (example: bank payments with no invoice at all). Such a detector must still return `[]` when the ledger **and** every context input it reads are empty, and must never raise.
- **REQ-DET-06** All numeric thresholds used by a detector must be module-level named constants (`UPPER_SNAKE_CASE`) with a docstring comment explaining their business meaning.

#### 2.2 `DetectorResult` helper type

- **REQ-DET-07** `ledger_kit/detectors/base.py` must export a `DetectorResult` named tuple or dataclass suitable for wrapping the `(detector_name, alerts)` pair returned by the registry runner.
- **REQ-DET-08** *(CR-LC-3d)* `ledger_kit/detectors/base.py` must export `loaded_source_refs(ledger: pd.DataFrame, context: Mapping[str, Any]) -> frozenset[str]` returning the union defined in REQ-DET-04. It tolerates a ledger or context DataFrame without a `source_ref` column (contributes nothing) and non-DataFrame context values (ignored). Tests and apps use it instead of re-implementing the union.
- **REQ-DET-09** *(CR-LC-3g)* Every number, date or amount that an explanation or a fallback template may mention must be stored as a named field of `Alert.data` (days apart, rates, counts, expected and stated amounts included), so the number guard can allow it (Finance Rule 1). An IBAN is stored in `Alert.data` only in masked form (REQ-PII-03), never in full.

---

### 2a — Alert model: deterministic id (CR-LC-1b)

- **REQ-MOD-01** When no `id` value is provided to `Alert`, the model must compute a **deterministic id** as the hex sha256 of the canonical JSON of `{"detector": ..., "source_refs": sorted(...), "data": ...}` (keys sorted, compact separators). This ensures the same alert data always produces the same `id` across process restarts and Streamlit reruns, enabling stable explanation caching.
- **REQ-MOD-02** When an explicit `id` is passed to `Alert`, it is used as-is (backward-compatible). The deterministic default applies only when `id` is absent or empty.
- **REQ-MOD-03** The `test_alert_deterministic_id` test must verify that two `Alert` instances constructed with identical `detector`, `source_refs`, and `data` fields (and no explicit `id`) produce the same `id`.
- **REQ-MOD-04** The `test_alert_explicit_id_preserved` test must verify that passing `id="custom-id"` returns that exact value without hashing.
- **REQ-MOD-05** Computing the deterministic id must never raise on non-JSON-native values in `Alert.data`. `Decimal` and `date` values are serialised with `json.dumps(..., default=str)`; numpy scalars are first converted to the equivalent Python type. (Otherwise a `TypeError` while building the id makes `run_all` drop every alert of that detector.)
- **REQ-MOD-06** Constructing an `Alert` without `source_refs` (or `detector`/`data`) must raise pydantic `ValidationError`, never `KeyError`.
- **REQ-MOD-07** Tests: `test_alert_id_with_decimal_and_date_data` (Decimal and date values in `data` give a 64-char hex id and the same id on a second construction), `test_alert_id_numpy_scalar_matches_python_value` (`numpy.int64(3)` and `3` in `data` give the same id), `test_alert_missing_source_refs_raises_validation_error`.
- **REQ-MOD-08** *(CR-LC-3a)* `ledger_kit/models.py` defines a frozen Pydantic model `Invoice` with the fields: `invoice_number: str`, `supplier_name: str`, `supplier_tax_id: str`, `issue_date: date`, `due_date: date` (always populated, REQ-ING-31), `due_date_is_default: bool = False`, `base_amount: Decimal`, `vat_rate: Decimal` (a percentage: `Decimal("21")` means 21 %), `vat_amount: Decimal`, `surcharge_amount: Decimal = Decimal("0")` (Spanish *recargo de equivalencia*), `withholding_amount: Decimal = Decimal("0")` (Spanish *IRPF*), `total: Decimal` (the amount payable), `iban: str | None = None` (verbatim), `currency: str`, `source_file: str`, `source_row: int`, `source_ref: str`. Amount fields and `vat_rate` are non-negative (`ValidationError` otherwise). `Invoice` has no `id` field. `Transaction`, `Invoice`, `Supplier` and `Alert` are re-exported from `ledger_kit/__init__.py`.
- **REQ-MOD-09** *(CR-LC-3b)* `ledger_kit/models.py` defines a frozen Pydantic model `Supplier` with `supplier_name: str`, `tax_id: str`, `iban: str | None = None` (verbatim), `source_file: str`, `source_row: int`, `source_ref: str`.
- **REQ-MOD-10** *(CR-LC-3a)* `Invoice` and `Supplier` models never normalise or validate identifiers: tax ids and IBANs are stored exactly as read. Validation of IBAN checksums and tax ids belongs to detectors and tests, not to the models.

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
      row_columns: Sequence[str] | None = None,   # CR-LC-3g; None = default whitelist
  ) -> str:
      """Return the guarded explanation text (delegates to explain_with_meta)."""

  def explain_with_meta(
      alert: Alert,
      rows: pd.DataFrame,
      *,
      fallback_template: str,
      client=None,
      row_columns: Sequence[str] | None = None,
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
- **REQ-EXP-04** When a client is available (injected or auto-created from `OPENAI_API_KEY`), `explain_with_meta` calls the LLM once (`LLM_MAX_RETRIES = 1`; `LLM_TIMEOUT_SECONDS = 10`). The base URL and model come from `OPENAI_BASE_URL` and `LEDGER_KIT_LLM_MODEL` env vars, defaulting to the standard OpenAI endpoint and `"gpt-4o-mini"`. When the client is auto-created it is built with `openai.OpenAI(timeout=LLM_TIMEOUT_SECONDS, max_retries=0)`: the SDK retries twice by default, which would silently multiply `LLM_MAX_RETRIES`. The `import openai` happens inside the guarded call, so a missing package falls back (REQ-EXP-09) instead of raising.
- **REQ-EXP-05** The LLM call uses `temperature=0`. On any exception (timeout, API error), `explain_with_meta` returns the fallback. No back-off or retry loop. Apps cache `Explanation` objects by `(alert.id, client_mode)` where `alert.id` is the deterministic sha256 from REQ-MOD-01, ensuring the cache survives Streamlit reruns.
- **REQ-EXP-06** The system prompt must include the Finance Rule 1 phrase verbatim.
- **REQ-EXP-07** The system prompt must instruct the model to cite at least one `source_ref` from `alert.source_refs`.
- **REQ-EXP-08** **Number guard** — Decimal-value comparison, not string comparison, using **one tokeniser** (`_tokenise`) for both the LLM text and the allowed set (`_allowed_decimals`). The tokeniser applies its patterns in this order and removes each match from the text before the next pattern runs:
  1. IBAN-shaped tokens. Any IBAN-shaped token in the LLM text rejects the answer.
  2. Dates (ISO `YYYY-MM-DD`, then `DD/MM/YYYY`). Each is parsed to `datetime.date` and checked against the `datetime.date` cells of **every whitelisted column** of the cited rows (REQ-EXP-11; for the default whitelist that is the `date` column) and the date values (objects or ISO strings) in `Alert.data`. An unrecognised date, or a date-shaped string that is not a real date, triggers the fallback.
  3. `source_ref` strings (`file:row`) of the alert and the cited rows, matched literally.
  4. European numbers (`1.234,56`, `12,99`).
  5. Plain numbers (`1234.56`, `1234`).

  Number patterns use digit lookarounds, not word boundaries, so numbers glued to letters (`15.99EUR`, `F2026099`) are still extracted. Removing European matches before the plain pass guarantees `12,99` is read as one number, never as `12` and `99`.
  Then:
  6. Parse each token to `Decimal` (European: strip `.`, replace `,` with `.`; plain: direct).
  7. The allowed `Decimal` set is built by running the same tokeniser over `str(value)` for every `Alert.data` value and over every cell of the cited `rows` that is in the whitelist (REQ-EXP-11; default: `amount`, `flow`, `currency`, `counterparty`, `source_ref`; cells holding a `datetime.date` are checked as dates only). **Never** `id`, `description`, or full IBAN. Because dates and cited `source_ref` strings are removed first, **row numbers, file-name digits and date parts are never added to the allowed set.**
  8. If any token's `Decimal` is not in the allowed set, discard the LLM text and return the fallback with `source="fallback"` and `rejected_numbers=(…token…)`.
  9. A European-formatted `12,99` passes against `Decimal("12.99")` in the allowed set. A made-up `3 EUR` is **rejected** even when row 3 is cited (`bank.csv:3`), unless `3` is also a value in `Alert.data` or a cited cell.
- **REQ-EXP-09** On any API error or timeout, `explain_with_meta` returns the fallback, logs the reason, and never propagates the exception.
- **REQ-EXP-10** *(revised)* The source rows are sent to the LLM as `to_json(orient="records", default_handler=str)` after **every whitelisted column that holds `datetime.date` cells** (for the default whitelist: `date`; for App 2: `issue_date`, `due_date`) has been converted to ISO strings with `date.isoformat` (missing values stay `None`). Dates therefore arrive as `2026-01-15` — not as epoch milliseconds and not as `2026-01-15T00:00:00.000`, which is what pandas `date_format="iso"` produces for `datetime.date` cells. `Decimal` cells are covered by `default_handler=str`.
- **REQ-EXP-11** *(CR-LC-3g)* The row-column whitelist is a parameter. `row_columns=None` (the default) uses the original whitelist `("date", "amount", "flow", "currency", "counterparty", "source_ref")`, so existing callers (App 1) are unchanged. When `row_columns` is given, **only** those columns (those present in `rows`, in the given order) are sent to the LLM and used to build the allowed sets. A caller must never include `id`, `description`, `iban` or a tax-id column in `row_columns`; the explainer does not enforce this, but `explain_with_meta` always drops any column named `id`, `description` or `iban` even when listed (defence in depth). App 2 passes `invoice_number, supplier_name, issue_date, due_date, base_amount, vat_rate, vat_amount, surcharge_amount, withholding_amount, total, currency, source_ref`.

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
- **REQ-MON-04** *(CR-LC-3e)* `money.py` exports `percent_of(base: Decimal, rate: Decimal) -> Decimal` = `round_to_cents(base × rate / 100)` (`ROUND_HALF_UP`), where `rate` is a percentage (`Decimal("21")` means 21 %). Example: `percent_of(Decimal("100.00"), Decimal("21"))` is `Decimal("21.00")`; `percent_of(Decimal("0.50"), Decimal("21"))` is `Decimal("0.11")` (0.105 rounds half-up).
- **REQ-MON-05** *(CR-LC-3e)* `money.py` exports `within_tolerance(a: Decimal, b: Decimal, tol: Decimal) -> bool` = `abs(a - b) <= tol` (inclusive: a difference of exactly `tol` is within tolerance). A negative `tol` raises `ValueError`.
- **REQ-MON-06** *(CR-LC-3e)* `money.py` exports `net_total(additions: Iterable[Decimal], subtractions: Iterable[Decimal] = ()) -> Decimal` = `sum(additions) - sum(subtractions)` without rounding (inputs are already in cents). It exists so that a detector checking `total = base + VAT + surcharge − withholding` performs no arithmetic itself. *(Helper added beyond the two named in CR-LC-3e; see phantom-invoices OD-PI-01.)*

---

### 6 — PII and data safety

- **REQ-PII-01** `ledger_kit/utils/anonymise.py` must export a `scrub(transaction: Transaction) -> Transaction` function that replaces known PII fields (counterparty name, IBAN) with placeholder values before any data is passed to the LLM explanation layer.
- **REQ-PII-02** No real personal data may appear in test fixtures, sample files, or committed source. Fixtures must use names, IBANs and tax ids conforming to Finance Rule 5 (revised by CR-LC-3h).
- **REQ-PII-03** *(CR-LC-3g)* `ledger_kit/utils/anonymise.py` must export `mask_iban(iban: str) -> str`: it removes all whitespace (including non-breaking spaces), uppercases, and returns `"****"` followed by the last 4 characters (`"ES88 2100 0418 5602 0005 1332"` → `"****1332"`). A value with 4 or fewer characters after cleaning returns `"****"` only, so the full value is never revealed. The result is never IBAN-shaped, so the number guard does not treat it as an IBAN.
- **REQ-PII-04** *(CR-LC-3g)* An `Alert.data` payload must never contain a full IBAN. Detectors store `mask_iban(...)` output only; the explainer's row whitelist never includes an `iban` column (REQ-EXP-11).

---

### 7 — Package and configuration

- **REQ-PKG-01** `ledger_kit` must be a proper Python package with `pyproject.toml` (PEP 517/518) and no `setup.py`.
- **REQ-PKG-02** All runtime dependencies must be pinned to exact versions in `requirements.txt`.
- **REQ-PKG-03** `ledger_kit` must not import from any app package (`apps.*`).
- **REQ-PKG-04** Shared default configuration lives in `ledger_kit/defaults.toml`; secrets come from environment variables only.
- **REQ-PKG-05** Linting and formatting are enforced by `ruff`; configuration lives in `pyproject.toml` with `max-line-length = 100`.
- **REQ-PKG-06** `pyproject.toml` must set `[tool.pytest.ini_options] pythonpath = ["."]` and `testpaths = ["tests", "apps"]`, so a plain `pytest` from the repo root finds `ledger_kit` and the app tests without an editable install.
- **REQ-PKG-07** `openai` is not a core dependency. It is pinned to an exact version in the optional extra `llm` (`[project.optional-dependencies]`) and in `requirements.txt` under an "optional" comment. `ledger_kit.explainer` imports it lazily inside the guarded call (REQ-EXP-04).

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
  - `test_build_prompt_includes_source_refs` — the system message in `client.calls[0]["messages"]` contains all values from `alert.source_refs`.
  - `test_build_prompt_includes_no_invention_instruction` — that system message contains the Finance Rule 1 phrase verbatim.
  - `test_mock_client_chat_completions_create_resolves` — `MockLLMClient(["x"]).chat.completions.create(model="m")` returns a response and appends its kwargs to `client.calls` (guards against `chat` being a plain method).
  - `test_explain_with_meta_returns_explanation_dataclass` — result is an `Explanation` with `.text`, `.source`, `.rejected_numbers`.
  - `test_explain_with_meta_llm_source_on_success` — valid mock response → `source="llm"`, `rejected_numbers=()`.
  - `test_explain_number_guard_european_format_passes` — mock returns `"12,99 EUR"` when `alert.data` has `"12.99"` → guard passes (both parse to `Decimal("12.99")`); `12,99 EUR` is not split into `12` and `99`.
  - `test_explain_number_guard_european_thousands_passes` — `"1.060,00 EUR"` passes when `alert.data` has `"1060.00"`.
  - `test_explain_number_guard_two_amounts_in_one_sentence_pass` — `"15,99 EUR monthly, 191,88 EUR yearly"` passes when both values are allowed.
  - `test_explain_number_guard_glued_allowed_number_passes` — `"15.99EUR"` passes when `15.99` is allowed.
  - `test_explain_number_guard_rejects_made_up_number_equal_to_row_index` — cited ref `bank.csv:3`, response `"3 EUR ... (bank.csv:3)"`, no value 3 in `alert.data` or cited cells → `source="fallback"`, `rejected_numbers=("3",)`; the same response without the made-up `3 EUR` passes.
  - `test_explain_number_guard_rejects_invented_number_glued_to_letters` — `"invoice F2026099"` (not allowed) → fallback, `"2026099"` in `rejected_numbers`.
  - `test_explain_number_guard_rejects_iban_shaped_token` — response containing `"DE00 0000 0000 0000 0000 00"` → fallback.
  - `test_explain_number_guard_rejects_malformed_date` — response containing `"31/02/2026"` → fallback.
  - `test_explain_number_guard_rejects_hallucinated_number` — mock returns response with `"999.99"` not in alert data or rows → `source="fallback"`, `rejected_numbers=("999.99",)` (or equivalent token).
  - `test_explain_number_guard_passes_valid_response` — mock returns response repeating only figures from `alert.data` → `source="llm"`.
  - `test_explain_date_guard_rejects_hallucinated_date` — mock returns a date not in cited rows → fallback.
  - `test_explain_date_guard_passes_row_date` — mock mentions an ISO date matching a row → passes, and the date's parts (`2026`, `01`, `15`) are not treated as numbers.
  - `test_explain_fallback_on_api_error` — mock raises `RuntimeError` → `source="fallback"`, no exception propagated.
  - `test_explain_openai_import_error_falls_back` — `OPENAI_API_KEY` set, no client injected, `openai` made unimportable (`monkeypatch.setitem(sys.modules, "openai", None)`) → fallback, no exception.
  - `test_explain_openai_client_built_with_no_sdk_retries` — with a fake `openai` module in `sys.modules` whose `OpenAI` records its kwargs: `timeout == LLM_TIMEOUT_SECONDS` and `max_retries == 0`.
  - `test_explain_rows_json_has_iso_dates` — the user message in `client.calls[0]["messages"]` contains `"2026-01-15"` and does not contain `"T00:00"`.
  - `test_explain_only_safe_columns_sent` — the user message in `client.calls[0]["messages"]` contains neither an `id` nor a `description` key for the rows.
  - *(CR-LC-3g)* `test_explain_row_columns_parameter_selects_columns` — with `row_columns=("invoice_number", "total", "source_ref")` the user message contains exactly those keys for the rows and none of the default-whitelist columns that are not listed.
  - *(CR-LC-3g)* `test_explain_default_row_columns_unchanged` — with `row_columns=None` the keys sent are exactly the original whitelist (regression guard for App 1).
  - *(CR-LC-3g)* `test_explain_invoice_date_columns_sent_as_iso_and_guarded` — `issue_date` and `due_date` cells arrive as `2026-01-15` (no `T00:00`); an answer mentioning the cited `due_date` passes, one mentioning an uncited date falls back, and neither date's parts are added to the allowed numbers.
  - *(CR-LC-3g)* `test_explain_iban_column_never_sent_even_if_listed` — `row_columns` containing `iban`, `id` or `description` still sends none of them.
  - *(CR-LC-3g)* `test_explain_masked_iban_in_alert_data_passes_guard` — an answer quoting `****1332` passes when `Alert.data` holds `"****1332"`, and an answer quoting a full IBAN-shaped token is rejected.
  - **Property** `test_number_guard_any_foreign_decimal_triggers_fallback` — `@settings(max_examples=200)`: inject a random Decimal (not in allowed set) into a valid answer → guard always rejects. Use a fixed `alert` and rows; generate foreign values via `st.decimals(min_value=Decimal("10000"), max_value=Decimal("99999"), places=2)`.
  - **Property** `test_number_guard_all_data_values_pass` — `@settings(max_examples=200)`: an LLM answer that only uses Decimal strings from `alert.data` always passes the guard.
- **REQ-TST-09** Registry test isolation. Tests must not call `_clear_registry()` for isolation (it also drops already-imported app detectors, which `auto_discover` cannot re-register). A function-scoped fixture snapshots the registry with `_snapshot_registry()` and restores it with `_restore_registry()`. Hypothesis tests must not use function-scoped fixtures and must not call `@register` inside the `@given` body; their detectors are registered once at module scope in `tests/detectors/test_registry_properties.py`.
- **REQ-TST-10** *(CR-LC-3d)* Detector tests that check "no invention" (Tier 3, `testing.md`) compare `Alert.source_refs` with `loaded_source_refs(ledger, context)` (REQ-DET-08), the union of all loaded inputs, not with the ledger alone. Detectors that read `context` (REQ-DET-05 exception) are additionally tested with an empty ledger and non-empty context inputs.

---

### 9 — Change record: CR-LC-3 (phantom-invoices prerequisites)

CR-LC-3 was raised by the `phantom-invoices` spec (App 2). It changes ledger-core as listed below; nothing else in this spec changed. The matching edits are in `design.md` and `tasks.md`, and in the steering files `finance-rules.md` (Rule 5) and `testing.md` (Tier 3 property and its template, empty-ledger edge case).

| CR-LC-3 item | Requirements touched or added | Design sections | Tasks |
|---|---|---|---|
| a. Invoice model, `parse_invoice` returns invoices, `normalise()` accepts invoices | Overview; REQ-ING-07, 08, 10, 13, 28 revised; REQ-ING-30, 31, 33, 34, REQ-MOD-08, 10 added | §1, §2.1a, §3.3, §3.4, §8.1, §11 | Task 2, 8, 9, 13 |
| b. Supplier master reader | REQ-ING-32, 34; REQ-MOD-09 | §1, §2.1b, §3.3a, §3.4 | Task 2, 8, 9 (supplier sub-items), 13 |
| c. `parse_csv` reads optional `iban` | REQ-ING-02, 14 revised; REQ-ING-29 added | §3.2 | Task 6, 13 |
| d. `source_refs` may point to any loaded input | REQ-DET-03, 04 revised; REQ-DET-08, REQ-TST-10 added | §4.1 | Task 10, 11, 14 |
| e. `percent_of`, `within_tolerance` (+ `net_total`) | REQ-MON-04, 05, 06 added (REQ-MON-03 text unchanged) | §5 | Task 3 |
| f. Empty-ledger exception for context-reading detectors | REQ-DET-05 revised | §4.1 | Task 10 |
| g. Explainer `row_columns`, numbers in `Alert.data`, masked IBANs | REQ-EXP-01, 08, 10 revised; REQ-EXP-11, REQ-DET-09, REQ-PII-03, 04 added; REQ-TST-08 extended | §4a.1, §4a.2, §4a.4, §4a.5, §6 | Task 5, 11a |
| h. Finance Rule 5 (steering) | REQ-PII-02 reworded | — | — |

---

### 10 — Session 32: the source line (REQ-LN-01 onwards)

Approved by the owner on 17 Nov. For a CSV file `source_row` is the 0-based index of the data row, so a person who opens the file finds the record on another line (the GYMPLUS charge of `zombie_demo_statement.csv` is `source_row` 181 and stands on line 183). A citation that points to the wrong line looks like an invented one. The internal key stays as it is; the line of the file is a new field that only the pages read.

- **REQ-LN-01** `Transaction`, `Invoice` and `Supplier` shall have the field `source_line: int | None = None`: the 1-based line of the file where the record starts, the header being line 1, numbered as a text editor numbers lines and as a spreadsheet numbers rows when no cell spans two lines. It defaults to `None`, so every model built without it stays valid.
- **REQ-LN-02** `source_row`, `source_ref`, `Alert.id`, the `source_refs` and the `data` of every alert, every detector, the number guard, the columns sent to the model (`_LLM_ROW_COLUMNS`, `_NEVER_SENT_COLUMNS`), `replay.py` and the files of `data/live_runs` shall not change. `source_line` is not an input of any detector, is not part of any alert and is never sent to a model.
- **REQ-LN-03** Every CSV reader (`parse_csv`, `parse_invoice` for CSV, `parse_suppliers`) shall set `source_line` on every record it returns. A blank line between records shall not shift it, and a quoted cell that spans several lines shall give the line where the record starts, so the next record gets the line after the last line of that cell. The records are read by one shared function, `iter_csv_records` in `csv_reader.py`, that returns the same records as `csv.DictReader`.
  - AE-LN-01 `date,...` header, a record, two blank lines, a record: the records have `source_row` 0 and 1 and `source_line` 2 and 5.
  - AE-LN-02 A record whose description is a quoted cell of two lines, then another record: `source_line` 2 and 4.
  - AE-LN-03 `zombie_demo_statement.csv`: the GYMPLUS charge of 2026-08-09 keeps `source_ref` `zombie_demo_statement.csv:181` and has `source_line` 183; line 183 of the file, read as text, is that charge.
- **REQ-LN-04** *Where* a record comes from a JSON array, `source_line` shall be `None` (an item has a position, not a line).
- **REQ-LN-05** `parse_norma43` shall set `source_line` to the line of the record 22, which is its `source_row` today.
- **REQ-LN-06** `parse_facturae` shall leave `source_line` `None`: an XML invoice has a position, not a line.
- **REQ-LN-07** Every quarantine record of every reader shall carry the key `source_line`: the line where the bad record starts, or `None` for a record about the whole file (undecodable file, ambiguous dialect, unsupported format, invalid JSON or XML, a record 88 check) or about an XML invoice. Norma 43 records that name a record carry its line. Every other key of a quarantine record stays as it is.
- **REQ-LN-08** `normalise()` shall add the column `source_line` right after `source_ref` in `CANONICAL_COLUMNS`, `INVOICE_COLUMNS` and `SUPPLIER_COLUMNS`, as a nullable integer (pandas `Int64`), so a `None` stays empty. A missing `source_line` shall not quarantine a record. The `source_row` column stays `int64`.
- **REQ-LN-09** *Where* a record has no line (REQ-LN-04, REQ-LN-06), every page shall show its position instead of a line (an XML invoice reads `invoice N`), and a CSV ref whose line is not known shall show its raw `source_ref`, never the word `row` next to the internal number. The pages are specified in `app-signatures` (REQ-AS-25 onwards).
- **REQ-LN-10** The tests shall cover: the GYMPLUS charge (AE-LN-03); for each sample CSV of `data/samples` and `data/samples/phantom_demo`, that every record has a `source_line` and that the line of the file at that number is the record (same date and amount); a CSV with a blank line between records and one with a quoted cell that spans two lines; Norma 43 (`source_line` equals `source_row`); Facturae (`None`); and the `source_line` key of the quarantine records. The tests that pin the exact set of keys or columns shall include the new key or column.
- **REQ-LN-11** `.kiro/steering/tech.md` (model `Transaction`) and `.kiro/steering/testing.md` (ingestion tests) shall describe `source_line` next to `source_row` and `source_ref`. The number of files in `.kiro/steering` (6) and of folders in `.kiro/specs` (18) shall not change.
