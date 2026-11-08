"""Scaffold tests for the zombie-subscriptions app package (Task Z1)."""

import ast
import importlib
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = APP_DIR.parents[1]
LEDGER_KIT_DIR = REPO_ROOT / "ledger_kit"


def _imported_modules(path: Path) -> set[str]:
    """Return every dotted module name a source file imports (from-imports expanded)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


@pytest.mark.parametrize(
    "module_name",
    ["apps", "apps.zombie_subscriptions", "apps.zombie_subscriptions.detectors"],
)
def test_app_package_importable(module_name: str) -> None:
    """The app packages import cleanly under plain pytest."""
    assert importlib.import_module(module_name) is not None


def test_no_app_level_requirements_txt() -> None:
    """An app-level requirements.txt would hide the root file on Streamlit Community Cloud."""
    assert not (APP_DIR / "requirements.txt").exists()


def test_app_does_not_import_other_app() -> None:
    """No module of this app imports apps.phantom_invoices."""
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in APP_DIR.rglob("*.py")
        for module in _imported_modules(path)
        if module == "apps.phantom_invoices" or module.startswith("apps.phantom_invoices.")
    ]
    assert offenders == []


def test_ledger_kit_imports_nothing_from_apps() -> None:
    """The shared library never imports from the apps package."""
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in LEDGER_KIT_DIR.rglob("*.py")
        for module in _imported_modules(path)
        if module == "apps" or module.startswith("apps.")
    ]
    assert offenders == []
