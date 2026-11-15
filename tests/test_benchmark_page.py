"""Tests of the Benchmark page of streamlit_app.py (Task BM8, REQ-BM-20, REQ-BM-21).

The page only reads ``data/benchmark/results.json`` and shows it; it recomputes nothing. The
tests point ``streamlit_app.RESULTS_PATH`` at synthetic results files and run the page function
headless. No test reads the clock or the network; only the entry run reads the committed results,
because the Home page shows them in its proof strip (haunted-design).
"""

import ast
import json
from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

import streamlit_app

REPO_ROOT = Path(__file__).resolve().parents[1]
ENTRY = str(REPO_ROOT / "streamlit_app.py")
TIMEOUT_SECONDS = 60
PAGE_SCRIPT = "import streamlit_app\nstreamlit_app.benchmark()"

NO_RESULTS = "No usable benchmark results. Run: python scripts/benchmark.py"
DETECTOR_COLUMNS = [
    "Detector",
    "Planted",
    "Found",
    "Missed",
    "False alarms",
    "Precision",
    "Recall",
    "Clean scenarios with an alert",
]
NEGATIVE_COLUMNS = ["Hard negative", "Instances", "Instances with a false alarm", "False alarms"]


def _entry(labels: int, tp: int, alerts: int, precision: str | None, recall: str | None) -> dict:
    """A per-detector entry of a synthetic results file."""
    return {
        "alerts": alerts,
        "false_alarms_per_noise_scenario": "0.2500",
        "fn": labels - tp,
        "fp": alerts - tp,
        "labels": labels,
        "noise_only_alerts": 3,
        "noise_only_scenarios_with_alert": 4,
        "precision": precision,
        "recall": recall,
        "seed": 5,
        "tp": tp,
    }


def _app(price_tp: int = 7) -> dict[str, Any]:
    """A synthetic app block; the zs.price_increase row is the one of REQ-BM-20."""
    return {
        "detectors": {
            "zs.price_increase": _entry(10, price_tp, 9, "0.7778", "0.7000"),
            "zs.trial": _entry(0, 0, 0, None, None),
        },
        "errors": {},
        "false_positives": [],
        "hard_negatives": {
            "fuel_irregular": {"false_alarms": 6, "instances": 21, "instances_with_false_alarm": 5}
        },
        "misses": [],
        "noise_only_scenarios": 40,
        "scenarios": 200,
        "scenarios_detail": [],
        "seed": 5,
        "totals": {"alerts": 9, "fn": 3, "fp": 2, "labels": 10, "precision": None, "tp": 7},
        "types": {},
    }


def _results(**overrides: Any) -> dict[str, Any]:
    """A synthetic results file."""
    results: dict[str, Any] = {
        "apps": {"zombie": _app(), "phantom": _app(price_tp=1)},
        "limits": ["a", "b"],
        "matching_rule": "rule",
        "scenarios_per_app": 123,
        "schema_version": 1,
        "seed": 4242,
    }
    results.update(overrides)
    return results


