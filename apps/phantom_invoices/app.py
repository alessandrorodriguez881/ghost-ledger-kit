"""Phantom Invoices: a haunted ledger lit by a flashlight (design sections 13 and 14).

Run with: ``streamlit run apps/phantom_invoices/app.py``

Pipeline: ingest invoices, supplier master and bank payments (ledger_kit) -> four deterministic
pi.* detectors -> the haunted ledger and the alert cards. The LLM only writes the explanation
text, and its numbers are checked by the guard. Pure view-model helpers live in settings.py and
explain_support.py so they can be tested without a Streamlit runtime.
"""

import html
import os
import sys
from collections.abc import Iterable, Sequence
from datetime import date
from pathlib import Path
from typing import Any

# `streamlit run apps/phantom_invoices/app.py` puts only this folder on sys.path, so make the
# repository root importable when the package is not installed (REQ-PI-53, design 14.2).
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from apps.phantom_invoices.detectors import LABELS  # noqa: E402  (registers the pi.* detectors)
from apps.phantom_invoices.explain_support import (  # noqa: E402
    HallucinatingStubClient,
    badge_kind,
    explain_alert,
    explanation_key,
    guard_badge,
    template_for,
)
from apps.phantom_invoices.flashlight import HAUNTED_CSS, render_ledger_html  # noqa: E402
from apps.phantom_invoices.settings import (  # noqa: E402
    DEMO_FORMATS,
    MULTI_RATE_NOTE,
    NO_FLASHLIGHT,
    SEVERITY_ICONS,
    SEVERITY_ORDER,
    UI_DEFAULT_AS_OF,
    Pipeline,
    Source,
    alert_captions,
    alert_option_label,
    apply_demo,
    as_of_note,
    cited_master_view,
    cited_payments_view,
    demo_inputs,
    flashlight_options,
    group_alerts,
    input_notice,
    ledger_view,
    lit_refs_for,
    load_config,
    markdown_safe,
    ordered_alerts,
    pipeline_key,
    quarantine_view,
    reset_selected,
    run_pipeline,
    severity_counts,
    verification_message,
)
from ledger_kit.explainer import Explanation, fill_fallback  # noqa: E402
from ledger_kit.ingestion.norma43_reader import control_check_messages  # noqa: E402
from ledger_kit.models import Alert  # noqa: E402

ROOT = _ROOT
CONFIG_PATH = Path(__file__).resolve().parent / "config.toml"
CONFIG = load_config(CONFIG_PATH)

SOURCE_KINDS: tuple[str, ...] = ("invoices", "suppliers", "payments")
# Bounds of the as-of date input (fixed, so the widget never depends on today's date).
AS_OF_MIN: date = date(2000, 1, 1)
AS_OF_MAX: date = date(2100, 12, 31)

# Session-state keys carry the app prefix `pi_` where the name could clash with the other app of
# the showcase (REQ-SC-04); the zombie app uses `zs_`.
LOAD_DEMO_KEY = "pi_load_demo"
HALLUCINATE_KEY = "pi_hallucinate"
EXPLANATIONS_KEY = "pi_explanations"
DEMO_FORMAT_KEY = "pi_demo_format"
UPLOAD_INVOICES_KEY = "pi_upload_invoices"
UPLOAD_SUPPLIERS_KEY = "pi_upload_suppliers"
UPLOAD_PAYMENTS_KEY = "pi_upload_payments"

# Widget state is dropped when a run does not render the widget (the user visited another page of
# the showcase). The widget values are copied to a plain key after the sidebar is drawn and put
# back before the widgets are built (REQ-SC-05). Uploaded files cannot be kept this way.
WIDGET_KEYS: tuple[str, ...] = ("use_as_of", "as_of_date", HALLUCINATE_KEY, DEMO_FORMAT_KEY)
KEPT_KEY = "pi_kept"

