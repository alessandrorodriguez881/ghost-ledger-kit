"""Committed official public data (INE CPI snapshot); no network access at run time."""

from ledger_kit.public_data.ine_cpi import (
    CPI_MAX_LAG_MONTHS,
    DEFAULT_SNAPSHOT_PATH,
    CpiPoint,
    CpiSeries,
    SnapshotError,
    load_snapshot,
    month_key,
    validate_snapshot,
)

__all__ = [
    "CPI_MAX_LAG_MONTHS",
    "DEFAULT_SNAPSHOT_PATH",
    "CpiPoint",
    "CpiSeries",
    "SnapshotError",
    "load_snapshot",
    "month_key",
    "validate_snapshot",
]
