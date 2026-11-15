"""The Home example and the honest labels (guard-honesty part 2, REQ-GH-20 to REQ-GH-22).

Tier 1: record P3 of the 2026-11-10 file is the Home example, today's guard rejects it, the Home
block says what it must say, the labels next to accepted answers and the README say that figures
are checked and wording is not. Tier 2: a missing or malformed file gives None, never an exception;
a recording without a mark gives no block. No model is called and no network is used; every figure
is synthetic or recorded.
"""

import json
import re
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from judge_path_support import COMMITTED_RUN, ROOT, Z1_ALERT_ID, find_case, template_of

from apps.phantom_invoices import explain_support as pi_support
from apps.vampire_fees import settings as vf_settings
from apps.zombie_subscriptions import settings as zs_settings
from ledger_kit import live_guard, replay
from ledger_kit.explainer import Explanation, explain_with_meta
from ledger_kit.live_guard import MARK_STYLE, TRICK_QUESTIONS
from ledger_kit.replay import HOME_EXAMPLE_MARKS, Recording, ReplayClient
from ledger_kit.ui import landing, theme

README = ROOT / "README.md"
HOME_FILE = replay.DEFAULT_HOME_EXAMPLE_PATH
FORECAST = TRICK_QUESTIONS[0]
LABEL_P3 = '<div class="gl-example-label">One recorded answer of llama3.2:3b, 2026-11-10.</div>'


def _verdict(case: Any, text: str, question: str | None = None) -> Explanation:
    """What an app does with a recorded text: the same call, with the replay client."""
    return explain_with_meta(
        case.alert,
        case.rows,
        fallback_template=template_of(case),
        client=ReplayClient(text),
        row_columns=case.columns,
        question=question,
    )


def _home() -> Recording:
    recording = replay.home_example(HOME_FILE)
    assert recording is not None
    return recording


# --- Tier 1: the constants and the recording ------------------------------------------------


def test_the_home_example_constants() -> None:
    folder = ROOT / "data" / "live_runs"
    assert replay.DEFAULT_HOME_EXAMPLE_PATH == folder / "2026-11-10_llama3.2-3b.json"
    assert replay.HOME_EXAMPLE_ID == "P3"
    assert replay.HOME_EXAMPLE_MARKS == ("5%", "617.51")
    # the root conftest points the call-time path at a missing file; the default stays as is
    assert replay.HOME_EXAMPLE_PATH != replay.DEFAULT_HOME_EXAMPLE_PATH
    assert replay.home_example() is None


