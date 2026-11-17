"""The visual signature of each app on every alert card (spec app-signatures).

Four pure functions return escaped markup, never a Streamlit call: ``refs_chips_html`` (one chip
per source ref, all apps), ``heartbeat_svg`` (Zombie: one dot per cited row on a pulse line, a
tombstone at the cancellation date), ``bites_svg`` (Vampire: one fang-shaped bar per cited fee row)
and ``lantern_html`` (Phantom: a table of the cited rows with the compared fields lit).
``signature_block`` wraps one drawing and its caption in the ``gl-signature`` box.

A signature shows only what the cited rows say. The visible text is the first and last cited date
and, for the heartbeat, the cancellation date; each mark carries a ``title`` with the date and the
amount of its row written as the ``Source rows`` expander writes them. There is no sum, no average
and no count. Colours are CSS variables set from the ``Accent`` of the page in ``theme.py``, so
this module imports no Streamlit. The one calculation on an amount, the height of a bar, is the
helper ``scale_to`` of ``money.py``; its result is a drawing length and never reaches a text.
"""

from __future__ import annotations

import html
import re
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import pandas as pd

from ledger_kit.utils.money import format_amount, scale_to

ZOMBIE_CAPTION: str = "Each dot is one cited charge."
VAMPIRE_CAPTION: str = "Each bite is one cited fee."
PHANTOM_CAPTION: str = "Lit: the fields the detector compares. Each line is one cited row."
DOT: str = "\u00b7"  # the middle dot of "file · row N" and of a row label
SVG_NAMESPACE: str = "http://www.w3.org/2000/svg"
HEARTBEAT_LABEL: str = "Charges of this alert over time, one dot per cited row"
HEARTBEAT_CANCEL_LABEL: str = ", with the cancellation date marked"
BITES_LABEL: str = "Fees of this alert over time, one bar per cited row"
LANTERN_LABEL: str = "Cited rows of this alert; the fields the detector compares are lit"
CANCELLED_WORD: str = "cancelled"

# --- the drawings share one design size (the CSS scales it) -------------------------------------

WIDTH: int = 640  # width of both viewBoxes
# The Home tile draws the heartbeat on a narrower viewBox (same height, same marks). A tile is
# about 240 px wide, so the browser scales that drawing by about 1, where a 640 wide viewBox
# would shrink the dots and the line to about 0.4. Only the design width changes; every mark
# keeps its size, so the line and the dots are at least as thick as on an alert card.
TILE_WIDTH: int = 240
HEIGHT: int = 114  # height of both viewBoxes
LABEL_ROW_A: int = 100  # y of the date labels
LABEL_ROW_B: int = 111  # y of the last label when the two would touch
LABEL_CLEARANCE: int = 36  # a centred date label is about 72 wide: keep half of it inside
LABEL_TOUCH: int = 76  # labels closer than this go on two rows

# heartbeat: taller than the bites, because the tombstone and its word stand above the line
HEART_HEIGHT: int = 166  # height of the heartbeat viewBox
HEART_LABEL_ROW_A: int = 152  # y of the date labels
HEART_LABEL_ROW_B: int = 163  # y of the last label when the two would touch
HEART_MARGIN: int = 28  # space left of the first date and right of the last
HEART_LINE_Y: int = 110  # y of the pulse line
HEART_PULSE: int = 18  # width of the spike before a dot
HEART_SPIKE_RISE: int = 5  # width of the rise of a spike
HEART_SPIKE_FALL: int = 6  # width of the fall of a spike
HEART_SPIKE_UP: int = 28  # the spike jumps this far above the line
HEART_SPIKE_DOWN: int = 14  # then falls this far below the line, then comes back to it
HEART_STACK: int = 9  # vertical step between dots of one date
HEART_STACK_LEVELS: int = 7  # dots of one date before the offsets start again
DOT_RADIUS: float = 5
DOT_AFTER_RADIUS: float = 6.5  # the zombie charges after the cancellation are a little bigger
TOMB_LABEL_Y: int = 11  # y of the word 'cancelled', above the tombstone
TOMB_LABEL_CLEARANCE: int = 64  # the word and the date are about 120 wide: keep half inside
TOMB_TOP: int = 17
TOMB_BASE: int = 67
TOMB_HALF: int = 14  # twice the size of the first version (half width 7, height 25)

