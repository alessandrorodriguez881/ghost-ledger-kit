"""Tests for the pi.duplicate_invoice detector (Task P10)."""

from datetime import date, timedelta
from decimal import Decimal
from types import MappingProxyType
from typing import Any

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from apps.phantom_invoices.detectors.duplicate_invoice import (
    DUPLICATE_TOTAL_TOLERANCE,
    DUPLICATE_WINDOW_DAYS,
    SAME_NUMBER_WINDOW_DAYS,
    detect_duplicate_invoices,
)
from apps.phantom_invoices.tests.pi_builders import SUPPLIER_NAMES, Scenario, ctx, make_invoices
from apps.phantom_invoices.tests.pi_strategies import consecutive_numbers, with_dirty_cells
from ledger_kit.detectors import loaded_source_refs, run_all
from ledger_kit.models import Alert

DETECTOR = "pi.duplicate_invoice"
NAME_1 = SUPPLIER_NAMES[1]
DAY_ONE = date(2026, 3, 2)
CONTRACT_KEYS = {
    "variant",
    "supplier_name",
    "invoice_count",
    "invoice_numbers",
    "totals",
    "total",
    "first_issue_date",
    "last_issue_date",
    "days_apart",
}


def _run(rows: list[dict[str, Any]]) -> list[Alert]:
    """Run the detector on invoices built from `rows` with an empty context."""
    return detect_duplicate_invoices(make_invoices(rows), ctx())


def _pair(first: str, second: str, gap: int, **extra: Any) -> list[dict[str, Any]]:
    """Two invoices of supplier 1, base 75.00 (total 90.75), `gap` days apart."""
    common: dict[str, Any] = {"base_amount": Decimal("75.00"), **extra}
    return [
        {"invoice_number": first, "issue_date": DAY_ONE, **common},
        {"invoice_number": second, "issue_date": DAY_ONE + timedelta(days=gap), **common},
    ]


# Rows 0-2: one supplier, rules A and B in one component; rows 3-4: rule C; rows 5-6: a multi-rate
# invoice of supplier 2 (dropped). The expected outcome is exactly two alerts.
BASE_ROWS: list[dict[str, Any]] = [
    {"invoice_number": "F-2026-0042", "issue_date": date(2026, 3, 1)},
    {"invoice_number": "F-2026-0042", "issue_date": date(2026, 3, 2)},
    {"invoice_number": "F2026-042", "issue_date": date(2026, 3, 3)},
    {"invoice_number": "FAC-0101", "issue_date": date(2026, 4, 1), "base_amount": Decimal("75.00")},
    {"invoice_number": "FAC-0102", "issue_date": date(2026, 4, 5), "base_amount": Decimal("75.00")},
    {"invoice_number": "G-1", "supplier": 2, "issue_date": date(2026, 4, 5)},
    {
        "invoice_number": "G-1",
        "supplier": 2,
        "issue_date": date(2026, 4, 6),
        "vat_rate": Decimal("10"),
    },
]
BASE_LEDGER = make_invoices(BASE_ROWS)


# Tier 1: normal cases


def test_duplicate_invoice_fires_on_typical_input(ledger_with_duplicate_invoice: Scenario) -> None:
    """The P1 fixture (the same invoice twice) raises exactly one critical alert."""
    scenario = ledger_with_duplicate_invoice

    alerts = detect_duplicate_invoices(scenario.invoices, scenario.context())

    assert len(alerts) == 1
    assert alerts[0].detector == DETECTOR
    assert alerts[0].severity == "critical"
    assert alerts[0].source_refs == ["inv.csv:0", "inv.csv:1"]
    assert alerts[0].data["variant"] == "same_number"


def test_duplicate_invoice_silent_on_clean_ledger(clean_ledger_10: pd.DataFrame) -> None:
    """Ten clean invoices of three suppliers raise no duplicate alert."""
    assert detect_duplicate_invoices(clean_ledger_10, ctx()) == []


def test_pi_acceptance_p01_same_invoice_twice(ledger_with_duplicate_invoice: Scenario) -> None:
    """P1: one critical same_number alert citing both rows (the other detectors: Task P14)."""
    scenario = ledger_with_duplicate_invoice

    alerts = detect_duplicate_invoices(scenario.invoices, scenario.context())

    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.detector == DETECTOR
    assert alert.severity == "critical"
    assert alert.title == f"Duplicate invoice: F-2026-0042 ({NAME_1})"
    assert alert.source_refs == ["inv.csv:0", "inv.csv:1"]
    assert alert.data["invoice_count"] == 2
    assert alert.data["totals"] == ["121.00", "121.00"]
    assert alert.data["days_apart"] == 0


