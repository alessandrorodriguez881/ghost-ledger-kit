"""Tests of source_line (spec ledger-core, REQ-LN-01 to REQ-LN-11).

`source_line` is the 1-based line of the file where a record starts, the header being line 1, as a
text editor numbers lines. `source_row` and `source_ref` stay the internal key. The sample files
are read as text and the line at each `source_line` is compared with the record it belongs to.
All data is synthetic.
"""

import csv
import io
import json
from decimal import Decimal
from pathlib import Path

import pytest

from ledger_kit.ingestion.csv_reader import iter_csv_records, parse_csv
from ledger_kit.ingestion.dialect import CsvDialect, detect_dialect, parse_amount, parse_date
from ledger_kit.ingestion.facturae_reader import parse_facturae
from ledger_kit.ingestion.invoice_reader import parse_invoice
from ledger_kit.ingestion.norma43_reader import parse_norma43
from ledger_kit.ingestion.sniffer import read_bank_statement
from ledger_kit.ingestion.supplier_reader import parse_suppliers
from ledger_kit.models import Invoice, Supplier, Transaction

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "data" / "samples"
PHANTOM = SAMPLES / "phantom_demo"
ZOMBIE_CSV = SAMPLES / "zombie_demo_statement.csv"
ZOMBIE_N43 = SAMPLES / "zombie_demo_statement.n43"
SAMPLE_CSVS = sorted([*SAMPLES.glob("*.csv"), *PHANTOM.glob("*.csv")])

HEADER = "date,amount,currency,counterparty,description"
AMBIGUOUS_HEADER = "date,amount;currency,counterparty;description"
INVOICE_HEADER = (
    "invoice_number,supplier_name,supplier_tax_id,issue_date,due_date,base_amount,vat_rate,"
    "vat_amount,total,currency"
)
INVOICE_TAIL = "2026-01-15,2026-02-14,100.00,21,21.00,121.00,EUR"
SUPPLIER_HEADER = "supplier_name,tax_id,iban"


def _text_of(path: Path) -> str:
    """Read a sample file as text, UTF-8 first and Windows-1252 second, like the readers."""
    data = path.read_bytes()
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252")


def _lines_of(text: str) -> list[str]:
    """Split text the way a text editor numbers lines: index 0 is line 1."""
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def _record_at(lines: list[str], line: int, header: list[str], delimiter: str) -> dict[str, str]:
    """Read the physical line number `line` of a file as one CSV record keyed by its header."""
    cells = next(csv.reader([lines[line - 1]], delimiter=delimiter))
    return dict(zip(header, cells, strict=False))


# --- the models ---------------------------------------------------------------------------------


def test_the_three_models_have_an_optional_source_line_that_defaults_to_none() -> None:
    transaction = Transaction(
        date="2026-01-15",
        amount=Decimal("1.00"),
        flow="debit",
        currency="EUR",
        counterparty="Ana García",
        description="x",
        source_file="a.csv",
        source_row=0,
        source_ref="a.csv:0",
    )
    supplier = Supplier(
        supplier_name="Dupont Services",
        tax_id="B00000002",
        source_file="s.csv",
        source_row=0,
        source_ref="s.csv:0",
    )

    assert transaction.source_line is None and supplier.source_line is None
    assert Transaction.model_fields["source_line"].annotation == (int | None)
    assert Invoice.model_fields["source_line"].default is None
    assert Supplier.model_fields["source_line"].default is None


# --- the CSV readers: blank lines and quoted cells that span lines -------------------------------


def test_a_blank_line_between_records_gives_the_line_where_the_record_starts() -> None:
    text = f"{HEADER}\n2026-01-15,-1.00,EUR,Ana,A\n\n\n2026-01-16,-2.00,EUR,Luigi,B\n"

    transactions, quarantined = parse_csv(io.StringIO(text), source_file="b.csv")

    assert quarantined == []
    assert [(t.source_row, t.source_line) for t in transactions] == [(0, 2), (1, 5)]
    assert [t.source_ref for t in transactions] == ["b.csv:0", "b.csv:1"]  # the key is unchanged
    assert _lines_of(text)[4].startswith("2026-01-16")


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_a_quoted_cell_that_spans_two_lines_gives_the_start_line_and_moves_the_next(
    newline: str,
) -> None:
    rows = [
        HEADER,
        '2026-01-15,-1.00,EUR,Ana,"first line',
        'second line"',
        "2026-01-16,-2.00,EUR,Luigi,B",
    ]
    text = newline.join(rows) + newline

    transactions, quarantined = parse_csv(io.StringIO(text), source_file="m.csv")

    assert quarantined == []
    assert [(t.source_row, t.source_line) for t in transactions] == [(0, 2), (1, 4)]
    lines = _lines_of(text)
    assert lines[2] == 'second line"' and lines[3].startswith("2026-01-16")


