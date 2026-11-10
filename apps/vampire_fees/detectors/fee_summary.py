"""Fee-summary detector: one alert with the total of every fee of the statement (design 5.4)."""

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

import pandas as pd

from apps.vampire_fees.detectors.utils import (
    DAYS_PER_YEAR,
    EMPTY_VOCABULARY,
    SUMMARY_MIN_SPAN_DAYS,
    SUMMARY_WARNING_YEARLY_EQUIVALENT,
    extract_fees,
    sorted_refs,
    statement_span,
)
from ledger_kit.detectors import register
from ledger_kit.models import Alert
from ledger_kit.utils.money import round_to_cents, sum_amounts


@register("vf.fee_summary")
def detect_fee_summary(ledger: pd.DataFrame, context: Mapping[str, Any]) -> list[Alert]:
    """Emit one alert with the fee count, the total and, for 90 days or more, the yearly figure."""
    fees = extract_fees(ledger, context.get("vocabulary", EMPTY_VOCABULARY))
    span = statement_span(ledger)
    if not fees or span is None:
        return []
    first, last = span
    span_days = (last - first).days + 1
    exact_total = sum_amounts(fee.amount for fee in fees)
    data: dict[str, Any] = {
        "fee_count": len(fees),
        "total_fees": str(round_to_cents(exact_total)),
        "first_date": first.isoformat(),
        "last_date": last.isoformat(),
        "span_days": span_days,
    }
    severity = "info"
    if span_days >= SUMMARY_MIN_SPAN_DAYS:
        yearly = round_to_cents(exact_total * DAYS_PER_YEAR / Decimal(span_days))
        data["yearly_equivalent"] = str(yearly)
        if yearly >= SUMMARY_WARNING_YEARLY_EQUIVALENT:
            severity = "warning"
    return [
        Alert(
            detector="vf.fee_summary",
            severity=severity,
            title="Bank fees on this statement",
            source_refs=sorted_refs(fees),
            data=data,
        )
    ]
