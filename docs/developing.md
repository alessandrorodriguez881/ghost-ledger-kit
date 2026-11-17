# Developing Ghost Ledger Kit

Back to the [README](../README.md).

## Try it

Python 3.11 or newer. On Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run streamlit_app.py
```

`streamlit_app.py` is the showcase: a Home page plus the three apps and the Benchmark page in one menu, with the shared dark theme from `.streamlit/config.toml`. Each app also runs alone:

```powershell
streamlit run apps/zombie_subscriptions/app.py
streamlit run apps/phantom_invoices/app.py
streamlit run apps/vampire_fees/app.py
```

In any app, click **Load demo data** in the sidebar if it has not loaded by itself. The CSV demo files are `data/samples/zombie_demo_statement.csv`, `data/samples/vampire_demo_statement.csv` and the three files in `data/samples/phantom_demo/`; the real-format versions are described in `docs/real-formats.md`. You can also upload your own files in the sidebar.

**Optional LLM.** `.env.example` documents `OPENAI_API_KEY`. The code reads it from the process environment and does not load a `.env` file, so set it in your shell before starting Streamlit (PowerShell: `$env:OPENAI_API_KEY = "your-key"`). Without a key every explanation is the fixed template filled from the alert, and the number guard still runs on whatever a client returns.

## Scan files from the command line

`scripts/ledger_scan.py` runs the three apps' pipelines on files and prints one JSON object, so another program can call the kit with the kit's own Python (the virtual environment above) without installing its packages. It sniffs each file by content, uses no model and no network, and gives the same bytes for the same files.

```powershell
# Bank statements (CSV or Norma 43) and invoices (CSV, JSON or Facturae), in one call
.venv\Scripts\python.exe scripts/ledger_scan.py scan data/samples/zombie_demo_statement.csv
.venv\Scripts\python.exe scripts/ledger_scan.py scan data/samples/phantom_demo/invoices.csv --suppliers data/samples/phantom_demo/suppliers.csv --payments data/samples/phantom_demo/payments.csv --as-of 2026-10-30

# Apply the number guard to a text for one alert id taken from the scan output
.venv\Scripts\python.exe scripts/ledger_scan.py check --alert-id ALERT_ID --text "your text" data/samples/zombie_demo_statement.csv
```

`scan` lists, per file, its path, SHA-256, kind, row count and quarantined count (an unreadable file carries an `error` and the others still run), and every alert with its id, app, detector, severity, title, the fixed template text of the card, `source_refs`, the cited rows and the Exorcise drafts in English and Spanish (or `null`). Statements go through Zombie Subscriptions (with no aliases and no cancellation dates, so the detectors that need them stay silent) and Vampire Fees; invoices go through Phantom Invoices, with the optional supplier master and payments. `check` reruns the scan and prints `passed` and the rejected tokens; an unknown alert id gives `passed` false and an error message. The exit code is 0 when the command ran and 2 for bad arguments. The spec is `.kiro/specs/scan-command/`.

## Run the tests

```powershell
pytest
ruff check .
ruff format --check .
```

`pytest` collects `tests/` and `apps/` (see `pyproject.toml`). The property-based tests use Hypothesis.

The demo CSVs are generated, not hand-edited, and tests fail if a committed file differs from the generator output:

```powershell
python scripts/generate_samples.py --mode zombie-demo --seed 42
python scripts/generate_samples.py --mode phantom-demo --seed 42
python scripts/generate_samples.py --mode vampire-demo --seed 42
python scripts/generate_samples.py --mode samples
```

## Project layout

```text
ledger_kit/            shared library: models, ingestion (CSV, Norma 43, Facturae), detectors, explainer, live_guard.py, replay.py, actions.py, utils, ui, public_data
apps/
  zombie_subscriptions/  app.py, config.toml, settings.py, detectors/, tests/
  phantom_invoices/      app.py, config.toml, settings.py, detectors/, tests/
  vampire_fees/          app.py, config.toml, settings.py, detectors/, tests/
scripts/               generate_samples.py (seeded synthetic data), generate_benchmark.py and benchmark.py (benchmark), fetch_ine_cpi.py (INE snapshot), ledger_scan.py (scan and check files, JSON on stdout), kiro_hooks.py (CLI hooks: lint after write, tests on stop)
data/samples/          synthetic sample and demo files only (CSV, Norma 43, Facturae)
data/public/           the committed INE CPI snapshot and its licence notes
data/benchmark/        results.json written by scripts/benchmark.py
data/live_runs/        raw answers of real-model runs on the synthetic demo data
data/hook_runs/        hook_log.jsonl, the log written by the CLI hooks
.kiro/                 specs, steering, hooks, agents (the custom agent)
.github/workflows/     two workflows: tests on every push, and a visit to the public demo every 6 hours once its address is set
powers/                the ghost-ledger-detector power
kiro_prompts/          the prompt file of every Kiro CLI call and run_kiro.ps1, the script that sent them
docs/                  how-it-works.md, real-formats.md, public-data.md, developing.md, benchmark.md (generated), live-guard.md, mcp-api-checks.md (library API checks made through MCP), img/ (home_moment.gif, the image in the README)
tests/                 tests of the shared library and the showcase
streamlit_app.py       showcase entry page
```

`ledger_kit` never imports from the apps, and the three apps never import from each other. The full layout and naming rules are in `.kiro/steering/structure.md`.
