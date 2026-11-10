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
gradient behind the content.
- Example: the CSS has no `animation`, `@keyframes` or `transition` property.

### Constraints

**REQ-HD-14** The system shall add no dependency, make no network request and leave detectors,
figures, `source_refs`, widget keys, alert texts, the explainer and the number guard unchanged.
- Example: `requirements.txt` and `pyproject.toml` are unchanged; the full test suite passes with
  only the title, emoji and palette assertions updated (listed in design.md).

**REQ-HD-15** Every page of the showcase (Home, the three apps with and without demo data,
Benchmark) shall render without an exception, and each page injects exactly one `<style>` block.
- Example: `AppTest` runs of the five pages end with `not at.exception`.
