"""Shared fixtures: synthetic, PII-safe ledgers (Finance Rules 5 and 6)."""

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from ledger_kit.ingestion.normaliser import normalise
from ledger_kit.models import Transaction

# Mod-97 valid, deliberately wrong Spanish national check digits (Finance Rule 5).
SYNTHETIC_IBAN = "ES88 2100 0418 5602 0005 1332"

_CLEAN_COUNTERPARTIES = (
    "Ana García",
    "Luigi Rossi",
    "Sophie Dupont",
    "Mateo Silva",
    "Chloé Martin",
    "Jonas Weber",
    "Elena Petrova",
    "Marco Bianchi",
    "Lucía Romero",
    "Hugo Laurent",
)


def make_transaction(
    index: int,
    *,
    source_file: str = "ledger.csv",
    counterparty: str = "Ana García",
    amount: Decimal = Decimal("10.00"),
    flow: str = "debit",
    day: date = date(2026, 1, 15),
    iban: str | None = None,
) -> Transaction:
    """Build one synthetic Transaction whose source_ref is '<source_file>:<index>'."""
    return Transaction(
        date=day,
        amount=amount,
        flow=flow,
        currency="EUR",
        counterparty=counterparty,
        description=f"Synthetic row {index}",
        iban=iban,
        source_file=source_file,
        source_row=index,
        source_ref=f"{source_file}:{index}",
    )


@pytest.fixture
def empty_ledger() -> pd.DataFrame:
    """Zero-row DataFrame with the canonical transaction columns."""
    frame, _ = normalise(kind="transaction")
    return frame


@pytest.fixture
def single_row_ledger() -> pd.DataFrame:
    """One valid Transaction row."""
    frame, _ = normalise([make_transaction(0, iban=SYNTHETIC_IBAN)])
    return frame


@pytest.fixture
def clean_ledger_10() -> pd.DataFrame:
    """Ten rows with distinct counterparties, distinct amounts and distinct months."""
    transactions = [
        make_transaction(
            i,
            source_file="clean.csv",
            counterparty=name,
            amount=Decimal(f"{20 + 13 * i}.{i:02d}"),
            flow="debit" if i % 3 else "credit",
            day=date(2026, 1 + i, 3 + i),
        )
        for i, name in enumerate(_CLEAN_COUNTERPARTIES)
    ]
    frame, _ = normalise(transactions)
    return frame
