"""Tests for constants, text folding, vocabulary and series keys (Task VF2)."""

import string
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from apps.vampire_fees.detectors import utils
from apps.vampire_fees.detectors.utils import (
    EMPTY_VOCABULARY,
    INTERVALS,
    FeeVocabulary,
    build_vocabulary,
    concept_of,
    contains_phrase,
    fold_tokens,
    series_key,
)

ASCII_TEXT = st.text(alphabet=string.ascii_letters + string.digits + " -/.,", max_size=40)

VALID_TABLE = {
    "fee": ["Comisión", "Cuota de Mantenimiento"],
    "overdraft": ["descubierto"],
    "interest": ["intereses"],
    "exclude": ["notaría"],
}


# --- Tier 1 ---------------------------------------------------------------------------------


def test_fold_tokens_folds_case_accents_and_punctuation() -> None:
    """Accents and case are removed, punctuation splits, digits stay."""
    assert fold_tokens("Comisión Mantenimiento-Cuenta 05/26") == (
        "comision",
        "mantenimiento",
        "cuenta",
        "05",
        "26",
    )


def test_contains_phrase_one_and_two_word_phrases() -> None:
    """A phrase matches when its tokens are consecutive."""
    tokens = fold_tokens("Cuota de mantenimiento cuenta")
    assert contains_phrase(tokens, [("cuota", "de", "mantenimiento")])
    assert contains_phrase(tokens, [("cuenta",)])
    assert not contains_phrase(tokens, [("cuota", "mantenimiento")])
    assert not contains_phrase(tokens, [("mantenimiento", "de")])


def test_series_key_drops_tokens_with_digits() -> None:
    """AE-VF-08: the month number does not split a series."""
    assert (
        series_key("BANCO FICTICIO", "Comisión mantenimiento cuenta 05/26")
        == "banco ficticio|comision mantenimiento cuenta"
    )


def test_concept_of_reads_the_common_concept_tag() -> None:
    """The first common_concept tag gives the concept."""
    assert concept_of(["x", "common_concept:17"]) == "17"
    assert concept_of(["own_concept:003", "common_concept:16", "common_concept:17"]) == "16"


def test_build_vocabulary_folds_phrases() -> None:
    """Phrases are folded to token tuples."""
    vocabulary = build_vocabulary(VALID_TABLE)
    assert isinstance(vocabulary, FeeVocabulary)
    assert ("comision",) in vocabulary.fee
    assert ("cuota", "de", "mantenimiento") in vocabulary.fee
    assert vocabulary.exclude == (("notaria",),)


# --- Tier 2 ---------------------------------------------------------------------------------


@pytest.mark.parametrize("value", [None, float("nan"), "", "   ", "--/"])
def test_fold_tokens_of_nothing_is_empty(value: object) -> None:
    """None, NaN, empty and punctuation-only text give no tokens."""
    assert fold_tokens(value) == ()


def test_fold_tokens_of_pandas_na_is_empty() -> None:
    """The pandas missing-value marker gives no tokens either."""
    import pandas as pd

    assert fold_tokens(pd.NA) == ()


def test_contains_phrase_on_no_tokens_is_false() -> None:
    """Empty tokens never match, and an empty phrase never matches."""
    assert not contains_phrase((), [("fee",)])
    assert not contains_phrase(("fee",), [()])
    assert not contains_phrase(("fee",), [])


def test_a_phrase_never_matches_across_two_fields() -> None:
    """Fields are searched separately, so a phrase cannot span them."""
    phrase = [("cuota", "de")]
    assert not contains_phrase(fold_tokens("cuota"), phrase)
    assert not contains_phrase(fold_tokens("de mantenimiento"), phrase)


def test_whole_token_matching() -> None:
    """A fee word does not match inside another word."""
    assert not contains_phrase(fold_tokens("Feelgood Market"), [("fee",)])
    assert not contains_phrase(fold_tokens("comisionista"), [("comision",)])
    assert contains_phrase(fold_tokens("FEE"), [("fee",)])


@pytest.mark.parametrize("tags", [None, [], float("nan"), ["own_concept:003"], ("x",)])
def test_concept_of_without_concept_is_none(tags: object) -> None:
    """No tags, a missing value or no concept tag give None."""
    assert concept_of(tags) is None


@pytest.mark.parametrize("missing", ["fee", "overdraft", "interest", "exclude"])
def test_build_vocabulary_rejects_missing_key(missing: str) -> None:
    """A missing key raises ValueError naming the key."""
    table = {k: v for k, v in VALID_TABLE.items() if k != missing}
    with pytest.raises(ValueError, match=missing):
        build_vocabulary(table)


