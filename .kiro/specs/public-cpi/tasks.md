# public-cpi — Implementation Tasks

Every task is test-first: write the tests named in the task, see them fail, then implement. Section
references (§) point to `design.md`, REQ ids to `requirements.md`. Hypothesis tests use
`settings(max_examples=200)`. Nothing reads the clock or the network. Verification (`ruff check .`,
`ruff format --check .`, `pytest`, a headless run of the Zombie app and of `streamlit_app.py`) is run by the
user; the author of the spec could not run anything.

Order matters: CPI1 to CPI3 are library and script work that need no app; CPI4 is the only task with a
**manual developer step** (running the script against the real API and committing the result) and every
later task that reads the real snapshot (CPI9, CPI10) depends on it; CPI5 to CPI8 use synthetic series only.

## Task CPI1 — Percent helpers in `money.py`

**Covers**: REQ-CPI-08, §2

- [x] Tests in `tests/test_money.py`: every example of REQ-CPI-08 (`18.0`, `2.0`, `30.0`, `23.1`, `0.3`
  for the two index values **(INE)**, half-up at `400→401` = `0.3` and `400→399` = `-0.3`);
  `percent_change` raises `ValueError` for `old = 0` and `old < 0`; `format_percent` (`"30,0 %"`, `"-0,3 %"`,
  `"1.234,5 %"`, `"0,0 %"`); `format_index` (`"104,978"`, `"100,000"`); the existing `format_amount` tests still
  pass unchanged. Hypothesis: `abs(round_percent(percent_change(a, b)) - percent_change(a, b)) <= 0.05` and the
  sign of the result follows `b - a`, for positive Decimals with up to three decimals.
- [x] Add `PERCENT_DECIMALS`, `percent_change`, `round_percent`, `format_percent`, `format_index` to
  `ledger_kit/utils/money.py`; factor the digit formatting so `format_amount` is byte-for-byte unchanged.

## Task CPI2 — Reader `ledger_kit/public_data/ine_cpi.py`

**Covers**: REQ-CPI-05, REQ-CPI-06, REQ-CPI-07, REQ-CPI-03 (library validator), §4

- [x] `tests/public_data/test_ine_cpi_reader.py`, fixtures `cpi_s_series`, `cpi_gapped_series`, `cpi_c_series`
  (all **synthetic**, in `tests/public_data/conftest.py`): the lookups of REQ-CPI-06 (exact, gap fallback
  with `is_fallback=True` and `used="2026-01"`, `date(2026, 2, 17)`, before, one month after = last month with
  `is_fallback=True`, two months after = `None`, on both series); invalid months (`"2026-13"`, `"2026-9"`, `"abc"`, `None`, `20260201`) raise `ValueError`; a `datetime` with a
  time part works; a one-month series; the value is the same `Decimal` object text (`str(point.value) ==
  "100.500"`); `load_snapshot` of a tiny valid temp file; `SnapshotError` for a missing file, invalid JSON,
  and every rejection of REQ-CPI-03 with its exact message (gap, `0.000`, two decimals, `IPC251852`, base year
  2021, repeated month, wrong `first_month`/`last_month`, extra key, missing key, empty status). Hypothesis:
  REQ-CPI-07 (never a later month, value belongs to the series, `used` is published, never raises for a valid
  out-of-range month).
- [x] Create `ledger_kit/public_data/__init__.py` (public names only) and `ine_cpi.py` (stdlib only). Add the
  package to `pyproject.toml` package discovery if packages are listed explicitly (read `tests/test_packaging.py`
  first and extend it if it enumerates packages).

## Task CPI3 — Fetch script `scripts/fetch_ine_cpi.py`

**Covers**: REQ-CPI-01, REQ-CPI-02, REQ-CPI-03, REQ-CPI-04, §3.1

- [x] `tests/test_fetch_ine_cpi.py` (loads the script by path like `tests/test_generate_samples.py` does for
  `generate_samples.py`; a module-level autouse fixture replaces `socket.socket.connect` with a function that
  fails the test): a fake opener returns a payload of 117 contiguous synthetic months (real shape: `Fecha`
  string, `T3_TipoDato`, `T3_Periodo`, `Anyo`, `Valor`; `Nombre` with a trailing space) → file written with the
  exact key order and `"value"` strings, `main` returns 0 and prints `wrote ...`; `Valor` as `104.9` pads to
  `"104.900"`, as `104.9781` is an error; a payload with `COD` `IPC251852` → exit 1 and the exact stderr line,
  existing file byte-identical afterwards; first month `2018-03` → exit 1; fake opener raising `URLError`,
  `HTTPError(404)` (checks the order of `except`), `TimeoutError`, and a body that is not JSON; an entry without
  `T3_TipoDato` → `error: no status for ...`; a `T3_Periodo` of `M13` → error; entries before 2017-01 are
  dropped; the output is UTF-8 with LF and a final newline; `retrieved_on` equals the injected `today`;
  `build_url(date(2026, 11, 9))` ends with `?date=20170101:20261109&tip=A`; the script file imports nothing outside
  the standard library (AST scan of its imports against `sys.stdlib_module_names`). Hypothesis: `build_snapshot`
  of generated contiguous payloads passes `ine_cpi.validate_snapshot` (this is the drift guard of DN-CPI-09).
