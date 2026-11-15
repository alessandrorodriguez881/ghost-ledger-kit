"""Tests for the optional `question` and `Explanation.raw_answer` (live-guard LG1).

No network: every model is the small MockLLMClient below (a copy; test modules do not import
each other). All data is synthetic.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from types import MappingProxyType

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ledger_kit.detectors import loaded_source_refs
from ledger_kit.explainer import (
    CALC_PROMPT_RULE,
    Explanation,
    explain,
    explain_with_meta,
    fill_fallback,
)
from ledger_kit.models import Alert

_NO_INVENTION = "You must not invent any number, date, name, or amount."
_TEMPLATE = "Charge {current_amount:money} ({source_refs})"
_SEP = "\n\nQuestion from the user: "
# Mod-97 valid, deliberately wrong national check digits (Finance Rule 5).
_FAKE_IBAN = "ES88 2100 0418 5602 0005 1332"


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
    """Mock client; an answer of None raises, like a provider failure."""

    def __init__(self, responses):
        self._responses = iter(responses)
        self.calls: list[dict] = []

    @property
    def chat(self):
        return self

    @property
    def completions(self):
        return self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        answer = next(self._responses)
        if answer is None:
            raise RuntimeError("down")
        return _Response([_Choice(_Msg(answer))])


def _alert() -> Alert:
    return Alert(
        detector="zs.recurring_charge",
        severity="warning",
        title="Recurring charge",
        source_refs=["bank.csv:0"],
        data={"current_amount": "12.99", "yearly_cost": "155.88"},
    )


def _rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": date(2026, 10, 1),
                "amount": Decimal("12.99"),
                "flow": "debit",
                "currency": "EUR",
                "counterparty": "STREAMBOX",
                "source_ref": "bank.csv:0",
            }
        ]
    )


def _ask(answer, question=None):
    """Run one call against a mock; returns (result, client)."""
    client = MockLLMClient([answer])
    result = explain_with_meta(
        _alert(), _rows(), fallback_template=_TEMPLATE, client=client, question=question
    )
    return result, client


# --- Tier 1: the request ------------------------------------------------------------------


@pytest.mark.parametrize("question", [None, ""])
def test_no_question_sends_todays_request(question: str | None) -> None:
    _, plain = _ask("ok 12,99 EUR bank.csv:0")
    _, with_arg = _ask("ok 12,99 EUR bank.csv:0", question)
    assert with_arg.calls[0]["messages"] == plain.calls[0]["messages"]
    assert _SEP not in with_arg.calls[0]["messages"][1]["content"]


def test_question_goes_to_the_user_message_only() -> None:
    question = "What amount will be charged next month? Give the amount."
    _, plain = _ask("ok bank.csv:0")
    _, asked = _ask("ok bank.csv:0", question)
    system_plain, user_plain = (m["content"] for m in plain.calls[0]["messages"])
    system_asked, user_asked = (m["content"] for m in asked.calls[0]["messages"])
    # A-MC-01: a question adds the placeholder rule to the system message and nothing else.
    assert system_asked == system_plain + " " + CALC_PROMPT_RULE
    assert _NO_INVENTION in system_asked
    assert user_asked == user_plain + _SEP + question
    assert user_asked.startswith("Alert: ")
    assert len(asked.calls) == 1
    assert asked.calls[0]["temperature"] == 0


# --- Tier 1: raw_answer and the verdict ---------------------------------------------------


def test_inventing_answer_is_rejected_and_kept_raw() -> None:
    answer = "You will pay 779.40 EUR. Source: bank.csv:0."
    result, _ = _ask(answer, "What will it cost?")
    assert result.source == "fallback"
    assert result.rejected_numbers == ("779.40",)
    assert result.raw_answer == answer
    assert result == Explanation(fill_fallback(_TEMPLATE, _alert()), "fallback", ("779.40",))


def test_faithful_answer_is_accepted_and_kept_raw() -> None:
    answer = "The alert gives a yearly cost of 155,88 EUR. Source: bank.csv:0."
    result, _ = _ask(answer, "What is the yearly cost?")
    assert result.source == "llm"
    assert result.rejected_numbers == ()
    assert result.text == answer
    assert result.raw_answer == answer


def test_failing_client_gives_empty_raw_answer() -> None:
    result, _ = _ask(None, "What will it cost?")
    assert result.source == "fallback"
    assert result.rejected_numbers == ()
    assert result.raw_answer == ""


def test_no_key_and_no_client_gives_empty_raw_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = explain_with_meta(
        _alert(), _rows(), fallback_template=_TEMPLATE, question="What will it cost?"
    )
    assert result.source == "fallback"
    assert result.raw_answer == ""


def test_raw_answer_is_not_in_repr_and_not_in_equality() -> None:
    a = Explanation("t", "fallback", (), raw_answer="secret figure 1.23")
    assert a == Explanation("t", "fallback", ())
    assert "secret figure" not in repr(a)


def test_explain_returns_the_guarded_text_with_a_question() -> None:
    client = MockLLMClient(["You will pay 779.40 EUR. Source: bank.csv:0."])
    text = explain(_alert(), _rows(), fallback_template=_TEMPLATE, client=client, question="Q?")
    assert text == "Charge 12,99 EUR (bank.csv:0)"


# --- Tier 2: edges ------------------------------------------------------------------------


def test_question_figures_are_not_allowed_for_the_answer() -> None:
    result, _ = _ask("Yes, 4242.", "Is 4242 right?")
    assert result.source == "fallback"
    assert result.rejected_numbers == ("4242",)


def test_empty_model_answer_gives_empty_raw_answer() -> None:
    result, _ = _ask("", "What will it cost?")
    assert result.source == "fallback"
    assert result.raw_answer == ""


def test_iban_shaped_answer_is_rejected_with_a_question() -> None:
    answer = f"Pay to {_FAKE_IBAN}. Source: bank.csv:0."
    result, _ = _ask(answer, "Where do I pay?")
    assert result.source == "fallback"
    assert result.rejected_numbers
    assert result.raw_answer == answer


def test_invalid_date_answer_is_rejected_with_a_question() -> None:
    result, _ = _ask("It renews on 2026-13-45. Source: bank.csv:0.", "When does it renew?")
    assert result.source == "fallback"
    assert result.rejected_numbers == ("2026-13-45",)


def test_unknown_valid_date_is_rejected_with_a_question() -> None:
    result, _ = _ask("It renews on 01/01/2031. Source: bank.csv:0.", "When does it renew?")
    assert result.rejected_numbers == ("2031-01-01",)


# --- Tier 3: properties -------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(question=st.text(max_size=200))
def test_any_question_leaves_the_system_message_alone(question: str) -> None:
    _, plain = _ask("ok bank.csv:0")
    _, asked = _ask("ok bank.csv:0", question)
    plain_system = plain.calls[0]["messages"][0]
    # A-MC-01: only the placeholder rule is added, and only when there is a question.
    expected = dict(plain_system)
    if question:
        expected["content"] = plain_system["content"] + " " + CALC_PROMPT_RULE
    assert asked.calls[0]["messages"][0] == expected
    assert asked.calls[0]["temperature"] == 0


@settings(max_examples=200, deadline=None)
@given(question=st.text(max_size=200), answer=st.text(max_size=200))
def test_cited_refs_stay_inside_the_loaded_inputs(question: str, answer: str) -> None:
    result, _ = _ask(answer, question)
    refs = loaded_source_refs(_rows(), MappingProxyType({}))
    assert set(_alert().source_refs) <= refs
    assert result.source in ("llm", "fallback")
    if result.source == "llm":
        assert result.raw_answer == answer
