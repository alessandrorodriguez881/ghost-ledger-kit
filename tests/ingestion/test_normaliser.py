"""Tests for ledger_kit.ingestion.normaliser (three tiers, three kinds)."""

import csv
import io
from datetime import date
from decimal import Decimal

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ledger_kit.ingestion.csv_reader import parse_csv
from ledger_kit.ingestion.dialect import CsvDialect, parse_amount
from ledger_kit.ingestion.normaliser import (
    CANONICAL_COLUMNS,
    COLUMNS,
    INVOICE_COLUMNS,
    SUPPLIER_COLUMNS,
    normalise,
)
from ledger_kit.models import Invoice, Supplier, Transaction
from ledger_kit.utils.money import format_as_european

IBAN = "ES88 2100 0418 5602 0005 1332"
CSV_FIELDS = ["date", "amount", "currency", "counterparty", "description"]


def _tx(index: int, source_file: str = "a.csv", **over: object) -> Transaction:
    """Build a synthetic Transaction."""
    values: dict = {
        "date": date(2026, 1, 15),
        "amount": Decimal("12.99"),
        "flow": "debit",
        "currency": "EUR",
        "counterparty": "Ana García",
        "description": "Streaming plan",
        "source_file": source_file,
        "source_row": index,
        "source_ref": f"{source_file}:{index}",
    }
    values.update(over)
    return Transaction(**values)


def _bad_tx(index: int, source_file: str = "a.csv") -> Transaction:
    """Build a Transaction that bypasses validation and holds a null required field."""
    values = _tx(index, source_file).model_dump()
    values["counterparty"] = None
    return Transaction.model_construct(**values)


def _inv(index: int, source_file: str = "inv.csv") -> Invoice:
    """Build a synthetic Invoice."""
    return Invoice(
        invoice_number=f"INV-{index:04d}",
        supplier_name="Rossi Forniture",
        supplier_tax_id="B00000001",
        issue_date=date(2026, 1, 15),
        due_date=date(2026, 2, 14),
        due_date_is_default=True,
        base_amount=Decimal("1000.00"),
        vat_rate=Decimal("21"),
        vat_amount=Decimal("210.00"),
        total=Decimal("1210.00"),
        iban=IBAN,
        currency="EUR",
        source_file=source_file,
        source_row=index,
        source_ref=f"{source_file}:{index}",
    )


def _sup(index: int, source_file: str = "sup.csv") -> Supplier:
    """Build a synthetic Supplier."""
    return Supplier(
        supplier_name="Dupont Services",
        tax_id="B00000002",
        iban=None,
        source_file=source_file,
        source_row=index,
        source_ref=f"{source_file}:{index}",
    )


def _all_object_of(frame: pd.DataFrame, column: str, kind: type) -> bool:
    """True when every value in `column` is an instance of `kind`."""
    return all(isinstance(v, kind) for v in frame[column])


# --- Tier 1 ---------------------------------------------------------------------------


def test_normalise_returns_dataframe() -> None:
    frame, quarantined = normalise([_tx(0)])
    assert isinstance(frame, pd.DataFrame)
    assert quarantined == []
    assert len(frame) == 1


def test_normalise_schema_columns_present() -> None:
    frame, _ = normalise([_tx(0)])
    assert tuple(frame.columns) == CANONICAL_COLUMNS
    assert CANONICAL_COLUMNS == (
        "id",
        "date",
        "amount",
        "flow",
        "currency",
        "counterparty",
        "description",
        "iban",
        "source_file",
        "source_row",
        "source_ref",
        "source_line",
        "tags",
    )


def test_normalise_empty_source_returns_empty_df() -> None:
    frame, quarantined = normalise([])
    assert frame.empty
    assert quarantined == []


def test_normalise_invoices_returns_invoice_columns() -> None:
    frame, quarantined = normalise([_inv(0), _inv(1)])
    assert tuple(frame.columns) == INVOICE_COLUMNS
    assert INVOICE_COLUMNS == (
        "invoice_number",
        "supplier_name",
        "supplier_tax_id",
        "issue_date",
        "due_date",
        "due_date_is_default",
        "base_amount",
        "vat_rate",
        "vat_amount",
        "surcharge_amount",
        "withholding_amount",
        "total",
        "iban",
        "currency",
        "source_file",
        "source_row",
        "source_ref",
        "source_line",
    )
    assert len(frame) == 2
    assert quarantined == []


