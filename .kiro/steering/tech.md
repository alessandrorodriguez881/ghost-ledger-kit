# Ghost Ledger Kit — Tech Stack

## Language & runtime
- **Python 3.11** — minimum version; f-string improvements and `tomllib` in stdlib are assumed.
- Use `pyproject.toml` (PEP 517/518) for all package metadata; no `setup.py`.
- Virtual environments managed with `venv`; dependencies pinned in `requirements.txt` (exact versions, no open ranges).

## Core libraries

| Purpose | Library | Notes |
|---|---|---|
| Data wrangling | **pandas ≥ 2.0** | Primary in-memory ledger format is `pd.DataFrame`. Use `pd.ArrowDtype` where applicable. |
| UI | **Streamlit ≥ 1.35** | Each app has its own `app.py` entry point. No shared Streamlit state between apps. |
| LLM calls | **openai** (optional extra `llm`, exact pin; or any OpenAI-compatible SDK) | Only used in the explanation layer. Imported lazily inside the guarded call in `explainer.py`; without it the fallback template is used. |
| Testing | **pytest ≥ 8.0** + **Hypothesis ≥ 6.100** | See `testing.md` for strategy. |
| CSV parsing | stdlib `csv` + pandas | No third-party CSV parsers needed. |
| Invoice parsing | stdlib `csv` + stdlib `json` + **defusedxml** (exact pin) | CSV and JSON invoice formats (e.g. FATURA annotations) and Facturae 3.2 / 3.2.1 / 3.2.2 XML. Only used in the ingestion layer. No PDF parsing. |
| XML safety | **defusedxml** (exact pin, `0.7.1`) | `facturae_reader.py` parses untrusted XML only through `defusedxml.ElementTree` with `forbid_dtd=True`; no other module imports an XML parser. |
| Bank statements | stdlib only | Norma 43 (AEB CSB 43) is fixed-width text read by `norma43_reader.py`; the content sniffer picks CSV or Norma 43. |
| Public data (INE CPI) | stdlib only (`urllib.request`, `json`, `decimal`) | The INE JSON API is called only by `scripts/fetch_ine_cpi.py`, run by the developer, never at run time, in tests or in CI. It writes `data/public/ine_cpi_ipc290751.json`; `ledger_kit/public_data/ine_cpi.py` reads and validates that file. Index values are `Decimal` built from the JSON text (`parse_float=Decimal`), never `float`. |
| Typing | **pydantic ≥ 2.0** | `Transaction` and `Alert` models are Pydantic models for validation and serialisation. |
| Linting / formatting | **ruff** | Single tool for lint + format; config in `pyproject.toml`. |

## Canonical data models

### Transaction
```python
class Transaction(BaseModel):
    id: str                  # UUID assigned at ingestion
    date: date
    amount: Decimal          # always positive; direction indicated by `flow`
    flow: Literal["debit", "credit"]
    currency: str            # ISO 4217, e.g. "EUR"
    counterparty: str
    description: str
    source_file: str         # original filename
    source_row: int          # CSV: 0-based index of the data row (internal key, never shown as a line); Norma 43: 1-based line of the record 22; Facturae: 1-based position of the invoice (DN-RF-01)
    source_ref: str          # f"{source_file}:{source_row}" (internal key)
    source_line: int | None = None  # 1-based line of the file where the record starts, header = line 1, as a text editor numbers lines; Norma 43: the line of the record 22; Facturae and JSON: None (a position, not a line). What the person reads in a chip or a table (REQ-LN-01)
    tags: list[str] = []
```

### Alert
```python
class Alert(BaseModel):
    id: str                  # sha256 of canonical JSON of detector + sorted source_refs + data, unless given
    detector: str            # name of the detector function that raised it
    severity: Literal["info", "warning", "critical"]
    title: str
    source_refs: list[str]   # one or more Transaction.source_ref values
    data: dict               # detector-specific structured payload
    explanation: str = ""    # populated by the explanation layer, never by detectors
```

## Arithmetic rules
- All monetary arithmetic uses `decimal.Decimal` with `ROUND_HALF_UP` and two decimal places.
- Never use `float` for amounts. Pandas columns that hold amounts use `object` dtype backed by `Decimal`, or convert to `Decimal` immediately after reading from CSV.
- The same holds for Norma 43 (implied-decimal digit fields) and Facturae (decimal text): amounts are built with `Decimal` from text, never through `float`.
- See `finance-rules.md` for the complete set of numerical and display rules.

## LLM integration constraints
- The explanation layer must call the LLM with a **system prompt** that includes the phrase: *"You must not invent any number, date, name, or amount. Every figure you mention must appear verbatim either in the source rows provided or in the structured fields of the alert (such as yearly_cost). Do not derive, round, or estimate any figure not explicitly present in those inputs."*
- The LLM is called with `temperature=0` to maximise determinism.
- The result is an `Explanation(text, source, rejected_numbers)`. `source` is `"llm"` or `"fallback"`; a rejected answer never becomes `text` (the offending tokens are kept in `rejected_numbers`). The optional field `raw_answer` (excluded from comparison and `repr`) keeps the model's text as received so the live-guard panel can show it next to the verdict; `explain_with_meta(..., question=...)` appends a user question to the user message only and never changes the system prompt or the guard.
- A single attempt per call: `LLM_MAX_RETRIES = 1`, `LLM_TIMEOUT_SECONDS = 10` (Streamlit renders synchronously). The optional environment variable `LEDGER_KIT_LLM_TIMEOUT` overrides the 10 seconds with a whole number from `LLM_TIMEOUT_MIN_SECONDS = 1` to `LLM_TIMEOUT_MAX_SECONDS = 120`; any other value, or none, falls back to 10 without an error (`llm_timeout_seconds()` in `explainer.py`). There is no back-off loop. The auto-created `openai.OpenAI` client uses `max_retries=0` so the SDK does not retry on top of this. Apps cache explanations by `(alert.id, client_mode)`.
- Any error, timeout, missing key/package or number-guard rejection returns the filled fallback template; the exception never propagates.

## Configuration
- App-level configuration (thresholds, currency, locale) lives in `config.toml` at the app root.
- Secrets (API keys) are loaded from environment variables only; never committed to source.
- Optional LLM environment variables: `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `LEDGER_KIT_LLM_MODEL`, `LEDGER_KIT_LLM_TIMEOUT` (see `.env.example` and `docs/live-guard.md`).
- Use `python-dotenv` for local development `.env` files.

## Code style
- All public functions and classes have type annotations and a one-line docstring.
- Detectors are pure functions with no side effects (no I/O, no global state mutations).
- Maximum line length: 100 characters (configured in `ruff`).
