"""Tests for scripts/import_bde_fees.py (public-fees PF8, amendment A1).

Every grid and record here is **synthetic**, built in the layout of Source fact 8 with invented
entities (9991 BANCO FICTICIO, 9992 CAJA DEMO); no row of a real Banco de España file is copied.
No .xls file is read: `read_grid` and `main` run against a fake `xlrd` module placed in
`sys.modules`, so these tests need neither the extra `import` nor the network.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import io
import json
import socket
import sys
import tomllib
import types
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ledger_kit.public_data import SERVICES, attribution_for, validate_fee_snapshot
from ledger_kit.public_data.bde_fees import (
    LICENCE_NOTE,
    NO_ENDORSEMENT,
    SNAPSHOT_KEYS,
    SOURCE,
    START_PAGE,
)

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "import_bde_fees.py"


def _load_script() -> Any:
    """Load scripts/import_bde_fees.py by path (scripts/ is not a package)."""
    spec = importlib.util.spec_from_file_location("import_bde_fees", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["import_bde_fees"] = module
    spec.loader.exec_module(module)
    return module


imp = _load_script()

# --- The synthetic layout (Source fact 8) ---

WIDTH = 25
FIRST_DATA_ROW = 14
PAD = " " * 40
CNO_TITLE = "COMPARACIÓN ENTRE ENTIDADES. COMISIONES DE CUENTAS DE PAGOS CUENTA NÓMINA/PENSIÓN"
COT_TITLE = "COMPARACIÓN ENTRE ENTIDADES. COMISIONES DE CUENTAS DE PAGOS OTRAS CUENTAS"
MAINTENANCE = "Mantenimiento de la cuenta"
CARD = "Emisión y mantenimiento de una tarjeta de débito"
ATM = "Retirada efectivo a débito mediante tarjeta en cajero"
MAINTENANCE_CONCEPT = "Comisión ANUAL total (euros)"
CARD_CONCEPT = "Comisión mantenimiento. ANUAL total (euros)"
ISSUE_CONCEPT = "Comisión de emisión (euros)"
CARD_PERIOD = "Comisión mantenimiento. Periodicidad."
LEGEND = "(*) No se cobra comisión/no se ofrece el servicio"

Cells = dict[tuple[int, int], Any]


def _account(cells: Cells, row: int, entity: tuple[str, str], account: str, *values: str) -> None:
    """Fill one account row: entity code and name, running number, name and the kept values."""
    code, name = entity
    cells[(row, 0)] = code
    cells[(row, 2)] = name
    cells[(row, 5)] = row - FIRST_DATA_ROW + 1  # an int: a number cell, as in the real files
    cells[(row, 6)] = account
    for col, text in zip((8, 10, 12, 15, 16, 17), values, strict=True):
        cells[(row, col)] = text
    # The cash-machine and overdraft blocks are filled too, but never kept (DN-PF-27).
    cells[(row, 18)] = "BANCO FICTICIO"
    cells[(row, 19)] = "*"
    cells[(row, 20)] = "CAJA DEMO"
    cells[(row, 21)] = "0,65"
    cells[(row, 22)] = "0,00"
    cells[(row, 23)] = "IMPORTE FIJO"
    cells[(row, 24)] = "*"


def base_cells() -> Cells:
    """A synthetic CNO file: entity 9991 with three accounts, entity 9992 with one."""
    cells: Cells = {
        (1, 11): "Fecha: 23/11/2026   8:06:35",
        (2, 4): "CSF - Comisiones y tipos de interés de los servicios financieros",
        (6, 4): CNO_TITLE + "   ",
        (8, 4): "Fecha de referencia: 23-11-2026",
        (12, 0): "SERVICIOS",
        (12, 6): "Proveedor de la Cuenta",
        (12, 8): MAINTENANCE + PAD,
        (12, 12): CARD,
        (12, 18): ATM,
        (12, 23): "Descubierto expreso",
        (12, 24): "Descubierto tácito",
        (13, 0): "CONCEPTOS\n" + LEGEND,
        (13, 6): "Nombre de la cuenta",
        (13, 8): "Periodicidad",
        (13, 10): MAINTENANCE_CONCEPT + "  ",
        (13, 12): "Marca comercial",
        (13, 15): ISSUE_CONCEPT,
        (13, 16): CARD_PERIOD,
        (13, 17): CARD_CONCEPT,
        (13, 18): "Entidad",
        (13, 19): "Importe (euros)",
        (13, 20): "Entidad",
        (13, 21): "Importe (euros)",
        (13, 22): "Porcentaje (%) comisión titular cajero",
        (13, 23): "Apertura",
        (13, 24): "Apertura",
    }
    bank = ("9991", "BANCO FICTICIO, S.A." + PAD)
    same = ("", "")
    card = ("VISA DEMO", "0,00", "ANUAL", "12,00")
    _account(cells, 14, bank, "CUENTA NÓMINA DEMO" + PAD, "ANUAL", "0,00", *card)
    _account(cells, 15, same, "CUENTA PENSIÓN DEMO", "ANUAL", "1.234,56", "*", "*", "*", "*" + PAD)
    _account(cells, 16, same, "CUENTA NÓMINA DEMO", "MENSUAL", "36,00", "", "", "", "")
    caja = ("9992", "CAJA DEMO")
    card = ("MC DEMO", "3,99", "ANUAL", "33,00")
    _account(cells, 17, caja, "CUENTA DEMO", "ANUAL", "240,00", *card)
    return cells


def make_grid(cells: Cells, height: int | None = None) -> Any:
    """Return the grid of `cells`: an int is a number cell, anything else a text cell."""
    rows = height if height is not None else max(r for r, _ in cells) + 1
    grid = []
    for r in range(rows):
        line = []
        for c in range(WIDTH):
            value = cells.get((r, c), "")
            if isinstance(value, int):
                line.append(imp.GridCell(str(value), number=True))
            else:
                line.append(imp.GridCell(value))
        grid.append(tuple(line))
    return tuple(grid)


def _renamed(cells: Cells, first: str, second: str, title: str = CNO_TITLE) -> Cells:
    """Return `cells` with two other synthetic entity codes and names, and a title."""
    out = dict(cells)
    out[(6, 4)] = title
    out[(14, 0)], out[(14, 2)] = first, f"BANCO DEMO {first}"
    out[(17, 0)], out[(17, 2)] = second, f"CAJA DEMO {second}"
    return out


def _parse_error(cells: Cells, message: str, account_type: str = "CNO") -> None:
    """Assert that parse_grid rejects `cells` with exactly `message`."""
    with pytest.raises(imp.ImporterError) as info:
        imp.parse_grid(make_grid(cells), account_type)
    assert str(info.value) == message


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail the test if anything tries to open a socket connection (decision Q6)."""

    def _blocked(*_args: Any, **_kwargs: Any) -> None:
        pytest.fail("a test of import_bde_fees tried to touch the network")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked)


