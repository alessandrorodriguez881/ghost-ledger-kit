"""Tests of the Home page building blocks (haunted-design, REQ-HD-09 to REQ-HD-11).

The proof strip is read from the committed files, so these tests compare it with those files by
a second route: the JSON itself, the generated docs/benchmark.md, the sample folder and the
snapshot reader. The test count is never shown, so it is never compared.
"""

import json
import re
from pathlib import Path

import pytest
from defusedxml.ElementTree import fromstring

from ledger_kit.public_data import load_snapshot
from ledger_kit.public_data.ine_cpi import ATTRIBUTION
from ledger_kit.ui import landing
from ledger_kit.ui.landing import (
    BENCHMARK_APPS,
    DIAGRAM_STEPS,
    FACTURAE_DIR,
    NOT_AVAILABLE,
    RESULTS_PATH,
    TILES,
    XSD_CHECKED_FILES,
    Fact,
    benchmark_facts,
    cpi_fact,
    diagram_html,
    facturae_fact,
    percent_text,
    proof_facts,
    proof_strip_html,
    tiles_html,
)

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs" / "benchmark.md"


def _results() -> dict:
    """The committed benchmark results."""
    return json.loads(RESULTS_PATH.read_text(encoding="utf-8"))


# --- the four facts equal the committed files (REQ-HD-10) --------------------------------------


def test_the_benchmark_facts_are_the_committed_totals() -> None:
    data = _results()
    facts = benchmark_facts()

    assert len(facts) == len(BENCHMARK_APPS) == 2
    for fact, (key, title) in zip(facts, BENCHMARK_APPS, strict=True):
        totals = data["apps"][key]["totals"]
        assert title in fact.label
        # judge-path (REQ-JP-16): a percentage with one decimal, never the raw 0.9980
        assert fact.figure == percent_text(totals["precision"])
        assert re.fullmatch(r"\d{1,3}\.\d %", fact.figure)
        recall = percent_text(totals["recall"])
        assert f"Recall {recall} on {data['scenarios_per_app']} " in fact.note
        assert fact.source == "data/benchmark/results.json"


def test_the_benchmark_facts_agree_with_the_generated_benchmark_document() -> None:
    """A second route to the same numbers: docs/benchmark.md is written from results.json."""
    document = DOCS.read_text(encoding="utf-8")
    for fact, (_key, title) in zip(benchmark_facts(), BENCHMARK_APPS, strict=True):
        section = document.split(f"## {title}", 1)[1].split("###", 1)[0]
        match = re.search(r"precision `([0-9.]+)`, recall `([0-9.]+)`", section)
        assert match is not None
        assert fact.figure == percent_text(match.group(1))
        assert f"Recall {percent_text(match.group(2))} " in fact.note


def test_the_facturae_fact_counts_the_committed_sample_files() -> None:
    files = [item for item in FACTURAE_DIR.iterdir() if item.suffix == ".xml"]
    fact = facturae_fact()

    assert len(files) == XSD_CHECKED_FILES == 25
    assert fact.figure == "25 of 25"
    assert "official XSD" in fact.note
    assert "once" in fact.note and "not part of CI" in fact.note  # DN-RF-23, stated honestly
    assert "validate again" not in fact.note
    assert fact.source == "data/samples/phantom_demo/facturae/"


def test_the_cpi_fact_is_the_committed_snapshot() -> None:
    series = load_snapshot()
    fact = cpi_fact()

    assert fact.figure == series.series_code == "IPC290751"
    assert series.first_month in fact.note and series.last_month in fact.note
    assert f"licence {series.licence}" in fact.note
    assert fact.source == "data/public/ine_cpi_ipc290751.json"
    assert ATTRIBUTION not in fact.note  # the page shows the attribution once, in its caption


def test_the_proof_strip_has_four_facts_and_no_test_count() -> None:
    facts = proof_facts()
    text = " ".join(f"{f.label} {f.figure} {f.note} {f.source}" for f in facts)

    assert len(facts) == 4
    assert [f.figure for f in facts[:2]] == [f.figure for f in benchmark_facts()]
    assert re.search(r"\btests?\b", text, flags=re.IGNORECASE) is None
    assert NOT_AVAILABLE not in text


# --- a missing or broken file never raises (REQ-HD-11) --------------------------------------------


