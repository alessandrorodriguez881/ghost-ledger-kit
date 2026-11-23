"""Config, matching, template, guard and card helpers of the fee comparison.

Public-fees PF3 (REQ-PF-09, REQ-PF-10) and PF5 (REQ-PF-16, REQ-PF-18, REQ-PF-19 helpers).
Every text and every snapshot is synthetic; counterparties are fictional (Finance Rule 5). Nothing
reads the committed snapshot.
"""

import copy
import re
import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import apps.vampire_fees.detectors  # noqa: F401  (registers the vf.* detectors)
from apps.vampire_fees.detectors.fee_summary import detect_fee_summary
from apps.vampire_fees.detectors.recurring_fee import detect_recurring_fees
from apps.vampire_fees.detectors.utils import (
    PeerService,
    build_peer_services,
    classify_fee,
    contains_phrase,
    fold_tokens,
    match_peer_service,
)
from apps.vampire_fees.explain_support import (
    FEE_SUMMARY_NO_YEARLY_TEMPLATE,
    PEER_SENTENCE,
    RECURRING_FEE_WITH_PEERS_TEMPLATE,
    TEMPLATES,
    template_for,
)
from apps.vampire_fees.settings import (
    markdown_safe,
    peer_attribution_lines,
    peer_sentence_to_add,
    peer_source_line,
)
from apps.vampire_fees.tests.vf_builders import (
    BANK,
    default_vocabulary,
    demo_maintenance_ledger,
    fee_row,
    peer_context,
    peer_fee,
    s12_snapshot_dict,
    snapshot_dict_of,
    summary_ledger,
)
from ledger_kit.detectors import registered_names
from ledger_kit.explainer import Explanation, explain_with_meta, fill_fallback
from ledger_kit.models import Alert
from ledger_kit.public_data import ACCOUNT_TYPES, FeeSnapshot
from ledger_kit.ui.signatures import chip_source_template

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.toml"
MAINTENANCE_CONCEPT = "Comisión ANUAL total (euros)"
CARD_CONCEPT = "Comisión mantenimiento. ANUAL total (euros)"

# The [peer_fees] table of REQ-PF-09, written here so the unit tests do not read config.toml.
PEER_TABLE: dict[str, Any] = {
    "snapshot_path": "data/public/bde_payment_account_fees.json",
    "default_account_type": "CNO",
    "maintenance": {
        "service": "101",
        "concept": MAINTENANCE_CONCEPT,
        "label": "account maintenance",
        "words": [
            "mantenimiento cuenta",
            "mantenimiento de cuenta",
            "mantenimiento de la cuenta",
            "account maintenance",
        ],
        "exclude": ["tarjeta", "card", "descubierto", "overdraft"],
    },
    "debit_card": {
        "service": "401",
        "concept": CARD_CONCEPT,
        "label": "debit card maintenance",
        "words": ["tarjeta debito", "tarjeta de debito", "debit card"],
        "exclude": ["credito", "credit"],
    },
}
SERVICES = build_peer_services(PEER_TABLE)


def _table(**maintenance: Any) -> dict[str, Any]:
    """Return PEER_TABLE with keys of the maintenance sub-table replaced (None removes one)."""
    table = copy.deepcopy(PEER_TABLE)
    for key, value in maintenance.items():
        if value is None:
            table["maintenance"].pop(key, None)
        else:
            table["maintenance"][key] = value
    return table


def _matched(description: str, counterparty: str = BANK) -> str | None:
    """Return the service code matched for a fee row classified by the default vocabulary."""
    row = fee_row(0, date(2026, 10, 5), "6.50", counterparty=counterparty, description=description)
    fee = classify_fee(row, default_vocabulary())
    assert fee is not None, description
    service = match_peer_service(fee, SERVICES)
    return None if service is None else service.service_code


# --- build_peer_services (REQ-PF-09) -----------------------------------------------------------


