"""Tests for ledger_kit.ingestion.invoice_reader (CSV + JSON, quarantine, encodings)."""

import io
import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from ledger_kit.ingestion.invoice_reader import DEFAULT_PAYMENT_TERM_DAYS, parse_invoice
from ledger_kit.models import Invoice

IBAN = "es88 2100 0418 5602 0005 1332"
HYPHEN_IBAN = "ES88-2100-0418-5602-0005-1332"

MANDATORY = (
    "invoice_number",
    "supplier_name",
    "supplier_tax_id",
    "issue_date",
    "base_amount",
    "vat_rate",
    "vat_amount",
    "total",
    "currency",
)
FULL_HEADER = (
    "invoice_number,supplier_name,supplier_tax_id,issue_date,due_date,base_amount,vat_rate,"
    "vat_amount,surcharge_amount,withholding_amount,total,iban,currency"
)
MIN_HEADER = (
    "invoice_number,supplier_name,supplier_tax_id,issue_date,base_amount,vat_rate,"
    "vat_amount,total,currency"
)
MIN_ROW = "INV-001,Rossi Forniture,B00000001,2026-01-15,1000.00,21,210.00,1210.00,EUR"


def _csv(header: str, *rows: str) -> io.StringIO:
    """Build a CSV text stream from a header and rows."""
    return io.StringIO("\n".join([header, *rows]) + "\n")


def _json_row(**over: object) -> dict:
    """A valid JSON invoice record with optional overrides."""
    row: dict = {
        "invoice_number": "INV-001",
        "supplier_name": "Rossi Forniture",
        "supplier_tax_id": "B00000001",
        "issue_date": "2026-01-15",
        "base_amount": "1000.00",
        "vat_rate": "21",
        "vat_amount": "210.00",
        "total": "1210.00",
        "currency": "EUR",
    }
    row.update(over)
    return row


def _json(*rows: dict) -> io.StringIO:
    """Build a JSON text stream from records."""
    return io.StringIO(json.dumps(list(rows)))


def _full_csv_row(**over: str) -> str:
    """A full-column CSV row where selected columns are overridden."""
    values = {
        "invoice_number": "INV-001",
        "supplier_name": "Rossi Forniture",
        "supplier_tax_id": "B00000001",
        "issue_date": "2026-01-15",
        "due_date": "2026-02-28",
        "base_amount": "1000.00",
        "vat_rate": "21",
        "vat_amount": "210.00",
        "surcharge_amount": "0",
        "withholding_amount": "0",
        "total": "1210.00",
        "iban": "",
        "currency": "EUR",
    }
    values.update(over)
    return ",".join(values[c] for c in FULL_HEADER.split(","))


# --- Tier 1 ---------------------------------------------------------------------------


def test_parse_invoice_csv_valid() -> None:
    row_2 = _full_csv_row(invoice_number="INV-002", iban=IBAN, withholding_amount="150.00")
    invoices, quarantined = parse_invoice(
        _csv(FULL_HEADER, _full_csv_row(), row_2), fmt="csv", source_file="inv.csv"
    )
    assert quarantined == []
    assert len(invoices) == 2
    assert all(isinstance(i, Invoice) for i in invoices)
    first = invoices[0]
    assert first.invoice_number == "INV-001"
    assert first.supplier_name == "Rossi Forniture"
    assert first.supplier_tax_id == "B00000001"
    assert first.issue_date == date(2026, 1, 15)
    assert first.due_date == date(2026, 2, 28)
    assert first.due_date_is_default is False
    assert first.base_amount == Decimal("1000.00")
    assert first.vat_rate == Decimal("21")
    assert first.vat_amount == Decimal("210.00")
    assert first.surcharge_amount == Decimal("0")
    assert first.withholding_amount == Decimal("0")
    assert first.total == Decimal("1210.00")
    assert first.iban is None
    assert first.currency == "EUR"
    assert first.source_file == "inv.csv"
    assert first.source_row == 0
    assert first.source_ref == "inv.csv:0"
    assert invoices[1].source_ref == "inv.csv:1"
    assert invoices[1].withholding_amount == Decimal("150.00")


def test_parse_invoice_json_valid() -> None:
    invoices, quarantined = parse_invoice(
        _json(_json_row(), _json_row(invoice_number="INV-002", due_date="2026-03-01")),
        fmt="json",
        source_file="inv.json",
    )
    assert quarantined == []
    assert [i.invoice_number for i in invoices] == ["INV-001", "INV-002"]
    assert all(isinstance(i, Invoice) for i in invoices)
    assert invoices[0].source_ref == "inv.json:0"
    assert invoices[1].due_date == date(2026, 3, 1)
    assert invoices[1].due_date_is_default is False


