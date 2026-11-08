"""Tests for the charges-after-cancellation detector (Task Z14)."""

from datetime import date, timedelta
from decimal import Decimal
from types import MappingProxyType

import pandas as pd
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from apps.zombie_subscriptions.detectors.charges_after_cancellation import (
    detect_charges_after_cancellation,
)
from ledger_kit.detectors import loaded_source_refs
from ledger_kit.models import Alert
from ledger_kit.utils.money import round_to_cents

START = date(2026, 1, 5)
PROP = settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
ALIASES = {"STREAMING": ["STREAMFLIX INTL", "STREAMFLIXCOM"]}


def _ctx(
    cancellation_dates: dict[str, date] | None = None,
    aliases: dict[str, list[str]] | None = None,
) -> MappingProxyType:
    """Build the read-only context the registry passes to a detector."""
    return MappingProxyType({"aliases": aliases, "cancellation_dates": cancellation_dates})


def _rows_at(
    entries: list[tuple[int, str | Decimal]], counterparty: str = "GYMPLUS", first_row: int = 0
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


def _by_id(alerts: list[Alert]) -> list[Alert]:
    """Order alerts by their deterministic id for order-agnostic comparison."""
    return sorted(alerts, key=lambda a: a.id)


_MERCHANTS = ["GYMPLUS", "CLOUDVAULT", "MUSICBOX"]


@st.composite
def _scenarios(draw: st.DrawFn) -> tuple[list[dict], dict[str, date]]:
    """Random debit rows over three merchants plus cancellation dates for some of them."""
    entries = draw(
        st.lists(
            st.tuples(
                st.sampled_from(_MERCHANTS),
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
    cancel_offsets = draw(
        st.dictionaries(st.sampled_from(_MERCHANTS), st.integers(min_value=0, max_value=400))
    )
    cancellation_dates = {k: START + timedelta(days=v) for k, v in cancel_offsets.items()}
    return rows, cancellation_dates


# --- Tier 1 ------------------------------------------------------------------------------------


def test_post_cancellation_alert_fires(
    ledger_with_post_cancellation: pd.DataFrame, builders
) -> None:
    """One charge after the cancellation date gives one critical alert with the exact total."""
    context = _ctx({"GYMPLUS": builders.cancellation_date})
    (alert,) = detect_charges_after_cancellation(ledger_with_post_cancellation, context)
    assert alert.detector == "zs.charges_after_cancellation"
    assert alert.severity == "critical"
    assert alert.title == "Charge after cancellation: GYMPLUS"
    assert alert.source_refs == ["zs_fixture.csv:3"]
    assert alert.data == {
        "counterparty": "GYMPLUS",
        "cancellation_date": "2026-03-31",
        "post_cancellation_count": 1,
        "total_charged_after": "8.99",
        "yearly_cost": "107.88",
    }


def test_total_charged_after_is_exact_sum_of_post_rows() -> None:
    """Three charges after the cancellation date sum to exactly 18.58."""
    entries: list[tuple[int, str | Decimal]] = [
        (0, "8.99"),
        (30, "8.99"),
        (60, "8.99"),
        (90, "8.99"),
        (120, "9.49"),
        (150, "0.10"),
    ]
    ledger = pd.DataFrame(_rows_at(entries))
    cancel = START + timedelta(days=75)
    (alert,) = detect_charges_after_cancellation(ledger, _ctx({"GYMPLUS": cancel}))
    assert alert.source_refs == ["f.csv:3", "f.csv:4", "f.csv:5"]
    assert alert.data["post_cancellation_count"] == 3
    assert alert.data["total_charged_after"] == "18.58"


@pytest.mark.parametrize("dates", [None, {}])
def test_silent_without_cancellation_dates(
    ledger_with_post_cancellation: pd.DataFrame, dates: dict[str, date] | None
) -> None:
    """No cancellation dates (None or empty) give no alert, also when the key is absent."""
    assert detect_charges_after_cancellation(ledger_with_post_cancellation, _ctx(dates)) == []
    no_keys = MappingProxyType({})
    assert detect_charges_after_cancellation(ledger_with_post_cancellation, no_keys) == []


def test_silent_on_clean_ledger(clean_ledger_10: pd.DataFrame) -> None:
    """A cancellation date after every charge of the service gives no alert."""
    context = _ctx({"FRESHCO": date(2030, 1, 1)})
    assert detect_charges_after_cancellation(clean_ledger_10, context) == []


def test_rows_outside_a_series_are_still_counted() -> None:
    """Irregular charges after the cancellation date count even though no series holds them."""
    entries: list[tuple[int, str | Decimal]] = [
        (0, "8.99"),
        (30, "8.99"),
        (60, "8.99"),
        (75, "3.00"),
        (83, "4.00"),
    ]
    ledger = pd.DataFrame(_rows_at(entries))
    cancel = START + timedelta(days=70)
    (alert,) = detect_charges_after_cancellation(ledger, _ctx({"GYMPLUS": cancel}))
    assert alert.source_refs == ["f.csv:3", "f.csv:4"]
    assert alert.data["post_cancellation_count"] == 2
    assert alert.data["total_charged_after"] == "7.00"
    assert alert.data["yearly_cost"] == "107.88"


# --- Tier 1 - canonical grouping ---------------------------------------------------------------


def test_two_aliased_keys_give_one_alert(ledger_with_aliased_duplicate: pd.DataFrame) -> None:
    """Post-cancellation rows under two aliased keys are reported in a single alert."""
    context = _ctx({"STREAMING": date(2026, 2, 10)}, ALIASES)
    (alert,) = detect_charges_after_cancellation(ledger_with_aliased_duplicate, context)
    assert alert.title == "Charge after cancellation: STREAMING"
    assert alert.source_refs == [f"zs_fixture.csv:{i}" for i in (3, 4, 5)]
    frame = ledger_with_aliased_duplicate
    cited = frame[frame["source_ref"].isin(alert.source_refs)]
    assert set(cited["counterparty"]) == {"STREAMFLIX INTL", "STREAMFLIXCOM"}
    assert alert.data["counterparty"] == "STREAMING"
    assert alert.data["post_cancellation_count"] == 3
    assert alert.data["total_charged_after"] == "44.97"


def test_yearly_cost_sums_active_series_of_all_keys(
    ledger_with_aliased_duplicate: pd.DataFrame,
) -> None:
    """The yearly cost adds the active series of both keys: 2 x 14.99 x 12."""
    context = _ctx({"STREAMING": date(2026, 2, 10)}, ALIASES)
    (alert,) = detect_charges_after_cancellation(ledger_with_aliased_duplicate, context)
    assert alert.data["yearly_cost"] == "359.76"


def test_yearly_cost_zero_when_no_active_series() -> None:
    """A dormant series (last charge long before the ledger end) adds nothing: 0.00."""
    entries: list[tuple[int, str | Decimal]] = [(0, "8.99"), (30, "8.99"), (60, "8.99")]
    rows = _rows_at(entries)
    rows += _rows_at([(300, "25.00")], "FRESHCO", first_row=3)
    cancel = START + timedelta(days=20)
    (alert,) = detect_charges_after_cancellation(pd.DataFrame(rows), _ctx({"GYMPLUS": cancel}))
    assert alert.source_refs == ["f.csv:1", "f.csv:2"]
    assert alert.data["yearly_cost"] == "0.00"


# --- Tier 2 ------------------------------------------------------------------------------------


def test_empty_ledger_returns_empty_list(empty_ledger: pd.DataFrame) -> None:
    """An empty ledger gives [] and never raises."""
    context = _ctx({"GYMPLUS": date(2026, 1, 1)})
    assert detect_charges_after_cancellation(empty_ledger, context) == []
    assert detect_charges_after_cancellation(pd.DataFrame(), MappingProxyType({})) == []


def test_single_row_returns_list(single_row_ledger: pd.DataFrame) -> None:
    """A one-row ledger returns a list, with or without a cancellation date."""
    assert detect_charges_after_cancellation(single_row_ledger, _ctx()) == []
    context = _ctx({"CLOUDVAULT": date(2026, 1, 1)})
    alerts = detect_charges_after_cancellation(single_row_ledger, context)
    assert isinstance(alerts, list)
    assert len(alerts) == 1


def test_charge_on_cancellation_date_is_not_after() -> None:
    """A charge on the cancellation date is not counted; one day later it is."""
    ledger = pd.DataFrame(_rows_at([(0, "8.99")]))
    on_day = _ctx({"GYMPLUS": START})
    assert detect_charges_after_cancellation(ledger, on_day) == []
    day_before = _ctx({"GYMPLUS": START - timedelta(days=1)})
    assert len(detect_charges_after_cancellation(ledger, day_before)) == 1


def test_unknown_service_in_cancellation_dates_ignored(
    ledger_with_post_cancellation: pd.DataFrame,
) -> None:
    """A cancellation date for a service absent from the ledger raises no alert."""
    context = _ctx({"NOSUCHSERVICE": date(2020, 1, 1)})
    assert detect_charges_after_cancellation(ledger_with_post_cancellation, context) == []


def test_date_map_keys_must_be_normalised_by_caller(
    ledger_with_post_cancellation: pd.DataFrame, builders
) -> None:
    """The detector matches keys verbatim: 'gymplus' is not 'GYMPLUS'."""
    cancel = builders.cancellation_date
    lower = _ctx({"gymplus": cancel})
    assert detect_charges_after_cancellation(ledger_with_post_cancellation, lower) == []
    upper = _ctx({"GYMPLUS": cancel})
    assert len(detect_charges_after_cancellation(ledger_with_post_cancellation, upper)) == 1


def test_duplicate_source_ref_handled(
    ledger_with_post_cancellation: pd.DataFrame, builders
) -> None:
    """A repeated row is cited and summed once."""
    doubled = pd.concat([ledger_with_post_cancellation, ledger_with_post_cancellation.iloc[[3]]])
    context = _ctx({"GYMPLUS": builders.cancellation_date})
    (alert,) = detect_charges_after_cancellation(doubled, context)
    assert alert.source_refs == ["zs_fixture.csv:3"]
    assert alert.data["post_cancellation_count"] == 1
    assert alert.data["total_charged_after"] == "8.99"


# --- Tier 3 ------------------------------------------------------------------------------------


@PROP
@given(scenario=_scenarios())
def test_source_refs_subset_of_input(scenario: tuple[list[dict], dict[str, date]]) -> None:
    """No invention: every cited source_ref belongs to a loaded input."""
    rows, cancellation_dates = scenario
    ledger = pd.DataFrame(rows)
    context = _ctx(cancellation_dates)
    known = loaded_source_refs(ledger, context)
    for alert in detect_charges_after_cancellation(ledger, context):
        assert alert.source_refs
        assert set(alert.source_refs) <= known


@PROP
@given(scenario=_scenarios())
def test_total_equals_sum_of_cited_rows(scenario: tuple[list[dict], dict[str, date]]) -> None:
    """total_charged_after is the sum of the cited rows and the count matches the refs."""
    rows, cancellation_dates = scenario
    ledger = pd.DataFrame(rows)
    by_ref = {r["source_ref"]: r for r in rows}
    for alert in detect_charges_after_cancellation(ledger, _ctx(cancellation_dates)):
        cited = [by_ref[ref] for ref in alert.source_refs]
        total = round_to_cents(sum((r["amount"] for r in cited), Decimal("0.00")))
        assert alert.data["total_charged_after"] == str(total)
        assert alert.data["post_cancellation_count"] == len(cited)
        cancel = date.fromisoformat(alert.data["cancellation_date"])
        assert all(r["date"] > cancel for r in cited)


@PROP
@given(scenario=_scenarios(), data=st.data())
def test_row_order_invariant(
    scenario: tuple[list[dict], dict[str, date]], data: st.DataObject
) -> None:
    """Shuffled rows give the same alerts."""
    rows, cancellation_dates = scenario
    shuffled = data.draw(st.permutations(rows))
    expected = detect_charges_after_cancellation(pd.DataFrame(rows), _ctx(cancellation_dates))
    actual = detect_charges_after_cancellation(
        pd.DataFrame(list(shuffled)), _ctx(cancellation_dates)
    )
    assert _by_id(actual) == _by_id(expected)
