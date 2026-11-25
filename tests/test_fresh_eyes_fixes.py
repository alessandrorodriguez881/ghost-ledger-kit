"""Session 34 (REQ-AS-36 to REQ-AS-39): small fixes found by a fresh-eyes review.

Each fix makes a sentence the person reads true, or shows the line of the file instead of the
internal key: the fixed template names its cited rows as the chips do, the badge of a rejected card
says the real reason, the sentences about the guard say what it does, and the Try it texts say
that only the CSV demo has recorded answers. The synthetic demo files only; no network, no model.
"""

import re
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from judge_path_support import (
    ROOT,
    SCRIPTS,
    cases_of,
    escape_for,
    filled_template,
    lines_of,
    shown_template,
)
from streamlit.testing.v1 import AppTest

import streamlit_app
from apps.phantom_invoices import explain_support as pi_support
from apps.vampire_fees import settings as vf_settings
from apps.zombie_subscriptions import settings as zs_settings
from ledger_kit import replay
from ledger_kit.calc import REASON_CALC_NOT_ALLOWED
from ledger_kit.detectors import _restore_registry, _snapshot_registry
from ledger_kit.explainer import REASON_PERIOD_MISMATCH, Explanation, fill_fallback
from ledger_kit.index_cause import REASON_INDEX_AS_CAUSE
from ledger_kit.live_guard import (
    NOTE_GUARD_SCOPE,
    VERDICT_ACCEPTED,
    rejection_clause,
    rejection_reason_text,
)
from ledger_kit.ui import landing
from ledger_kit.ui.signatures import chip_source_template, chip_text

TIMEOUT_SECONDS = 120
DOT = "\u00b7"
ENTRY = str(ROOT / "streamlit_app.py")
PREFIXES = sorted(SCRIPTS)
HEAD = "⚠️ LLM answer rejected: "
NOT_FOUND = "not found in the cited rows or the alert data"
INDEX_CAUSE = "the answer names the price index as the cause of the price change"
PERIOD = "the answer gives a figure a period that contradicts the alert field it matches"
CALC = "the answer asks the kit for a calculation it will not make"


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Snapshot and restore the detector registry; no key unless a test sets one."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    snapshot = _snapshot_registry()
    try:
        yield
    finally:
        _restore_registry(snapshot)


# --- REQ-AS-36: the fixed template names its rows as the chips do -------------------------------


def test_the_template_reads_its_rows_as_the_chips_read_them() -> None:
    lines = {"a.csv:5": 7, "b.csv:5": 30}

    shaped = chip_source_template("Total. Source: {source_refs}.", ["a.csv:5", "b.csv:5"], lines)

    assert shaped == f"Total. Source: a.csv {DOT} line 7, b.csv {DOT} line 30."
    assert shaped.count("{") == 0
    for ref in lines:
        assert chip_text(ref, lines) in shaped  # the very text of the chip


def test_an_xml_ref_reads_invoice_and_a_ref_without_a_line_stays_raw() -> None:
    shaped = chip_source_template("S: {source_refs}.", ["f.xml:3", "g.csv:4"], {})

    assert shaped == f"S: f.xml {DOT} invoice 3, g.csv:4."
    assert chip_source_template("S: {source_refs}.", ["g.csv:4"], None) == "S: g.csv:4."


def test_a_brace_in_a_file_name_still_fills_and_the_other_fields_are_left_alone() -> None:
    alert = cases_of("pi")[0].alert
    shaped = chip_source_template("{total:money} {x}. Source: {source_refs}.", ["w{i}.csv:1"], {})
    # a template with no placeholder of the alert is the plain case of fill_fallback
    assert shaped == "{total:money} {x}. Source: w{{i}}.csv:1."
    assert fill_fallback("Source: " + "w{{i}}.csv:1.", alert) == "Source: w{i}.csv:1."
    assert chip_source_template("No refs here.", ["a.csv:1"], {}) == "No refs here."


def test_the_alert_keeps_its_internal_refs() -> None:
    case = cases_of("pi")[0]
    before = list(case.alert.source_refs)

    shown_template(case)

    assert list(case.alert.source_refs) == before
    assert all(re.fullmatch(r".+:\d+", ref) for ref in before)  # still file:row


@pytest.mark.parametrize("prefix", PREFIXES)
def test_one_template_per_app_shows_lines_and_no_internal_key(prefix: str) -> None:
    lines = lines_of(prefix)
    case = next(c for c in cases_of(prefix) if any(r in lines for r in c.alert.source_refs))

    text = filled_template(case)

    chips = ", ".join(chip_text(ref, lines) for ref in case.alert.source_refs)
    assert f"Source: {chips}." in text
    assert f" {DOT} line " in text
    assert not any(ref in text for ref in case.alert.source_refs if ref in lines)


