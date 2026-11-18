"""Tests for the format sniffer and the two routers (REQ-RF-01, REQ-RF-02)."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from facturae_builders import facturae_bytes, facturae_doc
from hypothesis import given, settings
from hypothesis import strategies as st
from n43_builders import closing_33, fixture_a_bytes, header_11

from ledger_kit.ingestion import sniffer
from ledger_kit.ingestion.sniffer import (
    FORMAT_KINDS,
    SNIFF_BYTES,
    format_label,
    read_bank_statement,
    read_invoices,
    sniff_format,
    unsupported_message,
)

BOM = b"\xef\xbb\xbf"
CSV_COMMA = b"date,amount,currency,counterparty,description,iban\n2026-01-02,-12.99,EUR,A,B,\n"
CSV_SEMICOLON = b"date;amount;currency;counterparty;description\n02/01/2026;-12,99;EUR;A;B\n"
STATEMENT_CSV = b"date,amount,currency,counterparty,description\n2026-01-02,-12.99,EUR,Acme,Tea\n"
INVOICE_HEADER = "invoice_number,supplier_name,supplier_tax_id,issue_date,base_amount,vat_rate,"
INVOICE_ROW = "INV-001,Rossi Forniture,B00000001,2026-01-15,1000.00,21,210.00,1210.00,EUR"
INVOICE_CSV = f"{INVOICE_HEADER}vat_amount,total,currency\n{INVOICE_ROW}\n".encode()
INVOICE_JSON = json.dumps(
    [
        {
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
    ]
).encode("utf-8")
N43_HEADER = header_11().rstrip(" ").encode("latin-1")
FACTURAE_HEAD = (
    b'<?xml version="1.0" encoding="UTF-8"?>\n'
    b'<fe:Facturae xmlns:fe="http://www.facturae.gob.es/formato/Versiones/Facturaev3_2_2.xml">'
)
BANK = "CSV or Norma 43"
INVOICES = "CSV, JSON or Facturae"


@pytest.mark.parametrize(
    ("data", "kind"),
    [
        pytest.param(CSV_COMMA, "csv", id="csv-comma"),
        pytest.param(CSV_SEMICOLON, "csv", id="csv-semicolon"),
        pytest.param(b"\n\r\n  \n" + CSV_COMMA, "csv", id="csv-after-blank-lines"),
        pytest.param(BOM + CSV_COMMA, "csv", id="csv-with-bom"),
        pytest.param(b'[\n  {"invoice_number": "A-1"}\n]', "json", id="json-array"),
        pytest.param(b'{"a": 1}', "json", id="json-object"),
        pytest.param(b'\n\n   [{"a": 1}]', "json", id="json-after-blank-lines"),
        pytest.param(BOM + b'[{"a": 1}]', "json", id="json-with-bom"),
        pytest.param(N43_HEADER, "norma43", id="norma43-header"),
        pytest.param(fixture_a_bytes(), "norma43", id="norma43-file"),
        pytest.param(fixture_a_bytes(eol="\r\n"), "norma43", id="norma43-crlf"),
        pytest.param(b"\r\n\r\n" + fixture_a_bytes(), "norma43", id="norma43-after-blank-lines"),
        pytest.param(BOM + fixture_a_bytes(), "norma43", id="norma43-with-bom"),
        pytest.param(b"11,2026-01-02,12.99,EUR,A,B\n", "csv", id="csv-line-starting-11"),
        pytest.param(b"11" + b"9" * 17, "unknown", id="norma43-needs-18-digits"),
        pytest.param(BOM + FACTURAE_HEAD, "facturae", id="facturae-bom-prefixed"),
        pytest.param(FACTURAE_HEAD, "facturae", id="facturae-prefixed"),
        pytest.param(b"<Facturae xmlns='urn:x'/>", "facturae", id="facturae-unprefixed"),
        pytest.param(b"\n\n  <Facturae/>", "facturae", id="facturae-after-blank-lines"),
        pytest.param(
            b"<?xml version='1.0'?><!-- c --><fe:Facturae/>", "facturae", id="after-comment"
        ),
        pytest.param(b"<!DOCTYPE x SYSTEM 'x.dtd'><Facturae/>", "facturae", id="after-doctype"),
        pytest.param(b'<?xml version="1.0"?><Invoice/>', "unknown", id="other-xml"),
        pytest.param(b"<facturae/>", "unknown", id="root-name-is-case-sensitive"),
        pytest.param(b"<FacturaeX/>", "unknown", id="root-name-must-match-exactly"),
        pytest.param(b'<?xml version="1.0"?>', "unknown", id="declaration-only"),
        pytest.param(b"<html><body>hello</body></html>", "unknown", id="html"),
        pytest.param(b"%PDF-1.7", "unknown", id="pdf"),
        pytest.param(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj", "unknown", id="pdf-body"),
        pytest.param(b"just some words", "unknown", id="plain-text"),
        pytest.param(b"", "empty", id="no-bytes"),
        pytest.param(b" \r\n\t", "empty", id="whitespace-only"),
        pytest.param(BOM, "empty", id="bom-only"),
        pytest.param(BOM + b" \n", "empty", id="bom-and-blanks"),
    ],
)
def test_sniff_format_examples(data: bytes, kind: str) -> None:
    """The examples of REQ-RF-01 and their neighbours route to the expected kind."""
    assert sniff_format(data) == kind


def test_the_six_kinds_are_pinned() -> None:
    """The sniffer returns one of exactly six kinds."""
    assert set(FORMAT_KINDS) == {"csv", "json", "norma43", "facturae", "empty", "unknown"}


def test_only_the_first_4096_bytes_are_read() -> None:
    """A comma after the first 4096 bytes does not make a CSV."""
    assert sniff_format(b"x" * SNIFF_BYTES + b",") == "unknown"
    assert sniff_format(b"x" * (SNIFF_BYTES - 1) + b",") == "csv"


def test_a_bytearray_is_sniffed_like_bytes() -> None:
    """Any bytes-like object works; the result is the same as for bytes."""
    assert sniff_format(bytearray(CSV_COMMA)) == "csv"


@settings(max_examples=200, deadline=None)
@given(data=st.binary())
def test_sniff_format_never_raises_and_returns_a_known_kind(data: bytes) -> None:
    """Arbitrary bytes always give one of the six kinds."""
    assert sniff_format(data) in FORMAT_KINDS


@settings(max_examples=200, deadline=None)
@given(data=st.binary())
def test_sniff_format_depends_on_the_first_4096_bytes_only(data: bytes) -> None:
    """Cutting the input at 4096 bytes does not change the answer."""
    assert sniff_format(data) == sniff_format(data[:SNIFF_BYTES])


@settings(max_examples=200, deadline=None)
@given(data=st.binary(max_size=3000))
def test_empty_means_nothing_but_whitespace(data: bytes) -> None:
    """`empty` is returned exactly when the input has no non-whitespace byte after the BOM."""
    blank = data.removeprefix(BOM).strip() == b""

    assert (sniff_format(data) == "empty") is blank


# --- routers ---------------------------------------------------------------------------------


def test_bank_box_refuses_facturae_with_the_exact_record() -> None:
    """A Facturae in the bank-statement box gives the record and message of REQ-RF-02."""
    data = facturae_bytes()

    transactions, quarantine = read_bank_statement(io.BytesIO(data), source_file="a.xml")

    assert transactions == []
    assert quarantine == [
        {
            "source_file": "a.xml",
            "source_row": None,
            "source_line": None,
            "reason": "unsupported_format:facturae",
            "raw": "a.xml: this looks like Facturae XML; this box accepts CSV or Norma 43.",
        }
    ]


def test_invoice_box_refuses_a_pdf_with_the_exact_record() -> None:
    """A PDF in the invoices box is `unsupported_format:unknown`."""
    invoices, quarantine = read_invoices(io.BytesIO(b"%PDF-1.7 ..."), source_file="f.pdf")
    message = "f.pdf: the format is not recognised; this box accepts CSV, JSON or Facturae."

    assert invoices == []
    assert quarantine == [
        {
            "source_file": "f.pdf",
            "source_row": None,
            "source_line": None,
            "reason": "unsupported_format:unknown",
            "raw": message,
        }
    ]


@pytest.mark.parametrize(
    ("reader", "data", "kind", "text", "accepted"),
    [
        pytest.param(
            read_bank_statement, INVOICE_JSON, "json", "this looks like JSON", BANK, id="bank-json"
        ),
        pytest.param(
            read_bank_statement,
            b"<Facturae/>",
            "facturae",
            "this looks like Facturae XML",
            BANK,
            id="bank-facturae",
        ),
        pytest.param(
            read_bank_statement,
            b"%PDF-1.7",
            "unknown",
            "the format is not recognised",
            BANK,
            id="bank-unknown",
        ),
        pytest.param(
            read_invoices,
            fixture_a_bytes(),
            "norma43",
            "this looks like Norma 43",
            INVOICES,
            id="invoices-norma43",
        ),
        pytest.param(
            read_invoices,
            b"just some words",
            "unknown",
            "the format is not recognised",
            INVOICES,
            id="invoices-unknown",
        ),
    ],
)
def test_unsupported_messages_are_exact(
    reader, data: bytes, kind: str, text: str, accepted: str
) -> None:
    """Each refused kind gets its own wording and the list of what the box accepts."""
    accepted_rows, quarantine = reader(io.BytesIO(data), source_file="x.dat")

    assert accepted_rows == []
    assert quarantine == [
        {
            "source_file": "x.dat",
            "source_row": None,
            "source_line": None,
            "reason": f"unsupported_format:{kind}",
            "raw": f"x.dat: {text}; this box accepts {accepted}.",
        }
    ]


def test_unsupported_message_builds_the_documented_text() -> None:
    """The message helper is the single source of the wording."""
    message = unsupported_message("m.pdf", "unknown", "CSV or Norma 43")

    assert message == "m.pdf: the format is not recognised; this box accepts CSV or Norma 43."


def test_format_label_names_the_four_readable_kinds_only() -> None:
    """The pages name a detected format with these labels; empty and unknown have none."""
    assert [format_label(k) for k in ("csv", "json", "norma43", "facturae")] == [
        "CSV",
        "JSON",
        "Norma 43",
        "Facturae XML",
    ]
    assert format_label("empty") is None and format_label("unknown") is None
    assert format_label(sniffer.sniff_format(fixture_a_bytes())) == "Norma 43"


def _forbid_readers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every reader the sniffer module can call fail the test when it is called."""

    def boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("a reader was called")

    for name in ("parse_csv", "parse_norma43", "parse_invoice", "parse_facturae"):
        monkeypatch.setattr(sniffer, name, boom)


