# Ghost Ledger Kit

Financial apps where an LLM may word the explanation but cannot slip in a figure: any amount, date or IBAN that is not in the cited rows or the alert data, in digits or in English or Spanish words, sends the card back to a fixed template. It checks figures, not meaning (see What the guard does not check).

- Live app: TODO add the Streamlit Community Cloud URL here once the app is deployed.
- Demo video: TODO add the demo video link here once it is recorded.

## For judges: 60 seconds

No key and no install are needed on the public app.

1. Open Home. Within three seconds it shows one recorded answer of a real model (`llama3.2:3b`) that assumed a 5% interest rate found in no row and built 617.51 on it, and the number guard striking both figures out and showing a fixed template instead. Each app tile shows that app's own drawing, and the rest of the text is under *How it works*.
2. Open Zombie Subscriptions. The demo loads by itself.
3. Each card shows a drawing from its cited rows and the recorded real answer, re-checked by today's number guard and labelled *No model called*.
4. On the GYMPLUS card, open *Provoke the LLM* and replay the five-year question. The model's arithmetic is right (107.88 × 5 = 539.40) and the guard still rejects it: it does no arithmetic and lets through only figures it finds in the rows.
5. On any card, open *Exorcise* to get the refund request or the bank complaint.

To run it live with a local model, see `docs/live-guard.md`.

## The problem

LLM agents invent figures when money is involved. Ask a model to explain a charge or an invoice and it can produce an amount, a date or an IBAN that looks right and is not in the data. In a finance tool that is worse than no answer, because nobody can tell which numbers are real.

Ghost Ledger Kit is built around one promise: an LLM touches the explanation layer only. Every figure it writes must be one the detectors already produced (the alert data) or one in a cited row, and every alert cites the rows it comes from (`file:row`).

## How it works

Three layers, in this order. Each one only receives what the previous one produced.

1. **Ingestion** (`ledger_kit/ingestion/`). Bank statements (CSV or Norma 43), invoices (CSV, JSON or Facturae XML) and supplier lists are parsed into one canonical ledger; the content of a file, not its extension, picks the reader. Rows that fail validation are quarantined, not silently fixed. Every row gets a `source_ref` of the form `file:row`.
2. **Deterministic detectors** (`ledger_kit/detectors/`). Plain Python functions, no machine learning. Each takes the ledger and a read-only context and returns typed `Alert` objects. Detectors register themselves under a namespaced name (`zs.` for Zombie Subscriptions, `pi.` for Phantom Invoices, `vf.` for Vampire Fees) through `register` in `ledger_kit/detectors/registry.py`; `auto_discover` imports an app's detector modules and `run_all` runs them, isolating a failing detector so it cannot stop the others. Every alert lists the `source_refs` of the rows it comes from, and thresholds are named constants at the top of each detector module.
3. **Explainer** (`ledger_kit/explainer.py`, the only module that calls an LLM). The model gets the alert and the cited source rows, with a system prompt that forbids inventing numbers. Its answer then goes through a number guard: any number, date or IBAN-shaped token that is in neither the cited rows nor the alert's own data causes the answer to be rejected. The app then shows a fixed fallback template filled from the alert instead. The same fallback is used when there is no API key, no `openai` package, or the call fails.

The explanation is decorative. It never feeds back into the alert logic, and it cannot raise, change or dismiss an alert.

**The model asks, the kit computes.** When a question needs arithmetic, such as a total over five years, the model does not calculate: it writes a placeholder like `[[calc: yearly_cost * 5]]`, and `ledger_kit/calc.py` computes it in `Decimal` from the numeric fields of the alert and the whole numbers of the question. The card shows the result marked, with its formula (`yearly_cost 107,88 EUR x 5 = 539,40 EUR`). What did not change: the guard still rejects any figure the model writes itself that is not in the cited rows or the alert data, and an expression with an unknown field, a number the question does not contain, a power or a division by zero sends the card back to the fixed template. The spec is `.kiro/specs/model-computes/`.

**The proof is a switch.** Each of the three apps has a sidebar toggle, *Simulate a hallucinating LLM*. It replaces the model with a stub that always answers with an invented figure (99999.99). The number guard rejects it, the card shows the fixed template, and a warning badge appears. No API key is needed.

