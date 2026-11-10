"""Vampire Fees: the bank fees that drain an account, one coffin per recurring fee (design 8).

Run with: ``streamlit run apps/vampire_fees/app.py``

Pipeline: ingest (ledger_kit) -> the whole ledger -> four deterministic vf.* detectors -> coffins
and alerts. The LLM only writes the explanation text, and its numbers are checked by the guard.
"""

import html
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

# `streamlit run apps/vampire_fees/app.py` puts only this folder on sys.path, so make the
# repository root importable when the package is not installed.
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

import apps.vampire_fees.detectors  # noqa: E402,F401  (registers the vf.* detectors)
from apps.vampire_fees.explain_support import (  # noqa: E402
    HallucinatingStubClient,
    template_for,
)
from apps.vampire_fees.settings import (  # noqa: E402
    DEMO_FORMATS,
    SEVERITY_ORDER,
    SOURCE_KEY,
    CoffinView,
    apply_demo,
    coffin_view,
    demo_inputs,
    group_alerts_by_severity,
    guard_badge,
    load_config,
    load_vocabulary,
    markdown_safe,
    rule_sentences,
    run_pipeline,
    statement_caption,
    summary_view,
    vocabulary_lines,
)
from ledger_kit.explainer import Explanation, explain_with_meta, fill_fallback  # noqa: E402
from ledger_kit.ingestion.norma43_reader import control_check_messages  # noqa: E402
from ledger_kit.live_guard import (  # noqa: E402
    ASK_LABEL,
    LIVE_ASKS_PER_SESSION_LIMIT,
    MSG_LIMIT,
    NOTE_GUARD_SCOPE,
    PANEL_TITLE,
    RAW_LABEL,
    TEMPLATE_LABEL,
    TRICK_QUESTIONS,
    Counts,
    LiveStatus,
    ProbeResult,
    TrickQuestion,
    counter_caption,
    highlight_html,
    intro_line,
    live_status,
    no_answer_message,
    probe_result,
    tally,
    verdict_line,
)
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

# Every session-state key carries the app prefix `vf_` (DN-VF-14), including the source and the
# caches, so the three apps of the showcase never share a key.
LOAD_DEMO_KEY = "vf_load_demo"
HALLUCINATE_KEY = "vf_hallucinate"
EXPLANATIONS_KEY = "vf_explanations"
DEMO_FORMAT_KEY = "vf_demo_format"
UPLOAD_STATEMENT_KEY = "vf_upload_statement"
INGESTION_CACHE_KEY = "vf_ingestion_cache"
KEPT_KEY = "vf_kept"
# Live-guard panel: plain session values (probe results and the counter), not widgets.
LG_RESULTS_KEY = "vf_lg_results"
LG_COUNTS_KEY = "vf_lg_counts"

# Widget state is dropped when a run does not render the widget (the user visited another page of
# the showcase). The widget values are copied to a plain key after the sidebar is drawn and put
# back before the widgets are built (copied from zombie_subscriptions, C6).
WIDGET_KEYS: tuple[str, ...] = (HALLUCINATE_KEY, DEMO_FORMAT_KEY)

# Coffins per row of the crypt.
COFFINS_PER_ROW: int = 3
RECURRING_DETECTOR = "vf.recurring_fee"

# Vampire accent on top of the shared dark theme (the theme file is not edited): dark red,
# brighter red and a blood-dark card. `clip-path` is cosmetic and also clips the card border.
VAMPIRE_CSS = """
<style>
.stApp h1 { color: #c2334d; letter-spacing: 0.04em; }
.vf-coffin {
  background: linear-gradient(180deg, #3a1520 0%, #2a0f16 100%);
  border: 2px solid #9b1c31;
  color: #e8dcc0;
  padding: 26px 20px 20px 20px;
  margin-bottom: 8px;
  text-align: center;
  box-shadow: 0 6px 14px rgba(0, 0, 0, 0.55);
  clip-path: polygon(30% 0, 70% 0, 100% 18%, 88% 100%, 12% 100%, 0 18%);
}
.vf-title { color: #c2334d; font-weight: 700; letter-spacing: 0.08em; }
.vf-cost { color: #c2334d; font-size: 1.25rem; font-weight: 700; }
.vf-line { font-size: 0.95rem; margin: 2px 0; }
.vf-alert-title { font-size: 1.05rem; font-weight: 700; }
.vf-badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 12px;
  font-size: 0.85rem;
  border: 1px solid #9b1c31;
}
.vf-badge-llm { background: #25402f; color: #b9e0a8; border-color: #5f8f5a; }
.vf-badge-template { background: #2a0f16; color: #e8dcc0; }
.vf-badge-unavailable { background: #2a0f16; color: #e8dcc0; }
.vf-badge-rejected { background: #4a1a1f; color: #f0a0ae; border-color: #c2334d; }
</style>
"""


