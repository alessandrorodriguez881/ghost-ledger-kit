"""Tests for IBAN validity in the phantom-invoices detectors (Task P4)."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from apps.phantom_invoices.detectors.utils import (
    IBAN_FORMAT_RE,
    IBAN_MOD97_MODULUS,
    IBAN_MOD97_REMAINDER,
    iban_key,
    iban_problem,
    is_valid_iban,
)
from apps.phantom_invoices.tests.pi_checkers import (
    iban_check_digits,
    mod97_remainder,
    spanish_national_dc,
    spanish_national_dc_ok,
)
from apps.phantom_invoices.tests.pi_strategies import spaced_cased, valid_iban

# Mod-97 valid, deliberately wrong Spanish national check digits (Finance Rule 5).
DOC_IBAN = "ES88 2100 0418 5602 0005 1332"
DOC_KEY = "ES8821000418560200051332"


def test_documented_iban_is_valid() -> None:
    """The documented synthetic IBAN passes the structural and the mod-97 check."""
    assert iban_key(DOC_IBAN) == DOC_KEY
    assert iban_problem(iban_key(DOC_IBAN)) is None


def test_checkers_agree_with_documented_example() -> None:
    """Mod-97 remainder is 1, the correct national digits are 45, the IBAN carries 56."""
    assert mod97_remainder(DOC_KEY) == 1
    assert spanish_national_dc("2100", "0418", "0200051332") == "45"
    assert DOC_KEY[12:14] == "56"
    assert not spanish_national_dc_ok(DOC_KEY)


@pytest.mark.parametrize(
    "key",
    [
        "ES88-2100-0418-5602-0005-1332",
        "ES88.2100.0418.5602.0005.1332",
        "ES88",
        "ES8821000418",
        "88ES21000418560200051332",
        "ES88210004185602000513321234567890123456",
    ],
)
def test_format_problem_for_hyphens_dots_and_short_values(key: str) -> None:
    """Separators, short values and mis-shaped values are format problems, not checksum ones."""
    assert iban_problem(key) == "format"


def test_checksum_problem_for_valid_shape_bad_digits() -> None:
    """Changing the check digits 88 to 89 keeps the shape but breaks mod-97."""
    broken = DOC_KEY.replace("ES88", "ES89", 1)
    assert broken != DOC_KEY
    assert iban_problem(broken) == "checksum"


def test_is_valid_iban_matches_problem_none() -> None:
    """is_valid_iban is exactly iban_problem(...) is None."""
    for key in (DOC_KEY, "ES89" + DOC_KEY[4:], "ES88", ""):
        assert is_valid_iban(key) is (iban_problem(key) is None)


def test_lowercase_after_iban_key_is_valid() -> None:
    """iban_key upper-cases, so a lower-case re-typed IBAN is valid afterwards."""
    assert iban_problem(iban_key("es88 2100 0418 5602 0005 1332")) is None
    assert iban_problem("es8821000418560200051332") == "format"  # the raw cell is not a key


def test_empty_key_is_format_problem() -> None:
    """An empty key (missing cell) is a format problem, never an exception."""
    assert iban_problem("") == "format"
    assert is_valid_iban("") is False


def test_other_country_valid_iban_accepted() -> None:
    """National digits and per-country lengths are not validated (OD-PI-15)."""
    bban = "00000000000000000001"
    other = "DE" + iban_check_digits("DE", bban) + bban
    assert mod97_remainder(other) == 1
    assert iban_problem(other) is None


def test_constants_values() -> None:
    """The ISO 13616 constants and the structural regex keep their documented values."""
    assert IBAN_MOD97_MODULUS == 97
    assert IBAN_MOD97_REMAINDER == 1
    assert IBAN_FORMAT_RE.pattern == r"^[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}$"


@settings(max_examples=200, deadline=None)
@given(text=st.text())
def test_iban_problem_never_raises_on_any_text(text: str) -> None:
    """Any text, keyed or not, gives None, 'format' or 'checksum' and never raises."""
    assert iban_problem(text) in (None, "format", "checksum")
    assert iban_problem(iban_key(text)) in (None, "format", "checksum")


@settings(max_examples=200, deadline=None)
@given(data=valid_iban().flatmap(lambda iban: st.tuples(st.just(iban), spaced_cased(iban))))
def test_valid_iban_stays_valid_when_spaced_and_recased(data: tuple[str, str]) -> None:
    """Re-typing a valid IBAN with spaces, tabs and lower case never changes its key."""
    iban, retyped = data
    assert iban_key(retyped) == iban
    assert iban_problem(iban_key(retyped)) is None
