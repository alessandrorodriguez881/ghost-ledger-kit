# How Ghost Ledger Kit works

Back to the [README](../README.md).

## The problem

LLM agents invent figures when money is involved. Ask a model to explain a charge or an invoice and it can produce an amount, a date or an IBAN that looks right and is not in the data. In a finance tool that is worse than no answer, because nobody can tell which numbers are real.

Ghost Ledger Kit is built around one promise: an LLM touches the explanation layer only. Every figure it writes must be one the detectors already produced (the alert data) or one in a cited row, and every alert cites the rows it comes from, shown as `file · line N` (the internal key is `file:row`).

## How it works

Three layers, in this order. Each one only receives what the previous one produced.

1. **Ingestion** (`ledger_kit/ingestion/`). Bank statements (CSV or Norma 43), invoices (CSV, JSON or Facturae XML) and supplier lists are parsed into one canonical ledger; the content of a file, not its extension, picks the reader. Rows that fail validation are quarantined, not silently fixed. Every row gets a `source_ref` of the form `file:row`, the internal key, and a text file also gives the `source_line`: the line a person finds when opening the file in an editor, header = line 1. The cards show `file · line N`.
2. **Deterministic detectors** (`ledger_kit/detectors/`). Plain Python functions, no machine learning. Each takes the ledger and a read-only context and returns typed `Alert` objects. Detectors register themselves under a namespaced name (`zs.` for Zombie Subscriptions, `pi.` for Phantom Invoices, `vf.` for Vampire Fees) through `register` in `ledger_kit/detectors/registry.py`; `auto_discover` imports an app's detector modules and `run_all` runs them, isolating a failing detector so it cannot stop the others. Every alert lists the `source_refs` of the rows it comes from, and thresholds are named constants at the top of each detector module.
3. **Explainer** (`ledger_kit/explainer.py`, the only module that calls an LLM). The model gets the alert and the cited source rows, with a system prompt that forbids inventing numbers. Its answer then goes through a number guard: any number, date or IBAN-shaped token that is in neither the cited rows nor the alert's own data causes the answer to be rejected. The app then shows a fixed fallback template filled from the alert instead. The same fallback is used when there is no API key, no `openai` package, or the call fails.

The explanation is decorative. It never feeds back into the alert logic, and it cannot raise, change or dismiss an alert.

**The model asks, the kit computes.** When a question needs arithmetic, such as a total over five years, the model does not calculate: it writes a placeholder like `[[calc: yearly_cost * 5]]`, and `ledger_kit/calc.py` computes it in `Decimal` from the numeric fields of the alert and the whole numbers of the question. The card shows the result marked, with its formula (`5 x yearly_cost 107,88 EUR = 539,40 EUR`). What did not change: the guard still rejects any figure the model writes itself that is not in the cited rows or the alert data, and an expression with an unknown field, a number the question does not contain, a power or a division by zero sends the card back to the fixed template. The other numbers must come from the question, with one amendment: a number written with a decimal point that equals exactly one numeric field of the alert is read as that field (that is why GYMPLUS shows `yearly_cost` although the model wrote 107.88). The spec is `.kiro/specs/model-computes/`.

**The proof is a switch.** Each of the three apps has a sidebar toggle, *Simulate a hallucinating LLM*. It replaces the model with a stub that always answers with an invented figure (99999.99). The number guard rejects it, the card shows the fixed template, and a warning badge appears. No API key is needed.

**No key needed, real model output.** `data/live_runs/2026-11-16_llama3.2-3b_calc2.json` holds the raw answers that `llama3.2:3b` gave on the synthetic demo data, recorded on 16 Nov with the placeholder rule; it is the run the apps replay, and the older runs stay committed as the history that the specs cite. Without a key, a card shows the recorded answer of that alert if today's number guard accepts it, and the fixed template if not; the badge says which. The *Provoke the LLM* panel replays recorded answers only on the first critical card of each app (GYMPLUS in Zombie Subscriptions, the Suministros Ibéricos duplicate invoice in Phantom Invoices, the overdraft in Vampire Fees), because only there were the three questions recorded; it replays them with the figures the kit computed and their formula. On every other card the panel is disabled and shows the live-model-off message. No model is called and no network is used, and the captions say so. Home shows a 10 Nov recording (the 5% invention) while the apps replay the 16 Nov run, so the same card can show a different recorded answer in the app. With a key set, the apps call the model as before. To re-record, run `scripts/record_live_run.py` with the kit's own Python and a local model set up as in `docs/live-guard.md`: it asks every demo card once and the three trick questions, and writes a new file. A recording holds the raw answers of one run, not a rate.

**The proof, live.** With a key set, every alert card has a *Provoke the LLM* panel: three preset questions that tempt a model to state a figure that is not in the cited rows. It uses the model set through `OPENAI_API_KEY` (a local model through Ollama works too), shows the raw answer, marks the rejected tokens and shows the fixed template next to it. In general, small local models invent figures more often than large hosted ones, so a rejection is the likely outcome. The guard checks figures, dates and IBAN-shaped tokens only and does not judge wording: an accepted answer is not a statement that it is true, and a harmless count such as `3 months` is rejected too. The first call to a local model can take longer than the 10 seconds allowed, so warm it up first. Steps for Windows with Ollama are in `docs/live-guard.md`.

