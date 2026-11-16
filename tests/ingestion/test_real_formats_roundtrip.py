"""Round-trip, no-invention, tamper, never-raises and idempotency properties (RF8, design 9.1).

Rows are written by the generator's Norma 43 and Facturae writers and read back by the library
readers; the properties then check that nothing is lost, nothing is invented, an edited amount is
caught and no input can make a reader raise. `settings(max_examples=200)` as in `testing.md`.
"""

from __future__ import annotations

import io
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from hypothesis import example, given, settings
from hypothesis import strategies as st
from rf_strategies import (
    arbitrary_input,
    generator,
    invoice_files,
    layouts,
    render_with_layout,
    statements,
    subscription_statements,
)

from apps.zombie_subscriptions.detectors import run_zs_detectors
from ledger_kit.detectors import loaded_source_refs
from ledger_kit.ingestion.facturae_reader import parse_facturae
from ledger_kit.ingestion.invoice_reader import DEFAULT_PAYMENT_TERM_DAYS
from ledger_kit.ingestion.norma43_reader import parse_norma43
from ledger_kit.ingestion.normaliser import normalise
from ledger_kit.ingestion.sniffer import (
    FORMAT_KINDS,
    read_bank_statement,
    read_invoices,
    sniff_format,
)

N43_NAME = "prop.n43"
XML_NAME = "prop.xml"
DIGITS = "0123456789"
AMOUNT_FIRST_INDEX = 28  # position 29 of a record 22, 0-based
AMOUNT_LAST_INDEX = 41  # position 42
INVOICE_FIELDS = (
    "invoice_number",
    "supplier_name",
    "supplier_tax_id",
    "issue_date",
    "due_date",
    "due_date_is_default",
    "base_amount",
    "vat_rate",
    "vat_amount",
    "surcharge_amount",
    "withholding_amount",
    "total",
    "currency",
    "iban",
)


# --- helpers ------------------------------------------------------------------------------------
def _transaction_fields(transaction: Any) -> tuple[Any, ...]:
    """The fields of a Transaction a bank row determines (the id is random by design)."""
    return (
        transaction.date,
        transaction.amount,
        transaction.flow,
        transaction.currency,
        transaction.counterparty,
        transaction.description,
        transaction.iban,
    )


def _expected_transaction(row: Any) -> tuple[Any, ...]:
    """What a bank row must read back as."""
    debit = row.amount.startswith("-")
    return (
        row.day,
        Decimal(row.amount.removeprefix("-")),
        "debit" if debit else "credit",
        "EUR",
        row.counterparty,
        row.description,
        row.iban or None,
    )


def _expected_invoice(party: Any, record: dict[str, str]) -> tuple[Any, ...]:
    """What an invoice record of `party` must read back as."""
    issue = date.fromisoformat(record["issue_date"])
    has_due = bool(record["due_date"])
    due = date.fromisoformat(record["due_date"]) if has_due else None
    values = {
        "invoice_number": record["invoice_number"],
        "supplier_name": party.name,
        "supplier_tax_id": party.tax_id,
        "issue_date": issue,
        "due_date": due or issue + timedelta(days=DEFAULT_PAYMENT_TERM_DAYS),
        "due_date_is_default": not has_due,
        "base_amount": Decimal(record["base_amount"]),
        "vat_rate": Decimal(record["vat_rate"]),
        "vat_amount": Decimal(record["vat_amount"]),
        "surcharge_amount": Decimal(record["surcharge_amount"] or "0"),
        "withholding_amount": Decimal(record["withholding_amount"] or "0"),
        "total": Decimal(record["total"]),
        "currency": record["currency"],
        # DN-RF-20: the schema cannot express an IBAN without an installment due date
        "iban": (record["iban"] or None) if has_due else None,
    }
    return tuple(values[name] for name in INVOICE_FIELDS)


def _invoice_fields(invoice: Any) -> tuple[Any, ...]:
    """The Invoice fields compared by the Facturae round trip."""
    return tuple(getattr(invoice, name) for name in INVOICE_FIELDS)


def _read_n43(rows: list[Any], layout: Any) -> tuple[list[Any], list[dict], list[str]]:
    """Write rows with a layout, read them back; also return the 80-character records."""
    lines = generator.render_norma43_lines(rows)
    data = render_with_layout(lines, layout)
    transactions, quarantined = parse_norma43(io.BytesIO(data), source_file=N43_NAME)
    return transactions, quarantined, lines


# --- 1. round trip ------------------------------------------------------------------------------
@settings(max_examples=200, deadline=None)
@given(rows=statements, layout=layouts)
def test_norma43_round_trip_under_every_layout(rows, layout):
    transactions, quarantined, _ = _read_n43(rows, layout)
    assert quarantined == []
    got = [_transaction_fields(t) for t in transactions]
    assert got == [_expected_transaction(r) for r in rows]


@settings(max_examples=200, deadline=None)
@given(file=invoice_files())
def test_facturae_round_trip(file):
    party, records = file
    data = generator.render_facturae(party, records)
    invoices, quarantined = parse_facturae(io.BytesIO(data), source_file=XML_NAME)
    assert quarantined == []
    got = [_invoice_fields(i) for i in invoices]
    assert got == [_expected_invoice(party, r) for r in records]


# --- 3. no invention ----------------------------------------------------------------------------
@settings(max_examples=200, deadline=None)
@given(rows=statements, layout=layouts)
def test_norma43_source_refs_are_the_lines_of_the_22_records(rows, layout):
    transactions, _, lines = _read_n43(rows, layout)
    movement_lines = [number for number, line in enumerate(lines, start=1) if line[:2] == "22"]
    assert [t.source_ref for t in transactions] == [f"{N43_NAME}:{n}" for n in movement_lines]
    assert [t.source_row for t in transactions] == movement_lines
    assert {t.source_file for t in transactions} == {N43_NAME}


