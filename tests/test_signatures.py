"""Tests of the app signatures (spec app-signatures, REQ-AS-01 to 18).

The chips, the heartbeat, the bites and the lantern are pure functions of the cited rows, so they
are tested on small synthetic frames. The honesty test at the end builds the signature of every
alert of the three demos exactly as the apps do and runs the number guard on its text: a computed
figure added to a signature later makes it fail. All data is synthetic.
"""

import ast
import html
import re
from datetime import date
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path

import pandas as pd
import pytest
from judge_path_support import Case, _phantom, cases_of

from apps.phantom_invoices import settings as pi_settings
from apps.phantom_invoices.detectors import LABELS
from ledger_kit.explainer import check_figures
from ledger_kit.ui import signatures, theme
from ledger_kit.ui.reference_app import format_for_display
from ledger_kit.ui.signatures import (
    PHANTOM_CAPTION,
    VAMPIRE_CAPTION,
    ZOMBIE_CAPTION,
    bites_svg,
    heartbeat_svg,
    lantern_html,
    refs_chips_html,
    signature_block,
)
from ledger_kit.utils.money import format_amount, scale_to, sum_amounts

DOT = "\u00b7"
INVENTED_FIGURE = "98765,43 EUR"  # in no demo alert and no demo row
APP_ACCENTS = (theme.ZOMBIE, theme.PHANTOM, theme.VAMPIRE)
CAPTIONS = {"zs": ZOMBIE_CAPTION, "vf": VAMPIRE_CAPTION, "pi": PHANTOM_CAPTION}


# --- helpers -------------------------------------------------------------------------------------


def make_rows(*cells: tuple[str, str]) -> pd.DataFrame:
    """Return ledger-shaped rows from (ISO date, amount) pairs; source_ref numbers them."""
    return pd.DataFrame(
        {
            "source_ref": [f"stmt.csv:{index}" for index in range(len(cells))],
            "date": [date.fromisoformat(day) for day, _amount in cells],
            "amount": [Decimal(amount) for _day, amount in cells],
            "currency": ["EUR"] * len(cells),
        }
    )


def titles(markup: str) -> list[str]:
    """Return the contents of the SVG <title> elements, unescaped, in order."""
    return [html.unescape(text) for text in re.findall(r"<title>(.*?)</title>", markup)]


def visible_texts(markup: str) -> list[str]:
    """Return the contents of the SVG <text> elements, unescaped, in order."""
    return [html.unescape(text) for text in re.findall(r"<text [^>]*>(.*?)</text>", markup)]


def aria_label(markup: str) -> str:
    """Return the first aria-label of a drawing."""
    found = re.search(r'aria-label="([^"]*)"', markup)
    assert found is not None
    return found.group(1)


def signature_text(markup: str) -> str:
    """Return the text of a signature: visible text and SVG titles, no tag and no attribute."""
    spaced = re.sub(r"<[^>]*>", " ", markup)
    return html.unescape(re.sub(r"\s+", " ", spaced)).strip()


class _TableReader(HTMLParser):
    """Read a lantern: the header cells and the body rows as (classes, text) pairs."""

    def __init__(self) -> None:
        super().__init__()
        self.head: list[tuple[str, str]] = []
        self.body: list[list[tuple[str, str]]] = []
        self._row: list[tuple[str, str]] = []
        self._cell: list[str] | None = None
        self._in_head = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "thead":
            self._in_head = True
        elif tag == "tr":
            self._row = []
        elif tag in ("th", "td"):
            self._cell = [dict(attrs).get("class") or "", ""]

    def handle_endtag(self, tag: str) -> None:
        if tag == "thead":
            self._in_head = False
        elif tag in ("th", "td") and self._cell is not None:
            self._row.append((self._cell[0], self._cell[1]))
            self._cell = None
        elif tag == "tr":
            if self._in_head:
                self.head = self._row
            else:
                self.body.append(self._row)

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell[1] += data


def read_table(markup: str) -> _TableReader:
    """Parse the markup of a lantern."""
    reader = _TableReader()
    reader.feed(markup)
    return reader


def lit_names(reader: _TableReader) -> set[str]:
    """Return the header texts of the lit columns."""
    return {text for classes, text in reader.head if "gl-lit" in classes.split()}


FRAME = pd.DataFrame(
    {
        "source_ref": ["invoices.csv:0", "invoices.csv:1"],
        "invoice_number": ["F-2026-0310", "F-2026-0310"],
        "supplier_name": ["Ana García (Asesoría Fiscal)", "Ana García (Asesoría Fiscal)"],
        "total": ["484,00 EUR", "484,00 EUR"],
        "iban": ["****4321", "****9999"],
    }
)


# --- REQ-AS-03: the chips ------------------------------------------------------------------------


def test_a_ref_with_a_known_line_reads_file_dot_line_and_keeps_the_raw_ref_in_the_title() -> None:
    ref = "zombie_demo_statement.csv:181"
    markup = refs_chips_html([ref], {ref: 183})

    assert markup == (
        f'<span class="gl-ref-chip" title="{ref} (line 183 of zombie_demo_statement.csv)">'
        f"zombie_demo_statement.csv {DOT} line 183</span>"
    )


