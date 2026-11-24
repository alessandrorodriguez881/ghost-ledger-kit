"""README.md and docs checks: sections, real repository paths, allowed links, the Kiro table."""

import os
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
README = REPO_ROOT / "README.md"
DOCS = REPO_ROOT / "docs"
HOME_MOMENT = "docs/img/home_moment.gif"
HOME_MOMENT_ALT = (
    "Home: a recorded answer of llama3.2:3b invents 5% and 617.51, and the number guard "
    "strikes both out"
)
MAX_IMAGE_BYTES = 2 * 1024 * 1024

REQUIRED_HEADINGS = (
    "Ghost Ledger Kit",
    "Kiro at a glance",
    "For judges: 60 seconds",
    "The three apps",
    "How we used Kiro",
    "Who did what",
    "What the guard does not check",
    "More detail",
    "Data and licence",
    "Hackathon",
)

# Docs files that received sections moved out of the README, with their headings in order.
DOCS_HEADINGS = {
    "how-it-works.md": (
        "How Ghost Ledger Kit works",
        "The problem",
        "How it works",
        "The three apps",
        "Vampire Fees in detail",
        "Benchmark: does it catch what it should, and stay quiet when it should?",
    ),
    "real-formats.md": ("Real Spanish formats", "Real Spanish formats"),
    "public-data.md": ("Public data", "Public context: the INE consumer price index"),
    "developing.md": (
        "Developing Ghost Ledger Kit",
        "Try it",
        "Scan files from the command line",
        "Run the tests",
        "Project layout",
    ),
}
DOC_FILES = tuple(DOCS / name for name in DOCS_HEADINGS)
DOC_IDS = tuple(DOCS_HEADINGS)

KIRO_FEATURES = (
    "specs",
    "steering",
    "hooks",
    "mcp",
    "property-based testing",
    "powers",
    "custom agent",
    "kiro cli",
    "spec-driven versus vibe coding",
)

# Official documentation of the tools the README names; nothing else may be linked.
ALLOWED_LINK_PREFIXES = (
    "https://kiro.dev/docs",
    "https://docs.streamlit.io",
    "https://docs.pytest.org",
    "https://hypothesis.readthedocs.io",
    "https://docs.astral.sh/ruff",
)

PATH_SUFFIXES = {".py", ".md", ".toml", ".txt", ".csv", ".json", ".hook", ".example"}
ROOT_FILE_NAMES = {"LICENSE"}
SKIPPED_DIRS = {".git", ".venv", "__pycache__", ".hypothesis", ".ruff_cache", ".pytest_cache"}

FENCE_RE = re.compile(r"^```.*?^```[ \t]*$", re.DOTALL | re.MULTILINE)
INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
HEADING_RE = re.compile(r"^#{1,6}[ \t]+(.+?)[ \t]*$", re.MULTILINE)
LINK_RE = re.compile(r"https?://[^\s)\]>\"']+")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
KIRO_SECTION_RE = re.compile(
    r"^## How we used Kiro[ \t]*$(.*?)(?=^## |\Z)", re.MULTILINE | re.DOTALL
)


@pytest.fixture(scope="module")
def text() -> str:
    """The README text."""
    return README.read_text(encoding="utf-8")


def _without_fences(text: str) -> str:
    """The README with fenced code blocks removed."""
    return FENCE_RE.sub("", text)


def _file_exists_anywhere(name: str) -> bool:
    """True when a file or folder with this bare name exists somewhere in the repository."""
    for _dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIPPED_DIRS]
        if name in filenames or name in dirnames:
            return True
    return False


def _path_candidates(text: str) -> list[str]:
    """Inline-code tokens that look like repository paths."""
    found: list[str] = []
    for token in INLINE_CODE_RE.findall(_without_fences(text)):
        if re.search(r"[\s*<>:$=]", token) or token.startswith(("http", "-")):
            continue
        if "/" in token or Path(token).suffix in PATH_SUFFIXES or token in ROOT_FILE_NAMES:
            found.append(token)
    return found


def test_readme_exists() -> None:
    """The README is in the repository root and is not empty."""
    assert README.is_file()
    assert README.read_text(encoding="utf-8").strip()