- [x] Write the script as in §3.1. No `float`, no `datetime.now()` outside `main`.

## Task CPI4 — Snapshot, `.gitignore`, snapshot tests (manual step)

**Covers**: REQ-CPI-20, REQ-CPI-03, §3.4

- [x] Tests first: `tests/public_data/test_ine_cpi_snapshot.py` loads `data/public/ine_cpi_ipc290751.json` through
  `load_snapshot` and asserts the pinned checks of REQ-CPI-20 (`first_month == "2017-01"`, `last_month >=
  "2026-09"`, `2026-08 → 104.638`, `2026-09 → 104.978`, status `Definitivo`, `licence`, `attribution`,
  `no_endorsement`, `retrieved_on >= "2026-11-09"`, `base_year == 2025`, `series_code == "IPC290751"`,
  `"IPC251852"` appears nowhere in the file, every value positive). A text test of `.gitignore` asserts the two
  lines `!data/public/` and `!data/public/**` follow `*.json`. Both fail until the steps below are done.
- [x] `.gitignore`: add the two exception lines. *(Done in session 9b, ahead of its test; the test is still
  written in CPI4.)*
- [ ] **Developer step**: run `python scripts/fetch_ine_cpi.py` (Windows PowerShell, venv active), read the
  one-line result, run `git status` and check the file is listed (not ignored), commit it. The API field names
  are settled (DN-CPI-16); re-run the script once the INE publishes October 2026. *(Session 9c: the script was
  run on 2026-11-09 and printed `wrote data/public/ine_cpi_ipc290751.json: 117 months, 2017-01 to 2026-09`;
  the commit is still pending, so this box stays open until `git status` shows the file tracked.)*
- [x] Create `data/public/README.md`: source, series, licence line, attribution text, non-endorsement text,
  the statement that the snapshot is INE data that keeps the INE licence and is not covered by the repository
  MIT licence, the refresh command, the statement that no personal data is present.

## Task CPI5 — `Series.step_index` (no behaviour change)

**Covers**: REQ-CPI-10, REQ-CPI-12, §5.1

- [x] Tests in `apps/zombie_subscriptions/tests/test_zs_segment_by_price.py`: for the step fixtures already used
  there (`9.99 x3 → 12.99 x3`, `12.99 x3 → 15.99 x3`, the edge cases with a single row on one side), the series
  returned is **equal to before in every old field** and `step_index` is the index of the first new-level row;
  a stable series and a variable-bill series have `step_index is None`; after `_extend_once` and `_merge_once`
  in `test_zs_find_series.py` fixtures the index still points at the first row of the new level. Run all
  existing `test_zs_*` first: they must pass unchanged.
- [x] Add the field, thread `p` through the `splits` list and `_make_series` (§5.1). No other line of
  `_segment_by_price` changes.

## Task CPI6 — CPI context in `zs.price_increase`

**Covers**: REQ-CPI-09, REQ-CPI-10, REQ-CPI-11, REQ-CPI-12, REQ-CPI-13, REQ-CPI-15, §5.2, §5.3

- [x] `apps/zombie_subscriptions/tests/test_zs_price_increase_cpi.py` (the existing
  `test_zs_price_increase.py` is not edited; it keeps proving the no-CPI behaviour): Tier 1 — the exact
  18-versus-2 dict of REQ-CPI-11 with series C; the same ledger without `cpi` equals the six-key dict; E1 of
  the existing file with series C that does not cover 2026 (no CPI keys). Tier 2 — every REQ-CPI-13 case
  (before range, two months after range, one month after range = lag fallback, same-month weekly step, gap
  fallback with differing months, `cpi` is `None`,
  `cpi` is an object without `lookup`); empty and single-row ledgers with `cpi` present return `[]`/list; the
  threshold boundary tests (`5 %` fires, `4,95 %` does not) repeated with `cpi` present give the same alerts;
  a duplicate `source_ref` row does not crash. Tier 3 — the REQ-CPI-12 property (alerts with and without a
  random CPI series agree on `(detector, severity, title, source_refs)` and the six base keys) and the
  `source_refs ⊆ loaded_source_refs(ledger, context)` property with `context["cpi"]` set; idempotency.