def test_a_csv_ref_without_a_known_line_shows_the_raw_ref_never_the_word_row() -> None:
    ref = "zombie_demo_statement.csv:12"

    for lines in (None, {}, {"other.csv:1": 3}):
        markup = refs_chips_html([ref], lines)

        assert markup == f'<span class="gl-ref-chip" title="{ref}">{ref}</span>'
        assert "row" not in markup


def test_an_xml_ref_without_a_line_reads_file_dot_invoice_and_its_position() -> None:
    ref = "10-duplicate.xml:2"
    markup = refs_chips_html([ref])

    assert markup == (
        f'<span class="gl-ref-chip" title="{ref}">10-duplicate.xml {DOT} invoice 2</span>'
    )
    assert refs_chips_html([ref.replace("xml", "XML")]).count("invoice 2") == 1


def test_an_xml_ref_that_has_a_line_reads_line() -> None:
    ref = "a.xml:1"

    assert f"a.xml {DOT} line 9" in refs_chips_html([ref], {ref: 9})


@pytest.mark.parametrize("ref", ["plain-ref", "file.csv:", "file.csv:1a", "a:b", ""])
def test_a_ref_without_a_row_is_shown_raw(ref: str) -> None:
    assert refs_chips_html([ref]) == f'<span class="gl-ref-chip" title="{ref}">{ref}</span>'


def test_the_line_belongs_to_the_whole_ref_after_the_last_colon() -> None:
    ref = "C:data.csv:7"
    markup = refs_chips_html([ref], {ref: 9})

    assert f"C:data.csv {DOT} line 9" in markup
    assert f'title="{ref} (line 9 of C:data.csv)"' in markup


def test_chip_text_and_title_are_escaped() -> None:
    refs = ["a<b>.csv:3", 'q"x&.csv:4', "plain<i>", "<x>.xml:2"]
    markup = refs_chips_html(refs, {refs[0]: 5, refs[1]: 6})

    assert "<b>" not in markup and "<i>" not in markup and "<x>" not in markup
    assert f"a&lt;b&gt;.csv {DOT} line 5" in markup
    assert 'title="a&lt;b&gt;.csv:3 (line 5 of a&lt;b&gt;.csv)"' in markup
    assert f"q&quot;x&amp;.csv {DOT} line 6" in markup
    assert 'title="plain&lt;i&gt;">plain&lt;i&gt;</span>' in markup
    assert f"&lt;x&gt;.xml {DOT} invoice 2" in markup


def test_one_chip_per_ref_in_the_order_given() -> None:
    markup = refs_chips_html(["f.csv:2", "f.csv:1", "g.csv:0"])

    assert markup.count('class="gl-ref-chip"') == 3
    assert re.findall(r'title="([^"]*)"', markup) == ["f.csv:2", "f.csv:1", "g.csv:0"]


def test_no_chip_shows_the_word_row_next_to_a_number() -> None:
    refs = ["f.csv:2", "g.xml:1", "h.csv:7", "plain"]
    markup = refs_chips_html(refs, {"h.csv:7": 9})

    assert not re.search(r"\brow\s*\d", html.unescape(re.sub(r"<[^>]*>", " ", markup)))


def test_source_lines_of_maps_each_ref_to_its_line_and_skips_missing_lines() -> None:
    frame = pd.DataFrame(
        {
            "source_ref": ["a.csv:0", "a.csv:1", "b.xml:1"],
            "source_line": pd.array([2, 4, None], dtype="Int64"),
        }
    )

    assert signatures.source_lines_of(frame) == {"a.csv:0": 2, "a.csv:1": 4}
    assert signatures.source_lines_of(frame, frame.iloc[:1]) == {"a.csv:0": 2, "a.csv:1": 4}


def test_a_frame_without_source_line_gives_an_empty_map() -> None:
    frame = pd.DataFrame({"source_ref": ["a.csv:0"]})

    assert signatures.source_lines_of(frame) == {}
    assert signatures.source_lines_of(None, pd.DataFrame()) == {}


def test_a_ref_with_its_line_as_markdown() -> None:
    assert signatures.ref_with_line_markdown("a.csv:0", {"a.csv:0": 2}) == "`a.csv:0` (line 2)"
    assert signatures.ref_with_line_markdown("a.csv:0") == "`a.csv:0`"
    assert signatures.ref_with_line_markdown("a.xml:3") == "`a.xml:3` (invoice 3)"


def test_no_refs_give_no_chips() -> None:
    assert refs_chips_html([]) == ""


# --- REQ-AS-01, REQ-AS-02: the box ---------------------------------------------------------------


def test_the_block_wraps_a_drawing_and_ends_with_the_caption_it_is_given() -> None:
    assert signature_block("<svg></svg>", "Each dot is one cited charge.") == (
        '<div class="gl-signature"><svg></svg>'
        '<div class="gl-signature-caption">Each dot is one cited charge.</div></div>'
    )