def test_readme_has_every_required_heading(text: str) -> None:
    """Every required section heading is present."""
    headings = {h.strip() for h in HEADING_RE.findall(_without_fences(text))}
    missing = [h for h in REQUIRED_HEADINGS if h not in headings]
    assert not missing, f"README is missing the headings: {missing}"


def test_readme_title_is_the_first_heading(text: str) -> None:
    """The title is the first heading of the file."""
    first = HEADING_RE.findall(_without_fences(text))[0]
    assert first == "Ghost Ledger Kit"


def test_readme_mentions_repository_paths(text: str) -> None:
    """The path check below is not vacuous."""
    assert len(_path_candidates(text)) >= 10


def _missing_paths(text: str) -> list[str]:
    """The backticked paths of a text that point to no file or folder."""
    missing: list[str] = []
    for token in _path_candidates(text):
        path = token.rstrip("/")
        if "/" in path:
            if not (REPO_ROOT / path).exists():
                missing.append(token)
        elif not (REPO_ROOT / path).exists() and not _file_exists_anywhere(path):
            missing.append(token)
    return sorted(set(missing))


def _bad_links(text: str) -> list[str]:
    """The http links of a text that are not the allowed official docs."""
    return [link for link in LINK_RE.findall(text) if not link.startswith(ALLOWED_LINK_PREFIXES)]


def test_every_backticked_path_exists(text: str) -> None:
    """Each path in inline code points to a real file or folder."""
    missing = _missing_paths(text)
    assert not missing, f"README mentions paths that do not exist: {missing}"


def test_links_are_official_docs_only(text: str) -> None:
    """The only http links are the official docs of the tools the README names."""
    bad = _bad_links(text)
    assert not bad, f"README links outside the allowed docs: {bad}"


def test_the_only_image_is_the_home_moment_and_there_is_no_badge(text: str) -> None:
    """One markdown image, docs/img/home_moment.gif, under 2 MB; no badge and no img tag."""
    images = re.findall(r"!\[([^\]]*)\]\(([^)]*)\)", text)
    assert images == [(HOME_MOMENT_ALT, HOME_MOMENT)]
    gif = REPO_ROOT / HOME_MOMENT
    assert gif.is_file()
    assert gif.stat().st_size < MAX_IMAGE_BYTES
    assert "shields.io" not in text.lower()
    assert "<img" not in text.lower()


def test_no_email_address(text: str) -> None:
    """The README contains no e-mail address."""
    assert not EMAIL_RE.findall(text)


# --- the docs files that received the moved sections --------------------------------------------


@pytest.mark.parametrize("path", DOC_FILES, ids=DOC_IDS)
def test_docs_file_exists_with_its_headings(path: Path) -> None:
    """Each new docs file exists and has, in order, the headings it received."""
    assert path.is_file()
    doc = path.read_text(encoding="utf-8")
    headings = [h.strip() for h in HEADING_RE.findall(_without_fences(doc))]
    assert tuple(headings) == DOCS_HEADINGS[path.name]


@pytest.mark.parametrize("path", DOC_FILES, ids=DOC_IDS)
def test_docs_file_starts_with_a_title_and_a_link_back_to_the_readme(path: Path) -> None:
    """Line 1 is a level 1 heading; the next line with text links the root README."""
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert lines[0] == f"# {DOCS_HEADINGS[path.name][0]}"
    assert "](../README.md)" in lines[1]


@pytest.mark.parametrize("path", DOC_FILES, ids=DOC_IDS)
def test_docs_file_backticked_paths_exist(path: Path) -> None:
    """Each path in inline code of a docs file points to a real file or folder."""
    missing = _missing_paths(path.read_text(encoding="utf-8"))
    assert not missing, f"{path.name} mentions paths that do not exist: {missing}"


@pytest.mark.parametrize("path", DOC_FILES, ids=DOC_IDS)
def test_docs_file_links_are_official_docs_only(path: Path) -> None:
    """A docs file links no http address outside the allowed official docs."""
    bad = _bad_links(path.read_text(encoding="utf-8"))
    assert not bad, f"{path.name} links outside the allowed docs: {bad}"


