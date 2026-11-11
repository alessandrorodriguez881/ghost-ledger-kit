# scan-command — Requirements

## Overview

A separate program (Night Watch, a Kiro Crew app in its own repository) will watch a folder and
check every new bank statement or invoice with this kit. It must not install the kit into its own
Python, because the kit pins `pandas` and `streamlit` and they could clash with the packages of
that program. So it calls the kit as a **command** run with the kit's own Python, and reads JSON
on stdout.

`scripts/ledger_scan.py` is that command. It has two subcommands:

- `scan FILE [FILE ...]` finds out what each file is, runs the same pipelines the three pages run
  and prints every alert with its fixed text, its cited rows and its Exorcise drafts.
- `check --alert-id ID --text TEXT FILE [FILE ...]` reruns the scan and applies the number guard
  to a text for one alert.

It adds no detector, changes no figure, no alert text, no number-guard rule, no app and no page,
and adds no dependency. It calls no model and opens no connection.

Ids are `REQ-SCAN-nn` (the prefix `SC` belongs to the showcase spec). EARS keywords: *shall*,
*when*, *while*, *where*, *if ... then*. All data in examples is **(synthetic)**: the committed
demo files of `data/samples/`.

## Shared vocabulary

- **Page pipeline**: the `run_pipeline` function of an app's `settings.py`, the one its page calls.
- **Fixed text**: the card text without a model, `fill_fallback(template_for(alert), alert)`.
- **Visible columns**: the columns of the cited rows that the page shows for that alert.
- **Guard check**: `ledger_kit.explainer.check_figures(text, alert, rows, row_columns)`.

---

## 1 — Boundaries

- **REQ-SCAN-01** The command shall call no language model, read no API key and open no
  connection, and shall import nothing outside the standard library and the packages the kit
  already requires.
  - Example: with `OPENAI_API_KEY` set and `sys.modules["openai"] = None`, the output is the same.

- **REQ-SCAN-02** The command shall change no file of `ledger_kit/`, of the three apps or of the
  pages, and shall write nothing to disk. It lives in `scripts/ledger_scan.py` and is loaded by
  path in tests like the other scripts.

## 2 — Command line

- **REQ-SCAN-03** The command shall offer exactly two subcommands, built with the standard library
  `argparse`:
  - `scan FILE [FILE ...] [--suppliers CSV] [--payments FILE] [--as-of YYYY-MM-DD]`
  - `check --alert-id ID --text TEXT FILE [FILE ...] [--suppliers CSV] [--payments FILE] [--as-of YYYY-MM-DD]`

- **REQ-SCAN-04** The exit code shall be 0 when the command ran, even if a file could not be read
  or an alert id was unknown, and 2 when the arguments are bad. *If* the arguments are bad
  *then* nothing shall be written to stdout.
  - Example: no subcommand, `scan` with no file, `check` without `--alert-id` or `--text`, an
    unknown subcommand, `--as-of yesterday`, `--as-of 2026-02-30` and `--as-of 20261111` all exit
    with 2.

- **REQ-SCAN-05** The command shall be runnable from any working directory with the Python of the
  kit's virtual environment: `python <path>/scripts/ledger_scan.py scan FILE`.

## 3 — What a file is

- **REQ-SCAN-06** The command shall find the kind of each `FILE` from its content, never from its
  extension, with `ledger_kit.ingestion.sniffer.sniff_format`:
  - Norma 43 → `bank_statement`; JSON and Facturae XML → `invoice`;
  - CSV whose first line has the column `invoice_number` → `invoice`; CSV whose first line has the
    column `counterparty` (and not `invoice_number`) → `bank_statement`;
  - an empty file → `empty` (no alert, no error); any other file → `unknown` with an error.
  - Example: `data/samples/phantom_demo/invoices.csv` → `invoice`;
    `data/samples/zombie_demo_statement.n43` → `bank_statement`.

- **REQ-SCAN-07** The files given with `--suppliers` and `--payments` shall be reported with the
  kinds `supplier_master` and `payments`, and shall be used only by the invoice checks.

## 4 — Which pipeline runs

- **REQ-SCAN-08** *When* a file is a bank statement, the command shall run on it the Zombie
  Subscriptions page pipeline and the Vampire Fees page pipeline. The Zombie run shall have no
  aliases and no cancellation dates, so the detectors that need them do not fire, and shall carry
  the CPI context the page loads from the committed snapshot.

- **REQ-SCAN-09** *When* there are invoice files, the command shall run the Phantom Invoices page
  pipeline **once** on all of them together, with the optional supplier master, the optional
  payments file and the optional `--as-of` date (default: none, as the page).
  - Example: two Facturae files from one supplier are checked together for duplicates.

