"""Config and matching of the fee comparison (public-fees PF3: REQ-PF-09, REQ-PF-10).

Every text is synthetic; counterparties are fictional (Finance Rule 5). Nothing reads a snapshot.
"""

import copy
import tomllib
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from apps.vampire_fees.detectors.utils import (
    PeerService,
    build_peer_services,
    classify_fee,
    contains_phrase,
    fold_tokens,
    match_peer_service,
)
from apps.vampire_fees.tests.vf_builders import BANK, default_vocabulary, fee_row, peer_fee
from ledger_kit.public_data import ACCOUNT_TYPES

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.toml"
MAINTENANCE_CONCEPT = "Comisión anual total (euros)"
CARD_CONCEPT = "Comisión mantenimiento. Anual total (euros)"

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
