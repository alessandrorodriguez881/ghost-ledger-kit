"""The model asks, the kit computes: placeholders through explain_with_meta (model-computes).

No network: every model is the small MockLLMClient below (a copy; test modules do not import each
other). All data is synthetic.
"""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ledger_kit.calc import COMPUTED_MARK, REASON_CALC_NOT_ALLOWED
from ledger_kit.explainer import Explanation, explain, explain_with_meta
from ledger_kit.index_cause import REASON_INDEX_AS_CAUSE
from ledger_kit.live_guard import (
    TRICK_QUESTIONS,
    VERDICT_ACCEPTED,
    VERDICT_REJECTED_CALC_PREFIX,
    VERDICT_REJECTED_PREFIX,
    computed_lines,
    probe_result,
    verdict_line,
)
from ledger_kit.models import Alert

_NO_INVENTION = (
    "You must not invent any number, date, name, or amount. "
    "Every figure you mention must appear verbatim either in the source rows provided or in the "
    "structured fields of the alert (such as yearly_cost). "
    "Do not derive, round, or estimate any figure not explicitly present in those inputs."
)
_TEMPLATE = "Charge {current_amount:money}, {yearly_cost:money} per year ({source_refs})."
_FIVE_YEARS = "If nothing changes, what will this cost me in total five years from now?"
_CINCO_ANOS = "Si nada cambia, ¿cuánto me costará en total dentro de cinco años?"
_FORECAST = TRICK_QUESTIONS[0]
_LINE = (
    f"{COMPUTED_MARK} computed by the kit: yearly_cost 107,88 EUR x 5 = 539,40 EUR, "
    "from the alert fields."
)


@dataclass
class _Msg:
    content: str


@dataclass
class _Choice:
    message: _Msg


@dataclass
class _Response:
    choices: list[_Choice]


class MockLLMClient:
    """Mock client that answers with the given text."""

    def __init__(self, answer: str):
        self._answer = answer
        self.calls: list[dict] = []

    @property
    def chat(self):
        return self

    @property
    def completions(self):
        return self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _Response([_Choice(_Msg(self._answer))])


def _alert() -> Alert:
    return Alert(
        detector="zs.recurring_charge",
        severity="warning",
        title="Recurring charge",
        source_refs=["bank.csv:0"],
        data={"current_amount": Decimal("8.99"), "yearly_cost": Decimal("107.88")},
    )


def _rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": date(2026, 10, 1),
                "amount": Decimal("8.99"),
                "flow": "debit",
                "currency": "EUR",
                "counterparty": "GYMPLUS",
                "source_ref": "bank.csv:0",
            }
        ]
    )


def _ask(answer: str, question: str | None = _FIVE_YEARS) -> Explanation:
    return explain_with_meta(
        _alert(),
        _rows(),
        fallback_template=_TEMPLATE,
        client=MockLLMClient(answer),
        question=question,
    )


_CALC_ANSWER = "GYMPLUS over five years: [[calc: yearly_cost * 5]] (bank.csv:0)."


# --- accepted -----------------------------------------------------------------------------


def test_the_539_40_case_is_accepted_and_carries_its_provenance() -> None:
    result = _ask(_CALC_ANSWER)

    assert result.source == "llm"
    assert result.text == f"GYMPLUS over five years: 539,40 EUR{COMPUTED_MARK} (bank.csv:0)."
    assert result.rejected_numbers == ()
    assert result.raw_answer == _CALC_ANSWER
    (computation,) = result.computed
    assert computation.result == Decimal("539.40")
    assert computation.line == _LINE
    assert computed_lines(result.computed) == (_LINE,)


def test_the_same_with_digits_in_the_question() -> None:
    assert _ask(_CALC_ANSWER, "what is the total in 5 years?").source == "llm"


def test_spanish_question_words_work() -> None:
    result = _ask(_CALC_ANSWER, _CINCO_ANOS)

    assert result.source == "llm"
    assert result.computed[0].result == Decimal("539.40")


def test_explain_returns_the_text_with_the_computed_figure() -> None:
    text = explain(
        _alert(),
        _rows(),
        fallback_template=_TEMPLATE,
        client=MockLLMClient(_CALC_ANSWER),
        question=_FIVE_YEARS,
    )

    assert "539,40 EUR" in text


def test_an_answer_without_a_placeholder_has_no_computed_figures() -> None:
    result = _ask("GYMPLUS costs 107.88 EUR per year (bank.csv:0).")

    assert result.source == "llm"
    assert result.computed == ()
    assert result.text == result.raw_answer


# --- rejected -----------------------------------------------------------------------------


def test_the_same_figure_written_by_hand_is_rejected_as_today() -> None:
    result = _ask("GYMPLUS over five years: 539.40 (bank.csv:0).")

    assert result.source == "fallback"
    assert result.rejected_numbers == ("539.40",)
    assert result.rejected_reason == ""
    assert result.computed == ()


def test_a_figure_written_by_hand_next_to_a_valid_placeholder_is_still_rejected() -> None:
    result = _ask("GYMPLUS: [[calc: yearly_cost * 5]] plus 12.34 of interest (bank.csv:0).")

    assert result.source == "fallback"
    assert result.rejected_numbers == ("12.34",)
    assert result.computed == ()


def test_an_assumed_rate_is_rejected_because_the_question_does_not_give_it() -> None:
    result = _ask("GYMPLUS: [[calc: yearly_cost * 1.05]] (bank.csv:0).")

    assert result.source == "fallback"
    assert result.rejected_numbers == ("1.05",)
    assert result.rejected_reason == REASON_CALC_NOT_ALLOWED
    assert result.text == "Charge 8,99 EUR, 107,88 EUR per year (bank.csv:0)."


