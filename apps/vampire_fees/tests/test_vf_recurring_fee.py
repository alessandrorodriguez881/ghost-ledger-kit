"""Tests for the vf.recurring_fee detector (Task VF6; AE-VF-09 to AE-VF-16)."""

import re
from datetime import date, timedelta
from types import MappingProxyType
from typing import Any

import pandas as pd
from hypothesis import given, settings
from hypothesis import strategies as st

from apps.vampire_fees.detectors.recurring_fee import detect_recurring_fees
from apps.vampire_fees.tests.vf_builders import (
    default_vocabulary,
    fee_row,
    ledger_strategy,
    make_ledger,
    series_rows,
)
from ledger_kit.detectors import loaded_source_refs
from ledger_kit.models import Alert

VOCABULARY = default_vocabulary()
CONTEXT = MappingProxyType({"vocabulary": VOCABULARY})
TWO_DECIMALS = re.compile(r"^\d+\.\d{2}$")
MAINTENANCE = "Comisión mantenimiento cuenta"


def detect(entries: list[tuple[date, str]], **kwargs: Any) -> list[Alert]:
    """Run the detector on a maintenance-fee series."""
    return detect_recurring_fees(make_ledger(series_rows(entries, **kwargs)), CONTEXT)


def monthly(amount: str, *days: date) -> list[tuple[date, str]]:
    """Return (date, amount) entries for the given days."""
    return [(day, amount) for day in days]


MARCH_SERIES = (date(2026, 1, 5), date(2026, 2, 5), date(2026, 3, 5))


# --- Tier 1 -------------------------------------------------------------------------------------


def test_recurring_fee_fires_on_typical_input(ledger_with_monthly_fee: pd.DataFrame) -> None:
    """AE-VF-09: one warning alert with the three rows and the exact data."""
    alerts = detect_recurring_fees(ledger_with_monthly_fee, CONTEXT)
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.detector == "vf.recurring_fee"
    assert alert.severity == "warning"
    assert alert.title == f"Recurring monthly fee: BANCO FICTICIO · {MAINTENANCE}"
    assert alert.source_refs == ["vf_fixture.csv:0", "vf_fixture.csv:1", "vf_fixture.csv:2"]
    assert alert.data == {
        "counterparty": "BANCO FICTICIO",
        "description": MAINTENANCE,
        "interval_type": "monthly",
        "charge_count": 3,
        "current_amount": "5.00",
        "yearly_cost": "60.00",
        "first_charge_date": "2026-01-05",
        "last_charge_date": "2026-03-05",
    }


def test_recurring_fee_silent_on_clean_ledger(clean_ledger_10: pd.DataFrame) -> None:
    """A ledger without fee rows gives no alert."""
    assert detect_recurring_fees(clean_ledger_10, CONTEXT) == []


# --- Tier 2 -------------------------------------------------------------------------------------


def test_empty_ledger_gives_no_alert() -> None:
    """An empty frame, with or without columns, gives [] and does not raise."""
    assert detect_recurring_fees(pd.DataFrame(), MappingProxyType({})) == []
    assert detect_recurring_fees(make_ledger([]), CONTEXT) == []


def test_single_row_ledger_returns_a_list(single_row_ledger: pd.DataFrame) -> None:
    """One row gives a list, here empty."""
    assert detect_recurring_fees(single_row_ledger, CONTEXT) == []


def test_ae_vf_10_yearly_cost_below_the_warning_boundary() -> None:
    """AE-VF-10: 4.99 a month is 59.88 a year, severity info."""
    alerts = detect(monthly("4.99", *MARCH_SERIES))
    assert len(alerts) == 1
    assert alerts[0].data["yearly_cost"] == "59.88"
    assert alerts[0].severity == "info"


def test_ae_vf_11_two_monthly_charges_are_not_enough() -> None:
    """AE-VF-11: two monthly charges give nothing, the third gives an alert."""
    assert detect(monthly("5.00", *MARCH_SERIES[:2])) == []
    assert len(detect(monthly("5.00", *MARCH_SERIES))) == 1


