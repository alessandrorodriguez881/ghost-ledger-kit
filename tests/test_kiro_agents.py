"""Checks the Kiro custom agent .kiro/agents/ghost-ledger-builder.json (session 13a).

The agent is configuration, not code: these tests only prove that the JSON parses, has the
fields Kiro reads, cannot run a shell, and that every file or glob it points to exists, so a
renamed steering file or a moved skill is caught in CI instead of at agent start.
Relative paths in ``resources`` and ``prompt`` resolve from the workspace (repository) root, not
from the folder of the agent file. Checked with a probe on 10 November 2026: an agent that used
``file://../steering/...`` and ``skill://../../powers/...`` loaded only the always-included
steering files, while an agent with ``file://README.md`` and
``skill://powers/ghost-ledger-detector/skills/add-detector/SKILL.md`` loaded the README and the
add-detector skill. The JSON must also be UTF-8 without a byte order mark: Kiro rejects a BOM.
"""

import glob
import json
import os
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTS_DIR = REPO_ROOT / ".kiro" / "agents"
AGENT_FILE = AGENTS_DIR / "ghost-ledger-builder.json"
STEERING_DIR = REPO_ROOT / ".kiro" / "steering"
SKILL_DIR = REPO_ROOT / "powers" / "ghost-ledger-detector" / "skills" / "add-detector"

FILE_SCHEME = "file://"
SKILL_SCHEME = "skill://"
GLOB_CHARACTERS = frozenset("*?[")

# Tools the agent may hold: reading, writing and the context7 documentation server. Anything that
# runs a command or reaches the open web is excluded on purpose (the human runs the commands).
ALLOWED_TOOLS = frozenset({"read", "write", "@context7"})
FORBIDDEN_TOOLS = frozenset(
    {
        "shell",
        "web",
        "subagent",
        "knowledge",
        "*",
        "@builtin",
        "@mcp",
        "execute_bash",
        "execute_pwsh",
    }
)
# Permission capabilities that would give the agent a shell, directly or as a meta capability.
SHELL_CAPABILITIES = frozenset({"shell", "all", "builtin"})

# Kiro limits for file:// resources (configuration reference, CLI 3.1 and IDE 1.4.86).
MAX_FILE_RESOURCES = 32
MAX_TOTAL_CHARACTERS = 100_000
MAX_FILE_CHARACTERS = 50_000

# Phrases the recipe must keep, so that an edit cannot silently drop a rule of the template.
RECIPE_PHRASES: tuple[str, ...] = (
    "EARS",
    "REQ-<XX>-nn",
    "test-first",
    "apps/<name>/",
    "@register(",
    "namespace",
    "source_refs",
    "UPPER_SNAKE_CASE",
    "loaded_source_refs",
    "max_examples=200",
    "read_bank_statement",
    "explain_with_meta",
    "Simulate a hallucinating LLM",
    "number guard",
    "reference_app.py",
    "scripts/generate_samples.py",
    "Norma 43",
    "streamlit_app.py",
    "Never edit anything under `ledger_kit/`",
    "another app",
    "cannot run commands",
)


@pytest.fixture(scope="module")
def agent() -> dict[str, Any]:
    """The parsed agent configuration."""
    return json.loads(AGENT_FILE.read_text(encoding="utf-8"))


def _resolve(uri: str, scheme: str, base: Path = REPO_ROOT) -> list[Path]:
    """Files a resource URI points to, resolved from base; a glob may match many."""
    target = uri.removeprefix(scheme)
    pattern = target if os.path.isabs(target) else os.path.join(base, target)
    if GLOB_CHARACTERS & set(target):
        return [Path(match) for match in sorted(glob.glob(pattern, recursive=True))]
    path = Path(os.path.normpath(pattern))
    return [path] if path.exists() else []


def _file_resources(agent: dict[str, Any]) -> list[str]:
    """The file:// entries of resources."""
    return [r for r in agent["resources"] if isinstance(r, str) and r.startswith(FILE_SCHEME)]


def _skill_resources(agent: dict[str, Any]) -> list[str]:
    """The skill:// entries of resources."""
    return [r for r in agent["resources"] if isinstance(r, str) and r.startswith(SKILL_SCHEME)]


def _file_paths(agent: dict[str, Any]) -> set[Path]:
    """Every file the file:// resources resolve to."""
    return {path for uri in _file_resources(agent) for path in _resolve(uri, FILE_SCHEME)}


def test_agent_file_parses_and_has_the_required_fields(agent: dict[str, Any]) -> None:
    """name, description, prompt, tools, resources, includeMcpJson and welcomeMessage exist."""
    for key in (
        "name",
        "description",
        "prompt",
        "tools",
        "resources",
        "includeMcpJson",
        "welcomeMessage",
    ):
        assert key in agent, key
    assert agent["name"] == AGENT_FILE.stem
    assert isinstance(agent["description"], str) and agent["description"].strip()
    assert isinstance(agent["welcomeMessage"], str) and agent["welcomeMessage"].strip()
    assert isinstance(agent["resources"], list) and agent["resources"]


