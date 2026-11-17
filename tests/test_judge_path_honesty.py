"""Session 30a (REQ-JP-24 to REQ-JP-28): statements that match the app, readable reasons.

Pins the README and Home texts about what is replayed, the words that explain a rejected
calculation or a foreign currency sign, the one-line-per-calculation rule and the session limit
that only live calls consume. Pure tests: no page except the ones that say so, no network.
"""

import re
from datetime import date
from decimal import Decimal

import pandas as pd
import pytest
from judge_path_support import ROOT, cases_of

import streamlit_app
from apps.phantom_invoices.action_templates import action_for as pi_action_for
from apps.vampire_fees.action_templates import action_for as vf_action_for
from apps.zombie_subscriptions.action_templates import action_for as zs_action_for
from ledger_kit import replay
from ledger_kit.actions import build_draft
from ledger_kit.calc import REASON_CALC_NOT_ALLOWED, Computation, resolve_calculations
from ledger_kit.explainer import Explanation, explain_with_meta, is_currency_token
from ledger_kit.live_guard import (
    LIVE_ASKS_PER_SESSION_LIMIT,
    TRICK_QUESTIONS,
    Counts,
    ProbeResult,
    computed_lines,
    counter_caption,
    limit_reached,
    probe_result,
    tally,
    verdict_line,
)
from ledger_kit.models import Alert

README = (ROOT / "README.md").read_text(encoding="utf-8")
HOW_IT_WORKS = (ROOT / "docs" / "how-it-works.md").read_text(encoding="utf-8")
# The README and the docs file that received its How it works section.
README_AND_HOW_IT_WORKS = (README, HOW_IT_WORKS)
FIVE_YEARS = "What will this cost me in total five years from now? Give the amount."
ACTIONS = {"zs": zs_action_for, "pi": pi_action_for, "vf": vf_action_for}


def _alert(**data: str) -> Alert:
    return Alert(
        detector="x.y", severity="info", title="t", source_refs=["f.csv:0"], data=dict(data)
    )


def _rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": date(2026, 1, 5),
                "amount": Decimal("12.00"),
                "flow": "debit",
                "currency": "EUR",
                "counterparty": "BANCO FICTICIO",
                "source_ref": "f.csv:0",
            }
        ]
    )


def _explain(answer: str, alert: Alert, question: str | None = FIVE_YEARS) -> Explanation:
    return explain_with_meta(
        alert,
        _rows(),
        fallback_template="Fixed {fee_total:money}.",
        client=replay.ReplayClient(answer),
        question=question,
    )


INTEREST = {"interest_total": "61.00", "fee_total": "12.00", "total": "73.00", "currency": "EUR"}


# --- REQ-JP-24: the statements about what is replayed ----------------------------------------


def test_home_says_the_panel_replays_only_on_the_first_critical_card_of_each_app() -> None:
    text = streamlit_app.TRY_IT

    assert "first critical card of each app" in text
    assert "GYMPLUS" in text and "Suministros Ibéricos" in text and "Vampire Fees" in text
    assert "every other card" in text and "API key" in text
    assert "each card replays recorded answers" not in text


def test_readme_says_the_same_about_the_panel() -> None:
    assert "only on the first critical card of each app" in HOW_IT_WORKS
    assert "GYMPLUS" in HOW_IT_WORKS and "Suministros Ibéricos" in HOW_IT_WORKS
    assert "disabled" in HOW_IT_WORKS and "live-model-off" in HOW_IT_WORKS


def test_the_committed_run_records_the_three_questions_on_exactly_three_cards() -> None:
    run = replay.load_run(replay.DEFAULT_REPLAY_RUN_PATH)
    assert run is not None
    recorded = {
        prefix: [c.alert for c in cases_of(prefix) if run.has_probe(c.alert.id)]
        for prefix in ("zs", "pi", "vf")
    }

    assert {prefix: len(alerts) for prefix, alerts in recorded.items()} == {
        "zs": 1,
        "pi": 1,
        "vf": 1,
    }
    for _prefix, [alert] in recorded.items():
        assert alert.severity == "critical"
        assert all(run.probe(alert.id, q.id) for q in TRICK_QUESTIONS if q.id != "with_fees")
    assert sum(len(cases_of(p)) for p in recorded) > 3  # the other cards stay disabled


