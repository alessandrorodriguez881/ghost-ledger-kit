"""Tests for the Exorcise templates and card of zombie_subscriptions (spec exorcise, EX3).

The templates are fixed texts; no model and no network. Every figure and name is synthetic.
"""

import re
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

import apps.zombie_subscriptions.detectors  # noqa: F401  (registers the zs.* detectors)
from apps.zombie_subscriptions.action_templates import TEMPLATES, action_for
from apps.zombie_subscriptions.explain_support import CPI_SENTENCE
from ledger_kit.actions import DISCLAIMER, EXPANDER_TITLE, build_draft
from ledger_kit.detectors import _restore_registry, _snapshot_registry
from ledger_kit.explainer import fill_fallback
from ledger_kit.models import Alert

APP_PATH = str(Path(__file__).resolve().parents[1] / "app.py")
TIMEOUT_SECONDS = 60
PREFIX = "zs"
MONTHS = re.compile(
    r"\b(january|february|march|april|may|june|july|august|september|october|november|december"
    r"|enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre"
    r"|diciembre)\b",
    re.IGNORECASE,
)
DETECTORS = (
    "zs.charges_after_cancellation",
    "zs.duplicate_subscription",
    "zs.price_increase",
    "zs.free_trial_to_paid",
    "zs.recurring_charge",
)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """No provider variable leaks in; the global detector registry is restored afterwards."""
    for name in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "LEDGER_KIT_LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    snapshot = _snapshot_registry()
    try:
        yield
    finally:
        _restore_registry(snapshot)


def _rows(*days: date) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": day,
                "amount": Decimal("8.99"),
                "flow": "debit",
                "currency": "EUR",
                "counterparty": "GYMPLUS",
                "source_ref": f"s.csv:{index}",
            }
            for index, day in enumerate(days)
        ]
    )


def _alert(detector: str, data: dict[str, Any], refs: int = 2) -> Alert:
    return Alert(
        detector=detector,
        severity="warning",
        title="t",
        source_refs=[f"s.csv:{index}" for index in range(refs)],
        data=data,
    )


CHARGES = _alert(
    "zs.charges_after_cancellation",
    {
        "counterparty": "GYMPLUS",
        "cancellation_date": "2026-07-31",
        "post_cancellation_count": 2,
        "total_charged_after": "17.98",
        "yearly_cost": "107.88",
    },
)
PRICE = {
    "counterparty": "STREAMFLIX",
    "old_median_amount": "9.99",
    "new_amount": "12.99",
    "extra_cost_per_year": "36.00",
    "yearly_cost": "155.88",
    "interval_type": "monthly",
}
CPI = {
    "cpi_series": "IPC290751",
    "cpi_base_year": "2025",
    "cpi_start_month": "2025-03",
    "cpi_end_month": "2026-03",
    "price_start_month": "2025-03",
    "price_end_month": "2026-03",
    "cpi_start_index": "100.0",
    "cpi_end_index": "102.5",
    "price_change_percent": "30.0",
    "cpi_change_percent": "2.5",
}


# --- templates --------------------------------------------------------------------------------


def test_the_five_zombie_detectors_have_a_template_and_any_other_has_none() -> None:
    for detector in DETECTORS:
        assert action_for(_alert(detector, {})) is TEMPLATES[detector]
    assert action_for(_alert("zs.something_else", {})) is None
    assert set(TEMPLATES) == set(DETECTORS)


@pytest.mark.parametrize("detector", DETECTORS)
def test_a_template_holds_no_digit_no_month_and_keeps_the_senders_details_in_brackets(
    detector: str,
) -> None:
    for language in ("en", "es"):
        text = TEMPLATES[detector].texts[language]

        assert not re.search(r"\d", text), f"{detector} {language}: a digit in a fixed text"
        assert not MONTHS.search(text)
        assert re.search(r"\[[^\]]+\]", text)


def test_the_refund_draft_cites_the_cancellation_and_each_charge_after_it() -> None:
    rows = _rows(date(2026, 8, 9), date(2026, 9, 8))
    template = TEMPLATES["zs.charges_after_cancellation"]

    english = build_draft(CHARGES, rows, template, "en")
    spanish = build_draft(CHARGES, rows, template, "es")

    assert english is not None and spanish is not None
    for draft in (english, spanish):
        assert "2026-07-31" in draft and "17,98 EUR" in draft
        assert "2026-08-09: 8,99 EUR" in draft and "2026-09-08: 8,99 EUR" in draft
    assert "I cancelled my subscription on 2026-07-31" in english
    assert "You have charged me 2 times since then" in english
    assert "Request to my bank" in english and "dispute the charges" in english
    assert "Cancelé mi suscripción el 2026-07-31" in spanish
    assert "me han cobrado 2 veces" in spanish and "Solicitud a mi banco" in spanish


