# public-fees — Implementation Tasks

Every task is test-first: write the tests named in the task, see them fail, then implement. Section
references (§) point to `design.md`, REQ ids to `requirements.md`. Hypothesis tests use
`settings(max_examples=200)`. Nothing reads the clock, the network or an Excel file (PF8 uses synthetic grids
and a fake `xlrd`, amendment A1). Verification (`ruff check .`, `ruff format --check .`, `pytest`, a headless run of the
Vampire Fees app and of `streamlit_app.py`) is run by the user; the author of the spec ran nothing and wrote only
the three spec files.

**State when this spec was written: `data/public/bde_payment_account_fees.json` does not exist and the BdE Excel has
not been downloaded.** PF0 to PF7 need neither: they use **synthetic** fixtures and are complete without the real
data. PF8 and PF9 were **BLOCKED** until the Excel existed (decision Q4); the Excel is exported **by hand**, never by
automated access to the Banco de España site (decision Q6). **Amendment A1 (23 November 2026, end of this file):** the
Excel files exist outside the repository; PF8 is **unblocked**; PF9 stays a manual developer step. PF10 applies the steering edits the reviewer approved on
23 November 2026 (decision Q1).

Order: PF0 (alert id) → PF1 (money) → PF2 (reader) → PF3 (matching) → PF4 (detector) → PF5 (template and card
helpers) → PF6 (app) → PF7 (docs and `.gitignore`) → PF8 (importer) → PF9 (real snapshot, manual) →
PF10 (steering, final checks). PF0 must be done before PF4; PF1 to PF3 do not depend on it. PF8 depends on PF2 only
(the validator) and may be done before PF4 to PF7 (amendment A1). A later task may start
before an earlier one only where it says so.

Convention for every task that adds a module: all public functions and classes have type annotations and a one-line
docstring; lines are at most 100 characters; constants are named and commented (Finance Rule 7).

## Task PF0 — The alert id leaves out the `peer_*` keys (decision Q7, DN-PF-17)

**Covers**: REQ-PF-11, REQ-PF-13, DN-PF-17

- [x] Tests in `tests/test_alert_id_peer_keys.py` (the existing `tests/test_models.py` is not edited and stays green):
  an alert with peer fields has the same id as the same alert without them; a different `peer_*` value gives the same
  id; the peer fields stay in `data`; only top-level keys with the exact prefix `peer_` are left out (`peer`, `peers`,
  `Peer_a`, `xpeer_a` and a nested `peer_a` still change the id); every other key still changes the id; an explicit id
  is kept. **Every existing alert id is unchanged**: for every alert of the three demos (`judge_path_support.cases_of`),
  the test checks that `data` has no `peer_` key and that the id equals the id of the formula before the change (the
  whole `data` hashed), and that the pinned `Z1_ALERT_ID` is still found. Hypothesis: for random data without `peer_`
  keys plus random `peer_*` keys, the id ignores the `peer_*` keys and equals the old formula.
- [x] In `ledger_kit/models.py`: one named constant `ALERT_ID_EXCLUDED_PREFIX = "peer_"` with its comment (the
  documented rule), and `_deterministic_alert_id` hashes `data` without the top-level keys that start with it. Nothing
  else in the model changes.

## Task PF1 — `median_amount` in `money.py`

**Covers**: REQ-PF-15, §5

- [x] Tests in `tests/test_money.py` (existing tests stay unchanged and green): every example of REQ-PF-15 (the twelve
  amounts → `18.00`; `[1.00, 2.00, 4.00]` and its reverse → `2.00`; `[12.00, 12.01]` → `12.01`; `[0.00, 0.01]` →
  `0.01`; `[7.50]` → `7.50`); `[]` raises `ValueError`; the input list is not mutated; the result has exactly two
  decimals. Hypothesis: for non-empty lists of two-decimal non-negative `Decimal`, `min <= result <= max`.
- [x] Add `median_amount` to `ledger_kit/utils/money.py` as in §5, using `round_to_cents`. No other function changes.

## Task PF2 — Reader and validator `ledger_kit/public_data/bde_fees.py`

**Covers**: REQ-PF-01 (shape), REQ-PF-02, REQ-PF-03 (committed-file checks), REQ-PF-06, REQ-PF-07, REQ-PF-08, §2, §3

- [x] Builders first: `tests/public_data/bde_builders.py` with `make_snapshot(accounts, rows, **overrides)` that fills
  the constants (the `attribution` is `attribution_for(declaration_date)`, decision Q1), `synthetic_s12()` (REQ-PF-07:
  15 accounts of `CNO`, 12 amounts, 3 asterisks, entities `9901` to `9915`, declaration date `2026-11-23`),
  `synthetic_s10()` (REQ-PF-12, service `401`) and a Hypothesis strategy for valid snapshots. Everything is
  **(synthetic)**; fixtures in `tests/public_data/conftest.py` (`synthetic_s12_snapshot`, `synthetic_s10_snapshot`).