# --- parse_grid: the layout ---


def test_parse_grid_reads_the_dates_the_title_and_the_accounts() -> None:
    parsed = imp.parse_grid(make_grid(base_cells()), "CNO")
    assert parsed.account_type == "CNO"
    assert (parsed.declaration_date, parsed.retrieved_on) == ("2026-11-23", "2026-11-23")
    assert parsed.title == CNO_TITLE
    assert [(r.entity_code, r.entity_name, r.account_name) for r in parsed.records] == [
        ("9991", "BANCO FICTICIO, S.A.", "CUENTA NÓMINA DEMO"),
        ("9991", "BANCO FICTICIO, S.A.", "CUENTA PENSIÓN DEMO"),
        ("9991", "BANCO FICTICIO, S.A.", "CUENTA NÓMINA DEMO"),
        ("9992", "CAJA DEMO", "CUENTA DEMO"),
    ]
    assert {r.account_type for r in parsed.records} == {"CNO"}


def test_parse_grid_keeps_the_cells_of_services_101_and_401_in_column_order() -> None:
    first = imp.parse_grid(make_grid(base_cells()), "CNO").records[0]
    assert [(c.service_label, c.concept, c.text) for c in first.cells] == [
        (MAINTENANCE, "Periodicidad", "ANUAL"),
        (MAINTENANCE, MAINTENANCE_CONCEPT, "0,00"),
        (CARD, "Marca comercial", "VISA DEMO"),
        (CARD, ISSUE_CONCEPT, "0,00"),
        (CARD, CARD_PERIOD, "ANUAL"),
        (CARD, CARD_CONCEPT, "12,00"),
    ]


def test_parse_grid_does_not_keep_the_cash_machine_and_overdraft_blocks() -> None:
    records = imp.parse_grid(make_grid(base_cells()), "CNO").records
    assert {c.service_label for r in records for c in r.cells} == {MAINTENANCE, CARD}
    assert not any(c.concept in ("Entidad", "Importe (euros)") for r in records for c in r.cells)


def test_parse_grid_keeps_texts_as_written_and_leaves_out_empty_cells() -> None:
    records = imp.parse_grid(make_grid(base_cells()), "CNO").records
    assert records[1].cells[-1].text == "*" + PAD
    assert [c.concept for c in records[2].cells] == ["Periodicidad", MAINTENANCE_CONCEPT]


def test_parse_grid_takes_the_generation_date_from_the_fecha_cell() -> None:
    cells = base_cells()
    cells[(1, 11)] = "Fecha: 24/11/2026  9:00:00"
    parsed = imp.parse_grid(make_grid(cells), "CNO")
    assert (parsed.declaration_date, parsed.retrieved_on) == ("2026-11-23", "2026-11-24")


def test_parse_grid_reads_a_fecha_cell_without_a_time() -> None:
    cells = base_cells()
    cells[(1, 11)] = "Fecha: 25/11/2026"
    assert imp.parse_grid(make_grid(cells), "CNO").retrieved_on == "2026-11-25"


def test_parse_grid_reads_a_cot_file() -> None:
    cells = base_cells()
    cells[(6, 4)] = COT_TITLE
    parsed = imp.parse_grid(make_grid(cells), "COT")
    assert {r.account_type for r in parsed.records} == {"COT"}


def test_a_value_in_a_spacer_column_is_not_read() -> None:
    cells = base_cells()
    cells[(14, 9)] = "SPACER TEXT"
    first = imp.parse_grid(make_grid(cells), "CNO").records[0]
    assert "SPACER TEXT" not in [c.text for c in first.cells]


def test_a_number_cell_outside_the_kept_blocks_is_accepted() -> None:
    cells = base_cells()
    cells[(14, 19)] = 3
    assert len(imp.parse_grid(make_grid(cells), "CNO").records) == 4


def test_blank_rows_are_skipped() -> None:
    assert len(imp.parse_grid(make_grid(base_cells(), height=22), "CNO").records) == 4


def test_columns_are_found_by_header_text_not_by_position() -> None:
    cells = base_cells()
    # Move the overdraft labels one column right, as a longer cash-machine block would.
    cells[(12, 23)], cells[(12, 24)] = "", "Descubierto expreso"
    assert len(imp.parse_grid(make_grid(cells), "CNO").records) == 4


# --- parse_grid: every layout error ---


def _with(**changes: Any) -> Cells:
    """Return base_cells() with cells set; keys are 'r_c', a None value removes the cell."""
    cells = base_cells()
    for key, value in changes.items():
        row, col = (int(part) for part in key.lstrip("_").split("_"))
        if value is None:
            cells.pop((row, col), None)
        else:
            cells[(row, col)] = value
    return cells


