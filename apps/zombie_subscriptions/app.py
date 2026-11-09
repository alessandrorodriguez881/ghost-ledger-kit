"""Zombie subscriptions: a Halloween graveyard of forgotten recurring charges (design §7, §8).

Run with: ``streamlit run apps/zombie_subscriptions/app.py``

Pipeline: ingest (ledger_kit) -> debit rows -> five deterministic zs.* detectors -> tombstones
and alerts. The LLM only writes the explanation text, and its numbers are checked by the guard.
"""

import hashlib
import html
import io
import os
import sys
from collections.abc import Callable, MutableMapping, Sequence
from pathlib import Path
from typing import Any, TypeVar

# `streamlit run apps/zombie_subscriptions/app.py` puts only this folder on sys.path, so make the
# repository root importable when the package is not installed (REQ-ZS-41, design §8).
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

import apps.zombie_subscriptions.detectors  # noqa: E402,F401  (registers the zs.* detectors)
from apps.zombie_subscriptions.detectors.utils import (  # noqa: E402
    compute_zombie_cost,
    normalise_alias_map,
    normalise_date_map,
)
from apps.zombie_subscriptions.explain_support import (  # noqa: E402
    TEMPLATES,
    HallucinatingStubClient,
)
from apps.zombie_subscriptions.settings import (  # noqa: E402
    SEVERITY_ORDER,
    apply_demo,
    demo_inputs,
    group_alerts_by_severity,
    guard_badge,
    ledger_currency,
    load_config,
    parse_aliases_text,
    parse_dates_text,
    tombstone_view,
)
from ledger_kit.detectors import run_all  # noqa: E402
from ledger_kit.explainer import Explanation, explain_with_meta  # noqa: E402
from ledger_kit.ingestion.csv_reader import parse_csv  # noqa: E402
from ledger_kit.ingestion.normaliser import normalise  # noqa: E402
from ledger_kit.models import Alert  # noqa: E402
from ledger_kit.ui.reference_app import (  # noqa: E402
    SEVERITY_BADGES,
    count_by_severity,
    format_for_display,
    quarantine_table,
    rows_for_refs,
)

ROOT = _ROOT
CONFIG_PATH = Path(__file__).resolve().parent / "config.toml"

# Session-state keys carry the app prefix `zs_` where the name could clash with the other app of
# the showcase (REQ-SC-04); the phantom app uses `pi_`.
LOAD_DEMO_KEY = "zs_load_demo"
HALLUCINATE_KEY = "zs_hallucinate"
EXPLANATIONS_KEY = "zs_explanations"

# Widget state is dropped when a run does not render the widget (the user visited another page of
# the showcase). The widget values are copied to a plain key after the sidebar is drawn and put
# back before the widgets are built (REQ-SC-05).
WIDGET_KEYS: tuple[str, ...] = ("aliases_text", "last_used_text", "cancel_text", HALLUCINATE_KEY)
KEPT_KEY = "zs_kept"

# Tombstones per row of the graveyard.
TOMBSTONES_PER_ROW: int = 3

_T = TypeVar("_T")

