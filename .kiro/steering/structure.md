# Ghost Ledger Kit — Project Structure

## Top-level layout

```
ghost-ledger-kit/
├── .github/
│   └── workflows/                  # tests.yml (tests on every push), keep-demo-awake.yml (visit the public demo every 6 hours once DEMO_URL is set)
├── .kiro/
│   └── steering/                   # Kiro steering documents (this directory)
├── ledger_kit/                     # Shared template library (importable package)
│   ├── __init__.py
│   ├── models.py                   # Transaction and Alert Pydantic models
│   ├── ingestion/
│   │   ├── __init__.py
│   │   ├── csv_reader.py           # Bank-statement CSV parser → list[Transaction]
│   │   ├── invoice_reader.py       # Invoice parser (CSV + JSON, e.g. FATURA) → list[Invoice]
│   │   ├── norma43_reader.py       # AEB Norma 43 bank-statement parser (control checks, quarantine)
│   │   ├── facturae_reader.py      # Facturae 3.2/3.2.1/3.2.2 XML invoice parser (defusedxml only)
│   │   ├── iso4217.py              # The eleven AEB Annex 2 numeric → alpha currency codes
│   │   ├── sniffer.py              # Content sniffer; read_bank_statement / read_invoices routers
│   │   └── normaliser.py           # Merge sources, validate, assign source_ref
│   ├── detectors/
│   │   ├── __init__.py
│   │   └── base.py                 # DetectorResult type, detector registry
│   ├── explainer.py                # LLM explanation layer; only file that calls an LLM
│   ├── actions.py                  # Exorcise: fixed templates filled into drafts, each checked by the number guard (pure, no model)
│   ├── live_guard.py               # Pure helpers of the Provoke-the-LLM panel (no Streamlit, no model call)
│   ├── replay.py                   # Replay of a recorded real-model run through today's guard (no model, no network)
│   ├── public_data/
│   │   ├── __init__.py             # public names only
│   │   └── ine_cpi.py              # INE CPI snapshot reader and validator (stdlib only, no network)
│   ├── ui/
│   │   ├── __init__.py
│   │   ├── reference_app.py        # Library reference page (Streamlit)
│   │   ├── icons.py                # Six inline SVG line icons: tombstone, ghost, coffin, candle, magnifier, scales
│   │   ├── theme.py                # Palette, one accent per app, the one CSS block, card and heading helpers
│   │   ├── first_run.py            # Pure switch of the demo that loads by itself on the first run of a session
│   │   ├── exorcise.py             # The Exorcise expander shared by the three apps (language, draft, download)
│   │   ├── signatures.py           # Pure markup of the signature of each alert card: ref chips, heartbeat, bites, lantern (no Streamlit)
│   │   └── landing.py              # Home page parts: proof strip read from committed files, tiles, diagram
│   └── utils/
│       ├── __init__.py
│       ├── money.py                # Decimal arithmetic helpers, rounding, formatting
│       └── anonymise.py            # PII scrubbing utilities
├── apps/
│   ├── home_tiles.py               # Bridge for the Home page: runs each app's demo pipeline for one cited-row drawing per tile and the recorded moment
│   ├── zombie_subscriptions/       # App 1: personal recurring-charge detector
│   │   ├── __init__.py
│   │   ├── app.py                  # Streamlit entry point (path bootstrap at top)
│   │   ├── config.toml             # aliases, demo inputs (no thresholds)
│   │   ├── settings.py             # load config.toml, demo inputs, run_pipeline, sidebar text parse/format
│   │   ├── explain_support.py      # fallback TEMPLATES, HallucinatingStubClient
│   │   ├── action_templates.py     # Exorcise templates: refund, cancellation and bank-dispute drafts
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
│   │       ├── test_zs_price_increase_cpi.py  # CPI context of the price-increase alert
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
│   │       ├── test_zs_pipeline.py # run_pipeline of settings.py (amendment A-ZS-01)
│   │       ├── test_zs_real_formats.py  # Norma 43 demo, routers, equivalence with the CSV demo
│   │       ├── test_zs_cpi_support.py   # CPI template, card helpers, number guard with CPI figures
│   │       ├── test_zs_cpi_demo.py      # headless AppTest of the demo with the INE snapshot
│   │       ├── test_zs_scaffold.py
│   │       ├── test_zs_live_guard.py   # headless AppTest runs of the Provoke-the-LLM panel
│   │       ├── zs_live_fakes.py        # fake `openai` module for the live-guard tests
│   │       ├── test_zs_exorcise.py     # Exorcise templates and the card expander (headless AppTest)
│   │       └── test_zs_fixtures.py
│   ├── vampire_fees/               # App 3: bank-fee detector (built from the finished template)
│   │   ├── __init__.py
│   │   ├── app.py                  # Streamlit entry point (path bootstrap at top)
│   │   ├── config.toml             # fee vocabulary and demo paths (no thresholds)
│   │   ├── settings.py             # load config.toml, run_pipeline, view-model helpers
│   │   ├── explain_support.py      # fallback TEMPLATES, HallucinatingStubClient
│   │   ├── action_templates.py     # Exorcise template: the complaint to the bank for each fee alert
│   │   ├── detectors/
│   │   │   ├── __init__.py         # auto_discover
│   │   │   ├── utils.py            # constants, folding, vocabulary, classify_fee, runs
│   │   │   ├── recurring_fee.py
│   │   │   ├── fee_increase.py
│   │   │   ├── overdraft_cost.py
│   │   │   └── fee_summary.py
│   │   └── tests/
│   │       ├── conftest.py
│   │       ├── vf_builders.py      # row and ledger builders, Hypothesis strategies
│   │       ├── test_vf_scaffold.py
│   │       ├── test_vf_utils_normalise.py
│   │       ├── test_vf_classify.py
│   │       ├── test_vf_series.py
│   │       ├── test_vf_fixtures.py
│   │       ├── test_vf_recurring_fee.py
│   │       ├── test_vf_fee_increase.py
│   │       ├── test_vf_overdraft_cost.py
│   │       ├── test_vf_fee_summary.py
│   │       ├── test_vf_registry.py
│   │       ├── test_vf_explain_support.py
│   │       ├── test_vf_settings.py
│   │       ├── test_vf_demo_generator.py
│   │       ├── test_vf_demo_e2e.py
│   │       ├── test_vf_real_formats.py  # Norma 43 demo, routers, equivalence with the CSV demo
│   │       ├── test_vf_live_guard.py    # headless AppTest runs of the Provoke-the-LLM panel
│   │       ├── vf_live_fakes.py         # fake `openai` module for the live-guard tests
│   │       ├── test_vf_exorcise.py      # Exorcise templates and the card expander (headless AppTest)
│   │       └── test_vf_app_logic.py     # pure helpers and headless AppTest runs of app.py
│   └── phantom_invoices/           # App 2: SME invoice anomaly detector
│       ├── __init__.py
│       ├── app.py                  # Streamlit entry point (path bootstrap at top)
│       ├── config.toml             # demo input paths (no thresholds, no secrets)
│       ├── settings.py             # load config.toml, run_pipeline, view-model helpers
│       ├── prepare.py              # multi-rate invoice quarantine
│       ├── explain_support.py      # fallback TEMPLATES, ROW_COLUMNS, HallucinatingStubClient
│       ├── action_templates.py     # Exorcise templates: supplier e-mail, hold note and phone script, corrected invoice
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
│           ├── test_pi_real_formats.py  # Facturae + Norma 43 demo, routers, equivalence with CSV
│           ├── test_pi_live_guard.py    # headless AppTest runs of the Provoke-the-LLM panel
│           ├── pi_live_fakes.py         # fake `openai` module for the live-guard tests
│           ├── test_pi_exorcise.py      # Exorcise templates and the card expander (headless AppTest)
│           └── test_pi_demo_e2e.py
├── tests/                          # Shared library tests
│   ├── conftest.py
│   ├── ingestion/
│   │   ├── n43_builders.py         # Norma 43 record builders (n43_line, fixture_a)
│   │   ├── facturae_builders.py    # Facturae document builders (facturae_doc)
│   │   ├── rf_strategies.py        # Hypothesis strategies for the real-format round trips
│   │   ├── test_csv_reader.py
│   │   ├── test_invoice_reader.py
│   │   ├── test_normaliser.py
│   │   ├── test_iso4217.py
│   │   ├── test_sniffer.py
│   │   ├── test_norma43_reader.py
│   │   ├── test_norma43_controls.py
│   │   ├── test_facturae_reader.py
│   │   ├── test_facturae_security.py
│   │   └── test_real_formats_roundtrip.py
│   ├── public_data/
│   │   ├── conftest.py             # synthetic CPI series S, G and C as fixtures
│   │   ├── cpi_builders.py         # synthetic CPI values and snapshot builders (not INE figures)
│   │   ├── test_ine_cpi_reader.py
│   │   └── test_ine_cpi_snapshot.py  # pinned checks of the committed INE snapshot, .gitignore
│   ├── test_generate_real_formats.py   # Norma 43 / Facturae writers and committed samples
│   ├── test_fetch_ine_cpi.py       # fetch script with a fake opener; no network
│   ├── test_public_data_docs.py    # attribution identical in snapshot, READMEs, Home page
│   ├── test_showcase_app.py        # headless AppTest runs of streamlit_app.py
│   ├── test_showcase_requirements.py
│   ├── test_publish_ready.py       # text checks: usage statistics off, the two GitHub workflows
│   ├── test_benchmark_generator.py # scenario generator: independence, determinism, golden cases
│   ├── test_benchmark_matching.py  # matching rule and metrics (pure)
│   ├── test_benchmark_runner.py    # pipelines, results, CLI, committed files equal a fresh run
│   ├── test_benchmark_page.py      # Benchmark page of streamlit_app.py
│   ├── test_models.py
│   ├── test_explainer_question.py  # optional question and raw_answer of the explainer
│   ├── test_explainer_timeout.py   # optional LEDGER_KIT_LLM_TIMEOUT (1 to 120, default 10)
│   ├── test_explainer_live_run.py  # first real-model run replayed through the guard; guard rules
│   ├── test_live_guard.py          # pure helpers of the Provoke-the-LLM panel
│   ├── judge_path_support.py       # real demo alerts and a small recorded run for the judge-path tests
│   ├── test_judge_path_replay.py   # replay loader, re-check by today's guard, no network
│   ├── test_judge_path_pages.py    # headless AppTest runs: recorded cards, replayed panel, auto-load, Home
│   ├── test_judge_path_misc.py     # plurals, percentages, first-run switch, config key
│   ├── test_live_guard_docs.py     # docs/live-guard.md, README paragraph, .env.example
│   ├── exorcise_script.py          # AppTest script: one Exorcise expander on a sample alert
│   ├── test_actions.py             # Exorcise mechanism: fill, row lines, check_figures, the widget
│   ├── test_exorcise_demos.py      # every alert of the three demos, both languages: guard, words, figures
│   ├── test_exorcise_boundaries.py # no model, no key, no network; package rules of the new modules
│   ├── test_signatures.py          # chips, heartbeat, bites, lantern, CSS, the honesty test over the three demos
│   ├── test_signatures_pages.py    # headless AppTest runs: one signature per card, captions, chips, order
│   ├── test_money.py
│   └── test_anonymise.py
├── scripts/
│   ├── generate_samples.py         # Deterministic synthetic sample generator (--mode, --seed)
│   ├── generate_benchmark.py       # Seeded benchmark scenarios and labels (stdlib + money.py only)
│   ├── benchmark.py                # Benchmark runner: pipelines, matching, results.json, benchmark.md
│   └── fetch_ine_cpi.py            # Developer-run INE CPI snapshot download (stdlib only; never at run time)
├── docs/
│   ├── live-guard.md               # How to provoke a real model (hosted or Ollama) and read the result
│   └── benchmark.md                # Generated by scripts/benchmark.py from results.json; do not edit
├── data/
│   ├── benchmark/                  # Generated output of synthetic scenarios (no personal data)
│   │   └── results.json            # Written by scripts/benchmark.py; compared byte for byte by a test
│   ├── live_runs/                  # Raw answers of real-model runs on the synthetic demo data (never real statements)
│   │   └── 2026-11-10_llama3.2-3b.json  # LG8: llama3.2:3b on Ollama; replayed by test_explainer_live_run.py
│   ├── public/                     # Official public data under an open licence (never personal data)
│   │   ├── README.md               # Source, licence, attribution, refresh command
│   │   └── ine_cpi_ipc290751.json  # INE CPI snapshot written by scripts/fetch_ine_cpi.py
│   └── samples/                    # Synthetic or public-domain sample files only
│       ├── README.md               # Licence reference for any public-domain files
│       ├── bank_statement_sample.csv
│       ├── invoice_sample.csv
│       ├── zombie_demo_statement.csv   # zombie-subscriptions demo (generate_samples.py)
│       ├── zombie_demo_statement.n43   # the same demo as Norma 43 (information mode 3, SEPA)
│       ├── vampire_demo_statement.csv  # vampire-fees demo (generate_samples.py --mode vampire-demo)
│       ├── vampire_demo_statement.n43  # the same demo as Norma 43 (information mode 1)
│       └── phantom_demo/           # phantom-invoices demo (generate_samples.py --mode phantom-demo)
│           ├── suppliers.csv
│           ├── invoices.csv
│           ├── payments.csv
│           ├── payments.n43        # the same payments as Norma 43 (mode 1)
│           └── facturae/           # one Facturae 3.2.2 file per supplier: <kk>-<case>.xml
├── streamlit_app.py                # Showcase entry (st.navigation: Home + the three apps + Benchmark); Community Cloud default
├── conftest.py                     # Root fixture: replay and auto-load off for every test written before judge-path
├── .streamlit/
│   └── config.toml                 # Shared dark Halloween theme: [theme] keys only, no secrets
├── .gitattributes                  # demo CSV, .n43 and .xml samples are byte-compared: no line-ending conversion
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
| `apps/vampire_fees/` | `vf_` | `test_vf_recurring_fee.py` |

Shared library tests in `tests/` carry no prefix.

Tests of the real formats follow the same rules: library tests are named after the module they pin
(`test_norma43_reader.py`, `test_facturae_reader.py`, `test_sniffer.py`; builders and strategies
are `n43_builders.py`, `facturae_builders.py`, `rf_strategies.py` in `tests/ingestion/`), and each
app has one real-format test module with its prefix (`test_zs_real_formats.py`,
`test_pi_real_formats.py`). App tests do not import the builders of `tests/ingestion/`; they build
files with the generator (`scripts/generate_samples.py`).

## Package boundaries

- `ledger_kit` is a **library**: it must not import from either app folder.
- App packages (`apps.zombie_subscriptions`, `apps.phantom_invoices`) **import from `ledger_kit`** and from their own `detectors/` sub-package only.
- The zombie app may import `ledger_kit` and its own `detectors/`, `settings.py`, `explain_support.py` and `action_templates.py`.
- The phantom app may import `ledger_kit` (public names only) and its own `detectors/`, `settings.py`, `prepare.py`, `explain_support.py`, `flashlight.py`, `action_templates.py`.
- The vampire app may import `ledger_kit` (public names only) and its own `detectors/`, `settings.py`, `explain_support.py` and `action_templates.py`.
- Apps must not import from each other.
- Apps read bank statements and invoices through the routers of `ledger_kit/ingestion/sniffer.py`
  (`read_bank_statement`, `read_invoices`); the content, not the file extension, picks the reader.
- `facturae_reader.py` is the only module that parses XML, and it imports XML only from `defusedxml`.
- `ledger_kit/public_data/` is stdlib only and never touches the network; the committed snapshot in
  `data/public/` is its only input. `scripts/fetch_ine_cpi.py` is the only code that downloads it,
  it is run by the developer, imports nothing from the project, and is never called by an app, a
  test or CI.
- The zombie app receives the CPI series through `context["cpi"]`; the detectors do no I/O.
- `explainer.py` is the **only** module permitted to make LLM API calls.
- `live_guard.py` is pure: no Streamlit, no model call; the explainer stays the only module that calls a model.
- `replay.py` is pure too: it reads one committed run file and hands recorded text to the same call and the same guard as a live answer, through an OpenAI-shaped client that opens no connection.
- `actions.py` is pure and calls no model: a draft is a fixed template filled from the alert and its cited rows, and `explainer.check_figures` (the number guard) must pass it before it is shown. `ui/exorcise.py` is the one widget that draws it.
- `money.py` is the **only** module permitted to perform monetary arithmetic; all other modules call its helpers.

## Data directory rules
- `data/samples/` contains only synthetic or explicitly public-domain files.
- `data/benchmark/` contains only generated output of the benchmark (`results.json`): counts and
  ratios computed from synthetic scenarios made by `scripts/generate_benchmark.py`. No personal
  data, no real file. It is written by `python scripts/benchmark.py`, never edited by hand.
- `data/public/` contains only official public data under an open licence (today the INE CPI
  snapshot), with its licence reference and attribution in `data/public/README.md`. Never personal data.
- Real user data must never be committed to the repository.
- `.gitignore` must exclude `data/real/` and any `*.csv` / `*.json` outside `data/samples/`,
  `data/public/` and `data/benchmark/` (the lines `!data/public/`, `!data/public/**`,
  `!data/benchmark/` and `!data/benchmark/**` follow `*.json`).

## Configuration files
- Each app has its own `config.toml`; shared defaults live in `ledger_kit/defaults.toml`.
- Secrets are never stored in `config.toml`; they come from environment variables.
- `.env.example` documents required environment variables with placeholder values.
