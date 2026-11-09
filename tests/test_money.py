"""Tests for ledger_kit.utils.money."""

from decimal import ROUND_HALF_UP, Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ledger_kit.utils.money import (
    apply_sign,
    balance_after,
    decimal_from_implied,
    format_amount,
    format_as_european,
    implied_digits,
    net_total,
    percent_of,
    round_to_cents,
    sum_amounts,
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


# --- real-formats helpers (REQ-RF-30) ---


def test_sum_amounts_empty_is_zero() -> None:
    result = sum_amounts([])
    assert result == D("0")
    assert isinstance(result, Decimal)


def test_sum_amounts_is_exact_and_unrounded() -> None:
    assert sum_amounts([D("0.1"), D("0.2")]) == D("0.3")
    assert sum_amounts([D("1.005"), D("1.005")]) == D("2.010")


def test_sum_amounts_accepts_an_iterator() -> None:
    assert sum_amounts(iter([D("12.99"), D("2450.00")])) == D("2462.99")


@settings(max_examples=200)
@given(values=st.lists(st.decimals(min_value=0, max_value=1_000_000, places=2), max_size=20))
def test_sum_amounts_is_order_independent(values: list[Decimal]) -> None:
    assert sum_amounts(values) == sum_amounts(reversed(values))


def test_balance_after() -> None:
    assert balance_after(D("5000.00"), D("2450.00"), D("12.99")) == D("7437.01")
    assert balance_after(D("-5000.00"), D("2450.00"), D("12.99")) == D("-2562.99")
    assert balance_after(D("0"), D("0"), D("0")) == D("0")


def test_apply_sign() -> None:
    assert apply_sign(D("5000.00"), True) == D("-5000.00")
    assert apply_sign(D("5000.00"), False) == D("5000.00")
    assert apply_sign(D("0.00"), True) == D("0.00")


def test_decimal_from_implied_basic() -> None:
    assert decimal_from_implied("00000000001299") == D("12.99")
    assert decimal_from_implied("00000000245000") == D("2450.00")
    assert decimal_from_implied("00000000000000") == D("0.00")


def test_decimal_from_implied_short_strings() -> None:
    assert decimal_from_implied("0") == D("0")
    assert decimal_from_implied("5") == D("0.05")
    assert decimal_from_implied("123") == D("1.23")


def test_decimal_from_implied_is_exact_decimal() -> None:
    result = decimal_from_implied("00000000001299")
    assert isinstance(result, Decimal)
    assert result.as_tuple().exponent == -2


def test_decimal_from_implied_other_places() -> None:
    assert decimal_from_implied("1234", places=0) == D("1234")
    assert decimal_from_implied("1234", places=3) == D("1.234")


@pytest.mark.parametrize("bad", ["", "12A9", " 123", "12.9", "-123", "12 3", "²", "１２"])
def test_decimal_from_implied_rejects_non_digits(bad: str) -> None:
    with pytest.raises(ValueError):
        decimal_from_implied(bad)


def test_decimal_from_implied_rejects_negative_places() -> None:
    with pytest.raises(ValueError):
        decimal_from_implied("123", places=-1)


def test_implied_digits_basic() -> None:
    assert implied_digits(D("12.99")) == "00000000001299"
    assert implied_digits(D("2450.00")) == "00000000245000"
    assert implied_digits(D("0")) == "00000000000000"


def test_implied_digits_rounds_half_up() -> None:
    assert implied_digits(D("0.125")) == "00000000000013"
    assert implied_digits(D("0.124")) == "00000000000012"


def test_implied_digits_width() -> None:
    assert implied_digits(D("12.99"), width=5) == "01299"
    assert implied_digits(D("999.99"), width=5) == "99999"
    with pytest.raises(ValueError):
        implied_digits(D("1000.00"), width=5)


def test_implied_digits_widest_default() -> None:
    assert implied_digits(D("999999999999.99")) == "99999999999999"
    with pytest.raises(ValueError):
        implied_digits(D("1000000000000.00"))


def test_implied_digits_rejects_negative_and_non_finite() -> None:
    with pytest.raises(ValueError):
        implied_digits(D("-0.01"))
    with pytest.raises(ValueError):
        implied_digits(D("NaN"))
    with pytest.raises(ValueError):
        implied_digits(D("Infinity"))


def test_implied_digits_negative_that_rounds_to_zero_is_zero() -> None:
    assert implied_digits(D("-0.001")) == "00000000000000"


@settings(max_examples=200)
@given(x=st.decimals(min_value=0, max_value=999_999_999_999, places=4))
def test_implied_round_trip_equals_round_to_cents(x: Decimal) -> None:
    assert decimal_from_implied(implied_digits(x)) == round_to_cents(x)
