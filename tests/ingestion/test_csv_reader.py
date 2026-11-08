"""Tests for ledger_kit.ingestion.csv_reader (plain + European dialects, encodings)."""

import io
from datetime import date
from decimal import Decimal
from pathlib import Path

from ledger_kit.ingestion.csv_reader import parse_csv

PLAIN_HEADER = "date,amount,currency,counterparty,description"
EURO_HEADER = "date;amount;currency;counterparty;description"
SOURCE = "stmt.csv"
IBAN = " es88 2100 0418 5602 0005 1332"


def _text(header: str, *rows: str) -> str:
    """Join a header and rows into CSV text."""
    return "\n".join([header, *rows]) + "\n"


def _plain(*rows: str) -> io.StringIO:
    """Plain-dialect text stream."""
    return io.StringIO(_text(PLAIN_HEADER, *rows))


def _euro(*rows: str) -> io.StringIO:
    """European-dialect text stream."""
    return io.StringIO(_text(EURO_HEADER, *rows))


ROW_A = "2026-01-15,-12.99,EUR,Ana García,Streaming plan"
ROW_B = "2026-01-16,50.00,EUR,Luigi Rossi,Refund"
ROW_C = "2026-01-17,-7.50,EUR,Sophie Dupont,Coffee"


# --- Task 6: plain dialect + encoding -------------------------------------------------


def test_parse_csv_plain_valid() -> None:
    txs, quarantined = parse_csv(_plain(ROW_A, ROW_B, ROW_C), source_file=SOURCE)
    assert len(txs) == 3
    assert quarantined == []


def test_parse_csv_empty_file_returns_empty() -> None:
    assert parse_csv(io.StringIO(""), source_file=SOURCE) == ([], [])


def test_parse_csv_whitespace_only_file_returns_empty() -> None:
    assert parse_csv(io.StringIO("  \n\n\t\n"), source_file=SOURCE) == ([], [])


def test_parse_csv_empty_bytes_stream_returns_empty() -> None:
    assert parse_csv(io.BytesIO(b""), source_file=SOURCE) == ([], [])


def test_parse_csv_single_row_plain() -> None:
    txs, quarantined = parse_csv(_plain(ROW_A), source_file=SOURCE)
    assert len(txs) == 1
    assert quarantined == []
    assert txs[0].counterparty == "Ana García"
    assert txs[0].description == "Streaming plan"
    assert txs[0].currency == "EUR"


def test_parse_csv_header_only_returns_empty() -> None:
    assert parse_csv(_plain(), source_file=SOURCE) == ([], [])


def test_parse_csv_source_ref_assigned() -> None:
    txs, _ = parse_csv(_plain(ROW_A, ROW_B, ROW_C), source_file=SOURCE)
    for index, tx in enumerate(txs):
        assert tx.source_ref == f"{SOURCE}:{index}"
        assert tx.source_file == SOURCE


def test_parse_csv_source_row_zero_based() -> None:
    txs, _ = parse_csv(_plain(ROW_A, ROW_B), source_file=SOURCE)
    assert [t.source_row for t in txs] == [0, 1]


def test_parse_csv_source_file_defaults_to_path_name(tmp_path: Path) -> None:
    path = tmp_path / "bank_march.csv"
    path.write_text(_text(PLAIN_HEADER, ROW_A), encoding="utf-8")
    txs, _ = parse_csv(path)
    assert txs[0].source_ref == "bank_march.csv:0"
    txs_str, _ = parse_csv(str(path))
    assert txs_str[0].source_ref == "bank_march.csv:0"


def test_parse_csv_amount_is_decimal() -> None:
    txs, _ = parse_csv(_plain(ROW_A), source_file=SOURCE)
    assert isinstance(txs[0].amount, Decimal)
    assert txs[0].amount == Decimal("12.99")


def test_parse_csv_date_is_date() -> None:
    txs, _ = parse_csv(_plain(ROW_A), source_file=SOURCE)
    assert type(txs[0].date) is date
    assert txs[0].date == date(2026, 1, 15)


def test_parse_csv_negative_amount_becomes_debit() -> None:
    txs, _ = parse_csv(_plain("2026-01-15,-100.00,EUR,Ana García,Rent"), source_file=SOURCE)
    assert txs[0].flow == "debit"
    assert txs[0].amount == Decimal("100.00")


def test_parse_csv_positive_amount_becomes_credit() -> None:
    txs, _ = parse_csv(_plain("2026-01-15,50.00,EUR,Ana García,Refund"), source_file=SOURCE)
    assert txs[0].flow == "credit"
    assert txs[0].amount == Decimal("50.00")


def test_parse_csv_zero_amount_becomes_credit() -> None:
    txs, _ = parse_csv(_plain("2026-01-15,0.00,EUR,Ana García,Zero"), source_file=SOURCE)
    assert txs[0].flow == "credit"
    assert txs[0].amount == Decimal("0.00")


def test_parse_csv_missing_field_quarantined() -> None:
    txs, quarantined = parse_csv(_plain("2026-01-15,,EUR,Ana García,No amount"), source_file=SOURCE)
    assert txs == []
    assert len(quarantined) == 1
    assert "missing_field" in quarantined[0]["reason"]
    assert quarantined[0]["reason"] == "missing_field:amount"