def test_pi_acceptance_p02_monthly_rent_no_alert() -> None:
    """P2: three monthly rent invoices with the same total, 30 days apart, raise nothing."""
    rows = [
        {
            "invoice_number": f"ALQ-2026-{month:02d}",
            "issue_date": issued,
            "base_amount": Decimal("600.00"),
        }
        for month, issued in ((1, date(2026, 1, 5)), (2, date(2026, 2, 4)), (3, date(2026, 3, 6)))
    ]

    assert _run(rows) == []


def test_pi_acceptance_p03_near_identical_numbers(ledger_with_near_duplicate: Scenario) -> None:
    """P3: F-2026-0042 and F2026-042 three days apart give one near_identical_number warning."""
    scenario = ledger_with_near_duplicate

    alerts = detect_duplicate_invoices(scenario.invoices, scenario.context())

    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.detector == DETECTOR
    assert alert.severity == "warning"
    assert alert.title == f"Possible duplicate invoice: F-2026-0042 ({NAME_1})"
    assert alert.source_refs == ["inv.csv:0", "inv.csv:1"]
    assert alert.data["variant"] == "near_identical_number"
    assert alert.data["days_apart"] == 3
    assert alert.data["total"] == "121.00"


@pytest.mark.parametrize(("gap", "expected"), [(6, 1), (7, 0), (8, 0)])
def test_pi_acceptance_p10_same_total_6_7_8_days(gap: int, expected: int) -> None:
    """P10: same supplier and total, different numbers: 6 days alerts, 7 and 8 do not."""
    alerts = _run(_pair("FAC-0101", "FAC-0102", gap))

    assert len(alerts) == expected
    for alert in alerts:
        assert alert.detector == DETECTOR
        assert alert.severity == "warning"
        assert alert.source_refs == ["inv.csv:0", "inv.csv:1"]
        assert alert.data["variant"] == "same_total_close_dates"
        assert alert.data["days_apart"] == 6
        assert alert.data["total"] == "90.75"


def test_pi_same_number_2_days_apart_is_critical() -> None:
    """REQ-PI-21a: the same number two days apart is a critical same_number alert."""
    alerts = _run(_pair("F-2026-0042", "F-2026-0042", 2))

    assert len(alerts) == 1
    assert alerts[0].severity == "critical"
    assert alerts[0].data["variant"] == "same_number"


def test_pi_same_number_200_days_apart_no_alert() -> None:
    """REQ-PI-21a: the same number 200 days apart is an annual numbering restart."""
    assert _run(_pair("F-2026-0042", "F-2026-0042", 200)) == []


def test_alert_title_and_data_contract() -> None:
    """Every key of REQ-PI-20 is present and Alert.data holds only str, int and list[str]."""
    alerts = _run(_pair("F-2026-0042", "F-2026-0042", 2))

    data = alerts[0].data
    assert set(data) == CONTRACT_KEYS
    assert data["supplier_name"] == NAME_1
    assert data["invoice_numbers"] == ["F-2026-0042", "F-2026-0042"]
    assert data["first_issue_date"] == "2026-03-02"
    assert data["last_issue_date"] == "2026-03-04"
    for value in data.values():
        if isinstance(value, list):
            assert all(isinstance(item, str) for item in value)
        else:
            assert isinstance(value, (str, int))


def test_through_run_all_namespace_pi(
    isolated_registry: None, ledger_with_duplicate_invoice: Scenario
) -> None:
    """The detector is registered as pi.duplicate_invoice and runs through run_all."""
    scenario = ledger_with_duplicate_invoice

    results = run_all(scenario.invoices, namespace="pi", context=dict(scenario.context()))

    mine = [r for r in results if r.name == DETECTOR]
    assert len(mine) == 1
    assert len(mine[0].alerts) == 1
    assert mine[0].alerts[0].detector == DETECTOR


# Tier 2: edge cases


def test_empty_n1_row_skipped() -> None:
    """A number made only of symbols has an empty N1 and is never compared."""
    assert _run(_pair("/ /", "/ /", 0)) == []


