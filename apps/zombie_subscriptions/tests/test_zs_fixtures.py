"""Tests that the shared fixtures have the right shape and only synthetic content (Task Z4)."""

from collections import Counter
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest

from ledger_kit.ingestion.normaliser import CANONICAL_COLUMNS
from ledger_kit.utils.money import round_to_cents

LEDGER_FIXTURES = [
    "empty_ledger",
    "single_row_ledger",
    "clean_ledger_10",
    "ledger_with_recurring",
    "ledger_with_price_increase",
    "ledger_with_duplicate_sub",
    "ledger_with_aliased_duplicate",
    "ledger_with_free_trial",
    "ledger_with_post_cancellation",
    "ledger_with_zombie",
    "ledger_with_weekly_shopping",
]

# Invented merchants only: no person names and no real brands.
FICTIONAL_MERCHANTS = frozenset(
    {
        "CLOUDVAULT",
        "STREAMFLEX INTL",
        "MUSICBOX",
        "STREAMFLIX INTL",
        "STREAMFLIXCOM",
        "SECUREPASS",
        "GYMPLUS",
        "FRESHCO",
        "GLOWBILL",
        "SUPERMART",
        "BAKERYONE",
        "FUELSTOP",
        "BOOKNOOK",
        "TOYBARN",
        "GARDENPOINT",
        "CAFELUNA",
        "HARDWAREHUB",
        "PHARMAPOINT",
    }
)
REAL_BRAND_DENY_LIST = ("SPOTIFY", "ADOBE", "DROPBOX", "NETFLIX", "APPLE")


def _builder_frames(builders: SimpleNamespace) -> list[pd.DataFrame]:
    """Return one frame per builder function (E1-E7b, downgrade, recurring)."""
    names = [
        "rows_e1",
        "rows_e2",
        "rows_e3",
        "rows_e4",
        "rows_e6",
        "rows_e7",
        "rows_downgrade",
        "rows_weekly_shopping",
        "rows_recurring",
    ]
    return [builders.to_frame(getattr(builders, name)()) for name in names]


def test_fixture_columns_match_canonical_columns(
    request: pytest.FixtureRequest, builders: SimpleNamespace
) -> None:
    """Every fixture and builder frame has exactly the canonical columns."""
    frames = [request.getfixturevalue(name) for name in LEDGER_FIXTURES]
    for frame in frames + _builder_frames(builders):
        assert list(frame.columns) == list(CANONICAL_COLUMNS)


def test_fixtures_are_debit_only_with_unique_source_refs(
    request: pytest.FixtureRequest, builders: SimpleNamespace
) -> None:
    """Every row is a debit and every source_ref is unique within its frame."""
    frames = [request.getfixturevalue(name) for name in LEDGER_FIXTURES]
    for frame in frames + _builder_frames(builders):
        assert (frame["flow"] == "debit").all()
        assert frame["source_ref"].is_unique
        assert all(
            ref == f"{file}:{row}"
            for ref, file, row in zip(
                frame["source_ref"], frame["source_file"], frame["source_row"], strict=True
            )
        )


def test_fixture_counterparties_are_fictional_merchants(
    request: pytest.FixtureRequest, builders: SimpleNamespace
) -> None:
    """All counterparties come from the fixed fictional allow-list."""
    frames = [request.getfixturevalue(name) for name in LEDGER_FIXTURES]
    seen: set[str] = set()
    for frame in frames + _builder_frames(builders):
        seen.update(frame["counterparty"])
    assert seen <= FICTIONAL_MERCHANTS
    for name in seen:
        assert not any(brand in name for brand in REAL_BRAND_DENY_LIST)


def test_fixture_row_counts(request: pytest.FixtureRequest) -> None:
    """Spot-check the size of each fixture against the design §11.1 table."""
    expected = {
        "empty_ledger": 0,
        "single_row_ledger": 1,
        "clean_ledger_10": 10,
        "ledger_with_recurring": 3,
        "ledger_with_price_increase": 6,
        "ledger_with_duplicate_sub": 6,
        "ledger_with_aliased_duplicate": 6,
        "ledger_with_free_trial": 4,
        "ledger_with_post_cancellation": 4,
        "ledger_with_zombie": 3,
        "ledger_with_weekly_shopping": 26,
    }
    assert set(expected) == set(LEDGER_FIXTURES)
    for name, count in expected.items():
        assert len(request.getfixturevalue(name)) == count


def test_zombie_and_cancellation_dates_split_their_fixtures(
    ledger_with_zombie: pd.DataFrame,
    ledger_with_post_cancellation: pd.DataFrame,
    builders: SimpleNamespace,
) -> None:
    """Two charges follow the zombie last-used date; one follows the cancellation date."""
    after_use = ledger_with_zombie[ledger_with_zombie["date"] > builders.zombie_last_used_date]
    after_cancel = ledger_with_post_cancellation[
        ledger_with_post_cancellation["date"] > builders.cancellation_date
    ]
    assert len(after_use) == 2
    assert len(after_cancel) == 1


def test_weekly_shopping_fixture_matches_spec(ledger_with_weekly_shopping: pd.DataFrame) -> None:
    """E7b: 26 weekly rows, 13 price levels twice each 91 days apart, levels > 10% apart."""
    rows = ledger_with_weekly_shopping.to_dict("records")
    assert len(rows) == 26

    base = Decimal("40.00")
    for i, row in enumerate(rows):
        k = (5 * i) % 13
        assert row["date"] == date(2026, 5, 4) + timedelta(days=7 * i)
        assert row["amount"] == round_to_cents(base * Decimal("1.11") ** k)
        assert row["source_row"] == i

    counts = Counter(row["amount"] for row in rows)
    assert len(counts) == 13
    assert set(counts.values()) == {2}

    for amount in counts:
        days = sorted(row["date"] for row in rows if row["amount"] == amount)
        assert (days[1] - days[0]).days == 91

    levels = sorted(counts)
    assert levels[0] == Decimal("40.00")
    assert levels[-1] == Decimal("139.94")
    for lower, upper in zip(levels, levels[1:], strict=False):
        assert (upper - lower) / lower > Decimal("0.10")
