# showcase — Requirements

## Overview

`showcase` is the page the judges open. It puts the two finished apps (zombie-subscriptions and
phantom-invoices) behind one Streamlit Community Cloud entry point, gives them one dark Halloween
theme and removes two wording defects found in the browser review. It adds no detector, changes no
threshold and publishes nothing.

Ids are `REQ-SC-nn`. EARS keywords: *shall*, *when*, *while*, *where*, *if ... then*.

---

## 1 — Entry page

- **REQ-SC-01** The repository shall contain `streamlit_app.py` at its root, the default entry
  point of Streamlit Community Cloud. It shall build its menu with `st.navigation` and expose
  exactly four pages, in this order: **Home**, **Zombie Subscriptions**, **Phantom Invoices**,
  **Benchmark**. *(Amended by REQ-BM-20: the Benchmark page was added after the first three; it
  only shows the committed benchmark results.)*
- **REQ-SC-02** When the user opens the Home page, the system shall explain in a few lines that
  (a) deterministic detectors find the figures, (b) every alert cites its source rows, (c) the LLM
  only words the explanation and the number guard rejects any invented number, showing the
  *Simulate a hallucinating LLM* idea, (d) the two apps exist, and (e) all data is synthetic.
- **REQ-SC-03** When the user opens an app page, the system shall run that app's own `app.py`
  unchanged in behaviour, and each app shall still work alone with
  `streamlit run apps/<name>/app.py`. The showcase shall not import either app. *(Amended in
session 26b: `streamlit_app.py` imports exactly one app-side module, `apps.home_tiles`, and no
other app module, no detector and no benchmark runner. Reason: the drawings of the Home tiles
come from each app's own demo pipeline, so they show only cited rows and no figure of their own.)*
- **REQ-SC-04** The two apps shall share no widget key and no `st.session_state` key.
- **REQ-SC-05** When the user leaves an app page and comes back, the app shall still show the
  demo data and the sidebar values it had (Streamlit drops the state of widgets that a run does
  not render).

## 2 — Theme

- **REQ-SC-06** The repository shall contain `.streamlit/config.toml` with a single `[theme]`
  table: base `dark`, and background, secondary background, text and primary colours taken from
  the existing app CSS (`#12101a`, `#7cffb2`). It shall hold no secret and no `[server]`,
  `[browser]`, `[global]` or other non-theme setting. *(Amended by REQ-SC-13: one `[browser]` key,
  `gatherUsageStats = false`, is now allowed; `[server]`, `[global]` and secrets stay forbidden.
  The one `[client]` key of REQ-JP-13 is also allowed.)*

## 3 — Wording polish (phantom-invoices)

- **REQ-SC-07** When the invoices of a duplicate-invoice alert share one issue date
  (`first_issue_date == last_issue_date`), the fallback explanation shall say *issued on
  &lt;date&gt;* and shall not say *issued between D and D* or *0 days apart*.
- **REQ-SC-08** The verify-by-phone message (`VERIFY_BY_PHONE_MESSAGE`, REQ-PI-26) shall appear
  exactly once in each of the two critical IBAN cards: verbatim in the phone box. The fallback
  templates of those two variants shall not repeat it. *This amends REQ-PI-26, which listed the
  message as part of the fallback template.*
- **REQ-SC-09** The number guard shall accept the changed fallback texts: each filled template
  still restates only values of `Alert.data` and the cited rows.

## 4 — Community Cloud readiness

- **REQ-SC-10** The root `requirements.txt` shall pin (`==`) every third-party package that
  `ledger_kit`, the apps or `streamlit_app.py` import at run time. No app shall have a
  `requirements.txt` of its own. Dev tools may stay in the root file.
- **REQ-SC-11** Apps shall never import each other or a private (`_name`) `ledger_kit` name.
  Fixtures and demo files shall stay synthetic.
- **REQ-SC-12** Nothing shall be published, pushed or deployed by this work, and the README is
  out of scope (session 7).

## 5 — Publish readiness (13 Nov 2026)

Prepares the repository for the day the owner publishes it. Nothing is pushed or published by
this work; the owner does that.

- **REQ-SC-13** *(amends REQ-SC-06)* The file `.streamlit/config.toml` shall contain a `[browser]`
  table with exactly one key, `gatherUsageStats = false`, so that a running showcase sends no
  Streamlit usage statistics to a third party (checked on 13 Nov 2026: the browser called
  `webhooks.fivetran.com`, while the README says the apps never call the network). The file shall
  still hold no secret, no `[server]` and no `[global]` table. Its header comment shall describe
  the file as it is: theme keys, one client display key and one browser privacy key.
- **REQ-SC-14** The repository shall contain `.github/workflows/tests.yml`, a workflow named
  `tests` that runs on `push` and `pull_request` in one job on `ubuntu-latest` (60-minute limit)
  with Python 3.12, installs `requirements.txt`, then runs `ruff check .`, `ruff format --check .`
  and `python -m pytest --cov=ledger_kit --cov=apps/zombie_subscriptions
  --cov=apps/phantom_invoices --cov=apps/vampire_fees --cov-fail-under=80` (the command of
  `testing.md`, CI requirements). It shall use no secret, no deploy step and no network call beyond installing the pinned
  packages. The tests shall pass, or skip, on a clean Linux runner without an API key.
- **REQ-SC-15** The repository shall contain `.github/workflows/keep-demo-awake.yml`, which on a
  schedule (`17 */6 * * *`) and on `workflow_dispatch` visits the public demo so that a free
  Streamlit app does not sleep before a judge arrives. While the job-level `DEMO_URL` is empty
  the job shall print `No public URL yet` and end successfully without installing anything. When
  the owner sets `DEMO_URL`, it shall open the page with a headless browser, press the button
  *Yes, get this app back up!* if it is shown, stay on the page so the visit counts and close.
  It shall use no secret and run at most 10 minutes.
