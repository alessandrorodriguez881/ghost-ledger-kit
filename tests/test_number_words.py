"""The number-word parser alone (REQ-GH-01 to REQ-GH-05): English and Spanish, no guard.

Tier 1: the examples of the spec. Tier 2: where words do not join, ordinals, whole words, offsets.
Tier 3: a Hypothesis round trip, every integer from 0 to 999999 spelled in English parses back.
"""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ledger_kit.number_words import NumberPhrase, find_number_phrases


def _values(text: str) -> list[int]:
    return [p.value for p in find_number_phrases(text)]


def _only(text: str) -> NumberPhrase:
    phrases = find_number_phrases(text)
    assert len(phrases) == 1, phrases
    return phrases[0]


# --- Tier 1: English ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("five hundred and forty", 540),
        ("ninety-nine", 99),
        ("ninety nine", 99),
        ("a hundred", 100),
        ("A hundred", 100),
        ("two thousand and five", 2005),
        ("one million two hundred thousand", 1_200_000),
        ("twelve", 12),
        ("zero", 0),
        ("Five Hundred And Forty", 540),
    ],
)
def test_english_phrases(text: str, value: int) -> None:
    phrase = _only(text)

    assert phrase.value == value
    assert phrase.text == text


# --- Tier 1: Spanish ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("quinientos cuarenta", 540),
        ("treinta y cinco", 35),
        ("dieciséis", 16),
        ("dieciseis", 16),
        ("veintidós", 22),
        ("veintitres", 23),
        ("veintiséis", 26),
        ("mil doscientos", 1200),
        ("un millón", 1_000_000),
        ("un millón doscientos mil", 1_200_000),
        ("doscientas", 200),
        ("cien", 100),
        ("mil", 1000),
        ("Quinientos Cuarenta", 540),
    ],
)
def test_spanish_phrases(text: str, value: int) -> None:
    phrase = _only(text)

    assert phrase.value == value
    assert phrase.text == text


# --- Tier 2: joins, offsets, ordinals -------------------------------------------------------


def test_words_join_only_where_the_grammar_allows() -> None:
    phrases = find_number_phrases("five and six")

    assert [p.value for p in phrases] == [5, 6]
    assert [p.text for p in phrases] == ["five", "six"]


def test_a_spanish_article_before_a_number_is_one_phrase() -> None:
    phrase = _only("el cinco")

    assert phrase.value == 5 and phrase.text == "cinco"


def test_and_and_y_never_start_or_end_a_phrase() -> None:
    assert find_number_phrases("and") == []
    assert find_number_phrases("y") == []
    assert [p.text for p in find_number_phrases("five and")] == ["five"]
    assert [p.text for p in find_number_phrases("cinco y")] == ["cinco"]
    assert _values("cuarenta y cinco y seis") == [45, 6]


def test_and_joins_only_after_hundred_thousand_or_million() -> None:
    assert _values("five and forty") == [5, 40]
    assert _values("forty and five") == [40, 5]
    assert _values("five hundred and forty") == [540]


def test_y_joins_only_a_ten_and_a_unit() -> None:
    assert _values("cinco y seis") == [5, 6]
    assert _values("quince y cinco") == [15, 5]
    assert _values("treinta y cinco") == [35]


def test_a_unit_after_a_unit_starts_a_new_phrase() -> None:
    assert _values("two three") == [2, 3]
    assert _values("twenty twenty") == [20, 20]
    assert _values("treinta cinco") == [30, 5]


def test_the_leading_a_counts_only_before_hundred_thousand_million() -> None:
    assert find_number_phrases("a month") == []
    assert _values("a thousand") == [1000]
    assert _values("a million") == [1_000_000]


def test_offsets_slice_the_text_exactly() -> None:
    text = "Pay ninety-nine euros, then Quinientos cuarenta."

    phrases = find_number_phrases(text)

    assert [p.text for p in phrases] == ["ninety-nine", "Quinientos cuarenta"]
    for phrase in phrases:
        assert text[phrase.start : phrase.end] == phrase.text


def test_word_count_is_the_number_of_number_words() -> None:
    assert _only("five").word_count == 1
    assert _only("ninety-nine").word_count == 2
    assert _only("five hundred and forty").word_count == 3  # "and" is not counted
    assert _only("treinta y cinco").word_count == 2  # "y" is not counted
    assert _only("a hundred").word_count == 2


