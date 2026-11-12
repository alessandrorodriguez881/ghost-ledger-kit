"""Tooling JSON files must not be ignored by git, or a fresh clone would miss them."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

FIXED_FILES = [
    "powers/ghost-ledger-detector/plugin.json",
    ".kiro/hooks/review-gate.json",
    ".kiro/settings/mcp.json",
]
AGENT_FILES = sorted(
    p.relative_to(REPO_ROOT).as_posix() for p in (REPO_ROOT / ".kiro" / "agents").glob("*.json")
)


def _require_git_work_tree() -> None:
    """Skip the test when git is missing or the repo root is not a git work tree."""
    if shutil.which("git") is None:
        pytest.skip("git is not on PATH")
    probe = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0 or probe.stdout.strip() != "true":
        pytest.skip("the repository root is not a git work tree")


def test_agent_files_were_found() -> None:
    """The agents folder holds at least one JSON file, so the parametrised test is not empty."""
    assert AGENT_FILES


@pytest.mark.parametrize("relative_path", FIXED_FILES + AGENT_FILES)
def test_tooling_json_is_not_ignored_by_git(relative_path: str) -> None:
    """`git check-ignore -q` exits 1 (not ignored) for each tooling JSON file."""
    _require_git_work_tree()
    result = subprocess.run(
        ["git", "check-ignore", "-q", relative_path],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, (
        f"{relative_path} is ignored by git (exit {result.returncode}); "
        "add an exception to .gitignore"
    )
