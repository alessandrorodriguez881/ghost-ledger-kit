"""Headless tests of the judge path on the real pages (REQ-JP-05 to REQ-JP-15, REQ-JP-18).

``AppTest`` runs the three apps and the showcase with no API key. The replay run of these tests is
a small file written to ``tmp_path`` with the real alert ids of the demos (``judge_path_support``):
for each app, alert 0 has an accepted card, a rejected probe ``forecast`` and an accepted probe
``next_month``, and alert 1 has a card the guard rejects. The root conftest switches the replay and
the auto-load off; the ``judge_path`` fixture below switches them on. Nothing reads the network or
the clock.
"""

import ast
import re
import sys
import types
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest
from judge_path_support import (
    FIXTURE_DATE,
    FIXTURE_MODEL_NAME,
    INVENTED,
    ROOT,
    SCRIPTS,
    accepted_text,
    cases_of,
    escape_for,
    rejected_text,
    template_of,
    write_run,
)
from streamlit.testing.v1 import AppTest

import streamlit_app
from apps.zombie_subscriptions import settings as zs_settings
from ledger_kit import replay
from ledger_kit.detectors import _restore_registry, _snapshot_registry
from ledger_kit.explainer import fill_fallback
from ledger_kit.live_guard import (
    CAPTION_OFF,
    MSG_LIMIT,
    TRICK_QUESTIONS,
    VERDICT_ACCEPTED,
    Counts,
)
from ledger_kit.ui import first_run

TIMEOUT_SECONDS = 120
ENTRY = str(ROOT / "streamlit_app.py")
PREFIXES = sorted(SCRIPTS)
LABELS = [q.label for q in TRICK_QUESTIONS]
RECORDED = f"Recorded answer of {FIXTURE_MODEL_NAME}, {FIXTURE_DATE}"
REPLAY_CAPTION_START = f"Replay of a recorded answer of {FIXTURE_MODEL_NAME}, {FIXTURE_DATE}."


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


@pytest.fixture
def judge_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Switch the replay (the test run file) and the auto-load on."""
    path = write_run(tmp_path / "run.json")
    monkeypatch.setattr(replay, "REPLAY_RUN_PATH", path)
    monkeypatch.setattr(first_run, "AUTOLOAD_DEMO", True)
    return path


def _open(prefix: str, preset: dict[str, object] | None = None) -> AppTest:
    """Run one app alone, optionally with session values preset before the first run."""
    at = AppTest.from_file(str(ROOT / SCRIPTS[prefix]), default_timeout=TIMEOUT_SECONDS)
    for key, value in (preset or {}).items():
        at.session_state[key] = value
    at.run()
    assert not at.exception
    return at


def _markdown(at: AppTest) -> list[str]:
    return [element.value for element in at.markdown]


def _texts(at: AppTest) -> list[str]:
    """Every text the panel and the cards write to."""
    elements = [*at.markdown, *at.caption, *at.warning, *at.info, *at.error, *at.success]
    return [element.value for element in elements]


def _badges(at: AppTest, prefix: str) -> list[str]:
    return [v for v in _markdown(at) if v.startswith(f'<span class="{prefix}-badge ')]


def _titles(at: AppTest, prefix: str) -> list[str]:
    return [v for v in _markdown(at) if v.startswith(f'<div class="{prefix}-alert-title">')]


def _ask(at: AppTest, prefix: str, index: int = 0):
    return at.button(key=f"{prefix}_lg_ask_{cases_of(prefix)[index].alert.id}")


def _question_radio(at: AppTest, prefix: str, index: int = 0):
    return at.radio(key=f"{prefix}_lg_q_{cases_of(prefix)[index].alert.id}")


def _install_plain_fake_openai(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Install a fake `openai` whose every answer is figure-free; return the requests it got."""
    calls: list[dict] = []

    class _Completions:
        def create(self, **kwargs):
            calls.append(kwargs)
            message = types.SimpleNamespace(content="Nothing here is a figure.")
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])

    class _Client:
        def __init__(self, **_kwargs):
            self.chat = types.SimpleNamespace(completions=_Completions())

    module = types.ModuleType("openai")
    module.OpenAI = _Client  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", module)
    return calls


