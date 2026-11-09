"""Price-increase detector: one warning per upward price step of a series (design §5.2)."""

from collections.abc import Mapping
from typing import Any

import pandas as pd

from apps.zombie_subscriptions.detectors.utils import (
    PRICE_INCREASE_MIN_RATIO,
    cpi_context_fields,
    find_series,
    group_by_normalised_key,
    ppy_for,
    resolve_alias,
    sorted_source_refs,
)
from ledger_kit.detectors import register
from ledger_kit.models import Alert
from ledger_kit.utils.money import round_to_cents


@register("zs.price_increase")
def detect_price_increases(ledger: pd.DataFrame, context: Mapping[str, Any]) -> list[Alert]:
    """Emit one warning for every upward price step of at least PRICE_INCREASE_MIN_RATIO.

    When `context["cpi"]` is a CPI series, the alert's data also carries the CPI comparison of
    the same months (public-cpi REQ-CPI-09); it never changes which alerts fire.
    """
    alerts: list[Alert] = []
    if ledger.empty:
        return alerts
    aliases: dict[str, list[str]] | None = context.get("aliases")
    cpi = context.get("cpi")
    for key, key_rows in group_by_normalised_key(ledger):
        canonical = resolve_alias(key, aliases)
        for series in find_series(key_rows):
            ppy = ppy_for(series.interval_type)
            for old, new in series.price_steps:  # stored rounded medians
                if new <= old:
                    continue  # downward or flat: never an alert
                if (new - old) / old < PRICE_INCREASE_MIN_RATIO:
                    continue  # exactly 5% fires
                data = {
                    "counterparty": canonical,
                    "old_median_amount": str(old),
                    "new_amount": str(new),
                    "extra_cost_per_year": str(round_to_cents((new - old) * ppy)),
                    "yearly_cost": str(round_to_cents(new * ppy)),
                    "interval_type": series.interval_type,
                }
                data.update(cpi_context_fields(series, old, new, cpi))
                alerts.append(
                    Alert(
                        detector="zs.price_increase",
                        severity="warning",
                        title=f"Price increase detected: {canonical}",
                        source_refs=sorted_source_refs(series.rows),
                        data=data,
                    )
                )
    return alerts
