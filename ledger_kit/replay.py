"""Replay of a recorded real-model run (judge-path): no model, no network, no clock.

A judge who opens the public URL has no API key. This module reads one committed file of raw
answers a real model gave on the synthetic demo data and hands them back so the apps can pass them
through the CURRENT number guard. The guard is never told that a text is a replay: the apps give
``ReplayClient`` to the same call they make for a live answer, so the verdict is today's verdict
and the verdict stored in the file is never used to decide what a card or a panel shows.

The module is pure: it imports no Streamlit and no app. A missing or invalid file turns the replay
off (``load_run`` returns ``None``); it never raises and it shows no message.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import Any, Literal, Self

from ledger_kit.explainer import Explanation
from ledger_kit.index_cause import REASON_INDEX_AS_CAUSE
from ledger_kit.live_guard import TRICK_QUESTIONS, rejection_clause

ROOT = Path(__file__).resolve().parents[1]
# The one recorded run the apps replay: the only place the file name is written. It is the run of
# 16 Nov, recorded with the placeholder rule; older runs stay committed as history.
DEFAULT_REPLAY_RUN_PATH: Path = ROOT / "data" / "live_runs" / "2026-11-16_llama3.2-3b_calc2.json"
# The path read at call time; a test may point it elsewhere, DEFAULT_REPLAY_RUN_PATH stays as is.
REPLAY_RUN_PATH: Path = DEFAULT_REPLAY_RUN_PATH

# The Home example: one record of an older run, a real invention (a 5% interest rate found in no
# row, and 617.51 built on it). The path is read at call time like REPLAY_RUN_PATH.
DEFAULT_HOME_EXAMPLE_PATH: Path = ROOT / "data" / "live_runs" / "2026-11-10_llama3.2-3b.json"
HOME_EXAMPLE_PATH: Path = DEFAULT_HOME_EXAMPLE_PATH
HOME_EXAMPLE_ID = "P3"  # duplicate invoice F-2026-0310, the five-year question
# The two strings of the answer that Home marks: the assumed rate and the figure built on it.
HOME_EXAMPLE_MARKS: tuple[str, str] = ("5%", "617.51")

Kind = Literal["card", "probe"]

_QUESTION_TEXT: dict[str, str] = {q.id: q.text for q in TRICK_QUESTIONS}
# A money amount ends in a decimal part of one or two digits: 539.40, 1.349,40.
_MONEY_TOKEN = re.compile(r"\d[.,]\d{1,2}$")
# A sentence ends at . ! or ? followed by white space, or at a line break; 539.40 is not split.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")

BADGE_ACCEPTED = (
    "📼 Recorded answer of {model}, {date}, checked now by the number guard: figures accepted; "
    "wording not checked. No model called."
)
BADGE_REJECTED = (
    "📼 Recorded answer of {model}, {date}, checked now by the number guard: rejected{numbers}. "
    "Fixed template shown. No model called."
)
PANEL_INTRO = (
    "Three questions that tempt a model to state a figure that is not in the cited rows. "
    "Recorded answers of {model}, {date}: no model is called."
)
PANEL_CAPTION = (
    "Replay of a recorded answer of {model}, {date}. No model is called: the guard verdict "
    "below is today's number guard on that recorded text."
)


@dataclass(frozen=True)
class Recording:
    """One recorded answer: the raw text exactly as the model wrote it, and where it came from."""

    alert_id: str
    kind: Kind
    question_id: str | None  # the preset question of a probe; None for a card
    raw_answer: str
    model_name: str  # short name of the run's model, e.g. "llama3.2:3b"
    date: str  # ISO date of the run
    # The tokens the guard of the recording day rejected (only when it fell back). Used by the
    # Home example to pick a record; never to decide what a card or a panel shows.
    stored_rejection: tuple[str, ...] = ()

    @property
    def question_text(self) -> str | None:
        """The text of the preset question of a probe, else None."""
        return None if self.question_id is None else _QUESTION_TEXT.get(self.question_id)

    @property
    def invented_token(self) -> str | None:
        """The stored rejected token that matters: a money amount, else the longest token.

        A money amount ends in a decimal part (``539.40``, ``1.349,40``), so a multiplier such as
        ``5`` or a currency sign never wins over the amount the model made up. The first money
        amount wins; with none, the longest token (the first of equal length). None when the
        guard of the recording day rejected nothing.
        """
        tokens = self.stored_rejection
        for token in tokens:
            if _MONEY_TOKEN.search(token):
                return token
        return max(tokens, key=len, default=None)

    def sentence_with(self, token: str) -> str | None:
        """Return the sentence of the raw answer that contains `token`, else None."""
        for part in _SENTENCE_SPLIT.split(self.raw_answer.strip()):
            if token in part:
                return part.strip()
        return None

    def last_sentence_with(self, token: str) -> str | None:
        """Return the last sentence of the raw answer that contains `token`, else None."""
        for part in reversed(_SENTENCE_SPLIT.split(self.raw_answer.strip())):
            if token in part:
                return part.strip()
        return None


@dataclass(frozen=True)
class ReplayRun:
    """A valid run file: its model, its date and its recordings by key."""

    model: str  # as written in the file, with the server version and the model id
    date: str
    cards: Mapping[str, Recording]
    probes: Mapping[tuple[str, str], Recording]

    @property
    def model_name(self) -> str:
        """The model text up to the first ' (': 'llama3.2:3b (Ollama 0.40)' gives 'llama3.2:3b'."""
        return self.model.split(" (", 1)[0].strip()

    def card(self, alert_id: str) -> Recording | None:
        """Return the recorded card answer of an alert, or None."""
        return self.cards.get(alert_id)

    def probe(self, alert_id: str, question_id: str) -> Recording | None:
        """Return the recorded answer to one preset question on an alert, or None."""
        return self.probes.get((alert_id, question_id))

    def has_probe(self, alert_id: str) -> bool:
        """True when the alert has a recorded answer to at least one preset question."""
        return any(key[0] == alert_id for key in self.probes)

    def first_rejected_probe(self) -> Recording | None:
        """Return the first probe, in file order, that the guard of the recording day rejected."""
        for recording in self.probes.values():
            if recording.stored_rejection:
                return recording
        return None


def _kind(record: Mapping[str, Any]) -> Kind:
    """The kind of a record: its `kind`, else probe when it has a question, else card."""
    kind = record.get("kind")
    if kind == "card" or kind == "probe":
        return kind
    return "probe" if record.get("question") or record.get("question_id") else "card"


def _question_id(record: Mapping[str, Any]) -> str | None:
    """The preset question of a probe: `question_id`, else the id or text found in `question`."""
    wanted = record.get("question_id")
    if isinstance(wanted, str) and wanted in _QUESTION_TEXT:
        return wanted
    question = record.get("question")
    if isinstance(question, str):
        for preset in TRICK_QUESTIONS:
            if question.strip() in (preset.id, preset.text):
                return preset.id
    return None


def _recording(record: object, model_name: str, run_date: str) -> Recording | None:
    """Turn one record of the file into a Recording; None when it is malformed."""
    if not isinstance(record, Mapping):
        return None
    alert_id, raw = record.get("alert_id"), record.get("raw_answer")
    if not isinstance(alert_id, str) or not alert_id:
        return None
    if not isinstance(raw, str) or not raw.strip():
        return None
    kind = _kind(record)
    question_id = _question_id(record) if kind == "probe" else None
    if kind == "probe" and question_id is None:
        return None
    stored: tuple[str, ...] = ()
    observed = record.get("observed_rejected")
    if record.get("observed_source") == "fallback" and isinstance(observed, list):
        stored = tuple(token for token in observed if isinstance(token, str) and token)
    return Recording(alert_id, kind, question_id, raw, model_name, run_date, stored)


def _parse(data: object) -> ReplayRun | None:
    """Build a ReplayRun from the parsed JSON; None when the file as a whole is not usable."""
    if not isinstance(data, Mapping):
        return None
    model, run_date, records = data.get("model"), data.get("date"), data.get("records")
    if not isinstance(model, str) or not model.strip() or not isinstance(records, list):
        return None
    try:
        date.fromisoformat(str(run_date))
    except ValueError:
        return None
    model_name = model.split(" (", 1)[0].strip()
    cards: dict[str, Recording] = {}
    probes: dict[tuple[str, str], Recording] = {}
    for record in records:
        found = _recording(record, model_name, str(run_date))
        if found is None:
            continue
        if found.kind == "card":
            cards.setdefault(found.alert_id, found)
        elif found.question_id is not None:
            probes.setdefault((found.alert_id, found.question_id), found)
    return ReplayRun(
        model.strip(), str(run_date), MappingProxyType(cards), MappingProxyType(probes)
    )


@lru_cache(maxsize=8)
def _load_cached(path: str, mtime_ns: int, size: int) -> ReplayRun | None:
    """Read and parse one file; the arguments after `path` only key the cache."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return _parse(data)


