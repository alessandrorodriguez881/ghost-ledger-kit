"""Shared fixtures for the zombie-subscriptions tests: synthetic ledgers, fictional merchants.

Dates are always explicit; nothing here reads the system clock. Counterparties are invented
merchant names, never person names and never real brands (Finance Rule 5).
"""

from collections.abc import Iterable
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pandas as pd
import pytest

from ledger_kit.ingestion.normaliser import CANONICAL_COLUMNS, normalise
from ledger_kit.utils.money import round_to_cents

SOURCE_FILE = "zs_fixture.csv"

# Service cancelled on this date in `ledger_with_post_cancellation` (one charge follows it).
CANCELLATION_DATE = date(2026, 3, 31)
# Last use of the service in `ledger_with_zombie` (the last two charges follow it).
ZOMBIE_LAST_USED_DATE = date(2026, 1, 25)


def _debit_row(
    source_ref: str,
    date_val: date,
    amount: str | Decimal,
    counterparty: str,
    currency: str = "EUR",
) -> dict:
    """Build one synthetic debit row as a plain dict with the canonical columns."""
    return {
        "id": str(uuid4()),
        "date": date_val,
        "amount": Decimal(amount),
        "flow": "debit",
        "currency": currency,
        "counterparty": counterparty,
        "description": "synthetic",
        "iban": None,
        "source_file": source_ref.split(":")[0],
        "source_row": int(source_ref.split(":")[1]),
        "source_ref": source_ref,
        "tags": [],
    }


def to_frame(rows: list[dict]) -> pd.DataFrame:
    """Build a canonical ledger DataFrame from row dicts (zero rows allowed)."""
    if not rows:
        frame, _ = normalise(kind="transaction")
        return frame
    frame = pd.DataFrame(rows, columns=list(CANONICAL_COLUMNS))
    frame["source_row"] = frame["source_row"].astype("int64")
    return frame


def rows_from(
    counterparty: str,
    entries: Iterable[tuple[date, str | Decimal]],
    *,
    first_row: int = 0,
    source_file: str = SOURCE_FILE,
) -> list[dict]:
    """Build rows for explicit (date, amount) entries; source_row counts up from first_row."""
    return [
        _debit_row(f"{source_file}:{first_row + i}", day, amount, counterparty)
        for i, (day, amount) in enumerate(entries)
    ]


def periodic_rows(
    counterparty: str,
    start: date,
    amounts: Iterable[str | Decimal],
    *,
    step_days: int = 30,
    first_row: int = 0,
    source_file: str = SOURCE_FILE,
) -> list[dict]:
    """Build rows `step_days` apart (30 = monthly, 7 = weekly) starting at `start`."""
    entries = [(start + timedelta(days=step_days * i), a) for i, a in enumerate(amounts)]
    return rows_from(counterparty, entries, first_row=first_row, source_file=source_file)


def rows_e1() -> list[dict]:
    """E1: 5 x 12.99 then 1 x 15.99, monthly, STREAMFLEX INTL."""
    amounts = ["12.99"] * 5 + ["15.99"]
    return periodic_rows("STREAMFLEX INTL", date(2026, 1, 5), amounts)


def rows_e2() -> list[dict]:
    """E2: 3 x 9.99 then 3 x 12.99, monthly, CLOUDVAULT."""
    amounts = ["9.99"] * 3 + ["12.99"] * 3
    return periodic_rows("CLOUDVAULT", date(2026, 1, 5), amounts)


def rows_e3() -> list[dict]:
    """E3: interleaved monthly 2.99 and 0.99 charges, GLOWBILL."""
    entries = [
        (date(2026, 1, 1), "2.99"),
        (date(2026, 1, 15), "0.99"),
        (date(2026, 2, 1), "2.99"),
        (date(2026, 2, 15), "0.99"),
        (date(2026, 3, 1), "2.99"),
        (date(2026, 3, 15), "0.99"),
    ]
    return rows_from("GLOWBILL", entries)


def rows_e4() -> list[dict]:
    """E4: two interleaved monthly 10.99 series, MUSICBOX."""
    days = [
        date(2026, 1, 1),
        date(2026, 1, 15),
        date(2026, 2, 1),
        date(2026, 2, 15),
        date(2026, 3, 1),
        date(2026, 3, 15),
    ]
    return rows_from("MUSICBOX", [(day, "10.99") for day in days])


def rows_e6() -> list[dict]:
    """E6: two supermarket charges 30 days apart, SUPERMART."""
    return periodic_rows("SUPERMART", date(2026, 1, 10), ["87.50", "143.20"])


def rows_e7() -> list[dict]:
    """E7: six weekly grocery charges with varying amounts, FRESHCO."""
    amounts = ["35.00", "90.00", "210.00", "60.00", "150.00", "120.00"]
    return periodic_rows("FRESHCO", date(2026, 5, 4), amounts, step_days=7)


def rows_downgrade() -> list[dict]:
    """Downgrade: 3 x 14.99 then 3 x 9.99, monthly, CLOUDVAULT."""
    amounts = ["14.99"] * 3 + ["9.99"] * 3
    return periodic_rows("CLOUDVAULT", date(2026, 1, 5), amounts)


def rows_weekly_shopping() -> list[dict]:
    """E7b: 26 weekly FRESHCO charges, amount round_to_cents(40.00 x 1.11^k), k = 5i mod 13."""
    base = Decimal("40.00")
    amounts = [round_to_cents(base * Decimal("1.11") ** ((5 * i) % 13)) for i in range(26)]
    return periodic_rows("FRESHCO", date(2026, 5, 4), amounts, step_days=7)


