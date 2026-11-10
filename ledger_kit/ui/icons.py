"""Inline SVG line icons of the haunted ledger (spec haunted-design, REQ-HD-05).

Six monochrome icons drawn on a 24 by 24 grid with a 1.5 stroke: tombstone, ghost, coffin,
candle, magnifier and scales. Every icon is stroked with ``currentColor`` so it takes the colour
of the text around it, and carries a ``<title>`` element for accessibility. The module is pure:
no Streamlit, no I/O, no network, no font.

``icon`` returns one line of markup with no blank line, which is what ``st.markdown`` needs to
keep an inline SVG inside an HTML block. ``standalone_svg`` returns the same drawing with a fixed
colour, for the favicon and for the CSS masks of the navigation menu.
"""

from __future__ import annotations

import base64
import html

ICON_NAMES: tuple[str, ...] = ("tombstone", "ghost", "coffin", "candle", "magnifier", "scales")

VIEW_BOX: str = "0 0 24 24"
STROKE_WIDTH: str = "1.5"
SVG_NAMESPACE: str = "http://www.w3.org/2000/svg"

# The drawings: shapes only, no colour. Each one is a few paths and circles.
_SHAPES: dict[str, tuple[str, ...]] = {
    "tombstone": (
        '<path d="M6 21V10a6 6 0 0 1 12 0v11"/>',
        '<path d="M3 21h18"/>',
        '<path d="M12 9v6M9.5 11.5h5"/>',
    ),
    "ghost": (
        '<path d="M6 20.5V11a6 6 0 0 1 12 0v9.5l-2-1.75-2 1.75-2-1.75-2 1.75-2-1.75-2 1.75z"/>',
        '<circle cx="9.5" cy="11" r="0.9"/>',
        '<circle cx="14.5" cy="11" r="0.9"/>',
        '<path d="M10.5 14.5a1.5 1.5 0 0 0 3 0"/>',
    ),
    "coffin": (
        '<path d="M9 2.5h6l3.5 6-2.5 13H8l-2.5-13z"/>',
        '<path d="M12 8v8M9.5 11h5"/>',
    ),
    "candle": (
        '<path d="M9 11h6v10H9z"/>',
        '<path d="M7 21h10"/>',
        '<path d="M12 9.5V11"/>',
        '<path d="M12 3c1.8 2 2.5 3.4 2.5 4.6a2.5 2.5 0 0 1-5 0C9.5 6.4 10.2 5 12 3z"/>',
    ),
    "magnifier": (
        '<circle cx="10.5" cy="10.5" r="6.5"/>',
        '<path d="M15.3 15.3 21 21"/>',
        '<path d="M8 10.5a2.5 2.5 0 0 1 2.5-2.5"/>',
    ),
    "scales": (
        '<path d="M12 4v16M8 20h8M5 7h14"/>',
        '<path d="M5 7l-3 7M5 7l3 7M19 7l-3 7M19 7l3 7"/>',
        '<path d="M2 14h6a3 3 0 0 1-6 0zM16 14h6a3 3 0 0 1-6 0z"/>',
    ),
}

# Default accessible name of each icon (the text of its <title>).
_LABELS: dict[str, str] = {
    "tombstone": "Tombstone",
    "ghost": "Ghost",
    "coffin": "Coffin",
    "candle": "Candle",
    "magnifier": "Magnifying glass",
    "scales": "Scales",
}


def _check(name: str) -> None:
    """Raise ValueError for a name that is not one of ICON_NAMES."""
    if name not in _SHAPES:
        raise ValueError(f"unknown icon {name!r}; expected one of {list(ICON_NAMES)}")


def _svg(name: str, *, stroke: str, size: int, title: str, extra: str, css_class: str) -> str:
    """Assemble the one-line markup of an icon with the given stroke colour."""
    shapes = "".join(_SHAPES[name])
    return (
        f'<svg xmlns="{SVG_NAMESPACE}" viewBox="{VIEW_BOX}" width="{size}" height="{size}" '
        f'class="{css_class}" fill="none" stroke="{stroke}" stroke-width="{STROKE_WIDTH}" '
        f'stroke-linecap="round" stroke-linejoin="round"{extra}>'
        f"<title>{html.escape(title, quote=False)}</title>{shapes}</svg>"
    )


def icon(name: str, *, size: int = 24, title: str | None = None, decorative: bool = False) -> str:
    """Return the inline SVG of an icon, stroked with currentColor and titled for screen readers.

    ``decorative=True`` marks the icon ``aria-hidden`` for places where a word next to it already
    names it; the ``<title>`` element is still there.
    """
    _check(name)
    extra = ' aria-hidden="true" focusable="false"' if decorative else ' role="img"'
    return _svg(
        name,
        stroke="currentColor",
        size=size,
        title=_LABELS[name] if title is None else title,
        extra=extra,
        css_class=f"gl-icon gl-icon-{name}",
    )


def standalone_svg(name: str, color: str, *, size: int = 64) -> str:
    """Return the icon as a standalone SVG document string in a fixed ``#rrggbb`` colour."""
    _check(name)
    if len(color) != 7 or not color.startswith("#"):
        raise ValueError(f"colour must be written #rrggbb, got {color!r}")
    return _svg(
        name, stroke=color, size=size, title=_LABELS[name], extra="", css_class=f"gl-icon-{name}"
    )


def _data_uri(svg: str) -> str:
    """Return a base64 ``data:`` URI of an SVG string (no characters to escape in CSS)."""
    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def mask_uri(name: str) -> str:
    """Return the data URI used as a CSS ``mask-image``: the shape in black, alpha only."""
    return _data_uri(standalone_svg(name, "#000000", size=24))


def favicon_uri(name: str, color: str) -> str:
    """Return the data URI of the icon in an accent colour, for ``st.set_page_config``."""
    return _data_uri(standalone_svg(name, color, size=64))
