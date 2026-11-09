"""Tests for the pi.iban_change detector, the Poltergeist IBAN (Task P11)."""

from types import MappingProxyType

import pandas as pd
import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from apps.phantom_invoices.detectors.iban_change import (
    IBAN_FORMAT_RE,
    IBAN_MOD97_MODULUS,
    IBAN_MOD97_REMAINDER,
    VERIFY_BY_PHONE_MESSAGE,
    detect_iban_changes,
)
from apps.phantom_invoices.detectors.utils import iban_key
from apps.phantom_invoices.tests.pi_builders import (
    SUPPLIER_NAMES,
    Scenario,
    ctx,
    format_iban,
    iban_for_supplier,
    make_invoices,
    make_payments,
    make_suppliers,
    make_test_iban,
    master_iban,
)
from apps.phantom_invoices.tests.pi_strategies import spaced_cased, valid_iban, with_dirty_cells
from ledger_kit.detectors import loaded_source_refs, run_all
from ledger_kit.models import Alert
from ledger_kit.utils.anonymise import mask_iban

DETECTOR = "pi.iban_change"
NAME_1 = SUPPLIER_NAMES[1]
UNKNOWN_COUNTERPARTY = "Comercio Local Ficticio"
OWN_IBAN = master_iban(1)  # the master IBAN of supplier 1, written in groups of four
NEW_IBAN = format_iban(iban_for_supplier(1, other=True))  # a second valid account
HYPHENATED = "ES88-2100-0418-5602-0005-1332"  # the documented IBAN with hyphens: bad format
MASTER_1 = make_suppliers([{"supplier": 1}])
MASTER_3 = make_suppliers([{"supplier": k} for k in (1, 2, 3)])

INVOICE_DIFFERS_KEYS = {
    "variant",
    "supplier_name",
    "invoice_number",
    "invoice_iban_masked",
    "master_iban_masked",
    "last4_identical",
    "verification_message",
}
PAYMENT_DIFFERS_KEYS = {
    "variant",
    "supplier_name",
    "payment_date",
    "payment_amount",
    "payment_iban_masked",
    "master_iban_masked",
    "last4_identical",
    "verification_message",
}
INVALID_KEYS = {"variant", "subject", "label", "reason", "iban_masked"}


def _run(
    invoices: pd.DataFrame,
    suppliers: pd.DataFrame | None = None,
    payments: pd.DataFrame | None = None,
) -> list[Alert]:
    """Run the detector with a context built from the given frames."""
    return detect_iban_changes(invoices, ctx(suppliers, payments))


# Base data of the order properties: 3 master suppliers, 5 invoices and 4 payments, 5 alerts.
BASE_INVOICES = make_invoices(
    [
        {"iban": NEW_IBAN},  # differs from the master of supplier 1
        {"iban": OWN_IBAN},  # same account, no alert
        {"iban": HYPHENATED},  # invalid format
        {"supplier": 2, "iban": OWN_IBAN},  # supplier 2 names the account of supplier 1
        {"iban": None},  # missing, skipped
    ]
)
BASE_PAYMENTS = make_payments(
    [
        {"supplier": 1, "iban": NEW_IBAN},  # differs from the master
        {"supplier": 2, "iban": master_iban(2)},  # same account, no alert
        {"supplier": 3, "iban": HYPHENATED},  # invalid format
        {"supplier": 1, "flow": "credit", "iban": NEW_IBAN},  # credit, ignored
    ]
)
BASE_ALERT_COUNT = 5


# Tier 1: normal cases


def test_iban_change_fires_on_typical_input(ledger_with_iban_change: Scenario) -> None:
    """The P5 fixture (a new valid IBAN on an invoice) raises one critical alert."""
    scenario = ledger_with_iban_change

    alerts = detect_iban_changes(scenario.invoices, scenario.context())

    assert len(alerts) == 1
    assert alerts[0].detector == DETECTOR
    assert alerts[0].severity == "critical"
    assert alerts[0].source_refs == ["inv.csv:0", "sup.csv:0"]
    assert alerts[0].data["variant"] == "invoice_iban_differs_from_master"