def test_parse_invoice_optional_columns_default() -> None:
    invoices, quarantined = parse_invoice(
        _csv(MIN_HEADER, MIN_ROW), fmt="csv", source_file="inv.csv"
    )
    assert quarantined == []
    invoice = invoices[0]
    assert invoice.surcharge_amount == Decimal("0")
    assert invoice.withholding_amount == Decimal("0")
    assert invoice.iban is None
    assert DEFAULT_PAYMENT_TERM_DAYS == 30
    assert invoice.due_date == invoice.issue_date + timedelta(days=30)
    assert invoice.due_date_is_default is True


def test_parse_invoice_explicit_due_date_not_defaulted() -> None:
    invoices, _ = parse_invoice(
        _csv(FULL_HEADER, _full_csv_row(due_date="2026-01-31")), fmt="csv", source_file="i.csv"
    )
    assert invoices[0].due_date == date(2026, 1, 31)
    assert invoices[0].due_date_is_default is False


# --- Tier 2 ---------------------------------------------------------------------------


def test_parse_invoice_csv_empty() -> None:
    assert parse_invoice(io.StringIO(""), fmt="csv", source_file="inv.csv") == ([], [])


def test_parse_invoice_csv_whitespace_only() -> None:
    assert parse_invoice(io.StringIO("  \n\t\n"), fmt="csv", source_file="inv.csv") == ([], [])


def test_parse_invoice_json_empty_array() -> None:
    assert parse_invoice(io.StringIO("[]"), fmt="json", source_file="inv.json") == ([], [])


def test_parse_invoice_json_amount_as_string() -> None:
    invoices, quarantined = parse_invoice(
        _json(_json_row(base_amount="123.45")), fmt="json", source_file="inv.json"
    )
    assert quarantined == []
    assert invoices[0].base_amount == Decimal("123.45")


def test_parse_invoice_json_amount_as_float() -> None:
    invoices, quarantined = parse_invoice(
        _json(_json_row(base_amount=123.45, vat_rate=21, total=1210)),
        fmt="json",
        source_file="inv.json",
    )
    assert quarantined == []
    assert invoices[0].base_amount == Decimal("123.45")
    assert invoices[0].vat_rate == Decimal("21")
    assert invoices[0].total == Decimal("1210")


@pytest.mark.parametrize("column", MANDATORY)
def test_parse_invoice_csv_missing_field_quarantined(column: str) -> None:
    row = _full_csv_row(**{column: ""})
    invoices, quarantined = parse_invoice(_csv(FULL_HEADER, row), fmt="csv", source_file="inv.csv")
    assert invoices == []
    assert len(quarantined) == 1
    record = quarantined[0]
    assert record["reason"] == f"missing_field:{column}"
    assert record["source_file"] == "inv.csv"
    assert record["source_row"] == 0
    assert "raw" in record


@pytest.mark.parametrize("column", MANDATORY)
def test_parse_invoice_json_missing_field_quarantined(column: str) -> None:
    row = _json_row()
    del row[column]
    invoices, quarantined = parse_invoice(_json(row), fmt="json", source_file="inv.json")
    assert invoices == []
    assert quarantined[0]["reason"] == f"missing_field:{column}"


def test_parse_invoice_valid_rows_returned_alongside_quarantine() -> None:
    bad = _full_csv_row(total="")
    invoices, quarantined = parse_invoice(
        _csv(FULL_HEADER, _full_csv_row(), bad, _full_csv_row(invoice_number="INV-003")),
        fmt="csv",
        source_file="inv.csv",
    )
    assert [i.source_row for i in invoices] == [0, 2]
    assert [q["source_row"] for q in quarantined] == [1]


@pytest.mark.parametrize("column", ["total", "base_amount", "vat_rate", "vat_amount"])
def test_parse_invoice_negative_amount_quarantined(column: str) -> None:
    row = _full_csv_row(**{column: "-1.00"})
    invoices, quarantined = parse_invoice(_csv(FULL_HEADER, row), fmt="csv", source_file="inv.csv")
    assert invoices == []
    assert quarantined[0]["reason"] == "negative_amount"


@pytest.mark.parametrize("column", ["surcharge_amount", "withholding_amount"])
def test_parse_invoice_negative_optional_amount_quarantined(column: str) -> None:
    row = _full_csv_row(**{column: "-5.00"})
    _, quarantined = parse_invoice(_csv(FULL_HEADER, row), fmt="csv", source_file="inv.csv")
    assert quarantined[0]["reason"] == "negative_amount"


def test_parse_invoice_percent_sign_vat_rate_quarantined() -> None:
    row = _full_csv_row(vat_rate="21%")
    invoices, quarantined = parse_invoice(_csv(FULL_HEADER, row), fmt="csv", source_file="inv.csv")
    assert invoices == []
    assert quarantined[0]["reason"] == "unparseable_amount"


