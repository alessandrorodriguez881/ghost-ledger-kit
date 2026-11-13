"""The number guard reads numbers written in words (REQ-GH-06 to REQ-GH-13), through the public
`check_figures` on real demo cases (tests/judge_path_support.py), plus the highlight of a rejected
phrase and the proof that every Exorcise draft of the three demos still passes.

All data is the synthetic demo data of the repository.
"""

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest
import test_exorcise_demos as demos
from judge_path_support import Z1_ALERT_ID, Case, cases_of, find_case

from ledger_kit.explainer import _allowed_decimals, _select_llm_columns, check_figures
from ledger_kit.live_guard import highlight_segments
from ledger_kit.models import Alert
from ledger_kit.number_words import find_number_phrases


def _gymplus() -> Case:
    case = find_case(Z1_ALERT_ID)
    assert case is not None
    return case


def _musicbox() -> Case:
    found = [c for c in cases_of("zs") if c.alert.title == "Duplicate subscription: MUSICBOX"]
    assert len(found) == 1
    return found[0]


def _check(case: Case, text: str) -> tuple[bool, tuple[str, ...]]:
    return check_figures(text, case.alert, case.rows, case.columns)


# --- Tier 1: a figure written in words is rejected, named as written ------------------------


@pytest.mark.parametrize(
    ("text", "phrase"),
    [
        ("Over five years you pay five hundred and forty euros.", "five hundred and forty"),
        ("GYMPLUS: quinientos cuarenta euros.", "quinientos cuarenta"),
        ("It costs ninety-nine euros.", "ninety-nine"),
        ("Paga el cinco por ciento de interés.", "cinco"),
    ],
)
def test_a_figure_in_words_no_row_holds_is_rejected_as_written(text: str, phrase: str) -> None:
    ok, rejected = _check(_gymplus(), text)

    assert ok is False
    assert rejected == (phrase,)
    _assert_value_not_allowed(_gymplus(), phrase)


def test_the_five_per_cent_example_is_rejected_because_five_is_not_allowed() -> None:
    case = _gymplus()
    allowed = _allowed_decimals(case.alert, _select_llm_columns(case.rows, case.columns))

    assert Decimal(5) not in allowed


def _assert_value_not_allowed(case: Case, phrase: str) -> None:
    """The value of `phrase` is not allowed: no test relies on a value the data happens to hold."""
    allowed = _allowed_decimals(case.alert, _select_llm_columns(case.rows, case.columns))
    found = find_number_phrases(phrase)
    assert len(found) == 1, phrase
    assert Decimal(found[0].value) not in allowed, phrase


def test_the_same_figure_in_digits_is_rejected_too() -> None:
    ok, rejected = _check(_gymplus(), "Over five years you pay 540 euros.")

    assert ok is False and rejected == ("540",)


# --- Tier 1: what passes --------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "It was charged three times, one of them after you cancelled.",
        "GYMPLUS charged you once.",
        "The rows show three months.",
    ],
)
def test_small_counts_in_words_with_no_money_beside_them_pass(text: str) -> None:
    assert _check(_gymplus(), text) == (True, ())


def test_the_yearly_cost_in_digits_and_the_word_three_pass() -> None:
    case = _gymplus()
    text = f"The yearly cost is {case.alert.data['yearly_cost']} EUR over three charges."

    assert _check(case, text) == (True, ())


def test_once_is_checked_beside_a_currency() -> None:
    ok, rejected = _check(_gymplus(), "You paid once EUR.")

    assert ok is False and rejected == ("once",)


@pytest.mark.parametrize(
    ("text", "phrase"),
    [
        ("You pay five euros.", "five"),
        ("You pay EUR five.", "five"),
        ("You pay five €.", "five"),
        ("Interest is five percent.", "five"),
        ("Interest is five per cent.", "five"),
        ("Interest is five %.", "five"),
        ("Paga cinco por ciento.", "cinco"),
        ("Pagas dos euros.", "dos"),
        ("Pagas cuatro céntimos.", "cuatro"),
        ("You pay one dollar.", "one"),
    ],
)
def test_a_small_word_beside_a_currency_or_percent_is_checked(text: str, phrase: str) -> None:
    ok, rejected = _check(_gymplus(), text)

    assert ok is False and rejected == (phrase,)
    _assert_value_not_allowed(_gymplus(), phrase)


