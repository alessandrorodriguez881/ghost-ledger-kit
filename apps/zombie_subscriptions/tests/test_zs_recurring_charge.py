"""Tests for the recurring-charge detector (Task Z10)."""

from datetime import date, timedelta
from decimal import Decimal
from types import MappingProxyType, SimpleNamespace
from typing import Any

import pandas as pd
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from apps.zombie_subscriptions.detectors.recurring_charge import detect_recurring_charges
from ledger_kit.detectors import loaded_source_refs
from ledger_kit.models import Alert
from ledger_kit.utils.money import round_to_cents

START = date(2026, 1, 5)
PROP = settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
DATA_KEYS = {
    "counterparty",
    "normalised_key",
    "interval_type",
    "current_amount",
    "charge_count",
    "yearly_cost",
    "first_charge_date",
    "last_charge_date",
    "is_active",
}


def _ctx(aliases: dict[str, list[str]] | None = None) -> MappingProxyType:
    """Build the read-only context the registry passes to a detector."""
    return MappingProxyType({"aliases": aliases})


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


def _periodic(
    amounts: list[str], step_days: int = 30, counterparty: str = "CLOUDVAULT", first_row: int = 0
) -> list[dict]:
    """Build rows `step_days` apart starting at START."""
    entries = [(step_days * i, a) for i, a in enumerate(amounts)]
    return _rows_at(entries, counterparty, first_row)


def _amount(base_cents: int, bps: int) -> Decimal:
    """Return base_cents scaled by (1 + bps / 10000), as euros rounded to cents."""
    return round_to_cents(Decimal(base_cents * (10000 + bps)) / Decimal(1_000_000))


@st.composite
def _monthly_series(draw: st.DrawFn, min_charges: int, max_charges: int) -> list[dict]:
    """Monthly rows: each gap is 30 + jitter in [-3, 3] days, amounts within +/-4% of a base."""
    count = draw(st.integers(min_value=min_charges, max_value=max_charges))
    base_cents = draw(st.integers(min_value=500, max_value=20000))
    jitters = draw(st.lists(st.integers(-3, 3), min_size=count - 1, max_size=count - 1))
    noise = draw(st.lists(st.integers(-400, 400), min_size=count, max_size=count))
    offsets = [0]
    for jitter in jitters:
        offsets.append(offsets[-1] + 30 + jitter)
    amounts = [_amount(base_cents, bps) for bps in noise]
    return _rows_at(list(zip(offsets, amounts, strict=True)))


_STEP = st.tuples(st.integers(25, 35), st.integers(-15, 15))
_MERCHANTS = ["CLOUDVAULT", "STREAMFLEX INTL", "MUSICBOX", "GLOWBILL"]


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


def test_recurring_charge_fires_on_typical_input(ledger_with_recurring: pd.DataFrame) -> None:
    """Three monthly 12.99 charges give one info alert with every REQ-ZS-13 data key."""
    alerts = detect_recurring_charges(ledger_with_recurring, _ctx())
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.detector == "zs.recurring_charge"
    assert alert.severity == "info"
    assert alert.title == "Recurring charge detected: CLOUDVAULT"
    assert alert.source_refs == [f"zs_fixture.csv:{i}" for i in range(3)]
    assert set(alert.data) == DATA_KEYS
    assert alert.data["counterparty"] == "CLOUDVAULT"
    assert alert.data["normalised_key"] == "CLOUDVAULT"
    assert alert.data["interval_type"] == "monthly"
    assert alert.data["current_amount"] == "12.99"
    assert alert.data["charge_count"] == 3
    assert alert.data["yearly_cost"] == "155.88"
    assert alert.data["first_charge_date"] == "2026-01-10"
    assert alert.data["last_charge_date"] == "2026-03-11"
    assert alert.data["is_active"] is True


def test_recurring_charge_silent_on_clean_ledger(clean_ledger_10: pd.DataFrame) -> None:
    """Ten unrelated one-off purchases give no alert."""
    assert detect_recurring_charges(clean_ledger_10, _ctx()) == []


@pytest.mark.parametrize(
    ("step_days", "count", "amount", "yearly"),
    [
        (7, 4, "2.50", "130.00"),
        (30, 3, "12.99", "155.88"),
        (91, 2, "30.00", "120.00"),
        (365, 2, "99.00", "99.00"),
    ],
)
def test_yearly_cost_is_current_amount_times_ppy(
    step_days: int, count: int, amount: str, yearly: str
) -> None:
    """yearly_cost is current_amount x 52, 12, 4 or 1 for weekly, monthly, quarterly, yearly."""
    ledger = pd.DataFrame(_periodic([amount] * count, step_days))
    (alert,) = detect_recurring_charges(ledger, _ctx())
    assert alert.data["current_amount"] == amount
    assert alert.data["yearly_cost"] == yearly


