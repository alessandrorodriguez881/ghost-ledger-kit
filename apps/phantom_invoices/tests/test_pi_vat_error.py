"""Tests for the pi.vat_error detector (Task P12)."""

import ast
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pandas as pd
import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from apps.phantom_invoices.detectors import vat_error as vat_module
from apps.phantom_invoices.detectors.vat_error import (
    ALLOWED_VAT_RATES,
    TOTAL_TOLERANCE,
    VAT_TOLERANCE,
    detect_vat_errors,
)
from apps.phantom_invoices.tests.pi_builders import SUPPLIER_NAMES, Scenario, ctx, make_invoices
from apps.phantom_invoices.tests.pi_strategies import with_dirty_cells
from ledger_kit.detectors import loaded_source_refs, run_all
from ledger_kit.models import Alert
from ledger_kit.utils.money import percent_of

DETECTOR = "pi.vat_error"
NAME_1 = SUPPLIER_NAMES[1]
D = Decimal

VAT_KEYS = {
    "variant",
    "supplier_name",
    "invoice_number",
    "base_amount",
    "vat_rate",
    "expected_vat_amount",
    "vat_amount",
}
TOTAL_KEYS = {
    "variant",
    "supplier_name",
    "invoice_number",
    "base_amount",
    "vat_amount",
    "surcharge_amount",
    "withholding_amount",
    "expected_total",
    "total",
}
RATE_KEYS = {"variant", "supplier_name", "invoice_number", "vat_rate", "allowed_vat_rates"}


def _run(rows: list[dict[str, Any]]) -> list[Alert]:
    """Run the detector on invoices built from `rows` with an empty context."""
    return detect_vat_errors(make_invoices(rows), ctx())


def _variants(alerts: list[Alert]) -> list[str]:
    """Return the variant of every alert, in output order."""
    return [alert.data["variant"] for alert in alerts]


# Base ledger of the order properties: 7 invoices, 5 alerts.
BASE_ROWS: list[dict[str, Any]] = [
    {},  # clean
    {"vat_amount": D("12.10")},  # VAT amount mismatch (P7)
    {"total": D("130.00")},  # total mismatch
    {"vat_rate": D("20")},  # rate not allowed
    {"vat_rate": D("5"), "vat_amount": D("9.99")},  # rate not allowed and VAT amount mismatch
    {"base_amount": D("1000.00"), "withholding_amount": D("150.00")},  # clean (P8)
    {"vat_amount": None},  # VAT amount missing: only the rate check runs
]
BASE_LEDGER = make_invoices(BASE_ROWS)
BASE_ALERT_COUNT = 5


# Tier 1: normal cases


def test_vat_error_fires_on_typical_input(ledger_with_vat_error: Scenario) -> None:
    """The P7 fixture raises exactly one warning citing the invoice row."""
    scenario = ledger_with_vat_error

    alerts = detect_vat_errors(scenario.invoices, scenario.context())

    assert len(alerts) == 1
    assert alerts[0].detector == DETECTOR
    assert alerts[0].severity == "warning"
    assert alerts[0].source_refs == ["inv.csv:0"]
    assert alerts[0].data["variant"] == "vat_amount_mismatch"


def test_vat_error_silent_on_clean_ledger(clean_ledger_10: pd.DataFrame) -> None:
    """Ten clean invoices with correct VAT and totals raise nothing."""
    assert detect_vat_errors(clean_ledger_10, ctx()) == []


def test_pi_acceptance_p06_correct_vat() -> None:
    """P6: base 100.00, rate 21, VAT 21.00, total 121.00 is clean."""
    frame = make_invoices([{}])
    row = frame.iloc[0]
    assert (row["vat_amount"], row["total"]) == (D("21.00"), D("121.00"))

    assert detect_vat_errors(frame, ctx()) == []


def test_pi_acceptance_p07_wrong_vat_consistent_total_one_alert(
    ledger_with_vat_error: Scenario,
) -> None:
    """P7: wrong VAT with a total consistent with it gives exactly one alert."""
    scenario = ledger_with_vat_error
    assert scenario.invoices.iloc[0]["total"] == D("112.10")

    alerts = detect_vat_errors(scenario.invoices, scenario.context())

    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.title == "VAT amount mismatch: F-2026-0001"
    assert alert.data["variant"] == "vat_amount_mismatch"
    assert alert.data["expected_vat_amount"] == "21.00"
    assert alert.data["vat_amount"] == "12.10"


