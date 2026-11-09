"""Tests of everything in the zombie app that needs no Streamlit runtime (Task Z21)."""

import ast
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from apps.zombie_subscriptions.detectors.utils import ZombieCostResult
from apps.zombie_subscriptions.settings import (
    BADGE_LLM,
    BADGE_TEMPLATE,
    BADGE_UNAVAILABLE,
    SEVERITY_ORDER,
    apply_demo,
    demo_inputs,
    group_alerts_by_severity,
    guard_badge,
    ledger_currency,
    load_config,
    parse_aliases_text,
    parse_dates_text,
    tombstone_view,
)
from ledger_kit.explainer import Explanation
from ledger_kit.models import Alert

APP_DIR = Path(__file__).resolve().parents[1]
ROOT = APP_DIR.parents[1]
APP_PATH = APP_DIR / "app.py"


def _tree() -> ast.Module:
    """Parse app.py."""
    return ast.parse(APP_PATH.read_text(encoding="utf-8"))


def _is_st_button(node: ast.AST) -> bool:
    """True for a call of `st.button(...)`."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "button"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "st"
    )


def _imports_project(node: ast.stmt) -> bool:
    """True when a top-level statement imports ledger_kit or apps."""
    if isinstance(node, ast.Import):
        names = [alias.name for alias in node.names]
    elif isinstance(node, ast.ImportFrom) and node.module:
        names = [node.module]
    else:
        return False
    return any(name.split(".")[0] in {"ledger_kit", "apps"} for name in names)


def _alert(severity: str, title: str) -> Alert:
    """Build a throwaway alert."""
    return Alert(
        detector="zs.recurring_charge",
        severity=severity,
        title=title,
        source_refs=["f.csv:0"],
        data={"title": title},
    )


# --- Source-level checks ----------------------------------------------------------------------


def test_app_py_first_lines_bootstrap_sys_path() -> None:
    """The sys.path bootstrap runs before the first ledger_kit or apps import (REQ-ZS-41)."""
    body = _tree().body
    first_project_import = next(i for i, node in enumerate(body) if _imports_project(node))
    bootstrap = next(
        i
        for i, node in enumerate(body)
        if isinstance(node, ast.If) and "sys.path.insert" in ast.unparse(node)
    )
    assert bootstrap < first_project_import
    root_assignment = next(
        ast.unparse(node)
        for node in body
        if isinstance(node, ast.Assign) and ast.unparse(node.targets[0]) == "_ROOT"
    )
    assert "__file__" in root_assignment and "parents[2]" in root_assignment


def test_app_uses_on_click_for_load_demo() -> None:
    """Load demo data is a st.button with on_click; no widget key is assigned under an `if`."""
    tree = _tree()
    buttons = [
        node
        for node in ast.walk(tree)
        if _is_st_button(node)
        and isinstance(node, ast.Call)
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "Load demo data"
    ]
    assert len(buttons) == 1
    on_click = {kw.arg: kw.value for kw in buttons[0].keywords}["on_click"]
    assert isinstance(on_click, ast.Name) and on_click.id == "load_demo"
    functions = {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    assert functions["load_demo"].lineno < buttons[0].lineno  # defined before the widgets

    for node in ast.walk(tree):
        if isinstance(node, ast.If) and any(_is_st_button(sub) for sub in ast.walk(node.test)):
            for inner in ast.walk(node):
                if isinstance(inner, ast.Assign):
                    targets = [ast.unparse(target) for target in inner.targets]
                    assert not any(t.startswith("st.session_state[") for t in targets)


def test_app_does_not_read_the_clock() -> None:
    """Neither app.py nor settings.py reads the system clock (REQ-ZS-49)."""
    for path in (APP_PATH, APP_DIR / "settings.py"):
        source = path.read_text(encoding="utf-8")
        assert "date.today" not in source
        assert "datetime.now" not in source
        assert "time.time" not in source


# --- Demo callback ----------------------------------------------------------------------------


def test_load_demo_callback_prefills_widget_keys() -> None:
    """apply_demo sets the three text areas, the source and the demo_loaded flag."""
    demo = demo_inputs(load_config(APP_DIR / "config.toml"), ROOT)
    state: dict[str, object] = {}

    apply_demo(state, demo)

    assert set(state) == {"aliases_text", "last_used_text", "cancel_text", "source", "demo_loaded"}
    assert state["demo_loaded"] is True
    assert state["source"] == ("demo", demo.statement_bytes, demo.statement_name)
    assert parse_aliases_text(str(state["aliases_text"])) == demo.aliases
    assert parse_dates_text(str(state["last_used_text"])) == demo.last_used_dates
    assert parse_dates_text(str(state["cancel_text"])) == demo.cancellation_dates
    assert state["cancel_text"] == "GYMPLUS = 2026-07-31"


# --- View model -------------------------------------------------------------------------------


def test_all_amounts_rendered_with_format_amount() -> None:
    """Tombstone amounts use the European format of format_amount (REQ-ZS-39)."""
    result = ZombieCostResult(
        canonical_name="CLOUDVAULT",
        last_used_date=date(2026, 7, 15),
        cost_since_last_used=Decimal("1234.56"),
        source_refs=["f.csv:3", "f.csv:10"],
        yearly_cost=Decimal("1060"),
    )

    view = tombstone_view(result, "EUR")

    assert view.name == "CLOUDVAULT"
    assert view.died_on == "2026-07-15"
    assert view.cost_since == "1.234,56 EUR"
    assert view.yearly_cost == "1.060,00 EUR"
    assert view.source_refs == ("f.csv:3", "f.csv:10")


def test_tombstone_view_zero_cost_entry() -> None:
    """A service without charges after its last-used date is still a tombstone."""
    result = ZombieCostResult("MUSICBOX", date(2026, 8, 1), Decimal("0.00"), [], Decimal("0.00"))

    view = tombstone_view(result)

    assert view.cost_since == "0,00 EUR"
    assert view.source_refs == ()


def test_guard_badge_selection() -> None:
    """llm -> verified; fallback without key -> template; rejected -> names the number."""
    verified = Explanation(text="ok", source="llm", rejected_numbers=())
    plain = Explanation(text="t", source="fallback", rejected_numbers=())
    rejected = Explanation(text="t", source="fallback", rejected_numbers=("99999.99",))

    assert guard_badge(verified, has_api_key=True).label == BADGE_LLM
    assert guard_badge(verified, has_api_key=True).kind == "llm"
    assert guard_badge(plain, has_api_key=False).label == BADGE_TEMPLATE
    assert guard_badge(plain, has_api_key=False).kind == "template"
    assert guard_badge(plain, has_api_key=True).label == BADGE_UNAVAILABLE
    badge = guard_badge(rejected, has_api_key=False)
    assert badge.kind == "rejected"
    assert badge.label.startswith("⚠️") and "99999.99" in badge.label
    assert BADGE_LLM.startswith("🤖 ✓") and BADGE_TEMPLATE.startswith("📋")


def test_guard_badge_names_every_rejected_number() -> None:
    """Several rejected tokens are all listed."""
    rejected = Explanation(text="t", source="fallback", rejected_numbers=("1,5", "7.00"))

    assert "1,5" in guard_badge(rejected, has_api_key=True).label
    assert "7.00" in guard_badge(rejected, has_api_key=True).label


def test_alerts_grouped_critical_warning_info() -> None:
    """Groups come in the order critical, warning, info and keep the input order inside."""
    alerts = [
        _alert("info", "i1"),
        _alert("critical", "c1"),
        _alert("warning", "w1"),
        _alert("info", "i2"),
    ]

    groups = group_alerts_by_severity(alerts)

    assert list(groups) == ["critical", "warning", "info"] == list(SEVERITY_ORDER)
    assert [a.title for a in groups["info"]] == ["i1", "i2"]
    assert [a.title for a in groups["critical"]] == ["c1"]


def test_alerts_grouped_empty_has_every_severity() -> None:
    """No alerts still yields the three (empty) groups."""
    assert group_alerts_by_severity([]) == {"critical": [], "warning": [], "info": []}


@pytest.mark.parametrize(
    ("frame", "expected"),
    [
        (pd.DataFrame({"currency": []}), "EUR"),
        (pd.DataFrame({"amount": [1]}), "EUR"),
        (pd.DataFrame({"currency": ["USD", "EUR"]}), "USD"),
    ],
)
def test_ledger_currency(frame: pd.DataFrame, expected: str) -> None:
    """The currency comes from the first row; an empty or column-less ledger gives EUR."""
    assert ledger_currency(frame) == expected
