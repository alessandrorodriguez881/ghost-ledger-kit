"""Reconciliation detector: overdue invoices and supplier payments that match no invoice.

The matching itself is `reconcile` in `utils.py`, shared with the UI status column. Design
section 10.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd

from apps.phantom_invoices.detectors.utils import (
    MATCH_AMOUNT_TOLERANCE,
    PAYMENT_MATCH_WINDOW_DAYS,
    UNPAID_GRACE_DAYS,
    as_bool,
    as_text,
    build_master,
    finish,
    invoice_view,
    load_rows,
    payment_view,
    reconcile,
    resolve_as_of,
    sort_refs,
    supplier_label,
    text_or_ref,
)
from ledger_kit.detectors import register
from ledger_kit.models import Alert
from ledger_kit.utils.money import round_to_cents

__all__ = [
    "MATCH_AMOUNT_TOLERANCE",
    "PAYMENT_MATCH_WINDOW_DAYS",
    "UNPAID_GRACE_DAYS",
    "detect_reconciliation",
]


@register("pi.reconciliation")
def detect_reconciliation(ledger: pd.DataFrame, context: Mapping[str, Any]) -> list[Alert]:
    """Report overdue invoices and supplier payments that match no invoice."""
    suppliers, payments = context.get("suppliers"), context.get("payments")
    as_of = resolve_as_of(ledger, context)
    rec = reconcile(ledger, suppliers, payments, as_of)
    master = build_master(suppliers)
    alerts: list[Alert] = []

    for row in load_rows(ledger, "issue_date"):
        view = invoice_view(row)
        if view is None or rec.invoice_buckets.get(view.ref) != "overdue" or as_of is None:
            continue
        number = text_or_ref(row.get("invoice_number"), view.ref)
        name = supplier_label(row, view.ref)
        alerts.append(
            Alert(
                detector="pi.reconciliation",
                severity="warning",
                title=f"Unpaid invoice: {number} ({name})",
                source_refs=[view.ref],
                data={
                    "variant": "invoice_overdue",
                    "supplier_name": name,
                    "invoice_number": number,
                    "total": str(round_to_cents(view.total)),
                    "due_date": view.due.isoformat(),
                    "due_date_is_default": as_bool(row.get("due_date_is_default")),
                    "as_of": as_of.isoformat(),
                    "days_past_due": (as_of - view.due).days,
                },
            )
        )

    for row in load_rows(payments, "date"):
        view = payment_view(row)
        if view is None or rec.payment_buckets.get(view.ref) != "unmatched":
            continue
        sup = master.by_tax[rec.payment_supplier[view.ref]]
        sup_ref = as_text(sup.get("source_ref")) or ""
        name = text_or_ref(sup.get("supplier_name"), sup_ref)
        alerts.append(
            Alert(
                detector="pi.reconciliation",
                severity="warning",
                title=f"Payment without invoice: {name}",
                source_refs=sort_refs([view.ref, sup_ref]),
                data={
                    "variant": "payment_without_invoice",
                    "supplier_name": name,
                    "payment_date": view.day.isoformat(),
                    "payment_amount": str(round_to_cents(view.amount)),
                    "currency": view.currency,
                },
            )
        )
    return finish(alerts)
