"""The replay module of judge-path (REQ-JP-01 to REQ-JP-04, REQ-JP-15, REQ-JP-18).

Tier 1: the loader on a small fixture file and on the 2026-11-10 files, the lookup by alert and by
question, the badge and caption texts. Tier 2: missing, broken and half-broken files, the cache.
Tier 3: any text a recording holds goes through today's guard and the replay client never returns
anything else. No test touches the network or the clock; every figure is synthetic or recorded.
"""

import ast
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from judge_path_support import (
    COMMITTED_RUN,
    FIXTURE_DATE,
    FIXTURE_MODEL,
    FIXTURE_MODEL_NAME,
    INVENTED,
    OLD_RUNS,
    REPLAY_RUN,
    SCRIPTS,
    Z1_ALERT_ID,
    accepted_text,
    card_record,
    cases_of,
    find_case,
    rejected_text,
    template_of,
    write_run,
)

from ledger_kit import replay
from ledger_kit.explainer import Explanation, explain_with_meta, fill_fallback
from ledger_kit.live_guard import TRICK_QUESTIONS
from ledger_kit.replay import Recording, ReplayClient, ReplayRun, load_run, recorded_answer

ROOT = Path(__file__).resolve().parents[1]
QUESTION_IDS = [q.id for q in TRICK_QUESTIONS]


@pytest.fixture
def run_path(tmp_path: Path) -> Path:
    """The run file of the tests, written with the real alert ids of the three demos."""
    return write_run(tmp_path / "run.json")


def _minimal(records: list[Any], **top: Any) -> dict[str, Any]:
    """A small document with the given records."""
    return {"model": FIXTURE_MODEL, "date": FIXTURE_DATE, "records": records, **top}


def _write(tmp_path: Path, document: Any, name: str = "x.json") -> Path:
    path = tmp_path / name
    path.write_text(document if isinstance(document, str) else json.dumps(document), "utf-8")
    return path


def _run_of(path: Path) -> ReplayRun:
    run = load_run(path)
    assert run is not None
    return run


def _verdict(case, text: str, question: str | None = None) -> Explanation:
    """What an app does with a recorded text: the same call, with the replay client."""
    return explain_with_meta(
        case.alert,
        case.rows,
        fallback_template=template_of(case),
        client=ReplayClient(text),
        row_columns=case.columns,
        question=question,
    )


# --- Tier 1: the constant and the loader (REQ-JP-01) -----------------------------------------


def test_the_run_path_is_one_named_constant() -> None:
    # The root conftest patches REPLAY_RUN_PATH for every test; the default is never patched.
    assert replay.DEFAULT_REPLAY_RUN_PATH == REPLAY_RUN
    assert replay.DEFAULT_REPLAY_RUN_PATH.name == "2026-11-16_llama3.2-3b_calc2.json"
    assert replay.DEFAULT_REPLAY_RUN_PATH != COMMITTED_RUN  # the 11 Nov file is history now
    assert replay.DEFAULT_REPLAY_RUN_PATH.parent == ROOT / "data" / "live_runs"
    # Without a patch the call-time path is that same constant.
    assert replay.REPLAY_RUN_PATH != replay.DEFAULT_REPLAY_RUN_PATH  # patched by conftest
    assert replay.REPLAY_RUN_PATH.name == "no-replay-in-tests.json"


def test_load_run_reads_the_model_and_the_date(run_path: Path) -> None:
    run = _run_of(run_path)

    assert run.model == FIXTURE_MODEL
    assert run.model_name == FIXTURE_MODEL_NAME == "testmodel:1b"
    assert run.date == FIXTURE_DATE