- [x] Add `cpi_context_fields` to `detectors/utils.py`; in `price_increase.py` read `context.get("cpi")` and
  merge the fields (§5.2). The condition lines are not touched.

## Task CPI7 — Formatter specs and the number guard with CPI figures

**Covers**: REQ-CPI-14, REQ-CPI-16, §6.3, §6.4

- [x] Tests in `tests/test_explainer.py`: `fill_fallback` with `{x:pct}` (`"18.0"` → `18,0 %`, `"-0.3"` →
  `-0,3 %`, `"n/a"` unchanged) and `{x:idx}` (`"104.978"` → `104,978`); `money` behaviour unchanged. In
  `apps/zombie_subscriptions/tests/test_zs_cpi_support.py` (guard part, `MockLLMClient` as in the existing
  explainer tests): the four texts of REQ-CPI-14 (accepted; `2,5` rejected with `rejected_numbers ==
  ("2,5",)`; invented index `103.000` rejected; `2 %` accepted and `2,04 %` rejected); the system message sent
  to the client still contains the mandatory sentence verbatim and the alert JSON contains `cpi_change_percent`;
  `Explanation` is the fallback with the CPI sentence when rejected. Hypothesis: a text built only from numbers
  of `alert.data` is accepted, and the same text plus one number outside `data` is rejected.
- [x] Add the two branches to `_AlertFormatter.format_field`. No change to the guard, the prompt or the row
  columns sent.

## Task CPI8 — Template and card helpers

**Covers**: REQ-CPI-17, REQ-CPI-18, §7

- [x] Tests in `test_zs_cpi_support.py`: `template_for` returns `TEMPLATES["zs.price_increase"]` for an alert
  without CPI keys, the CPI variant with them and the lag variant when a CPI month differs from its price month; the
  filled text equals the string of REQ-CPI-17 exactly;
  `TEMPLATES` keys still equal the registered `zs.*` names (the existing test in `test_zs_explain_support.py`
  is not edited); the sentence contains none of `above`, `below`, `exceeds`, `should`; `cpi_source_line`
  (`CPI source: INE series IPC290751 (base 2025 = 100), 2026-01 = 100,000, 2026-04 = 102,000`, `None` without
  keys); `cpi_sentence_to_add` returns `None` for the fallback explanation (already contains it), the sentence for
  an LLM text without it, `None` for an alert without CPI keys; the sentence is never produced twice;
  `attribution_lines` returns the three lines of REQ-CPI-19 from a `CpiSeries`; text with markdown characters in
  the series name is escaped by `markdown_safe`.
- [x] Add `CPI_SENTENCE`, `PRICE_INCREASE_WITH_CPI_TEMPLATE`, `template_for` to `explain_support.py` and the
  three helpers to `settings.py`.

## Task CPI9 — App wiring and demo run

**Covers**: REQ-CPI-18, REQ-CPI-19, REQ-CPI-21, §8

Needs the committed snapshot of CPI4.

