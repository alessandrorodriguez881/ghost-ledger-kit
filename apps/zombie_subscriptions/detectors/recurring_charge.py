"""Recurring-charge detector: one info alert per recurring series (design §5.1)."""

from collections.abc import Mapping
from typing import Any

import pandas as pd

from apps.zombie_subscriptions.detectors.utils import (
    find_series,
    group_by_normalised_key,
    is_active,
    ledger_max_date,
    ppy_for,
    resolve_alias,
    sorted_source_refs,
)
from ledger_kit.detectors import register
from ledger_kit.models import Alert
from ledger_kit.utils.money import round_to_cents


@register("zs.recurring_charge")
def detect_recurring_charges(ledger: pd.DataFrame, context: Mapping[str, Any]) -> list[Alert]:
    """Emit one info alert for every recurring series found under each normalised key."""
    alerts: list[Alert] = []
    if ledger.empty:
        return alerts
    aliases: dict[str, list[str]] | None = context.get("aliases")
    max_date = ledger_max_date(ledger)
    for key, key_rows in group_by_normalised_key(ledger):
        canonical = resolve_alias(key, aliases)
        for series in find_series(key_rows):
            yearly_cost = round_to_cents(series.current_amount * ppy_for(series.interval_type))
            alerts.append(
                Alert(
                    detector="zs.recurring_charge",
                    severity="info",
                    title=f"Recurring charge detected: {canonical}",
                    source_refs=sorted_source_refs(series.rows),
                    data={
                        "counterparty": canonical,
                        "normalised_key": key,
                        "interval_type": series.interval_type,
                        "current_amount": str(series.current_amount),
                        "charge_count": len(series.rows),
                        "yearly_cost": str(yearly_cost),
                        "first_charge_date": series.rows[0]["date"].isoformat(),
                        "last_charge_date": series.rows[-1]["date"].isoformat(),
                        "is_active": is_active(series, max_date),
                    },
                )
            )
    return alerts
