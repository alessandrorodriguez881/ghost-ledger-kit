"""End-to-end test of the committed phantom demo (Task P24, design 15.6 and 16.4).

The three files of data/samples/phantom_demo/ go through ``run_pipeline``, the same path the
Streamlit app uses. The demo must raise exactly 9 alerts (3 critical, 6 warning). If it does not,
fix the generator or config.toml and regenerate the CSVs; never a detector to fit the data.
All data is synthetic (Finance Rule 5); nothing here reads the system clock.
"""

import json
import random
import re
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from freezegun import freeze_time

from apps.phantom_invoices.detectors.utils import (
    as_text,
    attribute_payment,
    build_master,
    iban_key,
    tax_key,
)
from apps.phantom_invoices.explain_support import (
    HallucinatingStubClient,
    explain_alert,
    template_for,
)
from apps.phantom_invoices.prepare import MULTI_RATE_REASON
from apps.phantom_invoices.settings import (
    Pipeline,
    Source,
    demo_inputs,
    load_config,
    run_pipeline,
)
from apps.phantom_invoices.tests.pi_builders import generator
from ledger_kit.detectors import loaded_source_refs
from ledger_kit.explainer import fill_fallback
from ledger_kit.models import Alert

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = REPO_ROOT / "apps" / "phantom_invoices" / "config.toml"
PI_NAMES = {"pi.duplicate_invoice", "pi.iban_change", "pi.reconciliation", "pi.vat_error"}
LATEST_DATE = date(2026, 10, 30)
INJECTED = "99999.99"
CLEAN_INVOICE_ROWS = 68  # 70 invoice rows minus the two multi-rate rows

# What each planted supplier of PHANTOM_CASES must raise: (detector, variant, severity).
DUP, IBAN, VAT, REC = "pi.duplicate_invoice", "pi.iban_change", "pi.vat_error", "pi.reconciliation"
EXPECTED_BY_CASE: dict[str, list[tuple[str, str, str]]] = {
    "P1": [(DUP, "same_number", "critical")],
    "P2": [],
    "P3": [(DUP, "near_identical_number", "warning")],
    "P4": [],
    "P5": [(IBAN, "invoice_iban_differs_from_master", "critical")],
    "P6": [],
    "P7": [(VAT, "vat_amount_mismatch", "warning")],
    "P8": [],
    "P9": [(REC, "payment_without_invoice", "warning")],
    "P10": [(DUP, "same_total_close_dates", "warning")],
    "P11": [],
    "P12": [(IBAN, "iban_invalid", "warning")],
    "NON_MASTER_PAYMENT": [(IBAN, "payment_to_non_master_iban", "critical")],
    "OVERDUE": [(REC, "invoice_overdue", "warning")],
    "OPEN_NOT_DUE": [],
    "MULTI_RATE": [],
}


def _sources() -> tuple[Source, Source, Source, date | None]:
    """The invoices, suppliers and payments Sources of [demo] in config.toml, and its as_of."""
    demo = demo_inputs(load_config(CONFIG_PATH), REPO_ROOT)
    return demo.invoices, demo.suppliers, demo.payments, demo.as_of


def _run(sources: tuple[Source, Source, Source, date | None] | None = None) -> Pipeline:
    """Run the app's pipeline on the demo inputs (or on the given sources)."""
    invoices, suppliers, payments, as_of = sources or _sources()
    return run_pipeline(invoices, suppliers, payments, as_of)


@pytest.fixture(scope="module")
def pipeline() -> Pipeline:
    """The pipeline of the committed demo, computed once for the module."""
    return _run()


def _alerts(pipeline: Pipeline) -> list[Alert]:
    """Every alert of the pipeline, detector by detector."""
    return [alert for result in pipeline.results for alert in result.alerts]


def _records(frame: Any) -> list[dict]:
    """The rows of a frame as dicts."""
    return frame.to_dict("records")


def _refs_of_invoice(pipeline: Pipeline, number: str) -> list[str]:
    """The source_refs of the invoice rows with this invoice number."""
    rows = _records(pipeline.invoices)
    return sorted(r["source_ref"] for r in rows if r["invoice_number"] == number)


