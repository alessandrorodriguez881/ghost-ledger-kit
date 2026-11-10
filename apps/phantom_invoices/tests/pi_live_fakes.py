"""Fake `openai` module for the live-guard tests (DN-LG-08, DN-LG-16). No network, no real key.

`install` puts a module named `openai` into `sys.modules`; the explainer imports it lazily, so
the real request path runs: key read, `OpenAI(base_url=, api_key=, timeout=, max_retries=)`, the
messages built by `_call_llm`. A copy of this helper lives in every app (apps stay self-contained).
"""

import json
import re
import sys
import types
from dataclasses import dataclass, field

import pytest

INVENTED = "8765.43"  # a figure that is in no demo file (the tests assert that)
CARD_SENTENCE = "The invoice appears in the cited rows."
QUESTION_SEPARATOR = "\n\nQuestion from the user: "
LEAKY_MESSAGE = "connect to http://localhost:11434 failed"
SCENARIOS = ("invent", "faithful", "raise")

_AMOUNT_RE = re.compile(r"\d+\.\d{2}")
_AMOUNT_KEYS = ("total", "base_amount", "amount")
_ROWS_MARK = "\n\nSource rows:\n"


def user_message(call: dict) -> str:
    """The user message of a recorded request."""
    return call["messages"][1]["content"]


def system_message(call: dict) -> str:
    """The system message of a recorded request."""
    return call["messages"][0]["content"]


@dataclass
class FakeOpenAI:
    """What the fake saw: constructor kwargs and every request, in order."""

    scenario: str
    init_kwargs: list[dict] = field(default_factory=list)
    calls: list[dict] = field(default_factory=list)

    @property
    def question_calls(self) -> list[dict]:
        """The requests that carried a trick question."""
        return [c for c in self.calls if QUESTION_SEPARATOR in user_message(c)]

    @property
    def card_calls(self) -> list[dict]:
        """The requests made for the card text."""
        return [c for c in self.calls if QUESTION_SEPARATOR not in user_message(c)]


def _parts(user: str) -> tuple[dict, list[dict]]:
    """Split a user message into the alert JSON and the rows JSON it carries."""
    head, _, rest = user.partition(_ROWS_MARK)
    alert = json.loads(head.removeprefix("Alert: "))
    rows = json.loads(rest.split(QUESTION_SEPARATOR, 1)[0])
    return alert, rows


def _amount_from(rows: list[dict]) -> str | None:
    """One amount copied from the rows as sent, or None when the cited rows hold none."""
    for row in rows:
        for key in _AMOUNT_KEYS:
            value = row.get(key)
            if isinstance(value, float):
                return f"{value:.2f}"
            if isinstance(value, str) and _AMOUNT_RE.fullmatch(value):
                return value
    return None


def _answer(scenario: str, user: str) -> str:
    """The scripted answer to a trick question."""
    alert, rows = _parts(user)
    ref = alert["source_refs"][0]
    if scenario == "invent":
        return f"In five years you will have paid {INVENTED} EUR. Source: {ref}."
    amount = _amount_from(rows)
    if amount is None:  # cited supplier-master or payment rows carry no amount column
        return f"The cited rows are listed in the source row. Source: {ref}."
    return f"The cited row shows {amount} EUR. Source: {ref}."


def _response(text: str):
    """A minimal chat-completion response object."""
    message = types.SimpleNamespace(content=text)
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])


def install(monkeypatch: pytest.MonkeyPatch, scenario: str = "faithful") -> FakeOpenAI:
    """Install the fake `openai` module; `scenario` scripts the answer to a trick question."""
    assert scenario in SCENARIOS
    state = FakeOpenAI(scenario)

    class _Completions:
        def create(self, **kwargs):
            state.calls.append(kwargs)
            user = user_message(kwargs)
            if QUESTION_SEPARATOR not in user:
                return _response(CARD_SENTENCE)
            if scenario == "raise":
                raise RuntimeError(LEAKY_MESSAGE)
            return _response(_answer(scenario, user))

    class _Client:
        def __init__(self, **kwargs):
            state.init_kwargs.append(kwargs)
            self.chat = types.SimpleNamespace(completions=_Completions())

    module = types.ModuleType("openai")
    module.OpenAI = _Client  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", module)
    return state