def test_a_refused_file_calls_no_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the kind is not accepted, none of the four readers is called."""
    _forbid_readers(monkeypatch)

    assert read_bank_statement(io.BytesIO(facturae_bytes()), source_file="a.xml")[1]
    assert read_bank_statement(io.BytesIO(INVOICE_JSON), source_file="a.json")[1]
    assert read_invoices(io.BytesIO(fixture_a_bytes()), source_file="a.n43")[1]
    assert read_invoices(io.BytesIO(b"%PDF-1.7"), source_file="a.pdf")[1]


def test_an_empty_file_calls_no_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty file is `([], [])` and no reader is called."""
    _forbid_readers(monkeypatch)

    for data in (b"", b"  \r\n\t ", BOM):
        assert read_bank_statement(io.BytesIO(data), source_file="e.csv") == ([], [])
        assert read_invoices(io.BytesIO(data), source_file="e.csv") == ([], [])


def test_bank_box_reads_a_norma43_file_named_csv() -> None:
    """The content decides: a Norma 43 named `.csv` is read as Norma 43."""
    transactions, quarantine = read_bank_statement(
        io.BytesIO(fixture_a_bytes()), source_file="acct.csv"
    )

    assert quarantine == []
    assert [t.source_ref for t in transactions] == ["acct.csv:2", "acct.csv:5"]
    assert [str(t.amount) for t in transactions] == ["12.99", "2450.00"]


