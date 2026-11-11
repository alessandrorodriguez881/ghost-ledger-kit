# scan-command — Design

Requirements are in `requirements.md` (`REQ-SCAN-nn`). Decisions are `DN-SCAN-nn`.

## 1 — Shape

One new file, `scripts/ledger_scan.py`, standard library plus code the kit already has. It is a
script, not a package module: `scripts/` is not a package, so tests load it by path, like
`benchmark.py`. At the top it adds the repository root to `sys.path` (as `benchmark.py` does) so
`python scripts/ledger_scan.py` works from any directory.

```
argv ──argparse──► scan_files(paths, suppliers, payments, as_of) ──► Scan(files, found)
                        │                                              │
        load_file ×N    │   bank statement ─► zs run_pipeline + vf run_pipeline
        (read, sha256,  │   invoice files ──► pi run_pipeline (once, all together)
         sniff, classify)│                                             ▼
                                                  scan_json / check_json ──► stdout (JSON)
```

## 2 — Pieces

| Piece | Job |
|---|---|
| `load_file(path, kind=None)` | read the bytes (an `OSError` becomes an `error` text), hash them, sniff the format, classify the kind |
| `classify(data, sniffed)` | `norma43` → statement; `json`, `facturae` → invoice; `csv` → by the header (`invoice_number` or `counterparty`); else `unknown` |
| `_scan_statement(report)` | Zombie `run_pipeline` (empty aliases and dates, CPI from the committed snapshot) and Vampire `run_pipeline` on the same bytes and base name |
| `_scan_invoices(...)` | Phantom `run_pipeline(sources, suppliers, payments, as_of)` once; per-file counts from the normalised frame and the quarantine |
| `Found` | one alert plus what its card holds: the rows the page hands to the guard and the draft, `row_columns`, the visible cited rows, the fixed text, the Exorcise template |
| `alert_json`, `scan_json`, `check_json`, `dumps` | the output, with the key order of the requirements |
| `main(argv, out)` | parse, run, write one JSON document; returns 0 (argparse exits with 2) |

## 3 — What each app contributes

| App | Pipeline (as the page calls it) | Rows given to guard and draft | Visible rows | Text | Template |
|---|---|---|---|---|---|
| Zombie | `zs_settings.run_pipeline(name, bytes, aliases=normalise_alias_map({}), cancellation_dates=normalise_date_map({}), cpi=load_cpi(...))` | `debit_ledger` rows cited, no `row_columns` | `format_for_display(rows_for_refs(...))` | `fill_fallback(zs_support.template_for(alert), alert)` | `zs_actions.action_for` |
| Vampire | `vf_settings.run_pipeline(name, bytes, vocabulary=...)` | `ledger` rows cited, no `row_columns` | same | `vf_support.template_for` | `vf_actions.action_for` |
| Phantom | `pi_settings.run_pipeline(sources, suppliers, payments, as_of)` | `pi_support.build_explain_rows(...)`, `row_columns=ROW_COLUMNS` | `ledger_view` + `cited_master_view` + `cited_payments_view` | `pi_support.template_for` | `pi_actions.action_for` |

## 4 — Decisions

- **DN-SCAN-01 — Base name as `source_file`.** Alert ids hash the `source_refs`, which start with
  the file name. The pages receive an upload by name only, so the command passes
  `Path(path).name`. The ids then equal the page ids. Two files with one base name in different
  folders clash exactly as they do on a page (the Phantom run quarantines the second one as
  `duplicate_file_name`).
- **DN-SCAN-02 — The content of a CSV picks the app.** The sniffer separates CSV from JSON, XML
  and Norma 43 but cannot tell an invoice CSV from a statement CSV. The first line decides: the
  columns are exactly the ones the two readers require (`invoice_number`, `counterparty`), no
  guessing and no new reader.
- **DN-SCAN-03 — One Phantom run for all invoice files.** The duplicate check needs every invoice
  at once, and the page does the same with several uploads.
- **DN-SCAN-04 — Empty aliases and cancellation dates.** Night Watch has no user inputs. The
  detectors that need them see nothing and do not fire; this is the same state as a page with
  empty sidebar fields. The `normalise_*_map({})` calls are the page's own.
- **DN-SCAN-05 — The visible columns come from the page helpers.** `format_for_display` and
  `rows_for_refs` (from `ledger_kit/ui/reference_app.py`) and the Phantom `*_view` functions are
  imported, not copied, so a change to a page table changes the command. Importing
  `reference_app` imports Streamlit, which is installed in the kit's environment; it starts no
  server and prints nothing to stdout.
- **DN-SCAN-06 — No model in `scan`.** `text` is the filled template, never `explain_with_meta`,
  so the output cannot depend on a key, a server or a replay file.
- **DN-SCAN-07 — A draft the guard rejects is `null`.** `build_draft` returns `None` and logs one
  warning on stderr; the JSON keeps the language key with `null`.
- **DN-SCAN-08 — Stable bytes.** `json.dumps(..., indent=2, ensure_ascii=True)` with dicts built in
  the fixed order and no `sort_keys`; the alert sort key is
  `(severity rank, title, app, detector, alert_id)`, a total order. Nothing reads the clock.
- **DN-SCAN-09 — Failure isolation by catching `Exception` per group.** A statement is one group
  per file; the invoice files are one group. A failure puts the exception text on the files of that
  group and does not touch the alerts already found.
- **DN-SCAN-10 — `kit_version`.** `importlib.metadata.version("ledger-kit")`, falling back to the
  `0.0.0` of `[tool.setuptools_scm]` when the kit runs from a checkout that is not installed.
- **DN-SCAN-11 — Supplier master or payments without invoices** are reported but unused: only the
  invoice checks read them.

## 5 — Limits

- Only the committed demo files are tested; a real statement may produce other alerts.
- `rows` of a Phantom file counts the invoice rows read for that base name after the multi-rate
  quarantine; `quarantined` counts the quarantine records tagged with that name.
- The command does not verify Facturae signatures (the Phantom page does not either).

## 6 — Tests

`tests/test_ledger_scan.py`, test-first, no network, no key:

- Tier 1: ids and counts of the CSV and real-format demos of the three apps equal the page
  pipelines (and the judge-path helpers); file reports; key order; alert order; money and dates.
- Tier 2: two runs give identical bytes; an unreadable file, a file in no known format and an empty
  file; an unreadable supplier master; `--as-of`; key and `openai` in the environment change
  nothing; argparse errors exit with 2; the script runs as a subprocess from another directory
  and prints the same bytes.
- `check`: accepts the fixed text of the GYMPLUS alert, rejects `539.40`, unknown id.
