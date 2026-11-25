"""Pure helpers of the "Provoke the LLM" panel: no Streamlit, no model call, no I/O.

The panel itself is drawn by each app. Everything the three apps must print identically
(questions, captions, verdict sentences, counter, highlight) lives here, once.
"""

import html
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, NamedTuple

from ledger_kit.calc import REASON_CALC_NOT_ALLOWED, Computation
from ledger_kit.explainer import (
    LLM_TIMEOUT_SECONDS,
    REASON_PERIOD_MISMATCH,
    Explanation,
    is_currency_token,
    llm_timeout_seconds,
)
from ledger_kit.index_cause import REASON_INDEX_AS_CAUSE

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
REPLAY_ASK_LABEL = "Replay the recorded answer"  # the button while the answers are recorded


def ask_label(*, live: bool, replayable: bool) -> str:
    """Return the button label: Ask the model with a key or without a recording, else Replay."""
    return REPLAY_ASK_LABEL if replayable and not live else ASK_LABEL


RAW_LABEL = "Model answer (raw, before the guard):"
TEMPLATE_LABEL = "Fixed template shown on the card when the answer is not trusted:"
NOTE_GUARD_SCOPE = (
    "The guard checks figures (digits, and numbers in English or Spanish words), dates and "
    "IBANs. It does not judge wording, except a period that contradicts the field a figure "
    "matches and the price index named as the cause of a price change. It does no arithmetic."
)
VERDICT_ACCEPTED = (
    "✅ Guard verdict: accepted. Every figure the model wrote itself, in digits or in words, was "
    "found in the cited rows or the alert data; a figure in a calc placeholder was computed by "
    "the kit. Figures checked; wording not checked."
)
VERDICT_REJECTED_HEAD = "🛑 Guard verdict: rejected. "
VERDICT_NOT_FOUND = "Not found in the cited rows or the alert data: "
VERDICT_REJECTED_PREFIX = VERDICT_REJECTED_HEAD + VERDICT_NOT_FOUND
VERDICT_REJECTED_INDEX_CAUSE_PREFIX = (
    "🛑 Guard verdict: rejected. The answer names the price index as the cause of the price "
    "change; the kit gives the index as context only: "
)
VERDICT_REJECTED_CALC_PREFIX = (
    "🛑 Guard verdict: rejected. The answer asks the kit for a calculation it will not make "
    "(only the numeric fields of the alert, whole numbers of the question and + - * / are "
    "allowed): "
)
VERDICT_REJECTED_PERIOD_PREFIX = (
    "🛑 Guard verdict: rejected. The answer gives a figure a period that contradicts the alert "
    "field it matches (the figure, then the period words): "
)
SHOWN_LABEL = "Answer as shown, with the figures the kit computed:"
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
    reason: str = ""  # Explanation.rejected_reason: "" for a figure, else why the tokens were
    # The accepted answer as shown on a card (placeholders replaced) and the calculations behind
    # it; both empty when the model asked for none.
    computed: tuple[Computation, ...] = ()
    shown_text: str = ""
    # Explanation.rejected_why: the rejection in words (a calculation refused, a foreign currency).
    why: tuple[str, ...] = ()


def computed_lines(computed: Sequence[Computation]) -> tuple[str, ...]:
    """Return the line of small text of each distinct calculation the kit made, in order.

    Two placeholders of one calculation (the same formula and result) print one line.
    """
    return tuple(dict.fromkeys(c.line for c in computed))


def probe_result(question: TrickQuestion, meta: Explanation, template_text: str) -> ProbeResult:
    """Classify an Explanation: no raw answer is unavailable, llm is accepted, else rejected."""
    if meta.raw_answer == "":
        verdict: Verdict = "unavailable"
    elif meta.source == "llm":
        verdict = "accepted"
    else:
        verdict = "rejected"
    return ProbeResult(
        question.id,
        meta.raw_answer,
        verdict,
        tuple(meta.rejected_numbers),
        template_text,
        meta.rejected_reason,
        tuple(meta.computed),
        meta.text if meta.computed else "",
        tuple(meta.rejected_why),
    )


