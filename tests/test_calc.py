"""Tests for ledger_kit/calc.py and money.combine: the model asks, the kit computes.

Pure tests, no model and no network. All data is synthetic.
"""

from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ledger_kit.calc import (
    CALC_EXPRESSION_MAX_CHARS,
    COMPUTED_MARK,
    GUARD_MARKER,
    REASON_CALC_NOT_ALLOWED,
    numeric_fields,
    question_integers,
    resolve_calculations,
)
from ledger_kit.utils.money import combine

_DATA = {
    "yearly_cost": Decimal("107.88"),
    "current_amount": Decimal("8.99"),
    "charge_count": 12,
    "price_change_percent": "18.5",
    "counterparty": "GYMPLUS",
    "cpi_start_month": "2025-03",
    "flag": True,
}
_QUESTION = "If nothing changes, what will this cost me in total five years from now?"
_ZERO_DIVISOR = "yearly_cost / (current_amount - current_amount)"


def _resolve(expression: str, question: str | None = _QUESTION, data=None, money=frozenset()):
    return resolve_calculations(
        f"Total: [[calc: {expression}]] (bank.csv:0).",
        _DATA if data is None else data,
        question=question,
        money_fields=money,
    )


# --- money.combine ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("operator", "expected"),
    [("+", "12"), ("-", "8"), ("*", "20"), ("/", "5")],
)
def test_combine_four_operators(operator: str, expected: str) -> None:
    other = Decimal(2)

    assert combine(operator, Decimal(10), other) == Decimal(expected)


def test_combine_keeps_full_precision() -> None:
    assert combine("/", Decimal(1), Decimal(3)) != Decimal("0.33")


def test_combine_rejects_zero_division_and_unknown_operator() -> None:
    with pytest.raises(ZeroDivisionError):
        combine("/", Decimal(1), Decimal(0))
    with pytest.raises(ValueError):
        combine("**", Decimal(1), Decimal(2))


# --- the fields and the question ----------------------------------------------------------


def test_numeric_fields_are_decimals_ints_and_plain_number_text_only() -> None:
    fields = numeric_fields(_DATA)

    assert fields == {
        "yearly_cost": Decimal("107.88"),
        "current_amount": Decimal("8.99"),
        "charge_count": Decimal(12),
        "price_change_percent": Decimal("18.5"),
    }


def test_question_integers_read_digits_and_english_and_spanish_words() -> None:
    assert question_integers("in 5 years") == {5}
    assert question_integers("in five years") == {5}
    assert question_integers("dentro de cinco años") == {5}
    assert question_integers("twenty-four months or 12 of them") == {24, 12}


def test_question_integers_skip_decimals_and_dates() -> None:
    assert question_integers("a rate of 1.05 on 2026-11-10") == frozenset()
    assert question_integers(None) == frozenset()
    assert question_integers("") == frozenset()


# --- accepted -----------------------------------------------------------------------------


def test_a_computed_amount_replaces_the_placeholder_with_a_marked_figure() -> None:
    outcome = _resolve("yearly_cost * 5", money=frozenset({"yearly_cost"}))

    assert outcome.rejected == ()
    assert outcome.text == f"Total: 539,40 EUR{COMPUTED_MARK} (bank.csv:0)."
    assert outcome.guard_text == f"Total: {GUARD_MARKER} (bank.csv:0)."
    (computation,) = outcome.computed
    assert computation.expression == "yearly_cost * 5"
    assert computation.result == Decimal("539.40")
    operands = [(o.name, o.value) for o in computation.operands]
    assert operands == [("yearly_cost", Decimal("107.88"))]
    assert computation.formula == "yearly_cost 107,88 EUR x 5 = 539,40 EUR"
    assert computation.line == (
        f"{COMPUTED_MARK} computed by the kit: yearly_cost 107,88 EUR x 5 = 539,40 EUR, "
        "from the alert fields."
    )


def test_a_field_named_like_an_amount_is_money_without_the_template() -> None:
    assert _resolve("yearly_cost * 5").computed[0].shown == "539,40 EUR"


def test_a_count_is_not_money() -> None:
    outcome = _resolve("charge_count * 5")

    assert outcome.computed[0].shown == "60"


