"""What a person reads when a citation points at a file (spec app-signatures, REQ-AS-25 to 32).

The chips, the Source rows tables, the lists of refs, the lantern and the quarantine tables show
the line of the file where a cited record starts (`source_line`), never the internal row number.
``AppTest`` runs each app alone with its demo data; the pure helpers are called directly. Nothing
reads the network or the clock; all data is synthetic.
"""

import html
import re
from collections.abc import Iterator
from functools import cache

import pandas as pd
import pytest
from judge_path_support import ROOT, SCRIPTS, cases_of
from streamlit.testing.v1 import AppTest

from apps import home_tiles
from apps.phantom_invoices import settings as pi_settings
from apps.zombie_subscriptions.app import _refs_markdown
from ledger_kit.detectors import _restore_registry, _snapshot_registry
from ledger_kit.ui.reference_app import DISPLAY_COLUMNS, format_for_display, quarantine_table
from ledger_kit.ui.signatures import refs_chips_html, source_lines_of

TIMEOUT_SECONDS = 120
DOT = "\u00b7"
GYMPLUS_REF = "zombie_demo_statement.csv:181"
CHIP = re.compile(r'<span class="gl-ref-chip" title="([^"]*)">([^<]*)</span>')
LINE_CHIP = re.compile(rf"\S+ {DOT} line \d+")
ROW_NEXT_TO_NUMBER = re.compile(r"\brow\s*\d")


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Snapshot and restore the detector registry; no key, so explanations are the templates."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    snapshot = _snapshot_registry()
    try:
        yield
    finally:
        _restore_registry(snapshot)


@cache
def _page(prefix: str) -> tuple[tuple[str, ...], tuple[pd.DataFrame, ...]]:
    """Run one app alone, click Load demo data and keep its markdown and its tables."""
    at = AppTest.from_file(str(ROOT / SCRIPTS[prefix]), default_timeout=TIMEOUT_SECONDS)
    at.run()
    at.button(key=f"{prefix}_load_demo").click().run()
    assert not at.exception
    return (
        tuple(element.value for element in at.markdown),
        tuple(frame.value for frame in at.dataframe),
    )


def _chips(markdown: tuple[str, ...]) -> list[tuple[str, str]]:
    """Return (title, text) of every ref chip of a page, unescaped."""
    return [
        (html.unescape(title), html.unescape(text))
        for value in markdown
        for title, text in CHIP.findall(value)
    ]


def _text_lines(relative: str) -> list[str]:
    """Return a committed sample file as the lines an editor shows (index 0 is line 1)."""
    data = (ROOT / relative).read_bytes()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    return text.replace("\r\n", "\n").split("\n")


def _is_xml(ref: str) -> bool:
    """True when a source_ref names a position in an XML file."""
    return ref.rpartition(":")[0].lower().endswith(".xml")


# --- the GYMPLUS card ---


def test_the_gymplus_chip_reads_file_dot_line_183_with_the_raw_ref_in_its_title() -> None:
    markdown, _frames = _page("zs")

    lines = [value for value in markdown if value.startswith("**Source refs:**")]
    gym = [value for value in lines if f'title="{GYMPLUS_REF} (line 183 of ' in value]

    assert gym, "no card cites the GYMPLUS charge"
    for value in gym:
        assert f"zombie_demo_statement.csv {DOT} line 183" in html.unescape(value)
        assert not ROW_NEXT_TO_NUMBER.search(html.unescape(value))
    assert any(GYMPLUS_REF in case.alert.source_refs for case in cases_of("zs"))


def test_the_gymplus_source_rows_table_has_the_line_right_after_the_ref() -> None:
    _markdown, frames = _page("zs")

    tables = [
        frame
        for frame in frames
        if "source_ref" in frame.columns and GYMPLUS_REF in set(frame["source_ref"])
    ]

    assert tables
    for table in tables:
        assert list(table.columns[:2]) == ["source_ref", "source_line"]
        assert table[table["source_ref"] == GYMPLUS_REF].iloc[0]["source_line"] == "183"
    assert (
        _text_lines("data/samples/zombie_demo_statement.csv")[183 - 1].upper().count("GYMPLUS") >= 1
    )


def test_the_display_columns_put_source_line_right_after_source_ref() -> None:
    assert DISPLAY_COLUMNS[:2] == ("source_ref", "source_line")


def test_the_source_rows_table_shows_an_empty_cell_when_a_row_has_no_line() -> None:
    rows = pd.DataFrame(
        {
            "source_ref": ["a.csv:0", "b.xml:1"],
            "source_line": pd.array([2, None], dtype="Int64"),
            "date": [pd.Timestamp("2026-01-15").date()] * 2,
            "amount": ["1.00", "2.00"],
            "flow": ["debit", "debit"],
            "counterparty": ["Ana García", "Luigi Rossi"],
            "description": ["x", "y"],
            "iban": [None, None],
        }
    )

    shown = format_for_display(rows)

    assert list(shown["source_line"]) == ["2", ""]
    assert "source_line" not in format_for_display(rows.drop(columns="source_line")).columns


