# Ghost Ledger Kit

Financial apps that cannot make up a number: a template where an LLM may word an explanation but can never introduce a figure.

- Live app: TODO add the Streamlit Community Cloud URL here once the app is deployed.
- Demo video: TODO add the demo video link here once it is recorded.

## The problem

LLM agents invent figures when money is involved. Ask a model to explain a charge or an invoice and it can produce an amount, a date or an IBAN that looks right and is not in the data. In a finance tool that is worse than no answer, because nobody can tell which numbers are real.

Ghost Ledger Kit is built around one promise: an LLM touches the explanation layer only, and every figure in any output is traceable to an exact row of the source data.

## How it works

Three layers, in this order. Each one only receives what the previous one produced.

1. **Ingestion** (`ledger_kit/ingestion/`). Bank statements (CSV or Norma 43), invoices (CSV, JSON or Facturae XML) and supplier lists are parsed into one canonical ledger; the content of a file, not its extension, picks the reader. Rows that fail validation are quarantined, not silently fixed. Every row gets a `source_ref` of the form `file:row`.
2. **Deterministic detectors** (`ledger_kit/detectors/`). Plain Python functions, no machine learning. Each takes the ledger and a read-only context and returns typed `Alert` objects. Detectors register themselves under a namespaced name (`zs.` for Zombie Subscriptions, `pi.` for Phantom Invoices) through `register` in `ledger_kit/detectors/registry.py`; `auto_discover` imports an app's detector modules and `run_all` runs them, isolating a failing detector so it cannot stop the others. Every alert lists the `source_refs` of the rows it comes from, and thresholds are named constants at the top of each detector module.
3. **Explainer** (`ledger_kit/explainer.py`, the only module that calls an LLM). The model gets the alert and the cited source rows, with a system prompt that forbids inventing numbers. Its answer then goes through a number guard: any number, date or IBAN-shaped token that is in neither the cited rows nor the alert's own data causes the answer to be rejected. The app then shows a fixed fallback template filled from the alert instead. The same fallback is used when there is no API key, no `openai` package, or the call fails.

The explanation is decorative. It never feeds back into the alert logic, and it cannot raise, change or dismiss an alert.

**The proof is a switch.** Both apps have a sidebar toggle, *Simulate a hallucinating LLM*. It replaces the model with a stub that always answers with an invented figure (99999.99). The number guard rejects that answer, the card shows the fixed template, and the alert card shows a warning badge. You can watch the guard work without an API key.

### Real Spanish formats

Both apps read the formats Spanish banks and invoicing software actually produce, not only CSV. The two readers live in `ledger_kit/ingestion/`, and the router in `sniffer.py` picks the reader from the file content.

| Format | Reader | What it does | Safety |
|---|---|---|---|
| Norma 43 bank statements (AEB Cuaderno 43) | `norma43_reader.py` | Fixed-width records 11, 22, 23, 24, 33 and 88; amounts are `Decimal`; the counts and totals of the closing record are checked, and a failed check is shown, not hidden. | Bad movements are quarantined with a reason. |
| Facturae 3.2, 3.2.1 and 3.2.2 e-invoices (XML) | `facturae_reader.py` | Each invoice becomes one canonical invoice, with taxes, withholdings and installments read from the schema paths; several files are merged in file-name order. | XML is parsed only with `defusedxml` (DTDs and entities refused). Digital signatures (`.xsig`) are read but **not verified**, and the page says so. A multi-rate invoice is quarantined. |

- **IBAN convention.** The Norma 43 standard has no counterparty IBAN field. The reader takes an IBAN only from a 23 record whose text starts with `IBAN `. A real bank file without such records still loads, and the page says that the payment-side IBAN checks are skipped for it.
- **Demo format choice.** Each app has a *Demo format* radio, `CSV` or `Real formats`. `Real formats` loads `data/samples/zombie_demo_statement.n43`, or `payments.n43` plus the 25 Facturae files in `data/samples/phantom_demo/facturae/`, and gives the same alerts as the CSV demo (same detectors, severities and figures; only the `source_refs` differ). Tests prove it: `test_zs_real_formats.py` and `test_pi_real_formats.py` in the app `tests/` folders.
- **What was checked, and by whom.** The reviewer compared the Norma 43 layouts with the AEB document and the Facturae paths with the official schema, and validated all 25 sample Facturae files once against the official `Facturaev3_2_2` XSD (25 of 25 valid). That XSD check is not part of CI, so it must be repeated by hand if the sample writer changes.

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

