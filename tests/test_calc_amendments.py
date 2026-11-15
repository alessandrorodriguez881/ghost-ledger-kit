"""Amendments A-MC-01 to A-MC-05 of model-computes, from the first real run (sessions 28b, 28c).

The raw answers of Z03, Z04, Z06, Z20, Z21, P32, V41 and V43 are the ones recorded in
`data/live_runs/2026-11-15_llama3.2-3b_calc.json`, read from that file and run through
`explain_with_meta` exactly as the replay does. The unit tests use small synthetic alerts.
No network, no model. All data is synthetic.
"""

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from judge_path_support import RUNS, find_case, template_of

from ledger_kit.calc import (
    COMPUTED_MARK,
    REASON_CALC_NOT_ALLOWED,
    CalcOutcome,
    numeric_fields,
    resolve_calculations,
)
from ledger_kit.explainer import CALC_PROMPT_RULE, Explanation, explain_with_meta
from ledger_kit.models import Alert
from ledger_kit.replay import ReplayClient

RUN_FILE = RUNS / "2026-11-15_llama3.2-3b_calc.json"
_FIVE_YEARS = "If nothing changes, what will this cost me in total five years from now?"
# The system prompt of a card with no question as it was before 15 Nov, word for word, for an
# alert that cites bank.csv:0.
_OLD_PROMPT = (
    "You must not invent any number, date, name, or amount. "
    "Every figure you mention must appear verbatim either in the source rows provided or in the "
    "structured fields of the alert (such as yearly_cost). "
    "Do not derive, round, or estimate any figure not explicitly present in those inputs. "
    "Cite at least one source reference from: ['bank.csv:0']. "
    "Answer in plain prose of at most three sentences: no lists, no JSON, no repetition "
    "of the input. Write source references exactly as given. "
    "Write every date exactly as given, in YYYY-MM-DD form."
)
_TEMPLATE = "Charge {current_amount:money}, {yearly_cost:money} per year ({source_refs})."


def _record(record_id: str) -> dict[str, Any]:
    """One record of the 15 Nov run file."""
    document = json.loads(RUN_FILE.read_text(encoding="utf-8"))
    [record] = [r for r in document["records"] if r["id"] == record_id]
    return record


def _replayed(record_id: str) -> Explanation:
    """The record's raw answer through today's guard, as the replay does it."""
    record = _record(record_id)
    case = find_case(record["alert_id"])
    assert case is not None, f"{record_id}: its alert is not in today's demo"
    return explain_with_meta(
        case.alert,
        case.rows,
        fallback_template=template_of(case),
        client=ReplayClient(record["raw_answer"]),
        row_columns=case.columns,
        question=record.get("question") or None,
    )


# --- The recorded answers (A-MC-02, A-MC-03) ----------------------------------------------


def test_z03_a_field_wrapped_in_a_placeholder_is_read_as_that_field() -> None:
    assert "[[calc: 359.76]]" in _record("Z03")["raw_answer"]

    result = _replayed("Z03")

    assert result.source == "llm"
    assert result.rejected_numbers == ()
    [computation] = result.computed
    assert computation.result == Decimal("359.76")
    assert [o.name for o in computation.operands] == ["yearly_cost"]
    assert computation.formula == "yearly_cost 359,76 EUR = 359,76 EUR"
    assert computation.line == (
        f"{COMPUTED_MARK} computed by the kit: yearly_cost 359,76 EUR = 359,76 EUR, "
        "from the alert fields."
    )
    assert f"total yearly cost of 359,76 EUR{COMPUTED_MARK}." in result.text
    assert "[[calc" not in result.text


