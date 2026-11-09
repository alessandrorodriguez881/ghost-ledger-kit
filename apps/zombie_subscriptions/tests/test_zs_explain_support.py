"""Tests for explain_support.py: fallback templates and the hallucinating stub (Task Z18)."""

import re
from typing import Any

import pandas as pd
import pytest

import apps.zombie_subscriptions.detectors  # noqa: F401  (registers the zs.* detectors)
from apps.zombie_subscriptions.explain_support import TEMPLATES, HallucinatingStubClient
from ledger_kit.detectors import registered_names, run_all
from ledger_kit.explainer import explain_with_meta, fill_fallback
from ledger_kit.models import Alert

INJECTED = "99999.99"
ALL_DETECTORS = {
    "zs.recurring_charge",
    "zs.price_increase",
    "zs.duplicate_subscription",
    "zs.free_trial_to_paid",
    "zs.charges_after_cancellation",
}
PLACEHOLDER = re.compile(r"\{[^{}]*\}")


@pytest.fixture
def zs_alerts(
    builders: Any,
    ledger_with_price_increase: pd.DataFrame,
    ledger_with_duplicate_sub: pd.DataFrame,
    ledger_with_free_trial: pd.DataFrame,
    ledger_with_post_cancellation: pd.DataFrame,
) -> dict[str, tuple[Alert, pd.DataFrame]]:
    """One alert per zs detector, each with the ledger it came from."""
    no_input: dict[str, Any] = {"aliases": None, "cancellation_dates": None}
    cancelled = {"aliases": None, "cancellation_dates": {"GYMPLUS": builders.cancellation_date}}
    cases = [
        (ledger_with_price_increase, no_input),
        (ledger_with_duplicate_sub, no_input),
        (ledger_with_free_trial, no_input),
        (ledger_with_post_cancellation, cancelled),
    ]
    found: dict[str, tuple[Alert, pd.DataFrame]] = {}
    for ledger, context in cases:
        for result in run_all(ledger, namespace="zs", context=context):
            for alert in result.alerts:
                found.setdefault(alert.detector, (alert, ledger))
    return found


def _cited_rows(alert: Alert, ledger: pd.DataFrame) -> pd.DataFrame:
    """Return the ledger rows an alert cites."""
    return ledger[ledger["source_ref"].isin(alert.source_refs)]


# --- Tier 1 -----------------------------------------------------------------------------------


def test_templates_cover_every_registered_zs_detector() -> None:
    """TEMPLATES has exactly one entry per registered zs.* detector."""
    assert set(TEMPLATES) == set(registered_names("zs")) == ALL_DETECTORS


def test_every_template_fills_from_its_alert_data(
    zs_alerts: dict[str, tuple[Alert, pd.DataFrame]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without an API key every template is filled completely, in European format, with a ref."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert set(zs_alerts) == ALL_DETECTORS
    for detector, (alert, ledger) in zs_alerts.items():
        meta = explain_with_meta(
            alert,
            _cited_rows(alert, ledger),
            fallback_template=TEMPLATES[detector],
            client=None,
        )
        assert meta.source == "fallback", detector
        assert meta.rejected_numbers == (), detector
        assert PLACEHOLDER.search(meta.text) is None, f"{detector}: unfilled placeholder"
        assert alert.source_refs[0] in meta.text, detector
        assert " EUR" in meta.text, detector


def test_recurring_template_uses_european_amounts(
    zs_alerts: dict[str, tuple[Alert, pd.DataFrame]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The E1 recurring alert shows 15,99 EUR and 191,88 EUR (no dot decimals)."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    alert, ledger = zs_alerts["zs.recurring_charge"]
    text = explain_with_meta(
        alert, _cited_rows(alert, ledger), fallback_template=TEMPLATES[alert.detector]
    ).text
    assert "15,99 EUR" in text
    assert "191,88 EUR" in text
    assert "191.88" not in text


def test_hallucinating_stub_is_rejected_by_number_guard(
    zs_alerts: dict[str, tuple[Alert, pd.DataFrame]],
) -> None:
    """The stub's foreign number is rejected for every detector; the filled template is used."""
    for detector, (alert, ledger) in zs_alerts.items():
        meta = explain_with_meta(
            alert,
            _cited_rows(alert, ledger),
            fallback_template=TEMPLATES[detector],
            client=HallucinatingStubClient(),
        )
        assert meta.source == "fallback", detector
        assert INJECTED in meta.rejected_numbers, detector
        assert meta.text == fill_fallback(TEMPLATES[detector], alert), detector
        assert INJECTED not in meta.text, detector


def test_stub_shape_matches_mock_client() -> None:
    """chat and completions are properties returning the stub; create returns choices[0]."""
    assert isinstance(HallucinatingStubClient.chat, property)
    assert isinstance(HallucinatingStubClient.completions, property)
    stub = HallucinatingStubClient()
    assert stub.chat is stub
    assert stub.completions is stub
    response = stub.chat.completions.create(
        model="any", messages=[{"role": "user", "content": "x"}]
    )
    content = response.choices[0].message.content
    assert isinstance(content, str)
    assert HallucinatingStubClient.INJECTED_NUMBER == INJECTED
    assert INJECTED in content


# --- Tier 2 -----------------------------------------------------------------------------------


def test_stub_ignores_extra_kwargs() -> None:
    """Extra keyword arguments (temperature, model, ...) are accepted and ignored."""
    stub = HallucinatingStubClient()
    response = stub.chat.completions.create(
        messages=[], model="m", temperature=0, timeout=1, anything="goes"
    )
    assert INJECTED in response.choices[0].message.content


def test_injected_number_not_in_any_fixture_alert(
    zs_alerts: dict[str, tuple[Alert, pd.DataFrame]],
) -> None:
    """The stub's number appears in no alert payload and no cited row, so the guard must fire."""
    for detector, (alert, ledger) in zs_alerts.items():
        assert INJECTED not in str(alert.data), detector
        assert INJECTED not in _cited_rows(alert, ledger).to_string(), detector
        assert INJECTED not in alert.title, detector
