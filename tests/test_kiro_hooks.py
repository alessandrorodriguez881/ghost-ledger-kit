"""Checks the Kiro agent hooks and the manual steering fallback under .kiro."""

import json
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOKS_DIR = REPO_ROOT / ".kiro" / "hooks"
USAGE_STEERING = REPO_ROOT / ".kiro" / "steering" / "update-kiro-usage.md"

REQUIRED_KEYS = ("enabled", "name", "description", "version", "when", "then")
KNOWN_WHEN_TYPES = {
    "fileEdited",
    "fileCreated",
    "fileDeleted",
    "userTriggered",
    "promptSubmit",
    "agentStop",
    "preToolUse",
    "postToolUse",
    "preTaskExecution",
    "postTaskExecution",
}
FILE_WHEN_TYPES = {"fileEdited", "fileCreated", "fileDeleted"}
EXPECTED_NAMES = {"detector-guard", "samples-sync", "kiro-usage"}

HOOK_FILES = sorted(HOOKS_DIR.glob("*.kiro.hook"))


def _load(path: Path) -> dict[str, Any]:
    """Parse one hook file as JSON."""
    return json.loads(path.read_text(encoding="utf-8"))


def _by_name() -> dict[str, dict[str, Any]]:
    """Map hook name to its parsed content."""
    return {_load(path)["name"]: _load(path) for path in HOOK_FILES}


def test_hooks_directory_has_hook_files() -> None:
    """The hooks directory contains at least one hook file."""
    assert HOOK_FILES


@pytest.mark.parametrize("path", HOOK_FILES, ids=lambda p: p.name)
def test_hook_is_well_formed(path: Path) -> None:
    """Each hook parses as JSON and has the required keys, a known trigger and a prompt."""
    hook = _load(path)
    for key in REQUIRED_KEYS:
        assert key in hook, f"{path.name} lacks {key!r}"
    assert isinstance(hook["enabled"], bool)
    assert hook["name"] and hook["description"] and hook["version"]
    assert path.name == f"{hook['name']}.kiro.hook"
    assert hook["when"]["type"] in KNOWN_WHEN_TYPES
    if hook["when"]["type"] in FILE_WHEN_TYPES:
        patterns = hook["when"]["patterns"]
        assert patterns and all(isinstance(p, str) and p for p in patterns)
    assert hook["then"]["type"] == "askAgent"
    assert isinstance(hook["then"]["prompt"], str)
    assert hook["then"]["prompt"].strip()


def test_expected_hook_names_exist() -> None:
    """The three project hooks are present."""
    assert EXPECTED_NAMES <= set(_by_name())


def test_detector_guard_trigger_and_prompt() -> None:
    """detector-guard watches detectors, skips helpers and checks the CR-LC-3 property."""
    hook = _by_name()["detector-guard"]
    assert hook["when"]["type"] == "fileEdited"
    assert hook["when"]["patterns"] == ["apps/*/detectors/*.py"]
    prompt = hook["then"]["prompt"]
    assert "__init__.py" in prompt
    assert "utils.py" in prompt
    assert "loaded_source_refs" in prompt


def test_samples_sync_trigger() -> None:
    """samples-sync watches the generator and the sample data."""
    hook = _by_name()["samples-sync"]
    assert hook["when"]["type"] == "fileEdited"
    assert set(hook["when"]["patterns"]) == {"scripts/generate_samples.py", "data/samples/**"}


def test_kiro_usage_is_manual() -> None:
    """kiro-usage is triggered by the user."""
    assert _by_name()["kiro-usage"]["when"]["type"] == "userTriggered"


def test_manual_steering_has_manual_front_matter() -> None:
    """The fallback steering file starts with front matter containing inclusion: manual."""
    lines = USAGE_STEERING.read_text(encoding="utf-8").splitlines()
    assert lines[0].strip() == "---"
    end = lines.index("---", 1)
    front_matter = [line.strip() for line in lines[1:end]]
    assert "inclusion: manual" in front_matter
