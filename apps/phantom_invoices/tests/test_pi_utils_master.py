"""Tests for the supplier master and payment attribution (Task P6)."""

from typing import Any

import pandas as pd
from hypothesis import given, settings
from hypothesis import strategies as st

from apps.phantom_invoices.detectors.utils import (
    Master,
    attribute_payment,
    build_master,
    iban_key,
    name_key,
)
from apps.phantom_invoices.tests.pi_checkers import iban_check_digits, spanish_national_dc
from apps.phantom_invoices.tests.pi_strategies import dirty_cell

SUPPLIER_COLUMNS = ["supplier_name", "tax_id", "iban", "source_ref"]
AURORA = "Suministros García, S.L."
VALDEMAR = "Inmuebles Valdemar, S.L."


def _iban(account: str) -> str:
    """Return a compact IBAN with a valid mod-97 checksum and wrong national digits (Rule 5)."""
    correct = spanish_national_dc("2100", "0418", account)
    wrong = f"{(int(correct) + 11) % 100:02d}"
    bban = "21000418" + wrong + account
    return "ES" + iban_check_digits("ES", bban) + bban


def _spaced(iban: str) -> str:
    """Write a compact IBAN in groups of four, as a human would."""
    return " ".join(iban[i : i + 4] for i in range(0, len(iban), 4))


IBAN_1 = _iban("0000000001")
IBAN_2 = _iban("0000000002")
IBAN_3 = _iban("0000000003")

ROW_A = (AURORA, "B00000001", IBAN_1)
ROW_B = (VALDEMAR, "B00000002", IBAN_2)


def _suppliers(rows: list[tuple[Any, Any, Any]]) -> pd.DataFrame:
    """Build an object-dtype master frame; source_ref is 'sup.csv:<position>'."""
    records = [
        {"supplier_name": name, "tax_id": tax, "iban": iban, "source_ref": f"sup.csv:{i}"}
        for i, (name, tax, iban) in enumerate(rows)
    ]
    return pd.DataFrame(records, columns=SUPPLIER_COLUMNS, dtype=object)


def _payment(counterparty: Any = None, iban: Any = None) -> dict:
    """Return a minimal payment record."""
    return {"counterparty": counterparty, "iban": iban, "source_ref": "pay.csv:0"}


def _tax_of(row: dict | None) -> str | None:
    """Return the tax id of an attributed master row, or None."""
    return None if row is None else row["tax_id"]


# Tier 1: normal cases


def test_build_master_indexes_by_tax_name_and_iban() -> None:
    """The master is indexed by tax_key, name_key and iban_key."""
    rows = [(AURORA, "b-00000001", IBAN_1), (VALDEMAR, "B00000002", _spaced(IBAN_2))]

    master = build_master(_suppliers(rows))

    assert isinstance(master, Master)
    assert list(master.by_tax) == ["B00000001", "B00000002"]
    assert master.by_tax["B00000001"]["supplier_name"] == AURORA
    assert name_key(AURORA) == "SUMINISTROSGARCIASL"
    assert [r["tax_id"] for r in master.by_name["SUMINISTROSGARCIASL"]] == ["b-00000001"]
    assert [r["tax_id"] for r in master.by_iban[iban_key(IBAN_1)]] == ["b-00000001"]
    assert [r["tax_id"] for r in master.by_iban[IBAN_2]] == ["B00000002"]


def test_attribute_payment_by_name() -> None:
    """A payment whose counterparty has the same name_key belongs to that supplier."""
    master = build_master(_suppliers([ROW_A, ROW_B]))

    row = attribute_payment(_payment("SUMINISTROS GARCIA SL"), master)

    assert _tax_of(row) == "B00000001"


def test_attribute_payment_by_iban_when_name_unknown() -> None:
    """With an unknown name, a payment is attributed through the master IBAN."""
    master = build_master(_suppliers([ROW_A, ROW_B]))
    retyped = f"{IBAN_2[:4]} {IBAN_2[4:]}".lower()

    row = attribute_payment(_payment("Pago desconocido", retyped), master)

    assert _tax_of(row) == "B00000002"


def test_attribute_payment_name_first_even_if_iban_differs() -> None:
    """OD-PI-09: a payment to a known supplier sent to another account is still attributed."""
    master = build_master(_suppliers([ROW_A, ROW_B]))

    row = attribute_payment(_payment(AURORA, IBAN_2), master)

    assert _tax_of(row) == "B00000001"


# Tier 2: edge cases


def test_duplicate_tax_key_first_in_source_ref_order_wins() -> None:
    """A repeated tax_key keeps the row with the lowest source_ref, whatever the frame order."""
    frame = _suppliers([ROW_A, ("Otro nombre", "b 00000001", IBAN_2)])
    shuffled = frame.iloc[::-1].reset_index(drop=True)

    for source in (frame, shuffled):
        master = build_master(source)
        assert list(master.by_tax) == ["B00000001"]
        assert master.by_tax["B00000001"]["source_ref"] == "sup.csv:0"
        assert IBAN_2 not in master.by_iban
        assert name_key("Otro nombre") not in master.by_name