- [x] `tests/public_data/test_bde_fees_validator.py`: `S12` and `S10` pass; every rejection of REQ-PF-02 with its exact
  message (format 2, bad date, `retrieved_on` before the declaration date, constants changed, an `attribution` whose
  date is not the declaration date, account type unknown / repeated / out of order / without account, `excel_files`
  missing a type / bad name / `size_bytes` 0 / `sha256` of 63 digits, account key not starting with its entity code,
  entity code with two names, repeated account, row naming an unknown account, unknown service `999`, extra key, empty
  concept, text with trailing space and with `\u00a0`, amount `6,5` and `-1.00` and `6.5`, `not_offered` with an amount,
  duplicate row, rows out of order); a value that is a JSON float where a string is expected. Hypothesis: a generated
  valid snapshot passes; removing an account that a row refers to fails.
- [x] `tests/public_data/test_bde_fees_reader.py`: the REQ-PF-07 examples on `S12` (all four); a type present with no
  rows for the service; only asterisks (`amounts=()`, `not_offered_count == account_count`); repeated `0.00` kept;
  `without_amount_count` for an account with a row that is neither amount nor asterisk; `ValueError` for an unknown
  type, an unknown service and an empty concept; `load_fee_snapshot` of a tiny valid temp file, of a missing file
  (`cannot read missing.json: file not found`), of invalid JSON, of a file that fails the validator
  (`invalid snapshot <path>: ...`); CRLF line endings load; `str(amount)` equals the stored string for every amount;
  `attribution_for("2026-11-23")` is the text of decision Q1; the module imports only the standard library (AST scan
  against `sys.stdlib_module_names`). Hypothesis: REQ-PF-08 properties.
- [x] `tests/public_data/test_bde_fees_snapshot.py` (committed file): every test is `skipif(not exists)` with the reason
  `snapshot not committed yet (PF9 is blocked)`; it runs the validator and the pinned checks of REQ-PF-03 (`CNO` and
  `COT` present (decision Q5), dates equal, constants equal, **51 distinct `CNO` entity codes if the declaration date is
  `2026-11-23` (BdE)**, no fee amount pinned). One extra test that does **not** skip: `DEFAULT_FEE_SNAPSHOT_PATH` ends
  with `data/public/bde_payment_account_fees.json`.
- [x] Create `ledger_kit/public_data/bde_fees.py` as in §3 and export the public names from
  `ledger_kit/public_data/__init__.py` (read the file first; the CPI names are unchanged). If `pyproject.toml` lists
  packages explicitly, nothing to add (the package exists); read `tests/test_packaging.py` first.

## Task PF3 — Config, services and matching

**Covers**: REQ-PF-09, REQ-PF-10, §6.2

- [x] Tests in `apps/vampire_fees/tests/test_vf_peer_support.py` (config part): `build_peer_services` on the table of
  REQ-PF-09 returns two services with folded phrases (`("mantenimiento", "cuenta")` is in the maintenance words); each
  error of REQ-PF-09 with its message (service `999`, `concept = "Periodicidad"`, empty `words`, missing `label`, a
  phrase with no letter); a `[peer_fees]` table with no sub-table gives `()`; the committed `config.toml` loads and
  gives exactly `maintenance` and `debit_card`; `default_account_type` is one of the five codes. The matching table of
  REQ-PF-10, row by row (each example is one parametrised case, with the `Fee` built through `classify_fee` or a small
  helper in `vf_builders.py`); accents and case (`COMISIÓN MANTENIMIENTO CUENTA`); the counterparty is read too
  (`Tarjeta Azul S.L.` → none); the plural `tarjeta debitos` does not match. Hypothesis: matching is invariant under
  changing the case of the text; `match_peer_service` never returns a service whose words do not match.
- [x] Add `[peer_fees]` to `apps/vampire_fees/config.toml` (the file's header comment says "no threshold lives here":
  extend it to say the table holds a path, a default type and words), and `PeerService`, `build_peer_services`,
  `match_peer_service` to `detectors/utils.py`. Existing tests of `build_vocabulary` and `classify_fee` pass unchanged.

## Task PF4 — Peer context in `vf.recurring_fee`

**Covers**: REQ-PF-11, REQ-PF-12, REQ-PF-13, REQ-PF-14, REQ-PF-17, §6.1, §6.3

- [x] Before editing, search the vf tests for 64-hex literals (an asserted alert id) and read
  `test_vf_recurring_fee.py`: none may change.
- [x] `apps/vampire_fees/tests/test_vf_recurring_fee_peers.py` (the existing `test_vf_recurring_fee.py` is not edited; it
  keeps proving the no-peers behaviour). Tier 1: the exact dict of REQ-PF-12 for the demo maintenance series with `S12`
  (built from rows through `vf_builders.py`, 22 monthly charges, last `6.50`); the `S10` case for the yearly card fee
  (`peer_lower_count` 8, `peer_median_yearly` `6.00`); the same ledger without `peers` equals the eight-key dict; the same
  ledger with a `PeerContext` whose services do not match (custody fee) has no peer keys. Tier 2: every REQ-PF-14 case
  (9 amounts vs 10; gap 365 vs 366 days; type `CDI` absent; empty `services`; `peers` a plain dict; `peers` `None`); the
  boundary of `yearly_cost` equal to an amount (not counted as lower); an amount `0.00` counted in both counts; a
  snapshot where all accounts are asterisks (`len(amounts) == 0`, none); empty and single-row ledgers with `peers`
  return `[]` and a list; a duplicate `source_ref` row does not crash; severity, title, `source_refs` **and `id`** equal
  with and without `peers` (decision Q7). Tier 3: the REQ-PF-13 property (random ledgers, random snapshot from the
  builder strategy, ids included), the `source_refs ⊆ loaded_source_refs(ledger, context)` property with
  `context["peers"]` set, idempotency, and the independent recomputation of REQ-PF-22 (`statistics.median` on `Decimal`
  plus a half-up quantize written in the test, `sum(...)` counts).
