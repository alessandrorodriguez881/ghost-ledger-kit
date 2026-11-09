"""Hypothesis strategies shared by the phantom-invoices tests (synthetic data only)."""

from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
from hypothesis import strategies as st

from apps.phantom_invoices.tests.pi_checkers import iban_check_digits

# Cells that look like text but mean "nothing here", plus symbol-only invoice numbers.
_BLANK_LIKE = ["", " ", "\u00a0", "\t", "-", "\u2013", "\u2014", "--", "/ /", "---"]
# A small pool of source_refs so that generated frames contain duplicates.
REF_POOL = ["f.csv:0", "f.csv:1", "f.csv:2", "f.csv:9", "f.csv:10", "g.csv:0"]
_UPPER = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_ALNUM = _UPPER + "0123456789"
# What a messy file may put between the characters of an IBAN.
_SEPARATORS = ["", "", "", " ", "\u00a0", "\t"]


def dirty_cell() -> st.SearchStrategy[Any]:
    """Return a strategy of every kind of cell a messy upstream file can produce."""
    return st.one_of(
        st.none(),
        st.text(max_size=12),
        st.sampled_from(_BLANK_LIKE),
        st.floats(allow_nan=True, allow_infinity=True),
        st.decimals(allow_nan=True, allow_infinity=True),
        st.integers(),
        st.booleans(),
        st.dates(),
        st.datetimes(min_value=datetime(1900, 1, 1), max_value=datetime(2200, 1, 1)),
        st.just(pd.NA),
        st.just(pd.NaT),
        st.just(np.nan),
        st.just(np.True_),
        st.just(np.False_),
        st.just(pd.Timestamp("2026-03-01 10:30:00")),
    )


@st.composite
def dirty_frame(
    draw: st.DrawFn,
    columns: tuple[str, ...] = ("source_ref", "issue_date", "total"),
    max_rows: int = 6,
) -> pd.DataFrame:
    """Draw an object-dtype frame whose cells are dirty; source_ref mostly comes from a pool."""
    ref_cell = st.one_of(st.sampled_from(REF_POOL), dirty_cell())
    count = draw(st.integers(min_value=0, max_value=max_rows))
    records = [
        {column: draw(ref_cell if column == "source_ref" else dirty_cell()) for column in columns}
        for _ in range(count)
    ]
    return pd.DataFrame(records, columns=list(columns), dtype=object)


@st.composite
def valid_iban(draw: st.DrawFn) -> str:
    """Draw a compact IBAN of any country shape whose ISO 13616 checksum is valid."""
    country = draw(st.text(alphabet=_UPPER, min_size=2, max_size=2))
    bban = draw(st.text(alphabet=_ALNUM, min_size=11, max_size=30))
    return country + iban_check_digits(country, bban) + bban


@st.composite
def spaced_cased(draw: st.DrawFn, iban: str) -> str:
    """Draw `iban` re-typed by a human: random case, spaces, tabs and non-breaking spaces."""
    pieces: list[str] = []
    for char in iban:
        pieces.append(draw(st.sampled_from(_SEPARATORS)))
        pieces.append(char.lower() if draw(st.booleans()) else char)
    pieces.append(draw(st.sampled_from(_SEPARATORS)))
    return "".join(pieces)