def test_each_app_has_its_own_caption_and_none_holds_a_figure() -> None:
    assert ZOMBIE_CAPTION == "Each dot is one cited charge."
    assert VAMPIRE_CAPTION == "Each bite is one cited fee."
    assert PHANTOM_CAPTION == "Lit: the fields the detector compares. Each line is one cited row."
    assert not [text for text in CAPTIONS.values() if re.search(r"\d", text)]


def test_the_caption_is_escaped() -> None:
    assert "&lt;b&gt;" in signature_block("<svg></svg>", "<b>")


def test_an_empty_drawing_gives_no_block() -> None:
    assert signature_block("", ZOMBIE_CAPTION) == ""


# --- DN-AS-06: the height of a bar ---------------------------------------------------------------


def test_scale_to_is_proportional_and_rounds_half_up() -> None:
    assert scale_to(Decimal("10"), Decimal("10"), 64) == 64
    assert scale_to(Decimal("5"), Decimal("10"), 64) == 32
    assert scale_to(Decimal("1"), Decimal("3"), 10) == 3
    assert scale_to(Decimal("1"), Decimal("2"), 5) == 3  # 2.5 rounds up


def test_scale_to_is_zero_without_a_positive_maximum_or_value_and_is_capped() -> None:
    assert scale_to(Decimal("5"), Decimal("0"), 64) == 0
    assert scale_to(Decimal("-1"), Decimal("10"), 64) == 0
    assert scale_to(Decimal("0"), Decimal("10"), 64) == 0
    assert scale_to(Decimal("20"), Decimal("10"), 64) == 64
    assert isinstance(scale_to(Decimal("5"), Decimal("10"), 64), int)


# --- REQ-AS-05 to 07, 15: the heartbeat ----------------------------------------------------------

FIVE = (
    ("2026-05-01", "9.99"),
    ("2026-06-01", "9.99"),
    ("2026-07-01", "9.99"),
    ("2026-08-01", "9.99"),
    ("2026-09-01", "14.99"),
)


def test_heartbeat_dots_equal_the_cited_rows_in_date_order() -> None:
    svg = heartbeat_svg(make_rows(*FIVE))

    assert len(re.findall(r'<circle class="gl-dot', svg)) == 5
    xs = [float(x) for x in re.findall(r'<circle class="[^"]*" cx="([0-9.]+)"', svg)]
    assert xs == sorted(xs) and len(set(xs)) == 5
    assert xs[0] == 28.0 and xs[-1] == 612.0  # from the first to the last cited date
    assert titles(svg)[0] == f"2026-05-01 {DOT} 9,99 EUR"


def test_heartbeat_sorts_rows_by_date() -> None:
    svg = heartbeat_svg(make_rows(*reversed(FIVE)))

    assert [title[:10] for title in titles(svg)] == [day for day, _amount in FIVE]


def test_heartbeat_with_one_row_has_one_dot_in_the_middle_and_one_date() -> None:
    svg = heartbeat_svg(make_rows(("2026-05-01", "9.99")))

    assert re.findall(r'<circle class="[^"]*" cx="([0-9.]+)"', svg) == ["320.0"]
    assert visible_texts(svg) == ["2026-05-01"]


def test_heartbeat_rows_of_one_date_stack_instead_of_hiding_each_other() -> None:
    svg = heartbeat_svg(make_rows(("2026-05-01", "9.99"), ("2026-05-01", "9.99")))

    assert len(re.findall(r'<circle class="gl-dot', svg)) == 2
    assert len(set(re.findall(r'cy="([0-9.]+)"', svg))) == 2


def test_heartbeat_has_no_tombstone_and_no_bright_dot_without_a_cancellation_date() -> None:
    svg = heartbeat_svg(make_rows(*FIVE))

    assert "gl-tomb" not in svg and "gl-dot-after" not in svg and "cancelled" not in svg


def test_heartbeat_marks_the_dots_after_the_cancellation_date() -> None:
    svg = heartbeat_svg(make_rows(*FIVE), "2026-07-15")

    assert 'class="gl-tomb"' in svg
    assert svg.count("gl-dot-after") == 2  # 2026-08-01 and 2026-09-01
    after = re.findall(r'<circle class="gl-dot gl-dot-after"[^>]*><title>(.*?)</title>', svg)
    assert [title[:10] for title in after] == ["2026-08-01", "2026-09-01"]


def test_heartbeat_does_not_mark_a_dot_on_the_cancellation_date_itself() -> None:
    svg = heartbeat_svg(make_rows(*FIVE), date(2026, 8, 1))  # a date is accepted as well

    assert svg.count("gl-dot-after") == 1


def test_heartbeat_reaches_a_cancellation_date_before_the_first_cited_date() -> None:
    svg = heartbeat_svg(make_rows(*FIVE), "2026-04-01")

    assert 'class="gl-tomb" d="M14.0,67' in svg  # the tombstone stands at the left end
    assert svg.count("gl-dot-after") == 5
    assert float(re.findall(r'<circle class="[^"]*" cx="([0-9.]+)"', svg)[0]) > 28.0


