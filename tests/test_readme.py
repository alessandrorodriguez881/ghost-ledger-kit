"""README.md checks: sections, real repository paths, allowed links, the Kiro table."""

import os
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
README = REPO_ROOT / "README.md"

REQUIRED_HEADINGS = (
    "Ghost Ledger Kit",
    "The problem",
    "How it works",
    "The two apps",
    "Try it",
    "Run the tests",
    "Project layout",
    "How we used Kiro",
    "Data and licence",
    "Hackathon",
)

KIRO_FEATURES = (
    "specs",
    "steering",
    "hooks",
    "mcp",
    "property-based testing",
    "powers",
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


def test_every_backticked_path_exists(text: str) -> None:
    """Each path in inline code points to a real file or folder."""
    missing: list[str] = []
    for token in _path_candidates(text):
        path = token.rstrip("/")
        if "/" in path:
            if not (REPO_ROOT / path).exists():
                missing.append(token)
        elif not (REPO_ROOT / path).exists() and not _file_exists_anywhere(path):
            missing.append(token)
    assert not missing, f"README mentions paths that do not exist: {sorted(set(missing))}"


def test_links_are_official_docs_only(text: str) -> None:
    """The only http links are the official docs of the tools the README names."""
    bad = [link for link in LINK_RE.findall(text) if not link.startswith(ALLOWED_LINK_PREFIXES)]
    assert not bad, f"README links outside the allowed docs: {bad}"


def test_no_images_and_no_badges(text: str) -> None:
    """No screenshots or badge images yet."""
    assert not re.search(r"!\[[^\]]*\]\([^)]*\)", text)
    assert "<img" not in text.lower()


def test_no_email_address(text: str) -> None:
    """The README contains no e-mail address."""
    assert not EMAIL_RE.findall(text)


def test_todo_lines_for_live_url_and_video(text: str) -> None:
    """The live URL and the demo video are clearly marked TODO until they exist."""
    todo_lines = [line for line in text.splitlines() if "TODO" in line]
    assert any("Community Cloud" in line for line in todo_lines)
    assert any("video" in line.lower() for line in todo_lines)


def _kiro_section(text: str) -> str:
    """The body of the 'How we used Kiro' section."""
    match = KIRO_SECTION_RE.search(text)
    assert match, "section 'How we used Kiro' not found"
    return match.group(1)


def _table_rows(section: str) -> list[list[str]]:
    """The cells of every row of the first Markdown table in `section`."""
    rows = []
    for line in section.splitlines():
        line = line.strip()
        if line.startswith("|") and line.endswith("|"):
            rows.append([cell.strip() for cell in line.strip("|").split("|")])
    return rows


def test_kiro_table_header_and_six_feature_rows(text: str) -> None:
    """The table has the agreed columns and one row per Kiro feature, in order."""
    rows = _table_rows(_kiro_section(text))
    assert rows[0] == ["Kiro feature", "What we did", "Why it mattered"]
    assert all(set(cell) <= set("-: ") for cell in rows[1])
    data = rows[2:]
    assert [row[0].lower() for row in data] == list(KIRO_FEATURES)
    assert all(len(row) == 3 and all(row) for row in data)


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
