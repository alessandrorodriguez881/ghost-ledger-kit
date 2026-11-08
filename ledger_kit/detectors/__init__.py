"""Detector layer: base types, registry and runner."""

from ledger_kit.detectors.base import DetectorError, DetectorResult, loaded_source_refs
from ledger_kit.detectors.registry import (
    _clear_registry,
    _restore_registry,
    _snapshot_registry,
    auto_discover,
    register,
    registered_names,
    run_all,
)

__all__ = [
    "register",
    "auto_discover",
    "run_all",
    "registered_names",
    "_clear_registry",
    "_snapshot_registry",
    "_restore_registry",
    "DetectorResult",
    "DetectorError",
    "loaded_source_refs",
]
