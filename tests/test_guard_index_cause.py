"""The price index is context, never the cause of the price change (REQ-GH-23).

Tier 1: the two recorded demo answers Z04 and Z05 of 2026-11-11, English and Spanish sentences.
Tier 2: sentences that must stay accepted (index without a cause, cause without an index, the
kit's own fixed CPI sentence). Tier 3: Hypothesis properties. The rejection is recorded like a
rejected token (`rejected_numbers`) plus a reason that the panel and the replay show.
"""

import json
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from judge_path_support import COMMITTED_RUN, cases_of, find_case, template_of

from ledger_kit.explainer import Explanation, explain_with_meta, fill_fallback
from ledger_kit.index_cause import (
    CAUSE_PHRASES,
    INDEX_TERMS,
    REASON_INDEX_AS_CAUSE,
    find_index_as_cause,
)
from ledger_kit.live_guard import (
    VERDICT_REJECTED_INDEX_CAUSE_PREFIX,
    TrickQuestion,
    highlight_segments,
    probe_result,
    verdict_line,
)
from ledger_kit.replay import Recording, ReplayClient, card_badge

# The two sentences of the recorded answers that the guard accepted before this rule.
Z04_SENTENCE = (
    "The price change is attributed to the IPC290751 CPI series, which is based on the 2025 "
    "base year."
)
Z05_SENTENCE = (
    "The price change is attributed to the CPI series IPC290751, which started in May 2026."
)


def _record(record_id: str) -> dict[str, Any]:
    document = json.loads(COMMITTED_RUN.read_text(encoding="utf-8"))
    return next(r for r in document["records"] if r["id"] == record_id)


def _verdict(record: dict[str, Any], text: str | None = None) -> Explanation:
    """Today's verdict on a recorded card answer, or on `text` for the same alert."""
    case = find_case(record["alert_id"])
    assert case is not None
    return explain_with_meta(
        case.alert,
        case.rows,
        fallback_template=template_of(case),
        client=ReplayClient(record["raw_answer"] if text is None else text),
        row_columns=case.columns,
    )


# --- Tier 1: the two recorded answers ---------------------------------------------------------


@pytest.mark.parametrize(("record_id", "sentence"), [("Z04", Z04_SENTENCE), ("Z05", Z05_SENTENCE)])
def test_the_recorded_demo_answer_is_rejected_and_the_card_falls_back(
    record_id: str, sentence: str
) -> None:
    record = _record(record_id)
    assert sentence in record["raw_answer"]
    assert record["observed_source"] == "llm"  # accepted on the day of the recording

    result = _verdict(record)

    assert result.source == "fallback"
    assert result.rejected_numbers == (sentence,)
    assert result.rejected_reason == REASON_INDEX_AS_CAUSE
    assert result.raw_answer == record["raw_answer"]
    case = find_case(record["alert_id"])
    assert case is not None
    assert result.text == fill_fallback(template_of(case), case.alert)


@pytest.mark.parametrize(
    "sentence",
    [
        Z04_SENTENCE,
        Z05_SENTENCE,
        "The increase is due to inflation.",
        "The rise was caused by the consumer price index.",
        "It happened because of the price index.",
        "The price is driven by the IPC.",
        "The rise is explained by the CPI.",
        "The rise is a result of the CPI.",
        "The increase is attributable to inflation.",
        "THE INCREASE IS DUE TO INFLATION.",
        "El aumento se debe a la inflación.",
        "El aumento se debe a la inflacion.",
        "El aumento se debe al IPC.",
        "El aumento, causado por el índice de precios, es visible.",
        "El aumento es causado por el indice de precios al consumo.",
        "El precio cambió debido a la inflación.",
        "Debido al IPC290751 el precio subió.",
    ],
)
def test_a_sentence_that_names_the_index_as_cause_is_found(sentence: str) -> None:
    assert find_index_as_cause(sentence) == (sentence,)
    assert find_index_as_cause(f"The charge rose. {sentence} Source: a.csv:1.") == (sentence,)


def test_only_the_sentences_with_both_parts_are_reported_in_text_order() -> None:
    text = (
        "The CPI gives context. The rise is due to inflation. The price rose because the plan "
        "changed.\nSe debe a la inflación."
    )

    assert find_index_as_cause(text) == (
        "The rise is due to inflation.",
        "Se debe a la inflación.",
    )


