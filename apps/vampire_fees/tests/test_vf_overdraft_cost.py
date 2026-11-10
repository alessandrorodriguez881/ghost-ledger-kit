"""Tests for the vf.overdraft_cost detector (Task VF8; AE-VF-21 to AE-VF-23)."""

from datetime import date
from decimal import Decimal
from types import MappingProxyType

import pandas as pd
from hypothesis import given, settings
from hypothesis import strategies as st

from apps.vampire_fees.detectors.overdraft_cost import detect_overdraft_cost
from apps.vampire_fees.detectors.utils import extract_fees
from apps.vampire_fees.tests.vf_builders import (
    default_vocabulary,
    fee_row,
    ledger_strategy,
    make_ledger,
)
from ledger_kit.detectors import loaded_source_refs
from ledger_kit.models import Alert

VOCABULARY = default_vocabulary()
CONTEXT = MappingProxyType({"vocabulary": VOCABULARY})
INTEREST = "Intereses deudores"
OVERDRAFT_FEE = "Comisión por descubierto"


def detect(*entries: tuple[str, str, str], tags: object = None) -> list[Alert]:
    """Run the detector on (iso date, description, amount) entries."""
    rows = [
        fee_row(i, date.fromisoformat(day), amount, description=text, tags=tags)
        for i, (day, text, amount) in enumerate(entries)
    ]
    return detect_overdraft_cost(make_ledger(rows), CONTEXT)


# --- Tier 1 -------------------------------------------------------------------------------------


def test_overdraft_cost_fires_on_typical_input(ledger_with_overdraft: pd.DataFrame) -> None:
    """AE-VF-21: interest 12.40 and a fee 15.00 give one warning with exact data."""
    alerts = detect_overdraft_cost(ledger_with_overdraft, CONTEXT)
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.detector == "vf.overdraft_cost"
    assert alert.severity == "warning"
    assert alert.title == "Overdraft cost on this statement"
    assert alert.source_refs == ["vf_fixture.csv:0", "vf_fixture.csv:1"]
    assert alert.data == {
        "interest_count": 1,
        "interest_total": "12.40",
        "fee_count": 1,
        "fee_total": "15.00",
        "total": "27.40",
        "first_charge_date": "2025-06-18",
        "last_charge_date": "2025-06-30",
    }


def test_overdraft_cost_silent_on_clean_ledger(clean_ledger_10: pd.DataFrame) -> None:
    """A ledger without overdraft rows gives no alert."""
    assert detect_overdraft_cost(clean_ledger_10, CONTEXT) == []


# --- Tier 2 -------------------------------------------------------------------------------------


def test_empty_ledger_gives_no_alert() -> None:
    """An empty frame gives [] and does not raise."""
    assert detect_overdraft_cost(pd.DataFrame(), MappingProxyType({})) == []
    assert detect_overdraft_cost(make_ledger([]), CONTEXT) == []


def test_single_row_ledger_returns_a_list(single_row_ledger: pd.DataFrame) -> None:
    """One non-overdraft row gives a list."""
    assert detect_overdraft_cost(single_row_ledger, CONTEXT) == []


def test_one_overdraft_row_is_enough() -> None:
    """A single overdraft row raises the alert."""
    alerts = detect(("2025-06-30", INTEREST, "1.00"))
    assert len(alerts) == 1 and alerts[0].source_refs == ["vf_fixture.csv:0"]


def test_ae_vf_22_critical_boundary() -> None:
    """AE-VF-22: a total of 100.00 is critical, 99.99 is a warning."""
    critical = detect(("2025-06-18", INTEREST, "60.00"), ("2025-06-30", OVERDRAFT_FEE, "40.00"))
    warning = detect(("2025-06-18", INTEREST, "60.00"), ("2025-06-30", OVERDRAFT_FEE, "39.99"))
    assert critical[0].data["total"] == "100.00" and critical[0].severity == "critical"
    assert warning[0].data["total"] == "99.99" and warning[0].severity == "warning"


def test_ae_vf_23_no_overdraft_no_alert(ledger_with_monthly_fee: pd.DataFrame) -> None:
    """AE-VF-23: other fees alone give no overdraft alert."""
    assert detect_overdraft_cost(ledger_with_monthly_fee, CONTEXT) == []


def test_only_interest_rows() -> None:
    """Interest only: the fee count and total are zero."""
    data = detect(("2025-06-30", INTEREST, "12.40"))[0].data
    assert data["fee_count"] == 0 and data["fee_total"] == "0.00"
    assert data["interest_count"] == 1 and data["interest_total"] == "12.40"