def test_pi_acceptance_p08_withholding() -> None:
    """P8: base 1000.00, VAT 210.00, withholding 150.00, total 1060.00 is clean."""
    frame = make_invoices([{"base_amount": D("1000.00"), "withholding_amount": D("150.00")}])
    assert frame.iloc[0]["total"] == D("1060.00")

    assert detect_vat_errors(frame, ctx()) == []


def test_pi_acceptance_p11_surcharge() -> None:
    """P11: base 100.00, VAT 21.00, surcharge 5.20, total 126.20 is clean."""
    frame = make_invoices([{"surcharge_amount": D("5.20")}])
    assert frame.iloc[0]["total"] == D("126.20")

    assert detect_vat_errors(frame, ctx()) == []


def test_total_mismatch_alert_contract() -> None:
    """A wrong stated total is one total_mismatch alert with the keys of REQ-PI-32."""
    alerts = _run([{"total": D("130.00")}])

    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.detector == DETECTOR
    assert alert.severity == "warning"
    assert alert.title == "Invoice total mismatch: F-2026-0001"
    assert alert.source_refs == ["inv.csv:0"]
    assert set(alert.data) == TOTAL_KEYS
    assert alert.data["supplier_name"] == NAME_1
    assert alert.data["base_amount"] == "100.00"
    assert alert.data["vat_amount"] == "21.00"
    assert alert.data["surcharge_amount"] == "0.00"
    assert alert.data["withholding_amount"] == "0.00"
    assert alert.data["expected_total"] == "121.00"
    assert alert.data["total"] == "130.00"


def test_vat_amount_alert_contract() -> None:
    """A wrong VAT amount carries the keys of REQ-PI-30, money as two-decimal strings."""
    alerts = _run([{"vat_amount": D("12.10")}])

    assert set(alerts[0].data) == VAT_KEYS
    assert alerts[0].data["base_amount"] == "100.00"
    assert alerts[0].data["vat_rate"] == "21"


def test_vat_rate_not_allowed_contract() -> None:
    """A rate outside the allowed set is one vat_rate_not_allowed alert."""
    alerts = _run([{"vat_rate": D("20")}])

    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.title == "Unexpected VAT rate: F-2026-0001"
    assert set(alert.data) == RATE_KEYS
    assert alert.data["variant"] == "vat_rate_not_allowed"
    assert alert.data["vat_rate"] == "20"
    assert alert.data["allowed_vat_rates"] == "21, 10, 4, 0"


def test_through_run_all_namespace_pi(
    isolated_registry: None, ledger_with_vat_error: Scenario
) -> None:
    """The detector is registered as pi.vat_error and runs through run_all."""
    scenario = ledger_with_vat_error

    results = run_all(scenario.invoices, namespace="pi", context=dict(scenario.context()))

    mine = [r for r in results if r.name == DETECTOR]
    assert len(mine) == 1
    assert len(mine[0].alerts) == 1
    assert mine[0].alerts[0].detector == DETECTOR


# Tier 2: edge cases


@pytest.mark.parametrize(
    ("stated", "fires"),
    [("21.01", False), ("21.02", True), ("20.99", False), ("20.98", True)],
)
def test_vat_amount_boundary_0_01_clean_0_02_alerts(stated: str, fires: bool) -> None:
    """The VAT amount may differ by 0.01 (inclusive); 0.02 alerts, and only that check."""
    alerts = _run([{"vat_amount": D(stated)}])

    assert _variants(alerts) == (["vat_amount_mismatch"] if fires else [])


@pytest.mark.parametrize(
    ("stated", "fires"),
    [("121.01", False), ("121.02", True), ("120.99", False), ("120.98", True)],
)
def test_total_boundary_0_01_clean_0_02_alerts(stated: str, fires: bool) -> None:
    """The total may differ by 0.01 (inclusive); 0.02 alerts, and only that check."""
    alerts = _run([{"total": D(stated)}])

    assert _variants(alerts) == (["total_mismatch"] if fires else [])


def test_rate_21_00_allowed_20_and_5_alert() -> None:
    """21.00 is the allowed rate 21; 20 and 5 are not."""
    assert _run([{"vat_rate": D("21.00")}]) == []
    assert _variants(_run([{"vat_rate": D("20")}])) == ["vat_rate_not_allowed"]
    assert _variants(_run([{"vat_rate": D("5")}])) == ["vat_rate_not_allowed"]


