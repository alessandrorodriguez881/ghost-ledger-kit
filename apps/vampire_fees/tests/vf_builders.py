"""Row and ledger builders plus Hypothesis strategies for the vampire-fees tests.

Dates are always explicit; nothing here reads the system clock. Counterparties are invented
names (Finance Rule 5) and every amount is a Decimal built from text.
"""

import importlib.util
import tomllib
from collections.abc import Iterable
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import pandas as pd
from hypothesis import strategies as st

from apps.vampire_fees.detectors.utils import (
    Fee,
    FeeVocabulary,
    PeerContext,
    PeerService,
    build_peer_services,
    build_vocabulary,
    series_key,
)
from ledger_kit.ingestion.normaliser import CANONICAL_COLUMNS, normalise
from ledger_kit.public_data import FeeSnapshot

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


def peer_fee(
    description: str,
    counterparty: str = BANK,
    *,
    day: date = date(2026, 10, 5),
    amount: str = "6.50",
) -> Fee:
    """Build one Fee directly (no classifier), for the peer-service matching tests."""
    return Fee(
        source_ref=f"{SOURCE_FILE}:0",
        source_row=0,
        date=day,
        amount=Decimal(amount),
        counterparty=counterparty,
        description=description,
        kind="other",
        overdraft_interest=False,
        key=series_key(counterparty, description),
    )


# --- Peer context (public-fees PF4, PF5): synthetic snapshots and demo series ------------------

PEER_DECLARATION_DATE = "2026-11-23"
MAINTENANCE_DESCRIPTION = MAINTENANCE
CARD_DESCRIPTION = "Comisión anual tarjeta débito"
CUSTODY_DESCRIPTION = "Comisión custodia valores"
# The file name the REQ-PF-16 and REQ-PF-18 examples cite.
PEER_SOURCE_FILE = "s.csv"
_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.toml"
_BDE_BUILDERS_PATH = (
    Path(__file__).resolve().parents[3] / "tests" / "public_data" / "bde_builders.py"
)
_loaded_bde_builders: list[ModuleType] = []


def bde_builders() -> ModuleType:
    """Return tests/public_data/bde_builders.py (synthetic snapshots), loaded once by its path."""
    if not _loaded_bde_builders:
        spec = importlib.util.spec_from_file_location("vf_loaded_bde_builders", _BDE_BUILDERS_PATH)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _loaded_bde_builders.append(module)
    return _loaded_bde_builders[0]


def peer_services() -> tuple[PeerService, ...]:
    """Return the services of the committed config.toml [peer_fees] table."""
    config = tomllib.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    return build_peer_services(config["peer_fees"])


def snapshot_dict_of(
    maintenance: Iterable[str] = (),
    card: Iterable[str] = (),
    *,
    maintenance_asterisks: int = 0,
    declaration_date: str = PEER_DECLARATION_DATE,
) -> dict[str, Any]:
    """Return a synthetic CNO snapshot: one account per amount of service 101 or 401.

    Account i has the i-th maintenance amount (then `maintenance_asterisks` accounts hold the
    asterisk) and the i-th card amount; an account with neither has no row. Every amount is a
    two-decimal string and everything is synthetic (never a Banco de España figure).
    """
    b = bde_builders()
    maintenance, card = tuple(maintenance), tuple(card)
    count = max(len(maintenance) + maintenance_asterisks, len(card), 1)
    accounts = [b.account(str(9901 + i), declaration_date=declaration_date) for i in range(count)]
    rows: list[dict[str, Any]] = []
    for i, acc in enumerate(accounts):
        if i < len(maintenance):
            rows.append(b.amount_row(acc, "101", b.MAINTENANCE_CONCEPT, maintenance[i]))
        elif i < len(maintenance) + maintenance_asterisks:
            rows.append(b.asterisk_row(acc, "101", b.MAINTENANCE_CONCEPT))
        if i < len(card):
            rows.append(b.amount_row(acc, "401", b.CARD_CONCEPT, card[i]))
    ordered = b.sort_rows(rows, accounts)
    return b.make_snapshot(accounts, ordered, declaration_date=declaration_date)


# S12 and S10 of REQ-PF-07 and REQ-PF-12, as amounts of the demo fees (synthetic).
S12_AMOUNTS: tuple[str, ...] = (
    "0.00",
    "0.00",
    "0.00",
    "0.00",
    "0.00",
    "12.00",
    "24.00",
    "36.00",
    "60.00",
    "78.00",
    "96.00",
    "240.00",
)
S10_AMOUNTS: tuple[str, ...] = (
    "0.00",
    "0.00",
    "0.00",
    "0.00",
    "0.00",
    "12.00",
    "18.00",
    "24.00",
    "30.00",
    "45.00",
)