- [x] Add `PEER_MIN_ACCOUNTS`, `PEER_MAX_DATE_GAP_DAYS`, `PeerContext`, `peer_context_fields` to `detectors/utils.py` and
  the two lines of §6.3 to `recurring_fee.py`. The run, severity, title and `sorted_refs` lines are not touched. Every
  key `peer_context_fields` returns starts with `peer_` (a test asserts it), so PF0 keeps the id.

## Task PF5 — Template, guard check and card helpers

**Covers**: REQ-PF-16, REQ-PF-18, REQ-PF-19 (helpers), §7, §8

- [x] Tests in `apps/vampire_fees/tests/test_vf_peer_support.py` (template and guard part):
  `template_for` returns `TEMPLATES["vf.recurring_fee"]` for an alert without peer keys and
  `RECURRING_FEE_WITH_PEERS_TEMPLATE` with them; the filled text equals the string of REQ-PF-18 exactly (the two
  sentences of decision Q9); the two templates start with the same text; `TEMPLATES` keys still equal the registered
  `vf.*` names (the existing test in `test_vf_explain_support.py` is not edited); the `fee_summary` branch is unchanged;
  the comparison sentences contain none of `above`, `below`, `too`, `expensive`, `should`, `cheaper`, `switch`, and no
  digit; the zero-count case fills `0 charge less than this fee costs a year (...). 0 charge nothing`. **Guard** (with
  `MockLLMClient` as in the existing explainer tests): the accepted text of REQ-PF-16 gives `source == "llm"`;
  `13 payroll` → `("13",)`; `250,00 EUR` → `("250,00",)`; `18,50 EUR` → `("18,50",)`; the date `2026-11-24` →
  `("2026-11-24",)`; `18 EUR` accepted; `240,00 EUR per month` → `rejected_reason == "period_mismatch"` and
  `("240,00", "per month")`; the filled template of REQ-PF-18 passes the guard; the system message still contains the
  mandatory sentence verbatim; the alert JSON contains `peer_median_yearly`; the rejected answer returns the filled
  template. If any expectation above differs from what the unchanged guard does, **stop and amend the spec** (REQ-PF-16
  says the guard needs no change); do not edit `explainer.py` silently. Hypothesis: a text built only from numbers of
  `alert.data` is accepted, and the same text plus one foreign number is rejected. Card helpers: `peer_source_line`
  (the line of REQ-PF-19, `None` without keys); `peer_sentence_to_add` returns `None` for the fallback explanation (it
  contains the sentence), the sentence for a model text without it, `None` without keys, never twice;
  `peer_attribution_lines` returns the lines of REQ-PF-19 from a snapshot; markdown characters in a label are escaped by
  `markdown_safe`.
- [x] Add `PEER_SENTENCE`, `RECURRING_FEE_WITH_PEERS_TEMPLATE` and the extra branch of `template_for` to
  `explain_support.py`; add the three helpers to `settings.py`. Read `ledger_kit/ui/signatures.py`
  (`chip_source_template`) first and confirm it still finds `Source: {source_refs}.` in the new template.

## Task PF6 — App wiring, select box, footer, Home caption, demo run

**Covers**: REQ-PF-13 (demo), REQ-PF-19, REQ-PF-20, REQ-PF-21 (demo), §9

Uses a synthetic snapshot in `tmp_path`; does not need the real one.

- [x] Read first: the rest of `apps/vampire_fees/app.py` (`_render_alert` and the page function; only the first 450 lines
  were read when the spec was written), `ledger_kit/replay.py`, `tests/judge_path_support.py`,
  `tests/test_showcase_app.py` and the existing `test_vf_app_logic.py`. Q7 is answered: `data/live_runs/` holds
  recorded answers for `vf.recurring_fee` alerts, and PF0 keeps their ids, so the replay keeps finding them with or
  without the snapshot; nothing is re-recorded.
