"""Tests for the zombie-demo mode of scripts/generate_samples.py and its CSV (Task Z19)."""

import importlib.util
import sys
from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from apps.zombie_subscriptions.detectors.utils import (
    date_key,
    find_series,
    group_by_normalised_key,
    normalise_counterparty,
)
from ledger_kit.ingestion.csv_reader import parse_csv
from ledger_kit.ingestion.normaliser import normalise
from ledger_kit.utils.money import round_to_cents

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "generate_samples.py"
DEMO_CSV = ROOT / "data" / "samples" / "zombie_demo_statement.csv"

DEMO_START = date(2026, 5, 1)
DEMO_END = date(2026, 10, 31)
REAL_BRAND_DENY_LIST = (
    "SPOTIFY",
    "ADOBE",
    "DROPBOX",
    "NETFLIX",
    "AMAZON",
    "GOOGLE",
    "APPLE",
    "MICROSOFT",
    "DISNEY",
    "HBO",
    "YOUTUBE",
    "UBER",
    "MERCADONA",
    "CARREFOUR",
    "LIDL",
    "ZARA",
    "IKEA",
)


def _load_generator() -> Any:
    """Load scripts/generate_samples.py by path (scripts/ is not a package)."""
    spec = importlib.util.spec_from_file_location("generate_samples_zs", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["generate_samples_zs"] = module
    spec.loader.exec_module(module)
    return module


gen = _load_generator()


def _debit_groups() -> dict[str, list[dict]]:
    """Return {normalised key: date-sorted debit rows} of the committed demo CSV."""
    transactions, quarantined = parse_csv(DEMO_CSV, dialect="plain")
    assert quarantined == []
    frame, _ = normalise(transactions)
    debits = frame[frame["flow"] == "debit"].reset_index(drop=True)
    return dict(group_by_normalised_key(debits))


def _amounts(rows: list[dict]) -> list[str]:
    """Return the amounts of `rows` as text, in date order."""
    return [str(r["amount"]) for r in rows]


def _gaps(rows: list[dict]) -> list[int]:
    """Return the day gaps between consecutive rows."""
    return [(b["date"] - a["date"]).days for a, b in zip(rows, rows[1:], strict=False)]


# --- generator behaviour ------------------------------------------------------------------------


def test_generator_is_deterministic(tmp_path: Path) -> None:
    """Two runs with --seed 42 give identical bytes (and match the in-memory builder)."""
    first, second = tmp_path / "first", tmp_path / "second"
    for target in (first, second):
        assert gen.main(["--mode", "zombie-demo", "--seed", "42", "--out-dir", str(target)]) == 0
    written = (first / gen.ZOMBIE_DEMO_FILE).read_bytes()
    assert written == (second / gen.ZOMBIE_DEMO_FILE).read_bytes()
    assert written == gen.build_zombie_demo_csv(42).encode("utf-8")
    assert gen.ZOMBIE_DEMO_FILE == "zombie_demo_statement.csv"
    assert gen.build_zombie_demo_csv(43) != gen.build_zombie_demo_csv(42)


def test_zombie_demo_mode_is_registered_and_not_a_stub() -> None:
    """MODE_HANDLERS maps zombie-demo to the real handler."""
    assert gen.MODE_HANDLERS["zombie-demo"] is gen.run_zombie_demo
    assert gen.run_zombie_demo.__name__ == "run_zombie_demo"


def test_committed_demo_csv_equals_generator_output() -> None:
    """The committed demo CSV is byte-identical to the seed-42 generator output."""
    committed = DEMO_CSV.read_bytes().replace(b"\r\n", b"\n")
    assert committed == gen.build_zombie_demo_csv(42).encode("utf-8"), (
        "zombie_demo_statement.csv is stale; run: "
        "python scripts/generate_samples.py --mode zombie-demo --seed 42"
    )


# --- committed file -----------------------------------------------------------------------------


def test_demo_csv_parses_with_zero_quarantine() -> None:
    """The demo parses in the plain dialect with no quarantine, 300-400 rows, in range."""
    text = DEMO_CSV.read_bytes().decode("utf-8")
    assert text.splitlines()[0] == ",".join(gen.BANK_COLUMNS)
    transactions, quarantined = parse_csv(DEMO_CSV, dialect="plain")
    assert quarantined == []
    assert 300 <= len(transactions) <= 400
    assert all(DEMO_START <= t.date <= DEMO_END for t in transactions)
    dates = [t.date for t in transactions]
    assert dates == sorted(dates)
    assert {t.currency for t in transactions} == {"EUR"}


def test_demo_counterparties_are_fictional() -> None:
    """No real brand appears; person names occur only on transfer rows."""
    transactions, _ = parse_csv(DEMO_CSV, dialect="plain")
    persons = set(gen.ZOMBIE_PERSON_COUNTERPARTIES)
    assert len(persons) >= 3
    for t in transactions:
        upper = t.counterparty.upper()
        assert not [brand for brand in REAL_BRAND_DENY_LIST if brand in upper], t.counterparty
        if t.counterparty in persons:
            assert t.description.startswith("Transfer"), t.source_ref
    assert {t.counterparty for t in transactions} >= persons
    credits = [t for t in transactions if t.flow == "credit"]
    assert credits and {t.counterparty for t in credits} == {gen.ZOMBIE_SALARY_COUNTERPARTY}


def test_demo_contains_all_planted_patterns() -> None:
    """Each pattern of design §10 is present with its documented shape."""
    groups = _debit_groups()
    transactions, _ = parse_csv(DEMO_CSV, dialect="plain")
    raw_names = {t.counterparty for t in transactions}

    # E1: five charges at 12.99 then 15.99, monthly.
    e1 = groups["STREAMFLEX INTL"]
    assert _amounts(e1) == ["12.99"] * 5 + ["15.99"]
    assert set(_gaps(e1)) == {30}
    assert "STREAMFLEX INTL 4412" in raw_names

    # E2: three charges at 9.99 then three at 12.99.
    e2 = groups["CLOUDVAULT"]
    assert _amounts(e2) == ["9.99"] * 3 + ["12.99"] * 3
    assert set(_gaps(e2)) == {30}

    # E3: two interleaved monthly series with different amounts.
    assert dict(Counter(_amounts(groups["GLOWBILL"]))) == {"2.99": 6, "0.99": 6}

    # E4: two interleaved monthly series with the same amount.
    assert _amounts(groups["MUSICBOX"]) == ["10.99"] * 12

    # E5: the same service under two counterparty spellings.
    assert "STREAMFLIX INTL 7731" in raw_names
    assert "STREAMFLIXCOM" in raw_names
    assert _amounts(groups["STREAMFLIX INTL"]) == ["14.99"] * 6
    assert _amounts(groups["STREAMFLIXCOM"]) == ["14.99"] * 6

    # Free trial: a 0.49 debit 14 days before the first of six monthly 14.99 charges.
    trial = groups["SECUREPASS"]
    assert _amounts(trial) == ["0.49"] + ["14.99"] * 6
    assert (trial[1]["date"] - trial[0]["date"]).days == 14
    assert set(_gaps(trial[1:])) == {30}

    # Post-cancellation: monthly 8.99, three charges after 2026-07-31.
    gym = groups["GYMPLUS"]
    assert _amounts(gym) == ["8.99"] * 6
    assert set(_gaps(gym)) == {30}
    assert [r["date"] > date(2026, 7, 31) for r in gym].count(True) == 3

    # Zombie candidates: six monthly charges each.
    for key in ("BEATSTREAM", "PHOTOBOX", "STASHCRATE"):
        assert len(groups[key]) == 6, key
        assert set(_gaps(groups[key])) == {30}, key
    assert "BEATSTREAM P2A3B4C5" in raw_names


def test_demo_noise_merchants_follow_e7b_construction_and_produce_no_series() -> None:
    """Weekly merchants are built like E7b and no noise merchant forms a series."""
    groups = _debit_groups()
    merchants = gen.ZOMBIE_WEEKLY_MERCHANTS
    assert len(merchants) >= 5
    for merchant in merchants:
        rows = groups[normalise_counterparty(merchant.name)]
        assert len(rows) == gen.E7B_WEEKS == 26, merchant.name
        assert set(_gaps(rows)) == {7}, merchant.name
        assert rows[0]["date"] == merchant.start, merchant.name
        base = Decimal(merchant.base)
        expected = [
            round_to_cents(base * Decimal("1.11") ** ((5 * i + merchant.shift) % 13))
            for i in range(26)
        ]
        assert [r["amount"] for r in rows] == expected, merchant.name
        assert len(set(expected)) == 13, merchant.name

    for name, _description in gen.ZOMBIE_ONE_OFF_MERCHANTS:
        assert len(groups[normalise_counterparty(name)]) == 1, name

    noise_keys = {normalise_counterparty(name) for name in gen.zombie_noise_counterparties()}
    for key in noise_keys & set(groups):
        assert find_series(sorted(groups[key], key=date_key)) == [], key


def test_demo_noise_keys_do_not_collide_with_planted_keys() -> None:
    """No noise counterparty normalises to the same key as a planted subscription."""
    planted = {
        "STREAMFLEX INTL",
        "CLOUDVAULT",
        "GLOWBILL",
        "MUSICBOX",
        "STREAMFLIX INTL",
        "STREAMFLIXCOM",
        "SECUREPASS",
        "GYMPLUS",
        "BEATSTREAM",
        "PHOTOBOX",
        "STASHCRATE",
    }
    noise = [normalise_counterparty(name) for name in gen.zombie_noise_counterparties()]
    assert len(noise) == len(set(noise))
    assert planted.isdisjoint(noise)


@pytest.mark.parametrize("seed", [0, 7, 42])
def test_one_off_dates_stay_inside_the_demo_window(seed: int) -> None:
    """Whatever the seed, every generated row lies within 2026-05-01..2026-10-31."""
    rows = gen.build_zombie_demo_rows(seed)
    assert all(DEMO_START <= row.day <= DEMO_END for row in rows)
    assert 300 <= len(rows) <= 400
