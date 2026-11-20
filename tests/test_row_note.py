"""Session 33 (REQ-AS-34, REQ-AS-35): the row numbers of a model answer, as lines of the file.

A model answer can say `rows 9 to 312` (the internal 0-based index the kit names to the model)
while the chips say `file · line N`. Under a model answer the person gets one note that says which
line of the file each of those numbers is; the answer itself is never edited. The lines of these
tests come from the readers (the demo pipelines), never from N plus 2; the recorded answers are
the real ones of the committed run. No network, no model, no clock.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from judge_path_support import REPLAY_RUN, ROOT, SCRIPTS, _phantom, _zombie
from streamlit.testing.v1 import AppTest

from ledger_kit import replay
from ledger_kit.detectors import _restore_registry, _snapshot_registry
from ledger_kit.ui import first_run
from ledger_kit.ui.signatures import (
    ROW_NOTE_HEAD,
    RowLine,
    answer_row_note,
    row_lines_note,
    row_mentions_to_lines,
    source_lines_of,
)

TIMEOUT_SECONDS = 120
DOT = "\u00b7"
SAMPLES = ROOT / "data" / "samples"
PHANTOM_DEMO = SAMPLES / "phantom_demo"


def _record(record_id: str) -> dict[str, Any]:
    """One record of the committed run of 16 Nov, by its id (Z02, P25, P26)."""
    document = json.loads(REPLAY_RUN.read_text(encoding="utf-8"))
    [found] = [r for r in document["records"] if r["id"] == record_id]
    return found


def _file_line(path: Path, line: int) -> str:
    """The text of one line of a file, numbered as a text editor does (the first line is 1)."""
    return path.read_text(encoding="utf-8").splitlines()[line - 1]


def _zombie_lines() -> dict[str, int]:
    """source_ref to source_line of the zombie demo ledger, as the page builds the map."""
    return source_lines_of(_zombie().debit_ledger)


def _phantom_lines() -> dict[str, int]:
    """source_ref to source_line of the phantom demo files, as the page builds the map."""
    pipeline = _phantom()
    return source_lines_of(pipeline.invoices, pipeline.suppliers, pipeline.payments)


def _by_ref(mentions: list[RowLine]) -> dict[str, RowLine]:
    return {m.ref: m for m in mentions}


# --- the recorded answers, with the lines the readers give -------------------------------------


def test_the_musicbox_answer_gives_the_lines_of_rows_9_and_312() -> None:
    record = _record("Z02")
    lines = _zombie_lines()
    file = "zombie_demo_statement.csv"

    found = _by_ref(row_mentions_to_lines(record["raw_answer"], record["source_refs"], lines))

    assert list(found) == [f"{file}:9", f"{file}:312"]
    assert found[f"{file}:9"] == RowLine(9, f"{file}:9", lines[f"{file}:9"])
    assert found[f"{file}:312"] == RowLine(312, f"{file}:312", lines[f"{file}:312"])
    # the line is the one a person finds in the file: the MUSICBOX charge is written there
    for ref in found:
        assert "MUSICBOX" in _file_line(SAMPLES / file, found[ref].line)


def test_the_p25_answer_gives_payments_row_46_and_suppliers_row_12() -> None:
    record = _record("P25")
    lines = _phantom_lines()

    found = _by_ref(row_mentions_to_lines(record["raw_answer"], record["source_refs"], lines))

    assert list(found) == ["payments.csv:46", "suppliers.csv:12"]
    assert found["payments.csv:46"].line == lines["payments.csv:46"]
    assert found["suppliers.csv:12"].line == lines["suppliers.csv:12"]
    assert "Mantenimientos Delta" in _file_line(
        PHANTOM_DEMO / "suppliers.csv", found["suppliers.csv:12"].line
    )


def test_the_p26_answer_gives_invoices_rows_5_and_6() -> None:
    record = _record("P26")
    lines = _phantom_lines()

    found = _by_ref(row_mentions_to_lines(record["raw_answer"], record["source_refs"], lines))

    assert list(found) == ["invoices.csv:5", "invoices.csv:6"]
    assert found["invoices.csv:5"].line == lines["invoices.csv:5"]
    assert found["invoices.csv:6"].line == lines["invoices.csv:6"]
    assert "F-2026-0042" in _file_line(PHANTOM_DEMO / "invoices.csv", found["invoices.csv:5"].line)
    assert "F2026-042" in _file_line(PHANTOM_DEMO / "invoices.csv", found["invoices.csv:6"].line)


def test_the_note_of_the_musicbox_answer_says_both_lines_in_one_line() -> None:
    record = _record("Z02")
    lines = _zombie_lines()
    file = "zombie_demo_statement.csv"

    note = answer_row_note(record["raw_answer"], record["source_refs"], lines)

    assert note == (
        f"{ROW_NOTE_HEAD}row 9 is {file} {DOT} line {lines[f'{file}:9']}, "
        f"row 312 is {file} {DOT} line {lines[f'{file}:312']}."
    )
    assert "\n" not in note


# --- what maps and what does not --------------------------------------------------------------


LINES = {"a.csv:5": 7, "a.csv:6": 8, "b.csv:5": 30, "b.csv:9": 34, "c.csv:2": 4}
REFS = list(LINES)


def test_a_number_that_is_not_a_cited_ref_gives_nothing() -> None:
    assert row_mentions_to_lines("See row 99 and rows 100 to 101.", REFS, LINES) == []
    assert answer_row_note("See row 99.", REFS, LINES) == ""


def test_a_ref_without_a_known_line_gives_nothing() -> None:
    assert row_mentions_to_lines("See row 2.", ["c.csv:2"], {}) == []
    assert row_mentions_to_lines("See row 2.", ["c.csv:2"], None) == []


def test_two_files_with_the_same_number_give_nothing_unless_a_file_is_named_before() -> None:
    assert row_mentions_to_lines("The charge is at row 5.", REFS, LINES) == []
    assert answer_row_note("The charge is at row 5.", REFS, LINES) == ""

    [only_b] = row_mentions_to_lines("In b.csv the charge is at row 5.", REFS, LINES)
    assert only_b == RowLine(5, "b.csv:5", 30)

    [only_a] = row_mentions_to_lines("In a.csv the charge is at row 5.", REFS, LINES)
    assert only_a == RowLine(5, "a.csv:5", 7)


def test_the_nearest_named_file_wins_and_a_far_one_does_not_count() -> None:
    [near] = row_mentions_to_lines("a.csv is ignored; in b.csv, row 5 is it.", REFS, LINES)
    assert near.ref == "b.csv:5"

    far = "a.csv " + "x" * 200 + " row 5"
    assert row_mentions_to_lines(far, REFS, LINES) == []


def test_an_answer_without_the_word_row_gives_no_note() -> None:
    assert answer_row_note("The charges are at 5 and 6 of a.csv.", REFS, LINES) == ""
    assert answer_row_note("Line 5 of a.csv, item 6.", REFS, LINES) == ""
    assert answer_row_note("The arrow 5 is not a row mention.", REFS, LINES) == ""
    assert answer_row_note("", REFS, LINES) == ""


@pytest.mark.parametrize(
    "text",
    [
        "a.csv rows 5 and 6",
        "a.csv rows 5 to 6",
        "a.csv rows 5, 6",
        "a.csv rows 5, and 6",
        "a.csv rows 5-6",
        "a.csv rows 5\u20136",
        "a.csv Rows 5 and 6",
    ],
)
def test_numbers_joined_by_and_to_a_comma_or_a_dash_are_all_read(text: str) -> None:
    found = row_mentions_to_lines(text, REFS, LINES)

    assert found == [RowLine(5, "a.csv:5", 7), RowLine(6, "a.csv:6", 8)]


def test_a_number_written_twice_gives_one_entry() -> None:
    found = row_mentions_to_lines("a.csv: row 5, and again row 5 of a.csv.", REFS, LINES)

    assert found == [RowLine(5, "a.csv:5", 7)]


def test_a_decimal_after_the_word_row_is_not_a_row_number() -> None:
    assert row_mentions_to_lines("The row 2,50 EUR is a price.", REFS, LINES) == []
    assert row_mentions_to_lines("The row 2.5 is a price.", REFS, LINES) == []


def test_the_note_is_empty_for_no_mapping_and_one_line_for_several() -> None:
    assert row_lines_note([]) == ""
    note = row_lines_note([RowLine(46, "payments.csv:46", 50), RowLine(12, "suppliers.csv:12", 17)])

    assert note == (
        "The model counts data rows from 0, as the kit names them to it: "
        f"row 46 is payments.csv {DOT} line 50, row 12 is suppliers.csv {DOT} line 17."
    )


def test_the_text_is_only_read() -> None:
    text = "In b.csv, row 5."
    answer_row_note(text, REFS, LINES)

    assert text == "In b.csv, row 5."


# --- the pages --------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch: pytest.MonkeyPatch):
    """Snapshot and restore the detector registry; no key unless a test sets one."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    snapshot = _snapshot_registry()
    try:
        yield
    finally:
        _restore_registry(snapshot)


