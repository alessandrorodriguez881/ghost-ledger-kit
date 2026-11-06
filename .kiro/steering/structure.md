# Ghost Ledger Kit — Project Structure

## Top-level layout

```
ghost-ledger-kit/
├── .kiro/
│   └── steering/                   # Kiro steering documents (this directory)
├── ledger_kit/                     # Shared template library (importable package)
│   ├── __init__.py
│   ├── models.py                   # Transaction and Alert Pydantic models
│   ├── ingestion/
│   │   ├── __init__.py
│   │   ├── csv_reader.py           # Bank-statement CSV parser → list[Transaction]
│   │   ├── invoice_reader.py       # Invoice parser (CSV + JSON, e.g. FATURA) → list[Transaction]
│   │   └── normaliser.py           # Merge sources, validate, assign source_ref
│   ├── detectors/
│   │   ├── __init__.py
│   │   └── base.py                 # DetectorResult type, detector registry
│   ├── explainer.py                # LLM explanation layer; only file that calls an LLM
│   └── utils/
│       ├── __init__.py
│       ├── money.py                # Decimal arithmetic helpers, rounding, formatting
│       └── anonymise.py            # PII scrubbing utilities
├── apps/
│   ├── zombie_subscriptions/       # App 1: personal recurring-charge detector
│   │   ├── __init__.py
│   │   ├── detectors/
│   │   │   ├── __init__.py
│   │   │   ├── recurring_charge.py
│   │   │   ├── last_use_gap.py
│   │   │   └── dormant_subscription.py
│   │   ├── tests/
│   │   │   ├── conftest.py
│   │   │   ├── test_zs_recurring_charge.py
│   │   │   ├── test_zs_last_use_gap.py
│   │   │   └── test_zs_dormant_subscription.py
│   │   ├── app.py                  # Streamlit entry point
│   │   ├── config.toml
│   │   └── requirements.txt
│   └── phantom_invoices/           # App 2: SME invoice anomaly detector
│       ├── __init__.py
│       ├── detectors/
│       │   ├── __init__.py
│       │   ├── duplicate_invoice.py
│       │   ├── iban_change.py
│       │   └── vat_error.py
│       ├── tests/
│       │   ├── conftest.py
│       │   ├── test_pi_duplicate_invoice.py
│       │   ├── test_pi_iban_change.py
│       │   └── test_pi_vat_error.py
│       ├── app.py                  # Streamlit entry point
│       ├── config.toml
│       └── requirements.txt
├── tests/                          # Shared library tests
│   ├── conftest.py
│   ├── ingestion/
│   │   ├── test_csv_reader.py
│   │   ├── test_invoice_reader.py
│   │   └── test_normaliser.py
│   ├── test_models.py
│   ├── test_money.py
│   └── test_anonymise.py
├── data/
│   └── samples/                    # Synthetic or public-domain sample files only
│       ├── README.md               # Licence reference for any public-domain files
│       ├── bank_statement_sample.csv
│       └── invoice_sample.csv
├── pyproject.toml
├── README.md
└── .env.example
```

## Naming conventions

| Artefact | Convention | Example |
|---|---|---|
| Modules | `snake_case` | `recurring_charge.py` |
| Classes | `PascalCase` | `RecurringChargeDetector` |
| Functions | `snake_case` | `detect_recurring_charges` |
| Constants | `UPPER_SNAKE_CASE` | `DEFAULT_LOOKBACK_DAYS = 90` |
| Test files | `test_<app_prefix>_<module>.py` | `test_zs_recurring_charge.py` |
| Fixtures | `snake_case`, descriptive | `ledger_with_dormant_sub` |

### App prefixes for test modules

To prevent pytest collection collisions, test files inside each app's `tests/` folder are prefixed with the app abbreviation:

| App folder | Prefix | Example test file |
|---|---|---|
| `apps/zombie_subscriptions/` | `zs_` | `test_zs_dormant_subscription.py` |
| `apps/phantom_invoices/` | `pi_` | `test_pi_duplicate_invoice.py` |

Shared library tests in `tests/` carry no prefix.

## Package boundaries

- `ledger_kit` is a **library**: it must not import from either app folder.
- App packages (`apps.zombie_subscriptions`, `apps.phantom_invoices`) **import from `ledger_kit`** and from their own `detectors/` sub-package only.
- Apps must not import from each other.
- `explainer.py` is the **only** module permitted to make LLM API calls.
- `money.py` is the **only** module permitted to perform monetary arithmetic; all other modules call its helpers.

## Data directory rules
- `data/samples/` contains only synthetic or explicitly public-domain files.
- Real user data must never be committed to the repository.
- `.gitignore` must exclude `data/real/` and any `*.csv` / `*.json` outside `data/samples/`.

## Configuration files
- Each app has its own `config.toml`; shared defaults live in `ledger_kit/defaults.toml`.
- Secrets are never stored in `config.toml`; they come from environment variables.
- `.env.example` documents required environment variables with placeholder values.
