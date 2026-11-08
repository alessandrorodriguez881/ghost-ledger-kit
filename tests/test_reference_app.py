"""Headless tests of the Streamlit reference page (REQ-UI-01 to REQ-UI-08)."""

from collections.abc import Iterator
from pathlib import Path

import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from ledger_kit.detectors import (
    _clear_registry,
    _restore_registry,
    _snapshot_registry,
    register,
)
from ledger_kit.models import Alert

APP_PATH = str(Path(__file__).resolve().parents[1] / "ledger_kit" / "ui" / "reference_app.py")
TIMEOUT_SECONDS = 60

# One valid row (ref "t.csv:0") and one row with an unparseable date (quarantined).
SAMPLE_CSV = (
    b"date,amount,currency,counterparty,description\n"
    b"2026-01-09,-12.99,EUR,Streamly Plus,Monthly subscription\n"
    b"not-a-date,-5.00,EUR,Streamly Plus,Broken row\n"
)


class FakeUpload:
    """Minimal stand-in for Streamlit's UploadedFile (AppTest cannot upload files)."""

    def __init__(self, name: str, data: bytes) -> None:
        """Store the file name and bytes."""
        self.name = name
        self._data = data

    def getvalue(self) -> bytes:
        """Return the file bytes."""
        return self._data


@pytest.fixture
def empty_registry() -> Iterator[None]:
    """Run against an empty detector registry, then restore the previous contents."""
    snapshot = _snapshot_registry()
    _clear_registry()
    try:
        yield
    finally:
        _restore_registry(snapshot)


@pytest.fixture
def uploaded_sample(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make `st.file_uploader` return one sample CSV (the script runs in this process)."""
    monkeypatch.setattr(st, "file_uploader", lambda *a, **k: [FakeUpload("t.csv", SAMPLE_CSV)])


def _run() -> AppTest:
    """Run the reference page headless."""
    return AppTest.from_file(APP_PATH, default_timeout=TIMEOUT_SECONDS).run()


def test_reference_app_empty_state_shows_title_and_info() -> None:
    """With no upload the page shows the title and the empty-state hint, no exception."""
    at = _run()
    assert not at.exception
    assert at.title[0].value == "Ghost Ledger Kit — Ledger Analyser"
    assert any("Upload one or more" in info.value for info in at.info)


def test_reference_app_shows_quarantine_section(
    uploaded_sample: None, empty_registry: None
) -> None:
    """A sample with one bad row renders the quarantine expander and the no-alerts note."""
    at = _run()
    assert not at.exception
    labels = [expander.label for expander in at.expander]
    assert any(label.startswith("⚠ Quarantined rows (1)") for label in labels)
    assert any("No alerts" in markdown.value for markdown in at.markdown)


def test_reference_app_renders_alert_for_registered_detector(
    uploaded_sample: None, empty_registry: None
) -> None:
    """A throwaway detector's alert is shown as an expander with its severity and title."""

    @register("tapp.sample")
    def _detector(ledger: pd.DataFrame, context: object) -> list[Alert]:
        """Cite the first ledger row."""
        if ledger.empty:
            return []
        return [
            Alert(
                detector="tapp.sample",
                severity="warning",
                title="Throwaway alert",
                source_refs=[str(ledger["source_ref"].iloc[0])],
                data={},
            )
        ]

    at = _run()
    assert not at.exception
    labels = [expander.label for expander in at.expander]
    assert any("[warning] Throwaway alert" in label for label in labels)
    metrics = {metric.label: metric.value for metric in at.metric}
    assert metrics["🟡 warning"] == "1"