def test_rate_zero_with_zero_vat_clean() -> None:
    """The exempt rate 0 with VAT 0.00 and total equal to the base is clean."""
    assert _run([{"vat_rate": D("0")}]) == []


def test_missing_base_rate_vat_or_total_skips_only_that_check() -> None:
    """A missing field skips the checks that need it and no other."""
    no_base = {
        "base_amount": None,
        "vat_rate": D("20"),
        "vat_amount": D("5.00"),
        "total": D("9.99"),
    }
    no_rate = {"vat_rate": None, "vat_amount": D("21.00"), "total": D("130.00")}
    no_vat = {"vat_amount": None, "total": D("130.00")}
    no_total = {"vat_amount": D("5.00"), "total": None}

    assert _variants(_run([no_base])) == ["vat_rate_not_allowed"]
    assert _variants(_run([no_rate])) == ["total_mismatch"]
    assert _run([no_vat]) == []
    assert _variants(_run([no_total])) == ["vat_amount_mismatch"]


def test_string_and_float_cells_treated_as_missing() -> None:
    """A str or float amount is the wrong type: the checks that need it are skipped."""
    rows = [
        {"vat_amount": "5.00", "total": 130.0},
        {"base_amount": 100.0, "vat_amount": 5.0, "total": D("130.00")},
        {"vat_rate": "20", "vat_amount": D("5.00"), "total": D("105.00")},
    ]

    assert _run(rows) == []


def test_half_up_case_0_50_at_21_percent() -> None:
    """21 % of 0.50 is 0.105, rounded half-up to 0.11: 0.11 and 0.10 are clean, 0.09 alerts."""
    assert percent_of(D("0.50"), D("21")) == D("0.11")
    assert _run([{"base_amount": D("0.50"), "vat_amount": D("0.11")}]) == []
    assert _run([{"base_amount": D("0.50"), "vat_amount": D("0.10")}]) == []

    alerts = _run([{"base_amount": D("0.50"), "vat_amount": D("0.09")}])

    assert _variants(alerts) == ["vat_amount_mismatch"]
    assert alerts[0].data["expected_vat_amount"] == "0.11"
    assert alerts[0].data["vat_amount"] == "0.09"


def test_withholding_larger_than_base_plus_vat_is_total_mismatch_not_error() -> None:
    """A negative expected total is compared like any other value."""
    alerts = _run([{"withholding_amount": D("500.00"), "total": D("121.00")}])

    assert _variants(alerts) == ["total_mismatch"]
    assert alerts[0].data["expected_total"] == "-379.00"


def test_missing_surcharge_and_withholding_default_to_zero() -> None:
    """Missing surcharge and withholding count as 0.00 in the total check."""
    rows = [{"surcharge_amount": None, "withholding_amount": None, "total": D("121.00")}]

    assert _run(rows) == []


def test_empty_ledger_and_empty_dataframe_return_empty_list(empty_ledger: pd.DataFrame) -> None:
    """An empty frame, with or without columns, gives an empty list."""
    assert detect_vat_errors(empty_ledger, ctx()) == []
    assert detect_vat_errors(pd.DataFrame(), MappingProxyType({})) == []


def test_single_row_returns_list(single_row_ledger: pd.DataFrame) -> None:
    """One clean invoice gives an empty list."""
    result = detect_vat_errors(single_row_ledger, ctx())

    assert isinstance(result, list)
    assert result == []


def test_constants_values() -> None:
    """The documented thresholds and the allowed VAT rates."""
    assert VAT_TOLERANCE == D("0.01")
    assert TOTAL_TOLERANCE == D("0.01")
    assert ALLOWED_VAT_RATES == (D("21"), D("10"), D("4"), D("0"))


def test_duplicate_source_ref_uses_first_row() -> None:
    """Two rows with one source_ref count as one invoice, whatever the frame order."""
    frame = make_invoices([{}, {"vat_amount": D("12.10")}])
    frame.loc[1, "source_ref"] = "inv.csv:0"

    alerts = detect_vat_errors(frame, ctx())
    reversed_alerts = detect_vat_errors(frame.iloc[::-1].reset_index(drop=True), ctx())

    assert len(alerts) <= 1
    assert all(alert.source_refs == ["inv.csv:0"] for alert in alerts)
    assert alerts == reversed_alerts


