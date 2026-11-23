# public-fees — Implementation Tasks

Every task is test-first: write the tests named in the task, see them fail, then implement. Section
references (§) point to `design.md`, REQ ids to `requirements.md`. Hypothesis tests use
`settings(max_examples=200)`. Nothing reads the clock, the network or an Excel file (except PF8, with a
synthetic workbook). Verification (`ruff check .`, `ruff format --check .`, `pytest`, a headless run of the
Vampire Fees app and of `streamlit_app.py`) is run by the user; the author of the spec ran nothing and wrote only
the three spec files.

**State when this spec was written: `data/public/bde_payment_account_fees.json` does not exist and the BdE Excel has
not been downloaded.** PF0 to PF7 need neither: they use **synthetic** fixtures and are complete without the real
data. PF8 and PF9 are **BLOCKED** until the Excel exists (decision Q4); the Excel is exported **by hand**, never by
automated access to the Banco de España site (decision Q6). PF10 applies the steering edits the reviewer approved on
23 November 2026 (decision Q1).

Order: PF0 (alert id) → PF1 (money) → PF2 (reader) → PF3 (matching) → PF4 (detector) → PF5 (template and card
helpers) → PF6 (app) → PF7 (docs and `.gitignore`) → PF8 (importer, BLOCKED) → PF9 (real snapshot, BLOCKED, manual) →
PF10 (steering, final checks). PF0 must be done before PF4; PF1 to PF3 do not depend on it. A later task may start
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

- [ ] Before editing, search the vf tests for 64-hex literals (an asserted alert id) and read
  `test_vf_recurring_fee.py`: none may change.
