"""CPI template, card helpers and the number guard with CPI figures (public-cpi CPI7, CPI8).

Every CPI figure here is **synthetic** (made-up index values, not INE figures). No network: the
LLM is a mock client that returns a fixed text.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Self

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from apps.zombie_subscriptions.explain_support import (
    CPI_SENTENCE,
    CPI_SENTENCE_LAG,
    PRICE_INCREASE_WITH_CPI_LAG_TEMPLATE,
    PRICE_INCREASE_WITH_CPI_TEMPLATE,
    TEMPLATES,
    cpi_uses_lag,
    has_cpi_context,
    template_for,
)
from apps.zombie_subscriptions.settings import (
    attribution_lines,
    cpi_sentence_to_add,
    cpi_source_line,
)
from ledger_kit.explainer import Explanation, explain_with_meta, fill_fallback
from ledger_kit.models import Alert
from ledger_kit.public_data import CpiSeries

_NO_INVENTION = (
    "You must not invent any number, date, name, or amount. "
    "Every figure you mention must appear verbatim either in the source rows "
    "provided or in the structured fields of the alert (such as yearly_cost). "
    "Do not derive, round, or estimate any figure not explicitly present in "
    "those inputs."
)
REFS = [f"f.csv:{i}" for i in range(6)]
BASE_DATA = {
    "counterparty": "CLOUDVAULT",
    "old_median_amount": "100.00",
    "new_amount": "118.00",
    "extra_cost_per_year": "216.00",
    "yearly_cost": "1416.00",
    "interval_type": "monthly",
}
CPI_DATA = {
    "price_start_month": "2026-01",
    "price_end_month": "2026-04",
    "price_change_percent": "18.0",
    "cpi_series": "IPC290751",
    "cpi_base_year": "2025",
    "cpi_start_month": "2026-01",
    "cpi_end_month": "2026-04",
    "cpi_start_index": "100.000",
    "cpi_end_index": "102.000",
    "cpi_change_percent": "2.0",
}
# A synthetic lag case: the price step is in 2026-10, the CPI stops at 2026-09.
LAG_DATA = {
    "counterparty": "STREAMFLEX INTL",
    "old_median_amount": "12.99",
    "new_amount": "15.99",
    "extra_cost_per_year": "36.00",
    "yearly_cost": "191.88",
    "interval_type": "monthly",
    "price_start_month": "2026-05",
    "price_end_month": "2026-10",
    "price_change_percent": "23.1",
    "cpi_series": "IPC290751",
    "cpi_base_year": "2025",
    "cpi_start_month": "2026-05",
    "cpi_end_month": "2026-09",
    "cpi_start_index": "100.000",
    "cpi_end_index": "101.000",
    "cpi_change_percent": "1.0",
}


def _alert(data: dict, detector: str = "zs.price_increase") -> Alert:
    return Alert(
        detector=detector,
        severity="warning",
        title=f"Price increase detected: {data['counterparty']}",
        source_refs=REFS,
        data=data,
    )


CPI_ALERT = _alert({**BASE_DATA, **CPI_DATA})
PLAIN_ALERT = _alert(dict(BASE_DATA))
LAG_ALERT = _alert(LAG_DATA)


def _rows() -> pd.DataFrame:
    days = [date(2026, 1, 5), date(2026, 2, 4), date(2026, 3, 6)]
    days += [date(2026, 4, 5), date(2026, 5, 5), date(2026, 6, 4)]
    amounts = ["100.00"] * 3 + ["118.00"] * 3
    return pd.DataFrame(
        [
            {
                "date": day,
                "amount": Decimal(amount),
                "flow": "debit",
                "currency": "EUR",
                "counterparty": "CLOUDVAULT",
                "source_ref": ref,
            }
            for day, amount, ref in zip(days, amounts, REFS, strict=True)
        ]
    )


@dataclass
class _Message:
    content: str


@dataclass
class _Choice:
    message: _Message


@dataclass
class _Response:
    choices: list[_Choice]


class MockLLMClient:
    """OpenAI-shaped mock that returns one fixed text and records each call's kwargs."""

    def __init__(self, text: str) -> None:
        self._text = text
        self.calls: list[dict] = []

    @property
    def chat(self) -> Self:
        return self

    @property
    def completions(self) -> Self:
        return self

    def create(self, **kwargs: object) -> _Response:
        self.calls.append(kwargs)
        return _Response([_Choice(_Message(self._text))])


def _explain(text: str, alert: Alert = CPI_ALERT) -> tuple[Explanation, MockLLMClient]:
    client = MockLLMClient(text)
    template = template_for(alert)
    result = explain_with_meta(alert, _rows(), fallback_template=template, client=client)
    return result, client