### Benchmark: does it catch what it should, and stay quiet when it should?

`scripts/generate_benchmark.py` builds, from a seed, 200 synthetic scenarios per app (40 of them clean). Each plants known problems with labels (a duplicate invoice, a changed IBAN, a forgotten subscription) next to 14 hard negatives per app: look-alike clean cases such as weekly groceries, two legitimate IBANs of one supplier or a late but full payment. The scenarios go through the same pipelines the apps run. **Matching rule:** an alert is a true positive when an unmatched label of the same type shares at least one `source_ref` with it; every other alert is a false alarm and every unmatched label a miss. There is no pass mark; the numbers are reported, not gated.

It found real weaknesses, which the `detector-fixes` spec then corrected without changing any threshold, label or hard negative (seed 2026, 200 scenarios per app):

| App | Precision before → after | False alarms before → after | Recall before → after | Cause fixed |
|---|---|---|---|---|
| Zombie Subscriptions | 0.9719 → 0.9980 | 29 → 2 | 1.0000 → 1.0000 | Similar charges picked out of a stream of weekly or irregular purchases at one shop were accepted as a "variable bill" subscription. |
| Phantom Invoices | 0.7742 → 1.0000 | 140 → 0 | 1.0000 → 1.0000 | A supplier's second valid IBAN in the master was ignored and raised a critical alert. |

- **A flaw in the benchmark itself.** The first run found only 9 of 84 planted duplicate subscriptions. The detector was right: the generator had placed the pairs at random dates, while the requirement counts only series still active at the end of the ledger. The generator was fixed, not the detector.
- **Limits.** The data is synthetic and the labels were written by the same team as the requirements, so a pattern nobody thought of is not planted. Only plain CSV is benchmarked. The 2 remaining zombie false alarms (both on `weekly_groceries_irregular`) are a documented limit: regular charges of one shop on one price level look like a subscription. The numbers describe this mix of scenarios, not real bank data.
- **Reproduce.** `python scripts/benchmark.py` rewrites `data/benchmark/results.json` and `docs/benchmark.md` (under a minute); `python scripts/benchmark.py --check` reruns and compares them byte for byte with the committed files. The showcase has a Benchmark page that shows the results file.

## The three apps

All three apps are built on the same `ledger_kit` library and share nothing else.

**Zombie Subscriptions** (`apps/zombie_subscriptions/`) is for individuals. It reads a bank statement and finds forgotten subscriptions. The registered detectors are `zs.recurring_charge`, `zs.price_increase`, `zs.duplicate_subscription`, `zs.free_trial_to_paid` and `zs.charges_after_cancellation`. It also shows the cost of a service since its last-used date as a tombstone card. With the demo data loaded in the browser it shows 3 tombstones and 19 alerts: 1 critical, 4 warning and 14 info.

**Phantom Invoices** (`apps/phantom_invoices/`) is for small Spanish businesses. It reads invoices, a supplier master and bank payments and finds duplicate invoices (`pi.duplicate_invoice`), supplier IBAN changes and invalid IBANs (`pi.iban_change`), VAT errors (`pi.vat_error`), and overdue invoices or payments that match no invoice (`pi.reconciliation`). With the demo data loaded it shows 9 alerts: 3 critical and 6 warning. The end-to-end test `apps/phantom_invoices/tests/test_pi_demo_e2e.py` pins this split.

**Vampire Fees** (`apps/vampire_fees/`) is for individuals and small businesses. It reads a bank statement and finds the bank fees that drain an account: recurring fees (`vf.recurring_fee`), fees that rise (`vf.fee_increase`), the cost of an overdraft (`vf.overdraft_cost`) and the total (`vf.fee_summary`). Each recurring fee is drawn as a coffin card. Refunds are not subtracted from its totals, and only EUR rows are analysed. The details are below.

