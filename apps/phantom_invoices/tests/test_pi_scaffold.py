"""Scaffold tests for the phantom-invoices app package (Task P1)."""

import ast
import importlib
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = APP_DIR.parents[1]
LEDGER_KIT_DIR = REPO_ROOT / "ledger_kit"
TESTS_DIR = APP_DIR / "tests"

# Calls that read the system clock (REQ-PI-65).
CLOCK_ATTRIBUTES = frozenset({"today", "now", "utcnow"})
# The only private ledger_kit names a test may use: the documented registry isolation helpers.
TEST_ONLY_PRIVATE_NAMES = frozenset({"_snapshot_registry", "_restore_registry"})


def _app_sources() -> list[Path]:
    """Every Python file under the app folder, in a stable order."""
    return sorted(p for p in APP_DIR.rglob("*.py") if "__pycache__" not in p.parts)


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


def _is_private(name: str) -> bool:
    """True for a single-underscore name (dunders such as __name__ are not private)."""
    return name.startswith("_") and not (name.startswith("__") and name.endswith("__"))


def _is_ledger_kit(module: str) -> bool:
    """True for 'ledger_kit' and every dotted module below it."""
    return module == "ledger_kit" or module.startswith("ledger_kit.")


def _private_ledger_kit_uses(path: Path) -> list[str]:
    """Return private ledger_kit names used by a file: imports and attribute accesses (DN-9)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    in_tests = TESTS_DIR in path.parents
    allowed = TEST_ONLY_PRIVATE_NAMES if in_tests else frozenset()
    found: list[str] = []
    bound: set[str] = set()  # local names that refer to a ledger_kit module

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if not _is_ledger_kit(alias.name):
                    continue
                found += [p for p in alias.name.split(".") if _is_private(p)]
                bound.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if not _is_ledger_kit(node.module):
                continue
            found += [p for p in node.module.split(".") if _is_private(p)]
            for alias in node.names:
                if _is_private(alias.name) and alias.name not in allowed:
                    found.append(alias.name)
                elif alias.asname or not _is_private(alias.name):
                    bound.add(alias.asname or alias.name)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute) or not _is_private(node.attr):
            continue
        if node.attr in allowed:
            continue
        root = node.value
        while isinstance(root, ast.Attribute):
            root = root.value
        if isinstance(root, ast.Name) and root.id in bound:
            found.append(node.attr)
    return found


def _clock_calls(path: Path) -> list[str]:
    """Return the clock-reading calls found in a file (today, now, utcnow, time.time)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            is_time_time = (
                func.attr == "time" and isinstance(func.value, ast.Name) and func.value.id == "time"
            )
            if func.attr in CLOCK_ATTRIBUTES or is_time_time:
                found.append(func.attr)
        elif isinstance(func, ast.Name) and func.id in CLOCK_ATTRIBUTES:
            found.append(func.id)
    return found


@pytest.mark.parametrize(
    "module_name",
    ["apps", "apps.phantom_invoices", "apps.phantom_invoices.detectors"],
)
def test_app_package_importable(module_name: str) -> None:
    """The app packages import cleanly under plain pytest."""
    assert importlib.import_module(module_name) is not None


def test_no_app_level_requirements_txt() -> None:
    """An app-level requirements.txt would hide the root file on Streamlit Community Cloud."""
    assert not (APP_DIR / "requirements.txt").exists()
    assert (REPO_ROOT / "requirements.txt").is_file()


def test_app_does_not_import_other_app() -> None:
    """No module of this app imports apps.zombie_subscriptions."""
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in _app_sources()
        for module in _imported_modules(path)
        if module == "apps.zombie_subscriptions" or module.startswith("apps.zombie_subscriptions.")
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


def test_app_imports_no_private_ledger_kit_name() -> None:
    """No file of the app uses an underscore-prefixed ledger_kit name (DN-9)."""
    offenders = {
        str(path.relative_to(REPO_ROOT)): names
        for path in _app_sources()
        if (names := _private_ledger_kit_uses(path))
    }
    assert offenders == {}


def test_private_name_scan_detects_violations(tmp_path: Path) -> None:
    """The scanner flags private imports and attribute accesses (guards the guard)."""
    sample = tmp_path / "sample.py"
    sample.write_text(
        "from ledger_kit.explainer import _fill_fallback\n"
        "import ledger_kit.explainer as ex\n"
        "from ledger_kit.detectors import _clear_registry, _snapshot_registry\n"
        "ex._select_llm_columns\n"
        "import ledger_kit\n"
        "ledger_kit.explainer._tokenise\n",
        encoding="utf-8",
    )
    found = _private_ledger_kit_uses(sample)
    assert "_fill_fallback" in found
    assert "_clear_registry" in found
    assert "_select_llm_columns" in found
    assert "_tokenise" in found


def test_no_clock_calls_in_package() -> None:
    """No file of the app reads the system clock (REQ-PI-65)."""
    offenders = {
        str(path.relative_to(REPO_ROOT)): calls
        for path in _app_sources()
        if (calls := _clock_calls(path))
    }
    assert offenders == {}


def test_clock_scan_detects_calls(tmp_path: Path) -> None:
    """The scanner flags today(), now(), utcnow() and time.time() (guards the guard)."""
    sample = tmp_path / "sample.py"
    sample.write_text(
        "import time\n"
        "from datetime import date, datetime\n"
        "date.today()\n"
        "datetime.now()\n"
        "datetime.utcnow()\n"
        "time.time()\n",
        encoding="utf-8",
    )
    assert _clock_calls(sample) == ["today", "now", "utcnow", "time"]