def test_parentheses_subtraction_and_several_operands() -> None:
    outcome = _resolve("(yearly_cost - current_amount) * 5")

    (computation,) = outcome.computed
    assert computation.result == Decimal("494.45")
    assert computation.formula == (
        "(yearly_cost 107,88 EUR - current_amount 8,99 EUR) x 5 = 494,45 EUR"
    )
    assert [o.name for o in computation.operands] == ["yearly_cost", "current_amount"]


def test_a_share_is_a_plain_number_not_an_amount() -> None:
    outcome = _resolve("current_amount / yearly_cost * 5")

    assert outcome.computed[0].shown == "0,42"


def test_unary_minus_is_allowed() -> None:
    assert _resolve("-yearly_cost * 5").computed[0].shown == "-539,40 EUR"


def test_the_result_is_rounded_half_up_at_the_end_only() -> None:
    data = {"fee_amount": Decimal("0.125")}

    outcome = _resolve("fee_amount * 1", question="one", data=data)

    assert outcome.computed[0].result == Decimal("0.13")
    assert outcome.computed[0].shown == "0,13 EUR"


def test_intermediate_precision_is_kept() -> None:
    data = {"fee_amount": Decimal("1")}

    outcome = _resolve("fee_amount / 3 * 3", question="three", data=data)

    assert outcome.computed[0].result == Decimal("1.00")


def test_the_currency_of_the_alert_data_is_used() -> None:
    data = {"yearly_cost": Decimal("10.00"), "currency": "GBP"}

    assert _resolve("yearly_cost * 5", data=data).computed[0].shown == "50,00 GBP"


def test_several_placeholders_are_replaced_in_order() -> None:
    answer = "A [[calc: yearly_cost * 5]] and B [[calc: yearly_cost * 2]] (bank.csv:0)."

    outcome = resolve_calculations(answer, _DATA, question="five and two")

    assert outcome.text == (
        f"A 539,40 EUR{COMPUTED_MARK} and B 215,76 EUR{COMPUTED_MARK} (bank.csv:0)."
    )
    assert outcome.guard_text == f"A {GUARD_MARKER} and B {GUARD_MARKER} (bank.csv:0)."
    assert len(outcome.computed) == 2


def test_an_answer_without_a_placeholder_is_returned_unchanged() -> None:
    answer = "GYMPLUS costs 107.88 per year (bank.csv:0)."

    outcome = resolve_calculations(answer, _DATA, question=_QUESTION)

    assert outcome.text == outcome.guard_text == answer
    assert outcome.computed == ()
    assert outcome.rejected == ()


def test_the_placeholder_keyword_is_not_case_sensitive_and_spaces_are_free() -> None:
    answer = "[[ CALC :yearly_cost*5 ]]"

    outcome = resolve_calculations(answer, _DATA, question="five")

    assert outcome.computed[0].result == Decimal("539.40")


# --- rejected -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("expression", "question", "part"),
    [
        ("yearly_cost * 1.05", "five years, one time", "1.05"),
        ("yearly_cost * 5", "in total from now", "5"),
        ("yearly_cost * 6", _QUESTION, "6"),
        ("monthly_cost * 5", _QUESTION, "monthly_cost"),
        ("counterparty * 5", _QUESTION, "counterparty"),
        ("flag * 5", _QUESTION, "flag"),
        ("yearly_cost ** 5", _QUESTION, "yearly_cost ** 5"),
        ("yearly_cost % 5", _QUESTION, "yearly_cost % 5"),
        ("yearly_cost // 5", _QUESTION, "yearly_cost // 5"),
        ("round(yearly_cost)", _QUESTION, "round(yearly_cost)"),
        ("yearly_cost.real", _QUESTION, "yearly_cost.real"),
        ("+yearly_cost", _QUESTION, "+yearly_cost"),
        ("yearly_cost / 0", "divided by 0", "yearly_cost / 0"),
        (_ZERO_DIVISOR, "five", _ZERO_DIVISOR),
        ("yearly_cost x 5", _QUESTION, "yearly_cost x 5"),
        ("5.0", _QUESTION, "5.0"),
        ("True", _QUESTION, "True"),
        ("'five'", _QUESTION, "'five'"),
        ("", _QUESTION, "(empty)"),
        ("yearly_cost *", _QUESTION, "yearly_cost *"),
    ],
)
def test_a_part_that_is_not_allowed_rejects_the_whole_answer(
    expression: str, question: str, part: str
) -> None:
    outcome = _resolve(expression, question=question)

    assert outcome.rejected == (part,)
    assert outcome.computed == ()
    assert outcome.text == outcome.guard_text == f"Total: [[calc: {expression}]] (bank.csv:0)."


