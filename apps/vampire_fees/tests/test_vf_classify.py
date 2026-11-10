"""Tests for fee classification and extraction (Task VF3; AE-VF-01 to AE-VF-07)."""

from datetime import date
from typing import Any

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from apps.vampire_fees.detectors.utils import (
    EMPTY_VOCABULARY,
    Fee,
    classify_fee,
    extract_fees,
    skipped_currency_rows,
    sorted_refs,
    statement_span,
)
from apps.vampire_fees.tests.vf_builders import (
    BANK,
    default_vocabulary,
    fee_row,
    ledger_strategy,
    make_ledger,
)
from ledger_kit.detectors import loaded_source_refs

DAY = date(2026, 1, 5)
VOCABULARY = default_vocabulary()


def classify(
    description: str,
    *,
    counterparty: str = BANK,
    tags: Any = None,
    flow: str = "debit",
    currency: str = "EUR",
    vocabulary=VOCABULARY,
) -> Fee | None:
    """Classify one synthetic row."""
    row = fee_row(
        0,
        DAY,
        "5.00",
        counterparty=counterparty,
        description=description,
        tags=tags,
        flow=flow,
        currency=currency,
    )
    return classify_fee(row, vocabulary)


# --- Tier 1: acceptance examples ----------------------------------------------------------------


def test_ae_vf_01_concept_rule() -> None:
    """AE-VF-01: concept 17 makes a fee whatever the words; without it the row is not a fee."""
    fee = classify("TARJ 0042", tags=["common_concept:17"])
    assert fee is not None
    assert fee.kind == "other"
    assert classify("TARJ 0042", tags=[]) is None


def test_ae_vf_02_accent_and_case_are_folded() -> None:
    """AE-VF-02: accent- and case-insensitive vocabulary match."""
    fee = classify("COMISIÓN MANTENIMIENTO")
    assert fee is not None and fee.kind == "other"
    fee = classify("Commission foreign payment")
    assert fee is not None and fee.kind == "other"


def test_ae_vf_03_fee_inside_a_word_is_not_a_fee() -> None:
    """AE-VF-03: `fee` is not a token of `Feelgood`."""
    assert (
        classify("Card purchase", counterparty="Feelgood Market", tags=["common_concept:12"])
        is None
    )


def test_ae_vf_04_notary_is_excluded_unless_a_concept_says_fee() -> None:
    """AE-VF-04: the exclusion vocabulary beats words, never a concept."""
    kwargs = {"counterparty": "Notaría Ana García"}
    assert classify("Transferencia gastos escritura", tags=["common_concept:04"], **kwargs) is None
    assert classify("Transferencia gastos escritura", tags=["common_concept:17"], **kwargs)


def test_ae_vf_05_credit_is_never_a_fee() -> None:
    """AE-VF-05: a refund of a fee is a credit and not a fee."""
    assert (
        classify("Devolución comisión transferencia", tags=["common_concept:17"], flow="credit")
        is None
    )


def test_ae_vf_06_kinds() -> None:
    """AE-VF-06: overdraft interest, overdraft fee and other."""
    interest = classify("Intereses deudores")
    assert interest is not None
    assert interest.kind == "overdraft" and interest.overdraft_interest is True
    fee = classify("Comisión por descubierto")
    assert fee is not None
    assert fee.kind == "overdraft" and fee.overdraft_interest is False
    other = classify("Comisión mantenimiento cuenta")
    assert other is not None and other.kind == "other"


def test_ae_vf_07_exclusion_wins_over_words_and_currency_is_skipped() -> None:
    """AE-VF-07: honorarios exclude; a USD row is not considered."""
    assert classify("Honorarios comisión", counterparty="Gestoría Luigi Rossi") is None
    assert classify("Comisión", currency="USD") is None


def test_concept_kind_applies_to_concept_accepted_rows() -> None:
    """The kind rule also applies to rows accepted by the concept rule."""
    fee = classify("Intereses deudores", tags=["common_concept:17"])
    assert fee is not None and fee.kind == "overdraft"


def test_other_concept_does_not_veto_a_fee_word() -> None:
    """REQ-VF-09: concept 12 with `Comisión` is a fee; concept 16 alone is a fee; 03 is not."""
    assert classify("Comisión", tags=["common_concept:12"]) is not None
    assert classify("Cargo", tags=["common_concept:16"]) is not None
    assert classify("Cargo", tags=["common_concept:03"]) is None


def test_fee_carries_the_row_values() -> None:
    """The Fee keeps ref, row, date, amount, raw text and the series key."""
    fee = classify("Comisión mantenimiento cuenta 05/26")
    assert fee is not None
    assert fee.source_ref == "vf_fixture.csv:0"
    assert fee.source_row == 0
    assert fee.date == DAY
    assert str(fee.amount) == "5.00"
    assert fee.counterparty == BANK
    assert fee.description == "Comisión mantenimiento cuenta 05/26"
    assert fee.key == "banco ficticio|comision mantenimiento cuenta"


def test_phrase_is_searched_in_each_field_separately() -> None:
    """A two-word phrase split over counterparty and description does not match."""
    assert classify("de mantenimiento", counterparty="cuota") is None


# --- Tier 2: extraction -------------------------------------------------------------------------