def test_a_bad_record_after_blank_lines_and_a_multiline_cell_carries_its_start_line() -> None:
    text = (
        f"{HEADER}\n"
        '2026-01-15,-1.00,EUR,Ana,"one\ntwo"\n'
        "\n"
        "not-a-date,-2.00,EUR,Luigi,Bad date\n"
        "2026-01-17,,EUR,Sophie,No amount\n"
    )

    transactions, quarantined = parse_csv(io.StringIO(text), source_file="q.csv")

    assert [t.source_line for t in transactions] == [2]
    assert [(q["reason"], q["source_row"], q["source_line"]) for q in quarantined] == [
        ("unparseable_date", 1, 5),
        ("missing_field:amount", 2, 6),
    ]


def test_iter_csv_records_reads_records_as_csv_dictreader_does() -> None:
    text = "a,b\n1,2,3\n4\n\n5,6\n"

    found = list(iter_csv_records(text, ","))
    expected = list(csv.DictReader(io.StringIO(text, newline="")))

    assert [row for _index, _line, row in found] == expected
    assert [(index, line) for index, line, _row in found] == [(0, 2), (1, 3), (2, 5)]
    assert list(iter_csv_records("", ",")) == []
    assert list(iter_csv_records("a,b\n", ",")) == []


def test_invoices_get_the_start_line_and_a_bad_one_keeps_it_in_quarantine() -> None:
    text = (
        f"{INVOICE_HEADER}\n"
        "\n"
        f"F-1,Rossi Forniture,B00000001,{INVOICE_TAIL}\n"
        f'F-2,"Rossi\nForniture",B00000001,{INVOICE_TAIL}\n'
        f"F-3,Rossi Forniture,B00000001,{INVOICE_TAIL}\n"
        f",Rossi Forniture,B00000001,{INVOICE_TAIL}\n"
    )

    found, quarantined = parse_invoice(io.StringIO(text), source_file="i.csv")

    assert [(i.source_row, i.source_line) for i in found] == [(0, 3), (1, 4), (2, 6)]
    assert [(q["reason"], q["source_line"]) for q in quarantined] == [
        ("missing_field:invoice_number", 7)
    ]


def test_suppliers_get_the_start_line_and_a_bad_one_keeps_it_in_quarantine() -> None:
    text = f"{SUPPLIER_HEADER}\n\nDupont Services,B00000002,\n,B00000003,\nRossi,B00000001,\n"

    found, quarantined = parse_suppliers(io.StringIO(text), source_file="s.csv")

    assert [(s.source_row, s.source_line) for s in found] == [(0, 3), (2, 5)]
    assert [(q["reason"], q["source_row"], q["source_line"]) for q in quarantined] == [
        ("missing_field:supplier_name", 1, 4)
    ]


def test_a_json_invoice_has_a_position_and_no_line() -> None:
    item = {
        "invoice_number": "F-1",
        "supplier_name": "Rossi Forniture",
        "supplier_tax_id": "B00000001",
        "issue_date": "2026-01-15",
        "base_amount": "100.00",
        "vat_rate": "21",
        "vat_amount": "21.00",
        "total": "121.00",
        "currency": "EUR",
    }
    document = json.dumps([item, {**item, "total": ""}, 7], indent=2)

    found, quarantined = parse_invoice(io.StringIO(document), fmt="json", source_file="i.json")

    assert [i.source_line for i in found] == [None]
    assert len(quarantined) == 2
    assert all("source_line" in q and q["source_line"] is None for q in quarantined)


# --- the quarantine records of the whole file ----------------------------------------------------


def test_a_quarantine_record_about_a_whole_file_has_a_source_line_key_that_is_none() -> None:
    bad_csv = HEADER.encode() + b"\n2026-01-15,-1,EUR,A,Bad \x81\n"
    bad_invoices = INVOICE_HEADER.encode() + b"\nx,\x81\n"
    ambiguous = f"{AMBIGUOUS_HEADER}\n2026-01-15,-1.00,EUR,Ana,Fee\n"
    records = [
        *parse_csv(io.BytesIO(bad_csv), source_file="a.csv")[1],
        *parse_csv(io.StringIO(ambiguous), source_file="b.csv")[1],
        *read_bank_statement(io.BytesIO(b'{"a": 1}'), source_file="c.json")[1],
        *parse_facturae(io.BytesIO(b"<not xml"), source_file="d.xml")[1],
        *parse_invoice(io.StringIO("[1,"), fmt="json", source_file="e.json")[1],
        *parse_invoice(io.BytesIO(bad_invoices), source_file="f.csv")[1],
        *parse_suppliers(io.BytesIO(b"a,b\n\x81,\x81\n"), source_file="g.csv")[1],
    ]

    assert len(records) == 7
    for record in records:
        assert "source_line" in record and record["source_line"] is None, record["reason"]


# --- every sample CSV: the line of the file is the record ----------------------------------------