def _supplier_ref(pipeline: Pipeline, tax_id: str) -> str:
    """The source_ref of the master row of a supplier."""
    key = tax_key(tax_id)
    [ref] = [
        r["source_ref"]
        for r in _records(pipeline.suppliers)
        if tax_key(as_text(r["tax_id"]) or "") == key
    ]
    return ref


def _refs_of_supplier(pipeline: Pipeline, tax_id: str) -> set[str]:
    """Every loaded row of one supplier: its invoices, master row and attributed payments."""
    key = tax_key(tax_id)
    refs = {
        r["source_ref"]
        for r in _records(pipeline.invoices)
        if tax_key(as_text(r["supplier_tax_id"]) or "") == key
    }
    refs.add(_supplier_ref(pipeline, tax_id))
    master = build_master(pipeline.suppliers)
    for payment in _records(pipeline.payments):
        owner = attribute_payment(payment, master)
        if owner is not None and tax_key(as_text(owner.get("tax_id")) or "") == key:
            refs.add(payment["source_ref"])
    return refs


def _alerts_of_supplier(pipeline: Pipeline, tax_id: str) -> list[Alert]:
    """The alerts that cite at least one row of this supplier."""
    refs = _refs_of_supplier(pipeline, tax_id)
    return [a for a in _alerts(pipeline) if refs & set(a.source_refs)]


def _signature(alert: Alert) -> tuple[str, str, str]:
    """(detector, variant, severity) of an alert."""
    return alert.detector, alert.data["variant"], alert.severity


def _by_variant(pipeline: Pipeline) -> dict[str, Alert]:
    """The alerts keyed by variant; the demo must raise each variant exactly once."""
    alerts = _alerts(pipeline)
    by_variant = {a.data["variant"]: a for a in alerts}
    assert len(by_variant) == len(alerts)
    return by_variant


def test_demo_raises_exactly_nine_alerts_3_critical_6_warning(pipeline: Pipeline) -> None:
    """The nine alerts of design 15.6, each with the evidence of its planted case."""
    alerts = _alerts(pipeline)
    by_variant = _by_variant(pipeline)

    assert len(alerts) == 9
    assert sorted(a.severity for a in alerts) == ["critical"] * 3 + ["warning"] * 6
    critical = {a.data["variant"] for a in alerts if a.severity == "critical"}
    assert critical == {
        "same_number",
        "invoice_iban_differs_from_master",
        "payment_to_non_master_iban",
    }
    assert set(by_variant) == critical | {
        "near_identical_number",
        "same_total_close_dates",
        "iban_invalid",
        "vat_amount_mismatch",
        "payment_without_invoice",
        "invoice_overdue",
    }

    p1 = by_variant["same_number"]
    assert p1.source_refs == _refs_of_invoice(pipeline, "F-2026-0310")
    assert p1.data["invoice_count"] == 2

    p3 = by_variant["near_identical_number"]
    expected = _refs_of_invoice(pipeline, "F-2026-0042") + _refs_of_invoice(pipeline, "F2026-042")
    assert set(p3.source_refs) == set(expected) and p3.data["days_apart"] == 3

    p10 = by_variant["same_total_close_dates"]  # only FAC-0101 and FAC-0102 (gap 6 days)
    expected = _refs_of_invoice(pipeline, "FAC-0101") + _refs_of_invoice(pipeline, "FAC-0102")
    assert set(p10.source_refs) == set(expected) and p10.data["days_apart"] == 6

    p12 = by_variant["iban_invalid"]  # only TR-2026-014; TR-2026-015 has no IBAN
    assert p12.source_refs == _refs_of_invoice(pipeline, "TR-2026-014")
    assert p12.data["reason"] == "format" and p12.data["subject"] == "invoice"

    p7 = by_variant["vat_amount_mismatch"]
    assert p7.source_refs == _refs_of_invoice(pipeline, "IR-2026-044")
    assert (p7.data["vat_amount"], p7.data["expected_vat_amount"]) == ("12.10", "21.00")

    p9 = by_variant["payment_without_invoice"]  # the second 605.00 payment, dated 2026-08-12
    assert p9.data["payment_date"] == "2026-08-12" and p9.data["payment_amount"] == "605.00"
    assert _supplier_ref(pipeline, generator.PHANTOM_CASES["P9"]) in p9.source_refs

    overdue = by_variant["invoice_overdue"]
    assert overdue.source_refs == _refs_of_invoice(pipeline, "CR-2026-051")
    assert overdue.data["days_past_due"] == 41 and overdue.data["as_of"] == "2026-10-30"

    p5 = by_variant["invoice_iban_differs_from_master"]
    assert set(p5.source_refs) == {
        *_refs_of_invoice(pipeline, "T-2026-077"),
        _supplier_ref(pipeline, generator.PHANTOM_CASES["P5"]),
    }

    delta = by_variant["payment_to_non_master_iban"]
    delta_master = _supplier_ref(pipeline, generator.PHANTOM_CASES["NON_MASTER_PAYMENT"])
    assert delta_master in delta.source_refs
    assert (delta.data["payment_date"], delta.data["payment_amount"]) == ("2026-09-14", "1210.00")