FILLED_CPI_TEXT = (
    "The CLOUDVAULT charge increased from 100,00 EUR to 118,00 EUR, adding 216,00 EUR to your "
    "yearly cost. The price rose 18,0 % while the Spanish CPI (INE series IPC290751) changed by "
    "2,0 % from 2026-01 to 2026-04. "
    "Source: f.csv:0, f.csv:1, f.csv:2, f.csv:3, f.csv:4, f.csv:5."
)
LLM_OK = (
    "The price rose 18,0 % while the Spanish CPI changed by {cpi} from 2026-01 to 2026-04 "
    "(index 100.000 to {end}). Source: f.csv:0."
)


# --- Guard with CPI figures (REQ-CPI-14) -------------------------------------------------------


def test_guard_accepts_the_cpi_figures_of_the_alert() -> None:
    result, _client = _explain(LLM_OK.format(cpi="2,0 %", end="102.000"))
    assert result.source == "llm"
    assert result.rejected_numbers == ()


def test_guard_rejects_an_invented_cpi_change() -> None:
    result, _client = _explain(LLM_OK.format(cpi="2,5 %", end="102.000"))
    assert result.source == "fallback"
    assert result.rejected_numbers == ("2,5",)
    assert result.text == FILLED_CPI_TEXT


def test_guard_rejects_an_invented_index() -> None:
    result, _client = _explain(LLM_OK.format(cpi="2,0 %", end="103.000"))
    assert result.source == "fallback"
    assert result.rejected_numbers == ("103.000",)
    assert "changed by 2,0 %" in result.text


def test_guard_accepts_an_equal_value_and_rejects_a_finer_one() -> None:
    accepted, _ = _explain(LLM_OK.format(cpi="2 %", end="102.000"))
    rejected, _ = _explain(LLM_OK.format(cpi="2,04 %", end="102.000"))
    assert accepted.source == "llm"
    assert rejected.source == "fallback"
    assert rejected.rejected_numbers == ("2,04",)


def test_prompt_unchanged_and_alert_json_has_the_cpi_fields() -> None:
    _result, client = _explain(LLM_OK.format(cpi="2,0 %", end="102.000"))
    system, user = client.calls[0]["messages"]
    assert system["role"] == "system"
    assert _NO_INVENTION in system["content"]
    assert "cpi_change_percent" in user["content"]
    assert "IPC290751" in user["content"]
    assert client.calls[0]["temperature"] == 0


_ALERT_NUMBERS = ["18.0", "2.0", "100.000", "102.000", "100.00", "118.00", "216.00", "1416.00"]


@settings(max_examples=200, deadline=None)
@given(
    picked=st.lists(st.sampled_from(_ALERT_NUMBERS), min_size=1, max_size=6),
    extra=st.decimals(min_value=Decimal("300.01"), max_value=Decimal("999.99"), places=2),
)
def test_guard_accepts_only_numbers_of_the_alert(picked: list[str], extra: Decimal) -> None:
    text = "Figures: " + " and ".join(picked) + ". Source: f.csv:0."
    accepted, _ = _explain(text)
    assert accepted.source == "llm"
    rejected, _ = _explain(text + f" Also {extra} EUR.")
    assert rejected.source == "fallback"
    assert rejected.rejected_numbers == (str(extra),)


# --- Templates (REQ-CPI-17) --------------------------------------------------------------------


def test_template_for_without_cpi_keys_is_todays_template() -> None:
    assert template_for(PLAIN_ALERT) is TEMPLATES["zs.price_increase"]
    filled = fill_fallback(template_for(PLAIN_ALERT), PLAIN_ALERT)
    assert "CPI" not in filled
    assert filled == fill_fallback(TEMPLATES["zs.price_increase"], PLAIN_ALERT)


def test_template_for_with_cpi_keys() -> None:
    assert template_for(CPI_ALERT) == PRICE_INCREASE_WITH_CPI_TEMPLATE
    assert fill_fallback(template_for(CPI_ALERT), CPI_ALERT) == FILLED_CPI_TEXT


def test_template_for_with_a_lag() -> None:
    assert cpi_uses_lag(LAG_ALERT.data) is True
    assert cpi_uses_lag(CPI_ALERT.data) is False
    assert template_for(LAG_ALERT) == PRICE_INCREASE_WITH_CPI_LAG_TEMPLATE
    assert fill_fallback(template_for(LAG_ALERT), LAG_ALERT) == (
        "The STREAMFLEX INTL charge increased from 12,99 EUR to 15,99 EUR, adding 36,00 EUR to "
        "your yearly cost. The price rose 23,1 % from 2026-05 to 2026-10, while the Spanish CPI "
        "(INE series IPC290751) changed by 1,0 % from 2026-05 to 2026-09, using the latest "
        "published CPI month available. Source: f.csv:0, f.csv:1, f.csv:2, f.csv:3, f.csv:4, "
        "f.csv:5."
    )


