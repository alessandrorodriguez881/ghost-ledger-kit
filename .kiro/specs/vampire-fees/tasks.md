# vampire-fees — Implementation Tasks

**Built by**: the Kiro custom agent `ghost-ledger-builder` (`.kiro/agents/ghost-ledger-builder.json`).
**Depends on**: the finished template (`ledger_kit/`, `apps/zombie_subscriptions/`,
`apps/phantom_invoices/`, `scripts/generate_samples.py`, `streamlit_app.py`). **Nothing here
modifies a file under `ledger_kit/` or in the other apps** (REQ-VF-04, REQ-VF-58). If a task finds
that it must, stop and write `DN-VF-L<n>` in `design.md` §11.1 (rule L); do not edit the library.

Every task is **test-first**: write the tests, then the code. The agent cannot run commands, so
each task ends with a **Check (human)** line; the human runs it and reports the result. Code is
written in the style `ruff format` produces (double quotes, 100 columns, trailing commas), imports
sorted (`ruff` rule I), every public function typed with a one-line docstring. Property tests use
`@settings(max_examples=200)`. No test reads the clock or the network. All fixtures are synthetic.

Windows, Python 3.12 venv, PowerShell, from the repository root:

```powershell
.\.venv\Scripts\Activate.ps1
```

Section references (§) point to `design.md`; REQ and AE ids to `requirements.md`.

---

## Task VF1 — App package scaffold

**Covers**: REQ-VF-04, REQ-VF-05 (names), REQ-VF-64, §1

*Status: written by the agent, not yet run by the human.*

- [x] Write `apps/vampire_fees/tests/test_vf_scaffold.py`:
  - `test_app_package_importable` — `apps.vampire_fees` and `apps.vampire_fees.detectors` import.
  - `test_no_app_level_requirements_txt`.
  - `test_app_does_not_import_other_app` — AST scan: no `apps.zombie_subscriptions` or
    `apps.phantom_invoices` import under `apps/vampire_fees/`; no `apps.vampire_fees` import in
    `ledger_kit/`.
  - `test_app_uses_no_private_ledger_kit_name` — AST scan of the app (tests excluded): no imported
    module or name that starts with `_`.
  - `test_config_has_no_threshold_constant_name` — once VF11 adds `config.toml`, none of the
    constant names of §2.1 appears in it.
- [x] Create `apps/vampire_fees/__init__.py`, `apps/vampire_fees/detectors/__init__.py` (empty for
  now), `apps/vampire_fees/tests/` (`apps/__init__.py` already exists).
- [ ] **Check (human)**: `pytest apps/vampire_fees/tests/test_vf_scaffold.py -q`; `ruff check .`

---

## Task VF2 — Constants, folding and vocabulary

**Covers**: REQ-VF-10, REQ-VF-12, REQ-VF-15 (key), AE-VF-08, §2, §4.1, §4.3 (`series_key`)

- [x] Write `test_vf_utils_normalise.py`:
  - **Tier 1**: `fold_tokens("Comisión Mantenimiento-Cuenta 05/26")` →
    `("comision", "mantenimiento", "cuenta", "05", "26")`; `contains_phrase` with a one-word and a
    two-word phrase; `series_key` (AE-VF-08); `concept_of(["x", "common_concept:17"])` → `"17"`.
  - **Tier 1**: `build_vocabulary` folds `"Comisión"` to `("comision",)` and
    `"Cuota de Mantenimiento"` to `("cuota", "de", "mantenimiento")`.
  - **Tier 2**: `fold_tokens(None)`, `fold_tokens(float("nan"))`, `fold_tokens("")` → `()`;
    `contains_phrase((), …)` false; a phrase never matches across two fields; `fee` does not match
    `feelgood`, `comision` does not match `comisionista`; `concept_of(None)`, `concept_of([])`,
    `concept_of(float("nan"))` → `None`; `build_vocabulary` raises `ValueError` naming the key for a
    missing key, an empty list, a non-string, and a phrase with no letter or digit (`"--"`).
  - **Tier 3**: `fold_tokens` is idempotent (`fold_tokens(" ".join(fold_tokens(t))) ==
    fold_tokens(t)`); output tokens contain only lowercase letters and digits; case and accent
    invariance for ASCII-letter text.
  - `test_constants_values` — every constant of §2.1 exists with the stated value and type;
    `INTERVALS` order is monthly, quarterly, yearly; the three tolerance ranges do not overlap.
