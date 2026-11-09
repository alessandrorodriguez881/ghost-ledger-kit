"""Tests of the real-format paths of the phantom-invoices app (Task RF9).

The first half drives ``run_pipeline`` and the settings helpers directly: one file or several,
file-name order, duplicate names, unsupported formats, the notes and the plain-words control
message. The second half drives the app headless with ``AppTest`` (no upload: DN-RF-22) and
checks the demo equivalence of REQ-RF-25: the ``Real formats`` demo shows exactly the alerts of
the ``CSV`` demo, up to the row numbers in ``source_refs``. If that comparison fails, the likely
cause is DN-RF-20 (the Facturae rows without a due date lose their IBAN); never weaken it.
All data is synthetic (Finance Rule 5); nothing here reads the system clock.
"""

import ast
import json
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

import apps.phantom_invoices.detectors  # noqa: F401  (registers the pi.* detectors)
from apps.phantom_invoices.prepare import MULTI_RATE_REASON
from apps.phantom_invoices.settings import (
    DEMO_FORMATS,
    DUPLICATE_FILE_REASON,
    MULTI_RATE_NOTE,
    NO_PAYMENT_IBAN_NOTE,
    SIGNATURE_NOTE,
    DemoInputs,
    Pipeline,
    Source,
    demo_inputs,
    invoice_files,
    load_config,
    pipeline_key,
    run_pipeline,
)
from apps.phantom_invoices.tests.pi_builders import generator as gen
from ledger_kit.detectors import _restore_registry, _snapshot_registry, registered_names
from ledger_kit.ingestion.norma43_reader import CONTROL_CHECK_FAILED_MESSAGE
from ledger_kit.ingestion.sniffer import (
    BANK_STATEMENT_ACCEPTED,
    INVOICES_ACCEPTED,
    unsupported_message,
)
from ledger_kit.models import Alert

ROOT = Path(__file__).resolve().parents[3]
APP_DIR = ROOT / "apps" / "phantom_invoices"
APP_PATH = APP_DIR / "app.py"
CONFIG = load_config(APP_DIR / "config.toml")
TIMEOUT_SECONDS = 60

CSV_OPTION, REAL_OPTION = "CSV", "Real formats"
DEMO_CRITICAL, DEMO_WARNING = 3, 6
FACTURAE_FILES = 25
CLEAN_INVOICES = 68
SUPPLIER = "Suministros Ficticios SL"
# Mod-97 valid, deliberately wrong Spanish national check digits (Finance Rule 5).
IBAN = "ES88 2100 0418 5602 0005 1332"
CSV_MULTI_RATE_REASONS = [MULTI_RATE_REASON] * 2
FACTURAE_MULTI_RATE_REASONS = ["multiple_vat_rates"]


# --- builders -----------------------------------------------------------------------------------


def _csv() -> DemoInputs:
    """The inputs of the CSV demo."""
    return demo_inputs(CONFIG, ROOT)


def _real() -> DemoInputs:
    """The inputs of the Real formats demo."""
    return demo_inputs(CONFIG, ROOT, "real")


def _run_demo(demo: DemoInputs) -> Pipeline:
    """Run the pipeline on a demo's files, as the app does."""
    return run_pipeline(demo.invoices, demo.suppliers, demo.payments, demo.as_of)


def _payment_row(iban: str) -> Any:
    """One fictional debit of 121,00 EUR, with or without a counterparty IBAN."""
    return gen.BankRow(date(2026, 3, 15), "-121.00", SUPPLIER, "Synthetic payment", iban)


def _n43(iban: str, name: str = "payments.n43") -> Source:
    """A one-movement Norma 43 payments file."""
    return Source(name, gen.render_norma43([_payment_row(iban)]))


def _tampered_n43() -> Source:
    """A Norma 43 file whose record 33 declares a debit total one cent too high."""
    lines = gen.render_norma43_lines([_payment_row("")])
    trailer = lines[-2]
    assert trailer.startswith("33")
    last_digit = 38  # position 39 (1-based): the last digit of the debit total, positions 26-39
    changed = "1" if trailer[last_digit] != "1" else "2"
    lines[-2] = trailer[:last_digit] + changed + trailer[last_digit + 1 :]
    return Source("tampered.n43", (gen.N43_EOL.join(lines) + gen.N43_EOL).encode("iso-8859-1"))


