"""Scaffold tests for the vampire-fees app package (Task VF1)."""

import ast
import importlib
import re
import tomllib
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = APP_DIR.parents[1]
LEDGER_KIT_DIR = REPO_ROOT / "ledger_kit"
OTHER_APPS = ("apps.zombie_subscriptions", "apps.phantom_invoices")

# Constant names of design section 2.1: none may appear in config.toml (REQ-VF-64).
THRESHOLD_CONSTANT_NAMES = (
    "STATEMENT_CURRENCY",
    "FEE_CONCEPTS",
    "CONCEPT_TAG_PREFIX",
    "MONTHLY_NOMINAL_DAYS",
    "QUARTERLY_NOMINAL_DAYS",
    "YEARLY_NOMINAL_DAYS",
    "MONTHLY_TOLERANCE_DAYS",
    "QUARTERLY_TOLERANCE_DAYS",
    "YEARLY_TOLERANCE_DAYS",
    "MIN_CHARGES_MONTHLY",
    "MIN_CHARGES_QUARTERLY",
    "MIN_CHARGES_YEARLY",
    "PERIODS_PER_YEAR_MONTHLY",
    "PERIODS_PER_YEAR_QUARTERLY",
    "PERIODS_PER_YEAR_YEARLY",
    "RECURRING_FEE_WARNING_YEARLY_COST",
    "FEE_INCREASE_MIN_RATIO",
    "FEE_STABLE_RATIO",
    "FEE_INCREASE_CRITICAL_RATIO",
    "OVERDRAFT_CRITICAL_TOTAL",
    "DAYS_PER_YEAR",
    "SUMMARY_MIN_SPAN_DAYS",
    "SUMMARY_WARNING_YEARLY_EQUIVALENT",
)


def _app_sources(*, include_tests: bool) -> list[Path]:
    """Return the Python files of the app, optionally without its tests folder."""
    return [
        path
        for path in APP_DIR.rglob("*.py")
        if include_tests or "tests" not in path.relative_to(APP_DIR).parts
    ]


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
    ["apps", "apps.vampire_fees", "apps.vampire_fees.detectors"],
)
def test_app_package_importable(module_name: str) -> None:
    """The app packages import cleanly under plain pytest."""
    assert importlib.import_module(module_name) is not None


def test_no_app_level_requirements_txt() -> None:
    """An app-level requirements.txt would hide the root file on Streamlit Community Cloud."""
    assert not (APP_DIR / "requirements.txt").exists()


def test_app_does_not_import_other_app() -> None:
    """No module of this app, tests included, imports another app."""
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in _app_sources(include_tests=True)
        for module in _imported_modules(path)
        for other in OTHER_APPS
        if module == other or module.startswith(f"{other}.")
    ]
    assert offenders == []


def test_ledger_kit_imports_nothing_from_apps() -> None:
    """The shared library never imports from the apps package (so not from this app)."""
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in LEDGER_KIT_DIR.rglob("*.py")
        for module in _imported_modules(path)
        if module == "apps" or module.startswith("apps.")
    ]
    assert offenders == []


def test_app_uses_no_private_ledger_kit_name() -> None:
    """No app module (tests excluded) imports a ledger_kit module or name that starts with _."""
    offenders: list[str] = []
    for path in _app_sources(include_tests=False):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                if not (node.module == "ledger_kit" or node.module.startswith("ledger_kit.")):
                    continue
                names = [node.module.split(".")[-1], *(alias.name for alias in node.names)]
                offenders.extend(
                    f"{path.relative_to(REPO_ROOT)}: {name}"
                    for name in names
                    if name.startswith("_")
                )
            elif isinstance(node, ast.Import):
                offenders.extend(
                    f"{path.relative_to(REPO_ROOT)}: {alias.name}"
                    for alias in node.names
                    if alias.name.startswith("ledger_kit")
                    and any(part.startswith("_") for part in alias.name.split("."))
                )
    assert offenders == []


def test_app_reads_no_clock() -> None:
    """No app module (tests excluded) reads the system clock (REQ-VF-35)."""
    pattern = re.compile(r"\.today\(|\.now\(|datetime\.utcnow|time\.time\(")
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in _app_sources(include_tests=False)
        if pattern.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_config_has_no_threshold_constant_name() -> None:
    """config.toml holds the vocabulary and demo paths only, never a threshold (REQ-VF-64)."""
    config_path = APP_DIR / "config.toml"
    if not config_path.exists():  # added by Task VF11
        pytest.skip("config.toml is created by Task VF11")
    text = config_path.read_text(encoding="utf-8")
    tomllib.loads(text)
    assert [name for name in THRESHOLD_CONSTANT_NAMES if name in text] == []