- [x] Implement the constants block, `fold_tokens`, `FeeVocabulary`, `EMPTY_VOCABULARY`,
  `build_vocabulary`, `contains_phrase`, `concept_of`, `series_key` in `detectors/utils.py`, each
  constant with a comment giving its reason (§2.2). (`Interval` and `INTERVALS` are defined here
  too, because the constants test checks them; VF4 adds `classify_gap` and `find_run`.)
- [ ] **Check (human)**: `pytest apps/vampire_fees/tests/test_vf_utils_normalise.py -q`; `ruff check .`

---

## Task VF3 — Classification and extraction

**Covers**: REQ-VF-06 … REQ-VF-14, REQ-VF-34, AE-VF-01 … AE-VF-07, §4.2

- [x] Write `vf_builders.py` first (`fee_row(...)` builds one canonical ledger row dict with
  explicit `date`, `Decimal` amount, `flow`, `currency`, `counterparty`, `description`, `tags`,
  `source_ref`; `make_ledger(rows)` builds the frame with `CANONICAL_COLUMNS`), then
  `test_vf_classify.py`:
  - **Tier 1**: each of AE-VF-01 … AE-VF-07 as its own test (concept rule, accent and case,
    `Feelgood`, notary with and without concept 17, credit with concept 17, kinds, exclusion and
    currency).
  - **Tier 1**: a concept `12` row with `Comisión` is a fee (REQ-VF-09); a concept `16` row with no
    words is a fee; a concept `03` row with no words is not.
  - **Tier 2**: `extract_fees` on `pd.DataFrame()` → `[]`; on one row → list; `tags` is `None`, NaN
    or `[]` → no crash; two rows with the same `source_ref` → one fee (the first); fees come out
    ordered by `(date, source_row)`; `skipped_currency_rows` counts USD rows; empty
    `EMPTY_VOCABULARY` classifies by concept only.
  - **Tier 3**: a credit row is never a fee for any text and tag; a debit EUR row with no
    vocabulary phrase and no concept tag is never a fee; `extract_fees` is idempotent and its
    `source_ref`s are a subset of the ledger's.
- [x] Implement `Fee`, `classify_fee`, `extract_fees`, `skipped_currency_rows`, `statement_span`,
  `sorted_refs`.
- [ ] **Check (human)**: `pytest apps/vampire_fees/tests/test_vf_classify.py -q`; `ruff check .`

---

## Task VF4 — Series and runs

**Covers**: REQ-VF-15 … REQ-VF-17, REQ-VF-20, AE-VF-12, AE-VF-13, AE-VF-16, §4.3

- [x] Write `test_vf_series.py`:
  - **Tier 1**: `classify_gap` for 30 → monthly, 91 → quarterly, 365 → yearly.
  - **Tier 2**: both sides of every boundary: 26/27, 33/34 (monthly), 87/88, 94/95 (quarterly),
    359/360, 370/371 (yearly); gap 0 and gap 200 → `None`; `find_run` with 0 and 1 rows → `None`;
    two monthly rows → `None`, three → run of 3; two quarterly rows → run; one outlier before a
    regular suffix → run of the suffix only (AE-VF-13); last gap irregular → `None` (AE-VF-16);
    two rows on the same date end the run.
  - **Tier 3**: for any list of rows, a returned run is a suffix of the input, has at least the
    interval's `min_charges`, and every consecutive gap matches the interval.
  - `test_yearly_cost` — `5.00` monthly → `60.00`; `9.00` quarterly → `36.00`; `30.00` yearly →
    `30.00`; `4.99` monthly → `59.88`.
