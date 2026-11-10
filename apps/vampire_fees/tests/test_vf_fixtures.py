"""Tests for the shared fixtures of the vampire-fees app (Task VF5)."""

from decimal import Decimal

import pandas as pd
import pytest

from apps.vampire_fees.detectors.utils import extract_fees
from apps.vampire_fees.tests.vf_builders import ALLOWED_COUNTERPARTIES
from ledger_kit.ingestion.normaliser import CANONICAL_COLUMNS

FIXTURE_NAMES = [
    "empty_ledger",
    "single_row_ledger",
    "clean_ledger_10",
    "ledger_with_monthly_fee",
    "ledger_with_fee_increase",
    "ledger_with_overdraft",
    "ledger_with_one_off_fees",
]


@pytest.fixture
def every_fixture(request: pytest.FixtureRequest) -> pd.DataFrame:
    """Resolve one fixture by name."""
    return request.getfixturevalue(request.param)


@pytest.mark.parametrize("every_fixture", FIXTURE_NAMES, indirect=True)
def test_fixture_has_canonical_columns_and_unique_refs(every_fixture: pd.DataFrame) -> None:
    """Every fixture frame has the canonical columns and unique source_refs."""
    assert tuple(every_fixture.columns) == CANONICAL_COLUMNS
    assert every_fixture["source_ref"].is_unique


@pytest.mark.parametrize("every_fixture", FIXTURE_NAMES, indirect=True)
def test_fixture_counterparties_are_fictional(every_fixture: pd.DataFrame) -> None:
    """Every counterparty belongs to the fixed allow-list of fictional names."""
    assert set(every_fixture["counterparty"]) <= ALLOWED_COUNTERPARTIES


@pytest.mark.parametrize("every_fixture", FIXTURE_NAMES, indirect=True)
def test_fixture_amounts_are_decimal_and_positive(every_fixture: pd.DataFrame) -> None:
    """Amounts are Decimal and positive; the direction is the flow column."""
    assert all(isinstance(a, Decimal) and a > 0 for a in every_fixture["amount"])


def test_empty_ledger_has_no_rows(empty_ledger: pd.DataFrame) -> None:
    """The empty fixture has zero rows."""
    assert empty_ledger.empty


def test_single_row_ledger_has_one_row(single_row_ledger: pd.DataFrame) -> None:
    """The single-row fixture has one row."""
    assert len(single_row_ledger) == 1


def test_clean_ledger_has_ten_rows_and_no_fee(clean_ledger_10, vocabulary) -> None:
    """clean_ledger_10 has ten rows and classifies to zero fees."""
    assert len(clean_ledger_10) == 10
    assert extract_fees(clean_ledger_10, vocabulary) == []


def test_fee_descriptions_hold_no_digit(
    ledger_with_monthly_fee,
    ledger_with_fee_increase,
    ledger_with_overdraft,
    ledger_with_one_off_fees,
) -> None:
    """No fee description of a fee fixture contains a digit."""
    for frame in (
        ledger_with_monthly_fee,
        ledger_with_fee_increase,
        ledger_with_overdraft,
        ledger_with_one_off_fees,
    ):
        assert not any(ch.isdigit() for text in frame["description"] for ch in text)


def test_fee_fixtures_classify_as_designed(
    ledger_with_monthly_fee,
    ledger_with_fee_increase,
    ledger_with_overdraft,
    ledger_with_one_off_fees,
    vocabulary,
) -> None:
    """Fee counts: 3, 4, 2 (both overdraft) and 3 (the credit refund is not a fee)."""
    assert len(extract_fees(ledger_with_monthly_fee, vocabulary)) == 3
    assert len(extract_fees(ledger_with_fee_increase, vocabulary)) == 4
    overdraft = extract_fees(ledger_with_overdraft, vocabulary)
    assert [f.kind for f in overdraft] == ["overdraft", "overdraft"]
    assert len(extract_fees(ledger_with_one_off_fees, vocabulary)) == 3
