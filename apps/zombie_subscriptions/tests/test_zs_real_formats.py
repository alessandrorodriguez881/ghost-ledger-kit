"""Tests of the real-format paths of the zombie-subscriptions app (Task RF10).

The first half calls ``_ingest`` of the app (CSV, Norma 43, a Norma 43 named ``.txt``, a Facturae
in the statement slot). The second half drives the app headless with ``AppTest`` (no upload:
DN-RF-22) and checks the demo equivalence of REQ-RF-25: the ``Real formats`` demo shows exactly
the tombstones and alerts of the ``CSV`` demo, up to the row numbers in ``source_refs``. If that
comparison fails, report the failing alert; never weaken it.
All data is synthetic (Finance Rule 5); nothing here reads the system clock.
"""

import ast
import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import apps.zombie_subscriptions.detectors  # noqa: F401  (registers the zs.* detectors)
from apps.zombie_subscriptions.app import _ingest
from apps.zombie_subscriptions.detectors.utils import normalise_alias_map, normalise_date_map
from apps.zombie_subscriptions.settings import (
    DEMO_FORMATS,
    DemoInputs,
    demo_inputs,
    load_config,
    parse_aliases_text,
    parse_dates_text,
)
from ledger_kit.detectors import _restore_registry, _snapshot_registry, registered_names, run_all
from ledger_kit.ingestion.norma43_reader import CONTROL_CHECK_FAILED_MESSAGE
from ledger_kit.ingestion.normaliser import normalise
from ledger_kit.ingestion.sniffer import BANK_STATEMENT_ACCEPTED, unsupported_message
from ledger_kit.models import Alert

ROOT = Path(__file__).resolve().parents[3]
APP_DIR = ROOT / "apps" / "zombie_subscriptions"
APP_PATH = APP_DIR / "app.py"
CONFIG = load_config(APP_DIR / "config.toml")
FACTURAE_SAMPLE = ROOT / "data" / "samples" / "phantom_demo" / "facturae" / "01-p1.xml"
TIMEOUT_SECONDS = 60

CSV_OPTION, REAL_OPTION = "CSV", "Real formats"
CSV_NAME, N43_NAME = "zombie_demo_statement.csv", "zombie_demo_statement.n43"
DEMO_ROWS = 335
DEMO_TOMBSTONES = 3
DEMO_ALERTS = 19
DEMO_METRICS = {"tombstones": "3", "critical": "1", "warning": "4", "info": "14"}
TEXT_AREAS = ("aliases_text", "last_used_text", "cancel_text")


# --- helpers --------------------------------------------------------------------------------------


def _inputs(option: str) -> DemoInputs:
    """The demo inputs of a radio option."""
    return demo_inputs(CONFIG, ROOT, DEMO_FORMATS[option])


def _n43_bytes() -> bytes:
    """The Norma 43 demo statement."""
    return _inputs(REAL_OPTION).statement_bytes


def _tampered_n43_bytes() -> bytes:
    """The demo with one digit of the debit total of its record 33 changed."""
    lines = _n43_bytes().decode("iso-8859-1").split("\r\n")
    index = max(i for i, line in enumerate(lines) if line.startswith("33"))
    last_digit = 38  # position 39 (1-based): the last digit of the debit total, positions 26-39
    trailer = lines[index]
    changed = "1" if trailer[last_digit] != "1" else "2"
    lines[index] = trailer[:last_digit] + changed + trailer[last_digit + 1 :]
    return "\r\n".join(lines).encode("iso-8859-1")


# --- _ingest (REQ-RF-20) --------------------------------------------------------------------------


def test_ingest_reads_the_csv_demo() -> None:
    """A CSV statement gives 335 rows and no quarantine, refs `file:0-based row`."""
    demo = _inputs(CSV_OPTION)

    ledger, quarantine = _ingest(demo.statement_name, demo.statement_bytes, {})

    assert quarantine == [] and len(ledger) == DEMO_ROWS
    assert ledger["source_ref"].iloc[0] == f"{CSV_NAME}:0"


def test_ingest_reads_the_norma43_demo() -> None:
    """A Norma 43 statement gives the same 335 rows, refs `file:line of the 22`."""
    demo = _inputs(REAL_OPTION)

    ledger, quarantine = _ingest(demo.statement_name, demo.statement_bytes, {})

    assert quarantine == [] and len(ledger) == DEMO_ROWS
    assert demo.statement_name == N43_NAME
    first_line = int(ledger["source_ref"].iloc[0].rsplit(":", 1)[1])
    assert ledger["source_ref"].iloc[0] == f"{N43_NAME}:{first_line}" and first_line >= 2
    assert set(ledger["flow"]) == {"debit", "credit"}


