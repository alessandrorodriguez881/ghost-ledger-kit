"""The replay of the 16 Nov run shows a computed figure like a live answer (session 28d).

Tier 1: record Z20 (GYMPLUS, the five-year question) goes through today's guard accepted, with
two computations and their provenance lines; the Zombie page replays it in the *Provoke the LLM*
panel and shows the computed figure and the formula under it. Tier 2: the other three questions
that ask for a calculation the kit will not make fall back with the reason `calc_not_allowed`.
No model, no network, no clock. All data is synthetic.
"""

import json
from collections.abc import Iterator
from decimal import Decimal

import pytest
from judge_path_support import REPLAY_RUN, ROOT, SCRIPTS, Z1_ALERT_ID, find_case, template_of
from streamlit.testing.v1 import AppTest

from ledger_kit import replay
from ledger_kit.calc import COMPUTED_MARK, REASON_CALC_NOT_ALLOWED
from ledger_kit.detectors import _restore_registry, _snapshot_registry
from ledger_kit.explainer import Explanation, explain_with_meta
from ledger_kit.replay import ReplayClient
from ledger_kit.ui import first_run

TIMEOUT_SECONDS = 120
FORMULA = "5 x yearly_cost 107,88 EUR = 539,40 EUR"
LINE = f"{COMPUTED_MARK} computed by the kit: {FORMULA}, from the alert fields."


def _record(record_id: str) -> dict:
    document = json.loads(REPLAY_RUN.read_text(encoding="utf-8"))
    [record] = [r for r in document["records"] if r["id"] == record_id]
    return record


def _replayed(record_id: str) -> Explanation:
    """The record's raw answer through today's guard, as the replay does it."""
    record = _record(record_id)
    case = find_case(record["alert_id"])
    assert case is not None, f"{record_id}: its alert is not in today's demo"
    return explain_with_meta(
        case.alert,
        case.rows,
        fallback_template=template_of(case),
        client=ReplayClient(record["raw_answer"]),
        row_columns=case.columns,
        question=record.get("question") or None,
    )


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Snapshot and restore the detector registry; no key, so the replay is on."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    snapshot = _snapshot_registry()
    try:
        yield
    finally:
        _restore_registry(snapshot)


# --- Tier 1: the record and the page ----------------------------------------------------------


def test_z20_is_accepted_and_the_kit_computes_the_five_year_total() -> None:
    result = _replayed("Z20")

    assert result.source == "llm"
    assert result.rejected_numbers == ()
    assert [c.result for c in result.computed] == [Decimal("539.40")] * 2
    assert [c.line for c in result.computed] == [LINE, LINE]
    assert result.text.count(f"539,40 EUR{COMPUTED_MARK}") == 2
    assert "[[calc" not in result.text


def test_the_zombie_panel_replays_z20_with_the_computed_figure_and_its_formula(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(replay, "REPLAY_RUN_PATH", replay.DEFAULT_REPLAY_RUN_PATH)
    monkeypatch.setattr(first_run, "AUTOLOAD_DEMO", True)
    at = AppTest.from_file(str(ROOT / SCRIPTS["zs"]), default_timeout=TIMEOUT_SECONDS).run()
    assert not at.exception

    at.button(key=f"zs_lg_ask_{Z1_ALERT_ID}").click().run()

    assert not at.exception
    shown = [m.value for m in at.markdown if f"539,40 EUR{COMPUTED_MARK}" in m.value]
    assert len(shown) == 1
    captions = [c.value for c in at.caption]
    assert captions.count(LINE) == 2
    caption = "Replay of a recorded answer of llama3.2:3b, 2026-11-16."
    assert any(c.startswith(caption) for c in captions)


# --- Tier 2: the calculations the kit refuses -------------------------------------------------


@pytest.mark.parametrize("record_id", ["Z22", "P32", "V41", "V42", "V43"])
def test_a_calculation_the_kit_will_not_make_falls_back_with_its_reason(record_id: str) -> None:
    result = _replayed(record_id)

    assert result.source == "fallback"
    assert result.rejected_reason == REASON_CALC_NOT_ALLOWED
    assert result.computed == ()
    assert "[[calc" not in result.text
