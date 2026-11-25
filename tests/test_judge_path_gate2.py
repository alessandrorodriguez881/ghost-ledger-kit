"""Session s51 (REQ-JP-30): the honesty and documentation fixes of the gate-2 review.

Pins the size sentence of the README against a recount of ``ledger_kit/``, the first-version
wording of the Vampire Fees record, the exceptions of the Kiro line in *Who did what*, the demo
format caption of the three apps, and the lines that had gone stale. Pure tests: no page run, no
model, no network.
"""

import ast
import importlib.util
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from types import ModuleType

import pandas as pd
import pytest

import streamlit_app
from ledger_kit.models import Alert
from ledger_kit.ui.first_run import DEMO_FORMAT_CAPTION

ROOT = Path(__file__).resolve().parents[1]
LEDGER_KIT = ROOT / "ledger_kit"
README = (ROOT / "README.md").read_text(encoding="utf-8")
HOW_IT_WORKS = (ROOT / "docs" / "how-it-works.md").read_text(encoding="utf-8")
DEVELOPING = (ROOT / "docs" / "developing.md").read_text(encoding="utf-8")
SCAN_SCRIPT = ROOT / "scripts" / "ledger_scan.py"
APP_FILES = tuple(
    ROOT / "apps" / name / "app.py"
    for name in ("zombie_subscriptions", "phantom_invoices", "vampire_fees")
)

# A README figure may be off by this share of the recounted lines (the figures are rounded).
SIZE_TOLERANCE = 0.10

# The core every app uses: the models, the detector registry, the explainer and the guard helpers
# it imports, and the money helpers the guard formats amounts with.
CORE_FILES = (
    "models.py",
    "explainer.py",
    "calc.py",
    "number_words.py",
    "index_cause.py",
    "utils/money.py",
)
CORE_FOLDERS = ("detectors",)
SPANISH_READERS = (
    "ingestion/norma43_reader.py",
    "ingestion/facturae_reader.py",
    "ingestion/iso4217.py",
)

# The phrase of the README sentence that holds each figure.
SIZE_PATTERNS = {
    "core": r"a core of about ([\d,]+) lines",
    "spanish": r"about ([\d,]+) lines of Spanish format readers",
    "public": r"about ([\d,]+) lines of public data",
    "ui": r"about ([\d,]+) lines of shared UI",
    "rest": r"about ([\d,]+) lines for the rest",
}


def _lines(paths: Iterable[Path]) -> int:
    """Physical lines of the files, as an editor numbers them."""
    return sum(len(path.read_text(encoding="utf-8").splitlines()) for path in paths)


def _in(folder: str) -> set[Path]:
    """Every .py file under one folder of ledger_kit."""
    return set((LEDGER_KIT / folder).rglob("*.py"))


def _groups() -> dict[str, set[Path]]:
    """The files of each group of the size sentence; `rest` is everything else."""
    core = {LEDGER_KIT / name for name in CORE_FILES}
    for folder in CORE_FOLDERS:
        core |= _in(folder)
    groups = {
        "core": core,
        "spanish": {LEDGER_KIT / name for name in SPANISH_READERS},
        "public": _in("public_data"),
        "ui": _in("ui"),
    }
    counted = set().union(*groups.values())
    groups["rest"] = set(LEDGER_KIT.rglob("*.py")) - counted
    return groups


def _size_sentence() -> str:
    """The README paragraph that states the size of ledger_kit."""
    [paragraph] = [p for p in README.split("\n\n") if "a core of about" in p]
    return paragraph


# --- the size of the template ---------------------------------------------------------------


def test_every_counted_file_exists_and_the_groups_do_not_overlap() -> None:
    groups = _groups()

    for paths in groups.values():
        assert paths and all(path.is_file() for path in paths)
    every = [path for paths in groups.values() for path in paths]
    assert len(every) == len(set(every)) == len(set(LEDGER_KIT.rglob("*.py")))


@pytest.mark.parametrize("group", list(SIZE_PATTERNS))
def test_the_readme_size_figure_is_within_ten_percent_of_a_recount(group: str) -> None:
    match = re.search(SIZE_PATTERNS[group], _size_sentence())
    assert match, f"the README states no figure for {group}"
    stated = int(match.group(1).replace(",", ""))
    counted = _lines(_groups()[group])

    assert abs(stated - counted) <= SIZE_TOLERANCE * counted, (group, stated, counted)


def test_the_size_sentence_names_the_files_it_counts_and_this_test() -> None:
    sentence = _size_sentence()

    for name in (*CORE_FILES[:-1], "detectors/", "ledger_kit/utils/money.py"):
        assert f"`{name}`" in sentence, name
    for name in ("norma43_reader.py", "facturae_reader.py", "iso4217.py"):
        assert f"`{name}`" in sentence, name
    for folder in ("ledger_kit/ingestion/", "ledger_kit/public_data/", "ledger_kit/ui/"):
        assert f"`{folder}`" in sentence, folder
    assert "physical lines" in sentence and "10 percent" in sentence
    assert "`tests/test_judge_path_gate2.py`" in sentence
    assert README.index(sentence) > README.index("\n## The three apps")
    assert README.index(sentence) < README.index("\n## How we used Kiro")


# --- Vampire Fees: the six calls were the first version -------------------------------------


def test_every_mention_of_the_six_calls_says_first_version() -> None:
    for document in (README, HOW_IT_WORKS):
        parts = re.split(r"\n\s*\n|\n\||\n- ", document)
        paragraphs = [part for part in parts if "6 Kiro calls" in part]
        assert paragraphs
        for paragraph in paragraphs:
            assert "first version" in paragraph, paragraph[:80]