# --- REQ-JP-11: the demo loads by itself ------------------------------------------------------


@pytest.mark.parametrize("prefix", PREFIXES)
def test_the_first_run_loads_the_csv_demo_by_itself(judge_path: Path, prefix: str) -> None:
    at = _open(prefix)

    assert at.session_state[f"{prefix}_autoloaded"] is True
    assert len(_titles(at, prefix)) == len(cases_of(prefix))
    assert not any("Load demo data" in info.value for info in at.info)
    assert at.button(key=f"{prefix}_load_demo").label == "Load demo data"  # the button stays


def test_the_zombie_inputs_are_filled_like_the_button_would_fill_them(judge_path: Path) -> None:
    at = _open("zs")

    assert at.text_area(key="cancel_text").value == "GYMPLUS = 2026-07-31"
    assert "BEATSTREAM = 2026-07-15" in at.text_area(key="last_used_text").value
    assert "streaming = " in at.text_area(key="aliases_text").value
    assert at.session_state["demo_loaded"] is True
    assert at.session_state["source"][2] == "zombie_demo_statement.csv"


def test_a_later_run_does_not_load_the_demo_again(judge_path: Path) -> None:
    at = _open("zs")

    at.text_area(key="cancel_text").input("GYMPLUS = 2026-08-31").run()

    assert not at.exception
    assert at.text_area(key="cancel_text").value == "GYMPLUS = 2026-08-31"


@pytest.mark.parametrize("prefix", PREFIXES)
def test_a_session_already_marked_shows_the_empty_page(judge_path: Path, prefix: str) -> None:
    at = _open(prefix, {f"{prefix}_autoloaded": True})

    assert any("Load demo data" in info.value for info in at.info)
    assert _titles(at, prefix) == []


def test_a_source_that_is_already_loaded_is_kept(judge_path: Path) -> None:
    config = zs_settings.load_config(ROOT / "apps" / "zombie_subscriptions" / "config.toml")
    demo = zs_settings.demo_inputs(config, ROOT, "real")
    preset = {"source": ("demo", demo.statement_bytes, demo.statement_name)}

    at = _open("zs", preset)

    assert at.session_state["source"][2] == "zombie_demo_statement.n43"
    assert at.session_state["zs_autoloaded"] is True


# --- REQ-JP-05 to REQ-JP-07, REQ-JP-18: the cards ----------------------------------------------


@pytest.mark.parametrize("prefix", PREFIXES)
def test_cards_show_recorded_answers_with_an_honest_badge(judge_path: Path, prefix: str) -> None:
    at = _open(prefix)
    first, second = cases_of(prefix)[:2]
    escape = escape_for(prefix)
    values = _markdown(at)
    badges = _badges(at, prefix)
    replayed = [b for b in badges if RECORDED in b]

    assert len(replayed) == 2
    assert sum(f"{prefix}-badge-llm" in b and "accepted" in b for b in replayed) == 1
    assert sum(f"{prefix}-badge-rejected" in b and INVENTED in b for b in replayed) == 1
    assert all("checked now by the number guard" in b and "No model called" in b for b in replayed)
    assert sum(f"{prefix}-badge-template" in b for b in badges) == len(badges) - 2
    assert not any("LLM text verified" in b or "LLM answer rejected" in b for b in badges)
    # the accepted recording is the card text; the rejected one gives way to the fixed template
    assert escape(accepted_text(first)) in values
    assert escape(rejected_text(second)) not in values
    assert escape(fill_fallback(template_of(second), second.alert)) in values
    assert not any(INVENTED in v for v in values if not v.startswith("<span"))


@pytest.mark.parametrize("prefix", PREFIXES)
def test_the_hallucination_switch_wins_over_the_replay(judge_path: Path, prefix: str) -> None:
    at = _open(prefix)

    at.toggle(key=f"{prefix}_hallucinate").set_value(True).run()

    assert not at.exception
    badges = _badges(at, prefix)
    assert badges and all(f"{prefix}-badge-rejected" in b and "99999.99" in b for b in badges)
    assert not any("Recorded answer" in b for b in badges)

    at.toggle(key=f"{prefix}_hallucinate").set_value(False).run()

    assert sum(RECORDED in b for b in _badges(at, prefix)) == 2