- [x] Tests: in `test_vf_app_logic.py`-style pure tests, `peer_type_options` and `default_peer_type` (REQ-PF-20 examples:
  `CNO` + `COT`; `CDI` + `COT`; a default absent from the snapshot), `peer_status` (`ok`, `missing`, `invalid`),
  `load_peers` (`None` for a missing and for an invalid file), `run_pipeline(..., peers=None)` gives results identical to
  today's (same `data`, same ids) and `peers=PeerContext(...)` adds the keys **and keeps the ids**;
  `explanation_cache_key` differs for the same alert with different peer fields and equals `(alert.id, mode, ())` for an
  alert without them (§9). In `test_vf_peer_demo.py` (headless `AppTest`, same helpers as the existing app tests, config
  patched to a synthetic snapshot with `CNO` (`S12` for `101`, `S10` for `401`, declaration date `2026-11-23`) and `COT`
  (8 amounts for `101`)): after **Load demo data** the alert counts equal those of the run without a snapshot (read from
  the same test run, not hard-coded; they are the six alerts of `test_vf_demo_e2e.py`); the maintenance card shows
  `9 charge less than this fee costs a year (78,00 EUR)` exactly once and the source line; the debit-card card shows
  `8 charge less than this fee costs a year (30,00 EUR)` once; the custody fee card shows neither; no other detector's
  card mentions the Banco de España; the footer holds the attribution, licence note and non-endorsement lines once; the
  select box lists `CNO · Cuenta Nómina/Pensión` and `COT · Otras Cuentas`, initial `CNO`; selecting `COT` removes the
  sentence from the maintenance card (8 amounts) and the card does not show the cached `CNO` text; with a synthetic
  snapshot that holds `CNO` only (the shape of the first real snapshot, amendment A1, DN-PF-32) there is **no** select
  box, the maintenance card still carries the sentence and its source line names `CNO`; a recorded
  `vf.recurring_fee` answer is still replayed when the snapshot is loaded; the toggle *Simulate a hallucinating LLM*
  still shows the rejected badge and the card still carries the sentence supplied by the card; with `snapshot_path`
  pointing to a missing file the page shows `Fee comparison unavailable: snapshot not found.`, no footer, no select box,
  and the alerts and counts are those of today; with an invalid file, `Fee comparison unavailable: snapshot invalid.`.
  The Norma 43 demo gives the same peer lines as the CSV demo (dates come from the rows). `tests/test_showcase_app.py`:
  the Home caption appears only when a snapshot loads (patch the default path). Existing `test_vf_*` tests pass
  unchanged.
- [x] Add `load_peers`, `peer_status`, `peer_type_options`, `default_peer_type`, `explanation_cache_key` and the `peers`
  argument of `run_pipeline` to `settings.py`; in `app.py` the cached loader, the select box (key `vf_peer_type`, added
  to `WIDGET_KEYS`, drawn only when the snapshot holds two or more types, DN-PF-32), the cache key, the card lines in the alert card, the footer and the unavailable captions; in
  `streamlit_app.py` the conditional Home caption.
- [x] Session 41b: Home shows a short credit (`fee_credit()`: Banco de España and the declaration date, as a separate caption right after the INE caption, not in the same caption, only while the snapshot loads); the full attribution of decision Q1 lives on the Vampire Fees page and in the documents.

## Task PF7 — Documents and `.gitignore` (before the snapshot exists)

**Covers**: REQ-PF-19 (documents), REQ-PF-21, §11

- [x] Read `tests/test_readme.py` (`REQUIRED_HEADINGS`), `tests/test_public_data_docs.py`, `tests/test_publish_ready.py` and
  the `.gitignore` tests first. Tests: `.gitignore` contains `*.xlsx` and `*.xls` and still has `!data/public/` and
  `!data/public/**` after `*.json`; `README.md` and `data/public/README.md` contain `attribution_for("YYYY-MM-DD")`,
  `LICENCE_NOTE` and `NO_ENDORSEMENT` of `bde_fees.py` verbatim (the date is the placeholder while no snapshot exists),
  and the README contains the sentence `The fee comparison appears once the snapshot
  data/public/bde_payment_account_fees.json is committed; without it the app shows no comparison.`;
  `data/public/README.md` says the file **does not exist yet** (this assertion is removed by PF9), names
  `scripts/import_bde_fees.py`, says the Excel is exported by hand and the importer reads local files only (decision
  Q6); when the snapshot exists, all of them equal the snapshot's texts (skipif absent); the existing README, publish
  and public-data tests pass (extend `tests/test_public_data_docs.py`, do not weaken it). The README says the app never
  calls the network and that the figures are context, not a verdict.
- [x] Update `.gitignore`, `data/public/README.md` (second section, §11), `README.md` (paragraph in "Public data") and
  `data/samples/README.md` (pointer line already says official public data lives in `data/public/`; extend only if it does
  not mention the BdE file).

## Task PF8 — Importer `scripts/import_bde_fees.py` (unblocked by amendment A1)

**Covers**: REQ-PF-02 (several files per type), REQ-PF-03 (`CNO` only), REQ-PF-04, REQ-PF-05, REQ-PF-22, §4,
DN-PF-24 to DN-PF-31

**Unblocked on 23 November 2026** (amendment A1): human step H1 is done. The owner exported the Excel by hand in the
tool *Comparación entre entidades para una fecha y cuenta* and keeps each `CompararEntidadesCCP.xls` in its own folder
outside the repository. The export is **manual**; no script, test or CI step ever accesses the Banco de España site
(decision Q6). The files are never read by a test and never committed. The layout is recorded in the amendment and
in Source fact 8 (the amendment came before any importer code).