def _alerts(pipeline: Pipeline) -> list[Alert]:
    """Every alert of the pipeline, detector by detector."""
    return [alert for result in pipeline.results for alert in result.alerts]


def _dump(pipeline: Pipeline) -> list[dict]:
    """The alerts as dicts, in order (Alert.id is a hash of the content, so it is stable)."""
    return [alert.model_dump() for alert in _alerts(pipeline)]


# --- demo inputs and the router (REQ-RF-20, REQ-RF-21, REQ-RF-24) --------------------------------


def test_demo_inputs_csv_is_one_invoices_file_and_real_is_the_facturae_folder() -> None:
    """`csv` keeps today's three files; `real` reads 25 XML files in name order and the .n43."""
    csv, real = _csv(), _real()

    assert [s.name for s in csv.invoices] == ["invoices.csv"]
    assert csv.payments.name == "payments.csv"
    assert len(real.invoices) == FACTURAE_FILES
    assert [s.name for s in real.invoices] == sorted(s.name for s in real.invoices)
    assert all(s.name.endswith(".xml") for s in real.invoices)
    assert real.payments.name == "payments.n43"
    assert csv.suppliers == real.suppliers and csv.suppliers.name == "suppliers.csv"
    assert csv.as_of is None and real.as_of is None


def test_demo_inputs_rejects_an_unknown_format() -> None:
    """Only `csv` and `real` exist."""
    with pytest.raises(ValueError, match="unknown demo format"):
        demo_inputs(CONFIG, ROOT, "pdf")  # type: ignore[arg-type]


def test_demo_format_options_are_the_radio_options() -> None:
    """The radio offers CSV and Real formats, CSV first, mapped to csv and real."""
    assert list(DEMO_FORMATS) == [CSV_OPTION, REAL_OPTION]
    assert DEMO_FORMATS == {CSV_OPTION: "csv", REAL_OPTION: "real"}


def test_run_pipeline_with_one_source_and_with_a_tuple_agree() -> None:
    """A single Source is wrapped: the same pipeline as a one-element tuple, refs per file."""
    first = _real().invoices[0]

    single = run_pipeline(first, None, None, None)
    wrapped = run_pipeline((first,), None, None, None)

    refs = list(single.invoices["source_ref"])
    assert refs and all(ref.startswith(f"{first.name}:") for ref in refs)
    assert refs == list(wrapped.invoices["source_ref"])
    assert _dump(single) == _dump(wrapped)
    assert single.quarantine == wrapped.quarantine == []
    assert pipeline_key(first, None, None, None) == pipeline_key((first,), None, None, None)


def test_invoices_are_read_in_file_name_order_whatever_the_selection_order() -> None:
    """Two selection orders give the same refs, the same alerts and the same cache key."""
    files = _real().invoices
    reverse = tuple(reversed(files))
    assert reverse != files

    forward = run_pipeline(files, None, None, None)
    backward = run_pipeline(reverse, None, None, None)

    assert invoice_files(reverse) == files
    assert list(forward.invoices["source_ref"]) == list(backward.invoices["source_ref"])
    assert _alerts(forward)  # the duplicate invoice of P1 is raised either way
    assert _dump(forward) == _dump(backward)
    assert pipeline_key(files, None, None, None) == pipeline_key(reverse, None, None, None)


def test_every_invoice_gets_the_source_ref_of_its_own_file() -> None:
    """Facturae refs are `file:position`, the position being 1-based (DN-RF-01)."""
    first, second = _real().invoices[:2]

    pipeline = run_pipeline((second, first), None, None, None)

    refs = list(pipeline.invoices["source_ref"])
    assert refs == sorted(refs, key=lambda ref: (ref.split(":")[0], int(ref.split(":")[1])))
    assert {ref.split(":")[0] for ref in refs} == {first.name, second.name}
    assert f"{first.name}:1" in refs


