"""Charges-after-cancellation detector: debits dated after a cancellation date (design §5.5)."""

from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from typing import Any

import pandas as pd

from apps.zombie_subscriptions.detectors.utils import (
    group_by_canonical,
    ledger_max_date,
    service_yearly_cost,
    sorted_source_refs,
    unique_rows,
)
from ledger_kit.detectors import register
from ledger_kit.models import Alert
from ledger_kit.utils.money import round_to_cents


@register("zs.charges_after_cancellation")
def detect_charges_after_cancellation(
    ledger: pd.DataFrame,
    context: Mapping[str, Any],
) -> list[Alert]:
    """Emit one critical alert per service that was charged after its cancellation date."""
    alerts: list[Alert] = []
    cancellation_dates: dict[str, date] | None = context.get("cancellation_dates")
    if not cancellation_dates or ledger.empty:
        return alerts
    aliases: dict[str, list[str]] | None = context.get("aliases")
    max_date = ledger_max_date(ledger)
    for canonical, key_groups in group_by_canonical(ledger, aliases).items():
        if canonical not in cancellation_dates:
            continue
        cancel_date = cancellation_dates[canonical]
        # Every row of the service counts, whether or not it belongs to a series (REQ-ZS-24).
        all_rows = [row for _key, rows in key_groups for row in rows]
        post = unique_rows([row for row in all_rows if row["date"] > cancel_date])
        if not post:
            continue
        total = sum((Decimal(row["amount"]) for row in post), Decimal("0.00"))
        alerts.append(
            Alert(
                detector="zs.charges_after_cancellation",
                severity="critical",
                title=f"Charge after cancellation: {canonical}",
                source_refs=sorted_source_refs(post),
                data={
                    "counterparty": canonical,
                    "cancellation_date": cancel_date.isoformat(),
                    "post_cancellation_count": len(post),
                    "total_charged_after": str(round_to_cents(total)),
                    "yearly_cost": str(service_yearly_cost(key_groups, max_date)),
                },
            )
        )
    return alerts