def test_template_for_other_detectors_ignores_cpi_keys() -> None:
    alert = _alert({**BASE_DATA, **CPI_DATA}, detector="zs.recurring_charge")
    assert template_for(alert) is TEMPLATES["zs.recurring_charge"]


def test_cpi_variants_keep_the_base_template_head() -> None:
    base = TEMPLATES["zs.price_increase"]
    head = base.removesuffix("Source: {source_refs}.")
    assert PRICE_INCREASE_WITH_CPI_TEMPLATE.startswith(head)
    assert PRICE_INCREASE_WITH_CPI_LAG_TEMPLATE.startswith(head)


@pytest.mark.parametrize("sentence", [CPI_SENTENCE, CPI_SENTENCE_LAG])
def test_cpi_sentences_draw_no_conclusion(sentence: str) -> None:
    lowered = sentence.lower()
    for word in ("above", "below", "exceeds", "should", "beat", "cancel"):
        assert word not in lowered


def test_has_cpi_context() -> None:
    assert has_cpi_context(CPI_ALERT.data) is True
    assert has_cpi_context(PLAIN_ALERT.data) is False


# --- Card helpers (REQ-CPI-18) -----------------------------------------------------------------


def test_cpi_source_line() -> None:
    assert cpi_source_line(CPI_ALERT) == (
        "CPI source: INE series IPC290751 (base 2025 = 100), 2026-01 = 100,000, 2026-04 = 102,000"
    )
    assert cpi_source_line(PLAIN_ALERT) is None


def test_cpi_source_line_with_a_lag_names_the_price_months() -> None:
    assert cpi_source_line(LAG_ALERT) == (
        "CPI source: INE series IPC290751 (base 2025 = 100), 2026-05 = 100,000, "
        "2026-09 = 101,000; latest published month used; price months 2026-05 and 2026-10"
    )


def test_sentence_not_added_to_the_fallback_explanation() -> None:
    fallback = Explanation(fill_fallback(template_for(CPI_ALERT), CPI_ALERT), "fallback", ())
    assert cpi_sentence_to_add(CPI_ALERT, fallback) is None


def test_sentence_added_to_an_llm_text_without_it() -> None:
    llm = Explanation("The CLOUDVAULT price went up. Source: f.csv:0.", "llm", ())
    added = cpi_sentence_to_add(CPI_ALERT, llm)
    assert added == (
        "The price rose 18,0 % while the Spanish CPI (INE series IPC290751) changed by 2,0 % "
        "from 2026-01 to 2026-04."
    )
    assert (llm.text + "\n" + added).count("changed by") == 1


def test_sentence_not_added_when_the_llm_text_has_it() -> None:
    sentence = fill_fallback(CPI_SENTENCE, CPI_ALERT)
    llm = Explanation(f"Summary. {sentence} Source: f.csv:0.", "llm", ())
    assert cpi_sentence_to_add(CPI_ALERT, llm) is None


def test_sentence_not_added_without_cpi_keys() -> None:
    llm = Explanation("Text. Source: f.csv:0.", "llm", ())
    assert cpi_sentence_to_add(PLAIN_ALERT, llm) is None


def test_lag_sentence_added_for_a_lag_alert() -> None:
    llm = Explanation("Text. Source: f.csv:0.", "llm", ())
    added = cpi_sentence_to_add(LAG_ALERT, llm)
    assert added is not None
    assert "using the latest published CPI month available" in added
    assert "from 2026-05 to 2026-10" in added


@settings(max_examples=200, deadline=None)
@given(prefix=st.text(max_size=40), with_sentence=st.booleans())
def test_card_never_shows_the_sentence_twice(prefix: str, with_sentence: bool) -> None:
    sentence = fill_fallback(CPI_SENTENCE, CPI_ALERT)
    text = prefix + (sentence if with_sentence else "")
    added = cpi_sentence_to_add(CPI_ALERT, Explanation(text, "llm", ()))
    shown = text + ("" if added is None else "\n" + added)
    assert shown.count(sentence) == 1


# --- Attribution (REQ-CPI-19) ------------------------------------------------------------------


def test_attribution_lines() -> None:
    cpi = CpiSeries.from_mapping({"2026-01": "100.000"}, retrieved_on="2026-11-09")
    assert attribution_lines(cpi) == [
        "Elaboración propia con datos extraídos del sitio web del INE: www.ine.es",
        "Licence: CC BY 4.0 · INE series IPC290751 (Nacional. Índice general. Índice) · "
        "retrieved 2026-11-09",
        "The INE does not take part in, sponsor or support this reuse.",
    ]


def test_attribution_escapes_markdown_in_the_series_name() -> None:
    cpi = CpiSeries.from_mapping({"2026-01": "100.000"}, series_name="Índice *x* [y]_z")
    licence_line = attribution_lines(cpi)[1]
    assert "Índice \\*x\\* \\[y\\]\\_z" in licence_line
