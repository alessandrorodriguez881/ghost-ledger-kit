"""Checks the Kiro workspace MCP config and the ghost-ledger-detector power."""

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MCP_JSON = REPO_ROOT / ".kiro" / "settings" / "mcp.json"
POWER_DIR = REPO_ROOT / "powers" / "ghost-ledger-detector"
PLUGIN_JSON = POWER_DIR / "plugin.json"
SKILL_MD = POWER_DIR / "skills" / "add-detector" / "SKILL.md"

REQUIRED_MANIFEST_KEYS = (
    "$schema",
    "name",
    "version",
    "description",
    "author",
    "license",
    "keywords",
)
SCHEMA_URL = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")
SECRET_WORDS = re.compile(
    r"(api[_-]?key|token|secret|password|bearer|authorization|sk-[a-z0-9]|ctx7sk)", re.IGNORECASE
)
CODE_NAME = re.compile(r"^(?:ledger_kit|apps)[\w./]*")


def _load_json(path: Path) -> dict[str, Any]:
    """Parse one JSON file."""
    return json.loads(path.read_text(encoding="utf-8"))


def _front_matter(text: str) -> dict[str, str]:
    """Return the simple `key: value` pairs of the leading --- block."""
    lines = text.splitlines()
    assert lines and lines[0].strip() == "---", "SKILL.md must start with front matter"
    pairs: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return pairs
        key, sep, value = line.partition(":")
        if sep:
            pairs[key.strip()] = value.strip()
    raise AssertionError("front matter is not closed with ---")


def _python_text(path: Path) -> str:
    """Return the source text of a .py file, or of every .py file under a directory."""
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(path.rglob("*.py")))


def _check_code_name(name: str) -> None:
    """Assert that a ledger_kit/apps path or dotted name exists in the source tree."""
    if "/" in name or name.endswith(".py"):
        assert (REPO_ROOT / name).exists(), f"{name} does not exist"
        return
    parts = name.split(".")
    current = REPO_ROOT
    index = 0
    while index < len(parts):
        part = parts[index]
        if (current / part).is_dir():
            current = current / part
            index += 1
        elif (current / f"{part}.py").is_file():
            current = current / f"{part}.py"
            index += 1
            break
        else:
            break
    assert current != REPO_ROOT, f"{name}: no matching package or module"
    text = _python_text(current)
    for attribute in parts[index:]:
        assert attribute in text, f"{name}: {attribute!r} not found in {current}"


def test_mcp_json_declares_context7_without_secrets() -> None:
    """mcp.json parses, declares context7 over https and carries no secret-looking value."""
    if not MCP_JSON.exists():
        pytest.skip(
            ".kiro/settings/mcp.json not created yet, the developer adds it by hand "
            "after approving the context7 server"
        )
    raw = MCP_JSON.read_text(encoding="utf-8")
    config = json.loads(raw)

    server = config["mcpServers"]["context7"]
    url = urlparse(server["url"])
    assert url.scheme == "https"
    assert url.hostname
    assert url.username is None and url.password is None
    assert not url.query
    assert "headers" not in server and "env" not in server
    assert SECRET_WORDS.search(raw) is None


def test_plugin_json_has_required_keys_and_semver() -> None:
    """plugin.json has every manifest key, a semantic version and non-empty keywords."""
    manifest = _load_json(PLUGIN_JSON)

    for key in REQUIRED_MANIFEST_KEYS:
        assert key in manifest, key
    assert manifest["$schema"] == SCHEMA_URL
    assert manifest["name"] == "ghost-ledger-detector"
    assert SEMVER.match(manifest["version"])
    assert manifest["description"].strip()
    assert manifest["author"]["name"] == "Ghost Ledger Kit"
    assert manifest["license"] == "MIT"
    keywords = manifest["keywords"]
    assert isinstance(keywords, list) and keywords
    assert all(isinstance(k, str) and k.strip() for k in keywords)


def test_power_readme_exists() -> None:
    """The power folder ships a README."""
    assert (POWER_DIR / "README.md").read_text(encoding="utf-8").strip()


def test_skill_has_front_matter_with_name_and_description() -> None:
    """SKILL.md starts with front matter holding a non-empty name and description."""
    pairs = _front_matter(SKILL_MD.read_text(encoding="utf-8"))

    assert pairs.get("name") == "add-detector"
    assert pairs.get("description")


def _skill_code_names() -> list[str]:
    """Every ledger_kit/apps name mentioned in inline backticks of SKILL.md."""
    text = re.sub(r"```.*?```", "", SKILL_MD.read_text(encoding="utf-8"), flags=re.DOTALL)
    names: list[str] = []
    for span in re.findall(r"`([^`\n]+)`", text):
        match = CODE_NAME.match(span)
        if match:
            names.append(match.group(0).rstrip("."))
    return sorted(set(names))


def test_skill_mentions_code_names() -> None:
    """The skill actually cites ledger_kit and apps names (guards the check below)."""
    names = _skill_code_names()
    assert any(n.startswith("ledger_kit") for n in names)
    assert any(n.startswith("apps") for n in names)


@pytest.mark.parametrize("name", _skill_code_names())
def test_skill_backticked_names_exist_in_the_code(name: str) -> None:
    """Every ledger_kit or apps name in backticks resolves to real source."""
    _check_code_name(name)
