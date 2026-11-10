"""Tests for interval classification and run finding (Task VF4)."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from hypothesis import given, settings

from apps.vampire_fees.detectors.utils import (
    INTERVALS,
    Fee,
    classify_gap,
    extract_fees,
    find_run,
    yearly_cost,
)
from apps.vampire_fees.tests.vf_builders import (
    default_vocabulary,
    make_ledger,
    regular_series_strategy,
    series_rows,
)

START = date(2026, 1, 1)
BY_NAME = {interval.name: interval for interval in INTERVALS}


def fees_on(*days: date) -> list[Fee]:
    """Return the Fee list of maintenance debits on the given days (5.00 each)."""
    rows = series_rows([(day, "5.00") for day in days])
    return extract_fees(make_ledger(rows), default_vocabulary())


def with_gaps(*gaps: int, start: date = START) -> list[Fee]:
    """Return fees whose consecutive date gaps are `gaps` (so len(gaps) + 1 fees)."""
    days = [start]
    for gap in gaps:
        days.append(days[-1] + timedelta(days=gap))
    return fees_on(*days)


# --- Tier 1 ---------------------------------------------------------------------------------


@pytest.mark.parametrize(("days", "name"), [(30, "monthly"), (91, "quarterly"), (365, "yearly")])
def test_classify_gap_nominal_values(days: int, name: str) -> None:
    """The nominal gaps classify as their interval."""
    interval = classify_gap(days)
    assert interval is not None and interval.name == name


# --- Tier 2: both sides of every boundary -----------------------------------------------------


@pytest.mark.parametrize(
    ("days", "name"),
    [
        (26, None),
        (27, "monthly"),
        (33, "monthly"),
        (34, None),
        (87, None),
        (88, "quarterly"),
        (94, "quarterly"),
        (95, None),
        (359, None),
        (360, "yearly"),
        (370, "yearly"),
        (371, None),
        (0, None),
        (200, None),
        (-5, None),
    ],
)
def test_classify_gap_boundaries(days: int, name: str | None) -> None:
    """Both sides of every tolerance boundary; zero, negative and in-between gaps match nothing."""
    interval = classify_gap(days)
    assert (interval.name if interval else None) == name


def test_find_run_needs_two_rows() -> None:
    """Zero and one row have no run."""
    assert find_run([]) is None
    assert find_run(fees_on(START)) is None


def test_two_monthly_rows_are_no_run_three_are() -> None:
    """MIN_CHARGES_MONTHLY is 3."""
    assert find_run(with_gaps(30)) is None
    found = find_run(with_gaps(30, 30))
    assert found is not None
    interval, rows = found
    assert interval.name == "monthly" and len(rows) == 3


def test_two_quarterly_and_two_yearly_rows_are_a_run() -> None:
    """MIN_CHARGES_QUARTERLY and MIN_CHARGES_YEARLY are 2."""
    quarterly = find_run(with_gaps(91))
    yearly = find_run(with_gaps(367))
    assert quarterly is not None and quarterly[0].name == "quarterly" and len(quarterly[1]) == 2
    assert yearly is not None and yearly[0].name == "yearly" and len(yearly[1]) == 2


def test_ae_vf_12_gaps_of_33_and_34() -> None:
    """AE-VF-12: gaps 33 and 31 are a run; 34 and 31 are not."""
    assert find_run(fees_on(date(2026, 1, 1), date(2026, 2, 3), date(2026, 3, 6))) is not None
    assert find_run(fees_on(date(2026, 1, 1), date(2026, 2, 4), date(2026, 3, 7))) is None


def test_ae_vf_13_outlier_before_a_regular_suffix_is_left_out() -> None:
    """AE-VF-13: only the three later rows are in the run (REQ-VF-20)."""
    fees = fees_on(date(2025, 10, 1), date(2026, 1, 5), date(2026, 2, 5), date(2026, 3, 5))
    found = find_run(fees)
    assert found is not None
    assert found[1] == fees[1:]


def test_ae_vf_14_quarterly_gaps_91_and_92() -> None:
    """AE-VF-14: 91 and 92 days are a quarterly run of 3."""
    found = find_run(fees_on(date(2026, 3, 31), date(2026, 6, 30), date(2026, 9, 30)))
    assert found is not None and found[0].name == "quarterly" and len(found[1]) == 3


def test_ae_vf_16_irregular_last_gap_has_no_run() -> None:
    """AE-VF-16: gaps 104, 196 and 205 match no interval."""
    assert find_run(with_gaps(104, 196, 205)) is None


def test_two_rows_on_the_same_date_end_the_run() -> None:
    """A gap of 0 days matches nothing: it ends the run, or leaves none when it is the last."""
    fees = fees_on(START, START, START + timedelta(days=30), START + timedelta(days=60))
    found = find_run(fees)
    assert found is not None and found[1] == fees[1:]
    fees = fees_on(
        START, START + timedelta(days=30), START + timedelta(days=60), START + timedelta(days=60)
    )
    assert find_run(fees) is None


def test_run_stops_at_a_gap_of_another_interval() -> None:
    """Monthly gaps after a quarterly one: the run is the monthly suffix only."""
    fees = with_gaps(91, 30, 30, 31)
    found = find_run(fees)
    assert found is not None and found[0].name == "monthly" and found[1] == fees[1:]


def test_yearly_cost_examples() -> None:
    """5.00 monthly 60.00; 9.00 quarterly 36.00; 30.00 yearly 30.00; 4.99 monthly 59.88."""
    assert yearly_cost(Decimal("5.00"), BY_NAME["monthly"]) == Decimal("60.00")
    assert yearly_cost(Decimal("9.00"), BY_NAME["quarterly"]) == Decimal("36.00")
    assert yearly_cost(Decimal("30.00"), BY_NAME["yearly"]) == Decimal("30.00")
    assert yearly_cost(Decimal("4.99"), BY_NAME["monthly"]) == Decimal("59.88")


# --- Tier 3 -----------------------------------------------------------------------------------


@settings(max_examples=200)
@given(rows=regular_series_strategy())
def test_a_run_is_a_matching_suffix_of_the_input(rows: list[dict]) -> None:
    """The run is a suffix, is long enough and all its consecutive gaps match its interval."""
    fees = extract_fees(make_ledger(rows), default_vocabulary())
    found = find_run(fees)
    if found is None:
        return
    interval, run = found
    assert run == fees[len(fees) - len(run) :]
    assert len(run) >= interval.min_charges
    for earlier, later in zip(run, run[1:], strict=False):
        gap = (later.date - earlier.date).days
        assert abs(gap - interval.nominal_days) <= interval.tolerance_days
