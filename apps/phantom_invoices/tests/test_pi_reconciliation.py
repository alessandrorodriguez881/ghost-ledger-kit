"""Tests for `reconcile` and the pi.reconciliation detector (Task P13)."""

from datetime import date, timedelta
from decimal import Decimal
from types import MappingProxyType
from typing import Any

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from apps.phantom_invoices.detectors.reconciliation import (
    MATCH_AMOUNT_TOLERANCE,
    PAYMENT_MATCH_WINDOW_DAYS,
    UNPAID_GRACE_DAYS,
    detect_reconciliation,
)
from apps.phantom_invoices.detectors.utils import (
    Reconciliation,
    attribute_payment,
    build_master,
    invoice_view,
    load_rows,
    payment_view,
    reconcile,
    resolve_as_of,
    tax_key,
)
from apps.phantom_invoices.tests.pi_builders import (
    SUPPLIER_NAMES,
    Scenario,
    ctx,
    format_iban,
    iban_for_supplier,
    make_invoices,
    make_payments,
    make_suppliers,
    master_iban,
    supplier_record,
)
from apps.phantom_invoices.tests.pi_strategies import reconciliation_inputs, with_dirty_cells
from ledger_kit.detectors import loaded_source_refs, run_all
from ledger_kit.models import Alert

DETECTOR = "pi.reconciliation"
D = Decimal
NAME_1 = SUPPLIER_NAMES[1]
TAX_1 = tax_key(supplier_record(1)["tax_id"])
UNKNOWN_COUNTERPARTY = "Comercio Local Ficticio"
NEW_IBAN = format_iban(iban_for_supplier(1, other=True))  # valid, but not in the master
MASTER_1 = make_suppliers([{"supplier": 1}])
ISSUE = date(2026, 3, 1)  # default issue date of the builders
DUE = date(2026, 3, 31)  # default due date: the issue date plus 30 days
OVERDUE_KEYS = {
    "variant",
    "supplier_name",
    "invoice_number",
    "total",
    "due_date",
    "due_date_is_default",
    "as_of",
    "days_past_due",
}
NO_INVOICE_KEYS = {"variant", "supplier_name", "payment_date", "payment_amount", "currency"}


def _rec(
    invoices: list[dict[str, Any]],
    payments: list[dict[str, Any]],
    as_of: date | None = None,
    suppliers: pd.DataFrame = MASTER_1,
) -> Reconciliation:
    """Reconcile invoices and payments built from spec rows."""
    return reconcile(make_invoices(invoices), suppliers, make_payments(payments), as_of)


def _detect(
    invoices: pd.DataFrame,
    suppliers: pd.DataFrame | None = None,
    payments: pd.DataFrame | None = None,
    as_of: date | None = None,
) -> list[Alert]:
    """Run the detector with a context built from the given frames."""
    return detect_reconciliation(invoices, ctx(suppliers, payments, as_of))


# Tier 1: normal cases


def test_reconciliation_fires_on_typical_input(ledger_with_unpaid_invoice: Scenario) -> None:
    """An invoice 65 days past its due date, with no payment, is one overdue alert."""
    scenario = ledger_with_unpaid_invoice

    alerts = detect_reconciliation(scenario.invoices, scenario.context())

    assert len(alerts) == 1
    assert alerts[0].detector == DETECTOR
    assert alerts[0].severity == "warning"
    assert alerts[0].source_refs == ["inv.csv:0"]
    assert alerts[0].data["variant"] == "invoice_overdue"
    assert alerts[0].data["days_past_due"] == (date(2026, 4, 15) - date(2026, 2, 9)).days


def test_reconciliation_silent_on_clean_ledger(
    clean_ledger_10: pd.DataFrame, suppliers_master: pd.DataFrame, payments_for_clean: pd.DataFrame
) -> None:
    """Ten invoices, each settled by one matching payment, raise nothing."""
    assert _detect(clean_ledger_10, suppliers_master, payments_for_clean) == []


