"""Tests for the ledger helpers in detectors/utils.py (Task Z3)."""

from datetime import date, timedelta
from decimal import Decimal

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from apps.zombie_subscriptions.detectors.utils import (
    date_key,
    group_by_canonical,
    group_by_normalised_key,
    ledger_max_date,
    median,
    ppy_for,
    sorted_source_refs,
)
from ledger_kit.ingestion.normaliser import CANONICAL_COLUMNS

ALIASES = {"STREAMING": ["STREAMFLIX INTL", "STREAMFLIXCOM"]}


def _row(
    source_ref: str,
    day: date,
    counterparty: str = "CLOUDVAULT",
    amount: str = "12.99",
) -> dict:
    """Build one synthetic debit row as a plain dict with the canonical columns."""
    source_file, source_row = source_ref.rsplit(":", 1)
    return {
        "id": f"id-{source_ref}",
        "date": day,
        "amount": Decimal(amount),
        "flow": "debit",
        "currency": "EUR",
        "counterparty": counterparty,
        "description": "synthetic",
        "iban": None,
        "source_file": source_file,
        "source_row": int(source_row),
        "source_ref": source_ref,
        "tags": [],
    }


def _ledger(rows: list[dict]) -> pd.DataFrame:
    """Build a ledger DataFrame with the canonical columns from row dicts."""
    return pd.DataFrame(rows, columns=list(CANONICAL_COLUMNS))


# --- Tier 1 -----------------------------------------------------------------------------------


def test_date_key_orders_by_date_then_source_row() -> None:
    """date_key sorts by date first and by source_row (an int) second."""
    a = _row("f.csv:10", date(2026, 1, 1))
    b = _row("f.csv:9", date(2026, 1, 1))
    c = _row("f.csv:1", date(2026, 1, 2))
    assert date_key(a) == (date(2026, 1, 1), 10)
    assert sorted([c, a, b], key=date_key) == [b, a, c]


def test_sorted_source_refs_by_date_not_text() -> None:
    """Refs follow (date, source_row), never the text order where 'f.csv:10' < 'f.csv:9'."""
    consecutive_days = [
        _row("f.csv:10", date(2026, 1, 2)),
        _row("f.csv:9", date(2026, 1, 1)),
    ]
    assert sorted_source_refs(consecutive_days) == ["f.csv:9", "f.csv:10"]

    same_day = [_row("f.csv:10", date(2026, 1, 1)), _row("f.csv:9", date(2026, 1, 1))]
    assert sorted_source_refs(same_day) == ["f.csv:9", "f.csv:10"]


def test_group_by_normalised_key_groups_and_sorts() -> None:
    """Keys come out alphabetically and each group's rows are ordered by date_key."""
    ledger = _ledger(
        [
            _row("f.csv:0", date(2026, 3, 1), "ZETA SHOP 99"),
            _row("f.csv:1", date(2026, 1, 1), "Alpha Shop"),
            _row("f.csv:2", date(2026, 1, 1), "Zeta Shop"),
            _row("f.csv:3", date(2026, 2, 1), "ALPHA SHOP 7"),
        ]
    )
    groups = group_by_normalised_key(ledger)
    assert [key for key, _ in groups] == ["ALPHA SHOP", "ZETA SHOP"]
    assert [r["source_ref"] for r in groups[0][1]] == ["f.csv:1", "f.csv:3"]
    assert [r["source_ref"] for r in groups[1][1]] == ["f.csv:2", "f.csv:0"]


def test_group_by_canonical_collects_aliased_keys() -> None:
    """Two aliased keys land under one canonical name, each keeping its own rows."""
    ledger = _ledger(
        [
            _row("f.csv:0", date(2026, 1, 5), "STREAMFLIXCOM"),
            _row("f.csv:1", date(2026, 1, 6), "STREAMFLIX INTL 7731"),
            _row("f.csv:2", date(2026, 2, 5), "STREAMFLIXCOM"),
            _row("f.csv:3", date(2026, 1, 7), "CLOUDVAULT"),
        ]
    )
    grouped = group_by_canonical(ledger, ALIASES)
    assert set(grouped) == {"STREAMING", "CLOUDVAULT"}
    streaming = grouped["STREAMING"]
    assert [key for key, _ in streaming] == ["STREAMFLIX INTL", "STREAMFLIXCOM"]
    assert [r["source_ref"] for r in streaming[0][1]] == ["f.csv:1"]
    assert [r["source_ref"] for r in streaming[1][1]] == ["f.csv:0", "f.csv:2"]
    assert [key for key, _ in grouped["CLOUDVAULT"]] == ["CLOUDVAULT"]


