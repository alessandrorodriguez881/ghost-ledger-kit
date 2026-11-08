"""Tests for compute_zombie_cost and ZombieCostResult (Task Z15)."""

from datetime import date, timedelta
from decimal import Decimal

import pandas as pd
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from apps.zombie_subscriptions.detectors import utils as zs
from apps.zombie_subscriptions.detectors.utils import ZombieCostResult, compute_zombie_cost
from ledger_kit.detectors import loaded_source_refs
from ledger_kit.utils.money import round_to_cents

START = date(2026, 1, 5)
PROP = settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
ALIASES = {"STREAMING": ["STREAMFLIX INTL", "STREAMFLIXCOM"]}
_SERVICES = ["CLOUDVAULT", "MUSICBOX", "GYMPLUS", "NOSUCHSERVICE"]


def _rows_at(
    entries: list[tuple[int, str | Decimal]], counterparty: str = "CLOUDVAULT", first_row: int = 0
) -> list[dict]:
    """Build rows from (day offset from START, amount) pairs numbered from first_row."""
    return [
        {
            "date": START + timedelta(days=offset),
            "amount": Decimal(amount),
            "counterparty": counterparty,
            "source_ref": f"f.csv:{first_row + i}",
            "source_row": first_row + i,
        }
        for i, (offset, amount) in enumerate(entries)
    ]


@st.composite
def _scenarios(draw: st.DrawFn) -> tuple[list[dict], dict[str, date]]:
    """Random debit rows over three merchants plus last-used dates for some services."""
    entries = draw(
        st.lists(
            st.tuples(
                st.sampled_from(_SERVICES[:3]),
                st.integers(min_value=0, max_value=400),
                st.integers(min_value=1, max_value=50000),
            ),
            max_size=25,
        )
    )
    rows = [
        {
            "date": START + timedelta(days=offset),
            "amount": Decimal(cents) / Decimal(100),
            "counterparty": merchant,
            "source_ref": f"f.csv:{i}",
            "source_row": i,
        }
        for i, (merchant, offset, cents) in enumerate(entries)
    ]
    offsets = draw(
        st.dictionaries(st.sampled_from(_SERVICES), st.integers(min_value=0, max_value=400))
    )
    return rows, {k: START + timedelta(days=v) for k, v in offsets.items()}


# --- Tier 1 ------------------------------------------------------------------------------------


def test_cost_is_sum_of_rows_after_last_used(ledger_with_zombie: pd.DataFrame, builders) -> None:
    """The last two of three 12.99 charges follow the last-used date: 25.98."""
    last_used = {"CLOUDVAULT": builders.zombie_last_used_date}
    (result,) = compute_zombie_cost(ledger_with_zombie, last_used)
    assert isinstance(result, ZombieCostResult)
    assert result.canonical_name == "CLOUDVAULT"
    assert result.last_used_date == builders.zombie_last_used_date
    assert result.cost_since_last_used == Decimal("25.98")


def test_source_refs_are_the_rows_after_last_used_sorted_by_date_row(
    ledger_with_zombie: pd.DataFrame, builders
) -> None:
    """The cited refs are exactly the rows after the last-used date."""
    last_used = {"CLOUDVAULT": builders.zombie_last_used_date}
    (result,) = compute_zombie_cost(ledger_with_zombie, last_used)
    assert result.source_refs == ["zs_fixture.csv:1", "zs_fixture.csv:2"]


def test_source_refs_ordered_by_date_then_row_not_as_text() -> None:
    """Refs follow (date, source_row): f.csv:10 on the earlier date comes before f.csv:9."""
    rows = _rows_at([(10, "5.00"), (20, "6.00"), (30, "7.00")])
    for row, number in zip(rows, [10, 9, 11], strict=True):
        row["source_row"] = number
        row["source_ref"] = f"f.csv:{number}"
    (result,) = compute_zombie_cost(pd.DataFrame(rows), {"CLOUDVAULT": START})
    assert result.source_refs == ["f.csv:10", "f.csv:9", "f.csv:11"]
    assert result.cost_since_last_used == Decimal("18.00")


def test_yearly_cost_from_active_series(ledger_with_zombie: pd.DataFrame, builders) -> None:
    """Yearly cost is the active series' current amount times 12: 12.99 x 12."""
    last_used = {"CLOUDVAULT": builders.zombie_last_used_date}
    (result,) = compute_zombie_cost(ledger_with_zombie, last_used)
    assert result.yearly_cost == Decimal("155.88")


def test_charge_on_last_used_date_excluded(ledger_with_zombie: pd.DataFrame) -> None:
    """A charge on the last-used date is not counted (strictly after)."""
    # The second charge is dated 2026-02-09.
    (result,) = compute_zombie_cost(ledger_with_zombie, {"CLOUDVAULT": date(2026, 2, 9)})
    assert result.source_refs == ["zs_fixture.csv:2"]
    assert result.cost_since_last_used == Decimal("12.99")


def test_two_aliased_keys_give_one_result(ledger_with_aliased_duplicate: pd.DataFrame) -> None:
    """A service with two aliased keys yields one result covering both keys."""
    results = compute_zombie_cost(
        ledger_with_aliased_duplicate, {"STREAMING": date(2026, 2, 10)}, aliases=ALIASES
    )
    assert len(results) == 1
    (result,) = results
    assert result.canonical_name == "STREAMING"
    assert result.source_refs == [f"zs_fixture.csv:{i}" for i in (3, 4, 5)]
    assert result.cost_since_last_used == Decimal("44.97")
    assert result.yearly_cost == Decimal("359.76")