# Halloween graveyard theme (REQ-ZS-35): dark background, pale stone text, muted green and amber.
GRAVEYARD_CSS = """
<style>
.stApp { background-color: #1a1a2e; color: #d9d6c7; }
[data-testid="stSidebar"] { background-color: #14142a; }
.stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp p, .stApp li, .stApp label,
.stApp [data-testid="stMarkdownContainer"], .stApp [data-testid="stCaptionContainer"],
.stApp [data-testid="stMetricLabel"], .stApp [data-testid="stMetricValue"],
.stApp [data-testid="stExpander"] summary { color: #d9d6c7; }
.stApp h1 { color: #9fbf8f; letter-spacing: 0.04em; }
.stApp h2, .stApp h3 { color: #c9b27a; }
.stApp textarea, .stApp input { background-color: #232347; color: #d9d6c7; }
[data-testid="stVerticalBlockBorderWrapper"] { border-color: #3d3d63; }
.zs-tombstone {
  background: linear-gradient(180deg, #4a4a6a 0%, #34344f 100%);
  border: 2px solid #6b6b8c;
  border-radius: 90px 90px 8px 8px;
  padding: 22px 18px 16px 18px;
  margin-bottom: 8px;
  text-align: center;
  box-shadow: 0 6px 14px rgba(0, 0, 0, 0.5);
}
.zs-rip { color: #9fbf8f; font-weight: 700; letter-spacing: 0.2em; font-size: 0.9rem; }
.zs-name { color: #ece8d8; font-size: 1.35rem; font-weight: 700; margin: 6px 0 10px 0; }
.zs-line { color: #d9d6c7; font-size: 0.95rem; margin: 2px 0; }
.zs-amber { color: #e0a43a; }
.zs-alert-title { font-size: 1.05rem; font-weight: 700; color: #ece8d8; }
.zs-badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 12px;
  font-size: 0.85rem;
  border: 1px solid #6b6b8c;
}
.zs-badge-llm { background: #25402f; color: #b9e0a8; border-color: #5f8f5a; }
.zs-badge-template { background: #2d2d4d; color: #d9d6c7; }
.zs-badge-unavailable { background: #2d2d4d; color: #d9d6c7; }
.zs-badge-rejected { background: #4a3517; color: #f0c26a; border-color: #e0a43a; }
</style>
"""


def load_demo() -> None:
    """on_click callback of Load demo data: pre-fill the widget keys before the rerun.

    It runs before the script reruns and builds any widget, so writing the widget keys is
    allowed here (and would raise StreamlitWidgetAlreadyInstantiatedError in an `if` body).
    """
    apply_demo(st.session_state, demo_inputs(load_config(CONFIG_PATH), ROOT))


def _restore_widgets() -> None:
    """Put back the widget values kept from the previous visit, before any widget is built."""
    for key, value in st.session_state.get(KEPT_KEY, {}).items():
        st.session_state.setdefault(key, value)


def _keep_widgets() -> None:
    """Copy the widget values to a plain key so they survive a visit to another page."""
    st.session_state[KEPT_KEY] = {key: st.session_state[key] for key in WIDGET_KEYS}


def _init_state() -> None:
    """Set the defaults of the widget keys and caches once, before any widget exists."""
    _restore_widgets()
    for key in ("aliases_text", "last_used_text", "cancel_text"):
        st.session_state.setdefault(key, "")
    st.session_state.setdefault(HALLUCINATE_KEY, False)
    st.session_state.setdefault("demo_loaded", False)
    st.session_state.setdefault("ingestion_cache", {})
    st.session_state.setdefault(EXPLANATIONS_KEY, {})


def _render_sidebar() -> Any:
    """Draw the sidebar widgets and return the uploaded file (None when there is none)."""
    with st.sidebar:
        st.header("Controls")
        st.button("Load demo data", key=LOAD_DEMO_KEY, on_click=load_demo)
        st.text_area(
            "Aliases",
            key="aliases_text",
            height=110,
            help="One service per line: streaming = STREAMFLIX INTL, STREAMFLIXCOM",
        )
        st.text_area(
            "Last-used dates",
            key="last_used_text",
            height=110,
            help="One per line: BEATSTREAM = 2026-07-15 (turns the service into a tombstone)",
        )
        st.text_area(
            "Cancellation dates",
            key="cancel_text",
            height=110,
            help="One per line: GYMPLUS = 2026-07-31",
        )
        st.toggle(
            "Simulate a hallucinating LLM",
            key=HALLUCINATE_KEY,
            help="Replaces the LLM with a stub that invents 99999.99; the guard rejects it.",
        )
        return st.file_uploader("Bank statement CSV", type="csv")


def _parse_field(label: str, parser: Callable[[str], _T], text: str, empty: _T) -> _T:
    """Parse one sidebar text area; show the error in the sidebar instead of crashing."""
    try:
        return parser(text)
    except ValueError as error:
        st.sidebar.error(f"{label}: {error}")
        return empty


