"""Pinned checks of the committed Banco de España fee snapshot (REQ-PF-03).

The snapshot is not committed yet: every test that reads it is skipped until task PF9. No fee
amount is pinned, so a refreshed snapshot breaks nothing.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from ledger_kit.public_data import (
    DEFAULT_FEE_SNAPSHOT_PATH,
    FeeSnapshot,
    attribution_for,
    load_fee_snapshot,
    validate_fee_snapshot,
)
from ledger_kit.public_data.bde_fees import LICENCE_NOTE, NO_ENDORSEMENT

REPO_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = REPO_ROOT / "data" / "public" / "bde_payment_account_fees.json"
# The number of entities that had declared CNO accounts on 23 November 2026 (BdE, Source fact 3).
CNO_ENTITIES_ON_2026_11_23 = 51

needs_snapshot = pytest.mark.skipif(
    not SNAPSHOT.exists(), reason="snapshot not committed yet (PF9 is blocked)"
)


@pytest.fixture(scope="module")
def raw() -> dict[str, Any]:
    """The committed snapshot as a JSON object (amounts stay strings)."""
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"), parse_float=Decimal)


@pytest.fixture(scope="module")
def snapshot() -> FeeSnapshot:
    """The committed snapshot, read through the library loader (which validates it)."""
    return load_fee_snapshot(SNAPSHOT)


def test_the_default_path_is_the_public_folder() -> None:
    expected = "data/public/bde_payment_account_fees.json"
    assert DEFAULT_FEE_SNAPSHOT_PATH.as_posix().endswith(expected)
    assert DEFAULT_FEE_SNAPSHOT_PATH == SNAPSHOT


@needs_snapshot
def test_the_snapshot_passes_the_validator(raw: dict[str, Any]) -> None:
    validate_fee_snapshot(raw)


@needs_snapshot
def test_cno_is_present(snapshot: FeeSnapshot) -> None:
    # Amendment A1 (DN-PF-25, replaces Q5): a type enters only when its files hold every entity
    # the tool lists for it; the first snapshot holds CNO only, COT is added once complete.
    assert "CNO" in snapshot.account_types


@needs_snapshot
def test_every_declaration_date_equals_the_top_level_one(raw: dict[str, Any]) -> None:
    assert {a["declaration_date"] for a in raw["accounts"]} == {raw["declaration_date"]}


@needs_snapshot
def test_the_texts_equal_the_constants(snapshot: FeeSnapshot) -> None:
    assert snapshot.licence_note == LICENCE_NOTE
    assert snapshot.no_endorsement == NO_ENDORSEMENT
    assert snapshot.attribution == attribution_for(snapshot.declaration_date)


@needs_snapshot
def test_cno_entity_count_on_the_reviewed_date(raw: dict[str, Any]) -> None:
    if raw["declaration_date"] != "2026-11-23":
        pytest.skip("the pinned entity count is for the declaration date 2026-11-23")
    codes = {a["entity_code"] for a in raw["accounts"] if a["account_type"] == "CNO"}
    assert len(codes) == CNO_ENTITIES_ON_2026_11_23
