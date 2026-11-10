"""Tests for the registry integration of the vf detectors (Task VF10; REQ-VF-05)."""

from collections.abc import Iterator

import pandas as pd
import pytest

from apps.vampire_fees.detectors.utils import EMPTY_VOCABULARY
from ledger_kit.detectors import (
    _restore_registry,
    _snapshot_registry,
    auto_discover,
    registered_names,
    run_all,
)

PACKAGE = "apps.vampire_fees.detectors"
EXPECTED_NAMES = [
    "vf.fee_increase",
    "vf.fee_summary",
    "vf.overdraft_cost",
    "vf.recurring_fee",
]


@pytest.fixture(autouse=True)
def _isolated_registry() -> Iterator[None]:
    """Snapshot the registry before a test and restore it afterwards (never clears it)."""
    snapshot = _snapshot_registry()
    try:
        yield
    finally:
        _restore_registry(snapshot)


def test_auto_discover_registers_the_four_vf_detectors() -> None:
    """Discovering the package registers exactly the four vf detectors."""
    auto_discover(PACKAGE)
    assert sorted(registered_names("vf")) == EXPECTED_NAMES


def test_auto_discover_twice_does_not_raise() -> None:
    """A second discovery imports nothing new and keeps the same names."""
    auto_discover(PACKAGE)
    auto_discover(PACKAGE)
    assert sorted(registered_names("vf")) == EXPECTED_NAMES


def test_every_name_is_in_the_vf_namespace() -> None:
    """All four names are '<vf>.<snake_case>' and no other namespace is touched."""
    auto_discover(PACKAGE)
    assert all(name.startswith("vf.") for name in registered_names("vf"))
    assert not any(name.startswith("vf.") for name in registered_names("zs"))
    assert not any(name.startswith("vf.") for name in registered_names("pi"))


def test_run_all_vf_namespace_on_empty_ledger(empty_ledger: pd.DataFrame) -> None:
    """All four detectors run on an empty ledger and return no alerts."""
    results = run_all(empty_ledger, namespace="vf", context={"vocabulary": EMPTY_VOCABULARY})
    assert sorted(r.name for r in results) == EXPECTED_NAMES
    assert all(r.alerts == [] for r in results)


def test_run_all_without_context_does_not_raise(single_row_ledger: pd.DataFrame) -> None:
    """Detectors classify by concept only when the vocabulary is absent (REQ-VF-12)."""
    results = run_all(single_row_ledger, namespace="vf")
    assert sorted(r.name for r in results) == EXPECTED_NAMES
    assert all(r.alerts == [] for r in results)


def test_run_all_on_the_monthly_fee_fixture(
    ledger_with_monthly_fee: pd.DataFrame, vocabulary: object
) -> None:
    """The typical fixture fires the recurring-fee and the summary detectors only."""
    results = run_all(ledger_with_monthly_fee, namespace="vf", context={"vocabulary": vocabulary})
    fired = {r.name for r in results if r.alerts}
    assert fired == {"vf.recurring_fee", "vf.fee_summary"}
