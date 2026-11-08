"""Tests for ledger_kit.ingestion.supplier_reader (supplier-master CSV)."""

import io

from ledger_kit.ingestion.supplier_reader import parse_suppliers
from ledger_kit.models import Supplier

HEADER = "supplier_name,tax_id,iban"
IBAN = " es88 2100 0418 5602 0005 1332"


def _csv(header: str, *rows: str) -> io.StringIO:
    """Build a CSV text stream from a header and rows."""
    return io.StringIO("\n".join([header, *rows]) + "\n")


# --- Tier 1 ---------------------------------------------------------------------------


def test_parse_suppliers_valid() -> None:
    rows = (
        "Rossi Forniture,B00000001,",
        "Dupont Services,B00000002,",
        "Ana García Consulting,B00000003,",
    )
    suppliers, quarantined = parse_suppliers(_csv(HEADER, *rows), source_file="sup.csv")
    assert quarantined == []
    assert len(suppliers) == 3
    assert all(isinstance(s, Supplier) for s in suppliers)
    first = suppliers[0]
    assert first.supplier_name == "Rossi Forniture"
    assert first.tax_id == "B00000001"
    assert first.iban is None
    assert first.source_file == "sup.csv"
    assert first.source_row == 0
    assert first.source_ref == "sup.csv:0"
    assert suppliers[2].source_ref == "sup.csv:2"


# --- Tier 2 ---------------------------------------------------------------------------


def test_parse_suppliers_empty_and_whitespace_only() -> None:
    assert parse_suppliers(io.StringIO(""), source_file="sup.csv") == ([], [])
    assert parse_suppliers(io.StringIO("  \n\t\n"), source_file="sup.csv") == ([], [])
    assert parse_suppliers(io.BytesIO(b""), source_file="sup.csv") == ([], [])


def test_parse_suppliers_header_only_returns_empty() -> None:
    assert parse_suppliers(_csv(HEADER), source_file="sup.csv") == ([], [])


def test_parse_suppliers_missing_name_or_tax_id_quarantined() -> None:
    suppliers, quarantined = parse_suppliers(
        _csv(HEADER, ",B00000001,", "Rossi Forniture,,", "Dupont Services,B00000002,"),
        source_file="sup.csv",
    )
    assert [s.source_row for s in suppliers] == [2]
    assert [q["reason"] for q in quarantined] == [
        "missing_field:supplier_name",
        "missing_field:tax_id",
    ]
    assert [q["source_row"] for q in quarantined] == [0, 1]
    assert all({"source_file", "source_row", "reason", "raw"} <= q.keys() for q in quarantined)


def test_parse_suppliers_iban_optional_and_verbatim() -> None:
    no_iban_column = "supplier_name,tax_id"
    suppliers, quarantined = parse_suppliers(
        _csv(no_iban_column, "Rossi Forniture,B00000001"), source_file="sup.csv"
    )
    assert quarantined == []
    assert suppliers[0].iban is None

    suppliers, quarantined = parse_suppliers(
        _csv(HEADER, f"Rossi Forniture,B00000001,{IBAN}", "Dupont Services,B00000002,   "),
        source_file="sup.csv",
    )
    assert quarantined == []
    assert suppliers[0].iban == IBAN
    assert suppliers[1].iban is None


def test_parse_suppliers_undecodable_file_quarantined() -> None:
    raw = b"supplier_name,tax_id\n\x81\x8d\x8f,B00000001\n"
    suppliers, quarantined = parse_suppliers(io.BytesIO(raw), source_file="sup.csv")
    assert suppliers == []
    assert len(quarantined) == 1
    assert quarantined[0]["reason"] == "undecodable_file"
    assert quarantined[0]["encoding_tried"] == ["utf-8-sig", "cp1252"]


def test_parse_suppliers_cp1252_and_bom_decoded() -> None:
    text = "\n".join([HEADER, "Ana García Consulting,B00000003,"]) + "\n"
    for raw in (b"\xef\xbb\xbf" + text.encode("utf-8"), text.encode("cp1252")):
        suppliers, quarantined = parse_suppliers(io.BytesIO(raw), source_file="sup.csv")
        assert quarantined == []
        assert suppliers[0].supplier_name == "Ana García Consulting"


def test_parse_suppliers_tax_id_and_iban_not_normalised() -> None:
    row = f"Rossi Forniture, b-0000001 ,{IBAN}"
    suppliers, _ = parse_suppliers(_csv(HEADER, row), source_file="sup.csv")
    assert suppliers[0].tax_id == " b-0000001 "
    assert suppliers[0].iban == IBAN