def test_the_gymplus_charge_keeps_its_internal_key_and_gets_line_183() -> None:
    transactions, quarantined = parse_csv(ZOMBIE_CSV)
    assert quarantined == []

    [charge] = [
        t
        for t in transactions
        if "GYMPLUS" in f"{t.counterparty} {t.description}".upper()
        and t.date.isoformat() == "2026-08-09"
    ]

    assert charge.source_ref == "zombie_demo_statement.csv:181"
    assert charge.source_row == 181
    assert charge.source_line == 183
    lines = _lines_of(_text_of(ZOMBIE_CSV))
    assert "2026-08-09" in lines[183 - 1] and "GYMPLUS" in lines[183 - 1].upper()
    assert lines[181 - 1] != lines[183 - 1]  # line 181 is a different charge


def _kind_of(header_line: str) -> str:
    """Tell which reader a sample file needs from its header."""
    names = {cell.strip() for cell in header_line.replace(";", ",").split(",")}
    if "invoice_number" in names:
        return "invoice"
    if "tax_id" in names:
        return "supplier"
    return "statement"


def test_there_are_sample_csv_files_to_check() -> None:
    names = {path.name for path in SAMPLE_CSVS}

    assert {"zombie_demo_statement.csv", "vampire_demo_statement.csv", "invoices.csv"} <= names
    assert {"suppliers.csv", "payments.csv"} <= names


@pytest.mark.parametrize("path", SAMPLE_CSVS, ids=lambda path: path.name)
def test_every_record_of_a_sample_csv_has_the_line_of_the_file_that_holds_it(path: Path) -> None:
    lines = _lines_of(_text_of(path))
    kind = _kind_of(lines[0])
    if kind == "invoice":
        records, _ = parse_invoice(path)
    elif kind == "supplier":
        records, _ = parse_suppliers(path)
    else:
        records, _ = parse_csv(path)
    assert records, path.name

    european = kind == "statement" and detect_dialect(lines[0]) == CsvDialect.EUROPEAN
    delimiter = ";" if european else ","
    dialect = CsvDialect.EUROPEAN if european else CsvDialect.PLAIN
    header = next(csv.reader([lines[0]], delimiter=delimiter))
    seen: list[int] = []
    for record in records:
        assert record.source_line is not None, record.source_ref
        cells = _record_at(lines, record.source_line, header, delimiter)
        if kind == "statement":
            assert parse_date(cells["date"], dialect) == record.date, record.source_ref
            amount = abs(parse_amount(cells["amount"], dialect))
            assert amount == record.amount, record.source_ref
        elif kind == "invoice":
            assert parse_date(cells["issue_date"], dialect) == record.issue_date
            assert parse_amount(cells["total"], dialect) == record.total
        else:
            assert cells["supplier_name"] == record.supplier_name, record.source_ref
            assert cells["tax_id"] == record.tax_id, record.source_ref
        seen.append(record.source_line)
    assert seen == sorted(set(seen))  # one line per record, in file order
    assert all(2 <= line <= len(lines) for line in seen)  # the header is line 1


# --- Norma 43 and Facturae -----------------------------------------------------------------------


def test_norma43_source_line_equals_source_row_and_is_the_line_of_the_record_22() -> None:
    transactions, _ = parse_norma43(ZOMBIE_N43)
    lines = _lines_of(_text_of(ZOMBIE_N43))

    assert transactions
    for transaction in transactions:
        assert transaction.source_line == transaction.source_row
        assert lines[transaction.source_line - 1].startswith("22")


def test_norma43_quarantine_records_carry_the_line_of_the_record_or_none_for_the_file() -> None:
    lines = _lines_of(_text_of(ZOMBIE_N43))
    lines.insert(1, "99" + "X" * 10)  # an unknown record code on line 2

    transactions, quarantined = parse_norma43(io.StringIO("\n".join(lines)), source_file="n.n43")

    assert transactions == []  # the record count of the record 88 no longer matches
    by_reason = {q["reason"]: q for q in quarantined}
    unknown = by_reason["unknown_record_code:99"]
    assert (unknown["source_row"], unknown["source_line"]) == (2, 2)
    whole_file = by_reason["control_check_failed:record88_count"]
    assert whole_file["source_row"] is None and whole_file["source_line"] is None
    assert all("source_line" in q for q in quarantined)


def test_facturae_leaves_source_line_none_for_invoices_and_quarantine_records() -> None:
    files = sorted((PHANTOM / "facturae").glob("*.xml"))
    assert files

    found = [invoice for path in files for invoice in parse_facturae(path)[0]]

    assert found and all(isinstance(invoice, Invoice) for invoice in found)
    assert all(invoice.source_line is None for invoice in found)
    assert all(invoice.source_row >= 1 for invoice in found)  # a position, not a line
    _, quarantined = parse_facturae(io.BytesIO(b"<Facturae/>"), source_file="x.xml")
    assert quarantined and all(q["source_line"] is None for q in quarantined)
