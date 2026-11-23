"""The INE attribution is the same in the snapshot, the READMEs, the library and the Home page.

public-cpi Task CPI10 (REQ-CPI-19): the attribution, the licence and the non-endorsement text are
written in several places; this module compares them so they cannot drift apart. Nothing here
reads the clock or the network.
"""

import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

import streamlit_app
from ledger_kit.public_data import attribution_for, bde_fees, load_fee_snapshot, load_snapshot
from ledger_kit.public_data.ine_cpi import ATTRIBUTION, LICENCE, NO_ENDORSEMENT

REPO_ROOT = Path(__file__).resolve().parents[1]
README = REPO_ROOT / "README.md"
PUBLIC_DATA_DOC = REPO_ROOT / "docs" / "public-data.md"
PUBLIC_README = REPO_ROOT / "data" / "public" / "README.md"
SAMPLES_README = REPO_ROOT / "data" / "samples" / "README.md"
SNAPSHOT = REPO_ROOT / "data" / "public" / "ine_cpi_ipc290751.json"
FEE_SNAPSHOT = REPO_ROOT / "data" / "public" / "bde_payment_account_fees.json"
GITIGNORE = REPO_ROOT / ".gitignore"
FETCH_COMMAND = "python scripts/fetch_ine_cpi.py"
IMPORT_SCRIPT = "scripts/import_bde_fees.py"
FEE_SENTENCE = (
    "The fee comparison appears once the snapshot data/public/bde_payment_account_fees.json is "
    "committed; without it the app shows no comparison."
)

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
    """Snapshot, READMEs and docs/public-data.md hold the same attribution, with no variant.

    public-fees: the Banco de España attribution also says *Elaboración propia*; a line that
    holds it must hold one of the two committed attributions verbatim, so neither may drift.
    """
    attribution = snapshot_texts[0]
    known = (attribution, load_fee_snapshot(FEE_SNAPSHOT).attribution)

    for document in (readme, public_readme, public_data_doc):
        lines = [line for line in document.splitlines() if "Elaboración propia" in line]
        assert lines, "the attribution is missing"
        assert any(attribution in line for line in lines), "the INE attribution is missing"
        variants = [line for line in lines if not any(text in line for text in known)]
        assert not variants, "a variant of the attribution exists"


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


# --- the Banco de España fee snapshot (public-fees PF7 and PF9) -------------------------------
# The facts the documents state are read from the committed snapshot, never hard-coded; no fee
# figure of the snapshot may be quoted in a document.

# A euro amount as the comparator publishes it (decimal comma, two decimals), e.g. 12,00.
_AMOUNT_TEXT = re.compile(r"\d+,\d{2}")


@pytest.fixture(scope="module")
def fee_raw() -> dict[str, Any]:
    """The committed fee snapshot as a JSON object (amounts stay strings)."""
    return json.loads(FEE_SNAPSHOT.read_text(encoding="utf-8"), parse_float=Decimal)


@pytest.fixture(scope="module")
def fee_texts() -> tuple[str, str, str]:
    """The attribution, licence note and non-endorsement texts of the committed fee snapshot."""
    snapshot = load_fee_snapshot(FEE_SNAPSHOT)
    return snapshot.attribution, snapshot.licence_note, snapshot.no_endorsement


def _section(text: str, heading: str) -> str:
    """The body of the section that starts with the line `heading`, up to the next same level."""
    level = heading.split(" ", 1)[0]
    body = text.split(f"\n{heading}\n", 1)[1]
    return body.split(f"\n{level} ", 1)[0]


def _fee_section(public_readme: str) -> str:
    """The section of data/public/README.md about the fee snapshot."""
    return _section(public_readme, "## `bde_payment_account_fees.json`")


def _readme_data_section(readme: str) -> str:
    """The Data and licence section of the root README, which holds the public data."""
    return _section(readme, "## Data and licence")


def test_the_fee_snapshot_texts_are_the_constants_of_the_reader(
    fee_raw: dict[str, Any], fee_texts: tuple[str, str, str]
) -> None:
    """The snapshot holds attribution_for of its own date, LICENCE_NOTE and NO_ENDORSEMENT."""
    assert fee_texts == (
        attribution_for(fee_raw["declaration_date"]),
        bde_fees.LICENCE_NOTE,
        bde_fees.NO_ENDORSEMENT,
    )