def test_pi_acceptance_p09_invoice_paid_twice(ledger_with_double_payment: Scenario) -> None:
    """P9: the first payment matches, the second is a payment without invoice, none is overdue."""
    scenario = ledger_with_double_payment
    as_of = resolve_as_of(scenario.invoices, scenario.context())

    rec = reconcile(scenario.invoices, scenario.suppliers, scenario.payments, as_of)
    alerts = detect_reconciliation(scenario.invoices, scenario.context())

    assert rec.invoice_buckets == {"inv.csv:0": "matched"}
    assert rec.payment_buckets == {"pay.csv:0": "matched", "pay.csv:1": "unmatched"}
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.detector == DETECTOR
    assert alert.severity == "warning"
    assert alert.title == f"Payment without invoice: {NAME_1}"
    assert alert.source_refs == ["pay.csv:1", "sup.csv:0"]
    assert alert.data["variant"] == "payment_without_invoice"
    assert alert.data["payment_date"] == "2026-03-20"
    assert alert.data["payment_amount"] == "121.00"


def test_overdue_alert_contract(ledger_with_unpaid_invoice: Scenario) -> None:
    """The overdue alert carries the keys of REQ-PI-39 with dates as ISO strings."""
    scenario = ledger_with_unpaid_invoice

    alert = detect_reconciliation(scenario.invoices, scenario.context())[0]

    assert alert.title == f"Unpaid invoice: F-2026-0001 ({NAME_1})"
    assert set(alert.data) == OVERDUE_KEYS
    assert alert.data["supplier_name"] == NAME_1
    assert alert.data["invoice_number"] == "F-2026-0001"
    assert alert.data["total"] == "121.00"
    assert alert.data["due_date"] == "2026-02-09"
    assert alert.data["due_date_is_default"] is False
    assert alert.data["as_of"] == "2026-04-15"
    assert alert.data["days_past_due"] == 65


def test_payment_without_invoice_alert_contract(ledger_with_double_payment: Scenario) -> None:
    """The payment alert carries the keys of REQ-PI-39."""
    scenario = ledger_with_double_payment

    alert = detect_reconciliation(scenario.invoices, scenario.context())[0]

    assert set(alert.data) == NO_INVOICE_KEYS
    assert alert.data["supplier_name"] == NAME_1
    assert alert.data["currency"] == "EUR"


def test_open_not_due_is_silent() -> None:
    """An unpaid invoice that is not yet overdue raises nothing."""
    invoices = make_invoices([{}])

    assert _detect(invoices, MASTER_1, as_of=DUE + timedelta(days=UNPAID_GRACE_DAYS)) == []


def test_reconcile_returns_all_four_fields(ledger_with_double_payment: Scenario) -> None:
    """The Reconciliation holds invoice_buckets, payment_buckets, matches and payment_supplier."""
    scenario = ledger_with_double_payment

    rec = reconcile(scenario.invoices, scenario.suppliers, scenario.payments, None)

    assert isinstance(rec, Reconciliation)
    assert rec.invoice_buckets == {"inv.csv:0": "matched"}
    assert rec.payment_buckets == {"pay.csv:0": "matched", "pay.csv:1": "unmatched"}
    assert rec.matches == [("inv.csv:0", "pay.csv:0")]
    assert rec.payment_supplier == {"pay.csv:0": TAX_1, "pay.csv:1": TAX_1}


def test_through_run_all_namespace_pi(
    isolated_registry: None, ledger_with_unpaid_invoice: Scenario
) -> None:
    """The detector is registered as pi.reconciliation and runs through run_all."""
    scenario = ledger_with_unpaid_invoice

    results = run_all(scenario.invoices, namespace="pi", context=dict(scenario.context()))

    mine = [r for r in results if r.name == DETECTOR]
    assert len(mine) == 1
    assert len(mine[0].alerts) == 1
    assert mine[0].alerts[0].detector == DETECTOR


# Tier 2: edge cases


@pytest.mark.parametrize(
    ("day", "matched"),
    [
        (ISSUE - timedelta(days=1), False),
        (ISSUE, True),
        (DUE + timedelta(days=PAYMENT_MATCH_WINDOW_DAYS), True),
        (DUE + timedelta(days=PAYMENT_MATCH_WINDOW_DAYS + 1), False),
    ],
)
def test_payment_on_issue_date_and_on_due_plus_60_matches_one_day_outside_does_not(
    day: date, matched: bool
) -> None:
    """Both ends of the payment window are inclusive; one day outside does not match."""
    rec = _rec([{}], [{"supplier": 1, "date": day}])

    expected = "matched" if matched else "unmatched"
    assert rec.payment_buckets == {"pay.csv:0": expected}
    assert rec.invoice_buckets["inv.csv:0"] == ("matched" if matched else "open_not_due")


