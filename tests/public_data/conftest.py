"""Fixtures of the synthetic CPI series S, G and C (REQ-CPI-06, REQ-CPI-11) and of the
synthetic fee snapshots S12 and S10 (REQ-PF-07, REQ-PF-12); not INE or Banco de España figures.
"""

from __future__ import annotations

import pytest
from bde_builders import synthetic_s10, synthetic_s12
from cpi_builders import C_VALUES, G_VALUES, S_VALUES

from ledger_kit.public_data import CpiSeries, FeeSnapshot


@pytest.fixture
def cpi_s_series() -> CpiSeries:
    """Synthetic series S: three contiguous months of 2026."""
    return CpiSeries.from_mapping(S_VALUES)


@pytest.fixture
def cpi_gapped_series() -> CpiSeries:
    """Synthetic series G: 2026-01 and 2026-03, with 2026-02 missing."""
    return CpiSeries.from_mapping(G_VALUES)


@pytest.fixture
def cpi_c_series() -> CpiSeries:
    """Synthetic series C: 2026-01 to 2026-06."""
    return CpiSeries.from_mapping(C_VALUES)


@pytest.fixture
def synthetic_s12_snapshot() -> FeeSnapshot:
    """Synthetic snapshot S12: 15 CNO accounts, 12 amounts and 3 asterisks for service 101."""
    return FeeSnapshot.from_dict(synthetic_s12())


@pytest.fixture
def synthetic_s10_snapshot() -> FeeSnapshot:
    """Synthetic snapshot S10: 10 CNO accounts with an amount for service 401."""
    return FeeSnapshot.from_dict(synthetic_s10())
