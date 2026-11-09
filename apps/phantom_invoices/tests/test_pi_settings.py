"""Tests for settings.py: config.toml, demo inputs and run_pipeline (Task P17).

All CSV text is encoded to bytes before it is written or handed to the pipeline, so Windows never
adds carriage returns. Every identifier follows Finance Rule 5; every name is fictional.
"""

import ast
import json
import tomllib
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from apps.phantom_invoices.detectors.utils import Reconciliation
from apps.phantom_invoices.prepare import MULTI_RATE_REASON
from apps.phantom_invoices.settings import (
    DemoInputs,
    Pipeline,
    Source,
    demo_inputs,
    load_config,
    run_pipeline,
    to_date,
)
from ledger_kit.detectors import DetectorResult
from ledger_kit.ingestion.normaliser import CANONICAL_COLUMNS, INVOICE_COLUMNS, SUPPLIER_COLUMNS
from ledger_kit.utils.money import net_total, percent_of

APP_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = APP_DIR / "config.toml"
SETTINGS_PATH = APP_DIR / "settings.py"

# Mod-97 valid, deliberately wrong Spanish national check digits (Finance Rule 5).
IBAN = "ES88 2100 0418 5602 0005 1332"
TAX_ID = "B00000001"
SUPPLIER = "Suministros Ficticios SL"

INVOICE_HEADER = (
    "invoice_number,supplier_name,supplier_tax_id,issue_date,due_date,base_amount,vat_rate,"
    "vat_amount,total,currency,iban\n"
)
INVOICES_CSV = (
    INVOICE_HEADER
    + f"F-2026-0001,{SUPPLIER},{TAX_ID},2026-03-01,2026-03-31,100.00,21,21.00,121.00,EUR,{IBAN}\n"
    + f"F-2026-0002,{SUPPLIER},{TAX_ID},2026-03-10,,200.00,21,42.00,242.00,EUR,\n"
)
SUPPLIERS_CSV = f"supplier_name,tax_id,iban\n{SUPPLIER},{TAX_ID},{IBAN}\n"
PAYMENT_HEADER = "date,amount,currency,counterparty,description,iban\n"
PAYMENTS_CSV = (
    PAYMENT_HEADER
    + f"2026-03-15,-121.00,EUR,{SUPPLIER},Synthetic payment,{IBAN}\n"
    + "2026-03-20,50.00,EUR,Cliente Ficticio,Synthetic refund,\n"
)
THRESHOLD_NAMES = (
    "DUPLICATE_WINDOW_DAYS",
    "SAME_NUMBER_WINDOW_DAYS",
    "VAT_TOLERANCE",
    "TOTAL_TOLERANCE",
    "ALLOWED_VAT_RATES",
    "PAYMENT_MATCH_WINDOW_DAYS",
    "UNPAID_GRACE_DAYS",
    "MATCH_AMOUNT_TOLERANCE",
    "DUPLICATE_TOTAL_TOLERANCE",
)
SECRET_WORDS = ("api_key", "apikey", "secret", "token", "password")
LEDGER_CORE_QUARANTINE_KEYS = {"source_file", "source_row", "reason", "raw"}
CLOCK_ATTRIBUTES = frozenset({"today", "now", "utcnow"})


def _src(name: str, text: str) -> Source:
    """Return a Source whose bytes are the UTF-8 encoding of `text`."""
    return Source(name, text.encode("utf-8"))


def _minimal() -> tuple[Source, Source, Source]:
    """Return the invoices, suppliers and payments sources of the minimal fixture."""
    return (
        _src("invoices.csv", INVOICES_CSV),
        _src("suppliers.csv", SUPPLIERS_CSV),
        _src("payments.csv", PAYMENTS_CSV),
    )


# Tier 1: normal cases


def test_load_config_reads_demo_paths() -> None:
    """config.toml names the three demo files."""
    config = load_config(CONFIG_PATH)

    assert config["demo"]["suppliers_path"] == "data/samples/phantom_demo/suppliers.csv"
    assert config["demo"]["invoices_path"] == "data/samples/phantom_demo/invoices.csv"
    assert config["demo"]["payments_path"] == "data/samples/phantom_demo/payments.csv"
    assert config["demo"]["payments_n43_path"] == "data/samples/phantom_demo/payments.n43"
    assert config["demo"]["facturae_dir"] == "data/samples/phantom_demo/facturae"
    assert "as_of" not in config["demo"]