- [x] Implement `Interval`, `INTERVALS`, `classify_gap`, `find_run`, `yearly_cost`, `ppy` access.
- [ ] **Check (human)**: `pytest apps/vampire_fees/tests/test_vf_series.py -q`; `ruff check .`

---

## Task VF5 — Shared fixtures

**Covers**: REQ-VF-61, REQ-VF-63, `testing.md` standard fixtures, §9

- [x] Write `test_vf_fixtures.py` first: every fixture frame has `CANONICAL_COLUMNS`; unique
  `source_ref`s; all counterparties come from a fixed allow-list of fictional names (`BANCO
  FICTICIO`, `Feelgood Market`, `Mercado Central Demo`, `STREAMFLIX INTL`, …); no digit in a fee
  description; `clean_ledger_10` classifies to zero fees.
- [x] Implement `conftest.py`: `empty_ledger`, `single_row_ledger`, `clean_ledger_10`,
  `ledger_with_monthly_fee` (AE-VF-09), `ledger_with_fee_increase` (AE-VF-17),
  `ledger_with_overdraft` (AE-VF-21), `ledger_with_one_off_fees`, `vocabulary` (the default
  vocabulary of §2.3 built with `build_vocabulary`), plus Hypothesis strategies in `vf_builders.py`
  (rows with random text drawn from vocabulary words, non-fee words and tags).
- [ ] **Check (human)**: `pytest apps/vampire_fees/tests/test_vf_fixtures.py -q`; `ruff check .`

---

## Task VF6 — `vf.recurring_fee`

**Covers**: REQ-VF-15 … REQ-VF-20, REQ-VF-31 … REQ-VF-35, AE-VF-09 … AE-VF-16, §5.1

- [x] Write `test_vf_recurring_fee.py` (three tiers):
  - **Tier 1**: `test_recurring_fee_fires_on_typical_input` (AE-VF-09: exactly one alert, detector
    `vf.recurring_fee`, three refs, exact `data`); `test_recurring_fee_silent_on_clean_ledger`.
  - **Tier 2**: empty ledger → `[]` with `MappingProxyType({})`; single row → list; AE-VF-10
    (59.88 → info), AE-VF-11 (two charges), AE-VF-12 (33/34), AE-VF-13 (outlier), AE-VF-14
    (quarterly), AE-VF-15 (yearly), AE-VF-16; overdraft rows never produce a recurring alert; two
    rows with the same `source_ref`; first and last day of the 27-to-33 window; threshold
    `RECURRING_FEE_WARNING_YEARLY_COST` on both sides (59.99 / 60.00 yearly cost).
  - **Tier 3**: no invention (`alert.source_refs ⊆ loaded_source_refs(ledger, context)`),
    idempotency, empty input → `[]`, every money value in `data` is a non-negative two-decimal
    string, every cited ref resolves to a ledger row.
- [x] Implement `detectors/recurring_fee.py` with `@register("vf.recurring_fee")` and
  `detect_recurring_fees`. Title and `data` exactly as §5.1. Refs by `sorted_refs`.
- [ ] **Check (human)**: `pytest apps/vampire_fees/tests/test_vf_recurring_fee.py -q`; `ruff check .`

---

## Task VF7 — `vf.fee_increase`

**Covers**: REQ-VF-21 … REQ-VF-23, AE-VF-17 … AE-VF-20, §5.2