def test_build_peer_services_returns_the_two_services() -> None:
    maintenance, card = SERVICES
    assert isinstance(maintenance, PeerService)
    assert (maintenance.key, maintenance.service_code, maintenance.concept) == (
        "maintenance",
        "101",
        MAINTENANCE_CONCEPT,
    )
    assert maintenance.label == "account maintenance"
    assert ("mantenimiento", "cuenta") in maintenance.words
    assert ("mantenimiento", "de", "la", "cuenta") in maintenance.words
    assert maintenance.exclude == (("tarjeta",), ("card",), ("descubierto",), ("overdraft",))
    assert (card.key, card.service_code, card.concept) == ("debit_card", "401", CARD_CONCEPT)
    assert ("tarjeta", "debito") in card.words
    assert card.exclude == (("credito",), ("credit",))


def test_phrases_are_folded() -> None:
    table = _table(words=["Mantenimiento de la CUENTA", "Débito Tarjeta"])
    words = build_peer_services(table)[0].words
    assert words == (("mantenimiento", "de", "la", "cuenta"), ("debito", "tarjeta"))


def test_unknown_service_999() -> None:
    with pytest.raises(ValueError) as info:
        build_peer_services(_table(service="999"))
    assert str(info.value) == (
        "peer service 'maintenance': 999 is not a Banco de España service code"
    )


@pytest.mark.parametrize("service", [101, None, ""])
def test_service_that_is_not_a_code_string(service: Any) -> None:
    with pytest.raises(ValueError, match="^peer service 'maintenance': .* service code$"):
        build_peer_services(_table(service=service))


def test_concept_that_is_not_an_annual_total() -> None:
    with pytest.raises(ValueError) as info:
        build_peer_services(_table(concept="Periodicidad"))
    assert str(info.value) == "peer service 'maintenance': concept must be an annual total"


def test_concept_with_the_words_apart_is_not_an_annual_total() -> None:
    with pytest.raises(ValueError, match="concept must be an annual total"):
        build_peer_services(_table(concept="Total de la comisión anual"))


@pytest.mark.parametrize("name", ["concept", "label"])
@pytest.mark.parametrize("value", [None, "", "   ", 7])
def test_missing_or_empty_text(name: str, value: Any) -> None:
    with pytest.raises(ValueError) as info:
        build_peer_services(_table(**{name: value}))
    assert str(info.value) == f"peer service 'maintenance': {name} is missing or empty"


@pytest.mark.parametrize("words", [None, [], "mantenimiento cuenta"])
def test_missing_or_empty_words(words: Any) -> None:
    with pytest.raises(ValueError) as info:
        build_peer_services(_table(words=words))
    assert str(info.value) == (
        "peer service 'maintenance': words must be a non-empty list of strings"
    )


@pytest.mark.parametrize("phrase", ["--", "", "123", " · "])
def test_phrase_with_no_letter(phrase: str) -> None:
    with pytest.raises(ValueError) as info:
        build_peer_services(_table(words=["mantenimiento cuenta", phrase]))
    assert str(info.value) == (
        f"peer service 'maintenance': words holds a phrase with no letter: {phrase!r}"
    )


def test_exclude_phrase_with_no_letter() -> None:
    with pytest.raises(ValueError, match="exclude holds a phrase with no letter"):
        build_peer_services(_table(exclude=["tarjeta", "--"]))


def test_non_string_phrase() -> None:
    with pytest.raises(ValueError, match="words holds a non-string: 5"):
        build_peer_services(_table(words=["mantenimiento cuenta", 5]))


def test_exclude_may_be_left_out() -> None:
    assert build_peer_services(_table(exclude=None))[0].exclude == ()


def test_a_table_with_no_sub_table_gives_no_service() -> None:
    table = {"snapshot_path": "x.json", "default_account_type": "CNO"}
    assert build_peer_services(table) == ()
    assert build_peer_services({}) == ()


@pytest.mark.parametrize("default", ["XXX", "cno", 1])
def test_default_account_type_that_is_not_a_code(default: Any) -> None:
    table = {**PEER_TABLE, "default_account_type": default}
    with pytest.raises(ValueError) as info:
        build_peer_services(table)
    assert str(info.value) == (
        f"peer_fees: default_account_type {default!r} is not a Banco de España account type"
    )