# --- the chips of the three pages ---


@pytest.mark.parametrize("prefix", sorted(SCRIPTS))
def test_every_chip_of_a_page_reads_line_and_none_reads_row(prefix: str) -> None:
    markdown, _frames = _page(prefix)

    chips = _chips(markdown)

    assert chips
    for title, text in chips:
        assert LINE_CHIP.fullmatch(text), (title, text)  # the demo files are CSV
        assert title.startswith(text.split(f" {DOT} ")[0] + ":"), (title, text)
        assert "(line " in title
    assert not [text for _title, text in chips if ROW_NEXT_TO_NUMBER.search(text)]


def test_the_home_tiles_show_chips_with_the_line_and_no_chip_with_row() -> None:
    at = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=TIMEOUT_SECONDS).run()
    assert not at.exception
    [tiles] = [
        element.value
        for element in at.markdown
        if element.value.startswith('<div class="gl-grid gl-tiles">')
    ]

    chips = [(html.unescape(t), html.unescape(x)) for t, x in CHIP.findall(tiles)]

    assert len(chips) >= 3  # at least one chip on each tile
    for title, text in chips:
        assert LINE_CHIP.fullmatch(text), (title, text)
        assert not ROW_NEXT_TO_NUMBER.search(text) and not ROW_NEXT_TO_NUMBER.search(title)


def test_a_tile_gives_every_chip_the_map_and_keeps_the_count_of_the_rest() -> None:
    refs = ["a.csv:1", "a.csv:2", "a.csv:3", "a.csv:4"]

    markup = home_tiles.tile_refs_html(refs, {"a.csv:1": 3, "a.csv:2": 4, "a.csv:3": 5})

    assert markup.count('class="gl-ref-chip"') == home_tiles.TILE_MAX_CHIPS == 3
    assert f"a.csv {DOT} line 3" in markup and f"a.csv {DOT} line 5" in markup
    assert '<div class="gl-tile-more">and 1 more cited row</div>' in markup
    # without the map nothing claims a line
    plain = home_tiles.tile_refs_html(refs)
    assert "line" not in plain.replace("gl-tile-more", "") and ">a.csv:1<" in plain


# --- the lists of refs ---


@pytest.mark.parametrize("prefix", ["zs", "vf"])
def test_the_tombstone_and_coffin_lists_of_refs_show_the_line_next_to_each_ref(
    prefix: str,
) -> None:
    markdown, _frames = _page(prefix)
    pattern = re.compile(r"(`[^`]+:\d+` \(line \d+\)(, )?)+")

    listed = [value for value in markdown if pattern.fullmatch(value)]

    assert listed, prefix


def test_a_ref_list_shows_the_line_only_when_it_is_known() -> None:
    lines = {"a.csv:0": 2, "a.csv:4": 6}

    assert _refs_markdown(["a.csv:0", "a.csv:4", "a.csv:9"], lines) == (
        "`a.csv:0` (line 2), `a.csv:4` (line 6), `a.csv:9`"
    )
    assert _refs_markdown(["a.csv:0"]) == "`a.csv:0`"


# --- the lantern and the tables of Phantom Invoices ---


def test_the_lantern_of_every_csv_alert_has_the_line_right_after_the_ref() -> None:
    markdown, _frames = _page("pi")

    lanterns = [value for value in markdown if value.startswith('<div class="gl-signature">')]

    assert len(lanterns) == len(cases_of("pi"))
    for value in lanterns:
        headers = re.findall(r'<th scope="col" class="[^"]*">([^<]*)</th>', value)
        assert headers[:2] == ["source ref", "source line"], headers
        assert 'class="gl-lit">source line' not in value  # the line is never lit


def test_the_phantom_tables_carry_the_line_after_the_ref() -> None:
    assert pi_settings.LEDGER_COLUMNS[:2] == ("source_ref", "source_line")
    assert pi_settings.MASTER_COLUMNS[:2] == ("source_ref", "source_line")
    assert pi_settings.PAYMENT_COLUMNS[:2] == ("source_ref", "source_line")


def _real_pipeline() -> pi_settings.Pipeline:
    """The Phantom demo in its real formats: Facturae invoices and a Norma 43 payments file."""
    config = pi_settings.load_config(ROOT / "apps" / "phantom_invoices" / "config.toml")
    demo = pi_settings.demo_inputs(config, ROOT, "real")
    return pi_settings.run_pipeline(demo.invoices, demo.suppliers, demo.payments, demo.as_of)


