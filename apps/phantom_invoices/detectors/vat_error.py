"""VAT-error detector: VAT amount, invoice total and VAT rate checked on the invoice base.

All money goes through the `ledger_kit.utils.money` helpers; this module applies no arithmetic
operator to a Decimal (REQ-MON-03). Surcharge and withholding are taken as stated and never
recomputed (OD-PI-16). Design section 9.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

import pandas as pd

from apps.phantom_invoices.detectors.utils import (
    ZERO,
    as_decimal,
    as_text,
    finish,
    load_rows,
    supplier_label,
    text_or_ref,
)
from ledger_kit.detectors import register
from ledger_kit.models import Alert
from ledger_kit.utils.money import net_total, percent_of, round_to_cents, within_tolerance

# Largest accepted difference (euros) between the stated and the computed VAT amount.
VAT_TOLERANCE: Decimal = Decimal("0.01")
# Largest accepted difference (euros) between the stated and the computed invoice total.
TOTAL_TOLERANCE: Decimal = Decimal("0.01")
# Spanish general, reduced, super-reduced and exempt rates (percent). Canary Islands IGIC and other
# special regimes (Ceuta, Melilla, agricultural flat-rate, ...) are out of scope.
ALLOWED_VAT_RATES: tuple[Decimal, ...] = (Decimal("21"), Decimal("10"), Decimal("4"), Decimal("0"))


def _m(amount: Decimal) -> str:
    """Return money as a two-decimal string (Finance Rule 3)."""
    return str(round_to_cents(amount))


def _alert(ref: str, variant: str, title: str, data: dict) -> Alert:
    """Build a warning alert citing the invoice row."""
    return Alert(
        detector="pi.vat_error",
        severity="warning",
        title=title,
        source_refs=[ref],
        data={"variant": variant, **data},
    )


@register("pi.vat_error")
def detect_vat_errors(ledger: pd.DataFrame, context: Mapping[str, Any]) -> list[Alert]:
    """Check VAT amount, total and VAT rate of each invoice on its base (not line by line)."""
    alerts: list[Alert] = []
    for row in load_rows(ledger, "issue_date"):
        ref = as_text(row.get("source_ref")) or ""
        base, rate = as_decimal(row.get("base_amount")), as_decimal(row.get("vat_rate"))
        vat, total = as_decimal(row.get("vat_amount")), as_decimal(row.get("total"))
        surcharge = as_decimal(row.get("surcharge_amount"))
        withholding = as_decimal(row.get("withholding_amount"))
        surcharge = ZERO if surcharge is None else surcharge  # missing -> 0 (REQ-PI-31)
        withholding = ZERO if withholding is None else withholding
        number = text_or_ref(row.get("invoice_number"), ref)
        common = {"supplier_name": supplier_label(row, ref), "invoice_number": number}

        if base is not None and rate is not None and vat is not None:  # VAT amount
            expected = percent_of(base, rate)
            if not within_tolerance(expected, vat, VAT_TOLERANCE):
                alerts.append(
                    _alert(
                        ref,
                        "vat_amount_mismatch",
                        f"VAT amount mismatch: {number}",
                        {
                            **common,
                            "base_amount": _m(base),
                            "vat_rate": str(rate),
                            "expected_vat_amount": _m(expected),
                            "vat_amount": _m(vat),
                        },
                    )
                )
        if base is not None and vat is not None and total is not None:  # total
            expected_total = net_total([base, vat, surcharge], [withholding])  # STATED VAT
            if not within_tolerance(expected_total, total, TOTAL_TOLERANCE):
                alerts.append(
                    _alert(
                        ref,
                        "total_mismatch",
                        f"Invoice total mismatch: {number}",
                        {
                            **common,
                            "base_amount": _m(base),
                            "vat_amount": _m(vat),
                            "surcharge_amount": _m(surcharge),
                            "withholding_amount": _m(withholding),
                            "expected_total": _m(expected_total),
                            "total": _m(total),
                        },
                    )
                )
        if rate is not None and rate not in ALLOWED_VAT_RATES:  # rate
            alerts.append(
                _alert(
                    ref,
                    "vat_rate_not_allowed",
                    f"Unexpected VAT rate: {number}",
                    {
                        **common,
                        "vat_rate": str(rate),
                        "allowed_vat_rates": ", ".join(str(r) for r in ALLOWED_VAT_RATES),
                    },
                )
            )
    return finish(alerts)
