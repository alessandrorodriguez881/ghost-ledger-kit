"""Tests for the vf.fee_increase detector (Task VF7; AE-VF-17 to AE-VF-20)."""

import re
from datetime import date, timedelta
from decimal import Decimal
from types import MappingProxyType
from typing import Any

import pandas as pd
from hypothesis import given, settings
from hypothesis import strategies as st

from apps.vampire_fees.detectors.fee_increase import detect_fee_increases
from apps.vampire_fees.tests.vf_builders import (
    default_vocabulary,
    ledger_strategy,
    make_ledger,
    series_rows,
)
from ledger_kit.detectors import loaded_source_refs
from ledger_kit.models import Alert

VOCABULARY = default_vocabulary()
CONTEXT = MappingProxyType({"vocabulary": VOCABULARY})
TWO_DECIMALS = re.compile(r"^\d+\.\d{2}$")
ONE_DECIMAL = re.compile(r"^\d+\.\d$")
MAINTENANCE = "Comisión mantenimiento cuenta"

NOV, DEC, JAN, FEB = date(2025, 11, 5), date(2025, 12, 5), date(2026, 1, 5), date(2026, 2, 5)


def detect(entries: list[tuple[date, str]], **kwargs: Any) -> list[Alert]:
    """Run the detector on a maintenance-fee series."""
    return detect_fee_increases(make_ledger(series_rows(entries, **kwargs)), CONTEXT)


def monthly_amounts(*amounts: str, start: date = NOV) -> list[tuple[date, str]]:
    """Return monthly entries (30-day steps) with the given amounts."""
    return [(start + timedelta(days=30 * i), amount) for i, amount in enumerate(amounts)]


# --- Tier 1 -------------------------------------------------------------------------------------


def test_fee_increase_fires_on_typical_input(ledger_with_fee_increase: pd.DataFrame) -> None:
    """AE-VF-17: 5.00, 5.00, 5.00, 5.25 gives one warning with the exact data."""
    alerts = detect_fee_increases(ledger_with_fee_increase, CONTEXT)
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.detector == "vf.fee_increase"
    assert alert.severity == "warning"
    assert alert.title == f"Fee increase: BANCO FICTICIO · {MAINTENANCE}"
    assert alert.source_refs == ["vf_fixture.csv:2", "vf_fixture.csv:3"]
    assert alert.data == {
        "counterparty": "BANCO FICTICIO",
        "description": MAINTENANCE,
        "interval_type": "monthly",
        "old_amount": "5.00",
        "new_amount": "5.25",
        "increase_percent": "5.0",
        "increase_date": "2026-02-05",
        "old_charge_date": "2026-01-05",
        "extra_cost_per_year": "3.00",
        "yearly_cost": "63.00",
    }


def test_fee_increase_silent_on_clean_ledger(clean_ledger_10: pd.DataFrame) -> None:
    """A ledger without fee rows gives no alert."""
    assert detect_fee_increases(clean_ledger_10, CONTEXT) == []


def test_ae_vf_20_demo_case() -> None:
    """AE-VF-20: 12 charges of 5.00 then 10 of 6.50."""
    entries: list[tuple[date, str]] = []
    for month in range(1, 13):
        entries.append((date(2025, month, 5), "5.00"))
    for month in range(1, 11):
        entries.append((date(2026, month, 5), "6.50"))
    alerts = detect(entries)
    assert len(alerts) == 1
    data = alerts[0].data
    assert data["old_amount"] == "5.00" and data["new_amount"] == "6.50"
    assert data["increase_percent"] == "30.0"
    assert data["increase_date"] == "2026-01-05" and data["old_charge_date"] == "2025-12-05"
    assert data["extra_cost_per_year"] == "18.00" and data["yearly_cost"] == "78.00"
    assert alerts[0].severity == "warning"
    assert alerts[0].source_refs == ["vf_fixture.csv:11", "vf_fixture.csv:12"]


# --- Tier 2 -------------------------------------------------------------------------------------


def test_empty_ledger_gives_no_alert() -> None:
    """An empty frame gives [] and does not raise."""
    assert detect_fee_increases(pd.DataFrame(), MappingProxyType({})) == []
    assert detect_fee_increases(make_ledger([]), CONTEXT) == []


def test_single_row_ledger_returns_a_list(single_row_ledger: pd.DataFrame) -> None:
    """One row gives a list."""
    assert detect_fee_increases(single_row_ledger, CONTEXT) == []


def test_minimum_ratio_boundary() -> None:
    """AE-VF-17: 5.25 is a rise (exactly 5 %), 5.24 is not."""
    assert len(detect(monthly_amounts("5.00", "5.00", "5.00", "5.25"))) == 1
    assert detect(monthly_amounts("5.00", "5.00", "5.00", "5.24")) == []


def test_critical_ratio_boundary() -> None:
    """AE-VF-18: a rise of exactly 50 % is critical, 7.49 is a warning."""
    assert detect(monthly_amounts("5.00", "5.00", "5.00", "7.50"))[0].severity == "critical"
    assert detect(monthly_amounts("5.00", "5.00", "5.00", "7.49"))[0].severity == "warning"


