"""Hypothesis strategies shared by the phantom-invoices tests (synthetic data only)."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd
from hypothesis import strategies as st

from apps.phantom_invoices.tests.pi_builders import (
    make_invoices,
    make_payments,
    make_suppliers,
    master_iban,
)
from apps.phantom_invoices.tests.pi_checkers import iban_check_digits

# Cells that look like text but mean "nothing here", plus symbol-only invoice numbers.
_BLANK_LIKE = ["", " ", "\u00a0", "\t", "-", "\u2013", "\u2014", "--", "/ /", "---"]
# A small pool of source_refs so that generated frames contain duplicates.
REF_POOL = ["f.csv:0", "f.csv:1", "f.csv:2", "f.csv:9", "f.csv:10", "g.csv:0"]
_UPPER = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_ALNUM = _UPPER + "0123456789"
# What a messy file may put between the characters of an IBAN.
_SEPARATORS = ["", "", "", " ", "\u00a0", "\t"]
# Separators between the parts of an invoice number such as F-2026-0042.
_NUMBER_SEPARATORS = ["-", "", "/", " "]
# Largest amount a tamed dirty cell may carry (see tame_dirty_cell).
TAME_LIMIT = Decimal(10) ** 9
# Counters that start just below a power of ten, so a rollover such as 0099 -> 0100 is common.
_ROLLOVER_STARTS = [8, 98, 998, 9998]

# (invoices, suppliers, payments) as drawn by reconciliation_inputs.
Frames = tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]
_RECON_BASE_DATE = date(2026, 1, 1)
_RECON_DAYS = 120  # invoices and payments fall within this many days of the base date
_RECON_MAX_ROWS = 6
_RECON_SUPPLIERS = [1, 2, 3]  # fictional supplier numbers of the master
# A small set of amounts forces collisions; the 0.01 and 0.02 steps probe the match tolerance.
_RECON_AMOUNTS = ["121.00", "121.01", "121.02", "242.00", "60.50", "60.51"]
_RECON_CURRENCIES = ["EUR", "EUR", "EUR", "USD"]
_RECON_FLOWS = ["debit", "debit", "debit", "credit"]


def dirty_cell() -> st.SearchStrategy[Any]:
    """Return a strategy of every kind of cell a messy upstream file can produce."""
    return st.one_of(
        st.none(),
        st.text(max_size=12),
        st.sampled_from(_BLANK_LIKE),
        st.floats(allow_nan=True, allow_infinity=True),
        # No signaling NaN: it breaks pandas isna/repr and the readers never let it in.
        st.decimals(allow_nan=False, allow_infinity=True),
        st.just(Decimal("NaN")),
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


def _tame(cell: Any) -> Any:
    """Replace a finite Decimal beyond TAME_LIMIT by Decimal(1); every other cell is unchanged."""
    if isinstance(cell, Decimal) and cell.is_finite() and abs(cell) > TAME_LIMIT:
        return Decimal(1)
    return cell


def tame_dirty_cell() -> st.SearchStrategy[Any]:
    """Return dirty_cell() without amounts beyond Decimal precision.

    An amount of 10**30 cannot be rounded to cents in the default Decimal context, which is a
    property of Decimal and not a defect of a detector; ingestion never lets such an amount in.
    """
    return dirty_cell().map(_tame)


@st.composite
def with_dirty_cells(draw: st.DrawFn, frame: pd.DataFrame) -> pd.DataFrame:
    """Draw `frame` with at most one tamed dirty cell planted in each row, in a random column."""
    columns = list(frame.columns)
    records = frame.to_dict("records")
    if not columns:
        return frame
    for record in records:
        if draw(st.booleans()):
            record[draw(st.sampled_from(columns))] = draw(tame_dirty_cell())
    return pd.DataFrame(records, columns=columns, dtype=object)


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


@st.composite
def consecutive_numbers(draw: st.DrawFn, min_size: int = 2, max_size: int = 6) -> list[str]:
    """Draw consecutive invoice numbers of one supplier (prefix, year, zero padding, rollover)."""
    prefix = draw(st.text(alphabet=_UPPER, min_size=1, max_size=4))
    year = draw(st.integers(min_value=2000, max_value=2099))
    width = draw(st.integers(min_value=1, max_value=6))
    separator = draw(st.sampled_from(_NUMBER_SEPARATORS))
    plain_start = st.integers(min_value=0, max_value=10_000)
    rollover_start = st.sampled_from(_ROLLOVER_STARTS)
    start = draw(st.one_of(plain_start, rollover_start))
    count = draw(st.integers(min_value=min_size, max_value=max_size))
    tail = f"{separator}{year}{separator}"
    return [f"{prefix}{tail}{start + step:0{width}d}" for step in range(count)]


@st.composite
def reconciliation_inputs(draw: st.DrawFn) -> Frames:
    """Draw (invoices, suppliers, payments) built to force collisions in the matching.

    Few suppliers, totals and payment amounts from a small set, dates within 120 days, payment
    counterparties from the master or unknown, an IBAN from the master or none.
    """
    day = st.integers(min_value=0, max_value=_RECON_DAYS)
    invoice_specs: list[dict[str, Any]] = []
    for _ in range(draw(st.integers(min_value=0, max_value=_RECON_MAX_ROWS))):
        spec = {
            "supplier": draw(st.sampled_from(_RECON_SUPPLIERS)),
            "issue_date": _RECON_BASE_DATE + timedelta(days=draw(day)),
            "total": Decimal(draw(st.sampled_from(_RECON_AMOUNTS))),
            "currency": draw(st.sampled_from(_RECON_CURRENCIES)),
        }
        invoice_specs.append(spec)
    payment_specs: list[dict[str, Any]] = []
    for _ in range(draw(st.integers(min_value=0, max_value=_RECON_MAX_ROWS))):
        known = draw(st.sampled_from([*_RECON_SUPPLIERS, None]))
        iban_of = draw(st.sampled_from([*_RECON_SUPPLIERS, None]))
        spec = {
            "supplier": known or 1,
            "date": _RECON_BASE_DATE + timedelta(days=draw(day)),
            "amount": Decimal(draw(st.sampled_from(_RECON_AMOUNTS))),
            "currency": draw(st.sampled_from(_RECON_CURRENCIES)),
            "flow": draw(st.sampled_from(_RECON_FLOWS)),
        }
        if known is None:
            spec["counterparty"] = "Comercio Local Ficticio"
        if iban_of is not None:
            spec["iban"] = master_iban(iban_of)
        payment_specs.append(spec)
    suppliers = make_suppliers([{"supplier": k} for k in _RECON_SUPPLIERS])
    return make_invoices(invoice_specs), suppliers, make_payments(payment_specs)
