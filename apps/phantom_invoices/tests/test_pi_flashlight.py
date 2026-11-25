"""Tests for the haunted-ledger theme and the flashlight renderer (Task P16)."""

import ast
import re
from pathlib import Path

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from apps.phantom_invoices.flashlight import HAUNTED_CSS, render_ledger_html

FLASHLIGHT_SOURCE = Path(__file__).resolve().parents[1] / "flashlight.py"
# The only tags (with the only attributes) that render_ledger_html may emit.
FIXED_TAG = re.compile(r'</?(?:table|thead|tbody|tr|th|td)(?: class="[a-z -]*")?>')


@pytest.fixture
def ledger() -> pd.DataFrame:
    """Three synthetic invoice rows."""
    return pd.DataFrame(
        {
            "source_ref": ["inv.csv:0", "inv.csv:1", "inv.csv:2"],
            "invoice_number": ["F-2026-0001", "F-2026-0002", "F-2026-0003"],
        }
    )


# Tier 1: normal cases


def test_cited_rows_lit_and_others_dimmed(ledger: pd.DataFrame) -> None:
    """Rows in lit_refs get class lit, every other row class dim, and the table has-lit."""
    html = render_ledger_html(ledger, {"inv.csv:1"})

    assert html.startswith('<table class="ledger has-lit">')
    assert html.count('<tr class="lit">') == 1
    assert html.count('<tr class="dim">') == 2
    assert '<tr class="lit"><td>inv.csv:1</td>' in html


def test_two_lit_rows(ledger: pd.DataFrame) -> None:
    """Several refs can be lit at once, in any collection type."""
    html = render_ledger_html(ledger, ["inv.csv:0", "inv.csv:2"])

    assert html.count('<tr class="lit">') == 2
    assert html.count('<tr class="dim">') == 1


@pytest.mark.parametrize("empty", [set(), [], (), frozenset()])
def test_no_lit_refs_dims_nothing(ledger: pd.DataFrame, empty: object) -> None:
    """Without lit refs the table class is just ledger and no row is dimmed."""
    html = render_ledger_html(ledger, empty)  # type: ignore[arg-type]

    assert html.startswith('<table class="ledger">')
    assert "dim" not in html
    assert "has-lit" not in html
    assert html.count("<td>inv.csv:") == 3


def test_header_cells_rendered(ledger: pd.DataFrame) -> None:
    """Each column name becomes a th cell, in column order."""
    html = render_ledger_html(ledger, set())

    assert "<thead><tr><th>source_ref</th><th>invoice_number</th></tr></thead>" in html


# Tier 2: edge cases


def test_script_tag_and_quotes_are_escaped() -> None:
    """Markup, quotes and ampersands are escaped in every cell and in a column name."""
    nasty = "<script>alert(1)</script> \"double\" 'single' & more"
    frame = pd.DataFrame({'<b>"col"</b>': [nasty], "source_ref": ["inv.csv:0"]})

    html = render_ledger_html(frame, {"inv.csv:0"})

    assert "<script>" not in html
    assert "</script>" not in html
    assert "<b>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "&quot;double&quot;" in html
    assert "&#x27;single&#x27;" in html
    assert "&amp; more" in html
    assert "<th>&lt;b&gt;&quot;col&quot;&lt;/b&gt;</th>" in html


def test_missing_cells_render_empty() -> None:
    """None, NaN, pd.NA and a lone dash are shown as empty cells."""
    frame = pd.DataFrame({"a": [None, float("nan"), pd.NA, "-"]}, dtype=object)

    html = render_ledger_html(frame, set())

    assert html.count("<td></td>") == 4
    assert "nan" not in html.lower()
    assert "None" not in html
    assert "<NA>" not in html


def test_empty_frame_renders_header_only() -> None:
    """A frame without rows gives the header and an empty body."""
    html = render_ledger_html(pd.DataFrame(columns=["a", "b"]), set())

    assert "<th>a</th><th>b</th>" in html
    assert "<tbody></tbody>" in html
    assert "<tr class=" not in html


