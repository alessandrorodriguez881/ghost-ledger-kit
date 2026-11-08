"""Detector registry: decorator, auto-discovery and runner (design §4.2)."""

import importlib
import logging
import pkgutil
import re
import types
from collections.abc import Callable, Mapping
from typing import Any

import pandas as pd

from ledger_kit.detectors.base import DetectorResult
from ledger_kit.models import Alert

DetectorFn = Callable[[pd.DataFrame, Mapping[str, Any]], list[Alert]]

_REGISTRY: dict[str, DetectorFn] = {}
_log = logging.getLogger(__name__)

# '<namespace>.<detector>', both parts non-empty lowercase snake_case.
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")


def register(name: str) -> Callable[[DetectorFn], DetectorFn]:
    """Return a decorator that registers a detector under `name` ('<namespace>.<detector>')."""
    if not _NAME_RE.match(name):
        raise ValueError(
            f"Detector name {name!r} must match '<namespace>.<detector>' "
            "with both parts being non-empty lowercase snake_case."
        )

    def decorator(fn: DetectorFn) -> DetectorFn:
        """Store `fn` in the registry and return it unchanged."""
        if name in _REGISTRY:
            raise ValueError(f"Detector '{name}' is already registered.")
        _REGISTRY[name] = fn
        return fn

    return decorator


def auto_discover(package: str) -> None:
    """Import all modules in `package` in sorted name order, triggering @register decorators."""
    pkg = importlib.import_module(package)
    modules = sorted(
        module_name
        for _, module_name, _ in pkgutil.walk_packages(pkg.__path__, prefix=f"{package}.")
    )
    for module_name in modules:
        importlib.import_module(module_name)


def run_all(
    ledger: pd.DataFrame,
    *,
    namespace: str | None = None,
    context: Mapping[str, Any] | None = None,
) -> list[DetectorResult]:
    """Run registered detectors in insertion order, isolating failures per detector."""
    proxy: Mapping[str, Any] = types.MappingProxyType(dict(context) if context else {})
    results: list[DetectorResult] = []
    for name, fn in list(_REGISTRY.items()):
        if namespace is not None and not name.startswith(namespace + "."):
            continue
        try:
            alerts = fn(ledger, proxy)
        except Exception as exc:
            _log.warning("Detector '%s' raised %s: %s", name, type(exc).__name__, exc)
            alerts = []
        results.append(DetectorResult(name=name, alerts=alerts))
    return results


def registered_names(namespace: str | None = None) -> list[str]:
    """Return registered detector names in insertion order, optionally for one namespace."""
    if namespace is None:
        return list(_REGISTRY.keys())
    prefix = namespace + "."
    return [n for n in _REGISTRY if n.startswith(prefix)]


def _clear_registry() -> None:
    """Remove all registered detectors. For use in tests only (prefer snapshot/restore)."""
    _REGISTRY.clear()


def _snapshot_registry() -> dict[str, DetectorFn]:
    """Return a copy of the registry for later restore. For use in tests only."""
    return dict(_REGISTRY)


def _restore_registry(snapshot: dict[str, DetectorFn]) -> None:
    """Replace the registry contents with `snapshot` (same dict object). Tests only."""
    _REGISTRY.clear()
    _REGISTRY.update(snapshot)
