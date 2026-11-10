"""Recurring-fee detector: one alert per regular run of a bank fee (design 4.4 and 5.1)."""

from collections.abc import Mapping
from typing import Any

import pandas as pd

from apps.vampire_fees.detectors.utils import (
    EMPTY_VOCABULARY,
    RECURRING_FEE_WARNING_YEARLY_COST,
    extract_fees,
    in_first_row_order,
    recurring_runs,
    sorted_refs,
    yearly_cost,
)
from ledger_kit.detectors import register
from ledger_kit.models import Alert
from ledger_kit.utils.money import round_to_cents


@register("vf.recurring_fee")
def detect_recurring_fees(ledger: pd.DataFrame, context: Mapping[str, Any]) -> list[Alert]:
    """Emit one alert for every regular monthly, quarterly or yearly run of a fee."""
    fees = extract_fees(ledger, context.get("vocabulary", EMPTY_VOCABULARY))
    entries: list[tuple[Any, Alert]] = []
    for interval, run in recurring_runs(fees):
        last = run[-1]
        cost = yearly_cost(last.amount, interval)
        severity = "warning" if cost >= RECURRING_FEE_WARNING_YEARLY_COST else "info"
        alert = Alert(
            detector="vf.recurring_fee",
            severity=severity,
            title=f"Recurring {interval.name} fee: {last.counterparty} · {last.description}",
            source_refs=sorted_refs(run),
            data={
                "counterparty": last.counterparty,
                "description": last.description,
                "interval_type": interval.name,
                "charge_count": len(run),
                "current_amount": str(round_to_cents(last.amount)),
                "yearly_cost": str(cost),
                "first_charge_date": run[0].date.isoformat(),
                "last_charge_date": last.date.isoformat(),
            },
        )
        entries.append((run[0], alert))
    return in_first_row_order(entries)