@pytest.mark.parametrize(
    ("cells", "message"),
    [
        (_with(_12_0="SERVICIO"), "no SERVICIOS header row in the CNO file"),
        (_with(_3_0="SERVICIOS"), "two SERVICIOS header rows in the CNO file"),
        (
            _with(_13_0="CONCEPT"),
            "the row after SERVICIOS does not start with CONCEPTOS in the CNO file",
        ),
        (
            _with(_13_0="CONCEPTOS"),
            f"the asterisk legend {LEGEND!r} is missing in the CNO file",
        ),
        (
            _with(_8_4=None),
            "no 'Fecha de referencia:' cell above the table of the CNO file",
        ),
        (_with(_1_11=None), "no 'Fecha:' cell above the table of the CNO file"),
        (
            _with(_1_12="Fecha: 22/11/2026"),
            "two 'Fecha:' cells above the table of the CNO file",
        ),
        (
            _with(_8_4="Fecha de referencia: 31-02-2026"),
            "invalid date in 'Fecha de referencia: 31-02-2026' of the CNO file",
        ),
        (
            _with(_6_4=None),
            "no title starting with 'COMPARACIÓN ENTRE ENTIDADES' in the CNO file",
        ),
        (
            _with(_6_4=COT_TITLE),
            "the title of the CNO file names account type COT, not CNO",
        ),
        (
            _with(_12_23="Servicio inventado"),
            "unknown service label 'Servicio inventado' in CNO file",
        ),
        (
            _with(_12_24="Descubierto expreso"),
            "service label 'Descubierto expreso' appears twice in the CNO file",
        ),
        (
            _with(_12_6=None),
            "no 'Proveedor de la Cuenta' block with 'Nombre de la cuenta' in the CNO file",
        ),
        (_with(_12_12=None), "no block for service 401 in the CNO file"),
        (
            # The screen spelling is not the Excel spelling (DN-PF-28): the import fails.
            _with(_13_10="Comisión anual total (euros)"),
            "service 101 of the CNO file has no concept 'Comisión ANUAL total (euros)'",
        ),
        (
            _with(_13_17="Comisión mantenimiento. Anual total (euros)"),
            "service 401 of the CNO file has no concept "
            "'Comisión mantenimiento. ANUAL total (euros)'",
        ),
        (
            _with(_13_9="Periodicidad"),
            "concept 'Periodicidad' appears twice in service 101 of the CNO file",
        ),
        (
            _with(_14_10=0),
            "number cell at row 14 column 10 in service 101 of the CNO file",
        ),
        (
            _with(_15_17=12),
            "number cell at row 15 column 17 in service 401 of the CNO file",
        ),
        (
            _with(_15_6=7),
            "number cell at row 15 column 6 in 'Proveedor de la Cuenta' of the CNO file",
        ),
        (
            _with(_14_0="", _14_2=""),
            "account at row 14 of the CNO file has no entity",
        ),
        (
            _with(_15_2="OTRO BANCO DEMO"),
            "account at row 15 of the CNO file has an entity name but no code",
        ),
        (_with(_14_0="991"), "invalid entity code '991' at row 14 of the CNO file"),
        (_with(_17_2=""), "entity 9992 at row 17 of the CNO file has no name"),
        (_with(_17_0="9991"), "entity 9991 appears twice in the CNO file"),
        (
            _with(_16_6="   "),
            "account at row 16 of the CNO file has no 'Nombre de la cuenta'",
        ),
    ],
)
def test_parse_grid_rejects(cells: Cells, message: str) -> None:
    _parse_error(cells, message)


def test_a_title_naming_no_known_type() -> None:
    title = "COMPARACIÓN ENTRE ENTIDADES. COMISIONES DE CUENTAS DE PAGOS CUENTA INVENTADA"
    _parse_error(
        _with(_6_4=title),
        f"the title of the CNO file names no known account type: {title!r}",
    )


def test_a_cno_title_given_as_cot() -> None:
    message = "the title of the COT file names account type CNO, not COT"
    _parse_error(base_cells(), message, "COT")


def test_a_file_without_accounts() -> None:
    cells = {key: value for key, value in base_cells().items() if key[0] < FIRST_DATA_ROW}
    _parse_error(cells, "no account in the CNO file")


# --- build_snapshot ---


def _sha(label: str) -> str:
    """Return a synthetic SHA-256 for one file entry."""
    return hashlib.sha256(f"synthetic xls {label}".encode()).hexdigest()


def _meta(*kinds: str, declaration: str = "2026-11-23", retrieved: str = "2026-11-23") -> Any:
    """Return a Meta with one synthetic file entry per type given (CNO by default)."""
    files = tuple(
        {
            "account_type": kind,
            "name": "CompararEntidadesCCP.xls",
            "size_bytes": 4096,
            "sha256": _sha(f"{kind} {index}"),
        }
        for index, kind in enumerate(kinds or ("CNO",))
    )
    return imp.Meta(declaration, retrieved, files)


def _record(
    cells: tuple[tuple[str, str, str], ...] = (),
    entity: str = "9991",
    account: str = "CUENTA DEMO",
    account_type: str = "CNO",
) -> Any:
    """Return one synthetic record; cells are (service label, concept, text)."""
    name = "BANCO FICTICIO" if entity == "9991" else f"ENTIDAD DEMO {entity}"
    return imp.Record(
        account_type,
        entity,
        name,
        account,
        tuple(imp.Cell(*cell) for cell in cells),
    )


def _one_row(text: str, concept: str = MAINTENANCE_CONCEPT, label: str = MAINTENANCE) -> dict:
    """Return the only row of a snapshot built from one cell."""
    snapshot = imp.build_snapshot([_record(((label, concept, text),))], _meta())
    [row] = snapshot["rows"]
    return row


def _build_error(records: list[Any], message: str, meta: Any = None) -> None:
    """Assert that build_snapshot rejects the records with exactly `message`."""
    with pytest.raises(imp.ImporterError) as info:
        imp.build_snapshot(records, meta or _meta())
    assert str(info.value) == message


def test_the_parsed_file_builds_a_valid_snapshot() -> None:
    parsed = imp.parse_grid(make_grid(base_cells()), "CNO")
    snapshot = imp.build_snapshot(parsed.records, _meta())
    validate_fee_snapshot(snapshot)
    keys = [a["account_key"] for a in snapshot["accounts"]]
    assert keys == ["9991-01", "9991-02", "9991-03", "9992-01"]
    assert snapshot["accounts"][0]["entity_name"] == "BANCO FICTICIO, S.A."
    assert snapshot["accounts"][0]["account_name"] == "CUENTA NÓMINA DEMO"
    assert len(snapshot["rows"]) == 20
    rows = {(r["account_key"], r["service_code"], r["concept"]): r for r in snapshot["rows"]}
    assert rows[("9991-02", "101", MAINTENANCE_CONCEPT)]["amount"] == "1234.56"
    assert rows[("9991-02", "401", CARD_CONCEPT)] == {
        "account_type": "CNO",
        "account_key": "9991-02",
        "service_code": "401",
        "concept": CARD_CONCEPT,
        "text": "*",
        "amount": None,
        "not_offered": True,
    }
    assert rows[("9992-01", "401", ISSUE_CONCEPT)]["amount"] == "3.99"
    assert rows[("9991-01", "101", "Periodicidad")]["amount"] is None
    card_rows = [r for r in snapshot["rows"] if r["service_code"] == "401"]
    assert "9991-03" not in {r["account_key"] for r in card_rows}