- [x] Write `test_vf_fee_increase.py` (three tiers): Tier 1 AE-VF-17 and AE-VF-20; Tier 2 5.24 vs
  5.25 (the `FEE_INCREASE_MIN_RATIO` boundary), 7.49 vs 7.50 (`FEE_INCREASE_CRITICAL_RATIO`), the
  spike AE-VF-19, a fall (6.50 → 5.00) raises nothing, two rises report the latest, new level
  drifting 1.9 % vs 2.1 % (`FEE_STABLE_RATIO` boundary), a run of only two rows, empty and one-row
  ledgers, duplicate `source_ref`; Tier 3 no invention, idempotency, empty input, `old_amount <
  new_amount`, exactly two refs.
- [x] Implement `detectors/fee_increase.py` with `@register("vf.fee_increase")`.
- [ ] **Check (human)**: `pytest apps/vampire_fees/tests/test_vf_fee_increase.py -q`; `ruff check .`

---

## Task VF8 — `vf.overdraft_cost`

**Covers**: REQ-VF-24 … REQ-VF-26, AE-VF-21 … AE-VF-23, §5.3

- [x] Write `test_vf_overdraft_cost.py` (three tiers): Tier 1 AE-VF-21; Tier 2 AE-VF-22 (100.00 vs
  99.99), AE-VF-23, only interest rows (`fee_count 0`, `fee_total "0.00"`), only fee rows, a
  concept-17 row with an overdraft word is overdraft kind, a concept-17 row without it is not,
  empty and one-row ledgers, duplicate `source_ref`; Tier 3 no invention, idempotency, empty input,
  `total == interest_total + fee_total` (as `Decimal`), refs equal the overdraft rows.
- [x] Implement `detectors/overdraft_cost.py` with `@register("vf.overdraft_cost")`.
- [ ] **Check (human)**: `pytest apps/vampire_fees/tests/test_vf_overdraft_cost.py -q`; `ruff check .`

---

## Task VF9 — `vf.fee_summary`

**Covers**: REQ-VF-27 … REQ-VF-30, AE-VF-24 … AE-VF-26, §5.4

- [x] Write `test_vf_fee_summary.py` (three tiers): Tier 1 AE-VF-24; Tier 2 AE-VF-25 (89 vs 90 days),
  AE-VF-26 (199.99 vs 200.00), a credit refund does not change the total, a non-EUR row neither
  counts nor extends the span, a ledger with fees only on one day, a statement whose credits widen
  the span, no fee → `[]`, empty and one-row ledgers, duplicate `source_ref`; Tier 3 no invention,
  idempotency, empty input, **`total_fees` equals the sum of the amounts of the cited rows**, and
  `fee_count == len(source_refs)`.
- [x] Implement `detectors/fee_summary.py` with `@register("vf.fee_summary")`.
- [ ] **Check (human)**: `pytest apps/vampire_fees/tests/test_vf_fee_summary.py -q`; `ruff check .`

---

## Task VF10 — Registry and explanation support

**Covers**: REQ-VF-05, REQ-VF-36 … REQ-VF-39, AE-VF-27, §6

- [x] Write `test_vf_registry.py`: after `auto_discover("apps.vampire_fees.detectors")`,
  `registered_names("vf")` equals the four names; calling `auto_discover` twice does not raise;
  `EXPECTED_NAMES` is defined once. Use `_snapshot_registry` / `_restore_registry` in a fixture.
- [x] Write `test_vf_explain_support.py`: a template exists for each registered detector; every
  placeholder is a key of the alert's `data` or `source_refs` (parse with `string.Formatter`);
  `fill_fallback` of AE-VF-27 gives the two exact strings; `template_for` picks the no-yearly
  variant; for each demo-shaped alert, a stub client answering with the filled template gives
  `source == "llm"` and no `rejected_numbers`; `HallucinatingStubClient` gives `source ==
  "fallback"` and `rejected_numbers == ("99999.99",)`; templates hold no digit.
- [x] Implement `detectors/__init__.py` (`auto_discover`) and `explain_support.py`.
- [ ] **Check (human)**: `pytest apps/vampire_fees/tests/test_vf_registry.py apps/vampire_fees/tests/test_vf_explain_support.py -q`

