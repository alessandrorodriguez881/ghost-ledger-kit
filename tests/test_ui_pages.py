"""Headless tests of every page of the showcase with the haunted look (haunted-design).

``AppTest`` runs the real scripts: the entry page with ``st.navigation``, the three apps alone and
the Benchmark page. They check that nothing raises, that each app wears its own accent, that the
Home proof strip shows the numbers of the committed files and that the demo numbers on the Home
tiles are the ones the apps really show. Nothing reads the clock or the network.
"""

import html
import json
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import apps.phantom_invoices.detectors  # noqa: F401  (registers the pi.* detectors)
import apps.vampire_fees.detectors  # noqa: F401  (registers the vf.* detectors)
import apps.zombie_subscriptions.detectors  # noqa: F401  (registers the zs.* detectors)
import streamlit_app
from ledger_kit.detectors import _restore_registry, _snapshot_registry
from ledger_kit.ui.icons import ICON_NAMES
from ledger_kit.ui.landing import TILES, percent_text
from ledger_kit.ui.theme import KIT, PHANTOM, VAMPIRE, ZOMBIE, Accent

REPO_ROOT = Path(__file__).resolve().parents[1]
ENTRY = str(REPO_ROOT / "streamlit_app.py")
TIMEOUT_SECONDS = 60
BENCHMARK_SCRIPT = "import streamlit_app\nstreamlit_app.benchmark()"
EMOJI = re.compile("[\U0001f000-\U0001faff\u2600-\u27bf\u2b00-\u2bff]")
FIGURE = re.compile(r'<div class="gl-figure">([^<]*)</div>')
HEADING_PREFIXES = ('<div class="gl-mast">', '<div class="gl-section"', '<div class="gl-sub"')

# (accent, script, load-demo button key)
APPS = (
    (ZOMBIE, "apps/zombie_subscriptions/app.py", "zs_load_demo"),
    (PHANTOM, "apps/phantom_invoices/app.py", "pi_load_demo"),
    (VAMPIRE, "apps/vampire_fees/app.py", "vf_load_demo"),
)
# Every script the user can open: the entry page, then the three apps alone.
SCRIPTS = [
    pytest.param(ENTRY, id="showcase"),
    *(pytest.param(script, id=accent.key) for accent, script, _button in APPS),
]


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Snapshot and restore the global detector registry; use the template path of the apps."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    snapshot = _snapshot_registry()
    try:
        yield
    finally:
        _restore_registry(snapshot)


def _run(script: str) -> AppTest:
    """Run a script headless; a repository-relative path is resolved from the root."""
    path = script if Path(script).is_absolute() else str(REPO_ROOT / script)
    return AppTest.from_file(path, default_timeout=TIMEOUT_SECONDS).run()


def _demo(script: str, button_key: str) -> AppTest:
    """Run an app and click Load demo data."""
    at = _run(script)
    at.button(key=button_key).click().run()
    return at


def _markdown(at: AppTest) -> list[str]:
    """Every markdown value of the page."""
    return [element.value for element in at.markdown]


def _starting(at: AppTest, prefix: str) -> list[str]:
    """The markdown values that start with `prefix`."""
    return [value for value in _markdown(at) if value.startswith(prefix)]


def _style(at: AppTest) -> str:
    """The single style block of the page."""
    blocks = [value for value in _markdown(at) if value.lstrip().startswith("<style>")]
    assert len(blocks) == 1
    return blocks[0]


# --- every page renders (REQ-HD-15) ---------------------------------------------------------------


@pytest.mark.parametrize("script", SCRIPTS)
def test_every_page_renders_without_exception(script: str) -> None:
    at = _run(script)

    assert not at.exception
    assert not at.error
    _style(at)  # exactly one style block


def test_the_benchmark_page_renders_without_exception() -> None:
    at = AppTest.from_string(BENCHMARK_SCRIPT, default_timeout=TIMEOUT_SECONDS).run()

    assert not at.exception
    assert at.title[0].value == "Benchmark"
    assert len(at.dataframe) >= 2
    style = _style(at)
    assert f"--gl-accent: {KIT.color};" in style
    assert any(value.startswith('<div class="gl-mast">') for value in _markdown(at))


@pytest.mark.parametrize("app", APPS, ids=lambda app: app[0].key)
def test_every_app_renders_with_its_demo_data(app: tuple[Accent, str, str]) -> None:
    _accent, script, button = app
    at = _demo(script, button)

    assert not at.exception
    assert not at.error and not at.sidebar.error
    _style(at)


def test_the_five_pages_are_reachable_from_the_navigation() -> None:
    at = _run(ENTRY)
    for page in streamlit_app.PAGES:
        if page.script is not None:
            at.switch_page(page.script).run()
            assert not at.exception, page.title
            assert at.title[0].value == page.title