def test_the_snapshot_carries_the_constants() -> None:
    snapshot = imp.build_snapshot([_record()], _meta(retrieved="2026-11-24"))
    assert list(snapshot) == list(SNAPSHOT_KEYS)
    assert snapshot["snapshot_format"] == 1
    assert (snapshot["source"], snapshot["start_page"]) == (SOURCE, START_PAGE)
    assert snapshot["licence_note"] == LICENCE_NOTE
    assert snapshot["no_endorsement"] == NO_ENDORSEMENT
    assert snapshot["attribution"] == attribution_for("2026-11-23")
    assert (snapshot["declaration_date"], snapshot["retrieved_on"]) == ("2026-11-23", "2026-11-24")
    assert snapshot["account_types"] == ["CNO"]


@pytest.mark.parametrize(
    ("text", "amount"),
    [
        ("3,99", "3.99"),
        ("33,00", "33.00"),
        ("1.234,56", "1234.56"),
        ("0,00", "0.00"),
        ("12.345.678,90", "12345678.90"),
    ],
)
def test_euro_amounts_become_decimal_strings(text: str, amount: str) -> None:
    row = _one_row(text)
    assert (row["text"], row["amount"], row["not_offered"]) == (text, amount, False)


def test_the_asterisk_with_trailing_spaces() -> None:
    row = _one_row("*" + PAD)
    assert (row["text"], row["amount"], row["not_offered"]) == ("*", None, True)


def test_nbsp_padding_is_trimmed() -> None:
    row = _one_row("\u00a06,50\u00a0 ", label="  Mantenimiento de la cuenta\u00a0  ")
    assert (row["service_code"], row["text"], row["amount"]) == ("101", "6,50", "6.50")


def test_a_euro_concept_with_a_word_is_kept_as_text() -> None:
    row = _one_row("ND")
    assert (row["text"], row["amount"], row["not_offered"]) == ("ND", None, False)


def test_a_concept_that_is_not_in_euros_keeps_only_its_text() -> None:
    row = _one_row("12,00", concept="Periodicidad")
    assert (row["text"], row["amount"]) == ("12,00", None)


def test_an_unknown_service_label() -> None:
    record = _record((("Servicio inventado", MAINTENANCE_CONCEPT, "1,00"),))
    _build_error([record], "unknown service label 'Servicio inventado' in CNO file")


def test_an_amount_with_three_decimals() -> None:
    record = _record(((MAINTENANCE, MAINTENANCE_CONCEPT, "3,999"),))
    _build_error([record], "amount '3,999' of CNO 9991-01 service 101 has more than two decimals")


@pytest.mark.parametrize("text", ["6,5", "-1,00", "1.23,00", "240", "1,234.56"])
def test_a_number_that_is_not_a_euro_amount(text: str) -> None:
    record = _record(((MAINTENANCE, MAINTENANCE_CONCEPT, text),))
    message = f"amount {text!r} of CNO 9991-01 service 101 is not a euro amount with two decimals"
    _build_error([record], message)


def test_account_keys_count_within_each_entity() -> None:
    records = [
        _record(entity="9991", account="CUENTA DEMO"),
        _record(entity="9991", account="CUENTA DEMO"),
        _record(entity="9992"),
        _record(entity="9991", account="CUENTA JOVEN DEMO"),
    ]
    snapshot = imp.build_snapshot(records, _meta())
    keys = [(a["account_key"], a["account_name"]) for a in snapshot["accounts"]]
    assert keys == [
        ("9991-01", "CUENTA DEMO"),
        ("9991-02", "CUENTA DEMO"),
        ("9991-03", "CUENTA JOVEN DEMO"),
        ("9992-01", "CUENTA DEMO"),
    ]


def test_an_account_without_cells_is_kept() -> None:
    snapshot = imp.build_snapshot([_record()], _meta())
    assert len(snapshot["accounts"]) == 1
    assert snapshot["rows"] == []


def test_rows_follow_the_order_of_req_pf_01() -> None:
    records = [
        _record(((CARD, CARD_CONCEPT, "30,00"),), entity="9992"),
        _record(
            (
                (CARD, CARD_CONCEPT, "12,00"),
                (MAINTENANCE, MAINTENANCE_CONCEPT, "0,00"),
                (MAINTENANCE, "Periodicidad", "ANUAL"),
            ),
        ),
    ]
    snapshot = imp.build_snapshot(records, _meta())
    order = [(r["account_key"], r["service_code"], r["concept"]) for r in snapshot["rows"]]
    assert order == [
        ("9991-01", "101", MAINTENANCE_CONCEPT),
        ("9991-01", "101", "Periodicidad"),
        ("9991-01", "401", CARD_CONCEPT),
        ("9992-01", "401", CARD_CONCEPT),
    ]


def test_several_files_for_one_type() -> None:
    snapshot = imp.build_snapshot([_record()], _meta("CNO", "CNO"))
    assert [e["account_type"] for e in snapshot["excel_files"]] == ["CNO", "CNO"]
    assert {e["name"] for e in snapshot["excel_files"]} == {"CompararEntidadesCCP.xls"}


def test_excel_files_follow_the_type_order() -> None:
    records = [_record(account_type="COT"), _record()]
    snapshot = imp.build_snapshot(records, _meta("COT", "CNO"))
    assert [e["account_type"] for e in snapshot["excel_files"]] == ["CNO", "COT"]
    assert snapshot["account_types"] == ["CNO", "COT"]


def test_a_concept_twice_in_one_record() -> None:
    cell = (MAINTENANCE, MAINTENANCE_CONCEPT, "0,00")
    message = f"duplicate concept {MAINTENANCE_CONCEPT!r} of CNO 9991-01 service 101"
    _build_error([_record((cell, cell))], message)


def test_an_entity_code_that_is_not_four_digits() -> None:
    _build_error([_record(entity="49")], "invalid entity code '49' in CNO file")


def test_no_records() -> None:
    _build_error([], "no account to import")


def test_a_failed_validator_check() -> None:
    meta = _meta(retrieved="2026-11-20")
    reason = "retrieved_on 2026-11-20 is before declaration_date 2026-11-23"
    _build_error([_record()], f"snapshot check failed: {reason}", meta)


# --- build_snapshot: round trip (Hypothesis) ---

_LABELS = {"101": SERVICES["101"], "401": SERVICES["401"]}
_CONCEPTS = {
    "101": ("Periodicidad", MAINTENANCE_CONCEPT),
    "401": ("Marca comercial", ISSUE_CONCEPT, CARD_CONCEPT),
}


