"""Duplicate-subscription detector: active series of one service billed twice (design §5.3)."""

from collections import defaultdict
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

import pandas as pd

from apps.zombie_subscriptions.detectors.utils import (
    AMOUNT_MATCH_RATIO,
    Series,
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


def _qualifying_series(series_list: list[tuple[str, Series]]) -> list[tuple[str, Series]]:
    """Return the series that take part in at least one duplicate pair, in input order."""
    qualifying: list[tuple[str, Series]] = []
    for i, (key_i, series_i) in enumerate(series_list):
        for key_j, series_j in series_list[i + 1 :]:
            if key_i == key_j:
                # Same key: the current amounts must be within AMOUNT_MATCH_RATIO (E4 yes, E3 no).
                larger = max(series_i.current_amount, series_j.current_amount)
                gap = abs(series_i.current_amount - series_j.current_amount)
                if gap / larger > AMOUNT_MATCH_RATIO:
                    continue
            # Different keys of one canonical name always qualify when both are active (E5).
            for item in ((key_i, series_i), (key_j, series_j)):
                if not any(item[1] is member[1] for member in qualifying):
                    qualifying.append(item)
    return qualifying


@register("zs.duplicate_subscription")
def detect_duplicate_subscriptions(
    ledger: pd.DataFrame,
    context: Mapping[str, Any],
) -> list[Alert]:
    """Emit one warning per service that has two or more active, matching series."""
    alerts: list[Alert] = []
    if ledger.empty:
        return alerts
    aliases: dict[str, list[str]] | None = context.get("aliases")
    max_date = ledger_max_date(ledger)

    # Active series per canonical service name, each tagged with its normalised key.
    by_service: dict[str, list[tuple[str, Series]]] = defaultdict(list)
    for key, key_rows in group_by_normalised_key(ledger):
        for series in find_series(key_rows):
            if is_active(series, max_date):
                by_service[resolve_alias(key, aliases)].append((key, series))

    for canonical, series_list in by_service.items():
        qualifying = _qualifying_series(series_list)
        if len(qualifying) < 2:
            continue
        all_rows = [row for _key, series in qualifying for row in series.rows]
        total_yearly = Decimal("0.00")
        for _key, series in qualifying:
            total_yearly += round_to_cents(series.current_amount * ppy_for(series.interval_type))
        alerts.append(
            Alert(
                detector="zs.duplicate_subscription",
                severity="warning",
                title=f"Duplicate subscription: {canonical}",
                source_refs=sorted_source_refs(all_rows),
                data={
                    "canonical_name": canonical,
                    "series_count": len(qualifying),
                    "series_counterparties": [key for key, _series in qualifying],
                    "yearly_cost": str(round_to_cents(total_yearly)),
                },
            )
        )
    return alerts