def test_second_file_with_the_same_name_is_quarantined_and_not_read() -> None:
    """`duplicate_file_name`: one record, and only the first file's invoices are loaded."""
    first, other = _real().invoices[:2]
    clone = Source(first.name, other.data)

    pipeline = run_pipeline((first, clone), None, None, None)

    records = [q for q in pipeline.quarantine if q["reason"] == DUPLICATE_FILE_REASON]
    assert len(records) == 1
    assert records[0]["source_file"] == first.name and records[0]["file_kind"] == "invoices"
    assert records[0]["source_row"] is None
    only_first = run_pipeline(first, None, None, None)
    assert list(pipeline.invoices["source_ref"]) == list(only_first.invoices["source_ref"])
    assert len(pipeline.quarantine) == 1


def test_a_facturae_in_the_payments_slot_is_unsupported() -> None:
    """The payments box shows the `unsupported_format:facturae` record; nothing is loaded."""
    facturae = _real().invoices[0]

    pipeline = run_pipeline(None, None, facturae, None)

    assert [(q["reason"], q["file_kind"]) for q in pipeline.quarantine] == [
        ("unsupported_format:facturae", "payments")
    ]
    expected = unsupported_message(facturae.name, "facturae", BANK_STATEMENT_ACCEPTED)
    assert pipeline.quarantine[0]["raw"] == expected
    assert pipeline.payments.empty and pipeline.notes == ()


def test_a_norma43_in_the_invoices_slot_is_unsupported() -> None:
    """The invoices box shows the `unsupported_format:norma43` record; nothing is loaded."""
    n43 = _real().payments

    pipeline = run_pipeline(n43, None, None, None)

    assert [(q["reason"], q["file_kind"]) for q in pipeline.quarantine] == [
        ("unsupported_format:norma43", "invoices")
    ]
    assert pipeline.quarantine[0]["raw"] == unsupported_message(
        n43.name, "norma43", INVOICES_ACCEPTED
    )
    assert pipeline.invoices.empty and pipeline.notes == ()


def test_a_norma43_named_csv_is_read_as_norma43() -> None:
    """The content decides, not the extension (REQ-RF-20)."""
    n43 = _real().payments

    pipeline = run_pipeline(None, None, Source("payments.csv", n43.data), None)

    assert len(pipeline.payments) == 62 and pipeline.quarantine == []
    assert "payments.csv: Norma 43" in pipeline.notes


# --- notes (REQ-RF-23) ----------------------------------------------------------------------------


def test_notes_name_the_detected_formats_and_the_signature_note_follows_facturae() -> None:
    """The Real formats demo names Norma 43 and Facturae and carries the signature note."""
    notes = _run_demo(_real()).notes

    assert "payments.n43: Norma 43" in notes
    assert f"{FACTURAE_FILES} files: Facturae XML" in notes
    assert notes.count(SIGNATURE_NOTE) == 1
    assert NO_PAYMENT_IBAN_NOTE not in notes  # the demo payments carry IBAN records


def test_the_csv_demo_has_no_signature_note() -> None:
    """With CSV only, the signature caption does not appear."""
    notes = _run_demo(_csv()).notes

    assert "invoices.csv: CSV" in notes and "payments.csv: CSV" in notes
    assert SIGNATURE_NOTE not in notes and NO_PAYMENT_IBAN_NOTE not in notes


def test_one_facturae_file_is_named_by_its_own_name() -> None:
    """A single file is named `<name>: Facturae XML`, not counted."""
    facturae = _real().invoices[3]

    notes = run_pipeline(facturae, None, None, None).notes

    assert notes == (f"{facturae.name}: Facturae XML", SIGNATURE_NOTE)


def test_signature_note_text_is_the_one_of_the_requirement() -> None:
    """REQ-RF-23: the caption is verbatim."""
    assert SIGNATURE_NOTE == (
        "Facturae digital signatures (.xsig) are read but not verified: this app does not "
        "check who signed a file."
    )


def test_no_payment_iban_note_when_a_norma43_carries_no_iban_record() -> None:
    """The caption shows for a Norma 43 payments file whose movements have no IBAN."""
    pipeline = run_pipeline(None, None, _n43(""), None)

    assert len(pipeline.payments) == 1 and pipeline.quarantine == []
    assert NO_PAYMENT_IBAN_NOTE in pipeline.notes
    assert NO_PAYMENT_IBAN_NOTE == (
        "This Norma 43 file carries no IBAN for its payments, so the payment-side IBAN checks "
        "are skipped for this file."
    )


