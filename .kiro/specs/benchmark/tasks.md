# benchmark — Implementation Tasks

Every task is test-first: write the tests (they fail), then the code. Section references (§)
point to `design.md`, REQ ids to `requirements.md`. Verification (`ruff check .`,
`ruff format --check .`, `pytest`) is run by the user. No task changes a detector, a threshold or
a demo file (REQ-BM-22). Test files are loaded by path where they import from `scripts/`
(`scripts/` is not a package), like `tests/test_generate_samples.py`.

## Task BM1 — Matching and metrics

**Covers**: REQ-BM-12, REQ-BM-13, §3.2, §3.3

- [ ] `tests/test_benchmark_matching.py`: the hand-made sets of REQ-BM-12 (eleven cases, including
  context rows, two labels with equal overlap, natural order of `f.csv:9` / `f.csv:10`), the ratio
  examples of REQ-BM-13 (`0.7778`, `0.7000`, `0.6667`, `0.3333`, `1.0000`, `null`), the
  noise-only figures (6 alerts / 40 scenarios → `0.1500`) and the hard-negative attribution
  example; Hypothesis properties (`max_examples=200`): conservation, order independence,
  idempotence, matched pairs share scenario, type and a ref, empty input gives zeros.
- [ ] Create `scripts/benchmark.py` with only the pure part: `AlertRecord`, `natural`, `match`,
  `ratio`, `metrics`, `attribute_false_positives`. No I/O, no pipeline yet.

## Task BM2 — Generator core and independence

**Covers**: REQ-BM-02, REQ-BM-03, REQ-BM-04, REQ-BM-09, REQ-BM-10 (identifiers), REQ-BM-23
(names), §2.1, §2.2, §2.3, §2.8, §2.9

- [ ] `tests/test_benchmark_generator.py`, first part: independence by AST (allowed imports) and by
  detector constant names (collected at test time from the detector modules), seed and index
  independence (scenario 7 inside runs of 10 and 200, other seed differs, RNG seed text
  `"2026:zombie:7"`), ids / file names / noise-only share / header line for n = 200 and n = 10,
  `RowTable` (refs from tags after ordering, unknown tag raises, empty label raises
  `label zs-0003/L2 cites no row`), identifier checks with test-local mod-97 / control-character
  checkers, no clock / network names in the AST.
- [ ] Create `scripts/generate_benchmark.py`: dataclasses, `RowTable`, string-seeded RNG, own IBAN /
  CIF / NIF helpers, name pools, CSV rendering, `build_scenario` / `build_scenarios` with empty
  case and negative lists (every scenario noise only for now).

## Task BM3 — Zombie cases, hard negatives, noise

**Covers**: REQ-BM-05 (zombie), REQ-BM-06 (zombie), REQ-BM-07 (zombie), REQ-BM-08, §2.4, §2.5,
§2.6

- [ ] Extend `tests/test_benchmark_generator.py`: golden examples of REQ-BM-06 for Z08, Z10, Z15,
  Z17 and the hard negatives `price_below_threshold`, `trial_too_early`, `cancel_same_day` (exact
  rows, dates, labels, context); NZ01 shape (26 weekly rows, amounts in range); salary yields no
  debit row; coverage at n = 200 (each zombie type ≥ 20 labels, each case ≥ 20, each hard-negative
  kind ≥ 15); noise count and distinct merchants; row cap 200; ingestion round trip with
  `read_bank_statement` (zero quarantine, every label ref resolves, row facts equal).
- [ ] Implement the 17 zombie cases, 14 zombie hard negatives, the zombie noise and the schedule
  of §2.2.

## Task BM4 — Phantom cases and hard negatives

**Covers**: REQ-BM-05 (phantom), REQ-BM-06 (phantom), REQ-BM-07 (phantom), REQ-BM-10, §2.4,
§2.5, §2.6, §2.7

- [ ] Extend `tests/test_benchmark_generator.py`: golden examples of REQ-BM-06 for P10b, P04, P02,
  P14 and `vat_off_by_one_cent`, `same_total_7_days_apart`, `numbering_restart_180`,
  `open_at_due_plus_15`; the golden rounding table against `percent_of` / `net_total`; case P01
  yields two invoices and two payments of equal amount; every non-overdue invoice is paid within
  10–40 days and not after `as_of`; coverage at n = 200 (11 phantom types, 17 cases, 14 kinds);
  ingestion round trip through `read_invoices`, `parse_suppliers`, `read_bank_statement` (zero
  quarantine, refs resolve, facts equal); no invalid IBAN outside P07–P09.
- [ ] Implement the 17 phantom cases, 14 phantom hard negatives, the phantom noise and the
  schedule.

## Task BM5 — Runner pipelines and error capture

**Covers**: REQ-BM-11, REQ-BM-14, §3.1, §3.4