def test_master_row_with_empty_tax_key_is_not_a_supplier() -> None:
    """DN-12: a master row without a usable tax id is not a supplier and attributes nothing."""
    rows = [(AURORA, "-", IBAN_1), (VALDEMAR, None, IBAN_2), ("Tres", "/ /", IBAN_3)]

    master = build_master(_suppliers(rows))

    assert dict(master.by_tax) == {}
    assert dict(master.by_name) == {}
    assert dict(master.by_iban) == {}
    assert attribute_payment(_payment(AURORA, IBAN_1), master) is None


def test_name_hit_on_two_suppliers_falls_through_to_iban() -> None:
    """Two suppliers with the same name_key are ambiguous by name; the IBAN decides."""
    rows = [("Acme, S.L.", "B00000001", IBAN_1), ("ACME SL", "B00000002", IBAN_2)]
    master = build_master(_suppliers(rows))

    assert attribute_payment(_payment("acme sl"), master) is None
    assert _tax_of(attribute_payment(_payment("acme sl", IBAN_2), master)) == "B00000002"


def test_iban_hit_on_two_suppliers_is_unattributed() -> None:
    """Two suppliers sharing a master IBAN cannot be told apart by IBAN."""
    rows = [(AURORA, "B00000001", IBAN_1), (VALDEMAR, "B00000002", IBAN_1)]
    master = build_master(_suppliers(rows))

    assert attribute_payment(_payment("Pago desconocido", IBAN_1), master) is None


def test_unknown_name_and_unknown_iban_returns_none() -> None:
    """A payment of an unknown counterparty with an unknown IBAN is not a supplier payment."""
    master = build_master(_suppliers([ROW_A]))

    assert attribute_payment(_payment("Pago desconocido", IBAN_3), master) is None


def test_build_master_empty_none_and_non_frame() -> None:
    """Empty frames, None and non-frames give an empty master and never raise."""
    for source in (pd.DataFrame(), _suppliers([]), None, "not a frame", 3, {"a": 1}):
        master = build_master(source)
        assert dict(master.by_tax) == {}
        assert dict(master.by_name) == {}
        assert dict(master.by_iban) == {}
        assert attribute_payment(_payment(AURORA, IBAN_1), master) is None


def test_build_master_frame_without_source_ref_is_empty() -> None:
    """A row without a source_ref cannot be cited, so a frame without the column is empty."""
    frame = pd.DataFrame({"supplier_name": [AURORA], "tax_id": ["B00000001"], "iban": [IBAN_1]})

    assert dict(build_master(frame).by_tax) == {}


def test_attribute_payment_missing_cells() -> None:
    """Missing counterparty and IBAN cells attribute nothing and never raise."""
    master = build_master(_suppliers([ROW_A]))
    missing = (None, float("nan"), pd.NA, pd.NaT, "", " ", "\u00a0", "-", 7, 1.5)

    for cell in missing:
        assert attribute_payment(_payment(cell, cell), master) is None
    assert attribute_payment({}, master) is None


# Tier 3: property-based tests

_DIRTY_MASTER = build_master(_suppliers([ROW_A, ROW_B]))
_UNAMBIGUOUS_ROWS = [
    ("Aurora Uno, S.L.", "B00000001", _iban("0000000011")),
    ("Valdemar Dos, S.L.", "B00000002", _iban("0000000012")),
    ("Tres Cantos, S.L.", "B00000003", _iban("0000000013")),
    ("Delta Cuatro, S.L.", "B00000004", None),
]
_UNAMBIGUOUS_PAYMENTS = [
    _payment("AURORA UNO SL"),
    _payment("desconocido", _iban("0000000012")),
    _payment("Tres Cantos SL", _iban("0000000011")),
    _payment("Delta Cuatro SL", None),
    _payment("nadie", _iban("0000000099")),
]
_UNAMBIGUOUS_EXPECTED = ["B00000001", "B00000002", "B00000003", "B00000004", None]


@settings(max_examples=200, deadline=None)
@given(order=st.permutations([0, 1, 2, 3]))
def test_attribution_independent_of_master_row_order_when_unambiguous(order: list[int]) -> None:
    """Shuffling the master rows never changes who a payment is attributed to."""
    # Each row keeps its own source_ref, so only the physical order of the frame changes.
    frame = _suppliers(_UNAMBIGUOUS_ROWS).iloc[order].reset_index(drop=True)

    master = build_master(frame)

    attributed = [_tax_of(attribute_payment(p, master)) for p in _UNAMBIGUOUS_PAYMENTS]
    assert attributed == _UNAMBIGUOUS_EXPECTED


@settings(max_examples=200, deadline=None)
@given(counterparty=dirty_cell(), iban=dirty_cell())
def test_attribute_payment_never_raises_on_dirty_cells(counterparty: Any, iban: Any) -> None:
    """Any pair of dirty cells gives a master row or None, never an exception."""
    result = attribute_payment(_payment(counterparty, iban), _DIRTY_MASTER)

    assert result is None or result["tax_id"] in ("B00000001", "B00000002")