@pytest.mark.parametrize("column", ["invoice_number", "issue_date", "total"])
def test_missing_number_date_or_total_skipped(column: str) -> None:
    """A row lacking its number, issue date or total is skipped; its twin stays alone."""
    rows = _pair("F-2026-0042", "F-2026-0042", 0)
    rows[1][column] = None

    assert _run(rows) == []


def test_non_string_number_skipped() -> None:
    """A number that is not text (an int cell) makes the row unusable."""
    rows = _pair("12345", "12345", 0)
    rows[1]["invoice_number"] = 12345

    assert _run(rows) == []


def test_identical_source_ref_uses_one_row() -> None:
    """Two rows with the same source_ref count as one invoice, so nothing is a duplicate."""
    frame = make_invoices(_pair("F-2026-0042", "F-2026-0042", 0))
    frame.loc[1, "source_ref"] = "inv.csv:0"

    assert detect_duplicate_invoices(frame, ctx()) == []


def test_multi_rate_group_no_alert_second_line_of_defence() -> None:
    """REQ-PI-16: one number with two VAT rates is a multi-rate invoice, never a duplicate."""
    rows = _pair("F-2026-0042", "F-2026-0042", 0)
    rows[0]["vat_rate"] = Decimal("21")
    rows[1]["vat_rate"] = Decimal("10")

    assert _run(rows) == []


def test_same_number_different_suppliers_no_alert() -> None:
    """The same number from two suppliers is two different invoices."""
    rows = _pair("F-2026-0042", "F-2026-0042", 0)
    rows[1]["supplier"] = 2

    assert _run(rows) == []


def test_rule_c_6_days_alerts_7_does_not() -> None:
    """Rule C is open for fewer than DUPLICATE_WINDOW_DAYS days."""
    assert len(_run(_pair("FAC-0101", "FAC-0102", DUPLICATE_WINDOW_DAYS - 1))) == 1
    assert _run(_pair("FAC-0101", "FAC-0102", DUPLICATE_WINDOW_DAYS)) == []


def test_rule_a_179_days_alerts_180_does_not() -> None:
    """Rule A is open for fewer than SAME_NUMBER_WINDOW_DAYS days."""
    assert len(_run(_pair("F-1", "F-1", SAME_NUMBER_WINDOW_DAYS - 1))) == 1
    assert _run(_pair("F-1", "F-1", SAME_NUMBER_WINDOW_DAYS)) == []


def test_totals_differing_by_one_cent_not_equal() -> None:
    """The total tolerance is 0.00: totals one cent apart never relate two invoices."""
    rows = _pair("FAC-0101", "FAC-0102", 1)
    rows[0]["total"] = Decimal("90.75")
    rows[1]["total"] = Decimal("90.76")
    assert _run(rows) == []

    rows[1]["total"] = Decimal("90.75")
    assert len(_run(rows)) == 1


def test_different_currency_never_paired() -> None:
    """DN-1: invoices in different currencies are never related, whatever the number."""
    rows = _pair("F-2026-0042", "F-2026-0042", 0)
    rows[1]["currency"] = "USD"

    assert _run(rows) == []


def test_group_of_three_with_mixed_rules_gives_one_alert_of_top_rule() -> None:
    """REQ-PI-19: rules A and B in one component give one alert, with the variant of rule A."""
    rows = [
        {"invoice_number": "F-2026-0042", "issue_date": date(2026, 3, 1)},
        {"invoice_number": "F-2026-0042", "issue_date": date(2026, 3, 2)},
        {"invoice_number": "F2026-042", "issue_date": date(2026, 3, 3)},
    ]

    alerts = _run(rows)

    assert len(alerts) == 1
    assert alerts[0].severity == "critical"
    assert alerts[0].data["variant"] == "same_number"
    assert alerts[0].data["invoice_count"] == 3
    assert alerts[0].source_refs == ["inv.csv:0", "inv.csv:1", "inv.csv:2"]


def test_consecutive_numbers_with_equal_totals_fire_rule_c() -> None:
    """OD-PI-06 (documented): consecutive numbers with equal totals close together fire rule C."""
    alerts = _run(_pair("ALQ-2026-01", "ALQ-2026-02", 3))

    assert len(alerts) == 1
    assert alerts[0].data["variant"] == "same_total_close_dates"


def test_window_constants_ordered() -> None:
    """Equal-N1 pairs are a rule-A-only matter: the C window is not longer than the A one."""
    assert DUPLICATE_WINDOW_DAYS <= SAME_NUMBER_WINDOW_DAYS


