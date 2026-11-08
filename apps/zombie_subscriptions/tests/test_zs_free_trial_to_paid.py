"""Tests for the free-trial-to-paid detector (Task Z13)."""

from datetime import date, timedelta
from decimal import Decimal
from types import MappingProxyType

import pandas as pd
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from apps.zombie_subscriptions.detectors.free_trial_to_paid import detect_free_trial_to_paid
from apps.zombie_subscriptions.detectors.utils import find_series
from ledger_kit.detectors import loaded_source_refs
from ledger_kit.models import Alert
from ledger_kit.utils.money import round_to_cents

START = date(2026, 1, 5)
PROP = settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])


def _ctx(aliases: dict[str, list[str]] | None = None) -> MappingProxyType:
    """Build the read-only context the registry passes to a detector."""
    return MappingProxyType({"aliases": aliases})


def _rows_at(
    entries: list[tuple[int, str | Decimal]], counterparty: str = "SECUREPASS", first_row: int = 0
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


def _trial_then_series(
    trial_amount: str, days_before: int, series_start: int = 60, first_row: int = 0
) -> list[dict]:
    """One trial charge `days_before` days before three monthly 14.99 charges."""
    entries: list[tuple[int, str | Decimal]] = [(series_start - days_before, trial_amount)]
    entries += [(series_start + 30 * i, "14.99") for i in range(3)]
    return _rows_at(entries, first_row=first_row)


def _amount(base_cents: int, bps: int) -> Decimal:
    """Return base_cents scaled by (1 + bps / 10000), as euros rounded to cents."""
    return round_to_cents(Decimal(base_cents * (10000 + bps)) / Decimal(1_000_000))


_STEP = st.tuples(st.integers(25, 35), st.integers(-15, 15))
_MERCHANTS = ["SECUREPASS", "CLOUDVAULT", "MUSICBOX"]


@st.composite
def _ledger_rows(draw: st.DrawFn) -> list[dict]:
    """Random debit rows: near-monthly streams, each optionally preceded by a token charge."""
    rows: list[dict] = []
    for merchant in draw(st.lists(st.sampled_from(_MERCHANTS), min_size=1, max_size=3)):
        offset = draw(st.integers(min_value=40, max_value=100))
        base_cents = draw(st.integers(min_value=500, max_value=20000))
        entries: list[tuple[int, str | Decimal]] = []
        trial_days = draw(st.one_of(st.none(), st.integers(min_value=1, max_value=40)))
        if trial_days is not None:
            token_cents = draw(st.integers(min_value=1, max_value=100))
            entries.append((offset - trial_days, Decimal(token_cents) / Decimal(100)))
        entries.append((offset, _amount(base_cents, 0)))
        for gap, pct in draw(st.lists(_STEP, max_size=6)):
            offset += gap
            entries.append((offset, _amount(base_cents, pct * 100)))
        rows.extend(_rows_at(entries, merchant, first_row=len(rows)))
    return rows


def _by_id(alerts: list[Alert]) -> list[Alert]:
    """Order alerts by their deterministic id for order-agnostic comparison."""
    return sorted(alerts, key=lambda a: a.id)


# --- Tier 1 ------------------------------------------------------------------------------------


def test_free_trial_fires_on_typical_input(ledger_with_free_trial: pd.DataFrame) -> None:
    """0.49 fourteen days before three monthly 14.99 charges gives one info alert."""
    (alert,) = detect_free_trial_to_paid(ledger_with_free_trial, _ctx())
    assert alert.detector == "zs.free_trial_to_paid"
    assert alert.severity == "info"
    assert alert.title == "Free trial converted to paid: SECUREPASS"
    assert alert.source_refs == [f"zs_fixture.csv:{i}" for i in range(4)]
    assert alert.data == {
        "counterparty": "SECUREPASS",
        "trial_amount": "0.49",
        "first_paid_amount": "14.99",
        "trial_source_ref": "zs_fixture.csv:0",
        "days_before_first_charge": 14,
        "yearly_cost": "179.88",
        "interval_type": "monthly",
    }


def test_free_trial_silent_on_clean_ledger(clean_ledger_10: pd.DataFrame) -> None:
    """Ten unrelated one-off purchases give no alert."""
    assert detect_free_trial_to_paid(clean_ledger_10, _ctx()) == []


def test_trial_row_not_part_of_series(ledger_with_free_trial: pd.DataFrame) -> None:
    """The 0.49 trial charge stays outside the three-row series."""
    (series,) = find_series(ledger_with_free_trial.to_dict("records"))
    refs = [r["source_ref"] for r in series.rows]
    assert refs == [f"zs_fixture.csv:{i}" for i in range(1, 4)]


def test_source_refs_include_trial_and_series_sorted_by_date_then_row() -> None:
    """Refs follow (date, source_row): trial row 10 comes first, then rows 7, 8, 9."""
    entries: list[tuple[int, str | Decimal]] = [(0, "0.49")]
    entries += [(14 + 30 * i, "14.99") for i in range(3)]
    rows = _rows_at(entries)
    for row, number in zip(rows, [10, 7, 8, 9], strict=True):
        row["source_row"] = number
        row["source_ref"] = f"f.csv:{number}"
    (alert,) = detect_free_trial_to_paid(pd.DataFrame(rows), _ctx())
    assert alert.source_refs == ["f.csv:10", "f.csv:7", "f.csv:8", "f.csv:9"]


# --- Tier 2 ------------------------------------------------------------------------------------


def test_empty_ledger_returns_empty_list(empty_ledger: pd.DataFrame) -> None:
    """An empty ledger gives [] and never raises."""
    assert detect_free_trial_to_paid(empty_ledger, MappingProxyType({})) == []
    assert detect_free_trial_to_paid(pd.DataFrame(), MappingProxyType({})) == []


def test_single_row_returns_list(single_row_ledger: pd.DataFrame) -> None:
    """A one-row ledger returns a list."""
    result = detect_free_trial_to_paid(single_row_ledger, _ctx())
    assert isinstance(result, list)
    assert result == []


@pytest.mark.parametrize(
    ("trial_amount", "fires"),
    [("0.01", True), ("1.00", True), ("1.01", False), ("0.00", False)],
)
def test_amount_boundaries_0_01_and_1_00_inclusive_1_01_excluded_0_00_absent(
    trial_amount: str, fires: bool
) -> None:
    """Token amounts 0.01 and 1.00 count; 1.01 does not; a 0.00 row is never a trial."""
    ledger = pd.DataFrame(_trial_then_series(trial_amount, days_before=14))
    assert (len(detect_free_trial_to_paid(ledger, _ctx())) == 1) is fires


@pytest.mark.parametrize(("days", "fires"), [(1, True), (35, True), (0, False), (36, False)])
def test_day_boundaries_1_and_35_inclusive_0_and_36_excluded(days: int, fires: bool) -> None:
    """A trial 1 or 35 days before the first charge counts; 0 or 36 days does not."""
    ledger = pd.DataFrame(_trial_then_series("0.49", days_before=days))
    alerts = detect_free_trial_to_paid(ledger, _ctx())
    assert (len(alerts) == 1) is fires
    if fires:
        assert alerts[0].data["days_before_first_charge"] == days


def test_closest_trial_charge_chosen() -> None:
    """Of two token charges before the series, the one closest to the first charge is cited."""
    entries: list[tuple[int, str | Decimal]] = [(40, "0.30"), (55, "0.50")]
    entries += [(60 + 30 * i, "14.99") for i in range(3)]
    (alert,) = detect_free_trial_to_paid(pd.DataFrame(_rows_at(entries)), _ctx())
    assert alert.data["trial_source_ref"] == "f.csv:1"
    assert alert.data["days_before_first_charge"] == 5
    assert alert.source_refs == ["f.csv:1", "f.csv:2", "f.csv:3", "f.csv:4"]


@pytest.mark.parametrize("days", [28, 30, 33])
def test_trial_28_to_33_days_before_series_still_a_trial(days: int) -> None:
    """A trial one cadence gap before the series is not absorbed into it."""
    rows = _trial_then_series("0.49", days_before=days)
    (series,) = find_series(rows)
    assert len(series.rows) == 3
    (alert,) = detect_free_trial_to_paid(pd.DataFrame(rows), _ctx())
    assert alert.data["days_before_first_charge"] == days
    assert len(alert.source_refs) == 4


def test_duplicate_source_ref_handled(ledger_with_free_trial: pd.DataFrame) -> None:
    """A row repeated with the same source_ref does not crash and is cited once."""
    doubled = pd.concat([ledger_with_free_trial, ledger_with_free_trial.iloc[[0]]])
    alerts = detect_free_trial_to_paid(doubled, _ctx())
    assert isinstance(alerts, list)
    for alert in alerts:
        assert len(alert.source_refs) == len(set(alert.source_refs))


# --- Tier 3 ------------------------------------------------------------------------------------


@PROP
@given(rows=_ledger_rows())
def test_source_refs_subset_of_input(rows: list[dict]) -> None:
    """No invention: every cited source_ref belongs to a loaded input."""
    ledger = pd.DataFrame(rows)
    context = _ctx()
    known = loaded_source_refs(ledger, context)
    for alert in detect_free_trial_to_paid(ledger, context):
        assert alert.source_refs
        assert set(alert.source_refs) <= known


@PROP
@given(rows=_ledger_rows(), data=st.data())
def test_row_order_invariant(rows: list[dict], data: st.DataObject) -> None:
    """Shuffled rows give the same alerts."""
    shuffled = data.draw(st.permutations(rows))
    expected = detect_free_trial_to_paid(pd.DataFrame(rows), _ctx())
    actual = detect_free_trial_to_paid(pd.DataFrame(list(shuffled)), _ctx())
    assert _by_id(actual) == _by_id(expected)


@PROP
@given(
    gaps=st.lists(st.integers(min_value=40, max_value=80), min_size=0, max_size=7),
    cents=st.lists(st.integers(min_value=1, max_value=100), min_size=8, max_size=8),
)
def test_never_fires_without_a_series(gaps: list[int], cents: list[int]) -> None:
    """Token charges at least 40 days apart never form a series, so no alert can fire."""
    offsets = [0]
    for gap in gaps:
        offsets.append(offsets[-1] + gap)
    entries = [(o, Decimal(c) / Decimal(100)) for o, c in zip(offsets, cents, strict=False)]
    ledger = pd.DataFrame(_rows_at(entries))
    assert detect_free_trial_to_paid(ledger, _ctx()) == []