def test_only_fee_rows() -> None:
    """Overdraft fees only: the interest count and total are zero."""
    data = detect(("2025-06-18", OVERDRAFT_FEE, "15.00"))[0].data
    assert data["interest_count"] == 0 and data["interest_total"] == "0.00"
    assert data["fee_count"] == 1 and data["fee_total"] == "15.00"


def test_concept_17_row_with_an_overdraft_word_is_overdraft() -> None:
    """The kind applies to concept-accepted rows; without the word it is not overdraft."""
    assert len(detect(("2025-06-30", INTEREST, "5.00"), tags=["common_concept:17"])) == 1
    assert detect(("2025-06-30", "Cargo", "5.00"), tags=["common_concept:17"]) == []


def test_credits_and_other_currencies_are_not_counted() -> None:
    """A refund of overdraft interest (credit) and a USD row are no overdraft cost."""
    rows = [
        fee_row(0, date(2025, 6, 30), "12.40", description=INTEREST, flow="credit"),
        fee_row(1, date(2025, 6, 30), "12.40", description=INTEREST, currency="USD"),
    ]
    assert detect_overdraft_cost(make_ledger(rows), CONTEXT) == []


def test_duplicate_source_ref_is_handled() -> None:
    """Two rows with one source_ref count once."""
    rows = [
        fee_row(0, date(2025, 6, 18), "15.00", description=OVERDRAFT_FEE, source_ref="s.csv:3"),
        fee_row(1, date(2025, 6, 30), "12.40", description=INTEREST, source_ref="s.csv:3"),
    ]
    alerts = detect_overdraft_cost(make_ledger(rows), CONTEXT)
    assert len(alerts) == 1
    assert alerts[0].source_refs == ["s.csv:3"] and alerts[0].data["total"] == "15.00"


def test_refs_are_ordered_by_date_then_row_not_by_text() -> None:
    """Row 10 on an earlier date comes before row 2 on a later date; ties by row number."""
    rows = [
        fee_row(2, date(2025, 7, 1), "1.00", description=INTEREST),
        fee_row(10, date(2025, 6, 1), "1.00", description=INTEREST),
        fee_row(9, date(2025, 6, 1), "1.00", description=INTEREST),
    ]
    alert = detect_overdraft_cost(make_ledger(rows), CONTEXT)[0]
    assert alert.source_refs == ["vf_fixture.csv:9", "vf_fixture.csv:10", "vf_fixture.csv:2"]


# --- Tier 3 -------------------------------------------------------------------------------------


@settings(max_examples=200)
@given(ledger=ledger_strategy())
def test_source_refs_are_a_subset_of_the_loaded_refs(ledger: pd.DataFrame) -> None:
    """No invention: every cited ref belongs to a loaded row."""
    loaded = loaded_source_refs(ledger, CONTEXT)
    for alert in detect_overdraft_cost(ledger, CONTEXT):
        assert alert.source_refs
        assert set(alert.source_refs) <= loaded


@settings(max_examples=200)
@given(ledger=ledger_strategy())
def test_detector_is_idempotent(ledger: pd.DataFrame) -> None:
    """Two runs on the same input return equal alerts."""
    assert detect_overdraft_cost(ledger, CONTEXT) == detect_overdraft_cost(ledger, CONTEXT)


@settings(max_examples=200)
@given(empty=st.sampled_from([pd.DataFrame(), make_ledger([])]))
def test_empty_input_gives_no_alert(empty: pd.DataFrame) -> None:
    """Empty frames give []."""
    assert detect_overdraft_cost(empty, CONTEXT) == []


@settings(max_examples=200)
@given(ledger=ledger_strategy())
def test_total_is_the_sum_of_the_parts_and_refs_are_the_overdraft_rows(
    ledger: pd.DataFrame,
) -> None:
    """total == interest_total + fee_total, refs equal the overdraft rows, counts add up."""
    overdraft = [f for f in extract_fees(ledger, VOCABULARY) if f.kind == "overdraft"]
    alerts = detect_overdraft_cost(ledger, CONTEXT)
    if not overdraft:
        assert alerts == []
        return
    assert len(alerts) == 1
    data = alerts[0].data
    assert Decimal(data["total"]) == Decimal(data["interest_total"]) + Decimal(data["fee_total"])
    assert data["interest_count"] + data["fee_count"] == len(alerts[0].source_refs)
    assert set(alerts[0].source_refs) == {f.source_ref for f in overdraft}
    assert Decimal(data["total"]) >= 0
    assert all(isinstance(v, (str, int)) for v in data.values())
