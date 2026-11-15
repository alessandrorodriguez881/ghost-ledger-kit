# Requirements: haunted-design (session 15a)

## Why

An adversarial jury gave the showcase Design 4 of 10: "default Streamlit with emojis". Past
winners won on polish. This spec is a design pass only: the look changes, the behaviour does not.

## Scope

In: one shared CSS and icon layer in `ledger_kit/ui/`, used by the three apps, the Benchmark page
and the Home page; a real landing page.

Out: detectors, figures, `source_refs`, widget keys, alert texts, the explainer and the number
guard, `.streamlit/config.toml` (the shared theme stays), any new dependency, any network request.

## Glossary

- **Accent**: the one colour of an app. Kit (Home, Benchmark) `#7cffb2`; Zombie Subscriptions moss
  green `#8fae6b`; Phantom Invoices spectral teal `#5fd0c8`; Vampire Fees blood red `#c2334d`
  (strokes, rules, glow) with the lighter `#e8647c` for accent *text*.
- **Card**: the one box style of the showcase: thin bone border, small-caps label, large figure,
  the cited rows under it, a soft accent glow only when critical.
- **Proof strip**: the four facts at the top of Home, each read from a committed file.

## Requirements (EARS)

### Palette and typography

**REQ-HD-01** The system shall keep the night background `#12101a` and the bone text `#e8dcc0` on
every page and shall not edit `.streamlit/config.toml`.
- Example: the CSS block of each page contains `#12101a` and `#e8dcc0`; the theme file is unchanged.

**REQ-HD-02** Where a page belongs to an app, the system shall use that app's accent, and only
that one, for the page icon, the rule under the headings and the glow of critical cards.
- Example: the Zombie page CSS defines `--gl-accent: #8fae6b` and not `#5fd0c8` or `#c2334d`.
- Example: Home and Benchmark use the kit accent `#7cffb2`.

**REQ-HD-03** The system shall set titles and headings in the stack `Georgia, "Times New Roman",
serif` with letter spacing, and leave body text in the default sans face, without loading any
external font.
- Example: the CSS contains the stack and no `@import`, `@font-face` or `url(http`.

**REQ-HD-04** The system shall give every text at least 4.5 to 1 contrast against the night
background and against the card background `#1c1829`, and the accent text colours shall meet it.
- Example: bone 13.9:1, muted bone `#b9ae95` at least 7:1, each accent text colour at least 4.5:1.

### Icons

**REQ-HD-05** The system shall draw the icons tombstone, ghost, coffin, candle, magnifier and
scales as inline SVG line icons in one module, monochrome, stroked with `currentColor`, each with a
non-empty `<title>` element.
- Example: `ledger_kit.ui.icons.icon("ghost")` parses as XML, its root is `svg`, its stroke is
  `currentColor`, and it has no fill colour, no script, no image and no link.

**REQ-HD-06** The system shall not use an emoji in a page title, a section heading or the
navigation menu. Emojis may remain only where an existing test pins them: the library reference
page, the ledger status cells of Phantom Invoices, the guard badge and the Provoke-the-LLM panel
title, and the flashlight radio labels. Alert severity badges use the icon set.
- Example: `st.title` of every page is plain text; `PAGES[i].icon` is an icon name, not an emoji.

**REQ-HD-07** Where the navigation menu shows a page, the system shall show its icon through a CSS
mask of the same SVG, coloured by the link text.
- Example: the CSS of each page holds one `mask` rule per page of the menu and no emoji.

### Cards

**REQ-HD-08** The system shall draw tombstones, coffins, proof-strip facts, app tiles, metrics and
alert cards in the one card style, and shall add a glow only to critical alert cards.
- Example: `card_html(..., critical=False)` has no `gl-critical`; the critical alert container key
  contains `_card_critical_` and the others do not.

### Home page

**REQ-HD-09** The Home page shall show: the promise in one line; a proof strip with four facts;
three app tiles, each with its icon, a one-line purpose and its demo numbers; and a small inline
SVG diagram of the three layers (ingestion, deterministic detectors, explainer with the number
guard).
- Example: Home contains four `gl-card` facts, three `gl-tile` tiles and one `gl-diagram`.

**REQ-HD-10** The four facts of the proof strip shall be read from committed files at run time:
the precision and recall of Zombie Subscriptions and of Phantom Invoices from the `totals` of
`data/benchmark/results.json`; the Facturae samples checked against the official XSD; the INE CPI
snapshot as public data. The number of tests shall not be shown.
- Example: Zombie precision on Home equals `apps.zombie.totals.precision` of the file.
- Example: the XSD fact says the check was done once by the reviewer and is not part of CI
  (DN-RF-23), and shows `25 of 25` while the folder holds 25 files.

**REQ-HD-11** If a source file of the proof strip is missing or malformed, then the system shall
show `n/a` for that fact and the rest of the page shall render.

### Behaviour of the layout

**REQ-HD-12** The system shall render every page legibly at 1400 and at 800 pixels wide: cards in
grids that wrap, Streamlit columns that wrap below 1100 pixels, no horizontal page scroll.
- Example: the CSS has a `max-width: 1100px` rule that wraps `stHorizontalBlock` and a
  `max-width: 800px` rule for the headings and the grids.

**REQ-HD-13** The system shall use no animation. The only decoration is a static, very faint fog
gradient behind the content. (Amended in session 26: the moment of Home, REQ-HD-18, is the one
exception, carried by the style block of Home only.)
- Example: the CSS has no `animation`, `@keyframes` or `transition` property.

