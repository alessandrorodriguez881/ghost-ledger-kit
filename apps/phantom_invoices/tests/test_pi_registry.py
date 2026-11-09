"""Tests for the registration of the pi.* detectors and run_pi_detectors (Task P14)."""

import logging
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

import pandas as pd
import pytest

from apps.phantom_invoices.detectors import LABELS, run_pi_detectors
from apps.phantom_invoices.detectors.duplicate_invoice import detect_duplicate_invoices
from apps.phantom_invoices.detectors.iban_change import detect_iban_changes
from apps.phantom_invoices.detectors.reconciliation import detect_reconciliation
from apps.phantom_invoices.detectors.vat_error import detect_vat_errors
from apps.phantom_invoices.tests.pi_builders import (
    Scenario,
    make_invoices,
    make_payments,
    make_suppliers,
)
from ledger_kit.detectors import DetectorResult, auto_discover, register, registered_names
from ledger_kit.models import Alert

EXPECTED_NAMES = [
    "pi.duplicate_invoice",
    "pi.iban_change",
    "pi.reconciliation",
    "pi.vat_error",
]

# Every test in this module may register probes: snapshot and restore the global registry.
pytestmark = pytest.mark.usefixtures("isolated_registry")


def _snapshot_frames(scenario: Scenario) -> dict[str, pd.DataFrame]:
    """Return independent copies of the three frames of a scenario."""
    return {
        "invoices": scenario.invoices.copy(deep=True),
        "suppliers": scenario.suppliers.copy(deep=True),
        "payments": scenario.payments.copy(deep=True),
    }


# Tier 1: normal cases


def test_auto_discover_registers_four_pi_detectors() -> None:
    """Discovering the package registers exactly the four pi.* detectors."""
    auto_discover("apps.phantom_invoices.detectors")

    assert sorted(registered_names(namespace="pi")) == EXPECTED_NAMES


def test_labels_cover_every_registered_pi_detector() -> None:
    """LABELS has one entry per registered pi.* detector, with the documented spelling."""
    assert sorted(LABELS) == sorted(registered_names(namespace="pi"))
    assert LABELS["pi.iban_change"] == "Poltergeist IBAN"
    assert LABELS["pi.duplicate_invoice"] == "Duplicate invoice"
    assert LABELS["pi.vat_error"] == "VAT error"
    assert LABELS["pi.reconciliation"] == "Reconciliation"


