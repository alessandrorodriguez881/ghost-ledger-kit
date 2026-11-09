"""Tests for the Norma 43 currency table (REQ-RF-04, design 4.6)."""

import re

from ledger_kit.ingestion.iso4217 import NUMERIC_TO_ALPHA

ANNEX_2 = {
    "978": "EUR",
    "840": "USD",
    "826": "GBP",
    "756": "CHF",
    "752": "SEK",
    "578": "NOK",
    "554": "NZD",
    "392": "JPY",
    "208": "DKK",
    "124": "CAD",
    "036": "AUD",
}


def test_table_is_exactly_the_eleven_annex_2_codes() -> None:
    assert NUMERIC_TO_ALPHA == ANNEX_2
    assert len(NUMERIC_TO_ALPHA) == 11


def test_every_entry_has_the_right_shape() -> None:
    for numeric, alpha in NUMERIC_TO_ALPHA.items():
        assert re.fullmatch(r"\d{3}", numeric), numeric
        assert re.fullmatch(r"[A-Z]{3}", alpha), alpha


def test_alpha_codes_are_unique() -> None:
    values = list(NUMERIC_TO_ALPHA.values())
    assert len(values) == len(set(values))


def test_codes_outside_the_table_are_absent() -> None:
    assert "999" not in NUMERIC_TO_ALPHA
    assert "000" not in NUMERIC_TO_ALPHA