def test_one_bad_placeholder_rejects_the_good_one_too() -> None:
    answer = "[[calc: yearly_cost * 5]] and [[calc: yearly_cost * 1.05]]"

    outcome = resolve_calculations(answer, _DATA, question=_QUESTION)

    assert outcome.rejected == ("1.05",)
    assert outcome.computed == ()


def test_a_placeholder_that_is_not_closed_is_rejected() -> None:
    outcome = resolve_calculations("Total [[calc: yearly_cost * 5", _DATA, question=_QUESTION)

    assert outcome.rejected == ("[[calc",)


def test_an_expression_over_the_length_limit_is_rejected() -> None:
    expression = " + ".join(["yearly_cost"] * 30)
    assert len(expression) > CALC_EXPRESSION_MAX_CHARS

    assert _resolve(expression).rejected


def test_a_division_by_a_field_that_is_zero_is_rejected() -> None:
    data = {"yearly_cost": Decimal("10.00"), "charge_count": 0}

    outcome = _resolve("yearly_cost / charge_count", data=data)

    assert outcome.rejected == ("yearly_cost / charge_count",)


def test_an_overflow_is_a_rejection_not_an_exception() -> None:
    data = {"yearly_cost": Decimal("9E+999999990")}

    outcome = _resolve("yearly_cost * yearly_cost", data=data)

    assert outcome.rejected
    assert outcome.computed == ()


def test_the_reason_name_is_stable() -> None:
    assert REASON_CALC_NOT_ALLOWED == "calc_not_allowed"


# --- Hypothesis: it computes or it rejects, it never raises -------------------------------

_NAMES = st.sampled_from(["yearly_cost", "current_amount", "charge_count", "unknown_field"])
_QUESTION_NUMBERS = st.sampled_from(["5", "12", "0", "7", "1.05"])
_OPERATORS = st.sampled_from(["+", "-", "*", "/", "**", "%", "//", "x", ""])
_ATOMS = st.one_of(_NAMES, _QUESTION_NUMBERS)


def _expressions() -> st.SearchStrategy[str]:
    return st.recursive(
        _ATOMS,
        lambda inner: st.one_of(
            st.builds(lambda a, op, b: f"{a} {op} {b}", inner, _OPERATORS, inner),
            st.builds(lambda a: f"({a})", inner),
            st.builds(lambda a: f"-{a}", inner),
        ),
        max_leaves=8,
    )


@settings(max_examples=200, deadline=None)
@given(expression=_expressions())
def test_an_expression_of_allowed_pieces_computes_or_rejects_and_never_raises(
    expression: str,
) -> None:
    outcome = _resolve(expression, question="five, twelve, zero and seven")

    assert bool(outcome.rejected) != bool(outcome.computed)
    if outcome.computed:
        assert outcome.computed[0].result == outcome.computed[0].result.quantize(Decimal("0.01"))
        assert outcome.guard_text == f"Total: {GUARD_MARKER} (bank.csv:0)."


@settings(max_examples=200, deadline=None)
@given(text=st.text(max_size=120))
def test_any_text_in_a_placeholder_never_raises(text: str) -> None:
    outcome = resolve_calculations(f"x [[calc:{text}]] y", _DATA, question=_QUESTION)

    assert bool(outcome.rejected) != bool(outcome.computed)


@settings(max_examples=200, deadline=None)
@given(answer=st.text(max_size=200))
def test_any_answer_never_raises(answer: str) -> None:
    outcome = resolve_calculations(answer, _DATA, question=_QUESTION)

    assert isinstance(outcome.rejected, tuple)