### Vampire Fees in detail

- **What it reads.** A bank statement as CSV or as Norma 43; the content picks the reader. For Norma 43 it uses the common concepts 16 (stamp duty and brokerage) and 17 (interest, fees and taxes) that the bank writes on each movement, so a fee with an unusual wording is still found.
- **Demo numbers.** With the Norma 43 demo (`data/samples/vampire_demo_statement.n43`) the page shows 45 fees, a total of 379,25 EUR and a yearly equivalent of 207,54 EUR, with the coffin cards and 45 cited rows from that file. The page was checked in the browser with no error. The matching CSV demo is `data/samples/vampire_demo_statement.csv`.
- **Template proof.** It was built as the third app, only from the finished template, by the Kiro custom agent `ghost-ledger-builder` (`.kiro/agents/ghost-ledger-builder.json`), with no change to `ledger_kit/` or to the other two apps (checked with `git diff`). The spec took about 7 minutes; the build took one call with the custom agent and one fix call. In total it took 6 Kiro calls (5 productive) and about one hour from the first spec prompt to a working, tested app: 11 code files with 1099 lines and 19 test files with 3064 lines. The one copy of code between apps is listed as a decision in `.kiro/specs/vampire-fees/design.md`; the full record is task VF17 in `.kiro/specs/vampire-fees/tasks.md`.

The demo numbers are pinned by tests: `apps/zombie_subscriptions/tests/test_zs_demo_e2e.py` and `apps/phantom_invoices/tests/test_pi_demo_e2e.py` run the demo end to end, and `tests/test_showcase_app.py` checks the alert counts shown in the showcase.

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
```

In either app, click **Load demo data** in the sidebar (choose *Demo format* `CSV` or `Real formats` first). The CSV demo files are `data/samples/zombie_demo_statement.csv` and the three files in `data/samples/phantom_demo/`; the real-format versions are described above. You can also upload your own files in the sidebar.

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
ledger_kit/            shared library: models, ingestion (CSV, Norma 43, Facturae), detectors, explainer, utils, ui, public_data
apps/
  zombie_subscriptions/  app.py, config.toml, settings.py, detectors/, tests/
  phantom_invoices/      app.py, config.toml, settings.py, detectors/, tests/
scripts/               generate_samples.py (seeded synthetic data), generate_benchmark.py and benchmark.py (benchmark), fetch_ine_cpi.py (INE snapshot)
data/samples/          synthetic sample and demo files only (CSV, Norma 43, Facturae)
data/public/           the committed INE CPI snapshot and its licence notes
data/benchmark/        results.json written by scripts/benchmark.py
.kiro/                 specs, steering, hooks
powers/                the ghost-ledger-detector power
docs/                  benchmark.md (generated), mcp-api-checks.md (library API checks made through MCP)
tests/                 tests of the shared library and the showcase
streamlit_app.py       showcase entry page
```

`ledger_kit` never imports from the apps, and the two apps never import from each other. The full layout and naming rules are in `.kiro/steering/structure.md`.

## How we used Kiro

Kiro wrote every spec, every test and every line of code in this repository from prompts. The developer's coding assistant, Claude Code, acted as reviewer: it wrote the prompts, ran the tools (`pytest`, `ruff`, the benchmark), read the results and sent any failures back to Kiro.