@pytest.mark.parametrize("name", ["README.md", "data/public/README.md"])
def test_both_readmes_carry_the_three_fee_texts_of_the_snapshot(
    name: str, fee_texts: tuple[str, str, str]
) -> None:
    """REQ-PF-19: the attribution with the real date, the licence note and the non-endorsement."""
    text = (REPO_ROOT / name).read_text(encoding="utf-8")

    for needle in fee_texts:
        assert needle in text, needle


def test_readme_paragraph_on_the_fee_comparison(
    readme: str, fee_texts: tuple[str, str, str]
) -> None:
    """The Data and licence section names the snapshot, its rule, the network and the verdict."""
    section = _readme_data_section(readme)

    assert FEE_SENTENCE in section
    for needle in fee_texts:
        assert needle in section, needle
    for needle in (
        "Banco de España",
        "`data/public/bde_payment_account_fees.json`",
        "never calls the network",
        "context, not a verdict",
        "exported by hand",
        "not covered by the repository MIT licence",
    ):
        assert needle in section, needle


def test_data_public_readme_describes_the_committed_fee_snapshot(
    public_readme: str, fee_raw: dict[str, Any]
) -> None:
    """Types, dates, counts and the Excel file of the snapshot, as the snapshot itself says."""
    section = _fee_section(public_readme)
    accounts = fee_raw["accounts"]
    entities = {(a["account_type"], a["entity_code"]) for a in accounts}

    for code in fee_raw["account_types"]:
        assert f"`{code}`" in section, code
    assert fee_raw["declaration_date"] in section
    assert fee_raw["retrieved_on"] in section
    assert f"{len(entities)} entities" in section
    assert f"{len(accounts)} accounts" in section
    assert f"{len(fee_raw['rows'])} rows" in section
    for entry in fee_raw["excel_files"]:
        assert f"`{entry['name']}`" in section
        assert f"{entry['size_bytes']} bytes" in section
        assert entry["sha256"] in section


def test_data_public_readme_says_how_the_fee_snapshot_is_made(public_readme: str) -> None:
    """By hand, local files only, the optional extra, complete types only, context only (Q6)."""
    section = _fee_section(public_readme)

    for needle in (
        IMPORT_SCRIPT,
        "exported by hand",
        "reads local files only",
        "developer machine",
        "xlrd",
        'pip install -e ".[import]"',
        "only complete account types",
        "context, not a verdict",
        "never call the network",
        "no personal data",
        "not committed",
    ):
        assert needle in section, needle


def test_no_document_says_that_the_fee_snapshot_does_not_exist_yet(
    readme: str, public_readme: str
) -> None:
    """PF9: the snapshot is committed, so no document says it does not exist yet."""
    for document in (readme, public_readme):
        assert "does not exist yet" not in document.lower()


def test_no_document_quotes_a_fee_of_the_snapshot(
    readme: str, public_readme: str, fee_raw: dict[str, Any]
) -> None:
    """The documents give counts and file facts only; no declared fee appears in them."""
    published = {row["text"] for row in fee_raw["rows"] if row["amount"] is not None}
    for section in (_fee_section(public_readme), _readme_data_section(readme)):
        quoted = set(_AMOUNT_TEXT.findall(section))
        assert not (quoted & published), sorted(quoted & published)


def test_no_document_suggests_that_the_banco_de_espana_endorses_the_apps(
    readme: str, public_readme: str
) -> None:
    """The only sentence about the Banco de España taking part is the negative one."""
    for document in (readme, public_readme):
        lowered = document.lower()
        assert "endorsed by the banco de españa" not in lowered
        assert "in partnership with the banco de españa" not in lowered
        assert "sponsored by the banco de españa" not in lowered


def test_gitignore_ignores_excel_exports_everywhere_and_keeps_the_public_folder() -> None:
    """DN-PF-20: *.xls and *.xlsx come after every exception, so no export is ever tracked."""
    lines = [line.strip() for line in GITIGNORE.read_text(encoding="utf-8").splitlines()]

    assert "*.xls" in lines and "*.xlsx" in lines
    json_rule = lines.index("*.json")
    assert lines.index("!data/public/") > json_rule
    assert lines.index("!data/public/**") > json_rule
    last_exception = max(index for index, line in enumerate(lines) if line.startswith("!"))
    assert lines.index("*.xls") > last_exception
    assert lines.index("*.xlsx") > last_exception


def test_samples_readme_names_the_fee_snapshot_among_the_public_data() -> None:
    """The pointer line of data/samples/README.md also names the Banco de España file."""
    text = SAMPLES_README.read_text(encoding="utf-8").replace("\n", " ")

    assert "Banco de España" in text
    assert "bde_payment_account_fees.json" in text