def test_a_table_that_is_not_a_mapping() -> None:
    with pytest.raises(ValueError, match="peer_fees must be a table"):
        build_peer_services(["maintenance"])  # type: ignore[arg-type]


def test_the_committed_config_gives_maintenance_and_debit_card() -> None:
    config = tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    table = config["peer_fees"]
    assert table["snapshot_path"] == "data/public/bde_payment_account_fees.json"
    assert table["default_account_type"] in ACCOUNT_TYPES
    assert table["default_account_type"] == "CNO"
    services = build_peer_services(table)
    assert [s.key for s in services] == ["maintenance", "debit_card"]
    assert services == SERVICES


# --- match_peer_service (REQ-PF-10) ------------------------------------------------------------


@pytest.mark.parametrize(
    ("description", "counterparty", "expected"),
    [
        ("Comisión mantenimiento cuenta", BANK, "101"),
        ("Comisión anual tarjeta débito", BANK, "401"),
        ("Comisión mantenimiento tarjeta débito", BANK, "401"),
        ("Cuota de mantenimiento de la cuenta y tarjeta de débito", BANK, None),
        ("Comisión tarjeta de crédito", BANK, None),
        ("Debit card credit card fee", BANK, None),
        ("Comisión custodia valores", BANK, None),
        ("Comisión por descubierto", BANK, None),
        ("Comisión transferencia inmediata", BANK, None),
        ("Comisión mantenimiento cuenta", "Tarjeta Azul S.L.", None),
    ],
)
def test_the_matching_table(description: str, counterparty: str, expected: str | None) -> None:
    assert _matched(description, counterparty) == expected


def test_the_matched_service_carries_its_concept() -> None:
    maintenance = match_peer_service(peer_fee("Comisión mantenimiento cuenta"), SERVICES)
    card = match_peer_service(peer_fee("Comisión anual tarjeta débito"), SERVICES)
    assert maintenance is not None and maintenance.concept == MAINTENANCE_CONCEPT
    assert card is not None and card.concept == CARD_CONCEPT


def test_accents_and_case_do_not_matter() -> None:
    assert _matched("COMISIÓN MANTENIMIENTO CUENTA") == "101"
    assert _matched("comision anual TARJETA DEBITO") == "401"


def test_the_counterparty_is_read_too() -> None:
    fee = peer_fee("Cuota anual", counterparty="Mantenimiento cuenta Demo")
    service = match_peer_service(fee, SERVICES)
    assert service is not None and service.service_code == "101"


def test_the_plural_does_not_match() -> None:
    assert _matched("Comisión tarjeta debitos") is None


def test_no_services_gives_no_match() -> None:
    assert match_peer_service(peer_fee("Comisión mantenimiento cuenta"), ()) is None


def test_ambiguity_comes_before_exclusion() -> None:
    fee = peer_fee("Mantenimiento cuenta y tarjeta de débito")
    assert match_peer_service(fee, SERVICES) is None
    assert match_peer_service(fee, SERVICES[1:]) is SERVICES[1]


# --- properties --------------------------------------------------------------------------------

_WORDS = (
    "Comisión",
    "mantenimiento",
    "de",
    "la",
    "cuenta",
    "tarjeta",
    "débito",
    "crédito",
    "debit",
    "credit",
    "card",
    "account",
    "maintenance",
    "custodia",
    "Azul",
    "anual",
)
_TEXTS = st.lists(st.sampled_from(_WORDS), max_size=6).map(" ".join)


@st.composite
def _recased(draw: st.DrawFn, text: str) -> str:
    """Draw the same text with the case of each character changed at random."""
    flags = draw(st.lists(st.booleans(), min_size=len(text), max_size=len(text)))
    return "".join(ch.upper() if up else ch.lower() for ch, up in zip(text, flags, strict=True))


