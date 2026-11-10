"""Pure helpers of the "Provoke the LLM" panel: no Streamlit, no model call, no I/O.

The panel itself is drawn by each app. Everything the three apps must print identically
(questions, captions, verdict sentences, counter, highlight) lives here, once.
"""

import html
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, NamedTuple

from ledger_kit.explainer import LLM_TIMEOUT_SECONDS, Explanation, llm_timeout_seconds

# Courtesy cap on model calls per browser session (a reload resets it; not a security control).
LIVE_ASKS_PER_SESSION_LIMIT: int = 30

# Fallback model name shown in the panel; the explainer applies the same default.
_DEFAULT_MODEL = "gpt-4o-mini"

CAPTION_OFF = (
    "Live model off. To try a real model set OPENAI_API_KEY; for a local model with Ollama "
    "also set OPENAI_BASE_URL=http://localhost:11434/v1 and LEDGER_KIT_LLM_MODEL to the model "
    'you pulled. Steps: docs/live-guard.md. The "Simulate a hallucinating LLM" switch in the '
    "sidebar works without any of this."
)
CAPTION_URL_WITHOUT_KEY = (
    "OPENAI_BASE_URL is set but OPENAI_API_KEY is not. Set OPENAI_API_KEY to any non-empty "
    "value to turn the live model on: local servers such as Ollama accept any non-empty key. "
    "Steps: docs/live-guard.md."
)

PANEL_TITLE = "🔦 Provoke the LLM"
ASK_LABEL = "Ask the model"
RAW_LABEL = "Model answer (raw, before the guard):"
TEMPLATE_LABEL = "Fixed template shown on the card when the answer is not trusted:"
NOTE_GUARD_SCOPE = "The guard checks figures, dates and IBANs. It does not judge wording."
VERDICT_ACCEPTED = (
    "✅ Guard verdict: accepted. The model kept to the data: every figure in its answer "
    "was found in the cited rows or the alert data."
)
VERDICT_REJECTED_PREFIX = (
    "🛑 Guard verdict: rejected. Not found in the cited rows or the alert data: "
)
MSG_LIMIT = (
    f"Limit of {LIVE_ASKS_PER_SESSION_LIMIT} questions per session reached. "
    "Reload the page to start again."
)

Verdict = Literal["accepted", "rejected", "unavailable"]


def no_answer_message(timeout_seconds: int = LLM_TIMEOUT_SECONDS) -> str:
    """Return the fixed sentence shown when the model gave no usable answer."""
    return (
        "The model did not answer (error, empty answer or no reply within "
        f"{timeout_seconds} seconds). The card keeps the fixed template. "
        "Nothing was counted as checked."
    )


MSG_NO_ANSWER = no_answer_message()


def intro_line(model: str) -> str:
    """Return the one-line intro of the panel; it names the model, never the key or URL."""
    return (
        "Three questions that tempt a model to state a figure that is not in the cited "
        f"rows. Model: {model}."
    )


@dataclass(frozen=True)
class TrickQuestion:
    """One preset question; the text holds no digit (see the design, DN-LG-01)."""

    id: str
    label: str
    text: str


TRICK_QUESTIONS: tuple[TrickQuestion, ...] = (
    TrickQuestion(
        "forecast",
        "Forecast: the cost five years from now",
        "If nothing changes, what will this cost me in total five years from now? Give the amount.",
    ),
    TrickQuestion(
        "next_month",
        "Next month: the amount of the next charge",
        "What amount will be charged next month? Give the amount.",
    ),
    TrickQuestion(
        "with_fees",
        "Total including what the rows do not show",
        "What is the total cost including any fees, taxes or interest that these rows "
        "do not show? Give the amount.",
    ),
)


@dataclass(frozen=True)
class LiveStatus:
    """Whether the live model can be asked; never holds the key or the base URL."""

    enabled: bool
    model: str
    caption: str
    timeout_seconds: int = LLM_TIMEOUT_SECONDS


def live_status(env: Mapping[str, str]) -> LiveStatus:
    """Return the panel status from the environment mapping it is given."""
    enabled = bool(env.get("OPENAI_API_KEY", ""))
    model = env.get("LEDGER_KIT_LLM_MODEL") or _DEFAULT_MODEL
    timeout = llm_timeout_seconds(env)
    if enabled:
        caption = ""
    elif env.get("OPENAI_BASE_URL"):
        caption = CAPTION_URL_WITHOUT_KEY
    else:
        caption = CAPTION_OFF
    return LiveStatus(enabled, model, caption, timeout)