def test_ingest_reads_a_norma43_named_txt() -> None:
    """The content decides, not the extension."""
    ledger, quarantine = _ingest("statement.txt", _n43_bytes(), {})

    assert quarantine == [] and len(ledger) == DEMO_ROWS
    assert ledger["source_ref"].iloc[0].startswith("statement.txt:")


def test_ingest_of_a_facturae_gives_the_unsupported_record_and_no_rows() -> None:
    """A Facturae in the statement box is quarantined with the message of REQ-RF-02."""
    data = FACTURAE_SAMPLE.read_bytes()

    ledger, quarantine = _ingest("01-p1.xml", data, {})

    assert ledger.empty
    assert [q["reason"] for q in quarantine] == ["unsupported_format:facturae"]
    assert quarantine[0]["raw"] == unsupported_message(
        "01-p1.xml", "facturae", BANK_STATEMENT_ACCEPTED
    )


def test_ingest_of_a_tampered_norma43_gives_control_records_and_no_rows() -> None:
    """A file that does not add up loads nothing."""
    ledger, quarantine = _ingest("tampered.n43", _tampered_n43_bytes(), {})

    assert ledger.empty
    assert quarantine and all(q["reason"].startswith("control_check_failed:") for q in quarantine)


def test_ingest_caches_the_parse_by_content_and_name() -> None:
    """The same bytes under the same name are parsed once."""
    cache: dict[str, Any] = {}

    _ingest(N43_NAME, _n43_bytes(), cache)
    _ingest(N43_NAME, _n43_bytes(), cache)
    _ingest("other.n43", _n43_bytes(), cache)

    assert len(cache) == 2


# --- app.py structure (REQ-RF-20, REQ-RF-22) ------------------------------------------------------


def _app_tree() -> ast.Module:
    """Parse app.py."""
    return ast.parse(APP_PATH.read_text(encoding="utf-8"))


def _string_constants(tree: ast.Module) -> dict[str, str]:
    """The module-level `NAME = "text"` assignments."""
    found: dict[str, str] = {}
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            found[node.targets[0].id] = node.value.value
    return found


def _calls(tree: ast.Module, suffix: str) -> list[ast.Call]:
    """Every call whose function name ends with `suffix`."""
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and ast.unparse(node.func).endswith(suffix)
    ]


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    """The value of a keyword argument, or None."""
    return next((kw.value for kw in call.keywords if kw.arg == name), None)


def test_uploader_has_the_prefixed_key_and_the_statement_extensions() -> None:
    """One uploader: key `zs_upload_statement`, five extensions, one file."""
    tree = _app_tree()
    constants = _string_constants(tree)
    [uploader] = _calls(tree, "file_uploader")
    key_node = _keyword(uploader, "key")

    assert isinstance(key_node, ast.Name)
    assert constants[key_node.id] == "zs_upload_statement"
    assert ast.literal_eval(_keyword(uploader, "type")) == [  # type: ignore[arg-type]
        "csv",
        "n43",
        "txt",
        "aeb",
        "csb43",
    ]
    assert _keyword(uploader, "accept_multiple_files") is None


def test_demo_format_is_a_horizontal_radio_kept_across_pages() -> None:
    """The radio has the key `zs_demo_format`, is horizontal and is in WIDGET_KEYS."""
    tree = _app_tree()
    constants = _string_constants(tree)
    [radio] = _calls(tree, "st.radio")
    key_node = _keyword(radio, "key")
    widget_keys = next(
        n
        for n in tree.body
        if (
            isinstance(n, ast.Assign)
            and isinstance(n.targets[0], ast.Name)
            and n.targets[0].id == "WIDGET_KEYS"
        )
        or (
            isinstance(n, ast.AnnAssign)
            and isinstance(n.target, ast.Name)
            and n.target.id == "WIDGET_KEYS"
        )
    )
    assert widget_keys.value is not None

    assert isinstance(key_node, ast.Name)
    assert constants[key_node.id] == constants["DEMO_FORMAT_KEY"] == "zs_demo_format"
    assert ast.literal_eval(_keyword(radio, "horizontal")) is True  # type: ignore[arg-type]
    assert "DEMO_FORMAT_KEY" in ast.unparse(widget_keys.value)


def test_load_demo_reads_the_radio_inside_the_callback() -> None:
    """The format is read in `load_demo` (on_click), never written under an `if` button."""
    tree = _app_tree()
    functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    source = ast.unparse(functions["load_demo"])

    assert "DEMO_FORMAT_KEY" in source
    assert "DEMO_FORMATS" in source