@settings(max_examples=200)
@given(data=st.data(), description=_TEXTS, counterparty=_TEXTS)
def test_matching_does_not_depend_on_case(
    data: st.DataObject, description: str, counterparty: str
) -> None:
    original = match_peer_service(peer_fee(description, counterparty), SERVICES)
    recased = peer_fee(data.draw(_recased(description)), data.draw(_recased(counterparty)))
    assert match_peer_service(recased, SERVICES) == original


@settings(max_examples=200)
@given(description=_TEXTS, counterparty=_TEXTS)
def test_a_returned_service_always_has_matching_words(description: str, counterparty: str) -> None:
    service = match_peer_service(peer_fee(description, counterparty), SERVICES)
    if service is None:
        return
    fields = (fold_tokens(counterparty), fold_tokens(description))
    assert any(contains_phrase(tokens, service.words) for tokens in fields)
    assert not any(contains_phrase(tokens, service.exclude) for tokens in fields)
    others = [s for s in SERVICES if s is not service]
    assert not any(contains_phrase(t, s.words) for s in others for t in fields)


# --- PF5: template, guard check and card helpers (REQ-PF-16, REQ-PF-18, REQ-PF-19) --------------

VOCABULARY = default_vocabulary()
MANDATORY_SENTENCE = (
    "You must not invent any number, date, name, or amount. Every figure you mention must appear "
    "verbatim either in the source rows provided or in the structured fields of the alert (such "
    "as yearly_cost). Do not derive, round, or estimate any figure not explicitly present in "
    "those inputs."
)
# The accepted model text of REQ-PF-16 (S12 and the demo maintenance series, file s.csv).
ACCEPTED_TEXT = (
    "Of 12 payroll or pension accounts that declared an annual account maintenance fee on "
    "2026-11-23, 9 charge less than 78,00 EUR, 5 charge nothing, the median is 18,00 EUR and "
    "the highest is 240,00 EUR. Source: s.csv:0."
)
# The two sentences of REQ-PF-18 for that alert.
EXPECTED_SENTENCES = (
    "Of 12 payroll or pension accounts that declared an annual account maintenance fee to the "
    "Banco de España on 2026-11-23, 9 charge less than this fee costs a year (78,00 EUR). "
    "5 charge nothing; the median is 18,00 EUR and the highest 240,00 EUR."
)
EXPECTED_SOURCE_LINE = (
    "Comparison source: Banco de España, Comisiones de Cuentas de Pago, account type CNO "
    "(payroll or pension), service 101 (account maintenance), declared 2026-11-23; "
    "3 accounts show an asterisk (no fee is charged or the service is not offered)."
)
BANNED_WORDS = ("above", "below", "too", "expensive", "should", "cheaper", "switch")


@dataclass
class _Msg:
    content: str


@dataclass
class _Choice:
    message: _Msg


@dataclass
class _Response:
    choices: list[_Choice]


