"""A year on its own gets its own words (guard-honesty amendment A-GH-01, REQ-GH-24, REQ-GH-25).

The number guard matches a date to the dates of the rows only when the date has a day: ISO, the
DD/MM/YYYY form, English `June 18, 2025` and `18 June 2025`, and `June 18` by month and day. A
year on its own (`in 2026`, `June 2026`) is read as a plain number. These tests pin that behaviour
as it is, then the words of the badge and of the verdict for such a year, and they pin the outcome
of every record of the run the apps replay, so the wording change is shown to change no verdict.
No model, no network, no clock; every figure is synthetic or recorded.
"""

import json
import re
from datetime import date
from decimal import Decimal
from functools import cache
from typing import Any

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from judge_path_support import REPLAY_RUN, ROOT, find_case, template_of

from apps.vampire_fees import settings as vf_settings
from ledger_kit import replay
from ledger_kit.calc import REASON_CALC_NOT_ALLOWED
from ledger_kit.explainer import Explanation, check_figures, explain_with_meta
from ledger_kit.index_cause import REASON_INDEX_AS_CAUSE
from ledger_kit.live_guard import (
    BADGE_NOT_FOUND,
    BADGE_YEAR_ALONE,
    TRICK_QUESTIONS,
    VERDICT_REJECTED_HEAD,
    VERDICT_REJECTED_PREFIX,
    VERDICT_YEAR_ALONE,
    YEAR_DIGITS,
    YEAR_MAX,
    YEAR_MIN,
    ProbeResult,
    is_year_alone,
    probe_result,
    rejection_clause,
    rejection_reason_text,
    verdict_line,
)
from ledger_kit.models import Alert

DOLLAR_WHY = (
    "the answer uses a dollar sign, but the currency of the cited rows and the alert data is EUR"
)


# --- The date forms the guard reads today (finding of session s50) ------------------------------


def _alert() -> Alert:
    """A synthetic alert: one date and one amount in its data, one cited row."""
    return Alert(
        detector="x.y",
        severity="info",
        title="t",
        source_refs=["f.csv:0"],
        data={"first_charge_date": "2025-06-18", "total": "106.00"},
    )


def _rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": date(2026, 5, 8),
                "amount": Decimal("106.00"),
                "flow": "debit",
                "currency": "EUR",
                "counterparty": "BANCO FICTICIO",
                "source_ref": "f.csv:0",
            }
        ]
    )


DATE_FORMS = [
    # A date with a day is matched to the date cells of the rows and the dates of the alert data.
    ("Charged 106.00 EUR on 2026-05-08.", True, ()),
    ("Charged on 08/05/2026.", True, ()),
    ("The first charge was on June 18, 2025.", True, ()),
    ("The first charge was on 18 June 2025.", True, ()),
    ("The first charge was on June 18.", True, ()),  # no year: month and day
    ("Charged on 2026-05-09.", False, ("2026-05-09",)),
    ("The first charge was on June 19, 2025.", False, ("2025-06-19",)),
    # A year on its own, or a month and a year, leaves the year as a plain number.
    ("These charges started in 2026.", False, ("2026",)),
    ("The first charge was in June 2025.", False, ("2025",)),
    # A Spanish month name is not read as a date: the day and the year are plain numbers.
    ("El primer cargo fue el 18 de junio de 2025.", False, ("18", "2025")),
]


@pytest.mark.parametrize(("text", "passed", "tokens"), DATE_FORMS)
def test_each_date_form_is_judged_as_it_is_today(
    text: str, passed: bool, tokens: tuple[str, ...]
) -> None:
    assert check_figures(text, _alert(), _rows()) == (passed, tokens)


def test_a_year_alone_passes_when_the_same_number_is_in_the_data() -> None:
    """It is a number check, not a date check: an invoice number holding 2026 lets 2026 pass."""
    alert = _alert().model_copy(update={"data": {**_alert().data, "invoice": "F-2026-0310"}})

    assert check_figures("These charges started in 2026.", alert, _rows()) == (True, ())


# --- The year test -----------------------------------------------------------------------------


def test_the_year_constants() -> None:
    assert (YEAR_MIN, YEAR_MAX, YEAR_DIGITS) == (1900, 2099, 4)


@pytest.mark.parametrize("token", ["1900", "2025", "2026", "2099"])
def test_a_plain_four_digit_number_in_range_is_a_year(token: str) -> None:
    assert is_year_alone(token)


