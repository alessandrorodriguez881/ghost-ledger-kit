"""Headless tests of the showcase entry page streamlit_app.py (REQ-SC-01 to REQ-SC-05).

``AppTest`` runs the real entry script, ``st.navigation`` and the unchanged app pages. Nothing
reads the system clock or the network; the demo files are the committed synthetic ones.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import apps.phantom_invoices.detectors  # noqa: F401  (registers the pi.* detectors)
import apps.zombie_subscriptions.detectors  # noqa: F401  (registers the zs.* detectors)
import streamlit_app
from ledger_kit.detectors import _restore_registry, _snapshot_registry, registered_names

REPO_ROOT = Path(__file__).resolve().parents[1]
ENTRY = str(REPO_ROOT / "streamlit_app.py")
ZOMBIE_PAGE = "apps/zombie_subscriptions/app.py"
PHANTOM_PAGE = "apps/phantom_invoices/app.py"
TIMEOUT_SECONDS = 60

PAGE_TITLES = ["Home", "Zombie Subscriptions", "Phantom Invoices"]
ZS_DETECTORS = 5  # zs.* detectors; the demo statement raises at least one alert for each
ZS_DEMO_TOMBSTONES = 3
PI_DEMO_CRITICAL, PI_DEMO_WARNING = 3, 6
PI_DEMO_ALERTS = PI_DEMO_CRITICAL + PI_DEMO_WARNING


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Snapshot and restore the global detector registry; both apps must stay registered."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)  # the apps must use the template path
    assert registered_names("zs") and registered_names("pi")
    snapshot = _snapshot_registry()
    try:
        yield
    finally:
        _restore_registry(snapshot)


def _run(path: str = ENTRY) -> AppTest:
    """Run a script headless."""
    return AppTest.from_file(path, default_timeout=TIMEOUT_SECONDS).run()


def _markdown(at: AppTest) -> list[str]:
    """Every markdown value of the page."""
    return [element.value for element in at.markdown]


def _starting(at: AppTest, prefix: str) -> list[str]:
    """The markdown values that start with `prefix` (HTML cards of the apps)."""
    return [value for value in _markdown(at) if value.startswith(prefix)]


def _zombie(at: AppTest) -> AppTest:
    """Open the Zombie Subscriptions page of the showcase."""
    at.switch_page(ZOMBIE_PAGE).run()
    assert not at.exception
    return at


def _phantom(at: AppTest) -> AppTest:
    """Open the Phantom Invoices page of the showcase."""
    at.switch_page(PHANTOM_PAGE).run()
    assert not at.exception
    return at


def _zombie_demo(at: AppTest) -> AppTest:
    """Click Load demo data on the zombie page."""
    at.button(key="zs_load_demo").click().run()
    assert not at.exception
    return at


def _phantom_demo(at: AppTest) -> AppTest:
    """Click Load demo data on the phantom page."""
    at.button(key="pi_load_demo").click().run()
    assert not at.exception
    return at


# --- the entry page and its three pages -------------------------------------------------------


def test_entry_page_starts_without_exception() -> None:
    """The entry script, st.navigation and the Home page run without an exception."""
    at = _run()

    assert not at.exception
    assert at.title[0].value == "👻 Ghost Ledger Kit"
    assert not at.error


def test_there_are_exactly_three_pages_in_order() -> None:
    """Home, Zombie Subscriptions and Phantom Invoices, Home first and the only default."""
    pages = streamlit_app.PAGES

    assert [page.title for page in pages] == PAGE_TITLES
    assert [page.script for page in pages] == [None, ZOMBIE_PAGE, PHANTOM_PAGE]
    assert len({page.url_path for page in pages}) == 3  # both app files are named app.py
    assert all(page.url_path and "/" not in page.url_path for page in pages)
    assert all(page.icon for page in pages)
    for page in pages[1:]:
        assert (REPO_ROOT / page.script).is_file()


def test_both_app_pages_are_registered_in_the_navigation() -> None:
    """switch_page only accepts files that st.navigation registered."""
    at = _run()

    _zombie(at)
    assert at.title[0].value == "🪦 Zombie Subscriptions"
    _phantom(at)
    assert at.title[0].value == "👻 Phantom Invoices"


def _home_text(at: AppTest) -> str:
    """Every text value of the Home page body (markdown, info boxes and captions)."""
    values = [*_markdown(at), *(i.value for i in at.info), *(c.value for c in at.caption)]
    return " ".join(values)


def test_home_explains_the_kit() -> None:
    """Home says what the kit guarantees, shows the hallucination idea and names both apps."""
    text = _home_text(_run())

    assert "deterministic" in text.lower()
    assert "source row" in text
    assert "only words the explanation" in text
    assert "number guard" in text
    assert "Simulate a hallucinating LLM" in text
    assert "99999.99" in text
    assert "Zombie Subscriptions" in text and "Phantom Invoices" in text
    assert "synthetic" in text
    assert len(text.split()) < 400  # a few lines, not a manual


def test_home_has_no_real_looking_data() -> None:
    """Home quotes no IBAN and no e-mail address."""
    text = _home_text(_run())

    assert "ES88" not in text and "@" not in text


# --- the app pages load their demo data -------------------------------------------------------


def test_zombie_page_loads_its_demo_data_and_shows_alerts() -> None:
    """The unchanged zombie app runs under navigation: tombstones, alerts and source refs."""
    at = _zombie_demo(_zombie(_run()))

    assert not at.sidebar.error
    assert len(_starting(at, '<div class="zs-tombstone">')) == ZS_DEMO_TOMBSTONES
    titles = _starting(at, '<div class="zs-alert-title">')
    assert len(titles) >= ZS_DETECTORS
    assert len(_starting(at, "**Source refs:**")) == len(titles)
    assert all("zs-badge-template" in b for b in _starting(at, '<span class="zs-badge '))


def test_phantom_page_loads_its_demo_data_and_shows_alerts() -> None:
    """The unchanged phantom app runs under navigation: 3 critical and 6 warning alerts."""
    at = _phantom_demo(_phantom(_run()))

    assert not at.sidebar.error
    assert {m.label.split()[-1]: m.value for m in at.metric} == {
        "critical": str(PI_DEMO_CRITICAL),
        "warning": str(PI_DEMO_WARNING),
    }
    titles = _starting(at, '<div class="pi-alert-title">')
    assert len(titles) == PI_DEMO_ALERTS
    assert len(_starting(at, "**Source refs:**")) == len(titles)
    assert len(_starting(at, '<span class="pi-badge ')) == len(titles)


def test_hallucination_toggle_works_inside_the_showcase() -> None:
    """The number guard rejects the stub's 99999.99 on both app pages."""
    at = _zombie_demo(_zombie(_run()))
    at.toggle(key="zs_hallucinate").set_value(True).run()
    assert not at.exception
    badges = _starting(at, '<span class="zs-badge ')
    assert badges and all("zs-badge-rejected" in b and "99999.99" in b for b in badges)

    at = _phantom_demo(_phantom(_run()))
    at.toggle(key="pi_hallucinate").set_value(True).run()
    assert not at.exception
    badges = _starting(at, '<span class="pi-badge ')
    assert badges and all("pi-badge-rejected" in b and "99999.99" in b for b in badges)


