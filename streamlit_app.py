"""Ghost Ledger Kit showcase: the entry page of the Streamlit Community Cloud app.

Run with: ``streamlit run streamlit_app.py``

``st.navigation`` offers five pages: Home and Benchmark (functions written below) and the three
apps, whose ``app.py`` files run unchanged as pages. Each app still works alone with
``streamlit run apps/<name>/app.py``. This file imports no app module except ``apps.home_tiles``
(the bridge that runs the demo data of the apps for the Home tiles and the moment) and none of
the benchmark code: the Benchmark page only shows ``data/benchmark/results.json``.

The look comes from ``ledger_kit/ui`` (spec haunted-design): the menu icons are drawn by the
theme's CSS from the icon names in ``PAGES``, because ``st.Page`` accepts only an emoji or a
Material icon.

Facts checked in Streamlit 1.67: ``st.set_page_config`` may be called again by a page (the calls
are additive, the page's title wins); a file page runs as ``__main__``, so the guard at the bottom
of each app fires; both apps are named ``app.py``, so every page needs an explicit ``url_path``.
"""

import html
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

import streamlit as st

from apps import home_tiles
from ledger_kit.ui import landing, theme


class PageSpec(NamedTuple):
    """One entry of the navigation menu."""

    title: str
    icon: str  # name of a ledger_kit.ui.icons icon; the menu draws it with CSS, no emoji
    url_path: str  # explicit and unique: both app files are called app.py
    script: str | None  # path of an app's app.py relative to this file; None: a function page


PAGES: tuple[PageSpec, ...] = (
    PageSpec("Home", "candle", "home", None),
    PageSpec(
        "Zombie Subscriptions",
        "tombstone",
        "zombie-subscriptions",
        "apps/zombie_subscriptions/app.py",
    ),
    PageSpec("Phantom Invoices", "ghost", "phantom-invoices", "apps/phantom_invoices/app.py"),
    PageSpec("Vampire Fees", "coffin", "vampire-fees", "apps/vampire_fees/app.py"),
    PageSpec("Benchmark", "scales", "benchmark", None),
)

HOME_TITLE = "Ghost Ledger Kit"
HOW_IT_WORKS = "How it works"  # the closed expander below the tiles

PROMISE = (
    "Financial apps that cannot make up a number: every figure comes from a row you can check."
)

# The story under the promise (judge-path, REQ-JP-14): three short lines, no figure.
STORY: tuple[str, ...] = (
    "Bank statements and invoices hide money leaks.",
    "A language model can explain them, but it makes up numbers.",
    "Here, plain code finds and computes every figure; a guard rejects invented ones.",
)
START_HERE = "Start here: Zombie Subscriptions"
START_HERE_ICON = "🪦"  # the tombstone of Zombie Subscriptions; st.page_link takes an emoji
START_HERE_FALLBACK = "Start here: open Zombie Subscriptions from the menu."

LAYERS = """
1. **Deterministic detectors find the figures.** Plain Python rules, no machine learning.
2. **Every alert cites its source rows.** Each lists file and line as `file · line N`, so every
   figure can be checked in the original file.
3. **The LLM only words the explanation.** It never raises, changes or dismisses an alert. The
   number guard rejects any answer with a number, date or IBAN found in neither the cited rows
   nor the alert, and the app shows a fixed template instead. When asked a question, the model
   may write a formula; the kit, not the model, computes it.
"""

TRY_IT = (
    "**Try it:** open an app and switch on **Simulate a hallucinating LLM** in the sidebar. A "
    "stub model invents 99999.99 EUR; the guard rejects it and the card shows a warning badge. "
    "With no API key every card replays a recorded answer of a real model, checked now by the "
    "number guard (no model is called), or the fixed template if rejected. The *Provoke the "
    "LLM* panel replays recorded answers only "
    "on the first critical card of each app (GYMPLUS, Suministros Ibéricos, Vampire Fees); on "
    "every other card it stays off until you set an API key."
)

SYNTHETIC_NOTE = (
    "All demo data in this showcase is synthetic: fictional names and merchants, and IBANs whose "
    "national check digits are deliberately wrong."
)

# Zombie Subscriptions compares price increases with a committed snapshot of the INE consumer
# price index (public-cpi). The same texts are in the snapshot, the README and the data/public
# README; tests/test_public_data_docs.py compares them. This file imports neither app.
INE_ATTRIBUTION = "Elaboración propia con datos extraídos del sitio web del INE: www.ine.es"
INE_LICENCE = "CC BY 4.0"
INE_NOTE = (
    "Official public data in Zombie Subscriptions (Spanish consumer price index): "
    f"{INE_ATTRIBUTION}. Licence {INE_LICENCE}."
)

# The Benchmark page shows the committed results file and nothing else (REQ-BM-20, REQ-BM-21).
# Home reads the same file for its proof strip, through the same (patchable) path.
RESULTS_PATH = Path(__file__).parent / "data" / "benchmark" / "results.json"
RESULTS_SCHEMA_VERSION = 1
BENCHMARK_TITLE = "Benchmark"


def _markdown(markup: str) -> None:
    """Render a block of trusted HTML built by ledger_kit.ui (every inserted text is escaped)."""
    st.markdown(markup, unsafe_allow_html=True)