@pytest.mark.parametrize(
    "token",
    [
        "1899",
        "2100",
        "0202",
        "202",
        "20260",
        "2026.00",
        "2.026",
        "2026,00",
        "2026-05-08",
        "€2026",
        "2026%",
        "+2026",
        " 2026",
        "\uff12\uff10\uff12\uff16",  # full-width digits
        "$",
        "twenty twenty-six",
        "",
    ],
)
def test_anything_else_is_not_a_year(token: str) -> None:
    assert not is_year_alone(token)


# --- The words of the badge --------------------------------------------------------------------


def test_a_year_alone_says_so_in_the_badge() -> None:
    clause = rejection_clause("", ("2026",), ())

    assert clause == " (a year on its own is not matched to the dates of the rows: 2026)"
    assert BADGE_NOT_FOUND not in clause


def test_two_years_share_one_phrase() -> None:
    assert rejection_clause("", ("2025", "2026"), ()) == (
        " (a year on its own is not matched to the dates of the rows: 2025, 2026)"
    )


def test_a_year_and_another_figure_have_one_parenthesis_and_two_phrases() -> None:
    assert rejection_clause("", ("24", "2026"), ()) == (
        " (not found in the cited rows or the alert data: 24; "
        "a year on its own is not matched to the dates of the rows: 2026)"
    )


@pytest.mark.parametrize(
    "tokens", [("98765.43",), ("2026.00",), ("2.026",), ("2100",), ("1899",), ("18", "539.40")]
)
def test_other_figures_keep_the_old_wording(tokens: tuple[str, ...]) -> None:
    expected = f" ({BADGE_NOT_FOUND}: {', '.join(tokens)})"

    assert rejection_clause("", tokens, ()) == expected


def test_a_year_and_a_currency_sign_each_say_their_reason() -> None:
    clause = rejection_clause("", ("2026", "$"), (DOLLAR_WHY,))

    assert clause == f" ({BADGE_YEAR_ALONE}: 2026; {DOLLAR_WHY})"


def test_a_calculation_or_an_index_rejection_keeps_its_own_words() -> None:
    calc = rejection_clause(REASON_CALC_NOT_ALLOWED, ("2026",), ("2026 is not allowed",))

    assert calc == (
        " (the answer asks the kit for a calculation it will not make: 2026 is not allowed)"
    )
    sentence = "The rise is due to the 2026 CPI."
    assert rejection_reason_text(REASON_INDEX_AS_CAUSE, (sentence,), ()) == (
        f"the answer names the price index as the cause of the price change: {sentence}"
    )


def test_the_reason_text_of_a_card_badge() -> None:
    assert rejection_reason_text("", ("2025", "2026"), ()) == (
        "a year on its own is not matched to the dates of the rows: 2025, 2026"
    )
    assert rejection_reason_text("", ("24", "2026"), ()) == (
        f"{BADGE_NOT_FOUND}: 24; {BADGE_YEAR_ALONE}: 2026"
    )
    assert rejection_reason_text("", ("539.40",), ()) == f"{BADGE_NOT_FOUND}: 539.40"


# --- The words of the verdict of the Provoke panel ---------------------------------------------


def _rejected(tokens: tuple[str, ...], why: tuple[str, ...] = ()) -> ProbeResult:
    return ProbeResult("forecast", "raw", "rejected", tokens, "T", "", (), "", why)


def test_the_verdict_of_a_year_alone() -> None:
    assert verdict_line(_rejected(("2026",))) == (
        "🛑 Guard verdict: rejected. A year on its own is not matched to the dates of the rows: "
        "`2026`"
    )


def test_the_verdict_of_a_year_and_another_figure() -> None:
    assert verdict_line(_rejected(("24", "2026"))) == (
        VERDICT_REJECTED_PREFIX + "`24`. " + VERDICT_YEAR_ALONE + "`2026`"
    )


def test_the_verdict_without_a_year_is_unchanged() -> None:
    assert verdict_line(_rejected(("779.40", "12"))) == VERDICT_REJECTED_PREFIX + "`779.40`, `12`"