def test_zs_acceptance_e1_yearly_cost_191_88(ledger_with_price_increase: pd.DataFrame) -> None:
    """E1: the yearly cost reflects the current price, 15.99 x 12."""
    (alert,) = detect_recurring_charges(ledger_with_price_increase, _ctx())
    assert alert.data["current_amount"] == "15.99"
    assert alert.data["charge_count"] == 6
    assert alert.data["yearly_cost"] == "191.88"


def test_zs_acceptance_e3_two_alerts(builders: SimpleNamespace) -> None:
    """E3: two parallel series with different amounts give two alerts."""
    alerts = detect_recurring_charges(builders.to_frame(builders.rows_e3()), _ctx())
    assert [a.data["current_amount"] for a in alerts] == ["2.99", "0.99"]
    assert all(len(a.source_refs) == 3 for a in alerts)


def test_zs_acceptance_e4_two_alerts(ledger_with_duplicate_sub: pd.DataFrame) -> None:
    """E4: two parallel series with the same amount give two alerts on disjoint rows."""
    alerts = detect_recurring_charges(ledger_with_duplicate_sub, _ctx())
    assert [a.source_refs for a in alerts] == [
        ["zs_fixture.csv:0", "zs_fixture.csv:2", "zs_fixture.csv:4"],
        ["zs_fixture.csv:1", "zs_fixture.csv:3", "zs_fixture.csv:5"],
    ]


def test_alias_resolves_counterparty_display_name(ledger_with_recurring: pd.DataFrame) -> None:
    """With an alias the counterparty and title use the canonical name; the key stays."""
    alerts = detect_recurring_charges(ledger_with_recurring, _ctx({"STREAMING": ["CLOUDVAULT"]}))
    assert alerts[0].title == "Recurring charge detected: STREAMING"
    assert alerts[0].data["counterparty"] == "STREAMING"
    assert alerts[0].data["normalised_key"] == "CLOUDVAULT"


def test_zs_acceptance_e7b_weekly_shopping_no_alerts_of_any_kind(
    ledger_with_weekly_shopping: pd.DataFrame,
) -> None:
    """E7b: 26 weekly shopping charges give no recurring-charge alert."""
    assert detect_recurring_charges(ledger_with_weekly_shopping, _ctx()) == []


# --- Tier 2 ------------------------------------------------------------------------------------


def test_empty_ledger_returns_empty_list(empty_ledger: pd.DataFrame) -> None:
    """An empty ledger gives [] and never raises."""
    assert detect_recurring_charges(empty_ledger, MappingProxyType({})) == []
    assert detect_recurring_charges(pd.DataFrame(), MappingProxyType({})) == []


def test_single_row_returns_list(single_row_ledger: pd.DataFrame) -> None:
    """A one-row ledger returns a list."""
    result = detect_recurring_charges(single_row_ledger, _ctx())
    assert isinstance(result, list)
    assert result == []


@pytest.mark.parametrize("context", [{}, {"aliases": None}, {"aliases": {}}])
def test_none_aliases_does_not_raise(
    ledger_with_recurring: pd.DataFrame, context: dict[str, Any]
) -> None:
    """Missing, None and empty aliases all work and leave the key as the display name."""
    alerts = detect_recurring_charges(ledger_with_recurring, MappingProxyType(context))
    assert [a.data["counterparty"] for a in alerts] == ["CLOUDVAULT"]


def test_duplicate_source_ref_handled(ledger_with_recurring: pd.DataFrame) -> None:
    """A row repeated with the same source_ref does not crash and is cited once."""
    doubled = pd.concat([ledger_with_recurring, ledger_with_recurring.iloc[[0]]])
    alerts = detect_recurring_charges(doubled, _ctx())
    assert isinstance(alerts, list)
    for alert in alerts:
        assert len(alert.source_refs) == len(set(alert.source_refs))


def test_two_monthly_charges_below_minimum() -> None:
    """Two monthly charges are below MIN_OCCURRENCES_MONTHLY."""
    ledger = pd.DataFrame(_periodic(["12.99", "12.99"]))
    assert detect_recurring_charges(ledger, _ctx()) == []


def test_is_active_true_and_false() -> None:
    """is_active is measured against the latest date in the ledger, not the clock."""
    series = _periodic(["12.99"] * 3)  # last charge on START + 60
    recent = _rows_at([(80, "5.00")], "BAKERYONE", first_row=10)
    late = _rows_at([(200, "5.00")], "BAKERYONE", first_row=10)
    active = detect_recurring_charges(pd.DataFrame([*series, *recent]), _ctx())
    dormant = detect_recurring_charges(pd.DataFrame([*series, *late]), _ctx())
    assert active[0].data["is_active"] is True
    assert dormant[0].data["is_active"] is False


