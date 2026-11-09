"""Tests for the constants and counterparty normalisation helpers (Task Z2)."""

import re
import string
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from apps.zombie_subscriptions.detectors import utils
from apps.zombie_subscriptions.detectors.utils import (
    normalise_alias_map,
    normalise_counterparty,
    normalise_date_map,
    resolve_alias,
)

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.toml"


# --- Tier 1 -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Streamflix Intl.", "STREAMFLIX INTL"),
        ("STREAMFLIX.COM", "STREAMFLIXCOM"),
        ("BEATSTREAM P2A3B4C5", "BEATSTREAM"),
        ("  cloudvault  ", "CLOUDVAULT"),
        ("STREAMFLEX INTL 4412", "STREAMFLEX INTL"),
    ],
)
def test_normalise_examples(raw: str, expected: str) -> None:
    """Documented examples of REQ-ZS-05 normalise as specified."""
    assert normalise_counterparty(raw) == expected


def test_resolve_alias_hit_and_miss() -> None:
    """A member key resolves to its canonical name; an unknown key is returned unchanged."""
    aliases = {"STREAMING": ["STREAMFLIX INTL", "STREAMFLIXCOM"]}
    assert resolve_alias("STREAMFLIXCOM", aliases) == "STREAMING"
    assert resolve_alias("STREAMFLIX INTL", aliases) == "STREAMING"
    assert resolve_alias("CLOUDVAULT", aliases) == "CLOUDVAULT"


def test_normalise_alias_map_normalises_names_and_members() -> None:
    """Canonical names and member keys are both normalised."""
    raw = {"Streaming": ["Streamflix.com", "Streamflix Intl 7731"]}
    assert normalise_alias_map(raw) == {"STREAMING": ["STREAMFLIXCOM", "STREAMFLIX INTL"]}


def test_normalise_date_map_normalises_keys() -> None:
    """Service names in a date map are normalised; the dates are kept."""
    raw = {"BeatStream": date(2026, 7, 15), "photo box 9": date(2026, 6, 20)}
    assert normalise_date_map(raw) == {
        "BEATSTREAM": date(2026, 7, 15),
        "PHOTO BOX": date(2026, 6, 20),
    }


def test_constants_values() -> None:
    """Every design §2 constant exists with the stated value."""
    assert utils.WEEKLY_NOMINAL_DAYS == 7
    assert utils.MONTHLY_NOMINAL_DAYS == 30
    assert utils.QUARTERLY_NOMINAL_DAYS == 91
    assert utils.YEARLY_NOMINAL_DAYS == 365
    assert utils.INTERVAL_TOLERANCE_DAYS == 3
    assert utils.MIN_OCCURRENCES_WEEKLY == 4
    assert utils.MIN_OCCURRENCES_MONTHLY == 3
    assert utils.MIN_OCCURRENCES_QUARTERLY == 2
    assert utils.MIN_OCCURRENCES_YEARLY == 2
    assert utils.STABLE_AMOUNT_RATIO == Decimal("0.02")
    assert utils.PRICE_INCREASE_MIN_RATIO == Decimal("0.05")
    assert utils.MAX_EDGE_STEP_RATIO == Decimal("0.50")
    assert utils.MIN_SIDE_ROWS == 2
    assert utils.AMOUNT_MATCH_RATIO == Decimal("0.10")
    # REQ-DF-10: a weekly run is never accepted as a variable bill.
    assert utils.VARIABLE_BILL_INTERVALS == ("monthly", "quarterly", "yearly")
    assert utils.FREE_TRIAL_MIN_TOKEN_AMOUNT == Decimal("0.01")
    assert utils.FREE_TRIAL_MAX_TOKEN_AMOUNT == Decimal("1.00")
    assert utils.TRIAL_MAX_DAYS_BEFORE_FIRST_CHARGE == 35
    assert utils.PERIODS_PER_YEAR_WEEKLY == 52
    assert utils.PERIODS_PER_YEAR_MONTHLY == 12
    assert utils.PERIODS_PER_YEAR_QUARTERLY == 4
    assert utils.PERIODS_PER_YEAR_YEARLY == 1


