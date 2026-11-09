"""Packaging and pytest-configuration tests (REQ-PKG-01..07)."""

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_pyproject() -> dict:
    """Parse pyproject.toml from the repository root."""
    with (ROOT / "pyproject.toml").open("rb") as fh:
        return tomllib.load(fh)


def test_pytest_config_sets_pythonpath_and_testpaths() -> None:
    """pytest finds ledger_kit through pythonpath and collects tests and apps."""
    cfg = _load_pyproject()["tool"]["pytest"]["ini_options"]
    assert cfg["pythonpath"] == ["."]
    assert cfg["testpaths"] == ["tests", "apps"]


def test_ledger_kit_importable_without_editable_install() -> None:
    """ledger_kit imports from the repository checkout, not from an installed copy."""
    import ledger_kit

    package_dir = Path(ledger_kit.__file__).resolve().parent
    assert package_dir == ROOT / "ledger_kit"


def test_openai_is_optional_extra_only() -> None:
    """openai is absent from runtime dependencies and pinned with == in the llm extra."""
    project = _load_pyproject()["project"]
    assert not any(dep.lower().startswith("openai") for dep in project["dependencies"])
    llm = project["optional-dependencies"]["llm"]
    openai_pins = [dep for dep in llm if dep.lower().startswith("openai")]
    assert len(openai_pins) == 1
    assert "==" in openai_pins[0]


def test_defusedxml_is_pinned_exactly_in_both_places() -> None:
    """REQ-RF-29: defusedxml==0.7.1 is a runtime dependency and in the root requirements."""
    dependencies = _load_pyproject()["project"]["dependencies"]
    assert "defusedxml==0.7.1" in dependencies
    lines = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    assert "defusedxml==0.7.1" in [line.strip() for line in lines]