**No key needed, real model output.** `data/live_runs/2026-11-11_llama3.2-3b_demo.json` holds the raw answers that `llama3.2:3b` gave on the synthetic demo data. Without a key, a card shows the recorded answer if today's number guard accepts it, and the fixed template if not; the *Provoke the LLM* panel replays a recorded answer to a trick question. No model is called and no network is used, and the captions say so. With a key set, the apps call the model as before.

**The proof, live.** Every alert card has a *Provoke the LLM* panel: three preset questions that tempt a model to state a figure that is not in the cited rows. It uses the model set through `OPENAI_API_KEY` (a local model through Ollama works too), shows the raw answer, marks the rejected tokens and shows the fixed template next to it. In general, small local models invent figures more often than large hosted ones, so a rejection is the likely outcome. The guard checks figures, dates and IBAN-shaped tokens only and does not judge wording: an accepted answer is not a statement that it is true, and a harmless count such as `3 months` is rejected too. The first call to a local model can take longer than the 10 seconds allowed, so warm it up first. Steps for Windows with Ollama are in `docs/live-guard.md`.

## What the guard does not check

- **Meaning.** It checks that each figure is in the cited rows or the alert data, not what the sentence says about it. `MUSICBOX costs 10.99 EUR every year` passes on a monthly 10.99 charge. The one exception: it rejects an answer that names the price index as the cause of the price change, because the kit promises the index is context only.
- **Arithmetic.** It does none. A right result that is in no row is rejected (107.88 × 5 = 539.40), and a figure that is in the rows passes whatever the sentence does with it.
- **Number words.** English and Spanish only. Any number above ten, or written with more than one word, is checked; ten or less only next to a currency or a percent. So `three months` and `one of them` pass, while `3 months` in digits is rejected. Ordinals and other languages are not read, so a day written as `twenty-first` is not checked. An amount with cents in words is rejected even when right.
- **Truth.** An accepted answer is not a statement that it is true.

### Real Spanish formats

All three apps read the formats Spanish banks and invoicing software actually produce, not only CSV. The two readers live in `ledger_kit/ingestion/`, and the router in `sniffer.py` picks the reader from the file content.

| Format | Reader | What it does | Safety |
|---|---|---|---|
| Norma 43 bank statements (AEB Cuaderno 43) | `norma43_reader.py` | Fixed-width records 11, 22, 23, 24, 33 and 88; amounts are `Decimal`; the counts and totals of the closing record are checked, and a failed check is shown, not hidden. | Bad movements are quarantined with a reason. |
| Facturae 3.2, 3.2.1 and 3.2.2 e-invoices (XML) | `facturae_reader.py` | Each invoice becomes one canonical invoice, with taxes, withholdings and installments read from the schema paths; several files are merged in file-name order. | XML is parsed only with `defusedxml` (DTDs and entities refused). Digital signatures (`.xsig`) are read but **not verified**, and the page says so. A multi-rate invoice is quarantined. |

- **IBAN convention.** Norma 43 has no counterparty IBAN field, so the reader takes an IBAN only from a 23 record whose text starts with `IBAN `. A file without such records still loads, and the page says the payment-side IBAN checks are skipped.
- **Demo format choice.** Zombie Subscriptions and Phantom Invoices have a *Demo format* radio, `CSV` or `Real formats`. `Real formats` loads `data/samples/zombie_demo_statement.n43`, or `payments.n43` plus the 25 Facturae files in `data/samples/phantom_demo/facturae/`, and gives the same alerts as the CSV demo (same detectors, severities and figures; only the `source_refs` differ). Tests prove it: `test_zs_real_formats.py` and `test_pi_real_formats.py` in the app `tests/` folders. Vampire Fees has `test_vf_real_formats.py` for its Norma 43 demo.
- **What was checked, and by whom.** The reviewer compared the Norma 43 layouts with the AEB document and the Facturae paths with the official schema, and validated all 25 sample Facturae files once against the official `Facturaev3_2_2` XSD (25 of 25 valid). That check is not part of CI.

### Public context: the INE consumer price index

A price increase says little on its own: 18 % is more or less depending on what prices did in the same months. When `zs.price_increase` has already raised an alert, it can add one neutral sentence of official context: how the Spanish consumer price index (IPC, INE series IPC290751, base 2025) changed between the same two months. It is context, not a verdict: it never decides whether an alert fires, changes a severity or a `source_refs` list, and gives no advice.