# --- Tier 2: what must stay accepted ----------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "The CPI gives context for these months.",
        "The Spanish CPI (INE series IPC290751) changed by 1,20 % from May 2026 to June 2026.",
        "El índice de precios da contexto para estos meses.",
        "La inflación cambió entre los dos meses.",
        "The price rose because the plan changed.",
        "El precio subió debido a que cambió el plan.",
        "A cause is due to be shown. The CPI is a series.",
        "The topic is a cpiano and a pipc.",
        "",
    ],
)
def test_a_text_without_both_parts_in_one_sentence_is_accepted(text: str) -> None:
    assert find_index_as_cause(text) == ()


def test_the_kits_own_cpi_sentence_is_never_a_cause() -> None:
    """The fixed templates of every price increase with CPI context, filled from a real alert."""
    cpi_cases = [
        case
        for case in cases_of("zs")
        if case.alert.detector == "zs.price_increase" and "cpi_change_percent" in case.alert.data
    ]
    assert cpi_cases, "the zombie demo must hold a price increase with CPI context"

    for case in cpi_cases:
        filled = fill_fallback(template_of(case), case.alert)
        assert "IPC290751" in filled
        assert find_index_as_cause(filled) == ()


def test_an_answer_that_only_gives_context_is_accepted_by_the_explainer() -> None:
    record = _record("Z04")
    text = f"The CPI gives context for these months. Source: {record['source_refs'][0]}."

    result = _verdict(record, text)

    assert result.source == "llm" and result.rejected_numbers == ()
    assert result.rejected_reason == ""


def test_a_figure_rejection_keeps_no_reason() -> None:
    record = _record("Z04")

    result = _verdict(record, "It will cost 98765.43 EUR.")

    assert result.source == "fallback" and "98765.43" in result.rejected_numbers
    assert result.rejected_reason == ""


# --- the reason is shown by the panel and the replay -------------------------------------------


def test_the_panel_verdict_says_why_and_the_sentence_is_marked() -> None:
    record = _record("Z05")
    probe = probe_result(TrickQuestion("forecast", "label", "text"), _verdict(record), "template")

    assert probe.reason == REASON_INDEX_AS_CAUSE
    assert verdict_line(probe) == VERDICT_REJECTED_INDEX_CAUSE_PREFIX + f"`{Z05_SENTENCE}`"
    assert "cause of the price change" in verdict_line(probe)
    flagged = [s.text for s in highlight_segments(record["raw_answer"], probe.rejected_numbers)]
    assert Z05_SENTENCE in flagged


def test_the_replay_badge_says_why_the_card_fell_back() -> None:
    record = _record("Z04")
    recording = Recording(
        record["alert_id"], "card", None, record["raw_answer"], "llama3.2:3b", "2026-11-11"
    )

    kind, label = card_badge(recording, _verdict(record))

    assert kind == "rejected"
    assert "the answer names the price index as the cause of the price change" in label
    assert Z04_SENTENCE in label
    assert "Fixed template shown. No model called." in label


# --- Tier 3: properties -------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(
    index=st.sampled_from(["IPC", "IPC290751", "CPI", "inflation", "price index", "Inflación"]),
    cause=st.sampled_from(CAUSE_PHRASES),
    shout=st.booleans(),
)
def test_any_index_term_with_any_cause_phrase_in_one_sentence_is_found(
    index: str, cause: str, shout: bool
) -> None:
    sentence = f"The change is {cause.upper() if shout else cause} the {index}."

    assert find_index_as_cause(sentence) == (sentence,)


@settings(max_examples=200, deadline=None)
@given(
    words=st.lists(
        st.sampled_from(["The", "CPI", "IPC", "inflation", "price index", "rose", "context", "."]),
        max_size=20,
    )
)
def test_index_words_without_a_cause_phrase_are_never_found(words: list[str]) -> None:
    assert find_index_as_cause(" ".join(words)) == ()


@settings(max_examples=200, deadline=None)
@given(text=st.text(max_size=200))
def test_the_check_never_raises_and_reports_only_sentences_of_the_text(text: str) -> None:
    for sentence in find_index_as_cause(text):
        assert sentence in text


def test_the_phrase_lists_are_the_ones_of_the_requirement() -> None:
    assert len(CAUSE_PHRASES) == 11
    assert len(INDEX_TERMS) == 7