def test_to_date_accepts_string_and_date() -> None:
    """A TOML string, a TOML date and a datetime all give a datetime.date."""
    assert to_date("2026-10-30") == date(2026, 10, 30)
    assert to_date(date(2026, 10, 30)) == date(2026, 10, 30)
    converted = to_date(datetime(2026, 10, 30, 12, 0))
    assert converted == date(2026, 10, 30)
    assert type(converted) is date


def test_demo_inputs_reads_three_files_as_sources(tmp_path: Path) -> None:
    """The three paths are read as bytes, relative to the root; as_of is optional."""
    folder = tmp_path / "demo"
    folder.mkdir()
    (folder / "invoices.csv").write_bytes(INVOICES_CSV.encode("utf-8"))
    (folder / "suppliers.csv").write_bytes(SUPPLIERS_CSV.encode("utf-8"))
    (folder / "payments.csv").write_bytes(PAYMENTS_CSV.encode("utf-8"))
    config = {
        "demo": {
            "invoices_path": "demo/invoices.csv",
            "suppliers_path": "demo/suppliers.csv",
            "payments_path": "demo/payments.csv",
        }
    }

    demo = demo_inputs(config, tmp_path)
    with_as_of = demo_inputs({"demo": {**config["demo"], "as_of": "2026-10-30"}}, tmp_path)

    assert isinstance(demo, DemoInputs)
    assert demo.invoices == (Source("invoices.csv", INVOICES_CSV.encode("utf-8")),)
    assert demo.suppliers == Source("suppliers.csv", SUPPLIERS_CSV.encode("utf-8"))
    assert demo.payments == Source("payments.csv", PAYMENTS_CSV.encode("utf-8"))
    assert demo.as_of is None
    assert with_as_of.as_of == date(2026, 10, 30)


def test_run_pipeline_on_minimal_fixtures() -> None:
    """Three small CSVs give clean frames, as_of, four results and a reconciliation."""
    invoices, suppliers, payments = _minimal()

    pipeline = run_pipeline(invoices, suppliers, payments, None)

    assert isinstance(pipeline, Pipeline)
    assert list(pipeline.invoices["source_ref"]) == ["invoices.csv:0", "invoices.csv:1"]
    assert list(pipeline.suppliers["source_ref"]) == ["suppliers.csv:0"]
    assert list(pipeline.payments["source_ref"]) == ["payments.csv:0", "payments.csv:1"]
    assert pipeline.quarantine == []
    assert pipeline.as_of_used == date(2026, 3, 20)
    assert len(pipeline.results) == 4
    assert all(isinstance(result, DetectorResult) for result in pipeline.results)
    assert sorted(result.name for result in pipeline.results) == [
        "pi.duplicate_invoice",
        "pi.iban_change",
        "pi.reconciliation",
        "pi.vat_error",
    ]
    assert sum(len(result.alerts) for result in pipeline.results) == 0
    assert isinstance(pipeline.reconciliation, Reconciliation)
    assert pipeline.reconciliation.invoice_buckets == {
        "invoices.csv:0": "matched",
        "invoices.csv:1": "open_not_due",
    }
    assert pipeline.invoices["total"].iloc[0] == Decimal("121.00")


def test_config_has_only_demo_section_and_no_threshold_names() -> None:
    """REQ-PI-59: only [demo] paths; no threshold constant name and no secret in the file."""
    text = CONFIG_PATH.read_text(encoding="utf-8")
    config = tomllib.loads(text)

    assert set(config) == {"demo"}
    assert set(config["demo"]) <= {
        "suppliers_path",
        "invoices_path",
        "payments_path",
        "payments_n43_path",
        "facturae_dir",
        "as_of",
    }
    for name in THRESHOLD_NAMES:
        assert name not in text, name
    for word in SECRET_WORDS:
        assert word not in text.lower(), word


