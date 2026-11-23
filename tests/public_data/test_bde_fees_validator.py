"""Tests for validate_fee_snapshot (REQ-PF-02); every snapshot here is synthetic."""

from __future__ import annotations

import copy
import json
from decimal import Decimal
from typing import Any

import pytest
from bde_builders import (
    MAINTENANCE_CONCEPT,
    account,
    amount_row,
    asterisk_row,
    make_snapshot,
    row,
    snapshot_strategy,
    synthetic_s10,
    synthetic_s12,
)
from hypothesis import given, settings
from hypothesis import strategies as st

from ledger_kit.public_data import FeeSnapshotError, attribution_for, validate_fee_snapshot
from ledger_kit.public_data.bde_fees import SNAPSHOT_KEYS


def _one_account(**row_overrides: Any) -> dict[str, Any]:
    """A snapshot with one CNO account 0049-01 and one row for service 101 (synthetic)."""
    acc = account("0049")
    cell = amount_row(acc, "101", MAINTENANCE_CONCEPT, "6.50")
    cell.update(row_overrides)
    return make_snapshot([acc], [cell])


def _rejects(data: Any, message: str) -> None:
    """Assert that the validator rejects `data` with exactly `message`."""
    with pytest.raises(FeeSnapshotError) as info:
        validate_fee_snapshot(data)
    assert str(info.value) == message


# --- valid snapshots ---------------------------------------------------------------------------


def test_s12_and_s10_pass() -> None:
    validate_fee_snapshot(synthetic_s12())
    validate_fee_snapshot(synthetic_s10())


def test_the_validator_does_not_change_its_input() -> None:
    data = synthetic_s12()
    before = copy.deepcopy(data)
    validate_fee_snapshot(data)
    assert data == before


def test_a_snapshot_with_two_types_passes() -> None:
    cno, cot = account("9901"), account("9901", account_type="COT")
    rows = [
        amount_row(cno, "101", MAINTENANCE_CONCEPT, "0.00"),
        amount_row(cot, "101", MAINTENANCE_CONCEPT, "12.00"),
    ]
    validate_fee_snapshot(make_snapshot([cno, cot], rows))


def test_a_snapshot_without_rows_passes() -> None:
    validate_fee_snapshot(make_snapshot([account("9901")], []))


# --- top level -------------------------------------------------------------------------------


def test_not_an_object() -> None:
    _rejects([], "the snapshot is not a JSON object")


def test_missing_key() -> None:
    data = synthetic_s12()
    del data["rows"]
    _rejects(data, "missing key 'rows'")


def test_extra_key() -> None:
    _rejects(synthetic_s12(extra="x"), "unexpected key 'extra'")


def test_snapshot_keys_are_the_twelve_of_req_pf_01() -> None:
    assert list(synthetic_s12()) == list(SNAPSHOT_KEYS)
    assert len(SNAPSHOT_KEYS) == 12


def test_format_2() -> None:
    _rejects(synthetic_s12(snapshot_format=2), "unsupported snapshot_format 2 (expected 1)")


@pytest.mark.parametrize("value", [True, "1", Decimal("1.0")])
def test_format_that_is_not_the_integer_1(value: Any) -> None:
    _rejects(
        synthetic_s12(snapshot_format=value),
        f"unsupported snapshot_format {value!r} (expected 1)",
    )


def test_bad_declaration_date() -> None:
    _rejects(
        synthetic_s12(declaration_date="23-11-2026", attribution=attribution_for("2026-11-23")),
        "invalid declaration_date '23-11-2026' (expected YYYY-MM-DD)",
    )


def test_impossible_retrieved_on() -> None:
    _rejects(
        synthetic_s12(retrieved_on="2026-02-30"),
        "invalid retrieved_on '2026-02-30' (expected YYYY-MM-DD)",
    )


def test_retrieved_before_the_declaration_date() -> None:
    _rejects(
        synthetic_s12(retrieved_on="2026-11-20"),
        "retrieved_on 2026-11-20 is before declaration_date 2026-11-23",
    )


@pytest.mark.parametrize("key", ["source", "start_page", "licence_note", "no_endorsement"])
def test_constants_changed(key: str) -> None:
    data = synthetic_s12()
    data[key] = data[key] + " "
    _rejects(data, f"{key} differs from the constant of bde_fees.py")


def test_attribution_changed() -> None:
    _rejects(
        synthetic_s12(attribution="Fuente: Banco de España."),
        "attribution differs from attribution_for('2026-11-23')",
    )


def test_attribution_with_another_date() -> None:
    _rejects(
        synthetic_s12(attribution=attribution_for("2026-11-24")),
        "attribution differs from attribution_for('2026-11-23')",
    )


# --- account types and excel files --------------------------------------------------------------


def test_account_types_empty() -> None:
    _rejects(synthetic_s12(account_types=[]), "account_types must be a non-empty list")


def test_account_type_unknown() -> None:
    _rejects(synthetic_s12(account_types=["CNO", "XXX"]), "unknown account type 'XXX'")


def test_account_type_repeated() -> None:
    _rejects(synthetic_s12(account_types=["CNO", "CNO"]), "repeated account type CNO")