def _unqualified(document: str, phrase: str) -> list[int]:
    """Positions of `phrase` in `document` not directly preceded by `first version of `."""
    qualifier = "first version of "
    found: list[int] = []
    for match in re.finditer(re.escape(phrase), document):
        before = document[: match.start()].lower()
        if not before.endswith(qualifier):
            found.append(match.start())
    return found


def test_no_document_says_the_agent_built_the_whole_app() -> None:
    claims = (
        "which built the Vampire Fees app",
        "It built the Vampire Fees app",
        "Vampire Fees was built by the custom agent",
    )
    for document in (README, HOW_IT_WORKS):
        for claim in claims:
            assert not _unqualified(document, claim), claim
        assert "normal Kiro sessions" in document


def test_the_whole_app_claim_check_reads_the_qualifier() -> None:
    claim = "Vampire Fees was built by the custom agent"
    assert not _unqualified(f"The first version of {claim}.", claim)
    assert _unqualified(f"The {claim}.", claim)
    assert _unqualified(f"The first version was fine. {claim}.", claim)


def test_the_readme_cites_the_record_and_its_commit() -> None:
    assert "task VF17 in `.kiro/specs/vampire-fees/tasks.md`, commit `e0d38b9`" in README


# --- Who did what: the Kiro line names its exceptions ---------------------------------------


def test_the_kiro_line_names_what_claude_code_wrote_and_recorded() -> None:
    [line] = [x for x in README.splitlines() if x.startswith("- **Kiro (CLI")]

    assert "wrote every spec, test and line of code in this repository" in line
    assert "`kiro_prompts/`" in line and "`run_kiro.ps1`" in line
    assert "four GIF files in `docs/img/`" in line
    assert line.count("Claude Code") == 2
    assert "the reviewer filled in only the records of Kiro calls" in line
    assert len(list((ROOT / "docs" / "img").glob("*.gif"))) == 4


# --- the demo format selector ----------------------------------------------------------------


def test_the_caption_says_the_demo_loads_on_load_demo_data() -> None:
    assert "Load demo data" in DEMO_FORMAT_CAPTION
    assert not re.search(r"\d", DEMO_FORMAT_CAPTION)


def _sidebar_calls(path: Path) -> list[str]:
    """The Streamlit calls of an app's `_render_sidebar`, in source order, as short names."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    [function] = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_render_sidebar"
    ]
    calls: list[tuple[int, int, str]] = []
    for node in ast.walk(function):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            first = node.args[0] if node.args else None
            label = first.id if isinstance(first, ast.Name) else ""
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                label = first.value
            calls.append((node.lineno, node.col_offset, f"{node.func.attr}:{label}"))
    return [name for _line, _col, name in sorted(calls)]


@pytest.mark.parametrize("path", APP_FILES, ids=lambda p: p.parent.name)
def test_each_app_draws_the_caption_between_the_selector_and_the_button(path: Path) -> None:
    calls = _sidebar_calls(path)
    radio = calls.index("radio:Demo format")

    assert calls[radio + 1] == "caption:DEMO_FORMAT_CAPTION"
    assert calls[radio + 2] == "button:Load demo data"
    assert calls.count("caption:DEMO_FORMAT_CAPTION") == 1


def test_readme_step_3_says_the_other_demos_load_on_load_demo_data() -> None:
    [step] = [x for x in README.splitlines() if x.startswith("3. ")]

    assert "the Real formats and Norma 43 demos have no recording" in step
    assert "choose them in the sidebar and press **Load demo data**" in step


# --- stale lines -----------------------------------------------------------------------------


def _layout_line(start: str) -> str:
    [line] = [x for x in DEVELOPING.splitlines() if x.startswith(start)]
    return line


def test_the_layout_names_the_bde_snapshot_and_every_gif() -> None:
    assert "Banco de España" in _layout_line("data/public/")
    docs = _layout_line("docs/ ")
    for gif in (ROOT / "docs" / "img").glob("*.gif"):
        assert gif.name in docs, gif.name
    assert "the image in the README" not in docs


def test_the_readme_says_the_fee_snapshot_is_committed() -> None:
    assert "appears once the snapshot" not in README
    assert "`data/public/bde_payment_account_fees.json` is committed" in README
    assert (ROOT / "data" / "public" / "bde_payment_account_fees.json").is_file()


def test_the_entry_page_docstring_names_all_three_apps() -> None:
    doc = streamlit_app.__doc__ or ""

    assert "both apps" not in doc
    assert "all three apps are named ``app.py``" in " ".join(doc.split())


@pytest.fixture(scope="module")
def scan_module() -> ModuleType:
    """Load scripts/ledger_scan.py by path, as the command line would run it."""
    spec = importlib.util.spec_from_file_location("ledger_scan", SCAN_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["ledger_scan"] = module
    spec.loader.exec_module(module)
    return module


def test_the_scan_keys_in_the_docs_are_the_keys_of_the_real_output(
    scan_module: ModuleType,
) -> None:
    alert = Alert(detector="x.y", severity="info", title="t", source_refs=["f.csv:0"], data={})
    found = scan_module.Found("zombie_subscriptions", alert, pd.DataFrame(), None, [], None, None)
    keys = [
        *scan_module.scan_json(scan_module.Scan([], [])),
        *scan_module.FileReport("f.csv").as_json(),
        *scan_module.alert_json(found),
        *scan_module.check_json(scan_module.Scan([], []), "x", "t"),
    ]
    section = DEVELOPING.split("## Scan files from the command line", 1)[1].split("\n## ", 1)[0]
    named = set(re.findall(r"`([a-z_0-9]+)`", section))

    assert "alert_id" in keys
    for key in set(keys):
        assert key in named, key
    assert "with its id," not in section