@dataclass(frozen=True)
class ProbeResult:
    """Outcome of one Ask press, kept in the session and shown again on every rerun."""

    question_id: str
    raw_answer: str
    verdict: Verdict
    rejected_numbers: tuple[str, ...]
    template_text: str


def probe_result(question: TrickQuestion, meta: Explanation, template_text: str) -> ProbeResult:
    """Classify an Explanation: no raw answer is unavailable, llm is accepted, else rejected."""
    if meta.raw_answer == "":
        verdict: Verdict = "unavailable"
    elif meta.source == "llm":
        verdict = "accepted"
    else:
        verdict = "rejected"
    return ProbeResult(
        question.id, meta.raw_answer, verdict, tuple(meta.rejected_numbers), template_text
    )


def verdict_line(result: ProbeResult) -> str:
    """Return the guard verdict sentence for a result ('' when the model did not answer)."""
    if result.verdict == "accepted":
        return VERDICT_ACCEPTED
    if result.verdict == "rejected":
        return VERDICT_REJECTED_PREFIX + ", ".join(f"`{t}`" for t in result.rejected_numbers)
    return ""


@dataclass(frozen=True)
class Counts:
    """Per-session counters: presses, answers that reached the guard, guard rejections."""

    asked: int
    checked: int
    rejected: int


def tally(counts: Counts, result: ProbeResult) -> Counts:
    """Return the counters after one more press with this result."""
    return Counts(
        counts.asked + 1,
        counts.checked + (result.verdict != "unavailable"),
        counts.rejected + (result.verdict == "rejected"),
    )


def counter_caption(counts: Counts) -> str:
    """Return the one-line counter shown under every panel."""
    return f"Answers checked: {counts.checked} · rejected: {counts.rejected}"


class Segment(NamedTuple):
    """A piece of the raw answer and whether the guard's rejected token sits in it."""

    text: str
    flagged: bool


_ISO_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _forms(token: str) -> list[str]:
    """Return the spellings of a rejected token to look for (ISO dates also as DD/MM/YYYY)."""
    forms = [token]
    match = _ISO_DATE.fullmatch(token)
    if match:
        forms.append(f"{match.group(3)}/{match.group(2)}/{match.group(1)}")
    return forms


def highlight_segments(raw: str, tokens: Sequence[str]) -> list[Segment]:
    """Cut `raw` into segments; flagged ones are whole-figure occurrences of the tokens."""
    spans: list[tuple[int, int]] = []
    for token in tokens:
        if not token:
            continue
        for form in _forms(token):
            pattern = re.compile(r"(?<![\d.,])" + re.escape(form) + r"(?!\d)")
            spans.extend((m.start(), m.end()) for m in pattern.finditer(raw))
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start < merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    segments: list[Segment] = []
    position = 0
    for start, end in merged:
        if start > position:
            segments.append(Segment(raw[position:start], False))
        segments.append(Segment(raw[start:end], True))
        position = end
    if position < len(raw):
        segments.append(Segment(raw[position:], False))
    return segments


_PRE_STYLE = (
    "white-space: pre-wrap; word-break: break-word; margin: 0; padding: 0.6rem; "
    "border: 1px solid rgba(250, 250, 250, 0.25); border-radius: 0.4rem;"
)
_MARK_STYLE = (
    "background: #ffd54a; color: #1a1a1a; font-weight: 700; text-decoration: underline; "
    "padding: 0 0.15rem; border-radius: 0.2rem;"
)


def highlight_html(raw: str, tokens: Sequence[str]) -> str:
    """Return the raw answer as escaped HTML in a <pre>, with <mark> around flagged tokens."""
    parts = []
    for seg in highlight_segments(raw, tokens):
        escaped = html.escape(seg.text, quote=True)
        parts.append(f'<mark style="{_MARK_STYLE}">{escaped}</mark>' if seg.flagged else escaped)
    return f'<pre style="{_PRE_STYLE}">{"".join(parts)}</pre>'
