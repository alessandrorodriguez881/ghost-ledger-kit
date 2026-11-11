"""Small pieces of judge-path: plurals, percentages, the first-run switch, the config key.

REQ-JP-11 (the pure part), REQ-JP-13, REQ-JP-16 and REQ-JP-17. Tier 1 normal cases, tier 2 edges,
tier 3 properties. Pure tests: no page, no clock, no network.
"""

import tomllib
from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from apps.phantom_invoices import explain_support as pi_support
from apps.vampire_fees import explain_support as vf_support
from apps.zombie_subscriptions import explain_support as zs_support
from ledger_kit.explainer import fill_fallback, format_times
from ledger_kit.models import Alert
from ledger_kit.ui import first_run
from ledger_kit.ui.first_run import should_autoload
from ledger_kit.ui.landing import NOT_AVAILABLE, percent_text

ROOT = Path(__file__).resolve().parents[1]


def _cancellation(count: object) -> Alert:
    return Alert(
        detector="zs.charges_after_cancellation",
        severity="critical",
        title="Charge after cancellation: GYMPLUS",
        source_refs=["bank.csv:3"],
        data={
            "counterparty": "GYMPLUS",
            "cancellation_date": "2026-03-31",
            "post_cancellation_count": count,
            "total_charged_after": "8.99",
            "yearly_cost": "107.88",
        },
    )


# --- REQ-JP-17: plurals ----------------------------------------------------------------------


def test_a_single_charge_after_cancellation_reads_1_time() -> None:
    text = fill_fallback(zs_support.TEMPLATES["zs.charges_after_cancellation"], _cancellation(1))

    assert text == (
        "GYMPLUS charged you 1 time totalling 8,99 EUR after your cancellation on 2026-03-31. "
        "Source: bank.csv:3."
    )


def test_three_charges_after_cancellation_read_3_times() -> None:
    text = fill_fallback(zs_support.TEMPLATES["zs.charges_after_cancellation"], _cancellation(3))

    assert text.startswith("GYMPLUS charged you 3 times totalling ")


@pytest.mark.parametrize(
    ("count", "expected"),
    [(1, "1 time"), (2, "2 times"), (0, "0 times"), (12, "12 times"), (Decimal("3"), "3 times")],
)
def test_format_times_writes_a_whole_count(count: object, expected: str) -> None:
    assert format_times(Decimal(str(count))) == expected


@pytest.mark.parametrize("value", ["1.5", "0.25", "-2.5"])
def test_format_times_leaves_a_count_that_is_not_whole_as_text(value: str) -> None:
    assert format_times(Decimal(value)) == value


def test_a_count_that_is_not_a_number_is_left_as_text_by_the_template() -> None:
    alert = Alert(
        detector="x.y", severity="info", title="t", source_refs=["f.csv:0"], data={"n": "many"}
    )

    assert fill_fallback("{n:times}", alert) == "many"


def test_no_fixed_template_writes_a_plural_in_brackets() -> None:
    templates = [
        *zs_support.TEMPLATES.values(),
        zs_support.CPI_SENTENCE,
        zs_support.CPI_SENTENCE_LAG,
        *pi_support.TEMPLATES.values(),
        *pi_support.SAME_DAY_TEMPLATES.values(),
        *vf_support.TEMPLATES.values(),
        vf_support.FEE_SUMMARY_NO_YEARLY_TEMPLATE,
    ]

    assert templates
    assert [t for t in templates if "(s)" in t or "(es)" in t] == []


@settings(max_examples=200, deadline=None)
@given(count=st.integers(min_value=0, max_value=10**6))
def test_the_count_is_always_followed_by_time_or_times(count: int) -> None:
    text = format_times(Decimal(count))

    assert text == (f"{count} time" if count == 1 else f"{count} times")


# --- REQ-JP-16: percentages ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ratio", "expected"),
    [
        ("0.9980", "99.8 %"),
        ("1.0000", "100.0 %"),
        ("0.0000", "0.0 %"),
        ("0.5000", "50.0 %"),
        ("0.9975", "99.8 %"),  # half up
        ("0.99949", "99.9 %"),
        ("0.9719", "97.2 %"),
        ("0.7742", "77.4 %"),
    ],
)
def test_percent_text_has_one_decimal_and_a_space_before_the_sign(
    ratio: str, expected: str
) -> None:
    assert percent_text(ratio) == expected


@pytest.mark.parametrize("ratio", [None, "n/a", "", "abc", "NaN", "Infinity", "-Infinity"])
def test_percent_text_of_no_ratio_is_not_available(ratio: object) -> None:
    assert percent_text(ratio) == NOT_AVAILABLE == "n/a"


@settings(max_examples=200, deadline=None)
@given(ratio=st.decimals(min_value=Decimal("0"), max_value=Decimal("1"), places=4))
def test_percent_text_is_a_percentage_between_0_and_100(ratio: Decimal) -> None:
    text = percent_text(f"{ratio:f}")
    number, sign = text.split(" ")

    assert sign == "%" and "." in number and len(number.split(".")[1]) == 1
    assert Decimal("0") <= Decimal(number) <= Decimal("100")
    assert abs(Decimal(number) - ratio * 100) <= Decimal("0.05")


# --- REQ-JP-11: the first-run switch -----------------------------------------------------------


def test_the_switch_is_on_in_production_and_off_in_the_tests_by_the_root_conftest() -> None:
    assert first_run.AUTOLOAD_DEMO is False  # root conftest.py, autouse
    source = (ROOT / "ledger_kit" / "ui" / "first_run.py").read_text(encoding="utf-8")
    assert "AUTOLOAD_DEMO: bool = True" in source


def test_autoload_fires_once_when_nothing_is_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(first_run, "AUTOLOAD_DEMO", True)
    state: dict[str, object] = {}

    assert should_autoload(state, "zs_autoloaded", False) is True
    assert state == {"zs_autoloaded": True}
    assert should_autoload(state, "zs_autoloaded", False) is False
    assert should_autoload(state, "zs_autoloaded", True) is False


def test_autoload_never_replaces_a_loaded_source_but_marks_the_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(first_run, "AUTOLOAD_DEMO", True)
    state: dict[str, object] = {}

    assert should_autoload(state, "k", True) is False
    assert state["k"] is True


def test_autoload_switched_off_does_nothing_but_still_marks_the_session() -> None:
    state: dict[str, object] = {}

    assert should_autoload(state, "k", False) is False
    assert state["k"] is True


# --- REQ-JP-13: the Deploy button -----------------------------------------------------------------


def test_the_client_table_hides_the_toolbar_for_visitors() -> None:
    text = (ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")
    config = tomllib.loads(text)

    assert config["client"] == {"toolbarMode": "viewer"}
    assert "neither" in text and "credentials" in text and "server" in text  # the comment
