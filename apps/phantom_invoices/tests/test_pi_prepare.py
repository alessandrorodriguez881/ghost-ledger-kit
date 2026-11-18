"""Tests for the multi-rate quarantine of the invoice frame (Task P7)."""

from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd
from hypothesis import given, settings
from hypothesis import strategies as st
from pandas.testing import assert_frame_equal

from apps.phantom_invoices.prepare import MULTI_RATE_REASON, quarantine_multi_rate

COLUMNS = [
    "invoice_number",
    "supplier_tax_id",
    "vat_rate",
    "iban",
    "source_file",
    "source_row",
    "source_ref",
]
TAX_1 = "B00000001"
TAX_2 = "B00000002"
D21 = Decimal("21")
D10 = Decimal("10")


def _row(index: int, number: Any, tax: Any, rate: Any, iban: Any = None) -> dict:
    """Return one invoice-like record whose source_ref is 'inv.csv:<index>'."""
    return {
        "invoice_number": number,
        "supplier_tax_id": tax,
        "vat_rate": rate,
        "iban": iban,
        "source_file": "inv.csv",
        "source_row": index,
        "source_ref": f"inv.csv:{index}",
    }


def _frame(rows: list[dict]) -> pd.DataFrame:
    """Build an object-dtype invoice-like frame (no dtype inference)."""
    return pd.DataFrame(rows, columns=COLUMNS, dtype=object)


# Tier 1: normal cases


def test_multi_rate_group_removed_and_recorded() -> None:
    """Both rows of a supplier+N1 group with rates 21 and 10 are removed and recorded."""
    frame = _frame(
        [
            _row(0, "F-2026-0001", TAX_2, D21),
            _row(10, "F-2026-0042", TAX_1, D10),
            _row(9, "F2026 0042", TAX_1, D21),
        ]
    )

    clean, quarantined = quarantine_multi_rate(frame)

    assert list(clean["source_ref"]) == ["inv.csv:0"]
    assert [q["source_row"] for q in quarantined] == [9, 10]  # natural order, 9 before 10
    for record in quarantined:
        assert set(record) == {"source_file", "source_row", "source_line", "reason", "raw"}
        assert record["source_line"] is None or type(record["source_line"]) is int
        assert record["reason"] == "multi_rate_invoice_out_of_scope"
        assert record["reason"] == MULTI_RATE_REASON
        assert record["source_file"] == "inv.csv"


def test_source_line_of_a_record_is_a_python_int_or_none() -> None:
    """Whatever the cell holds (int, numpy integer, float, pd.NA, NaN, None) the record has an
    int or None, never pd.NA, a numpy integer or a float."""
    cells = [7, np.int64(8), np.int32(9), 10.0, np.float64(11), pd.NA, float("nan"), None]
    rows = [_row(i, "F-1", TAX_1, D21 if i % 2 else D10) for i in range(len(cells))]
    frame = _frame(rows)
    frame["source_line"] = pd.Series(cells, dtype=object)

    _, quarantined = quarantine_multi_rate(frame)

    assert len(quarantined) == len(cells)
    lines = [q["source_line"] for q in quarantined]
    assert lines == [7, 8, 9, 10, 11, None, None, None]
    for line in lines:
        assert line is None or type(line) is int


def test_clean_invoices_untouched() -> None:
    """A frame without multi-rate groups comes back equal and with no records."""
    frame = _frame(
        [
            _row(0, "F-2026-0001", TAX_1, D21),
            _row(1, "F-2026-0002", TAX_1, D21),
            _row(2, "F-2026-0001", TAX_2, D10),
        ]
    )

    clean, quarantined = quarantine_multi_rate(frame)

    assert quarantined == []
    assert_frame_equal(clean, frame)


# Tier 2: edge cases


def test_missing_rate_not_counted_as_different_rate() -> None:
    """A row without a usable vat_rate never makes a group multi-rate."""
    frame = _frame(
        [
            _row(0, "F-1", TAX_1, D21),
            _row(1, "F-1", TAX_1, None),
            _row(2, "F-1", TAX_1, float("nan")),
            _row(3, "F-1", TAX_1, "10"),  # a string is not a Decimal: missing for this purpose
        ]
    )

    clean, quarantined = quarantine_multi_rate(frame)

    assert quarantined == []
    assert len(clean) == 4


def test_rate_21_and_21_00_are_one_rate() -> None:
    """Decimal('21') and Decimal('21.00') are the same rate."""
    frame = _frame([_row(0, "F-1", TAX_1, D21), _row(1, "F-1", TAX_1, Decimal("21.00"))])

    clean, quarantined = quarantine_multi_rate(frame)

    assert quarantined == []
    assert len(clean) == 2


