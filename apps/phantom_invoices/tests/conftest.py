"""Shared builders, strategies and fixtures of the phantom-invoices tests (REQ-PI-62).

The builders live in pi_builders.py and the Hypothesis strategies in pi_strategies.py, so tests can
import them as ordinary modules; this file re-exports them (``__all__``) and defines the fixtures.
All identifiers follow Finance Rule 5, all names are fictional and all dates are fixed literals:
nothing here reads the system clock.

Scenario fixtures (``ledger_with_*``) return a ``Scenario`` (invoices, suppliers, payments, as_of)
because several detectors need the supplier master or the payments next to the invoices.
"""

from collections.abc import Iterator
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pandas as pd
import pytest

from apps.phantom_invoices.tests.pi_builders import (
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
from apps.phantom_invoices.tests.pi_strategies import (
    consecutive_numbers,
    dirty_cell,
    dirty_frame,
    reconciliation_inputs,
    spaced_cased,
    valid_iban,
)
from ledger_kit.detectors import _restore_registry, _snapshot_registry

__all__ = [
    "Scenario",
    "consecutive_numbers",
    "ctx",
    "dirty_cell",
    "dirty_frame",
    "make_invoices",
    "make_payments",
    "make_suppliers",
    "make_test_iban",
    "reconciliation_inputs",
    "spaced_cased",
    "valid_iban",
]

# Base amounts of clean_ledger_10: all different, so no two invoices of a supplier share a total.
CLEAN_BASES: tuple[str, ...] = (
    "100.00",
    "137.50",
    "180.00",
    "215.25",
    "260.00",
    "305.75",
    "340.00",
    "388.20",
    "420.00",
    "475.10",
)
CLEAN_FIRST_ISSUE_DATE: date = date(2026, 3, 1)
CLEAN_ISSUE_STEP_DAYS: int = 4  # distance between the issue dates of consecutive clean invoices
CLEAN_PAYMENT_DELAY_DAYS: int = 10  # a clean invoice is paid this many days after its issue date
MASTER_SUPPLIERS: tuple[int, ...] = (1, 2, 3)
# A counterparty that is not in the supplier master: its payments belong to no bucket.
UNKNOWN_COUNTERPARTY = "Comercio Local Ficticio"


def _clean_invoice_specs() -> list[dict[str, Any]]:
    """Return the specs of the ten clean invoices: correct VAT, IBAN equal to the master."""
    specs: list[dict[str, Any]] = []
    for index, base in enumerate(CLEAN_BASES):
        supplier = MASTER_SUPPLIERS[index % len(MASTER_SUPPLIERS)]
        issue = CLEAN_FIRST_ISSUE_DATE + timedelta(days=CLEAN_ISSUE_STEP_DAYS * index)
        spec = {
            "supplier": supplier,
            "issue_date": issue,
            "base_amount": Decimal(base),
            "iban": master_iban(supplier),
        }
        specs.append(spec)
    return specs


def _clean_payment_specs() -> list[dict[str, Any]]:
    """Return one payment per clean invoice: its total, to the supplier, to the master IBAN."""
    specs: list[dict[str, Any]] = []
    for index, invoice in enumerate(make_invoices(_clean_invoice_specs()).to_dict("records")):
        supplier = MASTER_SUPPLIERS[index % len(MASTER_SUPPLIERS)]
        paid_on = invoice["issue_date"] + timedelta(days=CLEAN_PAYMENT_DELAY_DAYS)
        spec = {
            "supplier": supplier,
            "date": paid_on,
            "amount": invoice["total"],
            "iban": master_iban(supplier),
        }
        specs.append(spec)
    return specs


@pytest.fixture
def isolated_registry() -> Iterator[None]:
    """Snapshot the global detector registry before a test and restore it afterwards."""
    snapshot = _snapshot_registry()
    try:
        yield
    finally:
        _restore_registry(snapshot)


@pytest.fixture
def empty_ledger() -> pd.DataFrame:
    """Invoice-schema frame with zero rows and all INVOICE_COLUMNS."""
    return make_invoices([])


@pytest.fixture
def single_row_ledger() -> pd.DataFrame:
    """One clean invoice."""
    return make_invoices([{}])


@pytest.fixture
def clean_ledger_10() -> pd.DataFrame:
    """Ten clean invoices of three suppliers; with suppliers_master and payments_for_clean."""
    return make_invoices(_clean_invoice_specs())


@pytest.fixture
def suppliers_master() -> pd.DataFrame:
    """Three master suppliers with valid-checksum, wrong-national-digits IBANs."""
    return make_suppliers([{"supplier": k} for k in MASTER_SUPPLIERS])


@pytest.fixture
def payments_for_clean() -> pd.DataFrame:
    """The ten payments that settle clean_ledger_10."""
    return make_payments(_clean_payment_specs())


@pytest.fixture
def ledger_with_duplicate_invoice() -> Scenario:
    """P1: the same invoice (supplier, number, rate) present twice; no payments, no IBAN."""
    row = {"invoice_number": "F-2026-0042"}
    return Scenario(make_invoices([row, row]), make_suppliers([]), make_payments([]))


@pytest.fixture
def ledger_with_near_duplicate() -> Scenario:
    """P3: F-2026-0042 and F2026-042, same supplier and total, three days apart."""
    invoices = make_invoices(
        [
            {"invoice_number": "F-2026-0042", "issue_date": date(2026, 3, 1)},
            {"invoice_number": "F2026-042", "issue_date": date(2026, 3, 4)},
        ]
    )
    return Scenario(invoices, make_suppliers([]), make_payments([]))


@pytest.fixture
def ledger_with_iban_change(suppliers_master: pd.DataFrame) -> Scenario:
    """P5: an invoice of supplier 1 carries a new valid IBAN that differs from the master."""
    new_iban = format_iban(iban_for_supplier(1, other=True))
    return Scenario(make_invoices([{"iban": new_iban}]), suppliers_master, make_payments([]))


@pytest.fixture
def ledger_with_vat_error() -> Scenario:
    """P7: base 100.00, rate 21, VAT 12.10 and a total (112.10) consistent with that VAT."""
    invoices = make_invoices([{"vat_amount": Decimal("12.10")}])
    return Scenario(invoices, make_suppliers([]), make_payments([]))


@pytest.fixture
def ledger_with_unpaid_invoice(suppliers_master: pd.DataFrame) -> Scenario:
    """One overdue invoice; a later payment of an unknown counterparty fixes as_of."""
    invoices = make_invoices([{"issue_date": date(2026, 1, 10)}])
    payments = make_payments([{"counterparty": UNKNOWN_COUNTERPARTY, "date": date(2026, 4, 15)}])
    return Scenario(invoices, suppliers_master, payments)


@pytest.fixture
def ledger_with_double_payment(suppliers_master: pd.DataFrame) -> Scenario:
    """P9: one invoice paid twice by two debits of the invoice total, inside the window."""
    invoices = make_invoices([{}])
    payments = make_payments(
        [
            {"date": date(2026, 3, 15), "iban": master_iban(1)},
            {"date": date(2026, 3, 20), "iban": master_iban(1)},
        ]
    )
    return Scenario(invoices, suppliers_master, payments)
