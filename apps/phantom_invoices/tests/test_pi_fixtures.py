"""Tests for the shared builders, strategies and fixtures of the app (Task P9)."""

from datetime import date, timedelta
from decimal import Decimal
from types import MappingProxyType

import pandas as pd
import pytest
from hypothesis import given, settings

from apps.phantom_invoices.detectors import run_pi_detectors
from apps.phantom_invoices.detectors.utils import iban_key, is_missing, n2_key, resolve_as_of
from apps.phantom_invoices.tests.pi_builders import (
    Scenario,
    ctx,
    make_invoices,
    make_payments,
    make_suppliers,
)
from apps.phantom_invoices.tests.pi_checkers import (
    mod97_remainder,
    spanish_national_dc_ok,
    tax_id_control_ok,
)
from apps.phantom_invoices.tests.pi_strategies import consecutive_numbers, reconciliation_inputs
from ledger_kit.ingestion.normaliser import CANONICAL_COLUMNS, INVOICE_COLUMNS, SUPPLIER_COLUMNS
from ledger_kit.utils.money import net_total, percent_of

PLAIN_FIXTURES = (
    "empty_ledger",
    "single_row_ledger",
    "clean_ledger_10",
    "suppliers_master",
    "payments_for_clean",
)
SCENARIOS = (
    "ledger_with_duplicate_invoice",
    "ledger_with_near_duplicate",
    "ledger_with_iban_change",
    "ledger_with_vat_error",
    "ledger_with_unpaid_invoice",
    "ledger_with_double_payment",
)


def _all_frames(request: pytest.FixtureRequest) -> list[pd.DataFrame]:
    """Return every frame produced by the plain and the scenario fixtures."""
    frames = [request.getfixturevalue(name) for name in PLAIN_FIXTURES]
    for name in SCENARIOS:
        frames += list(request.getfixturevalue(name)[:3])
    return frames


# Tier 1: normal cases


def test_fixture_columns_match_canonical_columns(
    request: pytest.FixtureRequest,
    empty_ledger: pd.DataFrame,
    single_row_ledger: pd.DataFrame,
    clean_ledger_10: pd.DataFrame,
    suppliers_master: pd.DataFrame,
    payments_for_clean: pd.DataFrame,
) -> None:
    """Invoice fixtures have INVOICE_COLUMNS, supplier fixtures SUPPLIER_COLUMNS, and so on."""
    for frame in (empty_ledger, single_row_ledger, clean_ledger_10):
        assert tuple(frame.columns) == INVOICE_COLUMNS
    assert tuple(suppliers_master.columns) == SUPPLIER_COLUMNS
    assert tuple(payments_for_clean.columns) == CANONICAL_COLUMNS
    for name in SCENARIOS:
        scenario = request.getfixturevalue(name)
        assert isinstance(scenario, Scenario)
        assert tuple(scenario.invoices.columns) == INVOICE_COLUMNS
        assert tuple(scenario.suppliers.columns) == SUPPLIER_COLUMNS
        assert tuple(scenario.payments.columns) == CANONICAL_COLUMNS


def test_make_invoices_derives_vat_and_total_with_money_helpers() -> None:
    """Defaults are EUR and rate 21; VAT and total come from percent_of and net_total."""
    frame = make_invoices(
        [
            {},
            {"base_amount": Decimal("0.50")},
            {"surcharge_amount": Decimal("5.20"), "withholding_amount": Decimal("15.00")},
            {"vat_amount": Decimal("12.10")},
        ]
    )

    assert list(frame["source_ref"]) == [f"inv.csv:{i}" for i in range(4)]
    assert list(frame["source_row"]) == [0, 1, 2, 3]
    rows = frame.to_dict("records")
    for index, row in enumerate(rows):
        assert row["currency"] == "EUR"
        assert row["vat_rate"] == Decimal("21")
        assert row["source_file"] == "inv.csv"
        if index != 3:
            assert row["vat_amount"] == percent_of(row["base_amount"], row["vat_rate"])
        additions = [row["base_amount"], row["vat_amount"], row["surcharge_amount"]]
        assert row["total"] == net_total(additions, [row["withholding_amount"]])
    assert rows[0]["total"] == Decimal("121.00")
    assert rows[1]["vat_amount"] == Decimal("0.11")  # half-up
    assert rows[2]["total"] == Decimal("111.20")
    assert rows[3]["vat_amount"] == Decimal("12.10")
    assert rows[3]["total"] == Decimal("112.10")
    assert rows[0]["issue_date"] == date(2026, 3, 1)
    assert rows[0]["due_date"] == date(2026, 3, 31)