# bites
BITES_MARGIN: int = 12
BITES_BASE_Y: int = 84  # y of the baseline
BITES_FULL: int = 64  # height of the tallest bar
BITES_MIN: int = 4  # height of the smallest bar, so a small fee stays visible
BITES_MAX_WIDTH: float = 18.0
BITES_FILL: float = 0.8  # share of a slot a bar fills

_REF_ROW = re.compile(r"^(?P<file>.+):(?P<row>[0-9]+)$")


# --- reading the cited rows ---------------------------------------------------------------------


@dataclass(frozen=True)
class _Mark:
    """One cited row as the drawings use it: its date, its amount and its row label."""

    day: date
    amount: Decimal
    label: str


def _escape(value: object) -> str:
    """Return `value` as HTML text, quotes included."""
    return html.escape(str(value), quote=True)


def _as_date(value: Any) -> date | None:
    """Return a date from a date, a timestamp or an ISO string; None when it is none of these."""
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


def _as_amount(value: Any) -> Decimal | None:
    """Return a finite Decimal from an amount cell, else None."""
    if value is None or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        return None
    return amount if amount.is_finite() else None


def row_label(day: date, amount: Decimal, currency: str = "EUR") -> str:
    """Return '2026-08-31 · 29,99 EUR': date and amount as the Source rows expander shows them."""
    return f"{day.isoformat()} {DOT} {format_amount(amount, currency)}"


def _marks(rows: pd.DataFrame) -> list[_Mark]:
    """Return one mark per drawable cited row in date order (one date keeps the row order)."""
    if rows is None or rows.empty or not {"date", "amount"} <= set(rows.columns):
        return []
    currencies = rows["currency"] if "currency" in rows.columns else ["EUR"] * len(rows)
    marks: list[_Mark] = []
    for day_cell, amount_cell, currency in zip(
        rows["date"], rows["amount"], currencies, strict=True
    ):
        day, amount = _as_date(day_cell), _as_amount(amount_cell)
        if day is None or amount is None:
            continue
        code = currency if isinstance(currency, str) and currency else "EUR"
        marks.append(_Mark(day, amount, row_label(day, amount, code)))
    return sorted(marks, key=lambda mark: mark.day)


# --- chips and the box --------------------------------------------------------------------------


def _chip(ref: str) -> str:
    """Return the chip of one ref: 'file · row N' for 'file:N', the raw ref otherwise."""
    text = str(ref)
    found = _REF_ROW.match(text)
    shown = f"{found['file']} {DOT} row {found['row']}" if found else text
    return f'<span class="gl-ref-chip" title="{_escape(text)}">{_escape(shown)}</span>'


def refs_chips_html(refs: Iterable[str]) -> str:
    """Return one chip per source ref, in order, separated by a space; '' when there is none."""
    return " ".join(_chip(ref) for ref in refs)


def signature_block(inner: str, caption: str) -> str:
    """Wrap one drawing in the gl-signature box with its caption; '' when there is no drawing."""
    if not inner:
        return ""
    return (
        f'<div class="gl-signature">{inner}'
        f'<div class="gl-signature-caption">{_escape(caption)}</div></div>'
    )


# --- shared SVG pieces --------------------------------------------------------------------------


def _svg(css_class: str, label: str, body: str, height: int = HEIGHT, width: int = WIDTH) -> str:
    """Return the one-line <svg> element of a drawing, with its role and its words-only label."""
    return (
        f'<svg class="gl-sig-svg {css_class}" xmlns="{SVG_NAMESPACE}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{_escape(label)}" '
        f'preserveAspectRatio="xMidYMid meet">{body}</svg>'
    )


def _text(x: float, y: int, content: str) -> str:
    """Return one visible text of a drawing, centred on x."""
    return (
        f'<text class="gl-sig-text" x="{x:.1f}" y="{y}" text-anchor="middle">'
        f"{_escape(content)}</text>"
    )


def _date_labels(
    first: date,
    last: date,
    x_first: float,
    x_last: float,
    row_a: int = LABEL_ROW_A,
    row_b: int = LABEL_ROW_B,
    width: int = WIDTH,
) -> str:
    """Return the visible texts of the first and the last cited date (one when they are equal)."""
    low, high = LABEL_CLEARANCE, width - LABEL_CLEARANCE
    x1 = min(max(x_first, low), high)
    x2 = min(max(x_last, low), high)
    if first == last:
        return _text(x1, row_a, first.isoformat())
    row = row_b if x2 - x1 < LABEL_TOUCH else row_a
    return _text(x1, row_a, first.isoformat()) + _text(x2, row, last.isoformat())


