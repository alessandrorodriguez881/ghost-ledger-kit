# Ghost Ledger builder

You build a new small app on Ghost Ledger Kit using only what the template already offers. The
steering files, the README and the `add-detector` skill are loaded for you: follow them, do not
restate them. This file is the recipe and the order of work.

The point of every app you build is a measurement: **how fast a new app appears on the kit**. So
the rule that matters most is the boundary below.

## Hard rules

1. Never edit anything under `ledger_kit/`, and never edit another app (`apps/zombie_subscriptions/`,
   `apps/phantom_invoices/`, or any other `apps/<other>/`). Never import one app from another.
2. If you believe the library must change, **stop**. Write the gap as an explicit decision in the
   spec `design.md` (id `DN-<XX>-L<n>`: what is missing, evidence in file and line, the smallest
   change, what you did instead) and ask the human. Do not edit the library "just this once".
   Copying a small helper into your own app is allowed and must also be listed as a decision.
3. You can read and write files. You cannot run commands. Never claim that a test, ruff or the
   generator ran. Never invent test output, counts or file contents you did not write.
4. Finance Rules 1 to 9 apply to everything: no invented figure, every alert cites `source_refs`,
   `Decimal` and the helpers of `ledger_kit/utils/money.py`, European display, synthetic data only,
   named threshold constants, no financial advice from the LLM.
5. Read before you write: the closest existing app (`apps/zombie_subscriptions/` for statements,
   `apps/phantom_invoices/` for several inputs), `ledger_kit/ui/reference_app.py`,
   `ledger_kit/explainer.py`, `ledger_kit/detectors/registry.py`. Copy their shape and names. If
   something is unclear about a library API (pandas, Streamlit, Hypothesis), ask context7 before
   guessing.

## The recipe, in order

### 1. Spec first (skip only if `.kiro/specs/<name>/` already exists and is approved)

Create `.kiro/specs/<name>/requirements.md`, `design.md`, `tasks.md`.

- `requirements.md`: requirement ids `REQ-<XX>-nn` written in EARS (`The <system> shall ...`,
  `When <trigger>, the <system> shall ...`, `While <state>, ...`, `If <condition>, then ...`,
  `Where <feature>, ...`), grouped by topic, plus acceptance examples `AE-<XX>-nn` with a concrete
  input (rows, amounts, dates) and the exact output (alert fields, strings). A requirement without
  a testable example is not finished.
- `design.md`: module map, a table of every threshold constant with its value and the reason,
  the alert `data` keys per detector, the fallback templates, the demo tables, and a **library
  decisions** section that lists every gap found (see rule 2) or states that there is none.
- `tasks.md`: test-first tasks `<XX>1`, `<XX>2`, ... Each task names the tests to write first, then
  the code, then the check commands for the human. End with a task that records Kiro calls and
  elapsed time for the reviewer to fill in.

### 2. Package layout (`.kiro/steering/structure.md` is the authority)

```
apps/<name>/
  __init__.py  app.py  config.toml  settings.py  explain_support.py
  detectors/__init__.py  detectors/utils.py  detectors/<one module per detector>.py
  tests/conftest.py  tests/<xx>_builders.py  tests/test_<xx>_<module>.py
```

- `<xx>` is a two-letter app prefix for test files and session-state keys. `apps/__init__.py`
  exists already. No `requirements.txt` inside the app.
- `detectors/__init__.py` calls `auto_discover("apps.<name>.detectors")`, as the other apps do.
- `app.py` starts with the `sys.path` bootstrap of the other apps and ends with the
  `if __name__ == "__main__": main()` guard, so it works alone and as a page of `streamlit_app.py`.

### 3. Detectors

- Register under a **new namespace**: `@register("<xx>.<detector>")`, lowercase snake_case.
- Signature `(ledger: pd.DataFrame, context: Mapping[str, Any]) -> list[Alert]`. Pure: no I/O, no
  clock, no mutation. Anything a detector needs beyond the ledger comes through `context`.
- Every threshold is a module-level `UPPER_SNAKE_CASE` constant with a comment giving its reason.
  Constants live in `detectors/utils.py`; none lives in `config.toml` (vocabularies and demo paths
  may).
- Every alert has a non-empty `source_refs` list holding only refs of loaded rows, ordered by
  `(date, source_row)`, deduplicated. Every figure the explanation may quote is a named key of
  `Alert.data` (strings for money and dates, ints for counts). Money only through `money.py`.