def test_iban_change_silent_on_clean_ledger(
    clean_ledger_10: pd.DataFrame, suppliers_master: pd.DataFrame, payments_for_clean: pd.DataFrame
) -> None:
    """Ten clean invoices and their payments, all on the master IBANs, raise nothing."""
    assert _run(clean_ledger_10, suppliers_master, payments_for_clean) == []


def test_pi_acceptance_p04_spaces_and_lowercase_no_alert() -> None:
    """P4: the master IBAN re-typed with spaces and in lower case is the same account."""
    invoices = make_invoices([{"iban": "  " + OWN_IBAN.lower() + " "}])

    assert _run(invoices, MASTER_1) == []


def test_pi_acceptance_p05_new_valid_iban_critical(ledger_with_iban_change: Scenario) -> None:
    """P5: a new valid IBAN on an invoice is a critical Poltergeist IBAN alert."""
    scenario = ledger_with_iban_change

    alerts = detect_iban_changes(scenario.invoices, scenario.context())

    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.detector == DETECTOR
    assert alert.severity == "critical"
    assert alert.title == f"Poltergeist IBAN: {NAME_1}"
    assert alert.source_refs == ["inv.csv:0", "sup.csv:0"]
    assert alert.data["invoice_iban_masked"] == mask_iban(NEW_IBAN)
    assert alert.data["master_iban_masked"] == mask_iban(OWN_IBAN)
    assert alert.data["last4_identical"] is False
    assert alert.data["verification_message"] == VERIFY_BY_PHONE_MESSAGE


def test_pi_acceptance_p12a_hyphenated_iban_warning_format() -> None:
    """P12a: an IBAN with hyphens is not an IBAN; one warning, nothing compared to the master."""
    alerts = _run(make_invoices([{"iban": HYPHENATED}]), MASTER_1)

    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.detector == DETECTOR
    assert alert.severity == "warning"
    assert alert.source_refs == ["inv.csv:0"]
    assert alert.data["variant"] == "iban_invalid"
    assert alert.data["subject"] == "invoice"
    assert alert.data["reason"] == "format"
    assert alert.data["iban_masked"] == "****1332"


def test_pi_acceptance_p12b_nan_iban_skipped() -> None:
    """P12b: a NaN IBAN cell is a missing IBAN and is skipped."""
    assert _run(make_invoices([{"iban": float("nan")}]), MASTER_1) == []


def test_payment_to_non_master_iban_critical() -> None:
    """A payment to a known supplier that went to another account is a critical alert."""
    payments = make_payments([{"supplier": 1, "iban": NEW_IBAN}])

    alerts = _run(make_invoices([]), MASTER_1, payments)

    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.detector == DETECTOR
    assert alert.severity == "critical"
    assert alert.title == f"Payment sent to a non-master IBAN: {NAME_1}"
    assert alert.source_refs == ["pay.csv:0", "sup.csv:0"]
    assert alert.data["variant"] == "payment_to_non_master_iban"
    assert alert.data["payment_date"] == "2026-03-01"
    assert alert.data["payment_amount"] == "121.00"
    assert alert.data["payment_iban_masked"] == mask_iban(NEW_IBAN)
    assert alert.data["master_iban_masked"] == mask_iban(OWN_IBAN)


def test_verify_by_phone_message_has_no_digit() -> None:
    """REQ-PI-26: the advice is one fixed string without a digit."""
    assert isinstance(VERIFY_BY_PHONE_MESSAGE, str)
    assert VERIFY_BY_PHONE_MESSAGE
    assert not any(char.isdigit() for char in VERIFY_BY_PHONE_MESSAGE)


def test_alert_data_contracts() -> None:
    """The three variants carry exactly the keys of REQ-PI-27 and only str and bool values."""
    invoices = make_invoices([{"iban": NEW_IBAN}, {"iban": HYPHENATED}])
    payments = make_payments([{"supplier": 1, "iban": NEW_IBAN}])

    alerts = _run(invoices, MASTER_1, payments)

    by_variant = {a.data["variant"]: a for a in alerts}
    assert set(by_variant) == {
        "invoice_iban_differs_from_master",
        "iban_invalid",
        "payment_to_non_master_iban",
    }
    assert set(by_variant["invoice_iban_differs_from_master"].data) == INVOICE_DIFFERS_KEYS
    assert set(by_variant["payment_to_non_master_iban"].data) == PAYMENT_DIFFERS_KEYS
    assert set(by_variant["iban_invalid"].data) == INVALID_KEYS
    for alert in alerts:
        assert all(isinstance(v, (str, bool)) for v in alert.data.values())


