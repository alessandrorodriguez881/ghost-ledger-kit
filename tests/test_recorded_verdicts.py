"""Regression net: today's guard on every committed real-model answer (REQ-GH-14).

Each record of each run file in data/live_runs goes through `explain_with_meta` exactly as the
replay does (the case from `find_case`, its template, a `ReplayClient` of the raw answer, the row
columns and the question of the record). The set of record ids that end on the fixed template is
pinned per file.

A change in these sets must be explained in the guard-honesty spec (.kiro/specs/guard-honesty),
never just updated here: a guard that grows stricter or looser has to say why, record by record.
"""

import json
from typing import Any

import pytest
from judge_path_support import RUNS, find_case, template_of

from ledger_kit.explainer import explain_with_meta
from ledger_kit.replay import ReplayClient

# Record ids whose answer the guard of today rejects, per committed run file.
EXPECTED_FALLBACK: dict[str, set[str]] = {
    "2026-11-10_llama3.2-3b.json": {"Z4", "Z6", "P3", "V1", "V2"},
    "2026-11-10_llama3.2-3b_run2.json": {"Z4b", "Z6b"},
    "2026-11-10_llama3.2-3b_run3.json": {"Z3c", "Z4c"},
    "2026-11-11_llama3.2-3b_demo.json": {"Z03", "Z04", "Z05", "Z20", "P27", "V37"},
    # Derived by reading each raw answer (sessions 28b and 28c), explained record by record in
    # .kiro/specs/model-computes/tasks.md, tasks MC18 and MC21 (Z04 and V43 added by A-MC-04/05).
    "2026-11-15_llama3.2-3b_calc.json": {
        "Z04",
        "Z06",
        "Z08",
        "Z21",
        "Z22",
        "P32",
        "V37",
        "V38",
        "V41",
        "V42",
        "V43",
    },
    # The run the apps replay (session 28d): recorded with the placeholder rule, 43 records, 33
    # accepted and 10 on the template. Observed with today's guard and explained record by record
    # in .kiro/specs/model-computes/tasks.md, task MC25.
    "2026-11-16_llama3.2-3b_calc2.json": {
        "Z03",
        "Z04",
        "Z05",
        "Z22",
        "P27",
        "P32",
        "V37",
        "V41",
        "V42",
        "V43",
    },
}


def _records(name: str) -> list[dict[str, Any]]:
    document = json.loads((RUNS / name).read_text(encoding="utf-8"))
    return list(document["records"])


def _verdict_source(record: dict[str, Any]) -> str:
    """The source ('llm' or 'fallback') of today's guard on one recorded answer."""
    case = find_case(record["alert_id"])
    assert case is not None, f"{record['id']}: its alert is not in today's demo"
    result = explain_with_meta(
        case.alert,
        case.rows,
        fallback_template=template_of(case),
        client=ReplayClient(record.get("raw_answer") or ""),
        row_columns=case.columns,
        question=record.get("question") or None,
    )
    return result.source


def test_every_committed_run_file_is_pinned() -> None:
    committed = {path.name for path in RUNS.glob("*.json")}

    assert committed == set(EXPECTED_FALLBACK)


@pytest.mark.parametrize("name", sorted(EXPECTED_FALLBACK))
def test_every_record_alert_is_found_in_todays_demo(name: str) -> None:
    missing = [r["id"] for r in _records(name) if find_case(r["alert_id"]) is None]

    assert missing == []


@pytest.mark.parametrize("name", sorted(EXPECTED_FALLBACK))
def test_the_records_that_end_on_the_template_are_exactly_the_pinned_ones(name: str) -> None:
    fallback = {r["id"] for r in _records(name) if _verdict_source(r) == "fallback"}

    assert fallback == EXPECTED_FALLBACK[name]