---

## Task VF11 — `config.toml` and `settings.py`

**Covers**: REQ-VF-12, REQ-VF-40 … REQ-VF-47 (view models), §2.3, §8.1

- [x] Write `test_vf_settings.py`: `load_config` reads the committed file; `load_vocabulary` returns
  the default vocabulary and raises `ValueError` naming the key for each invalid case of
  REQ-VF-12 (use `tmp_path` TOML); `demo_inputs(config, root, "csv")` and `"n43"` read the paths
  of `[demo]` (use synthetic bytes in `tmp_path`, not the committed demo); unknown format →
  `ValueError`; `ingest_statement` caches by hash; `run_pipeline` on a small CSV in bytes returns
  the ledger with credits and debits, `skipped_currency` counted, and alerts from `vf.*` only;
  `coffin_view` reads `alert.data` only and formats money with `format_amount` (`78,00 EUR`);
  `summary_view` with and without `yearly_equivalent` (`"n/a"`); `statement_caption`,
  `rule_sentences("csv" | "norma43")` (REQ-VF-45); `guard_badge` for the four cases;
  `group_alerts_by_severity`; `markdown_safe`.
- [x] Create `config.toml` (§2.3) and `settings.py` (§8.1). No Streamlit import.
- [ ] **Check (human)**: `pytest apps/vampire_fees/tests/test_vf_settings.py apps/vampire_fees/tests/test_vf_scaffold.py -q`

---

## Task VF12 — Demo generator mode

**Covers**: REQ-VF-49 … REQ-VF-51, REQ-VF-54, §7.1, §7.2

- [x] Write `test_vf_demo_generator.py`: `build_vampire_demo_rows(42)` has 227 rows, 25 credits and
  202 debits; the first row is `2025-01-02`, the last `2026-10-30`; every planted row of §7.2 is
  present exactly (day, counterparty, description, amount) — compare to a literal list in the test;
  the same seed gives the same bytes; another seed changes only `Card purchase` noise rows; noise
  shop names contain no vocabulary phrase for seeds 0 to 20 (fold with the app's own
  `fold_tokens` and the default vocabulary); `build_vampire_demo_csv(42)` is valid plain CSV with
  the bank columns; `build_vampire_demo_n43(42)` read through `parse_norma43` gives 227
  transactions and no quarantine; the Norma 43 concepts are `17` for the fee descriptions, `16` for
  `Comisión custodia valores`, `04` for `Transferencia gastos escritura`; `main(["--mode",
  "vampire-demo", "--out-dir", str(tmp_path)])` returns 0 and writes both files; the other modes'
  output is unchanged (`build_zombie_demo_csv(42)` bytes equal the committed zombie demo).
  `tests/test_generate_samples.py` gets `test_vampire_demo_mode_is_implemented`.
- [x] Implement the names of §7.1 in `scripts/generate_samples.py`: constants, the extra
  `N43_CONCEPT_BY_DESCRIPTION` entries, builders, `run_vampire_demo`, the `MODE_HANDLERS` entry,
  the docstring line and the `--help` text. Do not change any existing function.
- [x] **Check (human)**: `pytest apps/vampire_fees/tests/test_vf_demo_generator.py tests/test_generate_samples.py -q`

### HUMAN STEP H1 — write the committed demo files (done in session 13d)

```powershell
python scripts/generate_samples.py --mode vampire-demo
git status --short data/samples
```

Expected: `data/samples/vampire_demo_statement.csv` and `data/samples/vampire_demo_statement.n43`
appear as new files and nothing else under `data/samples` changes. Until this step is done, VF13
and VF14 fail loudly, which is intended.

---

## Task VF13 — Demo end-to-end and real formats

**Covers**: REQ-VF-02, REQ-VF-52, REQ-VF-53, AE-VF-20, §7.3