- [x] Spec changes of D3 and D5 first, tests first: `tests/public_data/test_bde_fees_validator.py` — two `CNO`
  entries with different hashes pass, two entries with the same hash fail with `excel_files has two entries with
  the same sha256 (CNO)` (replacing the former "two entries for CNO" case), the duplicate-row message names
  `Comisión ANUAL total (euros)`; `tests/public_data/bde_builders.py` uses the Excel spelling of the two concepts
  and one distinct synthetic hash per file entry; `test_bde_fees_snapshot.py` requires `CNO` only (DN-PF-25);
  `apps/vampire_fees/tests/test_vf_peer_support.py` and `apps/vampire_fees/config.toml` use the Excel spelling
  (DN-PF-28). Then change `_check_excel_files` of `bde_fees.py` (one entry or more per type, no repeated hash).
- [x] Tests first. `tests/test_import_bde_fees.py`, loading the script by path as `tests/test_fetch_ine_cpi.py`
  does. Every grid and record is **synthetic** (entities such as `9991 BANCO FICTICIO`, `9992 CAJA DEMO`), never
  a row of the real files. `parse_grid` on a small grid in the layout of Source fact 8 (two entities, one with
  three accounts, a cash-machine block with repeated concepts, trailing spaces, an asterisk, the amount
  `1.234,56`): the dates, the title, the records, the spacer column skipped, the cash-machine block not kept;
  every layout error of §4.2 (no `SERVICIOS` row, no `CONCEPTOS` row, no legend, missing or repeated date
  cells, an invalid date, no title, a title naming another type, an unknown label, a label twice, no provider
  block, a kept block missing, a kept block without its compared concept, a concept twice in a kept block, a
  number cell in a kept block, an account with no entity, a bad entity code, an entity without a name, an entity
  twice, an account without a name, no account). `build_snapshot`: the REQ-PF-05 examples (`3,99`, `33,00`,
  `1.234,56`, `0,00`, asterisk with 40 trailing spaces, `\u00a0` padding, label to code), an unknown label,
  `3,999`, `6,5`, a euro concept with the text `ND` (kept as text, `amount null`), account keys `9991-01` to
  `9991-03`, two accounts with the same name, an account without cells, the row order of REQ-PF-01, several
  `excel_files` for one type, the result passes `validate_fee_snapshot`; Hypothesis round trip with generated
  records. `file_facts` of a temp file (name, size, SHA-256 equal to `hashlib` of the bytes). `read_grid` with a
  **fake `xlrd` module in `sys.modules`** (text, empty, blank, whole and non-whole number cells, a date cell, the
  `logfile` argument, `xlrd` missing, an `xlrd` error, a missing file). `main` with the fake `xlrd` and small
  temp files: success (stdout line, snapshot content, UTF-8, LF, final newline, no temp file left), and the exit
  code 1 and the exact stderr line of every error of REQ-PF-04 (missing file, unknown label, three decimals, title
  type mismatch, dates that differ between files, `--declaration-date` that differs, an entity in two files, a
  wrong or missing `--expect-entities`, the same SHA-256 twice, a wrong command line); a failed run leaves an
  existing snapshot byte-identical; no function reads the clock; the script never opens a socket (the
  `socket.socket.connect` guard of `tests/test_fetch_ine_cpi.py`) and imports no network module (`urllib`,
  `http`, `socket`, `requests`; AST scan, decision Q6); its only `import xlrd` is inside `read_grid`. Boundary
  tests of REQ-PF-22: no `xlrd` import in `ledger_kit/`, `apps/`, `streamlit_app.py`; not in `requirements.txt`;
  `pyproject.toml` has the extra `import = ["xlrd==2.0.1"]`; the compared concepts of the importer equal those
  of `apps/vampire_fees/config.toml`.
- [x] Write the script as in §4.2 to §4.4; add the optional extra `import` with `xlrd==2.0.1` to `pyproject.toml`
  (`tests/test_packaging.py` and `tests/test_showcase_requirements.py` stay green; CI installs `requirements.txt`
  only, so the extra never reaches CI or Community Cloud, and the importer tests still run there because they use
  the fake `xlrd`).

## Task PF9 — The committed snapshot — manual developer step

**Covers**: REQ-PF-03, REQ-PF-21, §2.4

**Waits for PF8 only** (amendment A1). Not done by an agent: the developer runs the importer on the files they keep.

- [ ] **Developer step H2** (PowerShell, venv active with the extra `import` installed — `pip install -e ".[import]"`
  — in the repository root; `<DOWNLOADS>` is the folder outside the repository that holds the exports):
  ```powershell
  python scripts/import_bde_fees.py --declaration-date 2026-11-23 --excel CNO=<DOWNLOADS>\nomina_pension\CompararEntidadesCCP.xls --expect-entities CNO=51
  git status
  ```
  The first snapshot holds `CNO` only (DN-PF-25); `COT` is added later with one `--excel COT=...` per file and
  `--expect-entities COT=<N>` once all its entities are exported. Read the one-line result (`92 accounts` is
  expected for `CNO`), check that `data/public/bde_payment_account_fees.json` is listed (not
  ignored), read the file's size (risk 7), open the file and check by eye three entities against the BdE page (code,
  name, one amount), then commit it. Record in the PR the file names, sizes and SHA-256 the importer wrote.
