"""Tests for the Exorcise templates and card of vampire_fees (spec exorcise, EX5).

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

import apps.vampire_fees.detectors  # noqa: F401  (registers the vf.* detectors)
from apps.vampire_fees.action_templates import BANK_PLACEHOLDER, TEMPLATES, action_for
from apps.vampire_fees.settings import demo_inputs, load_config, load_vocabulary, run_pipeline
from ledger_kit.actions import DISCLAIMER, EXPANDER_TITLE, build_draft
from ledger_kit.detectors import _restore_registry, _snapshot_registry
from ledger_kit.models import Alert
from ledger_kit.utils.money import format_amount

ROOT = Path(__file__).resolve().parents[3]
APP_PATH = str(ROOT / "apps" / "vampire_fees" / "app.py")
TIMEOUT_SECONDS = 60
PREFIX = "vf"
DETECTORS = ("vf.recurring_fee", "vf.fee_increase", "vf.overdraft_cost")
MONTHS = re.compile(
    r"\b(january|february|march|april|may|june|july|august|september|october|november|december"
    r"|enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre"
    r"|diciembre)\b",
    re.IGNORECASE,
)
# A deadline or the number of a legal article would be an invented duty (REQ-EX-20).
DEADLINE_OR_ARTICLE = re.compile(
    r"\b(days?|weeks?|hours?|deadline|article|section|law"
    r"|días|semanas|horas|plazo|artículo|ley)\b",
    re.IGNORECASE,
)
ADDRESSEE = {
    "en": "To: Customer Service Department (Servicio de Atención al Cliente), BANCO FICTICIO",
    "es": "A la atención de: Servicio de Atención al Cliente, BANCO FICTICIO",
}
CLOSING = {
    "en": "I can go to the Banco de España complaints service.",
    "es": "puedo acudir al Servicio de Reclamaciones del Banco de España.",
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


def _rows(*specs: tuple[date, str]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": day,
                "amount": Decimal(amount),
                "flow": "debit",
                "currency": "EUR",
                "counterparty": "BANCO FICTICIO",
                "source_ref": f"s.csv:{index}",
            }
            for index, (day, amount) in enumerate(specs)
        ]
    )


def _alert(detector: str, data: dict[str, Any], refs: int) -> Alert:
    return Alert(
        detector=detector,
        severity="warning",
        title="t",
        source_refs=[f"s.csv:{index}" for index in range(refs)],
        data=data,
    )


RECURRING = _alert(
    "vf.recurring_fee",
    {
        "counterparty": "BANCO FICTICIO",
        "description": "Comisión mantenimiento cuenta",
        "interval_type": "monthly",
        "charge_count": 3,
        "current_amount": "5.00",
        "yearly_cost": "60.00",
        "first_charge_date": "2025-01-05",
        "last_charge_date": "2025-03-05",
    },
    3,
)
INCREASE = _alert(
    "vf.fee_increase",
    {
        "counterparty": "BANCO FICTICIO",
        "description": "Comisión mantenimiento cuenta",
        "interval_type": "monthly",
        "old_amount": "5.00",
        "new_amount": "6.50",
        "increase_percent": "30.0",
        "increase_date": "2025-04-05",
        "old_charge_date": "2025-03-05",
        "extra_cost_per_year": "18.00",
        "yearly_cost": "78.00",
    },
    2,
)
OVERDRAFT = _alert(
    "vf.overdraft_cost",
    {
        "interest_count": 2,
        "interest_total": "7.50",
        "fee_count": 1,
        "fee_total": "30.00",
        "total": "37.50",
        "first_charge_date": "2025-02-14",
        "last_charge_date": "2025-04-09",
    },
    3,
)
RECURRING_ROWS = _rows(
    (date(2025, 3, 5), "5.00"), (date(2025, 1, 5), "5.00"), (date(2025, 2, 5), "5.00")
)
INCREASE_ROWS = _rows((date(2025, 3, 5), "5.00"), (date(2025, 4, 5), "6.50"))
OVERDRAFT_ROWS = _rows(
    (date(2025, 2, 14), "4.00"), (date(2025, 3, 14), "3.50"), (date(2025, 4, 9), "30.00")
)


def _draft(alert: Alert, rows: pd.DataFrame, language: str) -> str:
    template = action_for(alert)
    assert template is not None
    draft = build_draft(alert, rows, template, language)
    assert draft is not None, f"{alert.detector} {language}: the draft was rejected"
    return draft


# --- templates --------------------------------------------------------------------------------


def test_the_three_fee_detectors_have_a_template_and_the_summary_has_none() -> None:
    for detector in DETECTORS:
        assert action_for(_alert(detector, {}, 1)) is TEMPLATES[detector]
    assert action_for(_alert("vf.fee_summary", {}, 1)) is None
    assert set(TEMPLATES) == set(DETECTORS)


@pytest.mark.parametrize("detector", DETECTORS)
def test_a_template_holds_no_digit_no_month_no_deadline_and_no_article(detector: str) -> None:
    for language in ("en", "es"):
        text = TEMPLATES[detector].texts[language]

        assert not re.search(r"\d", text), f"{detector} {language}: a digit in a fixed text"
        assert not MONTHS.search(text)
        assert not DEADLINE_OR_ARTICLE.search(text)
        assert re.search(r"\[[^\]]+\]", text)


@pytest.mark.parametrize("language", ["en", "es"])
@pytest.mark.parametrize(
    ("alert", "rows"),
    [(RECURRING, RECURRING_ROWS), (INCREASE, INCREASE_ROWS), (OVERDRAFT, OVERDRAFT_ROWS)],
    ids=DETECTORS,
)
def test_every_complaint_is_addressed_lists_each_fee_row_and_ends_with_the_banco_de_espana_line(
    alert: Alert, rows: pd.DataFrame, language: str
) -> None:
    draft = _draft(alert, rows, language)

    assert ADDRESSEE[language] in draft
    for row in rows.itertuples():
        assert f"{row.date.isoformat()}: {format_amount(row.amount)}" in draft
    last_line = draft.splitlines()[-1]
    assert CLOSING[language] in last_line
    assert not DEADLINE_OR_ARTICLE.search(draft)


def test_the_recurring_complaint_cites_each_row_in_date_order_and_the_yearly_cost() -> None:
    draft = _draft(RECURRING, RECURRING_ROWS, "en")

    assert draft.index("2025-01-05: 5,00 EUR") < draft.index("2025-02-05: 5,00 EUR")
    assert draft.index("2025-02-05: 5,00 EUR") < draft.index("2025-03-05: 5,00 EUR")
    assert "charged 3 times between 2025-01-05 and 2025-03-05" in draft
    assert "about 60,00 EUR per year" in draft


def test_the_increase_complaint_cites_the_old_and_the_new_fee() -> None:
    english = _draft(INCREASE, INCREASE_ROWS, "en")
    spanish = _draft(INCREASE, INCREASE_ROWS, "es")

    assert "rose from 5,00 EUR to 6,50 EUR on 2025-04-05, an increase of 30,0 %" in english
    assert "subió de 5,00 EUR a 6,50 EUR el 2025-04-05, un aumento del 30,0 %" in spanish
    assert "adding 18,00 EUR per year" in english


def test_the_overdraft_complaint_takes_the_bank_from_the_cited_rows() -> None:
    draft = _draft(OVERDRAFT, OVERDRAFT_ROWS, "en")

    assert "BANCO FICTICIO" in draft
    assert "Overdraft interest was charged 2 times (7,50 EUR)" in draft
    assert "overdraft fees 1 time (30,00 EUR), in total 37,50 EUR" in draft


def test_without_a_named_bank_the_complaint_keeps_a_placeholder() -> None:
    nameless = _rows((date(2025, 2, 14), "4.00")).assign(counterparty="")

    draft = _draft(OVERDRAFT, nameless, "en")

    assert f"(Servicio de Atención al Cliente), {BANK_PLACEHOLDER}" in draft


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
    config = load_config(ROOT / "apps" / "vampire_fees" / "config.toml")
    demo = demo_inputs(config, ROOT)
    pipeline = run_pipeline(
        demo.statement_name, demo.statement_bytes, vocabulary=load_vocabulary(config)
    )
    alerts = pipeline.alerts
    return {a.id for a in alerts}, {a.id for a in alerts if action_for(a) is not None}


def _demo() -> AppTest:
    at = AppTest.from_file(APP_PATH, default_timeout=TIMEOUT_SECONDS)
    at.run()
    at.button(key=f"{PREFIX}_load_demo").click().run()
    assert not at.exception
    return at


def _language_radios(at: AppTest) -> list:
    return [r for r in at.radio if (r.key or "").startswith(f"{PREFIX}_ex_lang_")]


def test_the_expander_is_on_the_fee_cards_and_not_on_the_summary_card() -> None:
    every, with_template = _demo_alert_ids()
    at = _demo()

    shown = {(r.key or "").removeprefix(f"{PREFIX}_ex_lang_") for r in _language_radios(at)}
    assert with_template and shown == with_template <= every
    assert with_template != every  # the demo has a fee summary, which has no template
    assert [e.label for e in at.expander].count(EXPANDER_TITLE) == len(with_template)
    assert not any("_lg_" in (r.key or "") for r in _language_radios(at))


def test_switching_the_language_changes_the_draft_and_the_download(
    downloads: list[dict[str, Any]],
) -> None:
    at = _demo()
    radio = _language_radios(at)[0]
    alert_id = (radio.key or "").removeprefix(f"{PREFIX}_ex_lang_")
    english = at.text_area(key=f"{PREFIX}_ex_text_{alert_id}_en").value
    assert "Customer Service Department (Servicio de Atención al Cliente)" in english
    assert DISCLAIMER["en"] in [c.value for c in at.caption]

    radio.set_value("Español").run()

    assert not at.exception
    spanish = at.text_area(key=f"{PREFIX}_ex_text_{alert_id}_es").value
    assert "A la atención de: Servicio de Atención al Cliente" in spanish
    assert DISCLAIMER["es"] in [c.value for c in at.caption]
    last = [c for c in downloads if c["key"] == f"{PREFIX}_ex_dl_{alert_id}_es"][-1]
    assert last["file_name"].endswith(f"-es-{alert_id[:8]}.txt") and last["data"] == spanish