def test_account_types_out_of_order() -> None:
    _rejects(
        synthetic_s12(account_types=["COT", "CNO"]), "account types out of order: CNO after COT"
    )


def test_account_type_without_account() -> None:
    data = synthetic_s12(account_types=["CNO", "COT"])
    data["excel_files"].append({**data["excel_files"][0], "account_type": "COT"})
    _rejects(data, "account type COT has no account")


def test_excel_files_missing_a_type() -> None:
    _rejects(synthetic_s12(excel_files=[]), "excel_files has no entry for CNO")


def test_excel_files_with_two_entries_for_one_type() -> None:
    data = synthetic_s12()
    data["excel_files"].append(dict(data["excel_files"][0]))
    _rejects(data, "excel_files has two entries for CNO")


def test_excel_file_of_a_type_not_in_the_snapshot() -> None:
    data = synthetic_s12()
    data["excel_files"].append({**data["excel_files"][0], "account_type": "COT"})
    _rejects(data, "excel_files names unknown account type 'COT'")


@pytest.mark.parametrize("name", ["", "C:\\Users\\x\\cno.xlsx", "downloads/cno.xlsx", 7])
def test_excel_file_bad_name(name: Any) -> None:
    data = synthetic_s12()
    data["excel_files"][0]["name"] = name
    _rejects(data, f"invalid excel file name for CNO: {name!r}")


@pytest.mark.parametrize("size", [0, -1, True, "2048", Decimal("2048.0")])
def test_excel_file_bad_size(size: Any) -> None:
    data = synthetic_s12()
    data["excel_files"][0]["size_bytes"] = size
    _rejects(data, "invalid size_bytes for CNO: expected a positive integer")


@pytest.mark.parametrize("sha", ["a" * 63, "A" * 64, "g" * 64, None])
def test_excel_file_bad_sha256(sha: Any) -> None:
    data = synthetic_s12()
    data["excel_files"][0]["sha256"] = sha
    _rejects(data, "invalid sha256 for CNO: expected 64 lowercase hex digits")


def test_excel_file_with_an_extra_key() -> None:
    data = synthetic_s12()
    data["excel_files"][0]["path"] = "x"
    _rejects(
        data, "excel_files entry must have exactly ['account_type', 'name', 'size_bytes', 'sha256']"
    )


# --- accounts ------------------------------------------------------------------------------------


def test_account_key_not_starting_with_its_entity_code() -> None:
    acc = account("0049")
    acc["account_key"] = "0182-01"
    _rejects(
        make_snapshot([acc], []), "account_key '0182-01' does not start with entity_code '0049'"
    )


@pytest.mark.parametrize("key", ["0049-1", "0049_01", "0049-001", 4901])
def test_account_key_with_a_bad_shape(key: Any) -> None:
    acc = account("0049")
    acc["account_key"] = key
    _rejects(make_snapshot([acc], []), f"invalid account_key {key!r} (expected NNNN-NN)")


@pytest.mark.parametrize("code", ["49", "00490", "ABCD", 49])
def test_entity_code_that_is_not_four_digits(code: Any) -> None:
    acc = account("0049")
    acc["entity_code"] = code
    _rejects(make_snapshot([acc], []), f"invalid entity_code {code!r} (expected four digits)")


def test_entity_code_with_two_names() -> None:
    first, second = account("9903", 1), account("9903", 2)
    second["entity_name"] = "Otra Entidad Demo"
    _rejects(make_snapshot([first, second], []), "entity_code 9903 appears with two names")


def test_repeated_account() -> None:
    acc = account("9903")
    _rejects(make_snapshot([acc, dict(acc)], []), "repeated account: CNO 9903-01")


@pytest.mark.parametrize("key", ["entity_name", "account_name"])
def test_empty_names(key: str) -> None:
    acc = account("9903")
    acc[key] = "  "
    _rejects(make_snapshot([acc], []), f"empty {key} for CNO 9903-01")


def test_account_with_another_declaration_date() -> None:
    acc = account("9903", declaration_date="2026-11-22")
    _rejects(
        make_snapshot([acc], []),
        "account CNO 9903-01 has declaration_date '2026-11-22' (expected 2026-11-23)",
    )


def test_account_with_a_type_not_in_account_types() -> None:
    acc = account("9903")
    data = make_snapshot([acc], [])
    data["accounts"].append(account("9904", account_type="COT"))
    _rejects(data, "account 1 has unknown account type 'COT'")


def test_account_with_an_extra_key() -> None:
    acc = {**account("9903"), "iban": None}
    with pytest.raises(FeeSnapshotError, match="^account 0 must have exactly"):
        validate_fee_snapshot(make_snapshot([acc], []))


# --- rows ----------------------------------------------------------------------------------------


def test_row_naming_an_unknown_account() -> None:
    data = _one_account(account_key="0049-02")
    _rejects(data, "row 0 names unknown account CNO 0049-02")


def test_unknown_service_999() -> None:
    _rejects(_one_account(service_code="999"), "unknown service code '999'")