def test_per_cent_words_after_por_are_not_a_second_number() -> None:
    for text in ("Paga el cinco por ciento de interés.", "Paga cinco por ciento."):
        assert _check(_gymplus(), text) == (False, ("cinco",))


def test_a_word_above_ten_is_checked_even_alone() -> None:
    ok, rejected = _check(_gymplus(), "There were twelve charges.")

    assert ok is False and rejected == ("twelve",)


def test_two_small_words_in_one_phrase_are_checked() -> None:
    ok, rejected = _check(_gymplus(), "The total is twenty one.")

    assert ok is False and rejected == ("twenty one",)


def test_ordinals_are_not_read() -> None:
    assert _check(_gymplus(), "It happened on the twenty-first of August.") == (True, ())


def test_the_rejected_phrases_and_digits_come_in_text_order() -> None:
    first = _check(_gymplus(), "You pay five hundred and forty euros, which is 539.40 EUR.")
    second = _check(_gymplus(), "You pay 539.40 EUR, which is five hundred and forty euros.")

    assert first[1] == ("five hundred and forty", "539.40")
    assert second[1] == ("539.40", "five hundred and forty")


def test_a_number_phrase_in_a_row_or_in_the_alert_data_is_allowed() -> None:
    alert = Alert(
        detector="t.words",
        severity="info",
        title="Synthetic",
        source_refs=["f.csv:0"],
        data={"yearly_cost": "10.00"},
    )
    rows = pd.DataFrame(
        [
            {
                "date": date(2026, 1, 1),
                "amount": Decimal("10.00"),
                "flow": "debit",
                "currency": "EUR",
                "counterparty": "SEVEN ELEVEN",
                "source_ref": "f.csv:0",
            }
        ]
    )
    other = rows.assign(counterparty="SHOP")

    assert check_figures("SEVEN ELEVEN charged you 10.00 EUR.", alert, rows) == (True, ())
    ok, rejected = check_figures("SEVEN ELEVEN charged you 10.00 EUR.", alert, other)
    assert ok is False and rejected == ("ELEVEN",)


# --- Words that are not figures: the count of cited rows and row citations (REQ-GH-15) ------

_COUNT_WORDS = {
    11: "eleven",
    12: "twelve",
    13: "thirteen",
    14: "fourteen",
    15: "fifteen",
    16: "sixteen",
    17: "seventeen",
    18: "eighteen",
    19: "nineteen",
}


def _all_cases() -> list[Case]:
    return [case for prefix in ("zs", "pi", "vf") for case in cases_of(prefix)]


def _allowed_of(case: Case) -> set[Decimal]:
    return _allowed_decimals(case.alert, _select_llm_columns(case.rows, case.columns))


def _count_cases() -> tuple[Case, Case, str]:
    """A demo case that cites 12 rows (else the first count from 11 to 19), another that cites
    a different number, and the number in words; chosen by counting `source_refs`."""
    cases = _all_cases()
    twelve = [c for c in cases if len(c.alert.source_refs) == 12]
    big = twelve or [c for c in cases if len(c.alert.source_refs) in _COUNT_WORDS]
    assert big, "no demo alert cites eleven to nineteen rows"
    first = big[0]
    count = len(first.alert.source_refs)
    word = _COUNT_WORDS[count]
    value = Decimal(count)
    three = [c for c in cases if len(c.alert.source_refs) == 3 and value not in _allowed_of(c)]
    others = three or [
        c for c in cases if len(c.alert.source_refs) != count and value not in _allowed_of(c)
    ]
    assert others, "no demo alert cites another number of rows"
    return first, others[0], word


