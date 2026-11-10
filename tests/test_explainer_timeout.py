"""Tests for the optional LEDGER_KIT_LLM_TIMEOUT variable (live-guard, decision DN-LG-18)."""

import sys
import types
from datetime import date
from decimal import Decimal

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ledger_kit.explainer import (
    LLM_TIMEOUT_MAX_SECONDS,
    LLM_TIMEOUT_MIN_SECONDS,
    LLM_TIMEOUT_SECONDS,
    explain_with_meta,
    llm_timeout_seconds,
)
from ledger_kit.models import Alert

ENV = "LEDGER_KIT_LLM_TIMEOUT"


def test_default_is_the_documented_ten_seconds() -> None:
    assert LLM_TIMEOUT_SECONDS == 10
    assert (LLM_TIMEOUT_MIN_SECONDS, LLM_TIMEOUT_MAX_SECONDS) == (1, 120)
    assert llm_timeout_seconds({}) == 10


@pytest.mark.parametrize(
    ("value", "expected"),
    [("1", 1), ("30", 30), ("120", 120), (" 45 ", 45), ("10", 10)],
)
def test_values_in_range_are_used(value: str, expected: int) -> None:
    assert llm_timeout_seconds({ENV: value}) == expected


@pytest.mark.parametrize(
    "value",
    ["", "0", "121", "-5", "abc", "10.5", "1e2", "nan", "٣", "1 2", "+30"],
)
def test_anything_else_falls_back_to_ten(value: str) -> None:
    assert llm_timeout_seconds({ENV: value}) == 10


@settings(max_examples=200)
@given(value=st.text(max_size=12))
def test_result_is_always_an_int_in_range(value: str) -> None:
    result = llm_timeout_seconds({ENV: value})
    assert isinstance(result, int)
    assert LLM_TIMEOUT_MIN_SECONDS <= result <= LLM_TIMEOUT_MAX_SECONDS


def test_default_mapping_is_the_process_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV, "25")
    assert llm_timeout_seconds() == 25
    monkeypatch.delenv(ENV)
    assert llm_timeout_seconds() == 10


def _install_fake_openai(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Install a fake `openai` whose OpenAI(**kwargs) records its kwargs."""
    seen: list[dict] = []

    class _Create:
        def create(self, **_kwargs):
            raise RuntimeError("stop here")

    class _Client:
        def __init__(self, **kwargs):
            seen.append(kwargs)
            self.chat = types.SimpleNamespace(completions=_Create())

    module = types.ModuleType("openai")
    module.OpenAI = _Client  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", module)
    return seen


def _call() -> None:
    alert = Alert(
        detector="zs.recurring_charge",
        severity="warning",
        title="t",
        source_refs=["bank.csv:0"],
        data={"yearly_cost": "155.88"},
    )
    rows = pd.DataFrame(
        [{"date": date(2026, 10, 1), "amount": Decimal("12.99"), "source_ref": "bank.csv:0"}]
    )
    result = explain_with_meta(alert, rows, fallback_template="{yearly_cost}")
    assert result.source == "fallback"


@pytest.mark.parametrize(("value", "expected"), [(None, 10), ("45", 45), ("bad", 10)])
def test_the_client_gets_the_effective_timeout(
    monkeypatch: pytest.MonkeyPatch, value: str | None, expected: int
) -> None:
    seen = _install_fake_openai(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    if value is None:
        monkeypatch.delenv(ENV, raising=False)
    else:
        monkeypatch.setenv(ENV, value)
    _call()
    assert len(seen) == 1
    assert seen[0]["timeout"] == expected
    assert seen[0]["max_retries"] == 0
