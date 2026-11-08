"""Tests for the canonical models (Transaction, Invoice, Supplier, Alert)."""

import re
from datetime import date
from decimal import Decimal

import numpy
import pytest
from pydantic import ValidationError

from ledger_kit.models import Alert, Invoice, Supplier, Transaction


def _transaction(**overrides) -> Transaction:
    """Build a synthetic Transaction, overriding selected fields."""
    fields = {
        "date": date(2026, 1, 15),
        "amount": Decimal("12.99"),
        "flow": "debit",
        "currency": "EUR",
        "counterparty": "Ana García",
        "description": "Monthly plan",
        "source_file": "bank.csv",
        "source_row": 4,
        "source_ref": "bank.csv:4",
    }
    fields.update(overrides)
    return Transaction(**fields)


def _invoice(**overrides) -> Invoice:
    """Build a synthetic Invoice with only mandatory fields, overriding selected ones."""
    fields = {
        "invoice_number": "INV-001",
        "supplier_name": "Luigi Rossi",
        "supplier_tax_id": "B00000001",
        "issue_date": date(2026, 2, 1),
        "due_date": date(2026, 3, 3),
        "base_amount": Decimal("1000.00"),
        "vat_rate": Decimal("21"),
        "vat_amount": Decimal("210.00"),
        "total": Decimal("1210.00"),
        "currency": "EUR",
        "source_file": "inv.csv",
        "source_row": 0,
        "source_ref": "inv.csv:0",
    }
    fields.update(overrides)
    return Invoice(**fields)


def _alert_kwargs(**overrides) -> dict:
    """Return keyword arguments for a synthetic Alert, overriding selected ones."""
    kwargs = {
        "detector": "zs.recurring_charge",
        "severity": "warning",
        "title": "Recurring charge",
        "source_refs": ["bank.csv:1", "bank.csv:2"],
        "data": {"yearly_cost": "155.88"},
    }
    kwargs.update(overrides)
    return kwargs


def _quarantine_record(
    source_file: str, source_row: int | None, reason: str, raw: dict | str
) -> dict:
    """Build a quarantine record with the documented keys (design §2.3)."""
    return {"source_file": source_file, "source_row": source_row, "reason": reason, "raw": raw}


# --- Transaction -------------------------------------------------------------------------


def test_transaction_source_ref_computed() -> None:
    txn = _transaction(source_file="bank.csv", source_row=4, source_ref="bank.csv:4")
    assert txn.source_ref == f"{txn.source_file}:{txn.source_row}"
    assert txn.source_ref == "bank.csv:4"


def test_transaction_amount_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        _transaction(amount=Decimal("-0.01"))


def test_transaction_is_frozen() -> None:
    txn = _transaction()
    with pytest.raises(ValidationError):
        txn.amount = Decimal("1.00")


# --- Alert -------------------------------------------------------------------------------


def test_alert_requires_non_empty_source_refs() -> None:
    with pytest.raises(ValidationError):
        Alert(**_alert_kwargs(source_refs=[]))


def test_alert_is_frozen() -> None:
    alert = Alert(**_alert_kwargs())
    with pytest.raises(ValidationError):
        alert.title = "other"


def test_alert_deterministic_id() -> None:
    first = Alert(**_alert_kwargs())
    second = Alert(**_alert_kwargs())
    assert first.id == second.id
    assert first.id != ""


def test_alert_deterministic_id_ignores_source_ref_order() -> None:
    first = Alert(**_alert_kwargs(source_refs=["a:1", "a:2"]))
    second = Alert(**_alert_kwargs(source_refs=["a:2", "a:1"]))
    assert first.id == second.id


def test_alert_explicit_id_preserved() -> None:
    alert = Alert(**_alert_kwargs(id="custom-id"))
    assert alert.id == "custom-id"


def test_alert_id_with_decimal_and_date_data() -> None:
    data = {"yearly_cost": Decimal("155.88"), "last": date(2026, 1, 15)}
    first = Alert(**_alert_kwargs(data=data))
    second = Alert(**_alert_kwargs(data=dict(data)))
    assert re.fullmatch(r"[0-9a-f]{64}", first.id)
    assert first.id == second.id


def test_alert_id_numpy_scalar_matches_python_value() -> None:
    from_numpy = Alert(**_alert_kwargs(data={"n": numpy.int64(3)}))
    from_python = Alert(**_alert_kwargs(data={"n": 3}))
    assert from_numpy.id == from_python.id


def test_alert_missing_source_refs_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        Alert(detector="x.y", severity="info", title="t", data={})


def test_alert_does_not_mutate_input_dict() -> None:
    values = _alert_kwargs()
    Alert(**values)
    assert "id" not in values


def test_quarantine_dict_shape() -> None:
    record = _quarantine_record("bank.csv", 2, "missing_field:amount", {"date": "2026-01-01"})
    assert set(record) == {"source_file", "source_row", "reason", "raw"}
    whole_file = _quarantine_record("bank.csv", None, "undecodable_file", "")
    assert whole_file["source_row"] is None


# --- Invoice -----------------------------------------------------------------------------


def test_invoice_defaults() -> None:
    invoice = _invoice()
    assert invoice.surcharge_amount == Decimal("0")
    assert invoice.withholding_amount == Decimal("0")
    assert invoice.iban is None
    assert invoice.due_date_is_default is False


def test_invoice_vat_rate_is_a_percentage() -> None:
    invoice = _invoice(vat_rate=Decimal("21"))
    assert invoice.vat_rate == Decimal("21")
    assert invoice.vat_rate != Decimal("0.21")


@pytest.mark.parametrize(
    "field",
    [
        "base_amount",
        "vat_rate",
        "vat_amount",
        "surcharge_amount",
        "withholding_amount",
        "total",
    ],
)
def test_invoice_negative_amount_raises_validation_error(field: str) -> None:
    with pytest.raises(ValidationError):
        _invoice(**{field: Decimal("-0.01")})


def test_invoice_is_frozen_and_has_no_id_field() -> None:
    invoice = _invoice()
    assert "id" not in Invoice.model_fields
    with pytest.raises(ValidationError):
        invoice.total = Decimal("1.00")


# --- Supplier ----------------------------------------------------------------------------


def _supplier(**overrides) -> Supplier:
    """Build a synthetic Supplier, overriding selected fields."""
    fields = {
        "supplier_name": "Sophie Dupont",
        "tax_id": "B00000002",
        "source_file": "sup.csv",
        "source_row": 0,
        "source_ref": "sup.csv:0",
    }
    fields.update(overrides)
    return Supplier(**fields)


def test_supplier_iban_optional_and_verbatim() -> None:
    assert _supplier().iban is None
    assert _supplier(iban=" es88 2100 ").iban == " es88 2100 "


def test_supplier_is_frozen() -> None:
    supplier = _supplier()
    with pytest.raises(ValidationError):
        supplier.tax_id = "B00000003"


# --- Package -----------------------------------------------------------------------------


def test_package_reexports_models() -> None:
    import ledger_kit

    assert ledger_kit.Transaction is Transaction
    assert ledger_kit.Invoice is Invoice
    assert ledger_kit.Supplier is Supplier
    assert ledger_kit.Alert is Alert
