"""Synthetic CPI values and snapshot builders for the public-data tests (not INE figures)."""

from __future__ import annotations

import copy
from typing import Any

from ledger_kit.public_data.ine_cpi import ATTRIBUTION, LICENCE, NO_ENDORSEMENT

# Series S, G and C of REQ-CPI-06 / REQ-CPI-11 (synthetic).
S_VALUES = {"2026-01": "100.000", "2026-02": "100.500", "2026-03": "101.000"}
G_VALUES = {"2026-01": "100.000", "2026-03": "101.000"}
C_VALUES = {
    "2026-01": "100.000",
    "2026-02": "100.500",
    "2026-03": "101.000",
    "2026-04": "102.000",
    "2026-05": "102.500",
    "2026-06": "103.000",
}


def snapshot_dict(values: dict[str, str] | None = None, **overrides: Any) -> dict[str, Any]:
    """Return a valid snapshot object (synthetic values), with top-level keys overridden."""
    values = S_VALUES if values is None else values
    months = list(values)
    data: dict[str, Any] = {
        "series_code": "IPC290751",
        "series_name": "Nacional. Índice general. Índice",
        "table": 76125,
        "base_year": 2025,
        "classification": "ECOICOP v2",
        "periodicity": "monthly",
        "api_url": "https://servicios.ine.es/wstempus/js/ES/DATOS_SERIE/IPC290751",
        "retrieved_on": "2026-11-09",
        "licence": LICENCE,
        "attribution": ATTRIBUTION,
        "no_endorsement": NO_ENDORSEMENT,
        "first_month": months[0] if months else None,
        "last_month": months[-1] if months else None,
        "values": [{"month": m, "value": v, "status": "Definitivo"} for m, v in values.items()],
    }
    data.update(overrides)
    return copy.deepcopy(data)
