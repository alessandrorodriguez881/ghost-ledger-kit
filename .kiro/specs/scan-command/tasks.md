# scan-command — Implementation Tasks

Every task is test-first: write the tests, see them fail for the right reason, then implement.
Section references (§) point to `design.md`, REQ ids to `requirements.md`. Verification
(`ruff check .`, `ruff format --check .`, `pytest`) is run by the user: this session could not run
commands. Tasks run in order.

## Task SCAN1 — Command line, files and `scan`

**Covers**: REQ-SCAN-01 to 16, §1 to §4

- [x] Create `tests/test_ledger_scan.py` (loads `scripts/ledger_scan.py` by path): the alert ids
  and counts of the Zombie, Vampire and Phantom demos, CSV and real formats, equal the ids of the
  page pipelines; file reports (hash, kind, format, counts); key order; alert order by severity
  then title; money as European text and dates in ISO form; cited rows are a subset of
  `source_refs`; drafts are `en`/`es` or `null`; two runs give identical bytes; a key and a
  blocked `openai` change nothing; an unreadable file, a file in no known format, an empty file
  and an unreadable supplier master are reported and the others run.
- [x] Create `scripts/ledger_scan.py` (§2, §3): `load_file`, `classify`, `scan_files` with the
  three pipelines, `scan_json`, `main`.

## Task SCAN2 — `check` and argument errors

**Covers**: REQ-SCAN-03, 04, 17, 18

- [x] In `tests/test_ledger_scan.py`: `check` accepts the fixed text of the GYMPLUS
  `zs.recurring_charge` alert, rejects a text with `539.40` and names the token, and answers an
  unknown id with `passed` false and an error text; bad arguments (ten cases) exit with 2 and write
  nothing to stdout.
- [x] Add `check_json` and the `check` subcommand to `scripts/ledger_scan.py`.

## Task SCAN3 — As a real command

**Covers**: REQ-SCAN-01, 05

- [x] In `tests/test_ledger_scan.py`: run the script with `sys.executable` from a temporary
  directory: exit 0 and the same bytes as the in-process run; `scan` alone exits with 2 and prints
  nothing to stdout; the source holds no network or model word.
- [x] Make the script put the repository root on `sys.path` before the kit imports.

## Task SCAN4 — Documentation

**Covers**: REQ-SCAN-19

- [x] Add the section *Scan files from the command line* under *Try it* in `README.md` and one
  entry for `ledger_scan.py` in the layout block. No other file of the project changes.
