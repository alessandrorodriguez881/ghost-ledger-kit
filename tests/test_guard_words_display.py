"""Session s52, amendment A-GH-02 (REQ-GH-26): a number in words is shown as the answer wrote it.

When the guard rejects a number written in words, the badge, the replay badge, the Provoke verdict
and the highlight show the words with their spaces (`two hundred and sixty-four`), even when the
token reached them without its spaces. What the guard checks does not change. Synthetic data only;
no network, no model.
"""

from datetime import date
from decimal import Decimal

import pandas as pd

from apps.phantom_invoices import explain_support as pi_support
from apps.vampire_fees import settings as vf_settings
from apps.zombie_subscriptions import settings as zs_settings
from ledger_kit import replay
from ledger_kit.explainer import Explanation, explain_with_meta
from ledger_kit.live_guard import (
    ProbeResult,
    highlight_segments,
    rejection_clause,
    rejection_reason_text,
    shown_token,
    shown_tokens,
    verdict_line,
)
from ledger_kit.models import Alert
from ledger_kit.number_words import find_number_phrases

SPACED = "two hundred and sixty-four"
GLUED = "twohundredandsixty-four"
RAW = f"SHOP charges {SPACED} euros. Source: shop.csv:1."


def _alert() -> Alert:
    """A synthetic alert whose only figure is 10.00."""
    return Alert(
        detector="zs.recurring_charge",
        severity="info",
        title="Recurring charge detected: SHOP",
        source_refs=["shop.csv:1"],
        data={"current_amount": "10.00"},
    )


def _rows() -> pd.DataFrame:
    """The one cited row of the alert."""
    return pd.DataFrame(
        {
            "date": [date(2026, 1, 5)],
            "amount": [Decimal("10.00")],
            "flow": ["debit"],
            "currency": ["EUR"],
            "counterparty": ["SHOP"],
            "source_ref": ["shop.csv:1"],
        }
    )


def _glued_explanation() -> Explanation:
    """A rejection whose word token reached the display without its spaces."""
    return Explanation("Template.", "fallback", (GLUED,), raw_answer=RAW)


# --- the guard itself is unchanged -------------------------------------------------------------


def test_the_guard_rejects_the_phrase_exactly_as_written() -> None:
    meta = explain_with_meta(
        _alert(),
        _rows(),
        fallback_template="Template. Source: {source_refs}.",
        client=replay.ReplayClient(RAW),
    )

    assert meta.source == "fallback"
    assert meta.rejected_numbers == (SPACED,)
    assert [p.text for p in find_number_phrases(RAW)] == [SPACED]


# --- shown_token ---------------------------------------------------------------------------------


def test_a_glued_word_token_is_shown_with_the_spaces_of_the_answer() -> None:
    assert shown_token(GLUED, RAW) == SPACED
    assert shown_token(SPACED, RAW) == SPACED


def test_white_space_of_the_answer_is_shown_as_one_space() -> None:
    raw = "You pay two  hundred\nand\tsixty-four euros."

    assert shown_token(GLUED, raw) == SPACED
    assert shown_token("two  hundred") == "two  hundred"  # no answer: the token as it came


def test_digits_dates_and_unknown_words_are_left_as_they_are() -> None:
    assert shown_token("539.40", RAW) == "539.40"
    assert shown_token("2026-05-09", RAW) == "2026-05-09"
    assert shown_token("$", RAW) == "$"
    assert shown_token("fortytwo", RAW) == "fortytwo"  # not in the answer
    assert shown_tokens(("539.40", GLUED), RAW) == ("539.40", SPACED)


def test_a_word_is_found_only_as_a_whole_word() -> None:
    assert shown_token("once", "A concession was made.") == "once"
    assert shown_token("once", "It was charged once.") == "once"


# --- every place that shows the token ----------------------------------------------------------


def test_the_three_app_badges_show_the_words_with_their_spaces() -> None:
    meta = _glued_explanation()

    labels = [
        zs_settings.guard_badge(meta, has_api_key=True).label,
        vf_settings.guard_badge(meta, has_api_key=True).label,
        pi_support.guard_badge(meta, True),
    ]

    for label in labels:
        assert f"not found in the cited rows or the alert data: {SPACED}" in label
        assert GLUED not in label


def test_the_reason_text_and_the_clause_show_the_words_with_their_spaces() -> None:
    assert rejection_reason_text("", (GLUED,), (), RAW) == (
        f"not found in the cited rows or the alert data: {SPACED}"
    )
    assert rejection_clause("", (GLUED, "2026"), (), RAW) == (
        f" (not found in the cited rows or the alert data: {SPACED}; a year on its own is not "
        "matched to the dates of the rows: 2026)"
    )
    # Without the answer the token is shown as it came, as before.
    assert rejection_reason_text("", ("539.40",), ()) == (
        "not found in the cited rows or the alert data: 539.40"
    )


def test_the_replay_badge_shows_the_words_with_their_spaces() -> None:
    recording = replay.Recording("a" * 64, "card", None, RAW, "testmodel:1b", "2026-11-16")

    kind, label = replay.card_badge(recording, _glued_explanation())

    assert kind == "rejected"
    assert f"not found in the cited rows or the alert data: {SPACED})" in label
    assert GLUED not in label


def test_the_provoke_verdict_shows_the_words_with_their_spaces() -> None:
    result = ProbeResult("forecast", RAW, "rejected", (GLUED,), "Template.")

    line = verdict_line(result)

    assert f"`{SPACED}`" in line and GLUED not in line


def test_the_highlight_marks_the_words_of_a_glued_token() -> None:
    flagged = [s.text for s in highlight_segments(RAW, (GLUED,)) if s.flagged]

    assert flagged == [SPACED]


def test_a_real_rejection_shows_the_same_words_in_the_badge() -> None:
    meta = explain_with_meta(
        _alert(),
        _rows(),
        fallback_template="Template. Source: {source_refs}.",
        client=replay.ReplayClient(RAW),
    )

    label = zs_settings.guard_badge(meta, has_api_key=False).label

    assert label.endswith(f"not found in the cited rows or the alert data: {SPACED}")