def test_no_payment_iban_note_is_silent_when_one_movement_has_an_iban() -> None:
    """A single IBAN record is enough to keep the payment-side checks."""
    pipeline = run_pipeline(None, None, _n43(IBAN), None)

    assert pipeline.payments["iban"].notna().all()
    assert NO_PAYMENT_IBAN_NOTE not in pipeline.notes


def test_no_payment_iban_note_is_only_for_norma43() -> None:
    """A CSV payments file without IBANs does not trigger it, nor does an empty input."""
    csv = Source(
        "payments.csv",
        b"date,amount,currency,counterparty,description,iban\n"
        b"2026-03-15,-121.00,EUR,Suministros Ficticios SL,Synthetic payment,\n",
    )

    assert NO_PAYMENT_IBAN_NOTE not in run_pipeline(None, None, csv, None).notes
    assert NO_PAYMENT_IBAN_NOTE not in run_pipeline(None, None, None, None).notes


def test_a_tampered_norma43_is_quarantined_whole() -> None:
    """A file that does not add up loads nothing and has a control_check_failed record."""
    pipeline = run_pipeline(None, None, _tampered_n43(), None)

    reasons = [q["reason"] for q in pipeline.quarantine]
    assert pipeline.payments.empty
    assert reasons and all(r.startswith("control_check_failed:") for r in reasons)
    assert {q["file_kind"] for q in pipeline.quarantine} == {"payments"}
    assert NO_PAYMENT_IBAN_NOTE not in pipeline.notes  # nothing was loaded


def test_multi_rate_note_names_both_quarantine_reasons() -> None:
    """The note under the quarantine panel covers the CSV and the Facturae reason."""
    assert MULTI_RATE_REASON in MULTI_RATE_NOTE
    assert "multiple_vat_rates" in MULTI_RATE_NOTE


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


def test_uploaders_have_the_prefixed_keys_types_and_multiple_invoice_files() -> None:
    """REQ-RF-20, REQ-RF-22: three prefixed uploaders; only the invoices box takes several."""
    tree = _app_tree()
    constants = _string_constants(tree)
    uploaders: dict[str, tuple[Any, bool]] = {}
    for call in _calls(tree, "file_uploader"):
        key_node = _keyword(call, "key")
        assert isinstance(key_node, ast.Name)
        multiple = _keyword(call, "accept_multiple_files")
        uploaders[constants[key_node.id]] = (
            ast.literal_eval(_keyword(call, "type")),  # type: ignore[arg-type]
            multiple is not None and ast.literal_eval(multiple),
        )

    assert uploaders == {
        "pi_upload_invoices": (["csv", "json", "xml", "xsig"], True),
        "pi_upload_suppliers": ("csv", False),
        "pi_upload_payments": (["csv", "n43", "txt", "aeb", "csb43"], False),
    }
    strings = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant)}
    assert not strings & {"upload_invoices", "upload_suppliers", "upload_payments"}


def test_demo_format_is_a_horizontal_radio_kept_across_pages() -> None:
    """The radio has the key `pi_demo_format`, is horizontal and is in WIDGET_KEYS."""
    tree = _app_tree()
    constants = _string_constants(tree)
    [radio] = [c for c in _calls(tree, "sidebar.radio")]
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
    assert constants[key_node.id] == constants["DEMO_FORMAT_KEY"] == "pi_demo_format"
    assert ast.literal_eval(_keyword(radio, "horizontal")) is True  # type: ignore[arg-type]
    assert "DEMO_FORMAT_KEY" in ast.unparse(widget_keys.value)


# --- AppTest: the app headless --------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Snapshot and restore the global detector registry; use the template path."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert registered_names("pi")
    snapshot = _snapshot_registry()
    try:
        yield
    finally:
        _restore_registry(snapshot)