# --- AppTest: the app headless --------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Snapshot and restore the global detector registry; use the template path."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert registered_names("zs")
    snapshot = _snapshot_registry()
    try:
        yield
    finally:
        _restore_registry(snapshot)


def _run(source: tuple[str, bytes, str] | None = None) -> AppTest:
    """Run the app headless, optionally with a statement already in the session state."""
    at = AppTest.from_file(str(APP_PATH), default_timeout=TIMEOUT_SECONDS)
    if source is not None:
        at.session_state["source"] = source
    return at.run()


def _demo(option: str) -> AppTest:
    """Select a demo format, click Load demo data and return the run."""
    at = _run()
    at.radio(key="zs_demo_format").set_value(option).run()
    at.button(key="zs_load_demo").click().run()
    assert not at.exception
    return at


def _markdown(at: AppTest) -> list[str]:
    """Every markdown value of the page."""
    return [element.value for element in at.markdown]


def _tombstones(at: AppTest) -> list[str]:
    """The HTML of every tombstone card."""
    return [v for v in _markdown(at) if v.startswith('<div class="zs-tombstone">')]


def _alert_titles(at: AppTest) -> list[str]:
    """The HTML of every alert title."""
    return [v for v in _markdown(at) if v.startswith('<div class="zs-alert-title">')]


def _explanations(at: AppTest) -> list[str]:
    """The text of every alert explanation, as shown (the `write` values)."""
    return [v for v in _markdown(at) if not v.startswith(("<span", "<div", "<style", "**"))]


def _metrics(at: AppTest) -> dict[str, str]:
    """The metrics by last word of the label: tombstones, critical, warning, info."""
    return {m.label.split()[-1]: m.value for m in at.metric}


def _captions(at: AppTest) -> list[str]:
    """Every caption of the page."""
    return [element.value for element in at.caption]


def _frames_and_alerts(at: AppTest) -> tuple[pd.DataFrame, list[Alert]]:
    """The loaded ledger and the alerts, rebuilt from the app's own cache and sidebar texts."""
    [(transactions, _quarantine)] = at.session_state["ingestion_cache"].values()
    ledger, _ = normalise(transactions)
    debit = ledger[ledger["flow"] == "debit"].reset_index(drop=True)
    context = {
        "aliases": normalise_alias_map(parse_aliases_text(at.text_area(key="aliases_text").value)),
        "cancellation_dates": normalise_date_map(
            parse_dates_text(at.text_area(key="cancel_text").value)
        ),
    }
    results = run_all(debit, namespace="zs", context=context)
    return ledger, [alert for result in results for alert in result.alerts]