- [ ] Remove the `skipif(not exists)` marks of `test_bde_fees_snapshot.py` and the "does not exist yet" statements of the
  README and `data/public/README.md` (and their test assertions), replacing them by the real description (types, date,
  retrieval date, sizes, the attribution with the real date). The comparison now appears in the demo: run
  `streamlit run apps/vampire_fees/app.py`, Load demo data, and check the two cards (`BANCO FICTICIO` maintenance and
  debit card) carry the sentence, the custody card does not, the footer shows the attribution, the counts are those of
  today and the recorded answers are still replayed (decision Q7: ids unchanged); run `streamlit run streamlit_app.py`.

## Task PF10 — Steering updates and final checks

**Covers**: all REQ ids, §11, §12

- [ ] **Steering edits, approved by the reviewer on 23 November 2026** (these files bind every later session):
  `finance-rules.md` — Rule 6 (`data/public/` also holds the BdE snapshot, with its licence condition and attribution) and
  Rule 9: add the **one sentence** of design §11 about aggregates of public rows labelled *Elaboración propia*
  (decision Q1), and one sentence that the `peer_*` keys of `Alert.data` are left out of the alert id
  (`ALERT_ID_EXCLUDED_PREFIX`, decision Q7); `structure.md` — add `ledger_kit/public_data/bde_fees.py`,
  `scripts/import_bde_fees.py` (the one script allowed to import the library validator; it reads local files only), the
  snapshot file, the new test files (`tests/test_alert_id_peer_keys.py` included) and the vf package notes
  (`PeerContext`, `config.toml` `[peer_fees]`); `tech.md` — the BdE comparator row (no API, no automated access ever,
  Excel exported by hand, `xlrd` only in the optional extra `import`, never at run time, never in tests of the apps)
  and, in the `Alert` model, the note that the id leaves out the `peer_*` keys. Read `test_pi_structure_steering.py`
  first and keep it green; add the new folders to the structure listing it checks, if it checks one.
- [ ] Final checklist, run by the user: `ruff check .`; `ruff format --check .`; `pytest`; coverage at least 80 %
  (`--cov=ledger_kit --cov=apps/zombie_subscriptions --cov=apps/phantom_invoices --cov=apps/vampire_fees`);
  `streamlit run apps/vampire_fees/app.py` and Load demo data **without** the snapshot (no comparison, the caption, no
  footer; counts as today) and, once PF9 is done, **with** it; `streamlit run streamlit_app.py` loads all pages;
  `git status` shows the snapshot tracked and no `*.xlsx` or `*.xls` listed.

---

## Decisions on the former open questions (answered 23 November 2026)

Each former question is now a decision in the table of `design.md` §12.