def test_amount_boundary_at_stable_ratio() -> None:
    """Amounts exactly 2% from the median are one level; just beyond it is a recorded step."""
    level = pd.DataFrame(_periodic(["9.80"] * 3 + ["10.20"] * 3))
    (alert,) = detect_recurring_charges(level, _ctx())
    assert alert.data["current_amount"] == "10.00"
    step = pd.DataFrame(_periodic(["9.79"] * 3 + ["10.21"] * 3))
    (alert,) = detect_recurring_charges(step, _ctx())
    assert alert.data["current_amount"] == "10.21"


def test_amount_boundary_at_match_ratio() -> None:
    """A variable bill within 10% of its median is a series; 1 cent beyond it is not."""
    inside = pd.DataFrame(_periodic(["9.00", "10.00", "11.00"]))
    (alert,) = detect_recurring_charges(inside, _ctx())
    assert alert.data["current_amount"] == "10.00"
    outside = pd.DataFrame(_periodic(["8.99", "10.00", "11.01"]))
    assert detect_recurring_charges(outside, _ctx()) == []


def test_e7c_weekly_variable_amounts_raise_no_alert() -> None:
    """REQ-DF-10 (E7c): four weekly charges that vary by 4.5 % each are not a subscription."""
    weekly = pd.DataFrame(_periodic(["100.00", "104.50", "109.00", "113.50"], step_days=7))
    assert detect_recurring_charges(weekly, _ctx()) == []


def test_e7d_variable_bill_alert_only_with_an_exclusive_span() -> None:
    """REQ-DF-11 (E7d): 90.00, 95.00, 100.00 alert alone, but not with a purchase between."""
    alone = pd.DataFrame(_rows_at([(0, "90.00"), (30, "95.00"), (60, "100.00")]))
    (alert,) = detect_recurring_charges(alone, _ctx())
    assert alert.data["current_amount"] == "95.00"
    entries = [(0, "90.00"), (10, "20.00"), (30, "95.00"), (60, "100.00")]
    mixed = pd.DataFrame(_rows_at(entries))
    assert detect_recurring_charges(mixed, _ctx()) == []


def test_source_refs_sorted_by_date_not_text() -> None:
    """f.csv:8, f.csv:9, f.csv:10 stay in date order; text order would put 10 first."""
    ledger = pd.DataFrame(_periodic(["12.99"] * 3, first_row=8))
    (alert,) = detect_recurring_charges(ledger, _ctx())
    assert alert.source_refs == ["f.csv:8", "f.csv:9", "f.csv:10"]


# --- Tier 3 ------------------------------------------------------------------------------------


@PROP
@given(rows=_monthly_series(min_charges=3, max_charges=10))
def test_monthly_series_always_detected(rows: list[dict]) -> None:
    """Gaps of 30 +/- 3 days and amounts within +/-4% always form exactly one series."""
    alerts = detect_recurring_charges(pd.DataFrame(rows), _ctx())
    assert len(alerts) == 1
    assert alerts[0].data["charge_count"] == len(rows)
    assert alerts[0].data["interval_type"] == "monthly"


@PROP
@given(rows=_monthly_series(min_charges=1, max_charges=2))
def test_insufficient_occurrences_never_detected(rows: list[dict]) -> None:
    """One or two monthly charges never form a series."""
    assert detect_recurring_charges(pd.DataFrame(rows), _ctx()) == []


@PROP
@given(rows=_ledger_rows(), data=st.data())
def test_row_order_invariant(rows: list[dict], data: st.DataObject) -> None:
    """Shuffled rows give the same alerts."""
    shuffled = data.draw(st.permutations(rows))
    expected = detect_recurring_charges(pd.DataFrame(rows), _ctx())
    actual = detect_recurring_charges(pd.DataFrame(list(shuffled)), _ctx())
    assert _by_id(actual) == _by_id(expected)


@PROP
@given(rows=_monthly_series(min_charges=3, max_charges=10))
def test_yearly_cost_equals_current_price_times_12(rows: list[dict]) -> None:
    """yearly_cost is exactly round_to_cents(current_amount x 12) for a monthly series."""
    (alert,) = detect_recurring_charges(pd.DataFrame(rows), _ctx())
    expected = round_to_cents(Decimal(alert.data["current_amount"]) * 12)
    assert alert.data["yearly_cost"] == str(expected)


@PROP
@given(rows=_ledger_rows())
def test_source_refs_subset_of_input(rows: list[dict]) -> None:
    """No invention: every cited source_ref belongs to a loaded input."""
    ledger = pd.DataFrame(rows)
    context = _ctx()
    known = loaded_source_refs(ledger, context)
    for alert in detect_recurring_charges(ledger, context):
        assert alert.source_refs
        assert set(alert.source_refs) <= known


@PROP
@given(rows=_ledger_rows())
def test_detector_idempotent(rows: list[dict]) -> None:
    """Running the detector twice on the same ledger gives the same alerts."""
    ledger = pd.DataFrame(rows)
    assert detect_recurring_charges(ledger, _ctx()) == detect_recurring_charges(ledger, _ctx())
