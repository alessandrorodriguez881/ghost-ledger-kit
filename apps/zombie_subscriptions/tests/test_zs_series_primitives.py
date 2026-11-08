"""Tests for group_by_price_level and longest_cadence_run (Task Z5)."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from apps.zombie_subscriptions.detectors import utils as zs

START = date(2026, 1, 1)
MONTHLY = zs.INTERVALS_BY_NAME["monthly"]


def _row(index: int, day: date, amount: str | Decimal = "12.99") -> dict:
    """Build one synthetic ledger row dict; source_row is the index."""
    return {
        "date": day,
        "amount": Decimal(amount),
        "counterparty": "CLOUDVAULT",
        "source_ref": f"t.csv:{index}",
        "source_row": index,
    }


def _rows_at(offsets: list[int], amount: str = "12.99") -> list[dict]:
    """Build rows `offsets` days after START, all with the same amount."""
    return [_row(i, START + timedelta(days=d), amount) for i, d in enumerate(offsets)]


def _refs(rows: list[dict]) -> list[str]:
    """Return the source_ref values of rows in order."""
    return [r["source_ref"] for r in rows]


# --- Tier 1 -----------------------------------------------------------------------------------


def test_group_by_price_level_splits_on_10pct() -> None:
    """9.99 and 12.99 are separate buckets; 12.99 and 13.79 share one."""
    apart = zs.group_by_price_level([_row(0, START, "9.99"), _row(1, START, "12.99")])
    assert len(apart) == 2
    together = zs.group_by_price_level([_row(0, START, "12.99"), _row(1, START, "13.79")])
    assert len(together) == 1


def test_group_by_price_level_buckets_are_date_sorted() -> None:
    """A bucket comes back ordered by date_key, not by amount (regression)."""
    amounts = ["12.99", "12.50", "12.80", "12.00"]
    rows = [_row(i, START + timedelta(days=30 * i), a) for i, a in enumerate(amounts)]
    buckets = zs.group_by_price_level(rows)
    assert len(buckets) == 1
    assert _refs(buckets[0]) == ["t.csv:0", "t.csv:1", "t.csv:2", "t.csv:3"]


def test_longest_cadence_run_skips_interleaved_rows() -> None:
    """E4 dates give the run [Jan-01, Feb-01, Mar-01] without any stride step."""
    days = [date(2026, 1, 1), date(2026, 1, 15), date(2026, 2, 1)]
    days += [date(2026, 2, 15), date(2026, 3, 1), date(2026, 3, 15)]
    rows = [_row(i, d, "10.99") for i, d in enumerate(days)]
    run = zs.longest_cadence_run(rows, MONTHLY)
    assert _refs(run) == ["t.csv:0", "t.csv:2", "t.csv:4"]


@pytest.mark.parametrize("name", ["weekly", "monthly", "quarterly", "yearly"])
def test_longest_cadence_run_per_interval(name: str) -> None:
    """Each interval accepts nominal, nominal + 3 and nominal - 3 day gaps."""
    nominal = zs.INTERVALS_BY_NAME[name]["nominal"]
    offsets = [0]
    for gap in (nominal, nominal + 3, nominal - 3):
        offsets.append(offsets[-1] + gap)
    rows = _rows_at(offsets)
    assert len(zs.longest_cadence_run(rows, zs.INTERVALS_BY_NAME[name])) == 4


# --- Tier 2 -----------------------------------------------------------------------------------


def test_longest_cadence_run_empty_and_single_row() -> None:
    """No rows give an empty run; one row gives a run of that row."""
    assert zs.longest_cadence_run([], MONTHLY) == []
    single = _rows_at([0])
    assert zs.longest_cadence_run(single, MONTHLY) == single


@pytest.mark.parametrize(("gap", "expected_len"), [(26, 1), (27, 2), (33, 2), (34, 1)])
def test_gap_boundaries_inclusive(gap: int, expected_len: int) -> None:
    """Monthly gaps 27 and 33 are accepted; 26 and 34 are rejected."""
    rows = _rows_at([0, gap])
    assert len(zs.longest_cadence_run(rows, MONTHLY)) == expected_len


def test_group_by_price_level_empty() -> None:
    """No rows give no buckets."""
    assert zs.group_by_price_level([]) == []


def test_duplicate_source_ref_rows_do_not_crash() -> None:
    """Two rows with the same source_ref are handled by both primitives."""
    first = _row(0, START)
    twin = dict(first)
    rows = [first, twin, _row(1, START + timedelta(days=30))]
    assert isinstance(zs.group_by_price_level(rows), list)
    assert isinstance(zs.longest_cadence_run(rows, MONTHLY), list)


# --- Tier 3 -----------------------------------------------------------------------------------

_ROW_SPECS = st.lists(
    st.tuples(st.integers(min_value=0, max_value=400), st.integers(min_value=1, max_value=100000)),
    max_size=30,
)


def _rows_from_specs(specs: list[tuple[int, int]]) -> list[dict]:
    """Build rows from (day offset, amount in cents) pairs; source_row is the list index."""
    return [
        _row(i, START + timedelta(days=d), Decimal(cents) / Decimal(100))
        for i, (d, cents) in enumerate(specs)
    ]


@settings(max_examples=200, deadline=None)
@given(specs=_ROW_SPECS)
def test_buckets_partition_rows(specs: list[tuple[int, int]]) -> None:
    """Every row lands in exactly one bucket and every bucket is date-sorted."""
    rows = _rows_from_specs(specs)
    buckets = zs.group_by_price_level(rows)
    flat = [r["source_ref"] for bucket in buckets for r in bucket]
    assert sorted(flat) == sorted(r["source_ref"] for r in rows)
    for bucket in buckets:
        assert bucket == sorted(bucket, key=zs.date_key)


@settings(max_examples=200, deadline=None)
@given(
    offsets=st.lists(st.integers(min_value=0, max_value=800), max_size=30),
    name=st.sampled_from(["weekly", "monthly", "quarterly", "yearly"]),
)
def test_run_is_subsequence_with_valid_gaps(offsets: list[int], name: str) -> None:
    """The run is an ordered subsequence of the input and every gap fits the interval."""
    interval = zs.INTERVALS_BY_NAME[name]
    rows = sorted(_rows_at(offsets), key=zs.date_key)
    run = zs.longest_cadence_run(rows, interval)
    positions = [rows.index(r) for r in run]
    assert positions == sorted(positions)
    for earlier, later in zip(run, run[1:], strict=False):
        gap = (later["date"] - earlier["date"]).days
        assert abs(gap - interval["nominal"]) <= zs.INTERVAL_TOLERANCE_DAYS


@settings(max_examples=200, deadline=None)
@given(specs=_ROW_SPECS, data=st.data())
def test_bucket_membership_independent_of_input_order(
    specs: list[tuple[int, int]], data: st.DataObject
) -> None:
    """Shuffling the input rows does not change the buckets."""
    rows = _rows_from_specs(specs)
    shuffled = data.draw(st.permutations(rows))
    expected = [_refs(b) for b in zs.group_by_price_level(rows)]
    assert [_refs(b) for b in zs.group_by_price_level(list(shuffled))] == expected