def test_readme_step_5_is_true_about_exorcise() -> None:
    for document in README_AND_HOW_IT_WORKS:
        assert "On any card, open" not in document
    assert "On most cards, open *Exorcise*" in README
    with_draft = without_draft = 0
    for prefix, action_for in ACTIONS.items():
        for case in cases_of(prefix):
            template = action_for(case.alert)
            draft = None
            if template is not None:
                draft = build_draft(case.alert, case.rows, template, "en", row_columns=case.columns)
            if draft is None:
                without_draft += 1
            else:
                with_draft += 1

    assert without_draft >= 1  # an alert with nothing to claim has no draft
    assert with_draft > without_draft  # and most cards do


def test_readme_step_1_does_not_promise_three_seconds_from_a_cold_start() -> None:
    for document in README_AND_HOW_IT_WORKS:
        assert "Within three seconds" not in document
    assert "Once the page has loaded" in README
    assert "under three seconds" in README and "cold load takes longer" in README


def test_readme_writes_the_formula_as_the_app_does() -> None:
    app_formula = "`5 x yearly_cost 107,88 EUR = 539,40 EUR`"

    assert README.count(app_formula) >= 1  # the judges' step 4
    assert HOW_IT_WORKS.count(app_formula) >= 1  # the placeholder paragraph, moved to docs
    for document in README_AND_HOW_IT_WORKS:
        assert "yearly_cost 107,88 EUR x 5" not in document


def test_readme_states_the_amendment_that_a_figure_equal_to_one_field_is_read_as_it() -> None:
    assert "equals exactly one numeric field" in HOW_IT_WORKS
    assert "read as that field" in HOW_IT_WORKS
    assert "107.88" in HOW_IT_WORKS


def test_readme_says_home_shows_the_10_nov_recording_and_the_apps_the_16_nov_run() -> None:
    assert "Home shows a 10 Nov recording" in HOW_IT_WORKS
    assert "16 Nov run" in HOW_IT_WORKS
    assert "different recorded answer" in HOW_IT_WORKS


# --- REQ-JP-25: reasons in words --------------------------------------------------------------


@pytest.mark.parametrize(
    ("expression", "token", "reason"),
    [
        (
            "2 * interest_total",
            "2",
            "2 is neither a field of the alert nor a number in the question",
        ),
        (
            "interest_total + 61.00",
            "interest_total used more than once",
            "interest_total is used more than once (61.00 is its value, read as that field)",
        ),
        (
            "interest_total * interest_total",
            "interest_total used more than once",
            "interest_total is used more than once",
        ),
        (
            "total + interest_total + fee_total",
            "total = interest_total + fee_total",
            "a total is added to its own parts (total = interest_total + fee_total)",
        ),
        ("rate * 5", "rate", "rate is not a numeric field of the alert"),
    ],
)
def test_a_rejected_calculation_says_why_in_plain_words(
    expression: str, token: str, reason: str
) -> None:
    outcome = resolve_calculations(
        f"Result: [[calc: {expression}]]", dict(INTEREST), question=FIVE_YEARS
    )

    assert outcome.rejected == (token,)
    assert outcome.reasons == (reason,)


def test_reasons_are_kept_in_step_with_the_rejected_parts_and_never_repeat() -> None:
    answer = "[[calc: 2 * interest_total]] and [[calc: 2 * fee_total]] and [[calc: rate]]"

    outcome = resolve_calculations(answer, dict(INTEREST), question=FIVE_YEARS)

    assert outcome.rejected == ("2", "rate")
    assert len(outcome.reasons) == len(outcome.rejected) == 2


def test_an_unclosed_placeholder_has_a_reason_too() -> None:
    outcome = resolve_calculations("Result: [[calc: interest_total", dict(INTEREST), question="x")

    assert outcome.rejected and len(outcome.reasons) == len(outcome.rejected)
    assert all(reason for reason in outcome.reasons)