def test_constants_values() -> None:
    """The documented thresholds."""
    assert DUPLICATE_WINDOW_DAYS == 7
    assert SAME_NUMBER_WINDOW_DAYS == 180
    assert DUPLICATE_TOTAL_TOLERANCE == Decimal("0.00")


def test_empty_ledger_and_empty_dataframe_return_empty_list(empty_ledger: pd.DataFrame) -> None:
    """An empty frame, with or without columns, gives an empty list."""
    assert detect_duplicate_invoices(empty_ledger, ctx()) == []
    assert detect_duplicate_invoices(pd.DataFrame(), MappingProxyType({})) == []


def test_single_row_returns_list(single_row_ledger: pd.DataFrame) -> None:
    """One invoice cannot be a duplicate of anything."""
    result = detect_duplicate_invoices(single_row_ledger, ctx())

    assert isinstance(result, list)
    assert result == []


def test_empty_context_mapping_proxy_does_not_raise() -> None:
    """The context is ignored: an empty read-only mapping works like a full one."""
    frame = make_invoices(_pair("F-2026-0042", "F-2026-0042", 0))

    alerts = detect_duplicate_invoices(frame, MappingProxyType({}))

    assert len(alerts) == 1


def test_base_ledger_gives_two_alerts() -> None:
    """The base ledger holds one A+B alert and one C alert; the multi-rate invoice is dropped."""
    alerts = detect_duplicate_invoices(BASE_LEDGER, ctx())

    assert [a.data["variant"] for a in alerts] == ["same_number", "same_total_close_dates"]
    assert [a.source_refs for a in alerts] == [
        ["inv.csv:0", "inv.csv:1", "inv.csv:2"],
        ["inv.csv:3", "inv.csv:4"],
    ]


# Tier 3: property-based tests


@settings(max_examples=200, deadline=None)
@given(numbers=consecutive_numbers(min_size=2, max_size=6))
def test_consecutive_numbers_with_different_totals_never_duplicate(numbers: list[str]) -> None:
    """Consecutive numbers of one supplier with pairwise different totals never alert."""
    rows = [
        {"invoice_number": number, "issue_date": DAY_ONE, "base_amount": Decimal(100 + index)}
        for index, number in enumerate(numbers)
    ]

    assert _run(rows) == []


@settings(max_examples=200, deadline=None)
@given(order=st.permutations(list(range(len(BASE_ROWS)))))
def test_row_order_never_changes_any_detector(order: list[int]) -> None:
    """Shuffling the rows of the ledger never changes the alerts (REQ-PI-10)."""
    expected = detect_duplicate_invoices(BASE_LEDGER, ctx())
    shuffled = BASE_LEDGER.iloc[list(order)].reset_index(drop=True)

    assert detect_duplicate_invoices(shuffled, ctx()) == expected


@settings(max_examples=200, deadline=None)
@given(frame=with_dirty_cells(BASE_LEDGER))
def test_source_refs_subset_of_loaded_inputs(frame: pd.DataFrame) -> None:
    """No invention: every cited source_ref belongs to a loaded input."""
    context = ctx()

    alerts = detect_duplicate_invoices(frame, context)

    loaded = loaded_source_refs(frame, context)
    for alert in alerts:
        assert alert.source_refs
        assert set(alert.source_refs) <= loaded


@settings(max_examples=200, deadline=None)
@given(frame=with_dirty_cells(BASE_LEDGER))
def test_detector_idempotent(frame: pd.DataFrame) -> None:
    """Running the detector twice on the same frame gives the same alerts."""
    assert detect_duplicate_invoices(frame, ctx()) == detect_duplicate_invoices(frame, ctx())


@settings(max_examples=200, deadline=None)
@given(frame=with_dirty_cells(BASE_LEDGER))
def test_dirty_cells_never_raise(frame: pd.DataFrame) -> None:
    """Whatever cell kinds a messy file produces, the result is a list of alerts."""
    alerts = detect_duplicate_invoices(frame, ctx())

    assert isinstance(alerts, list)
    assert all(isinstance(alert, Alert) for alert in alerts)


@settings(max_examples=200, deadline=None)
@given(columns=st.lists(st.text(min_size=1, max_size=10), unique=True, max_size=6))
def test_empty_input_returns_empty(columns: list[str]) -> None:
    """Any frame without rows gives an empty list."""
    assert detect_duplicate_invoices(pd.DataFrame(columns=columns), ctx()) == []