# Tier 2: edge cases


def test_missing_files_are_empty_inputs_with_canonical_columns() -> None:
    """None for every input gives empty canonical frames and no alert (REQ-ING-28)."""
    pipeline = run_pipeline(None, None, None, None)

    assert tuple(pipeline.invoices.columns) == INVOICE_COLUMNS
    assert tuple(pipeline.suppliers.columns) == SUPPLIER_COLUMNS
    assert tuple(pipeline.payments.columns) == CANONICAL_COLUMNS
    assert pipeline.invoices.empty and pipeline.suppliers.empty and pipeline.payments.empty
    assert pipeline.quarantine == []
    assert pipeline.as_of_used is None
    assert len(pipeline.results) == 4
    assert [result.alerts for result in pipeline.results] == [[], [], [], []]
    assert pipeline.reconciliation.invoice_buckets == {}
    assert pipeline.reconciliation.payment_buckets == {}


def test_only_invoices_given_still_runs_all_detectors() -> None:
    """Without the supplier master and payments the other two inputs are empty frames."""
    invoices, _, _ = _minimal()

    pipeline = run_pipeline(invoices, None, None, None)

    assert len(pipeline.invoices) == 2
    assert pipeline.suppliers.empty and pipeline.payments.empty
    assert tuple(pipeline.suppliers.columns) == SUPPLIER_COLUMNS
    assert len(pipeline.results) == 4
    assert pipeline.as_of_used == date(2026, 3, 10)


def test_json_invoices_routed_to_json_reader() -> None:
    """A file name ending in .json is parsed as a JSON array of invoice objects."""
    document = [
        {
            "invoice_number": "F-2026-0001",
            "supplier_name": SUPPLIER,
            "supplier_tax_id": TAX_ID,
            "issue_date": "2026-03-01",
            "due_date": "2026-03-31",
            "base_amount": "100.00",
            "vat_rate": "21",
            "vat_amount": "21.00",
            "total": "121.00",
            "currency": "EUR",
        }
    ]
    source = Source("invoices.JSON", json.dumps(document).encode("utf-8"))

    pipeline = run_pipeline(source, None, None, None)

    assert list(pipeline.invoices["source_ref"]) == ["invoices.JSON:0"]
    assert pipeline.invoices["total"].iloc[0] == Decimal("121.00")
    assert pipeline.quarantine == []


def test_multi_rate_rows_in_quarantine_tagged_with_file_kind() -> None:
    """Both rows of a multi-rate invoice leave the ledger and are quarantined for invoices."""
    text = (
        INVOICE_HEADER
        + f"F-2026-0007,{SUPPLIER},{TAX_ID},2026-03-05,2026-04-04,100.00,21,21.00,121.00,EUR,\n"
        + f"F-2026-0007,{SUPPLIER},{TAX_ID},2026-03-05,2026-04-04,50.00,10,5.00,55.00,EUR,\n"
        + f"F-2026-0008,{SUPPLIER},{TAX_ID},2026-03-06,2026-04-05,100.00,21,21.00,121.00,EUR,\n"
    )

    pipeline = run_pipeline(_src("invoices.csv", text), None, None, None)

    assert list(pipeline.invoices["source_ref"]) == ["invoices.csv:2"]
    assert [q["reason"] for q in pipeline.quarantine] == [MULTI_RATE_REASON] * 2
    assert [q["source_row"] for q in pipeline.quarantine] == [0, 1]
    assert {q["file_kind"] for q in pipeline.quarantine} == {"invoices"}


