"""Synthetic fee snapshots for the public-data tests (REQ-PF-07, REQ-PF-12, REQ-PF-22).

Every amount here is **synthetic**, never a Banco de España figure. Entity codes are in the
placeholder range 9901 to 9999 and entity names are fictional (`BANCO FICTICIO`, `Caja Demo`).
"""

from __future__ import annotations

import copy
import hashlib
from decimal import Decimal
from typing import Any

from hypothesis import strategies as st

from ledger_kit.public_data.bde_fees import (
    ACCOUNT_TYPE_ORDER,
    LICENCE_NOTE,
    NO_ENDORSEMENT,
    SOURCE,
    START_PAGE,
    attribution_for,
)

DECLARATION_DATE = "2026-11-23"
# The two compared concepts as the Excel spells them, ANUAL in capitals (amendment A1, DN-PF-28).
MAINTENANCE_CONCEPT = "Comisión ANUAL total (euros)"
CARD_CONCEPT = "Comisión mantenimiento. ANUAL total (euros)"
PERIOD_CONCEPT = "Periodicidad"
# A synthetic SHA-256 (64 lowercase hex digits) for the Excel entries of a fixture.
FAKE_SHA256 = "ab" * 32


def fake_sha256(label: str) -> str:
    """Return a distinct synthetic SHA-256 for one fixture file entry (DN-PF-26: no repeat)."""
    return hashlib.sha256(f"synthetic excel {label}".encode()).hexdigest()


# S12 of REQ-PF-07: twelve amounts for service 101, in a scrambled order (synthetic).
S12_AMOUNTS: tuple[str, ...] = (
    "240.00",
    "0.00",
    "12.00",
    "0.00",
    "96.00",
    "24.00",
    "0.00",
    "78.00",
    "36.00",
    "0.00",
    "60.00",
    "0.00",
)
# S10 of REQ-PF-12: ten amounts for service 401 (synthetic).
S10_AMOUNTS: tuple[str, ...] = (
    "45.00",
    "0.00",
    "12.00",
    "0.00",
    "30.00",
    "18.00",
    "0.00",
    "24.00",
    "0.00",
    "0.00",
)


def entity_name(code: str) -> str:
    """Return the fictional name of a placeholder entity code."""
    if code == "9901":
        return "BANCO FICTICIO"
    if code == "9902":
        return "Caja Demo"
    return f"Entidad Demo {code}"


def account(
    entity_code: str,
    nn: int = 1,
    *,
    account_type: str = "CNO",
    declaration_date: str = DECLARATION_DATE,
    account_name: str | None = None,
) -> dict[str, Any]:
    """Return one account entry (one declaration) of a synthetic snapshot."""
    return {
        "account_type": account_type,
        "declaration_date": declaration_date,
        "entity_code": entity_code,
        "entity_name": entity_name(entity_code),
        "account_key": f"{entity_code}-{nn:02d}",
        "account_name": account_name or f"Cuenta Demo {nn}",
    }


def row(
    acc: dict[str, Any],
    service_code: str,
    concept: str,
    text: str,
    amount: str | None = None,
    not_offered: bool = False,
) -> dict[str, Any]:
    """Return one row of a synthetic snapshot for the account `acc`."""
    return {
        "account_type": acc["account_type"],
        "account_key": acc["account_key"],
        "service_code": service_code,
        "concept": concept,
        "text": text,
        "amount": amount,
        "not_offered": not_offered,
    }


def amount_row(acc: dict[str, Any], service_code: str, concept: str, amount: str) -> dict[str, Any]:
    """Return a row with a euro amount; the text is the amount with a decimal comma."""
    return row(acc, service_code, concept, amount.replace(".", ","), amount)


def asterisk_row(acc: dict[str, Any], service_code: str, concept: str) -> dict[str, Any]:
    """Return the row of a service the account does not offer (No practicado)."""
    return row(acc, service_code, concept, "*", None, True)