def load_run(path: Path | str | None = None) -> ReplayRun | None:
    """Load the run file (REPLAY_RUN_PATH when `path` is None); None when it is not usable."""
    target = Path(REPLAY_RUN_PATH if path is None else path)
    try:
        stat = target.stat()
    except OSError:
        return None
    return _load_cached(str(target), stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=8)
def _home_example_cached(path: str, mtime_ns: int, size: int) -> Recording | None:
    """Read one file and return its HOME_EXAMPLE_ID record; the arguments after `path` key it."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, Mapping):
        return None
    model, run_date, records = data.get("model"), data.get("date"), data.get("records")
    if not isinstance(model, str) or not model.strip() or not isinstance(records, list):
        return None
    try:
        date.fromisoformat(str(run_date))
    except ValueError:
        return None
    model_name = model.split(" (", 1)[0].strip()
    for record in records:
        if isinstance(record, Mapping) and record.get("id") == HOME_EXAMPLE_ID:
            found = _recording(record, model_name, str(run_date))
            if found is None or found.question_text is None:
                return None
            return found
    return None


def home_example(path: Path | str | None = None) -> Recording | None:
    """Return the Home example (record P3 of its file, a probe of a preset question), else None."""
    target = Path(HOME_EXAMPLE_PATH if path is None else path)
    try:
        stat = target.stat()
    except OSError:
        return None
    return _home_example_cached(str(target), stat.st_mtime_ns, stat.st_size)


def card_recording(alert_id: str, *, path: Path | str | None = None) -> Recording | None:
    """Return the recorded card answer of an alert, or None (also when replay is off)."""
    run = load_run(path)
    return None if run is None else run.card(alert_id)


def probe_recording(
    alert_id: str, question_id: str, *, path: Path | str | None = None
) -> Recording | None:
    """Return the recorded answer to one preset question on an alert, or None."""
    run = load_run(path)
    return None if run is None else run.probe(alert_id, question_id)


def recorded_answer(
    alert_id: str, question_id: str | None = None, *, path: Path | str | None = None
) -> str | None:
    """Return the recorded raw answer for an alert (a card), or for an alert and a question."""
    found = (
        card_recording(alert_id, path=path)
        if question_id is None
        else probe_recording(alert_id, question_id, path=path)
    )
    return None if found is None else found.raw_answer


class ReplayClient:
    """OpenAI-shaped client that answers every request with one recorded text.

    It opens no connection and imports no SDK; ``calls`` keeps the keyword arguments of each
    request so a test can prove that the replay went through the same call as a live answer.
    """

    def __init__(self, text: str) -> None:
        """Remember the recorded text to return."""
        self._text = text
        self.calls: list[dict[str, Any]] = []

    @property
    def chat(self) -> Self:
        """Mirror `client.chat`."""
        return self

    @property
    def completions(self) -> Self:
        """Mirror `client.chat.completions`."""
        return self

    def create(self, **kwargs: Any) -> SimpleNamespace:
        """Return a response whose text is the recorded answer."""
        self.calls.append(kwargs)
        message = SimpleNamespace(content=self._text)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def card_badge(recording: Recording, explanation: Explanation) -> tuple[str, str]:
    """Return (css kind, label) of the badge of a replayed card: it names model and date."""
    if explanation.source == "llm":
        return "llm", BADGE_ACCEPTED.format(model=recording.model_name, date=recording.date)
    numbers = ""
    if explanation.rejected_reason == REASON_INDEX_AS_CAUSE:
        numbers = (
            " (the answer names the price index as the cause of the price change: "
            f"{' '.join(explanation.rejected_numbers)})"
        )
    else:
        numbers = rejection_clause(
            explanation.rejected_reason,
            explanation.rejected_numbers,
            explanation.rejected_why,
            explanation.raw_answer,
        )
    label = BADGE_REJECTED.format(model=recording.model_name, date=recording.date, numbers=numbers)
    return "rejected", label


def panel_intro(run: ReplayRun) -> str:
    """Return the intro line of the Provoke panel when its answers are recorded."""
    return PANEL_INTRO.format(model=run.model_name, date=run.date)


def panel_caption(recording: Recording) -> str:
    """Return the caption that says the answer below is a replay and no model is called."""
    return PANEL_CAPTION.format(model=recording.model_name, date=recording.date)