def test_a_card_without_a_question_says_arithmetic_is_not_allowed() -> None:
    outcome = resolve_calculations("[[calc: interest_total + fee_total]]", dict(INTEREST))

    assert outcome.rejected and "no question" in outcome.reasons[0]


def test_the_explanation_carries_the_reasons_of_a_rejected_calculation() -> None:
    meta = _explain("Cost: [[calc: 2 * interest_total]]. See f.csv:0.", _alert(**INTEREST))

    assert meta.source == "fallback" and meta.rejected_reason == REASON_CALC_NOT_ALLOWED
    assert meta.rejected_why == ("2 is neither a field of the alert nor a number in the question",)


def test_the_replay_badge_and_the_verdict_say_why_a_calculation_was_refused() -> None:
    meta = _explain("Cost: [[calc: interest_total + 61.00]]. See f.csv:0.", _alert(**INTEREST))
    recording = replay.Recording("a", "probe", "forecast", "raw", "testmodel:1b", "2026-11-16")
    _kind, badge = replay.card_badge(recording, meta)
    result = probe_result(TRICK_QUESTIONS[0], meta, "template")
    verdict = verdict_line(result)

    reason = "interest_total is used more than once (61.00 is its value, read as that field)"
    assert reason in badge and reason in verdict
    assert "calculation it will not make" in badge
    assert "not found in the cited rows" not in badge
    assert "not found in the cited rows" not in verdict
    assert "`interest_total used more than once`" in verdict  # the token stays, for the marker


def test_the_calculation_reasons_hold_no_character_that_markdown_would_read() -> None:
    for expression in ("2 * interest_total", "interest_total + 61.00", "rate * 5"):
        outcome = resolve_calculations(
            f"[[calc: {expression}]]", dict(INTEREST), question=FIVE_YEARS
        )
        assert all("*" not in reason and "$" not in reason for reason in outcome.reasons)


def test_a_dollar_sign_on_a_euro_account_is_said_in_words() -> None:
    answer = "Source f.csv:0 shows 12.00 $ in fees."
    meta = _explain(answer, _alert(**INTEREST), question=None)
    recording = replay.Recording("a", "card", None, answer, "testmodel:1b", "2026-11-16")
    _kind, badge = replay.card_badge(recording, meta)
    verdict = verdict_line(probe_result(TRICK_QUESTIONS[1], meta, "template"))

    assert meta.source == "fallback" and meta.rejected_numbers == ("$",)
    [why] = meta.rejected_why
    assert why == (
        "the answer uses a dollar sign, but the currency of the cited rows and the alert data "
        "is EUR"
    )
    assert why in badge and why in verdict
    assert "not found in the cited rows or the alert data: $" not in badge
    assert "not found in the cited rows" not in verdict.lower()


def test_a_figure_and_a_currency_sign_are_both_reported() -> None:
    meta = _explain("Source f.csv:0: 98765.43 $.", _alert(**INTEREST), question=None)
    recording = replay.Recording("a", "card", None, "raw", "testmodel:1b", "2026-11-16")
    _kind, badge = replay.card_badge(recording, meta)

    assert meta.rejected_numbers == ("98765.43", "$")
    assert "not found in the cited rows or the alert data: 98765.43" in badge
    assert "a dollar sign" in badge


def test_a_plain_figure_rejection_keeps_todays_wording() -> None:
    meta = _explain("Source f.csv:0: 98765.43 EUR.", _alert(**INTEREST), question=None)
    recording = replay.Recording("a", "card", None, "raw", "testmodel:1b", "2026-11-16")
    _kind, badge = replay.card_badge(recording, meta)

    assert meta.rejected_why == ()
    assert "rejected (not found in the cited rows or the alert data: 98765.43)." in badge


def test_is_currency_token() -> None:
    assert is_currency_token("$") and is_currency_token("€") and is_currency_token("GBP")
    assert not is_currency_token("12.00") and not is_currency_token("2")


# --- REQ-JP-26: each distinct line once, in order ---------------------------------------------