def test_heartbeat_draws_the_tombstone_when_the_cancellation_is_after_the_last_row() -> None:
    svg = heartbeat_svg(make_rows(*FIVE), "2026-10-01")

    assert 'class="gl-tomb"' in svg and "gl-dot-after" not in svg
    assert 'text-anchor="middle">cancelled 2026-10-01' in svg


def test_heartbeat_spike_before_each_dot_goes_up_28_down_to_14_below_and_back() -> None:
    svg = heartbeat_svg(make_rows(*FIVE))

    line = re.search(r'class="gl-sig-line" d="([^"]*)"', svg)
    assert line is not None
    spikes = re.findall(r"l(\d+),(-?\d+) l(\d+),(-?\d+) l(\d+),(-?\d+)", line.group(1))
    assert len(spikes) == 5  # one before each of the five dots
    for _w1, up, _w2, down, _w3, back in spikes:
        assert (int(up), int(down), int(back)) == (-28, 42, -14)  # net 0: back on the line


def test_heartbeat_tombstone_is_twice_its_first_size_with_the_word_above_it() -> None:
    svg = heartbeat_svg(make_rows(*FIVE), "2026-07-15")

    tomb = re.search(r'class="gl-tomb" d="M([0-9.]+),(\d+) V(\d+) a14,14 0 0 1 28,0 V(\d+)', svg)
    assert tomb is not None
    _x, base, shoulder, _end = (float(value) for value in tomb.groups())
    assert base - (shoulder - 14) == 50  # 50 units high and 28 wide: twice 25 by 14
    word = re.search(r'<text [^>]*y="(\d+)"[^>]*>cancelled 2026-07-15</text>', svg)
    assert word is not None and int(word.group(1)) < shoulder - 14  # above the top of the arch


def test_heartbeat_keeps_the_word_and_the_tombstone_inside_the_drawing_at_both_ends() -> None:
    for cancel in ("2026-04-01", "2026-10-01"):
        svg = heartbeat_svg(make_rows(*FIVE), cancel)
        word_x = float(re.search(r'x="([0-9.]+)"[^>]*>cancelled', svg).group(1))
        left_edge = float(re.search(r'class="gl-tomb" d="M([0-9.]+),', svg).group(1))

        assert 60 <= word_x <= 580 and left_edge >= 0 and left_edge + 28 <= 640


def test_heartbeat_ignores_a_cancellation_date_that_is_not_a_date() -> None:
    svg = heartbeat_svg(make_rows(*FIVE), "not-a-date")

    assert "gl-tomb" not in svg and "cancelled" not in svg


def test_heartbeat_visible_text_is_the_first_and_last_date_and_the_cancellation() -> None:
    plain = heartbeat_svg(make_rows(*FIVE))
    cancelled = heartbeat_svg(make_rows(*FIVE), "2026-07-15")

    assert visible_texts(plain) == ["2026-05-01", "2026-09-01"]
    assert sorted(visible_texts(cancelled)) == sorted(
        ["2026-05-01", "2026-09-01", "cancelled 2026-07-15"]
    )


def test_heartbeat_titles_are_the_date_and_amount_of_the_source_rows_expander() -> None:
    rows = make_rows(("2026-08-31", "1234.5"), ("2026-09-30", "29.99"))
    shown = format_for_display(rows)
    expected = [
        f"{day} {DOT} {amount}" for day, amount in zip(shown["date"], shown["amount"], strict=True)
    ]

    assert titles(heartbeat_svg(rows)) == expected
    assert expected == [f"2026-08-31 {DOT} 1.234,50 EUR", f"2026-09-30 {DOT} 29,99 EUR"]


def test_heartbeat_has_a_role_and_a_label_in_words() -> None:
    svg = heartbeat_svg(make_rows(*FIVE), "2026-07-15")

    assert 'role="img"' in svg
    assert aria_label(svg).startswith("Charges of this alert over time, one dot per cited row")
    assert not re.search(r"\d", aria_label(svg))


def test_heartbeat_leaves_out_a_row_that_cannot_be_drawn() -> None:
    rows = pd.DataFrame(
        {"date": [date(2026, 5, 1), None], "amount": [Decimal("1.00"), Decimal("2.00")]}
    )

    assert len(re.findall(r'<circle class="gl-dot', heartbeat_svg(rows))) == 1


def test_heartbeat_gives_nothing_for_no_rows() -> None:
    assert heartbeat_svg(make_rows()) == ""
    assert heartbeat_svg(pd.DataFrame()) == ""


# --- REQ-AS-08 to 10, 15: the bites --------------------------------------------------------------

FANG = re.compile(
    r'class="gl-fang" d="M([0-9.]+),84 Q[0-9.]+,[0-9.]+ ([0-9.]+),([0-9.]+) '
    r'Q[0-9.]+,[0-9.]+ ([0-9.]+),84 Z"'
)