def verdict_line(result: ProbeResult) -> str:
    """Return the guard verdict sentence for a result ('' when the model did not answer)."""
    if result.verdict == "accepted":
        return VERDICT_ACCEPTED
    if result.verdict == "rejected":
        prefix = VERDICT_REJECTED_PREFIX
        if result.reason == REASON_INDEX_AS_CAUSE:
            prefix = VERDICT_REJECTED_INDEX_CAUSE_PREFIX
        elif result.reason == REASON_CALC_NOT_ALLOWED:
            prefix = VERDICT_REJECTED_CALC_PREFIX
        elif result.reason == REASON_PERIOD_MISMATCH:
            prefix = VERDICT_REJECTED_PERIOD_PREFIX
        elif result.why:
            return _currency_verdict(result)
        elif any(is_year_alone(t) for t in result.rejected_numbers):
            parts = _verdict_figure_parts(shown_tokens(result.rejected_numbers, result.raw_answer))
            return VERDICT_REJECTED_HEAD + ". ".join(parts)
        tokens = result.rejected_numbers
        if result.reason not in (REASON_INDEX_AS_CAUSE, REASON_CALC_NOT_ALLOWED):
            tokens = shown_tokens(tokens, result.raw_answer)
        line = prefix + ", ".join(f"`{t}`" for t in tokens)
        if result.reason == REASON_CALC_NOT_ALLOWED and result.why:
            line += ". Why: " + "; ".join(result.why) + "."
        return line
    return ""


def _currency_verdict(result: ProbeResult) -> str:
    """The verdict of an answer with a currency sign the data does not name, in words.

    A figure rejected with it keeps the usual wording, a year on its own gets its own words, and
    the sign gets its own sentence.
    """
    shown = shown_tokens(result.rejected_numbers, result.raw_answer)
    figures = [t for t in shown if not is_currency_token(t)]
    line = VERDICT_REJECTED_HEAD
    for part in _verdict_figure_parts(figures):
        line += part + ". "
    return line + "; ".join(result.why) + "."


# --- A year on its own (amendment A-GH-01, REQ-GH-24) ------------------------------------------

# A rejected token is a year on its own when it is a plain whole number of YEAR_DIGITS digits
# from YEAR_MIN to YEAR_MAX: no separator, no decimal part, no currency or percent sign. The guard
# matches a date to the dates of the rows only when it has a month and a day; a year alone is read
# as a plain number, so the badge says that instead of "not found".
YEAR_MIN: int = 1900
YEAR_MAX: int = 2099
YEAR_DIGITS: int = 4

BADGE_NOT_FOUND = "not found in the cited rows or the alert data"
BADGE_YEAR_ALONE = "a year on its own is not matched to the dates of the rows"
VERDICT_YEAR_ALONE = "A year on its own is not matched to the dates of the rows: "


def is_year_alone(token: str) -> bool:
    """True when a rejected token is a plain four-digit whole number from YEAR_MIN to YEAR_MAX."""
    if len(token) != YEAR_DIGITS or not token.isascii() or not token.isdigit():
        return False
    return YEAR_MIN <= int(token) <= YEAR_MAX


def _split_years(tokens: Sequence[str]) -> tuple[list[str], list[str]]:
    """Split figure tokens into (other figures, years on their own), each in the order given."""
    years = [t for t in tokens if is_year_alone(t)]
    others = [t for t in tokens if not is_year_alone(t)]
    return others, years


# --- A number in words, shown as the answer wrote it (amendment A-GH-02, REQ-GH-26) -------------

_SPACES = re.compile(r"\s+")


def _written_in(token: str, raw: str) -> str | None:
    """Return a letters-only token as `raw` writes it, any white space between its letters."""
    if not raw or not _WORDS_ONLY.fullmatch(token):
        return None
    letters = [char for char in token if not char.isspace()]
    pattern = r"\s*".join(re.escape(char) for char in letters)
    found = re.search(r"(?<!\w)" + pattern + r"(?!\w)", raw)
    return None if found is None else found.group(0)