@pytest.mark.parametrize(
    ("expression", "question", "part"),
    [
        ("monthly_cost * 12", "twelve months", "monthly_cost"),
        ("yearly_cost ** 2", "squared, two", "yearly_cost ** 2"),
        ("round(yearly_cost)", _FIVE_YEARS, "round(yearly_cost)"),
        ("yearly_cost / 0", "divided by 0", "yearly_cost / 0"),
        ("yearly_cost * 6", _FIVE_YEARS, "6"),
    ],
)
def test_not_allowed_expressions_send_the_card_back_to_the_template(
    expression: str, question: str, part: str
) -> None:
    result = _ask(f"GYMPLUS: [[calc: {expression}]] (bank.csv:0).", question)

    assert result.source == "fallback"
    assert result.rejected_numbers == (part,)
    assert result.rejected_reason == REASON_CALC_NOT_ALLOWED
    assert result.computed == ()


def test_a_placeholder_without_any_question_has_no_constants() -> None:
    result = _ask(_CALC_ANSWER, None)

    assert result.source == "fallback"
    assert result.rejected_numbers == ("5",)


def test_a_placeholder_with_no_constant_needs_a_question_for_any_arithmetic() -> None:
    # A-MC-04: on a card with no question a placeholder is one field and no operator.
    result = _ask("GYMPLUS: [[calc: yearly_cost - current_amount]] (bank.csv:0).", None)

    assert result.source == "fallback"
    assert result.rejected_numbers == ("yearly_cost - current_amount",)
    assert result.rejected_reason == REASON_CALC_NOT_ALLOWED
    assert result.computed == ()


def test_a_single_field_needs_no_question() -> None:
    result = _ask("GYMPLUS: [[calc: yearly_cost]] (bank.csv:0).", None)

    assert result.source == "llm"
    assert result.computed[0].result == Decimal("107.88")


def test_a_placeholder_with_no_constant_computes_with_a_question() -> None:
    result = _ask("GYMPLUS: [[calc: yearly_cost - current_amount]] (bank.csv:0).")

    assert result.source == "llm"
    assert result.computed[0].result == Decimal("98.89")


def test_the_index_as_cause_check_still_runs_before_the_substitution() -> None:
    answer = "The price rose due to inflation: [[calc: yearly_cost * 5]] (bank.csv:0)."

    result = _ask(answer)

    assert result.source == "fallback"
    assert result.rejected_reason == REASON_INDEX_AS_CAUSE
    assert result.computed == ()


def test_a_cited_row_still_has_to_be_cited() -> None:
    result = _ask("GYMPLUS over five years: [[calc: yearly_cost * 5]] (bank.csv:7).")

    assert result.source == "fallback"
    assert result.rejected_numbers == ("7",)


# --- the prompt ---------------------------------------------------------------------------


def test_the_system_prompt_keeps_the_no_invention_rule_and_adds_the_placeholder_rule() -> None:
    client = MockLLMClient(_CALC_ANSWER)

    explain_with_meta(
        _alert(), _rows(), fallback_template=_TEMPLATE, client=client, question=_FIVE_YEARS
    )

    system = client.calls[0]["messages"][0]["content"]
    assert _NO_INVENTION in system
    assert "[[calc: EXPRESSION]]" in system
    assert "do not compute it" in system
    assert "whole numbers that appear in the user's question" in system
    assert "bank.csv:0" in system


# --- the panel ----------------------------------------------------------------------------


def test_an_accepted_probe_keeps_the_shown_text_and_the_lines() -> None:
    meta = _ask(_CALC_ANSWER, _FORECAST.text)

    result = probe_result(_FORECAST, meta, "template")

    assert result.verdict == "accepted"
    assert verdict_line(result) == VERDICT_ACCEPTED
    assert result.raw_answer == _CALC_ANSWER
    assert result.shown_text == meta.text
    assert computed_lines(result.computed) == (_LINE,)


def test_a_probe_without_a_calculation_has_no_shown_text() -> None:
    result = probe_result(_FORECAST, _ask("GYMPLUS costs 107.88 EUR (bank.csv:0)."), "template")

    assert result.computed == ()
    assert result.shown_text == ""


def test_a_rejected_calculation_has_its_own_verdict_sentence() -> None:
    meta = _ask("GYMPLUS: [[calc: yearly_cost * 1.05]] (bank.csv:0).", _FORECAST.text)

    result = probe_result(_FORECAST, meta, "template")

    assert result.verdict == "rejected"
    assert verdict_line(result) == VERDICT_REJECTED_CALC_PREFIX + "`1.05`"


def test_a_rejected_figure_keeps_the_figure_verdict_sentence() -> None:
    meta = _ask("GYMPLUS: 539.40 (bank.csv:0).", _FORECAST.text)

    result = probe_result(_FORECAST, meta, "template")

    assert verdict_line(result) == VERDICT_REJECTED_PREFIX + "`539.40`"


# --- Hypothesis ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(answer=st.text(alphabet=st.characters(min_codepoint=32, max_codepoint=126), max_size=160))
def test_no_answer_makes_the_explainer_raise_or_show_a_placeholder(answer: str) -> None:
    result = _ask(answer)

    assert result.source in ("llm", "fallback")
    if result.source == "llm":
        assert re.search(r"\[\[\s*calc", result.text, re.IGNORECASE) is None