def test_z20_the_literal_of_a_field_is_read_as_the_field() -> None:
    answer = _record("Z20")["raw_answer"]
    assert "[[calc: 5 * yearly_cost]]" in answer
    assert "[[calc: 5 * 107.88]]" in answer

    result = _replayed("Z20")

    assert result.source == "llm"
    assert result.rejected_numbers == ()
    assert [c.result for c in result.computed] == [Decimal("539.40"), Decimal("539.40")]
    # The provenance names the field, not the literal.
    assert [c.formula for c in result.computed] == [
        "5 x yearly_cost 107,88 EUR = 539,40 EUR",
        "5 x yearly_cost 107,88 EUR = 539,40 EUR",
    ]
    assert [[o.name for o in c.operands] for c in result.computed] == [["yearly_cost"]] * 2
    assert result.text.count(f"539,40 EUR{COMPUTED_MARK}") == 2
    assert "[[calc" not in result.text


def test_z21_stays_rejected_because_8_99_is_no_field_of_this_alert() -> None:
    assert "[[calc: 8.99 + (amount - 8.99)]]" in _record("Z21")["raw_answer"]

    result = _replayed("Z21")

    assert result.source == "fallback"
    assert result.rejected_numbers == ("8.99",)
    assert result.rejected_reason == REASON_CALC_NOT_ALLOWED
    assert result.computed == ()


def test_the_z21_alert_has_no_field_amount_and_no_field_8_99() -> None:
    case = find_case(_record("Z21")["alert_id"])
    assert case is not None

    fields = numeric_fields(case.alert.data)

    assert "amount" not in fields
    assert Decimal("8.99") not in fields.values()


def test_p32_stays_rejected_because_the_two_is_invented() -> None:
    assert "[[calc: 484.00 * 2 * 5]]" in _record("P32")["raw_answer"]

    result = _replayed("P32")

    assert result.source == "fallback"
    assert result.rejected_numbers == ("2",)
    assert result.rejected_reason == REASON_CALC_NOT_ALLOWED
    assert result.computed == ()


def test_the_p32_alert_does_have_a_field_equal_to_two_but_a_whole_number_is_no_figure() -> None:
    case = find_case(_record("P32")["alert_id"])
    assert case is not None

    assert case.alert.data["invoice_count"] == 2


def test_v41_adds_a_total_and_its_own_two_parts_and_is_rejected_with_the_reason() -> None:
    assert "[[calc: (106.00 + 61.00 + 45.00) * 5]]" in _record("V41")["raw_answer"]

    result = _replayed("V41")

    assert result.source == "fallback"
    assert result.rejected_numbers == ("total = interest_total + fee_total",)
    assert result.rejected_reason == REASON_CALC_NOT_ALLOWED
    assert result.computed == ()


def test_z06_keeps_a_whole_number_the_question_does_not_give_rejected() -> None:
    assert "[[calc: 179.88 * 12]]" in _record("Z06")["raw_answer"]

    result = _replayed("Z06")

    assert result.source == "fallback"
    assert result.rejected_numbers == ("12",)
    assert result.rejected_reason == REASON_CALC_NOT_ALLOWED


def test_z04_a_plain_card_with_arithmetic_is_rejected_a_mc_04() -> None:
    assert "[[calc: 155.88 + 36.00]]" in _record("Z04")["raw_answer"]
    assert not _record("Z04").get("question")

    result = _replayed("Z04")

    assert result.source == "fallback"
    assert result.rejected_numbers == ("155.88 + 36.00",)
    assert result.rejected_reason == REASON_CALC_NOT_ALLOWED
    assert result.computed == ()


def test_v43_a_field_minus_itself_is_rejected_a_mc_05() -> None:
    assert "[[calc: interest_total - 61.00]]" in _record("V43")["raw_answer"]

    result = _replayed("V43")

    assert result.source == "fallback"
    assert result.rejected_numbers == ("interest_total used more than once",)
    assert result.rejected_reason == REASON_CALC_NOT_ALLOWED
    assert result.computed == ()


def test_z21_is_rejected_and_its_shape_is_also_a_mc_05_on_an_alert_with_that_field() -> None:
    # On the real alert the 8.99 is no field (test above). The same shape on an alert that does
    # have a field `amount` of 8.99 uses that field three times.
    data = {"amount": "8.99", "yearly_cost": "107.88"}

    outcome = _resolve("8.99 + (amount - 8.99)", data=data)

    assert outcome.rejected == ("amount used more than once",)
    assert outcome.computed == ()