def test_run_pi_detectors_empty_everything_returns_empty_alerts(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Four results, each with no alert and no logged failure."""
    with caplog.at_level(logging.WARNING):
        results = run_pi_detectors(make_invoices([]), make_suppliers([]), make_payments([]))

    assert all(isinstance(result, DetectorResult) for result in results)
    assert sorted(result.name for result in results) == EXPECTED_NAMES
    assert [result.alerts for result in results] == [[], [], [], []]
    assert [r for r in caplog.records if "raised" in r.getMessage()] == []


def test_run_pi_detectors_passes_the_context_keys() -> None:
    """The context carries suppliers, payments and as_of (REQ-PI-02)."""
    seen: list[Mapping[str, Any]] = []

    @register("pi.probe_keys")
    def _probe(ledger: pd.DataFrame, context: Mapping[str, Any]) -> list[Alert]:
        """Record the context object."""
        seen.append(context)
        return []

    suppliers, payments = make_suppliers([{}]), make_payments([{}])
    run_pi_detectors(make_invoices([]), suppliers, payments)

    assert len(seen) == 1
    assert set(seen[0]) == {"suppliers", "payments", "as_of"}
    assert seen[0]["suppliers"] is suppliers
    assert seen[0]["payments"] is payments
    assert seen[0]["as_of"] is None


def test_run_all_passes_context_as_mapping_proxy_and_detectors_do_not_mutate_it(
    ledger_with_double_payment: Scenario,
) -> None:
    """Detectors get a read-only mapping and leave every frame of the context unchanged."""
    seen: list[Mapping[str, Any]] = []
    blocked: list[bool] = []

    @register("pi.probe_context")
    def _probe(ledger: pd.DataFrame, context: Mapping[str, Any]) -> list[Alert]:
        """Record the context object and try to write to it."""
        seen.append(context)
        try:
            context["as_of"] = None  # type: ignore[index]
        except TypeError:
            blocked.append(True)
        return []

    scenario = ledger_with_double_payment
    before = _snapshot_frames(scenario)

    run_pi_detectors(scenario.invoices, scenario.suppliers, scenario.payments)

    assert isinstance(seen[0], MappingProxyType)
    assert blocked == [True]
    pd.testing.assert_frame_equal(scenario.invoices, before["invoices"])
    pd.testing.assert_frame_equal(scenario.suppliers, before["suppliers"])
    pd.testing.assert_frame_equal(scenario.payments, before["payments"])


def test_no_zs_detector_runs_in_pi_namespace() -> None:
    """A detector of another namespace is never run by run_pi_detectors."""
    ran: list[str] = []

    @register("zs_probe.never")
    def _other(ledger: pd.DataFrame, context: Mapping[str, Any]) -> list[Alert]:
        """Record that it ran."""
        ran.append("zs_probe.never")
        return []

    results = run_pi_detectors(make_invoices([]), make_suppliers([]), make_payments([]))

    assert ran == []
    assert all(result.name.startswith("pi.") for result in results)
    assert not any(result.name.startswith("zs.") for result in results)


def test_clean_ledger_10_raises_no_alert_from_any_detector(
    clean_ledger_10: pd.DataFrame,
    suppliers_master: pd.DataFrame,
    payments_for_clean: pd.DataFrame,
) -> None:
    """The clean fixtures give four results and no alert (the Task P9 placeholder, enabled)."""
    results = run_pi_detectors(clean_ledger_10, suppliers_master, payments_for_clean)

    assert len(results) == 4
    assert [result.alerts for result in results] == [[], [], [], []]


def test_pi_acceptance_p01_no_other_detector_fires(
    ledger_with_duplicate_invoice: Scenario,
) -> None:
    """P1 through run_pi_detectors: exactly one alert in total, and it is critical."""
    scenario = ledger_with_duplicate_invoice

    results = run_pi_detectors(scenario.invoices, scenario.suppliers, scenario.payments)

    alerts = [alert for result in results for alert in result.alerts]
    assert len(alerts) == 1
    assert alerts[0].detector == "pi.duplicate_invoice"
    assert alerts[0].severity == "critical"


# Tier 2: edge cases


@pytest.mark.parametrize(
    "detector",
    [detect_duplicate_invoices, detect_iban_changes, detect_reconciliation, detect_vat_errors],
)
def test_detectors_accept_empty_mapping_proxy_context(
    detector: Any, clean_ledger_10: pd.DataFrame
) -> None:
    """Each detector returns a list for an empty context and either an empty or a full ledger."""
    empty_context: Mapping[str, Any] = MappingProxyType({})

    assert detector(pd.DataFrame(), empty_context) == []
    assert isinstance(detector(clean_ledger_10, empty_context), list)


def test_run_pi_detectors_explicit_as_of_reaches_the_detectors(
    ledger_with_unpaid_invoice: Scenario,
) -> None:
    """An explicit as_of far before the due date silences the overdue alert."""
    scenario = ledger_with_unpaid_invoice
    derived = run_pi_detectors(scenario.invoices, scenario.suppliers, scenario.payments)
    early = run_pi_detectors(
        scenario.invoices,
        scenario.suppliers,
        scenario.payments,
        as_of=scenario.invoices["issue_date"].iloc[0],
    )

    derived_variants = {a.data["variant"] for r in derived for a in r.alerts}
    early_variants = {a.data["variant"] for r in early for a in r.alerts}
    assert "invoice_overdue" in derived_variants
    assert "invoice_overdue" not in early_variants
