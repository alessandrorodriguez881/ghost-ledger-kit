"""Tests of the inline SVG icons (haunted-design, REQ-HD-05).

The markup is parsed with defusedxml (the pinned XML parser of the project); a string that does
not parse, or that carries a script, an image, a link or a fixed colour, fails here.
"""

import base64
import re

import pytest
from defusedxml.ElementTree import fromstring

from ledger_kit.ui.icons import ICON_NAMES, favicon_uri, icon, mask_uri, standalone_svg

SVG = "{http://www.w3.org/2000/svg}"
ALLOWED_TAGS = {"svg", "title", "path", "circle"}
HEX_COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}")


def _decode(uri: str) -> str:
    """Return the SVG text inside a base64 data URI."""
    prefix = "data:image/svg+xml;base64,"
    assert uri.startswith(prefix)
    return base64.b64decode(uri[len(prefix) :]).decode("utf-8")


def test_the_set_is_the_six_requested_icons() -> None:
    assert set(ICON_NAMES) == {"tombstone", "ghost", "coffin", "candle", "magnifier", "scales"}
    assert len(ICON_NAMES) == 6


@pytest.mark.parametrize("name", ICON_NAMES)
def test_icon_is_valid_svg_with_a_title(name: str) -> None:
    root = fromstring(icon(name))

    assert root.tag == f"{SVG}svg"
    assert root.get("viewBox") == "0 0 24 24"
    title = root.find(f"{SVG}title")
    assert title is not None and (title.text or "").strip()
    assert [child for child in root if child.tag != f"{SVG}title"]  # it draws something


@pytest.mark.parametrize("name", ICON_NAMES)
def test_icon_is_monochrome_and_uses_current_color(name: str) -> None:
    markup = icon(name)
    root = fromstring(markup)

    assert root.get("stroke") == "currentColor"
    assert root.get("fill") == "none"
    assert HEX_COLOUR.search(markup) is None
    for element in root.iter():
        assert element.get("fill") in (None, "none")
        assert element.get("stroke") in (None, "currentColor")


@pytest.mark.parametrize("name", ICON_NAMES)
def test_icon_is_one_line_so_markdown_keeps_it_in_its_html_block(name: str) -> None:
    assert "\n" not in icon(name)


@pytest.mark.parametrize("name", ICON_NAMES)
def test_icon_has_no_script_image_link_or_network_reference(name: str) -> None:
    markup = icon(name)
    tags = {element.tag.removeprefix(SVG) for element in fromstring(markup).iter()}

    assert tags <= ALLOWED_TAGS
    assert "href" not in markup and "src=" not in markup and "url(" not in markup
    assert markup.count("http") == 1  # the SVG namespace in xmlns, which is not a request


def test_the_icons_are_all_different() -> None:
    assert len({icon(name) for name in ICON_NAMES}) == len(ICON_NAMES)


def test_the_title_can_be_set_and_is_escaped() -> None:
    root = fromstring(icon("ghost", title='A <b> & "c"'))

    title = root.find(f"{SVG}title")
    assert title is not None and title.text == 'A <b> & "c"'


def test_a_decorative_icon_is_hidden_from_assistive_technology_but_keeps_its_title() -> None:
    decorative = icon("candle", decorative=True)
    plain = icon("candle")

    assert 'aria-hidden="true"' in decorative and 'role="img"' not in decorative
    assert 'role="img"' in plain and "aria-hidden" not in plain
    assert "<title>Candle</title>" in decorative and "<title>Candle</title>" in plain


def test_the_size_is_set_on_both_sides() -> None:
    root = fromstring(icon("scales", size=40))

    assert (root.get("width"), root.get("height")) == ("40", "40")


def test_an_unknown_icon_is_an_error() -> None:
    with pytest.raises(ValueError, match="unknown icon"):
        icon("pumpkin")
    with pytest.raises(ValueError, match="unknown icon"):
        standalone_svg("pumpkin", "#ffffff")


def test_standalone_svg_has_a_fixed_colour() -> None:
    root = fromstring(standalone_svg("tombstone", "#8fae6b"))

    assert root.get("stroke") == "#8fae6b"
    assert root.find(f"{SVG}title") is not None


@pytest.mark.parametrize("colour", ["green", "#fff", "8fae6b", "#8fae6bff"])
def test_standalone_svg_rejects_a_colour_that_is_not_rrggbb(colour: str) -> None:
    with pytest.raises(ValueError, match="colour"):
        standalone_svg("ghost", colour)


@pytest.mark.parametrize("name", ICON_NAMES)
def test_mask_and_favicon_are_base64_svg_data_uris(name: str) -> None:
    mask = fromstring(_decode(mask_uri(name)))
    favicon = fromstring(_decode(favicon_uri(name, "#5fd0c8")))

    assert mask.get("stroke") == "#000000"
    assert favicon.get("stroke") == "#5fd0c8"
    assert mask.tag == favicon.tag == f"{SVG}svg"