def _current_source(uploaded: Any) -> tuple[str, bytes] | None:
    """Return (file name, bytes) of the uploaded file, else of the loaded demo, else None."""
    if uploaded is not None:
        return uploaded.name, uploaded.getvalue()
    stored = st.session_state.get("source")
    if stored:
        _kind, data, name = stored
        return name, data
    return None


def _ingest(
    name: str, data: bytes, cache: MutableMapping[str, Any]
) -> tuple[pd.DataFrame, list[dict]]:
    """Parse and normalise one CSV (parsing cached by content hash); return ledger, quarantine."""
    key = f"{hashlib.sha256(data).hexdigest()}:{name}"
    if key not in cache:
        cache[key] = parse_csv(io.BytesIO(data), source_file=name)
    transactions, quarantined = cache[key]
    ledger, normalise_quarantine = normalise(transactions)
    return ledger, [*quarantined, *normalise_quarantine]


def _explain(alert: Alert, ledger: pd.DataFrame, hallucinate: bool) -> Explanation:
    """Explain one alert; cached per (alert.id, client mode) across reruns (design §7)."""
    cache = st.session_state[EXPLANATIONS_KEY]
    key = (alert.id, "hallucinate" if hallucinate else "real")
    if key not in cache:
        rows = ledger[ledger["source_ref"].isin(alert.source_refs)]
        client = HallucinatingStubClient() if hallucinate else None
        cache[key] = explain_with_meta(
            alert, rows, fallback_template=TEMPLATES[alert.detector], client=client
        )
    return cache[key]


def _refs_markdown(refs: Sequence[str]) -> str:
    """Return the source refs as inline code, comma separated."""
    return ", ".join(f"`{ref}`" for ref in refs)


def _render_summary(alerts: Sequence[Alert], tombstones: int) -> None:
    """Metrics row: tombstones and alerts per severity."""
    counts = count_by_severity(alerts)
    columns = st.columns(len(SEVERITY_ORDER) + 1)
    columns[0].metric("🪦 tombstones", tombstones)
    for column, severity in zip(columns[1:], SEVERITY_ORDER, strict=True):
        column.metric(f"{SEVERITY_BADGES[severity]} {severity}", counts[severity])


def _tombstone_line(label: str, value: str) -> str:
    """Return one 'label: value' line of a tombstone; the value is escaped."""
    return f'<div class="zs-line">{label}: <b class="zs-amber">{html.escape(value)}</b></div>'


def _tombstone_html(name: str, died_on: str, cost_since: str, yearly_cost: str) -> str:
    """Return the HTML of one tombstone card; every value is escaped."""
    parts = [
        '<div class="zs-tombstone">',
        '<div class="zs-rip">R.I.P.</div>',
        f'<div class="zs-name">{html.escape(name)}</div>',
        _tombstone_line("Died on", died_on),
        _tombstone_line("Cost since then", cost_since),
        _tombstone_line("Yearly cost", yearly_cost),
        "</div>",
    ]
    return "".join(parts)


def _render_graveyard(zombies: Sequence[Any], currency: str) -> None:
    """One tombstone per zombie service, with its yearly cost and collapsible source refs."""
    st.subheader("🪦 The graveyard")
    if not zombies:
        st.caption("Add last-used dates in the sidebar to bury a subscription here.")
        return
    views = [tombstone_view(result, currency) for result in zombies]
    for start in range(0, len(views), TOMBSTONES_PER_ROW):
        row = views[start : start + TOMBSTONES_PER_ROW]
        for column, view in zip(st.columns(TOMBSTONES_PER_ROW), row, strict=False):
            with column:
                card = _tombstone_html(view.name, view.died_on, view.cost_since, view.yearly_cost)
                st.markdown(card, unsafe_allow_html=True)
                with st.expander(f"Source rows ({len(view.source_refs)})"):
                    if view.source_refs:
                        st.markdown(_refs_markdown(view.source_refs))
                    else:
                        st.caption("No charge after the last-used date.")