# App-level additions to the haunted-ledger theme (REQ-PI-48): CSS only, no external resource.
APP_CSS = """
[data-testid="stSidebar"] { background-color: #0d0b14; }
.stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp p, .stApp li, .stApp label,
.stApp [data-testid="stMarkdownContainer"], .stApp [data-testid="stCaptionContainer"],
.stApp [data-testid="stMetricLabel"], .stApp [data-testid="stMetricValue"],
.stApp [data-testid="stExpander"] summary { color: #e8dcc0; }
.stApp h1 { color: #7cffb2; letter-spacing: 0.04em; }
.stApp h2, .stApp h3 { color: #ffb347; }
.stApp textarea, .stApp input { background-color: #1c1829; color: #e8dcc0; }
[data-testid="stVerticalBlockBorderWrapper"] { border-color: #3a3350; }
.ledger-wrap { overflow-x: auto; margin-bottom: 12px; }
.ledger th, .ledger td { font-size: 0.85rem; white-space: nowrap; }
.pi-alert-title { font-size: 1.05rem; font-weight: 700; color: #ffffff; }
.pi-badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 12px;
  font-size: 0.85rem;
  border: 1px solid #3a3350;
}
.pi-badge-llm { background: #17352a; color: #7cffb2; border-color: #7cffb2; }
.pi-badge-template { background: #241f33; color: #e8dcc0; }
.pi-badge-unavailable { background: #241f33; color: #e8dcc0; }
.pi-badge-rejected { background: #3d2a12; color: #ffd166; border-color: #ffb347; }
"""


def load_demo() -> None:
    """on_click callback of Load demo data: pre-fill the widget keys before the rerun.

    It runs before the script reruns and builds any widget, so writing the widget keys is
    allowed here (and would raise StreamlitWidgetAlreadyInstantiatedError in an `if` body).
    """
    apply_demo(
        st.session_state,
        demo_inputs(CONFIG, ROOT, DEMO_FORMATS[st.session_state[DEMO_FORMAT_KEY]]),
    )


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
    st.session_state.setdefault("sources", {kind: None for kind in SOURCE_KINDS})
    st.session_state.setdefault("use_as_of", False)
    # A widget placeholder only: it reaches a detector when the user ticks use_as_of (DN-11).
    st.session_state.setdefault("as_of_date", UI_DEFAULT_AS_OF)
    st.session_state.setdefault(HALLUCINATE_KEY, False)
    st.session_state.setdefault(DEMO_FORMAT_KEY, next(iter(DEMO_FORMATS)))
    st.session_state.setdefault("selected_alert", NO_FLASHLIGHT)
    st.session_state.setdefault("pipeline_cache", {})
    st.session_state.setdefault(EXPLANATIONS_KEY, {})


def _render_sidebar() -> dict[str, Any]:
    """Draw the sidebar widgets and return the uploaded files by kind (None when not given)."""
    st.sidebar.header("Controls")
    st.sidebar.radio(
        "Demo format",
        list(DEMO_FORMATS),
        key=DEMO_FORMAT_KEY,
        horizontal=True,
        help="CSV: the CSV demo files. Real formats: Facturae XML invoices and a Norma 43 file.",
    )
    st.sidebar.button("Load demo data", key=LOAD_DEMO_KEY, on_click=load_demo)
    uploads = {
        "invoices": st.sidebar.file_uploader(
            "Invoices (.csv, .json, .xml or .xsig; several files allowed)",
            type=["csv", "json", "xml", "xsig"],
            accept_multiple_files=True,
            key=UPLOAD_INVOICES_KEY,
        ),
        "suppliers": st.sidebar.file_uploader(
            "Supplier master (.csv)", type="csv", key=UPLOAD_SUPPLIERS_KEY
        ),
        "payments": st.sidebar.file_uploader(
            "Bank payments (.csv or Norma 43)",
            type=["csv", "n43", "txt", "aeb", "csb43"],
            key=UPLOAD_PAYMENTS_KEY,
        ),
    }
    st.sidebar.checkbox(
        "Fix the as-of date",
        key="use_as_of",
        help="Off: the latest date in the data is used to decide which invoices are overdue.",
    )
    st.sidebar.date_input(
        "As-of date",
        key="as_of_date",
        min_value=AS_OF_MIN,
        max_value=AS_OF_MAX,
        disabled=not st.session_state["use_as_of"],
    )
    st.sidebar.toggle(
        "Simulate a hallucinating LLM",
        key=HALLUCINATE_KEY,
        help="Replaces the LLM with a stub that invents 99999.99; the number guard rejects it.",
    )
    return uploads


