"""Shared fixtures for the vampire-fees tests: synthetic ledgers, fictional names.

Dates are always explicit; nothing here reads the system clock. The builders live in
vf_builders.py (imported by the tests as an ordinary module).
"""

from datetime import date, timedelta

import pandas as pd
import pytest

from apps.vampire_fees.detectors.utils import FeeVocabulary
from apps.vampire_fees.tests.vf_builders import (
    default_vocabulary,
    fee_row,
    make_ledger,
    series_rows,
)

CLEAN_MERCHANTS: tuple[str, ...] = (
    "Mercado Central Demo",
    "Café del Puerto",
    "Tienda Luna",
    "Farmacia Sol",
    "Gasolinera Norte",
    "Papelería Azul",
    "Librería Poniente",
    "Feelgood Market",
    "Mercado Central Demo",
    "Tienda Luna",
)


@pytest.fixture
def vocabulary() -> FeeVocabulary:
    """The default vocabulary of design 2.3, folded."""
    return default_vocabulary()


@pytest.fixture
def empty_ledger() -> pd.DataFrame:
    """Zero-row DataFrame with the canonical columns."""
    return make_ledger([])


@pytest.fixture
def single_row_ledger() -> pd.DataFrame:
    """One maintenance-fee debit."""
    return make_ledger([fee_row(0, date(2026, 1, 5), "5.00")])


@pytest.fixture
def clean_ledger_10() -> pd.DataFrame:
    """Ten card purchases at fictional shops with no fee word and no concept tag."""
    start = date(2026, 1, 3)
    rows = [
        fee_row(
            i,
            start + timedelta(days=17 * i),
            f"{20 + 13 * i}.{i:02d}",
            counterparty=merchant,
            description="Card purchase",
        )
        for i, merchant in enumerate(CLEAN_MERCHANTS)
    ]
    return make_ledger(rows)


@pytest.fixture
def ledger_with_monthly_fee() -> pd.DataFrame:
    """AE-VF-09: debits of 5.00 on 2026-01-05, 2026-02-05 and 2026-03-05."""
    entries = [(date(2026, 1, 5), "5.00"), (date(2026, 2, 5), "5.00"), (date(2026, 3, 5), "5.00")]
    return make_ledger(series_rows(entries))


@pytest.fixture
def ledger_with_fee_increase() -> pd.DataFrame:
    """AE-VF-17: monthly 5.00, 5.00, 5.00 then 5.25."""
    entries = [
        (date(2025, 11, 5), "5.00"),
        (date(2025, 12, 5), "5.00"),
        (date(2026, 1, 5), "5.00"),
        (date(2026, 2, 5), "5.25"),
    ]
    return make_ledger(series_rows(entries))


@pytest.fixture
def ledger_with_overdraft() -> pd.DataFrame:
    """AE-VF-21: overdraft interest 12.40 and an overdraft fee 15.00 in June 2025."""
    rows = [
        fee_row(0, date(2025, 6, 18), "15.00", description="Comisión por descubierto"),
        fee_row(1, date(2025, 6, 30), "12.40", description="Intereses deudores"),
    ]
    return make_ledger(rows)


@pytest.fixture
def ledger_with_one_off_fees() -> pd.DataFrame:
    """Three one-off commissions with irregular gaps plus a refund credit (no series)."""
    rows = [
        fee_row(0, date(2025, 4, 9), "1.50", description="Comisión transferencia inmediata"),
        fee_row(1, date(2025, 7, 22), "1.50", description="Comisión transferencia inmediata"),
        fee_row(2, date(2026, 2, 3), "1.50", description="Comisión transferencia inmediata"),
        fee_row(
            3,
            date(2025, 4, 10),
            "1.50",
            description="Devolución comisión transferencia",
            flow="credit",
            tags=["common_concept:17"],
        ),
    ]
    return make_ledger(rows)