def shown_token(token: str, raw: str = "") -> str:
    """Return a rejected token as the answer wrote it, for a badge or a verdict only.

    A token made only of letters, spaces and hyphens (a number in words such as `two hundred and
    sixty-four`, a currency code) is looked up in `raw`, the model's answer, as whole words with
    any white space, or none, between its letters; the first match is returned with each run of
    white space written as one space. A token not found, an empty `raw` or any other token is
    returned unchanged. What the guard checked is not changed: only the words shown.
    """
    if not _WORDS_ONLY.fullmatch(token):
        return token
    written = _written_in(token, raw)
    return token if written is None else _SPACES.sub(" ", written).strip()


def shown_tokens(tokens: Sequence[str], raw: str = "") -> tuple[str, ...]:
    """Return each rejected token as `shown_token` writes it, in the order given."""
    return tuple(shown_token(token, raw) for token in tokens)


def _badge_figure_parts(tokens: Sequence[str]) -> list[str]:
    """The badge words of rejected figures: the not-found part, then the year part."""
    others, years = _split_years(tokens)
    parts = []
    if others:
        parts.append(f"{BADGE_NOT_FOUND}: {', '.join(others)}")
    if years:
        parts.append(f"{BADGE_YEAR_ALONE}: {', '.join(years)}")
    return parts


def _verdict_figure_parts(tokens: Sequence[str]) -> list[str]:
    """The verdict sentences of rejected figures (tokens in backticks), without the final stop."""
    others, years = _split_years(tokens)
    parts = []
    if others:
        parts.append(VERDICT_NOT_FOUND + ", ".join(f"`{t}`" for t in others))
    if years:
        parts.append(VERDICT_YEAR_ALONE + ", ".join(f"`{t}`" for t in years))
    return parts


def rejection_clause(reason: str, tokens: Sequence[str], why: Sequence[str], raw: str = "") -> str:
    """Return what a rejected card badge says after `rejected`, in parentheses; '' for no token.

    A calculation the kit will not make and a currency sign the data does not name are said in
    words (`why`); a year on its own says so (`BADGE_YEAR_ALONE`); any other token is "not found
    in the cited rows or the alert data". All parts stand in one parenthesis. `raw` is the
    model's answer: a number in words is shown as it wrote it (`shown_token`).
    """
    if reason == REASON_CALC_NOT_ALLOWED:
        said = "; ".join(why) if why else ", ".join(tokens)
        return f" (the answer asks the kit for a calculation it will not make: {said})"
    shown = shown_tokens(tokens, raw)
    if why:
        figures = [t for t in shown if not is_currency_token(t)]
        parts = [*_badge_figure_parts(figures), *why]
        return " (" + "; ".join(parts) + ")"
    if shown:
        return " (" + "; ".join(_badge_figure_parts(shown)) + ")"
    return ""


# What a rejected badge says for a rejection that is not a missing figure; the index wording is
# the one replay.card_badge writes for a recorded answer.
BADGE_INDEX_CAUSE = "the answer names the price index as the cause of the price change"
BADGE_PERIOD = "the answer gives a figure a period that contradicts the alert field it matches"


def rejection_reason_text(
    reason: str, tokens: Sequence[str], why: Sequence[str], raw: str = ""
) -> str:
    """Return the real reason of a rejection for the badge of a card, without parentheses.

    A figure in no row says `not found in the cited rows or the alert data: tokens` (the text the
    badge always had) and a year on its own says `BADGE_YEAR_ALONE: years`; the price index named
    as the cause, a period that contradicts its field, a calculation the kit will not make and a
    currency sign the data does not name each say their own reason, in the words of
    `rejection_clause` and of the replay badge. `raw` is the model's answer: a number in words is
    shown as it wrote it (`shown_token`).
    """
    if reason == REASON_INDEX_AS_CAUSE:
        return f"{BADGE_INDEX_CAUSE}: {' '.join(tokens)}"
    if reason == REASON_PERIOD_MISMATCH:
        return f"{BADGE_PERIOD}: {', '.join(shown_tokens(tokens, raw))}"
    clause = rejection_clause(reason, tokens, why, raw)
    if clause.startswith(" (") and clause.endswith(")"):
        return clause[2:-1]
    return f"{BADGE_NOT_FOUND}: {', '.join(shown_tokens(tokens, raw))}"