def test_ae_vf_12_gaps_of_33_and_34_days() -> None:
    """AE-VF-12: gaps 33 and 31 are a run; gaps 34 and 31 are not."""
    assert len(detect(monthly("5.00", date(2026, 1, 1), date(2026, 2, 3), date(2026, 3, 6)))) == 1
    assert detect(monthly("5.00", date(2026, 1, 1), date(2026, 2, 4), date(2026, 3, 7))) == []


def test_first_and_last_day_of_the_monthly_window() -> None:
    """Gaps of 27 and 33 days alert; 26 and 34 days do not."""
    start = date(2026, 1, 1)
    for gap, expected in ((27, 1), (33, 1), (26, 0), (34, 0)):
        days = [start, start + timedelta(days=gap), start + timedelta(days=2 * gap)]
        assert len(detect(monthly("5.00", *days))) == expected, gap


def test_ae_vf_13_outlier_is_not_cited() -> None:
    """AE-VF-13: the early outlier is left out of the refs and of the figures."""
    days = (date(2025, 10, 1), *MARCH_SERIES)
    alerts = detect(monthly("5.00", *days))
    assert len(alerts) == 1
    assert alerts[0].source_refs == ["vf_fixture.csv:1", "vf_fixture.csv:2", "vf_fixture.csv:3"]
    assert alerts[0].data["charge_count"] == 3
    assert alerts[0].data["first_charge_date"] == "2026-01-05"


def test_ae_vf_14_quarterly_series() -> None:
    """AE-VF-14: 9.00 on 2026-03-31, 06-30, 09-30 is quarterly, 36.00 a year, info."""
    alerts = detect(monthly("9.00", date(2026, 3, 31), date(2026, 6, 30), date(2026, 9, 30)))
    assert len(alerts) == 1
    data = alerts[0].data
    assert data["interval_type"] == "quarterly" and data["charge_count"] == 3
    assert data["yearly_cost"] == "36.00"
    assert alerts[0].severity == "info"


def test_ae_vf_15_yearly_series() -> None:
    """AE-VF-15: 30.00 on 2025-02-14 and 2026-02-16 is a yearly run of 2."""
    alerts = detect(monthly("30.00", date(2025, 2, 14), date(2026, 2, 16)))
    assert len(alerts) == 1
    assert alerts[0].data["interval_type"] == "yearly"
    assert alerts[0].data["charge_count"] == 2
    assert alerts[0].data["yearly_cost"] == "30.00"


def test_ae_vf_16_irregular_gaps_give_no_alert() -> None:
    """AE-VF-16: gaps 104, 196 and 205 match no interval."""
    start = date(2025, 4, 9)
    days = [start]
    for gap in (104, 196, 205):
        days.append(days[-1] + timedelta(days=gap))
    assert detect(monthly("5.00", *days)) == []


def test_warning_threshold_on_both_sides() -> None:
    """A yearly cost of 60.00 is a warning, 59.99 is info (inclusive boundary)."""
    days = (date(2025, 2, 14), date(2026, 2, 16))
    assert detect(monthly("60.00", *days))[0].severity == "warning"
    assert detect(monthly("59.99", *days))[0].severity == "info"


def test_overdraft_rows_never_make_a_recurring_alert() -> None:
    """REQ-VF-15: overdraft interest every month is for vf.overdraft_cost only."""
    alerts = detect(monthly("5.00", *MARCH_SERIES), description="Intereses deudores")
    assert alerts == []


def test_duplicate_source_ref_is_handled() -> None:
    """Two rows with one source_ref count once: two charges are no series, and nothing raises."""
    rows = series_rows(monthly("5.00", *MARCH_SERIES))
    rows[2]["source_ref"] = rows[1]["source_ref"]
    assert detect_recurring_fees(make_ledger(rows), CONTEXT) == []