- [x] Write `test_vf_demo_e2e.py` **from the literal table of §7.3**, not from detector output:
  read `data/samples/vampire_demo_statement.csv` through `run_pipeline` with the vocabulary of the
  committed `config.toml`; assert 227 rows in the ledger, 202 debit rows, 0 quarantined,
  `skipped_currency == 0`; assert the six alerts (detector, severity, every `data` key and value)
  and their ref counts (22, 7, 2, 2, 7, 45); assert 1 critical, 3 warning, 2 info; assert the
  expected refs of every alert by finding the planted rows in the CSV by `(date, description,
  amount)` and building `f"{name}:{index}"`; assert plain `Decimal` sums equal `379.25`, `125.00`,
  `63.00`, `60.00`, `106.00`; assert each hard negative (H1 … H4, S, E1, E2) is cited by **no**
  alert except E1 and E2, which are cited by the summary only; assert the committed CSV equals
  `build_vampire_demo_csv(42)` byte for byte and the `.n43` equals `build_vampire_demo_n43(42)`.
- [x] Write `test_vf_real_formats.py`: run the Norma 43 demo and assert the same six alerts as the
  CSV demo in detector, severity, title and `data`, and the same number of refs (REQ-VF-53);
  `sniff_format` says `norma43` for the `.n43` and `csv` for the CSV; the Norma 43 run has the
  tags `common_concept:17` on the fee rows; **concept-only path**: build a two-row statement with
  the generator's `render_norma43` where one debit has description `TARJ 0042` and no fee word,
  read it with `read_bank_statement`, and assert `extract_fees` returns it (concept 17) while the
  same row as CSV returns none.
- [x] No production code in this task. If an assertion fails, fix the generator or the detector,
  not the expected values, unless the table of §7.3 itself has an error (then correct the table
  and say so in the hand-over).
- [x] **Check (human)**: `pytest apps/vampire_fees/tests/test_vf_demo_e2e.py apps/vampire_fees/tests/test_vf_real_formats.py -q`

---

## Task VF14 — The page

**Covers**: REQ-VF-38, REQ-VF-40 … REQ-VF-48, §8.2, §8.3

- [x] Write `test_vf_app_logic.py`: pure helpers (`coffin_html` escapes `<script>` in a description;
  CSS block holds `#9b1c31`, `#c2334d` and `clip-path: polygon`; interval labels), and headless
  `AppTest` runs of `apps/vampire_fees/app.py` (timeout 60 s; the registry is snapshotted and
  restored around each run):
  - empty state shows the `st.info` text;
  - **Load demo data** with `CSV` shows 3 coffins with `78,00 EUR`, `36,00 EUR`, `30,00 EUR`, the
    caption `227 rows` / `202 debit` figures, the metrics `45`, `379,25 EUR`, `207,54 EUR`, and
    6 alert cards grouped critical, warning, info; the rule sentence for CSV is shown;
  - the same with `Norma 43`: same coffins and alerts, the Norma 43 rule sentence;
  - the **hallucination toggle** on: every alert card shows the badge `⚠️ LLM answer rejected:
    invented number 99999.99` and the filled template, never `99999.99` as text of an explanation;
  - an uploaded CSV with one control-failed Norma 43 file shows the error message of
    `control_check_messages`;
  - no exception in any run; session-state keys all start with `vf_` (assert on
    `at.session_state` keys of the app).
- [x] Implement `app.py` per §8.2 and §8.3 (bootstrap, CSS, state, sidebar with the vocabulary
  expander, caption, metrics, coffins three per row with `html.escape`, alerts grouped by
  severity, quarantine). Reuse `reference_app` helpers; copy (do not import) the items C1 to C7 of
  §11.3 already placed in `settings.py` and `explain_support.py`.
- [ ] **Check (human)**: `pytest apps/vampire_fees/tests/test_vf_app_logic.py -q`

---