# --- Tier 2 ------------------------------------------------------------------------------------


def test_empty_ledger_returns_zero_cost_entries(empty_ledger: pd.DataFrame) -> None:
    """A service with no rows still yields an entry with zero cost and no refs."""
    (result,) = compute_zombie_cost(empty_ledger, {"CLOUDVAULT": date(2026, 1, 1)})
    assert result.canonical_name == "CLOUDVAULT"
    assert result.last_used_date == date(2026, 1, 1)
    assert result.cost_since_last_used == Decimal("0.00")
    assert str(result.cost_since_last_used) == "0.00"
    assert result.source_refs == []
    assert result.yearly_cost == Decimal("0.00")
    assert str(result.yearly_cost) == "0.00"


@pytest.mark.parametrize("last_used", [None, {}])
def test_last_used_dates_none_returns_empty_list(
    ledger_with_zombie: pd.DataFrame, last_used: dict[str, date] | None
) -> None:
    """No last-used dates (None or empty) give an empty list."""
    assert compute_zombie_cost(ledger_with_zombie, last_used) == []


def test_last_used_after_all_charges_is_zero_cost_not_omitted(
    ledger_with_zombie: pd.DataFrame,
) -> None:
    """A last-used date after every charge keeps the entry, with zero cost."""
    (result,) = compute_zombie_cost(ledger_with_zombie, {"CLOUDVAULT": date(2026, 12, 31)})
    assert result.cost_since_last_used == Decimal("0.00")
    assert result.source_refs == []
    assert result.yearly_cost == Decimal("155.88")


def test_service_absent_from_ledger_is_zero_cost(ledger_with_zombie: pd.DataFrame) -> None:
    """A service that has no rows in a non-empty ledger still gets a zero-cost entry."""
    (result,) = compute_zombie_cost(ledger_with_zombie, {"NOSUCHSERVICE": date(2026, 1, 1)})
    assert result.cost_since_last_used == Decimal("0.00")
    assert result.source_refs == []
    assert result.yearly_cost == Decimal("0.00")


def test_single_row_ledger(single_row_ledger: pd.DataFrame) -> None:
    """One row after the last-used date is the whole cost; no series, so yearly cost is 0.00."""
    (result,) = compute_zombie_cost(single_row_ledger, {"CLOUDVAULT": date(2026, 1, 1)})
    assert result.cost_since_last_used == Decimal("12.99")
    assert result.source_refs == ["zs_fixture.csv:0"]
    assert result.yearly_cost == Decimal("0.00")


def test_duplicate_source_ref_handled(ledger_with_zombie: pd.DataFrame, builders) -> None:
    """A repeated row is cited and summed once."""
    doubled = pd.concat([ledger_with_zombie, ledger_with_zombie.iloc[[2]]])
    last_used = {"CLOUDVAULT": builders.zombie_last_used_date}
    (result,) = compute_zombie_cost(doubled, last_used)
    assert result.source_refs == ["zs_fixture.csv:1", "zs_fixture.csv:2"]
    assert result.cost_since_last_used == Decimal("25.98")


def test_no_system_clock_read(
    ledger_with_zombie: pd.DataFrame, builders, monkeypatch: pytest.MonkeyPatch
) -> None:
    """compute_zombie_cost never asks the system clock for today's date."""
    last_used = {"CLOUDVAULT": builders.zombie_last_used_date}
    expected = compute_zombie_cost(ledger_with_zombie, last_used)

    class _NoClockDate(date):
        """A date type whose today() fails the test."""

        @classmethod
        def today(cls) -> date:
            raise AssertionError("the system clock was read")

    monkeypatch.setattr(zs, "date", _NoClockDate)
    assert compute_zombie_cost(ledger_with_zombie, last_used) == expected


# --- Tier 3 ------------------------------------------------------------------------------------


@PROP
@given(scenario=_scenarios())
def test_cost_equals_sum_of_cited_row_amounts(scenario: tuple[list[dict], dict[str, date]]) -> None:
    """cost_since_last_used is the sum of the cited rows, all dated after the last-used date."""
    rows, last_used = scenario
    by_ref = {r["source_ref"]: r for r in rows}
    results = compute_zombie_cost(pd.DataFrame(rows), last_used)
    assert [r.canonical_name for r in results] == list(last_used)
    for result in results:
        cited = [by_ref[ref] for ref in result.source_refs]
        total = round_to_cents(sum((r["amount"] for r in cited), Decimal("0.00")))
        assert result.cost_since_last_used == total
        assert all(r["date"] > result.last_used_date for r in cited)
        assert all(r["counterparty"] == result.canonical_name for r in cited)


@PROP
@given(scenario=_scenarios())
def test_source_refs_subset_of_input(scenario: tuple[list[dict], dict[str, date]]) -> None:
    """No invention: every cited source_ref belongs to the loaded ledger."""
    rows, last_used = scenario
    ledger = pd.DataFrame(rows)
    known = loaded_source_refs(ledger, {})
    for result in compute_zombie_cost(ledger, last_used):
        assert set(result.source_refs) <= known


@PROP
@given(scenario=_scenarios(), data=st.data())
def test_row_order_invariant(
    scenario: tuple[list[dict], dict[str, date]], data: st.DataObject
) -> None:
    """Shuffled rows give the same results."""
    rows, last_used = scenario
    shuffled = data.draw(st.permutations(rows))
    expected = compute_zombie_cost(pd.DataFrame(rows), last_used)
    assert compute_zombie_cost(pd.DataFrame(list(shuffled)), last_used) == expected