@pytest.mark.parametrize("path", DOC_FILES, ids=DOC_IDS)
def test_docs_file_has_no_email_address(path: Path) -> None:
    """A docs file contains no e-mail address."""
    assert not EMAIL_RE.findall(path.read_text(encoding="utf-8"))


def test_more_detail_names_every_docs_file(text: str) -> None:
    """The More detail section links each docs file that holds a moved section."""
    section = text.split("## More detail", 1)[1].split("\n## ", 1)[0]
    for name in (*DOCS_HEADINGS, "benchmark.md", "live-guard.md"):
        assert f"(docs/{name})" in section, name


def test_live_url_and_video_lines_say_they_do_not_exist_yet(text: str) -> None:
    """The live app and demo video lines say they are not deployed or recorded yet; no TODO."""
    lines = text.splitlines()
    live = [line for line in lines if line.startswith("- Live app:")]
    video = [line for line in lines if line.startswith("- Demo video:")]
    assert any("not deployed yet" in line and "Community Cloud" in line for line in live)
    assert any("not recorded yet" in line for line in video)
    assert not [line for line in lines if "TODO" in line]


def _kiro_section(text: str) -> str:
    """The body of the 'How we used Kiro' section."""
    match = KIRO_SECTION_RE.search(text)
    assert match, "section 'How we used Kiro' not found"
    return match.group(1)


def _table_rows(section: str) -> list[list[str]]:
    """The cells of every row of the Kiro feature table (the one headed 'Kiro feature')."""
    rows: list[list[str]] = []
    started = False
    for line in section.splitlines():
        line = line.strip()
        is_row = line.startswith("|") and line.endswith("|")
        if not started:
            started = is_row and line.strip("|").split("|")[0].strip() == "Kiro feature"
        elif not is_row:
            break
        if started:
            rows.append([cell.strip() for cell in line.strip("|").split("|")])
    return rows


def test_kiro_table_header_and_feature_rows(text: str) -> None:
    """The table has the agreed columns and one row per Kiro feature, in order."""
    rows = _table_rows(_kiro_section(text))
    assert rows[0] == ["Kiro feature", "What we did", "Why it mattered"]
    assert all(set(cell) <= set("-: ") for cell in rows[1])
    data = rows[2:]
    assert [row[0].lower() for row in data] == list(KIRO_FEATURES)
    assert all(len(row) == 3 and all(row) for row in data)


def test_kiro_at_a_glance_is_short_first_and_states_the_real_spec_count(text: str) -> None:
    """The glance table comes before the judges section, has at most 7 rows, right spec count."""
    start = text.index("\n## Kiro at a glance")
    assert start < text.index("\n## For judges: 60 seconds")
    section = text[start + 1 :].split("\n## ", 1)[0]
    rows = [r for r in section.splitlines() if r.strip().startswith("|")]
    assert 3 <= len(rows) <= 2 + 7  # header and separator, then at most seven rows
    match = re.search(r"(\d+) specs", section)
    assert match, "the glance table states no spec count"
    specs = [p for p in (REPO_ROOT / ".kiro" / "specs").iterdir() if p.is_dir()]
    assert int(match.group(1)) == len(specs)


def test_mcp_row_is_planned_unless_config_exists(text: str) -> None:
    """MCP is marked planned unless .kiro/settings/mcp.json exists."""
    mcp_row = next(r for r in _table_rows(_kiro_section(text))[2:] if r[0].lower() == "mcp")
    if not (REPO_ROOT / ".kiro" / "settings" / "mcp.json").exists():
        assert "planned" in mcp_row[1].lower()


def test_mcp_row_cites_the_api_checks_document(text: str) -> None:
    """The MCP row points to docs/mcp-api-checks.md and that file exists."""
    mcp_row = next(r for r in _table_rows(_kiro_section(text))[2:] if r[0].lower() == "mcp")
    assert "docs/mcp-api-checks.md" in mcp_row[1]
    assert (REPO_ROOT / "docs" / "mcp-api-checks.md").is_file()