def test_ordinals_are_not_numbers_and_the_whole_phrase_is_skipped() -> None:
    assert find_number_phrases("the twenty-first of August") == []
    assert find_number_phrases("the ninth") == []
    assert find_number_phrases("tenth") == []
    assert find_number_phrases("el vigésimo primero") == []
    assert find_number_phrases("el primero") == []
    assert find_number_phrases("one hundred and first") == []


def test_one_off_gives_one_phrase_of_value_one() -> None:
    phrase = _only("a one-off charge")

    assert phrase.value == 1 and phrase.text == "one"


def test_matching_is_on_whole_words_only() -> None:
    assert find_number_phrases("phone") == []  # contains "one"
    assert find_number_phrases("often seven5") == []
    assert find_number_phrases("ten_twenty") == []
    assert find_number_phrases("twentyfive") == []
    assert find_number_phrases("") == []


def test_a_newline_or_a_comma_does_not_join_words() -> None:
    assert _values("twenty\nfive") == [20, 5]
    assert _values("twenty, five") == [20, 5]
    assert _values("twenty\u2013five") == [20, 5]


def test_english_and_spanish_words_do_not_join() -> None:
    assert _values("five mil") == [5, 1000]


def test_ciento_and_cien_right_after_por_are_percent_words_not_numbers() -> None:
    assert _values("Paga el cinco por ciento de interés.") == [5]
    assert _values("Paga cinco por ciento.") == [5]
    assert _values("por ciento") == []
    assert _values("por cien") == []
    assert _values("Por Ciento") == []


def test_cien_por_cien_gives_one_phrase_the_first_cien() -> None:
    phrase = _only("cien por cien")

    assert phrase.value == 100 and phrase.start == 0 and phrase.text == "cien"


def test_ciento_and_cien_elsewhere_are_still_one_hundred() -> None:
    assert _values("ciento veinte") == [120]
    assert _values("cien euros") == [100]
    assert _values("por\nciento") == [100]  # a newline does not join the words


# --- Tier 3: round trip ---------------------------------------------------------------------

_UNITS = "zero one two three four five six seven eight nine".split()
_TEENS = "ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def _below_hundred(n: int, hyphen: bool) -> str:
    if n < 10:
        return _UNITS[n]
    if n < 20:
        return _TEENS[n - 10]
    tens, unit = divmod(n, 10)
    if unit == 0:
        return _TENS[tens]
    return _TENS[tens] + ("-" if hyphen else " ") + _UNITS[unit]


def _below_thousand(n: int, hyphen: bool, with_and: bool) -> str:
    hundreds, rest = divmod(n, 100)
    if hundreds == 0:
        return _below_hundred(rest, hyphen)
    head = _UNITS[hundreds] + " hundred"
    if rest == 0:
        return head
    return head + (" and " if with_and else " ") + _below_hundred(rest, hyphen)


def spell(n: int, hyphen: bool = True, with_and: bool = False) -> str:
    """Write 0..999999 in English words (a small speller of the test)."""
    if n == 0:
        return "zero"
    thousands, rest = divmod(n, 1000)
    parts = []
    if thousands:
        parts.append(_below_thousand(thousands, hyphen, with_and) + " thousand")
    if rest:
        low = _below_thousand(rest, hyphen, with_and)
        # "two thousand and five": and before a last part below one hundred
        parts.append(("and " if with_and and thousands and rest < 100 else "") + low)
    return " ".join(parts)


def test_the_speller_of_the_test_is_right_on_known_numbers() -> None:
    assert spell(540, with_and=True) == "five hundred and forty"
    assert spell(2005, with_and=True) == "two thousand and five"
    assert spell(99) == "ninety-nine"
    assert spell(100000) == "one hundred thousand"


@settings(max_examples=200, deadline=None)
@given(
    n=st.integers(min_value=0, max_value=999_999),
    hyphen=st.booleans(),
    with_and=st.booleans(),
)
def test_every_integer_spelled_in_english_parses_back_as_one_phrase(
    n: int, hyphen: bool, with_and: bool
) -> None:
    words = spell(n, hyphen, with_and)

    phrases = find_number_phrases(words)

    assert len(phrases) == 1, (n, words, phrases)
    assert phrases[0].value == n
    assert phrases[0].text == words