class MockLLMClient:
    """Mock client: `chat` and `completions` are properties; `create` records each call."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = iter(responses)
        self.calls: list[dict[str, Any]] = []

    @property
    def chat(self) -> "MockLLMClient":
        return self

    @property
    def completions(self) -> "MockLLMClient":
        return self

    def create(self, **kwargs: Any) -> _Response:
        self.calls.append(kwargs)
        return _Response([_Choice(_Msg(next(self._responses)))])


def _alert_and_ledger(
    snapshot: dict[str, Any] | None = None,
) -> tuple[Alert, pd.DataFrame]:
    """Return the demo maintenance alert with peers (S12 by default) and its ledger."""
    ledger = demo_maintenance_ledger()
    peers = peer_context(snapshot if snapshot is not None else s12_snapshot_dict())
    context = MappingProxyType({"vocabulary": VOCABULARY, "peers": peers})
    alerts = detect_recurring_fees(ledger, context)
    assert len(alerts) == 1
    return alerts[0], ledger


def _cited(alert: Alert, ledger: pd.DataFrame) -> pd.DataFrame:
    """Return the ledger rows the alert cites."""
    return ledger[ledger["source_ref"].isin(alert.source_refs)]


def _explain(answer: str, alert: Alert, ledger: pd.DataFrame) -> tuple[Explanation, MockLLMClient]:
    """Ask the explanation layer with a mock model that answers `answer`."""
    client = MockLLMClient([answer])
    explanation = explain_with_meta(
        alert, _cited(alert, ledger), fallback_template=template_for(alert), client=client
    )
    return explanation, client


ALERT, LEDGER = _alert_and_ledger()
PLAIN_ALERT = detect_recurring_fees(LEDGER, MappingProxyType({"vocabulary": VOCABULARY}))[0]


# --- the template (REQ-PF-18) ----------------------------------------------------------------


def test_template_for_an_alert_without_peer_keys_is_todays_template() -> None:
    assert not any(key.startswith("peer_") for key in PLAIN_ALERT.data)
    assert template_for(PLAIN_ALERT) is TEMPLATES["vf.recurring_fee"]


def test_template_for_an_alert_with_peer_keys_is_the_peer_template() -> None:
    assert template_for(ALERT) is RECURRING_FEE_WITH_PEERS_TEMPLATE


def test_the_filled_peer_template_is_the_string_of_req_pf_18() -> None:
    refs = ", ".join(ALERT.source_refs)
    assert fill_fallback(template_for(ALERT), ALERT) == (
        "BANCO FICTICIO charged you a monthly fee of 6,50 EUR (Comisión mantenimiento cuenta), "
        "22 times between 2025-01-05 and 2026-10-05, about 78,00 EUR per year. "
        f"{EXPECTED_SENTENCES} Source: {refs}."
    )


def test_the_sentence_alone_fills_to_the_two_sentences_of_decision_q9() -> None:
    assert fill_fallback(PEER_SENTENCE, ALERT) == EXPECTED_SENTENCES


def test_the_filled_template_without_peers_has_no_mention_of_the_bank_of_spain() -> None:
    text = fill_fallback(template_for(PLAIN_ALERT), PLAIN_ALERT)
    assert "Banco de España" not in text
    refs = ", ".join(PLAIN_ALERT.source_refs)
    assert text.endswith(f"about 78,00 EUR per year. Source: {refs}.")


def test_the_two_templates_start_with_the_same_text_and_end_with_the_source() -> None:
    tail = " Source: {source_refs}."
    today = TEMPLATES["vf.recurring_fee"]
    assert today.endswith(tail)
    assert RECURRING_FEE_WITH_PEERS_TEMPLATE.startswith(today.removesuffix(tail) + " ")
    assert RECURRING_FEE_WITH_PEERS_TEMPLATE.endswith(PEER_SENTENCE + tail)


def test_chip_source_template_still_finds_the_source_tail() -> None:
    refs = ["s.csv:0", "s.csv:1"]
    lines = {"s.csv:0": 2, "s.csv:1": 3}
    shown = chip_source_template(RECURRING_FEE_WITH_PEERS_TEMPLATE, refs, lines)
    assert shown.endswith(" Source: s.csv \u00b7 line 2, s.csv \u00b7 line 3.")
    assert "{source_refs}" not in shown


def test_the_templates_keys_are_still_the_registered_detectors() -> None:
    assert set(TEMPLATES) == set(registered_names("vf"))


def test_the_fee_summary_branch_is_unchanged() -> None:
    with_yearly = detect_fee_summary(summary_ledger(), {"vocabulary": VOCABULARY})[0]
    short = detect_fee_summary(summary_ledger(date(2026, 3, 30)), {"vocabulary": VOCABULARY})[0]
    assert template_for(with_yearly) == TEMPLATES["vf.fee_summary"]
    assert template_for(short) == FEE_SUMMARY_NO_YEARLY_TEMPLATE


def test_the_comparison_sentences_are_neutral_and_hold_no_digit() -> None:
    for text in (PEER_SENTENCE, RECURRING_FEE_WITH_PEERS_TEMPLATE):
        assert not any(ch.isdigit() for ch in text)
    for word in BANNED_WORDS:
        assert re.search(rf"\b{word}\b", PEER_SENTENCE, re.IGNORECASE) is None, word


def test_zero_counts_are_filled_as_they_are() -> None:
    """Ten accounts that all charge more than the fee: 0 charge less, 0 charge nothing."""
    snapshot = snapshot_dict_of([f"{100 + 10 * i}.00" for i in range(10)])
    alert, _ = _alert_and_ledger(snapshot)
    assert alert.data["peer_lower_count"] == 0 and alert.data["peer_zero_count"] == 0
    text = fill_fallback(template_for(alert), alert)
    assert "0 charge less than this fee costs a year (78,00 EUR). 0 charge nothing" in text


# --- the number guard, unchanged (REQ-PF-16) --------------------------------------------------


def test_the_accepted_text_of_req_pf_16_is_accepted() -> None:
    explanation, _ = _explain(ACCEPTED_TEXT, ALERT, LEDGER)
    assert explanation.source == "llm"
    assert explanation.rejected_numbers == ()
    assert explanation.text == ACCEPTED_TEXT


@pytest.mark.parametrize(
    ("old", "new", "rejected"),
    [
        ("Of 12 payroll", "Of 13 payroll", ("13",)),
        ("the highest is 240,00 EUR", "the highest is 250,00 EUR", ("250,00",)),
        ("the median is 18,00 EUR", "the median is 18,50 EUR", ("18,50",)),
        ("on 2026-11-23", "on 2026-11-24", ("2026-11-24",)),
    ],
)
def test_a_foreign_figure_or_date_is_rejected_and_the_template_is_returned(
    old: str, new: str, rejected: tuple[str, ...]
) -> None:
    assert old in ACCEPTED_TEXT
    explanation, _ = _explain(ACCEPTED_TEXT.replace(old, new), ALERT, LEDGER)
    assert explanation.source == "fallback"
    assert explanation.rejected_numbers == rejected
    assert explanation.text == fill_fallback(template_for(ALERT), ALERT)


def test_18_eur_is_accepted_for_18_00() -> None:
    explanation, _ = _explain(ACCEPTED_TEXT.replace("18,00 EUR", "18 EUR"), ALERT, LEDGER)
    assert explanation.source == "llm"


def test_a_yearly_figure_per_month_is_a_period_mismatch() -> None:
    answer = ACCEPTED_TEXT.replace("240,00 EUR.", "240,00 EUR per month.")
    explanation, _ = _explain(answer, ALERT, LEDGER)
    assert explanation.source == "fallback"
    assert explanation.rejected_reason == "period_mismatch"
    assert explanation.rejected_numbers == ("240,00", "per month")
    assert explanation.text == fill_fallback(template_for(ALERT), ALERT)


def test_the_filled_peer_template_passes_the_guard() -> None:
    answer = fill_fallback(template_for(ALERT), ALERT)
    explanation, _ = _explain(answer, ALERT, LEDGER)
    assert explanation.source == "llm", explanation.rejected_numbers
    assert explanation.text == answer


def test_the_system_message_is_unchanged_and_the_alert_json_carries_the_peer_fields() -> None:
    _, client = _explain(ACCEPTED_TEXT, ALERT, LEDGER)
    system, user = client.calls[0]["messages"]
    assert MANDATORY_SENTENCE in system["content"]
    assert str(ALERT.source_refs) in system["content"]
    assert "peer_median_yearly" in user["content"]
    assert '"peer_max_yearly":"240.00"' in user["content"].replace(" ", "")
    assert client.calls[0]["temperature"] == 0


_PLAIN_FIGURES = ("12", "3", "9", "5", "22")
_MONEY_FIGURES = ("78,00 EUR", "18,00 EUR", "240,00 EUR", "6,50 EUR")


@settings(max_examples=200)
@given(
    figures=st.lists(st.sampled_from(_PLAIN_FIGURES + _MONEY_FIGURES), min_size=1, max_size=6),
    foreign=st.integers(min_value=1000, max_value=9999),
    position=st.integers(min_value=0, max_value=6),
)
def test_only_figures_of_the_alert_pass_and_one_foreign_figure_fails(
    figures: list[str], foreign: int, position: int
) -> None:
    """A text made of numbers of alert.data is accepted; the same plus one foreign number is not."""
    text = "Figures: " + "; ".join(figures) + ". Source: s.csv:0."
    accepted, _ = _explain(text, ALERT, LEDGER)
    assert accepted.source == "llm", accepted.rejected_numbers
    mixed = list(figures)
    mixed.insert(min(position, len(mixed)), str(foreign))
    rejected, _ = _explain("Figures: " + "; ".join(mixed) + ". Source: s.csv:0.", ALERT, LEDGER)
    assert rejected.source == "fallback"
    assert rejected.rejected_numbers == (str(foreign),)


# --- the card helpers (REQ-PF-19) -------------------------------------------------------------


def test_peer_source_line_is_the_line_of_req_pf_19() -> None:
    assert peer_source_line(ALERT) == EXPECTED_SOURCE_LINE


def test_peer_source_line_is_none_without_peer_keys() -> None:
    assert peer_source_line(PLAIN_ALERT) is None


def test_peer_source_line_says_one_account_in_the_singular() -> None:
    one = ALERT.model_copy(update={"data": {**ALERT.data, "peer_not_offered_count": 1}})
    legend = "(no fee is charged or the service is not offered)"
    assert peer_source_line(one).endswith(f"; 1 account shows an asterisk {legend}.")
    none = ALERT.model_copy(update={"data": {**ALERT.data, "peer_not_offered_count": 0}})
    assert peer_source_line(none).endswith(f"; 0 accounts show an asterisk {legend}.")


def test_markdown_characters_of_a_label_are_escaped_by_markdown_safe() -> None:
    data = {**ALERT.data, "peer_service_label": "account *maintenance* [x]"}
    line = peer_source_line(ALERT.model_copy(update={"data": data}))
    assert line is not None and "account *maintenance* [x]" in line
    assert "account \\*maintenance\\* \\[x\\]" in markdown_safe(line)


def test_peer_sentence_to_add_is_none_for_the_fallback_explanation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    explanation = explain_with_meta(
        ALERT, _cited(ALERT, LEDGER), fallback_template=template_for(ALERT), client=None
    )
    assert explanation.source == "fallback" and EXPECTED_SENTENCES in explanation.text
    assert peer_sentence_to_add(ALERT, explanation) is None


def test_peer_sentence_to_add_gives_the_sentence_for_a_model_text_without_it() -> None:
    explanation, _ = _explain(ACCEPTED_TEXT, ALERT, LEDGER)
    assert explanation.source == "llm"
    assert peer_sentence_to_add(ALERT, explanation) == EXPECTED_SENTENCES


def test_peer_sentence_to_add_is_none_without_peer_keys() -> None:
    explanation = Explanation(text="Some text.", source="llm", rejected_numbers=())
    assert peer_sentence_to_add(PLAIN_ALERT, explanation) is None


def test_peer_sentence_to_add_never_adds_the_sentence_twice() -> None:
    text = f"{ACCEPTED_TEXT} {EXPECTED_SENTENCES}"
    explanation = Explanation(text=text, source="llm", rejected_numbers=())
    assert peer_sentence_to_add(ALERT, explanation) is None


def test_peer_attribution_lines_come_from_the_snapshot() -> None:
    snapshot = FeeSnapshot.from_dict(s12_snapshot_dict())
    lines = peer_attribution_lines(snapshot)
    assert lines == [
        "Fuente: Banco de España, comparador de comisiones de cuentas de pago "
        "(declaraciones a fecha 2026-11-23). Elaboración propia: recuento, mediana y máximo.",
        "Licence: see the Banco de España legal notice · retrieved 2026-11-23 · "
        "declarations of 2026-11-23",
        snapshot.licence_note,
        snapshot.no_endorsement,
    ]
    assert snapshot.no_endorsement == (
        "The Banco de España does not take part in, endorse or support this reuse."
    )