def _open(prefix: str) -> AppTest:
    at = AppTest.from_file(str(ROOT / SCRIPTS[prefix]), default_timeout=TIMEOUT_SECONDS).run()
    assert not at.exception
    return at


def test_the_musicbox_card_shows_the_note_and_the_recorded_answer_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(replay, "REPLAY_RUN_PATH", REPLAY_RUN)
    monkeypatch.setattr(first_run, "AUTOLOAD_DEMO", True)
    record = _record("Z02")
    lines = _zombie_lines()
    file = "zombie_demo_statement.csv"
    expected = (
        f"{ROW_NOTE_HEAD}row 9 is {file} {DOT} line {lines[f'{file}:9']}, "
        f"row 312 is {file} {DOT} line {lines[f'{file}:312']}."
    )

    at = _open("zs")

    values = [element.value for element in at.markdown]
    assert values.count(record["raw_answer"]) == 1  # the recorded text, not edited
    assert [c.value for c in at.caption].count(expected) == 1
    assert f"line {lines[f'{file}:9']}" in expected and f"line {lines[f'{file}:312']}" in expected


def test_no_note_is_shown_under_a_fixed_template() -> None:
    at = _open("zs")  # no key and no replay: every card is the fixed template

    assert not any(c.value.startswith(ROW_NOTE_HEAD) for c in at.caption)