def test_prompt_is_a_file_uri_to_the_existing_markdown_recipe(agent: dict[str, Any]) -> None:
    """The prompt is a file URI relative to the agent folder, to the markdown next to the JSON."""
    assert agent["prompt"] == "file://./ghost-ledger-builder.md"
    # The prompt resolves from the agent folder; resources resolve from the repository root.
    found = _resolve(agent["prompt"], FILE_SCHEME, AGENTS_DIR)
    assert found == [AGENTS_DIR / "ghost-ledger-builder.md"]
    assert found[0].read_text(encoding="utf-8").strip()


def test_agent_json_has_no_byte_order_mark_and_no_parent_relative_paths(
    agent: dict[str, Any],
) -> None:
    """Kiro rejects a BOM, and '../' paths do not resolve (probe of 10 November 2026)."""
    assert not AGENT_FILE.read_bytes().startswith(b"\xef\xbb\xbf")
    uris = [agent["prompt"], *[r for r in agent["resources"] if isinstance(r, str)]]
    assert not [uri for uri in uris if ".." in uri]


def test_tools_exclude_shell_and_everything_that_runs_commands(agent: dict[str, Any]) -> None:
    """Only read, write and the context7 server are allowed; no shell, web or wildcard."""
    tools = agent["tools"]

    assert isinstance(tools, list) and all(isinstance(tool, str) for tool in tools)
    assert {"read", "write"} <= set(tools)
    assert set(tools) <= ALLOWED_TOOLS
    assert set(tools).isdisjoint(FORBIDDEN_TOOLS)
    assert not any("shell" in tool.lower() or "bash" in tool.lower() for tool in tools)


def test_permissions_do_not_grant_a_shell(agent: dict[str, Any]) -> None:
    """If the agent ever gains a permissions block, it must not allow the shell capability."""
    rules = agent.get("permissions", {}).get("rules", [])
    for rule in rules:
        allows = rule.get("effect") == "allow"
        assert not (allows and rule.get("capability") in SHELL_CAPABILITIES), rule


def test_include_mcp_json_is_true_so_context7_can_be_used(agent: dict[str, Any]) -> None:
    """includeMcpJson is the boolean true, and the tool list names the context7 server."""
    assert agent["includeMcpJson"] is True
    assert "@context7" in agent["tools"]


def test_every_file_resource_exists(agent: dict[str, Any]) -> None:
    """Each file:// entry resolves from the repository root to at least one existing file."""
    uris = _file_resources(agent)

    assert uris
    for uri in uris:
        found = _resolve(uri, FILE_SCHEME)
        assert found, f"{uri} matches no file"
        assert all(path.is_file() for path in found), uri


def test_resources_include_every_steering_file_and_the_readme(agent: dict[str, Any]) -> None:
    """A steering file added later must be added to the agent too (the set is compared)."""
    paths = _file_paths(agent)
    steering = set(STEERING_DIR.glob("*.md"))

    assert steering, "no steering file found"
    assert steering <= paths, sorted(p.name for p in steering - paths)
    assert (REPO_ROOT / "README.md") in paths


def test_skill_resource_points_to_the_add_detector_skill(agent: dict[str, Any]) -> None:
    """The skill URI resolves to the SKILL.md of the local power, whose front matter names it."""
    uris = _skill_resources(agent)

    assert len(uris) == 1
    found = _resolve(uris[0], SKILL_SCHEME)
    assert found == [SKILL_DIR / "SKILL.md"]
    text = found[0].read_text(encoding="utf-8")
    assert text.startswith("---")
    assert "name: add-detector" in text.split("---", 2)[1]
    assert (REPO_ROOT / "powers" / "ghost-ledger-detector" / "plugin.json").is_file()


def test_file_resources_stay_inside_the_kiro_loading_limits(agent: dict[str, Any]) -> None:
    """At most 32 files, 100.000 characters in total and 50.000 per file, or Kiro drops files."""
    paths = sorted(_file_paths(agent))
    sizes = {p: len(p.read_text(encoding="utf-8")) for p in paths}

    assert len(paths) <= MAX_FILE_RESOURCES
    assert all(size <= MAX_FILE_CHARACTERS for size in sizes.values()), sizes
    assert sum(sizes.values()) <= MAX_TOTAL_CHARACTERS, sum(sizes.values())


def test_recipe_keeps_the_rules_of_the_template() -> None:
    """The prompt file still carries every rule of the recipe (a rename cannot drop one)."""
    text = (AGENTS_DIR / "ghost-ledger-builder.md").read_text(encoding="utf-8")

    missing = [phrase for phrase in RECIPE_PHRASES if phrase not in text]
    assert missing == []


def test_the_only_agent_files_are_the_json_and_its_prompt() -> None:
    """A stray second agent would change what a session picks up."""
    names = sorted(path.name for path in AGENTS_DIR.iterdir())

    assert names == ["ghost-ledger-builder.json", "ghost-ledger-builder.md"]