- [x] `apps/zombie_subscriptions/tests/test_zs_cpi_demo.py` (headless `AppTest`, same helpers as
  `test_zs_app.py`): after Load demo data: 3 tombstones; 19 alerts (1 critical, 4 warning, 14 info) — the counts
  of the existing app test, asserted again with the snapshot loaded; the `CLOUDVAULT` price card contains
  `30,0 %`, `IPC290751`, `2026-05`, `2026-08`, the CPI percent **computed in the test** from the snapshot with
  `load_snapshot`, `percent_change` and `round_percent`, and exactly one element with `changed by`; the
  `STREAMFLEX INTL` card contains the CPI sentence **if and only if** the lookups answer under REQ-CPI-06 (with
  `last_month == "2026-09"` it shows `23,1 %`, the lag-variant sentence, `cpi_end_month` `2026-09` and the price
  months `2026-05` and `2026-10`; with `last_month >= "2026-10"` the plain sentence; expectation computed from the
  snapshot); no other card (recurring, duplicate,
  trial, cancellation) contains `IPC290751`; the footer contains the three attribution lines once; switching
  the toggle *Simulate a hallucinating LLM* still shows the rejected badge and, on the CLOUDVAULT card, the
  sentence supplied by the card (not by the LLM); a run with `snapshot_path` pointing to a missing file (the
  test patches `load_cpi`'s input config) shows `CPI context unavailable: snapshot not found.`, no attribution,
  and still 19 alerts. The same run for the Norma 43 demo ("Real formats") gives the same CPI lines
  (months come from row dates, identical in both formats). Existing `test_zs_app.py` and
  `test_zs_real_formats.py` pass unchanged (the latter compares `data` of both formats: CPI keys are equal).
- [x] Add `[cpi]` to `config.toml`, `load_cpi` to `settings.py`; in `app.py` the cached loader, `context["cpi"]`,
  `template_for`, the card lines in `_render_alert`, the footer `_render_attribution`. Add the one-line
  attribution caption to the showcase Home page (`streamlit_app.py`, DN-CPI-20) with a test in
  `tests/test_showcase_app.py`.

## Task CPI10 — README, sample docs, attribution consistency

**Covers**: REQ-CPI-19, §8

- [x] Read `tests/test_readme.py` (`REQUIRED_HEADINGS`, fence handling) before editing. Tests: the README
  contains the attribution, `CC BY 4.0` and the non-endorsement text exactly as in the snapshot; `data/public/README.md`
  contains the same three; a test compares the three sources (snapshot, README, `data/public/README.md`); the
  README states that the apps never call the network and names `python scripts/fetch_ine_cpi.py`; the existing
  README tests still pass (add the new heading to `REQUIRED_HEADINGS` only if the section is kept as a
  top-level heading).
- [x] Add a short "Public data" section to `README.md` and a pointer line in `data/samples/README.md`
  ("official public data lives in `data/public/`"). The README says in one sentence what the comparison is and
  that it is context, not a verdict. No claim of test counts or coverage.

## Task CPI11 — Steering updates and final checks

**Covers**: all REQ ids, §11

- [x] Steering edits (proposed text, reviewed with the user before saving because these files bind every later
  session): `finance-rules.md` — Rule 6 widened to "`data/public/`: official public data under an open licence
  with a licence reference and the required attribution; never personal data", and a new Rule 9 "Public reference
  data": a figure from a committed public snapshot may appear only as a named field of `Alert.data` with its
  series code and period, never in `source_refs`, with attribution displayed where it is shown, and without
  implying endorsement; `structure.md` — add `ledger_kit/public_data/`, `scripts/fetch_ine_cpi.py`,
  `data/public/`, the new tests and the `.gitignore` exception (keep `test_pi_structure_steering.py` green: read
  it first); `tech.md` — the INE API row (stdlib only, script only, never at run time).
- [ ] Final checklist, run by the user: `ruff check .`; `ruff format --check .`; `pytest`; coverage at least
  80 % (`--cov=ledger_kit --cov=apps/zombie_subscriptions --cov=apps/phantom_invoices`); `streamlit run
  apps/zombie_subscriptions/app.py` and Load demo data (3 tombstones, 19 alerts, the `CLOUDVAULT` card with its
  CPI sentence, the footer attribution); `streamlit run streamlit_app.py` still loads both pages; `git status`
  shows `data/public/ine_cpi_ipc290751.json` tracked.

---

## Decisions on the former open questions (answered 9 November 2026, session 9b)

Each former question is now a decision in the table of `design.md` §11.

| Question | Answer | Decision |
|---|---|---|
| Q1 — Attribution wording | The accented text is right; the notice body applies CC BY 4.0 (the page footer says CC BY-SA 4.0, an inconsistency of the page). `data/public/README.md` says the snapshot keeps the INE licence, is not covered by the repository MIT licence, and that the INE does not take part in, sponsor or support the reuse | DN-CPI-15 |
| Q2 — Status field | `T3_TipoDato` with `tip=A`; month from `Anyo` + `T3_Periodo`; name stripped; `json.loads(parse_float=Decimal)` | DN-CPI-16 |
| Q3 — `nult` with `tip=A` | Works, but the script uses one request: `tip=A` and `date=20170101:YYYYMMDD` | DN-CPI-16 |
| Q4 — Guard widening | Accepted: months stored as `YYYY-MM`, the small widening is documented | DN-CPI-17, DN-CPI-18 |
| Q5 — Home page credit | Yes: one short attribution line on the showcase Home page | DN-CPI-20 |
| Q6 — Newest month | `CPI_MAX_LAG_MONTHS = 1`: one month after `last_month` answers with `last_month` (`is_fallback=True`), labelled as the latest published month; two or more give no CPI context; the card always shows price months and CPI months when they differ; the developer re-runs the script once October is published | DN-CPI-03, DN-CPI-19 |
| Q7 — `Series.step_index` | Accepted: every existing test stays green and no detection condition changes | DN-CPI-21 |
