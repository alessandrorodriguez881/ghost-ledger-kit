"""Tests for the duplicate-subscription detector (Task Z12)."""

from datetime import date, timedelta
from decimal import Decimal
from types import MappingProxyType, SimpleNamespace
from typing import Any

import pandas as pd
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from apps.zombie_subscriptions.detectors.duplicate_subscription import (
    detect_duplicate_subscriptions,
)
from ledger_kit.detectors import loaded_source_refs
from ledger_kit.models import Alert
from ledger_kit.utils.money import round_to_cents

START = date(2026, 1, 5)
PROP = settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
STREAMING = {"STREAMING": ["STREAMFLIX INTL", "STREAMFLIXCOM"]}


def _ctx(aliases: dict[str, list[str]] | None = None) -> MappingProxyType:
    """Build the read-only context the registry passes to a detector."""
    return MappingProxyType({"aliases": aliases})


def _rows_at(
    entries: list[tuple[int, str | Decimal]], counterparty: str = "MUSICBOX", first_row: int = 0
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


def _stream(
    amount: str,
    start_offset: int,
    count: int = 3,
    counterparty: str = "MUSICBOX",
    first_row: int = 0,
) -> list[dict]:
    """Build `count` monthly charges of `amount`, the first on START + start_offset."""
    entries = [(start_offset + 30 * i, amount) for i in range(count)]
    return _rows_at(entries, counterparty, first_row)


def _amount(base_cents: int, bps: int) -> Decimal:
    """Return base_cents scaled by (1 + bps / 10000), as euros rounded to cents."""
    return round_to_cents(Decimal(base_cents * (10000 + bps)) / Decimal(1_000_000))


_STEP = st.tuples(st.integers(25, 35), st.integers(-15, 15))
_MERCHANTS = ["CLOUDVAULT", "STREAMFLEX INTL", "MUSICBOX", "GLOWBILL"]
_ALIASES = st.sampled_from([None, {"STREAMING": ["CLOUDVAULT", "MUSICBOX"]}])


@st.composite
def _ledger_rows(draw: st.DrawFn) -> list[dict]:
    """Random debit rows: one to three near-monthly streams, some of them parallel."""
    rows: list[dict] = []
    for merchant in draw(st.lists(st.sampled_from(_MERCHANTS), min_size=1, max_size=3)):
        offset = draw(st.integers(min_value=0, max_value=60))
        base_cents = draw(st.integers(min_value=500, max_value=20000))
        entries = [(offset, _amount(base_cents, 0))]
        for gap, pct in draw(st.lists(_STEP, max_size=7)):
            offset += gap
            entries.append((offset, _amount(base_cents, pct * 100)))
        rows.extend(_rows_at(entries, merchant, first_row=len(rows)))
    return rows


def _by_id(alerts: list[Alert]) -> list[Alert]:
    """Order alerts by their deterministic id for order-agnostic comparison."""
    return sorted(alerts, key=lambda a: a.id)


# --- Tier 1 ------------------------------------------------------------------------------------


def test_zs_acceptance_e4_duplicate_alert_without_aliases(
    ledger_with_duplicate_sub: pd.DataFrame,
) -> None:
    """E4: two interleaved 10.99 series under one key give one alert, no aliases needed."""
    (alert,) = detect_duplicate_subscriptions(ledger_with_duplicate_sub, _ctx())
    assert alert.detector == "zs.duplicate_subscription"
    assert alert.severity == "warning"
    assert alert.title == "Duplicate subscription: MUSICBOX"
    assert alert.source_refs == [f"zs_fixture.csv:{i}" for i in range(6)]
    assert alert.data == {
        "canonical_name": "MUSICBOX",
        "series_count": 2,
        "series_counterparties": ["MUSICBOX", "MUSICBOX"],
        "yearly_cost": "263.76",
    }


def test_zs_acceptance_e5_aliased_duplicate_alert(
    ledger_with_aliased_duplicate: pd.DataFrame,
) -> None:
    """E5: two aliased keys give one alert under the canonical name."""
    (alert,) = detect_duplicate_subscriptions(ledger_with_aliased_duplicate, _ctx(STREAMING))
    assert alert.title == "Duplicate subscription: STREAMING"
    assert alert.data["canonical_name"] == "STREAMING"
    assert alert.data["series_count"] == 2
    assert alert.data["series_counterparties"] == ["STREAMFLIX INTL", "STREAMFLIXCOM"]
    assert alert.data["yearly_cost"] == "359.76"
    assert len(alert.source_refs) == 6


def test_aliased_duplicate_regardless_of_amounts() -> None:
    """Two aliased keys qualify even when their amounts are far apart."""
    rows = _stream("14.99", 0, counterparty="STREAMFLIX INTL", first_row=0)
    rows += _stream("4.99", 15, counterparty="STREAMFLIXCOM", first_row=10)
    (alert,) = detect_duplicate_subscriptions(pd.DataFrame(rows), _ctx(STREAMING))
    assert alert.data["canonical_name"] == "STREAMING"
    assert alert.data["yearly_cost"] == "239.76"  # 179.88 + 59.88


def test_aliased_fixture_without_aliases_has_no_duplicate(
    ledger_with_aliased_duplicate: pd.DataFrame,
) -> None:
    """Without the alias the two keys are different services with one series each."""
    assert detect_duplicate_subscriptions(ledger_with_aliased_duplicate, _ctx()) == []


def test_zs_acceptance_e3_no_duplicate_alert(builders: SimpleNamespace) -> None:
    """E3: two series under one key with amounts 2.99 and 0.99 are not a duplicate."""
    assert detect_duplicate_subscriptions(builders.to_frame(builders.rows_e3()), _ctx()) == []


def test_duplicate_silent_on_clean_ledger(clean_ledger_10: pd.DataFrame) -> None:
    """Ten unrelated one-off purchases give no alert."""
    assert detect_duplicate_subscriptions(clean_ledger_10, _ctx()) == []


def test_yearly_cost_is_sum_of_series_yearly_costs() -> None:
    """Two parallel series at 10.00 and 10.50 cost 120.00 + 126.00 a year."""
    rows = _stream("10.00", 0, first_row=0) + _stream("10.50", 15, first_row=10)
    (alert,) = detect_duplicate_subscriptions(pd.DataFrame(rows), _ctx())
    assert alert.data["yearly_cost"] == "246.00"
    assert alert.data["series_count"] == 2


# --- Tier 2 ------------------------------------------------------------------------------------


def test_empty_ledger_returns_empty_list(empty_ledger: pd.DataFrame) -> None:
    """An empty ledger gives [] and never raises."""
    assert detect_duplicate_subscriptions(empty_ledger, MappingProxyType({})) == []
    assert detect_duplicate_subscriptions(pd.DataFrame(), MappingProxyType({})) == []


def test_single_row_returns_list(single_row_ledger: pd.DataFrame) -> None:
    """A one-row ledger returns a list."""
    result = detect_duplicate_subscriptions(single_row_ledger, _ctx())
    assert isinstance(result, list)
    assert result == []


@pytest.mark.parametrize("context", [{}, {"aliases": None}, {"aliases": {}}])
def test_none_and_empty_aliases_do_not_raise(
    ledger_with_duplicate_sub: pd.DataFrame, context: dict[str, Any]
) -> None:
    """Missing, None and empty aliases all still find the same-key duplicate (E4)."""
    alerts = detect_duplicate_subscriptions(ledger_with_duplicate_sub, MappingProxyType(context))
    assert [a.data["canonical_name"] for a in alerts] == ["MUSICBOX"]


def test_dormant_series_is_not_a_duplicate() -> None:
    """A series that ended long before the ledger maximum does not count."""
    dormant = _stream("10.99", 0, count=3, first_row=0)  # last charge START + 60
    active = _stream("10.99", 15, count=6, first_row=10)  # last charge START + 165
    assert detect_duplicate_subscriptions(pd.DataFrame(dormant + active), _ctx()) == []


@pytest.mark.parametrize(("lower", "expected_alerts"), [("9.00", 1), ("8.90", 0)])
def test_same_key_amounts_exactly_10pct_apart_is_duplicate_and_beyond_is_not(
    lower: str, expected_alerts: int
) -> None:
    """9.00 vs 10.00 is exactly 10% apart (duplicate); 8.90 vs 10.00 is 11% (not)."""
    rows = _stream(lower, 0, first_row=0) + _stream("10.00", 15, first_row=10)
    assert len(detect_duplicate_subscriptions(pd.DataFrame(rows), _ctx())) == expected_alerts


def test_three_series_two_qualifying_counts_only_qualifying() -> None:
    """A third series at 50.00 is left out of the count, the cost and the cited rows."""
    rows = _stream("10.00", 0, first_row=0)
    rows += _stream("10.30", 12, first_row=3)
    rows += _stream("50.00", 20, first_row=6)
    (alert,) = detect_duplicate_subscriptions(pd.DataFrame(rows), _ctx())
    assert alert.data["series_count"] == 2
    assert alert.data["yearly_cost"] == "243.60"  # 120.00 + 123.60
    assert alert.source_refs == ["f.csv:0", "f.csv:3", "f.csv:1", "f.csv:4", "f.csv:2", "f.csv:5"]


def test_duplicate_source_ref_handled(ledger_with_duplicate_sub: pd.DataFrame) -> None:
    """A row repeated with the same source_ref does not crash and is cited once."""
    doubled = pd.concat([ledger_with_duplicate_sub, ledger_with_duplicate_sub.iloc[[0]]])
    alerts = detect_duplicate_subscriptions(doubled, _ctx())
    assert isinstance(alerts, list)
    for alert in alerts:
        assert len(alert.source_refs) == len(set(alert.source_refs))


# --- Tier 3 ------------------------------------------------------------------------------------


@PROP
@given(rows=_ledger_rows(), aliases=_ALIASES)
def test_source_refs_subset_of_input(rows: list[dict], aliases: dict | None) -> None:
    """No invention: every cited source_ref belongs to a loaded input."""
    ledger = pd.DataFrame(rows)
    context = _ctx(aliases)
    known = loaded_source_refs(ledger, context)
    for alert in detect_duplicate_subscriptions(ledger, context):
        assert alert.source_refs
        assert set(alert.source_refs) <= known


@PROP
@given(rows=_ledger_rows(), aliases=_ALIASES, data=st.data())
def test_row_order_invariant(rows: list[dict], aliases: dict | None, data: st.DataObject) -> None:
    """Shuffled rows give the same alerts."""
    shuffled = data.draw(st.permutations(rows))
    expected = detect_duplicate_subscriptions(pd.DataFrame(rows), _ctx(aliases))
    actual = detect_duplicate_subscriptions(pd.DataFrame(list(shuffled)), _ctx(aliases))
    assert _by_id(actual) == _by_id(expected)


@PROP
@given(rows=_ledger_rows(), aliases=_ALIASES)
def test_idempotent(rows: list[dict], aliases: dict | None) -> None:
    """Running the detector twice on the same ledger gives the same alerts."""
    ledger = pd.DataFrame(rows)
    first = detect_duplicate_subscriptions(ledger, _ctx(aliases))
    assert first == detect_duplicate_subscriptions(ledger, _ctx(aliases))