def test_ae_vf_19_a_spike_is_not_a_new_price() -> None:
    """AE-VF-19: 5.00, 5.00, 9.00, 5.00 raises nothing."""
    assert detect(monthly_amounts("5.00", "5.00", "9.00", "5.00")) == []


def test_a_fall_raises_nothing() -> None:
    """6.50 then 5.00 is a fall."""
    assert detect(monthly_amounts("6.50", "6.50", "6.50", "5.00", "5.00")) == []


def test_two_rises_report_the_latest() -> None:
    """With 5.00, 5.00, 6.00, 6.00, 8.00 the rise to 8.00 is reported."""
    alerts = detect(monthly_amounts("5.00", "5.00", "6.00", "6.00", "8.00"))
    assert len(alerts) == 1
    assert alerts[0].data["old_amount"] == "6.00" and alerts[0].data["new_amount"] == "8.00"
    assert alerts[0].source_refs == ["vf_fixture.csv:3", "vf_fixture.csv:4"]


def test_stable_ratio_boundary() -> None:
    """A later charge exactly 2 % above the new level holds, one cent more does not."""
    assert len(detect(monthly_amounts("5.00", "5.00", "10.00", "10.20"))) == 1
    assert detect(monthly_amounts("5.00", "5.00", "10.00", "10.21")) == []


def test_quarterly_run_of_two_rows_can_rise() -> None:
    """A run of two quarterly rows is enough: 9.00 then 10.00."""
    alerts = detect([(date(2026, 3, 31), "9.00"), (date(2026, 6, 30), "10.00")])
    assert len(alerts) == 1
    data = alerts[0].data
    assert data["interval_type"] == "quarterly"
    assert data["extra_cost_per_year"] == "4.00" and data["yearly_cost"] == "40.00"


def test_zero_amount_rows_do_not_crash() -> None:
    """A zero old amount has no percentage; no alert and no exception."""
    assert detect(monthly_amounts("0.00", "0.00", "5.00")) == []


def test_duplicate_source_ref_is_handled() -> None:
    """Two rows with one source_ref count once and nothing raises."""
    rows = series_rows(monthly_amounts("5.00", "5.00", "5.00", "5.25"))
    rows[3]["source_ref"] = rows[2]["source_ref"]
    assert detect_fee_increases(make_ledger(rows), CONTEXT) == []


def test_overdraft_rows_never_make_a_rise() -> None:
    """Overdraft interest that changes every period is not a rising recurring fee."""
    entries = monthly_amounts("5.00", "5.00", "5.00", "9.00")
    assert detect(entries, description="Intereses deudores") == []


# --- Tier 3 -------------------------------------------------------------------------------------


@settings(max_examples=200)
@given(ledger=ledger_strategy())
def test_source_refs_are_a_subset_of_the_loaded_refs(ledger: pd.DataFrame) -> None:
    """No invention: both cited refs belong to a loaded row."""
    loaded = loaded_source_refs(ledger, CONTEXT)
    for alert in detect_fee_increases(ledger, CONTEXT):
        assert len(alert.source_refs) == 2
        assert set(alert.source_refs) <= loaded


@settings(max_examples=200)
@given(ledger=ledger_strategy())
def test_detector_is_idempotent(ledger: pd.DataFrame) -> None:
    """Two runs on the same input return equal alerts."""
    assert detect_fee_increases(ledger, CONTEXT) == detect_fee_increases(ledger, CONTEXT)


@settings(max_examples=200)
@given(empty=st.sampled_from([pd.DataFrame(), make_ledger([])]))
def test_empty_input_gives_no_alert(empty: pd.DataFrame) -> None:
    """Empty frames give []."""
    assert detect_fee_increases(empty, CONTEXT) == []


@settings(max_examples=200)
@given(
    base=st.decimals(min_value=Decimal("1.00"), max_value=Decimal("50.00"), places=2),
    extra=st.decimals(min_value=Decimal("0.00"), max_value=Decimal("50.00"), places=2),
)
def test_a_reported_rise_is_a_rise_with_plain_data(base: Decimal, extra: Decimal) -> None:
    """old_amount < new_amount, money has two decimals, the percent one decimal."""
    entries = monthly_amounts(str(base), str(base), str(base), str(base + extra))
    for alert in detect(entries):
        data = alert.data
        assert Decimal(data["old_amount"]) < Decimal(data["new_amount"])
        for key in ("old_amount", "new_amount", "extra_cost_per_year", "yearly_cost"):
            assert TWO_DECIMALS.match(data[key])
        assert ONE_DECIMAL.match(data["increase_percent"])
        assert all(isinstance(v, str) for v in data.values())


@settings(max_examples=200)
@given(ledger=ledger_strategy())
def test_amounts_in_a_generated_ledger_are_never_negative(ledger: pd.DataFrame) -> None:
    """With only positive inputs no alert carries a negative amount."""
    for alert in detect_fee_increases(ledger, CONTEXT):
        for key in ("old_amount", "new_amount", "extra_cost_per_year", "yearly_cost"):
            assert Decimal(alert.data[key]) >= 0
