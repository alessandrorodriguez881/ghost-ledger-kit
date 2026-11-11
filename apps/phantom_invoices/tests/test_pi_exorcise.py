"""Tests for the Exorcise templates and card of phantom_invoices (spec exorcise, EX4).

The templates are fixed texts; no model and no network. Every figure, name and identifier is
synthetic (masked IBANs only, as the detectors write them).
"""

import logging
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from apps.phantom_invoices.action_templates import TEMPLATES, action_for
from apps.phantom_invoices.detectors import LABELS  # noqa: F401  (registers the pi.* detectors)
from apps.phantom_invoices.settings import demo_inputs, load_config, run_pipeline
from ledger_kit.actions import DISCLAIMER, EXPANDER_TITLE, build_draft
from ledger_kit.detectors import _restore_registry, _snapshot_registry
from ledger_kit.models import Alert

ROOT = Path(__file__).resolve().parents[3]
APP_PATH = str(ROOT / "apps" / "phantom_invoices" / "app.py")
TIMEOUT_SECONDS = 60
PREFIX = "pi"
MONTHS = re.compile(
    r"\b(january|february|march|april|may|june|july|august|september|october|november|december"
    r"|enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre"
    r"|diciembre)\b",
    re.IGNORECASE,
)
WITH_TEMPLATE = (
    ("pi.duplicate_invoice", "same_number"),
    ("pi.duplicate_invoice", "near_identical_number"),
    ("pi.duplicate_invoice", "same_total_close_dates"),
    ("pi.iban_change", "invoice_iban_differs_from_master"),
    ("pi.iban_change", "payment_to_non_master_iban"),
    ("pi.vat_error", "vat_amount_mismatch"),
    ("pi.vat_error", "total_mismatch"),
)
WITHOUT_TEMPLATE = (
    ("pi.iban_change", "iban_invalid"),
    ("pi.vat_error", "vat_rate_not_allowed"),
    ("pi.reconciliation", "invoice_overdue"),
    ("pi.reconciliation", "payment_without_invoice"),
    ("pi.something_else", ""),
)
NEVER_FROM_THE_INVOICE = {
    "en": "Never use a phone number or e-mail address from the invoice or from the message "
    "that announced the change",
    "es": "No use nunca un teléfono ni un correo que figure en la factura o en el mensaje que "
    "anunció el cambio",
}


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


def _alert(detector: str, variant: str, data: dict[str, Any]) -> Alert:
    return Alert(
        detector=detector,
        severity="critical",
        title="t",
        source_refs=["invoices.csv:0"],
        data={"variant": variant, **data},
    )


DUPLICATE = {
    "supplier_name": "Suministros Aurora, S.L.",
    "invoice_count": 2,
    "invoice_numbers": ["F-2026-0310", "F-2026-0310"],
    "totals": ["484.00", "484.00"],
    "total": "484.00",
    "first_issue_date": "2026-10-06",
    "last_issue_date": "2026-10-06",
    "days_apart": 0,
}
INVOICE_IBAN = {
    "supplier_name": "Suministros Aurora, S.L.",
    "invoice_number": "F-2026-0310",
    "invoice_iban_masked": "****4321",
    "master_iban_masked": "****7788",
    "last4_identical": False,
    "verification_message": "Verify this change by phone, using a contact you already have.",
}
PAYMENT_IBAN = {
    "supplier_name": "Agua y Gas Cantábrico, S.L.",
    "payment_date": "2026-05-18",
    "payment_amount": "578.91",
    "payment_iban_masked": "****7778",
    "master_iban_masked": "****1234",
    "last4_identical": False,
    "verification_message": "Verify this change by phone, using a contact you already have.",
}
VAT_AMOUNT = {
    "supplier_name": "Software Colmena, S.L.",
    "invoice_number": "F-2026-0211",
    "base_amount": "100.00",
    "vat_rate": "21",
    "expected_vat_amount": "21.00",
    "vat_amount": "12.10",
}
TOTAL = {
    "supplier_name": "Software Colmena, S.L.",
    "invoice_number": "F-2026-0212",
    "base_amount": "100.00",
    "vat_amount": "21.00",
    "surcharge_amount": "0.00",
    "withholding_amount": "0.00",
    "expected_total": "121.00",
    "total": "130.00",
}
NO_ROWS = pd.DataFrame()


def _draft(alert: Alert, language: str) -> str:
    template = action_for(alert)
    assert template is not None
    draft = build_draft(alert, NO_ROWS, template, language)
    assert draft is not None, f"{alert.detector} {language}: the draft was rejected"
    return draft


# --- templates --------------------------------------------------------------------------------


def test_seven_phantom_alert_types_have_a_template_and_the_rest_have_none() -> None:
    for detector, variant in WITH_TEMPLATE:
        assert action_for(_alert(detector, variant, {})) is TEMPLATES[(detector, variant)]
    for detector, variant in WITHOUT_TEMPLATE:
        assert action_for(_alert(detector, variant, {})) is None
    assert set(TEMPLATES) == set(WITH_TEMPLATE)


@pytest.mark.parametrize(("detector", "variant"), WITH_TEMPLATE)
def test_a_template_holds_no_digit_no_month_and_keeps_the_senders_details_in_brackets(
    detector: str, variant: str
) -> None:
    for language in ("en", "es"):
        text = TEMPLATES[(detector, variant)].texts[language]

        assert not re.search(r"\d", text), f"{detector} {variant} {language}: a digit"
        assert not MONTHS.search(text)
        assert re.search(r"\[[^\]]+\]", text)


