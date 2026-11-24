"""The haunted-ledger look shared by the three apps, the Benchmark page and Home (haunted-design).

One module owns the palette, the accent of each app, the single ``<style>`` block every page
injects, and the small HTML helpers (masthead, section heading, card, severity badge). Nothing
here loads a font, an image or a script from the network, and nothing animates, with one
exception: the moment of Home (``MOMENT_CSS``, only in the style block of the kit accent).

The helpers that build markup (``masthead_html``, ``card_html`` ...) are pure strings; the few
that call Streamlit are ``apply_theme``, ``set_page``, ``show_masthead``, ``show_section`` and
``show_severity``. App code keeps its own markup (tombstone, coffin, badge classes) and only asks
this module for the colours and the box style.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

import streamlit as st

from ledger_kit.ui.icons import favicon_uri, icon, mask_uri

# --- palette ------------------------------------------------------------------------------------

NIGHT: str = "#12101a"  # page background (shared with .streamlit/config.toml)
BONE: str = "#e8dcc0"  # body text (shared with .streamlit/config.toml)
MUTED: str = "#b9ae95"  # captions and labels, 7:1 or better on NIGHT and PANEL
PANEL: str = "#1c1829"  # card and input background (shared with .streamlit/config.toml)
SIDEBAR: str = "#0d0b14"
LINE: str = "rgba(232, 220, 192, 0.30)"  # the thin bone border of a card
DISPLAY_FONT: str = 'Georgia, "Times New Roman", serif'


@dataclass(frozen=True)
class Accent:
    """The one colour of a page, with the icon and the kicker line of its masthead."""

    key: str
    title: str
    color: str  # icon strokes, heading rule, glow, mask of the menu icon
    text_color: str  # accent as text: at least 4.5 to 1 on NIGHT and on PANEL
    rgb: str  # "r, g, b" of `color`, for translucent fills
    icon: str  # name in ledger_kit.ui.icons
    kicker: str


KIT = Accent(
    key="kit",
    title="Ghost Ledger Kit",
    color="#7cffb2",
    text_color="#7cffb2",
    rgb="124, 255, 178",
    icon="candle",
    kicker="Every figure has a source row",
)
ZOMBIE = Accent(
    key="zombie",
    title="Zombie Subscriptions",
    color="#8fae6b",
    text_color="#8fae6b",
    rgb="143, 174, 107",
    icon="tombstone",
    kicker="Forgotten charges, buried one by one",
)
PHANTOM = Accent(
    key="phantom",
    title="Phantom Invoices",
    color="#5fd0c8",
    text_color="#5fd0c8",
    rgb="95, 208, 200",
    icon="ghost",
    kicker="Invoices that should not be there",
)
VAMPIRE = Accent(
    key="vampire",
    title="Vampire Fees",
    color="#c2334d",
    text_color="#e8647c",
    rgb="194, 51, 77",
    icon="coffin",
    kicker="The fees that drain an account",
)
BENCHMARK = Accent(
    key="benchmark",
    title="Benchmark",
    color="#7cffb2",
    text_color="#7cffb2",
    rgb="124, 255, 178",
    icon="scales",
    kicker="What the detectors found, and what they missed",
)

ACCENTS: tuple[Accent, ...] = (KIT, ZOMBIE, PHANTOM, VAMPIRE)
# The Home tiles each wear the accent of their app; only Home and Benchmark carry these rules.
TILE_ACCENTS: tuple[Accent, ...] = (ZOMBIE, PHANTOM, VAMPIRE)

SEVERITY_ICON: dict[str, str] = {"critical": "candle", "warning": "magnifier", "info": "scales"}

# Menu entries: (CSS attribute test on the link href, icon name). The url_paths are explicit in
# streamlit_app.py, so a suffix or a fragment is enough; Home is the only href that ends in "/".
NAV_ICONS: tuple[tuple[str, str], ...] = (
    ('[href$="/"]', "candle"),
    ('[href*="zombie-subscriptions"]', "tombstone"),
    ('[href*="phantom-invoices"]', "ghost"),
    ('[href*="vampire-fees"]', "coffin"),
    ('[href*="benchmark"]', "scales"),
)

_SAFE_CLASS = re.compile(r"^[a-z0-9 _-]*$")

# --- the CSS ------------------------------------------------------------------------------------
# Every line is at most 100 characters (ruff E501 applies to the strings of this file too). The
# colours that depend on the accent come from the variables of `_accent_vars`; the rest is the
# shared night palette.

BASE_CSS: str = """
.stApp {
  background-color: #12101a;
  background-image:
    radial-gradient(ellipse 70% 38% at 12% 0%,
      rgba(var(--gl-accent-rgb), 0.10), transparent 70%),
    radial-gradient(ellipse 60% 30% at 90% 100%,
      rgba(var(--gl-accent-rgb), 0.06), transparent 70%);
  background-attachment: fixed;
  color: #e8dcc0;
}
[data-testid="stSidebar"] {
  background-color: #0d0b14;
  border-right: 1px solid var(--gl-line);
}
.stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp p, .stApp li, .stApp label,
.stApp [data-testid="stMarkdownContainer"],
.stApp [data-testid="stMetricLabel"],
.stApp [data-testid="stMetricValue"],
.stApp [data-testid="stExpander"] summary {
  color: #e8dcc0;
}
.stApp [data-testid="stCaptionContainer"],
.stApp [data-testid="stCaptionContainer"] p,
.stApp .gl-note {
  color: #b9ae95;
  opacity: 1;
}
.stApp textarea, .stApp input { background-color: #1c1829; color: #e8dcc0; }
.stApp textarea:disabled { -webkit-text-fill-color: #e8dcc0; opacity: 1; }
.stApp code { color: var(--gl-accent-text); overflow-wrap: anywhere; }
.stApp h1, .stApp h2, .stApp h3, .stApp .gl-section, .stApp .gl-sub, .stApp .gl-figure,
.stApp .gl-tile-name, .stApp .gl-promise {
  font-family: Georgia, "Times New Roman", serif;
  letter-spacing: 0.05em;
}
.stApp h1 {
  color: var(--gl-accent-text);
  font-size: 2.4rem;
  border-bottom: 1px solid var(--gl-accent);
  padding-bottom: 0.35rem;
  margin-bottom: 0.6rem;
}
.stApp h2, .stApp h3 { color: #e8dcc0; }
.stApp .gl-mast { display: flex; align-items: center; gap: 0.8rem; margin: 0.4rem 0 0.2rem; }
.stApp .gl-mast-icon { color: var(--gl-accent); display: inline-flex; }
.stApp .gl-kicker {
  font-variant-caps: all-small-caps;
  letter-spacing: 0.14em;
  font-size: 0.95rem;
  color: #b9ae95;
}
.stApp .gl-section {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  font-size: 1.55rem;
  color: #e8dcc0;
  border-bottom: 1px solid var(--gl-accent);
  padding-bottom: 0.3rem;
  margin: 2rem 0 1rem;
}
.stApp .gl-section svg { color: var(--gl-accent); flex: none; }
.stApp .gl-sub { display: flex; align-items: center; margin: 1.4rem 0 0.6rem; }
.stApp .gl-sev {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  font-variant-caps: all-small-caps;
  letter-spacing: 0.12em;
  font-size: 0.9rem;
  color: #b9ae95;
  margin-right: 0.7rem;
}
.stApp .gl-sev-critical { color: var(--gl-accent-text); }
.stApp .gl-sev svg { flex: none; }
.stApp [class$="-alert-title"] {
  font-size: 1.05rem;
  font-weight: 700;
  color: #e8dcc0;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
}
.stApp .gl-card, .stApp .zs-tombstone, .stApp .vf-coffin {
  background: var(--gl-wash), #1c1829;
  border: 1px solid var(--gl-line);
  border-radius: 6px;
  box-shadow: none;
  clip-path: none;
  color: #e8dcc0;
  margin-bottom: 0.5rem;
  padding: 1rem 1.1rem;
  text-align: left;
}
.stApp .gl-card.gl-critical { box-shadow: var(--gl-glow); }
.stApp .gl-label, .stApp .zs-rip, .stApp .vf-title {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-variant-caps: all-small-caps;
  letter-spacing: 0.14em;
  font-size: 0.9rem;
  font-weight: 400;
  color: #b9ae95;
  overflow-wrap: anywhere;
}
.stApp .zs-rip, .stApp .vf-title { color: var(--gl-accent-text); }
.stApp .gl-figure { font-size: 2.1rem; line-height: 1.2; color: #e8dcc0; margin: 0.25rem 0; }
.stApp .gl-note { font-size: 0.9rem; }
.stApp .gl-ref {
  display: block;
  margin-top: 0.6rem;
  font-family: ui-monospace, Consolas, monospace;
  font-size: 0.8rem;
  color: var(--gl-accent-text);
  text-decoration: underline;
  text-underline-offset: 3px;
  overflow-wrap: anywhere;
}
.stApp .gl-ref-chip {
  display: inline-block;
  font-family: ui-monospace, Consolas, monospace;
  font-size: 0.8rem;
  color: var(--gl-accent-text);
  background: rgba(var(--gl-accent-rgb), 0.12);
  border: 1px solid rgba(var(--gl-accent-rgb), 0.55);
  border-radius: 999px;
  padding: 0.05rem 0.65rem;
  margin: 0.15rem 0.25rem 0.15rem 0;
  overflow-wrap: anywhere;
}
.stApp .gl-signature {
  background: rgba(var(--gl-accent-rgb), 0.05);
  border: 1px dashed var(--gl-line);
  border-radius: 6px;
  margin: 0.5rem 0 0.4rem;
  max-width: 100%;
  overflow-x: auto;
  padding: 0.5rem 0.7rem 0.4rem;
}
.stApp .gl-signature svg.gl-sig-svg {
  display: block;
  height: auto;
  min-width: 30rem;
  width: 100%;
}
.stApp .gl-signature-caption { font-size: 0.8rem; color: #b9ae95; margin-top: 0.3rem; }
.stApp .gl-sig-line { fill: none; stroke: var(--gl-accent); stroke-width: 1.5; opacity: 0.85; }
.stApp .gl-dot { fill: var(--gl-accent); stroke: #12101a; stroke-width: 1; }
.stApp .gl-dot-after {
  fill: #e8dcc0;
  stroke: var(--gl-accent-text);
  stroke-width: 2;
  filter: drop-shadow(0 0 4px var(--gl-accent));
}
.stApp .gl-tomb { fill: #1c1829; stroke: #e8dcc0; stroke-width: 1.4; stroke-linejoin: round; }
.stApp .gl-fang {
  fill: var(--gl-accent);
  stroke: var(--gl-accent-text);
  stroke-width: 1;
  stroke-linejoin: round;
}
.stApp .gl-sig-text {
  fill: #b9ae95;
  font-family: Georgia, "Times New Roman", serif;
  font-size: 11px;
}
.stApp .gl-lantern-wrap { max-width: 100%; overflow-x: auto; }
.stApp table.gl-lantern {
  border-collapse: collapse;
  font-size: 0.8rem;
  margin: 0;
  min-width: 100%;
  width: max-content;
}
.stApp table.gl-lantern th, .stApp table.gl-lantern td {
  background: transparent;
  border: 0;
  border-bottom: 1px solid rgba(232, 220, 192, 0.18);
  padding: 0.25rem 0.65rem;
  text-align: left;
  white-space: nowrap;
}
.stApp table.gl-lantern .gl-dim { color: #b9ae95; }
.stApp table.gl-lantern th.gl-lit {
  color: var(--gl-accent-text);
  border-bottom: 1px solid var(--gl-accent);
}
.stApp table.gl-lantern td.gl-lit {
  background: rgba(var(--gl-accent-rgb), 0.22);
  box-shadow: inset 0 0 12px rgba(var(--gl-accent-rgb), 0.5);
  color: #fff7e0;
}
.stApp .zs-name { font-size: 1.35rem; font-weight: 700; margin: 6px 0 10px; color: #e8dcc0; }
.stApp .zs-line, .stApp .vf-line { font-size: 0.95rem; margin: 2px 0; color: #e8dcc0; }
.stApp .zs-amber, .stApp .vf-cost { color: var(--gl-accent-text); }
.stApp .zs-tombstone .zs-line:last-child b { display: block; font-size: 1.6rem; }
.stApp .vf-cost { font-size: 1.5rem; font-weight: 700; margin-top: 0.4rem; }
.stApp [data-testid="stMetric"] {
  background: var(--gl-wash), #1c1829;
  border: 1px solid var(--gl-line);
  border-radius: 6px;
  padding: 0.7rem 1rem;
}
.stApp [data-testid="stMetricLabel"], .stApp [data-testid="stMetricLabel"] p {
  font-variant-caps: all-small-caps;
  letter-spacing: 0.14em;
  color: #b9ae95;
}
.stApp [data-testid="stMetricValue"] {
  font-family: Georgia, "Times New Roman", serif;
  font-size: 2rem;
}
.stApp [data-testid="stVerticalBlockBorderWrapper"] { border-color: rgba(232, 220, 192, 0.30); }
.stApp [class*="_card_critical_"]:not([data-testid="stVerticalBlock"]) {
  border-radius: 6px;
  box-shadow: var(--gl-glow);
}
.stApp [data-testid="stVerticalBlockBorderWrapper"]:has(
    > [data-testid="stVerticalBlock"][class*="_card_critical_"]) {
  border-radius: 6px;
  box-shadow: var(--gl-glow);
}
.stApp [data-testid="stExpander"] details {
  border: 1px solid rgba(232, 220, 192, 0.30);
  border-radius: 6px;
}
.stApp [data-testid="stExpander"] summary { color: var(--gl-accent-text); }
.stApp [data-testid="stBaseButton-secondary"]:hover {
  border-color: var(--gl-accent);
  color: var(--gl-accent-text);
}
.stApp [class^="zs-badge"], .stApp [class^="pi-badge"], .stApp [class^="vf-badge"] {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 12px;
  font-size: 0.85rem;
  border: 1px solid rgba(232, 220, 192, 0.30);
  background: #241f33;
  color: #e8dcc0;
}
.stApp [class*="-badge-llm"] {
  background: rgba(var(--gl-accent-rgb), 0.16);
  border-color: var(--gl-accent);
  color: var(--gl-accent-text);
}
.stApp [class*="-badge-rejected"] { background: #3d2a12; border-color: #ffb347; color: #ffd166; }
.stApp .gl-promise {
  font-size: 1.35rem;
  line-height: 1.5;
  color: #e8dcc0;
  margin: 0.8rem 0 1.2rem;
}
.stApp .gl-story { font-size: 1.05rem; line-height: 1.6; color: #e8dcc0; margin: 0 0 0.9rem; }
.stApp .gl-story p { margin: 0 0 0.35rem; }
.stApp .gl-example {
  border-left: 3px solid #ffb347;
  padding: 0.5rem 0.9rem;
  margin: 0 0 0.9rem;
  color: #e8dcc0;
}
.stApp .gl-example-label { font-size: 0.9rem; color: #b9ae95; margin-bottom: 0.3rem; }
.stApp .gl-example-note { font-size: 0.85rem; color: #b9ae95; margin-top: 0.4rem; }
.stApp .gl-example b { color: #ffd166; }
.stApp .gl-example mark { border-radius: 0.2rem; }
.stApp [data-testid="stMainBlockContainer"] [data-testid="stPageLink-NavLink"] {
  border: 1px solid var(--gl-accent);
  border-radius: 0.5rem;
  padding: 0.45rem 0.9rem;
  width: fit-content;
  margin: 0 0 0.9rem;
}
.stApp [data-testid="stMainBlockContainer"] [data-testid="stPageLink-NavLink"] p {
  font-size: 1rem;
  font-weight: 600;
  color: var(--gl-accent-text);
  text-decoration: underline;
}
.stApp .gl-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr));
  gap: 0.9rem;
  margin: 0.4rem 0 1.4rem;
}
.stApp .gl-grid.gl-proof { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.stApp .gl-grid .gl-card { margin-bottom: 0; }
.stApp .gl-tile-head {
  display: flex;
  align-items: center;
  gap: 0.7rem;
  border-bottom: 1px solid var(--gl-accent);
  padding-bottom: 0.6rem;
  margin-bottom: 0.6rem;
}
.stApp .gl-tile-head svg { width: 2.4rem; height: 2.4rem; color: var(--gl-accent); flex: none; }
.stApp .gl-tile-name { font-size: 1.25rem; color: #e8dcc0; }
.stApp .gl-stats { display: flex; flex-wrap: wrap; gap: 0.4rem 1.6rem; margin-top: 0.7rem; }
.stApp .gl-stats .gl-figure { font-size: 1.8rem; margin: 0; }
.stApp .gl-tiles .gl-tile { display: flex; flex-direction: column; }
.stApp .gl-tiles .gl-stats { margin-top: auto; padding-top: 0.7rem; }
.stApp .gl-tile .gl-signature { margin: 0.6rem 0 0.2rem; padding: 0.4rem 0.5rem 0.3rem; }
.stApp .gl-tile .gl-signature svg.gl-sig-svg { min-width: 0; }
.stApp .gl-tile .gl-lantern-wrap { overflow-x: auto; }
.stApp .gl-tile table.gl-lantern { width: 100%; }
.stApp .gl-tile table.gl-lantern th, .stApp .gl-tile table.gl-lantern td {
  white-space: nowrap;
}
.stApp .gl-tile table.gl-lantern td.gl-wrap {
  white-space: normal;
  word-break: normal;
}
.stApp .gl-tile-refs { margin-top: 0.2rem; }
.stApp .gl-tile-more { font-size: 0.8rem; color: #b9ae95; margin: 0.1rem 0 0; }
.stApp .gl-card-more { font-size: 0.8rem; color: #b9ae95; margin: 0.1rem 0 0; }
.stApp .gl-diagram { margin: 0.4rem 0 1rem; }
.stApp .gl-diagram svg { width: 100%; height: auto; color: #e8dcc0; }
.stApp .gl-diagram text { font-family: Georgia, "Times New Roman", serif; fill: currentColor; }
.stApp .gl-diagram .gl-diagram-step { fill: var(--gl-accent-text); letter-spacing: 0.12em; }
.stApp .gl-diagram rect { fill: #1c1829; stroke: rgba(232, 220, 192, 0.45); stroke-width: 1; }
.stApp .gl-diagram rect.gl-guard { stroke: var(--gl-accent); stroke-width: 1.6; }
.stApp .gl-diagram path { stroke: var(--gl-accent); fill: none; stroke-width: 1.6; }
@media (max-width: 1100px) {
  .stApp [data-testid="stHorizontalBlock"] { flex-wrap: wrap; }
  .stApp [data-testid="stColumn"] { flex: 1 1 15rem; min-width: min(100%, 15rem); }
}
@media (max-width: 800px) {
  .stApp .gl-grid.gl-proof { grid-template-columns: 1fr; }
  .stApp h1 { font-size: 1.9rem; }
  .stApp .gl-section { font-size: 1.3rem; }
  .stApp .gl-promise { font-size: 1.15rem; }
  .stApp .gl-figure { font-size: 1.8rem; }
  .stApp .gl-signature { padding: 0.4rem 0.5rem 0.3rem; }
  .stApp .gl-ref-chip { font-size: 0.75rem; padding: 0.05rem 0.5rem; }
  .stApp table.gl-lantern { font-size: 0.75rem; }
  .stApp [data-testid="stMainBlockContainer"] { padding: 3.5rem 1rem 4rem; }
}
"""

# The one animation of the showcase: the moment of Home (REQ-HD-18). Only the Home style block
# carries it. The base style of every piece is its final state; a keyframe names only the `from`
# state, and `both` keeps that state during the delay. Timeline: the strikes start at 1.0 s and
# 1.3 s and last 0.4 s each, the stamp starts at 1.7 s, the template at 2.1 s, everything is over
# at 2.5 s. Each animation runs once. `prefers-reduced-motion` shows the final state at once.
MOMENT_CSS: str = """
.stApp .gl-moment {
  background: var(--gl-wash), #1c1829;
  border: 1px solid var(--gl-line);
  border-left: 3px solid #ffb347;
  border-radius: 6px;
  margin: 0.4rem 0 1.4rem;
  padding: 0.9rem 1.2rem 1rem;
}
.stApp .gl-moment-label, .stApp .gl-moment-q, .stApp .gl-moment-note {
  color: #b9ae95;
  font-size: 0.9rem;
}
.stApp .gl-moment-answer { font-size: 1.2rem; line-height: 1.7; margin: 0.6rem 0 0.4rem; }
.stApp .gl-moment mark.gl-strike { border-radius: 0.2rem; position: relative; }
.stApp .gl-moment mark.gl-strike::after {
  animation: gl-strike 0.4s ease-out 1s 1 both;
  background: #b3122e;
  content: "";
  height: 3px;
  left: -2px;
  position: absolute;
  right: -2px;
  top: 50%;
  transform-origin: left center;
}
.stApp .gl-moment mark.gl-strike-2::after { animation-delay: 1.3s; }
.stApp .gl-moment .gl-stamp {
  animation: gl-stamp 0.4s ease-out 1.7s 1 both;
  border: 2px solid #ffb347;
  border-radius: 4px;
  color: #ffd166;
  font-size: 1.05rem;
  margin: 0.5rem 0 0.8rem;
  padding: 0.35rem 0.8rem;
  transform: rotate(-1deg);
  width: fit-content;
}
.stApp .gl-moment .gl-moment-after { animation: gl-fade 0.4s ease-out 2.1s 1 both; }
.stApp .gl-moment-template { margin: 0.2rem 0 0.6rem; }
@keyframes gl-strike { from { transform: scaleX(0); } }
@keyframes gl-stamp { from { opacity: 0; transform: rotate(-1deg) scale(1.6); } }
@keyframes gl-fade { from { opacity: 0; } }
@media (prefers-reduced-motion: reduce) {
  .stApp .gl-moment mark.gl-strike::after,
  .stApp .gl-moment .gl-stamp,
  .stApp .gl-moment .gl-moment-after { animation: none; }
}
"""


def _accent_vars(selector: str, accent: Accent) -> str:
    """Return the rule that sets the accent variables (colour, text colour, wash, glow)."""
    rgb = accent.rgb
    return (
        f"{selector} {{\n"
        f"  --gl-accent: {accent.color};\n"
        f"  --gl-accent-text: {accent.text_color};\n"
        f"  --gl-accent-rgb: {rgb};\n"
        f"  --gl-line: {LINE};\n"
        f"  --gl-wash: linear-gradient(180deg, rgba({rgb}, 0.08), transparent 55%);\n"
        f"  --gl-glow: 0 0 0 1px rgba({rgb}, 0.55), 0 0 22px rgba({rgb}, 0.28);\n"
        f"}}"
    )


def _nav_css() -> str:
    """Return the rules that draw the menu icons as masked SVG, coloured by the link text."""
    rules = []
    for test, name in NAV_ICONS:
        selector = (
            f'.stApp [data-testid="stSidebarNavLink"]{test}::before,\n'
            f'.stApp [data-testid="stSidebarNav"] a{test}::before'
        )
        uri = mask_uri(name)
        rules.append(
            f"{selector} {{\n"
            "  content: '';\n"
            "  display: inline-block;\n"
            "  flex: none;\n"
            "  width: 1.15rem;\n"
            "  height: 1.15rem;\n"
            "  margin-right: 0.6rem;\n"
            "  background-color: currentColor;\n"
            f"  -webkit-mask: url({uri}) center / contain no-repeat;\n"
            f"  mask: url({uri}) center / contain no-repeat;\n"
            "}"
        )
    return "\n".join(rules)


def theme_css(accent: Accent, app_css: str = "") -> str:
    """Return the one ``<style>`` block of a page: accent variables, app rules, base, menu icons.

    The base comes after the app's own rules on purpose: an app may bring older rules of equal
    weight (the phantom `.stApp` background, the coffin clip-path) and the shared look must win.
    The card box and the accent rules carry a `.stApp` prefix for the same reason.
    """
    parts = [_accent_vars(".stApp", accent), app_css, BASE_CSS, _nav_css()]
    if accent is KIT:
        parts.append(MOMENT_CSS)
    if accent is KIT or accent is BENCHMARK:
        parts += [_accent_vars(f".stApp .gl-tile-{tile.key}", tile) for tile in TILE_ACCENTS]
    return "<style>\n" + "\n".join(part.strip("\n") for part in parts if part) + "\n</style>"


# --- Streamlit wrappers -------------------------------------------------------------------------


def apply_theme(accent: Accent, app_css: str = "") -> None:
    """Inject the one style block of the page."""
    st.markdown(theme_css(accent, app_css), unsafe_allow_html=True)


def set_page(title: str, accent: Accent) -> None:
    """Set the browser tab: the page title and the accent-coloured SVG icon (no emoji)."""
    st.set_page_config(
        page_title=title, page_icon=favicon_uri(accent.icon, accent.color), layout="wide"
    )


def masthead_html(accent: Accent, kicker: str | None = None) -> str:
    """Return the icon and kicker line that sits above the page title."""
    text = accent.kicker if kicker is None else kicker
    return (
        '<div class="gl-mast">'
        f'<span class="gl-mast-icon">{icon(accent.icon, size=44, decorative=True)}</span>'
        f'<span class="gl-kicker">{html.escape(text)}</span></div>'
    )


def show_masthead(accent: Accent, kicker: str | None = None) -> None:
    """Draw the masthead; call it right before ``st.title``."""
    st.markdown(masthead_html(accent, kicker), unsafe_allow_html=True)


def section_html(icon_name: str, text: str) -> str:
    """Return a section heading: icon, text, and the accent rule under them."""
    return (
        '<div class="gl-section" role="heading" aria-level="2">'
        f"{icon(icon_name, size=26, decorative=True)}<span>{html.escape(text)}</span></div>"
    )


def show_section(icon_name: str, text: str) -> None:
    """Draw a section heading (replaces ``st.subheader`` with an emoji)."""
    st.markdown(section_html(icon_name, text), unsafe_allow_html=True)


def severity_marker(severity: str) -> str:
    """Return the severity badge of an alert: a small icon and the severity word."""
    if severity not in SEVERITY_ICON:
        raise ValueError(f"unknown severity {severity!r}; expected one of {list(SEVERITY_ICON)}")
    return (
        f'<span class="gl-sev gl-sev-{severity}">'
        f"{icon(SEVERITY_ICON[severity], size=16, decorative=True)}"
        f"<span>{severity}</span></span>"
    )


def severity_heading_html(severity: str) -> str:
    """Return the sub-heading that opens a group of alerts of one severity."""
    return f'<div class="gl-sub" role="heading" aria-level="3">{severity_marker(severity)}</div>'


def show_severity(severity: str) -> None:
    """Draw the sub-heading of a severity group."""
    st.markdown(severity_heading_html(severity), unsafe_allow_html=True)


def card_key(prefix: str, severity: str, alert_id: str) -> str:
    """Return the container key of an alert card; ``_card_critical_`` makes it glow."""
    return f"{prefix}_card_{severity}_{alert_id}"


def card_html(
    label: str,
    figure: str,
    note: str = "",
    refs: tuple[str, ...] = (),
    *,
    critical: bool = False,
    extra_class: str = "",
) -> str:
    """Return a card: small-caps label, large figure, a note, the cited rows under it.

    Every text is escaped. ``extra_class`` may only hold lowercase letters, digits, ``-``, ``_``
    and spaces. A soft accent glow is added only when ``critical`` is true.
    """
    if not _SAFE_CLASS.match(extra_class):
        raise ValueError(f"unsafe class name {extra_class!r}")
    classes = ["gl-card"]
    if critical:
        classes.append("gl-critical")
    if extra_class:
        classes.append(extra_class)
    parts = [
        f'<div class="{" ".join(classes)}">',
        f'<div class="gl-label">{html.escape(label)}</div>',
        f'<div class="gl-figure">{html.escape(figure)}</div>',
    ]
    if note:
        parts.append(f'<div class="gl-note">{html.escape(note)}</div>')
    parts.extend(f'<span class="gl-ref">{html.escape(ref)}</span>' for ref in refs)
    parts.append("</div>")
    return "".join(parts)