def _run(sources: dict[str, Any] | None = None) -> AppTest:
    """Run the app headless, optionally with sources already in the session state."""
    at = AppTest.from_file(str(APP_PATH), default_timeout=TIMEOUT_SECONDS)
    if sources is not None:
        at.session_state["sources"] = sources
    return at.run()


def _demo(option: str) -> AppTest:
    """Select a demo format, click Load demo data and return the run."""
    at = _run()
    at.radio(key="pi_demo_format").set_value(option).run()
    at.button(key="pi_load_demo").click().run()
    assert not at.exception
    return at


def _pipeline(at: AppTest) -> Pipeline:
    """The one cached Pipeline of the run."""
    [pipeline] = at.session_state["pipeline_cache"].values()
    return pipeline


def _captions(at: AppTest) -> list[str]:
    """Every caption of the page."""
    return [element.value for element in at.caption]


def _positions(pipeline: Pipeline) -> dict[str, tuple[str, int]]:
    """source_ref -> (frame, position in the loaded frame), for the three loaded frames."""
    mapping: dict[str, tuple[str, int]] = {}
    frames = (
        ("invoices", pipeline.invoices),
        ("suppliers", pipeline.suppliers),
        ("payments", pipeline.payments),
    )
    for name, frame in frames:
        for position, ref in enumerate(frame["source_ref"]):
            assert ref not in mapping, ref
            mapping[ref] = (name, position)
    return mapping


def _mapped_alerts(pipeline: Pipeline) -> list[str]:
    """The alerts with every cited ref replaced by its position (REQ-RF-25, design 9.2).

    Alert.id and the explanation are left out because they contain the references. Lists in
    `data` are sorted: their order follows the order of the refs, which differs by format.
    """
    positions = _positions(pipeline)

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
    for alert in _alerts(pipeline):
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


def _severity_counts(pipeline: Pipeline) -> dict[str, int]:
    """Alerts per severity."""
    alerts = _alerts(pipeline)
    return {s: sum(a.severity == s for a in alerts) for s in ("critical", "warning", "info")}


def test_radio_defaults_to_csv_and_offers_both_formats() -> None:
    """The demo format radio starts on CSV."""
    at = _run()

    assert not at.exception
    radio = at.radio(key="pi_demo_format")
    assert radio.value == CSV_OPTION
    assert list(radio.options) == [CSV_OPTION, REAL_OPTION]


def test_csv_demo_still_gives_nine_alerts_and_two_multi_rate_records() -> None:
    """Nothing changed for CSV: 3 critical and 6 warning, two multi-rate rows quarantined."""
    at = _demo(CSV_OPTION)
    pipeline = _pipeline(at)

    assert {m.label.split()[-1]: m.value for m in at.metric} == {
        "critical": str(DEMO_CRITICAL),
        "warning": str(DEMO_WARNING),
    }
    assert [q["reason"] for q in pipeline.quarantine] == CSV_MULTI_RATE_REASONS
    assert len(pipeline.invoices) == CLEAN_INVOICES
    assert SIGNATURE_NOTE not in _captions(at)
    assert at.session_state["sources"]["invoices"] == tuple(_csv().invoices)


def test_real_formats_demo_gives_the_same_nine_alerts_and_one_multi_rate_record() -> None:
    """Facturae + Norma 43: 3 critical, 6 warning; one multiple_vat_rates record in the panel."""
    at = _demo(REAL_OPTION)
    pipeline = _pipeline(at)

    assert {m.label.split()[-1]: m.value for m in at.metric} == {
        "critical": str(DEMO_CRITICAL),
        "warning": str(DEMO_WARNING),
    }
    assert len(_alerts(pipeline)) == DEMO_CRITICAL + DEMO_WARNING
    assert [q["reason"] for q in pipeline.quarantine] == FACTURAE_MULTI_RATE_REASONS
    assert len(pipeline.invoices) == CLEAN_INVOICES
    assert len(pipeline.payments) == 62
    [panel] = [element.value for element in at.dataframe]
    assert panel["reason"].tolist() == FACTURAE_MULTI_RATE_REASONS
    assert len(at.session_state["sources"]["invoices"]) == FACTURAE_FILES
    assert pipeline.as_of_used == date(2026, 10, 30)