def test_a_count_in_words_of_the_cited_rows_passes_and_another_count_is_rejected() -> None:
    cited, other, word = _count_cases()
    text = f"{word} debit transactions"

    assert Decimal(len(cited.alert.source_refs)) not in _allowed_of(cited)
    assert _check(cited, text) == (True, ())
    assert len(other.alert.source_refs) != len(cited.alert.source_refs)
    assert _check(other, text) == (False, (word,))


def test_a_count_in_words_followed_by_a_currency_stays_a_figure() -> None:
    cited, _, word = _count_cases()

    ok, rejected = _check(cited, f"{word} euros")

    assert ok is False and rejected == (word,)


def _citing_case() -> Case:
    alert = Alert(
        detector="t.words",
        severity="info",
        title="Synthetic",
        source_refs=["f.csv:1", "f.csv:2", "f.csv:12"],
        data={"yearly_cost": "10.00"},
    )
    rows = pd.DataFrame(
        [
            {
                "date": date(2026, 1, 1),
                "amount": Decimal("10.00"),
                "flow": "debit",
                "currency": "EUR",
                "counterparty": "SHOP",
                "source_ref": ref,
            }
            for ref in alert.source_refs
        ]
    )
    return Case("zs", alert, rows, None)


@pytest.mark.parametrize(
    "text",
    ["Rows one and two.", "Row twelve.", "rows one, two, and twelve", "Line twelve says so."],
)
def test_a_row_citation_in_words_of_a_cited_line_passes(text: str) -> None:
    assert _check(_citing_case(), text) == (True, ())


@pytest.mark.parametrize(
    ("text", "rejected"),
    [
        ("Row fourteen.", ("fourteen",)),
        ("Rows twelve and fourteen.", ("fourteen",)),
        ("It happened twelve times in rows one and two.", ("twelve",)),
        ("Row two and fourteen", ("fourteen",)),
    ],
)
def test_a_word_that_is_not_a_cited_line_stays_a_figure(
    text: str, rejected: tuple[str, ...]
) -> None:
    assert _check(_citing_case(), text) == (False, rejected)


# --- A documented limit, accepted on purpose -------------------------------------------------


def test_documented_limit_the_guard_checks_figures_not_meaning() -> None:
    """MUSICBOX costs 10.99 EUR every year: wrong in meaning (it is monthly), but 10.99 is a row
    figure, so the guard accepts it. The guard checks figures; it does not judge wording."""
    text = "MUSICBOX costs 10.99 EUR every year."

    assert _check(_musicbox(), text) == (True, ())


# --- Highlight ------------------------------------------------------------------------------


def test_a_rejected_phrase_is_one_flagged_segment() -> None:
    raw = "Over five years you pay five hundred and forty euros."

    segments = highlight_segments(raw, ["five hundred and forty"])

    flagged = [s for s in segments if s.flagged]
    assert [s.text for s in flagged] == ["five hundred and forty"]
    assert "".join(s.text for s in segments) == raw


def test_the_token_once_does_not_flag_the_word_concession() -> None:
    raw = "A concession was made."

    assert highlight_segments(raw, ["once"]) == [(raw, False)]


def test_the_token_once_flags_the_whole_word() -> None:
    segments = highlight_segments("It was charged once.", ["once"])

    assert [s.text for s in segments if s.flagged] == ["once"]


def test_digit_highlighting_is_unchanged() -> None:
    segments = highlight_segments("Total 539.40 EUR, not 39.40.", ["39.40"])

    assert [s.text for s in segments if s.flagged] == ["39.40"]


# --- Every Exorcise draft still passes ------------------------------------------------------

DRAFT_CASES = [case for case in demos.CASES if demos._has_template(case)]


@pytest.mark.parametrize("language", demos.LANGUAGES)
@pytest.mark.parametrize("case", DRAFT_CASES, ids=demos._id)
def test_every_exorcise_draft_of_the_demos_still_passes_the_guard(
    case: Case, language: str
) -> None:
    draft = demos._draft(case, language)

    assert draft is not None, f"{demos._id(case)} {language}: the draft was rejected"
    assert check_figures(draft, case.alert, case.rows, case.columns) == (True, ())