def test_without_vocabulary_only_concepts_count() -> None:
    """REQ-VF-12: no vocabulary in the context means concept-only classification."""
    entries = monthly("5.00", *MARCH_SERIES)
    plain = make_ledger(series_rows(entries))
    tagged = make_ledger(series_rows(entries, description="TARJ", tags=["common_concept:17"]))
    assert detect_recurring_fees(plain, MappingProxyType({})) == []
    assert len(detect_recurring_fees(tagged, MappingProxyType({}))) == 1


def test_two_series_give_two_alerts_ordered_by_first_row() -> None:
    """Different descriptions are different series; alerts follow their first cited row."""
    later = series_rows(
        monthly("5.00", date(2026, 1, 20), date(2026, 2, 20), date(2026, 3, 20)),
        description="Comisión tarjeta",
        first_row=0,
    )
    earlier = series_rows(monthly("7.00", *MARCH_SERIES), first_row=10)
    alerts = detect_recurring_fees(make_ledger(later + earlier), CONTEXT)
    assert [a.data["current_amount"] for a in alerts] == ["7.00", "5.00"]


def test_a_month_number_in_the_description_does_not_split_the_series() -> None:
    """AE-VF-08 in action: tokens with digits are dropped from the key."""
    rows = [
        fee_row(0, date(2026, 1, 5), "5.00", description=f"{MAINTENANCE} 01/26"),
        fee_row(1, date(2026, 2, 5), "5.00", description=f"{MAINTENANCE} 02/26"),
        fee_row(2, date(2026, 3, 5), "5.00", description=f"{MAINTENANCE} 03/26"),
    ]
    assert len(detect_recurring_fees(make_ledger(rows), CONTEXT)) == 1


# --- Tier 3 -------------------------------------------------------------------------------------


@settings(max_examples=200)
@given(ledger=ledger_strategy())
def test_source_refs_are_a_subset_of_the_loaded_refs(ledger: pd.DataFrame) -> None:
    """No invention: every cited ref belongs to a loaded row; refs are unique and non-empty."""
    loaded = loaded_source_refs(ledger, CONTEXT)
    for alert in detect_recurring_fees(ledger, CONTEXT):
        assert alert.source_refs
        assert len(set(alert.source_refs)) == len(alert.source_refs)
        assert set(alert.source_refs) <= loaded


@settings(max_examples=200)
@given(ledger=ledger_strategy())
def test_detector_is_idempotent(ledger: pd.DataFrame) -> None:
    """Two runs on the same input return equal alerts."""
    assert detect_recurring_fees(ledger, CONTEXT) == detect_recurring_fees(ledger, CONTEXT)


@settings(max_examples=200)
@given(empty=st.sampled_from([pd.DataFrame(), make_ledger([])]))
def test_empty_input_gives_no_alert(empty: pd.DataFrame) -> None:
    """Empty frames give []."""
    assert detect_recurring_fees(empty, CONTEXT) == []


@settings(max_examples=200)
@given(ledger=ledger_strategy())
def test_data_values_are_plain_and_money_is_non_negative(ledger: pd.DataFrame) -> None:
    """REQ-VF-32: data holds str, int or list[str]; money is a non-negative 2-decimal string."""
    for alert in detect_recurring_fees(ledger, CONTEXT):
        for key, value in alert.data.items():
            assert isinstance(value, (str, int, list))
            assert not isinstance(value, bool)
            if key in ("current_amount", "yearly_cost"):
                assert TWO_DECIMALS.match(value)


@settings(max_examples=200)
@given(ledger=ledger_strategy())
def test_cited_rows_are_fee_rows_and_match_the_charge_count(ledger: pd.DataFrame) -> None:
    """The refs resolve to ledger rows and their number equals charge_count."""
    known = set(ledger["source_ref"]) if not ledger.empty else set()
    for alert in detect_recurring_fees(ledger, CONTEXT):
        assert set(alert.source_refs) <= known
        assert len(alert.source_refs) == alert.data["charge_count"]