# --- keys and state ---------------------------------------------------------------------------


def test_the_two_apps_share_no_session_state_or_widget_key() -> None:
    """Run alone, the apps leave disjoint key sets in st.session_state (REQ-SC-04)."""
    zombie = _zombie_demo(_run(str(REPO_ROOT / ZOMBIE_PAGE)))
    phantom = _phantom_demo(_run(str(REPO_ROOT / PHANTOM_PAGE)))

    zombie_keys = set(zombie.session_state.keys())
    phantom_keys = set(phantom.session_state.keys())

    assert {"zs_load_demo", "zs_hallucinate", "zs_explanations"} <= zombie_keys
    assert {"pi_load_demo", "pi_hallucinate", "pi_explanations"} <= phantom_keys
    assert zombie_keys.isdisjoint(phantom_keys), zombie_keys & phantom_keys


def test_each_app_keeps_its_state_when_the_user_visits_the_other_page() -> None:
    """Demo data and sidebar values survive a round trip; the toggles stay independent."""
    at = _zombie_demo(_zombie(_run()))
    at.toggle(key="zs_hallucinate").set_value(True).run()

    _phantom(at)
    assert at.toggle(key="pi_hallucinate").value is False  # not the zombie toggle
    _phantom_demo(at)
    assert len(_starting(at, '<div class="pi-alert-title">')) == PI_DEMO_ALERTS

    _zombie(at)
    assert at.toggle(key="zs_hallucinate").value is True
    assert at.text_area(key="cancel_text").value == "GYMPLUS = 2026-07-31"
    assert "BEATSTREAM = 2026-07-15" in at.text_area(key="last_used_text").value
    assert len(_starting(at, '<div class="zs-tombstone">')) == ZS_DEMO_TOMBSTONES
    assert all("zs-badge-rejected" in b for b in _starting(at, '<span class="zs-badge '))

    _phantom(at)
    assert len(_starting(at, '<div class="pi-alert-title">')) == PI_DEMO_ALERTS
    assert at.toggle(key="pi_hallucinate").value is False
    assert all("pi-badge-template" in b for b in _starting(at, '<span class="pi-badge '))


def test_registries_are_untouched_by_a_showcase_session() -> None:
    """Visiting both pages neither drops nor duplicates a detector."""
    before = (sorted(registered_names("zs")), sorted(registered_names("pi")))

    at = _zombie_demo(_zombie(_run()))
    _phantom_demo(_phantom(at))

    assert (sorted(registered_names("zs")), sorted(registered_names("pi"))) == before