def test_normalise_suppliers_returns_supplier_columns() -> None:
    frame, quarantined = normalise([_sup(0), _sup(1), _sup(2)])
    assert tuple(frame.columns) == SUPPLIER_COLUMNS
    assert SUPPLIER_COLUMNS == (
        "supplier_name",
        "tax_id",
        "iban",
        "source_file",
        "source_row",
        "source_ref",
        "source_line",
    )
    assert list(frame["source_ref"]) == ["sup.csv:0", "sup.csv:1", "sup.csv:2"]
    assert quarantined == []


# --- Tier 2 ---------------------------------------------------------------------------


def test_normalise_all_quarantined_returns_empty_df_with_columns() -> None:
    frame, quarantined = normalise([_bad_tx(0), _bad_tx(1)])
    assert frame.empty
    assert tuple(frame.columns) == CANONICAL_COLUMNS
    assert len(frame["source_ref"]) == 0  # must not raise KeyError
    assert len(quarantined) == 2


def test_normalise_no_sources_returns_empty_df_with_columns() -> None:
    frame, quarantined = normalise()
    assert frame.empty
    assert tuple(frame.columns) == CANONICAL_COLUMNS
    assert len(frame["source_ref"]) == 0
    assert quarantined == []


def test_normalise_single_transaction() -> None:
    frame, _ = normalise([_tx(0, counterparty="Luigi Rossi")])
    assert len(frame) == 1
    assert frame.iloc[0]["counterparty"] == "Luigi Rossi"
    assert frame.iloc[0]["source_ref"] == "a.csv:0"


def test_normalise_multiple_sources_merged() -> None:
    frame, quarantined = normalise([_tx(0, "a.csv"), _tx(1, "a.csv")], [_tx(0, "b.csv")])
    assert list(frame["source_ref"]) == ["a.csv:0", "a.csv:1", "b.csv:0"]
    assert quarantined == []


def test_normalise_quarantines_null_required_field() -> None:
    frame, quarantined = normalise([_tx(0), _bad_tx(1), _tx(2)])
    assert list(frame["source_ref"]) == ["a.csv:0", "a.csv:2"]
    assert len(quarantined) == 1
    record = quarantined[0]
    assert record["source_file"] == "a.csv"
    assert record["source_row"] == 1
    assert record["reason"] == "missing_field:counterparty"
    assert isinstance(record["raw"], dict)


def test_normalise_optional_iban_none_is_not_quarantined() -> None:
    frame, quarantined = normalise([_tx(0, iban=None)])
    assert len(frame) == 1
    assert quarantined == []


def test_normalise_amount_dtype_is_object_decimal() -> None:
    frame, _ = normalise([_tx(0), _tx(1)])
    assert frame["amount"].dtype == object
    assert _all_object_of(frame, "amount", Decimal)


def test_normalise_date_dtype_is_object_date() -> None:
    frame, _ = normalise([_tx(0), _tx(1)])
    assert frame["date"].dtype == object
    assert _all_object_of(frame, "date", date)


def test_normalise_source_row_dtype_is_int() -> None:
    frame, _ = normalise([_tx(0), _tx(1)])
    assert frame["source_row"].dtype == "int64"


def test_normalise_empty_invoice_kind_returns_empty_df_with_invoice_columns() -> None:
    frame, quarantined = normalise(kind="invoice")
    assert frame.empty
    assert tuple(frame.columns) == INVOICE_COLUMNS
    frame, quarantined = normalise([], kind="supplier")
    assert frame.empty
    assert tuple(frame.columns) == SUPPLIER_COLUMNS
    assert quarantined == []


def test_normalise_all_invoices_quarantined_keeps_columns() -> None:
    values = _inv(0).model_dump()
    values["supplier_name"] = None
    bad = Invoice.model_construct(**values)
    frame, quarantined = normalise([bad])
    assert frame.empty
    assert tuple(frame.columns) == INVOICE_COLUMNS
    assert len(frame["source_ref"]) == 0
    assert quarantined[0]["reason"] == "missing_field:supplier_name"


def test_normalise_mixed_kinds_raises_value_error() -> None:
    with pytest.raises(ValueError):
        normalise([_tx(0)], [_inv(0)])
    with pytest.raises(ValueError):
        normalise([_tx(0), _sup(0)])


def test_normalise_kind_disagreeing_with_inferred_kind_raises_value_error() -> None:
    with pytest.raises(ValueError):
        normalise([_tx(0)], kind="invoice")