def test_bank_box_reads_a_csv_statement() -> None:
    """A CSV statement still goes through the CSV reader, with 0-based rows."""
    transactions, quarantine = read_bank_statement(io.BytesIO(STATEMENT_CSV), source_file="s.txt")

    assert quarantine == []
    assert [t.source_ref for t in transactions] == ["s.txt:0"]
    assert transactions[0].flow == "debit"
    assert str(transactions[0].amount) == "12.99"


def test_invoice_box_reads_json_named_txt() -> None:
    """The content decides: JSON invoices named `.txt` are read as JSON."""
    invoices, quarantine = read_invoices(io.BytesIO(INVOICE_JSON), source_file="data.txt")

    assert quarantine == []
    assert [i.source_ref for i in invoices] == ["data.txt:0"]
    assert invoices[0].invoice_number == "INV-001"


def test_invoice_box_reads_a_csv_named_json() -> None:
    """A CSV named `.json` is read as CSV: the extension rule is gone."""
    invoices, quarantine = read_invoices(io.BytesIO(INVOICE_CSV), source_file="odd.json")

    assert quarantine == []
    assert [i.source_ref for i in invoices] == ["odd.json:0"]


def test_invoice_box_reads_a_facturae() -> None:
    """A Facturae goes through the Facturae reader, with 1-based invoice positions."""
    invoices, quarantine = read_invoices(io.BytesIO(facturae_bytes()), source_file="aurora.xml")

    assert quarantine == []
    assert [i.source_ref for i in invoices] == ["aurora.xml:1"]
    assert invoices[0].invoice_number == "F-2026-0310"