def test_the_duplicate_draft_names_the_accounts_and_asks_to_cancel_the_duplicate() -> None:
    alert = _alert(
        "zs.duplicate_subscription",
        {
            "canonical_name": "streaming",
            "series_count": 2,
            "series_counterparties": ["STREAMFLIX INTL", "STREAMFLIXCOM"],
            "yearly_cost": "299.76",
        },
    )

    template = action_for(alert)
    assert template is not None

    draft = build_draft(alert, _rows(date(2026, 8, 9)), template, "en")

    assert draft is not None
    assert "STREAMFLIX INTL, STREAMFLIXCOM" in draft and "299,76 EUR" in draft
    assert "cancel the duplicate account" in draft


def test_the_price_increase_draft_has_the_cpi_sentence_of_the_card_only_with_cpi_keys() -> None:
    plain = _alert("zs.price_increase", PRICE)
    with_cpi = _alert("zs.price_increase", {**PRICE, **CPI})
    rows = _rows(date(2026, 8, 9), date(2026, 9, 8))

    without = build_draft(plain, rows, TEMPLATES["zs.price_increase"], "en")
    english = build_draft(with_cpi, rows, TEMPLATES["zs.price_increase"], "en")
    spanish = build_draft(with_cpi, rows, TEMPLATES["zs.price_increase"], "es")

    assert without is not None and "CPI" not in without and "IPC" not in without
    assert english is not None and fill_fallback(CPI_SENTENCE, with_cpi) in english
    assert "9,99 EUR" in english and "12,99 EUR" in english and "36,00 EUR" in english
    assert spanish is not None
    assert "IPC de España (serie INE IPC290751)" in spanish
    assert "30,0 %" in spanish and "2,5 %" in spanish
    assert "Su cobro mensual subió" in spanish


def test_the_trial_and_recurring_drafts_are_cancellation_requests() -> None:
    trial = _alert(
        "zs.free_trial_to_paid",
        {"counterparty": "CLOUDVAULT", "trial_amount": "0.00", "first_paid_amount": "9.99"},
    )
    recurring = _alert(
        "zs.recurring_charge",
        {
            "counterparty": "BOOKCLUB",
            "current_amount": "9.99",
            "yearly_cost": "119.88",
            "interval_type": "monthly",
            "charge_count": 6,
        },
    )

    first = build_draft(trial, _rows(date(2026, 8, 9)), TEMPLATES["zs.free_trial_to_paid"], "en")
    second = build_draft(recurring, _rows(date(2026, 8, 9)), TEMPLATES["zs.recurring_charge"], "es")

    assert first is not None and "0,00 EUR" in first and "9,99 EUR" in first
    assert "Please cancel my subscription" in first
    assert second is not None and "119,88 EUR" in second and "(mensual)" in second
    assert "cancelen mi suscripción" in second


# --- the card ---------------------------------------------------------------------------------