- **A committed file, never the network.** The index is a snapshot in `data/public/ine_cpi_ipc290751.json`, read by `ledger_kit/public_data/`. The apps, the tests and the explanation layer never call the network. Only the developer runs `python scripts/fetch_ine_cpi.py`, which makes one request, checks the result and replaces the file only if every check passes.
- **Same promise as every other figure.** The index values and the percentage are named fields of `Alert.data`, so the number guard admits them and rejects any other number. When a month is not covered by the snapshot the alert carries no CPI field at all.
- **Attribution.** The INE data keeps its own licence (CC BY 4.0) and is not covered by the MIT licence of this repository. The Zombie Subscriptions page shows this notice once, below its alerts:

> Elaboración propia con datos extraídos del sitio web del INE: www.ine.es
>
> Licence: CC BY 4.0
>
> The INE does not take part in, sponsor or support this reuse.

Source, series, licence and refresh steps are in `data/public/README.md`.

### Benchmark: does it catch what it should, and stay quiet when it should?

`scripts/generate_benchmark.py` builds, from a seed, 200 synthetic scenarios per app (Zombie Subscriptions and Phantom Invoices; 40 of them clean). Each plants known problems with labels (a duplicate invoice, a changed IBAN, a forgotten subscription) next to 14 hard negatives per app: look-alike clean cases such as weekly groceries, two legitimate IBANs of one supplier or a late but full payment. The scenarios go through the same pipelines the apps run. **Matching rule:** an alert is a true positive when an unmatched label of the same type shares at least one `source_ref` with it; every other alert is a false alarm and every unmatched label a miss. There is no pass mark; the numbers are reported, not gated.

It found real weaknesses, which the `detector-fixes` spec then corrected without changing any threshold, label or hard negative (seed 2026, 200 scenarios per app):

| App | Precision before → after | False alarms before → after | Recall before → after | Cause fixed |
|---|---|---|---|---|
| Zombie Subscriptions | 0.9719 → 0.9980 | 29 → 2 | 1.0000 → 1.0000 | Similar charges picked out of a stream of weekly or irregular purchases at one shop were accepted as a "variable bill" subscription. |
| Phantom Invoices | 0.7742 → 1.0000 | 140 → 0 | 1.0000 → 1.0000 | A supplier's second valid IBAN in the master was ignored and raised a critical alert. |

- **A flaw in the benchmark itself.** The first run found only 9 of 84 planted duplicate subscriptions. The detector was right: the generator had planted the pairs at dates that ended before the ledger did. The generator was fixed, not the detector.
- **Limits.** The data is synthetic and the labels were written by the same team as the requirements, so a pattern nobody thought of is not planted. Only plain CSV is benchmarked. The 2 remaining zombie false alarms (both on `weekly_groceries_irregular`) are a documented limit. The numbers describe this mix of scenarios, not real bank data.
- **Reproduce.** `python scripts/benchmark.py` rewrites `data/benchmark/results.json` and `docs/benchmark.md` (under a minute); `python scripts/benchmark.py --check` reruns and compares them byte for byte with the committed files. The showcase has a Benchmark page that shows the results file.

## The three apps

All three apps are built on the same `ledger_kit` library and share nothing else.

**Zombie Subscriptions** (`apps/zombie_subscriptions/`) is for individuals. It reads a bank statement and finds forgotten subscriptions. The registered detectors are `zs.recurring_charge`, `zs.price_increase`, `zs.duplicate_subscription`, `zs.free_trial_to_paid` and `zs.charges_after_cancellation`. It also shows the cost of a service since its last-used date as a tombstone card. With the demo data loaded in the browser it shows 3 tombstones and 19 alerts: 1 critical, 4 warning and 14 info.

**Phantom Invoices** (`apps/phantom_invoices/`) is for small Spanish businesses. It reads invoices, a supplier master and bank payments and finds duplicate invoices (`pi.duplicate_invoice`), supplier IBAN changes and invalid IBANs (`pi.iban_change`), VAT errors (`pi.vat_error`), and overdue invoices or payments that match no invoice (`pi.reconciliation`). With the demo data loaded it shows 9 alerts: 3 critical and 6 warning. The end-to-end test `apps/phantom_invoices/tests/test_pi_demo_e2e.py` pins this split.