def test_empty_frame_with_lit_refs_still_marks_the_table() -> None:
    """The table class depends on lit_refs only, not on the rows."""
    html = render_ledger_html(pd.DataFrame(columns=["a"]), {"x"})

    assert html.startswith('<table class="ledger has-lit">')


def test_row_without_source_ref_column_is_dimmed_when_lit_refs_given() -> None:
    """A frame with no source_ref column has nothing to light: every row is dimmed."""
    frame = pd.DataFrame({"supplier_name": ["Ana García", "Luigi Rossi"]})

    html = render_ledger_html(frame, {"inv.csv:0"})

    assert html.count('<tr class="dim">') == 2
    assert 'class="lit"' not in html


def test_non_string_cells_are_rendered_as_text() -> None:
    """Numbers and dates are shown with str()."""
    frame = pd.DataFrame({"n": [3], "source_ref": ["inv.csv:0"]})

    assert "<td>3</td>" in render_ledger_html(frame, set())


def test_haunted_css_contains_theme_colours_and_dim_opacity() -> None:
    """The theme has the candle-lit background, the ghost-green glow and the dim opacity."""
    for token in ("#12101a", "#7cffb2", "opacity: 0.25", "box-shadow", "radial-gradient"):
        assert token in HAUNTED_CSS, token
    assert "tr.dim" in HAUNTED_CSS
    assert "tr.lit td" in HAUNTED_CSS


def test_haunted_css_has_no_external_url() -> None:
    """No remote resource: no URL, no @import, no url()."""
    lowered = HAUNTED_CSS.lower()

    for forbidden in ("http:", "https:", "//", "@import", "url("):
        assert forbidden not in lowered, forbidden