@settings(max_examples=200, deadline=None)
@given(file=invoice_files())
def test_facturae_source_refs_are_invoice_positions(file):
    party, records = file
    data = generator.render_facturae(party, records)
    invoices, _ = parse_facturae(io.BytesIO(data), source_file=XML_NAME)
    positions = range(1, len(records) + 1)
    assert [i.source_ref for i in invoices] == [f"{XML_NAME}:{n}" for n in positions]
    assert [i.source_row for i in invoices] == list(positions)


@settings(max_examples=200, deadline=None)
@given(rows=subscription_statements(), layout=layouts)
def test_zombie_alerts_over_a_norma43_ledger_cite_only_loaded_rows(rows, layout):
    transactions, quarantined, _ = _read_n43(rows, layout)
    assert quarantined == []
    frame, frame_quarantine = normalise(transactions)
    assert frame_quarantine == []
    loaded = loaded_source_refs(frame, {})
    assert loaded == {t.source_ref for t in transactions}
    for result in run_zs_detectors(frame):
        for alert in result.alerts:
            assert alert.source_refs, alert.id
            assert set(alert.source_refs) <= loaded, alert.id


def test_the_zombie_demo_statement_gives_alerts_that_cite_loaded_rows():
    data = generator.build_zombie_demo_n43(42)
    transactions, quarantined = parse_norma43(io.BytesIO(data), source_file=N43_NAME)
    assert quarantined == []
    frame, _ = normalise(transactions)
    loaded = loaded_source_refs(frame, {})
    alerts = [alert for result in run_zs_detectors(frame) for alert in result.alerts]
    assert alerts
    assert all(set(alert.source_refs) <= loaded for alert in alerts)


# --- 4. tamper detection ------------------------------------------------------------------------
@settings(max_examples=200, deadline=None)
@given(rows=statements, layout=layouts, data=st.data())
def test_changing_one_amount_digit_is_always_detected(rows, layout, data):
    lines = generator.render_norma43_lines(rows)
    movements = [index for index, line in enumerate(lines) if line[:2] == "22"]
    index = data.draw(st.sampled_from(movements))
    position = data.draw(st.integers(min_value=AMOUNT_FIRST_INDEX, max_value=AMOUNT_LAST_INDEX))
    old = lines[index][position]
    new = data.draw(st.sampled_from([digit for digit in DIGITS if digit != old]))
    lines[index] = lines[index][:position] + new + lines[index][position + 1 :]

    payload = render_with_layout(lines, layout)
    transactions, quarantined = parse_norma43(io.BytesIO(payload), source_file=N43_NAME)
    assert transactions == []
    assert any(r["reason"].startswith("control_check_failed:") for r in quarantined)


# --- 5. never raises ----------------------------------------------------------------------------
@example(payload=b'<?xml version="1.0" encoding="ATF-8"?><Facturae/>')  # Task RF12
@settings(max_examples=200, deadline=None)
@given(payload=arbitrary_input)
def test_no_input_makes_the_sniffer_the_readers_or_the_routers_raise(payload):
    assert sniff_format(payload) in FORMAT_KINDS
    results = (
        parse_norma43(io.BytesIO(payload), source_file="x"),
        parse_facturae(io.BytesIO(payload), source_file="x"),
        read_bank_statement(io.BytesIO(payload), source_file="x"),
        read_invoices(io.BytesIO(payload), source_file="x"),
    )
    for valid, quarantined in results:
        assert isinstance(valid, list) and isinstance(quarantined, list)
        assert all(isinstance(record, dict) for record in quarantined)


# --- 6. idempotency and empty input -------------------------------------------------------------
@settings(max_examples=200, deadline=None)
@given(rows=statements, layout=layouts)
def test_parsing_a_norma43_file_twice_gives_the_same_transactions(rows, layout):
    payload = render_with_layout(generator.render_norma43_lines(rows), layout)
    first = parse_norma43(io.BytesIO(payload), source_file=N43_NAME)
    second = parse_norma43(io.BytesIO(payload), source_file=N43_NAME)
    first_fields = [_transaction_fields(t) for t in first[0]]
    assert first_fields == [_transaction_fields(t) for t in second[0]]
    assert [t.source_ref for t in first[0]] == [t.source_ref for t in second[0]]
    assert first[1] == second[1]


@settings(max_examples=200, deadline=None)
@given(file=invoice_files())
def test_parsing_a_facturae_file_twice_gives_the_same_invoices(file):
    party, records = file
    payload = generator.render_facturae(party, records)
    first = parse_facturae(io.BytesIO(payload), source_file=XML_NAME)
    second = parse_facturae(io.BytesIO(payload), source_file=XML_NAME)
    assert first == second


@settings(max_examples=200, deadline=None)
@given(blanks=st.text(alphabet=" \t\r\n", max_size=50))
def test_empty_or_blank_input_gives_nothing_and_no_quarantine(blanks):
    payload = blanks.encode("ascii")
    assert parse_norma43(io.BytesIO(payload), source_file="x") == ([], [])
    assert parse_facturae(io.BytesIO(payload), source_file="x") == ([], [])
    assert read_bank_statement(io.BytesIO(payload), source_file="x") == ([], [])
    assert read_invoices(io.BytesIO(payload), source_file="x") == ([], [])
    assert sniff_format(payload) == "empty"