## The three apps

All three apps are built on the same `ledger_kit` library and share nothing else.

**Zombie Subscriptions** (`apps/zombie_subscriptions/`) is for individuals. It reads a bank statement and finds forgotten subscriptions. The registered detectors are `zs.recurring_charge`, `zs.price_increase`, `zs.duplicate_subscription`, `zs.free_trial_to_paid` and `zs.charges_after_cancellation`. It also shows the cost of a service since its last-used date as a tombstone card. With the demo data loaded in the browser it shows 3 tombstones and 19 alerts: 1 critical, 4 warning and 14 info.

**Phantom Invoices** (`apps/phantom_invoices/`) is for small Spanish businesses. It reads invoices, a supplier master and bank payments and finds duplicate invoices (`pi.duplicate_invoice`), supplier IBAN changes and invalid IBANs (`pi.iban_change`), VAT errors (`pi.vat_error`), and overdue invoices or payments that match no invoice (`pi.reconciliation`). With the demo data loaded it shows 9 alerts: 3 critical and 6 warning. The end-to-end test `apps/phantom_invoices/tests/test_pi_demo_e2e.py` pins this split.

**Vampire Fees** (`apps/vampire_fees/`) is for individuals and small businesses. It reads a bank statement and finds the bank fees that drain an account: recurring fees (`vf.recurring_fee`), fees that rise (`vf.fee_increase`), the cost of an overdraft (`vf.overdraft_cost`) and the total (`vf.fee_summary`). Each recurring fee is drawn as a coffin card. Refunds are not subtracted from its totals, and only EUR rows are analysed. The details are below.

## Vampire Fees in detail

- **What it reads.** A bank statement as CSV or Norma 43. For Norma 43 it also uses the common concepts 16 and 17 that the bank writes on each movement, so a fee with an unusual wording is still found.
- **Demo numbers.** With the Norma 43 demo (`data/samples/vampire_demo_statement.n43`) the page shows 45 fees, a total of 379,25 EUR and a yearly equivalent of 207,54 EUR, with the coffin cards and 45 cited rows from that file. The matching CSV demo is `data/samples/vampire_demo_statement.csv`.
- **Template proof.** It was built as the third app, only from the finished template, by the Kiro custom agent `ghost-ledger-builder` (`.kiro/agents/ghost-ledger-builder.json`), with no change to `ledger_kit/` or to the other two apps (checked with `git diff`). It took 6 Kiro calls (5 productive) and about one hour from the first spec prompt to a working, tested app. The one copy of code between apps is listed as a decision in `.kiro/specs/vampire-fees/design.md`; the full record is task VF17 in `.kiro/specs/vampire-fees/tasks.md`.

The demo numbers are pinned by tests: `apps/zombie_subscriptions/tests/test_zs_demo_e2e.py` and `apps/phantom_invoices/tests/test_pi_demo_e2e.py` run the demo end to end, and `tests/test_showcase_app.py` checks the alert counts shown in the showcase.

## Benchmark: does it catch what it should, and stay quiet when it should?

`scripts/generate_benchmark.py` builds, from a seed, 200 synthetic scenarios per app (Zombie Subscriptions and Phantom Invoices; 40 of them clean). Each plants known problems with labels (a duplicate invoice, a changed IBAN, a forgotten subscription) next to 14 hard negatives per app: look-alike clean cases such as weekly groceries, two legitimate IBANs of one supplier or a late but full payment. The scenarios go through the same pipelines the apps run. **Matching rule:** an alert is a true positive when an unmatched label of the same type shares at least one `source_ref` with it; every other alert is a false alarm and every unmatched label a miss. There is no pass mark; the numbers are reported, not gated.

It found real weaknesses, which the `detector-fixes` spec then corrected without changing any threshold, label or hard negative (seed 2026, 200 scenarios per app):

| App | Precision before → after | False alarms before → after | Recall before → after | Cause fixed |
|---|---|---|---|---|
| Zombie Subscriptions | 0.9719 → 0.9980 | 29 → 2 | 1.0000 → 1.0000 | Similar charges picked out of a stream of weekly or irregular purchases at one shop were accepted as a "variable bill" subscription. |
| Phantom Invoices | 0.7742 → 1.0000 | 140 → 0 | 1.0000 → 1.0000 | A supplier's second valid IBAN in the master was ignored and raised a critical alert. |

- **A flaw in the benchmark itself.** The first run found only 9 of 84 planted duplicate subscriptions. The detector was right: the generator had planted the pairs at dates that ended before the ledger did. The generator was fixed, not the detector.
- **Limits.** The data is synthetic and the labels were written by the same team as the requirements, so a pattern nobody thought of is not planted. Only plain CSV is benchmarked. The 2 remaining zombie false alarms (both on `weekly_groceries_irregular`) are a documented limit. The numbers describe this mix of scenarios, not real bank data.
- **Reproduce.** `python scripts/benchmark.py` rewrites `data/benchmark/results.json` and `docs/benchmark.md` (under a minute); `python scripts/benchmark.py --check` reruns and compares them byte for byte with the committed files. The showcase has a Benchmark page that shows the results file.

The generated results are in [benchmark.md](benchmark.md).
