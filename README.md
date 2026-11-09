# Ghost Ledger Kit

Financial apps that cannot make up a number: a template where an LLM may word an explanation but can never introduce a figure.

- Live app: TODO add the Streamlit Community Cloud URL here once the app is deployed.
- Demo video: TODO add the demo video link here once it is recorded.

## The problem

LLM agents invent figures when money is involved. Ask a model to explain a charge or an invoice and it can produce an amount, a date or an IBAN that looks right and is not in the data. In a finance tool that is worse than no answer, because nobody can tell which numbers are real.

Ghost Ledger Kit is built around one promise: an LLM touches the explanation layer only, and every figure in any output is traceable to an exact row of the source data.

## How it works

Three layers, in this order. Each one only receives what the previous one produced.

1. **Ingestion** (`ledger_kit/ingestion/`). Bank-statement CSVs, invoice CSV/JSON files and supplier lists are parsed into one canonical ledger. Rows that fail validation are quarantined, not silently fixed. Every row gets a `source_ref` of the form `file:row`.
2. **Deterministic detectors** (`ledger_kit/detectors/`). Plain Python functions, no machine learning. Each takes the ledger and a read-only context and returns typed `Alert` objects. Detectors register themselves under a namespaced name (`zs.` for Zombie Subscriptions, `pi.` for Phantom Invoices) through `register` in `ledger_kit/detectors/registry.py`; `auto_discover` imports an app's detector modules and `run_all` runs them, isolating a failing detector so it cannot stop the others. Every alert lists the `source_refs` of the rows it comes from, and thresholds are named constants at the top of each detector module.
3. **Explainer** (`ledger_kit/explainer.py`, the only module that calls an LLM). The model gets the alert and the cited source rows, with a system prompt that forbids inventing numbers. Its answer then goes through a number guard: any number, date or IBAN-shaped token that is in neither the cited rows nor the alert's own data causes the answer to be rejected. The app then shows a fixed fallback template filled from the alert instead. The same fallback is used when there is no API key, no `openai` package, or the call fails.

The explanation is decorative. It never feeds back into the alert logic, and it cannot raise, change or dismiss an alert.

**The proof is a switch.** Both apps have a sidebar toggle, *Simulate a hallucinating LLM*. It replaces the model with a stub that always answers with an invented figure (99999.99). The number guard rejects that answer, the card shows the fixed template, and the alert card shows a warning badge. You can watch the guard work without an API key.

### Public context: the INE consumer price index

A price increase says little on its own: 18 % is more or less depending on what prices did in the same months. When `zs.price_increase` has already raised an alert, it can add one piece of official context: how the Spanish consumer price index (IPC, INE series IPC290751, base 2025) changed between the same two months, in one neutral sentence on the card. It is context, not a verdict: it never decides whether an alert fires, changes a severity or a `source_refs` list, and gives no advice.

- **A committed file, never the network.** The index is a snapshot in `data/public/ine_cpi_ipc290751.json`, read by `ledger_kit/public_data/`. The apps, the tests and the explanation layer never call the network. Only the developer runs `python scripts/fetch_ine_cpi.py`, which makes one request, checks the result and replaces the file only if every check passes.
- **Same promise as every other figure.** The index values and the two percentages are named fields of `Alert.data` (`cpi_series`, the months used, the two index values, `cpi_change_percent`), so the number guard admits them and rejects any other number. When a month is not covered by the snapshot the alert carries no CPI field at all.
- **Attribution.** The INE data keeps its own licence (CC BY 4.0) and is not covered by the MIT licence of this repository. The Zombie Subscriptions page shows this notice once, below its alerts:

> Elaboración propia con datos extraídos del sitio web del INE: www.ine.es
>
> Licence: CC BY 4.0
>
> The INE does not take part in, sponsor or support this reuse.

Source, series, licence and refresh steps are in `data/public/README.md`.

## The two apps

Both apps are built on the same `ledger_kit` library and share nothing else.

**Zombie Subscriptions** (`apps/zombie_subscriptions/`) is for individuals. It reads a bank statement and finds forgotten subscriptions. The registered detectors are `zs.recurring_charge`, `zs.price_increase`, `zs.duplicate_subscription`, `zs.free_trial_to_paid` and `zs.charges_after_cancellation`. It also shows the cost of a service since its last-used date as a tombstone card. With the demo data loaded in the browser it shows 3 tombstones and 19 alerts: 1 critical, 4 warning and 14 info.

**Phantom Invoices** (`apps/phantom_invoices/`) is for small Spanish businesses. It reads invoices, a supplier master and bank payments and finds duplicate invoices (`pi.duplicate_invoice`), supplier IBAN changes and invalid IBANs (`pi.iban_change`), VAT errors (`pi.vat_error`), and overdue invoices or payments that match no invoice (`pi.reconciliation`). With the demo data loaded it shows 9 alerts: 3 critical and 6 warning. The end-to-end test `apps/phantom_invoices/tests/test_pi_demo_e2e.py` pins this split.

The demo numbers for Zombie Subscriptions come from a manual run in the browser; for Phantom Invoices they are also asserted by the test above.

## Try it