@pytest.fixture
def downloads(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Wrap st.download_button; AppTest has no typed element for it, so record every call."""
    seen: list[dict[str, Any]] = []
    original = st.download_button

    def spy(*args: Any, **kwargs: Any) -> Any:
        label, data = (args + (None, None))[:2]
        seen.append({"label": label, "data": data, **kwargs})
        return original(*args, **kwargs)

    monkeypatch.setattr(st, "download_button", spy)
    return seen


def _demo() -> AppTest:
    at = AppTest.from_file(APP_PATH, default_timeout=TIMEOUT_SECONDS)
    at.run()
    at.button(key=f"{PREFIX}_load_demo").click().run()
    assert not at.exception
    return at


def _language_radios(at: AppTest) -> list:
    return [r for r in at.radio if (r.key or "").startswith(f"{PREFIX}_ex_lang_")]


def test_every_zombie_card_has_the_collapsed_expander_before_the_provoke_panel() -> None:
    at = _demo()

    labels = [e.label for e in at.expander]
    cards = labels.count("🔦 Provoke the LLM")
    assert cards >= 5 and labels.count(EXPANDER_TITLE) == cards == len(_language_radios(at))
    first = labels.index(EXPANDER_TITLE)
    assert labels[first + 1] == "🔦 Provoke the LLM"  # the expander sits right before the panel
    assert not any("_lg_" in (r.key or "") for r in _language_radios(at))


def test_switching_the_language_of_a_card_changes_its_draft_and_download(
    downloads: list[dict[str, Any]],
) -> None:
    at = _demo()
    radio = _language_radios(at)[0]
    alert_id = (radio.key or "").removeprefix(f"{PREFIX}_ex_lang_")
    english = at.text_area(key=f"{PREFIX}_ex_text_{alert_id}_en").value
    assert english and DISCLAIMER["en"] in [c.value for c in at.caption]

    radio.set_value("Español").run()

    assert not at.exception
    spanish = at.text_area(key=f"{PREFIX}_ex_text_{alert_id}_es").value
    assert spanish and spanish != english
    assert DISCLAIMER["es"] in [c.value for c in at.caption]
    last = [c for c in downloads if c["key"] == f"{PREFIX}_ex_dl_{alert_id}_es"][-1]
    assert last["file_name"].endswith(f"-es-{alert_id[:8]}.txt") and last["data"] == spanish
    assert last["mime"] == "text/plain"


def test_the_draft_of_the_gymplus_card_lists_each_charge_after_the_cancellation() -> None:
    at = _demo()

    drafts = [
        t.value
        for t in at.text_area
        if (t.key or "").startswith(f"{PREFIX}_ex_text_") and "GYMPLUS" in t.value
    ]

    [draft] = [d for d in drafts if d.startswith("Subject: Refund request")]
    assert "I cancelled my subscription on 2026-07-31" in draft
    assert "2026-08-09: 8,99 EUR" in draft


# --- duplicate draft: each distinct account name once -------------------------------------------

DRAFT_WORD_LIMIT = 150


def _demo_duplicate_draft(canonical: str, language: str) -> tuple[Alert, str]:
    """Run the zs detectors on the demo and return the duplicate alert and its draft."""
    from apps.zombie_subscriptions import settings as zs_settings
    from apps.zombie_subscriptions.detectors.utils import (
        normalise_alias_map,
        normalise_date_map,
    )

    root = Path(__file__).resolve().parents[3]
    config = zs_settings.load_config(root / "apps" / "zombie_subscriptions" / "config.toml")
    demo = zs_settings.demo_inputs(config, root, "csv")
    pipeline = zs_settings.run_pipeline(
        demo.statement_name,
        demo.statement_bytes,
        aliases=normalise_alias_map(demo.aliases),
        cancellation_dates=normalise_date_map(demo.cancellation_dates),
        cpi=zs_settings.load_cpi(config, root),
    )
    ledger = pipeline.debit_ledger
    [alert] = [
        a
        for a in pipeline.alerts
        if a.detector == "zs.duplicate_subscription" and a.data["canonical_name"] == canonical
    ]
    rows = ledger[ledger["source_ref"].isin(alert.source_refs)]
    draft = build_draft(alert, rows, TEMPLATES[alert.detector], language)
    assert draft is not None  # the number guard passed
    assert len(draft.split()) < DRAFT_WORD_LIMIT
    return alert, draft


def test_the_musicbox_duplicate_draft_lists_no_repeated_name_in_both_languages() -> None:
    alert, english = _demo_duplicate_draft("MUSICBOX", "en")
    _, spanish = _demo_duplicate_draft("MUSICBOX", "es")

    assert len(set(alert.data["series_counterparties"])) == 1  # the names are all the same
    assert f"I have {alert.data['series_count']} separate accounts for MUSICBOX. " in english
    assert f"Tengo {alert.data['series_count']} cuentas distintas de MUSICBOX. " in spanish
    assert english.count("MUSICBOX") == 1 and spanish.count("MUSICBOX") == 1


def test_the_streaming_duplicate_draft_still_lists_both_different_names() -> None:
    alert, english = _demo_duplicate_draft("STREAMING", "en")
    _, spanish = _demo_duplicate_draft("STREAMING", "es")

    assert set(alert.data["series_counterparties"]) == {"STREAMFLIX INTL", "STREAMFLIXCOM"}
    for draft in (english, spanish):
        assert draft.count("STREAMFLIX INTL") == 1 and draft.count("STREAMFLIXCOM") == 1
    assert "accounts for STREAMING: " in english
    assert "cuentas distintas de STREAMING: " in spanish
