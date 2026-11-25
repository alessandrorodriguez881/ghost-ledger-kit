"""Session s52 (REQ-AS-41, REQ-AS-42): two display fixes of the alert cards.

A fixed template or a recorded answer that lists more than six cited rows shows six and then the
line the chips already use, and two cards of a page with the same title show the amount of each
in the heading. Display only: the explanation keeps its whole text, Alert.title and the alert id
do not change. The synthetic demo files only; no network, no model.
"""

from collections.abc import Iterator
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from judge_path_support import ROOT, SCRIPTS, cases_of, filled_template, lines_of, shown_template
from streamlit.testing.v1 import AppTest

from ledger_kit.detectors import _restore_registry, _snapshot_registry
from ledger_kit.models import Alert
from ledger_kit.ui.signatures import (
    CARD_MAX_CHIPS,
    card_chips_html,
    card_headings,
    card_more_text,
    card_source_text,
    chip_text,
)

TIMEOUT_SECONDS = 120
DOT = "\u00b7"
GLOWBILL = "Recurring charge detected: GLOWBILL"


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Snapshot and restore the detector registry; no key, so explanations are the templates."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    snapshot = _snapshot_registry()
    try:
        yield
    finally:
        _restore_registry(snapshot)


def _refs(count: int) -> list[str]:
    """Return `count` synthetic refs of one file."""
    return [f"stmt.csv:{index}" for index in range(count)]


def _lines(refs: list[str]) -> dict[str, int]:
    """Give each ref the line after its row number plus one (the header is line 1)."""
    return {ref: int(ref.rsplit(":", 1)[1]) + 2 for ref in refs}


def _demo(prefix: str) -> list[str]:
    """Run one app alone, click Load demo data and return the markdown values of the page."""
    at = AppTest.from_file(str(ROOT / SCRIPTS[prefix]), default_timeout=TIMEOUT_SECONDS)
    at.run()
    at.button(key=f"{prefix}_load_demo").click().run()
    assert not at.exception
    return [element.value for element in at.markdown]


# --- REQ-AS-41: six refs, then the line of the chips -------------------------------------------


def test_six_refs_or_fewer_leave_the_text_as_it_is() -> None:
    refs = _refs(6)
    text = "Total. Source: " + ", ".join(refs) + "."

    assert card_source_text(text, refs) == text
    assert card_source_text(text, refs, _lines(refs)) == text


def test_seven_chip_refs_show_six_and_one_more_cited_row() -> None:
    refs = _refs(7)
    lines = _lines(refs)
    chips = [chip_text(ref, lines) for ref in refs]
    text = "Total. Source: " + ", ".join(chips) + "."

    shown = card_source_text(text, refs, lines)

    head = ", ".join(chips[:CARD_MAX_CHIPS])
    assert shown == f"Total. Source: {head} and 1 more cited row, all in Source rows below."
    assert chips[6] not in shown


def test_forty_five_raw_refs_show_six_and_thirty_nine_more_rows() -> None:
    refs = _refs(45)
    text = "Fees. Source: " + ", ".join(refs) + "."

    shown = card_source_text(text, refs)

    assert shown.endswith(" and 39 more cited rows, all in Source rows below.")
    assert "stmt.csv:5 and 39 more" in shown and "stmt.csv:6" not in shown


def test_the_text_line_reads_as_the_line_under_the_chips() -> None:
    refs = _refs(45)

    markup = card_chips_html(refs)
    shown = card_source_text("Source: " + ", ".join(refs) + ".", refs)

    assert card_more_text(39) in markup and card_more_text(39) in shown
    assert card_more_text(1) == "and 1 more cited row, all in Source rows below"


def test_a_text_without_the_whole_list_is_not_touched() -> None:
    refs = _refs(9)
    text = "This alert points to stmt.csv:0 and stmt.csv:8."

    assert card_source_text(text, refs) == text
    assert card_source_text("", refs) == ""


@settings(max_examples=200)
@given(count=st.integers(min_value=0, max_value=60))
def test_the_shown_list_never_holds_more_than_six_refs(count: int) -> None:
    refs = _refs(count)
    text = "Source: " + ", ".join(refs) + "."

    shown = card_source_text(text, refs)

    listed = shown.removeprefix("Source: ").split(" and ", 1)[0].rstrip(".").split(", ")
    assert len([item for item in listed if item]) == min(count, CARD_MAX_CHIPS)
    assert ("more cited row" in shown) == (count > CARD_MAX_CHIPS)


