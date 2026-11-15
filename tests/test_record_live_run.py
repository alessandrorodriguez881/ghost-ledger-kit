"""Tests of scripts/record_live_run.py (model-computes, requirements group 7, task MC12).

A fake OpenAI-shaped client only: no model, no network. The format to keep is the format of
`data/live_runs/2026-11-11_llama3.2-3b_demo.json` (its top-level fields and the fields of each
record), plus the two new record fields `observed_reason` and `observed_calcs`. All data is
synthetic (the committed CSV demos).
"""

import importlib.util
import io
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from ledger_kit.live_guard import TRICK_QUESTIONS

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "record_live_run.py"
DEMO_RUN_PATH = ROOT / "data" / "live_runs" / "2026-11-11_llama3.2-3b_demo.json"
DEMO_RUN: dict[str, Any] = json.loads(DEMO_RUN_PATH.read_text(encoding="utf-8"))

# The answer of the fake client: a calculation the kit can make only on an alert with a
# yearly_cost and a question that says five (the zombie forecast probe).
FIXED = "Over five years: [[calc: yearly_cost * 5]]."
TODAY = date(2026, 11, 16)
STEP_SECONDS = 1.5  # the fake clock advances this much on every read


def _load() -> ModuleType:
    """Load the script by path, as the other script tests do."""
    spec = importlib.util.spec_from_file_location("record_live_run", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["record_live_run"] = module
    spec.loader.exec_module(module)
    return module


rl: Any = _load()


class _Client:
    """Answers every request with one fixed text; records the requests and the file state."""

    def __init__(self, answer: str = FIXED, out: Path | None = None) -> None:
        self.answer = answer
        self.out = out
        self.calls: list[dict[str, Any]] = []
        self.file_seen_during_run = False

    @property
    def chat(self) -> "_Client":
        return self

    @property
    def completions(self) -> "_Client":
        return self

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        if self.out is not None and self.out.exists():
            self.file_seen_during_run = True
        message = SimpleNamespace(content=self.answer)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class _RaisingOnFirstClient(_Client):
    """Raises on the first request, then answers like _Client."""

    def create(self, **kwargs: Any) -> SimpleNamespace:
        if not self.calls:
            self.calls.append(kwargs)
            raise TimeoutError("simulated timeout")
        return super().create(**kwargs)


def _clock() -> Any:
    """A fake clock: 0.0, 1.5, 3.0, ... so every record takes STEP_SECONDS."""
    ticks = iter(range(10_000))
    return lambda: next(ticks) * STEP_SECONDS


def _boom(*_args: Any, **_kwargs: Any) -> None:
    raise AssertionError("the model was asked")


def _expected_record_keys() -> list[str]:
    """The record fields of the 11 Nov file, with the two new ones before raw_answer."""
    keys = list(DEMO_RUN["records"][0])
    assert keys[-1] == "raw_answer"
    return [*keys[:-1], "observed_reason", "observed_calcs", "raw_answer"]


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    """No real key in any test; a fixed model name and timeout for the settings fields."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.setenv("LEDGER_KIT_LLM_MODEL", "testmodel:1b")
    monkeypatch.setenv("LEDGER_KIT_LLM_TIMEOUT", "90")


# --- Tier 1 ---------------------------------------------------------------------------------------


def test_plan_has_the_scope_of_the_11_nov_file() -> None:
    planned = rl.plan()
    asked = [(p.card.alert.id, None if p.question is None else p.question.id) for p in planned]
    recorded = [(r["alert_id"], r["question_id"]) for r in DEMO_RUN["records"]]

    assert len(planned) == len(DEMO_RUN["records"]) == 43
    assert sorted(asked, key=str) == sorted(recorded, key=str)
    assert len({p.id for p in planned}) == len(planned)
    assert all(re.fullmatch(r"[ZPV]\d{2}", p.id) for p in planned)
    assert Counter(p.id[0] for p in planned) == Counter(r["id"][0] for r in DEMO_RUN["records"])


def test_plan_asks_the_three_questions_on_the_first_critical_card_of_each_app() -> None:
    planned = rl.plan()
    for app in rl.APP_ORDER:
        mine = [p for p in planned if p.card.app == app]
        cards = [p for p in mine if p.kind == "card"]
        probes = [p for p in mine if p.kind == "probe"]
        first_critical = next(p for p in cards if p.card.alert.severity == "critical")

        assert [p.question for p in probes] == list(TRICK_QUESTIONS)
        assert {p.card.alert.id for p in probes} == {first_critical.card.alert.id}
        assert [p.id for p in mine] == [p.id for p in cards + probes]  # cards, then questions


def test_dry_run_lists_every_record_and_calls_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rl, "explain_with_meta", _boom)
    client = _Client()
    out = tmp_path / "run.json"
    buffer = io.StringIO()

    code = rl.main(["--out", str(out), "--dry-run"], client=client, out=buffer)

    lines = buffer.getvalue().splitlines()
    record_lines = [line for line in lines if "\t" in line]
    assert code == rl.EXIT_OK
    assert client.calls == []
    assert not out.exists()
    assert len(record_lines) == len(DEMO_RUN["records"])
    first = record_lines[0].split("\t")
    assert first[0] == "Z01" and first[1] == rl.APP_ZOMBIE and first[4] == ""
    assert any(TRICK_QUESTIONS[0].text in line for line in record_lines)


def test_run_with_a_fixed_answer_writes_the_documented_format(tmp_path: Path) -> None:
    out = tmp_path / "run.json"
    client = _Client(out=out)
    buffer = io.StringIO()

    code = rl.main(
        ["--out", str(out), "--machine", "test machine", "--tag", "commit test"],
        client=client,
        clock=_clock(),
        today=TODAY,
        out=buffer,
    )

    assert code == rl.EXIT_OK
    assert not client.file_seen_during_run  # written only at the end
    document = json.loads(out.read_text(encoding="utf-8"))
    assert list(document) == list(DEMO_RUN)
    assert document["date"] == "2026-11-16"
    assert document["model"] == "testmodel:1b"
    assert document["machine"] == "test machine"
    assert document["guard_version"] == "commit test"
    assert list(document["settings"]) == list(DEMO_RUN["settings"])
    assert document["settings"]["temperature"] == 0
    assert document["settings"]["LEDGER_KIT_LLM_TIMEOUT"] == 90
    assert document["settings"]["retries"] == 0
    assert "One run, not a rate." in document["note"]

    records = document["records"]
    assert len(records) == len(client.calls) == len(DEMO_RUN["records"])
    assert all(list(r) == _expected_record_keys() for r in records)
    assert all(r["raw_answer"] == FIXED for r in records)
    assert all(r["seconds"] == STEP_SECONDS for r in records)
    assert all(call["temperature"] == 0 for call in client.calls)

    forecast = next(
        r for r in records if r["app"] == rl.APP_ZOMBIE and r["question_id"] == "forecast"
    )
    assert forecast["observed_source"] == "llm"
    assert forecast["observed_rejected"] == []
    assert forecast["observed_reason"] == ""
    assert forecast["observed_calcs"] == [
        {
            "expression": "yearly_cost * 5",
            "formula": "yearly_cost 107,88 EUR x 5 = 539,40 EUR",
            "result": "539.40",
        }
    ]
    card = records[0]
    assert card["kind"] == "card" and card["question"] is None
    assert card["observed_source"] == "fallback"
    assert card["observed_reason"] == "calc_not_allowed"  # no question: 5 is no question number
    assert card["observed_calcs"] == []

    lines = buffer.getvalue().splitlines()
    assert [line.split(" ")[0] for line in lines[:-1]] == [r["id"] for r in records]
    assert lines[-1].startswith(f"{len(records)} records written")


def test_existing_out_is_refused_and_nothing_is_written(tmp_path: Path) -> None:
    out = tmp_path / "run.json"
    out.write_text("keep", encoding="utf-8")
    client = _Client()

    code = rl.main(["--out", str(out)], client=client, out=io.StringIO())

    assert code == rl.EXIT_REFUSED
    assert out.read_text(encoding="utf-8") == "keep"
    assert client.calls == []


# --- Tier 2 ---------------------------------------------------------------------------------------


def test_a_client_that_raises_records_a_fallback_and_the_run_continues(tmp_path: Path) -> None:
    out = tmp_path / "run.json"
    client = _RaisingOnFirstClient()

    code = rl.main(["--out", str(out)], client=client, clock=_clock(), out=io.StringIO())

    assert code == rl.EXIT_OK
    records = json.loads(out.read_text(encoding="utf-8"))["records"]
    failed = records[0]
    assert failed["observed_source"] == "fallback"
    assert failed["raw_answer"] == ""
    assert failed["observed_rejected"] == []
    assert failed["observed_reason"] == rl.REASON_NO_ANSWER
    assert failed["observed_calcs"] == []
    assert len(records) == len(client.calls) == len(DEMO_RUN["records"])
    assert all(r["raw_answer"] == FIXED for r in records[1:])


def test_no_key_and_no_client_is_refused_before_asking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rl, "explain_with_meta", _boom)
    out = tmp_path / "run.json"

    code = rl.main(["--out", str(out)], out=io.StringIO())

    assert code == rl.EXIT_REFUSED
    assert not out.exists()


def test_missing_folder_is_refused_before_asking(tmp_path: Path) -> None:
    client = _Client()
    out = tmp_path / "no_such_folder" / "run.json"

    code = rl.main(["--out", str(out)], client=client, out=io.StringIO())

    assert code == rl.EXIT_REFUSED
    assert client.calls == []
    assert not out.parent.exists()


def test_out_is_required() -> None:
    with pytest.raises(SystemExit) as exit_info:
        rl.main([], out=io.StringIO())
    assert exit_info.value.code == 2


def test_observed_reason_names_a_figure_not_found() -> None:
    meta = rl.Explanation(text="t", source="fallback", rejected_numbers=("9",), raw_answer="9")
    accepted = rl.Explanation(text="t", source="llm", rejected_numbers=(), raw_answer="t")

    assert rl.observed_reason(meta) == rl.REASON_NOT_FOUND
    assert rl.observed_reason(accepted) == ""