**Vampire Fees** (`apps/vampire_fees/`) is for individuals and small businesses. It reads a bank statement and finds the bank fees that drain an account: recurring fees (`vf.recurring_fee`), fees that rise (`vf.fee_increase`), the cost of an overdraft (`vf.overdraft_cost`) and the total (`vf.fee_summary`). Each recurring fee is drawn as a coffin card. Refunds are not subtracted from its totals, and only EUR rows are analysed. The details are below.

### Vampire Fees in detail

- **What it reads.** A bank statement as CSV or Norma 43. For Norma 43 it also uses the common concepts 16 and 17 that the bank writes on each movement, so a fee with an unusual wording is still found.
- **Demo numbers.** With the Norma 43 demo (`data/samples/vampire_demo_statement.n43`) the page shows 45 fees, a total of 379,25 EUR and a yearly equivalent of 207,54 EUR, with the coffin cards and 45 cited rows from that file. The matching CSV demo is `data/samples/vampire_demo_statement.csv`.
- **Template proof.** It was built as the third app, only from the finished template, by the Kiro custom agent `ghost-ledger-builder` (`.kiro/agents/ghost-ledger-builder.json`), with no change to `ledger_kit/` or to the other two apps (checked with `git diff`). It took 6 Kiro calls (5 productive) and about one hour from the first spec prompt to a working, tested app. The one copy of code between apps is listed as a decision in `.kiro/specs/vampire-fees/design.md`; the full record is task VF17 in `.kiro/specs/vampire-fees/tasks.md`.

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
streamlit run apps/vampire_fees/app.py
```

In any app, click **Load demo data** in the sidebar if it has not loaded by itself. The CSV demo files are `data/samples/zombie_demo_statement.csv`, `data/samples/vampire_demo_statement.csv` and the three files in `data/samples/phantom_demo/`; the real-format versions are described above. You can also upload your own files in the sidebar.

**Optional LLM.** `.env.example` documents `OPENAI_API_KEY`. The code reads it from the process environment and does not load a `.env` file, so set it in your shell before starting Streamlit (PowerShell: `$env:OPENAI_API_KEY = "your-key"`). Without a key every explanation is the fixed template filled from the alert, and the number guard still runs on whatever a client returns.

### Scan files from the command line

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
docs/                  benchmark.md (generated), live-guard.md, mcp-api-checks.md (library API checks made through MCP)
tests/                 tests of the shared library and the showcase
streamlit_app.py       showcase entry page
```

`ledger_kit` never imports from the apps, and the three apps never import from each other. The full layout and naming rules are in `.kiro/steering/structure.md`.

## Who did what

This is a student project. I set the goal, picked the idea from two options an AI coding assistant drafted, and steered it from there: the Spanish formats, the real-model test and the adversarial reviews were my calls. Kiro wrote the code. The assistant drafted the prompts, ran the tests and, under my general go-ahead, made the overnight fixes the reviews asked for. The table says who proposed and who decided each choice.

- **Me (Alessandro Lair, student):** chose to build for Spanish bank and invoice data instead of a generic money app; turned down the first version as too simple and asked for the official formats (Norma 43, Facturae), public data (INE CPI) and a measured benchmark; asked for the guard to be tested against a real model before the video and approved running one locally; asked for an adversarial review against past winners before recording; decide what is published and when.
- **Kiro (CLI, spec mode and a custom agent):** wrote every spec, test and line of code in this repository.
- **Claude Code (AI coding assistant):** proposed options, drafted the prompts and sent them to Kiro CLI on my account, ran the tests and the benchmark, and sent every failure back to Kiro.

