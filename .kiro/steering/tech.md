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
| LLM calls | **openai ≥ 1.0** (or any OpenAI-compatible SDK) | Only used in the explanation layer. Calls are isolated in `explainer.py` modules. |
| Testing | **pytest ≥ 8.0** + **Hypothesis ≥ 6.100** | See `testing.md` for strategy. |
| CSV parsing | stdlib `csv` + pandas | No third-party CSV parsers needed. |
| Invoice parsing | stdlib `csv` + stdlib `json` | CSV and JSON invoice formats (e.g. FATURA annotations). Only used in the ingestion layer. No PDF parsing. |
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
    source_row: int          # 0-based row index in source file
    source_ref: str          # f"{source_file}:{source_row}"
    tags: list[str] = []
```

### Alert
```python
class Alert(BaseModel):
    id: str                  # UUID assigned at detection time
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
- See `finance-rules.md` for the complete set of numerical and display rules.

## LLM integration constraints
- The explanation layer must call the LLM with a **system prompt** that includes the phrase: *"You must not invent any number, date, name, or amount. Every figure you mention must appear verbatim either in the source rows provided or in the structured fields of the alert (such as yearly_cost). Do not derive, round, or estimate any figure not explicitly present in those inputs."*
- The LLM is called with `temperature=0` to maximise determinism.
- The raw LLM response is stored alongside the explanation for auditability.
- LLM calls are wrapped in a retry decorator (max 3 attempts, exponential back-off) and must time out after 30 s.

## Configuration
- App-level configuration (thresholds, currency, locale) lives in `config.toml` at the app root.
- Secrets (API keys) are loaded from environment variables only; never committed to source.
- Use `python-dotenv` for local development `.env` files.

## Code style
- All public functions and classes have type annotations and a one-line docstring.
- Detectors are pure functions with no side effects (no I/O, no global state mutations).
- Maximum line length: 100 characters (configured in `ruff`).
