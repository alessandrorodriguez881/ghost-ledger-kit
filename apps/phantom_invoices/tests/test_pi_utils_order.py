"""Tests for deterministic order, load_rows, as_of and alert hygiene (Task P5)."""

from datetime import date, datetime
from decimal import Decimal
from types import MappingProxyType
from typing import Any

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import apps.phantom_invoices.detectors.utils as utils
from apps.phantom_invoices.detectors.utils import (
    finish,
    load_rows,
    resolve_as_of,
    sort_refs,
    source_ref_key,
    supplier_label,
    text_or_ref,
)
from apps.phantom_invoices.tests.pi_strategies import REF_POOL, dirty_frame
from ledger_kit.models import Alert

COLUMNS = ["source_ref", "issue_date", "total"]


def _frame(rows: list[tuple[Any, ...]]) -> pd.DataFrame:
    """Build an object-dtype frame (no dtype inference) with the invoice-like test columns."""
    return pd.DataFrame(rows, columns=COLUMNS, dtype=object)


def _refs(rows: list[dict]) -> list[str]:
    """Return the source_ref of every record."""
    return [row["source_ref"] for row in rows]


def _alert(ref: str, variant: str, extra: int = 0) -> Alert:
    """Build a minimal alert for ordering tests."""
    return Alert(
        detector="pi.test",
        severity="info",
        title="Ordering",
        source_refs=[ref],
        data={"variant": variant, "extra": extra},
    )


def _no_clock(base: type) -> type:
    """Return a subclass of `base` whose today/now/utcnow raise but whose isinstance is real."""

    def boom(cls: type, *args: object, **kwargs: object) -> None:
        raise AssertionError("the system clock was read")

    class Meta(type):
        """Metaclass that keeps isinstance(real_object, fake_class) true."""

        def __instancecheck__(cls, obj: object) -> bool:
            return isinstance(obj, base)

    namespace = {name: classmethod(boom) for name in ("today", "now", "utcnow")}
    return Meta(base.__name__, (base,), namespace)


# Tier 1: normal cases


def test_source_ref_key_natural_order() -> None:
    """Row numbers compare as integers: f.csv:9 sorts before f.csv:10."""
    refs = ["f.csv:10", "f.csv:9", "e.csv:100", "f.csv:2"]
    assert sorted(refs) != sorted(refs, key=source_ref_key)  # plain text order is wrong
    assert sorted(refs, key=source_ref_key) == ["e.csv:100", "f.csv:2", "f.csv:9", "f.csv:10"]
    assert source_ref_key("f.csv:10") == ("f.csv", 10)


def test_sort_refs_dedupes() -> None:
    """sort_refs returns every ref once, in natural order."""
    ordered = sort_refs(["b.csv:1", "a.csv:2", "b.csv:1", "a.csv:10"])

    assert ordered == ["a.csv:2", "a.csv:10", "b.csv:1"]


def test_load_rows_sorted_by_date_then_ref() -> None:
    """Rows come back by date, then by natural source_ref order, whatever the input order."""
    frame = _frame(
        [
            ("f.csv:2", date(2026, 3, 2), Decimal("1.00")),
            ("f.csv:10", date(2026, 3, 1), Decimal("2.00")),
            ("f.csv:9", date(2026, 3, 1), Decimal("3.00")),
        ]
    )

    rows = load_rows(frame, "issue_date")

    assert _refs(rows) == ["f.csv:9", "f.csv:10", "f.csv:2"]
    assert rows[0]["total"] == Decimal("3.00")


def test_load_rows_without_date_column_sorts_by_source_ref() -> None:
    """With date_col None the order is the natural source_ref order."""
    frame = _frame([("f.csv:10", None, None), ("f.csv:9", None, None), ("f.csv:1", None, None)])
    assert _refs(load_rows(frame, None)) == ["f.csv:1", "f.csv:9", "f.csv:10"]


def test_resolve_as_of_explicit_wins() -> None:
    """An explicit as_of beats any date in the data; a datetime is cut to its date."""
    ledger = _frame([("inv.csv:0", date(2026, 6, 30), Decimal("1.00"))])
    explicit = date(2026, 1, 15)
    stamp = datetime(2026, 1, 15, 8, 0)

    assert resolve_as_of(ledger, MappingProxyType({"as_of": explicit})) == explicit
    assert resolve_as_of(ledger, MappingProxyType({"as_of": stamp})) == explicit


