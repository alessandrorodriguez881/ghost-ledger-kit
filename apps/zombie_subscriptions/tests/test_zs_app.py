"""Headless tests of the zombie-subscriptions Streamlit app with AppTest (Task Z21)."""

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import apps.zombie_subscriptions.detectors  # noqa: F401  (registers the zs.* detectors)
from ledger_kit.detectors import _restore_registry, _snapshot_registry, registered_names

APP_PATH = str(Path(__file__).resolve().parents[1] / "app.py")
TIMEOUT_SECONDS = 60

ZS_DETECTORS = {
    "zs.recurring_charge",
    "zs.price_increase",
    "zs.duplicate_subscription",
    "zs.free_trial_to_paid",
    "zs.charges_after_cancellation",
}

# Cost since the last-used date of the three demo tombstones (see test_zs_demo_e2e.py).
DEMO_TOMBSTONE_COSTS = {
    "BEATSTREAM": "29,97 EUR",
    "PHOTOBOX": "19,96 EUR",
    "STASHCRATE": "8,97 EUR",
}

YEARLY_COST_RE = re.compile(r'Yearly cost: <b class="zs-amber">([^<]+)</b>')


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Snapshot and restore the global detector registry; the zs detectors must stay in it."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)  # the app must use the template path
    assert ZS_DETECTORS <= set(registered_names("zs"))
    snapshot = _snapshot_registry()
    try:
        yield
    finally:
        _restore_registry(snapshot)


def _run() -> AppTest:
    """Run the app headless."""
    return AppTest.from_file(APP_PATH, default_timeout=TIMEOUT_SECONDS).run()


def _demo() -> AppTest:
    """Run the app and click Load demo data."""
    at = _run()
    at.button(key="load_demo").click().run()
    return at


def _markdown(at: AppTest) -> list[str]:
    """Every markdown value of the page."""
    return [element.value for element in at.markdown]


def _tombstones(at: AppTest) -> list[str]:
    """The HTML of every tombstone card."""
    return [value for value in _markdown(at) if value.startswith('<div class="zs-tombstone">')]


def _alert_titles(at: AppTest) -> list[str]:
    """The HTML of every alert title."""
    return [value for value in _markdown(at) if value.startswith('<div class="zs-alert-title">')]


def _badges(at: AppTest) -> list[str]:
    """The HTML of every guard badge."""
    return [value for value in _markdown(at) if value.startswith('<span class="zs-badge ')]


def test_app_starts_without_exception() -> None:
    """With no data the page shows the title, the hint, the demo button and no tombstone."""
    at = _run()

    assert not at.exception
    assert at.title[0].value == "🪦 Zombie Subscriptions"
    assert any("Load demo data" in info.value for info in at.info)
    assert at.button(key="load_demo").label == "Load demo data"
    assert at.toggle(key="hallucinate").value is False
    assert _tombstones(at) == []
    assert _alert_titles(at) == []


def test_app_has_the_graveyard_theme() -> None:
    """The dark background and the tombstone class are injected as CSS."""
    css = [value for value in _markdown(_run()) if value.lstrip().startswith("<style>")]

    assert len(css) == 1
    assert "#1a1a2e" in css[0]
    assert ".zs-tombstone" in css[0]


def test_load_demo_data_shows_tombstones_and_alerts() -> None:
    """Clicking Load demo data fills the inputs and renders the demo's tombstones and alerts."""
    at = _demo()

    assert not at.exception
    assert at.session_state["demo_loaded"] is True
    assert at.text_area(key="cancel_text").value == "GYMPLUS = 2026-07-31"
    assert "BEATSTREAM = 2026-07-15" in at.text_area(key="last_used_text").value
    assert "streaming = " in at.text_area(key="aliases_text").value

    tombstones = _tombstones(at)
    assert len(tombstones) == len(DEMO_TOMBSTONE_COSTS)
    for name, cost in DEMO_TOMBSTONE_COSTS.items():
        [card] = [t for t in tombstones if f'<div class="zs-name">{name}</div>' in t]
        assert "Died on:" in card and "Cost since then:" in card
        assert f'<b class="zs-amber">{cost}</b>' in card
        [yearly] = YEARLY_COST_RE.findall(card)
        assert yearly.endswith(" EUR") and yearly != "0,00 EUR"

    captions = " ".join(element.value for element in at.caption)
    for detector in ZS_DETECTORS:
        assert f"`{detector}`" in captions
    assert len(_alert_titles(at)) >= len(ZS_DETECTORS)
    assert len(_badges(at)) == len(_alert_titles(at))
    assert all("zs-badge-template" in badge for badge in _badges(at))
    assert not at.sidebar.error


def test_demo_alerts_show_source_refs_and_european_amounts() -> None:
    """Every alert lists its source refs; amounts in the explanations are European."""
    at = _demo()

    markdown = _markdown(at)
    refs_lines = [v for v in markdown if v.startswith("**Source refs:**")]
    assert len(refs_lines) == len(_alert_titles(at))
    assert any("zombie_demo_statement.csv:" in v for v in markdown)
    assert any("36,00 EUR" in v for v in markdown)  # price increase: extra cost per year


def test_hallucination_toggle_produces_fallback_with_guard_badge() -> None:
    """The stub LLM invents 99999.99: every explanation falls back and carries the badge."""
    at = _demo()

    at.toggle(key="hallucinate").set_value(True).run()

    assert not at.exception
    badges = _badges(at)
    assert len(badges) == len(_alert_titles(at)) >= len(ZS_DETECTORS)
    for badge in badges:
        assert "zs-badge-rejected" in badge
        assert "⚠️ LLM answer rejected: invented number 99999.99" in badge
    explanations = [v for v in _markdown(at) if not v.startswith(("<span", "<div", "<style"))]
    assert not any("99999.99" in value for value in explanations)
    assert any("36,00 EUR" in value for value in explanations)  # the filled fallback template

    at.toggle(key="hallucinate").set_value(False).run()

    assert not at.exception
    assert all("zs-badge-template" in badge for badge in _badges(at))


def test_bad_date_input_is_reported_not_raised() -> None:
    """A malformed date line shows a sidebar error and the page still renders."""
    at = _demo()

    at.text_area(key="cancel_text").input("GYMPLUS = not-a-date").run()

    assert not at.exception
    assert any("Cancellation dates" in error.value for error in at.sidebar.error)
    assert len(_tombstones(at)) == len(DEMO_TOMBSTONE_COSTS)


def test_zs_detectors_stay_registered_after_the_app_ran() -> None:
    """Running the app neither drops nor duplicates the zs detectors in the registry."""
    _demo()

    names = registered_names("zs")
    assert set(names) == ZS_DETECTORS
    assert len(names) == len(ZS_DETECTORS)