| Date | Decision | Proposed by | Decided by |
|---|---|---|---|
| 23 Oct | Build Ghost Ledger Kit (Skeleton Crew) and not a COBOL tool, after reading the 2025 gallery | Claude Code (two options: this kit or a COBOL tool) | Me |
| 6 Nov | Hand the building to Kiro CLI, driven by the assistant, instead of the IDE | Me (to delegate), Claude Code (the CLI route) | Me |
| 9 Nov | Version 1 is too simple: add the official formats, INE data and a benchmark | Me (the concern), Claude Code (the three additions) | Me |
| 9 Nov | Turn on the Context7 MCP server | Claude Code | Me |
| 10 Nov | Test the guard against a real model, locally with Ollama | Claude Code | Me |
| 10 Nov | Adversarial review against past winners before the video | Me | Me |
| 12 Nov | Make the hooks run in the CLI build (lint after every write, tests on stop, a log in the repo) | Claude Code, after the adversarial review found that the hooks never ran | Claude Code, within my general go-ahead to keep improving the project |
| 13 Nov | Read number words in the guard, and make the Home example a real invention, after a fresh jury showed that 539.40 is right arithmetic and that five hundred and forty euros passed | Claude Code, after the fresh jury | Claude Code, within my go-ahead to keep working through the night |
| 13 Nov | Give each app its own drawing on every alert card (a pulse for Zombie, bites for Vampire, a lantern for Phantom), drawn only from the cited rows and checked by the number guard, after the fresh jury found the three apps looked the same | Claude Code, after the fresh jury | Claude Code, within my go-ahead to keep working through the night |
| 15 Nov | Home with one clear moment: the recorded invention appears and the guard strikes it out in under three seconds; the rest of the text moves into How it works; each app tile shows its own drawing | the adversarial review of 14 Nov, drafted by Claude Code | Me |
| 15 Nov | The model asks, the kit computes: placeholders that the kit evaluates from the alert fields, shown with their formula | the adversarial review of 14 Nov, drafted by Claude Code | Me |

## How we used Kiro

| Kiro feature | What we did | Why it mattered |
|---|---|---|
| Specs | 18 specs in `.kiro/specs/`, each with `requirements.md`, `design.md` and `tasks.md`: `ledger-core`, `zombie-subscriptions`, `phantom-invoices`, `showcase`, `public-cpi` (INE price-index context), `real-formats` (Norma 43 and Facturae), `benchmark`, `detector-fixes` (the corrections the benchmark found), `vampire-fees` (the third app), `live-guard` (the Provoke the LLM panel), `haunted-design` (the look), `judge-path` (recorded real answers for visitors without a key), `exorcise` (action drafts), `scan-command` (the command-line scan), `cli-hooks` (the hooks that run in the CLI), `guard-honesty` (numbers written in words, an honest Home example and labels), `app-signatures` (a drawing per app on every alert card, from the cited rows only) and `model-computes` (the model names a calculation, the kit computes it from the alert fields and shows the formula). Tasks are ticked off as work was done. Amendments are recorded in the specs, for example REQ-PI-09 and REQ-ZS-10a; A-LG-01 to A-LG-03 in `live-guard` came from real model answers. | Each rule that keeps figures honest (cite the source row, no invented number) is a numbered requirement with a test, so the promise is written down before the code. |
| Steering | Six files in `.kiro/steering/`. Five are always included: `product.md`, `tech.md`, `structure.md`, `testing.md` and `finance-rules.md`. One is manual: `update-kiro-usage.md`, used to rewrite this section. | `finance-rules.md` makes "never invent a figure, always cite the source row" binding on every change, and it carries the exact no-invention wording the explainer prompt must use. |
| Hooks | `.kiro/hooks/review-gate.json` holds two Kiro CLI hooks written on 12 Nov (spec `cli-hooks`): `lint-after-write` (PostToolUse on the write tools: `ruff check` and `ruff format --check` on each `.py` file Kiro writes, and the findings go back to Kiro) and `tests-on-stop` (Stop: `ruff check .` and `pytest` on the test folders of the parts Kiro touched; it always exits 0). Every run adds a line to `data/hook_runs/hook_log.jsonl`. They loaded during the call that wrote them: 12 writes in that call, 8 of them lint runs on the test file being written (`tests/test_kiro_hooks.py`), 4 non-Python files skipped, then once on stop. All 8 lint runs failed: each reported E501 (line too long), and one also reported F821 (undefined name), which was gone from the next write; the E501 was fixed in the following call. The stop run reported the same E501 and ran 2,137 tests, all passing. In the next call the stop run caught a README test that failed, and the call after that fixed it. The three IDE hook files, `detector-guard.kiro.hook`, `samples-sync.kiro.hook` and `kiro-usage.kiro.hook`, are not read by the CLI, so they never ran here; they are kept for anyone who opens the repo in the Kiro IDE. | In this build Kiro has no shell, so it could not run `ruff` or the tests itself; the hooks gave it that feedback without giving it a shell, and the log shows when they ran. |
| MCP | The context7 MCP server (remote, no API key) is configured in `.kiro/settings/mcp.json` after the developer approved it. The agent used it in sessions 5c, to check the Streamlit, pandas and Hypothesis behaviour the code relies on (results in `docs/mcp-api-checks.md`, no mismatch), and 8a, to look up `defusedxml` before writing the Facturae reader (notes in section 6 of `.kiro/specs/real-formats/design.md`). | Library APIs change between releases, so the assumptions behind the code were checked against current docs instead of memory. |
| Property-based testing | Hypothesis tests with `max_examples=200` in `tests/` and in `apps/*/tests/`. The no-invention property uses `loaded_source_refs` from `ledger_kit/detectors/` and asserts that every cited `source_ref` belongs to a loaded input; see `apps/phantom_invoices/tests/test_pi_vat_error.py` and `apps/zombie_subscriptions/tests/test_zs_price_increase.py`. | It checks the core promise on generated inputs, including dirty cells, not only on hand-picked examples: no alert may cite a row that was not loaded. |
| Powers | One local power, `powers/ghost-ledger-detector/`, with the `add-detector` skill in `powers/ghost-ledger-detector/skills/add-detector/SKILL.md`. The skill was loaded into the custom agent through a `skill://` resource in `.kiro/agents/ghost-ledger-builder.json`. | It teaches an agent to add a new detector the same way as the existing ones, with the namespaced registration, source refs and tests, so a new detector keeps the contract. |
| Custom agent | `.kiro/agents/ghost-ledger-builder.json` with its prompt `.kiro/agents/ghost-ledger-builder.md`. It loads the five always-included steering files, `update-kiro-usage.md`, `README.md` and the `add-detector` skill, and may use the context7 MCP server. It reads and writes files only, so it cannot run commands. It built the Vampire Fees app (`apps/vampire_fees/`). | The agent starts with the finance rules in its context and a hard boundary (no edit of `ledger_kit/` or another app), so a new app inherits the no-invention contract; `git diff` showed zero changes to the library and the other two apps. |
| Kiro CLI | Built non-interactively in spec mode, one fresh conversation per phase; the reviewer ran the tests between calls. | Different from the IDE: it does not read the IDE hook files but runs the JSON hooks in `.kiro/hooks/`, no panels, scriptable, and every call is a prompt file in `kiro_prompts/` and can be rerun with `run_kiro.ps1`. |
| Spec-driven versus vibe coding | Vampire Fees was built by the custom agent from its spec with zero changes to `ledger_kit/` and the other apps. The benchmark found two detector bugs, fixed in the `detector-fixes` spec: precision 0.9719 → 0.9980 (Zombie Subscriptions) and 0.7742 → 1.0000 (Phantom Invoices), see `docs/benchmark.md`. Four recorded runs of real model answers in `data/live_runs/` exist; the first three led to A-LG-01 to A-LG-03 and their regression tests. | A written requirement can be checked by a test and by a diff; a chat request cannot. These numbers come from files in the repo. |