def test_explicit_values_win_and_dirty_cells_are_kept() -> None:
    """A given value is never replaced; a derived value of a non-Decimal input is missing."""
    frame = make_invoices(
        [{"total": Decimal("1.00"), "invoice_number": "X", "supplier": 2}, {"vat_rate": "21"}]
    )

    first, second = frame.to_dict("records")
    assert first["total"] == Decimal("1.00")
    assert first["invoice_number"] == "X"
    assert first["supplier_name"] == "Inmuebles Valdemar, S.L."
    assert second["vat_rate"] == "21"
    assert is_missing(second["vat_amount"])
    assert is_missing(second["total"])


def test_make_suppliers_and_payments_defaults() -> None:
    """Suppliers default to fictional suppliers 1, 2, 3; payments are debits of 121.00 EUR."""
    suppliers = make_suppliers([{}, {}, {}])
    payments = make_payments([{}, {"flow": "credit"}])

    assert list(suppliers["source_ref"]) == ["sup.csv:0", "sup.csv:1", "sup.csv:2"]
    assert len(set(suppliers["tax_id"])) == 3
    assert suppliers["supplier_name"].iloc[2] == "Ana García (Asesoría Fiscal)"
    assert all(" " in iban and iban == iban.upper() for iban in suppliers["iban"])
    assert list(payments["source_ref"]) == ["pay.csv:0", "pay.csv:1"]
    assert len(set(payments["id"])) == 2
    assert list(payments["flow"]) == ["debit", "credit"]
    assert payments["amount"].iloc[0] == Decimal("121.00")
    assert payments["currency"].iloc[0] == "EUR"


def test_fixture_identifiers_follow_finance_rule_5(request: pytest.FixtureRequest) -> None:
    """IBANs: valid mod-97, wrong national digits. Tax ids: wrong control. E-mails: example.com."""
    ibans: set[str] = set()
    tax_ids: set[str] = set()
    emails: set[str] = set()
    for frame in _all_frames(request):
        for column in frame.columns:
            for cell in frame[column]:
                if not isinstance(cell, str):
                    continue
                if column == "iban":
                    ibans.add(iban_key(cell))
                if column in ("supplier_tax_id", "tax_id"):
                    tax_ids.add(cell)
                if "@" in cell:
                    emails.add(cell)

    assert len(ibans) >= 4
    for iban in ibans:
        assert len(iban) == 24, iban
        assert mod97_remainder(iban) == 1, iban
        assert not spanish_national_dc_ok(iban), iban
    assert len(tax_ids) >= 3
    for tax_id in tax_ids:
        assert not tax_id_control_ok(tax_id), tax_id
    assert all(email.endswith("@example.com") for email in emails)


def test_clean_fixtures_are_consistent(
    clean_ledger_10: pd.DataFrame,
    suppliers_master: pd.DataFrame,
    payments_for_clean: pd.DataFrame,
) -> None:
    """Ten distinct invoices, ten matching payments and a three-supplier master."""
    assert len(clean_ledger_10) == 10
    assert len(payments_for_clean) == 10
    assert len(suppliers_master) == 3
    assert len(set(clean_ledger_10["total"])) == 10
    assert sorted(payments_for_clean["amount"]) == sorted(clean_ledger_10["total"])
    assert set(payments_for_clean["flow"]) == {"debit"}
    master = {row["tax_id"]: iban_key(row["iban"]) for row in suppliers_master.to_dict("records")}
    for row in clean_ledger_10.to_dict("records"):
        assert iban_key(row["iban"]) == master[row["supplier_tax_id"]]


