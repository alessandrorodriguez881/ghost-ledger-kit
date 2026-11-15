"""Community Cloud readiness and package boundaries of the showcase (REQ-SC-10, REQ-SC-11)."""

import ast
import itertools
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = REPO_ROOT / "requirements.txt"
ENTRY = REPO_ROOT / "streamlit_app.py"
FIRST_PARTY = {"ledger_kit", "apps", "streamlit_app"}
# Import name -> distribution name, for packages whose two names differ (none are used so far).
DISTRIBUTION: dict[str, str] = {}
PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.-]*)==([0-9][^\s#;]*)$")
APPS = ("zombie_subscriptions", "phantom_invoices", "vampire_fees")


def _runtime_files() -> list[Path]:
    """Every module the deployed showcase can import: ledger_kit, the apps (no tests), entry."""
    files = [ENTRY]
    for package in ("ledger_kit", "apps"):
        for path in sorted((REPO_ROOT / package).rglob("*.py")):
            if "__pycache__" not in path.parts and "tests" not in path.parts:
                files.append(path)
    return files


def _imports(path: Path) -> list[tuple[str, list[str]]]:
    """Return (module, imported names) of every absolute import in the file, nested ones too."""
    found: list[tuple[str, list[str]]] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.level == 0:
            found.append((node.module or "", [alias.name for alias in node.names]))
        elif isinstance(node, ast.Import):
            found.extend((alias.name, []) for alias in node.names)
    return found


def _normalise(name: str) -> str:
    """PEP 503 normalised distribution name."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirement_lines() -> list[str]:
    """The non-empty, non-comment lines of the root requirements.txt."""
    lines = REQUIREMENTS.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]


def test_runtime_files_are_found() -> None:
    """The scan covers the entry page, the library and both apps (guards the tests below)."""
    names = {path.relative_to(REPO_ROOT).as_posix() for path in _runtime_files()}

    assert "streamlit_app.py" in names
    assert "ledger_kit/explainer.py" in names
    assert "apps/zombie_subscriptions/app.py" in names
    assert "apps/phantom_invoices/detectors/utils.py" in names
    assert "apps/vampire_fees/detectors/utils.py" in names
    assert not any("/tests/" in name for name in names)


def test_every_requirement_is_pinned_exactly() -> None:
    """No open range and no unpinned package: every line is name==version."""
    lines = _requirement_lines()

    assert lines
    assert [line for line in lines if PIN.match(line) is None] == []


def _pinned_names() -> set[str]:
    """The normalised distribution names pinned in the root requirements.txt."""
    names: set[str] = set()
    for line in _requirement_lines():
        match = PIN.match(line)
        if match is not None:
            names.add(_normalise(match.group(1)))
    return names


def test_every_third_party_import_is_pinned_in_the_root_requirements() -> None:
    """Whatever ledger_kit, the apps or the entry page import at run time gets installed."""
    pinned = _pinned_names()
    third_party: dict[str, set[str]] = {}
    for path in _runtime_files():
        for module, _names in _imports(path):
            top = module.split(".")[0]
            if top and top not in sys.stdlib_module_names and top not in FIRST_PARTY:
                third_party.setdefault(top, set()).add(path.relative_to(REPO_ROOT).as_posix())

    assert {"streamlit", "pandas", "pydantic", "numpy", "defusedxml"} <= set(third_party)
    missing = {
        top: sorted(files)
        for top, files in third_party.items()
        if _normalise(DISTRIBUTION.get(top, top)) not in pinned
    }
    assert missing == {}


def test_defusedxml_is_pinned_exactly_for_the_facturae_reader() -> None:
    """The only XML parser the showcase may use is the pinned defusedxml (REQ-RF-29, DN-RF-15)."""
    assert "defusedxml==0.7.1" in _requirement_lines()
    users = {
        path.relative_to(REPO_ROOT).as_posix()
        for path in _runtime_files()
        for module, _names in _imports(path)
        if module.split(".")[0] == "defusedxml"
    }
    assert users == {"ledger_kit/ingestion/facturae_reader.py"}


def test_no_app_has_its_own_requirements_file() -> None:
    """An app-level requirements.txt would hide the root one on Streamlit Community Cloud."""
    assert REQUIREMENTS.is_file()
    assert list((REPO_ROOT / "apps").rglob("requirements*.txt")) == []
    assert not (REPO_ROOT / "ledger_kit" / "requirements.txt").exists()


def test_the_entry_page_imports_no_app_but_the_bridge() -> None:
    """streamlit_app.py runs the apps as pages; the one app module it imports is the bridge.

    ``apps.home_tiles`` runs the demo data of the apps for the Home tiles and the moment
    (REQ-HD-23). No other module outside an app folder may import an app.
    """
    for module, names in _imports(ENTRY):
        if module.split(".")[0] != "apps":
            continue
        assert module == "apps" and names == ["home_tiles"], (module, names)


def test_only_the_bridge_outside_the_app_folders_imports_an_app() -> None:
    """Under apps/, a file that is not in an app folder is the bridge, and nothing else is."""
    loose = sorted(path.name for path in (REPO_ROOT / "apps").glob("*.py"))

    assert loose == ["__init__.py", "home_tiles.py"]
    modules = {module for module, _names in _imports(REPO_ROOT / "apps" / "home_tiles.py")}
    assert any(module.startswith("apps.") for module in modules)
    for path in sorted((REPO_ROOT / "ledger_kit").rglob("*.py")):
        offenders = [m for m, _n in _imports(path) if m.split(".")[0] == "apps"]
        assert offenders == [], path.name


def test_apps_never_import_each_other() -> None:
    """No app imports another one: every ordered pair of the three apps is checked (REQ-SC-11)."""
    assert len(APPS) == 3
    for app, other in itertools.permutations(APPS, 2):
        forbidden = f"apps.{other}"
        offenders = [
            path.relative_to(REPO_ROOT).as_posix()
            for path in sorted((REPO_ROOT / "apps" / app).rglob("*.py"))
            for module, _names in _imports(path)
            if module == forbidden or module.startswith(f"{forbidden}.")
        ]
        assert offenders == [], app


def test_apps_and_entry_page_use_no_private_ledger_kit_name() -> None:
    """No `_name` is imported from ledger_kit by an app or the entry page (REQ-SC-11)."""
    offenders: list[str] = []
    for path in _runtime_files():
        if "ledger_kit" in path.relative_to(REPO_ROOT).parts[:1]:
            continue
        for module, names in _imports(path):
            if module.split(".")[0] != "ledger_kit":
                continue
            parts = [*module.split("."), *names]
            if any(part.startswith("_") for part in parts):
                offenders.append(f"{path.relative_to(REPO_ROOT).as_posix()}: {module} {names}")
    assert offenders == []