def test_the_verdict_of_a_year_and_a_currency_sign() -> None:
    assert verdict_line(_rejected(("2026", "$"), (DOLLAR_WHY,))) == (
        VERDICT_REJECTED_HEAD + VERDICT_YEAR_ALONE + "`2026`. " + DOLLAR_WHY + "."
    )


# --- The run the apps replay: the same verdicts before and after -------------------------------

RECORDS: list[dict[str, Any]] = json.loads(REPLAY_RUN.read_text(encoding="utf-8"))["records"]
RECORD_IDS = [record["id"] for record in RECORDS]
BY_ID = {record["id"]: record for record in RECORDS}

# Every record of 2026-11-16_llama3.2-3b_calc2.json that goes back to the fixed template, with
# its reason and its rejected tokens, as computed before the wording change (session s50) and as
# the run itself recorded them. Every other record is accepted with no token.
EXPECTED_REJECTED: dict[str, tuple[str, tuple[str, ...]]] = {
    "Z03": ("", ("$",)),
    "Z04": (
        REASON_INDEX_AS_CAUSE,
        (
            "The price change is attributed to the IPC290751 CPI series, which is based on the "
            "2025 base year.",
        ),
    ),
    "Z05": (
        REASON_INDEX_AS_CAUSE,
        ("The price change is attributed to the CPI series IPC290751, which started in May 2026.",),
    ),
    "Z22": (REASON_CALC_NOT_ALLOWED, ("8.99",)),
    "P27": ("", ("24", "2026")),
    "P32": (REASON_CALC_NOT_ALLOWED, ("2",)),
    "V37": ("", ("2025", "2026")),
    "V41": (REASON_CALC_NOT_ALLOWED, ("total = interest_total + fee_total",)),
    "V42": (REASON_CALC_NOT_ALLOWED, ("12.40",)),
    "V43": (REASON_CALC_NOT_ALLOWED, ("interest_total used more than once",)),
}
EXPECTED_RECORD_COUNT = 43
EXPECTED_REJECTED_COUNT = 10


@cache
def _explanation(record_id: str) -> Explanation:
    """Today's guard on one recorded answer, exactly as the replay runs it."""
    record = BY_ID[record_id]
    case = find_case(record["alert_id"])
    assert case is not None, f"{record_id}: its alert is not in today's demo"
    return explain_with_meta(
        case.alert,
        case.rows,
        fallback_template=template_of(case),
        client=replay.ReplayClient(record["raw_answer"]),
        row_columns=case.columns,
        question=record.get("question") or None,
    )


def test_the_run_has_43_records_and_10_go_back_to_the_template() -> None:
    assert len(RECORDS) == EXPECTED_RECORD_COUNT
    assert len(set(RECORD_IDS)) == EXPECTED_RECORD_COUNT
    assert set(EXPECTED_REJECTED) <= set(RECORD_IDS)
    assert len(EXPECTED_REJECTED) == EXPECTED_REJECTED_COUNT


def test_the_pinned_outcomes_are_the_ones_the_run_recorded() -> None:
    for record in RECORDS:
        rejected = record["id"] in EXPECTED_REJECTED
        reason, tokens = EXPECTED_REJECTED.get(record["id"], ("", ()))
        # The run file writes figure_not_found where Explanation.rejected_reason is empty.
        recorded_reason = (reason or "figure_not_found") if rejected else ""
        assert record["observed_source"] == ("fallback" if rejected else "llm"), record["id"]
        assert tuple(record["observed_rejected"]) == tokens, record["id"]
        assert record["observed_reason"] == recorded_reason, record["id"]


@pytest.mark.parametrize("record_id", RECORD_IDS)
def test_todays_guard_gives_each_record_its_pinned_outcome(record_id: str) -> None:
    result = _explanation(record_id)
    reason, tokens = EXPECTED_REJECTED.get(record_id, ("", ()))

    assert result.source == ("fallback" if record_id in EXPECTED_REJECTED else "llm")
    assert result.rejected_numbers == tokens
    assert result.rejected_reason == reason


def _badge(record_id: str) -> str:
    run = replay.load_run(REPLAY_RUN)
    assert run is not None
    recording = run.card(BY_ID[record_id]["alert_id"])
    assert recording is not None and recording.raw_answer == BY_ID[record_id]["raw_answer"]
    kind, label = replay.card_badge(recording, _explanation(record_id))
    assert kind == "rejected"
    return label


