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

## Not verified by the author

The tasks were written without running a command. The user runs `ruff check .`,
`ruff format --check .`, `pytest` and a headless start of `streamlit_app.py` and reports failures.
