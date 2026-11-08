"""Registry-isolation fixtures for detector tests (design §4.2, OD-4; REQ-TST-09)."""

from collections.abc import Iterator

import pytest

from ledger_kit.detectors import _clear_registry, _restore_registry, _snapshot_registry


@pytest.fixture
def isolated_registry() -> Iterator[None]:
    """Snapshot the registry before a test and restore it afterwards (never clears)."""
    snapshot = _snapshot_registry()
    try:
        yield
    finally:
        _restore_registry(snapshot)


@pytest.fixture
def empty_registry() -> Iterator[None]:
    """Run a test against an empty registry, then restore the previous contents."""
    snapshot = _snapshot_registry()
    _clear_registry()
    try:
        yield
    finally:
        _restore_registry(snapshot)