def _current_sources(uploads: dict[str, Any]) -> dict[str, Any]:
    """Return the inputs: the uploaded files, else the loaded demo files, else None.

    `invoices` is a tuple of Source (several files are allowed) or None; the others are one
    Source or None.
    """
    stored = st.session_state["sources"]
    sources: dict[str, Any] = {}
    uploaded_invoices = uploads["invoices"] or []
    if uploaded_invoices:
        sources["invoices"] = tuple(Source(f.name, f.getvalue()) for f in uploaded_invoices)
    else:
        sources["invoices"] = tuple(stored.get("invoices") or ()) or None
    for kind in ("suppliers", "payments"):
        upload = uploads[kind]
        if upload is not None:
            sources[kind] = Source(name=upload.name, data=upload.getvalue())
        else:
            sources[kind] = stored.get(kind)
    return sources


def _pipeline(sources: dict[str, Any], as_of: date | None) -> Pipeline | None:
    """Return the pipeline for these inputs, cached by the SHA-256 of the files."""
    key = pipeline_key(sources["invoices"], sources["suppliers"], sources["payments"], as_of)
    cache = st.session_state["pipeline_cache"]
    if key not in cache:
        try:
            cache[key] = run_pipeline(
                sources["invoices"], sources["suppliers"], sources["payments"], as_of
            )
        except Exception as error:  # a malformed upload must be reported, not crash the page
            st.error(f"The inputs could not be read: {error}")
            return None
    return cache[key]


def _explain(alert: Alert, pipeline: Pipeline, hallucinate: bool) -> Explanation:
    """Explain one alert; cached per (alert.id, client mode) across reruns (REQ-PI-47)."""
    cache = st.session_state[EXPLANATIONS_KEY]
    key = explanation_key(alert, hallucinate)
    if key not in cache:
        client = None
        if hallucinate:
            client = HallucinatingStubClient(fill_fallback(template_for(alert), alert))
        cache[key] = explain_alert(
            alert, pipeline.invoices, pipeline.suppliers, pipeline.payments, client=client
        )
    return cache[key]


def _refs_markdown(refs: Iterable[str]) -> str:
    """Return the source refs as inline code, comma separated."""
    return ", ".join(f"`{ref}`" for ref in refs)


def _table_html(view: pd.DataFrame, lit_refs: Sequence[str]) -> str:
    """Return the flashlight table of `view`, wrapped so a wide table scrolls sideways."""
    return f'<div class="ledger-wrap">{render_ledger_html(view, lit_refs)}</div>'


def _render_summary(alerts: Sequence[Alert]) -> None:
    """Severity summary row: one metric per severity (REQ-PI-49 part 1)."""
    counts = severity_counts(alerts)
    for column, severity in zip(st.columns(2), ("critical", "warning"), strict=True):
        column.metric(f"{SEVERITY_ICONS[severity]} {severity}", counts[severity])


def _render_cited_rows(pipeline: Pipeline, lit_refs: Sequence[str]) -> None:
    """Show the cited supplier-master and payment rows below the ledger, all lit."""
    master = cited_master_view(pipeline.suppliers, lit_refs)
    if not master.empty:
        st.markdown("**Cited supplier-master rows**")
        st.markdown(_table_html(master, list(master["source_ref"])), unsafe_allow_html=True)
    payments = cited_payments_view(pipeline.payments, lit_refs)
    if not payments.empty:
        st.markdown("**Cited bank payments**")
        st.markdown(_table_html(payments, list(payments["source_ref"])), unsafe_allow_html=True)


def _render_ledger(pipeline: Pipeline, alerts: Sequence[Alert]) -> None:
    """The haunted ledger with its flashlight: the cited rows of the selected alert are lit."""
    st.subheader("📖 The haunted ledger")
    options = flashlight_options(alerts)
    # Allowed here: the radio is not instantiated yet in this run (design 13.3).
    st.session_state["selected_alert"] = reset_selected(
        st.session_state.get("selected_alert"), options
    )
    labels = {alert.id: alert_option_label(alert) for alert in alerts}
    selected = st.radio(
        "🔦 Flashlight: choose an alert to light the rows it cites",
        options,
        key="selected_alert",
        format_func=lambda option: labels.get(option, option),
    )
    lit_refs = lit_refs_for(selected, alerts)
    view = ledger_view(pipeline.invoices, pipeline.reconciliation)
    st.markdown(_table_html(view, lit_refs), unsafe_allow_html=True)
    st.caption("✅ matched · 🕯️ open, not yet due · 💀 overdue · blank: row not usable")
    if lit_refs:
        _render_cited_rows(pipeline, lit_refs)