# --- A-MC-01: the prompt ------------------------------------------------------------------


@dataclass
class _Msg:
    content: str


@dataclass
class _Choice:
    message: _Msg


@dataclass
class _Response:
    choices: list[_Choice]


class _MockLLMClient:
    """Mock client that answers with the given text and keeps every call."""

    def __init__(self, answer: str) -> None:
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


def _alert(data: dict[str, Any] | None = None) -> Alert:
    return Alert(
        detector="zs.recurring_charge",
        severity="warning",
        title="Recurring charge",
        source_refs=["bank.csv:0"],
        data={"current_amount": "8.99", "yearly_cost": "107.88"} if data is None else data,
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


def _system_message(question: str | None) -> str:
    client = _MockLLMClient("GYMPLUS costs 107.88 EUR per year (bank.csv:0).")
    explain_with_meta(
        _alert(), _rows(), fallback_template=_TEMPLATE, client=client, question=question
    )
    return client.calls[0]["messages"][0]["content"]


def test_a_card_with_no_question_gets_the_prompt_it_had_before_15_nov() -> None:
    assert _system_message(None) == _OLD_PROMPT


def test_an_empty_question_is_no_question() -> None:
    assert _system_message("") == _OLD_PROMPT


def test_a_plain_card_prompt_has_no_placeholder_instruction() -> None:
    prompt = _system_message(None)

    assert "[[calc" not in prompt
    assert "EXPRESSION" not in prompt


def test_a_question_adds_the_placeholder_rule_after_the_old_prompt() -> None:
    prompt = _system_message(_FIVE_YEARS)

    assert prompt == _OLD_PROMPT + " " + CALC_PROMPT_RULE
    assert "[[calc: EXPRESSION]]" in prompt


def test_the_user_message_does_not_change_with_the_rule() -> None:
    plain, asked = _MockLLMClient("ok bank.csv:0"), _MockLLMClient("ok bank.csv:0")

    explain_with_meta(_alert(), _rows(), fallback_template=_TEMPLATE, client=plain)
    explain_with_meta(
        _alert(), _rows(), fallback_template=_TEMPLATE, client=asked, question=_FIVE_YEARS
    )

    user_plain = plain.calls[0]["messages"][1]["content"]
    user_asked = asked.calls[0]["messages"][1]["content"]
    assert user_asked == user_plain + "\n\nQuestion from the user: " + _FIVE_YEARS


# --- A-MC-02: a figure that is one field --------------------------------------------------

_DATA = {
    "yearly_cost": "107.88",
    "current_amount": "8.99",
    "charge_count": 12,
    "total": "100.00",
    "twin_total": "100.00",
}


def _resolve(expression: str, question: str | None = _FIVE_YEARS, data=None):
    return resolve_calculations(
        f"Total: [[calc: {expression}]] (bank.csv:0).",
        _DATA if data is None else data,
        question=question,
    )


def test_a_decimal_equal_to_exactly_one_field_is_that_field() -> None:
    outcome = _resolve("107.88 * 5")

    assert outcome.rejected == ()
    [computation] = outcome.computed
    assert computation.formula == "yearly_cost 107,88 EUR x 5 = 539,40 EUR"
    assert [o.name for o in computation.operands] == ["yearly_cost"]


def test_the_literal_and_the_name_give_the_same_computation() -> None:
    by_name = _resolve("yearly_cost - current_amount").computed
    by_literal = _resolve("107.88 - 8.99").computed

    assert [c.formula for c in by_literal] == [c.formula for c in by_name]
    assert by_literal[0].result == Decimal("98.89")


def test_a_decimal_equal_to_two_fields_with_different_names_is_ambiguous() -> None:
    outcome = _resolve("100.00 * 5")

    assert outcome.rejected == ("100.00",)
    assert outcome.computed == ()


def test_the_same_value_written_with_other_zeros_is_still_ambiguous() -> None:
    assert _resolve("100.0 * 5").rejected == ("100.0",)


def test_the_name_of_one_of_two_equal_fields_is_still_allowed() -> None:
    outcome = _resolve("total * 5")

    assert outcome.rejected == ()
    assert outcome.computed[0].result == Decimal("500.00")


def test_a_decimal_equal_to_no_field_is_rejected_as_before() -> None:
    assert _resolve("107.89 * 5").rejected == ("107.89",)
    assert _resolve("yearly_cost * 1.05").rejected == ("1.05",)


def test_a_whole_number_equal_to_a_field_is_not_read_as_that_field() -> None:
    # charge_count is 12, the question gives only 5: the 12 is an invented constant.
    outcome = _resolve("yearly_cost * 12")

    assert outcome.rejected == ("12",)


def test_a_whole_number_of_the_question_is_still_a_constant() -> None:
    assert _resolve("yearly_cost * 5").computed[0].result == Decimal("539.40")
    assert _resolve("yearly_cost * 12", "twelve months").computed[0].result == Decimal("1294.56")


def test_a_literal_that_is_not_plain_decimal_text_is_rejected() -> None:
    assert _resolve("1e2").rejected == ("1e2",)
    assert _resolve(".5").rejected == (".5",)
    assert _resolve("1_0.5").rejected == ("1_0.5",)


def test_a_negative_literal_of_a_field_works() -> None:
    outcome = _resolve("-107.88 * 5")

    assert outcome.computed[0].result == Decimal("-539.40")
    assert outcome.computed[0].operands[0].name == "yearly_cost"


def test_text_that_is_not_a_plain_number_is_no_field_for_a_figure() -> None:
    data = {"yearly_cost": "107.88", "counterparty": "107.88x"}

    outcome = _resolve("107.88 * 5", data=data)

    assert outcome.rejected == ()
    assert [o.name for o in outcome.computed[0].operands] == ["yearly_cost"]


# --- A-MC-03: double counting -------------------------------------------------------------

_PARTS = {"total": "106.00", "interest_total": "61.00", "fee_total": "45.00", "fee_count": 4}


def _double_count_parts(outcome: CalcOutcome) -> tuple[str, set[str]]:
    """The total and the set of parts named by the one rejection of a double count."""
    [reason] = outcome.rejected
    total, _, parts = reason.partition(" = ")
    return total, set(parts.split(" + "))


def test_a_total_added_to_its_two_parts_is_rejected_with_the_reason() -> None:
    outcome = _resolve("(total + interest_total + fee_total) * 5", data=_PARTS)

    assert outcome.rejected == ("total = interest_total + fee_total",)
    assert outcome.computed == ()


@pytest.mark.parametrize(
    "expression",
    [
        "interest_total + total + fee_total",
        "fee_total + (interest_total + total)",
        "106.00 + 61.00 + 45.00",
        "total + (fee_total + interest_total)",
    ],
)
def test_the_same_with_figures_in_any_order_and_parentheses(expression: str) -> None:
    outcome = _resolve(expression, data=_PARTS)

    assert outcome.computed == ()
    assert _double_count_parts(outcome) == ("total", {"interest_total", "fee_total"})


def test_the_total_alone_and_the_two_parts_alone_are_fine() -> None:
    total_alone = _resolve("total * 5", data=_PARTS)
    parts_alone = _resolve("(interest_total + fee_total) * 5", data=_PARTS)

    assert total_alone.computed[0].result == Decimal("530.00")
    assert parts_alone.computed[0].result == Decimal("530.00")


def test_a_total_and_only_one_part_is_not_the_pattern() -> None:
    outcome = _resolve("total + interest_total", data=_PARTS)

    assert outcome.rejected == ()
    assert outcome.computed[0].result == Decimal("167.00")


def test_a_total_minus_its_parts_is_not_adding_it() -> None:
    outcome = _resolve("total - interest_total - fee_total", data=_PARTS)

    assert outcome.rejected == ()
    assert outcome.computed[0].result == Decimal("0.00")


def test_the_total_and_the_parts_in_different_sums_are_not_one_sum() -> None:
    outcome = _resolve("total * (interest_total + fee_total)", data=_PARTS)

    assert outcome.rejected == ()


def test_three_parts_that_make_a_total_are_found() -> None:
    data = {"total": "10.00", "a_total": "1.00", "b_total": "2.00", "c_total": "7.00"}

    outcome = _resolve("total + a_total + b_total + c_total", data=data)

    assert outcome.rejected == ("total = a_total + b_total + c_total",)


def test_two_parts_of_a_larger_set_are_found() -> None:
    data = {"total": "10.00", "a_total": "3.00", "b_total": "7.00", "other_total": "99.00"}

    outcome = _resolve("other_total + total + a_total + b_total", data=data)

    assert outcome.rejected == ("total = a_total + b_total",)


def test_a_part_of_value_zero_is_no_part() -> None:
    data = {"total": "5.00", "a_total": "5.00", "zero_total": "0.00", "other_zero": "0.00"}

    outcome = _resolve("total + a_total + zero_total + other_zero", data=data)

    assert outcome.rejected == ()


def test_the_same_field_twice_is_rejected_by_a_mc_05_not_as_double_counting() -> None:
    data = {"total": "10.00", "a_total": "5.00"}

    outcome = _resolve("total + total + a_total", data=data)

    assert outcome.rejected == ("total used more than once",)


def test_a_bad_part_is_reported_before_double_counting() -> None:
    outcome = _resolve("total + interest_total + fee_total + missing", data=_PARTS)

    assert outcome.rejected == ("missing",)


def test_one_double_counted_placeholder_rejects_the_good_one_too() -> None:
    answer = "[[calc: total * 5]] and [[calc: total + interest_total + fee_total]]"

    outcome = resolve_calculations(answer, _PARTS, question="five")

    assert outcome.rejected == ("total = interest_total + fee_total",)
    assert outcome.computed == ()


# --- A-MC-04: a card with no question holds no arithmetic -----------------------------------


def test_a_plain_card_accepts_one_field_by_name() -> None:
    outcome = _resolve("yearly_cost", question=None)

    assert outcome.rejected == ()
    assert outcome.computed[0].result == Decimal("107.88")


def test_a_plain_card_accepts_one_figure_equal_to_one_field() -> None:
    outcome = _resolve("107.88", question=None)

    assert outcome.rejected == ()
    assert [o.name for o in outcome.computed[0].operands] == ["yearly_cost"]


@pytest.mark.parametrize(
    "expression",
    ["yearly_cost + current_amount", "107.88 - 8.99", "-yearly_cost", "(yearly_cost)  * 1"],
)
def test_any_operator_on_a_plain_card_rejects_the_answer(expression: str) -> None:
    outcome = _resolve(expression, question=None)

    assert outcome.computed == ()
    assert outcome.rejected


def test_the_rejected_part_of_a_plain_card_is_the_expression() -> None:
    outcome = _resolve("yearly_cost + current_amount", question=None)

    assert outcome.rejected == ("yearly_cost + current_amount",)


def test_an_empty_question_is_a_plain_card_too() -> None:
    assert _resolve("yearly_cost + current_amount", question="").rejected


def test_with_a_question_the_same_arithmetic_is_computed() -> None:
    outcome = _resolve("yearly_cost + current_amount")

    assert outcome.rejected == ()
    assert outcome.computed[0].result == Decimal("116.87")


def test_a_question_mode_single_use_expression_is_accepted() -> None:
    outcome = _resolve("5 * yearly_cost")

    assert outcome.rejected == ()
    assert outcome.computed[0].result == Decimal("539.40")


# --- A-MC-05: a field is used once per placeholder ------------------------------------------


@pytest.mark.parametrize(
    ("expression", "field"),
    [
        ("yearly_cost - yearly_cost", "yearly_cost"),
        ("yearly_cost - 107.88", "yearly_cost"),
        ("107.88 + 107.88", "yearly_cost"),
        ("yearly_cost + (current_amount - yearly_cost)", "yearly_cost"),
        ("current_amount + 107.88 + (yearly_cost - 8.99)", "current_amount"),
    ],
)
def test_a_field_used_twice_rejects_the_answer(expression: str, field: str) -> None:
    outcome = _resolve(expression)

    assert outcome.computed == ()
    assert outcome.rejected == (f"{field} used more than once",)


def test_the_same_field_in_two_placeholders_is_fine() -> None:
    answer = "[[calc: yearly_cost * 5]] and [[calc: yearly_cost * 2]]"

    outcome = resolve_calculations(answer, _DATA, question="five and two")

    assert outcome.rejected == ()
    assert len(outcome.computed) == 2


def test_two_fields_of_the_same_value_are_two_fields_when_named() -> None:
    outcome = _resolve("total + twin_total")

    assert outcome.rejected == ()
    assert outcome.computed[0].result == Decimal("200.00")


# --- explainer: the whole flow ------------------------------------------------------------


def test_the_explainer_rejects_arithmetic_on_a_plain_card_with_calc_not_allowed() -> None:
    answer = "The yearly cost is [[calc: yearly_cost + current_amount]] (bank.csv:0)."

    result = explain_with_meta(
        _alert(), _rows(), fallback_template=_TEMPLATE, client=_MockLLMClient(answer)
    )

    assert result.source == "fallback"
    assert result.rejected_numbers == ("yearly_cost + current_amount",)
    assert result.rejected_reason == REASON_CALC_NOT_ALLOWED
    assert result.computed == ()


def test_the_explainer_rejects_a_double_count_with_calc_not_allowed() -> None:
    alert = _alert({"total": "106.00", "interest_total": "61.00", "fee_total": "45.00"})
    answer = "Over five years: [[calc: (total + interest_total + fee_total) * 5]] (bank.csv:0)."

    result = explain_with_meta(
        alert,
        _rows(),
        fallback_template="Cost ({source_refs}).",
        client=_MockLLMClient(answer),
        question=_FIVE_YEARS,
    )

    assert result.source == "fallback"
    assert result.rejected_numbers == ("total = interest_total + fee_total",)
    assert result.rejected_reason == REASON_CALC_NOT_ALLOWED
    assert result.raw_answer == answer


def test_the_explainer_accepts_a_wrapped_field_on_a_card_with_no_question() -> None:
    answer = "The yearly cost is [[calc: 107.88]] (bank.csv:0)."

    result = explain_with_meta(
        _alert(),
        _rows(),
        fallback_template=_TEMPLATE,
        client=_MockLLMClient(answer),
    )

    assert result.source == "llm"
    assert result.text == f"The yearly cost is 107,88 EUR{COMPUTED_MARK} (bank.csv:0)."
    assert result.computed[0].formula == "yearly_cost 107,88 EUR = 107,88 EUR"


# --- Hypothesis ---------------------------------------------------------------------------

_ATOMS = st.sampled_from(
    [
        "total",
        "interest_total",
        "fee_total",
        "fee_count",
        "106.00",
        "61.00",
        "45.00",
        "5",
        "7.00",
        "unknown_field",
    ]
)


def _expressions() -> st.SearchStrategy[str]:
    return st.recursive(
        _ATOMS,
        lambda inner: st.one_of(
            st.builds(lambda a, op, b: f"{a} {op} {b}", inner, st.sampled_from("+-*/"), inner),
            st.builds(lambda a: f"({a})", inner),
        ),
        max_leaves=8,
    )


@settings(max_examples=200, deadline=None)
@given(expression=_expressions())
def test_with_figures_and_double_counting_it_still_computes_or_rejects_and_never_raises(
    expression: str,
) -> None:
    outcome = _resolve(expression, question="five", data=_PARTS)

    assert bool(outcome.rejected) != bool(outcome.computed)


# --- the recorded file itself -------------------------------------------------------------


@pytest.mark.parametrize("record_id", ["Z03", "Z04", "Z06", "Z20", "Z21", "P32", "V41", "V43"])
def test_the_records_read_here_hold_a_placeholder(record_id: str) -> None:
    assert "[[calc" in _record(record_id)["raw_answer"]
