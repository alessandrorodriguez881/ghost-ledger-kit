"""Tests for ledger_kit.live_guard (live-guard LG2): pure helpers, no model, no Streamlit."""

import ast
import re
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ledger_kit import live_guard
from ledger_kit.explainer import Explanation
from ledger_kit.live_guard import (
    CAPTION_OFF,
    CAPTION_URL_WITHOUT_KEY,
    LIVE_ASKS_PER_SESSION_LIMIT,
    MSG_LIMIT,
    MSG_NO_ANSWER,
    TRICK_QUESTIONS,
    VERDICT_ACCEPTED,
    VERDICT_REJECTED_PREFIX,
    Counts,
    LiveStatus,
    ProbeResult,
    Segment,
    counter_caption,
    highlight_html,
    highlight_segments,
    live_status,
    no_answer_message,
    probe_result,
    tally,
    verdict_line,
)

ROOT = Path(__file__).resolve().parents[1]
Q = TRICK_QUESTIONS[0]


# --- Tier 1: questions --------------------------------------------------------------------


def test_trick_questions_are_exactly_the_three_of_the_spec() -> None:
    assert [q.id for q in TRICK_QUESTIONS] == ["forecast", "next_month", "with_fees"]
    assert [q.label for q in TRICK_QUESTIONS] == [
        "Forecast: the cost five years from now",
        "Next month: the amount of the next charge",
        "Total including what the rows do not show",
    ]
    assert [q.text for q in TRICK_QUESTIONS] == [
        "If nothing changes, what will this cost me in total five years from now? Give the amount.",
        "What amount will be charged next month? Give the amount.",
        "What is the total cost including any fees, taxes or interest that these rows "
        "do not show? Give the amount.",
    ]


def test_no_digit_in_any_question_text() -> None:
    assert not any(ch.isdigit() for q in TRICK_QUESTIONS for ch in q.text)


# --- Tier 1: live_status ------------------------------------------------------------------


def test_status_off_without_key_and_url() -> None:
    assert live_status({}) == LiveStatus(False, "gpt-4o-mini", CAPTION_OFF)


def test_status_on_with_key_url_and_model() -> None:
    env = {
        "OPENAI_API_KEY": "ollama",
        "OPENAI_BASE_URL": "http://localhost:11434/v1",
        "LEDGER_KIT_LLM_MODEL": "llama3.2:1b",
    }
    assert live_status(env) == LiveStatus(True, "llama3.2:1b", "")


def test_status_url_without_key_has_its_own_caption() -> None:
    status = live_status({"OPENAI_BASE_URL": "http://localhost:11434/v1"})
    assert status == LiveStatus(False, "gpt-4o-mini", CAPTION_URL_WITHOUT_KEY)
    assert "any non-empty key" in CAPTION_URL_WITHOUT_KEY
    assert "Ollama" in CAPTION_URL_WITHOUT_KEY


def test_status_never_contains_key_or_url() -> None:
    env = {"OPENAI_API_KEY": "test-key-not-real", "OPENAI_BASE_URL": "http://base.invalid/v1"}
    text = repr(live_status(env))
    assert "test-key-not-real" not in text
    assert "base.invalid" not in text


def test_status_reports_the_effective_timeout() -> None:
    assert live_status({}).timeout_seconds == 10
    assert live_status({"LEDGER_KIT_LLM_TIMEOUT": "45"}).timeout_seconds == 45
    assert live_status({"LEDGER_KIT_LLM_TIMEOUT": "999"}).timeout_seconds == 10


def test_whitespace_only_key_counts_as_set_like_the_explainer() -> None:
    assert live_status({"OPENAI_API_KEY": " "}).enabled is True


def test_empty_key_is_off() -> None:
    assert live_status({"OPENAI_API_KEY": ""}).enabled is False


def test_status_reads_the_documented_variables_by_name() -> None:
    names = set(re.findall(r'"([A-Z][A-Z0-9_]+)"', Path(live_guard.__file__).read_text("utf-8")))
    assert {"OPENAI_API_KEY", "OPENAI_BASE_URL", "LEDGER_KIT_LLM_MODEL"} <= names


# --- Tier 1: probe_result, tally, texts ---------------------------------------------------