def test_parse_csv_missing_column_quarantines_every_row() -> None:
    text = "date,amount,currency,counterparty\n2026-01-15,-1.00,EUR,Ana García\n"
    txs, quarantined = parse_csv(io.StringIO(text), source_file=SOURCE)
    assert txs == []
    assert [q["reason"] for q in quarantined] == ["missing_field:description"]


def test_parse_csv_unparseable_date_quarantined() -> None:
    _, quarantined = parse_csv(
        _plain("not-a-date,-1.00,EUR,Ana García,Bad date"), source_file=SOURCE
    )
    assert [q["reason"] for q in quarantined] == ["unparseable_date"]


def test_parse_csv_unparseable_amount_quarantined() -> None:
    _, quarantined = parse_csv(
        _plain("2026-01-15,abc,EUR,Ana García,Bad amount"), source_file=SOURCE
    )
    assert [q["reason"] for q in quarantined] == ["unparseable_amount"]


def test_parse_csv_non_finite_amount_quarantined() -> None:
    _, quarantined = parse_csv(_plain("2026-01-15,NaN,EUR,Ana García,NaN"), source_file=SOURCE)
    assert [q["reason"] for q in quarantined] == ["unparseable_amount"]


def test_parse_csv_quarantine_record_keys() -> None:
    _, quarantined = parse_csv(_plain("2026-01-15,abc,EUR,Ana García,Bad"), source_file=SOURCE)
    record = quarantined[0]
    assert {"source_file", "source_row", "reason", "raw"} <= set(record)
    assert record["source_file"] == SOURCE
    assert record["source_row"] == 0
    assert record["raw"]["amount"] == "abc"


def test_parse_csv_valid_rows_returned_alongside_quarantine() -> None:
    txs, quarantined = parse_csv(
        _plain(ROW_A, "2026-01-16,abc,EUR,Luigi Rossi,Bad", ROW_C), source_file=SOURCE
    )
    assert len(txs) == 2
    assert len(quarantined) == 1
    assert quarantined[0]["source_row"] == 1
    assert [t.source_row for t in txs] == [0, 2]


def test_parse_csv_utf8_bom_decoded() -> None:
    data = b"\xef\xbb\xbf" + _text(PLAIN_HEADER, ROW_A).encode("utf-8")
    txs, quarantined = parse_csv(io.BytesIO(data), source_file=SOURCE)
    assert quarantined == []
    assert len(txs) == 1
    assert txs[0].date == date(2026, 1, 15)
    assert txs[0].counterparty == "Ana García"


def test_parse_csv_cp1252_decoded() -> None:
    data = _text(PLAIN_HEADER, "2026-01-15,-5.00,EUR,Ana García,Pago 5€").encode("cp1252")
    assert b"\x80" in data
    txs, quarantined = parse_csv(io.BytesIO(data), source_file=SOURCE)
    assert quarantined == []
    assert txs[0].description == "Pago 5€"
    assert txs[0].counterparty == "Ana García"


def test_parse_csv_undecodable_file_quarantined() -> None:
    data = PLAIN_HEADER.encode("ascii") + b"\n2026-01-15,-1.00,EUR,Ana,Bad \x81 byte\n"
    txs, quarantined = parse_csv(io.BytesIO(data), source_file=SOURCE)
    assert txs == []
    assert len(quarantined) == 1
    assert quarantined[0]["reason"] == "undecodable_file"
    assert quarantined[0]["encoding_tried"] == ["utf-8-sig", "cp1252"]
    assert quarantined[0]["source_row"] is None
    assert quarantined[0]["source_file"] == SOURCE


def test_parse_csv_iban_column_read_verbatim() -> None:
    text = _text(f"{PLAIN_HEADER},iban", f'2026-01-15,-1.00,EUR,Ana García,Fee,"{IBAN}"')
    txs, quarantined = parse_csv(io.StringIO(text), source_file=SOURCE)
    assert quarantined == []
    assert txs[0].iban == IBAN


def test_parse_csv_iban_column_absent_is_none() -> None:
    txs, quarantined = parse_csv(_plain(ROW_A), source_file=SOURCE)
    assert quarantined == []
    assert txs[0].iban is None


def test_parse_csv_iban_empty_or_blank_cell_is_none() -> None:
    text = _text(
        f"{PLAIN_HEADER},iban",
        "2026-01-15,-1.00,EUR,Ana García,Empty,",
        "2026-01-16,-2.00,EUR,Luigi Rossi,Blank,   ",
    )
    txs, quarantined = parse_csv(io.StringIO(text), source_file=SOURCE)
    assert quarantined == []
    assert [t.iban for t in txs] == [None, None]


def test_parse_csv_iban_column_european_dialect() -> None:
    text = _text(
        f"{EURO_HEADER};iban",
        f"15/01/2026;-1,00;EUR;Ana García;Fee;{IBAN}",
        "16/01/2026;-2,00;EUR;Luigi Rossi;Blank;  ",
        "17/01/2026;-3,00;EUR;Sophie Dupont;Empty;",
    )
    txs, quarantined = parse_csv(io.StringIO(text), source_file=SOURCE)
    assert quarantined == []
    assert [t.iban for t in txs] == [IBAN, None, None]