def test_module_applies_no_arithmetic_operator() -> None:
    """REQ-MON-03: vat_error.py has no BinOp and no augmented assignment (money via helpers)."""
    tree = ast.parse(Path(vat_module.__file__).read_text(encoding="utf-8"))

    operators = [n for n in ast.walk(tree) if isinstance(n, (ast.BinOp, ast.AugAssign))]

    assert operators == []


def test_base_ledger_gives_the_expected_alerts() -> None:
    """The base ledger of the order properties holds exactly BASE_ALERT_COUNT alerts."""
    assert len(detect_vat_errors(BASE_LEDGER, ctx())) == BASE_ALERT_COUNT


# Tier 3: property-based tests

_AMOUNTS = st.decimals(min_value=D(0), max_value=D(1_000_000), places=2)
_RATES = st.sampled_from(ALLOWED_VAT_RATES)


@settings(max_examples=200, deadline=None)
@given(base=_AMOUNTS, rate=_RATES, surcharge=_AMOUNTS, withholding=_AMOUNTS)
def test_correct_invoice_never_fires_vat_check(
    base: Decimal, rate: Decimal, surcharge: Decimal, withholding: Decimal
) -> None:
    """An invoice whose VAT and total come from the money helpers never alerts."""
    rows = [
        {
            "base_amount": base,
            "vat_rate": rate,
            "surcharge_amount": surcharge,
            "withholding_amount": withholding,
        }
    ]

    assert _run(rows) == []


@settings(max_examples=200, deadline=None)
@given(
    base=_AMOUNTS,
    rate=_RATES,
    shift=st.one_of(st.integers(2, 100_000), st.integers(-100_000, -2)),
)
def test_vat_off_by_two_cents_or_more_always_fires(
    base: Decimal, rate: Decimal, shift: int
) -> None:
    """A stated VAT two cents or more away from percent_of(base, rate) always alerts."""
    stated = percent_of(base, rate) + D(shift).scaleb(-2)
    assume(stated >= 0)

    alerts = _run([{"base_amount": base, "vat_rate": rate, "vat_amount": stated}])

    assert "vat_amount_mismatch" in _variants(alerts)


@settings(max_examples=200, deadline=None)
@given(order=st.permutations(list(range(len(BASE_ROWS)))))
def test_row_order_never_changes_any_detector(order: list[int]) -> None:
    """Shuffling the rows never changes the alerts (REQ-PI-10)."""
    expected = detect_vat_errors(BASE_LEDGER, ctx())
    shuffled = BASE_LEDGER.iloc[list(order)].reset_index(drop=True)

    assert detect_vat_errors(shuffled, ctx()) == expected


@settings(max_examples=200, deadline=None)
@given(frame=with_dirty_cells(BASE_LEDGER))
def test_source_refs_subset_of_loaded_inputs(frame: pd.DataFrame) -> None:
    """No invention: every cited source_ref belongs to a loaded input."""
    context = ctx()

    alerts = detect_vat_errors(frame, context)

    loaded = loaded_source_refs(frame, context)
    for alert in alerts:
        assert alert.source_refs
        assert set(alert.source_refs) <= loaded


@settings(max_examples=200, deadline=None)
@given(frame=with_dirty_cells(BASE_LEDGER))
def test_detector_idempotent(frame: pd.DataFrame) -> None:
    """Running the detector twice on the same frame gives the same alerts."""
    assert detect_vat_errors(frame, ctx()) == detect_vat_errors(frame, ctx())


@settings(max_examples=200, deadline=None)
@given(frame=with_dirty_cells(BASE_LEDGER))
def test_dirty_cells_never_raise(frame: pd.DataFrame) -> None:
    """Whatever cell kinds a messy file produces, the result is a list of alerts."""
    alerts = detect_vat_errors(frame, ctx())

    assert isinstance(alerts, list)
    assert all(isinstance(alert, Alert) for alert in alerts)


@settings(max_examples=200, deadline=None)
@given(columns=st.lists(st.text(min_size=1, max_size=10), unique=True, max_size=6))
def test_empty_input_returns_empty(columns: list[str]) -> None:
    """Any frame without rows gives an empty list."""
    assert detect_vat_errors(pd.DataFrame(columns=columns), ctx()) == []