def _render_alert(alert: Alert, ledger: pd.DataFrame, hallucinate: bool) -> None:
    """One alert card: title, detector, explanation, guard badge, refs and cited rows."""
    explanation = _explain(alert, ledger, hallucinate)
    badge = guard_badge(explanation, has_api_key=bool(os.environ.get("OPENAI_API_KEY", "")))
    with st.container(border=True):
        title = f"{SEVERITY_BADGES[alert.severity]} {html.escape(alert.title)}"
        st.markdown(f'<div class="zs-alert-title">{title}</div>', unsafe_allow_html=True)
        st.caption(f"Detector: `{alert.detector}` · severity: {alert.severity}")
        st.write(explanation.text)
        st.markdown(
            f'<span class="zs-badge zs-badge-{badge.kind}">{html.escape(badge.label)}</span>',
            unsafe_allow_html=True,
        )
        st.markdown("**Source refs:** " + _refs_markdown(alert.source_refs))
        with st.expander(f"Source rows ({len(alert.source_refs)})"):
            cited, _missing = rows_for_refs(ledger, alert.source_refs)
            st.dataframe(format_for_display(cited), hide_index=True, width="stretch")


def _render_alerts(alerts: Sequence[Alert], ledger: pd.DataFrame, hallucinate: bool) -> None:
    """The alert list grouped critical, warning, info (REQ-ZS-37)."""
    st.subheader("👻 Alerts")
    if not alerts:
        st.write("No alerts: nothing in this statement looks like a zombie.")
        return
    groups = group_alerts_by_severity(alerts)
    for severity in SEVERITY_ORDER:
        if not groups[severity]:
            continue
        st.markdown(f"#### {SEVERITY_BADGES[severity]} {severity.capitalize()}")
        for alert in groups[severity]:
            _render_alert(alert, ledger, hallucinate)


def _render_quarantine(quarantine: Sequence[dict]) -> None:
    """Collapsible warning section; only rendered when something was quarantined."""
    if not quarantine:
        return
    with st.expander(f"⚠ Quarantined rows ({len(quarantine)})"):
        st.warning("These rows were not loaded. Fix them in the source file and upload it again.")
        st.dataframe(quarantine_table(quarantine), hide_index=True, width="stretch")


def main() -> None:
    """Render the zombie-subscriptions page."""
    st.set_page_config(page_title="Zombie Subscriptions", page_icon="🪦", layout="wide")
    st.markdown(GRAVEYARD_CSS, unsafe_allow_html=True)
    _init_state()
    uploaded = _render_sidebar()
    _keep_widgets()

    st.title("🪦 Zombie Subscriptions")
    st.caption("Every figure comes from a cited row of your statement. The LLM only explains.")

    source = _current_source(uploaded)
    if source is None:
        st.info("Click Load demo data in the sidebar, or upload a bank statement CSV.")
        return

    aliases = normalise_alias_map(
        _parse_field("Aliases", parse_aliases_text, st.session_state["aliases_text"], {})
    )
    last_used_dates = normalise_date_map(
        _parse_field("Last-used dates", parse_dates_text, st.session_state["last_used_text"], {})
    )
    cancellation_dates = normalise_date_map(
        _parse_field("Cancellation dates", parse_dates_text, st.session_state["cancel_text"], {})
    )

    name, data = source
    ledger, quarantine = _ingest(name, data, st.session_state["ingestion_cache"])
    debit_ledger = ledger[ledger["flow"] == "debit"].reset_index(drop=True)
    st.caption(f"{name}: {len(debit_ledger)} debit rows analysed, {len(quarantine)} quarantined")

    context = {"aliases": aliases, "cancellation_dates": cancellation_dates}
    results = run_all(debit_ledger, namespace="zs", context=context)
    alerts = [alert for result in results for alert in result.alerts]
    zombies = compute_zombie_cost(debit_ledger, last_used_dates, aliases=aliases)

    _render_summary(alerts, len(zombies))
    _render_quarantine(quarantine)
    _render_graveyard(zombies, ledger_currency(debit_ledger))
    _render_alerts(alerts, debit_ledger, bool(st.session_state[HALLUCINATE_KEY]))


# Streamlit executes the script as __main__; importing the module (tests) renders nothing.
if __name__ == "__main__":
    main()