def test_due_plus_15_open_due_plus_16_overdue() -> None:
    """An unpaid invoice is overdue strictly after due + UNPAID_GRACE_DAYS."""
    last_open = _rec([{}], [], DUE + timedelta(days=UNPAID_GRACE_DAYS))
    first_overdue = _rec([{}], [], DUE + timedelta(days=UNPAID_GRACE_DAYS + 1))

    assert last_open.invoice_buckets == {"inv.csv:0": "open_not_due"}
    assert first_overdue.invoice_buckets == {"inv.csv:0": "overdue"}


@pytest.mark.parametrize(
    ("amount", "matched"),
    [("121.01", True), ("121.02", False), ("120.99", True), ("120.98", False)],
)
def test_amount_difference_0_01_matches_0_02_does_not(amount: str, matched: bool) -> None:
    """The payment amount may differ from the total by 0.01 (inclusive), not by 0.02."""
    rec = _rec([{}], [{"supplier": 1, "amount": D(amount)}])

    assert rec.invoice_buckets["inv.csv:0"] == ("matched" if matched else "open_not_due")


def test_different_currency_does_not_match() -> None:
    """A payment in another currency never matches, whatever the amount."""
    rec = _rec([{}], [{"supplier": 1, "currency": "USD"}])

    assert rec.matches == []
    assert rec.payment_buckets == {"pay.csv:0": "unmatched"}


def test_two_equal_invoices_two_payments_pair_in_date_ref_order() -> None:
    """Each invoice, in (issue date, ref) order, takes the earliest free payment."""
    rec = _rec(
        [{}, {}],
        [{"supplier": 1, "date": date(2026, 3, 20)}, {"supplier": 1, "date": date(2026, 3, 10)}],
    )

    assert rec.matches == [("inv.csv:0", "pay.csv:1"), ("inv.csv:1", "pay.csv:0")]
    assert set(rec.invoice_buckets.values()) == {"matched"}
    assert set(rec.payment_buckets.values()) == {"matched"}


def test_credits_ignored() -> None:
    """A credit is not a payment of an invoice: no bucket, no match."""
    rec = _rec([{}], [{"supplier": 1, "flow": "credit"}])

    assert rec.payment_buckets == {}
    assert rec.invoice_buckets == {"inv.csv:0": "open_not_due"}


def test_payment_attributed_by_name_and_by_iban() -> None:
    """A payment is attributed by counterparty name, or else by the master IBAN."""
    payments = [
        {"supplier": 1, "date": date(2026, 3, 10)},
        {"counterparty": UNKNOWN_COUNTERPARTY, "date": date(2026, 3, 20), "iban": master_iban(1)},
    ]

    rec = _rec([{}, {}], payments)

    assert rec.payment_supplier == {"pay.csv:0": TAX_1, "pay.csv:1": TAX_1}
    assert rec.payment_buckets == {"pay.csv:0": "matched", "pay.csv:1": "matched"}


def test_unknown_counterparty_and_iban_is_in_no_bucket() -> None:
    """A debit to an unknown counterparty on an unknown account is not a supplier payment."""
    payments = [{"counterparty": UNKNOWN_COUNTERPARTY, "iban": NEW_IBAN}]
    invoices = make_invoices([{}])
    paid = make_payments(payments)

    rec = reconcile(invoices, MASTER_1, paid, None)

    assert rec.payment_buckets == {}
    assert rec.payment_supplier == {}
    assert _detect(invoices, MASTER_1, paid, as_of=DUE) == []


def test_as_of_none_no_overdue_alert() -> None:
    """Without any date there is no as_of, so nothing is overdue."""
    assert _rec([{}], [], None).invoice_buckets == {"inv.csv:0": "open_not_due"}
    undated = make_invoices([{"issue_date": None}])
    assert _detect(undated, MASTER_1) == []


