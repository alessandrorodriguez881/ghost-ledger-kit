"""Detector package of App 2: importing it registers the four pi.* detectors."""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from ledger_kit.detectors import DetectorResult, auto_discover, run_all

# User-visible label per registered detector name (REQ-PI-14).
LABELS: dict[str, str] = {
    "pi.duplicate_invoice": "Duplicate invoice",
    "pi.iban_change": "Poltergeist IBAN",
    "pi.vat_error": "VAT error",
    "pi.reconciliation": "Reconciliation",
}

auto_discover("apps.phantom_invoices.detectors")  # imports every module, triggering @register


def run_pi_detectors(
    invoices: pd.DataFrame,
    suppliers: pd.DataFrame,
    payments: pd.DataFrame,
    as_of: date | None = None,
) -> list[DetectorResult]:
    """Run the four pi.* detectors with the context of REQ-PI-02."""
    ctx: dict[str, Any] = {"suppliers": suppliers, "payments": payments, "as_of": as_of}
    return run_all(invoices, namespace="pi", context=ctx)


__all__ = ["LABELS", "run_pi_detectors"]