def _mapped_alerts(at: AppTest) -> list[str]:
    """The alerts with every cited ref replaced by its position in the ledger (design 9.2).

    Alert.id and the explanation are left out because they contain the references. Lists in
    `data` are sorted: their order follows the order of the refs, which differs by format.
    """
    ledger, alerts = _frames_and_alerts(at)
    positions = {ref: position for position, ref in enumerate(ledger["source_ref"])}

    def translate(value: Any) -> Any:
        """Replace every loaded source_ref by its position, at any depth; figures stay as is."""
        if isinstance(value, str) and value in positions:
            return positions[value]
        if isinstance(value, dict):
            return {k: translate(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            items = [translate(v) for v in value]
            return sorted(items, key=lambda i: json.dumps(i, sort_keys=True, default=str))
        return value

    rows = []
    for alert in alerts:
        data = translate(alert.data)
        cited = sorted(positions[ref] for ref in alert.source_refs)
        rows.append(
            json.dumps(
                [alert.detector, alert.severity, alert.title, data, cited],
                sort_keys=True,
                default=str,
            )
        )
    return sorted(rows)


def test_radio_defaults_to_csv_and_offers_both_formats() -> None:
    """The demo format radio starts on CSV."""
    at = _run()

    assert not at.exception
    radio = at.radio(key="zs_demo_format")
    assert radio.value == CSV_OPTION
    assert list(radio.options) == [CSV_OPTION, REAL_OPTION]
    assert list(DEMO_FORMATS) == [CSV_OPTION, REAL_OPTION]


def test_csv_demo_gives_three_tombstones_and_nineteen_alerts() -> None:
    """Nothing changed for CSV: 3 tombstones, 19 alerts (1 critical, 4 warning, 14 info)."""
    at = _demo(CSV_OPTION)

    assert _metrics(at) == DEMO_METRICS
    assert len(_tombstones(at)) == DEMO_TOMBSTONES
    assert len(_alert_titles(at)) == DEMO_ALERTS
    assert at.session_state["source"][2] == CSV_NAME


def test_real_formats_demo_gives_three_tombstones_and_nineteen_alerts() -> None:
    """The Norma 43 demo gives the same counts, from the .n43 file."""
    at = _demo(REAL_OPTION)

    assert _metrics(at) == DEMO_METRICS
    assert len(_tombstones(at)) == DEMO_TOMBSTONES
    assert len(_alert_titles(at)) == DEMO_ALERTS
    assert at.session_state["source"][2] == N43_NAME
    assert not at.sidebar.error and not at.error
    markdown = _markdown(at)
    assert any(f"{N43_NAME}:" in v for v in markdown if v.startswith("**Source refs:**"))


def test_both_demos_show_the_same_tombstone_figures() -> None:
    """Died on, cost since then and yearly cost are the same in both formats."""
    csv = _tombstones(_demo(CSV_OPTION))
    real = _tombstones(_demo(REAL_OPTION))

    assert len(csv) == len(real) == DEMO_TOMBSTONES
    assert sorted(csv) == sorted(real)


def test_both_demos_fill_the_same_aliases_last_used_and_cancellation_texts() -> None:
    """Aliases and dates are keyed by counterparty, which is the same in both files."""
    csv, real = _demo(CSV_OPTION), _demo(REAL_OPTION)

    for key in TEXT_AREAS:
        assert csv.text_area(key=key).value == real.text_area(key=key).value, key
        assert real.text_area(key=key).value
    assert real.text_area(key="cancel_text").value == "GYMPLUS = 2026-07-31"


def test_real_formats_demo_equals_the_csv_demo_element_for_element() -> None:
    """REQ-RF-25: mapped by position, the alert lists are the same, figures included."""
    csv, real = _demo(CSV_OPTION), _demo(REAL_OPTION)

    csv_ledger, csv_alerts = _frames_and_alerts(csv)
    real_ledger, real_alerts = _frames_and_alerts(real)

    assert len(csv_ledger) == len(real_ledger) == DEMO_ROWS
    assert len(csv_alerts) == len(real_alerts) == DEMO_ALERTS
    assert _mapped_alerts(real) == _mapped_alerts(csv)


def test_both_demos_show_the_same_explanations_up_to_the_row_numbers() -> None:
    """The explanation texts differ only where they cite a `file:row` reference."""
    csv, real = _demo(CSV_OPTION), _demo(REAL_OPTION)

    def strip(texts: list[str], name: str) -> list[str]:
        return sorted(re.sub(rf"{re.escape(name)}:\d+", "REF", text) for text in texts)

    assert strip(_explanations(real), N43_NAME) == strip(_explanations(csv), CSV_NAME)


def test_caption_names_the_detected_format() -> None:
    """The line under the title says which format was read."""
    csv = _captions(_demo(CSV_OPTION))
    real = _captions(_demo(REAL_OPTION))

    assert any(c.startswith(f"{CSV_NAME} (CSV): ") for c in csv)
    assert any(c.startswith(f"{N43_NAME} (Norma 43): ") for c in real)


def test_page_shows_the_plain_words_message_for_a_tampered_norma43() -> None:
    """Every control_check_failed record is shown with the incomplete-or-edited message."""
    at = _run(("demo", _tampered_n43_bytes(), "tampered.n43"))

    assert not at.exception
    messages = [element.value for element in at.error]
    assert messages and all(CONTROL_CHECK_FAILED_MESSAGE in m for m in messages)
    assert "incomplete or was edited" in messages[0] and "fresh export" in messages[0]
    [panel] = [element.value for element in at.dataframe]
    assert all(r.startswith("control_check_failed:") for r in panel["reason"])
    assert len(messages) == len(panel)
    assert _tombstones(at) == [] and _alert_titles(at) == []


def test_page_shows_the_unsupported_format_record_for_a_facturae() -> None:
    """A Facturae in the statement box does not crash the page and is listed."""
    at = _run(("demo", FACTURAE_SAMPLE.read_bytes(), "01-p1.xml"))

    assert not at.exception
    [panel] = [element.value for element in at.dataframe]
    assert panel["reason"].tolist() == ["unsupported_format:facturae"]
    assert panel["raw"].tolist() == [
        unsupported_message("01-p1.xml", "facturae", BANK_STATEMENT_ACCEPTED)
    ]


def test_page_reads_a_norma43_named_txt() -> None:
    """A Norma 43 file under a .txt name is read as Norma 43 by the page."""
    at = _run(("demo", _n43_bytes(), "statement.txt"))

    assert not at.exception
    assert any(c.startswith("statement.txt (Norma 43): ") for c in _captions(at))
    assert not at.error