def daily_rows(count: int) -> pd.DataFrame:
    """Return `count` rows, one per day from 2026-01-01, with amounts that vary."""
    first = date(2026, 1, 1).toordinal()
    return make_rows(
        *((date.fromordinal(first + i).isoformat(), f"{1 + i % 9}.50") for i in range(count))
    )


def test_bites_bars_equal_the_cited_rows() -> None:
    rows = make_rows(("2026-01-05", "3.00"), ("2026-02-05", "3.00"), ("2026-03-05", "3.00"))

    svg = bites_svg(rows)

    assert len(FANG.findall(svg)) == 3 and svg.count('<g class="gl-bite">') == 3


def test_bites_height_is_proportional_to_the_amount() -> None:
    rows = make_rows(("2026-01-05", "10.00"), ("2026-02-05", "5.00"), ("2026-03-05", "2.50"))

    tips = [float(tip) for _x, _ax, tip, _end in FANG.findall(bites_svg(rows))]

    assert tips == [20.0, 52.0, 68.0]  # heights 64, 32 and 16 above the baseline at 84


def test_bites_a_tiny_amount_keeps_a_visible_bar() -> None:
    rows = make_rows(("2026-01-05", "100.00"), ("2026-02-05", "0.01"))

    tips = [float(tip) for _x, _ax, tip, _end in FANG.findall(bites_svg(rows))]

    assert tips == [20.0, 80.0]


@pytest.mark.parametrize("count", [1, 2, 45])
def test_bites_stay_inside_the_drawing_and_apart(count: int) -> None:
    svg = bites_svg(daily_rows(count))

    bars = [(float(x), float(end)) for x, _ax, _tip, end in FANG.findall(svg)]
    assert len(bars) == count
    assert all(0 <= start and end <= 640 for start, end in bars)
    assert all(bars[i][1] < bars[i + 1][0] for i in range(count - 1))  # none hides another
    if count == 45:
        assert all(end - start >= 8 for start, end in bars)  # still readable


def test_bites_for_45_rows_have_one_title_per_row_and_two_dates() -> None:
    rows = daily_rows(45)
    svg = bites_svg(rows)

    shown = format_for_display(rows)
    expected = [
        f"{day} {DOT} {amount}" for day, amount in zip(shown["date"], shown["amount"], strict=True)
    ]
    assert titles(svg) == expected
    assert visible_texts(svg) == ["2026-01-01", "2026-02-14"]


def test_bites_visible_text_is_one_date_for_one_date() -> None:
    svg = bites_svg(make_rows(("2026-01-05", "3.00"), ("2026-01-05", "4.00")))

    assert visible_texts(svg) == ["2026-01-05"]


def test_bites_sort_rows_by_date_and_show_no_computed_figure() -> None:
    svg = bites_svg(make_rows(("2026-03-05", "3.00"), ("2026-01-05", "4.00")))

    assert [title[:10] for title in titles(svg)] == ["2026-01-05", "2026-03-05"]
    assert visible_texts(svg) == ["2026-01-05", "2026-03-05"]  # the two dates, no sum, no count


def test_bites_have_a_role_and_a_label_in_words() -> None:
    svg = bites_svg(daily_rows(3))

    assert 'role="img"' in svg
    assert aria_label(svg) == "Fees of this alert over time, one bar per cited row"
    assert not re.search(r"\d", aria_label(svg))


def test_bites_give_nothing_for_no_rows() -> None:
    assert bites_svg(make_rows()) == "" and bites_svg(pd.DataFrame()) == ""


# --- REQ-AS-11 to 14: the lantern ----------------------------------------------------------------


def test_the_lantern_lights_the_mapped_columns_and_dims_the_others() -> None:
    reader = read_table(lantern_html(FRAME, ("invoice_number", "total")))

    assert lit_names(reader) == {"invoice number", "total"}
    for row in reader.body:
        classes = [cls for cls, _text in row]
        assert classes == [
            "gl-dim" if name not in ("invoice_number", "total") else "gl-lit"
            for name in FRAME.columns
        ]


def test_the_lantern_shows_the_values_as_given() -> None:
    reader = read_table(lantern_html(FRAME, ("total",)))

    assert [[text for _cls, text in row] for row in reader.body] == FRAME.values.tolist()
    assert [text for _cls, text in reader.head][:2] == ["source ref", "invoice number"]


def test_the_lantern_ignores_a_mapped_name_the_table_lacks() -> None:
    reader = read_table(lantern_html(FRAME, ("total", "no_such_column")))

    assert lit_names(reader) == {"total"}


def test_the_lantern_with_an_empty_mapping_lights_nothing() -> None:
    assert lit_names(read_table(lantern_html(FRAME, ()))) == set()


def test_an_unmapped_detector_lights_the_columns_that_differ() -> None:
    reader = read_table(lantern_html(FRAME, None))

    assert lit_names(reader) == {"iban"}  # not source_ref, which always differs


def test_one_row_lights_nothing_when_nothing_is_mapped() -> None:
    assert lit_names(read_table(lantern_html(FRAME.iloc[:1], None))) == set()