def _published(value: Decimal) -> str:
    """Return a two-decimal amount as the comparator publishes it, e.g. '1.234,56'."""
    whole, cents = f"{abs(value):.2f}".split(".")
    return f"{int(whole):,}".replace(",", ".") + "," + cents


_AMOUNTS = st.decimals(min_value=Decimal("0"), max_value=Decimal("99999.99"), places=2)
_TEXTS = st.one_of(
    _AMOUNTS.map(_published),
    st.sampled_from(("*", "*" + PAD, "ANUAL", "ND", "IMPORTE FIJO", "VISA DEMO")),
)


@st.composite
def _records(draw: st.DrawFn) -> list[Any]:
    """Draw 1 to 8 synthetic records of CNO and COT with random kept cells."""
    records = []
    for _ in range(draw(st.integers(min_value=1, max_value=8))):
        entity = draw(st.sampled_from(("9991", "9992", "9993")))
        kind = draw(st.sampled_from(("CNO", "COT")))
        cells = []
        for code in draw(st.lists(st.sampled_from(("101", "401")), unique=True)):
            for concept in draw(st.lists(st.sampled_from(_CONCEPTS[code]), unique=True)):
                cells.append((_LABELS[code], concept, draw(_TEXTS)))
        records.append(_record(tuple(cells), entity=entity, account_type=kind))
    return records


@settings(max_examples=200)
@given(records=_records())
def test_build_snapshot_round_trip(records: list[Any]) -> None:
    kinds = [k for k in ("CNO", "COT") if any(r.account_type == k for r in records)]
    snapshot = imp.build_snapshot(records, _meta(*kinds))
    validate_fee_snapshot(snapshot)
    assert len(snapshot["accounts"]) == len(records)
    assert len(snapshot["rows"]) == sum(len(r.cells) for r in records)
    for row in snapshot["rows"]:
        assert row["text"] == row["text"].strip()
        assert row["not_offered"] == (row["text"] == "*")
        if row["amount"] is not None:
            assert row["amount"] == row["text"].replace(".", "").replace(",", ".")
    assert imp.build_snapshot(records, _meta(*kinds)) == snapshot


# --- file_facts ---


def test_file_facts(tmp_path: Path) -> None:
    path = tmp_path / "CompararEntidadesCCP.xls"
    content = b"synthetic bytes, not an Excel file" * 100
    path.write_bytes(content)
    assert imp.file_facts(path, "CNO") == {
        "account_type": "CNO",
        "name": "CompararEntidadesCCP.xls",
        "size_bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def test_file_facts_of_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(imp.ImporterError, match="^cannot read "):
        imp.file_facts(tmp_path / "missing.xls", "CNO")


# --- read_grid with a fake xlrd ---

EMPTY, TEXT, NUMBER, DATE, BOOLEAN, ERROR, BLANK = range(7)


class _FakeSheet:
    """A sheet of the fake xlrd: rows of (cell type, value)."""

    def __init__(self, cells: list[list[tuple[int, Any]]]) -> None:
        self._cells = cells
        self.nrows = len(cells)
        self.ncols = max((len(row) for row in cells), default=0)

    def cell_type(self, row: int, col: int) -> int:
        return self._cells[row][col][0]

    def cell_value(self, row: int, col: int) -> Any:
        return self._cells[row][col][1]


class _FakeBook:
    """A workbook of the fake xlrd with one sheet."""

    def __init__(self, sheet: _FakeSheet) -> None:
        self._sheet = sheet

    def sheet_by_index(self, index: int) -> _FakeSheet:
        assert index == 0
        return self._sheet


def _fake_xlrd(books: dict[str, list[list[tuple[int, Any]]]], calls: list) -> types.ModuleType:
    """Return a module shaped like xlrd 2.0.1 that serves `books` by file name."""
    module = types.ModuleType("xlrd")
    module.XL_CELL_EMPTY = EMPTY
    module.XL_CELL_TEXT = TEXT
    module.XL_CELL_NUMBER = NUMBER
    module.XL_CELL_DATE = DATE
    module.XL_CELL_BOOLEAN = BOOLEAN
    module.XL_CELL_ERROR = ERROR
    module.XL_CELL_BLANK = BLANK

    class XLRDError(Exception):
        """The error class of the fake xlrd."""

    def open_workbook(filename: str, logfile: Any = sys.stdout, **kwargs: Any) -> _FakeBook:
        calls.append((filename, logfile, kwargs))
        # The real xlrd writes this warning for the BdE files (Source fact 8).
        print("WARNING *** file size (212929) not 512 + multiple of sector size", file=logfile)
        if filename not in books:
            raise XLRDError("Unsupported format, or corrupt file")
        return _FakeBook(_FakeSheet(books[filename]))

    module.XLRDError = XLRDError
    module.open_workbook = open_workbook
    return module


def _fake_cells(grid: Any) -> list[list[tuple[int, Any]]]:
    """Return the fake xlrd cells of a grid: a number cell holds a float, as in xlrd."""
    out = []
    for line in grid:
        row = []
        for cell in line:
            if cell.number:
                row.append((NUMBER, float(cell.text)))
            elif cell.text:
                row.append((TEXT, cell.text))
            else:
                row.append((EMPTY, ""))
        out.append(row)
    return out


@pytest.fixture
def books(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[list[tuple[int, Any]]]]:
    """Install a fake xlrd in sys.modules and return its file-name -> cells table."""
    table: dict[str, list[list[tuple[int, Any]]]] = {}
    calls: list = []
    monkeypatch.setitem(sys.modules, "xlrd", _fake_xlrd(table, calls))
    table["__calls__"] = calls  # type: ignore[assignment]
    return table


def _xls(tmp_path: Path, folder: str = "nomina_pension", content: bytes | None = None) -> Path:
    """Write a synthetic stand-in for one export (every export has the same name)."""
    path = tmp_path / "downloads" / folder / "CompararEntidadesCCP.xls"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content if content is not None else f"synthetic {folder}".encode())
    return path


