"""Tests for the fee snapshot reader (REQ-PF-06 to REQ-PF-08); every snapshot here is synthetic."""

from __future__ import annotations

import ast
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from bde_builders import (
    CARD_CONCEPT,
    MAINTENANCE_CONCEPT,
    account,
    amount_row,
    asterisk_row,
    make_snapshot,
    row,
    snapshot_strategy,
    synthetic_s12,
)
from hypothesis import given, settings

import ledger_kit.public_data as public_data
from ledger_kit.public_data import (
    ACCOUNT_TYPE_ORDER,
    ACCOUNT_TYPES,
    SERVICES,
    FeeDeclarations,
    FeeSnapshot,
    FeeSnapshotError,
    attribution_for,
    bde_fees,
    load_fee_snapshot,
)

D = Decimal
S12_SORTED = tuple(
    D(v) for v in ("0.00",) * 5 + ("12.00", "24.00", "36.00", "60.00", "78.00", "96.00", "240.00")
)


def _write(path: Path, data: Any) -> Path:
    """Write `data` as UTF-8 JSON with two-space indent and return the path."""
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


# --- REQ-PF-07 on S12 ----------------------------------------------------------------------------


def test_s12_maintenance_declarations(synthetic_s12_snapshot: FeeSnapshot) -> None:
    found = synthetic_s12_snapshot.declarations("CNO", "101", MAINTENANCE_CONCEPT)
    assert found == FeeDeclarations(
        account_type="CNO",
        service_code="101",
        concept=MAINTENANCE_CONCEPT,
        declaration_date="2026-11-23",
        account_count=15,
        amounts=S12_SORTED,
        not_offered_count=3,
    )
    assert found.without_amount_count == 0


def test_s12_type_not_in_the_snapshot_is_none(synthetic_s12_snapshot: FeeSnapshot) -> None:
    assert synthetic_s12_snapshot.declarations("CDI", "101", MAINTENANCE_CONCEPT) is None


def test_s12_service_without_rows(synthetic_s12_snapshot: FeeSnapshot) -> None:
    found = synthetic_s12_snapshot.declarations("CNO", "301", MAINTENANCE_CONCEPT)
    assert found is not None
    assert (found.account_count, found.amounts, found.not_offered_count) == (15, (), 0)
    assert found.without_amount_count == 15


def test_s12_unknown_type_or_service_raises(synthetic_s12_snapshot: FeeSnapshot) -> None:
    with pytest.raises(ValueError):
        synthetic_s12_snapshot.declarations("XXX", "101", MAINTENANCE_CONCEPT)
    with pytest.raises(ValueError):
        synthetic_s12_snapshot.declarations("CNO", "999", "x")


def test_empty_concept_raises(synthetic_s12_snapshot: FeeSnapshot) -> None:
    with pytest.raises(ValueError):
        synthetic_s12_snapshot.declarations("CNO", "101", "")


def test_another_concept_of_the_same_service_has_no_amounts(
    synthetic_s12_snapshot: FeeSnapshot,
) -> None:
    found = synthetic_s12_snapshot.declarations("CNO", "101", CARD_CONCEPT)
    assert found is not None
    assert found.amounts == ()
    assert found.without_amount_count == 15


def test_s10_card_declarations(synthetic_s10_snapshot: FeeSnapshot) -> None:
    found = synthetic_s10_snapshot.declarations("CNO", "401", CARD_CONCEPT)
    assert found is not None
    assert found.amounts == tuple(
        D(v) for v in ("0.00",) * 5 + ("12.00", "18.00", "24.00", "30.00", "45.00")
    )
    assert (found.account_count, found.not_offered_count) == (10, 0)


def test_snapshot_exposes_its_texts(synthetic_s12_snapshot: FeeSnapshot) -> None:
    snap = synthetic_s12_snapshot
    assert snap.source == bde_fees.SOURCE
    assert snap.start_page == bde_fees.START_PAGE
    assert snap.licence_note == bde_fees.LICENCE_NOTE
    assert snap.no_endorsement == bde_fees.NO_ENDORSEMENT
    assert snap.attribution == attribution_for("2026-11-23")
    assert (snap.retrieved_on, snap.declaration_date) == ("2026-11-23", "2026-11-23")
    assert snap.account_types == ("CNO",)
    assert snap.excel_files[0]["account_type"] == "CNO"


def test_snapshot_is_immutable(synthetic_s12_snapshot: FeeSnapshot) -> None:
    with pytest.raises(AttributeError):
        synthetic_s12_snapshot.declaration_date = "2027-01-01"  # type: ignore[misc]
    with pytest.raises(TypeError):
        synthetic_s12_snapshot.excel_files[0]["name"] = "x.xlsx"  # type: ignore[index]


def test_from_dict_validates() -> None:
    with pytest.raises(FeeSnapshotError, match="unsupported snapshot_format 2"):
        FeeSnapshot.from_dict(synthetic_s12(snapshot_format=2))