def test_load_run_without_a_path_reads_the_constant_at_call_time(
    run_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert load_run() is None  # the root conftest points the constant at a missing file
    monkeypatch.setattr(replay, "REPLAY_RUN_PATH", run_path)

    run = load_run()

    assert run is not None and run.model_name == FIXTURE_MODEL_NAME


def test_the_real_model_text_is_shortened_to_its_name() -> None:
    run = ReplayRun("llama3.2:3b (Ollama 0.40.16, model id a80c4f17acd5)", "2026-11-11", {}, {})

    assert run.model_name == "llama3.2:3b"


# --- Tier 1: the lookup (REQ-JP-03) ---------------------------------------------------------


def test_a_record_without_a_question_is_a_card(tmp_path: Path) -> None:
    path = _write(tmp_path, _minimal([{"alert_id": "a1", "question": None, "raw_answer": "T"}]))

    assert recorded_answer("a1", path=path) == "T"
    assert recorded_answer("a1", "forecast", path=path) is None
    assert replay.card_recording("a1", path=path).kind == "card"


def test_a_probe_is_found_by_alert_and_question(tmp_path: Path) -> None:
    record = {"alert_id": "a1", "kind": "probe", "question_id": "forecast", "raw_answer": "P"}
    path = _write(tmp_path, _minimal([record]))

    assert recorded_answer("a1", "forecast", path=path) == "P"
    assert recorded_answer("a1", path=path) is None
    assert recorded_answer("a1", "next_month", path=path) is None
    assert recorded_answer("other", "forecast", path=path) is None
    found = replay.probe_recording("a1", "forecast", path=path)
    assert found.kind == "probe" and found.question_id == "forecast"
    assert found.question_text == TRICK_QUESTIONS[0].text


def test_an_older_record_without_kind_resolves_its_question_text(tmp_path: Path) -> None:
    question = TRICK_QUESTIONS[1]
    records = [
        {"alert_id": "a1", "question": None, "raw_answer": "card"},
        {"alert_id": "a1", "question": question.text, "raw_answer": "probe"},
        {"alert_id": "a2", "question": "a question nobody preset", "raw_answer": "lost"},
    ]
    run = _run_of(_write(tmp_path, _minimal(records)))

    assert run.card("a1").raw_answer == "card"
    assert run.probe("a1", question.id).raw_answer == "probe"
    assert run.card("a2") is None and not run.has_probe("a2")


def test_the_first_record_of_a_key_wins(tmp_path: Path) -> None:
    records = [
        {"alert_id": "a1", "raw_answer": "first"},
        {"alert_id": "a1", "raw_answer": "second"},
    ]

    assert recorded_answer("a1", path=_write(tmp_path, _minimal(records))) == "first"


def test_the_stored_verdict_only_marks_a_record_for_the_home_example(tmp_path: Path) -> None:
    kept = {"alert_id": "a1", "kind": "probe", "question_id": "forecast", "raw_answer": "x"}
    rejected = {
        **kept,
        "alert_id": "a2",
        "observed_source": "fallback",
        "observed_rejected": ["$", "1.349,40"],
    }
    run = _run_of(_write(tmp_path, _minimal([kept, rejected])))

    found = run.first_rejected_probe()
    assert found is not None and found.alert_id == "a2"
    assert found.invented_token == "1.349,40"  # the money amount, not the currency sign
    assert run.probe("a1", "forecast").stored_rejection == ()


def _recording_with(raw: str, tokens: tuple[str, ...]) -> Recording:
    return Recording("a1", "probe", "forecast", raw, "m", "2026-11-11", tokens)


def test_the_invented_token_is_the_money_amount_not_the_multiplier() -> None:
    recording = _recording_with("Five years: 5 x 107.88 = 539.40 EUR.", ("5", "539.40"))

    assert recording.invented_token == "539.40"


def test_without_a_money_amount_the_invented_token_is_the_longest() -> None:
    assert _recording_with("x", ("5", "$", "2030")).invented_token == "2030"
    assert _recording_with("x", ("5", "7")).invented_token == "5"  # first of equal length
    assert _recording_with("x", ()).invented_token is None


def test_the_sentence_holds_the_token_and_is_not_cut_inside_an_amount() -> None:
    raw = "It costs a lot. Over five years you will pay 539.40 EUR. Cancel it.\nBye."
    recording = _recording_with(raw, ("539.40",))

    assert recording.sentence_with("539.40") == "Over five years you will pay 539.40 EUR."
    assert recording.sentence_with("77.77") is None


@pytest.mark.parametrize("path", OLD_RUNS, ids=lambda p: p.name)
def test_the_2026_11_10_files_load_and_hold_the_first_card(path: Path) -> None:
    run = _run_of(path)

    assert run.date == "2026-11-10"
    assert run.model_name == "llama3.2:3b"
    assert run.card(Z1_ALERT_ID) is not None


# --- Tier 1: the re-check is today's guard (REQ-JP-04) ----------------------------------------


def test_a_record_stored_as_rejected_for_row_numbers_is_accepted_now() -> None:
    """Z1 of 2026-11-10 was rejected for 181, 236 and 292; the guard learned row citations."""
    stored = json.loads(OLD_RUNS[0].read_text(encoding="utf-8"))["records"][0]
    assert stored["alert_id"] == Z1_ALERT_ID
    assert stored["observed_source"] == "fallback"
    assert stored["observed_rejected"] == ["181", "236", "292"]
    case = find_case(Z1_ALERT_ID)
    assert case is not None
    client = ReplayClient(recorded_answer(Z1_ALERT_ID, path=OLD_RUNS[0]) or "")

    result = explain_with_meta(
        case.alert,
        case.rows,
        fallback_template=template_of(case),
        client=client,
        row_columns=case.columns,
    )

    assert result.source == "llm" and result.rejected_numbers == ()
    assert result.text == stored["raw_answer"]
    assert len(client.calls) == 1  # one request through the same call a live answer takes


def test_the_verdict_is_todays_guard_on_the_recorded_text_not_the_stored_one(
    tmp_path: Path,
) -> None:
    case = cases_of("zs")[0]
    record = card_record(case, rejected_text(case))
    assert record["observed_source"] == "llm" and record["observed_rejected"] == []
    path = _write(tmp_path, _minimal([record]))

    result = _verdict(case, recorded_answer(case.alert.id, path=path) or "")

    assert result.source == "fallback"
    assert INVENTED in result.rejected_numbers
    assert result.text == fill_fallback(template_of(case), case.alert)
    assert result.raw_answer == rejected_text(case)


@pytest.mark.parametrize("prefix", sorted(SCRIPTS))
def test_an_accepted_recording_is_shown_a_rejected_one_gives_the_template(prefix: str) -> None:
    case = cases_of(prefix)[0]

    accepted = _verdict(case, accepted_text(case))
    rejected = _verdict(case, rejected_text(case))

    assert accepted.source == "llm" and accepted.text == accepted_text(case)
    assert rejected.source == "fallback" and rejected.rejected_numbers == (INVENTED,)
    assert rejected.text == fill_fallback(template_of(case), case.alert)


def test_replay_calls_no_sdk_and_opens_no_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    """With the SDK made unimportable, the replay still answers: nothing else could have."""
    monkeypatch.setitem(sys.modules, "openai", None)
    monkeypatch.setenv("OPENAI_BASE_URL", "http://unreachable.invalid/v1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    case = cases_of("zs")[0]
    client = ReplayClient(accepted_text(case))

    result = explain_with_meta(
        case.alert, case.rows, fallback_template=template_of(case), client=client
    )

    assert result.source == "llm"
    assert len(client.calls) == 1
    [call] = client.calls
    assert call["temperature"] == 0 and call["messages"][0]["role"] == "system"


def test_the_replay_module_imports_no_network_or_model_library() -> None:
    tree = ast.parse((ROOT / "ledger_kit" / "replay.py").read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    assert imported
    assert not imported & {"openai", "socket", "urllib", "http", "requests", "streamlit", "apps"}


# --- Tier 1: the texts (REQ-JP-07, REQ-JP-08, REQ-JP-18) ---------------------------------------


def test_badge_texts_name_the_model_the_date_and_say_no_model_was_called(run_path: Path) -> None:
    run = _run_of(run_path)
    case = cases_of("zs")[0]
    recording = run.card(case.alert.id)
    assert recording is not None

    kind, label = replay.card_badge(recording, _verdict(case, recording.raw_answer))
    refused = _verdict(case, rejected_text(case))
    rejected_kind, rejected_label = replay.card_badge(recording, refused)

    assert kind == "llm"
    assert label == (
        "📼 Recorded answer of testmodel:1b, 2026-11-11, checked now by the number guard: "
        "figures accepted; wording not checked. No model called."
    )
    assert rejected_kind == "rejected"
    assert rejected_label == (
        "📼 Recorded answer of testmodel:1b, 2026-11-11, checked now by the number guard: "
        f"rejected (not found in the cited rows or the alert data: {INVENTED}). "
        "Fixed template shown. No model called."
    )
    for text in (label, rejected_label):
        assert "LLM text verified" not in text and "LLM answer rejected" not in text


def test_panel_texts_say_replay_and_no_model_is_called(run_path: Path) -> None:
    run = _run_of(run_path)
    case = cases_of("zs")[0]
    recording = run.probe(case.alert.id, "forecast")
    assert recording is not None

    intro = replay.panel_intro(run)
    caption = replay.panel_caption(recording)

    assert "Recorded answers of testmodel:1b, 2026-11-11" in intro and "no model is called" in intro
    assert caption.startswith("Replay of a recorded answer of testmodel:1b, 2026-11-11.")
    assert "No model is called" in caption and "today's number guard" in caption


# --- Tier 2: files that cannot be used (REQ-JP-02) ------------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        "",
        "[]",
        "null",
        json.dumps({"model": "m", "date": "2026-11-11"}),
        json.dumps({"model": "m", "date": "2026-11-11", "records": {}}),
        json.dumps({"model": "", "date": "2026-11-11", "records": []}),
        json.dumps({"model": 3, "date": "2026-11-11", "records": []}),
        json.dumps({"model": "m", "date": "11/11/2026", "records": []}),
        json.dumps({"model": "m", "date": None, "records": []}),
    ],
)
def test_an_unusable_file_turns_the_replay_off(tmp_path: Path, content: str) -> None:
    path = _write(tmp_path, content)

    assert load_run(path) is None
    assert recorded_answer("a1", path=path) is None


def test_a_missing_file_or_a_folder_turns_the_replay_off(tmp_path: Path) -> None:
    assert load_run(tmp_path / "nowhere.json") is None
    assert load_run(tmp_path) is None
    assert replay.card_recording("a1", path=tmp_path / "nowhere.json") is None


def test_binary_garbage_turns_the_replay_off(tmp_path: Path) -> None:
    path = tmp_path / "bin.json"
    path.write_bytes(b"\xff\xfe\x00\x01\x80")

    assert load_run(path) is None


def test_only_a_malformed_record_is_skipped(tmp_path: Path) -> None:
    records: list[Any] = [
        "not an object",
        {"raw_answer": "no alert id"},
        {"alert_id": "", "raw_answer": "empty id"},
        {"alert_id": "a1", "raw_answer": ""},
        {"alert_id": "a1", "raw_answer": "   "},
        {"alert_id": "a1", "raw_answer": 5},
        {"alert_id": "a1", "kind": "probe", "question_id": "unknown", "raw_answer": "x"},
        {"alert_id": "good", "raw_answer": "kept"},
    ]
    run = _run_of(_write(tmp_path, _minimal(records)))

    assert set(run.cards) == {"good"} and not run.probes


def test_a_file_without_records_is_a_valid_empty_run(tmp_path: Path) -> None:
    run = _run_of(_write(tmp_path, _minimal([])))

    assert not run.cards and not run.probes
    assert run.first_rejected_probe() is None


def test_a_changed_file_is_read_again(tmp_path: Path) -> None:
    path = _write(tmp_path, _minimal([{"alert_id": "a1", "raw_answer": "one"}]))
    assert recorded_answer("a1", path=path) == "one"

    path.write_text(json.dumps(_minimal([{"alert_id": "a1", "raw_answer": "changed!"}])), "utf-8")

    assert recorded_answer("a1", path=path) == "changed!"


# --- the committed file stays usable ----------------------------------------------------------


@pytest.mark.parametrize("path", [REPLAY_RUN, COMMITTED_RUN], ids=lambda p: p.name)
def test_every_alert_id_of_the_committed_run_is_raised_by_the_demo(path: Path) -> None:
    """A recording whose alert id no demo alert has would silently never be shown."""
    run = load_run(path)
    if run is None:
        pytest.skip("the committed run file is not there yet")
    missing = [
        record.alert_id
        for record in [*run.cards.values(), *run.probes.values()]
        if find_case(record.alert_id) is None
    ]

    assert missing == []


def test_the_home_example_is_a_record_todays_guard_rejects_with_the_same_token() -> None:
    """The Home example is record P3: today's guard must reject it with its marked figures."""
    recording = replay.home_example(replay.DEFAULT_HOME_EXAMPLE_PATH)
    assert recording is not None
    case = find_case(recording.alert_id)
    assert case is not None

    result = _verdict(case, recording.raw_answer, recording.question_text)

    assert result.source == "fallback"
    assert "617.51" in result.rejected_numbers and "5" in result.rejected_numbers
    assert recording.invented_token in result.rejected_numbers


# --- Tier 3: properties -----------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(text=st.text(max_size=300))
def test_the_replay_client_returns_exactly_the_recorded_text(text: str) -> None:
    client = ReplayClient(text)

    response = client.chat.completions.create(model="m", messages=[])

    assert response.choices[0].message.content == text
    assert len(client.calls) == 1


@settings(max_examples=200, deadline=None)
@given(extra=st.decimals(min_value=Decimal("10000"), max_value=Decimal("99999.99"), places=2))
def test_an_invented_figure_in_any_recording_is_rejected_and_never_reaches_the_card(
    extra: Decimal,
) -> None:
    case = cases_of("vf")[0]
    invented = f"{extra:f}"
    text = f"{accepted_text(case)} The total will be {invented} EUR."

    result = _verdict(case, text)

    assert result.source == "fallback"
    assert invented in result.rejected_numbers
    assert invented not in result.text


@settings(max_examples=200, deadline=None)
@given(
    alert_id=st.text(min_size=1, max_size=20),
    question_id=st.sampled_from(QUESTION_IDS),
)
def test_an_alert_that_was_not_recorded_has_no_answer(alert_id: str, question_id: str) -> None:
    run = replay.ReplayRun("m", FIXTURE_DATE, {}, {})

    assert run.card(alert_id) is None
    assert run.probe(alert_id, question_id) is None
    assert not run.has_probe(alert_id)