@pytest.mark.parametrize("prefix", PREFIXES)
def test_the_cards_without_a_model_answer_show_the_chip_template(
    prefix: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    if prefix == "vf":
        # No snapshot here; the cards with the comparison are checked in test_vf_peer_demo.py.
        real_load_config = vf_settings.load_config

        def without_snapshot(config_path: Path) -> dict:
            config = real_load_config(config_path)
            missing = str(Path(__file__).parent / "missing_fee_snapshot.json")
            config["peer_fees"] = {**config["peer_fees"], "snapshot_path": missing}
            return config

        monkeypatch.setattr(vf_settings, "load_config", without_snapshot)
    at = AppTest.from_file(str(ROOT / SCRIPTS[prefix]), default_timeout=TIMEOUT_SECONDS).run()
    at.button(key=f"{prefix}_load_demo").click().run()

    assert not at.exception
    values = [element.value for element in at.markdown]
    escape = escape_for(prefix)
    for case in cases_of(prefix):
        assert escape(shown_template(case)) in values


def test_the_phantom_duplicate_card_says_line_2_and_line_3() -> None:
    at = AppTest.from_file(str(ROOT / SCRIPTS["pi"]), default_timeout=TIMEOUT_SECONDS).run()
    at.button(key="pi_load_demo").click().run()

    line = (
        "Supplier Suministros Ibéricos Aurora, S.L. sent 2 invoices with the same invoice "
        "number, both issued on 2026-10-06. "
        f"Source: invoices.csv {DOT} line 2, invoices.csv {DOT} line 3."
    )
    assert line in [element.value for element in at.markdown]
    assert "invoices.csv:0" not in line and "invoices.csv:1" not in line


def test_the_home_moment_template_names_its_rows_as_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(replay, "HOME_EXAMPLE_PATH", replay.DEFAULT_HOME_EXAMPLE_PATH)

    at = AppTest.from_file(ENTRY, default_timeout=TIMEOUT_SECONDS).run()

    assert not at.exception
    [moment] = [e.value for e in at.markdown if e.value.startswith('<div class="gl-moment">')]
    [template] = re.findall(r'<div class="gl-moment-template">(.*?)</div>', moment)
    assert f"Source: invoices.csv {DOT} line " in template
    assert re.search(r"\.csv:\d", template) is None


# --- REQ-AS-37: the badge says the real reason --------------------------------------------------


def _zs_badge(meta: Explanation) -> str:
    return zs_settings.guard_badge(meta, has_api_key=False).label


def _vf_badge(meta: Explanation) -> str:
    return vf_settings.guard_badge(meta, has_api_key=False).label


def _pi_badge(meta: Explanation) -> str:
    return pi_support.guard_badge(meta, False)


BADGES: list[Callable[[Explanation], str]] = [_zs_badge, _vf_badge, _pi_badge]


def _rejected(tokens: tuple[str, ...], reason: str = "", why: tuple[str, ...] = ()) -> Explanation:
    """A fallback explanation as the explainer returns it after a rejection."""
    return Explanation(
        text="fixed template",
        source="fallback",
        rejected_numbers=tokens,
        raw_answer="raw",
        rejected_reason=reason,
        rejected_why=why,
    )


def _replay_label(meta: Explanation) -> str:
    """The badge of the same rejection as the recorded-answer badge writes it."""
    recording = replay.Recording("id", "card", None, "raw", "model", "2026-11-16")
    return replay.card_badge(recording, meta)[1]


@pytest.mark.parametrize("badge", BADGES)
def test_a_figure_rejection_keeps_its_badge(badge: Callable[[Explanation], str]) -> None:
    label = badge(_rejected(("99999.99", "5")))

    assert label == f"{HEAD}{NOT_FOUND}: 99999.99, 5"


@pytest.mark.parametrize("badge", BADGES)
def test_the_price_index_as_cause_is_named_not_called_a_missing_figure(
    badge: Callable[[Explanation], str],
) -> None:
    sentence = "The price change is attributed to the CPI series."
    meta = _rejected((sentence,), REASON_INDEX_AS_CAUSE)

    label = badge(meta)

    assert label == f"{HEAD}{INDEX_CAUSE}: {sentence}"
    assert NOT_FOUND not in label
    assert f"({INDEX_CAUSE}: {sentence})" in _replay_label(meta)  # the wording of the replay badge


@pytest.mark.parametrize("badge", BADGES)
def test_a_period_that_contradicts_its_field_is_named(
    badge: Callable[[Explanation], str],
) -> None:
    meta = _rejected(("10.99", "every year"), REASON_PERIOD_MISMATCH)

    label = badge(meta)

    assert label == f"{HEAD}{PERIOD}: 10.99, every year"
    assert NOT_FOUND not in label


@pytest.mark.parametrize("badge", BADGES)
def test_a_refused_calculation_is_named_with_its_reasons(
    badge: Callable[[Explanation], str],
) -> None:
    why = ("the field total is not a field of the alert",)
    meta = _rejected(("total + 1",), REASON_CALC_NOT_ALLOWED, why)

    label = badge(meta)

    assert label == f"{HEAD}{CALC}: {why[0]}"
    assert f"({CALC}: {why[0]})" in _replay_label(meta)


@pytest.mark.parametrize("badge", BADGES)
def test_a_currency_the_data_does_not_name_is_said_in_words(
    badge: Callable[[Explanation], str],
) -> None:
    why = ("the currency $ is not named in the cited rows",)
    meta = _rejected(("$",), "", why)

    label = badge(meta)

    assert label == HEAD + rejection_clause("", ("$",), why)[2:-1]
    assert why[0] in label


def test_the_reason_text_is_the_clause_of_the_replay_without_its_parentheses() -> None:
    why = ("the field x is not a field of the alert",)

    assert f" ({rejection_reason_text(REASON_CALC_NOT_ALLOWED, ('x',), why)})" == (
        rejection_clause(REASON_CALC_NOT_ALLOWED, ("x",), why)
    )
    assert rejection_reason_text("", ("1", "2"), ()) == f"{NOT_FOUND}: 1, 2"


# --- REQ-AS-38: the sentences say what the guard does -------------------------------------------


def test_the_scope_note_names_the_two_cases_of_wording_it_judges() -> None:
    assert "does not judge wording, except" in NOTE_GUARD_SCOPE
    assert "a period that contradicts the field a figure matches" in NOTE_GUARD_SCOPE
    assert "the price index named as the cause" in NOTE_GUARD_SCOPE
    assert "does no arithmetic" in NOTE_GUARD_SCOPE
    assert "does not judge wording, except" in landing.MOMENT_NOTE
    assert "contradicted period" in landing.MOMENT_NOTE
    assert "price index named as the cause" in landing.MOMENT_NOTE


def test_the_accepted_verdict_separates_what_the_model_wrote_from_what_the_kit_computed() -> None:
    assert "Every figure the model wrote itself" in VERDICT_ACCEPTED
    assert "found in the cited rows or the alert data" in VERDICT_ACCEPTED
    assert "a figure in a calc placeholder was computed by the kit" in VERDICT_ACCEPTED


def test_the_promise_says_computed_by_plain_code_on_home_and_in_every_app() -> None:
    phrase = "comes from, or is computed by plain code from,"

    assert phrase in streamlit_app.PROMISE
    assert streamlit_app.PROMISE.endswith("rows you can check.")
    for prefix in PREFIXES:
        source = (ROOT / SCRIPTS[prefix]).read_text(encoding="utf-8")
        assert phrase in source, prefix
    kicker = (ROOT / "ledger_kit" / "ui" / "theme.py").read_text(encoding="utf-8")
    assert "computed by plain code" not in kicker  # the kicker is left as it was


def test_the_guard_sentences_of_the_docs_name_the_two_exceptions() -> None:
    docs = (ROOT / "docs" / "how-it-works.md").read_text(encoding="utf-8")

    assert "does not judge wording, except a period that contradicts the field" in docs
    assert "the price index named as the cause of a price change" in docs


# --- REQ-AS-39: only the CSV demo has recorded answers ------------------------------------------


def test_try_it_says_that_only_the_csv_demo_replays_recorded_answers() -> None:
    text = streamlit_app.TRY_IT

    assert "the CSV demo that loads first replays a recorded answer on every card" in text
    assert "the Real formats and Norma 43 demos have no recording" in text
    assert "the overdraft card in Vampire Fees" in text
    assert "99999.99" in text and "Simulate a hallucinating LLM" in text


def test_the_docs_and_the_readme_say_the_same() -> None:
    docs = (ROOT / "docs" / "how-it-works.md").read_text(encoding="utf-8")
    readme = Path(ROOT / "README.md").read_text(encoding="utf-8")

    assert "on the CSV demo that loads by itself" in docs
    assert "The Real formats and Norma 43 demos have no recording" in docs
    assert "the CSV demo that loads by itself" in readme
    assert "the Real formats and Norma 43 demos have no recording" in readme