def test_the_lantern_escapes_cells_and_headers() -> None:
    frame = pd.DataFrame({'a<b "c"': ["<script>x</script>"], "source_ref": ["f.csv:0&1"]})

    markup = lantern_html(frame, None)

    assert "<script>" not in markup and "&lt;script&gt;x&lt;/script&gt;" in markup
    assert "a&lt;b &quot;c&quot;" in markup and "f.csv:0&amp;1" in markup


def test_the_lantern_shows_a_missing_value_as_an_empty_cell() -> None:
    frame = pd.DataFrame({"source_ref": ["f.csv:0"], "total": [None], "iban": [float("nan")]})

    reader = read_table(lantern_html(frame, None))

    assert [text for _cls, text in reader.body[0]] == ["f.csv:0", "", ""]


def test_the_lantern_sits_in_a_box_that_scrolls_sideways() -> None:
    markup = lantern_html(FRAME, ("total",))

    assert markup.startswith('<div class="gl-lantern-wrap"><table class="gl-lantern"')
    assert ".gl-lantern-wrap { max-width: 100%; overflow-x: auto; }" in theme.BASE_CSS


def test_the_lantern_gives_nothing_for_no_rows() -> None:
    assert lantern_html(FRAME.iloc[0:0], None) == "" and lantern_html(pd.DataFrame(), None) == ""


def test_the_mapping_covers_the_four_phantom_detectors_with_known_columns() -> None:
    assert set(pi_settings.LANTERN_COLUMNS) == set(LABELS)
    for columns in pi_settings.LANTERN_COLUMNS.values():
        assert columns and set(columns) <= set(pi_settings.LANTERN_ORDER)


def test_the_lit_columns_of_an_alert_come_from_its_detector_and_fall_back_to_none() -> None:
    alert = cases_of("pi")[0].alert

    assert pi_settings.lantern_lit_columns(alert) == pi_settings.LANTERN_COLUMNS[alert.detector]
    other = alert.model_copy(update={"detector": "pi.unknown"})
    assert pi_settings.lantern_lit_columns(other) is None


def test_the_lantern_rows_follow_the_cited_refs_of_each_demo_alert() -> None:
    pipeline = _phantom()

    for case in cases_of("pi"):
        view = pi_settings.lantern_view(case.alert, pipeline)
        assert list(view["source_ref"]) == list(case.alert.source_refs)


def test_the_lantern_shows_only_the_ref_the_number_and_the_lit_columns_in_mapping_order() -> None:
    pipeline = _phantom()

    for case in cases_of("pi"):
        alert = case.alert
        view = pi_settings.lantern_view(alert, pipeline)
        mapped = pi_settings.LANTERN_COLUMNS[alert.detector]
        naming = [] if "invoice_number" in mapped else ["invoice_number"]
        # the line of the file sits right after the source ref (REQ-AS-23)
        allowed = ["source_ref", "source_line", *naming, *mapped]
        # nothing else, in that order; a column with no value in any cited row is left out
        assert list(view.columns) == [c for c in allowed if c in view.columns], alert.id
        assert view.columns[0] == "source_ref"
        assert view.columns[1] == "source_line"  # every cited row of the demo is in a CSV file


def test_the_invoice_number_names_the_invoice_rows_of_every_demo_lantern() -> None:
    pipeline = _phantom()

    for case in cases_of("pi"):
        view = pi_settings.lantern_view(case.alert, pipeline)
        invoice_rows = view[view["source_ref"].str.startswith("invoices")]
        if not invoice_rows.empty:
            assert "invoice_number" in view.columns and all(invoice_rows["invoice_number"])


def test_an_unmapped_detector_shows_the_ref_the_number_and_the_differing_columns() -> None:
    pipeline = _phantom()
    case = next(c for c in cases_of("pi") if c.alert.detector == "pi.vat_error")
    alert = case.alert.model_copy(update={"detector": "pi.unknown"})

    view = pi_settings.lantern_view(alert, pipeline)

    assert list(view.columns[:3]) == ["source_ref", "source_line", "invoice_number"]
    assert pi_settings.lantern_lit_columns(alert) is None
    for column in view.columns[3:]:
        assert len(set(view[column])) > 1  # only the columns whose values differ


def test_the_lantern_of_the_demo_alerts_lights_what_the_detector_compares() -> None:
    pipeline = _phantom()

    for case in cases_of("pi"):
        alert = case.alert
        view = pi_settings.lantern_view(alert, pipeline)
        reader = read_table(lantern_html(view, pi_settings.lantern_lit_columns(alert)))
        expected = set(pi_settings.LANTERN_COLUMNS[alert.detector]) & set(view.columns)
        assert lit_names(reader) == {name.replace("_", " ") for name in expected}
        assert lit_names(reader)  # at least one lit column on every demo alert


