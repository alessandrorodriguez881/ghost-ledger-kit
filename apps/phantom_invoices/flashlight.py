"""The haunted-ledger theme and the flashlight table renderer (design section 13).

Pure module: no Streamlit import and no I/O. `render_ledger_html` escapes every cell, header and
attribute value (the row `data-ref` and the Line cell title); class names are fixed.
"""

from __future__ import annotations

import html
from collections.abc import Collection

import pandas as pd

from apps.phantom_invoices.detectors.utils import is_missing

# Injected once by the app inside a <style> element. No external CSS framework, font or image.
HAUNTED_CSS: str = """
.stApp { background: #12101a; color: #e8dcc0; }
.ledger { width: 100%; border-collapse: separate; border-spacing: 0; font-family: Georgia, serif; }
.ledger th { color: #ffb347; text-align: left; border-bottom: 1px solid #3a3350; }
.ledger td { padding: 4px 8px; border-bottom: 1px solid #241f33; }
.ledger.has-lit tr.dim { opacity: 0.25; }
.ledger tr.lit td {
  background: radial-gradient(circle at 50% 50%, #1f3d33 0%, #12101a 120%);
  color: #ffffff;
  box-shadow: inset 0 0 14px 2px #7cffb2;
}
.ledger tr.lit td:first-child { border-left: 3px solid #7cffb2; }
.badge-critical { color: #ff6b6b; }
.badge-warning { color: #ffd166; }
"""


def _esc(value: object) -> str:
    """HTML-escape a cell value (quotes included); a missing value is shown as empty text."""
    return html.escape("" if is_missing(value) else str(value), quote=True)


# Visible columns of the haunted ledger, in order: (key in `ledger_view`, plain header). The
# source_ref is not a column: it rides on each row as `data-ref` and on the Line cell as a title
# (REQ-PI-71).
LEDGER_VISIBLE: tuple[tuple[str, str], ...] = (
    ("source_line", "Line"),
    ("status", "Status"),
    ("invoice_number", "Invoice"),
    ("supplier_name", "Supplier"),
    ("total", "Total"),
    ("issue_date", "Issued"),
    ("due_date", "Due"),
    ("base_amount", "Base"),
    ("vat_rate", "VAT rate"),
    ("vat_amount", "VAT"),
    ("surcharge_amount", "Surcharge"),
    ("withholding_amount", "Withholding"),
    ("iban", "IBAN"),
)
# The one cell that may wrap onto several lines (see APP_CSS in app.py).
WRAP_KEY: str = "supplier_name"


def _is_ledger(df: pd.DataFrame) -> bool:
    """True when `df` is the haunted-ledger view: source_ref plus every visible column."""
    keys = {"source_ref", *(key for key, _ in LEDGER_VISIBLE)}
    return keys.issubset(df.columns)


def _row_class(lit: frozenset[str], ref: object) -> str:
    """Return the row class: empty when nothing is lit, else lit or dim."""
    return "" if not lit else ("lit" if ref in lit else "dim")


def _table(lit: frozenset[str], head: str, body: list[str]) -> str:
    """Wrap a header and rows in the table element."""
    table_cls = "ledger has-lit" if lit else "ledger"
    return (
        f'<table class="{table_cls}"><thead><tr>{head}</tr></thead>'
        f"<tbody>{''.join(body)}</tbody></table>"
    )


def _render_haunted(df: pd.DataFrame, lit: frozenset[str]) -> str:
    """Render the haunted ledger: plain headers, the file line first, the ref as data-ref."""
    head = "".join(f"<th>{_esc(header)}</th>" for _, header in LEDGER_VISIBLE)
    body = []
    for rec in df.to_dict("records"):
        ref = rec.get("source_ref")
        cells = []
        for key, _ in LEDGER_VISIBLE:
            if key == "source_line":
                cells.append(f'<td title="{_esc(ref)}">{_esc(rec.get(key))}</td>')
            elif key == WRAP_KEY:
                cells.append(f'<td class="supplier">{_esc(rec.get(key))}</td>')
            else:
                cells.append(f"<td>{_esc(rec.get(key))}</td>")
        body.append(
            f'<tr class="{_row_class(lit, ref)}" data-ref="{_esc(ref)}">{"".join(cells)}</tr>'
        )
    return _table(lit, head, body)


def render_ledger_html(df: pd.DataFrame, lit_refs: Collection[str]) -> str:
    """Render `df` as an HTML table; rows in `lit_refs` are lit, all others dimmed.

    The ledger view (`ledger_view`) gets the plain-header layout of REQ-PI-71; any other frame
    (the cited master and payment rows) is shown column by column under its own names. Every
    cell, header and attribute is HTML-escaped. An empty `lit_refs` dims nothing. A row without a
    `source_ref` cell is dimmed whenever `lit_refs` is not empty.
    """
    lit = frozenset(lit_refs)
    if _is_ledger(df):
        return _render_haunted(df, lit)
    cols = list(df.columns)
    head = "".join(f"<th>{_esc(c)}</th>" for c in cols)
    body = []
    for rec in df.to_dict("records"):
        cells = "".join(f"<td>{_esc(rec.get(c))}</td>" for c in cols)
        body.append(f'<tr class="{_row_class(lit, rec.get("source_ref"))}">{cells}</tr>')
    return _table(lit, head, body)
