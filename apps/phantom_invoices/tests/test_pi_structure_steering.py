"""Checks that the phantom section of .kiro/steering/structure.md matches the repository (P23).

The layout tree of the steering file is parsed and compared with the file list of the
phantom-invoices spec (plus the two shared test helper modules the code base split out of
conftest.py); every listed path must exist on disk.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
STRUCTURE = REPO_ROOT / ".kiro" / "steering" / "structure.md"
PHANTOM = "apps/phantom_invoices/"
ZOMBIE = "apps/zombie_subscriptions/"

# One line of the tree: indentation groups of four characters, a connector, then the name.
TREE_LINE = re.compile(r"^((?:[│ ]\s{3})*)[├└]── (\S+)")

APP_FILES = {
    "__init__.py",
    "app.py",
    "config.toml",
    "settings.py",
    "prepare.py",
    "explain_support.py",
    "flashlight.py",
}
DETECTOR_FILES = {
    "detectors/__init__.py",
    "detectors/utils.py",
    "detectors/duplicate_invoice.py",
    "detectors/iban_change.py",
    "detectors/vat_error.py",
    "detectors/reconciliation.py",
}
TEST_MODULES = (
    "scaffold",
    "ledger_core_contract",
    "utils_keys",
    "utils_iban",
    "utils_order",
    "utils_master",
    "prepare",
    "identifiers",
    "fixtures",
    "duplicate_invoice",
    "iban_change",
    "vat_error",
    "reconciliation",
    "registry",
    "explain_support",
    "flashlight",
    "settings",
    "demo_generator",
    "demo_data",
    "gitattributes",
    "app_logic",
    "structure_steering",
    "demo_e2e",
)
# conftest.py and pi_checkers.py are in the spec; pi_builders.py and pi_strategies.py hold the
# builders and strategies that conftest.py re-exports.
TEST_HELPERS = {"conftest.py", "pi_builders.py", "pi_checkers.py", "pi_strategies.py"}
HELPER_PATHS = {f"tests/{name}" for name in TEST_HELPERS}
MODULE_PATHS = {f"tests/test_pi_{module}.py" for module in TEST_MODULES}
SPEC_FILES = APP_FILES | DETECTOR_FILES | HELPER_PATHS | MODULE_PATHS
EXPECTED_PHANTOM_FILES = {f"{PHANTOM}{name}" for name in SPEC_FILES}
EXTRA_PATHS = (
    "scripts/generate_samples.py",
    ".gitattributes",
    "requirements.txt",
    "data/samples/phantom_demo/suppliers.csv",
    "data/samples/phantom_demo/invoices.csv",
    "data/samples/phantom_demo/payments.csv",
)


def _layout_block() -> str:
    """The first fenced block under '## Top-level layout'."""
    text = STRUCTURE.read_text(encoding="utf-8")
    section = text.split("## Top-level layout", 1)[1]
    return section.split("```", 2)[1]


def _tree_files() -> list[str]:
    """Every file listed in the layout tree, as a path relative to the repository root."""
    stack: list[str] = []
    files: list[str] = []
    for line in _layout_block().splitlines():
        match = TREE_LINE.match(line)
        if match is None:
            continue  # the root line and blank lines
        depth = len(match.group(1)) // 4
        name = match.group(2)
        del stack[depth:]
        if name.endswith("/"):
            stack.append(name.rstrip("/"))
        else:
            files.append("/".join([*stack, name]))
    return files


def test_phantom_block_lists_exactly_the_spec_files() -> None:
    """The phantom_invoices block of the tree lists the spec's files and nothing else."""
    listed = {path for path in _tree_files() if path.startswith(PHANTOM)}

    assert listed == EXPECTED_PHANTOM_FILES
    assert len(listed) == len(EXPECTED_PHANTOM_FILES) == 7 + 6 + 4 + 23


def test_phantom_block_has_no_requirements_txt() -> None:
    """REQ-PI-53: the app has no requirements.txt of its own; the root one is listed."""
    files = _tree_files()

    assert not [path for path in files if path.startswith(PHANTOM) and "requirements" in path]
    assert "requirements.txt" in files
    assert not (REPO_ROOT / "apps" / "phantom_invoices" / "requirements.txt").exists()


def test_every_listed_phantom_path_exists_on_disk() -> None:
    """Every file the tree lists for the phantom app, and the shared files, exists."""
    files = _tree_files()

    missing = [p for p in sorted(EXPECTED_PHANTOM_FILES) if not (REPO_ROOT / p).is_file()]
    assert missing == []
    for path in EXTRA_PATHS:
        assert path in files, path
        assert (REPO_ROOT / path).is_file(), path


def test_no_phantom_python_file_on_disk_is_missing_from_the_tree() -> None:
    """The tree is complete: every .py and .toml file of the app folder is listed."""
    app_dir = REPO_ROOT / "apps" / "phantom_invoices"
    on_disk = {
        path.relative_to(REPO_ROOT).as_posix()
        for pattern in ("*.py", "*.toml")
        for path in app_dir.rglob(pattern)
        if "__pycache__" not in path.parts
    }

    assert on_disk == EXPECTED_PHANTOM_FILES


def test_zombie_block_is_still_listed_and_boundaries_note_added() -> None:
    """The zombie block is untouched and the package-boundaries note names the phantom app."""
    files = _tree_files()
    zombie = {path for path in files if path.startswith(ZOMBIE)}

    assert {f"{ZOMBIE}app.py", f"{ZOMBIE}settings.py", f"{ZOMBIE}tests/test_zs_app.py"} <= zombie
    note = "The phantom app may import `ledger_kit` (public names only)"
    assert note in STRUCTURE.read_text(encoding="utf-8")
