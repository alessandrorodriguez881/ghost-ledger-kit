"""Script run by AppTest in tests/test_actions.py: one Exorcise expander on a sample alert.

`st.session_state["ex_mode"]` picks the case: `ok` (a good template), `none` (no template) or
`broken` (a template that writes a figure that is in no row). The sample is synthetic.
"""

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ledger_kit.actions import ActionTemplate, row_lines  # noqa: E402
from ledger_kit.models import Alert  # noqa: E402
from ledger_kit.ui.exorcise import render_exorcise  # noqa: E402

PREFIX = "zs"

ALERT = Alert(
    detector="zs.charges_after_cancellation",
    severity="critical",
    title="Charge after cancellation: GYMPLUS",
    source_refs=["s.csv:2", "s.csv:3"],
    data={
        "counterparty": "GYMPLUS",
        "cancellation_date": "2026-07-31",
        "post_cancellation_count": 2,
        "total_charged_after": "17.98",
    },
)
ROWS = pd.DataFrame(
    [
        {
            "date": date(2026, 8, 9),
            "amount": Decimal("8.99"),
            "flow": "debit",
            "currency": "EUR",
            "counterparty": "GYMPLUS",
            "source_ref": "s.csv:2",
        },
        {
            "date": date(2026, 9, 8),
            "amount": Decimal("8.99"),
            "flow": "debit",
            "currency": "EUR",
            "counterparty": "GYMPLUS",
            "source_ref": "s.csv:3",
        },
    ]
)
GOOD = ActionTemplate(
    "sample",
    {
        "en": "Dear {counterparty},\nYou charged me {post_cancellation_count:times} after "
        "{cancellation_date}, {total_charged_after:money}:\n{lines}\n[Your name]",
        "es": "Estimados {counterparty}:\nMe cobraron {post_cancellation_count:times} tras "
        "{cancellation_date}, {total_charged_after:money}:\n{lines}\n[Su nombre]",
    },
    lambda alert, rows, language: {"lines": row_lines(rows)},
)
BROKEN = ActionTemplate("broken", {"en": "You owe 99999.99 EUR.", "es": "Debe 99999.99 EUR."})

mode = st.session_state.get("ex_mode", "ok")
st.session_state["ex_alert_id"] = ALERT.id
render_exorcise(
    ALERT,
    ROWS,
    {"ok": GOOD, "none": None, "broken": BROKEN}[mode],
    prefix=PREFIX,
)