- **REQ-SCAN-10** The `source_file` of every row shall be the base name of the path, as when a page
  receives an upload, so that **the alert ids equal the ids the pages show** for the same file
  names and inputs.
  - Example: `scan data/samples/vampire_demo_statement.csv` gives the same Vampire alert ids as the
    Vampire page with its CSV demo.
  - Example: `scan` of the CSV Phantom demo (invoices, `--suppliers`, `--payments`) gives the same
    nine alert ids as the Phantom page with its CSV demo.

## 5 — Failure isolation

- **REQ-SCAN-11** *If* a file cannot be read, is in no known format, or makes its pipeline fail,
  *then* the command shall report that file with an `error` text and continue with the others.
  - Example: `scan missing.csv zombie_demo_statement.csv` → the first file has `error` and
    `sha256: null`; the Zombie alerts of the second are all there; exit code 0.

## 6 — Output

- **REQ-SCAN-12** The command shall print one JSON object to stdout with the keys, in this order:
  `kit_version`, `files`, `alerts`. `kit_version` is the installed version of `ledger-kit`, or
  `0.0.0` when the kit is not installed as a package.

- **REQ-SCAN-13** Each entry of `files` shall have, in this order: `path` (as given), `sha256` (of
  the bytes), `kind`, `format` (the sniffed format), `rows`, `quarantined`, `error`. `rows` is the
  number of rows read into the ledger of that file, `quarantined` the number of rows put aside.

- **REQ-SCAN-14** Each entry of `alerts` shall have, in this order: `alert_id`, `app`
  (`zombie_subscriptions`, `vampire_fees` or `phantom_invoices`), `detector`, `severity`, `title`,
  `text`, `source_refs`, `rows`, `drafts`.
  - `text` is the fixed text of the alert.
  - `rows` are the cited rows with the visible columns only: for Zombie and Vampire the columns of
    the page table (`source_ref`, `date`, `amount`, `flow`, `counterparty`, `description`, `iban`;
    IBAN masked); for Phantom the columns of the page ledger, supplier-master and payments views
    (IBAN masked, no tax id). Rows follow the ledger order (Zombie, Vampire) or the order of
    `source_refs` (Phantom).
  - `drafts` is `{"en": ..., "es": ...}` built by `ledger_kit.actions.build_draft` with the
    template and the rows the page uses, or `null` when the alert type has no template. A draft
    the number guard rejects is `null` in its language.

- **REQ-SCAN-15** Money in the output shall be the text the kit formats (`format_amount`, European
  notation, for example `14,99 EUR`), dates shall be ISO `YYYY-MM-DD`, and no amount shall be a
  JSON number.

- **REQ-SCAN-16** The output shall be stable: keys in the fixed order above; `files` in the order
  given (then the supplier master, then the payments file); `alerts` ordered by severity
  (`critical`, `warning`, `info`), then by `title`, then by `app`, `detector` and `alert_id`; ASCII
  only (non-ASCII characters escaped). The same files and options shall give **byte-identical**
  output on two runs.

## 7 — check

- **REQ-SCAN-17** *When* `check` is run, the command shall rerun the scan, find the alert whose
  `alert_id` equals `--alert-id`, and apply the number guard of `ledger_kit.explainer` to `--text`
  for that alert, its cited rows and the same `row_columns` the page uses. It shall print
  `{"alert_id", "passed", "rejected", "error"}` in that order, with `rejected` the list of tokens
  the guard refused and `error` null.
  - Example: the `text` of the GYMPLUS `zs.recurring_charge` alert passes. The same text with
    `539.40` added fails and `539.40` is in `rejected`.

- **REQ-SCAN-18** *If* no alert has the id, *then* `check` shall print `passed` false, `rejected`
  `[]` and an `error` text, and shall exit with 0.

## 8 — Documentation

- **REQ-SCAN-19** `README.md` shall describe both subcommands under *Try it* and name the script
  in the project layout block.

## Acceptance examples (synthetic)

| Command | Result |
|---|---|
| `scan data/samples/zombie_demo_statement.csv` | Zombie and Vampire alerts of that statement; Zombie ids equal the page ids with no aliases and no cancellation dates |
| `scan data/samples/zombie_demo_statement.n43` | same, from Norma 43 |
| `scan data/samples/phantom_demo/invoices.csv --suppliers ...suppliers.csv --payments ...payments.csv` | the nine alerts of the Phantom CSV demo |
| `scan data/samples/phantom_demo/facturae/*.xml --suppliers ...suppliers.csv --payments ...payments.n43` | the alerts of the Phantom real-format demo |
| `scan missing.csv data/samples/zombie_demo_statement.csv` | `error` on the first file, all alerts of the second, exit 0 |
| `check --alert-id <GYMPLUS id> --text "<its text>" <statement>` | `passed: true` |
| `check --alert-id <GYMPLUS id> --text "... 539.40 ..." <statement>` | `passed: false`, `rejected: ["539.40"]` |
| `check --alert-id 000...0 --text x <statement>` | `passed: false`, `error` set, exit 0 |
| `scan` | usage on stderr, exit 2 |