def test_the_bank_fees_card_says_the_years_are_on_their_own() -> None:
    assert _badge("V37") == (
        "📼 Recorded answer of llama3.2:3b, 2026-11-16, checked now by the number guard: "
        "rejected (a year on its own is not matched to the dates of the rows: 2025, 2026). "
        "Fixed template shown. No model called."
    )


def test_the_phantom_card_keeps_not_found_for_24_and_names_the_year() -> None:
    assert _badge("P27") == (
        "📼 Recorded answer of llama3.2:3b, 2026-11-16, checked now by the number guard: "
        "rejected (not found in the cited rows or the alert data: 24; "
        "a year on its own is not matched to the dates of the rows: 2026). "
        "Fixed template shown. No model called."
    )


def test_the_dollar_card_badge_is_unchanged() -> None:
    label = _badge("Z03")

    assert "a dollar sign" in label
    assert BADGE_YEAR_ALONE not in label and BADGE_NOT_FOUND not in label


def test_the_live_badge_of_vampire_fees_names_the_years() -> None:
    badge = vf_settings.guard_badge(_explanation("V37"), has_api_key=True)

    assert badge.kind == "rejected"
    assert badge.label == (
        "⚠️ LLM answer rejected: a year on its own is not matched to the dates of the rows: "
        "2025, 2026"
    )


def test_the_panel_verdict_of_the_bank_fees_answer() -> None:
    result = probe_result(TRICK_QUESTIONS[0], _explanation("V37"), "T")

    assert verdict_line(result) == VERDICT_REJECTED_HEAD + VERDICT_YEAR_ALONE + "`2025`, `2026`"


# --- The README says what these tests show -----------------------------------------------------


def _readme_section() -> str:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    after = text.split("## What the guard does not check", 1)[1]
    return re.split(r"\n#{1,6} ", after, maxsplit=1)[0]


def test_readme_has_the_dates_bullet() -> None:
    section = _readme_section()
    [line] = [item for item in section.splitlines() if item.startswith("- **Dates.**")]

    for form in ("`2026-05-08`", "`08/05/2026`", "`June 18, 2025`", "`18 June 2025`"):
        assert form in line
    assert "A year on its own (`in 2026`, `June 2026`)" in line
    assert "`18 de junio de 2025`" in line


def test_the_meaning_example_of_v35_is_true() -> None:
    record = BY_ID["V35"]
    case = find_case(record["alert_id"])
    assert case is not None
    data = case.alert.data

    assert record["title"] == "Overdraft cost on this statement"
    assert "€61.00" in record["raw_answer"] and "€106.00" in record["raw_answer"]
    assert (data["interest_total"], data["total"]) == ("61.00", "106.00")
    assert Decimal(data["interest_total"]) + Decimal(data["fee_total"]) == Decimal(data["total"])
    assert _explanation("V35").source == "llm"
    section = _readme_section()
    [line] = [item for item in section.splitlines() if item.startswith("- **Meaning.**")]
    assert "record V35 of the 16 Nov run" in line
    assert "61.00 is `interest_total`" in line and "106.00 is `total`" in line


# --- Tier 3: properties ------------------------------------------------------------------------


def _old_clause(tokens: tuple[str, ...]) -> str:
    """The clause of a figure rejection before session s50."""
    return " (not found in the cited rows or the alert data: " + ", ".join(tokens) + ")"


def _not_a_year(token: str) -> bool:
    return not is_year_alone(token)


_NOT_YEARS = st.lists(
    st.text(alphabet="0123456789.,", min_size=1, max_size=8).filter(_not_a_year),
    min_size=1,
    max_size=4,
).map(tuple)


@settings(max_examples=200, deadline=None)
@given(tokens=_NOT_YEARS)
def test_without_a_year_the_clause_is_the_old_one(tokens: tuple[str, ...]) -> None:
    assert rejection_clause("", tokens, ()) == _old_clause(tokens)


@settings(max_examples=200, deadline=None)
@given(year=st.integers(min_value=YEAR_MIN, max_value=YEAR_MAX))
def test_any_year_on_its_own_is_rejected_and_said_as_a_year(year: int) -> None:
    passed, tokens = check_figures(f"These charges started in {year}.", _alert(), _rows())

    assert (passed, tokens) == (False, (str(year),))
    assert rejection_clause("", tokens, ()) == f" ({BADGE_YEAR_ALONE}: {year})"
