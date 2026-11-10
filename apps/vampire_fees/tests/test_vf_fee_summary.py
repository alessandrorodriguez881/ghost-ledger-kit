"""Tests for the vf.fee_summary detector (Task VF9; AE-VF-24 to AE-VF-26)."""

from datetime import date
from decimal import Decimal
from types import MappingProxyType

import pandas as pd
from hypothesis import given, settings
from hypothesis import strategies as st

from apps.vampire_fees.detectors.fee_summary import detect_fee_summary
from apps.vampire_fees.tests.vf_builders import (
    default_vocabulary,
    fee_row,
    ledger_strategy,
    make_ledger,
    summary_ledger,
)
from ledger_kit.detectors import loaded_source_refs
from ledger_kit.models import Alert

VOCABULARY = default_vocabulary()
CONTEXT = MappingProxyType({"vocabulary": VOCABULARY})


def summarise(ledger: pd.DataFrame) -> list[Alert]:
    """Run the detector with the default vocabulary."""
    return detect_fee_summary(ledger, CONTEXT)


def one_fee_statement(amount: str, first: date, last: date, fee_day: date) -> pd.DataFrame:
    """A credit on `first`, a maintenance fee on `fee_day` and a purchase on `last`."""
    rows = [
        fee_row(0, first, "100.00", flow="credit", description="Payroll", counterparty="Luna"),
        fee_row(1, fee_day, amount),
        fee_row(2, last, "5.00", description="Card purchase", counterparty="Tienda Luna"),
    ]
    return make_ledger(rows)


# --- Tier 1 -------------------------------------------------------------------------------------


def test_fee_summary_fires_on_typical_input() -> None:
    """AE-VF-24: two fees, a 90-day statement: yearly equivalent 121.67, severity info."""
    alerts = summarise(summary_ledger())
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.detector == "vf.fee_summary"
    assert alert.severity == "info"
    assert alert.title == "Bank fees on this statement"
    assert alert.source_refs == ["s.csv:3", "s.csv:5"]
    assert alert.data == {
        "fee_count": 2,
        "total_fees": "30.00",
        "first_date": "2026-01-01",
        "last_date": "2026-03-31",
        "span_days": 90,
        "yearly_equivalent": "121.67",
    }


def test_fee_summary_silent_on_clean_ledger(clean_ledger_10: pd.DataFrame) -> None:
    """No fee row, no summary."""
    assert summarise(clean_ledger_10) == []


# --- Tier 2 -------------------------------------------------------------------------------------


def test_empty_ledger_gives_no_alert() -> None:
    """An empty frame gives [] and does not raise."""
    assert detect_fee_summary(pd.DataFrame(), MappingProxyType({})) == []
    assert summarise(make_ledger([])) == []


def test_single_row_ledger_is_a_summary_without_yearly_figure(
    single_row_ledger: pd.DataFrame,
) -> None:
    """One fee row: a list with one alert, one day long, so no yearly equivalent."""
    alerts = summarise(single_row_ledger)
    assert len(alerts) == 1
    assert alerts[0].data["span_days"] == 1
    assert "yearly_equivalent" not in alerts[0].data


def test_ae_vf_25_89_days_has_no_yearly_equivalent() -> None:
    """AE-VF-25: statement 2026-01-01 to 2026-03-30 is 89 days: no yearly figure."""
    alert = summarise(summary_ledger(date(2026, 3, 30)))[0]
    assert alert.data["span_days"] == 89
    assert "yearly_equivalent" not in alert.data
    assert alert.severity == "info"


def test_ae_vf_26_warning_boundary() -> None:
    """AE-VF-26: 200.00 over exactly 365 days is a warning, 199.99 is info."""
    first, last, fee_day = date(2026, 1, 1), date(2026, 12, 31), date(2026, 6, 15)
    high = summarise(one_fee_statement("200.00", first, last, fee_day))[0]
    low = summarise(one_fee_statement("199.99", first, last, fee_day))[0]
    assert high.data["span_days"] == 365
    assert high.data["yearly_equivalent"] == "200.00" and high.severity == "warning"
    assert low.data["yearly_equivalent"] == "199.99" and low.severity == "info"


def test_a_credit_refund_does_not_change_the_total() -> None:
    """Refunds are not subtracted (REQ-VF-13)."""
    base = summary_ledger()
    refund = fee_row(
        7,
        date(2026, 2, 1),
        "10.00",
        description="Devolución comisión transferencia",
        flow="credit",
        tags=["common_concept:17"],
        source_file="s.csv",
    )
    with_refund = make_ledger([*base.to_dict("records"), refund])
    assert summarise(with_refund)[0].data == summarise(base)[0].data