@pytest.mark.parametrize(
    "content",
    [None, "not json", "[]", "{}", '{"apps": {"zombie": {}, "phantom": {}}}'],
    ids=["missing", "not-json", "not-an-object", "empty-object", "no-totals"],
)
def test_unusable_benchmark_results_give_na(tmp_path: Path, content: str | None) -> None:
    path = tmp_path / "results.json"
    if content is not None:
        path.write_text(content, encoding="utf-8")

    facts = benchmark_facts(path)

    assert [f.figure for f in facts] == [NOT_AVAILABLE, NOT_AVAILABLE]
    assert all("not usable" in f.note for f in facts)


def test_a_null_ratio_in_the_results_is_shown_as_na(tmp_path: Path) -> None:
    totals = {"precision": None, "recall": "0.5000"}
    block = {"totals": totals}
    path = tmp_path / "results.json"
    path.write_text(
        json.dumps({"apps": {"zombie": block, "phantom": block}, "scenarios_per_app": 7}),
        encoding="utf-8",
    )

    facts = benchmark_facts(path)

    assert [f.figure for f in facts] == [NOT_AVAILABLE, NOT_AVAILABLE]
    assert all("Recall 50.0 % on 7 synthetic scenarios." == f.note for f in facts)


def test_a_changed_sample_folder_is_flagged(tmp_path: Path) -> None:
    for number in range(3):
        (tmp_path / f"{number}.xml").write_text("<x/>", encoding="utf-8")
    (tmp_path / "readme.txt").write_text("not a sample", encoding="utf-8")

    fact = facturae_fact(tmp_path)

    assert fact.figure == "25 of 3"
    assert "The folder has 3 files now: validate again." in fact.note


def test_a_missing_or_empty_sample_folder_gives_na(tmp_path: Path) -> None:
    assert facturae_fact(tmp_path / "nowhere").figure == NOT_AVAILABLE
    assert facturae_fact(tmp_path).figure == NOT_AVAILABLE


def test_a_broken_snapshot_gives_na(tmp_path: Path) -> None:
    for name, content in (("missing.json", None), ("bad.json", "{}")):
        path = tmp_path / name
        if content is not None:
            path.write_text(content, encoding="utf-8")
        assert cpi_fact(path).figure == NOT_AVAILABLE


def test_the_proof_facts_never_raise_when_every_file_is_missing(tmp_path: Path) -> None:
    facts = proof_facts(tmp_path / "a.json", tmp_path / "b", tmp_path / "c.json")

    assert [f.figure for f in facts] == [NOT_AVAILABLE] * 4


# --- the HTML (REQ-HD-09) ------------------------------------------------------------------------


def test_the_proof_strip_html_is_four_well_formed_cards() -> None:
    markup = proof_strip_html(proof_facts())
    root = fromstring(markup)

    assert markup.startswith('<div class="gl-grid gl-proof">')
    assert markup.count('class="gl-card"') == 4
    assert root.attrib["class"] == "gl-grid gl-proof"
    assert "\n" not in markup


def test_the_proof_strip_escapes_every_text() -> None:
    markup = proof_strip_html([Fact("<i>", "<b>", "<u>", "<s>")])

    for raw in ("<i>", "<b>", "<u>", "<s>"):
        assert raw not in markup
    fromstring(markup)


def test_three_tiles_each_with_icon_purpose_and_demo_numbers() -> None:
    markup = tiles_html()
    root = fromstring(markup)

    assert [tile.accent.key for tile in TILES] == ["zombie", "phantom", "vampire"]
    assert markup.count('class="gl-card gl-tile ') == 3
    for tile in TILES:
        assert f"gl-tile-{tile.accent.key}" in markup
        assert f"gl-icon-{tile.accent.icon}" in markup
        assert tile.accent.title in markup and tile.purpose in markup
        assert tile.purpose.count(".") == 1 and tile.purpose.endswith(".")  # one line
        assert len(tile.stats) == 2
    assert root.attrib["class"] == "gl-grid gl-tiles"


def test_the_diagram_is_a_titled_inline_svg_of_the_three_layers() -> None:
    markup = diagram_html()
    root = fromstring(markup)
    svg = next(iter(root))
    names = [child.tag.rsplit("}", 1)[1] for child in svg]

    assert svg.tag == "{http://www.w3.org/2000/svg}svg"
    assert names[0] == "title"
    assert names.count("rect") == 3 and names.count("path") == 2
    assert 'class="gl-guard"' in markup
    for step, first, second in DIAGRAM_STEPS:
        assert all(text in markup for text in (step, first, second))
    for word in ("Ingestion", "Detectors", "Explainer", "number guard", "deterministic"):
        assert word in markup
    assert "\n" not in markup
    assert landing.DIAGRAM_TITLE in markup
