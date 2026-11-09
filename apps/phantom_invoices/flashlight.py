"""The haunted-ledger theme and the flashlight table renderer (design section 13).

Pure module: no Streamlit import and no I/O. `render_ledger_html` escapes every cell and header;
only fixed class names ever reach an attribute.
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


def render_ledger_html(df: pd.DataFrame, lit_refs: Collection[str]) -> str:
    """Render `df` as an HTML table; rows in `lit_refs` are lit, all others dimmed.

    Every cell and header is HTML-escaped. An empty `lit_refs` dims nothing. A row without a
    `source_ref` cell is dimmed whenever `lit_refs` is not empty.
    """
    lit = frozenset(lit_refs)
    cols = list(df.columns)
    head = "".join(f"<th>{_esc(c)}</th>" for c in cols)
    body = []
    for rec in df.to_dict("records"):
        cls = "" if not lit else ("lit" if rec.get("source_ref") in lit else "dim")
        cells = "".join(f"<td>{_esc(rec.get(c))}</td>" for c in cols)
        body.append(f'<tr class="{cls}">{cells}</tr>')
    table_cls = "ledger has-lit" if lit else "ledger"
    return (
        f'<table class="{table_cls}"><thead><tr>{head}</tr></thead>'
        f"<tbody>{''.join(body)}</tbody></table>"
    )