- Empty ledger returns `[]`. A duplicate `source_ref` is handled, not fatal.
- Add one fallback template per detector (and per variant) in `explain_support.py`, and a stub
  `HallucinatingStubClient` whose answer contains `99999.99`, with the same shape as the other
  apps (`chat`, `completions` properties and `create`).

### 4. Pipeline, settings and page

- `settings.py` holds `load_config`, the demo inputs, `run_pipeline(name, data, ..., cache)` and the
  view-model helpers (guard badge, severity grouping, card view). No Streamlit import there.
- Read statements with `ledger_kit.ingestion.sniffer.read_bank_statement` (CSV and Norma 43, picked
  by content), then `normalise`, then `run_all(ledger, namespace="<xx>", context=...)`. Show
  quarantine and `control_check_messages`. Do not write a reader.
- Explain with `ledger_kit.explainer.explain_with_meta(alert, rows, fallback_template=...,
  client=...)`, cached per `(alert.id, client mode)` in `st.session_state`. The sidebar toggle
  *Simulate a hallucinating LLM* swaps in the stub client. The number guard belongs to the library:
  never bypass it, never post-process its output.
- Reuse the UI helpers of `ledger_kit/ui/reference_app.py` (`SEVERITY_BADGES`, `count_by_severity`,
  `format_for_display`, `quarantine_table`, `rows_for_refs`). Session-state keys are prefixed
  `<xx>_`; the sidebar widget values are kept and restored like the other apps so they survive a
  visit to another page.
- Theme: the shared dark theme of `.streamlit/config.toml` is not edited. Page colours live in the
  app's own CSS block.

### 5. Tests (three tiers, no real data, no wall clock)

- Write the test before the code, one file per module, `test_<xx>_<module>.py`.
- Tier 1 normal case and clean ledger; tier 2 empty ledger, single row, both sides of every
  threshold constant, first and last day of every window, duplicate `source_ref`; tier 3
  Hypothesis with `@settings(max_examples=200)`: no invention
  (`alert.source_refs ⊆ ledger_kit.detectors.loaded_source_refs(ledger, context)`), idempotency,
  empty input, non-negative amounts, plus one property that ties a figure to its cited rows.
- Contract tests: registry names, template for every detector, template accepted by the number
  guard through a stub client, hallucinated answer rejected and replaced by the template.
- Headless `AppTest` runs of `app.py` (demo CSV, demo Norma 43, hallucination switch, empty state).
- Boundary tests: no module of the app imports another app; none imports a private (`_name`)
  library name; `git`-level proof that `ledger_kit/` and the other apps are untouched is a command
  for the human (step 8).

### 6. Demo data

- Add a seeded mode to `scripts/generate_samples.py` (new entry in `MODE_HANDLERS`, builder
  functions, constants for the file names). Reuse `BankRow`, `render_bank_csv` and
  `render_norma43`. Planted cases are literal tables; the seed drives only the noise. Write both
  `data/samples/<name>_demo_statement.csv` and `.n43` from the same rows.
- Plant realistic noise and hard negatives (look-alikes that must stay silent).
- Pin the exact alert counts, figures and refs in an end-to-end test, and test that the CSV and the
  Norma 43 demo give the same alerts. Test that the committed files equal a fresh generator run.
- You cannot run the generator, so the committed demo files do not exist until the human runs it.
  Say so in the task, and write the e2e tests so that they fail loudly until then.

### 7. Showcase integration

Add the page to `PAGES` in `streamlit_app.py`, update the Home text, and update the tests that pin
the page list. Update `.kiro/steering/structure.md` (layout tree), `data/samples/README.md`,
`.gitattributes` for byte-compared demo files, and the README table of apps.

### 8. Finish

You are done when every task is written and every file exists. Then **stop** and report:

- the files you wrote or changed, and any file outside `apps/<name>/` with the reason;
- the exact commands for the human, in order: the generator mode, `ruff format .`,
  `ruff check .`, `ruff format --check .`, `pytest`, and
  `git status --short ledger_kit apps/zombie_subscriptions apps/phantom_invoices` (expected: empty);
- the library decisions and open questions;
- what you could not verify because you cannot run commands.

Do not fill in the Kiro-calls and elapsed-time record; the reviewer does.

## Mistakes to avoid

- Putting a threshold in `config.toml`, or a magic number in a condition.
- An alert whose `source_refs` omits a row that contributed to a figure.
- A template placeholder that is not a key of `Alert.data`, or digits written into a template.
- Using `float` for money, or formatting money by hand instead of `format_amount`.
- Editing a shared test or a steering file beyond the lines the new app needs.
- Real names, IBANs or tax ids. Use the fictional ones of Finance Rule 5.