def test_clean_ledger_10_raises_no_alert_from_any_detector(
    clean_ledger_10: pd.DataFrame,
    suppliers_master: pd.DataFrame,
    payments_for_clean: pd.DataFrame,
) -> None:
    """No pi detector fires on the clean fixtures."""
    results = run_pi_detectors(clean_ledger_10, suppliers_master, payments_for_clean)

    assert len(results) == 4
    assert [result.alerts for result in results] == [[], [], [], []]


# Scenario fixtures


def test_scenario_p1_same_invoice_twice(ledger_with_duplicate_invoice: Scenario) -> None:
    """P1: two identical invoices, no IBAN, no payments, no master."""
    rows = ledger_with_duplicate_invoice.invoices.to_dict("records")

    assert len(rows) == 2
    assert rows[0]["invoice_number"] == rows[1]["invoice_number"] == "F-2026-0042"
    assert rows[0]["supplier_tax_id"] == rows[1]["supplier_tax_id"]
    assert rows[0]["vat_rate"] == rows[1]["vat_rate"]
    assert is_missing(rows[0]["iban"])
    assert ledger_with_duplicate_invoice.payments.empty
    assert ledger_with_duplicate_invoice.suppliers.empty


def test_scenario_p3_near_identical_numbers(ledger_with_near_duplicate: Scenario) -> None:
    """P3: F-2026-0042 and F2026-042, same supplier and total, three days apart."""
    first, second = ledger_with_near_duplicate.invoices.to_dict("records")

    assert (first["invoice_number"], second["invoice_number"]) == ("F-2026-0042", "F2026-042")
    assert first["supplier_tax_id"] == second["supplier_tax_id"]
    assert first["total"] == second["total"]
    assert (second["issue_date"] - first["issue_date"]).days == 3
    assert n2_key(first["invoice_number"]) == n2_key(second["invoice_number"])


def test_scenario_p5_new_valid_iban(ledger_with_iban_change: Scenario) -> None:
    """P5: the invoice IBAN is valid, differs from the master of the same supplier."""
    invoice = ledger_with_iban_change.invoices.to_dict("records")[0]
    master = ledger_with_iban_change.suppliers.to_dict("records")[0]

    assert invoice["supplier_tax_id"] == master["tax_id"]
    assert iban_key(invoice["iban"]) != iban_key(master["iban"])
    assert mod97_remainder(iban_key(invoice["iban"])) == 1
    assert master["source_ref"] == "sup.csv:0"


def test_scenario_p7_wrong_vat_consistent_total(ledger_with_vat_error: Scenario) -> None:
    """P7: base 100.00, rate 21, VAT 12.10, total 112.10."""
    row = ledger_with_vat_error.invoices.to_dict("records")[0]

    assert row["base_amount"] == Decimal("100.00")
    assert row["vat_rate"] == Decimal("21")
    assert row["vat_amount"] == Decimal("12.10")
    assert row["total"] == Decimal("112.10")


def test_scenario_unpaid_invoice_is_overdue_at_derived_as_of(
    ledger_with_unpaid_invoice: Scenario,
) -> None:
    """The later payment fixes as_of beyond due date + 15 days of the unpaid invoice."""
    scenario = ledger_with_unpaid_invoice
    invoice = scenario.invoices.to_dict("records")[0]

    as_of = resolve_as_of(scenario.invoices, scenario.context())

    assert as_of == date(2026, 4, 15)
    assert as_of > invoice["due_date"] + timedelta(days=15)
    assert scenario.as_of is None
    assert len(scenario.payments) == 1


