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
│   │   ├── app.py                  # Streamlit entry point (path bootstrap at top)
│   │   ├── config.toml             # aliases, demo inputs (no thresholds)
│   │   ├── settings.py             # load config.toml, demo inputs, sidebar text parse/format
│   │   ├── explain_support.py      # fallback TEMPLATES, HallucinatingStubClient
│   │   ├── detectors/
│   │   │   ├── __init__.py         # auto_discover; run_zs_detectors convenience wrapper
│   │   │   ├── utils.py            # normalisation, series helpers, compute_zombie_cost
│   │   │   ├── recurring_charge.py
│   │   │   ├── price_increase.py
│   │   │   ├── duplicate_subscription.py
│   │   │   ├── free_trial_to_paid.py
│   │   │   └── charges_after_cancellation.py
│   │   └── tests/
│   │       ├── conftest.py
│   │       ├── test_zs_recurring_charge.py
│   │       ├── test_zs_price_increase.py
│   │       ├── test_zs_duplicate_subscription.py
│   │       ├── test_zs_free_trial_to_paid.py
│   │       ├── test_zs_charges_after_cancellation.py
│   │       ├── test_zs_demo_e2e.py
│   │       ├── test_zs_utils_normalise.py
│   │       ├── test_zs_utils_helpers.py
│   │       ├── test_zs_series_primitives.py
│   │       ├── test_zs_segment_by_price.py
│   │       ├── test_zs_find_series.py
│   │       ├── test_zs_active.py
│   │       ├── test_zs_compute_zombie_cost.py
│   │       ├── test_zs_registry.py
│   │       ├── test_zs_settings.py
│   │       ├── test_zs_explain_support.py
│   │       ├── test_zs_demo_generator.py
│   │       ├── test_zs_app_logic.py
│   │       ├── test_zs_app.py      # headless AppTest runs of app.py
│   │       ├── test_zs_scaffold.py
│   │       └── test_zs_fixtures.py
│   └── phantom_invoices/           # App 2: SME invoice anomaly detector
│       ├── __init__.py
│       ├── app.py                  # Streamlit entry point (path bootstrap at top)
│       ├── config.toml             # demo input paths (no thresholds, no secrets)
│       ├── settings.py             # load config.toml, run_pipeline, view-model helpers
│       ├── prepare.py              # multi-rate invoice quarantine
│       ├── explain_support.py      # fallback TEMPLATES, ROW_COLUMNS, HallucinatingStubClient
│       ├── flashlight.py           # haunted-ledger CSS and the flashlight table renderer
│       ├── detectors/
│       │   ├── __init__.py         # auto_discover; LABELS; run_pi_detectors
│       │   ├── utils.py            # keys, IBAN validity, ordering, supplier master, reconcile
│       │   ├── duplicate_invoice.py
│       │   ├── iban_change.py
│       │   ├── vat_error.py
│       │   └── reconciliation.py
│       └── tests/
│           ├── conftest.py         # fixtures; re-exports builders and strategies
│           ├── pi_builders.py      # make_invoices / make_suppliers / make_payments, identifiers
│           ├── pi_checkers.py      # test-local mod-97, national-digit and tax-id checkers
│           ├── pi_strategies.py    # Hypothesis strategies (dirty cells, IBANs, numbers)
│           ├── test_pi_scaffold.py
│           ├── test_pi_ledger_core_contract.py
│           ├── test_pi_utils_keys.py
│           ├── test_pi_utils_iban.py
│           ├── test_pi_utils_order.py
│           ├── test_pi_utils_master.py
│           ├── test_pi_prepare.py
│           ├── test_pi_identifiers.py
│           ├── test_pi_fixtures.py
│           ├── test_pi_duplicate_invoice.py
│           ├── test_pi_iban_change.py
│           ├── test_pi_vat_error.py
│           ├── test_pi_reconciliation.py
│           ├── test_pi_registry.py
│           ├── test_pi_explain_support.py
│           ├── test_pi_flashlight.py
│           ├── test_pi_settings.py
│           ├── test_pi_demo_generator.py
│           ├── test_pi_demo_data.py
│           ├── test_pi_gitattributes.py
│           ├── test_pi_app_logic.py    # pure helpers and headless AppTest runs of app.py
│           ├── test_pi_structure_steering.py
│           └── test_pi_demo_e2e.py
├── tests/                          # Shared library tests
│   ├── conftest.py
│   ├── ingestion/
│   │   ├── test_csv_reader.py
│   │   ├── test_invoice_reader.py
│   │   └── test_normaliser.py
│   ├── test_models.py
│   ├── test_money.py
│   └── test_anonymise.py
├── scripts/
│   └── generate_samples.py         # Deterministic synthetic sample generator (--mode, --seed)
├── data/
│   └── samples/                    # Synthetic or public-domain sample files only
│       ├── README.md               # Licence reference for any public-domain files
│       ├── bank_statement_sample.csv
│       ├── invoice_sample.csv
│       ├── zombie_demo_statement.csv   # zombie-subscriptions demo (generate_samples.py)
│       └── phantom_demo/           # phantom-invoices demo (generate_samples.py --mode phantom-demo)
│           ├── suppliers.csv
│           ├── invoices.csv
│           └── payments.csv
├── .gitattributes                  # demo CSVs are byte-compared: no line-ending conversion
├── pyproject.toml
├── requirements.txt                # Only requirements file (Streamlit Community Cloud)
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
- The zombie app may import `ledger_kit` and its own `detectors/`, `settings.py` and `explain_support.py`.
- The phantom app may import `ledger_kit` (public names only) and its own `detectors/`, `settings.py`, `prepare.py`, `explain_support.py`, `flashlight.py`.
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