# --- accents and icons (REQ-HD-02, 06) ----------------------------------------------------


@pytest.mark.parametrize("app", APPS, ids=lambda app: app[0].key)
def test_each_app_uses_its_own_accent_and_icon(app: tuple[Accent, str, str]) -> None:
    accent, script, _button = app
    at = _run(script)
    style = _style(at)
    [mast] = _starting(at, '<div class="gl-mast">')

    assert re.findall(r"--gl-accent: (#[0-9a-f]{6});", style) == [accent.color]
    assert f"--gl-accent-text: {accent.text_color};" in style
    assert f"gl-icon-{accent.icon}" in mast and accent.kicker in mast
    assert at.title[0].value == accent.title


def test_home_and_benchmark_use_the_kit_accent() -> None:
    style = _style(_run(ENTRY))

    assert re.findall(r"--gl-accent: (#[0-9a-f]{6});", style)[0] == KIT.color == "#7cffb2"


@pytest.mark.parametrize("app", APPS, ids=lambda app: app[0].key)
def test_headings_and_navigation_carry_no_emoji(app: tuple[Accent, str, str]) -> None:
    _accent, script, button = app
    at = _demo(script, button)
    headings = [value for value in _markdown(at) if value.startswith(HEADING_PREFIXES)]

    assert headings
    assert not any(EMOJI.search(value) for value in headings)
    assert not EMOJI.search(at.title[0].value)
    assert not EMOJI.search(_style(at))
    assert all(page.icon in ICON_NAMES for page in streamlit_app.PAGES)


def test_alert_titles_carry_the_icon_badge_instead_of_an_emoji() -> None:
    at = _demo("apps/phantom_invoices/app.py", "pi_load_demo")
    titles = _starting(at, '<div class="pi-alert-title">')

    assert len(titles) == 9
    assert all('class="gl-sev gl-sev-' in title for title in titles)
    assert sum("gl-sev-critical" in title for title in titles) == 3
    assert not any(EMOJI.search(title) for title in titles)


# --- the Home page (REQ-HD-09, 10) ----------------------------------------------------------


def test_home_proof_strip_shows_the_numbers_of_the_committed_files() -> None:
    at = _run(ENTRY)
    [strip] = _starting(at, '<div class="gl-grid gl-proof">')
    figures = [html.unescape(figure) for figure in FIGURE.findall(strip)]
    results = json.loads((REPO_ROOT / "data" / "benchmark" / "results.json").read_text("utf-8"))
    zombie = results["apps"]["zombie"]["totals"]
    phantom = results["apps"]["phantom"]["totals"]

    assert figures == [
        percent_text(zombie["precision"]),
        percent_text(phantom["precision"]),
        "25 of 25",
        "IPC290751",
    ]
    assert f"Recall {percent_text(zombie['recall'])} on 200" in strip
    assert f"Recall {percent_text(phantom['recall'])} on 200" in strip
    assert "Checked once by the reviewer" in strip and "not part of CI" in strip
    assert "licence CC BY 4.0" in strip


def test_home_has_three_tiles_and_a_diagram_and_the_promise_in_one_line() -> None:
    at = _run(ENTRY)
    markdown = _markdown(at)

    [tiles] = _starting(at, '<div class="gl-grid gl-tiles">')
    assert tiles.count('class="gl-card gl-tile ') == 3
    assert sum(value.startswith('<div class="gl-diagram">') for value in markdown) == 1
    [promise] = _starting(at, '<div class="gl-promise">')
    assert "\n" not in promise
    assert streamlit_app.PROMISE in html.unescape(promise)
    assert len(_starting(at, '<div class="gl-section"')) == 3


def test_the_home_demo_numbers_are_the_ones_the_apps_show() -> None:
    zombie = _demo("apps/zombie_subscriptions/app.py", "zs_load_demo")
    zombie_shown = (
        len(_starting(zombie, '<div class="zs-tombstone">')),
        len(_starting(zombie, '<div class="zs-alert-title">')),
    )
    phantom = _demo("apps/phantom_invoices/app.py", "pi_load_demo")
    counts = {metric.label.split()[-1]: metric.value for metric in phantom.metric}
    vampire = _demo("apps/vampire_fees/app.py", "vf_load_demo")
    vampire_shown = (
        len(_starting(vampire, '<div class="vf-coffin">')),
        len(_starting(vampire, '<div class="vf-alert-title">')),
    )

    shown = {
        "zombie": (str(zombie_shown[0]), str(zombie_shown[1])),
        "phantom": (counts["critical"], counts["warning"]),
        "vampire": (str(vampire_shown[0]), str(vampire_shown[1])),
    }
    stated = {tile.accent.key: tuple(figure for figure, _label in tile.stats) for tile in TILES}
    assert stated == shown
