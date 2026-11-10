"""Headless tests of the Provoke-the-LLM panel of vampire_fees (live-guard LG4).

A fake `openai` module stands in for the model; no network, no real key (REQ-LG-20).
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import apps.vampire_fees.detectors  # noqa: F401  (registers the vf.* detectors)
from apps.vampire_fees.tests import vf_live_fakes as fakes
from ledger_kit.detectors import _restore_registry, _snapshot_registry
from ledger_kit.live_guard import (
    CAPTION_OFF,
    CAPTION_URL_WITHOUT_KEY,
    MSG_LIMIT,
    MSG_NO_ANSWER,
    NOTE_GUARD_SCOPE,
    TRICK_QUESTIONS,
    VERDICT_ACCEPTED,
    Counts,
)

ROOT = Path(__file__).resolve().parents[3]
APP_PATH = str(ROOT / "apps" / "vampire_fees" / "app.py")
DEMO_CSV = ROOT / "data" / "samples" / "vampire_demo_statement.csv"
TIMEOUT_SECONDS = 60
PREFIX = "vf"
KEY = "test-key-not-real"
BASE_URL = "http://base.invalid/v1"
ENV_NAMES = (
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "LEDGER_KIT_LLM_MODEL",
    "LEDGER_KIT_LLM_TIMEOUT",
)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """No provider variable leaks in; the global detector registry is restored afterwards."""
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    snapshot = _snapshot_registry()
    try:
        yield
    finally:
        _restore_registry(snapshot)


def _live(monkeypatch: pytest.MonkeyPatch, scenario: str = "faithful") -> fakes.FakeOpenAI:
    """Turn the live model on with a dummy key and install the fake `openai`."""
    monkeypatch.setenv("OPENAI_API_KEY", KEY)
    return fakes.install(monkeypatch, scenario)


def _demo(preset: dict[str, object] | None = None) -> AppTest:
    """Start the app (optionally with session values preset) and click Load demo data."""
    assert DEMO_CSV.is_file(), "run `python scripts/generate_samples.py --mode vampire-demo`"
    at = AppTest.from_file(APP_PATH, default_timeout=TIMEOUT_SECONDS)
    for key, value in (preset or {}).items():
        at.session_state[key] = value
    at.run()
    at.button(key=f"{PREFIX}_load_demo").click().run()
    assert not at.exception
    return at


def _texts(at: AppTest) -> list[str]:
    """Every text value of the page body that the panel can write to."""
    elements = [*at.markdown, *at.caption, *at.warning, *at.info, *at.error, *at.success]
    return [element.value for element in elements]


def _page(at: AppTest) -> str:
    """The text of the whole page, joined."""
    return "\n".join(_texts(at))


def _badges(at: AppTest) -> list[str]:
    """The HTML of every guard badge."""
    return [m.value for m in at.markdown if m.value.startswith('<span class="vf-badge ')]


def _ask_buttons(at: AppTest) -> list:
    """The Ask buttons, one per alert card."""
    return [b for b in at.button if (b.key or "").startswith(f"{PREFIX}_lg_ask_")]


def _radios(at: AppTest) -> list:
    """The trick-question radios, one per alert card."""
    return [r for r in at.radio if (r.key or "").startswith(f"{PREFIX}_lg_q_")]


def _press(at: AppTest, index: int = 0) -> AppTest:
    """Press the Ask button of the card at `index`."""
    _ask_buttons(at)[index].click().run()
    assert not at.exception
    return at


# --- Case 1: structure ---------------------------------------------------------------------


def test_every_card_has_one_panel_with_three_questions(monkeypatch: pytest.MonkeyPatch) -> None:
    _live(monkeypatch)
    at = _demo()
    cards = len(_ask_buttons(at))

    assert cards >= 3
    assert [e.label for e in at.expander].count("🔦 Provoke the LLM") == cards
    assert len(_radios(at)) == cards
    labels = [q.label for q in TRICK_QUESTIONS]
    for radio in _radios(at):
        assert list(radio.options) == labels
        assert radio.value == labels[0]
    assert all(b.label == "Ask the model" for b in _ask_buttons(at))
    assert not [t for t in at.text_input if "_lg_" in (t.key or "")]
    assert not [t for t in at.text_area if "_lg_" in (t.key or "")]


# --- Case 2: an invented figure is caught --------------------------------------------------


def test_invented_figure_is_marked_and_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    assert fakes.INVENTED not in DEMO_CSV.read_text(encoding="utf-8")
    state = _live(monkeypatch, "invent")
    at = _demo()
    assert fakes.INVENTED not in _page(at)
    card_system = {fakes.system_message(c) for c in state.card_calls}

    _press(at)

    [call] = state.question_calls
    question = TRICK_QUESTIONS[0].text
    assert fakes.user_message(call).endswith(fakes.QUESTION_SEPARATOR + question)
    assert fakes.system_message(call) in card_system
    marks = [v for v in _texts(at) if "<mark" in v]
    assert len(marks) == 1 and f"{fakes.INVENTED}</mark>" in marks[0]
    assert any(
        v.startswith("🛑 Guard verdict: rejected.") and f"`{fakes.INVENTED}`" in v
        for v in _texts(at)
    )
    assert "Answers checked: 1 · rejected: 1" in _page(at)
    assert NOTE_GUARD_SCOPE in _page(at)
    assert "Fixed template shown on the card when the answer is not trusted:" in _page(at)


# --- Case 3: a faithful answer is accepted ------------------------------------------------


def test_faithful_answer_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _live(monkeypatch, "faithful")
    at = _demo()

    _press(at)

    assert len(state.question_calls) == 1
    assert VERDICT_ACCEPTED in _page(at)
    assert not [v for v in _texts(at) if "<mark" in v]
    assert "Answers checked: 1 · rejected: 0" in _page(at)


# --- Case 4: the model fails ---------------------------------------------------------------


def test_failed_call_shows_the_fixed_message_and_leaks_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _live(monkeypatch, "raise")
    at = _demo()
    badges_before = _badges(at)
    refs_before = [m.value for m in at.markdown if m.value.startswith("**Source refs:**")]

    _press(at)

    assert len(state.question_calls) == 1
    page = _page(at)
    assert MSG_NO_ANSWER in page
    assert "localhost" not in page
    assert "Answers checked: 0 · rejected: 0" in page
    assert _badges(at) == badges_before
    assert [m.value for m in at.markdown if m.value.startswith("**Source refs:**")] == refs_before
    assert fakes.CARD_SENTENCE in page


def test_timeout_setting_shows_in_the_no_answer_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", KEY)
    monkeypatch.setenv("LEDGER_KIT_LLM_TIMEOUT", "45")
    state = fakes.install(monkeypatch, "raise")
    at = _demo()

    _press(at)

    assert "no reply within 45 seconds" in _page(at)
    assert {k["timeout"] for k in state.init_kwargs} == {45}


# --- Case 5: reruns do not call the model --------------------------------------------------


def test_a_rerun_does_not_ask_again(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _live(monkeypatch, "invent")
    at = _demo()
    _press(at)

    radio = at.radio(key=f"{PREFIX}_demo_format")
    radio.set_value(radio.options[1]).run()
    assert not at.exception
    at.run()

    assert len(state.question_calls) == 1
    assert any(f"{fakes.INVENTED}</mark>" in v for v in _texts(at))


# --- Case 6: disabled ---------------------------------------------------------------------


def test_panel_is_disabled_without_key_or_url() -> None:
    at = _demo()
    cards = len(_ask_buttons(at))

    assert cards >= 3
    assert all(b.disabled for b in _ask_buttons(at))
    assert all(r.disabled for r in _radios(at))
    assert [c.value for c in at.caption].count(CAPTION_OFF) == cards
    assert "Answers checked: 0 · rejected: 0" in _page(at)


def test_url_without_key_gets_its_own_caption(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_BASE_URL", BASE_URL)
    at = _demo()
    cards = len(_ask_buttons(at))

    assert all(b.disabled for b in _ask_buttons(at))
    assert [c.value for c in at.caption].count(CAPTION_URL_WITHOUT_KEY) == cards
    assert CAPTION_OFF not in _page(at)
    assert BASE_URL not in _page(at)


def test_simulated_hallucination_still_works_when_the_panel_is_off() -> None:
    at = _demo()
    at.toggle(key=f"{PREFIX}_hallucinate").set_value(True).run()

    assert not at.exception
    assert "99999.99" in _page(at)
    assert all(b.disabled for b in _ask_buttons(at))


# --- Case 7: isolation and secrets --------------------------------------------------------


def test_probe_ignores_the_hallucinate_switch_and_leaves_the_cache_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_BASE_URL", BASE_URL)
    state = _live(monkeypatch, "faithful")
    at = _demo()
    at.toggle(key=f"{PREFIX}_hallucinate").set_value(True).run()
    keys_before = set(at.session_state[f"{PREFIX}_explanations"])
    badges_before = _badges(at)

    _press(at)

    assert len(state.question_calls) == 1
    assert set(at.session_state[f"{PREFIX}_explanations"]) == keys_before
    assert _badges(at) == badges_before
    assert VERDICT_ACCEPTED in _page(at)


def test_key_and_base_url_never_reach_the_page_or_the_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_BASE_URL", BASE_URL)
    state = _live(monkeypatch, "invent")
    at = _demo()

    _press(at)

    secrets = (KEY, BASE_URL, "base.invalid")
    page = _page(at) + str(dict(at.session_state.items()))
    assert not any(secret in page for secret in secrets)
    assert not any(secret in str(e.label) for e in at.expander for secret in secrets)
    assert state.init_kwargs
    for kwargs in state.init_kwargs:
        assert kwargs["base_url"] == BASE_URL
        assert kwargs["timeout"] == 10
        assert kwargs["max_retries"] == 0
        assert kwargs["api_key"] == KEY


def test_the_probe_sends_only_whitelisted_columns(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _live(monkeypatch)
    at = _demo()

    _press(at)

    [call] = state.question_calls
    rows_part = fakes.user_message(call).split("Source rows:\n", 1)[1]
    for hidden in ('"description"', '"iban"', '"id"'):
        assert hidden not in rows_part


# --- Case 8: the courtesy limit -------------------------------------------------------------


def test_limit_disables_the_button(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _live(monkeypatch)
    at = _demo({f"{PREFIX}_lg_counts": Counts(30, 0, 0)})

    assert all(b.disabled for b in _ask_buttons(at))
    assert [c.value for c in at.caption].count(MSG_LIMIT) == len(_ask_buttons(at))
    assert state.question_calls == []


def test_counter_is_the_same_in_every_card(monkeypatch: pytest.MonkeyPatch) -> None:
    _live(monkeypatch, "invent")
    at = _demo()
    cards = len(_ask_buttons(at))

    _press(at, 0)
    _press(at, 1)

    counters = [c.value for c in at.caption if c.value.startswith("Answers checked:")]
    assert counters == ["Answers checked: 2 · rejected: 2"] * cards