@dataclass(frozen=True)
class Counts:
    """Per-session counters: presses, answers that reached the guard, guard rejections.

    `replayed` is how many of the presses replayed a recorded answer; they are counted in
    `asked` and `checked` like any press, but no model was called for them, so only the others
    (`live_asked`) use the session limit.
    """

    asked: int
    checked: int
    rejected: int
    replayed: int = 0

    @property
    def live_asked(self) -> int:
        """The presses that called a model: the only ones LIVE_ASKS_PER_SESSION_LIMIT counts."""
        return self.asked - self.replayed


def tally(counts: Counts, result: ProbeResult, *, replayed: bool = False) -> Counts:
    """Return the counters after one more press with this result (`replayed`: no model called)."""
    return Counts(
        counts.asked + 1,
        counts.checked + (result.verdict != "unavailable"),
        counts.rejected + (result.verdict == "rejected"),
        counts.replayed + replayed,
    )


def limit_reached(counts: Counts) -> bool:
    """True when the session has made as many live model calls as the courtesy limit allows."""
    return counts.live_asked >= LIVE_ASKS_PER_SESSION_LIMIT


def counter_caption(counts: Counts) -> str:
    """Return the one-line counter shown under every panel (replays are labelled)."""
    line = f"Answers checked: {counts.checked} · rejected: {counts.rejected}"
    if counts.replayed:
        line += f" · recorded replays: {counts.replayed}"
    return line


class Segment(NamedTuple):
    """A piece of the raw answer and whether the guard's rejected token sits in it."""

    text: str
    flagged: bool


_ISO_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
# A token of letters, spaces and hyphens only (a number phrase, a currency code): whole words.
_WORDS_ONLY = re.compile(r"[^\W\d_]+(?:[ \t-]+[^\W\d_]+)*")


def _forms(token: str) -> list[str]:
    """Return the spellings of a rejected token to look for (ISO dates also as DD/MM/YYYY)."""
    forms = [token]
    match = _ISO_DATE.fullmatch(token)
    if match:
        forms.append(f"{match.group(3)}/{match.group(2)}/{match.group(1)}")
    return forms


def _token_pattern(form: str) -> re.Pattern[str]:
    """Pattern of one spelling: whole words for a token of letters, else a whole figure."""
    if _WORDS_ONLY.fullmatch(form):
        return re.compile(r"(?<!\w)" + re.escape(form) + r"(?!\w)")
    return re.compile(r"(?<![\d.,])" + re.escape(form) + r"(?!\d)")


def highlight_segments(raw: str, tokens: Sequence[str]) -> list[Segment]:
    """Cut `raw` into segments; flagged ones are whole-figure occurrences of the tokens."""
    spans: list[tuple[int, int]] = []
    for token in tokens:
        if not token:
            continue
        written = _written_in(token, raw)
        forms = _forms(token) + ([written] if written and written != token else [])
        for form in forms:
            spans.extend((m.start(), m.end()) for m in _token_pattern(form).finditer(raw))
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


MARK_STYLE = _MARK_STYLE  # public name for the pages that mark a token inline (Home example)


def highlight_html(raw: str, tokens: Sequence[str]) -> str:
    """Return the raw answer as escaped HTML in a <pre>, with <mark> around flagged tokens."""
    parts = []
    for seg in highlight_segments(raw, tokens):
        escaped = html.escape(seg.text, quote=True)
        parts.append(f'<mark style="{_MARK_STYLE}">{escaped}</mark>' if seg.flagged else escaped)
    return f'<pre style="{_PRE_STYLE}">{"".join(parts)}</pre>'