@pytest.fixture
def results_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A results path inside tmp_path that the page reads instead of the committed file."""
    path = tmp_path / "results.json"
    monkeypatch.setattr(streamlit_app, "RESULTS_PATH", path)
    return path


def _page(path: Path, content: Any = None, *, raw: str | None = None) -> AppTest:
    """Write the file (JSON of ``content`` or the ``raw`` text; nothing for None) and run."""
    if raw is not None:
        path.write_text(raw, encoding="utf-8")
    elif content is not None:
        path.write_text(json.dumps(content), encoding="utf-8")
    at = AppTest.from_string(PAGE_SCRIPT, default_timeout=TIMEOUT_SECONDS).run()
    assert not at.exception
    return at


# --- the page list ------------------------------------------------------------------------------


def test_the_five_pages_in_order() -> None:
    pages = streamlit_app.PAGES

    assert [page.title for page in pages] == [
        "Home",
        "Zombie Subscriptions",
        "Phantom Invoices",
        "Vampire Fees",
        "Benchmark",
    ]
    assert pages[-1].url_path == "benchmark"
    assert pages[-1].icon == "scales"  # an icon name; the theme's CSS draws it
    assert pages[-1].script is None  # a function page: it has no app.py
    assert len({page.url_path for page in pages}) == 5


def test_every_function_page_has_a_function() -> None:
    for page in streamlit_app.PAGES:
        if page.script is None:
            assert callable(streamlit_app.FUNCTION_PAGES[page.url_path])


def test_the_results_path_is_the_committed_file() -> None:
    assert streamlit_app.RESULTS_PATH == REPO_ROOT / "data" / "benchmark" / "results.json"


def test_the_entry_runs_without_exception() -> None:
    at = AppTest.from_file(ENTRY, default_timeout=TIMEOUT_SECONDS).run()

    assert not at.exception
    assert at.title[0].value == "Ghost Ledger Kit"


# --- the page shows the file --------------------------------------------------------------------


def test_the_page_shows_the_seed_line_and_the_synthetic_note(results_path: Path) -> None:
    at = _page(results_path, _results())

    captions = [caption.value for caption in at.caption]
    assert at.title[0].value == "Benchmark"
    assert "Seed 4242; 123 scenarios per app." in captions
    assert any("synthetic" in text and "labelled" in text for text in captions)
    assert not at.error


def test_the_zombie_table_has_the_price_increase_row(results_path: Path) -> None:
    at = _page(results_path, _results())

    table = at.dataframe[0].value
    assert list(table.columns) == DETECTOR_COLUMNS
    row = table[table["Detector"] == "zs.price_increase"].iloc[0].tolist()
    assert row == ["zs.price_increase", 10, 7, 3, 2, "0.7778", "0.7000", 4]


def test_a_null_ratio_is_shown_as_na(results_path: Path) -> None:
    at = _page(results_path, _results())

    table = at.dataframe[0].value
    row = table[table["Detector"] == "zs.trial"].iloc[0].tolist()
    assert row == ["zs.trial", 0, 0, 0, 0, "n/a", "n/a", 4]


def test_each_app_has_a_detector_table_and_a_hard_negative_table(results_path: Path) -> None:
    at = _page(results_path, _results())

    assert len(at.dataframe) == 4
    assert [sub.value for sub in at.subheader] == ["Zombie Subscriptions", "Phantom Invoices"]
    negatives = at.dataframe[1].value
    assert list(negatives.columns) == NEGATIVE_COLUMNS
    assert negatives.iloc[0].tolist() == ["fuel_irregular", 21, 5, 6]


def test_the_page_reads_the_file_it_is_given(results_path: Path) -> None:
    at = _page(results_path, _results())

    zombie = at.dataframe[0].value
    phantom = at.dataframe[2].value
    assert zombie[zombie["Detector"] == "zs.price_increase"]["Found"].tolist() == [7]
    assert phantom[phantom["Detector"] == "zs.price_increase"]["Found"].tolist() == [1]


def test_the_limits_are_one_list_with_one_item_each(results_path: Path) -> None:
    at = _page(results_path, _results(limits=["a", "b"]))

    lists = [md.value for md in at.markdown if md.value.startswith("- ")]
    assert lists == ["- a\n- b"]


def test_the_page_points_to_the_documentation(results_path: Path) -> None:
    at = _page(results_path, _results())

    assert any("docs/benchmark.md" in caption.value for caption in at.caption)


# --- no usable file: one error, no exception ----------------------------------------------------

BAD_FILES = {
    "not json": "this is not json",
    "empty": "",
    "wrong schema": json.dumps({"schema_version": 99}),
    "no schema": json.dumps({"apps": {}}),
    "a list": json.dumps([1, 2]),
    "schema one but no apps": json.dumps({"schema_version": 1}),
    "an app block missing": json.dumps(_results(apps={"zombie": _app()})),
    "limits not a list": json.dumps(_results(limits="abc")),
}


def test_a_missing_file_gives_one_error(results_path: Path) -> None:
    assert not results_path.exists()

    at = _page(results_path)

    assert [error.value for error in at.error] == [NO_RESULTS]
    assert not at.dataframe


@pytest.mark.parametrize("name", list(BAD_FILES))
def test_an_unusable_file_gives_one_error(results_path: Path, name: str) -> None:
    at = _page(results_path, raw=BAD_FILES[name])

    assert [error.value for error in at.error] == [NO_RESULTS]
    assert not at.dataframe


def test_schema_version_99_with_a_full_body_gives_one_error(results_path: Path) -> None:
    at = _page(results_path, _results(schema_version=99))

    assert [error.value for error in at.error] == [NO_RESULTS]


def test_a_binary_file_gives_one_error(results_path: Path) -> None:
    results_path.write_bytes(b"\xff\xfe\x00\x01")

    at = _page(results_path)

    assert [error.value for error in at.error] == [NO_RESULTS]


# --- boundaries of the page ---------------------------------------------------------------------


def _imported_modules(path: Path) -> set[str]:
    """Every module name imported by a source file."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def test_the_entry_imports_no_runner_app_or_detector_code() -> None:
    imported = _imported_modules(REPO_ROOT / "streamlit_app.py")

    allowed = {"apps", "apps.home_tiles"}  # the one bridge to the demo data of the apps
    for name in imported - allowed:
        root = name.split(".")[0]
        assert root not in {"scripts", "apps", "pandas"}, name
        assert not name.startswith("ledger_kit.detectors"), name
    assert "apps.home_tiles" in imported


def test_the_entry_reads_the_results_with_the_standard_library_json() -> None:
    assert "json" in _imported_modules(REPO_ROOT / "streamlit_app.py")