def test_resolve_as_of_latest_over_invoices_and_all_payments() -> None:
    """Without as_of: the latest of all invoice issue dates and all payment dates, credits too."""
    ledger = _frame([("inv.csv:0", date(2026, 3, 1), Decimal("1.00"))])
    payments = pd.DataFrame(
        [
            ("pay.csv:0", date(2026, 3, 10), "debit"),
            ("pay.csv:1", date(2026, 4, 5), "credit"),
        ],
        columns=["source_ref", "date", "flow"],
        dtype=object,
    )

    assert resolve_as_of(ledger, MappingProxyType({"payments": payments})) == date(2026, 4, 5)
    assert resolve_as_of(ledger, MappingProxyType({})) == date(2026, 3, 1)


def test_text_or_ref_and_supplier_label_fallbacks() -> None:
    """Display text falls back: name, then tax id as written, then the row's own source_ref."""
    assert text_or_ref("F-1", "inv.csv:0") == "F-1"
    assert text_or_ref(None, "inv.csv:0") == "inv.csv:0"
    assert text_or_ref(float("nan"), "inv.csv:0") == "inv.csv:0"
    assert text_or_ref("--", "inv.csv:0") == "inv.csv:0"

    full = {"supplier_name": "Suministros García", "supplier_tax_id": "b-00000001"}
    no_name = {"supplier_name": None, "supplier_tax_id": "b-00000001"}
    nothing = {"supplier_name": "", "supplier_tax_id": pd.NA}
    assert supplier_label(full, "inv.csv:0") == "Suministros García"
    assert supplier_label(no_name, "inv.csv:0") == "b-00000001"
    assert supplier_label(nothing, "inv.csv:0") == "inv.csv:0"
    assert supplier_label({}, "inv.csv:0") == "inv.csv:0"


def test_finish_orders_by_first_ref_variant_id() -> None:
    """Alerts are ordered by (first source_ref natural order, variant, id)."""
    late = _alert("f.csv:10", "a")
    second = _alert("f.csv:9", "b")
    first = _alert("f.csv:9", "a")
    tie_one = _alert("f.csv:1", "a", extra=1)
    tie_two = _alert("f.csv:1", "a", extra=2)
    tied = sorted([tie_one, tie_two], key=lambda alert: alert.id)

    ordered = finish([late, second, first, tie_two, tie_one])

    assert ordered == [*tied, first, second, late]
    assert finish([]) == []


# Tier 2: edge cases


@pytest.mark.parametrize(
    "frame",
    [
        pd.DataFrame(),
        pd.DataFrame(columns=["source_ref", "issue_date"]),
        pd.DataFrame({"issue_date": [date(2026, 3, 1)]}),
        None,
        "not a frame",
        [{"source_ref": "f.csv:0"}],
    ],
    ids=["empty", "no-rows", "missing-column", "none", "string", "list"],
)
def test_load_rows_empty_non_frame_and_missing_column(frame: object) -> None:
    """Anything that is not a usable frame yields an empty list and never raises."""
    assert load_rows(frame, "issue_date") == []
    assert load_rows(frame, None) == []


def test_load_rows_drops_row_without_source_ref() -> None:
    """A row that cannot be cited is dropped."""
    frame = _frame(
        [
            (None, date(2026, 3, 1), None),
            (float("nan"), date(2026, 3, 1), None),
            ("", date(2026, 3, 1), None),
            (" ", date(2026, 3, 1), None),
            (7, date(2026, 3, 1), None),
            ("f.csv:1", date(2026, 3, 1), None),
        ]
    )
    assert _refs(load_rows(frame, "issue_date")) == ["f.csv:1"]


def test_load_rows_keeps_first_of_duplicate_source_ref() -> None:
    """For a repeated source_ref the first row in sort order (the earlier date) is kept."""
    frame = _frame(
        [
            ("f.csv:0", date(2026, 3, 5), Decimal("1.00")),
            ("f.csv:0", date(2026, 3, 1), Decimal("2.00")),
        ]
    )

    rows = load_rows(frame, "issue_date")

    assert len(rows) == 1
    assert rows[0]["total"] == Decimal("2.00")


def test_load_rows_missing_date_sorts_last() -> None:
    """A row without a usable date comes after every dated row."""
    frame = _frame(
        [
            ("f.csv:0", None, None),
            ("f.csv:1", "2026-03-01", None),
            ("f.csv:5", date(2026, 3, 1), None),
        ]
    )
    assert _refs(load_rows(frame, "issue_date")) == ["f.csv:5", "f.csv:0", "f.csv:1"]


def test_load_rows_conflicting_duplicates_are_shuffle_invariant() -> None:
    """Two different rows with one source_ref: the same one wins in either input order (DN-5)."""
    one = ("f.csv:0", date(2026, 3, 1), 1)
    two = ("f.csv:0", date(2026, 3, 1), 2)
    text_one = ("f.csv:0", date(2026, 3, 1), "1")

    for first, second in ((one, two), (two, one), (one, text_one), (text_one, one)):
        kept = load_rows(_frame([first, second]), "issue_date")
        assert len(kept) == 1
    kept_ab = load_rows(_frame([one, two]), "issue_date")
    kept_ba = load_rows(_frame([two, one]), "issue_date")
    assert kept_ab == kept_ba
    typed_ab = load_rows(_frame([one, text_one]), "issue_date")
    typed_ba = load_rows(_frame([text_one, one]), "issue_date")
    assert typed_ab == typed_ba


