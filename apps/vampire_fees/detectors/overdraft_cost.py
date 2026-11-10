"""Overdraft-cost detector: one alert with the interest and fees of the overdraft (design 5.3)."""

from collections.abc import Mapping
from typing import Any

import pandas as pd

from apps.vampire_fees.detectors.utils import (
    EMPTY_VOCABULARY,
    OVERDRAFT_CRITICAL_TOTAL,
    extract_fees,
    sorted_refs,
)
from ledger_kit.detectors import register
from ledger_kit.models import Alert
from ledger_kit.utils.money import round_to_cents, sum_amounts


@register("vf.overdraft_cost")
def detect_overdraft_cost(ledger: pd.DataFrame, context: Mapping[str, Any]) -> list[Alert]:
    """Emit one alert for the statement when it has at least one overdraft interest or fee."""
    fees = extract_fees(ledger, context.get("vocabulary", EMPTY_VOCABULARY))
    overdraft = [fee for fee in fees if fee.kind == "overdraft"]
    if not overdraft:
        return []
    interest = [fee for fee in overdraft if fee.overdraft_interest]
    charges = [fee for fee in overdraft if not fee.overdraft_interest]
    total = round_to_cents(sum_amounts(fee.amount for fee in overdraft))
    return [
        Alert(
            detector="vf.overdraft_cost",
            severity="critical" if total >= OVERDRAFT_CRITICAL_TOTAL else "warning",
            title="Overdraft cost on this statement",
            source_refs=sorted_refs(overdraft),
            data={
                "interest_count": len(interest),
                "interest_total": str(round_to_cents(sum_amounts(f.amount for f in interest))),
                "fee_count": len(charges),
                "fee_total": str(round_to_cents(sum_amounts(f.amount for f in charges))),
                "total": str(total),
                "first_charge_date": overdraft[0].date.isoformat(),
                "last_charge_date": overdraft[-1].date.isoformat(),
            },
        )
    ]
