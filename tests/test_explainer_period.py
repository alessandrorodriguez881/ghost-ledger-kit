"""Each figure is tied to its field: a period that contradicts it rejects the answer.

model-computes REQ-MC-17 to REQ-MC-26. No network: every model is the small MockLLMClient below
(a copy; test modules do not import each other). All data is synthetic.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ledger_kit.explainer import (
    PERIOD_PHRASES,
    REASON_PERIOD_MISMATCH,
    Explanation,
    explain_with_meta,
    field_periods,
    find_period_mismatches,
)
from ledger_kit.index_cause import REASON_INDEX_AS_CAUSE
from ledger_kit.live_guard import (
    TRICK_QUESTIONS,
    VERDICT_REJECTED_PERIOD_PREFIX,
    probe_result,
    verdict_line,
)
from ledger_kit.models import Alert

_TEMPLATE = "{counterparty}: {current_amount:money}, {yearly_cost:money} per year ({source_refs})."
_FALLBACK = "MUSICBOX: 10,99 EUR, 131,88 EUR per year (bank.csv:0, bank.csv:1)."


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


def _recurring(interval: str = "monthly", amount: str = "10.99", yearly: str = "131.88") -> Alert:
    """A zs.recurring_charge alert of MUSICBOX, with the fields the detector writes."""
    return Alert(
        detector="zs.recurring_charge",
        severity="info",
        title="Recurring charge detected: MUSICBOX",
        source_refs=["bank.csv:0", "bank.csv:1"],
        data={
            "counterparty": "MUSICBOX",
            "normalised_key": "MUSICBOX",
            "interval_type": interval,
            "current_amount": amount,
            "charge_count": 2,
            "yearly_cost": yearly,
            "first_charge_date": "2026-05-08",
            "last_charge_date": "2026-06-07",
            "is_active": True,
        },
    )


def _duplicate() -> Alert:
    """A zs.duplicate_subscription alert of MUSICBOX: no per-charge field, no interval."""
    return Alert(
        detector="zs.duplicate_subscription",
        severity="warning",
        title="Duplicate subscription: MUSICBOX",
        source_refs=["bank.csv:0", "bank.csv:1"],
        data={
            "canonical_name": "MUSICBOX",
            "series_count": 2,
            "series_counterparties": ["MUSICBOX", "MUSICBOX"],
            "yearly_cost": "263.76",
        },
    )


def _fee_rise() -> Alert:
    """A vf.fee_increase alert whose new monthly fee equals its extra cost per year."""
    return Alert(
        detector="vf.fee_increase",
        severity="warning",
        title="Fee increase: BANCO FICTICIO",
        source_refs=["bank.csv:0", "bank.csv:1"],
        data={
            "counterparty": "BANCO FICTICIO",
            "interval_type": "monthly",
            "old_amount": "11.00",
            "new_amount": "12.00",
            "increase_percent": "9.1",
            "extra_cost_per_year": "12.00",
            "yearly_cost": "144.00",
        },
    )


def _rows(amount: str = "10.99") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": day,
                "amount": Decimal(amount),
                "flow": "debit",
                "currency": "EUR",
                "counterparty": "MUSICBOX",
                "source_ref": ref,
            }
            for day, ref in ((date(2026, 5, 8), "bank.csv:0"), (date(2026, 6, 7), "bank.csv:1"))
        ]
    )


def _ask(answer: str, alert: Alert | None = None, question: str | None = None) -> Explanation:
    return explain_with_meta(
        alert or _recurring(),
        _rows(),
        fallback_template=_TEMPLATE,
        client=MockLLMClient(answer),
        question=question,
    )


def _rejected(result: Explanation, *tokens: str) -> None:
    assert result.source == "fallback"
    assert result.rejected_reason == REASON_PERIOD_MISMATCH
    assert result.rejected_numbers == tokens


# --- Tier 1: the cases of the README -------------------------------------------------------------


def test_musicbox_every_year_on_a_monthly_charge_is_rejected() -> None:
    answer = "MUSICBOX costs 10.99 EUR every year (bank.csv:0)."
    result = _ask(answer)

    _rejected(result, "10.99", "every year")
    assert result.text == _FALLBACK
    assert result.raw_answer == answer


def test_the_same_amount_per_month_passes() -> None:
    result = _ask("MUSICBOX costs 10.99 EUR per month (bank.csv:0).")

    assert result.source == "llm"
    assert result.rejected_numbers == ()


def test_yearly_cost_per_month_is_rejected() -> None:
    _rejected(_ask("MUSICBOX costs 131.88 EUR per month (bank.csv:0)."), "131.88", "per month")


def test_both_figures_with_their_own_period_pass() -> None:
    answer = "MUSICBOX costs €10.99 per month and €131.88 per year (bank.csv:0)."

    assert _ask(answer).source == "llm"


def test_the_yearly_word_of_the_next_clause_does_not_bind_the_first_figure() -> None:
    answer = "A recurring charge of €10.99 has been detected, with a yearly cost of €131.88."

    assert _ask(answer + " (bank.csv:0)").source == "llm"


def test_a_period_word_in_a_clause_without_a_figure_is_not_read() -> None:
    answer = (
        "The total yearly cost is €131.88, indicating that six monthly charges have been made "
        "(bank.csv:0)."
    )

    assert _ask(answer).source == "llm"


@pytest.mark.parametrize(
    ("answer", "tokens"),
    [
        ("MUSICBOX cuesta 10,99 EUR al año (bank.csv:0).", ("10,99", "al año")),
        ("MUSICBOX cuesta 10,99 EUR cada año (bank.csv:0).", ("10,99", "cada año")),
        ("El coste anual es 131,88 EUR (bank.csv:0).", ()),
        ("MUSICBOX cuesta 131,88 EUR al mes (bank.csv:0).", ("131,88", "al mes")),
        ("Cargo mensual de 131,88 EUR (bank.csv:0).", ("131,88", "mensual")),
    ],
)
def test_spanish_period_words(answer: str, tokens: tuple[str, ...]) -> None:
    result = _ask(answer)

    if tokens:
        _rejected(result, *tokens)
    else:
        assert result.source == "llm"


@pytest.mark.parametrize(
    "answer",
    [
        "MUSICBOX cuesta 10,99 EUR al mes y 131,88 EUR al año (bank.csv:0).",
        "MUSICBOX: cuota mensual de 10,99 EUR, coste anual de 131,88 EUR (bank.csv:0).",
        "MUSICBOX cuesta 10,99 EUR cada mes (bank.csv:0).",
    ],
)
def test_spanish_period_words_that_agree_pass(answer: str) -> None:
    assert _ask(answer).source == "llm"


def test_a_figure_with_no_period_word_passes() -> None:
    assert _ask("MUSICBOX costs 10.99 EUR, 131.88 EUR in all (bank.csv:0).").source == "llm"


def test_an_ambiguous_figure_is_not_checked() -> None:
    alert = _fee_rise()
    rows = _rows("12.00")
    for answer in (
        "The fee is now 12.00 EUR every year (bank.csv:1).",
        "The fee is now 12.00 EUR per month (bank.csv:1).",
    ):
        result = explain_with_meta(
            alert, rows, fallback_template=_TEMPLATE, client=MockLLMClient(answer)
        )
        assert result.source == "llm", answer


def test_a_computed_figure_is_not_checked() -> None:
    answer = "MUSICBOX: [[calc: current_amount * 12]] per month (bank.csv:0)."
    result = _ask(answer, question="What do twelve charges cost?")

    assert result.source == "llm"
    assert len(result.computed) == 1


def test_a_figure_only_in_the_rows_states_no_period_and_still_passes() -> None:
    """The duplicate-subscription card has no per-charge field: 10.99 is only in the rows."""
    result = _ask("MUSICBOX costs 10.99 EUR every year (bank.csv:0).", alert=_duplicate())

    assert result.source == "llm"


def test_other_meaning_is_still_not_checked() -> None:
    """The period agrees with the field; that the price rose is not checked (README)."""
    result = _ask("MUSICBOX raised its price to 10.99 EUR per month (bank.csv:0).")

    assert result.source == "llm"


# --- Tier 2: the other intervals, the order of checks, the panel ---------------------------------


@pytest.mark.parametrize(
    ("interval", "agrees", "contradicts"),
    [
        ("weekly", "per week", "per month"),
        ("weekly", "a la semana", "al mes"),
        ("quarterly", "quarterly", "a month"),
        ("quarterly", "al trimestre", "anual"),
        ("yearly", "annually", "weekly"),
        ("monthly", "every month", "per quarter"),
    ],
)
def test_each_interval_type(interval: str, agrees: str, contradicts: str) -> None:
    alert = _recurring(interval=interval, amount="9.00", yearly="99.00")
    good = f"MUSICBOX costs 9.00 EUR {agrees} (bank.csv:0)."
    bad = f"MUSICBOX costs 9.00 EUR {contradicts} (bank.csv:0)."

    assert _ask(good, alert=alert).source == "llm"
    _rejected(_ask(bad, alert=alert), "9.00", contradicts)


def test_a_yearly_per_charge_field_and_yearly_cost_agree_and_are_checked() -> None:
    alert = _recurring(interval="yearly", amount="30.00", yearly="30.00")

    assert _ask("The fee is 30.00 EUR a year (bank.csv:0).", alert=alert).source == "llm"
    _rejected(_ask("The fee is 30.00 EUR a month (bank.csv:0).", alert=alert), "30.00", "a month")


def test_a_period_phrase_is_case_insensitive_and_whole_words_only() -> None:
    _rejected(_ask("MUSICBOX costs 10.99 EUR Every Year (bank.csv:0)."), "10.99", "Every Year")
    assert _ask("MUSICBOX 10.99 EUR, see yearly_cost (bank.csv:0).").source == "llm"


def test_an_unknown_interval_states_no_period() -> None:
    alert = _recurring(interval="irregular")

    assert _ask("MUSICBOX costs 10.99 EUR every year (bank.csv:0).", alert=alert).source == "llm"


def test_an_invented_figure_is_reported_by_the_number_guard_first() -> None:
    result = _ask("MUSICBOX costs 10.99 EUR every year, and 55.55 EUR more (bank.csv:0).")

    assert result.source == "fallback"
    assert result.rejected_numbers == ("55.55",)
    assert result.rejected_reason == ""


def test_the_period_check_runs_before_the_index_as_cause_check() -> None:
    answer = "MUSICBOX costs 10.99 EUR every year, due to inflation (bank.csv:0)."
    result = _ask(answer)

    _rejected(result, "10.99", "every year")
    assert result.rejected_reason != REASON_INDEX_AS_CAUSE


def test_the_panel_names_the_period_rejection() -> None:
    meta = _ask("MUSICBOX costs 10.99 EUR every year (bank.csv:0).")
    line = verdict_line(probe_result(TRICK_QUESTIONS[0], meta, _FALLBACK))

    assert line == VERDICT_REJECTED_PERIOD_PREFIX + "`10.99`, `every year`"


def test_field_periods_lists_the_stated_periods_only() -> None:
    assert field_periods(_recurring().data) == {
        "current_amount": "monthly",
        "yearly_cost": "yearly",
    }
    assert field_periods(_duplicate().data) == {"yearly_cost": "yearly"}
    assert field_periods(_fee_rise().data) == {
        "old_amount": "monthly",
        "new_amount": "monthly",
        "extra_cost_per_year": "yearly",
        "yearly_cost": "yearly",
    }
    assert field_periods({"total": "26.97", "first_paid_amount": "14.99"}) == {}


def test_an_alert_with_no_stated_period_is_never_checked() -> None:
    alert = Alert(
        detector="pi.duplicate_invoice",
        severity="critical",
        title="Duplicate invoice",
        source_refs=["invoices.csv:0"],
        data={"total": "484.00"},
    )

    assert find_period_mismatches("It costs 484.00 EUR every month.", alert) == ()


def test_empty_and_figure_free_texts_find_nothing() -> None:
    assert find_period_mismatches("", _recurring()) == ()
    assert find_period_mismatches("It is charged every year.", _recurring()) == ()


# --- Tier 3: properties --------------------------------------------------------------------------

_ALL_PHRASES = [(phrase, period) for period, words in PERIOD_PHRASES.items() for phrase in words]


@settings(max_examples=200)
@given(
    interval=st.sampled_from(["weekly", "monthly", "quarterly", "yearly"]),
    field=st.sampled_from(["current_amount", "yearly_cost"]),
    phrase=st.sampled_from(_ALL_PHRASES),
)
def test_a_lone_figure_is_rejected_exactly_when_the_period_contradicts_its_field(
    interval: str, field: str, phrase: tuple[str, str]
) -> None:
    alert = _recurring(interval=interval, amount="7.25", yearly="91.00")
    figure = "7.25" if field == "current_amount" else "91.00"
    field_period = interval if field == "current_amount" else "yearly"
    words, said = phrase

    found = find_period_mismatches(f"MUSICBOX: {figure} EUR {words} (bank.csv:0).", alert)

    assert found == (() if said == field_period else (figure, words))


@settings(max_examples=200)
@given(text=st.text(max_size=200))
def test_any_text_never_raises(text: str) -> None:
    result = find_period_mismatches(text, _recurring())

    assert isinstance(result, tuple)
    assert all(isinstance(token, str) for token in result)
