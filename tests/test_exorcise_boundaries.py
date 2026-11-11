"""Boundaries of Exorcise: no model, no network, no key, and the package rules (EX6, REQ-EX-06, 21).

The draft is a pure function of the alert, the cited rows and the language. These tests read the
source of the new modules and run a draft with the model SDK made unimportable, every socket
refused and the key set and unset.
"""

import ast
import socket
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from apps.zombie_subscriptions.action_templates import TEMPLATES
from ledger_kit.actions import build_draft
from ledger_kit.models import Alert

ROOT = Path(__file__).resolve().parents[1]
ACTIONS = ROOT / "ledger_kit" / "actions.py"
WIDGET = ROOT / "ledger_kit" / "ui" / "exorcise.py"
APP_MODULES = {
    "zombie_subscriptions": ROOT / "apps" / "zombie_subscriptions" / "action_templates.py",
    "phantom_invoices": ROOT / "apps" / "phantom_invoices" / "action_templates.py",
    "vampire_fees": ROOT / "apps" / "vampire_fees" / "action_templates.py",
}
NETWORK_OR_MODEL = {"openai", "requests", "httpx", "urllib", "socket", "http", "aiohttp"}
STDLIB_OR_DATA = {"__future__", "collections", "decimal", "pandas"}


def _imports(path: Path) -> set[str]:
    """Return the dotted names of every module the file imports."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.level == 0:
            found.add(node.module or "")
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
    return found


def _roots(modules: set[str]) -> set[str]:
    return {module.split(".")[0] for module in modules}


def test_the_mechanism_is_pure_and_the_widget_is_the_only_streamlit_module() -> None:
    assert "streamlit" not in _roots(_imports(ACTIONS))
    assert "streamlit" in _roots(_imports(WIDGET))
    for path in (ACTIONS, WIDGET):
        assert not _roots(_imports(path)) & NETWORK_OR_MODEL, path.name
        assert "apps" not in _roots(_imports(path)), path.name


def test_neither_new_library_module_reads_a_key_or_names_a_model() -> None:
    for path in (ACTIONS, WIDGET):
        text = path.read_text(encoding="utf-8")

        assert "OPENAI" not in text and "os.environ" not in text and "chat.completions" not in text


@pytest.mark.parametrize("app", sorted(APP_MODULES))
def test_a_template_module_imports_only_ledger_kit_data_libraries_and_its_own_app(
    app: str,
) -> None:
    modules = _imports(APP_MODULES[app])
    own = f"apps.{app}"

    for module in modules:
        root = module.split(".")[0]
        assert root in STDLIB_OR_DATA | {"ledger_kit"} or module.startswith(own + "."), module
    assert not _roots(modules) & NETWORK_OR_MODEL
    assert not any(m.startswith("apps.") and not m.startswith(own + ".") for m in modules)


def test_ledger_kit_imports_no_app_after_this_change() -> None:
    offenders = [
        str(path.relative_to(ROOT))
        for path in (ROOT / "ledger_kit").rglob("*.py")
        if "apps" in _roots(_imports(path))
    ]

    assert offenders == []


def _alert_and_rows() -> tuple[Alert, pd.DataFrame]:
    alert = Alert(
        detector="zs.charges_after_cancellation",
        severity="critical",
        title="Charge after cancellation: GYMPLUS",
        source_refs=["s.csv:0", "s.csv:1"],
        data={
            "counterparty": "GYMPLUS",
            "cancellation_date": "2026-07-31",
            "post_cancellation_count": 2,
            "total_charged_after": "17.98",
            "yearly_cost": "107.88",
        },
    )
    rows = pd.DataFrame(
        [
            {
                "date": day,
                "amount": Decimal("8.99"),
                "flow": "debit",
                "currency": "EUR",
                "counterparty": "GYMPLUS",
                "source_ref": f"s.csv:{index}",
            }
            for index, day in enumerate((date(2026, 8, 9), date(2026, 9, 8)))
        ]
    )
    return alert, rows


def test_a_draft_needs_no_key_no_sdk_and_no_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    alert, rows = _alert_and_rows()
    template = TEMPLATES["zs.charges_after_cancellation"]
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    without_key = [build_draft(alert, rows, template, lang) for lang in ("en", "es")]

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("a draft must not open a connection")

    monkeypatch.setitem(sys.modules, "openai", None)  # import openai now fails
    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    with_key = [build_draft(alert, rows, template, lang) for lang in ("en", "es")]

    assert without_key == with_key
    assert all(draft is not None for draft in with_key)
