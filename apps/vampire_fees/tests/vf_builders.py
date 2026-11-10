"""Row and ledger builders plus Hypothesis strategies for the vampire-fees tests.

Dates are always explicit; nothing here reads the system clock. Counterparties are invented
names (Finance Rule 5) and every amount is a Decimal built from text.
"""

from collections.abc import Iterable
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pandas as pd
from hypothesis import strategies as st

from apps.vampire_fees.detectors.utils import FeeVocabulary, build_vocabulary
from ledger_kit.ingestion.normaliser import CANONICAL_COLUMNS, normalise

SOURCE_FILE = "vf_fixture.csv"

# The default vocabulary of design 2.3, repeated here so unit tests do not read config.toml.
DEFAULT_VOCABULARY_TABLE: dict[str, list[str]] = {
    "fee": [
        "comision",
        "comisiones",
        "cuota de mantenimiento",
        "gastos",
        "fee",
        "fees",
        "commission",
        "commissions",
        "maintenance",
    ],
    "overdraft": ["descubierto", "intereses deudores", "overdraft"],
    "interest": ["intereses", "interest"],
    "exclude": ["notaria", "notario", "notary", "gestoria", "abogado", "lawyer", "honorarios"],
}


def default_vocabulary() -> FeeVocabulary:
    """Return the default vocabulary folded by the app's own build_vocabulary."""
    return build_vocabulary(DEFAULT_VOCABULARY_TABLE)


BANK = "BANCO FICTICIO"
MAINTENANCE = "Comisión mantenimiento cuenta"

# Fictional counterparties the fixtures may use (Finance Rule 5).
ALLOWED_COUNTERPARTIES: frozenset[str] = frozenset(
    {
        BANK,
        "Feelgood Market",
        "Mercado Central Demo",
        "STREAMFLIX INTL",
        "Café del Puerto",
        "Tienda Luna",
        "Farmacia Sol",
        "Gasolinera Norte",
        "Papelería Azul",
        "Librería Poniente",
        "Luminar Estudio S.L.",
    }
)

# Words that the default vocabulary (config.toml) recognises, and words it does not.
FEE_WORDS: tuple[str, ...] = ("Comisión", "fee", "Commission", "gastos", "Maintenance")
OVERDRAFT_WORDS: tuple[str, ...] = ("descubierto", "Intereses deudores", "overdraft")
EXCLUDE_WORDS: tuple[str, ...] = ("Notaría", "Gestoría", "lawyer", "Honorarios")
NEUTRAL_WORDS: tuple[str, ...] = ("Mercado", "Café", "Tienda", "Farmacia", "Papelería", "Luna")
TAG_CHOICES: tuple[Any, ...] = (
    None,
    [],
    ["common_concept:17"],
    ["common_concept:16"],
    ["common_concept:12"],
    ["common_concept:04", "own_concept:003"],
)


def fee_row(
    row_index: int,
    day: date,
    amount: str | Decimal,
    *,
    counterparty: str = BANK,
    description: str = MAINTENANCE,
    flow: str = "debit",
    currency: str = "EUR",
    tags: Any = None,
    source_file: str = SOURCE_FILE,
    source_ref: str | None = None,
) -> dict[str, Any]:
    """Build one canonical ledger row as a plain dict with an explicit date and Decimal amount."""
    ref = source_ref if source_ref is not None else f"{source_file}:{row_index}"
    return {
        "id": f"vf-{ref}",
        "date": day,
        "amount": Decimal(amount),
        "flow": flow,
        "currency": currency,
        "counterparty": counterparty,
        "description": description,
        "iban": None,
        "source_file": ref.split(":")[0],
        "source_row": row_index,
        "source_ref": ref,
        "tags": [] if tags is None else tags,
    }


def make_ledger(rows: Iterable[dict[str, Any]]) -> pd.DataFrame:
    """Build a canonical ledger DataFrame from row dicts (zero rows allowed)."""
    rows = list(rows)
    if not rows:
        frame, _ = normalise(kind="transaction")
        return frame
    frame = pd.DataFrame(rows, columns=list(CANONICAL_COLUMNS))
    frame["source_row"] = frame["source_row"].astype("int64")
    return frame


def series_rows(
    entries: Iterable[tuple[date, str | Decimal]],
    *,
    counterparty: str = BANK,
    description: str = MAINTENANCE,
    first_row: int = 0,
    tags: Any = None,
    source_file: str = SOURCE_FILE,
) -> list[dict[str, Any]]:
    """Build debit rows for explicit (date, amount) entries; source_row counts up from first_row."""
    return [
        fee_row(
            first_row + i,
            day,
            amount,
            counterparty=counterparty,
            description=description,
            tags=tags,
            source_file=source_file,
        )
        for i, (day, amount) in enumerate(entries)
    ]


