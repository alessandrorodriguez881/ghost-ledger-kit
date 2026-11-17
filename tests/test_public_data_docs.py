"""The INE attribution is the same in the snapshot, the READMEs, the library and the Home page.

public-cpi Task CPI10 (REQ-CPI-19): the attribution, the licence and the non-endorsement text are
written in several places; this module compares them so they cannot drift apart. Nothing here
reads the clock or the network.
"""

from pathlib import Path

import pytest

import streamlit_app
from ledger_kit.public_data import load_snapshot
from ledger_kit.public_data.ine_cpi import ATTRIBUTION, LICENCE, NO_ENDORSEMENT

REPO_ROOT = Path(__file__).resolve().parents[1]
README = REPO_ROOT / "README.md"
PUBLIC_DATA_DOC = REPO_ROOT / "docs" / "public-data.md"
PUBLIC_README = REPO_ROOT / "data" / "public" / "README.md"
SAMPLES_README = REPO_ROOT / "data" / "samples" / "README.md"
SNAPSHOT = REPO_ROOT / "data" / "public" / "ine_cpi_ipc290751.json"
FETCH_COMMAND = "python scripts/fetch_ine_cpi.py"

PINNED_ATTRIBUTION = "Elaboración propia con datos extraídos del sitio web del INE: www.ine.es"
PINNED_NO_ENDORSEMENT = "The INE does not take part in, sponsor or support this reuse."


@pytest.fixture(scope="module")
def snapshot_texts() -> tuple[str, str, str]:
    """The attribution, licence and non-endorsement texts written in the committed snapshot."""
    series = load_snapshot(SNAPSHOT)
    return series.attribution, series.licence, series.no_endorsement


@pytest.fixture(scope="module")
def readme() -> str:
    """The root README text."""
    return README.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def public_readme() -> str:
    """The README of data/public/."""
    return PUBLIC_README.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def public_data_doc() -> str:
    """docs/public-data.md, which holds the section moved out of the root README."""
    return PUBLIC_DATA_DOC.read_text(encoding="utf-8")


def test_the_snapshot_texts_are_the_pinned_ones(snapshot_texts: tuple[str, str, str]) -> None:
    """The snapshot holds the INE-prescribed attribution, CC BY 4.0 and the non-endorsement."""
    assert snapshot_texts == (PINNED_ATTRIBUTION, "CC BY 4.0", PINNED_NO_ENDORSEMENT)


def test_library_and_home_page_constants_equal_the_snapshot(
    snapshot_texts: tuple[str, str, str],
) -> None:
    """The constants of the reader and of streamlit_app.py are the texts of the snapshot."""
    attribution, licence, no_endorsement = snapshot_texts

    assert (ATTRIBUTION, LICENCE, NO_ENDORSEMENT) == (attribution, licence, no_endorsement)
    assert streamlit_app.INE_ATTRIBUTION == attribution
    assert streamlit_app.INE_LICENCE == licence


def test_readme_carries_the_three_texts_of_the_snapshot(
    readme: str, snapshot_texts: tuple[str, str, str]
) -> None:
    """The root README repeats the attribution, the licence and the non-endorsement."""
    for text in snapshot_texts:
        assert text in readme, text


def test_public_data_doc_carries_the_three_texts_of_the_snapshot(
    public_data_doc: str, snapshot_texts: tuple[str, str, str]
) -> None:
    """docs/public-data.md repeats the attribution, the licence and the non-endorsement."""
    for text in snapshot_texts:
        assert text in public_data_doc, text


def test_data_public_readme_carries_the_three_texts_of_the_snapshot(
    public_readme: str, snapshot_texts: tuple[str, str, str]
) -> None:
    """data/public/README.md repeats the same three texts."""
    for text in snapshot_texts:
        assert text in public_readme, text


def test_the_three_sources_agree(
    readme: str, public_readme: str, public_data_doc: str, snapshot_texts: tuple[str, str, str]
) -> None:
    """Snapshot, READMEs and docs/public-data.md hold the same attribution, with no variant."""
    attribution = snapshot_texts[0]

    for document in (readme, public_readme, public_data_doc):
        lines = [line for line in document.splitlines() if "Elaboración propia" in line]
        assert lines, "the attribution is missing"
        assert all(attribution in line for line in lines), "a variant of the attribution exists"


def test_public_data_doc_says_the_apps_never_call_the_network_and_names_the_refresh_command(
    public_data_doc: str,
) -> None:
    """docs/public-data.md says the apps read a committed file, and how it is refreshed."""
    assert "never call the network" in public_data_doc
    assert FETCH_COMMAND in public_data_doc
    assert "data/public/" in public_data_doc
    assert "context, not a verdict" in public_data_doc


def test_readme_says_the_ine_data_is_not_under_the_mit_licence(
    readme: str,
) -> None:
    """The README says the INE data keeps its licence and is not covered by the MIT licence."""
    assert "not covered by the MIT licence" in readme


def test_data_public_readme_gives_the_licence_reference_and_the_refresh_command(
    public_readme: str,
) -> None:
    """Finance Rule 6: source, series, licence, refresh command, no personal data."""
    for needle in (
        "IPC290751",
        "76125",
        "CC BY 4.0",
        FETCH_COMMAND,
        "keeps the INE licence",
        "not covered by the repository MIT licence",
        "no personal data",
        "ine_cpi_ipc290751.json",
    ):
        assert needle in public_readme, needle


def test_data_public_readme_does_not_suggest_that_the_ine_endorses_the_apps(
    public_readme: str,
) -> None:
    """The only sentence about the INE taking part is the negative one of the snapshot."""
    lowered = public_readme.lower()

    assert "endorsed by the ine" not in lowered
    assert "in partnership with the ine" not in lowered
    assert "official app" not in lowered


def test_samples_readme_points_to_the_public_data_folder() -> None:
    """data/samples/README.md says official public data lives in data/public/."""
    text = SAMPLES_README.read_text(encoding="utf-8").replace("\n", " ").lower()

    assert "official public data lives in `data/public/`" in text