### Constraints

**REQ-HD-14** The system shall add no dependency, make no network request and leave detectors,
figures, `source_refs`, widget keys, alert texts, the explainer and the number guard unchanged.
- Example: `requirements.txt` and `pyproject.toml` are unchanged; the full test suite passes with
  only the title, emoji and palette assertions updated (listed in design.md).

**REQ-HD-15** Every page of the showcase (Home, the three apps with and without demo data,
Benchmark) shall render without an exception, and each page injects exactly one `<style>` block.
- Example: `AppTest` runs of the five pages end with `not at.exception`.

---

# Session 26: Home with one clear moment (15 Nov)

## Why

The owner chose this on 15 Nov from the three improvements that a fresh jury proposed on 14 Nov
(the jury: Design 5 of 10, too much text, the three apps look alike, a judge should get the point
in three seconds without reading). It is a Home-page change only: the order of the page, one
animated moment, less text above the fold and one drawing per app tile.

## Scope

In: `streamlit_app.py` (`home`), `ledger_kit/ui/landing.py` and `theme.py`, one new module
`apps/home_tiles.py` (the bridge to the demo data of the apps), the tests that pin the Home layout,
`README.md` (the For judges step 1 and one Decisions row).

Out: the three apps, the detectors, the explainer and the number guard, `replay.py`, the committed
run files, `signatures.py`, every dependency, every network request.

## Requirements (EARS)

**REQ-HD-16** The Home page shall show, in this order: the title, the one-line promise, the
moment, the proof strip, the three app tiles, and one closed expander named `How it works`.
- Example: in `AppTest`, the index of the title is lower than the promise, the moment, the proof
  strip, the tiles and the expander, in that order.

**REQ-HD-17** The moment shall show the recorded real answer that `replay.home_example()` returns
(record P3 of `data/live_runs/2026-11-10_llama3.2-3b.json`) as the model wrote it, with each
invented figure (`HOME_EXAMPLE_MARKS`) highlighted; then a stamp `Rejected by the number guard`
that names the struck figures; then the fixed template the guard showed instead; and the honest
note that the answer is recorded and no model is called.
- Example: the markup holds two `gl-strike` marks, one `gl-stamp` with `5%` and `617.51`, and one
  `gl-moment-template`; the label says `No model is called`.

**REQ-HD-18** The system shall play the moment with CSS only: about one second after the page
loads each invented figure is struck through, then the stamp appears, then the template; all of it
ends within three seconds and plays once. Where the visitor prefers reduced motion
(`prefers-reduced-motion: reduce`), the system shall show the final state at once. The system
shall use no JavaScript, no component and no new package. This is the one animation of the
showcase and it is carried by the CSS of Home only: REQ-HD-13 holds for every other page.
- Example: the largest `delay + duration` of the moment rules is at most 3 s; the first delay is
  about 1 s; every animation has the iteration count 1; the reduced-motion rule sets
  `animation: none`.

**REQ-HD-19** The moment shall write no figure of its own. Every figure on screen comes from the
recording or from the alert. The verdict is today's number guard run on the recorded text and the
alert that the record names (a Phantom Invoices demo alert), through the same call as a card
replay. If the file is missing or malformed, the alert is not found, the guard no longer rejects
the answer, or a mark is not in the answer, then the system shall draw no moment and the rest of
Home shall render.
- Example: every number in the visible text of the moment is in the raw answer or in the filled
  template; with no run file Home has no `gl-moment` and still has the proof strip and tiles.

**REQ-HD-20** The system shall move the three-line story, the Start here link, the diagram with
its heading, the layers text, the try-it box, the synthetic note and the INE note into the
expander `How it works`, below the tiles, in that order and with the same words. Nothing is
deleted. The proof strip stays right under the moment.
- Example: the expander holds `STORY`, `START_HERE`, `LAYERS`, `TRY_IT`, `SYNTHETIC_NOTE` and
  `INE_NOTE` unchanged; the INE attribution still appears once on the page.

**REQ-HD-21** Each app tile shall show the signature drawing of its own app (the pulse for Zombie
Subscriptions, the lantern for Phantom Invoices, the bites for Vampire Fees), drawn by the same
`signatures.py` functions and from the same cited rows as the alert cards, for one real alert of
that app's demo data. The alert is the first alert in the order the page lists them: the first
critical alert, else the first warning, else the first info. The tile also shows that alert's
`source_refs` as chips. The tile keeps its title, colour, one line and demo numbers.
- Example: the Zombie tile holds `gl-heartbeat`, the Vampire tile `gl-bites`, the Phantom tile
  `gl-lantern`; each tile's drawing equals the drawing the app page makes for the same alert.

**REQ-HD-22** The system shall build the three tile drawings once per process (`st.cache_data`)
and Home shall render within the timeout of the existing Home tests (60 s). A failure of one
drawing shall leave that tile without a drawing and shall not stop Home.
- Example: after `tile_signatures.clear()`, two runs of Home call `run_pipeline` of Zombie
  Subscriptions once.

**REQ-HD-23** `apps/home_tiles.py` shall be the only module outside the three app folders that
imports an app. `streamlit_app.py` shall import no app module except `apps.home_tiles`, and
`ledger_kit` shall import no app.
- Example: `test_the_entry_page_imports_no_app_but_the_bridge` and
  `test_ledger_kit_imports_no_app_after_this_change`.