def test_each_planted_case_raises_exactly_its_alerts_via_phantom_cases(
    pipeline: Pipeline,
) -> None:
    """Per PHANTOM_CASES supplier, the alerts citing its rows are exactly the planted ones."""
    assert set(EXPECTED_BY_CASE) == set(generator.PHANTOM_CASES)

    for case, tax_id in generator.PHANTOM_CASES.items():
        actual = sorted(_signature(a) for a in _alerts_of_supplier(pipeline, tax_id))
        assert actual == sorted(EXPECTED_BY_CASE[case]), case

    planted = sum(len(expected) for expected in EXPECTED_BY_CASE.values())
    assert planted == len(_alerts(pipeline)) == 9


def test_every_detector_fires_at_least_once(pipeline: Pipeline) -> None:
    """All four pi.* detectors ran and each of them raised at least one alert."""
    assert {result.name for result in pipeline.results} == PI_NAMES
    assert {alert.detector for alert in _alerts(pipeline)} == PI_NAMES
    assert all(len(result.alerts) >= 1 for result in pipeline.results)


def test_multi_rate_rows_quarantined_and_raise_no_alert(pipeline: Pipeline) -> None:
    """The two OB-2026-008 rows are quarantined, absent from the ledger and cited by no alert."""
    records = [q for q in pipeline.quarantine if q["reason"] == MULTI_RATE_REASON]

    assert len(records) == len(pipeline.quarantine) == 2
    assert {q["raw"]["invoice_number"] for q in records} == {"OB-2026-008"}
    assert {q["file_kind"] for q in records} == {"invoices"}
    refs = {f"{q['source_file']}:{q['source_row']}" for q in records}
    assert len(refs) == 2
    assert not refs & {r["source_ref"] for r in _records(pipeline.invoices)}
    assert len(pipeline.invoices) == CLEAN_INVOICE_ROWS
    assert not refs & {ref for alert in _alerts(pipeline) for ref in alert.source_refs}


def test_no_alert_on_any_clean_supplier(pipeline: Pipeline) -> None:
    """None of the nine clean suppliers has a row cited by an alert."""
    assert len(generator.CLEAN_SUPPLIERS) == 9
    for tax_id in generator.CLEAN_SUPPLIERS:
        assert _alerts_of_supplier(pipeline, tax_id) == [], tax_id


def test_as_of_defaults_to_latest_data_date(pipeline: Pipeline) -> None:
    """With no as_of in config.toml the latest date in the data is used."""
    assert _sources()[3] is None
    assert pipeline.as_of_used == LATEST_DATE == generator.DEMO_LATEST_DATE


def test_every_source_ref_is_in_loaded_source_refs(pipeline: Pipeline) -> None:
    """No alert cites a row that was not loaded (the no-invention property on the demo)."""
    loaded = loaded_source_refs(
        pipeline.invoices, {"suppliers": pipeline.suppliers, "payments": pipeline.payments}
    )

    for alert in _alerts(pipeline):
        assert alert.source_refs
        assert set(alert.source_refs) <= loaded, alert.title


