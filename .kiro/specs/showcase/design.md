# showcase — Design

## 1 Entry page (REQ-SC-01..03)

`streamlit_app.py` holds `PAGES`, a tuple of `PageSpec(title, icon, url_path, script)`; `script` is
`None` for Home (rendered by `home()` in the same file) or the repository-relative path of an app's
`app.py`. `main()` calls `st.set_page_config(...)`, builds one `st.Page` per spec and runs
`st.navigation(pages).run()`. A test imports the module and reads `PAGES`, because `st.Page`
returns an empty object outside a script run.

Facts checked in Streamlit 1.67.0:

| Question | Answer (source) |
|---|---|
| Two `st.set_page_config` calls (entry, then the page)? | Allowed and additive; the docstring says the command "can be called multiple times in a script run". The entry sets title, icon and layout, the app page overrides the title. Apps keep their own call, so `streamlit run apps/<name>/app.py` still works. |
| Does a file page see `__name__ == "__main__"`? | Yes. `Page.run` execs the code in `types.ModuleType("__main__")` with `__file__` set, so the `if __name__ == "__main__": main()` guard of each app fires. |
| Path bootstrap? | Each app inserts the repository root into `sys.path` if absent. Under the entry script the root is already first on the path, so the insert is a no-op; standalone it does the work. |
| `url_path` of two files both named `app.py`? | Inferred from the file name, so both would be `app` and collide. Every `PageSpec` therefore passes an explicit, unique `url_path`. |
| Page paths | Relative to the entry script's folder, so `streamlit run streamlit_app.py` works from any working directory. |

## 2 Keys (REQ-SC-04, REQ-SC-05)

Only three names were shared by both apps; each gets the app prefix (`zs_`, `pi_`):

| Was | Zombie | Phantom |
|---|---|---|
| `load_demo` (button key) | `zs_load_demo` | `pi_load_demo` |
| `hallucinate` (toggle key) | `zs_hallucinate` | `pi_hallucinate` |
| `explanations` (cache) | `zs_explanations` | `pi_explanations` |

The `load_demo` callback function keeps its name. A test runs both apps, collects the keys of
`st.session_state` and asserts that the two sets are disjoint.

Widget state is dropped when a run does not render the widget, so the text areas, toggle and date
inputs would reset after a visit to the other page. Each app copies its widget values to a plain
key (`zs_kept` / `pi_kept`) right after the sidebar is drawn and puts them back with
`setdefault` before the widgets are built. Loaded demo sources and caches are already plain keys.

## 3 Theme (REQ-SC-06)

`.streamlit/config.toml`:

```toml
[theme]
base = "dark"
primaryColor = "#7cffb2"
backgroundColor = "#12101a"
secondaryBackgroundColor = "#1c1829"
textColor = "#e8dcc0"
```

*(Amended by REQ-SC-13, see §6: the file also holds `[client]` and `[browser]`.)*

All values appear in `flashlight.py` / `app.py` CSS of the phantom app. The zombie app keeps its
own graveyard CSS on top. `.streamlit/secrets.toml` stays git-ignored.

## 4 Wording (REQ-SC-07..09)

- `TEMPLATES` keeps its 11 keys. `SAME_DAY_TEMPLATES` holds the same-date wording of the three
  duplicate variants; `template_for` returns it when `first_issue_date == last_issue_date`.
  Placeholders are fields of `Alert.data`, so the number guard needs no change.
- The two critical IBAN templates drop `{verification_message}`; the data field and the phone box
  (`verification_message(alert)`, `st.warning`) are unchanged.

## 5 Requirements file (REQ-SC-10)

A test walks the AST of every runtime module (`ledger_kit`, `apps` without `tests`,
`streamlit_app.py`), keeps the imports that are neither stdlib nor first-party, maps them to
distributions and asserts each is pinned with `==` in the root `requirements.txt`.

## 6 Publish readiness (REQ-SC-13..15)

**REQ-SC-13, no usage statistics (amends REQ-SC-06).** `.streamlit/config.toml` gets
`[browser]` with `gatherUsageStats = false`. This is a privacy key, not a server setting, so
Community Cloud still manages everything under `[server]`. `tests/test_showcase_theme.py` now
expects the tables `theme`, `client` and `browser`, with `browser == {"gatherUsageStats": False}`;
the check that `[server]` and `[global]` are absent and the secret-word check stay.

**REQ-SC-14, tests on GitHub.** `.github/workflows/tests.yml`: `on: [push, pull_request]`, one job
`pytest` on `ubuntu-latest`, `timeout-minutes: 60`, `actions/checkout@v4`,
`actions/setup-python@v5` (3.12, `cache: pip`), `pip install -r requirements.txt`, `ruff check .`,
`ruff format --check .`, then `python -m pytest --cov=ledger_kit --cov=apps/zombie_subscriptions
--cov=apps/phantom_invoices --cov=apps/vampire_fees --cov-fail-under=80`. No `secrets.*`, no `env` with a key, no deploy. The suite was read for
Windows paths, local paths, API keys and Ollama: the tests fake `openai` and set or clear
variables with `monkeypatch`, so no key is needed; the git-based tests skip when there is no work
tree. The format check and the 80 percent coverage floor are in the workflow because `testing.md`
(CI requirements) demands them. Measured on the laptop: `ruff format --check .` reports 245 files
already formatted, and the coverage command passed in a clean LF clone with 99.00 percent total
coverage in 32 minutes, hence the 60-minute limit.

**REQ-SC-15, keep the demo awake.** `.github/workflows/keep-demo-awake.yml`: `cron: "17 */6 * * *"`
(quoted) plus `workflow_dispatch`; job-level `env: DEMO_URL: ""`, which the owner fills in once
the app is public. Step 1 prints `No public URL yet` and exits 0 when it is empty; every later
step has `if: env.DEMO_URL != ''`. Those steps set up Python 3.12, install `playwright==1.48.0`
and Chromium, and run a short inline script: open the URL (120 s timeout), wait 5 s, click the
button named `Yes, get this app back up!` if visible, wait 90 s so the visit counts, print the
title, close. `timeout-minutes: 10`, no secret.

**Tests.** `tests/test_publish_ready.py` reads the three files as text (no YAML library, nothing is
run).