def test_routers_accept_text_streams() -> None:
    """`str` content is encoded to UTF-8 first, then sniffed and read."""
    text = STATEMENT_CSV.decode("utf-8")

    transactions, _ = read_bank_statement(io.StringIO(text), source_file="s.csv")
    invoices, _ = read_invoices(io.StringIO(facturae_doc()), source_file="aurora.xml")

    assert [t.source_ref for t in transactions] == ["s.csv:0"]
    assert [i.source_ref for i in invoices] == ["aurora.xml:1"]


def test_routers_read_a_path_and_name_rows_after_its_file(tmp_path: Path) -> None:
    """A path whose extension means nothing is sniffed; rows carry the file's own name."""
    path = tmp_path / "statement.dat"
    path.write_bytes(fixture_a_bytes())

    transactions, quarantine = read_bank_statement(path)

    assert quarantine == []
    assert [t.source_ref for t in transactions] == ["statement.dat:2", "statement.dat:5"]


def test_a_tampered_norma43_is_quarantined_through_the_router() -> None:
    """The router returns the reader's control-check record: no transaction, one record."""
    data = fixture_a_bytes(trailer=closing_33(debit_count=2))

    transactions, quarantine = read_bank_statement(io.BytesIO(data), source_file="acct.n43")

    assert transactions == []
    assert [record["reason"] for record in quarantine] == ["control_check_failed:debit_count"]


@settings(max_examples=200, deadline=None)
@given(data=st.binary())
def test_routers_never_raise_on_arbitrary_bytes(data: bytes) -> None:
    """Whatever the bytes, both routers return two lists."""
    for reader in (read_bank_statement, read_invoices):
        accepted, quarantined = reader(io.BytesIO(data), source_file="x.bin")

        assert isinstance(accepted, list)
        assert isinstance(quarantined, list)