def test_normalise_invoice_decimal_and_date_dtypes() -> None:
    frame, _ = normalise([_inv(0), _inv(1)])
    for column in ("base_amount", "vat_rate", "total"):
        assert _all_object_of(frame, column, Decimal)
    for column in ("issue_date", "due_date"):
        assert _all_object_of(frame, column, date)
    assert frame["source_row"].dtype == "int64"
    assert frame.iloc[0]["vat_rate"] == Decimal("21")


def test_normalise_no_sources_defaults_to_transaction_columns() -> None:
    frame, _ = normalise([], [])
    assert tuple(frame.columns) == CANONICAL_COLUMNS


def test_normalise_empty_frames_have_expected_dtypes() -> None:
    frame, _ = normalise(kind="transaction")
    assert frame["source_row"].dtype == "int64"
    assert frame["source_line"].dtype == "Int64"


@pytest.mark.parametrize("kind", ["transaction", "invoice", "supplier"])
def test_source_line_sits_right_after_source_ref_for_every_kind(kind: str) -> None:
    columns = list(COLUMNS[kind])
    assert columns[columns.index("source_ref") + 1] == "source_line"


def test_source_line_is_a_nullable_integer_and_none_stays_empty() -> None:
    frame, quarantined = normalise([_tx(0, source_line=3), _tx(1), _tx(2, source_line=9)])
    assert quarantined == []
    assert frame["source_line"].dtype == "Int64"
    assert frame["source_line"][0] == 3 and frame["source_line"][2] == 9
    assert pd.isna(frame["source_line"][1])
    for model, kind in ((_inv(0), "invoice"), (_sup(0), "supplier")):
        other, _ = normalise([model], kind=kind)
        assert other["source_line"].dtype == "Int64" and other["source_line"].isna().all()


def test_a_missing_source_line_is_not_a_reason_to_quarantine() -> None:
    frame, quarantined = normalise([_tx(0)])
    assert len(frame) == 1 and quarantined == []


# --- Tier 3 ---------------------------------------------------------------------------


def _csv_text(row: dict[str, str]) -> io.StringIO:
    """Write a one-row plain-dialect CSV into a text stream."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_FIELDS)
    writer.writeheader()
    writer.writerow(row)
    buf.seek(0)
    return buf


@settings(max_examples=200)
@given(
    signed=st.decimals(
        min_value=Decimal("-1000000"),
        max_value=Decimal("1000000"),
        places=2,
        allow_nan=False,
        allow_infinity=False,
    )
)
def test_signed_amount_round_trip(signed: Decimal) -> None:
    """abs(amount) and flow survive CSV write -> parse_csv -> normalise."""
    row = {
        "date": "2026-01-15",
        "amount": str(signed),
        "currency": "EUR",
        "counterparty": "Test",
        "description": "x",
    }
    txns, quarantined = parse_csv(_csv_text(row), dialect="plain", source_file="test.csv")
    assert quarantined == []
    transaction = txns[0]
    assert transaction.amount == abs(signed)
    assert transaction.flow == ("debit" if signed < 0 else "credit")
    reconstructed = -transaction.amount if transaction.flow == "debit" else transaction.amount
    assert reconstructed == signed

    frame, frame_quarantine = normalise(txns)
    assert frame_quarantine == []
    assert frame.iloc[0]["amount"] == abs(signed)
    assert frame.iloc[0]["flow"] == transaction.flow


@settings(max_examples=200)
@given(d=st.dates(min_value=date(1900, 1, 1), max_value=date(2100, 12, 31)))
def test_date_round_trip_plain(d: date) -> None:
    """An ISO date survives CSV write -> parse_csv -> normalise."""
    row = {
        "date": d.isoformat(),
        "amount": "10.00",
        "currency": "EUR",
        "counterparty": "Test",
        "description": "x",
    }
    txns, quarantined = parse_csv(_csv_text(row), dialect="plain", source_file="test.csv")
    assert quarantined == []
    assert txns[0].date == d
    frame, _ = normalise(txns)
    assert frame.iloc[0]["date"] == d


@settings(max_examples=200)
@given(
    amount=st.decimals(
        min_value=Decimal("0"),
        max_value=Decimal("999999.99"),
        places=2,
        allow_nan=False,
        allow_infinity=False,
    ),
    negative=st.booleans(),
)
def test_european_amount_round_trip(amount: Decimal, negative: bool) -> None:
    """format_as_european then parse_amount(EUROPEAN) is the identity function."""
    signed = -amount if negative else amount
    parsed = parse_amount(format_as_european(signed), CsvDialect.EUROPEAN)
    assert parsed == signed