def test_from_dict_does_not_keep_a_reference_to_the_input() -> None:
    data = synthetic_s12()
    snap = FeeSnapshot.from_dict(data)
    data["rows"].clear()
    assert len(snap.declarations("CNO", "101", MAINTENANCE_CONCEPT).amounts) == 12


# --- edge cases --------------------------------------------------------------------------------


def test_only_asterisks() -> None:
    accounts = [account(str(9901 + i)) for i in range(4)]
    rows = [asterisk_row(a, "101", MAINTENANCE_CONCEPT) for a in accounts]
    found = FeeSnapshot.from_dict(make_snapshot(accounts, rows)).declarations(
        "CNO", "101", MAINTENANCE_CONCEPT
    )
    assert found.amounts == ()
    assert found.not_offered_count == found.account_count == 4
    assert found.without_amount_count == 0


def test_repeated_zero_amounts_are_kept() -> None:
    accounts = [account("9901"), account("9902")]
    rows = [amount_row(a, "101", MAINTENANCE_CONCEPT, "0.00") for a in accounts]
    found = FeeSnapshot.from_dict(make_snapshot(accounts, rows)).declarations(
        "CNO", "101", MAINTENANCE_CONCEPT
    )
    assert found.amounts == (D("0.00"), D("0.00"))


def test_a_row_that_is_neither_amount_nor_asterisk() -> None:
    accounts = [account("9901"), account("9902"), account("9903")]
    rows = [
        amount_row(accounts[0], "101", MAINTENANCE_CONCEPT, "6.00"),
        row(accounts[1], "101", MAINTENANCE_CONCEPT, "ND"),
        asterisk_row(accounts[2], "101", MAINTENANCE_CONCEPT),
    ]
    found = FeeSnapshot.from_dict(make_snapshot(accounts, rows)).declarations(
        "CNO", "101", MAINTENANCE_CONCEPT
    )
    assert (found.account_count, len(found.amounts), found.not_offered_count) == (3, 1, 1)
    assert found.without_amount_count == 1


def test_several_accounts_of_one_entity_count_separately() -> None:
    accounts = [account("9901", 1), account("9901", 2)]
    rows = [
        amount_row(accounts[0], "101", MAINTENANCE_CONCEPT, "0.00"),
        amount_row(accounts[1], "101", MAINTENANCE_CONCEPT, "36.00"),
    ]
    found = FeeSnapshot.from_dict(make_snapshot(accounts, rows)).declarations(
        "CNO", "101", MAINTENANCE_CONCEPT
    )
    assert found.account_count == 2
    assert found.amounts == (D("0.00"), D("36.00"))


def test_types_are_answered_separately() -> None:
    cno, cot = account("9901"), account("9901", account_type="COT")
    rows = [
        amount_row(cno, "101", MAINTENANCE_CONCEPT, "0.00"),
        amount_row(cot, "101", MAINTENANCE_CONCEPT, "12.00"),
    ]
    snap = FeeSnapshot.from_dict(make_snapshot([cno, cot], rows))
    assert snap.declarations("CNO", "101", MAINTENANCE_CONCEPT).amounts == (D("0.00"),)
    assert snap.declarations("COT", "101", MAINTENANCE_CONCEPT).amounts == (D("12.00"),)


def test_str_of_every_amount_is_the_stored_string(synthetic_s12_snapshot: FeeSnapshot) -> None:
    stored = sorted((r["amount"] for r in synthetic_s12()["rows"] if r["amount"]), key=D)
    found = synthetic_s12_snapshot.declarations("CNO", "101", MAINTENANCE_CONCEPT)
    assert [str(a) for a in found.amounts] == stored


def test_constants() -> None:
    assert ACCOUNT_TYPE_ORDER == ("CNO", "CDI", "CJO", "CBA", "COT")
    assert {code: (t.label, t.phrase) for code, t in ACCOUNT_TYPES.items()} == {
        "CNO": ("Cuenta Nómina/Pensión", "payroll or pension"),
        "CDI": ("Cuenta Digital", "digital"),
        "CJO": ("Cuenta Joven", "youth"),
        "CBA": ("Cuenta Básica", "basic"),
        "COT": ("Otras Cuentas", "other"),
    }
    assert list(SERVICES) == [
        "101",
        "201",
        "301",
        "302",
        "401",
        "402",
        "403",
        "404",
        "501",
        "502",
        "601",
        "602",
        "603",
    ]
    assert SERVICES["101"] == "Mantenimiento de la cuenta"
    assert SERVICES["401"] == "Emisión y mantenimiento de una tarjeta de débito"


def test_attribution_of_decision_q1() -> None:
    assert attribution_for("2026-11-23") == (
        "Fuente: Banco de España, comparador de comisiones de cuentas de pago (declaraciones a "
        "fecha 2026-11-23). Elaboración propia: recuento, mediana y máximo."
    )