def test_no_full_iban_is_in_the_lantern_and_the_masked_form_is_where_it_is_compared() -> None:
    pipeline = _phantom()
    full = {
        re.sub(r"\s+", "", str(iban)).upper()
        for frame in (pipeline.invoices, pipeline.suppliers, pipeline.payments)
        if "iban" in frame.columns
        for iban in frame["iban"]
        if isinstance(iban, str) and iban.strip()
    }
    assert full  # the demo does carry IBANs

    for case in cases_of("pi"):
        view = pi_settings.lantern_view(case.alert, pipeline)
        markup = lantern_html(view, pi_settings.lantern_lit_columns(case.alert))
        squeezed = re.sub(r"\s+", "", markup).upper()
        assert not [iban for iban in full if iban in squeezed], case.alert.id
        if case.alert.detector == "pi.iban_change":
            cells = [cell for cell in view["iban"] if cell]
            assert cells and all(re.fullmatch(r"\*{4}\w{4}", cell) for cell in cells)
        else:
            assert "iban" not in view.columns


# --- REQ-AS-17, REQ-AS-18: the look and the boundaries ------------------------------------------


@pytest.mark.parametrize("accent", APP_ACCENTS, ids=lambda accent: accent.key)
def test_the_css_of_the_signatures_is_in_the_page_style_and_wears_the_accent(
    accent: theme.Accent,
) -> None:
    css = theme.theme_css(accent)

    for rule in (
        ".stApp .gl-signature {",
        ".stApp .gl-signature-caption",
        ".stApp .gl-ref-chip {",
        ".stApp .gl-dot-after {",
        ".stApp .gl-fang {",
        ".stApp .gl-lantern-wrap",
        "table.gl-lantern td.gl-lit",
        "table.gl-lantern .gl-dim",
    ):
        assert rule in css, rule
    assert f"--gl-accent: {accent.color};" in css
    assert ".stApp .gl-dot { fill: var(--gl-accent);" in css
    assert "rgba(var(--gl-accent-rgb)" in css


def test_the_signatures_adapt_to_800_pixels() -> None:
    css = theme.theme_css(theme.PHANTOM)
    narrow = css[css.index("@media (max-width: 800px)") :]

    assert ".gl-signature" in narrow and "table.gl-lantern" in narrow
    assert "overflow-x: auto" in css  # the drawing and the lantern scroll inside their box


def test_the_signature_fills_the_card_width_and_keeps_its_minimum_width() -> None:
    css = theme.BASE_CSS
    rule = css[css.index(".stApp .gl-signature svg.gl-sig-svg {") :].split("}", 1)[0]

    assert "width: 100%;" in rule and "min-width: 30rem;" in rule
    assert "max-width" not in rule  # no cap: on a wide card the drawing fills it


