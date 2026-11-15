"""Polish of the three Home tiles (haunted-design session 26c).

The zombie drawing is made on the narrower tile viewBox, so the browser scales it by about one
instead of about 0.4; the lantern of the tile keeps the source ref and at most two compared
columns and wraps free text only between words; a tile
shows at most three source-ref chips and one computed line for the rest; the three tiles have the
same height with the demo numbers at the bottom. The alert cards are unchanged. No model, no
network; all data is synthetic.
"""

import re
from datetime import date

import pandas as pd
from judge_path_support import _vampire

from apps import home_tiles
from ledger_kit.ui import signatures, theme
from ledger_kit.ui.signatures import TILE_WIDTH, WIDTH, heartbeat_svg, refs_chips_html

VIEW_BOX = re.compile(r'viewBox="0 0 (\d+) (\d+)"')
CHIP = 'class="gl-ref-chip"'


def _rows() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": [date(2026, 5, 31), date(2026, 6, 30), date(2026, 7, 31)],
            "amount": ["9.99", "9.99", "9.99"],
            "currency": ["EUR", "EUR", "EUR"],
        }
    )


def _rule(css: str, selector: str) -> str:
    """The body of the first rule whose selector list ends with `selector`."""
    found = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert found, selector
    return found.group(1)


# --- 1. the zombie drawing is scaled to the width of the tile ------------------------------------


def test_the_tile_heartbeat_uses_the_tile_viewbox_and_the_card_keeps_its_own() -> None:
    card = VIEW_BOX.search(heartbeat_svg(_rows(), "2026-06-30"))
    tile = VIEW_BOX.search(heartbeat_svg(_rows(), "2026-06-30", width=TILE_WIDTH))

    assert card is not None and tile is not None
    assert int(card[1]) == WIDTH and int(tile[1]) == TILE_WIDTH < WIDTH
    assert card[2] == tile[2]  # same height: only the time line is shorter


def test_the_tile_heartbeat_marks_are_as_big_as_on_the_card() -> None:
    card = heartbeat_svg(_rows(), "2026-06-30")
    tile = heartbeat_svg(_rows(), "2026-06-30", width=TILE_WIDTH)

    assert re.findall(r' r="([\d.]+)"', card) == re.findall(r' r="([\d.]+)"', tile)
    assert f"H{TILE_WIDTH - 8}" in tile and f"H{WIDTH - 8}" in card
    assert "gl-sig-line" in tile and "gl-dot" in tile and "gl-tomb" in tile


def test_the_tile_heartbeat_keeps_every_mark_inside_its_viewbox() -> None:
    tile = heartbeat_svg(_rows(), None, width=TILE_WIDTH)

    xs = [float(x) for x in re.findall(r'cx="([\d.]+)"', tile)]
    assert len(xs) == 3 and all(0 <= x <= TILE_WIDTH for x in xs)


def test_the_zombie_tile_is_drawn_on_the_tile_viewbox() -> None:
    drawing = home_tiles.tile_signatures()["zombie"]
    found = VIEW_BOX.search(drawing)

    assert found is not None and int(found[1]) == TILE_WIDTH
    assert "gl-heartbeat" in drawing


def test_the_tile_svg_fills_the_tile_width() -> None:
    css = theme.BASE_CSS

    assert "width: 100%" in _rule(css, ".stApp .gl-signature svg.gl-sig-svg")
    assert "min-width: 0" in _rule(css, ".stApp .gl-tile .gl-signature svg.gl-sig-svg")
    assert signatures.DOT_RADIUS == 5  # the dot of the card is the dot of the tile


# --- 2. the lantern of the tile wraps only between words -----------------------------------------


def test_the_tile_lantern_never_breaks_inside_a_word_and_the_card_is_unchanged() -> None:
    css = theme.BASE_CSS
    tile = _rule(css, ".stApp .gl-tile table.gl-lantern td")
    text = _rule(css, ".stApp .gl-tile table.gl-lantern td.gl-wrap")
    card = _rule(css, ".stApp table.gl-lantern td")

    assert "white-space: nowrap" in tile and "white-space: nowrap" in card
    assert "white-space: normal" in text and "word-break: normal" in text
    assert "width: 100%" in _rule(css, ".stApp .gl-tile table.gl-lantern")
    assert "overflow-x: auto" in _rule(css, ".stApp .gl-tile .gl-lantern-wrap")


def test_no_rule_of_the_tile_lantern_breaks_words() -> None:
    rules = [line for line in theme.BASE_CSS.split("}") if ".gl-tile table.gl-lantern" in line]

    assert rules
    for rule in rules:
        assert "overflow-wrap" not in rule
        assert "break-all" not in rule and "break-word" not in rule