def _start_here() -> None:
    """The Start here link to Zombie Subscriptions; a plain sentence if it cannot be drawn."""
    zombie = next(spec for spec in PAGES if spec.url_path == "zombie-subscriptions")
    try:
        st.page_link(_page(zombie), label=START_HERE, icon=START_HERE_ICON)
    except Exception:  # a link that cannot be drawn must never take Home down
        st.markdown(START_HERE_FALLBACK)


def home() -> None:
    """Render Home: promise, the moment, proof strip, app tiles, then How it works (closed)."""
    theme.apply_theme(theme.KIT)
    theme.show_masthead(theme.KIT)
    st.title(HOME_TITLE)
    _markdown(f'<div class="gl-promise">{html.escape(PROMISE)}</div>')
    moment = landing.moment_html(home_tiles.home_moment())
    if moment:
        _markdown(moment)
    theme.show_section("scales", "Proof, read from the committed files")
    _markdown(landing.proof_strip_html(landing.proof_facts(results_path=RESULTS_PATH)))
    theme.show_section("ghost", "Three apps, one contract")
    _markdown(landing.tiles_html(drawings=home_tiles.tile_signatures()))
    with st.expander(HOW_IT_WORKS, expanded=False):
        _markdown(landing.story_html(STORY))
        _start_here()
        theme.show_section("candle", "How a figure reaches the screen")
        _markdown(landing.diagram_html())
        st.markdown(LAYERS)
        st.info(TRY_IT)
        st.caption(SYNTHETIC_NOTE)
        st.caption(INE_NOTE)


NO_RESULTS = "No usable benchmark results. Run: python scripts/benchmark.py"
BENCHMARK_APPS: tuple[tuple[str, str], ...] = (
    ("zombie", "Zombie Subscriptions"),
    ("phantom", "Phantom Invoices"),
)
BENCHMARK_NOTE = (
    "These numbers come from synthetic data that the project generated and labelled itself; "
    "they describe that mix of problems, not real accounts. Method, matching rule and limits: "
    "docs/benchmark.md."
)
HARD_NEGATIVES_NOTE = "Hard negatives: look-alike clean cases that must stay silent."


class BenchmarkApp(NamedTuple):
    """The rows of one app on the Benchmark page."""

    title: str
    detectors: list[dict[str, Any]]
    negatives: list[dict[str, Any]]


def _cell(value: Any) -> Any:
    """A table cell: ``null`` in the results file is shown as ``n/a``."""
    return "n/a" if value is None else value


def _benchmark_app(title: str, data: dict[str, Any]) -> BenchmarkApp:
    """Turn the block of one app of the results file into table rows (no arithmetic)."""
    detectors = [
        {
            "Detector": name,
            "Planted": entry["labels"],
            "Found": entry["tp"],
            "Missed": entry["fn"],
            "False alarms": entry["fp"],
            "Precision": _cell(entry["precision"]),
            "Recall": _cell(entry["recall"]),
            "Clean scenarios with an alert": entry["noise_only_scenarios_with_alert"],
        }
        for name, entry in sorted(data["detectors"].items())
    ]
    negatives = [
        {
            "Hard negative": kind,
            "Instances": row["instances"],
            "Instances with a false alarm": row["instances_with_false_alarm"],
            "False alarms": row["false_alarms"],
        }
        for kind, row in sorted(data["hard_negatives"].items())
    ]
    return BenchmarkApp(title, detectors, negatives)


def _load_benchmark(path: Path) -> tuple[str, list[BenchmarkApp], list[str]] | None:
    """Read the results file; None when it is missing, not JSON, another schema or malformed."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("schema_version") != RESULTS_SCHEMA_VERSION:
            return None
        limits = data["limits"]
        if not isinstance(limits, list) or not all(isinstance(text, str) for text in limits):
            return None
        apps = [_benchmark_app(title, data["apps"][key]) for key, title in BENCHMARK_APPS]
        header = f"Seed {data['seed']}; {data['scenarios_per_app']} scenarios per app."
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None
    return header, apps, limits


def benchmark() -> None:
    """Render the Benchmark page from results.json; show one error when it is not usable."""
    theme.apply_theme(theme.BENCHMARK)
    theme.show_masthead(theme.BENCHMARK)
    st.title(BENCHMARK_TITLE)
    loaded = _load_benchmark(RESULTS_PATH)
    if loaded is None:
        st.error(NO_RESULTS)
        return
    header, apps, limits = loaded
    st.caption(header)
    st.caption(BENCHMARK_NOTE)
    for app in apps:
        st.subheader(app.title)
        st.dataframe(app.detectors, hide_index=True)
        if app.negatives:
            st.caption(HARD_NEGATIVES_NOTE)
            st.dataframe(app.negatives, hide_index=True)
    st.markdown("**Limits**")
    st.markdown("\n".join(f"- {text}" for text in limits))


# Pages without a script are functions, found by their url_path.
FUNCTION_PAGES: dict[str, Callable[[], None]] = {"home": home, "benchmark": benchmark}


def _page(spec: PageSpec) -> st.Page:
    """Build the st.Page of one spec; Home is the default page (its icon is drawn by CSS)."""
    return st.Page(
        spec.script or FUNCTION_PAGES[spec.url_path],
        title=spec.title,
        url_path=spec.url_path,
        default=spec.url_path == "home",
    )


def main() -> None:
    """Set the page defaults, build the menu and run the selected page."""
    theme.set_page("Ghost Ledger Kit", theme.KIT)
    st.navigation([_page(spec) for spec in PAGES]).run()


# Streamlit executes the script as __main__; importing the module (tests) renders nothing.
if __name__ == "__main__":
    main()