def test_read_grid_returns_every_cell_as_text(
    tmp_path: Path, books: dict, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _xls(tmp_path)
    books[str(path)] = [
        [(TEXT, "SERVICIOS   "), (EMPTY, ""), (BLANK, ""), (NUMBER, 7.0)],
        [(TEXT, "9991"), (TEXT, "*" + PAD), (NUMBER, 12.0), (TEXT, "0,00")],
    ]
    grid = imp.read_grid(path)
    assert grid == (
        (
            imp.GridCell("SERVICIOS   "),
            imp.GridCell(""),
            imp.GridCell(""),
            imp.GridCell("7", True),
        ),
        (
            imp.GridCell("9991"),
            imp.GridCell("*" + PAD),
            imp.GridCell("12", True),
            imp.GridCell("0,00"),
        ),
    )
    [(filename, logfile, _kwargs)] = books["__calls__"]
    assert filename == str(path)
    assert isinstance(logfile, io.StringIO)
    assert "WARNING" in logfile.getvalue()
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    "cell", [(NUMBER, 2.5), (DATE, 46349.0), (BOOLEAN, 1), (ERROR, 42)], ids=str
)
def test_read_grid_rejects_a_cell_that_is_not_text_or_a_whole_number(
    tmp_path: Path, books: dict, cell: tuple[int, Any]
) -> None:
    path = _xls(tmp_path)
    books[str(path)] = [[(TEXT, "x"), cell]]
    with pytest.raises(imp.ImporterError) as info:
        imp.read_grid(path)
    assert str(info.value) == (
        f"cannot read {path}: cell at row 0 column 1 is not text or a whole number"
    )


def test_read_grid_of_a_missing_file(tmp_path: Path, books: dict) -> None:
    path = tmp_path / "missing.xls"
    with pytest.raises(imp.ImporterError) as info:
        imp.read_grid(path)
    assert str(info.value) == f"cannot read {path}: file not found"


def test_read_grid_reports_an_xlrd_error(tmp_path: Path, books: dict) -> None:
    path = _xls(tmp_path)
    with pytest.raises(imp.ImporterError) as info:
        imp.read_grid(path)
    assert str(info.value) == f"cannot read {path}: Unsupported format, or corrupt file"


def test_read_grid_without_xlrd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "xlrd", None)
    path = _xls(tmp_path)
    with pytest.raises(imp.ImporterError) as info:
        imp.read_grid(path)
    assert str(info.value) == (
        f'cannot read {path}: xlrd is not installed (pip install -e ".[import]")'
    )


# --- main ---


def _export(
    tmp_path: Path, books: dict, cells: Cells, folder: str, content: bytes | None = None
) -> Path:
    """Write one synthetic export and register its grid with the fake xlrd."""
    path = _xls(tmp_path, folder, content)
    books[str(path)] = _fake_cells(make_grid(cells))
    return path


def _main(
    capsys: pytest.CaptureFixture[str], out: Path, *pairs: str, extra: tuple[str, ...] = ()
) -> tuple[int, str, str]:
    """Run main with --declaration-date 2026-11-23, the --excel / --expect pairs and --output."""
    argv = ["--declaration-date", "2026-11-23", *pairs, "--output", str(out), *extra]
    code = imp.main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _fails(result: tuple[int, str, str], out: Path, line: str) -> None:
    """Assert exit code 1, nothing on stdout, exactly one error line and no snapshot."""
    code, stdout, stderr = result
    assert (code, stdout) == (1, "")
    assert stderr == f"error: {line}\n"
    assert not out.exists()


def test_main_writes_the_snapshot(
    tmp_path: Path, books: dict, capsys: pytest.CaptureFixture[str]
) -> None:
    cells = base_cells()
    cells[(1, 11)] = "Fecha: 24/11/2026   8:06:35"
    path = _export(tmp_path, books, cells, "nomina_pension")
    out = tmp_path / "public" / "bde_payment_account_fees.json"
    pairs = ("--excel", f"CNO={path}", "--expect-entities", "CNO=2")
    code, stdout, stderr = _main(capsys, out, *pairs)
    assert (code, stderr) == (0, "")
    assert stdout == f"wrote {out}: 4 accounts, 20 rows, types CNO\n"
    raw = out.read_bytes()
    assert b"\r\n" not in raw
    assert raw.endswith(b"}\n")
    assert "NÓMINA".encode() in raw  # UTF-8, ensure_ascii=False
    data = json.loads(raw.decode("utf-8"))
    validate_fee_snapshot(data)
    assert (data["declaration_date"], data["retrieved_on"]) == ("2026-11-23", "2026-11-24")
    assert data["excel_files"] == [imp.file_facts(path, "CNO")]
    assert sorted(p.name for p in out.parent.iterdir()) == [out.name]


def test_main_with_several_files_and_types(
    tmp_path: Path, books: dict, capsys: pytest.CaptureFixture[str]
) -> None:
    cno = _export(tmp_path, books, base_cells(), "nomina_pension")
    cot_a = _export(tmp_path, books, _renamed(base_cells(), "9993", "9994", COT_TITLE), "otras_1")
    cot_b = _export(tmp_path, books, _renamed(base_cells(), "9995", "9996", COT_TITLE), "otras_2")
    out = tmp_path / "public" / "fees.json"
    pairs = (
        "--excel",
        f"COT={cot_a}",
        "--excel",
        f"CNO={cno}",
        "--excel",
        f"COT={cot_b}",
        "--expect-entities",
        "CNO=2",
        "--expect-entities",
        "COT=4",
    )
    code, stdout, stderr = _main(capsys, out, *pairs)
    assert (code, stderr) == (0, "")
    assert stdout == f"wrote {out}: 12 accounts, 60 rows, types CNO, COT\n"
    data = json.loads(out.read_text(encoding="utf-8"))
    files = [(e["account_type"], e["sha256"]) for e in data["excel_files"]]
    assert files == [
        ("CNO", imp.file_facts(cno, "CNO")["sha256"]),
        ("COT", imp.file_facts(cot_a, "COT")["sha256"]),
        ("COT", imp.file_facts(cot_b, "COT")["sha256"]),
    ]
    assert {e["name"] for e in data["excel_files"]} == {"CompararEntidadesCCP.xls"}
    cot_keys = [a["account_key"] for a in data["accounts"] if a["account_type"] == "COT"]
    assert cot_keys[:3] == ["9993-01", "9993-02", "9993-03"]
    assert data["account_types"] == ["CNO", "COT"]