def test_probe_rejected() -> None:
    meta = Explanation("T", "fallback", ("779.40",), raw_answer="Pay 779.40")
    result = probe_result(Q, meta, "T")
    assert result == ProbeResult("forecast", "Pay 779.40", "rejected", ("779.40",), "T")


def test_probe_accepted() -> None:
    result = probe_result(Q, Explanation("ok", "llm", (), raw_answer="ok"), "T")
    assert result.verdict == "accepted"
    assert result.rejected_numbers == ()


def test_probe_unavailable() -> None:
    result = probe_result(Q, Explanation("T", "fallback", ()), "T")
    assert result.verdict == "unavailable"
    assert result.raw_answer == ""


def test_tally_sequence() -> None:
    def make(verdict: str) -> ProbeResult:
        return ProbeResult("forecast", "x", verdict, (), "T")

    counts = Counts(0, 0, 0)
    counts = tally(counts, make("accepted"))
    assert counts == Counts(1, 1, 0)
    counts = tally(counts, make("rejected"))
    assert counts == Counts(2, 2, 1)
    counts = tally(counts, make("unavailable"))
    assert counts == Counts(3, 2, 1)


def test_counter_caption() -> None:
    assert counter_caption(Counts(2, 2, 1)) == "Answers checked: 2 · rejected: 1"
    assert counter_caption(Counts(0, 0, 0)) == "Answers checked: 0 · rejected: 0"


def test_fixed_sentences() -> None:
    assert LIVE_ASKS_PER_SESSION_LIMIT == 30
    assert MSG_LIMIT == "Limit of 30 questions per session reached. Reload the page to start again."
    assert MSG_NO_ANSWER == (
        "The model did not answer (error, empty answer or no reply within 10 seconds). "
        "The card keeps the fixed template. Nothing was counted as checked."
    )
    assert "within 45 seconds" in no_answer_message(45)
    assert VERDICT_ACCEPTED.startswith("✅ Guard verdict: accepted.")
    assert VERDICT_REJECTED_PREFIX.endswith("the alert data: ")


def test_verdict_line_per_verdict() -> None:
    rejected = ProbeResult("forecast", "x", "rejected", ("779.40", "12"), "T")
    assert verdict_line(rejected) == VERDICT_REJECTED_PREFIX + "`779.40`, `12`"
    assert verdict_line(ProbeResult("forecast", "x", "accepted", (), "T")) == VERDICT_ACCEPTED
    assert verdict_line(ProbeResult("forecast", "", "unavailable", (), "T")) == ""


# --- Tier 1: highlight --------------------------------------------------------------------


def test_highlight_amount() -> None:
    raw = "In five years you will have paid 779.40 EUR. Source: bank.csv:0."
    assert highlight_segments(raw, ("779.40",)) == [
        ("In five years you will have paid ", False),
        ("779.40", True),
        (" EUR. Source: bank.csv:0.", False),
    ]


def test_highlight_not_inside_a_longer_figure() -> None:
    segments = highlight_segments("It costs 12,99 EUR or 112,99 EUR", ("12,99",))
    assert [s.text for s in segments if s.flagged] == ["12,99"]
    assert segments[0] == Segment("It costs ", False)


def test_highlight_eu_form_of_an_iso_date() -> None:
    segments = highlight_segments("Renewal on 01/01/2031.", ("2031-01-01",))
    assert [s.text for s in segments if s.flagged] == ["01/01/2031"]


def test_highlight_iso_date_in_iso_form() -> None:
    segments = highlight_segments("Renewal on 2031-01-01.", ("2031-01-01",))
    assert [s.text for s in segments if s.flagged] == ["2031-01-01"]


def test_highlight_html_escapes_the_answer() -> None:
    html = highlight_html("<img src=x onerror=alert(1)> 8765.43", ("8765.43",))
    assert "&lt;img src=x onerror=alert(1)&gt;" in html
    assert "<img" not in html
    assert html.count("<mark") == 1
    assert html.startswith('<pre style="white-space: pre-wrap')
    assert html.endswith("</pre>")


# --- Tier 2: edges ------------------------------------------------------------------------