# --- a ref written whole in an answer, file:N (session 34, REQ-AS-35 amendment) -----------------

ZOMBIE_FILE = "zombie_demo_statement.csv"


def test_the_z06_answer_names_its_ref_whole_and_gets_its_line() -> None:
    record = _record("Z06")
    lines = _zombie_lines()
    ref = f"{ZOMBIE_FILE}:10"
    assert f"{ref}." in record["raw_answer"]  # the recorded text writes the internal key

    found = row_mentions_to_lines(record["raw_answer"], record["source_refs"], lines)

    assert found == [RowLine(10, ref, lines[ref], ref)]
    assert lines[ref] == 12  # the chip of this row says line 12
    assert "SECUREPASS" in _file_line(SAMPLES / ZOMBIE_FILE, found[0].line)
    note = answer_row_note(record["raw_answer"], record["source_refs"], lines)
    assert note == f"{ROW_NOTE_HEAD}{ref} is {ZOMBIE_FILE} {DOT} line 12."


def test_the_z21_answer_names_its_ref_whole_and_gets_its_line() -> None:
    record = _record("Z21")
    lines = _zombie_lines()
    ref = f"{ZOMBIE_FILE}:236"
    assert ref in record["raw_answer"]

    found = _by_ref(row_mentions_to_lines(record["raw_answer"], record["source_refs"], lines))

    assert found[ref] == RowLine(236, ref, lines[ref], ref)
    assert lines[ref] == 238  # the chip of this row says line 238
    assert "GYMPLUS" in _file_line(SAMPLES / ZOMBIE_FILE, found[ref].line)
    note = answer_row_note(record["raw_answer"], record["source_refs"], lines)
    assert f"{ref} is {ZOMBIE_FILE} {DOT} line 238" in note
    assert note.startswith(ROW_NOTE_HEAD) and "\n" not in note


