"""Tests of the shared haunted-ledger look (haunted-design, REQ-HD-01 to REQ-HD-08, 12, 13).

Pure tests: they read the CSS string and the HTML helpers, not a browser. What a browser makes of
them (inline SVG inside st.markdown, the menu selectors, the glow) is checked by eye.
"""

import base64
import re
import tomllib
from pathlib import Path

import pytest

from ledger_kit.ui import theme
from ledger_kit.ui.icons import ICON_NAMES
from ledger_kit.ui.theme import (
    ACCENTS,
    BENCHMARK,
    BONE,
    KIT,
    MUTED,
    NAV_ICONS,
    NIGHT,
    PANEL,
    PHANTOM,
    SEVERITY_ICON,
    VAMPIRE,
    ZOMBIE,
    Accent,
    card_html,
    card_key,
    masthead_html,
    section_html,
    severity_heading_html,
    severity_marker,
    theme_css,
)

CONFIG = Path(__file__).resolve().parents[1] / ".streamlit" / "config.toml"
EMOJI = re.compile("[\U0001f000-\U0001faff\u2600-\u27bf\u2b00-\u2bff]")
MIN_TEXT_CONTRAST = 4.5
APPS = (ZOMBIE, PHANTOM, VAMPIRE)


def _luminance(colour: str) -> float:
    """Relative luminance of a #rrggbb colour (WCAG 2.x)."""
    channels = []
    for index in (1, 3, 5):
        value = int(colour[index : index + 2], 16) / 255
        channels.append(value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast(foreground: str, background: str) -> float:
    """WCAG contrast ratio between two #rrggbb colours."""
    light, dark = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


# --- palette and accents (REQ-HD-01, 02, 04) ---------------------------------------------------


def test_the_night_and_bone_colours_are_the_shared_theme() -> None:
    config = tomllib.loads(CONFIG.read_text(encoding="utf-8"))["theme"]

    assert (NIGHT, BONE, PANEL) == ("#12101a", "#e8dcc0", "#1c1829")
    assert config["backgroundColor"] == NIGHT
    assert config["textColor"] == BONE
    assert config["secondaryBackgroundColor"] == PANEL
    assert config["primaryColor"] == KIT.color == "#7cffb2"  # the kit accent stays


def test_each_app_has_its_own_accent() -> None:
    assert ZOMBIE.color == "#8fae6b"  # moss green
    assert PHANTOM.color == "#5fd0c8"  # spectral teal
    assert VAMPIRE.color == "#c2334d"  # blood red
    assert len({accent.color for accent in ACCENTS}) == len(ACCENTS)


@pytest.mark.parametrize("accent", [*ACCENTS, BENCHMARK], ids=lambda accent: accent.key)
def test_accent_text_is_readable_on_the_night_and_card_backgrounds(accent: Accent) -> None:
    assert _contrast(accent.text_color, NIGHT) >= MIN_TEXT_CONTRAST
    assert _contrast(accent.text_color, PANEL) >= MIN_TEXT_CONTRAST


def test_body_and_muted_text_are_readable() -> None:
    for text in (BONE, MUTED):
        assert _contrast(text, NIGHT) >= MIN_TEXT_CONTRAST
        assert _contrast(text, PANEL) >= MIN_TEXT_CONTRAST
    assert _contrast(BONE, NIGHT) > 12


@pytest.mark.parametrize("accent", [*ACCENTS, BENCHMARK], ids=lambda accent: accent.key)
def test_the_rgb_triplet_is_the_accent_colour(accent: Accent) -> None:
    red, green, blue = (int(part) for part in accent.rgb.split(","))

    assert f"#{red:02x}{green:02x}{blue:02x}" == accent.color


def test_every_accent_names_an_existing_icon() -> None:
    assert {accent.icon for accent in [*ACCENTS, BENCHMARK]} <= set(ICON_NAMES)
    assert set(SEVERITY_ICON.values()) <= set(ICON_NAMES)
    assert {name for _test, name in NAV_ICONS} <= set(ICON_NAMES)


# --- the CSS block (REQ-HD-01 to 03, 07, 12, 13) ------------------------------------------------


@pytest.mark.parametrize("accent", [*ACCENTS, BENCHMARK], ids=lambda accent: accent.key)
def test_the_css_is_one_style_block_with_the_palette_and_the_accent(accent: Accent) -> None:
    css = theme_css(accent)

    assert css.startswith("<style>") and css.endswith("</style>")
    assert css.count("<style") == 1 and css.count("</style>") == 1
    assert NIGHT in css and BONE in css
    assert f"--gl-accent: {accent.color};" in css
    assert f"--gl-accent-text: {accent.text_color};" in css


@pytest.mark.parametrize("accent", APPS, ids=lambda accent: accent.key)
def test_an_app_page_declares_its_accent_and_no_other(accent: Accent) -> None:
    css = theme_css(accent)

    assert re.findall(r"--gl-accent: (#[0-9a-f]{6});", css) == [accent.color]
    for other in (a for a in ACCENTS if a is not accent):
        assert f"--gl-accent: {other.color};" not in css


def test_only_home_and_benchmark_carry_the_tile_accents() -> None:
    for accent in (KIT, BENCHMARK):
        css = theme_css(accent)
        assert css.count("--gl-accent: ") == 1 + len(APPS)
        assert all(f".gl-tile-{app.key}" in css for app in APPS)
    for accent in APPS:
        assert all(f".gl-tile-{app.key}" not in theme_css(accent) for app in APPS)


def test_titles_use_the_serif_display_stack_with_letter_spacing() -> None:
    css = theme_css(KIT)

    assert theme.DISPLAY_FONT == 'Georgia, "Times New Roman", serif'
    start = css.index(".stApp h1, .stApp h2, .stApp h3, .stApp .gl-section")
    rule = css[start : css.index("}", start)]
    assert 'font-family: Georgia, "Times New Roman", serif;' in rule
    assert "letter-spacing: 0.05em;" in rule


def test_no_external_font_style_sheet_script_or_url() -> None:
    css = theme_css(KIT, ".x { color: red; }")

    for forbidden in ("@import", "@font-face", "url(http", "//fonts", "<script", "<link"):
        assert forbidden not in css
    urls = re.findall(r"url\(([^)]*)\)", css)
    assert urls and all(url.startswith("data:image/svg+xml;base64,") for url in urls)


def test_nothing_animates() -> None:
    css = theme_css(KIT).lower()

    for word in ("animation", "@keyframes", "transition"):
        assert word not in css


def test_the_only_decoration_is_a_static_fog_gradient() -> None:
    css = theme_css(ZOMBIE)

    assert css.count("radial-gradient(") >= 2
    assert "background-attachment: fixed" in css


def test_the_layout_adapts_to_1100_and_800_pixels() -> None:
    css = theme_css(KIT)

    assert "@media (max-width: 1100px)" in css and "@media (max-width: 800px)" in css
    wide = css[css.index("@media (max-width: 1100px)") : css.index("@media (max-width: 800px)")]
    assert 'stHorizontalBlock"] { flex-wrap: wrap; }' in wide
    assert "auto-fit, minmax(14rem, 1fr)" in css  # the card grids wrap by themselves


def test_each_menu_entry_has_a_masked_icon_and_no_emoji() -> None:
    css = theme_css(KIT)
    masks = re.findall(r"^  mask: url\(([^)]+)\)", css, flags=re.MULTILINE)

    assert len(masks) == len(NAV_ICONS) == 5
    for uri, (_test, name) in zip(masks, NAV_ICONS, strict=True):
        svg = base64.b64decode(uri.split(",", 1)[1]).decode("utf-8")
        assert f"gl-icon-{name}" in svg and 'stroke="#000000"' in svg
    assert EMOJI.search(css) is None
    assert css.count("background-color: currentColor") == len(NAV_ICONS)


def test_the_app_rules_come_before_the_base_so_the_shared_look_wins() -> None:
    css = theme_css(VAMPIRE, ".vf-marker { color: red; }")

    assert css.index(".vf-marker") < css.index(".stApp .gl-card, .stApp .zs-tombstone")


def test_the_css_has_no_line_longer_than_100_characters() -> None:
    assert max(len(line) for line in theme.BASE_CSS.splitlines()) <= 100


def test_a_critical_glow_is_defined_for_cards_and_alert_containers_only() -> None:
    css = theme_css(PHANTOM)

    assert "_card_critical_" in css
    assert "_card_warning_" not in css and "_card_info_" not in css
    assert ".stApp .gl-card.gl-critical { box-shadow: var(--gl-glow); }" in css
    assert "--gl-glow: 0 0 0 1px rgba(95, 208, 200, 0.55)" in css


# --- HTML helpers (REQ-HD-06, 08) ----------------------------------------------------------------


def test_a_card_has_label_figure_note_and_the_cited_rows_under_it() -> None:
    markup = card_html("Yearly cost", "78,00 EUR", "Monthly fee.", ("s.csv:1", "s.csv:2"))

    assert markup.startswith('<div class="gl-card">') and markup.endswith("</div>")
    positions = [markup.index(part) for part in ("gl-label", "gl-figure", "gl-note", "gl-ref")]
    assert positions == sorted(positions)
    assert markup.count('class="gl-ref"') == 2
    assert "gl-critical" not in markup


def test_only_a_critical_card_gets_the_glow_class() -> None:
    glowing = card_html("a", "b", critical=True, extra_class="tile")

    assert "gl-critical" in card_html("a", "b", critical=True)
    assert "gl-critical" not in card_html("a", "b", critical=False)
    assert 'class="gl-card gl-critical tile"' in glowing


def test_a_card_escapes_every_text_and_refuses_an_unsafe_class() -> None:
    markup = card_html("<i>", "<b>1</b>", "<u>", ("<s>",))

    for raw in ("<i>", "<b>", "<u>", "<s>"):
        assert raw not in markup
    with pytest.raises(ValueError, match="unsafe class"):
        card_html("a", "b", extra_class='x" onmouseover="y')


def test_the_severity_badge_is_an_icon_and_a_word_without_emoji() -> None:
    for severity, name in SEVERITY_ICON.items():
        markup = severity_marker(severity)
        assert f"gl-sev-{severity}" in markup and f"gl-icon-{name}" in markup
        assert f"<span>{severity}</span>" in markup
        assert EMOJI.search(markup) is None
    assert 'role="heading"' in severity_heading_html("critical")
    with pytest.raises(ValueError, match="unknown severity"):
        severity_marker("fatal")


def test_masthead_and_section_headings_carry_an_icon_and_no_emoji() -> None:
    mast = masthead_html(ZOMBIE)
    section = section_html("tombstone", "The <graveyard>")

    assert "gl-icon-tombstone" in mast and ZOMBIE.kicker in mast
    assert 'role="heading" aria-level="2"' in section and "gl-icon-tombstone" in section
    assert "The &lt;graveyard&gt;" in section and "<graveyard>" not in section
    assert EMOJI.search(mast + section) is None
    assert masthead_html(ZOMBIE, "A <b> kicker").count("<b>") == 0


def test_the_container_key_carries_the_severity() -> None:
    assert card_key("zs", "critical", "abc") == "zs_card_critical_abc"
    assert "_card_critical_" not in card_key("zs", "warning", "abc")