def test_highlight_edges() -> None:
    assert highlight_segments("", ("1.5",)) == []
    assert highlight_segments("abc", ()) == [("abc", False)]
    assert highlight_segments("abc 1.5", ("",)) == [("abc 1.5", False)]
    assert highlight_segments("abc 1.5", ("9.9",)) == [("abc 1.5", False)]
    assert highlight_segments("7.5 apples", ("7.5",)) == [("7.5", True), (" apples", False)]
    assert highlight_segments("apples 7.5", ("7.5",)) == [("apples ", False), ("7.5", True)]


def test_highlight_token_after_digit_or_separator_is_not_flagged() -> None:
    assert highlight_segments("x 1.50 y", ("50",)) == [("x 1.50 y", False)]
    assert highlight_segments("x 1,50 y", ("50",)) == [("x 1,50 y", False)]
    assert highlight_segments("x 150 y", ("15",)) == [("x 150 y", False)]


def test_highlight_overlapping_tokens_are_merged() -> None:
    segments = highlight_segments("pay 1234.5 now", ("1234.5", "1234"))
    flagged = [s.text for s in segments if s.flagged]
    assert flagged == ["1234.5"]


def test_highlight_html_of_empty_text() -> None:
    assert highlight_html("", ()).endswith("</pre>")


# --- Tier 3: properties -------------------------------------------------------------------

_TEXT = st.text(alphabet=st.sampled_from(list("0123456789.,-/ <>&\"'ab\n")), max_size=60)
_TOKENS = st.lists(st.text(alphabet=st.sampled_from(list("0123456789.,-")), max_size=8), max_size=4)
_TAGS = re.compile(r'<mark style="[^"<>]*">|</mark>|<pre style="[^"<>]*">|</pre>')


def _forms(token: str) -> list[str]:
    forms = [token]
    match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", token)
    if match:
        forms.append(f"{match.group(3)}/{match.group(2)}/{match.group(1)}")
    return forms


@settings(max_examples=200)
@given(raw=_TEXT, tokens=_TOKENS)
def test_segments_join_back_to_raw_and_flag_only_token_forms(raw: str, tokens: list[str]) -> None:
    segments = highlight_segments(raw, tokens)
    assert "".join(s.text for s in segments) == raw
    assert all(s.text for s in segments)
    forms = [f for t in tokens if t for f in _forms(t)]
    for seg in segments:
        if seg.flagged:
            assert any(f in seg.text for f in forms)


@settings(max_examples=200)
@given(raw=_TEXT, tokens=_TOKENS)
def test_flagged_segments_are_disjoint_and_ordered(raw: str, tokens: list[str]) -> None:
    position = 0
    for seg in highlight_segments(raw, tokens):
        assert raw[position : position + len(seg.text)] == seg.text
        position += len(seg.text)
    assert position == len(raw)


@settings(max_examples=200)
@given(raw=st.text(max_size=80), tokens=_TOKENS)
def test_html_has_no_foreign_angle_bracket(raw: str, tokens: list[str]) -> None:
    html = highlight_html(raw, tokens)
    assert "<" not in _TAGS.sub("", html)
    assert ">" not in _TAGS.sub("", html)


@settings(max_examples=200)
@given(verdicts=st.lists(st.sampled_from(["accepted", "rejected", "unavailable"]), max_size=40))
def test_tally_keeps_rejected_le_checked_le_asked(verdicts: list[str]) -> None:
    counts = Counts(0, 0, 0)
    for verdict in verdicts:
        counts = tally(counts, ProbeResult("forecast", "x", verdict, (), "T"))
        assert 0 <= counts.rejected <= counts.checked <= counts.asked


# --- Boundaries ---------------------------------------------------------------------------


def test_module_imports_no_streamlit_and_no_app() -> None:
    tree = ast.parse(Path(live_guard.__file__).read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
    assert "streamlit" not in modules
    assert "apps" not in modules
    assert "openai" not in modules


def test_ledger_kit_still_imports_no_app() -> None:
    for path in (ROOT / "ledger_kit").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"^\s*(from|import)\s+apps\b", text, re.M), path


@pytest.mark.parametrize("name", ["TrickQuestion", "Segment", "Counts", "ProbeResult"])
def test_value_types_are_frozen(name: str) -> None:
    cls = getattr(live_guard, name)
    assert getattr(cls, "__dataclass_params__", None) is None or cls.__dataclass_params__.frozen