def test_a_ref_written_whole_maps_to_exactly_that_ref_even_when_the_number_is_shared() -> None:
    # `row 5` alone is ambiguous between a.csv and b.csv; the whole ref is not
    found = row_mentions_to_lines("See b.csv:5 and a.csv:6.", REFS, LINES)

    assert found == [RowLine(5, "b.csv:5", 30, "b.csv:5"), RowLine(6, "a.csv:6", 8, "a.csv:6")]


def test_a_ref_written_whole_that_is_not_cited_or_has_no_line_gives_nothing() -> None:
    assert row_mentions_to_lines("See z.csv:5 and a.csv:55.", REFS, LINES) == []
    assert row_mentions_to_lines("See c.csv:2.", ["c.csv:2"], {}) == []
    assert row_mentions_to_lines("See c.csv:2.", ["a.csv:5"], {"c.csv:2": 4}) == []
    assert answer_row_note("See z.csv:5.", REFS, LINES) == ""


def test_a_ref_written_whole_and_the_same_row_as_row_n_give_one_entry_in_answer_order() -> None:
    found = row_mentions_to_lines("b.csv:5 is it; in b.csv, row 5 again.", REFS, LINES)
    assert found == [RowLine(5, "b.csv:5", 30, "b.csv:5")]

    mixed = row_mentions_to_lines("Row 6 of a.csv, then b.csv:9.", REFS, LINES)
    assert mixed == [RowLine(6, "a.csv:6", 8), RowLine(9, "b.csv:9", 34, "b.csv:9")]
    reverse = row_mentions_to_lines("b.csv:9 first, then row 6 of a.csv.", REFS, LINES)
    assert [m.ref for m in reverse] == ["b.csv:9", "a.csv:6"]


def test_the_note_says_the_ref_as_the_answer_wrote_it() -> None:
    ref = f"{ZOMBIE_FILE}:236"

    note = row_lines_note([RowLine(236, ref, 238, ref)])
    both = row_lines_note([RowLine(46, "payments.csv:46", 50), RowLine(236, ref, 238, ref)])

    assert note == f"{ROW_NOTE_HEAD}{ref} is {ZOMBIE_FILE} {DOT} line 238."
    assert both == (
        f"{ROW_NOTE_HEAD}row 46 is payments.csv {DOT} line 50, "
        f"{ref} is {ZOMBIE_FILE} {DOT} line 238."
    )


def test_the_z06_card_shows_the_note_with_the_ref_and_its_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(replay, "REPLAY_RUN_PATH", REPLAY_RUN)
    monkeypatch.setattr(first_run, "AUTOLOAD_DEMO", True)
    record = _record("Z06")
    expected = answer_row_note(record["raw_answer"], record["source_refs"], _zombie_lines())

    at = _open("zs")

    values = [element.value for element in at.markdown]
    assert values.count(record["raw_answer"]) == 1  # the recorded text, not edited
    assert [c.value for c in at.caption].count(expected) == 1
    assert expected.endswith(f"{ZOMBIE_FILE}:10 is {ZOMBIE_FILE} {DOT} line 12.")


@pytest.mark.parametrize("prefix", sorted(SCRIPTS))
def test_every_app_writes_the_note_under_cards_and_provoke_results(prefix: str) -> None:
    source = (ROOT / SCRIPTS[prefix]).read_text(encoding="utf-8")

    assert "answer_row_note(explanation.text, alert.source_refs, lines)" in source
    assert 'if explanation.source != "llm":' in source  # never under the fixed template
    assert "answer_row_note(result.raw_answer, refs, lines)" in source  # the Provoke results
    assert "_render_probe_result(" in source
    assert "alert.source_refs" in source
    assert "source_lines_of(" in source