def test_flashlight_module_is_pure() -> None:
    """The renderer imports no Streamlit (REQ-PI-50)."""
    tree = ast.parse(FLASHLIGHT_SOURCE.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    assert "streamlit" not in imported


# REQ-PI-71: the haunted ledger shows plain headers and the file line, not the source ref

LEDGER_HEADERS = [
    "Line",
    "Status",
    "Invoice",
    "Supplier",
    "Total",
    "Issued",
    "Due",
    "Base",
    "VAT rate",
    "VAT",
    "Surcharge",
    "Withholding",
    "IBAN",
]


def _view(suppliers: tuple[str, ...] = ("Ana García", "Luigi Rossi")) -> pd.DataFrame:
    """A synthetic frame shaped like `ledger_view` (LEDGER_COLUMNS), one row per supplier."""
    rows = [
        {
            "source_ref": f"invoices.csv:{i + 1}",
            "source_line": str(i + 3),
            "status": "✅",
            "invoice_number": f"F-2026-{i:04d}",
            "supplier_name": name,
            "issue_date": "2026-01-05",
            "due_date": "2026-02-04",
            "base_amount": "100,00 EUR",
            "vat_rate": "21 %",
            "vat_amount": "21,00 EUR",
            "surcharge_amount": "",
            "withholding_amount": "",
            "total": "121,00 EUR",
            "iban": "ES88************1332",
        }
        for i, name in enumerate(suppliers)
    ]
    return pd.DataFrame(rows)


def _cells(row_html: str) -> list[str]:
    """The text of each td of one row."""
    return re.findall(r"<td[^>]*>(.*?)</td>", row_html)


def test_ledger_header_order_and_names() -> None:
    """The visible headers are the plain names, in the order of REQ-PI-71."""
    html = render_ledger_html(_view(), set())

    assert re.findall(r"<th>(.*?)</th>", html) == LEDGER_HEADERS
    assert "source_ref" not in html.split("<tbody>")[0]
    assert "invoice_number" not in html


def test_source_ref_is_not_the_text_of_any_cell() -> None:
    """The ref is only an attribute: no cell shows it, and the line cell shows the file line."""
    frame = _view()

    html = render_ledger_html(frame, set())
    rows = re.findall(r"<tr class=[^>]*>.*?</tr>", html)

    assert len(rows) == 2
    for row, ref in zip(rows, frame["source_ref"], strict=True):
        assert ref not in _cells(row)
        assert _cells(row)[0] == frame.loc[frame["source_ref"] == ref, "source_line"].item()
        assert f'<td title="{ref}">' in row


def test_every_row_carries_data_ref() -> None:
    """Each row has its ref as data-ref, lit or not."""
    for lit in (set(), {"invoices.csv:1"}):
        html = render_ledger_html(_view(), lit)

        assert 'data-ref="invoices.csv:1"' in html
        assert 'data-ref="invoices.csv:2"' in html
        assert html.count("data-ref=") == 2


def test_lit_and_dim_follow_the_refs() -> None:
    """The cited ref lights its row, the other row dims; the order of the frame is kept."""
    html = render_ledger_html(_view(), {"invoices.csv:2"})

    assert html.startswith('<table class="ledger has-lit">')
    assert '<tr class="dim" data-ref="invoices.csv:1">' in html
    assert '<tr class="lit" data-ref="invoices.csv:2">' in html
    assert 'class="dim"' in html and html.count('class="lit"') == 1


def test_no_lit_refs_leaves_ledger_rows_plain() -> None:
    """Without lit refs no row has a lit or dim class."""
    html = render_ledger_html(_view(), set())

    assert html.startswith('<table class="ledger">')
    assert html.count('<tr class="" data-ref=') == 2
    assert "dim" not in html and "lit" not in html


def test_ledger_cells_headers_and_attributes_are_escaped() -> None:
    """Angle brackets and quotes in a supplier name and in a ref never become markup."""
    nasty = '<img src=x onerror="alert(1)"> O\'Neil & "Sons"'
    frame = _view((nasty,))
    frame.loc[0, "source_ref"] = 'inv"><script>.csv:1'

    html = render_ledger_html(frame, {'inv"><script>.csv:1'})

    assert "<img" not in html and "<script>" not in html
    assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in html
    assert "O&#x27;Neil &amp; &quot;Sons&quot;" in html
    assert 'data-ref="inv&quot;&gt;&lt;script&gt;.csv:1"' in html
    assert '<td title="inv&quot;&gt;&lt;script&gt;.csv:1">' in html
    assert '<tr class="lit" data-ref=' in html


def test_ledger_empty_line_cell_keeps_the_title() -> None:
    """An XML invoice has no line: the cell is empty and the ref is still on hover."""
    frame = _view()
    frame.loc[0, "source_line"] = ""

    html = render_ledger_html(frame, set())

    assert '<td title="invoices.csv:1"></td>' in html


def test_supplier_cell_is_the_only_wrapping_cell() -> None:
    """Only the supplier cell has the class that lets it wrap (see APP_CSS)."""
    html = render_ledger_html(_view(), set())

    assert html.count('<td class="supplier">') == 2


# Tier 3: property-based tests


@settings(max_examples=200, deadline=None)
@given(
    cells=st.lists(st.text(), max_size=6),
    lit=st.sets(st.text(max_size=3), max_size=3),
    header=st.text(min_size=1, max_size=8),
)
def test_render_never_emits_unescaped_markup(cells: list[str], lit: set[str], header: str) -> None:
    """Arbitrary text cells never add markup: only the fixed tags contain angle brackets."""
    frame = pd.DataFrame(
        {"source_ref": [f"inv.csv:{i}" for i in range(len(cells))], header: cells}
        if header != "source_ref"
        else {"source_ref": cells}
    )

    html = render_ledger_html(frame, lit)

    remainder = FIXED_TAG.sub("", html)
    assert "<" not in remainder
    assert ">" not in remainder
    assert '"' not in remainder
