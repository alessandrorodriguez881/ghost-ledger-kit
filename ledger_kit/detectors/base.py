"""Detector base types and the loaded-input helper (design §4.1)."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import pandas as pd

from ledger_kit.models import Alert


@dataclass(frozen=True)
class DetectorResult:
    """The alerts produced by one registered detector in one run."""

    name: str
    alerts: list[Alert]


class DetectorError(Exception):
    """Raised internally when a detector fails; caught by run_all."""

    def __init__(self, name: str, cause: Exception) -> None:
        """Remember the detector name and the original exception."""
        self.name = name
        self.cause = cause
        super().__init__(f"Detector '{name}' failed: {cause}")


def loaded_source_refs(ledger: pd.DataFrame, context: Mapping[str, Any]) -> frozenset[str]:
    """Return the source_ref values of the ledger and of every DataFrame in context.

    A frame without a `source_ref` column contributes nothing; non-DataFrame context
    values are ignored. Alert.source_refs must always be a subset of this set (REQ-DET-04).
    """
    refs: set[str] = set()
    for frame in (ledger, *context.values()):
        if isinstance(frame, pd.DataFrame) and "source_ref" in frame.columns:
            refs.update(str(r) for r in frame["source_ref"].dropna())
    return frozenset(refs)