def test_interval_types_order_and_lookup() -> None:
    """INTERVAL_TYPES is weekly, monthly, quarterly, yearly; INTERVALS_BY_NAME matches."""
    assert [i["name"] for i in utils.INTERVAL_TYPES] == [
        "weekly",
        "monthly",
        "quarterly",
        "yearly",
    ]
    assert [(i["nominal"], i["min"], i["ppy"]) for i in utils.INTERVAL_TYPES] == [
        (7, 4, 52),
        (30, 3, 12),
        (91, 2, 4),
        (365, 2, 1),
    ]
    assert set(utils.INTERVALS_BY_NAME) == {"weekly", "monthly", "quarterly", "yearly"}
    for interval in utils.INTERVAL_TYPES:
        assert utils.INTERVALS_BY_NAME[interval["name"]] is interval


def test_no_thresholds_in_config_toml() -> None:
    """REQ-ZS-42: config.toml (added by Task Z17) names none of the threshold constants."""
    if not CONFIG_PATH.exists():
        pytest.skip("config.toml is created by Task Z17")
    text = CONFIG_PATH.read_text(encoding="utf-8")
    constant_names = [name for name in dir(utils) if name.isupper()]
    assert constant_names
    assert [name for name in constant_names if name in text] == []


# --- Tier 2 -----------------------------------------------------------------------------------


def test_normalise_all_tokens_have_digits_falls_back() -> None:
    """When every token has a digit, the digit-drop step is skipped (letters are kept)."""
    assert normalise_counterparty("A1 B2") == "A B"
    assert normalise_counterparty("1234 5678") == ""


def test_normalise_empty_string() -> None:
    """The empty string and whitespace normalise to the empty string."""
    assert normalise_counterparty("") == ""
    assert normalise_counterparty("   \t ") == ""


def test_resolve_alias_none_and_empty() -> None:
    """A missing or empty alias map leaves the key unchanged."""
    assert resolve_alias("CLOUDVAULT", None) == "CLOUDVAULT"
    assert resolve_alias("CLOUDVAULT", {}) == "CLOUDVAULT"


def test_normalise_alias_map_none() -> None:
    """None stays None and an empty map stays empty."""
    assert normalise_alias_map(None) is None
    assert normalise_alias_map({}) == {}


def test_normalise_date_map_none() -> None:
    """None stays None and an empty map stays empty."""
    assert normalise_date_map(None) is None
    assert normalise_date_map({}) == {}


# --- Tier 3 -----------------------------------------------------------------------------------

_ASCII_NAME_ALPHABET = string.ascii_letters + string.digits + " .-"


@given(raw=st.text(max_size=40))
@settings(max_examples=200)
def test_normalise_idempotent(raw: str) -> None:
    """Normalising an already normalised key changes nothing."""
    once = normalise_counterparty(raw)
    assert normalise_counterparty(once) == once


@given(raw=st.text(max_size=40))
@settings(max_examples=200)
def test_normalise_output_only_letters_and_spaces(raw: str) -> None:
    """The key contains only A-Z and single spaces, with no leading or trailing space."""
    result = normalise_counterparty(raw)
    assert re.fullmatch(r"[A-Z]+( [A-Z]+)*", result) or result == ""


@given(raw=st.text(alphabet=_ASCII_NAME_ALPHABET, max_size=30))
@settings(max_examples=200)
def test_normalise_case_and_whitespace_invariant(raw: str) -> None:
    """Letter case and surrounding whitespace never change the key."""
    expected = normalise_counterparty(raw)
    assert normalise_counterparty(raw.lower()) == expected
    assert normalise_counterparty(raw.upper()) == expected
    assert normalise_counterparty("  " + raw + " \t") == expected
