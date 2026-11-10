# Design: haunted-design

## Modules (all in `ledger_kit/ui/`, none imports an app)

| File | Role |
|---|---|
| `icons.py` | Six inline SVG line icons, `icon()`, `standalone_svg()`, `mask_uri()`, `favicon_uri()`. Pure. |
| `theme.py` | Palette, `Accent` per app, the one CSS block (`theme_css`), `apply_theme`, `set_page`, `page_header`, `section_heading`, `card_html`, `severity_marker`, `card_key`. |
| `landing.py` | Pure builders of the Home page: `proof_facts` (reads the committed files), tiles, diagram, HTML of the strip. No Streamlit. |

`streamlit_app.py` uses all three for Home and Benchmark. Each `app.py` uses `theme` only.

## One CSS block per page

`theme_css(accent, app_css)` returns a single `<style>` string in this order: the accent variables
(`--gl-accent`, `--gl-accent-text`, `--gl-accent-rgb`, `--gl-wash`, `--gl-glow`, set on `.stApp`),
the app's own rules (`ZOMBIE_CSS`, `VAMPIRE_CSS`, `HAUNTED_CSS` + `APP_CSS`), the base rules, then
the menu icons. The base comes after the app rules on purpose: the older app rules (the phantom
`.stApp` background, the coffin clip-path, the amber headings) have the same weight as the base
and must lose. The card box is `.stApp .zs-tombstone, .stApp .vf-coffin, .stApp .gl-card`
(specificity 0,2,0), so it wins over any app rule whatever the order. App CSS keeps only the
markup it owns.

Existing tests count `<style>` blocks per page (exactly one). The masthead, headings and cards
are separate markdown elements that start with `<div`, which also keeps them out of the
"explanation" lists some tests build from markdown that does not start with `<span`, `<div` or
`<style`.

## Decisions

- **DN-HD-01 Page icon above the title, title stays `st.title`.** `st.title` stays plain text, so
  the heading is a real `h1` and `at.title[0].value` is the bare name. The icon sits in a masthead
  line (`page_header`) above it with a one-line kicker.
- **DN-HD-02 Section headings are `<div role="heading" aria-level="2">`** with an icon and the
  accent rule; they replace `st.subheader("🪦 ...")`. The Benchmark page keeps `st.subheader`
  (a test pins `at.subheader`).
- **DN-HD-03 Navigation icons by CSS mask.** `st.Page(icon=...)` accepts only an emoji or a
  Material icon, so `PageSpec.icon` holds an icon *name* and the menu icon is a `::before` with
  `mask: url(data:image/svg+xml;base64,...)` and `background-color: currentColor`. Selectors use
  `href` suffixes of the explicit `url_path`s. If a Streamlit upgrade renames the test ids the
  menu simply shows no icon.
- **DN-HD-04 Favicon.** `set_page` passes a base64 SVG data URI in the accent colour. Streamlit
  falls back to the raw string when it cannot make a URL, so this cannot raise.
- **DN-HD-05 Critical glow without `:has()` on the page root.** Alert containers get
  `st.container(border=True, key="<app>_card_<severity>_<alert.id>")`; the CSS targets
  `[class*="_card_critical_"]`. A container key is not a widget key and is not in session state.
  The title keeps the exact `<div class="…-alert-title">` start the tests look for.
- **DN-HD-06 Severity badge = icon + word.** critical: candle, warning: magnifier, info: scales.
  The word keeps the badge readable without colour. `SEVERITY_BADGES` stays in `reference_app.py`
  (the library page and its test pin the emojis); `SEVERITY_ICONS` stays in the phantom
  `settings.py` (it feeds the flashlight radio labels).
- **DN-HD-07 Metrics stay `st.metric`** (tests read `at.metric`); only the labels lose their
  emoji, keeping the severity word last, and CSS draws them as cards.
- **DN-HD-08 Proof-strip arithmetic.** Precision and recall are copied from `totals` in
  `results.json`, never recomputed. The XSD fact cannot be machine-read (the check was done once
  by the reviewer, DN-RF-23), so the page prints the count of files in the folder against the 25
  checked and says so.
- **DN-HD-09 Home demo numbers** are constants in `landing.py`; a test runs the three apps on
  their demo data and compares.
- **DN-HD-10 Columns wrap.** Instead of changing `TOMBSTONES_PER_ROW` / `COFFINS_PER_ROW`
  (pinned), CSS lets `stHorizontalBlock` wrap with a 15rem column minimum below 1100 px.

## Tests that had to change (the only ones)

| Test | Why |
|---|---|
| `test_showcase_app` titles, Home word limit and text helper | Titles lose their emoji; Home is richer (word budget 450, HTML tags and the style block are not text). |
| `test_benchmark_page` titles and Benchmark icon | Same. |
| `test_zs_app` title and graveyard theme | Title; the pinned `#1a1a2e` background contradicts the shared night background. |
| `test_pi_app_logic`, `test_vf_app_logic` titles; coffin card emoji | Titles; `🧛 BANCO FICTICIO` becomes the icon and the name. |
| `test_showcase_theme` | The palette now also lives in `ledger_kit/ui/theme.py`, so that file joins the sources the theme colours are looked up in. |

## Not verified without a browser

Raw inline `<svg>` inside `st.markdown`, the sidebar link selectors, the container-key class
position and the favicon are checked by the user in the browser at 1400 and 800 px.