def test_the_module_imports_no_streamlit_and_no_theme() -> None:
    tree = ast.parse(Path(signatures.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    assert not [name for name in imported if name.split(".")[0] == "streamlit"]
    assert "ledger_kit.ui.theme" not in imported
    assert not [name for name in imported if name.split(".")[0] in ("apps", "openai", "urllib")]


# --- REQ-AS-16: the honesty test over the three demos --------------------------------------------


def build_signature(case: Case) -> str:
    """Return the signature of a demo alert exactly as its app draws it."""
    alert = case.alert
    if case.prefix == "zs":
        inner = heartbeat_svg(case.rows, alert.data.get("cancellation_date"))
    elif case.prefix == "vf":
        inner = bites_svg(case.rows)
    else:
        lantern = pi_settings.lantern_view(alert, _phantom())
        inner = lantern_html(lantern, pi_settings.lantern_lit_columns(alert))
    return signature_block(inner, CAPTIONS[case.prefix])


def with_lines(case: Case) -> tuple[pd.DataFrame, tuple[str, ...] | None]:
    """Return the rows and columns the guard may read for a signature: the cited rows' lines too.

    A lantern shows the line of the file where each cited row starts. That number is where the
    row stands in the loaded file, copied from the cited row, so the check lets it through. It is
    never sent to a model: only this test adds it, the explainer's whitelist is untouched.
    """
    if case.prefix != "pi":
        return case.rows, case.columns
    pipeline = _phantom()
    lines = signatures.source_lines_of(pipeline.invoices, pipeline.suppliers, pipeline.payments)
    rows = case.rows.assign(source_line=[lines.get(str(ref)) for ref in case.rows["source_ref"]])
    return rows, (*(case.columns or ()), "source_line")


@pytest.mark.parametrize("prefix", ["zs", "pi", "vf"])
def test_every_demo_alert_has_a_signature_that_passes_the_number_guard(prefix: str) -> None:
    cases = cases_of(prefix)
    assert cases
    failures = []
    for case in cases:
        markup = build_signature(case)
        assert markup.startswith('<div class="gl-signature">'), case.alert.id
        rows, columns = with_lines(case)
        passed, rejected = check_figures(signature_text(markup), case.alert, rows, columns)
        if not passed:
            failures.append((case.alert.detector, case.alert.id, rejected))
    assert failures == []


@pytest.mark.parametrize("prefix", ["zs", "vf"])
def test_the_text_of_a_drawing_is_one_row_label_per_cited_row(prefix: str) -> None:
    for case in cases_of(prefix):
        text = signature_text(build_signature(case))

        assert text.count("EUR") == len(case.rows), case.alert.id
        assert text.endswith(CAPTIONS[prefix])


def test_the_demo_has_the_alerts_the_task_describes() -> None:
    zs = cases_of("zs")
    cancelled = [case for case in zs if "cancellation_date" in case.alert.data]

    assert (len(zs), len(cases_of("pi")), len(cases_of("vf"))) == (19, 9, 6)
    [case] = cancelled
    markup = build_signature(case)
    assert 'class="gl-tomb"' in markup and "gl-dot-after" in markup
    assert f"cancelled {case.alert.data['cancellation_date']}" in signature_text(markup)
    assert sum("gl-tomb" in build_signature(c) for c in zs) == 1
    [summary] = [c for c in cases_of("vf") if c.alert.detector == "vf.fee_summary"]
    assert len(FANG.findall(build_signature(summary))) == len(summary.rows) == 45


def test_an_invented_figure_added_to_a_signature_fails_the_guard() -> None:
    case = cases_of("vf")[0]
    text = signature_text(build_signature(case))

    assert check_figures(text, case.alert, case.rows, case.columns) == (True, ())
    passed, rejected = check_figures(
        f"{text} {INVENTED_FIGURE}", case.alert, case.rows, case.columns
    )
    assert not passed and rejected


def test_a_sum_of_the_cited_amounts_added_to_a_signature_fails_the_guard() -> None:
    failed = 0
    checked = 0
    for case in [*cases_of("zs"), *cases_of("vf")]:
        if len(case.rows) < 2:
            continue
        total = sum_amounts(Decimal(str(amount)) for amount in case.rows["amount"])
        text = f"{signature_text(build_signature(case))} {format_amount(total, 'EUR')}"
        passed, _rejected = check_figures(text, case.alert, case.rows, case.columns)
        checked += 1
        failed += not passed
    # a sum that an alert states itself (a total field) is an attributed figure and may pass;
    # every other sum is a computed figure and must be rejected
    assert checked > 0 and failed > 0


# --- REQ-AS-40: a short Source refs line on the card ---------------------------------------------


def _refs(count: int) -> list[str]:
    """Return `count` synthetic refs of one file."""
    return [f"stmt.csv:{index}" for index in range(count)]


def test_six_refs_give_six_chips_and_no_more_line() -> None:
    markup = signatures.card_chips_html(_refs(6))

    assert signatures.CARD_MAX_CHIPS == 6
    assert markup.count('class="gl-ref-chip"') == 6
    assert "gl-card-more" not in markup


def test_seven_refs_give_six_chips_and_the_line_with_one_row() -> None:
    markup = signatures.card_chips_html(_refs(7))

    assert markup.count('class="gl-ref-chip"') == 6
    assert (
        '<div class="gl-card-more">and 1 more cited row, all in Source rows below</div>' in markup
    )


def test_forty_five_refs_give_six_chips_and_thirty_nine_more_rows() -> None:
    markup = signatures.card_chips_html(_refs(45))

    assert markup.count('class="gl-ref-chip"') == 6
    assert "and 39 more cited rows, all in Source rows below" in markup
    assert markup.endswith("</div>") and markup.count("gl-card-more") == 1


def test_the_card_chips_keep_the_order_of_the_refs() -> None:
    refs = ["z.csv:9", "a.csv:1", "m.csv:5", "b.csv:2", "c.csv:3", "d.csv:4", "e.csv:6"]

    markup = signatures.card_chips_html(refs)

    assert re.findall(r'title="([^"]*)"', markup) == refs[:6]
    assert "e.csv:6" not in markup


def test_a_card_chip_with_a_known_line_shows_the_file_and_the_line() -> None:
    markup = signatures.card_chips_html(["a.csv:3", *_refs(7)], {"a.csv:3": 5})

    assert f"a.csv {DOT} line 5" in markup
    assert 'title="a.csv:3 (line 5 of a.csv)"' in markup


def test_a_card_chip_with_markup_is_escaped() -> None:
    markup = signatures.card_chips_html(["<b>x</b>.csv:1"])

    assert "<b>" not in markup and "&lt;b&gt;x&lt;/b&gt;.csv:1" in markup


def test_no_refs_give_an_empty_card_line() -> None:
    assert signatures.card_chips_html([]) == ""


@pytest.mark.parametrize("folder", ["zombie_subscriptions", "vampire_fees"])
def test_the_zombie_and_vampire_cards_call_card_chips_html_and_keep_source_rows(
    folder: str,
) -> None:
    path = Path(signatures.__file__).resolve().parents[2] / "apps" / folder / "app.py"
    source = path.read_text(encoding="utf-8")

    assert "card_chips_html(alert.source_refs" in source
    assert "refs_chips_html" not in source
    assert 'st.expander(f"Source rows ({len(alert.source_refs)})")' in source