def test_through_run_all_namespace_pi(
    isolated_registry: None, ledger_with_iban_change: Scenario
) -> None:
    """The detector is registered as pi.iban_change and runs through run_all."""
    scenario = ledger_with_iban_change

    results = run_all(scenario.invoices, namespace="pi", context=dict(scenario.context()))

    mine = [r for r in results if r.name == DETECTOR]
    assert len(mine) == 1
    assert len(mine[0].alerts) == 1
    assert mine[0].alerts[0].detector == DETECTOR


# Tier 2: edge cases


def test_ibans_differing_before_last_four_still_alert_with_last4_identical() -> None:
    """Same last four characters, different account: the alert fires and says so."""
    account = "0007654321"  # the account of supplier 1
    twin = format_iban(make_test_iban("0049", "1500", account))
    assert twin != OWN_IBAN

    alerts = _run(make_invoices([{"iban": twin}]), MASTER_1)

    assert len(alerts) == 1
    assert alerts[0].data["last4_identical"] is True
    assert alerts[0].data["invoice_iban_masked"] == alerts[0].data["master_iban_masked"]


def test_nbsp_inside_iban_removed() -> None:
    """A non-breaking space inside the IBAN is whitespace like any other."""
    typed = OWN_IBAN.replace(" ", "\u00a0")

    assert _run(make_invoices([{"iban": typed}]), MASTER_1) == []


@pytest.mark.parametrize("cell", ["-", "---", "\u2013", "\u2014", " ", "\u00a0", ""])
def test_hyphen_only_iban_is_missing(cell: str) -> None:
    """A cell made only of dashes or blanks is a missing IBAN, not an invalid one."""
    assert _run(make_invoices([{"iban": cell}]), MASTER_1) == []


def test_checksum_failure_reason_checksum() -> None:
    """A well-shaped IBAN with wrong check digits is an iban_invalid alert (checksum)."""
    compact = iban_for_supplier(1)
    broken = compact[:2] + "00" + compact[4:]  # check digits 00 are never valid

    alerts = _run(make_invoices([{"iban": broken}]), MASTER_1)

    assert len(alerts) == 1
    assert alerts[0].data["variant"] == "iban_invalid"
    assert alerts[0].data["reason"] == "checksum"
    assert alerts[0].data["label"] == "F-2026-0001"


def test_lowercase_accepted() -> None:
    """A lower-case copy of the master IBAN is the same account."""
    typed = iban_for_supplier(1).lower()

    assert _run(make_invoices([{"iban": typed}]), MASTER_1) == []


def test_invoice_and_payment_same_supplier_two_independent_alerts() -> None:
    """An invoice and a payment of one supplier on a new account give two alerts."""
    invoices = make_invoices([{"iban": NEW_IBAN}])
    payments = make_payments([{"supplier": 1, "iban": NEW_IBAN}])

    alerts = _run(invoices, MASTER_1, payments)

    assert [a.data["variant"] for a in alerts] == [
        "invoice_iban_differs_from_master",
        "payment_to_non_master_iban",
    ]
    assert alerts[0].source_refs == ["inv.csv:0", "sup.csv:0"]
    assert alerts[1].source_refs == ["pay.csv:0", "sup.csv:0"]


def test_empty_ledger_with_non_master_payment_alerts(empty_ledger: pd.DataFrame) -> None:
    """REQ-PI-22: the detector reads the context, so an empty ledger can still alert."""
    payments = make_payments([{"supplier": 1, "iban": NEW_IBAN}])

    alerts = _run(empty_ledger, MASTER_1, payments)

    assert len(alerts) == 1
    assert alerts[0].data["variant"] == "payment_to_non_master_iban"


def test_everything_empty_returns_empty_list(empty_ledger: pd.DataFrame) -> None:
    """No invoice, no master and no payment: an empty list, never an error."""
    assert _run(empty_ledger) == []
    assert detect_iban_changes(pd.DataFrame(), MappingProxyType({})) == []


def test_unknown_supplier_skipped() -> None:
    """An invoice of a supplier absent from the master is not compared with anything."""
    invoices = make_invoices([{"supplier": 5, "iban": NEW_IBAN}])

    assert _run(invoices, MASTER_3) == []