- [ ] `apps/vampire_fees/tests/test_vf_recurring_fee_peers.py` (the existing `test_vf_recurring_fee.py` is not edited; it
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
- [ ] Add `PEER_MIN_ACCOUNTS`, `PEER_MAX_DATE_GAP_DAYS`, `PeerContext`, `peer_context_fields` to `detectors/utils.py` and
  the two lines of §6.3 to `recurring_fee.py`. The run, severity, title and `sorted_refs` lines are not touched. Every
  key `peer_context_fields` returns starts with `peer_` (a test asserts it), so PF0 keeps the id.

## Task PF5 — Template, guard check and card helpers

**Covers**: REQ-PF-16, REQ-PF-18, REQ-PF-19 (helpers), §7, §8

- [ ] Tests in `apps/vampire_fees/tests/test_vf_peer_support.py` (template and guard part):
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
- [ ] Add `PEER_SENTENCE`, `RECURRING_FEE_WITH_PEERS_TEMPLATE` and the extra branch of `template_for` to
  `explain_support.py`; add the three helpers to `settings.py`. Read `ledger_kit/ui/signatures.py`
  (`chip_source_template`) first and confirm it still finds `Source: {source_refs}.` in the new template.

## Task PF6 — App wiring, select box, footer, Home caption, demo run

**Covers**: REQ-PF-13 (demo), REQ-PF-19, REQ-PF-20, REQ-PF-21 (demo), §9

Uses a synthetic snapshot in `tmp_path`; does not need the real one.

- [ ] Read first: the rest of `apps/vampire_fees/app.py` (`_render_alert` and the page function; only the first 450 lines
  were read when the spec was written), `ledger_kit/replay.py`, `tests/judge_path_support.py`,
  `tests/test_showcase_app.py` and the existing `test_vf_app_logic.py`. Q7 is answered: `data/live_runs/` holds
  recorded answers for `vf.recurring_fee` alerts, and PF0 keeps their ids, so the replay keeps finding them with or
  without the snapshot; nothing is re-recorded.
- [ ] Tests: in `test_vf_app_logic.py`-style pure tests, `peer_type_options` and `default_peer_type` (REQ-PF-20 examples:
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
  sentence from the maintenance card (8 amounts) and the card does not show the cached `CNO` text; a recorded
  `vf.recurring_fee` answer is still replayed when the snapshot is loaded; the toggle *Simulate a hallucinating LLM*
  still shows the rejected badge and the card still carries the sentence supplied by the card; with `snapshot_path`
  pointing to a missing file the page shows `Fee comparison unavailable: snapshot not found.`, no footer, no select box,
  and the alerts and counts are those of today; with an invalid file, `Fee comparison unavailable: snapshot invalid.`.
  The Norma 43 demo gives the same peer lines as the CSV demo (dates come from the rows). `tests/test_showcase_app.py`:
  the Home caption appears only when a snapshot loads (patch the default path). Existing `test_vf_*` tests pass
  unchanged.
- [ ] Add `load_peers`, `peer_status`, `peer_type_options`, `default_peer_type`, `explanation_cache_key` and the `peers`
  argument of `run_pipeline` to `settings.py`; in `app.py` the cached loader, the select box (key `vf_peer_type`, added
  to `WIDGET_KEYS`), the cache key, the card lines in the alert card, the footer and the unavailable captions; in
  `streamlit_app.py` the conditional Home caption.

## Task PF7 — Documents and `.gitignore` (before the snapshot exists)

**Covers**: REQ-PF-19 (documents), REQ-PF-21, §11

- [ ] Read `tests/test_readme.py` (`REQUIRED_HEADINGS`), `tests/test_public_data_docs.py`, `tests/test_publish_ready.py` and
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
- [ ] Update `.gitignore`, `data/public/README.md` (second section, §11), `README.md` (paragraph in "Public data") and
  `data/samples/README.md` (pointer line already says official public data lives in `data/public/`; extend only if it does
  not mention the BdE file).

## Task PF8 — Importer `scripts/import_bde_fees.py` — **BLOCKED**

**Covers**: REQ-PF-04, REQ-PF-05, §4

**BLOCKED until the BdE Excel exists** (decision Q4). Human step H1 (owner): in the tool *Comparación entre entidades
para una fecha y cuenta* pick the declaration date, one account type, all entities and all services, press *Exportar
comparación a Excel*, save the file outside the repository (for example `C:\Users\<you>\Downloads\`), and repeat for
each account type: `CNO` and `COT` are required, `CDI` and `CJO` are added if they were downloaded, `CBA` is not needed
(decision Q5). The export is **manual**; no script, test or CI step ever accesses the Banco de España site (decision
Q6). Do not commit the files (`.gitignore` of PF7 blocks them). Note the date, the account type, the file names.
Nothing else in the project waits for this task.

- [ ] **Start by reading the real file** and write an **amendment** at the end of this `tasks.md` (and of
  `requirements.md` REQ-PF-04/05 if needed) that records: the extension and the library chosen (`openpyxl` for `.xlsx`; if
  it is `.xls` or an HTML table, decide and justify), sheet and column layout, where the declaration date and the account
  type appear, how entities with several accounts appear, the padding characters, whether amounts are text or numbers,
  and how entity codes appear (Q4). `account_key` is already decided (Q8): entity code plus the position of the account
  within that entity in file order. **No importer code before the amendment.**
- [ ] Tests first. `tests/test_import_bde_fees.py`: **pure part, no `openpyxl`** — `build_snapshot` on small hand-made
  `Record` lists: the REQ-PF-05 examples (`3,99`, `33,00`, `1.234,56`, `0,00`, asterisk with 40 trailing spaces,
  `\u00a0` padding, label to code), an unknown label, `3,999`, a euro concept with the text `ND` (kept as text,
  `amount null`), duplicate declarations, account keys `0049-01`, `0049-02` for one entity, row order of REQ-PF-01, the
  result passes `validate_fee_snapshot`; Hypothesis round trip with generated records. `file_facts` of a temp file (name,
  size, SHA-256 equal to `hashlib` of the bytes). **Workbook part** (`pytest.importorskip("openpyxl")`): a tiny **synthetic**
  workbook written to `tmp_path` in the layout found in the amendment → expected snapshot; `main` exit codes and stderr
  lines of REQ-PF-04 (missing file, unknown label, three decimals); a failed run leaves an existing snapshot
  byte-identical; the output is UTF-8 with LF and a final newline; `today` injected; the script never opens a socket (the
  `socket.socket.connect` guard of `tests/test_fetch_ine_cpi.py`) and imports no network module (`urllib`, `http`,
  `socket`, `requests`; AST scan, decision Q6). Boundary tests of REQ-PF-22 (no `openpyxl` import in `ledger_kit/`,
  `apps/`, `streamlit_app.py`; not in `requirements.txt`).
- [ ] Write the script as in §4.2 to §4.4; add the optional extra `import` with the exact `openpyxl` pin to
  `pyproject.toml` (read `tests/test_packaging.py` and `tests/test_showcase_requirements.py` first so the extra does not
  reach `requirements.txt`; check `.github/workflows/tests.yml` to see whether CI installs extras; the default is that CI
  does not, so the workbook tests skip there and run on the developer machine).

## Task PF9 — The committed snapshot — **BLOCKED**, manual step

**Covers**: REQ-PF-03, REQ-PF-21, §2.4

**BLOCKED by PF8.**

- [ ] **Developer step H2** (PowerShell, venv active, in the repository root):
  ```powershell
  python scripts/import_bde_fees.py --declaration-date 2026-11-23 --excel CNO=C:\path\to\cno.xlsx --excel COT=C:\path\to\cot.xlsx
  git status
  ```
  Use the real declaration date and one `--excel` per type (`CNO` and `COT` always, `CDI` and `CJO` if downloaded,
  decision Q5). Read the one-line result, check that `data/public/bde_payment_account_fees.json` is listed (not
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
  Excel exported by hand, `openpyxl` only in the optional extra `import`, never at run time, never in tests of the apps)
  and, in the `Alert` model, the note that the id leaves out the `peer_*` keys. Read `test_pi_structure_steering.py`
  first and keep it green; add the new folders to the structure listing it checks, if it checks one.
- [ ] Final checklist, run by the user: `ruff check .`; `ruff format --check .`; `pytest`; coverage at least 80 %
  (`--cov=ledger_kit --cov=apps/zombie_subscriptions --cov=apps/phantom_invoices --cov=apps/vampire_fees`);
  `streamlit run apps/vampire_fees/app.py` and Load demo data **without** the snapshot (no comparison, the caption, no
  footer; counts as today) and, once PF9 is done, **with** it; `streamlit run streamlit_app.py` loads all pages;
  `git status` shows the snapshot tracked and no `*.xlsx` listed.

---

## Decisions on the former open questions (answered 23 November 2026)

Each former question is now a decision in the table of `design.md` §12.

| Question | Answer | Decision |
|---|---|---|
| Q1 — Attribution and faithfulness | The attribution is shown once on the page, with the text `Fuente: Banco de España, comparador de comisiones de cuentas de pago (declaraciones a fecha YYYY-MM-DD). Elaboración propia: recuento, mediana y máximo.` (`YYYY-MM-DD` is the snapshot's declaration date; `attribution_for(declaration_date)` in `bde_fees.py`). The legal notice allows reuse and calculations with the data if it is reproduced faithfully and the source is cited, so counts, a median and a maximum are allowed when labelled *Elaboración propia*. The Rule 9 widening of PF10 is approved and is applied as one sentence (design §11) | DN-PF-01, DN-PF-21 |
| Q2 — Default account type | `CNO`, the default of the Banco de España tool itself; the select box offers the types present in the snapshot | DN-PF-14 |
| Q3 — The two limits | Keep `PEER_MIN_ACCOUNTS = 10` and `PEER_MAX_DATE_GAP_DAYS = 365` | DN-PF-07, DN-PF-08 |
| Q4 — The Excel | The layout is decided when the file exists, with an amendment before any importer code. PF8 and PF9 stay BLOCKED | DN-PF-03 |
| Q5 — Types in the first snapshot | `CNO` and `COT` are required; `CDI` and `CJO` are added if they were downloaded; `CBA` is not needed. The validator accepts any non-empty set of types; the pinned check of the committed file requires `CNO` and `COT` | DN-PF-22 |
| Q6 — Access to the BdE site | No automated access to the Banco de España site, ever: the export is manual and the importer reads local files only | DN-PF-23 |
| Q7 — Recorded runs | Changed decision, replaces the old DN-PF-17: `data/live_runs/` holds recorded model answers for `vf.recurring_fee` alerts that the demo replays by alert id, so the id must **not** change when peer fields are added. `_deterministic_alert_id` leaves out of the hash every `data` key that starts with `peer_` (one documented rule, one constant `ALERT_ID_EXCLUDED_PREFIX`); no alert has a `peer_` key today, so every existing id is unchanged (task PF0). Because the id no longer changes, the Vampire explanation cache key gains the peer fields (§9) | DN-PF-17 (replaced) |
| Q8 — Account identity | `account_key` is the entity code plus the position of the account within that entity in file order, stable within one snapshot; the snapshot keeps the account name for display | DN-PF-02 |
| Q9 — Wording | Two short sentences instead of a nested one (REQ-PF-18): `Of 12 payroll or pension accounts that declared an annual account maintenance fee to the Banco de España on 2026-11-23, 9 charge less than this fee costs a year (78,00 EUR). 5 charge nothing; the median is 18,00 EUR and the highest 240,00 EUR.` (synthetic numbers) | DN-PF-15 |
| Q10 — Comparability | Only the two annual-total concepts (`101` *Comisión anual total (euros)*, `401` *Comisión mantenimiento. Anual total (euros)*); fees with a waiver condition are a non-goal | DN-PF-11 |
