"""Tests for the typed readers and identifier keys of the phantom-invoices detectors (Task P3)."""

import re
from datetime import date, datetime
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from apps.phantom_invoices.detectors.utils import (
    DASH_CHARS,
    ZERO,
    as_bool,
    as_date,
    as_decimal,
    as_text,
    iban_key,
    is_missing,
    n1_key,
    n2_key,
    name_key,
    tax_key,
)
from apps.phantom_invoices.tests.pi_strategies import dirty_cell


@pytest.mark.parametrize(
    ("number", "n1", "n2"),
    [
        ("F-2026-0042", "F20260042", "F202642"),
        ("F2026-042", "F2026042", "F202642"),
        ("f-2026-0042", "F20260042", "F202642"),
        ("ALQ-2026-01", "ALQ202601", "ALQ20261"),
        ("ALQ-2026-02", "ALQ202602", "ALQ20262"),
        ("F-000", "F000", "F0"),
    ],
)
def test_n1_n2_table_of_req_pi_07(number: str, n1: str, n2: str) -> None:
    """The six rows of the REQ-PI-07 table."""
    assert n1_key(number) == n1
    assert n2_key(number) == n2


def test_tax_key_and_name_key_examples() -> None:
    """Tax ids and supplier names reduce to accent-free upper-case alphanumerics."""
    assert tax_key("b-00000001") == "B00000001"
    assert name_key("Suministros García, S.L.") == "SUMINISTROSGARCIASL"


def test_iban_key_removes_all_whitespace_and_keeps_hyphens() -> None:
    """Spaces, tabs, newlines and non-breaking spaces go; hyphens stay; letters are upper-cased."""
    assert iban_key(" es88 2100-0418\u00a05602 \t0005 1332\n") == "ES882100-0418560200051332"
    assert iban_key("ES88 2100 0418 5602 0005 1332") == "ES8821000418560200051332"


def test_as_text_as_decimal_as_date_as_bool_typical() -> None:
    """Typical well-typed cells come back as the matching Python type."""
    assert as_text("F-2026-0042") == "F-2026-0042"
    assert as_decimal(Decimal("121.00")) == Decimal("121.00")
    assert as_date(date(2026, 3, 1)) == date(2026, 3, 1)
    assert as_date(datetime(2026, 3, 1, 10, 30)) == date(2026, 3, 1)
    assert as_date(pd.Timestamp("2026-03-01 10:30:00")) == date(2026, 3, 1)
    assert as_bool(True) is True
    assert as_bool(np.True_) is True


def test_zero_and_dash_constants() -> None:
    """ZERO is a Decimal zero; DASH_CHARS holds hyphen, en dash and em dash."""
    assert ZERO == Decimal("0")
    assert isinstance(ZERO, Decimal)
    assert set(DASH_CHARS) == {"-", "\u2013", "\u2014"}


# Tier 2: edge cases


@pytest.mark.parametrize(
    "value",
    [
        None,
        float("nan"),
        np.nan,
        np.float64("nan"),
        pd.NA,
        pd.NaT,
        Decimal("NaN"),
        "",
        " ",
        "\u00a0",
        "-",
        "\u2013",
        "\u2014",
        "--",
    ],
)
def test_is_missing_every_kind(value: object) -> None:
    """Every flavour of "nothing here" is reported missing."""
    assert is_missing(value) is True


@pytest.mark.parametrize(
    "value",
    [0, 0.0, Decimal("0"), "0", "a", "- -", False, date(2026, 3, 1), float("inf"), np.True_],
)
def test_is_missing_false_for_real_values(value: object) -> None:
    """Zero, text with content, booleans and dates are not missing."""
    assert is_missing(value) is False


@pytest.mark.parametrize(
    "value",
    [1.5, 1, "1.50", True, Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity"), None],
)
def test_as_decimal_rejects_float_int_and_string(value: object) -> None:
    """Only a finite Decimal is a usable amount."""
    assert as_decimal(value) is None


def test_as_text_keeps_value_unstripped() -> None:
    """A usable text cell is returned exactly as written, whitespace included."""
    assert as_text("  F-1 \t") == "  F-1 \t"
    assert as_text("\u00a0") is None
    assert as_text(5) is None
    assert as_text(b"abc") is None
    assert as_text(Decimal("1")) is None


@pytest.mark.parametrize("value", ["2026-03-01", 7, 1.5, None, pd.NaT, np.nan, Decimal("1")])
def test_as_date_rejects_string(value: object) -> None:
    """Strings, numbers and missing cells are not dates."""
    assert as_date(value) is None


@pytest.mark.parametrize("value", [1, 0, "True", "true", None, 1.0, np.int64(1), np.nan, pd.NA])
def test_as_bool_false_for_everything_else(value: object) -> None:
    """Only the bool True / numpy True is true; every other cell is False."""
    assert as_bool(value) is False


def test_as_bool_false_for_false() -> None:
    """The bool False and numpy False stay False."""
    assert as_bool(False) is False
    assert as_bool(np.False_) is False


def test_n1_empty_for_symbols_only() -> None:
    """A number made only of symbols has an empty key (it is not usable for duplicates)."""
    assert n1_key("/ /") == ""
    assert n2_key("/ /") == ""


def test_equal_n1_does_not_imply_equal_n2() -> None:
    """F0-05 and F005 share N1 but not N2, so no rule may rely on that implication."""
    assert n1_key("F0-05") == n1_key("F005") == "F005"
    assert n2_key("F0-05") == "F05"
    assert n2_key("F005") == "F5"
    assert n2_key("F0-05") != n2_key("F005")


def test_n2_all_zero_run_becomes_zero() -> None:
    """A digit run made only of zeros keeps one zero instead of vanishing."""
    assert n2_key("000") == "0"
    assert n2_key("A-00-000") == "A00"


def test_keys_of_empty_text_are_empty() -> None:
    """Callers pass `as_text(cell) or ''`, so an empty string must give empty keys."""
    for key in (n1_key, n2_key, tax_key, name_key, iban_key):
        assert key("") == ""


# Tier 3: property-based


@settings(max_examples=200, deadline=None)
@given(cell=dirty_cell())
def test_dirty_cells_never_raise_helpers(cell: object) -> None:
    """Every reader and every key function accepts any cell value without raising."""
    for reader in (is_missing, as_text, as_decimal, as_date, as_bool):
        reader(cell)
    text = cell if isinstance(cell, str) else (as_text(cell) or "")
    for key in (n1_key, n2_key, tax_key, name_key, iban_key):
        assert isinstance(key(text), str)


@settings(max_examples=200, deadline=None)
@given(text=st.text())
def test_n1_idempotent_and_alnum_only(text: str) -> None:
    """N1 keeps only ASCII upper-case letters and digits, and applying it twice changes nothing."""
    key = n1_key(text)
    assert re.fullmatch(r"[A-Z0-9]*", key) is not None
    assert n1_key(key) == key


@settings(max_examples=200, deadline=None)
@given(text=st.text())
def test_n2_never_longer_than_n1(text: str) -> None:
    """Dropping leading zeros can only shorten the key."""
    assert len(n2_key(text)) <= len(n1_key(text))