def coffin_html(view: CoffinView) -> str:
    """Return the HTML of one coffin card; every inserted text is escaped (REQ-VF-41)."""
    parts = [
        '<div class="vf-coffin">',
        f'<div class="vf-title">🧛 {html.escape(view.counterparty)}</div>',
        f'<div class="vf-line">{html.escape(view.description)}</div>',
        f'<div class="vf-line">{html.escape(view.interval)}</div>',
        f'<div class="vf-line">Now {html.escape(view.current_amount)}</div>',
        f'<div class="vf-cost">Drains {html.escape(view.yearly_cost)} a year</div>',
        "</div>",
    ]
    return "".join(parts)


def load_demo() -> None:
    """on_click callback of Load demo data: set the source before the rerun builds any widget."""
    apply_demo(
        st.session_state,
        demo_inputs(
            load_config(CONFIG_PATH), ROOT, DEMO_FORMATS[st.session_state[DEMO_FORMAT_KEY]]
        ),
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
    st.session_state.setdefault(HALLUCINATE_KEY, False)
    st.session_state.setdefault(DEMO_FORMAT_KEY, next(iter(DEMO_FORMATS)))
    st.session_state.setdefault(INGESTION_CACHE_KEY, {})
    st.session_state.setdefault(EXPLANATIONS_KEY, {})
    st.session_state.setdefault(LG_RESULTS_KEY, {})
    st.session_state.setdefault(LG_COUNTS_KEY, Counts(0, 0, 0))


def _render_sidebar(config: dict[str, Any]) -> Any:
    """Draw the sidebar widgets and return the uploaded file (None when there is none)."""
    with st.sidebar:
        st.header("Controls")
        st.radio(
            "Demo format",
            list(DEMO_FORMATS),
            key=DEMO_FORMAT_KEY,
            horizontal=True,
            help="CSV or Norma 43: the same demo statement in the format you choose.",
        )
        st.button("Load demo data", key=LOAD_DEMO_KEY, on_click=load_demo)
        st.toggle(
            "Simulate a hallucinating LLM",
            key=HALLUCINATE_KEY,
            help="Replaces the LLM with a stub that invents 99999.99; the guard rejects it.",
        )
        uploaded = st.file_uploader(
            "Bank statement (.csv or Norma 43)",
            type=["csv", "n43", "txt", "aeb", "csb43"],
            key=UPLOAD_STATEMENT_KEY,
        )
        with st.expander("Fee vocabulary in use"):
            st.caption("Read-only. Edit apps/vampire_fees/config.toml to change it.")
            lines = vocabulary_lines(config["vocabulary"])
            st.markdown("\n".join(f"- {markdown_safe(line)}" for line in lines))
        return uploaded


def _current_source(uploaded: Any) -> tuple[str, bytes] | None:
    """Return (file name, bytes) of the uploaded file, else of the loaded demo, else None."""
    if uploaded is not None:
        return uploaded.name, uploaded.getvalue()
    stored = st.session_state.get(SOURCE_KEY)
    if stored:
        _kind, data, name = stored
        return name, data
    return None


def _explain(alert: Alert, ledger: pd.DataFrame, hallucinate: bool) -> Explanation:
    """Explain one alert; cached per (alert.id, client mode) across reruns."""
    cache = st.session_state[EXPLANATIONS_KEY]
    key = (alert.id, "hallucinate" if hallucinate else "real")
    if key not in cache:
        rows = ledger[ledger["source_ref"].isin(alert.source_refs)]
        client = HallucinatingStubClient() if hallucinate else None
        cache[key] = explain_with_meta(
            alert, rows, fallback_template=template_for(alert), client=client
        )
    return cache[key]


def _refs_markdown(refs: Sequence[str]) -> str:
    """Return the source refs as inline code, comma separated."""
    return ", ".join(f"`{ref}`" for ref in refs)


def _render_metrics(alerts: Sequence[Alert]) -> None:
    """Metrics row: the summary figures, then the alert counts per severity (REQ-VF-42)."""
    counts = count_by_severity(alerts)
    summary = summary_view(alerts)
    figures = (
        []
        if summary is None
        else [
            ("Fees found", summary.fee_count),
            ("Total fees", summary.total_fees),
            ("Yearly equivalent", summary.yearly_equivalent),
        ]
    )
    # Two rows so that every value is shown in full: the figures, then the severity counts.
    if figures:
        for column, (label, value) in zip(st.columns(len(figures)), figures, strict=True):
            column.metric(label, value)
    for column, severity in zip(st.columns(len(SEVERITY_ORDER)), SEVERITY_ORDER, strict=True):
        column.metric(f"{SEVERITY_BADGES[severity]} {severity}", counts[severity])


def _render_coffins(alerts: Sequence[Alert]) -> None:
    """One coffin per recurring-fee alert, three per row, with collapsible source refs."""
    st.subheader("🧛 The coffins")
    recurring = [alert for alert in alerts if alert.detector == RECURRING_DETECTOR]
    if not recurring:
        st.caption("No recurring fee found in this statement.")
        return
    for start in range(0, len(recurring), COFFINS_PER_ROW):
        row = recurring[start : start + COFFINS_PER_ROW]
        for column, alert in zip(st.columns(COFFINS_PER_ROW), row, strict=False):
            view = coffin_view(alert)
            with column:
                st.markdown(coffin_html(view), unsafe_allow_html=True)
                with st.expander(f"Source rows ({len(view.source_refs)})"):
                    st.markdown(_refs_markdown(view.source_refs))


def _ask_model(alert: Alert, ledger: pd.DataFrame, question: TrickQuestion) -> None:
    """on_click of Ask the model: one real call, kept apart from the card text (DN-LG-07)."""
    rows = ledger[ledger["source_ref"].isin(alert.source_refs)]
    template = template_for(alert)
    meta = explain_with_meta(
        alert, rows, fallback_template=template, client=None, question=question.text
    )
    result = probe_result(question, meta, fill_fallback(template, alert))
    st.session_state[LG_RESULTS_KEY][(alert.id, question.id)] = result
    st.session_state[LG_COUNTS_KEY] = tally(st.session_state[LG_COUNTS_KEY], result)


def _render_probe_result(result: ProbeResult, status: LiveStatus) -> None:
    """Show the raw answer, the guard verdict and the fixed template of one probe."""
    if result.verdict == "unavailable":
        st.warning(no_answer_message(status.timeout_seconds))
    else:
        st.markdown(f"**{RAW_LABEL}**")
        st.markdown(
            highlight_html(result.raw_answer, result.rejected_numbers), unsafe_allow_html=True
        )
        st.markdown(verdict_line(result))
        st.caption(NOTE_GUARD_SCOPE)
    st.markdown(f"**{TEMPLATE_LABEL}**")
    st.write(result.template_text)


def _render_live_panel(alert: Alert, ledger: pd.DataFrame) -> None:
    """Provoke the LLM: three preset questions to the configured real model (never the stub)."""
    status = live_status(os.environ)
    labels = [q.label for q in TRICK_QUESTIONS]
    counts = st.session_state[LG_COUNTS_KEY]
    with st.expander(PANEL_TITLE):
        st.caption(intro_line(status.model))
        label = st.radio(
            "Trick question",
            labels,
            key=f"vf_lg_q_{alert.id}",
            disabled=not status.enabled,
            label_visibility="collapsed",
        )
        question = TRICK_QUESTIONS[labels.index(label)]
        st.button(
            ASK_LABEL,
            key=f"vf_lg_ask_{alert.id}",
            disabled=not (status.enabled and counts.asked < LIVE_ASKS_PER_SESSION_LIMIT),
            on_click=_ask_model,
            args=(alert, ledger, question),
        )
        result = st.session_state[LG_RESULTS_KEY].get((alert.id, question.id))
        if result is not None:
            _render_probe_result(result, status)
        if not status.enabled:
            st.caption(status.caption)
        elif counts.asked >= LIVE_ASKS_PER_SESSION_LIMIT:
            st.caption(MSG_LIMIT)
        st.caption(counter_caption(counts))


def _render_alert(alert: Alert, ledger: pd.DataFrame, hallucinate: bool) -> None:
    """One alert card: title, detector, explanation, guard badge, refs and cited rows."""
    explanation = _explain(alert, ledger, hallucinate)
    badge = guard_badge(explanation, has_api_key=bool(os.environ.get("OPENAI_API_KEY", "")))
    with st.container(border=True):
        title = f"{SEVERITY_BADGES[alert.severity]} {html.escape(alert.title)}"
        st.markdown(f'<div class="vf-alert-title">{title}</div>', unsafe_allow_html=True)
        st.caption(f"Detector: `{alert.detector}` · severity: {alert.severity}")
        st.write(explanation.text)
        st.markdown(
            f'<span class="vf-badge vf-badge-{badge.kind}">{html.escape(badge.label)}</span>',
            unsafe_allow_html=True,
        )
        st.markdown("**Source refs:** " + _refs_markdown(alert.source_refs))
        with st.expander(f"Source rows ({len(alert.source_refs)})"):
            cited, _missing = rows_for_refs(ledger, alert.source_refs)
            st.dataframe(format_for_display(cited), hide_index=True, width="stretch")
        _render_live_panel(alert, ledger)


def _render_alerts(alerts: Sequence[Alert], ledger: pd.DataFrame, hallucinate: bool) -> None:
    """The alert list grouped critical, warning, info (REQ-VF-43)."""
    st.subheader("🩸 Alerts")
    if not alerts:
        st.write("No alerts: no bank fee was found in this statement.")
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
        for message in control_check_messages(quarantine):
            st.error(markdown_safe(message))
        st.dataframe(quarantine_table(quarantine), hide_index=True, width="stretch")


def main() -> None:
    """Render the vampire-fees page."""
    st.set_page_config(page_title="Vampire Fees", page_icon="🧛", layout="wide")
    st.markdown(VAMPIRE_CSS, unsafe_allow_html=True)
    config = load_config(CONFIG_PATH)
    _init_state()
    uploaded = _render_sidebar(config)
    _keep_widgets()

    st.title("🧛 Vampire Fees")
    st.caption("Every figure comes from a cited row of your statement. The LLM only explains.")

    source = _current_source(uploaded)
    if source is None:
        st.info(
            "Click Load demo data in the sidebar, or upload a bank statement (CSV or Norma 43)."
        )
        return

    name, data = source
    pipeline = run_pipeline(
        name,
        data,
        vocabulary=load_vocabulary(config),
        cache=st.session_state[INGESTION_CACHE_KEY],
    )
    ledger = pipeline.ledger
    debits = int((ledger["flow"] == "debit").sum()) if not ledger.empty else 0
    st.caption(
        statement_caption(
            name,
            pipeline.kind,
            len(ledger),
            debits,
            len(pipeline.quarantine),
            pipeline.skipped_currency,
        )
    )
    for sentence in rule_sentences(pipeline.kind):
        st.caption(sentence)

    alerts = pipeline.alerts
    _render_metrics(alerts)
    _render_quarantine(pipeline.quarantine)
    _render_coffins(alerts)
    _render_alerts(alerts, ledger, bool(st.session_state[HALLUCINATE_KEY]))


# Streamlit executes the script as __main__; importing the module (tests) renders nothing.
if __name__ == "__main__":
    main()