def _render_alert(alert: Alert, pipeline: Pipeline, hallucinate: bool) -> None:
    """One alert card: title, detector label, explanation, guard badge, refs and captions."""
    explanation = _explain(alert, pipeline, hallucinate)
    has_key = bool(os.environ.get("OPENAI_API_KEY", ""))
    badge = guard_badge(explanation, has_key)
    kind = badge_kind(explanation, has_key)
    with st.container(border=True):
        title = f"{SEVERITY_ICONS[alert.severity]} {html.escape(alert.title)}"
        st.markdown(f'<div class="pi-alert-title">{title}</div>', unsafe_allow_html=True)
        label = LABELS.get(alert.detector, alert.detector)
        st.caption(f"{label} · `{alert.detector}` · severity: {alert.severity}")
        st.markdown(markdown_safe(explanation.text))
        st.markdown(
            f'<span class="pi-badge pi-badge-{kind}">{html.escape(badge)}</span>',
            unsafe_allow_html=True,
        )
        message = verification_message(alert)
        if message is not None:
            st.warning(message, icon="📞")
        for caption in alert_captions(alert):
            st.caption(caption)
        st.markdown("**Source refs:** " + _refs_markdown(alert.source_refs))


def _render_alerts(alerts: Sequence[Alert], pipeline: Pipeline, hallucinate: bool) -> None:
    """The alert list grouped critical, then warning (REQ-PI-49 part 3)."""
    st.subheader("👻 Alerts")
    if not alerts:
        st.write("No alerts: nothing in these files looks like a phantom invoice.")
        return
    groups = group_alerts(alerts)
    for severity in SEVERITY_ORDER:
        if not groups[severity]:
            continue
        st.markdown(f"#### {SEVERITY_ICONS[severity]} {severity.capitalize()}")
        for alert in groups[severity]:
            _render_alert(alert, pipeline, hallucinate)


def _render_quarantine(quarantine: Sequence[dict]) -> None:
    """Collapsible warning section; only rendered when something was quarantined."""
    if not quarantine:
        return
    with st.expander(f"⚠ Quarantined rows ({len(quarantine)})"):
        st.warning("These rows were not analysed. Fix them in the file and upload it again.")
        for message in control_check_messages(quarantine):
            st.error(markdown_safe(message))
        st.caption(MULTI_RATE_NOTE)
        st.dataframe(quarantine_view(quarantine), hide_index=True, width="stretch")


def main() -> None:
    """Render the phantom-invoices page."""
    st.set_page_config(page_title="Phantom Invoices", page_icon="👻", layout="wide")
    st.markdown(f"<style>{HAUNTED_CSS}{APP_CSS}</style>", unsafe_allow_html=True)
    _init_state()
    uploads = _render_sidebar()
    _keep_widgets()

    st.title("👻 Phantom Invoices")
    st.caption("Every figure comes from a cited row of your files. The LLM only explains.")

    sources = _current_sources(uploads)
    if all(source is None for source in sources.values()):
        st.info(
            "Click Load demo data in the sidebar, or upload your invoices, suppliers and payments."
        )
        return

    # UI_DEFAULT_AS_OF only seeds the widget; a detector gets an as_of when the box is ticked.
    fixed = bool(st.session_state["use_as_of"])
    as_of = st.session_state["as_of_date"] if fixed else None
    pipeline = _pipeline(sources, as_of)
    if pipeline is None:
        return

    alerts = ordered_alerts(alert for result in pipeline.results for alert in result.alerts)
    st.info(input_notice(sources["suppliers"] is not None, sources["payments"] is not None))
    for note in pipeline.notes:
        st.caption(markdown_safe(note))
    _render_summary(alerts)
    _render_ledger(pipeline, alerts)
    _render_quarantine(pipeline.quarantine)
    _render_alerts(alerts, pipeline, bool(st.session_state[HALLUCINATE_KEY]))
    st.caption(as_of_note(pipeline.as_of_used, fixed))


# Streamlit executes the script as __main__; importing the module (tests) renders nothing.
if __name__ == "__main__":
    main()