def test_public_names_are_exported() -> None:
    for name in (
        "FeeSnapshot",
        "FeeDeclarations",
        "FeeSnapshotError",
        "load_fee_snapshot",
        "validate_fee_snapshot",
        "attribution_for",
        "DEFAULT_FEE_SNAPSHOT_PATH",
        "ACCOUNT_TYPES",
        "ACCOUNT_TYPE_ORDER",
        "ATTRIBUTION_TEMPLATE",
        "SERVICES",
    ):
        assert name in public_data.__all__
        assert getattr(public_data, name) is getattr(bde_fees, name)


def test_fee_snapshot_error_is_a_value_error() -> None:
    assert issubclass(FeeSnapshotError, ValueError)


# --- load_fee_snapshot ---------------------------------------------------------------------------


def test_load_a_tiny_valid_file(tmp_path: Path) -> None:
    acc = account("9901")
    data = make_snapshot([acc], [amount_row(acc, "101", MAINTENANCE_CONCEPT, "6.50")])
    snap = load_fee_snapshot(_write(tmp_path / "fees.json", data))
    assert snap.declarations("CNO", "101", MAINTENANCE_CONCEPT).amounts == (D("6.50"),)


def test_load_a_missing_file() -> None:
    with pytest.raises(FeeSnapshotError) as info:
        load_fee_snapshot(Path("missing.json"))
    assert str(info.value) == "cannot read missing.json: file not found"


def test_load_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text('{\n  "snapshot_format": 1,\n  oops\n}\n', encoding="utf-8")
    with pytest.raises(FeeSnapshotError) as info:
        load_fee_snapshot(path)
    assert str(info.value) == f"cannot read {path}: invalid JSON at line 3"


def test_load_a_file_that_is_not_utf8(tmp_path: Path) -> None:
    path = tmp_path / "latin1.json"
    path.write_bytes('{"source": "Banco de España"}'.encode("latin-1"))
    with pytest.raises(FeeSnapshotError) as info:
        load_fee_snapshot(path)
    assert str(info.value) == f"cannot read {path}: not UTF-8 text"


def test_load_a_file_that_fails_the_validator(tmp_path: Path) -> None:
    path = _write(tmp_path / "fees.json", synthetic_s12(snapshot_format=2))
    with pytest.raises(FeeSnapshotError) as info:
        load_fee_snapshot(path)
    assert str(info.value) == f"invalid snapshot {path}: unsupported snapshot_format 2 (expected 1)"


def test_load_a_file_with_a_json_float_amount(tmp_path: Path) -> None:
    path = tmp_path / "fees.json"
    text = json.dumps(synthetic_s12(), indent=2, ensure_ascii=False)
    path.write_text(text.replace('"240.00"', "240.0"), encoding="utf-8")
    with pytest.raises(FeeSnapshotError, match="amount '240.0' of CNO 9901-01 service 101"):
        load_fee_snapshot(path)


def test_crlf_line_endings_load(tmp_path: Path) -> None:
    text = json.dumps(synthetic_s12(), indent=2, ensure_ascii=False) + "\n"
    path = tmp_path / "fees.json"
    path.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
    snap = load_fee_snapshot(path)
    assert snap.declarations("CNO", "101", MAINTENANCE_CONCEPT).amounts == S12_SORTED


def test_load_equals_from_dict(tmp_path: Path) -> None:
    data = synthetic_s12()
    loaded = load_fee_snapshot(_write(tmp_path / "fees.json", data))
    assert loaded == FeeSnapshot.from_dict(data)


# --- boundaries ----------------------------------------------------------------------------------


def test_the_module_imports_only_the_standard_library() -> None:
    tree = ast.parse(Path(bde_fees.__file__).read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    assert names <= set(sys.stdlib_module_names) | {"__future__"}, names


# --- properties (REQ-PF-08) --------------------------------------------------------------------


@settings(max_examples=200)
@given(data=snapshot_strategy())
def test_counts_add_up_amounts_are_sorted_and_come_from_rows(data: dict[str, Any]) -> None:
    snap = FeeSnapshot.from_dict(data)
    stored = {
        (r["account_type"], r["service_code"], r["concept"], r["amount"])
        for r in data["rows"]
        if r["amount"] is not None
    }
    concepts = {r["concept"] for r in data["rows"]} | {MAINTENANCE_CONCEPT}
    services = {r["service_code"] for r in data["rows"]} | {"101"}
    for code in ACCOUNT_TYPE_ORDER:
        for service in services:
            for concept in concepts:
                found = snap.declarations(code, service, concept)
                if code not in data["account_types"]:
                    assert found is None
                    continue
                total = len(found.amounts) + found.not_offered_count + found.without_amount_count
                assert total == found.account_count
                assert found.without_amount_count >= 0
                assert list(found.amounts) == sorted(found.amounts)
                for amount in found.amounts:
                    assert (code, service, concept, str(amount)) in stored