@pytest.mark.parametrize(
    ("ref", "expected"),
    [
        ("f.csv:x", ("f.csv:x", -1)),
        ("f.csv:", ("f.csv:", -1)),
        ("f.csv:-1", ("f.csv:-1", -1)),
        ("f.csv:1.5", ("f.csv:1.5", -1)),
        ("nocolon", ("nocolon", -1)),
        ("", ("", -1)),
        ("dir:sub.csv:12", ("dir:sub.csv", 12)),
        ("f.csv:007", ("f.csv", 7)),
    ],
)
def test_source_ref_key_non_integer_row(ref: str, expected: tuple[str, int]) -> None:
    """A ref whose row part is not a non-negative integer sorts by its whole text, row -1."""
    assert source_ref_key(ref) == expected


def test_resolve_as_of_none_without_any_date() -> None:
    """No explicit as_of and no date anywhere gives None, never today."""
    assert resolve_as_of(pd.DataFrame(), MappingProxyType({})) is None
    assert resolve_as_of(None, MappingProxyType({"payments": None})) is None
    assert resolve_as_of(pd.DataFrame(), MappingProxyType({"as_of": "2026-01-01"})) is None


def test_resolve_as_of_ignores_unusable_dates() -> None:
    """Strings, numbers and missing cells are skipped; the real dates still count."""
    ledger = _frame(
        [
            ("inv.csv:0", "2026-12-31", None),
            ("inv.csv:1", None, None),
            ("inv.csv:2", pd.NaT, None),
            ("inv.csv:3", 20261231, None),
            ("inv.csv:4", float("nan"), None),
        ]
    )
    payments = pd.DataFrame(
        [("pay.csv:0", "x"), ("pay.csv:1", date(2026, 2, 1))],
        columns=["source_ref", "date"],
        dtype=object,
    )

    assert resolve_as_of(ledger, MappingProxyType({"payments": payments})) == date(2026, 2, 1)
    assert resolve_as_of(ledger, MappingProxyType({})) is None


def test_resolve_as_of_never_calls_the_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neither date.today nor datetime.now is reached by the order helpers."""

    monkeypatch.setattr(utils, "date", _no_clock(date))
    monkeypatch.setattr(utils, "datetime", _no_clock(datetime))
    ledger = _frame([("inv.csv:0", date(2026, 3, 1), None)])

    assert resolve_as_of(ledger, MappingProxyType({})) == date(2026, 3, 1)
    assert resolve_as_of(pd.DataFrame(), MappingProxyType({})) is None
    assert _refs(load_rows(ledger, "issue_date")) == ["inv.csv:0"]
    assert _refs(load_rows(_frame([("inv.csv:1", None, None)]), "issue_date")) == ["inv.csv:1"]


# Tier 3: property-based


@settings(max_examples=200, deadline=None)
@given(frame=dirty_frame(), data=st.data())
def test_load_rows_shuffle_invariant(frame: pd.DataFrame, data: st.DataObject) -> None:
    """Shuffling the input rows never changes the loaded rows (REQ-PI-10, DN-5)."""
    order = data.draw(st.permutations(list(range(len(frame)))))
    shuffled = frame.iloc[list(order)].reset_index(drop=True)

    assert repr(load_rows(shuffled, "issue_date")) == repr(load_rows(frame, "issue_date"))


@settings(max_examples=200, deadline=None)
@given(frame=dirty_frame())
def test_load_rows_one_row_per_source_ref(frame: pd.DataFrame) -> None:
    """The result holds at most one row per source_ref, each a citable text."""
    refs = _refs(load_rows(frame, "issue_date"))

    assert len(refs) == len(set(refs))
    assert all(isinstance(ref, str) and ref.strip() for ref in refs)


@settings(max_examples=200, deadline=None)
@given(refs=st.lists(st.one_of(st.sampled_from(REF_POOL), st.text(max_size=8)), max_size=12))
def test_sort_refs_is_sorted_and_distinct(refs: list[str]) -> None:
    """sort_refs returns each distinct ref once, in non-decreasing natural order."""
    result = sort_refs(refs)

    assert len(result) == len(set(refs))
    assert set(result) == set(refs)
    keys = [source_ref_key(ref) for ref in result]
    assert keys == sorted(keys)
    assert sort_refs(list(reversed(refs))) == result