def _stack_offset(index: int) -> int:
    """Return the vertical offset of the index-th dot of one date: 0, -9, +9, -18, +18 ..."""
    level = index % HEART_STACK_LEVELS
    step = (level + 1) // 2 * HEART_STACK
    return -step if level % 2 else step


# --- the heartbeat (Zombie) ---------------------------------------------------------------------


def heartbeat_svg(rows: pd.DataFrame, cancellation_date: Any = None, *, width: int = WIDTH) -> str:
    """Return the heartbeat of the cited rows, or '' when no row can be drawn.

    `width` is the design width of the viewBox: ``WIDTH`` on an alert card, ``TILE_WIDTH`` on
    the Home tile. The marks keep their size; only the time line gets shorter.

    One dot per row on a time line from the first to the last cited date, joined by a static pulse
    line. Before each dot the line makes a spike: up 28 units, down 14 below the line, back to it.
    With a cancellation date (a date or an ISO string) a tombstone stands at that date, the
    time line reaches it, and the dots dated after it are brighter. The visible text is the first
    and last cited date and, above the tombstone, the word 'cancelled' with the cancellation date.
    """
    marks = _marks(rows)
    if not marks:
        return ""
    cancel = _as_date(cancellation_date)
    first, last = marks[0].day, marks[-1].day
    start = min(first, cancel) if cancel else first
    end = max(last, cancel) if cancel else last
    left, right = HEART_MARGIN, width - HEART_MARGIN
    span = (end - start).days

    def x_of(day: date) -> float:
        """Place a date on the time line; one single date sits in the middle."""
        if span == 0:
            return width / 2
        return left + (right - left) * (day - start).days / span

    pulse = [f"M8,{HEART_LINE_Y}"]
    cursor = 8.0
    back = HEART_PULSE - HEART_SPIKE_RISE - HEART_SPIKE_FALL
    spike = (
        f"l{HEART_SPIKE_RISE},-{HEART_SPIKE_UP} "
        f"l{HEART_SPIKE_FALL},{HEART_SPIKE_UP + HEART_SPIKE_DOWN} "
        f"l{back},-{HEART_SPIKE_DOWN}"
    )
    for x in sorted({x_of(mark.day) for mark in marks}):
        if x - cursor >= HEART_PULSE:
            pulse.append(f"H{x - HEART_PULSE:.1f} {spike}")
        else:
            pulse.append(f"H{x:.1f}")
        cursor = x
    pulse.append(f"H{width - 8}")
    parts = [f'<path class="gl-sig-line" d="{" ".join(pulse)}"/>']

    seen: dict[date, int] = {}
    for mark in marks:
        index = seen.get(mark.day, 0)
        seen[mark.day] = index + 1
        after = cancel is not None and mark.day > cancel
        css_class = "gl-dot gl-dot-after" if after else "gl-dot"
        radius = DOT_AFTER_RADIUS if after else DOT_RADIUS
        parts.append(
            f'<circle class="{css_class}" cx="{x_of(mark.day):.1f}" '
            f'cy="{HEART_LINE_Y + _stack_offset(index)}" r="{radius}">'
            f"<title>{_escape(mark.label)}</title></circle>"
        )

    label = HEARTBEAT_LABEL
    if cancel is not None:
        label += HEARTBEAT_CANCEL_LABEL
        cx = x_of(cancel)
        top, base, half = TOMB_TOP, TOMB_BASE, TOMB_HALF
        parts.append(
            f'<path class="gl-tomb" d="M{cx - half:.1f},{base} V{top + half} '
            f"a{half},{half} 0 0 1 {2 * half},0 V{base} Z "
            f'M{cx - half - 3:.1f},{base} h{2 * half + 6}"/>'
        )
        word_x = min(max(cx, TOMB_LABEL_CLEARANCE), width - TOMB_LABEL_CLEARANCE)
        parts.append(_text(word_x, TOMB_LABEL_Y, f"{CANCELLED_WORD} {cancel.isoformat()}"))
    parts.append(
        _date_labels(
            first, last, x_of(first), x_of(last), HEART_LABEL_ROW_A, HEART_LABEL_ROW_B, width
        )
    )
    return _svg("gl-heartbeat", label, "".join(parts), HEART_HEIGHT, width)


# --- the bites (Vampire) ------------------------------------------------------------------------