def test_the_wrap_rule_reaches_the_header_cells_too() -> None:
    assert ".stApp .gl-tile table.gl-lantern th" in theme.BASE_CSS


def test_the_tile_lantern_has_at_most_three_columns_and_marks_the_text_ones() -> None:
    drawing = home_tiles.tile_signatures()["phantom"]
    head = drawing[drawing.index("<thead>") : drawing.index("</thead>")]

    assert head.count("<th ") <= 3 and head.count("<th ") >= 1
    assert "source ref" in head
    assert home_tiles.TILE_MAX_COMPARED == 2


def test_only_text_columns_get_the_wrap_class() -> None:
    frame = pd.DataFrame(
        {"source_ref": ["i.csv:0"], "supplier_name": ["Acme Ltd"], "total": ["48 4,00 EUR"]}
    )
    markup = signatures.lantern_html(frame, ["total"], text_columns=["supplier_name"])

    assert markup.count("gl-wrap") == 2  # the header and the cell of supplier_name
    assert 'class="gl-lit">48 4,00' in markup
    assert "gl-wrap" not in signatures.lantern_html(frame, ["total"])  # card markup unchanged


def test_the_tile_columns_are_the_first_two_lantern_columns_of_the_detector() -> None:
    from ledger_kit.models import Alert

    alert = Alert(
        detector="pi.vat_error", severity="warning", title="t", source_refs=["i.csv:0"], data={}
    )
    view = pd.DataFrame(columns=["source_ref", "total", "vat_amount", "base_amount", "vat_rate"])

    columns = home_tiles.tile_lantern_columns
    assert columns(alert, view) == ["source_ref", "base_amount", "vat_rate"]
    # a column the view lacks is skipped, the next one of the mapping takes its place
    view = view.drop(columns=["base_amount"])
    assert columns(alert, view) == ["source_ref", "vat_rate", "vat_amount"]


# --- 3. at most three chips, then a computed line ------------------------------------------------


def _refs(count: int) -> list[str]:
    return [f"s.csv:{n}" for n in range(count)]


def test_a_tile_with_many_refs_shows_three_chips_and_the_computed_rest() -> None:
    markup = home_tiles.tile_refs_html(_refs(7))

    assert markup.count(CHIP) == 3
    assert markup.endswith('<div class="gl-tile-more">and 4 more cited rows</div>')
    assert "s.csv · row 3" not in markup and "s.csv · row 2" in markup


def test_the_remainder_is_computed_from_the_number_of_refs() -> None:
    for count in range(4, 30):
        markup = home_tiles.tile_refs_html(_refs(count))
        assert f"and {count - 3} more cited row" in markup


def test_one_more_ref_is_singular() -> None:
    assert "and 1 more cited row</div>" in home_tiles.tile_refs_html(_refs(4))


def test_three_refs_or_fewer_show_all_chips_and_no_line() -> None:
    for count in range(0, 4):
        markup = home_tiles.tile_refs_html(_refs(count))
        assert markup == refs_chips_html(_refs(count))
        assert "gl-tile-more" not in markup


def test_the_vampire_tile_has_three_chips_and_its_rest() -> None:
    alert = home_tiles.pick_alert(_vampire().alerts)
    assert alert is not None
    drawing = home_tiles.tile_signatures()["vampire"]
    refs = drawing[drawing.index('<div class="gl-tile-refs">') :]

    assert home_tiles.TILE_MAX_CHIPS == 3
    assert refs.count(CHIP) == min(3, len(alert.source_refs))
    if len(alert.source_refs) > 3:
        assert f"and {len(alert.source_refs) - 3} more cited row" in refs


def test_the_alert_card_still_has_a_chip_for_every_ref() -> None:
    assert refs_chips_html(_refs(7)).count(CHIP) == 7


# --- 4. the three tiles have the same height -----------------------------------------------------


def test_the_tiles_are_columns_and_the_numbers_sit_at_the_bottom() -> None:
    css = theme.BASE_CSS

    assert "display: flex" in _rule(css, ".stApp .gl-tiles .gl-tile")
    assert "flex-direction: column" in _rule(css, ".stApp .gl-tiles .gl-tile")
    assert "margin-top: auto" in _rule(css, ".stApp .gl-tiles .gl-stats")
    assert "align-items" not in _rule(css, ".stApp .gl-grid")  # grid items stretch by default


def test_the_new_css_lines_stay_within_one_hundred_characters() -> None:
    assert max(len(line) for line in theme.BASE_CSS.splitlines()) <= 100