@pytest.mark.parametrize("key", ["fee", "overdraft", "interest", "exclude"])
@pytest.mark.parametrize("bad", [[], [1], ["--"], [""], "comision", [None]])
def test_build_vocabulary_rejects_invalid_values(key: str, bad: object) -> None:
    """An empty list, a non-string, a phrase without letter or digit raises naming the key."""
    table = dict(VALID_TABLE) | {key: bad}
    with pytest.raises(ValueError, match=key):
        build_vocabulary(table)


def test_empty_vocabulary_has_no_phrases() -> None:
    """EMPTY_VOCABULARY holds nothing."""
    assert EMPTY_VOCABULARY == FeeVocabulary((), (), (), ())


# --- Tier 3 ---------------------------------------------------------------------------------


@settings(max_examples=200)
@given(text=st.text(max_size=60))
def test_fold_tokens_is_idempotent(text: str) -> None:
    """Folding the folded tokens again changes nothing."""
    tokens = fold_tokens(text)
    assert fold_tokens(" ".join(tokens)) == tokens


@settings(max_examples=200)
@given(text=st.text(max_size=60))
def test_fold_tokens_output_is_lowercase_alphanumeric(text: str) -> None:
    """Every token is non-empty, alphanumeric and case-folded."""
    for token in fold_tokens(text):
        assert token
        assert token.isalnum()
        assert token == token.casefold()


@settings(max_examples=200)
@given(text=ASCII_TEXT)
def test_fold_tokens_ignores_case_for_ascii(text: str) -> None:
    """Upper, lower and original case give the same tokens."""
    assert fold_tokens(text.upper()) == fold_tokens(text.lower()) == fold_tokens(text)


@settings(max_examples=200)
@given(text=ASCII_TEXT)
def test_series_key_has_no_digit_tokens(text: str) -> None:
    """No token of a series key contains a digit."""
    key = series_key(text, text)
    assert not any(ch.isdigit() for ch in key)


def test_fold_removes_accents() -> None:
    """Accents are dropped, not just lowered."""
    assert fold_tokens("ÁÉÍÓÚ ñ ü") == ("aeiou", "n", "u")


# --- Constants --------------------------------------------------------------------------------


def test_constants_values() -> None:
    """Every constant of design 2.1 exists with the stated value and type."""
    expected = {
        "STATEMENT_CURRENCY": "EUR",
        "FEE_CONCEPTS": ("16", "17"),
        "CONCEPT_TAG_PREFIX": "common_concept:",
        "MONTHLY_NOMINAL_DAYS": 30,
        "QUARTERLY_NOMINAL_DAYS": 91,
        "YEARLY_NOMINAL_DAYS": 365,
        "MONTHLY_TOLERANCE_DAYS": 3,
        "QUARTERLY_TOLERANCE_DAYS": 3,
        "YEARLY_TOLERANCE_DAYS": 5,
        "MIN_CHARGES_MONTHLY": 3,
        "MIN_CHARGES_QUARTERLY": 2,
        "MIN_CHARGES_YEARLY": 2,
        "PERIODS_PER_YEAR_MONTHLY": 12,
        "PERIODS_PER_YEAR_QUARTERLY": 4,
        "PERIODS_PER_YEAR_YEARLY": 1,
        "RECURRING_FEE_WARNING_YEARLY_COST": Decimal("60.00"),
        "FEE_INCREASE_MIN_RATIO": Decimal("0.05"),
        "FEE_STABLE_RATIO": Decimal("0.02"),
        "FEE_INCREASE_CRITICAL_RATIO": Decimal("0.50"),
        "OVERDRAFT_CRITICAL_TOTAL": Decimal("100.00"),
        "DAYS_PER_YEAR": 365,
        "SUMMARY_MIN_SPAN_DAYS": 90,
        "SUMMARY_WARNING_YEARLY_EQUIVALENT": Decimal("200.00"),
    }
    for name, value in expected.items():
        actual = getattr(utils, name)
        assert actual == value, name
        assert type(actual) is type(value), name


def test_intervals_order_and_non_overlapping_ranges() -> None:
    """INTERVALS is monthly, quarterly, yearly and the tolerance ranges never overlap."""
    assert [i.name for i in INTERVALS] == ["monthly", "quarterly", "yearly"]
    ranges = [
        (i.nominal_days - i.tolerance_days, i.nominal_days + i.tolerance_days) for i in INTERVALS
    ]
    for (_, high), (low, _) in zip(ranges, ranges[1:], strict=False):
        assert high < low
    assert [i.min_charges for i in INTERVALS] == [3, 2, 2]
    assert [i.periods_per_year for i in INTERVALS] == [12, 4, 1]
