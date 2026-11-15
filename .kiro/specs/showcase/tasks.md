# showcase — Implementation Tasks

Every task is test-first. Section references (§) point to `design.md`, REQ ids to
`requirements.md`. Verification (`ruff check .`, `ruff format --check .`, `pytest`, a headless run
of `streamlit_app.py`) is run by the user.

## Task SC1 — Wording polish

**Covers**: REQ-SC-07, REQ-SC-08, REQ-SC-09, §4

- [x] Update the tests that pin the old wording (`test_pi_explain_support.py`) and add: same-date
  duplicate reads *issued on*, different dates still read *between*, the two IBAN templates do not
  contain the verification message, the guard accepts the new texts; the demo AppTest shows the
  phone message once per critical IBAN card and no *between D and D*.
- [x] Implement `SAME_DAY_TEMPLATES`, the `template_for` switch and the template edit in
  `apps/phantom_invoices/explain_support.py`.
- [x] Amend REQ-PI-26 and the template section of the phantom-invoices spec.

## Task SC2 — Collision-free keys and state that survives navigation

**Covers**: REQ-SC-04, REQ-SC-05, §2

- [x] Update the app tests to the new key names (`test_zs_app.py`, `test_pi_app_logic.py`).
- [x] Rename the three shared keys in both apps and in the phantom `apply_demo`; add
  `_restore_widgets` / `_keep_widgets` to both apps.

## Task SC3 — Theme

**Covers**: REQ-SC-06, §3

- [x] `tests/test_showcase_theme.py`: the file parses, holds only `theme`, only known theme keys,
  hex colours taken from the app CSS, base `dark`, no secret-like word, no `secrets.toml`.
- [x] Create `.streamlit/config.toml`.

## Task SC4 — Entry page

**Covers**: REQ-SC-01, REQ-SC-02, REQ-SC-03, §1

- [x] `tests/test_showcase_app.py` (`AppTest`, `default_timeout=60`, registry snapshot/restore):
  starts without exception, `PAGES` has the three pages, Home text, each app page loads its demo
  and shows alerts, the hallucination toggle works, state survives navigation, key sets are
  disjoint.
- [x] Create `streamlit_app.py`.

## Task SC5 — Community Cloud readiness

**Covers**: REQ-SC-10, REQ-SC-11, §5

- [x] `tests/test_showcase_requirements.py`: every runtime import is pinned in the root file, every
  line is pinned with `==`, no app has its own `requirements.txt`, the entry page imports no app,
  the apps import each other nowhere and no private `ledger_kit` name.
- [x] Document the root `requirements.txt` sections; add the new files to the layout of
  `.kiro/steering/structure.md`.

## Task SC6 — Publish readiness (13 Nov 2026)

**Covers**: REQ-SC-13, REQ-SC-14, REQ-SC-15, §6

- [x] `tests/test_publish_ready.py` (text checks only): `gatherUsageStats = false`; `tests.yml` runs
  on push and pull_request, Python 3.12, installs `requirements.txt`, runs `ruff check .` and
  pytest; neither workflow mentions secrets; `keep-demo-awake.yml` has the schedule,
  `workflow_dispatch`, an empty `DEMO_URL`, the skip message, `playwright==1.48.0` and the button
  name.
- [x] Update `tests/test_showcase_theme.py` (REQ-SC-06 as amended): exactly one `[browser]` key,
  value false; `[server]`, `[global]` and secrets still forbidden.
- [x] Add `[browser]` and the new header comment to `.streamlit/config.toml`.
- [x] Create `.github/workflows/tests.yml` and `.github/workflows/keep-demo-awake.yml`.
- [x] Add `.github/` to the layout of `README.md` and `.kiro/steering/structure.md`.

Runs recorded for SC6 (session 24b):

- After session 24, the user's run: ruff clean, 3,935 passed, 1 skipped, 1 failed
  (`tests/test_judge_path_misc.py::test_the_client_table_hides_the_toolbar_for_visitors`, the
  config comment lacked the word *neither*); fixed in 24b by rewording the comment.
- Clean clone with LF line endings: 3,927 passed, 1 skipped, `ruff check .` clean;
  `ruff format --check .` reported 245 files already formatted.
- Coverage run (the command of `testing.md` line 139, `--cov-fail-under=80`): passed, total
  coverage 99.00 percent, 32 minutes; hence `timeout-minutes: 60` in `tests.yml`.
- Browser check with the new config: Home and Vampire Fees made no request outside localhost;
  before the change the browser sent three requests to `webhooks.fivetran.com`.
- The workflows themselves have not run on GitHub yet.
- Session 25b: Hypothesis deadline off for shared runners (profile `ghost-ledger`, `deadline=None`, in the root `conftest.py`; `tests/test_hypothesis_profile.py`; note in `testing.md`).
- `tests.yml` now also runs `ruff format --check .` and the coverage command (REQ-SC-14,
  `tests/test_publish_ready.py` updated).

## Not verified by the author

The tasks were written without running a command. The user runs `ruff check .`,
`ruff format --check .`, `pytest` and a headless start of `streamlit_app.py` and reports failures.