Kiro documentation: [kiro.dev/docs](https://kiro.dev/docs/).

## Data and licence

All demo and sample data in this repository is synthetic and generated by `scripts/generate_samples.py` with a fixed seed (42 by default), so regenerating gives the same bytes; this includes the Norma 43 and Facturae samples. There is no real personal or financial data; see `data/samples/README.md`.

- Company and person names are invented.
- IBANs pass the ISO 13616 mod-97 check but have deliberately wrong Spanish national check digits, so they cannot be real accounts.
- Spanish tax ids carry a wrong control character, a different one per fictional supplier.

The one exception is `data/public/`: official public data from the INE (the consumer price index), under CC BY 4.0, with its licence reference and attribution in `data/public/README.md` and in the section above. It contains no personal data.

Released under the MIT licence, see `LICENSE`. The INE data keeps the INE licence.

## Hackathon

Kiroween 2026, category Skeleton Crew: one template, three different apps (two of them read the same bank statement). A personal-finance tool for individuals, a bank-fee tool and an invoice-checking tool for small Spanish businesses are built on the same three layers and the same guarantee.

Tools used: [Streamlit](https://docs.streamlit.io/), [pytest](https://docs.pytest.org/), [Hypothesis](https://hypothesis.readthedocs.io/) and [Ruff](https://docs.astral.sh/ruff/).