def test_main_missing_file(tmp_path: Path, books: dict, capsys: pytest.CaptureFixture[str]) -> None:
    missing = tmp_path / "missing.xls"
    out = tmp_path / "out.json"
    result = _main(capsys, out, "--excel", f"CNO={missing}", "--expect-entities", "CNO=2")
    _fails(result, out, f"cannot read {missing}: file not found")


def test_main_unknown_service_label(
    tmp_path: Path, books: dict, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _export(tmp_path, books, _with(_12_23="Servicio inventado"), "a")
    out = tmp_path / "out.json"
    result = _main(capsys, out, "--excel", f"CNO={path}", "--expect-entities", "CNO=2")
    _fails(result, out, "unknown service label 'Servicio inventado' in CNO file")


def test_main_three_decimals(
    tmp_path: Path, books: dict, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _export(tmp_path, books, _with(_14_10="3,999"), "a")
    out = tmp_path / "out.json"
    result = _main(capsys, out, "--excel", f"CNO={path}", "--expect-entities", "CNO=2")
    _fails(result, out, "amount '3,999' of CNO 9991-01 service 101 has more than two decimals")


def test_main_title_of_another_type(
    tmp_path: Path, books: dict, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _export(tmp_path, books, _with(_6_4=COT_TITLE), "a")
    out = tmp_path / "out.json"
    result = _main(capsys, out, "--excel", f"CNO={path}", "--expect-entities", "CNO=2")
    _fails(result, out, "the title of the CNO file names account type COT, not CNO")


def test_main_declaration_dates_that_differ(
    tmp_path: Path, books: dict, capsys: pytest.CaptureFixture[str]
) -> None:
    first = _export(tmp_path, books, base_cells(), "a")
    other = _renamed(_with(_8_4="Fecha de referencia: 22-11-2026"), "9993", "9994")
    second = _export(tmp_path, books, other, "b")
    out = tmp_path / "out.json"
    pairs = ("--excel", f"CNO={first}", "--excel", f"CNO={second}", "--expect-entities", "CNO=4")
    result = _main(capsys, out, *pairs)
    _fails(result, out, "the files give two declaration dates: 2026-11-23 and 2026-11-22")


def test_main_generation_dates_that_differ(
    tmp_path: Path, books: dict, capsys: pytest.CaptureFixture[str]
) -> None:
    first = _export(tmp_path, books, base_cells(), "a")
    other = _renamed(_with(_1_11="Fecha: 24/11/2026   9:15:00"), "9993", "9994")
    second = _export(tmp_path, books, other, "b")
    out = tmp_path / "out.json"
    pairs = ("--excel", f"CNO={first}", "--excel", f"CNO={second}", "--expect-entities", "CNO=4")
    result = _main(capsys, out, *pairs)
    _fails(result, out, "the files give two generation dates: 2026-11-23 and 2026-11-24")


def test_main_declaration_date_argument_that_differs(
    tmp_path: Path, books: dict, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _export(tmp_path, books, base_cells(), "a")
    out = tmp_path / "out.json"
    argv = [
        "--declaration-date",
        "2026-11-24",
        "--excel",
        f"CNO={path}",
        "--expect-entities",
        "CNO=2",
        "--output",
        str(out),
    ]
    code = imp.main(argv)
    captured = capsys.readouterr()
    _fails(
        (code, captured.out, captured.err),
        out,
        "--declaration-date 2026-11-24 differs from the date of the files (2026-11-23)",
    )


def test_main_entity_in_two_files(
    tmp_path: Path, books: dict, capsys: pytest.CaptureFixture[str]
) -> None:
    cot = _renamed(base_cells(), "9991", "9992", COT_TITLE)
    first = _export(tmp_path, books, cot, "otras_1")
    second = _export(tmp_path, books, _renamed(cot, "9993", "9991", COT_TITLE), "otras_2")
    out = tmp_path / "out.json"
    pairs = ("--excel", f"COT={first}", "--excel", f"COT={second}", "--expect-entities", "COT=3")
    result = _main(capsys, out, *pairs)
    _fails(result, out, f"entity 9991 is in two COT files: {first} and {second}")


def test_main_same_file_twice(
    tmp_path: Path, books: dict, capsys: pytest.CaptureFixture[str]
) -> None:
    first = _export(tmp_path, books, base_cells(), "a", b"same synthetic bytes")
    other = _renamed(base_cells(), "9993", "9994")
    second = _export(tmp_path, books, other, "b", b"same synthetic bytes")
    out = tmp_path / "out.json"
    pairs = ("--excel", f"CNO={first}", "--excel", f"CNO={second}", "--expect-entities", "CNO=4")
    result = _main(capsys, out, *pairs)
    _fails(result, out, f"{second} has the same SHA-256 as {first}")


def test_main_wrong_entity_count(
    tmp_path: Path, books: dict, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _export(tmp_path, books, base_cells(), "a")
    out = tmp_path / "out.json"
    result = _main(capsys, out, "--excel", f"CNO={path}", "--expect-entities", "CNO=51")
    _fails(result, out, "the CNO files hold 2 entities, expected 51")


@pytest.mark.parametrize(
    ("expect", "line"),
    [
        ((), "--expect-entities is missing for CNO"),
        (
            ("--expect-entities", "CNO=2", "--expect-entities", "COT=5"),
            "--expect-entities names COT, which has no --excel file",
        ),
        (
            ("--expect-entities", "CNO=2", "--expect-entities", "CNO=2"),
            "--expect-entities is given twice for CNO",
        ),
        (
            ("--expect-entities", "CNO=x"),
            "invalid --expect-entities 'CNO=x' (expected TYPE=N, N a positive whole number)",
        ),
        (
            ("--expect-entities", "CNO=0"),
            "invalid --expect-entities 'CNO=0' (expected TYPE=N, N a positive whole number)",
        ),
        (
            ("--expect-entities", "XXX=2"),
            "unknown account type 'XXX' in --expect-entities 'XXX=2'",
        ),
    ],
)
def test_main_expect_entities_errors(
    tmp_path: Path,
    books: dict,
    capsys: pytest.CaptureFixture[str],
    expect: tuple[str, ...],
    line: str,
) -> None:
    path = _export(tmp_path, books, base_cells(), "a")
    out = tmp_path / "out.json"
    _fails(_main(capsys, out, "--excel", f"CNO={path}", *expect), out, line)


@pytest.mark.parametrize(
    ("argv", "line"),
    [
        (
            ["--excel", "CNO=a.xls", "--expect-entities", "CNO=1"],
            "the following arguments are required: --declaration-date",
        ),
        (
            ["--declaration-date", "23-11-2026", "--excel", "CNO=a.xls"],
            "invalid --declaration-date '23-11-2026' (expected YYYY-MM-DD)",
        ),
        (
            ["--declaration-date", "2026-02-30", "--excel", "CNO=a.xls"],
            "invalid --declaration-date '2026-02-30' (expected YYYY-MM-DD)",
        ),
        (
            ["--declaration-date", "2026-11-23", "--excel", "CNO"],
            "invalid --excel 'CNO' (expected TYPE=PATH)",
        ),
        (
            ["--declaration-date", "2026-11-23", "--excel", "XXX=a.xls"],
            "unknown account type 'XXX' in --excel 'XXX=a.xls'",
        ),
        (
            [
                "--declaration-date",
                "2026-11-23",
                "--excel",
                "CNO=a.xls",
                "--retrieved-on",
                "2026-11-23",
            ],
            "unrecognized arguments: --retrieved-on 2026-11-23",
        ),
    ],
)
def test_main_wrong_command_line(
    capsys: pytest.CaptureFixture[str], argv: list[str], line: str
) -> None:
    code = imp.main(argv)
    captured = capsys.readouterr()
    assert (code, captured.out) == (1, "")
    assert captured.err == f"error: {line}\n"


def test_main_without_xlrd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setitem(sys.modules, "xlrd", None)
    path = _xls(tmp_path)
    out = tmp_path / "out.json"
    result = _main(capsys, out, "--excel", f"CNO={path}", "--expect-entities", "CNO=2")
    _fails(result, out, f'cannot read {path}: xlrd is not installed (pip install -e ".[import]")')


def test_a_failed_run_leaves_the_existing_snapshot_untouched(
    tmp_path: Path, books: dict, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _export(tmp_path, books, _with(_14_10="3,999"), "a")
    out = tmp_path / "public" / "fees.json"
    out.parent.mkdir()
    out.write_bytes(b'{"keep": "me"}\r\n')
    code = imp.main(
        [
            "--declaration-date",
            "2026-11-23",
            "--excel",
            f"CNO={path}",
            "--expect-entities",
            "CNO=2",
            "--output",
            str(out),
        ]
    )
    assert code == 1
    assert "more than two decimals" in capsys.readouterr().err
    assert out.read_bytes() == b'{"keep": "me"}\r\n'
    assert sorted(p.name for p in out.parent.iterdir()) == ["fees.json"]


def test_a_write_failure_is_one_error_line(
    tmp_path: Path, books: dict, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _export(tmp_path, books, base_cells(), "a")
    out = tmp_path / "public"
    (out / "occupied").mkdir(parents=True)  # the output is a non-empty folder: replace fails
    pairs = ("--excel", f"CNO={path}", "--expect-entities", "CNO=2")
    code, stdout, stderr = _main(capsys, out, *pairs)
    assert (code, stdout) == (1, "")
    assert stderr.startswith(f"error: cannot write {out}: ")
    assert stderr.count("\n") == 1
    assert sorted(p.name for p in tmp_path.iterdir()) == ["downloads", "public"]
    assert sorted(p.name for p in out.iterdir()) == ["occupied"]


# --- hygiene and boundaries (REQ-PF-22, decision Q6, DN-PF-24, DN-PF-30, DN-PF-31) ---


def _imports(path: Path) -> list[tuple[str, ast.AST]]:
    """Return (top-level module name, node) of every import in a file."""
    found: list[tuple[str, ast.AST]] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.extend((alias.name.split(".")[0], node) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.append((node.module.split(".")[0], node))
    return found


def test_the_script_imports_the_stdlib_the_library_and_xlrd_only() -> None:
    roots = {name for name, _ in _imports(SCRIPT)} - {"__future__"}
    assert roots - set(sys.stdlib_module_names) == {"ledger_kit", "xlrd"}
    assert not roots & {"urllib", "http", "socket", "requests", "openpyxl"}


def test_the_only_import_of_xlrd_is_inside_read_grid() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    everywhere = [n for name, n in _imports(SCRIPT) if name == "xlrd"]
    functions = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    [read_grid] = [n for n in functions if n.name == "read_grid"]
    inside = [n for n in ast.walk(read_grid) if isinstance(n, ast.Import)]
    assert len(everywhere) == 1
    assert [alias.name for node in inside for alias in node.names] == ["xlrd"]


def test_the_script_reads_no_clock_and_uses_no_float() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    for forbidden in (".today(", ".now(", "time.time(", "utcnow", "float("):
        assert forbidden not in source, forbidden


def _project_python_files() -> list[Path]:
    """Every .py file under ledger_kit/ and apps/, and streamlit_app.py."""
    files = [ROOT / "streamlit_app.py"]
    for package in ("ledger_kit", "apps"):
        found = sorted((ROOT / package).rglob("*.py"))
        files += [path for path in found if "__pycache__" not in path.parts]
    return files


def test_no_project_module_imports_xlrd() -> None:
    offenders = [
        path.relative_to(ROOT).as_posix()
        for path in _project_python_files()
        if any(name in ("xlrd", "openpyxl") for name, _ in _imports(path))
    ]
    assert offenders == []


def test_requirements_do_not_name_xlrd() -> None:
    lines = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower().splitlines()
    assert not [line for line in lines if line.strip().startswith(("xlrd", "openpyxl"))]


def test_xlrd_is_pinned_in_the_optional_extra_import() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["optional-dependencies"]["import"] == ["xlrd==2.0.1"]
    assert not any(dep.lower().startswith("xlrd") for dep in project["dependencies"])


def test_the_compared_concepts_equal_the_vampire_config() -> None:
    config_path = ROOT / "apps" / "vampire_fees" / "config.toml"
    table = tomllib.loads(config_path.read_text(encoding="utf-8"))["peer_fees"]
    services = [sub for sub in table.values() if isinstance(sub, dict)]
    concepts = {sub["service"]: sub["concept"] for sub in services}
    assert concepts == dict(imp.COMPARED_CONCEPTS)
    assert imp.KEPT_SERVICES == ("101", "401")


def test_the_main_function_takes_no_clock_argument() -> None:
    main: Callable[..., int] = imp.main
    assert list(main.__code__.co_varnames[: main.__code__.co_argcount]) == ["argv"]
    assert main.__code__.co_kwonlyargcount == 0