| Kiro feature | What we did | Why it mattered |
|---|---|---|
| Specs | Eight specs in `.kiro/specs/`, each with `requirements.md`, `design.md` and `tasks.md`: `ledger-core`, `zombie-subscriptions`, `phantom-invoices`, `showcase`, `public-cpi` (INE price-index context), `real-formats` (Norma 43 and Facturae), `benchmark` and `detector-fixes` (the corrections the benchmark found). Tasks are ticked off as work was done; amendments are recorded in the older specs, for example in REQ-PI-09 and REQ-ZS-10a. | Each rule that keeps figures honest (cite the source row, no invented number) is a numbered requirement with a test, so the promise is written down before the code. |
| Steering | Six files in `.kiro/steering/`. Five are always included: `product.md`, `tech.md`, `structure.md`, `testing.md` and `finance-rules.md`. One is manual: `update-kiro-usage.md`, used to rewrite this section. | `finance-rules.md` makes "never invent a figure, always cite the source row" binding on every change, and it carries the exact no-invention wording the explainer prompt must use. |
| Hooks | Three hooks in `.kiro/hooks/`: `detector-guard.kiro.hook` (audits a detector when it is edited), `samples-sync.kiro.hook` (keeps the demo data in sync with the generator) and `kiro-usage.kiro.hook` (manual, rewrites this section). | The detector hook audits registration, the three test tiers, purity and named thresholds on every detector edit; the samples hook keeps the demo numbers reproducible from a fixed seed. |
| MCP | The context7 MCP server (remote, no API key) is configured in `.kiro/settings/mcp.json` after the developer approved it. The agent used it in two sessions: 5c, to check the Streamlit, pandas and Hypothesis behaviour the code relies on against the official docs (results in `docs/mcp-api-checks.md`, no mismatch), and 8a, to look up `defusedxml` and the Python 3.12 XML security notes before writing the Facturae reader (library notes in section 6 of `.kiro/specs/real-formats/design.md`). | Library APIs change between releases, so the assumptions behind the demo-loading callback, the AppTest tests, the property tests and the safe XML parsing were checked against current docs instead of memory. |
| Property-based testing | Hypothesis tests with `max_examples=200` in `tests/` and in `apps/*/tests/`. The no-invention property uses `loaded_source_refs` from `ledger_kit/detectors/` and asserts that every cited `source_ref` belongs to a loaded input; see `apps/phantom_invoices/tests/test_pi_vat_error.py` and `apps/zombie_subscriptions/tests/test_zs_price_increase.py`. | It checks the core promise on generated inputs, including dirty cells, not only on hand-picked examples: no alert may cite a row that was not loaded. |
| Powers | One local power, `powers/ghost-ledger-detector/`, with the `add-detector` skill in `powers/ghost-ledger-detector/skills/add-detector/SKILL.md`. It is imported from the folder in the Kiro Powers panel. | It teaches an agent to add a new detector the same way as the existing ones, with the namespaced registration, source refs and tests, so a new detector keeps the contract. |
| Custom agent | `.kiro/agents/ghost-ledger-builder.json` with its prompt `.kiro/agents/ghost-ledger-builder.md`. It loads the five always-included steering files, `update-kiro-usage.md`, `README.md` and the `add-detector` skill, and may use the context7 MCP server. It reads and writes files only, so it cannot run commands. It built the Vampire Fees app (`apps/vampire_fees/`). | The agent starts with the finance rules in its context and a hard boundary (no edit of `ledger_kit/` or another app), so a new app inherits the no-invention contract; `git diff` showed zero changes to the library and the other two apps. |

Kiro documentation: [kiro.dev/docs](https://kiro.dev/docs/).

## Data and licence

All demo and sample data in this repository is synthetic and generated by `scripts/generate_samples.py` with a fixed seed (42 by default), so regenerating gives the same bytes; this includes the Norma 43 and Facturae samples. There is no real personal or financial data; see `data/samples/README.md`.

- Company and person names are invented.
- IBANs pass the ISO 13616 mod-97 check but have deliberately wrong Spanish national check digits, so they cannot be real accounts.
- Spanish tax ids carry a wrong control character, a different one per fictional supplier.

The one exception is `data/public/`: official public data from the INE (the consumer price index), under CC BY 4.0, with its licence reference and attribution in `data/public/README.md` and in the section above. It contains no personal data.

Released under the MIT licence, see `LICENSE`. The INE data keeps the INE licence.

## Hackathon

Kiroween 2026, category Skeleton Crew: one template, two very different apps. A personal-finance tool for individuals and an invoice-checking tool for small Spanish businesses are built on the same three layers and the same guarantee.

Tools used: [Streamlit](https://docs.streamlit.io/), [pytest](https://docs.pytest.org/), [Hypothesis](https://hypothesis.readthedocs.io/) and [Ruff](https://docs.astral.sh/ruff/).
