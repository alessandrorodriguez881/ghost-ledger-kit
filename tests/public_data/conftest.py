"""Fixtures of the synthetic CPI series S, G and C (REQ-CPI-06, REQ-CPI-11); not INE figures."""

from __future__ import annotations

import pytest
from cpi_builders import C_VALUES, G_VALUES, S_VALUES

from ledger_kit.public_data import CpiSeries


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