def test_nan_and_none_ibans_skipped() -> None:
    """NaN, None and blank IBAN cells on invoices and payments are skipped."""
    invoices = make_invoices([{"iban": None}, {"iban": float("nan")}, {"iban": " "}])
    payments = make_payments([{"supplier": 1, "iban": None}, {"supplier": 1, "iban": float("nan")}])

    assert _run(invoices, MASTER_1, payments) == []


def test_invalid_master_iban_flagged_once_and_never_compared() -> None:
    """An invalid master IBAN is flagged once; invoices are not compared against it."""
    master = make_suppliers([{"supplier": 1, "iban": HYPHENATED}])
    invoices = make_invoices([{"iban": NEW_IBAN}, {"iban": OWN_IBAN}])

    alerts = _run(invoices, master)

    assert len(alerts) == 1
    assert alerts[0].data["variant"] == "iban_invalid"
    assert alerts[0].data["subject"] == "supplier"
    assert alerts[0].data["label"] == NAME_1
    assert alerts[0].source_refs == ["sup.csv:0"]


def test_attribution_by_name_and_by_iban_for_payments() -> None:
    """Payments are attributed by counterparty name first, then by the master IBAN."""
    payments = make_payments(
        [
            {"supplier": 1, "iban": NEW_IBAN},  # attributed by name, other account: alert
            {"counterparty": UNKNOWN_COUNTERPARTY, "iban": OWN_IBAN},  # by IBAN, same account
            {"counterparty": UNKNOWN_COUNTERPARTY, "iban": NEW_IBAN},  # not attributed at all
        ]
    )

    alerts = _run(make_invoices([]), MASTER_1, payments)

    assert len(alerts) == 1
    assert alerts[0].source_refs == ["pay.csv:0", "sup.csv:0"]


def test_credit_payments_ignored() -> None:
    """Only debits are checked: a credit on a new account raises nothing."""
    payments = make_payments([{"supplier": 1, "flow": "credit", "iban": NEW_IBAN}])

    assert _run(make_invoices([]), MASTER_1, payments) == []


def test_one_alert_per_row() -> None:
    """An invalid IBAN is flagged and never also compared: one alert per row."""
    invoices = make_invoices([{"iban": NEW_IBAN}, {"iban": HYPHENATED}, {"iban": OWN_IBAN}])

    alerts = _run(invoices, MASTER_1)

    assert [a.source_refs[0] for a in alerts] == ["inv.csv:0", "inv.csv:1"]


def test_missing_suppliers_and_payments_keys_in_context() -> None:
    """A context without suppliers and payments is an empty master and no payments."""
    invoices = make_invoices([{"iban": NEW_IBAN}])

    assert detect_iban_changes(invoices, MappingProxyType({})) == []


def test_format_constants_are_reexported() -> None:
    """The IBAN constants are reachable from the detector module (design section 2)."""
    assert IBAN_MOD97_MODULUS == 97
    assert IBAN_MOD97_REMAINDER == 1
    assert IBAN_FORMAT_RE.fullmatch(iban_key(OWN_IBAN))


# Tier 3: property-based tests


@settings(max_examples=200, deadline=None)
@given(data=st.data())
def test_iban_spacing_and_case_never_fire(data: st.DataObject) -> None:
    """The master IBAN re-typed with any spacing and case never raises an alert."""
    iban = data.draw(valid_iban())
    on_invoice = data.draw(spaced_cased(iban))
    on_payment = data.draw(spaced_cased(iban))
    master = make_suppliers([{"supplier": 1, "iban": iban}])
    invoices = make_invoices([{"iban": on_invoice}])
    payments = make_payments([{"supplier": 1, "iban": on_payment}])

    assert _run(invoices, master, payments) == []


def _texts(alert: Alert) -> list[str]:
    """Every string an alert exposes: the title and all str / list[str] values of its data."""
    texts = [alert.title]
    for value in alert.data.values():
        if isinstance(value, str):
            texts.append(value)
        elif isinstance(value, list):
            texts.extend(str(item) for item in value)
    return texts