def bites_svg(rows: pd.DataFrame, *, labels: bool = True) -> str:
    """Return the bites of the cited rows, or '' when no row can be drawn.

    One fang-shaped bar per row, in date order, evenly spaced; the height is proportional to the
    amount (the largest cited amount is the full height). The visible text is the first and last
    cited date only; each bar has a title with the date and the amount of its row. With
    ``labels=False`` (the Home tile, where the scaled labels would be unreadable) there is no
    visible text and the viewBox ends under the baseline.
    """
    marks = _marks(rows)
    if not marks:
        return ""
    largest = max(mark.amount for mark in marks)
    slot = (WIDTH - 2 * BITES_MARGIN) / len(marks)
    width = max(2.0, min(slot * BITES_FILL, BITES_MAX_WIDTH))
    parts = [
        f'<line class="gl-sig-line" x1="{BITES_MARGIN}" y1="{BITES_BASE_Y}" '
        f'x2="{WIDTH - BITES_MARGIN}" y2="{BITES_BASE_Y}"/>'
    ]
    centres: list[float] = []
    for index, mark in enumerate(marks):
        height = max(BITES_MIN, scale_to(mark.amount, largest, BITES_FULL))
        x = BITES_MARGIN + slot * index + (slot - width) / 2
        tip = BITES_BASE_Y - height
        bend = tip + height * 0.45
        centres.append(x + width / 2)
        parts.append(
            f'<g class="gl-bite"><title>{_escape(mark.label)}</title>'
            f'<path class="gl-fang" d="M{x:.1f},{BITES_BASE_Y} '
            f"Q{x + width * 0.1:.1f},{bend:.1f} {x + width / 2:.1f},{tip} "
            f'Q{x + width * 0.9:.1f},{bend:.1f} {x + width:.1f},{BITES_BASE_Y} Z"/></g>'
        )
    if not labels:
        return _svg("gl-bites", BITES_LABEL, "".join(parts), BITES_BASE_Y + BITES_MARGIN)
    parts.append(_date_labels(marks[0].day, marks[-1].day, centres[0], centres[-1]))
    return _svg("gl-bites", BITES_LABEL, "".join(parts))


# --- the lantern (Phantom) ----------------------------------------------------------------------


def _cell(value: Any) -> str:
    """Return a table value as text; a missing value is an empty cell."""
    if value is None or value is pd.NA or value is pd.NaT:
        return ""
    if isinstance(value, float) and value != value:
        return ""
    return str(value)


def lantern_html(
    rows: pd.DataFrame,
    lit_columns: Collection[str] | None = None,
    *,
    text_columns: Collection[str] = (),
) -> str:
    """Return the lantern: the cited rows as a table, the compared columns lit, the rest dimmed.

    `rows` holds display strings, already formatted as the page formats its cited rows (an IBAN
    masked). `lit_columns` names the columns to light; names the table lacks are ignored. With
    None, the columns whose values differ between the rows are lit (never `source_ref`), so one
    row lights nothing. The table sits in a box that scrolls sideways. '' when there is no row.
    `text_columns` names the columns of free text: their cells get the class ``gl-wrap``, which
    the Home tile lets wrap between words. Without it the markup is the one of the alert card.
    """
    if rows is None or rows.empty:
        return ""
    names = [str(column) for column in rows.columns]
    body_rows = [[_cell(value) for value in record] for record in rows.itertuples(index=False)]
    if lit_columns is None:
        lit = {
            name
            for index, name in enumerate(names)
            if name != "source_ref" and len({row[index] for row in body_rows}) > 1
        }
    else:
        lit = set(lit_columns) & set(names)

    wrap = set(text_columns)

    def kind(name: str) -> str:
        """Return the class of a column: lit or dim, plus gl-wrap for a free-text column."""
        base = "gl-lit" if name in lit else "gl-dim"
        return f"{base} gl-wrap" if name in wrap else base

    head = "".join(
        f'<th scope="col" class="{kind(name)}">{_escape(name.replace("_", " "))}</th>'
        for name in names
    )
    body = "".join(
        "<tr>"
        + "".join(
            f'<td class="{kind(name)}">{_escape(value)}</td>'
            for name, value in zip(names, row, strict=True)
        )
        + "</tr>"
        for row in body_rows
    )
    return (
        '<div class="gl-lantern-wrap">'
        f'<table class="gl-lantern" aria-label="{_escape(LANTERN_LABEL)}">'
        f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"
    )
