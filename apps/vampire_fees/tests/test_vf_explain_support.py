"""Tests for explain_support.py: fallback templates and the hallucinating stub (Task VF10)."""

import re
import string
from datetime import date
from types import SimpleNamespace
from typing import Any, Self

import pandas as pd
import pytest

import apps.vampire_fees.detectors  # noqa: F401  (registers the vf.* detectors)
from apps.vampire_fees.detectors.fee_increase import detect_fee_increases
from apps.vampire_fees.detectors.fee_summary import detect_fee_summary
from apps.vampire_fees.detectors.overdraft_cost import detect_overdraft_cost
from apps.vampire_fees.detectors.recurring_fee import detect_recurring_fees
from apps.vampire_fees.explain_support import (
    FEE_SUMMARY_NO_YEARLY_TEMPLATE,
    TEMPLATES,
    HallucinatingStubClient,
    template_for,
)
from apps.vampire_fees.tests.vf_builders import default_vocabulary, summary_ledger
from ledger_kit.detectors import registered_names
from ledger_kit.explainer import explain_with_meta, fill_fallback
from ledger_kit.models import Alert

INJECTED = "99999.99"
ALL_DETECTORS = {
    "vf.recurring_fee",
    "vf.fee_increase",
    "vf.overdraft_cost",
    "vf.fee_summary",
}
CONTEXT = {"vocabulary": default_vocabulary()}
PLACEHOLDER = re.compile(r"\{[^{}]*\}")

EXPECTED_WITH_YEARLY = (
    "Between 2026-01-01 and 2026-03-31 (90 days) your statement shows 2 bank fees totalling "
    "30,00 EUR, about 121,67 EUR per year. Source: s.csv:3, s.csv:5."
)
EXPECTED_WITHOUT_YEARLY = (
    "Between 2026-01-01 and 2026-03-30 (89 days) your statement shows 2 bank fees totalling "
    "30,00 EUR. Source: s.csv:3, s.csv:5."
)


class EchoClient:
    """OpenAI-shaped client that answers with a fixed text (used to test acceptance)."""

    def __init__(self, text: str) -> None:
        """Remember the answer."""
        self.text = text

    @property
    def chat(self) -> Self:
        """Mirror `client.chat`."""
        return self

    @property
    def completions(self) -> Self:
        """Mirror `client.chat.completions`."""
        return self

    def create(self, **_kwargs: Any) -> SimpleNamespace:
        """Return a response whose text is the stored answer."""
        message = SimpleNamespace(content=self.text)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


@pytest.fixture
def vf_alerts(
    ledger_with_monthly_fee: pd.DataFrame,
    ledger_with_fee_increase: pd.DataFrame,
    ledger_with_overdraft: pd.DataFrame,
) -> dict[str, tuple[Alert, pd.DataFrame]]:
    """One alert per vf detector (the summary with its yearly figure), each with its ledger."""
    summary = summary_ledger()
    return {
        "vf.recurring_fee": (
            detect_recurring_fees(ledger_with_monthly_fee, CONTEXT)[0],
            ledger_with_monthly_fee,
        ),
        "vf.fee_increase": (
            detect_fee_increases(ledger_with_fee_increase, CONTEXT)[0],
            ledger_with_fee_increase,
        ),
        "vf.overdraft_cost": (
            detect_overdraft_cost(ledger_with_overdraft, CONTEXT)[0],
            ledger_with_overdraft,
        ),
        "vf.fee_summary": (detect_fee_summary(summary, CONTEXT)[0], summary),
    }


def _cited_rows(alert: Alert, ledger: pd.DataFrame) -> pd.DataFrame:
    """Return the ledger rows an alert cites."""
    return ledger[ledger["source_ref"].isin(alert.source_refs)]


def _placeholder_keys(template: str) -> set[str]:
    """Return the field names used by a template, without format specs."""
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


# --- Tier 1 -------------------------------------------------------------------------------------


def test_templates_cover_every_registered_vf_detector() -> None:
    """TEMPLATES has exactly one entry per registered vf.* detector."""
    assert set(TEMPLATES) == set(registered_names("vf")) == ALL_DETECTORS


def test_every_placeholder_is_a_data_key_or_source_refs(
    vf_alerts: dict[str, tuple[Alert, pd.DataFrame]],
) -> None:
    """REQ-VF-36: each placeholder of the chosen template is a key of data (or source_refs)."""
    short = detect_fee_summary(summary_ledger(date(2026, 3, 30)), CONTEXT)[0]
    for alert in [*(a for a, _ in vf_alerts.values()), short]:
        keys = _placeholder_keys(template_for(alert))
        assert keys <= set(alert.data) | {"source_refs"}, alert.detector


def test_templates_hold_no_digit() -> None:
    """No template contains a literal digit (Finance Rule 1)."""
    for template in [*TEMPLATES.values(), FEE_SUMMARY_NO_YEARLY_TEMPLATE]:
        assert not any(ch.isdigit() for ch in template)