Python 3.11 or newer. On Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run streamlit_app.py
```

`streamlit_app.py` is the showcase: a Home page plus the two apps in one menu, with the shared dark theme from `.streamlit/config.toml`. Each app also runs alone:

```powershell
streamlit run apps/zombie_subscriptions/app.py
streamlit run apps/phantom_invoices/app.py
```

In either app, click **Load demo data** in the sidebar. The demo files are `data/samples/zombie_demo_statement.csv` and the three files in `data/samples/phantom_demo/`. You can also upload your own files in the sidebar.

**Optional LLM.** `.env.example` documents `OPENAI_API_KEY`. The code reads that variable from the process environment and does not load a `.env` file itself, so set it in your shell before starting Streamlit (PowerShell: `$env:OPENAI_API_KEY = "your-key"`). Without a key nothing breaks: every explanation is the fixed template filled from the alert, and the number guard still runs on whatever a client returns.

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
python scripts/generate_samples.py --mode samples
```

## Project layout

```text
ledger_kit/            shared library: models, ingestion, detectors, explainer, utils, ui, public_data
apps/
  zombie_subscriptions/  app.py, config.toml, settings.py, detectors/, tests/
  phantom_invoices/      app.py, config.toml, settings.py, detectors/, tests/
scripts/               generate_samples.py (seeded synthetic data), fetch_ine_cpi.py (INE snapshot)
data/samples/          synthetic sample and demo files only
data/public/           the committed INE CPI snapshot and its licence notes
.kiro/                 specs, steering, hooks
powers/                the ghost-ledger-detector power
docs/                  mcp-api-checks.md (library API checks made through MCP)
tests/                 tests of the shared library and the showcase
streamlit_app.py       showcase entry page
```

`ledger_kit` never imports from the apps, and the two apps never import from each other. The full layout and naming rules are in `.kiro/steering/structure.md`.

## How we used Kiro

| Kiro feature | What we did | Why it mattered |
|---|---|---|
| Specs | Specs under `.kiro/specs/`, each with `requirements.md`, `design.md` and `tasks.md`: `.kiro/specs/ledger-core/`, `.kiro/specs/zombie-subscriptions/`, `.kiro/specs/phantom-invoices/`, `.kiro/specs/showcase/` and `.kiro/specs/public-cpi/` (the INE price-index context of the Zombie Subscriptions price-increase alert). The tasks files are ticked off as work was done. | Each rule that keeps figures honest (cite the source row, no invented number) is a numbered requirement with a test, so the promise is written down before the code. |
| Steering | Six files in `.kiro/steering/`. Five are always included: `product.md`, `tech.md`, `structure.md`, `testing.md` and `finance-rules.md`. One is manual: `update-kiro-usage.md`, used to rewrite this section. | `finance-rules.md` makes "never invent a figure, always cite the source row" binding on every change, and it carries the exact no-invention wording the explainer prompt must use. |
| Hooks | Three hooks in `.kiro/hooks/`: `detector-guard.kiro.hook` (audits a detector when it is edited), `samples-sync.kiro.hook` (keeps the demo data in sync with the generator) and `kiro-usage.kiro.hook` (manual, rewrites this section). | The detector hook audits registration, the three test tiers, purity and named thresholds on every detector edit; the samples hook keeps the demo numbers reproducible from a fixed seed. |
| MCP | The context7 MCP server (remote, no API key) is configured in `.kiro/settings/mcp.json` after the developer approved it. The agent used it to check the Streamlit, pandas and Hypothesis behaviour the code relies on against the official docs, with the results in `docs/mcp-api-checks.md` (no mismatch; the open points were then confirmed against the installed versions). | Library APIs change between releases, so the assumptions behind the demo-loading callback, the AppTest tests and the property tests were checked against current docs instead of memory. |
| Property-based testing | Hypothesis tests with `max_examples=200` in `tests/` and in `apps/*/tests/`. The no-invention property uses `loaded_source_refs` from `ledger_kit/detectors/` and asserts that every cited `source_ref` belongs to a loaded input; see `apps/phantom_invoices/tests/test_pi_vat_error.py` and `apps/zombie_subscriptions/tests/test_zs_price_increase.py`. | It checks the core promise on generated inputs, including dirty cells, not only on hand-picked examples: no alert may cite a row that was not loaded. |
| Powers | One local power, `powers/ghost-ledger-detector/`, with the `add-detector` skill in `powers/ghost-ledger-detector/skills/add-detector/SKILL.md`. It is imported from the folder in the Kiro Powers panel. | It teaches an agent to add a new detector the same way as the existing ones, with the namespaced registration, source refs and tests, so a new detector keeps the contract. |

Kiro documentation: [kiro.dev/docs](https://kiro.dev/docs/).

## Data and licence

All demo and sample data in this repository is synthetic and generated by `scripts/generate_samples.py` with a fixed seed (42 by default), so regenerating gives the same bytes. There is no real personal or financial data; see `data/samples/README.md`.

- Company and person names are invented.
- IBANs pass the ISO 13616 mod-97 check but have deliberately wrong Spanish national check digits, so they cannot be real accounts.
- Spanish tax ids carry a wrong control character, a different one per fictional supplier.

The one exception is `data/public/`: official public data from the INE (the consumer price index), under CC BY 4.0, with its licence reference and attribution in `data/public/README.md` and in the section above. It contains no personal data.

Released under the MIT licence, see `LICENSE`. The INE data keeps the INE licence.

## Hackathon

Kiroween 2026, category Skeleton Crew: one template, two very different apps. A personal-finance tool for individuals and an invoice-checking tool for small Spanish businesses are built on the same three layers and the same guarantee.

Tools used: [Streamlit](https://docs.streamlit.io/), [pytest](https://docs.pytest.org/), [Hypothesis](https://hypothesis.readthedocs.io/) and [Ruff](https://docs.astral.sh/ruff/).