@settings(max_examples=200, deadline=None)
@given(data=st.data())
def test_alert_data_never_contains_full_iban(data: st.DataObject) -> None:
    """REQ-PII-04: no title or data value of any alert holds a full IBAN."""
    master_value = data.draw(valid_iban())
    other = data.draw(valid_iban())
    assume(iban_key(master_value) != iban_key(other))
    hyphenated = "-".join(other[i : i + 4] for i in range(0, len(other), 4))
    master = make_suppliers([{"supplier": 1, "iban": master_value}])
    invoices = make_invoices([{"iban": other}, {"iban": hyphenated}])
    payments = make_payments([{"supplier": 1, "iban": other}, {"supplier": 1, "iban": hyphenated}])

    alerts = _run(invoices, master, payments)

    assert len(alerts) == 4
    secrets = [iban_key(master_value), iban_key(other), iban_key(hyphenated)]
    for alert in alerts:
        for text in _texts(alert):
            squashed = iban_key(text)
            assert all(secret not in squashed for secret in secrets)


def test_base_data_gives_the_expected_alerts() -> None:
    """The base data of the order properties holds exactly BASE_ALERT_COUNT alerts."""
    assert len(_run(BASE_INVOICES, MASTER_3, BASE_PAYMENTS)) == BASE_ALERT_COUNT


@settings(max_examples=200, deadline=None)
@given(
    invoice_order=st.permutations(list(range(len(BASE_INVOICES)))),
    payment_order=st.permutations(list(range(len(BASE_PAYMENTS)))),
)
def test_row_order_never_changes_any_detector(
    invoice_order: list[int], payment_order: list[int]
) -> None:
    """Shuffling the invoices and the payments never changes the alerts (REQ-PI-10)."""
    expected = _run(BASE_INVOICES, MASTER_3, BASE_PAYMENTS)
    invoices = BASE_INVOICES.iloc[list(invoice_order)].reset_index(drop=True)
    payments = BASE_PAYMENTS.iloc[list(payment_order)].reset_index(drop=True)

    assert _run(invoices, MASTER_3, payments) == expected


@settings(max_examples=200, deadline=None)
@given(
    invoices=with_dirty_cells(BASE_INVOICES),
    suppliers=with_dirty_cells(MASTER_3),
    payments=with_dirty_cells(BASE_PAYMENTS),
)
def test_source_refs_subset_of_loaded_inputs(
    invoices: pd.DataFrame, suppliers: pd.DataFrame, payments: pd.DataFrame
) -> None:
    """No invention: every cited source_ref is in the ledger, the suppliers or the payments."""
    context = ctx(suppliers, payments)

    alerts = detect_iban_changes(invoices, context)

    loaded = loaded_source_refs(invoices, context)
    for alert in alerts:
        assert alert.source_refs
        assert set(alert.source_refs) <= loaded


@settings(max_examples=200, deadline=None)
@given(
    invoices=with_dirty_cells(BASE_INVOICES),
    suppliers=with_dirty_cells(MASTER_3),
    payments=with_dirty_cells(BASE_PAYMENTS),
)
def test_detector_idempotent(
    invoices: pd.DataFrame, suppliers: pd.DataFrame, payments: pd.DataFrame
) -> None:
    """Running the detector twice on the same inputs gives the same alerts."""
    assert _run(invoices, suppliers, payments) == _run(invoices, suppliers, payments)


@settings(max_examples=200, deadline=None)
@given(
    invoices=with_dirty_cells(BASE_INVOICES),
    suppliers=with_dirty_cells(MASTER_3),
    payments=with_dirty_cells(BASE_PAYMENTS),
)
def test_dirty_cells_never_raise(
    invoices: pd.DataFrame, suppliers: pd.DataFrame, payments: pd.DataFrame
) -> None:
    """Whatever cell kinds a messy file produces, the result is a list of alerts."""
    alerts = _run(invoices, suppliers, payments)

    assert isinstance(alerts, list)
    assert all(isinstance(alert, Alert) for alert in alerts)


@settings(max_examples=200, deadline=None)
@given(columns=st.lists(st.text(min_size=1, max_size=10), unique=True, max_size=6))
def test_empty_input_returns_empty(columns: list[str]) -> None:
    """Any ledger without rows, with empty suppliers and payments, gives an empty list."""
    assert detect_iban_changes(pd.DataFrame(columns=columns), ctx()) == []