@pytest.mark.parametrize("language", ["en", "es"])
def test_the_duplicate_draft_lists_each_invoice_and_asks_for_a_credit_note(language: str) -> None:
    draft = _draft(_alert("pi.duplicate_invoice", "same_number", DUPLICATE), language)
    same_day = {"en": "all issued on 2026-10-06", "es": "todas emitidas el 2026-10-06"}

    assert draft.count("F-2026-0310: 484,00 EUR") == 2
    assert "factura rectificativa" in draft
    assert same_day[language] in draft


def test_a_duplicate_group_over_several_days_gives_the_span_of_dates() -> None:
    data = {**DUPLICATE, "last_issue_date": "2026-10-08", "days_apart": 2}

    english = _draft(_alert("pi.duplicate_invoice", "near_identical_number", data), "en")
    spanish = _draft(_alert("pi.duplicate_invoice", "near_identical_number", data), "es")

    assert "issued between 2026-10-06 and 2026-10-08" in english
    assert "emitidas entre 2026-10-06 y 2026-10-08" in spanish


def test_lists_of_different_length_give_no_draft_and_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    alert = _alert("pi.duplicate_invoice", "same_number", {**DUPLICATE, "totals": ["484.00"]})
    template = action_for(alert)
    assert template is not None
    with caplog.at_level(logging.WARNING, logger="ledger_kit.actions"):
        assert build_draft(alert, NO_ROWS, template, "en") is None

    assert any(alert.id in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("language", ["en", "es"])
def test_the_invoice_iban_draft_is_a_hold_note_and_a_phone_script_with_masked_ibans(
    language: str,
) -> None:
    alert = _alert("pi.iban_change", "invoice_iban_differs_from_master", INVOICE_IBAN)

    draft = _draft(alert, language)

    assert "****4321" in draft and "****7788" in draft and "F-2026-0310" in draft
    assert NEVER_FROM_THE_INVOICE[language] in draft
    headings = {
        "en": ("INTERNAL HOLD NOTE", "PHONE SCRIPT"),
        "es": ("NOTA INTERNA DE RETENCIÓN", "GUION TELEFÓNICO"),
    }
    first, second = headings[language]
    assert draft.index(first) < draft.index(second)
    assert "verification_message" not in draft and "Verify this change" not in draft


@pytest.mark.parametrize("language", ["en", "es"])
def test_the_payment_iban_draft_names_the_payment_and_the_masked_accounts(language: str) -> None:
    draft = _draft(_alert("pi.iban_change", "payment_to_non_master_iban", PAYMENT_IBAN), language)

    assert "578,91 EUR" in draft and "2026-05-18" in draft
    assert "****7778" in draft and "****1234" in draft
    assert NEVER_FROM_THE_INVOICE[language] in draft


@pytest.mark.parametrize("language", ["en", "es"])
def test_the_vat_drafts_ask_for_a_corrected_invoice_with_the_figures_of_the_alert(
    language: str,
) -> None:
    amount = _draft(_alert("pi.vat_error", "vat_amount_mismatch", VAT_AMOUNT), language)
    total = _draft(_alert("pi.vat_error", "total_mismatch", TOTAL), language)

    for figure in ("12,10 EUR", "21,00 EUR", "100,00 EUR", "F-2026-0211"):
        assert figure in amount
    for figure in ("130,00 EUR", "121,00 EUR", "0,00 EUR", "F-2026-0212"):
        assert figure in total
    assert "factura rectificativa" in amount and "factura rectificativa" in total


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


def _demo_alert_ids() -> tuple[set[str], set[str]]:
    """The ids of every alert of the demo and of those that have a template."""
    config = load_config(ROOT / "apps" / "phantom_invoices" / "config.toml")
    demo = demo_inputs(config, ROOT)
    pipeline = run_pipeline(demo.invoices, demo.suppliers, demo.payments, demo.as_of)
    alerts = [alert for result in pipeline.results for alert in result.alerts]
    return {a.id for a in alerts}, {a.id for a in alerts if action_for(a) is not None}


def _demo() -> AppTest:
    at = AppTest.from_file(APP_PATH, default_timeout=TIMEOUT_SECONDS)
    at.run()
    at.button(key=f"{PREFIX}_load_demo").click().run()
    assert not at.exception
    return at


def _language_radios(at: AppTest) -> list:
    return [r for r in at.radio if (r.key or "").startswith(f"{PREFIX}_ex_lang_")]


def test_the_expander_is_on_the_cards_that_have_a_template_and_on_no_other() -> None:
    every, with_template = _demo_alert_ids()
    at = _demo()

    shown = {(r.key or "").removeprefix(f"{PREFIX}_ex_lang_") for r in _language_radios(at)}
    assert with_template and shown == with_template <= every
    labels = [e.label for e in at.expander]
    assert labels.count(EXPANDER_TITLE) == len(with_template)
    assert not any("_lg_" in (r.key or "") for r in _language_radios(at))


def test_the_iban_card_shows_a_draft_that_keeps_to_the_masked_iban() -> None:
    at = _demo()

    drafts = [t.value for t in at.text_area if (t.key or "").startswith(f"{PREFIX}_ex_text_")]
    iban_drafts = [d for d in drafts if d.startswith("INTERNAL HOLD NOTE")]
    assert iban_drafts, "the demo has a critical IBAN alert"
    assert "****" in iban_drafts[0] and NEVER_FROM_THE_INVOICE["en"] in iban_drafts[0]
    assert not re.search(r"[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,}", iban_drafts[0])


def test_switching_the_language_changes_the_draft_and_the_download(
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
