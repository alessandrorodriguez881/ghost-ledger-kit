"""Poltergeist-IBAN detector: invoice or payment IBANs that differ from the supplier master.

Also flags IBANs that are not valid IBANs. At most one alert per row. Only the masked form of an
IBAN ever reaches `Alert.data` (REQ-PII-04). Design section 8.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from typing import Any

import pandas as pd

from apps.phantom_invoices.detectors.utils import (
    IBAN_FORMAT_RE,
    IBAN_MOD97_MODULUS,
    IBAN_MOD97_REMAINDER,
    as_date,
    as_decimal,
    as_text,
    attribute_payment,
    build_master,
    finish,
    iban_key,
    iban_problem,
    load_rows,
    sort_refs,
    tax_key,
    text_or_ref,
)
from ledger_kit.detectors import register
from ledger_kit.models import Alert
from ledger_kit.utils.anonymise import mask_iban
from ledger_kit.utils.money import round_to_cents

__all__ = [
    "IBAN_FORMAT_RE",
    "IBAN_MOD97_MODULUS",
    "IBAN_MOD97_REMAINDER",
    "VERIFY_BY_PHONE_MESSAGE",
    "detect_iban_changes",
]

# Deterministic advice shown with the two critical variants (REQ-PI-26): one string, no digit.
VERIFY_BY_PHONE_MESSAGE: str = (
    "Verify this change by phone, using a contact you already have for this supplier. "
    "Never use a phone number or e-mail address printed on the invoice."
)


def _iban_state(cell: Any) -> tuple[str, str | None] | None:
    """Return (iban_key, problem) for a present IBAN cell; None when the cell is missing."""
    text = as_text(cell)
    if text is None:
        return None
    key = iban_key(text)
    return key, iban_problem(key)


def _valid_master_key(sup: dict | None) -> str | None:
    """Return the iban_key of the master IBAN when it is present and valid, else None."""
    if sup is None:
        return None
    state = _iban_state(sup.get("iban"))
    return state[0] if state is not None and state[1] is None else None


def _invalid(subject: str, label: str, problem: str, raw_iban: Any, refs: list[str]) -> Alert:
    """Build a warning / iban_invalid alert; the full IBAN never reaches Alert.data."""
    return Alert(
        detector="pi.iban_change",
        severity="warning",
        title=f"Invalid IBAN on {subject} {label}",
        source_refs=sort_refs(refs),
        data={
            "variant": "iban_invalid",
            "subject": subject,
            "label": label,
            "reason": problem,
            "iban_masked": mask_iban(as_text(raw_iban) or ""),
        },
    )


def _invoice_differs(row: dict, ref: str, number: str, sup: dict, raw_iban: Any) -> Alert:
    """Build a critical / invoice_iban_differs_from_master alert."""
    sup_ref = as_text(sup.get("source_ref")) or ""
    invoice_masked = mask_iban(as_text(raw_iban) or "")
    master_masked = mask_iban(as_text(sup.get("iban")) or "")
    name = text_or_ref(sup.get("supplier_name"), sup_ref)
    return Alert(
        detector="pi.iban_change",
        severity="critical",
        title=f"Poltergeist IBAN: {name}",
        source_refs=sort_refs([ref, sup_ref]),
        data={
            "variant": "invoice_iban_differs_from_master",
            "supplier_name": name,
            "invoice_number": number,
            "invoice_iban_masked": invoice_masked,
            "master_iban_masked": master_masked,
            "last4_identical": invoice_masked == master_masked,
            "verification_message": VERIFY_BY_PHONE_MESSAGE,
        },
    )


def _payment_differs(row: dict, ref: str, sup: dict, day: date, amount: Decimal) -> Alert:
    """Build a critical / payment_to_non_master_iban alert."""
    sup_ref = as_text(sup.get("source_ref")) or ""
    payment_masked = mask_iban(as_text(row.get("iban")) or "")
    master_masked = mask_iban(as_text(sup.get("iban")) or "")
    name = text_or_ref(sup.get("supplier_name"), sup_ref)
    return Alert(
        detector="pi.iban_change",
        severity="critical",
        title=f"Payment sent to a non-master IBAN: {name}",
        source_refs=sort_refs([ref, sup_ref]),
        data={
            "variant": "payment_to_non_master_iban",
            "supplier_name": name,
            "payment_date": day.isoformat(),
            "payment_amount": str(round_to_cents(amount)),
            "payment_iban_masked": payment_masked,
            "master_iban_masked": master_masked,
            "last4_identical": payment_masked == master_masked,
            "verification_message": VERIFY_BY_PHONE_MESSAGE,
        },
    )


@register("pi.iban_change")
def detect_iban_changes(ledger: pd.DataFrame, context: Mapping[str, Any]) -> list[Alert]:
    """Flag invoice or payment IBANs that differ from the supplier master, and invalid IBANs."""
    master = build_master(context.get("suppliers"))
    alerts: list[Alert] = []

    # 1 - master rows whose own IBAN is present but invalid
    for row in master.by_tax.values():
        state = _iban_state(row.get("iban"))
        if state is not None and state[1] is not None:
            ref = as_text(row.get("source_ref")) or ""
            label = text_or_ref(row.get("supplier_name"), ref)
            alerts.append(_invalid("supplier", label, state[1], row.get("iban"), [ref]))

    # 2 - invoices
    for row in load_rows(ledger, "issue_date"):
        ref = as_text(row.get("source_ref")) or ""
        state = _iban_state(row.get("iban"))
        if state is None:
            continue  # missing IBAN: skipped (P12b)
        key, problem = state
        number = text_or_ref(row.get("invoice_number"), ref)
        if problem is not None:
            alerts.append(_invalid("invoice", number, problem, row.get("iban"), [ref]))
            continue
        sup = master.by_tax.get(tax_key(as_text(row.get("supplier_tax_id")) or ""))
        master_key = _valid_master_key(sup)
        if sup is None or master_key is None or master_key == key:
            continue  # unknown supplier / no usable master IBAN / same account
        alerts.append(_invoice_differs(row, ref, number, sup, row.get("iban")))

    # 3 - bank payments (debits attributed to a master supplier)
    for row in load_rows(context.get("payments"), "date"):
        if as_text(row.get("flow")) != "debit":
            continue
        sup = attribute_payment(row, master)
        state = _iban_state(row.get("iban"))
        if sup is None or state is None:
            continue
        ref = as_text(row.get("source_ref")) or ""
        key, problem = state
        if problem is not None:
            label = text_or_ref(row.get("counterparty"), ref)
            alerts.append(_invalid("payment", label, problem, row.get("iban"), [ref]))
            continue
        master_key = _valid_master_key(sup)
        day, amount = as_date(row.get("date")), as_decimal(row.get("amount"))
        if master_key is None or master_key == key or day is None or amount is None:
            continue
        alerts.append(_payment_differs(row, ref, sup, day, amount))
    return finish(alerts)
