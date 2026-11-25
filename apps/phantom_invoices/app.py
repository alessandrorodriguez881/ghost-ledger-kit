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
from collections.abc import Mapping, Sequence
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

from apps.phantom_invoices.action_templates import action_for  # noqa: E402
from apps.phantom_invoices.detectors import LABELS  # noqa: E402  (registers the pi.* detectors)
from apps.phantom_invoices.explain_support import (  # noqa: E402
    ROW_COLUMNS,
    HallucinatingStubClient,
    badge_kind,
    build_explain_rows,
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
    lantern_lit_columns,
    lantern_view,
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
from ledger_kit import replay  # noqa: E402
from ledger_kit.explainer import Explanation, fill_fallback  # noqa: E402
from ledger_kit.ingestion.norma43_reader import control_check_messages  # noqa: E402
from ledger_kit.live_guard import (  # noqa: E402
    MSG_LIMIT,
    NOTE_GUARD_SCOPE,
    PANEL_TITLE,
    RAW_LABEL,
    SHOWN_LABEL,
    TEMPLATE_LABEL,
    TRICK_QUESTIONS,
    Counts,
    LiveStatus,
    ProbeResult,
    TrickQuestion,
    ask_label,
    computed_lines,
    counter_caption,
    highlight_html,
    intro_line,
    limit_reached,
    live_status,
    no_answer_message,
    probe_result,
    tally,
    verdict_line,
)
from ledger_kit.models import Alert  # noqa: E402
from ledger_kit.ui.exorcise import render_exorcise  # noqa: E402
from ledger_kit.ui.first_run import DEMO_FORMAT_CAPTION, should_autoload  # noqa: E402
from ledger_kit.ui.signatures import (  # noqa: E402
    PHANTOM_CAPTION,
    answer_row_note,
    chip_source_template,
    lantern_html,
    refs_chips_html,
    signature_block,
    source_lines_of,
)
from ledger_kit.ui.theme import (  # noqa: E402
    PHANTOM,
    apply_theme,
    card_key,
    set_page,
    severity_marker,
    show_masthead,
    show_section,
    show_severity,
)

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
# Plain session key (not a widget): the demo was already loaded by itself once in this session.
AUTOLOAD_KEY = "pi_autoloaded"
# Live-guard panel: plain session values (probe results and the counter), not widgets.
LG_RESULTS_KEY = "pi_lg_results"
LG_COUNTS_KEY = "pi_lg_counts"

# Widget state is dropped when a run does not render the widget (the user visited another page of
# the showcase). The widget values are copied to a plain key after the sidebar is drawn and put
# back before the widgets are built (REQ-SC-05). Uploaded files cannot be kept this way.
WIDGET_KEYS: tuple[str, ...] = ("use_as_of", "as_of_date", HALLUCINATE_KEY, DEMO_FORMAT_KEY)
KEPT_KEY = "pi_kept"

# App-level additions to the haunted-ledger theme (REQ-PI-48): CSS only, no external resource.
# The colours of headings, cards and badges come from the shared theme (spectral teal accent);
# the rules below restate the pieces of HAUNTED_CSS that carried the old green and amber.
APP_CSS = """
.ledger-wrap { overflow-x: auto; margin-bottom: 12px; }
.ledger th, .ledger td { font-size: 0.85rem; white-space: nowrap; padding: 3px 6px; }
.ledger td.supplier { white-space: normal; max-width: 15em; min-width: 9em; }
.ledger th { color: var(--gl-accent-text); border-bottom-color: var(--gl-accent); }
.ledger tr.lit td { box-shadow: inset 0 0 14px 2px var(--gl-accent); }
.ledger tr.lit td:first-child { border-left-color: var(--gl-accent); }
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


def _autoload_demo() -> None:
    """First run of a session with nothing loaded: load the CSV demo as the button would.

    Runs before any widget is built, so the widget keys may be written here. The button stays.
    """
    loaded = any(source is not None for source in st.session_state["sources"].values())
    if should_autoload(st.session_state, AUTOLOAD_KEY, loaded):
        apply_demo(st.session_state, demo_inputs(CONFIG, ROOT, "csv"))


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
    st.session_state.setdefault(LG_RESULTS_KEY, {})
    st.session_state.setdefault(LG_COUNTS_KEY, Counts(0, 0, 0))


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
    st.sidebar.caption(DEMO_FORMAT_CAPTION)
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
    # Developer inputs: one collapsed expander, the widget keys are unchanged.
    with st.sidebar.expander("Advanced inputs", expanded=False):
        st.checkbox(
            "Fix the as-of date",
            key="use_as_of",
            help="Off: the latest date in the data is used to decide which invoices are overdue.",
        )
        st.date_input(
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


def _card_recording(alert: Alert, hallucinate: bool) -> replay.Recording | None:
    """Return the recorded card answer to replay, or None.

    None while the stub is on (it wins), while a key is set (live calls) and when the alert has
    no recording or the run file is off.
    """
    if hallucinate or os.environ.get("OPENAI_API_KEY", ""):
        return None
    return replay.card_recording(alert.id)


def _explain(alert: Alert, pipeline: Pipeline, hallucinate: bool) -> Explanation:
    """Explain one alert; cached per (alert.id, client mode) across reruns (REQ-PI-47).

    The mode is `replay` when a recorded answer goes through the guard instead of a live call.
    """
    cache = st.session_state[EXPLANATIONS_KEY]
    recording = _card_recording(alert, hallucinate)
    key = explanation_key(alert, hallucinate) if recording is None else (alert.id, "replay")
    if key not in cache:
        client: Any = None
        if hallucinate:
            client = HallucinatingStubClient(fill_fallback(template_for(alert), alert))
        elif recording is not None:
            client = replay.ReplayClient(recording.raw_answer)
        cache[key] = explain_alert(
            alert,
            pipeline.invoices,
            pipeline.suppliers,
            pipeline.payments,
            client=client,
            lines=_lines_of(pipeline),
        )
    return cache[key]


def _lines_of(pipeline: Pipeline) -> dict[str, int]:
    """Map each cited source_ref of the three frames to its line, as the chips read it."""
    return source_lines_of(pipeline.invoices, pipeline.suppliers, pipeline.payments)


def _table_html(view: pd.DataFrame, lit_refs: Sequence[str]) -> str:
    """Return the flashlight table of `view`, wrapped so a wide table scrolls sideways."""
    return f'<div class="ledger-wrap">{render_ledger_html(view, lit_refs)}</div>'


def _render_summary(alerts: Sequence[Alert]) -> None:
    """Severity summary row: one metric per severity (REQ-PI-49 part 1)."""
    counts = severity_counts(alerts)
    for column, severity in zip(st.columns(2), ("critical", "warning"), strict=True):
        column.metric(severity, counts[severity])


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
    show_section("candle", "The haunted ledger")
    options = flashlight_options(alerts)
    # Allowed here: the radio is not instantiated yet in this run (design 13.3).
    st.session_state["selected_alert"] = reset_selected(
        st.session_state.get("selected_alert"), options
    )
    labels = {alert.id: alert_option_label(alert) for alert in alerts}
    selected = st.radio(
        "Flashlight: choose an alert to light the rows it cites",
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


def _ask_model(alert: Alert, pipeline: Pipeline, question: TrickQuestion) -> None:
    """on_click of Ask the model: one real call, or the replay of a recorded answer.

    With a key set the call is today's. With no key and a recording, the recorded text goes
    through the same call and the same guard; no model is called (DN-LG-07, DN-JP-06).
    """
    client: Any = None
    if not live_status(os.environ).enabled:
        recording = replay.probe_recording(alert.id, question.id)
        if recording is not None:
            client = replay.ReplayClient(recording.raw_answer)
    lines = _lines_of(pipeline)
    meta = explain_alert(
        alert,
        pipeline.invoices,
        pipeline.suppliers,
        pipeline.payments,
        client=client,
        question=question.text,
        lines=lines,
    )
    template = chip_source_template(template_for(alert), alert.source_refs, lines)
    result = probe_result(question, meta, fill_fallback(template, alert))
    st.session_state[LG_RESULTS_KEY][(alert.id, question.id)] = result
    st.session_state[LG_COUNTS_KEY] = tally(
        st.session_state[LG_COUNTS_KEY], result, replayed=isinstance(client, replay.ReplayClient)
    )


def _render_row_note(explanation: Explanation, alert: Alert, lines: Mapping[str, int]) -> None:
    """Under a model answer: which line of the file each row number of the answer is.

    Nothing under the fixed template, and the answer itself is never edited (REQ-AS-34).
    """
    if explanation.source != "llm":
        return
    note = answer_row_note(explanation.text, alert.source_refs, lines)
    if note:
        st.caption(note)


def _render_probe_result(
    result: ProbeResult,
    status: LiveStatus,
    refs: Sequence[str] = (),
    lines: Mapping[str, int] | None = None,
) -> None:
    """Show the raw answer, the guard verdict and the fixed template of one probe."""
    if result.verdict == "unavailable":
        st.warning(no_answer_message(status.timeout_seconds))
    else:
        st.markdown(f"**{RAW_LABEL}**")
        st.markdown(
            highlight_html(result.raw_answer, result.rejected_numbers), unsafe_allow_html=True
        )
        note = answer_row_note(result.raw_answer, refs, lines)
        if note:
            st.caption(note)
        st.markdown(verdict_line(result))
        if result.computed:
            st.markdown(f"**{SHOWN_LABEL}**")
            st.markdown(markdown_safe(result.shown_text))
            for line in computed_lines(result.computed):
                st.caption(line)
        st.caption(NOTE_GUARD_SCOPE)
    st.markdown(f"**{TEMPLATE_LABEL}**")
    st.markdown(markdown_safe(result.template_text))


def _render_live_panel(alert: Alert, pipeline: Pipeline) -> None:
    """Provoke the LLM: three preset questions to the real model, or a replay of recorded ones.

    With no key, a question that has a recorded answer is enabled and replays it under a caption
    that says so; a question without one stays disabled with today's caption.
    """
    status = live_status(os.environ)
    run = None if status.enabled else replay.load_run()
    replayable = run is not None and run.has_probe(alert.id)
    labels = [q.label for q in TRICK_QUESTIONS]
    counts = st.session_state[LG_COUNTS_KEY]
    with st.expander(PANEL_TITLE):
        intro = intro_line(status.model)
        if run is not None and replayable:
            intro = replay.panel_intro(run)
        st.caption(intro)
        label = st.radio(
            "Trick question",
            labels,
            key=f"pi_lg_q_{alert.id}",
            disabled=not (status.enabled or replayable),
            label_visibility="collapsed",
        )
        question = TRICK_QUESTIONS[labels.index(label)]
        recorded = None if run is None else run.probe(alert.id, question.id)
        can_ask = status.enabled or recorded is not None
        st.button(
            ask_label(live=status.enabled, replayable=replayable),
            key=f"pi_lg_ask_{alert.id}",
            disabled=not (can_ask and not limit_reached(counts)),
            on_click=_ask_model,
            args=(alert, pipeline, question),
        )
        if recorded is not None:
            st.caption(replay.panel_caption(recorded))
        result = st.session_state[LG_RESULTS_KEY].get((alert.id, question.id))
        if result is not None:
            _render_probe_result(
                result,
                status,
                alert.source_refs,
                source_lines_of(pipeline.invoices, pipeline.suppliers, pipeline.payments),
            )
        if not can_ask:
            st.caption(status.caption)
        elif limit_reached(counts):
            st.caption(MSG_LIMIT)
        st.caption(counter_caption(counts))


def _render_signature(alert: Alert, pipeline: Pipeline) -> None:
    """Draw the lantern of the cited rows; draw nothing when no cited row is found."""
    lantern = lantern_html(lantern_view(alert, pipeline), lantern_lit_columns(alert))
    drawing = signature_block(lantern, PHANTOM_CAPTION)
    if drawing:
        st.markdown(drawing, unsafe_allow_html=True)


def _render_alert(alert: Alert, pipeline: Pipeline, hallucinate: bool) -> None:
    """One alert card: title, detector label, explanation, guard badge, refs and captions."""
    explanation = _explain(alert, pipeline, hallucinate)
    recording = _card_recording(alert, hallucinate)
    if recording is not None:
        kind, badge = replay.card_badge(recording, explanation)
    else:
        has_key = bool(os.environ.get("OPENAI_API_KEY", ""))
        badge = guard_badge(explanation, has_key)
        kind = badge_kind(explanation, has_key)
    # The container key only carries the severity into the CSS: a critical card glows.
    with st.container(border=True, key=card_key("pi", alert.severity, alert.id)):
        title = f"{severity_marker(alert.severity)}{html.escape(alert.title)}"
        st.markdown(f'<div class="pi-alert-title">{title}</div>', unsafe_allow_html=True)
        label = LABELS.get(alert.detector, alert.detector)
        st.caption(f"{label} · `{alert.detector}` · severity: {alert.severity}")
        st.markdown(markdown_safe(explanation.text))
        lines = _lines_of(pipeline)
        for line in computed_lines(explanation.computed):
            st.caption(line)
        _render_row_note(explanation, alert, lines)
        st.markdown(
            f'<span class="pi-badge pi-badge-{kind}">{html.escape(badge)}</span>',
            unsafe_allow_html=True,
        )
        _render_signature(alert, pipeline)
        message = verification_message(alert)
        if message is not None:
            st.warning(message)
        for caption in alert_captions(alert):
            st.caption(caption)
        st.markdown(
            "**Source refs:** " + refs_chips_html(alert.source_refs, lines),
            unsafe_allow_html=True,
        )
        render_exorcise(
            alert,
            build_explain_rows(alert, pipeline.invoices, pipeline.suppliers, pipeline.payments),
            action_for(alert),
            prefix="pi",
            row_columns=ROW_COLUMNS,
        )
        _render_live_panel(alert, pipeline)


def _render_alerts(alerts: Sequence[Alert], pipeline: Pipeline, hallucinate: bool) -> None:
    """The alert list grouped critical, then warning (REQ-PI-49 part 3)."""
    show_section("magnifier", "Alerts")
    if not alerts:
        st.write("No alerts: nothing in these files looks like a phantom invoice.")
        return
    groups = group_alerts(alerts)
    for severity in SEVERITY_ORDER:
        if not groups[severity]:
            continue
        show_severity(severity)
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
    set_page("Phantom Invoices", PHANTOM)
    apply_theme(PHANTOM, f"{HAUNTED_CSS}{APP_CSS}")
    _init_state()
    _autoload_demo()
    uploads = _render_sidebar()
    _keep_widgets()

    show_masthead(PHANTOM)
    st.title("Phantom Invoices")
    st.caption(
        "Every figure comes from, or is computed by plain code from, cited rows of your "
        "files. The LLM only explains."
    )

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
