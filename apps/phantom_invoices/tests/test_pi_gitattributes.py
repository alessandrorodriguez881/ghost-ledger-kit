"""Tests for the .gitattributes line of the phantom demo CSVs (Task P20, DN-10)."""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
GITATTRIBUTES = REPO_ROOT / ".gitattributes"
DEMO_LINE = "data/samples/phantom_demo/*.csv -text"
DEMO_FILES = ("suppliers.csv", "invoices.csv", "payments.csv")


def _lines() -> list[str]:
    """The lines of the repository's .gitattributes, stripped."""
    return [line.strip() for line in GITATTRIBUTES.read_text(encoding="utf-8").splitlines()]


def test_gitattributes_marks_phantom_demo_csvs_binary_like():
    lines = _lines()
    assert DEMO_LINE in lines
    above = lines[lines.index(DEMO_LINE) - 1]
    assert above.startswith("#")
    assert "DN-10" in above


@pytest.mark.parametrize("name", DEMO_FILES)
def test_git_reports_text_unset_for_each_demo_csv(name):
    if shutil.which("git") is None:
        pytest.skip("git is not on PATH")
    if not (REPO_ROOT / ".git").exists():
        pytest.skip("the project folder is not a git repository")
    path = f"data/samples/phantom_demo/{name}"
    result = subprocess.run(
        ["git", "check-attr", "text", "--", path],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"{path}: text: unset"


def test_gitattributes_does_not_touch_other_patterns():
    lines = _lines()
    demo_index = lines.index(DEMO_LINE)
    for index, line in enumerate(lines):
        tokens = line.split()
        if not tokens or tokens[0].startswith("#") or index == demo_index:
            continue
        sets_text = any(token.lstrip("-!").startswith("text") for token in tokens[1:])
        if tokens[0] == "*" and sets_text:
            # a catch-all text rule is only acceptable when the more specific line comes later
            assert index < demo_index, line
        assert "phantom_demo" not in tokens[0], line
