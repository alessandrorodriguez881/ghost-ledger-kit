"""Smoke test of the ledger-core contract the phantom-invoices app relies on (Task P2).

One test per CR-LC-3 item, so a missing ledger-core piece fails here with a clear name instead of
deep inside a detector. Nothing under ledger_kit/ is patched from this spec.
"""

import io
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from types import MappingProxyType

import pandas as pd
import pytest

import ledger_kit.explainer as explainer
from ledger_kit.detectors import (
    _restore_registry,
    _snapshot_registry,
    loaded_source_refs,
    register,
    run_all,
)
from ledger_kit.explainer import explain_with_meta, fill_fallback
from ledger_kit.ingestion.csv_reader import parse_csv
from ledger_kit.ingestion.invoice_reader import parse_invoice
from ledger_kit.ingestion.normaliser import (
    CANONICAL_COLUMNS,
    INVOICE_COLUMNS,
    SUPPLIER_COLUMNS,
    normalise,
)
from ledger_kit.ingestion.supplier_reader import parse_suppliers
from ledger_kit.models import Alert, Invoice, Supplier, Transaction
from ledger_kit.utils.anonymise import mask_iban
from ledger_kit.utils.money import net_total, percent_of, within_tolerance

# Mod-97 valid, deliberately wrong Spanish national check digits (Finance Rule 5).
DOC_IBAN = "ES88 2100 0418 5602 0005 1332"

INVOICE_CSV = (
    "invoice_number,supplier_name,supplier_tax_id,issue_date,due_date,base_amount,vat_rate,"
    "vat_amount,total,currency,iban\n"
    "F-2026-0001,Suministros García,B00000001,2026-03-01,2026-03-31,100.00,21,21.00,121.00,"
    f"EUR,{DOC_IBAN}\n"
)
SUPPLIER_CSV = f"supplier_name,tax_id,iban\nSuministros García,B00000001,{DOC_IBAN}\n"
BANK_CSV = (
    "date,amount,currency,counterparty,description,iban\n"
    "2026-03-15,-121.00,EUR,Suministros García,Synthetic payment,es88 2100 0418 5602 0005 1332\n"
)


@pytest.fixture
def isolated_registry() -> Iterator[None]:
    """Snapshot the global detector registry before a test and restore it afterwards."""
    snapshot = _snapshot_registry()
    try:
        yield
    finally:
        _restore_registry(snapshot)


def _utf8(text: str) -> io.BytesIO:
    """Encode CSV text to bytes so Windows never adds carriage returns."""
    return io.BytesIO(text.encode("utf-8"))


class _Message:
    """Minimal chat-completion message."""

    def __init__(self, content: str) -> None:
        self.content = content


class _Choice:
    """Minimal chat-completion choice."""

    def __init__(self, content: str) -> None:
        self.message = _Message(content)


class _Response:
    """Minimal chat-completion response."""

    def __init__(self, content: str) -> None:
        self.choices = [_Choice(content)]


class _RecordingClient:
    """OpenAI-shaped client that records every call and returns a fixed answer."""

    def __init__(self, answer: str) -> None:
        self._answer = answer
        self.calls: list[dict] = []

    @property
    def chat(self) -> "_RecordingClient":
        """Mimic client.chat."""
        return self

    @property
    def completions(self) -> "_RecordingClient":
        """Mimic client.chat.completions."""
        return self

    def create(self, **kwargs) -> _Response:
        """Record the call and return the canned response."""
        self.calls.append(kwargs)
        return _Response(self._answer)


def test_cr_lc_3a_invoice_model_and_reader() -> None:
    """Invoice, parse_invoice and normalise(kind='invoice') give INVOICE_COLUMNS."""
    invoices, quarantined = parse_invoice(_utf8(INVOICE_CSV), fmt="csv", source_file="inv.csv")
    assert quarantined == []
    assert len(invoices) == 1
    assert isinstance(invoices[0], Invoice)
    assert invoices[0].source_ref == "inv.csv:0"
    assert invoices[0].total == Decimal("121.00")

    frame, frame_quarantine = normalise(invoices, kind="invoice")
    assert frame_quarantine == []
    assert tuple(frame.columns) == INVOICE_COLUMNS
    assert len(frame) == 1

    empty, _ = normalise(kind="invoice")
    assert tuple(empty.columns) == INVOICE_COLUMNS
    assert empty.empty


def test_cr_lc_3b_supplier_model_and_reader() -> None:
    """Supplier, parse_suppliers and normalise(kind='supplier') give SUPPLIER_COLUMNS."""
    suppliers, quarantined = parse_suppliers(_utf8(SUPPLIER_CSV), source_file="sup.csv")
    assert quarantined == []
    assert len(suppliers) == 1
    assert isinstance(suppliers[0], Supplier)
    assert suppliers[0].source_ref == "sup.csv:0"
    assert suppliers[0].tax_id == "B00000001"

    frame, frame_quarantine = normalise(suppliers, kind="supplier")
    assert frame_quarantine == []
    assert tuple(frame.columns) == SUPPLIER_COLUMNS
    assert len(frame) == 1

    empty, _ = normalise(kind="supplier")
    assert tuple(empty.columns) == SUPPLIER_COLUMNS
    assert empty.empty