| Question | Answer | Decision |
|---|---|---|
| Q1 — Attribution and faithfulness | The attribution is shown once on the page, with the text `Fuente: Banco de España, comparador de comisiones de cuentas de pago (declaraciones a fecha YYYY-MM-DD). Elaboración propia: recuento, mediana y máximo.` (`YYYY-MM-DD` is the snapshot's declaration date; `attribution_for(declaration_date)` in `bde_fees.py`). The legal notice allows reuse and calculations with the data if it is reproduced faithfully and the source is cited, so counts, a median and a maximum are allowed when labelled *Elaboración propia*. The Rule 9 widening of PF10 is approved and is applied as one sentence (design §11) | DN-PF-01, DN-PF-21 |
| Q2 — Default account type | `CNO`, the default of the Banco de España tool itself; the select box offers the types present in the snapshot | DN-PF-14 |
| Q3 — The two limits | Keep `PEER_MIN_ACCOUNTS = 10` and `PEER_MAX_DATE_GAP_DAYS = 365` | DN-PF-07, DN-PF-08 |
| Q4 — The Excel | The layout is decided when the file exists, with an amendment before any importer code. PF8 and PF9 stay BLOCKED. **Closed by amendment A1** | DN-PF-03 |
| Q5 — Types in the first snapshot | `CNO` and `COT` are required; `CDI` and `CJO` are added if they were downloaded; `CBA` is not needed. The validator accepts any non-empty set of types; the pinned check of the committed file requires `CNO` and `COT`. **Replaced by amendment A1 (D2, DN-PF-25): the first snapshot holds `CNO` only** | DN-PF-22 (replaced by DN-PF-25) |
| Q6 — Access to the BdE site | No automated access to the Banco de España site, ever: the export is manual and the importer reads local files only | DN-PF-23 |
| Q7 — Recorded runs | Changed decision, replaces the old DN-PF-17: `data/live_runs/` holds recorded model answers for `vf.recurring_fee` alerts that the demo replays by alert id, so the id must **not** change when peer fields are added. `_deterministic_alert_id` leaves out of the hash every `data` key that starts with `peer_` (one documented rule, one constant `ALERT_ID_EXCLUDED_PREFIX`); no alert has a `peer_` key today, so every existing id is unchanged (task PF0). Because the id no longer changes, the Vampire explanation cache key gains the peer fields (§9) | DN-PF-17 (replaced) |
| Q8 — Account identity | `account_key` is the entity code plus the position of the account within that entity in file order, stable within one snapshot; the snapshot keeps the account name for display | DN-PF-02 |
| Q9 — Wording | Two short sentences instead of a nested one (REQ-PF-18): `Of 12 payroll or pension accounts that declared an annual account maintenance fee to the Banco de España on 2026-11-23, 9 charge less than this fee costs a year (78,00 EUR). 5 charge nothing; the median is 18,00 EUR and the highest 240,00 EUR.` (synthetic numbers) | DN-PF-15 |
| Q10 — Comparability | Only the two annual-total concepts (`101` *Comisión ANUAL total (euros)*, `401` *Comisión mantenimiento. ANUAL total (euros)*); fees with a waiver condition are a non-goal | DN-PF-11 |

---

## Amendment A1 (23 November 2026): the real Excel

Written before any importer code, as task PF8 required (decision Q4). The reviewer read the three exported files
on 23 November 2026 with a script; the agent writing this amendment could not read them (binary `.xls`) and did not
add them to the repository. Row and column numbers are 0-based, as `xlrd` gives them.

### Facts read by the reviewer

- **F1. Format.** A real binary `.xls` (OLE2, BIFF8, Excel 97-2003), not `.xlsx` and not an HTML table. One sheet,
  named `CompararEntidadesCCP`. Every export has the same file name, `CompararEntidadesCCP.xls`, so the developer
  keeps each one in its own folder. Sizes 212928, 229312 and 237504 bytes. `xlrd` 2.0.1 reads them; it prints a
  harmless warning about the file size not being a multiple of the sector size, which must not stop the import.
- **F2. Above the table.** Row 1 col 11 holds `Fecha: 23/11/2026   8:06:35` (when the file was generated); row 2
  col 4 `CSF - Comisiones y tipos de interés de los servicios financieros`; row 6 col 4 `COMPARACIÓN ENTRE
  ENTIDADES. COMISIONES DE CUENTAS DE PAGOS CUENTA NÓMINA/PENSIÓN` (it ends with the account type label in
  capitals; `OTRAS CUENTAS` for `COT`); row 8 col 4 `Fecha de referencia: 23-11-2026` (the declaration date,
  `DD-MM-YYYY`).
- **F3. Header.** The row whose column 0 is `SERVICIOS` (row 12) holds each service label in the first column of its
  block; the next row (row 13) holds the concept labels, and its column 0 is `CONCEPTOS` followed by a line break
  and `(*) No se cobra comisión/no se ofrece el servicio`. A block runs from its label column to the column before
  the next non-empty label; header columns with an empty concept inside a block are blank spacers. The blocks, in
  order: *Proveedor de la Cuenta* (col 6 *Nombre de la cuenta*); *Mantenimiento de la cuenta* (col 8
  *Periodicidad*, col 10 *Comisión ANUAL total (euros)*); *Emisión y mantenimiento de una tarjeta de débito* (col
  12 *Marca comercial*, col 15 *Comisión de emisión (euros)*, col 16 *Comisión mantenimiento. Periodicidad.*, col
  17 *Comisión mantenimiento. ANUAL total (euros)*); then *Retirada efectivo a débito mediante tarjeta en
  cajero*, *Descubierto expreso* and *Descubierto tácito*. The cash-machine block has a variable number of
  sub-groups whose concepts repeat (*Entidad*, *Importe (euros)*, *Porcentaje (%) comisión titular cajero*,
  *Retiradas/mes*, *Número*) in an order that changes between files, so every column after the card block moves:
  the three files have 60, 58 and 54 columns. **Columns must be found by header text, never by position.**
- **F4. Data.** From the row after the concept row to the last row, one row per account (declaration). Column 0
  (entity code, four-digit text) and column 2 (entity name) are filled only on the first account of each entity;
  the next accounts of the same entity leave them empty and belong to the entity above. Column 5 is a running
  number 1 to n stored as a number cell (1.0, 2.0, ...); it is the only number cell. No merged cells. Up to 20
  accounts per entity.
- **F5. Cells.** Every value cell is text. Amounts use a decimal comma and two decimals (`240,00`; `0,00`;
  `12,02`); no thousands separator was seen (the highest is `300,00`). A lone asterisk is the asterisk. Text cells
  carry trailing spaces only (up to about 200); no other padding character was seen.
- **F6. Spelling.** The two compared concepts are spelled differently from the screen: `Comisión ANUAL total
  (euros)` and `Comisión mantenimiento. ANUAL total (euros)`, with `ANUAL` in capitals.
- **F7. Asterisk legend.** `(*) No se cobra comisión/no se ofrece el servicio` (no fee is charged, or the service
  is not offered); on screen it said *No practicado*.
- **F8. What was exported on 23 November 2026.** `CNO` with *Tipo de entidad* *Todos* and all entities selected:
  51 entities and 92 accounts, the whole list the tool offers for `CNO` (banks, branches of foreign banks such as
  `1465` ING, savings banks and credit cooperatives). `COT` had to be split, because the tool refuses an export of
  more than 238 declarations, and a captcha stopped the downloads: 22 banks (114 accounts) and 28 of the 58 savings
  banks and credit cooperatives (136 accounts) were exported; the other 30 savings banks and cooperatives, the
  branches of foreign banks, the credit finance establishments and the payment entities are missing. No entity
  appears in two `COT` files.

### Decisions of the reviewer (23 November 2026)

| Id | Decision | Design |
|---|---|---|
| D1 | Library: `xlrd` 2.0.1, exact pin, in the optional extra `import` of `pyproject.toml`; it replaces `openpyxl` everywhere in the spec (`openpyxl` cannot read `.xls`). Never in `requirements.txt`; never imported under `ledger_kit/`, `apps/` or by `streamlit_app.py` (the boundary tests of REQ-PF-22 name `xlrd`) | DN-PF-24 (and DN-PF-04) |
| D2 | An account type enters the snapshot only when its files hold every entity the tool lists for that type. The command line takes `--expect-entities TYPE=N` once for every type given; the import fails unless the files of that type hold exactly `N` distinct entities. The first snapshot holds `CNO` only (51 entities); `COT` is left out until its missing parts are exported. Replaces Q5 and DN-PF-22: the pinned check of the committed file requires `CNO`, not `COT` | DN-PF-25 |
| D3 | Several files per type: `--excel TYPE=PATH` may repeat for one type; `excel_files` may hold several entries per type, each with its own `name`, `size_bytes` and `sha256` (two entries with the same `sha256` are an error); an entity found in two files of one type is an error; account keys are numbered within the entity in file order, the files of a type taken in the order given | DN-PF-26 |
| D4 | The snapshot keeps the rows of services `101` and `401` only, with all their concepts. The cash-machine and overdraft blocks are not stored; their service labels are still checked against `SERVICES`. *Proveedor de la Cuenta* is not a service: its *Nombre de la cuenta* becomes `account_name`. A kept block must contain its compared concept and no concept twice, else the import fails | DN-PF-27 |
| D5 | Concepts are stored verbatim as the Excel writes them (F6). `config.toml` `[peer_fees]` and every spec example, builder and test fixture that names the two compared concepts use the Excel spelling | DN-PF-28 |
| D6 | `not_offered` keeps its name and still records the asterisk; DN-PF-06 quotes the Excel legend and says an asterisk is never counted as `0.00` nor as an amount, because the legend joins two meanings and the kit does not guess which one applies. The sentence counts only accounts with a declared amount | DN-PF-29 (and DN-PF-06) |
| D7 | Dates come from the files, never from the clock: `declaration_date` from the *Fecha de referencia* cell and `retrieved_on` from the date of the *Fecha:* cell; every file must give the same two dates. `--declaration-date` stays required as a cross-check and must equal the files' date; `--retrieved-on` is removed; `main` reads no clock. The account type in the title row must equal the `TYPE` given with the file | DN-PF-30 |
| D8 | `read_grid(path)` is the only function that imports `xlrd` (sheet 0, every cell as text: a text cell as written, an integral number cell as its integer text); `parse_grid(grid, account_type)` is pure and is the only function that knows the layout of F2 to F4, returning the dates, the title and the records; `build_snapshot` stays as designed. A number cell inside a kept block is an error | DN-PF-31 |
| D9 | With a single account type in the snapshot the app shows no select box; the source line names the type. With two or more, the select box of REQ-PF-20 is shown | DN-PF-32 |

### What the amendment changes

- `requirements.md`: Source fact 6 (closed) and the new Source fact 8; REQ-PF-01 (`retrieved_on` and
  `declaration_date` from the files, `excel_files` one or more per type, rows of `101` and `401` only, the asterisk
  legend, the Excel spelling); REQ-PF-02 (several `excel_files` per type, no repeated hash); REQ-PF-03 (`CNO` only);
  REQ-PF-04 and REQ-PF-05 (rewritten for `xlrd`, `read_grid` / `parse_grid` / `build_snapshot`, the new command line
  and errors); REQ-PF-20 (no select box for one type); REQ-PF-22 (synthetic grids, a fake `xlrd`, boundary tests
  naming `xlrd`); every example naming the two compared concepts (D5).
- `design.md`: §1, §2.1 to §2.4, §4 (rewritten), §9, §10, §11, §12 (DN-PF-04, DN-PF-06, DN-PF-22 replaced,
  DN-PF-24 to DN-PF-32), §13 (risks 1 and 2).
- `tasks.md`: the header, PF6 (the `CNO`-only case of the select box), PF8 (unblocked, rewritten), PF9 (the command
  line of the first snapshot), PF10 (`xlrd`), Q4 and Q5 of the decisions table.
- Task PF2, already done, gets two follow-ups inside PF8: the validator accepts several `excel_files` per type (D3)
  and its committed-file test requires `CNO` only (D2). The account keys and every other check of PF2 are unchanged.
- Rules the amendment adds on its own, where the facts left a choice (fail-safe, no guess): the importer checks that
  the concept row carries the asterisk legend (F3, F7); an empty value cell is not stored as a row (the account still
  counts); a non-whole number, date, boolean or error cell anywhere is an error in `read_grid`; an entity code is
  taken as published (four-digit text) and never padded; a euro text made of digits, dots and commas that is not an
  amount with two decimals is an error; a wrong command line is reported as one `error:` line with exit 1.
