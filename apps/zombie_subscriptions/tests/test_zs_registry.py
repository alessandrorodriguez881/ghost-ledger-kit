"""Tests for the registry integration of the zs detectors (Task Z16)."""

import copy
from collections.abc import Iterator, Mapping
from datetime import date
from typing import Any

import pandas as pd
import pytest

import apps.zombie_subscriptions.detectors as zs_detectors
from apps.zombie_subscriptions.detectors import utils
from ledger_kit.detectors import (
    DetectorResult,
    _restore_registry,
    _snapshot_registry,
    auto_discover,
    register,
    registered_names,
    run_all,
)
from ledger_kit.models import Alert

EXPECTED_NAMES = [
    "zs.charges_after_cancellation",
    "zs.duplicate_subscription",
    "zs.free_trial_to_paid",
    "zs.price_increase",
    "zs.recurring_charge",
]
NO_INPUT = {"aliases": None, "cancellation_dates": None}


@pytest.fixture(autouse=True)
def _isolated_registry() -> Iterator[None]:
    """Snapshot the registry before a test and restore it afterwards (never clears it)."""
    snapshot = _snapshot_registry()
    try:
        yield
    finally:
        _restore_registry(snapshot)


def _fired(results: list[DetectorResult]) -> set[str]:
    """Return the names of the detectors that produced at least one alert."""
    return {r.name for r in results if r.alerts}


def test_auto_discover_registers_five_zs_detectors() -> None:
    """Discovering the package registers exactly the five zs detectors."""
    auto_discover("apps.zombie_subscriptions.detectors")
    assert sorted(registered_names("zs")) == EXPECTED_NAMES


def test_normalise_counterparty_is_reexported_by_the_package() -> None:
    """REQ-ZS-06: the helper is importable from the detectors package."""
    assert zs_detectors.normalise_counterparty is utils.normalise_counterparty
    assert zs_detectors.normalise_counterparty("BEATSTREAM P2A3B4C5") == "BEATSTREAM"


def test_run_all_zs_namespace_on_empty_ledger_returns_empty_alerts(
    empty_ledger: pd.DataFrame,
) -> None:
    """All five zs detectors run on an empty ledger and return no alerts."""
    results = run_all(empty_ledger, namespace="zs", context=NO_INPUT)
    assert sorted(r.name for r in results) == EXPECTED_NAMES
    assert all(r.alerts == [] for r in results)


def test_run_all_passes_context_as_mapping_proxy_and_detectors_do_not_mutate_it(
    ledger_with_post_cancellation: pd.DataFrame,
) -> None:
    """Detectors receive a read-only mapping, and the caller's context stays unchanged."""
    seen: list[Mapping[str, Any]] = []
    blocked: list[bool] = []

    @register("zs_probe.context")
    def _probe(ledger: pd.DataFrame, context: Mapping[str, Any]) -> list[Alert]:
        """Record the context object and try to write to it."""
        seen.append(context)
        try:
            context["aliases"] = {}  # type: ignore[index]
        except TypeError:
            blocked.append(True)
        return []

    context = {"aliases": {"GYM": ["GYMPLUS"]}, "cancellation_dates": {"GYM": date(2026, 3, 31)}}
    before = copy.deepcopy(context)
    run_all(ledger_with_post_cancellation, namespace="zs_probe", context=context)
    assert type(seen[0]).__name__ == "mappingproxy"
    assert blocked == [True]
    run_all(ledger_with_post_cancellation, namespace="zs", context=context)
    assert context == before


def test_e7b_run_all_produces_no_alerts_of_any_kind(
    ledger_with_weekly_shopping: pd.DataFrame,
) -> None:
    """Acceptance E7b: 26 weekly supermarket charges raise no alert from any zs detector."""
    results = run_all(ledger_with_weekly_shopping, namespace="zs", context=NO_INPUT)
    assert len(results) == len(EXPECTED_NAMES)
    assert _fired(results) == set()


@pytest.mark.parametrize(
    ("fixture_name", "context", "expected"),
    [
        ("ledger_with_recurring", NO_INPUT, {"zs.recurring_charge"}),
        (
            "ledger_with_price_increase",
            NO_INPUT,
            {"zs.recurring_charge", "zs.price_increase"},
        ),
        (
            "ledger_with_duplicate_sub",
            NO_INPUT,
            {"zs.recurring_charge", "zs.duplicate_subscription"},
        ),
        (
            "ledger_with_free_trial",
            NO_INPUT,
            {"zs.recurring_charge", "zs.free_trial_to_paid"},
        ),
        (
            "ledger_with_post_cancellation",
            {"aliases": None, "cancellation_dates": {"GYMPLUS": date(2026, 3, 31)}},
            {"zs.recurring_charge", "zs.charges_after_cancellation"},
        ),
    ],
)
def test_run_all_on_acceptance_fixtures_expected_detectors_fire(
    request: pytest.FixtureRequest,
    fixture_name: str,
    context: dict[str, Any],
    expected: set[str],
) -> None:
    """Each acceptance fixture makes exactly the expected zs detectors fire."""
    ledger = request.getfixturevalue(fixture_name)
    results = run_all(ledger, namespace="zs", context=context)
    assert _fired(results) == expected


def test_run_zs_detectors_wrapper_matches_run_all(
    ledger_with_post_cancellation: pd.DataFrame,
) -> None:
    """run_zs_detectors is run_all(namespace='zs') with the two user inputs as context."""
    cancellation = {"GYMPLUS": date(2026, 3, 31)}
    wrapped = zs_detectors.run_zs_detectors(
        ledger_with_post_cancellation, aliases=None, cancellation_dates=cancellation
    )
    direct = run_all(
        ledger_with_post_cancellation,
        namespace="zs",
        context={"aliases": None, "cancellation_dates": cancellation},
    )
    assert wrapped == direct
    assert _fired(wrapped) == {"zs.recurring_charge", "zs.charges_after_cancellation"}