def test_the_path_is_read_at_call_time(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(replay, "HOME_EXAMPLE_PATH", HOME_FILE)

    assert replay.home_example() == _home()


def test_home_example_returns_record_p3_with_the_model_and_the_date_of_its_file() -> None:
    recording = _home()

    assert recording.model_name == "llama3.2:3b"
    assert recording.date == "2026-11-10"
    assert recording.kind == "probe" and recording.question_id == FORECAST.id
    assert recording.question_text == FORECAST.text
    assert "Assuming a constant interest rate of 5% per annum" in recording.raw_answer
    assert "approximately €617.51" in recording.raw_answer
    stored = json.loads(HOME_FILE.read_text(encoding="utf-8"))["records"]
    [p3] = [r for r in stored if r["id"] == "P3"]
    assert recording.alert_id == p3["alert_id"]
    assert recording.raw_answer == p3["raw_answer"]


def test_the_cards_and_the_panel_still_replay_the_2026_11_11_file() -> None:
    assert replay.DEFAULT_REPLAY_RUN_PATH.name == "2026-11-11_llama3.2-3b_demo.json"
    assert replay.DEFAULT_REPLAY_RUN_PATH != replay.DEFAULT_HOME_EXAMPLE_PATH
    run = replay.load_run(COMMITTED_RUN)
    assert run is not None and run.date == "2026-11-11"
    assert run.first_rejected_probe() is not None  # unchanged


def test_todays_guard_rejects_the_home_example_with_the_rate_and_the_total() -> None:
    recording = _home()
    case = find_case(recording.alert_id)
    assert case is not None

    result = _verdict(case, recording.raw_answer, recording.question_text)

    assert result.source == "fallback"
    assert "617.51" in result.rejected_numbers and "5" in result.rejected_numbers


def test_each_mark_sits_in_the_raw_answer_and_in_a_sentence() -> None:
    recording = _home()

    for mark in HOME_EXAMPLE_MARKS:
        assert mark in recording.raw_answer
        assert recording.sentence_with(mark) is not None
    assert "interest rate of 5%" in (recording.sentence_with("5%") or "")


# --- Tier 1: the Home block -------------------------------------------------------------------


def test_example_html_of_the_home_example_says_what_it_must() -> None:
    block = landing.example_html(_home())

    assert block.startswith('<div class="gl-example">')
    assert LABEL_P3 in block
    assert f"<div>Question: {FORECAST.text}</div>" in block
    assert "The model wrote: “" in block
    assert f'<mark style="{MARK_STYLE}">5%</mark>' in block
    assert f'<mark style="{MARK_STYLE}">617.51</mark>' in block
    assert block.count("<mark") == 2
    assert (
        "No cited row and no alert field holds an interest rate: the model assumed 5% and built "
        "617.51 on it. The number guard: <b>rejected</b>."
    ) in block
    assert '<div class="gl-example-note">' in block
    assert "The guard does no arithmetic." in block
    assert "107.88 × 5 = 539.40: the sum is right" in block
    assert "539.40 is in no cited row" in block
    assert "it does not check the wording" in block


def test_the_example_quotes_the_conclusion_sentence_for_the_total() -> None:
    block = landing.example_html(_home())
    conclusion = (
        "So, the total cost in five years will be approximately "
        f'€<mark style="{MARK_STYLE}">617.51</mark>'
    )

    assert conclusion in block
    assert not re.search(r"A = \s*<mark", block)


def test_last_sentence_with_returns_the_last_sentence_or_none() -> None:
    recording = _home()
    last = recording.last_sentence_with("617.51")

    assert last is not None and last.startswith("So, the total cost in five years")
    assert "A = " not in last
    assert recording.last_sentence_with("no-such-token-9") is None


def test_example_html_is_empty_without_a_recording() -> None:
    assert landing.example_html(None) == ""


def test_example_html_is_empty_when_a_mark_is_missing_from_the_answer() -> None:
    recording = _home()
    for mark in HOME_EXAMPLE_MARKS:
        cut = replace(recording, raw_answer=recording.raw_answer.replace(mark, "x"))
        assert landing.example_html(cut) == ""
    assert landing.example_html(replace(recording, raw_answer="Nothing here.")) == ""


def test_example_html_is_empty_when_the_question_is_not_a_preset() -> None:
    assert landing.example_html(replace(_home(), question_id=None)) == ""
    assert landing.example_html(replace(_home(), question_id="not-a-preset")) == ""


def test_the_note_class_is_styled_like_the_label() -> None:
    css = theme.BASE_CSS
    assert ".gl-example-label" in css and ".gl-example-note" in css


# --- Tier 2: files that cannot give the example ----------------------------------------------


def _write(tmp_path: Path, document: Any) -> Path:
    path = tmp_path / "x.json"
    path.write_text(document if isinstance(document, str) else json.dumps(document), "utf-8")
    return path


def _good_record(**changes: Any) -> dict[str, Any]:
    return {
        "id": "P3",
        "alert_id": "a1",
        "question": FORECAST.text,
        "raw_answer": "Assuming 5% we get approximately €617.51.",
        "observed_source": "fallback",
        "observed_rejected": ["5", "617.51"],
        **changes,
    }


def _document(records: Any, **top: Any) -> dict[str, Any]:
    return {"model": "m:1b (Server 1.0)", "date": "2026-11-10", "records": records, **top}


def test_a_small_valid_file_gives_the_example(tmp_path: Path) -> None:
    recording = replay.home_example(_write(tmp_path, _document([_good_record()])))

    assert recording is not None
    assert recording.model_name == "m:1b" and recording.date == "2026-11-10"
    assert recording.alert_id == "a1" and recording.question_id == FORECAST.id


@pytest.mark.parametrize(
    "document",
    [
        "not json",
        "",
        "[]",
        "null",
        {"date": "2026-11-10", "records": [_good_record()]},
        {"model": "", "date": "2026-11-10", "records": [_good_record()]},
        {"model": 3, "date": "2026-11-10", "records": [_good_record()]},
        {"model": "m", "records": [_good_record()]},
        {"model": "m", "date": "10/11/2026", "records": [_good_record()]},
        {"model": "m", "date": None, "records": [_good_record()]},
        {"model": "m", "date": "2026-11-10"},
        {"model": "m", "date": "2026-11-10", "records": {}},
        _document([]),
        _document(["P3", None, 5]),
        _document([_good_record(id="P4")]),
        _document([_good_record(raw_answer="")]),
        _document([_good_record(raw_answer=5)]),
        _document([_good_record(alert_id="")]),
        _document([_good_record(question="a question nobody preset")]),
        _document([_good_record(question=None)]),
    ],
)
def test_a_malformed_file_gives_none_and_never_raises(tmp_path: Path, document: Any) -> None:
    assert replay.home_example(_write(tmp_path, document)) is None


def test_a_missing_file_a_folder_or_binary_garbage_gives_none(tmp_path: Path) -> None:
    binary = tmp_path / "bin.json"
    binary.write_bytes(b"\xff\xfe\x00\x01\x80")

    assert replay.home_example(tmp_path / "nowhere.json") is None
    assert replay.home_example(tmp_path) is None
    assert replay.home_example(binary) is None


def test_a_changed_file_is_read_again(tmp_path: Path) -> None:
    path = _write(tmp_path, _document([_good_record(id="P4")]))
    assert replay.home_example(path) is None

    path.write_text(json.dumps(_document([_good_record()])), encoding="utf-8")

    assert replay.home_example(path) is not None


# --- Tier 1: the note on Home stays true -----------------------------------------------------


def test_the_gymplus_forecast_answer_is_right_arithmetic_that_the_guard_rejects() -> None:
    run = replay.load_run(COMMITTED_RUN)
    assert run is not None
    recording = run.probe(Z1_ALERT_ID, FORECAST.id)
    assert recording is not None and "539.40" in recording.raw_answer
    case = find_case(Z1_ALERT_ID)
    assert case is not None

    result = _verdict(case, recording.raw_answer, recording.question_text)

    assert result.source == "fallback" and "539.40" in result.rejected_numbers
    assert Decimal("107.88") * 5 == Decimal("539.40")
    assert "107.88 × 5 = 539.40" in landing.EXAMPLE_NOTE


# --- Tier 1: the labels -----------------------------------------------------------------------

LABELS = {
    "VERDICT_ACCEPTED": live_guard.VERDICT_ACCEPTED,
    "BADGE_ACCEPTED": replay.BADGE_ACCEPTED,
    "zs BADGE_LLM": zs_settings.BADGE_LLM,
    "vf BADGE_LLM": vf_settings.BADGE_LLM,
    "pi BADGE_LLM": pi_support.BADGE_LLM,
}


@pytest.mark.parametrize("name", sorted(LABELS))
def test_a_label_next_to_an_accepted_answer_says_figures_checked_wording_not_checked(
    name: str,
) -> None:
    text = LABELS[name].lower()

    assert "figures checked" in text or "figures accepted" in text
    assert "wording not checked" in text


CHECKED_FIGURES = ["VERDICT_ACCEPTED", "zs BADGE_LLM", "vf BADGE_LLM", "pi BADGE_LLM"]


@pytest.mark.parametrize("name", CHECKED_FIGURES)
def test_the_verdict_and_the_llm_badges_say_figures_checked(name: str) -> None:
    assert "figures checked" in LABELS[name].lower()


def test_the_exact_label_texts() -> None:
    assert live_guard.VERDICT_ACCEPTED == (
        "✅ Guard verdict: accepted. Every figure in the answer, in digits or in words, was found "
        "in the cited rows or the alert data. Figures checked; wording not checked."
    )
    assert live_guard.NOTE_GUARD_SCOPE == (
        "The guard checks figures (digits, and numbers in English or Spanish words), dates and "
        "IBANs. It does not judge wording and does no arithmetic."
    )
    badge = "🤖 ✓ LLM text · figures checked by the number guard; wording not checked"
    assert zs_settings.BADGE_LLM == vf_settings.BADGE_LLM == pi_support.BADGE_LLM == badge
    assert replay.BADGE_ACCEPTED == (
        "📼 Recorded answer of {model}, {date}, checked now by the number guard: figures "
        "accepted; wording not checked. No model called."
    )


# --- Tier 1: the README ------------------------------------------------------------------------

LINE_3 = (
    "Financial apps where an LLM may word the explanation but cannot slip in a figure: any "
    "amount, date or IBAN that is not in the cited rows or the alert data, in digits or in "
    "English or Spanish words, sends the card back to a fixed template. It checks figures, "
    "not meaning (see What the guard does not check)."
)
STEP_1 = (
    "1. Open Home. Within three seconds it shows one recorded answer of a real model "
    "(`llama3.2:3b`) that assumed a 5% interest rate found in no row and built 617.51 on it, and "
    "the number guard striking both figures out and showing a fixed template instead. Each app "
    "tile shows that app's own drawing, and the rest of the text is under *How it works*."
)
STEP_4_ADDED = (
    "The model's arithmetic is right (107.88 × 5 = 539.40) and the guard still rejects it: it "
    "does no arithmetic and lets through only figures it finds in the rows."
)
PROMISE = (
    "Ghost Ledger Kit is built around one promise: an LLM touches the explanation layer only. "
    "Every figure it writes must be one the detectors already produced (the alert data) or one "
    "in a cited row, and every alert cites the rows it comes from (`file:row`)."
)


def _readme() -> tuple[str, list[str]]:
    text = README.read_text(encoding="utf-8")
    return text, text.splitlines()


def test_readme_line_3_says_what_the_guard_checks() -> None:
    _, lines = _readme()

    assert lines[2] == LINE_3


def test_readme_judge_steps_1_and_4() -> None:
    _, lines = _readme()

    assert lines[11] == STEP_1
    [step_4] = [line for line in lines if line.startswith("4. On the GYMPLUS card")]
    assert step_4.startswith(
        "4. On the GYMPLUS card, open *Provoke the LLM* and replay the five-year question. "
    )
    assert step_4.endswith(STEP_4_ADDED)


def test_readme_promise_sentence() -> None:
    text, _ = _readme()

    assert PROMISE in text


def test_readme_has_the_section_on_what_the_guard_does_not_check() -> None:
    text, lines = _readme()

    assert "## What the guard does not check" in lines
    section = text.split("## What the guard does not check", 1)[1].split("\n### ", 1)[0]
    assert text.index("**The proof, live.**") < text.index("## What the guard does not check")
    assert "MUSICBOX costs 10.99 EUR every year" in section
    assert "107.88 × 5 = 539.40" in section
    assert "`three months`" in section and "`one of them`" in section
    assert "`3 months` in digits is rejected" in section
    assert "`twenty-first`" in section
    assert "An accepted answer is not a statement that it is true." in section


def test_readme_has_the_decisions_row_of_13_nov() -> None:
    _, lines = _readme()

    rows = [line for line in lines if line.startswith("| 13 Nov |")]
    [row] = [line for line in rows if "number words" in line]
    assert "number words" in row and "real invention" in row and "539.40" in row
    assert "five hundred and forty euros passed" in row
    [other] = [line for line in rows if line is not row]
    assert "its own drawing" in other


def test_readme_no_longer_makes_the_old_claims() -> None:
    text, _ = _readme()

    assert "inventing 539.40" not in text
    assert "can never introduce a figure" not in text
    assert "traceable to an exact row" not in text