def test_a_non_eur_row_neither_counts_nor_extends_the_span() -> None:
    """A USD fee is not counted and a USD row after the last EUR day does not move the span."""
    rows = [
        *summary_ledger().to_dict("records"),
        fee_row(7, date(2027, 1, 1), "50.00", currency="USD", source_file="s.csv"),
    ]
    alert = summarise(make_ledger(rows))[0]
    assert alert.data["fee_count"] == 2 and alert.data["last_date"] == "2026-03-31"


def test_fees_on_one_day_of_a_longer_statement() -> None:
    """Fees on a single day still cite that day's rows; the span is the statement's."""
    rows = [
        fee_row(0, date(2026, 1, 1), "100.00", flow="credit", description="Payroll"),
        fee_row(1, date(2026, 2, 1), "3.00"),
        fee_row(2, date(2026, 2, 1), "4.00", description="Comisión tarjeta"),
        fee_row(3, date(2026, 4, 30), "9.00", description="Card purchase", counterparty="Luna"),
    ]
    alert = summarise(make_ledger(rows))[0]
    assert alert.data["fee_count"] == 2 and alert.data["total_fees"] == "7.00"
    assert alert.data["span_days"] == 120


def test_credits_widen_the_span() -> None:
    """The span runs from the first to the last EUR row of any flow."""
    rows = [
        fee_row(0, date(2026, 1, 10), "5.00"),
        fee_row(1, date(2026, 1, 1), "50.00", flow="credit", description="Payroll"),
        fee_row(2, date(2026, 4, 20), "50.00", flow="credit", description="Payroll"),
    ]
    alert = summarise(make_ledger(rows))[0]
    assert alert.data["first_date"] == "2026-01-01" and alert.data["last_date"] == "2026-04-20"
    assert alert.data["span_days"] == 110


def test_summary_counts_every_kind_of_fee() -> None:
    """Overdraft rows and recurring fees are all in the total."""
    rows = [
        fee_row(0, date(2026, 1, 5), "5.00"),
        fee_row(1, date(2026, 1, 31), "12.40", description="Intereses deudores"),
        fee_row(2, date(2026, 2, 3), "1.50", description="Comisión transferencia inmediata"),
    ]
    alert = summarise(make_ledger(rows))[0]
    assert alert.data["fee_count"] == 3 and alert.data["total_fees"] == "18.90"


def test_duplicate_source_ref_is_handled() -> None:
    """Two rows with one source_ref count once."""
    rows = [
        fee_row(0, date(2026, 1, 5), "5.00", source_ref="s.csv:1"),
        fee_row(1, date(2026, 2, 5), "7.00", source_ref="s.csv:1"),
    ]
    alert = summarise(make_ledger(rows))[0]
    assert alert.source_refs == ["s.csv:1"] and alert.data["total_fees"] == "5.00"


# --- Tier 3 -------------------------------------------------------------------------------------


@settings(max_examples=200)
@given(ledger=ledger_strategy())
def test_source_refs_are_a_subset_of_the_loaded_refs(ledger: pd.DataFrame) -> None:
    """No invention: every cited ref belongs to a loaded row."""
    loaded = loaded_source_refs(ledger, CONTEXT)
    for alert in summarise(ledger):
        assert alert.source_refs
        assert set(alert.source_refs) <= loaded


@settings(max_examples=200)
@given(ledger=ledger_strategy())
def test_detector_is_idempotent(ledger: pd.DataFrame) -> None:
    """Two runs on the same input return equal alerts."""
    assert summarise(ledger) == summarise(ledger)


@settings(max_examples=200)
@given(empty=st.sampled_from([pd.DataFrame(), make_ledger([])]))
def test_empty_input_gives_no_alert(empty: pd.DataFrame) -> None:
    """Empty frames give []."""
    assert summarise(empty) == []


@settings(max_examples=200)
@given(ledger=ledger_strategy())
def test_total_fees_equals_the_sum_of_the_cited_rows(ledger: pd.DataFrame) -> None:
    """total_fees is the sum of the cited rows' amounts and fee_count their number."""
    by_ref = {str(r["source_ref"]): r["amount"] for r in ledger.to_dict("records")}
    for alert in summarise(ledger):
        cited = [by_ref[ref] for ref in alert.source_refs]
        assert Decimal(alert.data["total_fees"]) == sum(cited, Decimal(0))
        assert alert.data["fee_count"] == len(alert.source_refs)
        assert alert.data["span_days"] >= 1


@settings(max_examples=200)
@given(ledger=ledger_strategy())
def test_yearly_equivalent_only_for_long_statements(ledger: pd.DataFrame) -> None:
    """yearly_equivalent is present exactly when span_days >= 90 and is non-negative."""
    for alert in summarise(ledger):
        data = alert.data
        assert ("yearly_equivalent" in data) == (data["span_days"] >= 90)
        if "yearly_equivalent" in data:
            assert Decimal(data["yearly_equivalent"]) >= 0
        assert all(isinstance(v, (str, int)) for v in data.values())
