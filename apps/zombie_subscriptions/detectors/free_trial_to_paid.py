"""Free-trial-to-paid detector: a token charge shortly before a series starts (design §5.4)."""

from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from typing import Any

import pandas as pd

from apps.zombie_subscriptions.detectors.utils import (
    FREE_TRIAL_MAX_TOKEN_AMOUNT,
    FREE_TRIAL_MIN_TOKEN_AMOUNT,
    TRIAL_MAX_DAYS_BEFORE_FIRST_CHARGE,
    date_key,
    find_series,
    group_by_normalised_key,
    ppy_for,
    resolve_alias,
    sorted_source_refs,
)
from ledger_kit.detectors import register
from ledger_kit.models import Alert
from ledger_kit.utils.money import round_to_cents


def _is_trial(row: dict, series_start: date, series_refs: set[str]) -> bool:
    """Return True for a token charge, outside the series, 1..35 days before it starts."""
    days_before = (series_start - row["date"]).days
    return (
        row["source_ref"] not in series_refs
        and FREE_TRIAL_MIN_TOKEN_AMOUNT <= Decimal(row["amount"]) <= FREE_TRIAL_MAX_TOKEN_AMOUNT
        and 1 <= days_before <= TRIAL_MAX_DAYS_BEFORE_FIRST_CHARGE
    )


@register("zs.free_trial_to_paid")
def detect_free_trial_to_paid(
    ledger: pd.DataFrame,
    context: Mapping[str, Any],
) -> list[Alert]:
    """Emit one info alert per series that follows a token trial charge of the same key."""
    alerts: list[Alert] = []
    if ledger.empty:
        return alerts
    aliases: dict[str, list[str]] | None = context.get("aliases")
    for key, key_rows in group_by_normalised_key(ledger):
        canonical = resolve_alias(key, aliases)
        for series in find_series(key_rows):
            series_start = series.rows[0]["date"]
            series_refs = {r["source_ref"] for r in series.rows}
            candidates = [r for r in key_rows if _is_trial(r, series_start, series_refs)]
            if not candidates:
                continue
            # The closest trial charge wins; ties go to the earlier (date, source_row).
            trial = min(candidates, key=lambda r: ((series_start - r["date"]).days, date_key(r)))
            trial_amount = round_to_cents(Decimal(trial["amount"]))
            first_paid = round_to_cents(Decimal(series.rows[0]["amount"]))
            yearly_cost = round_to_cents(series.current_amount * ppy_for(series.interval_type))
            alerts.append(
                Alert(
                    detector="zs.free_trial_to_paid",
                    severity="info",
                    title=f"Free trial converted to paid: {canonical}",
                    # Ordered by (date, source_row), never as text ('f.csv:10' < 'f.csv:9').
                    source_refs=sorted_source_refs([*series.rows, trial]),
                    data={
                        "counterparty": canonical,
                        "trial_amount": str(trial_amount),
                        "first_paid_amount": str(first_paid),
                        "trial_source_ref": trial["source_ref"],
                        "days_before_first_charge": (series_start - trial["date"]).days,
                        "yearly_cost": str(yearly_cost),
                        "interval_type": series.interval_type,
                    },
                )
            )
    return alerts