def test_real_formats_demo_equals_the_csv_demo_element_for_element() -> None:
    """REQ-RF-25: mapped by position, the alert lists are the same, figures included."""
    csv = _pipeline(_demo(CSV_OPTION))
    real = _pipeline(_demo(REAL_OPTION))

    expected = {"critical": DEMO_CRITICAL, "warning": DEMO_WARNING, "info": 0}
    assert _severity_counts(csv) == expected
    assert _severity_counts(real) == expected
    assert len(csv.invoices) == len(real.invoices) == CLEAN_INVOICES
    assert len(csv.suppliers) == len(real.suppliers)
    assert len(csv.payments) == len(real.payments)
    assert csv.as_of_used == real.as_of_used
    assert _mapped_alerts(real) == _mapped_alerts(csv)


def test_page_shows_the_signature_caption_and_the_format_names_for_facturae_only() -> None:
    """REQ-RF-23: the caption appears with the Facturae demo and not with the CSV demo."""
    real = _captions(_demo(REAL_OPTION))
    csv = _captions(_demo(CSV_OPTION))

    assert SIGNATURE_NOTE in real
    assert "payments.n43: Norma 43" in real
    assert f"{FACTURAE_FILES} files: Facturae XML" in real
    assert NO_PAYMENT_IBAN_NOTE not in real
    assert SIGNATURE_NOTE not in csv
    assert "payments.csv: CSV" in csv


def test_quarantine_note_names_both_reasons_on_the_page() -> None:
    """The quarantine panel's explanation covers the CSV and the Facturae reason."""
    for option in (CSV_OPTION, REAL_OPTION):
        assert MULTI_RATE_NOTE in _captions(_demo(option))


def test_page_shows_the_no_iban_caption_for_a_norma43_without_iban_records() -> None:
    """The caption shows once, with the page otherwise intact."""
    csv = _csv()
    sources = {"invoices": tuple(csv.invoices), "suppliers": csv.suppliers, "payments": _n43("")}

    at = _run(sources)

    assert not at.exception
    assert _captions(at).count(NO_PAYMENT_IBAN_NOTE) == 1


def test_page_does_not_show_the_no_iban_caption_when_the_payments_carry_ibans() -> None:
    """The Norma 43 of the Real formats demo has IBAN records: no caption."""
    assert NO_PAYMENT_IBAN_NOTE not in _captions(_demo(REAL_OPTION))


def test_page_shows_the_plain_words_message_for_a_tampered_norma43() -> None:
    """Every control_check_failed record is shown with the incomplete-or-edited message."""
    csv = _csv()
    sources = {
        "invoices": tuple(csv.invoices),
        "suppliers": csv.suppliers,
        "payments": _tampered_n43(),
    }

    at = _run(sources)

    assert not at.exception
    messages = [element.value for element in at.error]
    control = [q for q in _pipeline(at).quarantine if q["reason"].startswith("control_check")]
    assert len(messages) == len(control) >= 1
    assert all(CONTROL_CHECK_FAILED_MESSAGE in m for m in messages)
    assert "incomplete or was edited" in messages[0] and "fresh export" in messages[0]


def test_page_shows_the_unsupported_format_record_for_a_facturae_in_the_payments_box() -> None:
    """The page does not crash and lists the `unsupported_format:facturae` record."""
    csv = _csv()
    facturae = _real().invoices[0]
    sources = {"invoices": tuple(csv.invoices), "suppliers": csv.suppliers, "payments": facturae}

    at = _run(sources)

    assert not at.exception
    [panel] = [element.value for element in at.dataframe]
    assert "unsupported_format:facturae" in panel["reason"].tolist()
    raw = panel.loc[panel["reason"] == "unsupported_format:facturae", "raw"].tolist()
    assert raw == [unsupported_message(facturae.name, "facturae", BANK_STATEMENT_ACCEPTED)]


def test_pipeline_cache_has_one_entry_per_distinct_input() -> None:
    """Loading the same demo twice reuses the cached pipeline."""
    at = _demo(REAL_OPTION)
    at.button(key="pi_load_demo").click().run()

    assert not at.exception
    assert len(at.session_state["pipeline_cache"]) == 1