def test_quarantine_records_keep_ledger_core_shape() -> None:
    """Reader records keep source_file/source_row/reason/raw; only file_kind is added."""
    bad_invoice = f"F-2026-0009,{SUPPLIER},{TAX_ID},2026-03-01,,100.00,21,21.00,121.00,,\n"
    bad_payment = f"not-a-date,-10.00,EUR,{SUPPLIER},Synthetic payment,\n"
    invoices = _src("invoices.csv", INVOICE_HEADER + bad_invoice)
    payments = _src("payments.csv", PAYMENT_HEADER + bad_payment)

    pipeline = run_pipeline(invoices, None, payments, None)

    kinds = {q["file_kind"]: q for q in pipeline.quarantine}
    assert set(kinds) == {"invoices", "payments"}
    assert kinds["invoices"]["reason"] == "missing_field:currency"
    assert kinds["payments"]["reason"] == "unparseable_date"
    for record in pipeline.quarantine:
        assert set(record) == LEDGER_CORE_QUARANTINE_KEYS | {"file_kind"}
    assert kinds["invoices"]["source_file"] == "invoices.csv"
    assert kinds["invoices"]["source_row"] == 0
    assert pipeline.invoices.empty and pipeline.payments.empty


def test_explicit_as_of_wins_over_data() -> None:
    """An explicit as_of is used even when the data holds later dates."""
    invoices, suppliers, payments = _minimal()

    pipeline = run_pipeline(invoices, suppliers, payments, date(2026, 1, 1))

    assert pipeline.as_of_used == date(2026, 1, 1)


def test_as_of_used_is_none_without_any_date() -> None:
    """No invoice and no payment date and no explicit as_of: as_of_used is None."""
    pipeline = run_pipeline(None, _minimal()[1], None, None)

    assert pipeline.as_of_used is None


def test_pipeline_does_not_read_the_clock() -> None:
    """as_of_used is a function of the data, and settings.py has no clock call."""
    invoices, suppliers, payments = _minimal()
    first = run_pipeline(invoices, suppliers, payments, None)
    second = run_pipeline(invoices, suppliers, payments, None)
    tree = ast.parse(SETTINGS_PATH.read_text(encoding="utf-8"))
    clock_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in CLOCK_ATTRIBUTES
    ]

    assert first.as_of_used == second.as_of_used == date(2026, 3, 20)
    assert clock_calls == []


def test_credits_in_payments_are_passed_through_not_filtered() -> None:
    """REQ-PI-03: the payments frame keeps credits; the detectors filter debits themselves."""
    invoices, suppliers, payments = _minimal()

    pipeline = run_pipeline(invoices, suppliers, payments, None)

    assert set(pipeline.payments["flow"]) == {"debit", "credit"}
    assert len(pipeline.payments) == 2


# Tier 3: property-based test

NUMBER_BASES = ("100.00", "150.00", "200.00")  # one fixed base per invoice number


def _invoice_row(number_index: int, offset: int) -> str:
    """Return one CSV row; VAT and total come from the money helpers."""
    base = Decimal(NUMBER_BASES[number_index])
    vat = percent_of(base, Decimal("21"))
    total = net_total([base, vat], [])
    issue = date(2026, 3, 1) + timedelta(days=offset)
    return (
        f"F-2026-{number_index + 1:04d},{SUPPLIER},{TAX_ID},{issue.isoformat()},,"
        f"{base},21,{vat},{total},EUR,\n"
    )


def _fingerprint(pipeline: Pipeline) -> list[str]:
    """Return the alerts without ids and source_refs, sorted: what a row shuffle must keep."""
    return sorted(
        repr((a.detector, a.severity, a.title, sorted(a.data.items())))
        for result in pipeline.results
        for a in result.alerts
    )


@settings(max_examples=200, deadline=None)
@given(
    rows=st.lists(st.tuples(st.integers(0, 2), st.integers(0, 30)), min_size=1, max_size=6),
    data=st.data(),
)
def test_run_pipeline_shuffled_rows_same_alerts(
    rows: list[tuple[int, int]], data: st.DataObject
) -> None:
    """Reordering the rows of the invoices file never changes the alerts (up to source_refs)."""
    shuffled = data.draw(st.permutations(rows))
    original = _src("invoices.csv", INVOICE_HEADER + "".join(_invoice_row(*r) for r in rows))
    permuted = _src("invoices.csv", INVOICE_HEADER + "".join(_invoice_row(*r) for r in shuffled))

    first = run_pipeline(original, None, None, None)
    second = run_pipeline(permuted, None, None, None)

    assert len(first.invoices) == len(second.invoices) == len(rows)
    assert _fingerprint(first) == _fingerprint(second)
    assert first.as_of_used == second.as_of_used