def test_same_number_other_supplier_not_grouped() -> None:
    """The same invoice number at two suppliers with different rates is not multi-rate."""
    frame = _frame([_row(0, "F-1", TAX_1, D21), _row(1, "F-1", TAX_2, D10)])

    clean, quarantined = quarantine_multi_rate(frame)

    assert quarantined == []
    assert len(clean) == 2


def test_rows_without_tax_id_or_number_are_never_grouped() -> None:
    """Rows that cannot be keyed (no tax id, empty N1) stay in the clean frame."""
    frame = _frame(
        [
            _row(0, "F-1", None, D21),
            _row(1, "F-1", "-", D10),
            _row(2, "/ /", TAX_1, D21),
            _row(3, "/ /", TAX_1, D10),
        ]
    )

    clean, quarantined = quarantine_multi_rate(frame)

    assert quarantined == []
    assert len(clean) == 4


def test_empty_frame_and_non_frame_return_unchanged() -> None:
    """Empty frames, None and non-frames are returned as they came, with no records."""
    empty = _frame([])
    for value in (empty, pd.DataFrame(), None, "not a frame", 7):
        clean, quarantined = quarantine_multi_rate(value)  # type: ignore[arg-type]
        assert clean is value
        assert quarantined == []


def test_input_frame_not_mutated() -> None:
    """The input frame keeps its rows, its index and its values."""
    frame = _frame(
        [_row(5, "F-1", TAX_1, D21), _row(6, "F-1", TAX_1, D10), _row(7, "G", TAX_2, D21)]
    )
    before = frame.copy(deep=True)

    quarantine_multi_rate(frame)

    assert_frame_equal(frame, before)
    assert list(frame.index) == [0, 1, 2]


def test_clean_frame_has_fresh_range_index() -> None:
    """After removing rows the clean frame is re-indexed from zero."""
    frame = _frame(
        [_row(0, "F-1", TAX_1, D21), _row(1, "F-1", TAX_1, D10), _row(2, "G", TAX_2, D21)]
    )

    clean, _ = quarantine_multi_rate(frame)

    assert list(clean.index) == [0]
    assert list(clean["source_ref"]) == ["inv.csv:2"]


def test_raw_values_are_strings_and_missing_is_empty() -> None:
    """The raw payload holds a string per column; a missing cell becomes an empty string."""
    frame = _frame(
        [
            _row(0, "F-1", TAX_1, D21, iban=None),
            _row(1, "F-1", TAX_1, D10, iban="ES88 2100 0418 5602 0005 1332"),
        ]
    )

    _, quarantined = quarantine_multi_rate(frame)

    first, second = quarantined
    assert set(first["raw"]) == set(COLUMNS)
    assert all(isinstance(value, str) for value in first["raw"].values())
    assert first["raw"]["iban"] == ""
    assert first["raw"]["vat_rate"] == "21"
    assert first["raw"]["source_row"] == "0"
    assert second["raw"]["iban"] == "ES88 2100 0418 5602 0005 1332"
    assert second["raw"]["vat_rate"] == "10"


# Tier 3: property-based tests

_NUMBERS = ["F-1", "F1", "F-2", "/ /", "G-7", None]
_TAXES = [TAX_1, TAX_2, None, "-"]
_RATES = [D21, Decimal("21.00"), D10, Decimal("4"), None, float("nan")]


@settings(max_examples=200, deadline=None)
@given(
    cells=st.lists(
        st.tuples(st.sampled_from(_NUMBERS), st.sampled_from(_TAXES), st.sampled_from(_RATES)),
        max_size=12,
    )
)
def test_quarantine_partitions_rows(cells: list[tuple[Any, Any, Any]]) -> None:
    """Clean and quarantined rows add up to the input and share no source_ref."""
    frame = _frame([_row(i, number, tax, rate) for i, (number, tax, rate) in enumerate(cells)])

    clean, quarantined = quarantine_multi_rate(frame)

    all_refs = set(frame["source_ref"])
    clean_refs = set(clean["source_ref"])
    quarantined_refs = {f"{q['source_file']}:{q['source_row']}" for q in quarantined}
    assert len(clean) + len(quarantined) == len(frame)
    assert len(quarantined_refs) == len(quarantined)
    assert clean_refs.isdisjoint(quarantined_refs)
    assert clean_refs | quarantined_refs == all_refs