def test_row_with_an_extra_key() -> None:
    data = _one_account()
    data["rows"][0]["note"] = "x"
    with pytest.raises(FeeSnapshotError, match="^row 0 must have exactly"):
        validate_fee_snapshot(data)


def test_row_with_a_missing_key() -> None:
    data = _one_account()
    del data["rows"][0]["not_offered"]
    with pytest.raises(FeeSnapshotError, match="^row 0 must have exactly"):
        validate_fee_snapshot(data)


def test_empty_concept() -> None:
    _rejects(_one_account(concept=""), "empty concept: CNO 0049-01 service 101")


@pytest.mark.parametrize("text", ["6,50 ", " 6,50", "6,50\u00a0", "\u00a06,50"])
def test_text_with_surrounding_whitespace(text: str) -> None:
    _rejects(
        _one_account(text=text),
        "text of CNO 0049-01 service 101 has leading or trailing whitespace",
    )


def test_concept_with_surrounding_whitespace() -> None:
    _rejects(
        _one_account(concept=MAINTENANCE_CONCEPT + "\u00a0"),
        "concept of CNO 0049-01 service 101 has leading or trailing whitespace",
    )


@pytest.mark.parametrize("amount", ["6,5", "-1.00", "6.5", "6.500", "", "1e2"])
def test_amount_that_is_not_two_decimals(amount: str) -> None:
    _rejects(
        _one_account(amount=amount),
        f"amount '{amount}' of CNO 0049-01 service 101 is not a decimal with two places",
    )


def test_amount_that_is_a_json_float() -> None:
    data = json.loads(json.dumps(_one_account()).replace('"6.50"', "6.5"), parse_float=Decimal)
    _rejects(data, "amount '6.5' of CNO 0049-01 service 101 is not a decimal with two places")


def test_text_that_is_a_json_float() -> None:
    data = json.loads(json.dumps(_one_account()).replace('"6,50"', "6.5"), parse_float=Decimal)
    _rejects(data, "text of CNO 0049-01 service 101 is not a string")


def test_not_offered_with_an_amount() -> None:
    _rejects(
        _one_account(text="*", amount="0.00", not_offered=True),
        "not_offered row with an amount: CNO 0049-01 service 101",
    )


@pytest.mark.parametrize("flag", [None, 0, "false"])
def test_not_offered_that_is_not_a_bool(flag: Any) -> None:
    _rejects(
        _one_account(not_offered=flag),
        "not_offered of CNO 0049-01 service 101 is not true or false",
    )


def test_duplicate_row() -> None:
    data = _one_account()
    data["rows"].append(dict(data["rows"][0]))
    _rejects(data, "duplicate row: CNO 0049-01 service 101 concept 'Comisión anual total (euros)'")


def test_rows_out_of_order_by_service() -> None:
    acc = account("9901")
    rows = [
        asterisk_row(acc, "401", MAINTENANCE_CONCEPT),
        amount_row(acc, "101", MAINTENANCE_CONCEPT, "0.00"),
    ]
    _rejects(make_snapshot([acc], rows), "rows out of order: CNO 9901-01 service 101 after row 0")


def test_rows_out_of_order_by_entity() -> None:
    first, second = account("9901"), account("9902")
    rows = [
        amount_row(second, "101", MAINTENANCE_CONCEPT, "0.00"),
        amount_row(first, "101", MAINTENANCE_CONCEPT, "0.00"),
    ]
    _rejects(
        make_snapshot([first, second], rows),
        "rows out of order: CNO 9901-01 service 101 after row 0",
    )


def test_concepts_keep_their_published_order() -> None:
    acc = account("9901")
    rows = [
        row(acc, "101", "Periodicidad", "ANUAL"),
        amount_row(acc, "101", MAINTENANCE_CONCEPT, "0.00"),
    ]
    validate_fee_snapshot(make_snapshot([acc], rows))
    validate_fee_snapshot(make_snapshot([acc], rows[::-1]))


# --- properties --------------------------------------------------------------------------------


@settings(max_examples=200)
@given(data=snapshot_strategy())
def test_a_generated_valid_snapshot_passes(data: dict[str, Any]) -> None:
    validate_fee_snapshot(data)


@settings(max_examples=200)
@given(data=snapshot_strategy(), choice=st.integers(min_value=0))
def test_removing_an_account_that_a_row_refers_to_fails(data: dict[str, Any], choice: int) -> None:
    referenced = {(r["account_type"], r["account_key"]) for r in data["rows"]}
    if not referenced:
        return
    target = sorted(referenced)[choice % len(referenced)]
    data["accounts"] = [
        a for a in data["accounts"] if (a["account_type"], a["account_key"]) != target
    ]
    with pytest.raises(FeeSnapshotError):
        validate_fee_snapshot(data)


@settings(max_examples=200)
@given(data=snapshot_strategy(), key=st.sampled_from(SNAPSHOT_KEYS))
def test_deleting_a_top_level_key_fails(data: dict[str, Any], key: str) -> None:
    del data[key]
    with pytest.raises(FeeSnapshotError, match=f"^missing key '{key}'$"):
        validate_fee_snapshot(data)