def test_ppy_for_all_interval_types() -> None:
    """Periods per year: weekly 52, monthly 12, quarterly 4, yearly 1."""
    assert ppy_for("weekly") == 52
    assert ppy_for("monthly") == 12
    assert ppy_for("quarterly") == 4
    assert ppy_for("yearly") == 1


def test_ledger_max_date() -> None:
    """The latest date of the ledger is returned."""
    ledger = _ledger([_row("f.csv:0", date(2026, 1, 1)), _row("f.csv:1", date(2026, 5, 9))])
    assert ledger_max_date(ledger) == date(2026, 5, 9)


def test_median_odd_even_decimal() -> None:
    """The median of an odd count is the middle value; of an even count the middle mean."""
    assert median([Decimal("3"), Decimal("1"), Decimal("2")]) == Decimal("2")
    assert median([Decimal("4"), Decimal("1"), Decimal("3"), Decimal("2")]) == Decimal("2.5")
    assert median([Decimal("10.00"), Decimal("10.10")]) == Decimal("10.05")
    assert median([Decimal("12.99")]) == Decimal("12.99")


# --- Tier 2 -----------------------------------------------------------------------------------


def test_group_helpers_empty_ledger_return_empty(empty_ledger: pd.DataFrame) -> None:
    """Empty ledgers yield empty groupings, never an error."""
    assert group_by_normalised_key(empty_ledger) == []
    assert group_by_canonical(empty_ledger, ALIASES) == {}
    assert group_by_canonical(empty_ledger, None) == {}


def test_ledger_max_date_empty_returns_none(empty_ledger: pd.DataFrame) -> None:
    """An empty ledger has no maximum date (and the clock is never read)."""
    assert ledger_max_date(empty_ledger) is None


def test_sorted_source_refs_dedupes_duplicate_source_ref() -> None:
    """Two rows with the same source_ref produce the reference once."""
    rows = [
        _row("f.csv:1", date(2026, 1, 2)),
        _row("f.csv:1", date(2026, 1, 1)),
        _row("f.csv:2", date(2026, 1, 3)),
    ]
    assert sorted_source_refs(rows) == ["f.csv:1", "f.csv:2"]
    assert sorted_source_refs([]) == []


def test_single_row_ledger_groups(single_row_ledger: pd.DataFrame) -> None:
    """One row gives one group of one row."""
    groups = group_by_normalised_key(single_row_ledger)
    assert len(groups) == 1
    assert groups[0][0] == "CLOUDVAULT"
    assert len(groups[0][1]) == 1
    assert list(group_by_canonical(single_row_ledger, None)) == ["CLOUDVAULT"]


def test_median_of_empty_list_raises() -> None:
    """median() has no value for an empty list."""
    with pytest.raises(ValueError, match="at least one"):
        median([])


# --- Tier 3 -----------------------------------------------------------------------------------


@given(
    entries=st.lists(
        st.tuples(st.text(alphabet="abXY 12", max_size=6), st.integers(0, 400)),
        max_size=20,
    )
)
@settings(max_examples=200)
def test_group_by_normalised_key_partitions_rows(entries: list[tuple[str, int]]) -> None:
    """Every input row appears in exactly one group; keys are unique; rows are date-sorted."""
    start = date(2026, 1, 1)
    rows = [
        _row(f"p.csv:{i}", start + timedelta(days=offset), counterparty)
        for i, (counterparty, offset) in enumerate(entries)
    ]
    groups = group_by_normalised_key(_ledger(rows))

    keys = [key for key, _ in groups]
    assert keys == sorted(set(keys))
    grouped_refs = [r["source_ref"] for _, group_rows in groups for r in group_rows]
    assert sorted(grouped_refs) == sorted(r["source_ref"] for r in rows)
    for _, group_rows in groups:
        assert group_rows == sorted(group_rows, key=date_key)
