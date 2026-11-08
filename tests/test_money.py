"""Tests for ledger_kit.utils.money."""

from decimal import ROUND_HALF_UP, Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ledger_kit.utils.money import (
    format_amount,
    format_as_european,
    net_total,
    percent_of,
    round_to_cents,
    within_tolerance,
)

D = Decimal


def test_round_to_cents_half_up() -> None:
    assert round_to_cents(D("2.345")) == D("2.35")


def test_round_to_cents_half_up_negative() -> None:
    assert round_to_cents(D("-2.345")) == D("-2.35")


def test_round_to_cents_already_exact() -> None:
    assert round_to_cents(D("1.23")) == D("1.23")


def test_format_amount_thousands() -> None:
    assert format_amount(D("1234567.89")) == "1.234.567,89 EUR"


def test_format_amount_no_thousands() -> None:
    assert format_amount(D("99.00")) == "99,00 EUR"


def test_format_amount_negative() -> None:
    assert format_amount(D("-12.50")) == "-12,50 EUR"


def test_format_amount_zero() -> None:
    assert format_amount(D("0")) == "0,00 EUR"


def test_format_amount_custom_currency() -> None:
    assert format_amount(D("5"), "USD") == "5,00 USD"


def test_format_as_european_no_currency_code() -> None:
    result = format_as_european(D("12.5"))
    assert " " not in result
    assert result == "12,50"


def test_format_as_european_thousands() -> None:
    assert format_as_european(D("1234.56")) == "1.234,56"


def test_format_as_european_negative() -> None:
    assert format_as_european(D("-12.50")) == "-12,50"


@pytest.mark.parametrize(
    ("rate", "expected"),
    [("21", "21.00"), ("10", "10.00"), ("4", "4.00"), ("0", "0.00")],
)
def test_percent_of_basic(rate: str, expected: str) -> None:
    assert percent_of(D("100.00"), D(rate)) == D(expected)


def test_percent_of_rounds_half_up() -> None:
    assert percent_of(D("0.50"), D("21")) == D("0.11")
    assert percent_of(D("1000.00"), D("21")) == D("210.00")


def test_percent_of_is_never_float() -> None:
    result = percent_of(D("19.99"), D("21"))
    assert isinstance(result, Decimal)
    assert result.as_tuple().exponent == -2


def test_within_tolerance_boundaries() -> None:
    tol = D("0.01")
    assert within_tolerance(D("10.00"), D("10.01"), tol) is True
    assert within_tolerance(D("10.00"), D("10.02"), tol) is False
    assert within_tolerance(D("10.01"), D("10.00"), tol) is True
    assert within_tolerance(D("10.02"), D("10.00"), tol) is False


def test_within_tolerance_negative_tol_raises() -> None:
    with pytest.raises(ValueError):
        within_tolerance(D("1"), D("1"), D("-0.01"))


def test_net_total() -> None:
    assert net_total([D("1000.00"), D("210.00")], [D("150.00")]) == D("1060.00")
    assert net_total([D("100.00"), D("21.00"), D("5.20")]) == D("126.20")
    assert net_total([]) == D("0")


@settings(max_examples=200)
@given(
    base=st.decimals(min_value=0, max_value=1_000_000, places=2),
    rate=st.sampled_from([D("21"), D("10"), D("4"), D("0")]),
)
def test_percent_of_matches_quantize(base: Decimal, rate: Decimal) -> None:
    expected = (base * rate / 100).quantize(D("0.01"), ROUND_HALF_UP)
    assert percent_of(base, rate) == expected