def sort_rows(rows: list[dict[str, Any]], accounts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the rows in the order of REQ-PF-01 (stable, so concepts keep their order)."""
    entity = {(a["account_type"], a["account_key"]): a["entity_code"] for a in accounts}

    def position(r: dict[str, Any]) -> tuple[int, str, str, str]:
        code, key = r["account_type"], r["account_key"]
        return (ACCOUNT_TYPE_ORDER.index(code), entity[(code, key)], key, r["service_code"])

    return sorted(rows, key=position)


def make_snapshot(
    accounts: list[dict[str, Any]], rows: list[dict[str, Any]], **overrides: Any
) -> dict[str, Any]:
    """Return a valid snapshot object from accounts and rows, top-level keys overridden."""
    declaration_date = overrides.get("declaration_date", DECLARATION_DATE)
    present = {a["account_type"] for a in accounts}
    types = [code for code in ACCOUNT_TYPE_ORDER if code in present]
    data: dict[str, Any] = {
        "snapshot_format": 1,
        "source": SOURCE,
        "start_page": START_PAGE,
        "retrieved_on": declaration_date,
        "declaration_date": declaration_date,
        "account_types": types,
        "licence_note": LICENCE_NOTE,
        "attribution": attribution_for(declaration_date),
        "no_endorsement": NO_ENDORSEMENT,
        "excel_files": [
            {
                "account_type": code,
                "name": f"synthetic_{code.lower()}.xls",
                "size_bytes": 2048,
                "sha256": fake_sha256(code),
            }
            for code in types
        ],
        "accounts": accounts,
        "rows": rows,
    }
    data.update(overrides)
    return copy.deepcopy(data)


def _amount_accounts(
    amounts: tuple[str, ...],
    asterisks: int,
    service_code: str,
    concept: str,
    *,
    account_type: str = "CNO",
    declaration_date: str = DECLARATION_DATE,
    first_entity: int = 9901,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return accounts with one amount each, then `asterisks` accounts with the asterisk."""
    accounts: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for i in range(len(amounts) + asterisks):
        acc = account(
            str(first_entity + i), account_type=account_type, declaration_date=declaration_date
        )
        accounts.append(acc)
        if i < len(amounts):
            rows.append(amount_row(acc, service_code, concept, amounts[i]))
        else:
            rows.append(asterisk_row(acc, service_code, concept))
    return accounts, rows


def synthetic_s12(**overrides: Any) -> dict[str, Any]:
    """S12 (synthetic): 15 CNO accounts, 12 amounts and 3 asterisks for service 101."""
    declaration_date = overrides.get("declaration_date", DECLARATION_DATE)
    accounts, rows = _amount_accounts(
        S12_AMOUNTS, 3, "101", MAINTENANCE_CONCEPT, declaration_date=declaration_date
    )
    return make_snapshot(accounts, rows, **overrides)


def synthetic_s10(**overrides: Any) -> dict[str, Any]:
    """S10 (synthetic): 10 CNO accounts, each with an amount for service 401."""
    declaration_date = overrides.get("declaration_date", DECLARATION_DATE)
    accounts, rows = _amount_accounts(
        S10_AMOUNTS, 0, "401", CARD_CONCEPT, declaration_date=declaration_date
    )
    return make_snapshot(accounts, rows, **overrides)


# --- Hypothesis strategy of valid snapshots (synthetic) ----------------------------------------

_CONCEPTS = (MAINTENANCE_CONCEPT, CARD_CONCEPT, PERIOD_CONCEPT, "Comisión de emisión (euros)")
_SERVICES = ("101", "201", "301", "401", "501", "603")
_AMOUNTS = st.decimals(min_value=Decimal("0.00"), max_value=Decimal("999.99"), places=2)


@st.composite
def _cell(draw: st.DrawFn) -> tuple[str, str | None, bool]:
    """Draw (text, amount, not_offered): an amount, the asterisk or a text without amount."""
    kind = draw(st.sampled_from(("amount", "amount", "asterisk", "text")))
    if kind == "amount":
        amount = str(abs(draw(_AMOUNTS)).quantize(Decimal("0.01")))
        return amount.replace(".", ","), amount, False
    if kind == "asterisk":
        return "*", None, True
    return draw(st.sampled_from(("ANUAL", "IMPORTE FIJO", "ND"))), None, False


@st.composite
def snapshot_strategy(draw: st.DrawFn) -> dict[str, Any]:
    """Draw a valid snapshot: 1 to 3 types, 1 to 6 accounts each, random cells (synthetic)."""
    types = draw(st.lists(st.sampled_from(ACCOUNT_TYPE_ORDER), min_size=1, max_size=3, unique=True))
    accounts: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for code in sorted(types, key=ACCOUNT_TYPE_ORDER.index):
        entities = draw(st.lists(st.integers(9901, 9910), min_size=1, max_size=6))
        counter: dict[int, int] = {}
        for entity in entities:
            counter[entity] = counter.get(entity, 0) + 1
            acc = account(str(entity), counter[entity], account_type=code)
            accounts.append(acc)
            services = draw(st.lists(st.sampled_from(_SERVICES), max_size=3, unique=True))
            for service in sorted(services):
                concepts = draw(st.lists(st.sampled_from(_CONCEPTS), max_size=2, unique=True))
                for concept in concepts:
                    text, amount, flag = draw(_cell())
                    rows.append(row(acc, service, concept, text, amount, flag))
    return make_snapshot(accounts, sort_rows(rows, accounts))
