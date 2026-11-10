"""Fee-increase detector: one alert per run whose latest rise holds (design 4.4 and 5.2)."""

from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd

from apps.vampire_fees.detectors.utils import (
    EMPTY_VOCABULARY,
    FEE_INCREASE_CRITICAL_RATIO,
    FEE_INCREASE_MIN_RATIO,
    FEE_STABLE_RATIO,
    Fee,
    extract_fees,
    in_first_row_order,
    recurring_runs,
    sorted_refs,
    yearly_cost,
)
from ledger_kit.detectors import register
from ledger_kit.models import Alert
from ledger_kit.utils.money import percent_change, round_percent, round_to_cents


def latest_rise(run: Sequence[Fee]) -> int | None:
    """Return the latest index i whose step from i-1 is a rise that every later row holds."""
    for i in range(len(run) - 1, 0, -1):
        old, new = run[i - 1].amount, run[i].amount
        if old <= 0 or new - old < old * FEE_INCREASE_MIN_RATIO:
            continue
        if all(abs(later.amount - new) <= new * FEE_STABLE_RATIO for later in run[i + 1 :]):
            return i
    return None


@register("vf.fee_increase")
def detect_fee_increases(ledger: pd.DataFrame, context: Mapping[str, Any]) -> list[Alert]:
    """Emit one alert for every regular fee series whose latest rise holds."""
    fees = extract_fees(ledger, context.get("vocabulary", EMPTY_VOCABULARY))
    entries: list[tuple[Fee, Alert]] = []
    for interval, run in recurring_runs(fees):
        i = latest_rise(run)
        if i is None:
            continue
        before, after, last = run[i - 1], run[i], run[-1]
        old, new = before.amount, after.amount
        critical = new - old >= old * FEE_INCREASE_CRITICAL_RATIO
        alert = Alert(
            detector="vf.fee_increase",
            severity="critical" if critical else "warning",
            title=f"Fee increase: {last.counterparty} · {last.description}",
            source_refs=sorted_refs([before, after]),
            data={
                "counterparty": last.counterparty,
                "description": last.description,
                "interval_type": interval.name,
                "old_amount": str(round_to_cents(old)),
                "new_amount": str(round_to_cents(new)),
                "increase_percent": str(round_percent(percent_change(old, new))),
                "increase_date": after.date.isoformat(),
                "old_charge_date": before.date.isoformat(),
                "extra_cost_per_year": str(round_to_cents((new - old) * interval.periods_per_year)),
                "yearly_cost": str(yearly_cost(new, interval)),
            },
        )
        entries.append((before, alert))
    return in_first_row_order(entries)