def s12_snapshot_dict() -> dict[str, Any]:
    """S12 (synthetic): 12 amounts and 3 asterisks for service 101, declared 2026-11-23."""
    return snapshot_dict_of(S12_AMOUNTS, maintenance_asterisks=3)


def s10_snapshot_dict() -> dict[str, Any]:
    """S10 (synthetic): ten amounts for service 401, declared 2026-11-23."""
    return snapshot_dict_of(card=S10_AMOUNTS)


def peer_context(snapshot: FeeSnapshot | dict[str, Any], account_type: str = "CNO") -> PeerContext:
    """Return a PeerContext for a snapshot (a dict is validated first) and the config services."""
    loaded = snapshot if isinstance(snapshot, FeeSnapshot) else FeeSnapshot.from_dict(snapshot)
    return PeerContext(loaded, account_type, peer_services())


def monthly_entries(
    count: int, amount: str, start: date = date(2025, 1, 5)
) -> list[tuple[date, str]]:
    """Return `count` (date, amount) entries on the same day of consecutive months."""
    entries = []
    for i in range(count):
        month = start.month - 1 + i
        entries.append((date(start.year + month // 12, month % 12 + 1, start.day), amount))
    return entries


def demo_maintenance_rows(
    first_row: int = 0, source_file: str = PEER_SOURCE_FILE
) -> list[dict[str, Any]]:
    """The demo maintenance series: 22 monthly 6.50 from 2025-01-05 to 2026-10-05 (78.00 a year)."""
    return series_rows(
        monthly_entries(22, "6.50"),
        description=MAINTENANCE_DESCRIPTION,
        first_row=first_row,
        source_file=source_file,
    )


def demo_card_rows(first_row: int = 0, source_file: str = PEER_SOURCE_FILE) -> list[dict[str, Any]]:
    """The demo yearly card fee: 30.00 on 2025-02-14 and 2026-02-16 (30.00 a year)."""
    return series_rows(
        [(date(2025, 2, 14), "30.00"), (date(2026, 2, 16), "30.00")],
        description=CARD_DESCRIPTION,
        first_row=first_row,
        source_file=source_file,
    )


def demo_custody_rows(
    first_row: int = 0, source_file: str = PEER_SOURCE_FILE
) -> list[dict[str, Any]]:
    """A monthly custody fee (a service with no comparison): 5.00 on 2026-03-05, 04-05, 05-05."""
    return series_rows(
        monthly_entries(3, "5.00", date(2026, 3, 5)),
        description=CUSTODY_DESCRIPTION,
        first_row=first_row,
        source_file=source_file,
    )


def demo_maintenance_ledger() -> pd.DataFrame:
    """The maintenance series alone (rows 0 to 21 of s.csv)."""
    return make_ledger(demo_maintenance_rows())


def demo_card_ledger() -> pd.DataFrame:
    """The card series alone (rows 0 and 1 of s.csv)."""
    return make_ledger(demo_card_rows())


def demo_fee_ledger() -> pd.DataFrame:
    """Maintenance (rows 0 to 21), card (22, 23) and custody (24 to 26), all in s.csv."""
    return make_ledger([*demo_maintenance_rows(), *demo_card_rows(22), *demo_custody_rows(24)])


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


_PEER_AMOUNTS = st.decimals(min_value=Decimal("0.00"), max_value=Decimal("400.00"), places=2).map(
    lambda amount: format(amount.quantize(Decimal("0.01")), "f")
)
_PEER_DECLARATION_DATES = st.dates(min_value=date(2025, 6, 1), max_value=date(2027, 6, 30))


@st.composite
def peer_snapshot_dict_strategy(draw: st.DrawFn) -> dict[str, Any]:
    """Draw a synthetic CNO snapshot with 0 to 14 amounts for service 101 and for 401."""
    return snapshot_dict_of(
        draw(st.lists(_PEER_AMOUNTS, max_size=14)),
        draw(st.lists(_PEER_AMOUNTS, max_size=14)),
        maintenance_asterisks=draw(st.integers(min_value=0, max_value=4)),
        declaration_date=draw(_PEER_DECLARATION_DATES).isoformat(),
    )


@st.composite
def peer_series_ledger_strategy(draw: st.DrawFn) -> pd.DataFrame:
    """Draw one regular fee series: maintenance, debit card or custody, 3 to 5 charges."""
    description = draw(
        st.sampled_from((MAINTENANCE_DESCRIPTION, CARD_DESCRIPTION, CUSTODY_DESCRIPTION))
    )
    step = draw(st.sampled_from((30, 91, 365)))
    start = draw(st.dates(min_value=date(2024, 6, 1), max_value=date(2026, 6, 30)))
    amount = draw(_AMOUNTS)
    count = draw(st.integers(min_value=3, max_value=5))
    entries = [(start + timedelta(days=step * i), amount) for i in range(count)]
    return make_ledger(series_rows(entries, description=description))