@pytest.mark.parametrize("prefix", PREFIXES)
def test_with_a_key_the_cards_and_the_panel_are_live_and_never_replay(
    judge_path: Path, monkeypatch: pytest.MonkeyPatch, prefix: str
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    calls = _install_plain_fake_openai(monkeypatch)

    at = _open(prefix)

    assert len(calls) == len(cases_of(prefix))  # one live call per card
    badges = _badges(at, prefix)
    assert all(f"{prefix}-badge-llm" in b and "LLM text verified" in b for b in badges)
    assert not any("Recorded answer" in b for b in badges)
    assert not any("Recorded answers of" in v for v in _texts(at))
    assert not _ask(at, prefix).disabled and not _question_radio(at, prefix).disabled
    assert _ask(at, prefix).label == "Ask the model"  # REQ-JP-20: with a key it is a real call
    assert not any(REPLAY_CAPTION_START in v for v in _texts(at))
    live_keys = {(case.alert.id, "real") for case in cases_of(prefix)}
    assert set(at.session_state[f"{prefix}_explanations"]) == live_keys


@pytest.mark.parametrize("prefix", PREFIXES)
def test_an_unusable_run_file_leaves_every_page_as_it_was(judge_path: Path, prefix: str) -> None:
    judge_path.write_text("not json", encoding="utf-8")

    at = _open(prefix)

    badges = _badges(at, prefix)
    assert badges and all(f"{prefix}-badge-template" in b for b in badges)
    assert not at.error
    assert all(b.disabled for b in at.button if (b.key or "").startswith(f"{prefix}_lg_ask_"))


# --- REQ-JP-08 to REQ-JP-10: the Provoke panel ------------------------------------------------


@pytest.mark.parametrize("prefix", PREFIXES)
def test_a_recorded_probe_is_replayed_with_the_marked_token_and_todays_verdict(
    judge_path: Path, prefix: str
) -> None:
    at = _open(prefix)
    assert not _question_radio(at, prefix).disabled
    assert not _ask(at, prefix).disabled
    assert _ask(at, prefix).label == "Replay the recorded answer"  # REQ-JP-20
    _ask(at, prefix).click().run()

    assert not at.exception
    texts = _texts(at)
    marks = [v for v in texts if "<mark" in v]
    assert len(marks) == 1 and f"{INVENTED}</mark>" in marks[0]
    verdicts = [v for v in texts if v.startswith("🛑 Guard verdict: rejected.")]
    assert len(verdicts) == 1 and f"`{INVENTED}`" in verdicts[0]
    captions = [c.value for c in at.caption]
    [caption] = [c for c in captions if c.startswith(REPLAY_CAPTION_START)]
    assert "No model is called" in caption
    assert any(f"Recorded answers of {FIXTURE_MODEL_NAME}" in c for c in captions)
    assert "Answers checked: 1 · rejected: 1" in "\n".join(texts)


@pytest.mark.parametrize("prefix", PREFIXES)
def test_each_recorded_question_replays_and_an_unrecorded_one_stays_off(
    judge_path: Path, prefix: str
) -> None:
    at = _open(prefix)
    _question_radio(at, prefix).set_value(LABELS[1]).run()

    _ask(at, prefix).click().run()

    assert VERDICT_ACCEPTED in _texts(at)
    assert "Answers checked: 1 · rejected: 0" in "\n".join(_texts(at))
    _question_radio(at, prefix).set_value(LABELS[2]).run()  # with_fees: nothing recorded
    assert _ask(at, prefix).disabled
    assert [c.value for c in at.caption].count(CAPTION_OFF) == len(cases_of(prefix))


@pytest.mark.parametrize("prefix", PREFIXES)
def test_an_alert_without_a_recorded_probe_keeps_todays_disabled_panel(
    judge_path: Path, prefix: str
) -> None:
    at = _open(prefix)
    other = cases_of(prefix)[1].alert.id

    assert at.button(key=f"{prefix}_lg_ask_{other}").disabled
    assert at.button(key=f"{prefix}_lg_ask_{other}").label == "Ask the model"  # nothing recorded
    assert at.radio(key=f"{prefix}_lg_q_{other}").disabled


@pytest.mark.parametrize("prefix", PREFIXES)
def test_a_replayed_press_counts_and_is_refused_at_the_session_limit(
    judge_path: Path, prefix: str
) -> None:
    at = _open(prefix, {f"{prefix}_lg_counts": Counts(30, 0, 0)})

    assert _ask(at, prefix).disabled
    assert [c.value for c in at.caption].count(MSG_LIMIT) == 1

    at = _open(prefix)
    _ask(at, prefix).click().run()
    assert at.session_state[f"{prefix}_lg_counts"] == Counts(1, 1, 1)


@pytest.mark.parametrize("prefix", PREFIXES)
def test_no_model_and_no_network_are_used_by_a_replay(
    judge_path: Path, monkeypatch: pytest.MonkeyPatch, prefix: str
) -> None:
    monkeypatch.setitem(sys.modules, "openai", None)  # importing the SDK would fail
    opened: list[object] = []

    def _no_network(*args: object, **kwargs: object) -> None:
        opened.append(args)
        raise AssertionError("the replay must not open a connection")

    monkeypatch.setattr(urllib.request, "urlopen", _no_network)
    requests: list[dict] = []
    original = replay.ReplayClient.create

    def _counting(self: replay.ReplayClient, **kwargs: object):
        requests.append(kwargs)
        return original(self, **kwargs)

    monkeypatch.setattr(replay.ReplayClient, "create", _counting)

    at = _open(prefix)
    cards = len(requests)
    _ask(at, prefix).click().run()

    assert not at.exception
    assert cards == 2  # the two recorded cards
    assert len(requests) == cards + 1
    asked = [r for r in requests if "Question from the user:" in r["messages"][1]["content"]]
    assert len(asked) == 1
    assert opened == []


# --- REQ-JP-12: Advanced inputs ------------------------------------------------------------------


@pytest.mark.parametrize("prefix", PREFIXES)
def test_developer_inputs_sit_in_one_sidebar_expander(prefix: str) -> None:
    at = _open(prefix)

    [inside] = [e for e in at.sidebar.expander if e.label == "Advanced inputs"]

    if prefix == "zs":
        keys = {w.key for w in inside.text_area}
        assert keys == {"aliases_text", "last_used_text", "cancel_text"}
        assert {w.key for w in at.sidebar.text_area} == keys
    elif prefix == "pi":
        assert {w.key for w in inside.checkbox} == {"use_as_of"}
        assert {w.key for w in inside.date_input} == {"as_of_date"}
    else:
        assert any("comision" in m.value for m in inside.markdown)
    # the demo-format radio, the button, the switch and the uploader stay outside
    assert len(inside.radio) == len(inside.button) == len(inside.toggle) == 0
    assert at.radio(key=f"{prefix}_demo_format") is not None
    assert at.button(key=f"{prefix}_load_demo").label == "Load demo data"
    assert at.toggle(key=f"{prefix}_hallucinate").value is False


@pytest.mark.parametrize("prefix", PREFIXES)
def test_the_advanced_inputs_expander_starts_collapsed(prefix: str) -> None:
    app = (ROOT / SCRIPTS[prefix]).read_text(encoding="utf-8")
    calls = [
        node
        for node in ast.walk(ast.parse(app))
        if isinstance(node, ast.Call)
        and ast.unparse(node.func).endswith("expander")
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "Advanced inputs"
    ]

    [call] = calls
    assert {kw.arg: ast.literal_eval(kw.value) for kw in call.keywords} == {"expanded": False}


# --- REQ-JP-14, REQ-JP-15: Home -------------------------------------------------------------------


def _main_items(at: AppTest) -> list[tuple[str, str]]:
    """The elements of the page body, in order, as (type, value)."""
    children = sorted(at.main.children.items())
    return [(child.type, str(getattr(child, "value", ""))) for _index, child in children]


def _first(items: list[tuple[str, str]], kind: str, start: str = "") -> int:
    """Index of the first item of this type whose value starts with `start`."""
    return next(i for i, (t, v) in enumerate(items) if t == kind and v.startswith(start))


def _home_order(at: AppTest) -> dict[str, int]:
    items = _main_items(at)
    link = next(
        i
        for i, (t, v) in enumerate(items)
        if t == "page_link" or v == streamlit_app.START_HERE_FALLBACK
    )
    return {
        "title": _first(items, "title"),
        "promise": _first(items, "markdown", '<div class="gl-promise">'),
        "story": _first(items, "markdown", '<div class="gl-story">'),
        "link": link,
        "proof": _first(items, "markdown", '<div class="gl-grid gl-proof">'),
    }


def test_home_starts_with_the_story_then_the_recorded_example_then_the_link(
    judge_path: Path,
) -> None:
    at = AppTest.from_file(ENTRY, default_timeout=TIMEOUT_SECONDS).run()

    assert not at.exception
    order = _home_order(at)
    items = _main_items(at)
    order["example"] = _first(items, "markdown", '<div class="gl-example">')
    assert (
        order["title"]
        < order["promise"]
        < order["story"]
        < order["example"]
        < order["link"]
        < order["proof"]
    )
    [story] = [v for t, v in items if v.startswith('<div class="gl-story">')]
    assert story.count("<p>") == len(streamlit_app.STORY) == 3
    assert all(line in story for line in streamlit_app.STORY)
    [example] = [v for t, v in items if v.startswith('<div class="gl-example">')]
    assert f"One recorded answer of {FIXTURE_MODEL_NAME}, {FIXTURE_DATE}." in example
    assert f"Question: {TRICK_QUESTIONS[0].text}" in example  # the first rejected probe
    assert "You asked" not in example
    assert f"{INVENTED}</mark>" in example  # the invented token is marked in its sentence
    assert "Over five years: <mark" in example and "<b>rejected</b>" in example


def test_home_without_a_run_file_keeps_the_story_and_drops_the_example() -> None:
    at = AppTest.from_file(ENTRY, default_timeout=TIMEOUT_SECONDS).run()

    assert not at.exception
    items = _main_items(at)
    assert not any(v.startswith('<div class="gl-example">') for _t, v in items)
    order = _home_order(at)
    assert order["title"] < order["promise"] < order["story"] < order["link"] < order["proof"]


def test_the_proof_strip_shows_percentages_with_one_decimal() -> None:
    at = AppTest.from_file(ENTRY, default_timeout=TIMEOUT_SECONDS).run()

    [strip] = [v for v in _markdown(at) if v.startswith('<div class="gl-grid gl-proof">')]
    figures = re.findall(r'<div class="gl-figure">([^<]*)</div>', strip)

    for figure in figures[:2]:
        assert re.fullmatch(r"\d{1,3}\.\d %", figure), figure
    assert "0.9980" not in strip and "1.0000" not in strip
    assert re.search(r"Recall \d{1,3}\.\d % on 200", strip)


def test_the_start_here_link_names_zombie_subscriptions() -> None:
    at = AppTest.from_file(ENTRY, default_timeout=TIMEOUT_SECONDS).run()

    items = _main_items(at)
    [link] = [(t, v) for t, v in items if t == "page_link" or "Start here" in v]
    assert streamlit_app.START_HERE.endswith("Zombie Subscriptions")
    assert link[0] == "page_link" or link[1] == streamlit_app.START_HERE_FALLBACK


def test_the_start_here_link_has_the_tombstone_icon_and_body_text_size() -> None:
    from ledger_kit.ui import theme

    assert streamlit_app.START_HERE_ICON == "🪦"  # REQ-JP-23
    css = theme.theme_css(theme.KIT)
    rule = css[css.index('[data-testid="stPageLink-NavLink"] p') :]
    assert "font-size: 1rem" in rule.split("}")[0]
    assert "text-decoration: underline" in rule.split("}")[0]