def test_an_xml_invoice_reads_invoice_n_and_has_an_empty_line_cell() -> None:
    pipeline = _real_pipeline()
    lines = source_lines_of(pipeline.invoices, pipeline.suppliers, pipeline.payments)
    alerts = [a for result in pipeline.results for a in result.alerts]
    xml = [a for a in alerts if any(_is_xml(ref) for ref in a.source_refs)]
    assert xml

    for alert in xml:
        chips = CHIP.findall(refs_chips_html(alert.source_refs, lines))
        for ref, (_title, text) in zip(alert.source_refs, chips, strict=True):
            file_name, _sep, position = ref.rpartition(":")
            if file_name.lower().endswith(".xml"):
                assert ref not in lines
                assert html.unescape(text) == f"{file_name} {DOT} invoice {position}"
            else:
                assert html.unescape(text).endswith(f"line {lines[ref]}"), ref  # CSV or Norma 43
        view = pi_settings.lantern_view(alert, pipeline)
        xml_rows = view[view["source_ref"].str.lower().str.contains(r"\.xml:", regex=True)]
        assert list(xml_rows.get("source_line", [])) in ([], [""] * len(xml_rows))
    ledger = pi_settings.ledger_view(pipeline.invoices, pipeline.reconciliation)
    assert set(ledger["source_line"]) == {""}  # every invoice of this demo is an XML invoice


def test_norma_43_payments_show_the_line_of_their_record_22() -> None:
    pipeline = _real_pipeline()
    n43_lines = _text_lines("data/samples/phantom_demo/payments.n43")

    refs = list(pipeline.payments["source_ref"])
    view = pi_settings.cited_payments_view(pipeline.payments, refs)

    assert len(view) > 0
    for ref, line in zip(view["source_ref"], view["source_line"], strict=True):
        assert line == ref.rpartition(":")[2]  # a Norma 43 row is the line
        assert n43_lines[int(line) - 1].startswith("22")


# --- the quarantine tables ---


RECORDS = [
    {"source_file": "a.csv", "source_row": 3, "source_line": 5, "reason": "r", "raw": {"a": "1"}},
    {"source_file": "b.xml", "source_row": 2, "source_line": None, "reason": "r", "raw": ""},
    {"source_file": "c.csv", "source_row": None, "source_line": None, "reason": "x", "raw": ""},
    {"source_file": "d.csv", "source_row": 1, "reason": "no key", "raw": ""},
]


def test_the_reference_quarantine_table_has_a_line_column_not_a_row_column() -> None:
    table = quarantine_table(RECORDS)

    assert list(table.columns) == ["file", "line", "reason", "raw"]
    assert list(table["line"]) == ["5", "", "", ""]
    assert list(table["file"]) == ["a.csv", "b.xml", "c.csv", "d.csv"]


def test_the_phantom_quarantine_table_has_a_line_column_not_a_row_column() -> None:
    table = pi_settings.quarantine_view(RECORDS)

    assert list(table.columns) == ["file", "line", "reason", "raw"]
    assert list(table["line"]) == ["5", "", "", ""]


def test_the_phantom_page_quarantine_lines_point_at_the_multi_rate_rows_of_the_file() -> None:
    _markdown, frames = _page("pi")
    tables = [f for f in frames if list(f.columns) == ["file", "line", "reason", "raw"]]

    [table] = tables
    invoice_lines = _text_lines("data/samples/phantom_demo/invoices.csv")

    assert len(table) == 2
    for line, raw in zip(table["line"], table["raw"], strict=True):
        number = re.search(r"'invoice_number': '([^']*)'", raw)
        assert number is not None and line.isdigit()
        assert number.group(1) in invoice_lines[int(line) - 1], (line, number.group(1))


# --- a line is a Python int or None ---


def test_source_lines_of_gives_python_ints_whatever_the_cell_holds() -> None:
    import numpy as np

    frame = pd.DataFrame(
        {
            "source_ref": ["a.csv:0", "a.csv:1", "a.csv:2", "a.csv:3", "a.csv:4", "a.csv:5"],
            "source_line": pd.Series(
                [np.int64(2), np.int32(3), 4.0, pd.NA, float("nan"), None], dtype=object
            ),
        }
    )

    lines = source_lines_of(frame)

    assert lines == {"a.csv:0": 2, "a.csv:1": 3, "a.csv:2": 4}
    assert all(type(line) is int for line in lines.values())
    nullable = pd.DataFrame({"source_ref": ["b.csv:0", "b.csv:1"]})
    nullable["source_line"] = pd.array([5, None], dtype="Int64")
    assert source_lines_of(nullable) == {"b.csv:0": 5}
    assert type(source_lines_of(nullable)["b.csv:0"]) is int