def test_no_alert_data_contains_a_full_iban(pipeline: Pipeline) -> None:
    """Only masked IBANs reach Alert.data (REQ-PII-04)."""
    ibans: set[str] = set()
    for frame in (pipeline.invoices, pipeline.suppliers, pipeline.payments):
        for record in _records(frame):
            text = as_text(record.get("iban"))
            if text is not None:
                ibans.add(iban_key(text))
    assert len(ibans) > 20

    for alert in _alerts(pipeline):
        blob = re.sub(r"[\s-]", "", json.dumps(alert.data, sort_keys=True)).upper()
        assert not any(iban in blob for iban in ibans), alert.title
        assert not re.search(r"ES\d{22}", blob), alert.title


def test_every_alert_explanation_fallback_fills(
    pipeline: Pipeline, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without an API key all nine alerts get the filled template and cite a source_ref."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    for alert in _alerts(pipeline):
        meta = explain_alert(
            alert, pipeline.invoices, pipeline.suppliers, pipeline.payments, client=None
        )

        assert meta.source == "fallback" and meta.rejected_numbers == (), alert.title
        assert meta.text and "{" not in meta.text and "}" not in meta.text, alert.title
        assert any(ref in meta.text for ref in alert.source_refs), alert.title


def test_hallucinating_stub_rejected_for_every_alert(
    pipeline: Pipeline, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The stub invents 99999.99 for every alert; the number guard rejects it each time."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    alerts = _alerts(pipeline)

    assert len(alerts) == 9
    for alert in alerts:
        stub = HallucinatingStubClient(fill_fallback(template_for(alert), alert))

        meta = explain_alert(
            alert, pipeline.invoices, pipeline.suppliers, pipeline.payments, client=stub
        )

        assert meta.source == "fallback", alert.title
        assert meta.rejected_numbers == (INJECTED,), alert.title
        assert INJECTED not in meta.text, alert.title


def test_result_identical_under_two_clocks() -> None:
    """The alerts do not depend on the system clock (REQ-PI-65, design 16.4 part 2)."""
    sources = _sources()

    with freeze_time("2020-01-01"):
        first = _run(sources)
    with freeze_time("2031-12-31"):
        second = _run(sources)

    dump_first = [a.model_dump() for a in _alerts(first)]
    dump_second = [a.model_dump() for a in _alerts(second)]
    assert len(dump_first) == 9
    assert dump_first == dump_second
    assert first.as_of_used == second.as_of_used == LATEST_DATE


def _normalised(alert: Alert) -> tuple[str, str, str, int]:
    """An alert without row numbers: data with its lists sorted, and the count of cited rows."""
    data = {k: sorted(v) if isinstance(v, list) else v for k, v in alert.data.items()}
    return alert.detector, alert.severity, json.dumps(data, sort_keys=True), len(alert.source_refs)


def _shuffled(source: Source, seed: int) -> Source:
    """The same file with its data rows in a different order (the header stays first)."""
    header, *rows = source.data.decode("utf-8").splitlines(keepends=True)
    random.Random(seed).shuffle(rows)
    return Source(source.name, (header + "".join(rows)).encode("utf-8"))


def test_pipeline_result_independent_of_row_order(pipeline: Pipeline) -> None:
    """Shuffling the data rows of the three files gives the same nine alerts, modulo row numbers."""
    invoices, suppliers, payments, as_of = _sources()
    shuffled = (
        _shuffled(invoices, 1),
        _shuffled(suppliers, 2),
        _shuffled(payments, 3),
        as_of,
    )
    assert shuffled[0].data != invoices.data  # the shuffle really changed the order

    again = _run(shuffled)

    assert len(_alerts(again)) == 9
    assert again.as_of_used == pipeline.as_of_used
    assert sorted(map(_normalised, _alerts(again))) == sorted(map(_normalised, _alerts(pipeline)))