## Task VF15 — Showcase page and the files that list the apps

**Covers**: REQ-VF-55 … REQ-VF-57, §10

- [x] Update the tests first: `tests/test_showcase_app.py` (`PAGE_TITLES` gets "Vampire Fees"
  after "Phantom Invoices"; a run of the Vampire page loads the demo; Home text for three apps;
  the registry is snapshotted/restored as the file already does), `tests/test_showcase_requirements.py`
  (`APPS` has three entries and `test_apps_never_import_each_other` checks every ordered pair).
  Read both files fully before editing and change only what the new app needs.
- [x] Edit `streamlit_app.py`: one `PageSpec`, the Home `PROMISE` wording ("the apps in the menu"),
  `LAYERS` unchanged, a `VAMPIRE_BLURB`, three columns on Home. The entry page still imports no
  app. `.streamlit/config.toml` is not touched.
- [x] Edit, with only the lines the new app needs: `README.md` (one row in the apps table, one
  sentence on how the third app was built), `data/samples/README.md` (vampire demo section),
  `.gitattributes` (`data/samples/vampire_demo_statement.csv -text`),
  `.kiro/steering/structure.md` (layout tree: the app, its test files, the demo files, the
  generator mode), `.kiro/steering/testing.md` (`--cov=apps/vampire_fees`).
- [x] Also (found while writing, design 11.4 F-VF-1 and F-VF-2): `tests/test_benchmark_page.py`
  pins the page list and was updated to five pages; `tests/test_readme.py` keeps the heading
  `The two apps`, so the README section name was not changed.
- [ ] **Check (human)**: `pytest tests/test_showcase_app.py tests/test_showcase_requirements.py tests/test_showcase_theme.py tests/test_benchmark_page.py tests/test_readme.py tests/test_generate_samples.py tests/test_kiro_agents.py apps/phantom_invoices/tests/test_pi_structure_steering.py -q` (the vampire page runs need the demo files of step H1)

---

## Task VF16 — Whole-repository verification and the boundary check

**Covers**: REQ-VF-04, REQ-VF-58, `testing.md` CI requirements

- [ ] Nothing to write. The human runs, in order, and pastes the output into the hand-over:

```powershell
.\.venv\Scripts\Activate.ps1
ruff format .
ruff check .
ruff format --check .
pytest --cov=ledger_kit --cov=apps/zombie_subscriptions --cov=apps/phantom_invoices --cov=apps/vampire_fees --cov-fail-under=80
git status --short ledger_kit apps/zombie_subscriptions apps/phantom_invoices pyproject.toml requirements.txt .streamlit
git diff --stat
```

- [ ] Expected: `ruff` clean; all tests green; coverage at least 80 %; the `git status` command
  prints **nothing**; `git diff --stat` lists only paths allowed by REQ-VF-58. Any other path is a
  finding to write in the record below.

---

## Task VF17 — Record: Kiro calls and time (filled in by the reviewer)

**Covers**: REQ-VF-59, REQ-VF-60

The reviewer fills this table after the build session. The agent leaves it blank.

| Item | Value |
|---|---|
| Date and Kiro version | |
| Agent used | `ghost-ledger-builder` |
| Kiro calls (requests or credits, as the usage panel shows) | |
| Elapsed time, first prompt to green `pytest` | |
| Of which waiting for the human to run commands | |
| Human interventions (each: what, why) | |
| Files outside `apps/vampire_fees/` changed (count and list) | |
| Edits in `ledger_kit/` (expected 0) | |
| Edits in the other apps (expected 0) | |
| Output of `git status --short ledger_kit apps/zombie_subscriptions apps/phantom_invoices` | |
| Library decisions `DN-VF-L<n>` raised | |
| Copied helpers (design §11.3), count at the end | |
| Tests written (files, approximate count) | |
| Result: did the template claim hold? | |
| Comparison with the first two apps (if known) | |
