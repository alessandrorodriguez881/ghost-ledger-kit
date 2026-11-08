"""Zombie-subscriptions detectors: importing this package registers the five zs.* detectors."""

from collections.abc import Mapping
from datetime import date
from typing import Any

import pandas as pd

from apps.zombie_subscriptions.detectors.utils import normalise_counterparty
from ledger_kit.detectors import DetectorResult, auto_discover, run_all

auto_discover("apps.zombie_subscriptions.detectors")


def run_zs_detectors(
    ledger: pd.DataFrame,
    *,
    aliases: dict[str, list[str]] | None = None,
    cancellation_dates: dict[str, date] | None = None,
) -> list[DetectorResult]:
    """Run every registered zs.* detector with the user's aliases and cancellation dates."""
    context: Mapping[str, Any] = {"aliases": aliases, "cancellation_dates": cancellation_dates}
    return run_all(ledger, namespace="zs", context=context)


__all__ = ["normalise_counterparty", "run_zs_detectors"]