def test_extract_fees_on_an_empty_frame() -> None:
    """A frame without rows or columns gives no fees."""
    assert extract_fees(pd.DataFrame(), VOCABULARY) == []
    assert extract_fees(make_ledger([]), VOCABULARY) == []


def test_extract_fees_on_one_row() -> None:
    """A one-row ledger gives a list."""
    ledger = make_ledger([fee_row(0, DAY, "5.00")])
    fees = extract_fees(ledger, VOCABULARY)
    assert isinstance(fees, list) and len(fees) == 1


@pytest.mark.parametrize("tags", [None, float("nan"), [], ("x",)])
def test_extract_fees_survives_missing_tags(tags: Any) -> None:
    """None, NaN, empty and odd tag values do not crash."""
    row = fee_row(0, DAY, "5.00", description="Cargo")
    row["tags"] = tags
    assert extract_fees(make_ledger([row]), VOCABULARY) == []


def test_extract_fees_duplicate_source_ref_keeps_the_first() -> None:
    """REQ-VF-14: two rows with one source_ref give one fee, the first."""
    first = fee_row(0, DAY, "5.00", source_ref="s.csv:7")
    second = fee_row(1, date(2026, 2, 5), "9.00", source_ref="s.csv:7")
    fees = extract_fees(make_ledger([first, second]), VOCABULARY)
    assert len(fees) == 1
    assert str(fees[0].amount) == "5.00" and fees[0].date == DAY


def test_extract_fees_orders_by_date_then_row() -> None:
    """Fees come out ordered by (date, source_row), never by ref text."""
    rows = [
        fee_row(10, date(2026, 3, 5), "5.00"),
        fee_row(2, date(2026, 1, 5), "5.00"),
        fee_row(9, date(2026, 1, 5), "5.00"),
    ]
    fees = extract_fees(make_ledger(rows), VOCABULARY)
    assert [f.source_row for f in fees] == [2, 9, 10]
    assert sorted_refs(reversed(fees)) == [f.source_ref for f in fees]


def test_sorted_refs_are_unique() -> None:
    """A repeated fee is cited once."""
    fee = classify("Comisión")
    assert fee is not None
    assert sorted_refs([fee, fee]) == [fee.source_ref]


def test_skipped_currency_rows_counts_non_eur_rows() -> None:
    """USD rows are counted, EUR rows are not."""
    rows = [
        fee_row(0, DAY, "5.00"),
        fee_row(1, DAY, "5.00", currency="USD"),
        fee_row(2, DAY, "5.00", currency="USD", flow="credit"),
    ]
    assert skipped_currency_rows(make_ledger(rows)) == 2
    assert skipped_currency_rows(pd.DataFrame()) == 0


def test_empty_vocabulary_classifies_by_concept_only() -> None:
    """Without a vocabulary only concepts 16 and 17 make a fee."""
    rows = [
        fee_row(0, DAY, "5.00", description="Comisión"),
        fee_row(1, DAY, "5.00", description="Cargo", tags=["common_concept:17"]),
    ]
    fees = extract_fees(make_ledger(rows), EMPTY_VOCABULARY)
    assert [f.source_row for f in fees] == [1]


def test_non_eur_row_neither_counts_nor_extends_the_span() -> None:
    """statement_span uses EUR rows only, credits included."""
    rows = [
        fee_row(0, date(2026, 1, 1), "5.00"),
        fee_row(1, date(2026, 3, 31), "9.00", flow="credit"),
        fee_row(2, date(2027, 1, 1), "9.00", currency="USD"),
    ]
    assert statement_span(make_ledger(rows)) == (date(2026, 1, 1), date(2026, 3, 31))
    assert statement_span(pd.DataFrame()) is None
    assert statement_span(make_ledger([fee_row(0, DAY, "1.00", currency="USD")])) is None


# --- Tier 3: properties ---------------------------------------------------------------------------


@settings(max_examples=200)
@given(
    text=st.text(max_size=30),
    tags=st.sampled_from([None, [], ["common_concept:17"], ["common_concept:16"]]),
    cp=st.sampled_from([BANK, "Ana García"]),
)
def test_a_credit_is_never_a_fee(text: str, tags: Any, cp: str) -> None:
    """A credit row is never a fee, for any text and tag."""
    assert classify(text, tags=tags, counterparty=cp, flow="credit") is None


@settings(max_examples=200)
@given(
    words=st.lists(st.sampled_from(("Mercado", "Café", "Tienda", "Luna", "Feelgood")), max_size=3),
    tag=st.sampled_from([None, [], ["common_concept:12"], ["common_concept:04"]]),
)
def test_no_word_and_no_concept_is_never_a_fee(words: list[str], tag: Any) -> None:
    """A debit EUR row without vocabulary phrase and without concept 16/17 is never a fee."""
    assert classify(" ".join(words), tags=tag, counterparty="Mercado Central Demo") is None


@settings(max_examples=200)
@given(ledger=ledger_strategy())
def test_extract_fees_is_idempotent_and_cites_only_loaded_rows(ledger: pd.DataFrame) -> None:
    """Two runs give equal fees and every ref belongs to the ledger."""
    first = extract_fees(ledger, VOCABULARY)
    assert first == extract_fees(ledger, VOCABULARY)
    loaded = loaded_source_refs(ledger, {})
    assert {fee.source_ref for fee in first} <= loaded
    assert all(fee.amount > 0 for fee in first)