def test_parse_invoice_unparseable_amount_quarantined() -> None:
    row = _full_csv_row(total="abc")
    _, quarantined = parse_invoice(_csv(FULL_HEADER, row), fmt="csv", source_file="inv.csv")
    assert quarantined[0]["reason"] == "unparseable_amount"


def test_parse_invoice_unparseable_issue_date_quarantined() -> None:
    row = _full_csv_row(issue_date="15/01/2026")
    invoices, quarantined = parse_invoice(_csv(FULL_HEADER, row), fmt="csv", source_file="inv.csv")
    assert invoices == []
    assert quarantined[0]["reason"] == "unparseable_date"


def test_parse_invoice_unparseable_due_date_quarantined() -> None:
    row = _full_csv_row(due_date="not-a-date")
    _, quarantined = parse_invoice(_csv(FULL_HEADER, row), fmt="csv", source_file="inv.csv")
    assert quarantined[0]["reason"] == "unparseable_date"


def test_parse_invoice_iban_kept_verbatim() -> None:
    rows = [_full_csv_row(iban=IBAN), _full_csv_row(iban=HYPHEN_IBAN)]
    invoices, quarantined = parse_invoice(
        _csv(FULL_HEADER, *rows), fmt="csv", source_file="inv.csv"
    )
    assert quarantined == []
    assert invoices[0].iban == IBAN
    assert invoices[1].iban == HYPHEN_IBAN


def test_parse_invoice_json_invalid_document_quarantined() -> None:
    invoices, quarantined = parse_invoice(
        io.StringIO("{not json"), fmt="json", source_file="inv.json"
    )
    assert invoices == []
    assert quarantined[0]["reason"] == "invalid_json"
    assert quarantined[0]["source_row"] is None


def test_parse_invoice_json_non_array_quarantined() -> None:
    invoices, quarantined = parse_invoice(
        io.StringIO('{"invoice_number": "INV-001"}'), fmt="json", source_file="inv.json"
    )
    assert invoices == []
    assert quarantined[0]["reason"] == "invalid_json"


def test_parse_invoice_json_non_object_row_quarantined() -> None:
    invoices, quarantined = parse_invoice(
        io.StringIO(json.dumps([_json_row(), 42])), fmt="json", source_file="inv.json"
    )
    assert len(invoices) == 1
    assert quarantined[0]["source_row"] == 1
    assert quarantined[0]["reason"] == "invalid_row"


def test_parse_invoice_format_auto_detect_json(tmp_path: Path) -> None:
    path = tmp_path / "inv.json"
    path.write_text(json.dumps([_json_row()]), encoding="utf-8")
    invoices, quarantined = parse_invoice(path)
    assert quarantined == []
    assert invoices[0].source_ref == "inv.json:0"


def test_parse_invoice_format_auto_detect_csv(tmp_path: Path) -> None:
    path = tmp_path / "inv.csv"
    path.write_text("\n".join([MIN_HEADER, MIN_ROW]) + "\n", encoding="utf-8")
    invoices, quarantined = parse_invoice(path)
    assert quarantined == []
    assert invoices[0].source_ref == "inv.csv:0"


def test_parse_invoice_utf8_bom_decoded() -> None:
    row = MIN_ROW.replace("Rossi Forniture", "Ana García Consulting")
    raw = b"\xef\xbb\xbf" + ("\n".join([MIN_HEADER, row]) + "\n").encode("utf-8")
    invoices, quarantined = parse_invoice(io.BytesIO(raw), fmt="csv", source_file="inv.csv")
    assert quarantined == []
    assert invoices[0].invoice_number == "INV-001"
    assert invoices[0].supplier_name == "Ana García Consulting"


def test_parse_invoice_cp1252_decoded() -> None:
    row = MIN_ROW.replace("Rossi Forniture", "Ana García Consulting")
    raw = ("\n".join([MIN_HEADER, row]) + "\n").encode("cp1252")
    invoices, quarantined = parse_invoice(io.BytesIO(raw), fmt="csv", source_file="inv.csv")
    assert quarantined == []
    assert invoices[0].supplier_name == "Ana García Consulting"


def test_parse_invoice_undecodable_file_quarantined() -> None:
    raw = MIN_HEADER.encode("ascii") + b"\n\x81\x8d\x8f,x\n"
    invoices, quarantined = parse_invoice(io.BytesIO(raw), fmt="csv", source_file="inv.csv")
    assert invoices == []
    assert len(quarantined) == 1
    assert quarantined[0]["reason"] == "undecodable_file"
    assert quarantined[0]["encoding_tried"] == ["utf-8-sig", "cp1252"]