def test_templates_give_no_advice() -> None:
    """No template tells the user what to do (Finance Rule 8)."""
    words = ("cancel", "close", "should", "switch", "refuse", "recommend")
    for template in [*TEMPLATES.values(), FEE_SUMMARY_NO_YEARLY_TEMPLATE]:
        assert not any(word in template.lower() for word in words)


def test_every_template_fills_from_its_alert_data(
    vf_alerts: dict[str, tuple[Alert, pd.DataFrame]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without an API key every template is filled completely, European, with a source ref."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert set(vf_alerts) == ALL_DETECTORS
    for detector, (alert, ledger) in vf_alerts.items():
        meta = explain_with_meta(
            alert,
            _cited_rows(alert, ledger),
            fallback_template=template_for(alert),
            client=None,
        )
        assert meta.source == "fallback", detector
        assert meta.rejected_numbers == (), detector
        assert PLACEHOLDER.search(meta.text) is None, f"{detector}: unfilled placeholder"
        assert alert.source_refs[0] in meta.text, detector
        assert " EUR" in meta.text, detector


def test_ae_vf_27_summary_text_with_and_without_the_yearly_sentence() -> None:
    """AE-VF-27: the two exact strings."""
    long_alert = detect_fee_summary(summary_ledger(), CONTEXT)[0]
    short_alert = detect_fee_summary(summary_ledger(date(2026, 3, 30)), CONTEXT)[0]
    assert fill_fallback(template_for(long_alert), long_alert) == EXPECTED_WITH_YEARLY
    assert fill_fallback(template_for(short_alert), short_alert) == EXPECTED_WITHOUT_YEARLY


def test_template_for_chooses_the_summary_variant(
    vf_alerts: dict[str, tuple[Alert, pd.DataFrame]],
) -> None:
    """The no-yearly variant is used exactly when yearly_equivalent is absent."""
    with_yearly = vf_alerts["vf.fee_summary"][0]
    without = detect_fee_summary(summary_ledger(date(2026, 3, 30)), CONTEXT)[0]
    assert template_for(with_yearly) == TEMPLATES["vf.fee_summary"]
    assert template_for(without) == FEE_SUMMARY_NO_YEARLY_TEMPLATE
    for detector in ("vf.recurring_fee", "vf.fee_increase", "vf.overdraft_cost"):
        assert template_for(vf_alerts[detector][0]) == TEMPLATES[detector]


def test_a_template_given_as_the_llm_answer_passes_the_guard(
    vf_alerts: dict[str, tuple[Alert, pd.DataFrame]],
) -> None:
    """REQ-VF-39: the filled template as an 'LLM' answer is accepted (source llm)."""
    for detector, (alert, ledger) in vf_alerts.items():
        answer = fill_fallback(template_for(alert), alert)
        meta = explain_with_meta(
            alert,
            _cited_rows(alert, ledger),
            fallback_template=template_for(alert),
            client=EchoClient(answer),
        )
        assert meta.source == "llm", f"{detector}: {meta.rejected_numbers}"
        assert meta.rejected_numbers == (), detector
        assert meta.text == answer, detector


def test_hallucinating_stub_is_rejected_by_the_number_guard(
    vf_alerts: dict[str, tuple[Alert, pd.DataFrame]],
) -> None:
    """The stub's foreign number is rejected for every detector; the filled template is used."""
    for detector, (alert, ledger) in vf_alerts.items():
        meta = explain_with_meta(
            alert,
            _cited_rows(alert, ledger),
            fallback_template=template_for(alert),
            client=HallucinatingStubClient(),
        )
        assert meta.source == "fallback", detector
        assert INJECTED in meta.rejected_numbers, detector
        assert meta.text == fill_fallback(template_for(alert), alert), detector
        assert INJECTED not in meta.text, detector


def test_stub_shape_matches_the_other_apps() -> None:
    """chat and completions are properties returning the stub; create returns choices[0]."""
    assert isinstance(HallucinatingStubClient.chat, property)
    assert isinstance(HallucinatingStubClient.completions, property)
    stub = HallucinatingStubClient()
    assert stub.chat is stub and stub.completions is stub
    response = stub.chat.completions.create(model="m", messages=[], temperature=0, timeout=1)
    content = response.choices[0].message.content
    assert HallucinatingStubClient.INJECTED_NUMBER == INJECTED
    assert INJECTED in content


# --- Tier 2 -------------------------------------------------------------------------------------


def test_injected_number_is_in_no_alert(vf_alerts: dict[str, tuple[Alert, pd.DataFrame]]) -> None:
    """The stub's number appears in no alert payload, title or cited row."""
    for detector, (alert, ledger) in vf_alerts.items():
        assert INJECTED not in str(alert.data), detector
        assert INJECTED not in alert.title, detector
        assert INJECTED not in _cited_rows(alert, ledger).to_string(), detector