def monthly_dates(start: date, count: int, step_days: int = 30) -> list[date]:
    """Return `count` dates `step_days` apart starting at `start`."""
    return [start + timedelta(days=step_days * i) for i in range(count)]


def summary_ledger(last_day: date = date(2026, 3, 31)) -> pd.DataFrame:
    """AE-VF-24: fees 10.00 and 20.00 (rows 3 and 5 of s.csv); the statement runs to `last_day`.

    Row 0 is a credit on 2026-01-01 (the first date); the last row is a card purchase on
    `last_day`. The fees are on 2026-01-10 and 2026-03-10.
    """
    purchase = {"counterparty": "Mercado Central Demo", "description": "Card purchase"}
    rows = [
        fee_row(
            0,
            date(2026, 1, 1),
            "1850.00",
            counterparty="Luminar Estudio S.L.",
            description="Payroll",
            flow="credit",
            source_file="s.csv",
        ),
        fee_row(1, date(2026, 1, 3), "20.00", source_file="s.csv", **purchase),
        fee_row(2, date(2026, 1, 9), "30.00", source_file="s.csv", **purchase),
        fee_row(3, date(2026, 1, 10), "10.00", source_file="s.csv"),
        fee_row(4, date(2026, 2, 14), "12.00", source_file="s.csv", **purchase),
        fee_row(5, date(2026, 3, 10), "20.00", source_file="s.csv"),
        fee_row(6, last_day, "8.00", source_file="s.csv", **purchase),
    ]
    return make_ledger(rows)


def refs_of(rows: Iterable[dict[str, Any]]) -> list[str]:
    """Return the source_ref of each row, in order."""
    return [row["source_ref"] for row in rows]


# --- Hypothesis strategies ---------------------------------------------------------------------

_DATES = st.dates(min_value=date(2025, 1, 1), max_value=date(2026, 12, 31))
_AMOUNTS = st.decimals(min_value=Decimal("0.01"), max_value=Decimal("900.00"), places=2)
_TEXTS = st.lists(
    st.sampled_from(FEE_WORDS + OVERDRAFT_WORDS + EXCLUDE_WORDS + NEUTRAL_WORDS),
    min_size=0,
    max_size=3,
).map(" ".join)
_COUNTERPARTIES = st.sampled_from((BANK, "Feelgood Market", "Mercado Central Demo", "Ana García"))


@st.composite
def row_strategy(draw: st.DrawFn, index: int = 0) -> dict[str, Any]:
    """Draw one row with random text from the word pools, random tags, flow and currency."""
    return fee_row(
        index,
        draw(_DATES),
        draw(_AMOUNTS),
        counterparty=draw(_COUNTERPARTIES),
        description=draw(_TEXTS),
        flow=draw(st.sampled_from(("debit", "debit", "credit"))),
        currency=draw(st.sampled_from(("EUR", "EUR", "EUR", "USD"))),
        tags=draw(st.sampled_from(TAG_CHOICES)),
    )


@st.composite
def ledger_strategy(draw: st.DrawFn, max_rows: int = 12) -> pd.DataFrame:
    """Draw a ledger (possibly empty) with unique source_refs."""
    count = draw(st.integers(min_value=0, max_value=max_rows))
    rows = [draw(row_strategy(index=i)) for i in range(count)]
    return make_ledger(rows)


@st.composite
def positive_ledger_strategy(draw: st.DrawFn, max_rows: int = 12) -> pd.DataFrame:
    """Draw a ledger of EUR debit rows only, every amount positive."""
    count = draw(st.integers(min_value=0, max_value=max_rows))
    rows = []
    for i in range(count):
        row = draw(row_strategy(index=i))
        row["flow"] = "debit"
        row["currency"] = "EUR"
        rows.append(row)
    return make_ledger(rows)


@st.composite
def regular_series_strategy(draw: st.DrawFn) -> list[dict[str, Any]]:
    """Draw 0 to 8 maintenance-fee debits with gaps drawn from 0 to 400 days."""
    count = draw(st.integers(min_value=0, max_value=8))
    day = draw(_DATES)
    rows = []
    for i in range(count):
        rows.append(fee_row(i, day, draw(_AMOUNTS)))
        day = day + timedelta(days=draw(st.integers(min_value=0, max_value=400)))
    return rows