def test_scenario_p9_invoice_paid_twice(ledger_with_double_payment: Scenario) -> None:
    """P9: two debits of the invoice total inside the payment window."""
    scenario = ledger_with_double_payment
    invoice = scenario.invoices.to_dict("records")[0]
    first, second = scenario.payments.to_dict("records")

    assert first["amount"] == second["amount"] == invoice["total"]
    assert first["flow"] == second["flow"] == "debit"
    assert invoice["issue_date"] <= first["date"] < second["date"] <= invoice["due_date"]
    assert first["counterparty"] == second["counterparty"] == invoice["supplier_name"]


# Tier 2: edge cases


def test_single_row_and_empty_ledger_shapes(
    empty_ledger: pd.DataFrame, single_row_ledger: pd.DataFrame
) -> None:
    """The empty fixture has zero rows and all columns; the single-row fixture one clean row."""
    assert len(empty_ledger) == 0
    assert tuple(empty_ledger.columns) == INVOICE_COLUMNS
    assert len(single_row_ledger) == 1
    row = single_row_ledger.to_dict("records")[0]
    assert row["source_ref"] == "inv.csv:0"
    assert row["total"] == Decimal("121.00")


def test_ctx_returns_mapping_proxy() -> None:
    """ctx gives a read-only mapping with the three documented keys."""
    context = ctx()

    assert isinstance(context, MappingProxyType)
    assert set(context) == {"suppliers", "payments", "as_of"}
    assert context["as_of"] is None
    assert tuple(context["suppliers"].columns) == SUPPLIER_COLUMNS
    assert tuple(context["payments"].columns) == CANONICAL_COLUMNS
    assert context["suppliers"].empty and context["payments"].empty
    with pytest.raises(TypeError):
        context["as_of"] = date(2026, 3, 1)  # type: ignore[index]


def test_ctx_passes_frames_and_as_of_through() -> None:
    """Given frames and a date are exposed unchanged."""
    suppliers = make_suppliers([{}])
    payments = make_payments([{}])

    context = ctx(suppliers, payments, date(2026, 4, 1))

    assert context["suppliers"] is suppliers
    assert context["payments"] is payments
    assert context["as_of"] == date(2026, 4, 1)


def test_scenario_context_matches_its_fields(ledger_with_double_payment: Scenario) -> None:
    """Scenario.context() wraps the scenario's own frames."""
    context = ledger_with_double_payment.context()

    assert isinstance(context, MappingProxyType)
    assert context["suppliers"] is ledger_with_double_payment.suppliers
    assert context["payments"] is ledger_with_double_payment.payments


# Tier 3: property-based tests of the strategies


@settings(max_examples=200, deadline=None)
@given(numbers=consecutive_numbers())
def test_consecutive_numbers_are_distinct_after_both_keys(numbers: list[str]) -> None:
    """Consecutive numbers never collapse under N2, so no pair is a rule-B near-duplicate."""
    assert len(numbers) >= 2
    assert len(set(numbers)) == len(numbers)
    assert len({n2_key(number) for number in numbers}) == len(numbers)


@settings(max_examples=200, deadline=None)
@given(frames=reconciliation_inputs())
def test_reconciliation_inputs_shapes(frames: tuple[pd.DataFrame, ...]) -> None:
    """The drawn frames have canonical columns, unique source_refs and a three-supplier master."""
    invoices, suppliers, payments = frames

    assert tuple(invoices.columns) == INVOICE_COLUMNS
    assert tuple(suppliers.columns) == SUPPLIER_COLUMNS
    assert tuple(payments.columns) == CANONICAL_COLUMNS
    assert len(suppliers) == 3
    assert invoices["source_ref"].is_unique
    assert payments["source_ref"].is_unique
    assert len(invoices) <= 6 and len(payments) <= 6