def _computation(name: str, shown: str) -> Computation:
    formula = f"{name} 107,88 EUR x 5 = {shown}"
    return Computation(f"{name} * 5", (), Decimal("539.40"), shown, formula)


def test_the_same_line_is_printed_once_and_the_order_is_kept() -> None:
    first, second = _computation("yearly_cost", "539,40 EUR"), _computation("other", "1,00 EUR")

    lines = computed_lines((first, second, first, second, first))

    assert lines == (first.line, second.line)
    assert computed_lines(()) == ()
    assert computed_lines((first,)) == (first.line,)


def test_no_recorded_answer_of_the_committed_run_prints_a_line_twice() -> None:
    run = replay.load_run(replay.DEFAULT_REPLAY_RUN_PATH)
    assert run is not None
    duplicated = 0
    for prefix in ("zs", "pi", "vf"):
        for case in cases_of(prefix):
            for recording, question in _recordings(run, case.alert.id):
                meta = explain_with_meta(
                    case.alert,
                    case.rows,
                    fallback_template="x",
                    client=replay.ReplayClient(recording.raw_answer),
                    row_columns=case.columns,
                    question=question,
                )
                lines = computed_lines(meta.computed)
                assert len(lines) == len(set(lines))
                duplicated += len(meta.computed) > len(lines)

    assert duplicated >= 1  # the GYMPLUS recording has two placeholders of one calculation


def _recordings(run: replay.ReplayRun, alert_id: str) -> list[tuple[replay.Recording, str | None]]:
    found: list[tuple[replay.Recording, str | None]] = []
    card = run.card(alert_id)
    if card is not None:
        found.append((card, None))
    for question in TRICK_QUESTIONS:
        probe = run.probe(alert_id, question.id)
        if probe is not None:
            found.append((probe, question.text))
    return found


# --- REQ-JP-27: only live calls use the session limit -------------------------------------------


def _result() -> ProbeResult:
    return ProbeResult("forecast", "text", "accepted", (), "template")


def test_a_replay_press_is_counted_but_does_not_use_the_limit() -> None:
    counts = Counts(0, 0, 0)
    for _ in range(LIVE_ASKS_PER_SESSION_LIMIT + 5):
        counts = tally(counts, _result(), replayed=True)

    assert counts.asked == counts.checked == counts.replayed == LIVE_ASKS_PER_SESSION_LIMIT + 5
    assert counts.live_asked == 0
    assert not limit_reached(counts)


def test_live_presses_use_the_limit_and_replays_do_not_add_to_it() -> None:
    counts = Counts(0, 0, 0)
    for _ in range(LIVE_ASKS_PER_SESSION_LIMIT - 1):
        counts = tally(counts, _result())
    counts = tally(counts, _result(), replayed=True)  # one replay between the live ones

    assert counts.live_asked == LIVE_ASKS_PER_SESSION_LIMIT - 1 and not limit_reached(counts)
    assert limit_reached(tally(counts, _result()))


def test_the_old_three_field_counts_still_work_and_mean_live_presses() -> None:
    assert Counts(3, 2, 1).replayed == 0 and Counts(3, 2, 1).live_asked == 3
    assert limit_reached(Counts(LIVE_ASKS_PER_SESSION_LIMIT, 0, 0))


def test_the_counter_caption_is_unchanged_without_replays_and_labels_them_with() -> None:
    assert counter_caption(Counts(2, 2, 1)) == "Answers checked: 2 · rejected: 1"
    caption = counter_caption(Counts(3, 3, 1, 2))
    assert caption == "Answers checked: 3 · rejected: 1 · recorded replays: 2"


def test_the_apps_use_the_limit_helper_and_pass_the_replay_flag() -> None:
    for name in ("zombie_subscriptions", "phantom_invoices", "vampire_fees"):
        source = (ROOT / "apps" / name / "app.py").read_text(encoding="utf-8")
        assert "limit_reached(counts)" in source
        assert "counts.asked < LIVE_ASKS_PER_SESSION_LIMIT" not in source
        assert re.search(r"tally\(\s*st\.session_state\[LG_COUNTS_KEY\],[^)]*replayed=", source)