- [ ] `tests/test_benchmark_runner.py`, first part: the zombie runner on the committed demo
  statement with the demo aliases and dates gives 19 alerts, the phantom runner on the committed
  phantom demo gives 9 (constants copied from `tests/test_showcase_app.py` with a comment naming
  them); a six-month salary produces no alert; a detector replaced by one that raises
  `ValueError("boom")` is counted per scenario and the run reports exit code 1 without writing
  (registry snapshot / restore as in `test_showcase_app.py`).
- [ ] Add `run_zombie`, `run_phantom`, the logging handler and `run_scenarios` to
  `scripts/benchmark.py`.

## Task BM6 — Results, documentation, CLI

**Covers**: REQ-BM-13 (aggregation), REQ-BM-15, REQ-BM-16, REQ-BM-17, §3.5, §3.6, §3.7

- [ ] Extend `tests/test_benchmark_runner.py`: schema and top-level key order of a reduced run (10
  scenarios), byte rules (LF only, UTF-8, no BOM, final newline, no date / path / machine name),
  per-detector `seed`, `render_markdown` from a hand-made results dict (six `limits` → six list
  items, every integer of the document is in the dict, `null` → `n/a`, no digit in static text),
  CLI: `--seed 7` alone → exit 2 with the message, `--seed 7 --scenarios 10 --out-dir tmp` writes
  `results.json` and `benchmark.md` and leaves the committed files alone, `--check` exits 1 when
  one byte differs, `--export-scenarios` layout; reduced run twice → equal bytes, other seed →
  different bytes.
- [ ] Implement aggregation, `render_markdown`, serialisation and the CLI.

## Task BM7 — First full run, run time, committed results

**Covers**: REQ-BM-18, REQ-BM-19, REQ-BM-23, §4

- [ ] Add to `tests/test_benchmark_runner.py` the committed-results test: one module-scoped full
  run at `BENCHMARK_SEED` and `SCENARIOS_PER_APP`; `results.json` and `benchmark.md` bytes equal
  the committed files (failure names the first differing line); `schema_version`, `seed` and
  `scenarios_per_app` equal the constants.
- [ ] Run `python scripts/benchmark.py` once, time it. If it takes more than 45 s lower
  `SCENARIOS_PER_APP` to the largest multiple of 20 that fits (D-BM-17) and rerun. Commit
  `data/benchmark/results.json` and `docs/benchmark.md`.
- [ ] `.gitattributes`: `data/benchmark/*.json -text`, `docs/benchmark.md -text`; check
  `.gitignore` does not ignore the two files (add `!data/benchmark/` and `!data/benchmark/**`
  after any `*.json` rule).

## Task BM8 — Benchmark page

**Covers**: REQ-BM-20, REQ-BM-21, §5

- [ ] `tests/test_benchmark_page.py`: `PAGES` titles and `url_path`, the page function run with
  `AppTest.from_string` and a monkeypatched `RESULTS_PATH` (synthetic results: the
  `zs.price_increase` row, `n/a`, the two limits, seed line), missing file / invalid JSON /
  `schema_version: 99` → one `st.error` and no exception, AST of `streamlit_app.py` imports none
  of `scripts`, `apps`, `ledger_kit.detectors`, entry run without exception. Try
  `at.switch_page("benchmark")` and keep it as an extra test only if it works (§5).
- [ ] Update `PAGE_TITLES` in `tests/test_showcase_app.py` and amend REQ-SC-01 in
  `.kiro/specs/showcase/requirements.md` (three → four pages).
- [ ] Add `FUNCTION_PAGES`, the Benchmark `PageSpec` and `benchmark()` to `streamlit_app.py`.

## Task BM9 — Findings, follow-ups, documentation

**Covers**: REQ-BM-22, REQ-BM-23, §8

- [ ] Read `false_positives` and `misses` of the committed `results.json`. For each finding write
  a row in the "Measured" table of `design.md` §8 (scenario id, rows, observed, expected, test to
  write first); confirm or delete FU-P1, FU-P2, FU-P3. Do not touch a detector, a label or a hard
  negative. A test checks that every scenario id in the two lists is named by a Follow-up row or
  covered by a grouped row that names its kind.
- [ ] Steering: add `scripts/generate_benchmark.py`, `scripts/benchmark.py`, `data/benchmark/`,
  `docs/benchmark.md` and the four test files to the layout of `structure.md`; add `data/benchmark/`
  (synthetic, generated, no personal data) to the data-directory rules and to Finance Rule 6.
- [ ] Out of scope, noted for the reviewer: the README and Home page sentences that cite the
  benchmark number (session 7).

## Not verified by the author

The tasks were written without running a command. The user runs `ruff check .`,
`ruff format --check .`, `pytest` and the first full benchmark run (BM7), measures its time and
reports failures.
