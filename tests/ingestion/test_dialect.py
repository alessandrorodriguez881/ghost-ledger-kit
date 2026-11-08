"""Tests for ledger_kit.ingestion.dialect."""

from datetime import date
from decimal import Decimal, InvalidOperation

import pytest

from ledger_kit.ingestion.dialect import (
    CsvDialect,
    detect_dialect,
    parse_amount,
    parse_date,
)

D = Decimal


def test_detect_dialect_semicolon_only() -> None:
    assert detect_dialect("date;amount;currency") == CsvDialect.EUROPEAN


def test_detect_dialect_comma_only() -> None:
    assert detect_dialect("date,amount,currency") == CsvDialect.PLAIN


def test_detect_dialect_both_separators() -> None:
    assert detect_dialect("date;amount,currency") is None


def test_detect_dialect_empty_line() -> None:
    assert detect_dialect("") is None


def test_parse_amount_plain_positive() -> None:
    assert parse_amount("123.45", CsvDialect.PLAIN) == D("123.45")


def test_parse_amount_plain_negative() -> None:
    assert parse_amount("-99.00", CsvDialect.PLAIN) == D("-99.00")


def test_parse_amount_plain_invalid() -> None:
    with pytest.raises(InvalidOperation):
        parse_amount("abc", CsvDialect.PLAIN)


def test_parse_amount_european_with_thousands() -> None:
    assert parse_amount("1.234,56", CsvDialect.EUROPEAN) == D("1234.56")


def test_parse_amount_european_no_thousands() -> None:
    assert parse_amount("12,50", CsvDialect.EUROPEAN) == D("12.50")


def test_parse_amount_european_negative() -> None:
    assert parse_amount("-12,50", CsvDialect.EUROPEAN) == D("-12.50")


def test_parse_amount_european_invalid() -> None:
    with pytest.raises(InvalidOperation):
        parse_amount("1,2,3", CsvDialect.EUROPEAN)


def test_parse_amount_european_rejects_plain_decimal() -> None:
    with pytest.raises(InvalidOperation):
        parse_amount("12.50", CsvDialect.EUROPEAN)


def test_parse_amount_european_rejects_negative_plain_decimal() -> None:
    with pytest.raises(InvalidOperation):
        parse_amount("-12.5", CsvDialect.EUROPEAN)


def test_parse_amount_european_rejects_anglo_thousands() -> None:
    with pytest.raises(InvalidOperation):
        parse_amount("1,234.56", CsvDialect.EUROPEAN)


def test_parse_date_plain() -> None:
    assert parse_date("2026-12-31", CsvDialect.PLAIN) == date(2026, 12, 31)


def test_parse_date_european() -> None:
    assert parse_date("31/12/2026", CsvDialect.EUROPEAN) == date(2026, 12, 31)


def test_parse_date_plain_invalid() -> None:
    with pytest.raises(ValueError):
        parse_date("31/12/2026", CsvDialect.PLAIN)


def test_parse_date_european_invalid() -> None:
    with pytest.raises(ValueError):
        parse_date("2026-12-31", CsvDialect.EUROPEAN)