@pytest.mark.parametrize("prefix", ["zs", "vf"])
def test_every_long_demo_template_is_cut_and_the_explanation_keeps_every_row(prefix: str) -> None:
    lines = lines_of(prefix)
    long_cases = [c for c in cases_of(prefix) if len(c.alert.source_refs) > CARD_MAX_CHIPS]
    assert long_cases  # Zombie: the STREAMING and MUSICBOX cards; Vampire: Bank fees

    for case in long_cases:
        refs = list(case.alert.source_refs)
        chips = [chip_text(ref, lines) for ref in refs]
        full, shown = filled_template(case), shown_template(case)
        assert ", ".join(chips) in full  # what the guard and the explanation keep
        assert card_more_text(len(refs) - CARD_MAX_CHIPS) in shown
        assert ", ".join(chips[:CARD_MAX_CHIPS]) in shown
        assert shown.count(f" {DOT} line ") == CARD_MAX_CHIPS


def test_the_vampire_bank_fees_card_lists_six_rows_and_thirty_nine_more() -> None:
    values = _demo("vf")

    # The card text; the chips line under it ("**Source refs:** ...") ends with the same line.
    texts = [v for v in values if not v.startswith(("<", "**"))]
    [text] = [v for v in texts if card_more_text(39) in v]

    assert text.count(f"vampire_demo_statement.csv {DOT} line ") == CARD_MAX_CHIPS


def test_the_zombie_page_shows_no_card_text_with_more_than_six_rows() -> None:
    values = _demo("zs")

    texts = [v for v in values if not v.startswith(("<", "**"))]

    assert any("more cited rows, all in Source rows below" in t for t in texts)
    assert all(t.count(f"zombie_demo_statement.csv {DOT} line ") <= CARD_MAX_CHIPS for t in texts)


def test_phantom_cards_keep_their_whole_list() -> None:
    for case in cases_of("pi"):
        assert shown_template(case) == filled_template(case)


# --- REQ-AS-42: equal titles show the amount of each card ---------------------------------------


def _recurring(amount: str, title: str = GLOWBILL, **extra: object) -> Alert:
    """A recurring-charge alert of one amount."""
    return Alert(
        detector="zs.recurring_charge",
        severity="info",
        title=title,
        source_refs=[f"stmt.csv:{amount}"],
        data={"current_amount": amount, **extra},
    )


def test_two_cards_with_one_title_show_the_amount_of_each() -> None:
    first, second = _recurring("2.99"), _recurring("0.99")

    headings = card_headings([first, second])

    assert headings[first.id] == f"{GLOWBILL}, 2,99 EUR"
    assert headings[second.id] == f"{GLOWBILL}, 0,99 EUR"


def test_a_title_shown_once_stays_bare_and_the_alerts_are_not_touched() -> None:
    alone = _recurring("8.99", "Recurring charge detected: GYMPLUS")
    first, second = _recurring("2.99"), _recurring("0.99")
    before = [(a.id, a.title, dict(a.data)) for a in (alone, first, second)]

    headings = card_headings([alone, first, second])

    assert headings[alone.id] == "Recurring charge detected: GYMPLUS"
    assert [(a.id, a.title, dict(a.data)) for a in (alone, first, second)] == before
    assert first.id == Alert(**first.model_dump(exclude={"id", "explanation"})).id


def test_the_amount_takes_the_currency_of_the_alert_and_a_card_without_one_stays_bare() -> None:
    usd = _recurring("1234.5", currency="USD")
    other = _recurring("3.00")
    bare = Alert(detector="x", severity="info", title=GLOWBILL, source_refs=["s.csv:1"], data={})

    headings = card_headings([usd, other, bare], currency="EUR")

    assert headings[usd.id] == f"{GLOWBILL}, 1.234,50 USD"
    assert headings[other.id] == f"{GLOWBILL}, 3,00 EUR"
    assert headings[bare.id] == GLOWBILL


def test_the_zombie_demo_glowbill_cards_have_two_headings_and_unchanged_ids() -> None:
    glowbill = [c.alert for c in cases_of("zs") if c.alert.title == GLOWBILL]
    assert len(glowbill) == 2
    ids = [a.id for a in glowbill]

    headings = card_headings([c.alert for c in cases_of("zs")], "EUR")
    amounts = {Decimal(a.data["current_amount"]) for a in glowbill}

    assert amounts == {Decimal("2.99"), Decimal("0.99")}
    assert {headings[i] for i in ids} == {f"{GLOWBILL}, 2,99 EUR", f"{GLOWBILL}, 0,99 EUR"}
    assert [a.title for a in glowbill] == [GLOWBILL, GLOWBILL]
    assert [a.id for a in glowbill] == ids

    values = _demo("zs")
    titles = [v for v in values if v.startswith('<div class="zs-alert-title">')]
    assert sum(t.endswith(f"{GLOWBILL}, 2,99 EUR</div>") for t in titles) == 1
    assert sum(t.endswith(f"{GLOWBILL}, 0,99 EUR</div>") for t in titles) == 1
    assert not any(t.endswith(f"{GLOWBILL}</div>") for t in titles)
