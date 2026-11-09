"""Pinned checks of the committed INE CPI snapshot and of its .gitignore exception (REQ-CPI-20)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from ledger_kit.public_data import CpiSeries, load_snapshot
from ledger_kit.public_data.ine_cpi import ATTRIBUTION, LICENCE, NO_ENDORSEMENT

REPO_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = REPO_ROOT / "data" / "public" / "ine_cpi_ipc290751.json"
GITIGNORE = REPO_ROOT / ".gitignore"

D = Decimal
PINNED_ATTRIBUTION = "Elaboración propia con datos extraídos del sitio web del INE: www.ine.es"
PINNED_NO_ENDORSEMENT = "The INE does not take part in, sponsor or support this reuse."


@pytest.fixture(scope="module")
def snapshot() -> CpiSeries:
    """The committed snapshot, read through the library loader (which validates it)."""
    return load_snapshot(SNAPSHOT)


def test_the_snapshot_file_is_committed_in_the_public_folder() -> None:
    assert SNAPSHOT.is_file()


def test_series_and_base(snapshot: CpiSeries) -> None:
    assert snapshot.series_code == "IPC290751"
    assert snapshot.base_year == 2025


def test_range(snapshot: CpiSeries) -> None:
    assert snapshot.first_month == "2017-01"
    assert snapshot.last_month >= "2026-09"


def test_the_two_pinned_ine_figures(snapshot: CpiSeries) -> None:
    august = snapshot.lookup("2026-08")
    september = snapshot.lookup("2026-09")
    assert (august.value, august.status) == (D("104.638"), "Definitivo")
    assert august.is_fallback is False
    assert (september.value, september.status) == (D("104.978"), "Definitivo")
    assert str(august.value) == "104.638"
    assert str(september.value) == "104.978"
    assert september.is_fallback is False


def test_the_first_figure_of_the_series(snapshot: CpiSeries) -> None:
    assert snapshot.lookup("2017-01").value == D("79.896")


def test_licence_attribution_and_non_endorsement(snapshot: CpiSeries) -> None:
    assert snapshot.licence == LICENCE == "CC BY 4.0"
    assert snapshot.attribution == ATTRIBUTION == PINNED_ATTRIBUTION
    assert snapshot.no_endorsement == NO_ENDORSEMENT == PINNED_NO_ENDORSEMENT


def test_retrieved_on_is_an_iso_date_not_before_the_pinned_run(snapshot: CpiSeries) -> None:
    assert len(snapshot.retrieved_on) == 10
    assert snapshot.retrieved_on >= "2026-11-09"
    assert snapshot.retrieved_on[4] == snapshot.retrieved_on[7] == "-"


def test_every_value_is_positive_with_three_decimals(snapshot: CpiSeries) -> None:
    for month, value, _status in snapshot.entries:
        assert value > 0, month
        assert value.as_tuple().exponent == -3, month


def test_every_month_is_published_without_a_gap(snapshot: CpiSeries) -> None:
    assert len(snapshot.months) == len(set(snapshot.months))
    for month in snapshot.months:
        point = snapshot.lookup(month)
        assert point is not None and point.is_fallback is False


def test_the_old_series_appears_nowhere_in_the_file() -> None:
    assert "IPC251852" not in SNAPSHOT.read_text(encoding="utf-8")


def test_the_file_is_utf8_with_a_final_newline() -> None:
    """UTF-8 text ending in a newline; a CRLF checkout is accepted, so endings are not pinned."""
    raw = SNAPSHOT.read_bytes()
    raw.decode("utf-8")
    assert raw.endswith(b"\n")


# --- .gitignore (REQ-CPI-20) -------------------------------------------------------------


def test_gitignore_allows_the_public_folder_after_the_json_rule() -> None:
    lines = [line.strip() for line in GITIGNORE.read_text(encoding="utf-8").splitlines()]
    assert "*.json" in lines
    assert "!data/public/" in lines
    assert "!data/public/**" in lines
    json_rule = lines.index("*.json")
    assert lines.index("!data/public/") > json_rule
    assert lines.index("!data/public/**") > json_rule