def test_cr_lc_3c_parse_csv_reads_iban_verbatim() -> None:
    """parse_csv keeps the iban cell exactly as written (case and spacing included)."""
    transactions, quarantined = parse_csv(_utf8(BANK_CSV), source_file="pay.csv")
    assert quarantined == []
    assert len(transactions) == 1
    assert isinstance(transactions[0], Transaction)
    assert transactions[0].iban == "es88 2100 0418 5602 0005 1332"
    assert transactions[0].flow == "debit"

    frame, _ = normalise(transactions)
    assert tuple(frame.columns) == CANONICAL_COLUMNS
    assert frame.loc[0, "iban"] == "es88 2100 0418 5602 0005 1332"


def test_cr_lc_3d_loaded_source_refs_is_union() -> None:
    """loaded_source_refs returns the refs of the ledger and of every frame in the context."""
    ledger = pd.DataFrame({"source_ref": ["inv.csv:0", "inv.csv:1"]})
    suppliers = pd.DataFrame({"source_ref": ["sup.csv:0"]})
    payments = pd.DataFrame({"source_ref": ["pay.csv:0"]})
    context = MappingProxyType({"suppliers": suppliers, "payments": payments, "as_of": None})

    refs = loaded_source_refs(ledger, context)

    assert refs == frozenset({"inv.csv:0", "inv.csv:1", "sup.csv:0", "pay.csv:0"})
    assert loaded_source_refs(pd.DataFrame(), MappingProxyType({})) == frozenset()


def test_cr_lc_3e_money_helpers() -> None:
    """percent_of, within_tolerance and net_total behave as the detectors expect."""
    assert percent_of(Decimal("100.00"), Decimal("21")) == Decimal("21.00")
    assert percent_of(Decimal("0.50"), Decimal("21")) == Decimal("0.11")  # half-up
    assert within_tolerance(Decimal("1.00"), Decimal("1.01"), Decimal("0.01"))
    assert not within_tolerance(Decimal("1.00"), Decimal("1.02"), Decimal("0.01"))
    assert net_total([Decimal("100.00"), Decimal("21.00")], [Decimal("5.00")]) == Decimal("116.00")


def test_cr_lc_3f_empty_ledger_context_detector_runs(isolated_registry: None) -> None:
    """A context-reading detector may alert on an empty ledger and never raises when all empty."""

    @register("p2smoke.reads_payments")
    def _detect(ledger: pd.DataFrame, context) -> list[Alert]:
        payments = context.get("payments")
        if not isinstance(payments, pd.DataFrame) or payments.empty:
            return []
        return [
            Alert(
                detector="p2smoke.reads_payments",
                severity="info",
                title="Payment without ledger",
                source_refs=[str(payments["source_ref"].iloc[0])],
                data={"variant": "smoke"},
            )
        ]

    payments = pd.DataFrame({"source_ref": ["pay.csv:0"]})

    results = run_all(pd.DataFrame(), namespace="p2smoke", context={"payments": payments})
    assert [r.name for r in results] == ["p2smoke.reads_payments"]
    assert len(results[0].alerts) == 1
    assert results[0].alerts[0].source_refs == ["pay.csv:0"]

    quiet = run_all(pd.DataFrame(), namespace="p2smoke", context={"payments": pd.DataFrame()})
    assert quiet[0].alerts == []


def test_cr_lc_3g_mask_iban_and_row_columns() -> None:
    """mask_iban keeps the last four characters; explain_with_meta takes row_columns."""
    assert mask_iban(DOC_IBAN) == "****1332"
    assert mask_iban("ES88") == "****"

    alert = Alert(
        detector="p2smoke.reads_payments",
        severity="info",
        title="Total",
        source_refs=["inv.csv:0"],
        data={"total": "121.00"},
    )
    rows = pd.DataFrame(
        [
            {
                "supplier_tax_id": "B00000001",
                "issue_date": date(2026, 3, 1),
                "total": Decimal("121.00"),
                "source_ref": "inv.csv:0",
            }
        ]
    )
    client = _RecordingClient("The invoice total is 121.00, see inv.csv:0.")

    result = explain_with_meta(
        alert,
        rows,
        fallback_template="Total {total:money} ({source_refs})",
        client=client,
        row_columns=("total", "source_ref"),
    )

    assert result.source == "llm"
    sent = client.calls[0]["messages"][1]["content"]
    assert "total" in sent
    assert "supplier_tax_id" not in sent
    assert "issue_date" not in sent


def test_fill_fallback_is_public() -> None:
    """fill_fallback is importable, fills {total:money}, and has no private twin (DN-9)."""
    alert = Alert(
        detector="p2smoke.reads_payments",
        severity="info",
        title="Total",
        source_refs=["inv.csv:0"],
        data={"total": "121.00"},
    )

    filled = fill_fallback("Total {total:money} ({source_refs})", alert)

    assert filled == "Total 121,00 EUR (inv.csv:0)"
    assert not hasattr(explainer, "_fill_fallback")
