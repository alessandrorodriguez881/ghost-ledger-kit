"""The Exorcise expander shared by the three apps (spec exorcise, design section 3).

``render_exorcise`` draws, for an alert that has a template, one collapsed expander with the
language choice, the draft in a read-only text area, a download button and one line that says the
text is a draft. The draft comes from ``ledger_kit.actions.build_draft`` (fixed template, number
guard); no model is called. It lives here, not in the app files, so that each app file keeps its
one ``st.radio`` call (the demo-format radio) that the app tests pin.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ledger_kit.actions import (
    DISCLAIMER,
    DOWNLOAD_LABEL,
    DRAFT_LABEL,
    EXPANDER_TITLE,
    LANGUAGE_LABEL,
    LANGUAGES,
    UNAVAILABLE,
    ActionTemplate,
    build_draft,
    file_name,
)
from ledger_kit.models import Alert

# The text area grows with the draft, between these heights in pixels.
_MIN_HEIGHT = 160
_MAX_HEIGHT = 520
_LINE_HEIGHT = 26


def _height(draft: str) -> int:
    """Return a text area height that shows the whole draft, within the limits."""
    wanted = _LINE_HEIGHT * (draft.count("\n") + 3)
    return max(_MIN_HEIGHT, min(_MAX_HEIGHT, wanted))


def render_exorcise(
    alert: Alert,
    rows: pd.DataFrame,
    template: ActionTemplate | None,
    *,
    prefix: str,
    row_columns: tuple[str, ...] | None = None,
) -> None:
    """Draw the Exorcise expander of one alert card; draw nothing when it has no template."""
    if template is None:
        return
    names = [label for _code, label in LANGUAGES]
    with st.expander(EXPANDER_TITLE, expanded=False):
        choice = st.radio(
            LANGUAGE_LABEL,
            names,
            index=0,
            horizontal=True,
            key=f"{prefix}_ex_lang_{alert.id}",
        )
        code = LANGUAGES[names.index(choice)][0]
        draft = build_draft(alert, rows, template, code, row_columns=row_columns)
        if draft is None:
            st.info(UNAVAILABLE[code])
            return
        st.text_area(
            DRAFT_LABEL[code],
            draft,
            height=_height(draft),
            disabled=True,
            key=f"{prefix}_ex_text_{alert.id}_{code}",
        )
        st.download_button(
            DOWNLOAD_LABEL[code],
            draft,
            file_name=file_name(alert, code),
            mime="text/plain",
            on_click="ignore",
            key=f"{prefix}_ex_dl_{alert.id}_{code}",
        )
        st.caption(DISCLAIMER[code])