# --- Task 7: European dialect and auto-detection --------------------------------------


def test_parse_csv_single_row_european() -> None:
    txs, quarantined = parse_csv(
        _euro("15/01/2026;-12,99;EUR;Ana García;Streaming plan"), source_file=SOURCE
    )
    assert quarantined == []
    assert len(txs) == 1
    assert txs[0].amount == Decimal("12.99")
    assert txs[0].flow == "debit"
    assert txs[0].date == date(2026, 1, 15)
    assert txs[0].source_ref == f"{SOURCE}:0"


def test_parse_csv_european_thousands_separator() -> None:
    txs, _ = parse_csv(_euro("15/01/2026;1.234,56;EUR;Luigi Rossi;Salary"), source_file=SOURCE)
    assert txs[0].amount == Decimal("1234.56")
    assert txs[0].flow == "credit"


def test_parse_csv_european_negative_amount() -> None:
    txs, _ = parse_csv(_euro("15/01/2026;-12,50;EUR;Ana García;Lunch"), source_file=SOURCE)
    assert txs[0].flow == "debit"
    assert txs[0].amount == Decimal("12.50")


def test_parse_csv_european_date() -> None:
    txs, _ = parse_csv(_euro("31/12/2026;-1,00;EUR;Ana García;Year end"), source_file=SOURCE)
    assert txs[0].date == date(2026, 12, 31)


def test_parse_csv_european_iso_date_quarantined() -> None:
    _, quarantined = parse_csv(
        _euro("2026-12-31;-1,00;EUR;Ana García;Wrong date format"), source_file=SOURCE
    )
    assert [q["reason"] for q in quarantined] == ["unparseable_date"]


def test_parse_csv_ambiguous_dialect_quarantines_file() -> None:
    text = "date,amount;currency,counterparty;description\n2026-01-15,-1.00,EUR,Ana,Fee\n"
    txs, quarantined = parse_csv(io.StringIO(text), source_file=SOURCE)
    assert txs == []
    assert len(quarantined) == 1
    assert quarantined[0]["reason"] == "ambiguous_dialect"
    assert quarantined[0]["source_row"] is None
    assert quarantined[0]["source_file"] == SOURCE


def test_parse_csv_european_plain_decimal_amount_quarantined() -> None:
    txs, quarantined = parse_csv(
        _euro(
            "15/01/2026;12.50;EUR;Ana García;Plain decimal",
            "16/01/2026;1,234.56;EUR;Luigi Rossi;Anglo thousands",
        ),
        source_file=SOURCE,
    )
    assert txs == []
    assert [q["reason"] for q in quarantined] == ["unparseable_amount", "unparseable_amount"]
    assert [q["source_row"] for q in quarantined] == [0, 1]


def test_parse_csv_ambiguous_quarantine_includes_first_line() -> None:
    header = "date,amount;currency,counterparty;description"
    text = f"\n{header}\n2026-01-15,-1.00,EUR,Ana,Fee\n"
    _, quarantined = parse_csv(io.StringIO(text), source_file=SOURCE)
    assert quarantined[0]["first_line"] == header


def test_parse_csv_explicit_dialect_overrides_sniff() -> None:
    # This header is ambiguous for detect_dialect (both separators present); an explicit
    # dialect must bypass detection and parse with ';'.
    text = _text(
        f"{EURO_HEADER};note,x",
        "15/01/2026;-12,99;EUR;Ana García;Streaming plan;n/a",
    )
    auto_txs, auto_q = parse_csv(io.StringIO(text), source_file=SOURCE)
    assert auto_txs == []
    assert auto_q[0]["reason"] == "ambiguous_dialect"

    txs, quarantined = parse_csv(io.StringIO(text), dialect="european", source_file=SOURCE)
    assert quarantined == []
    assert len(txs) == 1
    assert txs[0].amount == Decimal("12.99")


def test_parse_csv_auto_detect_plain() -> None:
    txs, quarantined = parse_csv(_plain(ROW_A), source_file=SOURCE)
    assert quarantined == []
    assert txs[0].date == date(2026, 1, 15)
    assert txs[0].amount == Decimal("12.99")


def test_parse_csv_auto_detect_european() -> None:
    txs, quarantined = parse_csv(
        _euro("15/01/2026;-12,99;EUR;Ana García;Streaming plan"), source_file=SOURCE
    )
    assert quarantined == []
    assert txs[0].date == date(2026, 1, 15)
    assert txs[0].amount == Decimal("12.99")


def test_parse_csv_european_bytes_cp1252() -> None:
    data = _text(EURO_HEADER, "15/01/2026;-5,00;EUR;Sophie Dupont;Café 5€").encode("cp1252")
    txs, quarantined = parse_csv(io.BytesIO(data), source_file=SOURCE)
    assert quarantined == []
    assert txs[0].description == "Café 5€"
