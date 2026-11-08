"""Tests for is_active and service_yearly_cost (Task Z9)."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from apps.zombie_subscriptions.detectors import utils as zs

START = date(2026, 1, 5)


def _periodic(
    counterparty: str,
    amounts: list[str],
    *,
    step_days: int = 30,
    start_offset: int = 0,
    first_row: int = 0,
) -> list[dict]:
    """Build rows `step_days` apart from START + start_offset, numbered from first_row."""
    return [
        {
            "date": START + timedelta(days=start_offset + step_days * i),
            "amount": Decimal(amount),
            "counterparty": counterparty,
            "source_ref": f"t.csv:{first_row + i}",
            "source_row": first_row + i,
        }
        for i, amount in enumerate(amounts)
    ]


def _series(amounts: list[str], step_days: int = 30) -> zs.Series:
    """Return the single series found in a periodic run of `amounts`."""
    found = zs.find_series(_periodic("CLOUDVAULT", amounts, step_days=step_days))
    assert len(found) == 1
    return found[0]


# --- Tier 1 ------------------------------------------------------------------------------------


def test_is_active_within_nominal_plus_tolerance() -> None:
    """A series whose last charge is recent is active, on the day itself and 30 days later."""
    series = _series(["12.99"] * 3)
    last = series.rows[-1]["date"]
    assert zs.is_active(series, last)
    assert zs.is_active(series, last + timedelta(days=30))


@pytest.mark.parametrize(
    ("step_days", "count", "limit"),
    [(7, 4, 10), (30, 3, 33), (91, 2, 94), (365, 2, 368)],
)
def test_is_active_boundary_inclusive(step_days: int, count: int, limit: int) -> None:
    """Exactly nominal + 3 days after the last charge is active, one more day is not."""
    series = _series(["9.99"] * count, step_days=step_days)
    assert series.nominal_days + zs.INTERVAL_TOLERANCE_DAYS == limit
    last = series.rows[-1]["date"]
    assert zs.is_active(series, last + timedelta(days=limit))
    assert not zs.is_active(series, last + timedelta(days=limit + 1))


def test_service_yearly_cost_sums_active_series_only() -> None:
    """Active monthly and weekly series are summed; a dormant series adds nothing."""
    monthly = _periodic("CLOUDVAULT", ["12.99"] * 3, first_row=0)  # last charge START + 60
    weekly = _periodic("WEEKLYCO", ["2.00"] * 4, step_days=7, start_offset=42, first_row=10)
    dormant = _periodic("OLDSERVICE", ["5.00"] * 3, start_offset=-330, first_row=20)
    groups = [("CLOUDVAULT", monthly), ("OLDSERVICE", dormant), ("WEEKLYCO", weekly)]
    max_date = START + timedelta(days=63)  # last weekly charge
    # 12.99 x 12 = 155.88 and 2.00 x 52 = 104.00; the dormant 5.00 series is left out.
    assert zs.service_yearly_cost(groups, max_date) == Decimal("259.88")


# --- Tier 2 ------------------------------------------------------------------------------------


def test_service_yearly_cost_no_series_is_zero() -> None:
    """Keys without a series, and no keys at all, cost 0.00."""
    two_charges = _periodic("SUPERMART", ["87.50", "143.20"])
    assert str(zs.service_yearly_cost([("SUPERMART", two_charges)], START)) == "0.00"
    assert str(zs.service_yearly_cost([], START)) == "0.00"


def test_service_yearly_cost_max_date_none_is_zero() -> None:
    """An unknown ledger maximum date (empty ledger) gives 0.00 even with rows present."""
    rows = _periodic("CLOUDVAULT", ["12.99"] * 3)
    assert str(zs.service_yearly_cost([("CLOUDVAULT", rows)], None)) == "0.00"


def test_service_yearly_cost_two_aliased_keys_found_per_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Series are found once per key; the rows of two keys never reach one find_series call."""
    intl = _periodic("STREAMFLIX INTL", ["14.99"] * 3, first_row=0)
    com = _periodic("STREAMFLIXCOM", ["14.99"] * 3, start_offset=15, first_row=10)
    calls: list[set[str]] = []
    original = zs.find_series

    def spy(rows: list[dict]) -> list[zs.Series]:
        """Record the counterparties of one call, then delegate to the real function."""
        calls.append({r["counterparty"] for r in rows})
        return original(rows)

    monkeypatch.setattr(zs, "find_series", spy)
    groups = [("STREAMFLIX INTL", intl), ("STREAMFLIXCOM", com)]
    total = zs.service_yearly_cost(groups, START + timedelta(days=75))
    assert total == Decimal("359.76")  # 2 x (14.99 x 12)
    assert calls == [{"STREAMFLIX INTL"}, {"STREAMFLIXCOM"}]


# --- Tier 3 ------------------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(
    first=st.integers(min_value=0, max_value=120),
    second=st.integers(min_value=0, max_value=120),
)
def test_is_active_monotone_in_max_date(first: int, second: int) -> None:
    """If a series is active at a later max_date it is also active at every earlier one."""
    series = _series(["12.99"] * 3)
    last = series.rows[-1]["date"]
    early, late = sorted((first, second))
    if zs.is_active(series, last + timedelta(days=late)):
        assert zs.is_active(series, last + timedelta(days=early))