def test_invoice_of_supplier_not_in_master_never_matched() -> None:
    """OD-PI-11: an invoice of a supplier absent from the master is never matched."""
    invoices = [{"supplier": 2}]
    payments = [{"supplier": 2}]

    open_rec = _rec(invoices, payments, None)
    late_rec = _rec(invoices, payments, DUE + timedelta(days=UNPAID_GRACE_DAYS + 1))

    assert open_rec.invoice_buckets == {"inv.csv:0": "open_not_due"}
    assert late_rec.invoice_buckets == {"inv.csv:0": "overdue"}
    assert late_rec.payment_buckets == {}
    assert late_rec.matches == []


def test_defaulted_due_date_flagged() -> None:
    """A defaulted due date is copied into the overdue alert."""
    invoices = make_invoices([{"due_date_is_default": True}])

    alerts = _detect(invoices, MASTER_1, as_of=DUE + timedelta(days=30))

    assert len(alerts) == 1
    assert alerts[0].data["due_date_is_default"] is True


def test_duplicate_source_ref_uses_first_row() -> None:
    """Two rows with one source_ref count as one invoice in the buckets."""
    frame = make_invoices([{}, {"base_amount": D("200.00")}])
    frame.loc[1, "source_ref"] = "inv.csv:0"

    rec = reconcile(frame, MASTER_1, make_payments([]), None)
    reversed_rec = reconcile(frame.iloc[::-1].reset_index(drop=True), MASTER_1, None, None)

    assert list(rec.invoice_buckets) == ["inv.csv:0"]
    assert rec.invoice_buckets == reversed_rec.invoice_buckets


def test_unusable_rows_in_no_bucket_and_never_raise() -> None:
    """Rows lacking a required cell belong to no bucket."""
    invoices = [
        {"due_date": None},
        {"currency": None},
        {"total": None},
        {"supplier_tax_id": None},
        {"issue_date": None},
    ]
    payments = [
        {"supplier": 1, "amount": None},
        {"supplier": 1, "date": None},
        {"supplier": 1, "currency": None},
        {"supplier": 1, "flow": "credit"},
    ]

    rec = _rec(invoices, payments, DUE)

    assert rec.invoice_buckets == {}
    assert rec.payment_buckets == {}
    assert rec.matches == []


def test_partial_payment_overpayment_and_payment_before_issue_not_matched() -> None:
    """OD-PI-17: only a payment of the total, inside the window, matches."""
    payments = [
        {"supplier": 1, "amount": D("60.50")},
        {"supplier": 1, "amount": D("242.00")},
        {"supplier": 1, "date": ISSUE - timedelta(days=1)},
    ]

    rec = _rec([{}], payments)

    assert rec.matches == []
    assert set(rec.payment_buckets.values()) == {"unmatched"}
    assert len(rec.payment_buckets) == 3
    assert rec.invoice_buckets == {"inv.csv:0": "open_not_due"}


def test_empty_ledger_with_unmatched_supplier_payment_alerts(empty_ledger: pd.DataFrame) -> None:
    """REQ-PI-34: with an empty ledger an unmatched supplier payment still alerts."""
    alerts = _detect(empty_ledger, MASTER_1, make_payments([{"supplier": 1}]))

    assert len(alerts) == 1
    assert alerts[0].data["variant"] == "payment_without_invoice"
    assert alerts[0].source_refs == ["pay.csv:0", "sup.csv:0"]


def test_everything_empty_returns_empty_list(empty_ledger: pd.DataFrame) -> None:
    """No invoice, no master and no payment: an empty list, never an error."""
    assert _detect(empty_ledger) == []
    assert detect_reconciliation(pd.DataFrame(), MappingProxyType({})) == []


def test_constants_values() -> None:
    """The documented thresholds."""
    assert PAYMENT_MATCH_WINDOW_DAYS == 60
    assert UNPAID_GRACE_DAYS == 15
    assert MATCH_AMOUNT_TOLERANCE == D("0.01")


# Tier 3: property-based tests


