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