def rows_recurring() -> list[dict]:
    """Three monthly 12.99 charges, CLOUDVAULT."""
    return periodic_rows("CLOUDVAULT", date(2026, 1, 10), ["12.99"] * 3)


@pytest.fixture
def builders() -> SimpleNamespace:
    """Row and frame builders plus the constants shared by the fixtures."""
    return SimpleNamespace(
        debit_row=_debit_row,
        to_frame=to_frame,
        rows_from=rows_from,
        periodic_rows=periodic_rows,
        rows_e1=rows_e1,
        rows_e2=rows_e2,
        rows_e3=rows_e3,
        rows_e4=rows_e4,
        rows_e6=rows_e6,
        rows_e7=rows_e7,
        rows_downgrade=rows_downgrade,
        rows_weekly_shopping=rows_weekly_shopping,
        rows_recurring=rows_recurring,
        cancellation_date=CANCELLATION_DATE,
        zombie_last_used_date=ZOMBIE_LAST_USED_DATE,
    )


@pytest.fixture
def empty_ledger() -> pd.DataFrame:
    """Zero-row DataFrame with the canonical columns."""
    return to_frame([])


@pytest.fixture
def single_row_ledger() -> pd.DataFrame:
    """One debit row for CLOUDVAULT."""
    return to_frame(periodic_rows("CLOUDVAULT", date(2026, 1, 10), ["12.99"]))


@pytest.fixture
def clean_ledger_10() -> pd.DataFrame:
    """Ten debit rows at ten different fictional merchants with no recurring pattern."""
    merchants = [
        "FRESHCO",
        "SUPERMART",
        "BAKERYONE",
        "FUELSTOP",
        "BOOKNOOK",
        "TOYBARN",
        "GARDENPOINT",
        "CAFELUNA",
        "HARDWAREHUB",
        "PHARMAPOINT",
    ]
    start = date(2026, 1, 3)
    entries = [
        (start + timedelta(days=17 * i), Decimal(f"{20 + 13 * i}.{i:02d}")) for i in range(10)
    ]
    rows = [
        _debit_row(f"{SOURCE_FILE}:{i}", day, amount, merchant)
        for i, ((day, amount), merchant) in enumerate(zip(entries, merchants, strict=True))
    ]
    return to_frame(rows)


@pytest.fixture
def ledger_with_recurring() -> pd.DataFrame:
    """Three monthly 12.99 charges for CLOUDVAULT (meets MIN_OCCURRENCES_MONTHLY)."""
    return to_frame(rows_recurring())


@pytest.fixture
def ledger_with_price_increase() -> pd.DataFrame:
    """E1: 5 x 12.99 then 1 x 15.99, monthly, STREAMFLEX INTL."""
    return to_frame(rows_e1())


@pytest.fixture
def ledger_with_duplicate_sub() -> pd.DataFrame:
    """E4: two interleaved monthly 10.99 series for MUSICBOX."""
    return to_frame(rows_e4())


@pytest.fixture
def ledger_with_aliased_duplicate() -> pd.DataFrame:
    """E5: 3 monthly STREAMFLIX INTL charges and 3 monthly STREAMFLIXCOM charges."""
    entries_intl = [
        (date(2026, 1, 5), "14.99"),
        (date(2026, 2, 4), "14.99"),
        (date(2026, 3, 6), "14.99"),
    ]
    entries_com = [
        (date(2026, 1, 20), "14.99"),
        (date(2026, 2, 19), "14.99"),
        (date(2026, 3, 21), "14.99"),
    ]
    tagged = [("STREAMFLIX INTL", d, a) for d, a in entries_intl]
    tagged += [("STREAMFLIXCOM", d, a) for d, a in entries_com]
    tagged.sort(key=lambda t: t[1])
    rows = [
        _debit_row(f"{SOURCE_FILE}:{i}", day, amount, counterparty)
        for i, (counterparty, day, amount) in enumerate(tagged)
    ]
    return to_frame(rows)


@pytest.fixture
def ledger_with_free_trial() -> pd.DataFrame:
    """One 0.49 trial charge, then 3 monthly 14.99 charges starting 14 days later, SECUREPASS."""
    entries = [
        (date(2026, 1, 1), "0.49"),
        (date(2026, 1, 15), "14.99"),
        (date(2026, 2, 14), "14.99"),
        (date(2026, 3, 16), "14.99"),
    ]
    return to_frame(rows_from("SECUREPASS", entries))


@pytest.fixture
def ledger_with_post_cancellation() -> pd.DataFrame:
    """3 monthly 8.99 charges and one more after CANCELLATION_DATE, GYMPLUS."""
    entries = [
        (date(2026, 1, 10), "8.99"),
        (date(2026, 2, 9), "8.99"),
        (date(2026, 3, 11), "8.99"),
        (date(2026, 4, 10), "8.99"),
    ]
    return to_frame(rows_from("GYMPLUS", entries))


@pytest.fixture
def ledger_with_zombie() -> pd.DataFrame:
    """Recurring CLOUDVAULT charges; the last two follow ZOMBIE_LAST_USED_DATE."""
    return to_frame(rows_recurring())


@pytest.fixture
def ledger_with_weekly_shopping() -> pd.DataFrame:
    """E7b: 26 weekly FRESHCO charges built from the design §4.8 formula."""
    return to_frame(rows_weekly_shopping())