@settings(max_examples=200, deadline=None)
@given(frames=reconciliation_inputs())
def test_every_invoice_and_supplier_payment_in_exactly_one_bucket(
    frames: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame],
) -> None:
    """Usable invoices and supplier payments each get one bucket; matches are one-to-one."""
    invoices, suppliers, payments = frames
    as_of = resolve_as_of(invoices, ctx(suppliers, payments))
    master = build_master(suppliers)

    rec = reconcile(invoices, suppliers, payments, as_of)

    usable = {v.ref for v in map(invoice_view, load_rows(invoices, "issue_date")) if v is not None}
    supplier_refs = set()
    for row in load_rows(payments, "date"):
        view = payment_view(row)
        if view is not None and attribute_payment(row, master) is not None:
            supplier_refs.add(view.ref)
    assert set(rec.invoice_buckets) == usable
    assert set(rec.payment_buckets) == supplier_refs
    assert set(rec.invoice_buckets.values()) <= {"matched", "open_not_due", "overdue"}
    assert set(rec.payment_buckets.values()) <= {"matched", "unmatched"}
    matched_invoices = [inv for inv, _ in rec.matches]
    matched_payments = [pay for _, pay in rec.matches]
    assert len(set(matched_invoices)) == len(matched_invoices)
    assert len(set(matched_payments)) == len(matched_payments)
    assert {r for r, b in rec.invoice_buckets.items() if b == "matched"} == set(matched_invoices)
    assert {r for r, b in rec.payment_buckets.items() if b == "matched"} == set(matched_payments)


def _shuffled(frame: pd.DataFrame, data: st.DataObject) -> pd.DataFrame:
    """Return `frame` with its rows in a drawn order (each row keeps its own source_ref)."""
    order = data.draw(st.permutations(list(range(len(frame)))))
    return frame.iloc[list(order)].reset_index(drop=True)


@settings(max_examples=200, deadline=None)
@given(frames=reconciliation_inputs(), data=st.data())
def test_row_order_never_changes_any_detector(
    frames: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame], data: st.DataObject
) -> None:
    """Shuffling the rows of the three frames changes neither the alerts nor the buckets."""
    invoices, suppliers, payments = frames
    shuffled = (_shuffled(invoices, data), _shuffled(suppliers, data), _shuffled(payments, data))

    assert _detect(shuffled[0], shuffled[1], shuffled[2]) == _detect(*frames)
    as_of = resolve_as_of(invoices, ctx(suppliers, payments))
    assert reconcile(*shuffled, as_of) == reconcile(*frames, as_of)


@settings(max_examples=200, deadline=None)
@given(frames=reconciliation_inputs())
def test_source_refs_subset_of_loaded_inputs(
    frames: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame],
) -> None:
    """No invention: every cited source_ref is in the ledger, the suppliers or the payments."""
    invoices, suppliers, payments = frames
    context = ctx(suppliers, payments)

    alerts = detect_reconciliation(invoices, context)

    loaded = loaded_source_refs(invoices, context)
    for alert in alerts:
        assert alert.source_refs
        assert set(alert.source_refs) <= loaded


@settings(max_examples=200, deadline=None)
@given(frames=reconciliation_inputs())
def test_detector_idempotent(frames: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]) -> None:
    """Running the detector twice on the same inputs gives the same alerts."""
    assert _detect(*frames) == _detect(*frames)


@settings(max_examples=200, deadline=None)
@given(frames=reconciliation_inputs(), data=st.data())
def test_dirty_cells_never_raise(
    frames: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame], data: st.DataObject
) -> None:
    """Whatever cell kinds a messy file produces, the result is a list of alerts."""
    dirty = tuple(data.draw(with_dirty_cells(frame)) for frame in frames)

    alerts = _detect(*dirty)
    rec = reconcile(*dirty, resolve_as_of(dirty[0], ctx(dirty[1], dirty[2])))

    assert isinstance(alerts, list)
    assert all(isinstance(alert, Alert) for alert in alerts)
    assert isinstance(rec, Reconciliation)


@settings(max_examples=200, deadline=None)
@given(columns=st.lists(st.text(min_size=1, max_size=10), unique=True, max_size=6))
def test_empty_input_returns_empty(columns: list[str]) -> None:
    """Any ledger without rows, with empty suppliers and payments, gives an empty list."""
    assert detect_reconciliation(pd.DataFrame(columns=columns), ctx()) == []
