"""Vampire Fees: the bank fees that drain an account, one coffin per recurring fee (design 8).

Run with: ``streamlit run apps/vampire_fees/app.py``

Pipeline: ingest (ledger_kit) -> the whole ledger -> four deterministic vf.* detectors -> coffins
and alerts. The LLM only writes the explanation text, and its numbers are checked by the guard.
"""

import html
import os
import sys
from collections.abc import Mapping, Sequence
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
from apps.vampire_fees.action_templates import action_for  # noqa: E402
from apps.vampire_fees.explain_support import (  # noqa: E402
    HallucinatingStubClient,
    template_for,
)
from apps.vampire_fees.settings import (  # noqa: E402
    DEMO_FORMATS,
    PEER_SELECT_LABEL,
    SEVERITY_ORDER,
    SOURCE_KEY,
    CoffinView,
    apply_demo,
    coffin_view,
    configured_peer_type,
    default_peer_type,
    demo_inputs,
    explanation_cache_key,
    group_alerts_by_severity,
    guard_badge,
    load_config,
    load_vocabulary,
    markdown_safe,
    peer_attribution_lines,
    peer_context_for,
    peer_sentence_to_add,
    peer_snapshot_path,
    peer_source_line,
    peer_status,
    peer_type_label,
    peer_type_options,
    peer_unavailable_caption,
    read_fee_snapshot,
    rule_sentences,
    run_pipeline,
    statement_caption,
    summary_view,
    vocabulary_lines,
)
from ledger_kit import replay  # noqa: E402
from ledger_kit.explainer import Explanation, explain_with_meta, fill_fallback  # noqa: E402
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
from ledger_kit.public_data import FeeSnapshot  # noqa: E402
from ledger_kit.ui.exorcise import render_exorcise  # noqa: E402
from ledger_kit.ui.first_run import DEMO_FORMAT_CAPTION, should_autoload  # noqa: E402
from ledger_kit.ui.icons import icon  # noqa: E402
from ledger_kit.ui.reference_app import (  # noqa: E402
    count_by_severity,
    format_for_display,
    quarantine_table,
    rows_for_refs,
)
from ledger_kit.ui.signatures import (  # noqa: E402
    VAMPIRE_CAPTION,
    answer_row_note,
    bites_svg,
    card_chips_html,
    card_headings,
    card_source_text,
    chip_source_template,
    ref_with_line_markdown,
    signature_block,
    source_lines_of,
)
from ledger_kit.ui.theme import (  # noqa: E402
    VAMPIRE,
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

# Every session-state key carries the app prefix `vf_` (DN-VF-14), including the source and the
# caches, so the three apps of the showcase never share a key.
LOAD_DEMO_KEY = "vf_load_demo"
HALLUCINATE_KEY = "vf_hallucinate"
EXPLANATIONS_KEY = "vf_explanations"
DEMO_FORMAT_KEY = "vf_demo_format"
UPLOAD_STATEMENT_KEY = "vf_upload_statement"
INGESTION_CACHE_KEY = "vf_ingestion_cache"
KEPT_KEY = "vf_kept"
# Plain session key (not a widget): the demo was already loaded by itself once in this session.
AUTOLOAD_KEY = "vf_autoloaded"
# Live-guard panel: plain session values (probe results and the counter), not widgets.
LG_RESULTS_KEY = "vf_lg_results"
LG_COUNTS_KEY = "vf_lg_counts"
# The account type the fees are compared with (public-fees REQ-PF-20): a select box when the
# snapshot holds two or more types, a plain value otherwise (DN-PF-32).
PEER_TYPE_KEY = "vf_peer_type"
# The comparison each cached explanation was written for: (alert.id, mode) -> the full
# explanation_cache_key. The peer fields are not in the alert id (decision Q7), so an explanation
# is reused only while its comparison is the same (design 9).
EXPLANATION_PEERS_KEY = "vf_explanation_peers"

# Widget state is dropped when a run does not render the widget (the user visited another page of
# the showcase). The widget values are copied to a plain key after the sidebar is drawn and put
# back before the widgets are built (copied from zombie_subscriptions, C6).
WIDGET_KEYS: tuple[str, ...] = (HALLUCINATE_KEY, DEMO_FORMAT_KEY, PEER_TYPE_KEY)

# Coffins per row of the crypt.
COFFINS_PER_ROW: int = 3
RECURRING_DETECTOR = "vf.recurring_fee"

# Vampire accent on top of the shared theme (ledger_kit/ui/theme.py, accent: blood red). The card
# box, the headings and the title colours come from the theme; this block keeps the coffin colours
# and the badge kinds of the app. The theme's `.stApp .vf-coffin` rule (more specific) drops the
# clip-path below so that the coffin is a card like the others; the polygon stays here because
# REQ-VF-41's test pins it.
VAMPIRE_CSS = """
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
.vf-title { font-weight: 700; letter-spacing: 0.08em; }
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
"""


def coffin_html(view: CoffinView) -> str:
    """Return the HTML of one coffin card; every inserted text is escaped (REQ-VF-41)."""
    parts = [
        '<div class="vf-coffin">',
        f'<div class="vf-title">{icon("coffin", size=20, decorative=True)}'
        f"{html.escape(view.counterparty)}</div>",
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


def _autoload_demo() -> None:
    """First run of a session with nothing loaded: load the CSV demo as the button would.

    Runs before any widget is built. The button stays and works as before.
    """
    if should_autoload(st.session_state, AUTOLOAD_KEY, bool(st.session_state.get(SOURCE_KEY))):
        apply_demo(st.session_state, demo_inputs(load_config(CONFIG_PATH), ROOT, "csv"))


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
    st.session_state.setdefault(EXPLANATION_PEERS_KEY, {})
    st.session_state.setdefault(PEER_TYPE_KEY, None)
    st.session_state.setdefault(LG_RESULTS_KEY, {})
    st.session_state.setdefault(LG_COUNTS_KEY, Counts(0, 0, 0))


@st.cache_resource(show_spinner=False)
def _cached_snapshot(path: str, stamp: tuple[int, int]) -> FeeSnapshot | None:
    """Load the fee snapshot once per (path, modification time, size); the object is immutable.

    `stamp` is only part of the cache key, so a refreshed or newly added file is picked up.
    """
    return read_fee_snapshot(Path(path))


def _load_snapshot(config: dict[str, Any]) -> tuple[FeeSnapshot | None, str | None]:
    """Return the fee snapshot (None when unavailable) and the caption to show when it is None."""
    path = peer_snapshot_path(config, ROOT)
    snapshot = None
    if path is not None and path.is_file():
        stat = path.stat()
        snapshot = _cached_snapshot(str(path), (stat.st_mtime_ns, stat.st_size))
    if snapshot is None:
        return None, peer_unavailable_caption(peer_status(config, ROOT))
    return snapshot, None


def _prepare_peer_type(config: dict[str, Any], snapshot: FeeSnapshot | None) -> None:
    """Before the sidebar: keep the chosen account type only when the snapshot still has it."""
    if snapshot is None:
        return
    if st.session_state.get(PEER_TYPE_KEY) not in peer_type_options(snapshot):
        st.session_state[PEER_TYPE_KEY] = default_peer_type(snapshot, configured_peer_type(config))


def _render_sidebar(config: dict[str, Any], snapshot: FeeSnapshot | None = None) -> Any:
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
        st.caption(DEMO_FORMAT_CAPTION)
        st.button("Load demo data", key=LOAD_DEMO_KEY, on_click=load_demo)
        st.toggle(
            "Simulate a hallucinating LLM",
            key=HALLUCINATE_KEY,
            help="Replaces the LLM with a stub that invents 99999.99; the guard rejects it.",
        )
        # With one account type in the snapshot there is nothing to choose (DN-PF-32).
        options = () if snapshot is None else peer_type_options(snapshot)
        if len(options) >= 2:
            st.selectbox(
                PEER_SELECT_LABEL,
                options,
                key=PEER_TYPE_KEY,
                format_func=peer_type_label,
                help="The account type of the declarations the fees are compared with.",
            )
        uploaded = st.file_uploader(
            "Bank statement (.csv or Norma 43)",
            type=["csv", "n43", "txt", "aeb", "csb43"],
            key=UPLOAD_STATEMENT_KEY,
        )
        # Developer inputs: one collapsed expander (expanders do not nest, so the read-only
        # vocabulary list sits in it directly).
        with st.expander("Advanced inputs", expanded=False):
            st.caption("Fee vocabulary in use. Read-only: edit apps/vampire_fees/config.toml.")
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


def _card_recording(alert: Alert, hallucinate: bool) -> replay.Recording | None:
    """Return the recorded card answer to replay, or None.

    None while the stub is on (it wins), while a key is set (live calls) and when the alert has
    no recording or the run file is off.
    """
    if hallucinate or os.environ.get("OPENAI_API_KEY", ""):
        return None
    return replay.card_recording(alert.id)


def _explain(alert: Alert, ledger: pd.DataFrame, hallucinate: bool) -> Explanation:
    """Explain one alert; cached per (alert.id, client mode) and its comparison across reruns.

    The mode is `replay` when a recorded answer goes through the guard instead of a live call.
    The peer fields are not in the alert id, so the cached text is reused only while
    `explanation_cache_key` (id, mode and peer fields) is the one it was written for.
    """
    cache = st.session_state[EXPLANATIONS_KEY]
    written_for = st.session_state[EXPLANATION_PEERS_KEY]
    recording = _card_recording(alert, hallucinate)
    client: Any = None
    if hallucinate:
        mode, client = "hallucinate", HallucinatingStubClient()
    elif recording is not None:
        mode, client = "replay", replay.ReplayClient(recording.raw_answer)
    else:
        mode = "real"
    key = (alert.id, mode)
    full_key = explanation_cache_key(alert, mode)
    if key not in cache or written_for.get(key) != full_key:
        rows = ledger[ledger["source_ref"].isin(alert.source_refs)]
        template = chip_source_template(
            template_for(alert), alert.source_refs, source_lines_of(ledger)
        )
        cache[key] = explain_with_meta(alert, rows, fallback_template=template, client=client)
        written_for[key] = full_key
    return cache[key]


def _refs_markdown(refs: Sequence[str], lines: Mapping[str, int] | None = None) -> str:
    """Return the source refs as inline code, comma separated, each with its line when known."""
    return ", ".join(ref_with_line_markdown(ref, lines) for ref in refs)


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
        column.metric(severity, counts[severity])


def _render_coffins(alerts: Sequence[Alert], lines: Mapping[str, int] | None = None) -> None:
    """One coffin per recurring-fee alert, three per row, with collapsible source refs."""
    show_section("coffin", "The coffins")
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
                    st.markdown(_refs_markdown(view.source_refs, lines))


def _ask_model(alert: Alert, ledger: pd.DataFrame, question: TrickQuestion) -> None:
    """on_click of Ask the model: one real call, or the replay of a recorded answer.

    With a key set the call is today's. With no key and a recording, the recorded text goes
    through the same call and the same guard; no model is called (DN-LG-07, DN-JP-06).
    """
    rows = ledger[ledger["source_ref"].isin(alert.source_refs)]
    template = chip_source_template(template_for(alert), alert.source_refs, source_lines_of(ledger))
    client: Any = None
    if not live_status(os.environ).enabled:
        recording = replay.probe_recording(alert.id, question.id)
        if recording is not None:
            client = replay.ReplayClient(recording.raw_answer)
    meta = explain_with_meta(
        alert, rows, fallback_template=template, client=client, question=question.text
    )
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
            st.write(result.shown_text)
            for line in computed_lines(result.computed):
                st.caption(line)
        st.caption(NOTE_GUARD_SCOPE)
    st.markdown(f"**{TEMPLATE_LABEL}**")
    st.write(card_source_text(result.template_text, refs, lines))


def _render_live_panel(alert: Alert, ledger: pd.DataFrame) -> None:
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
            key=f"vf_lg_q_{alert.id}",
            disabled=not (status.enabled or replayable),
            label_visibility="collapsed",
        )
        question = TRICK_QUESTIONS[labels.index(label)]
        recorded = None if run is None else run.probe(alert.id, question.id)
        can_ask = status.enabled or recorded is not None
        st.button(
            ask_label(live=status.enabled, replayable=replayable),
            key=f"vf_lg_ask_{alert.id}",
            disabled=not (can_ask and not limit_reached(counts)),
            on_click=_ask_model,
            args=(alert, ledger, question),
        )
        if recorded is not None:
            st.caption(replay.panel_caption(recorded))
        result = st.session_state[LG_RESULTS_KEY].get((alert.id, question.id))
        if result is not None:
            _render_probe_result(result, status, alert.source_refs, source_lines_of(ledger))
        if not can_ask:
            st.caption(status.caption)
        elif limit_reached(counts):
            st.caption(MSG_LIMIT)
        st.caption(counter_caption(counts))


def _render_signature(alert: Alert, ledger: pd.DataFrame) -> None:
    """Draw the bites of the cited rows; draw nothing when no row can be drawn."""
    cited, _missing = rows_for_refs(ledger, alert.source_refs)
    drawing = signature_block(bites_svg(cited), VAMPIRE_CAPTION)
    if drawing:
        st.markdown(drawing, unsafe_allow_html=True)


def _render_peer_lines(alert: Alert, explanation: Explanation) -> None:
    """Under the explanation: the comparison when the text lacks it, then its source line.

    Both come from the alert's peer fields, so the comparison is shown whatever the LLM wrote and
    never twice (REQ-PF-19). An alert without peer fields shows neither.
    """
    sentence = peer_sentence_to_add(alert, explanation)
    if sentence is not None:
        st.caption(markdown_safe(sentence))
    source_line = peer_source_line(alert)
    if source_line is not None:
        st.caption(markdown_safe(source_line))


def _render_alert(
    alert: Alert, ledger: pd.DataFrame, hallucinate: bool, heading: str | None = None
) -> None:
    """One alert card: title, detector, explanation, guard badge, refs and cited rows.

    `heading` is what the title line shows (`card_headings`); None shows Alert.title.
    """
    explanation = _explain(alert, ledger, hallucinate)
    recording = _card_recording(alert, hallucinate)
    if recording is not None:
        badge_kind, badge_label = replay.card_badge(recording, explanation)
    else:
        badge = guard_badge(explanation, has_api_key=bool(os.environ.get("OPENAI_API_KEY", "")))
        badge_kind, badge_label = badge.kind, badge.label
    lines = source_lines_of(ledger)
    # The container key only carries the severity into the CSS: a critical card glows.
    with st.container(border=True, key=card_key("vf", alert.severity, alert.id)):
        shown_title = alert.title if heading is None else heading
        title = f"{severity_marker(alert.severity)}{html.escape(shown_title)}"
        st.markdown(f'<div class="vf-alert-title">{title}</div>', unsafe_allow_html=True)
        st.caption(f"Detector: `{alert.detector}` · severity: {alert.severity}")
        st.write(card_source_text(explanation.text, alert.source_refs, lines))
        for line in computed_lines(explanation.computed):
            st.caption(line)
        _render_row_note(explanation, alert, lines)
        st.markdown(
            f'<span class="vf-badge vf-badge-{badge_kind}">{html.escape(badge_label)}</span>',
            unsafe_allow_html=True,
        )
        _render_signature(alert, ledger)
        _render_peer_lines(alert, explanation)
        st.markdown(
            "**Source refs:** " + card_chips_html(alert.source_refs, lines),
            unsafe_allow_html=True,
        )
        with st.expander(f"Source rows ({len(alert.source_refs)})"):
            cited, _missing = rows_for_refs(ledger, alert.source_refs)
            st.dataframe(format_for_display(cited), hide_index=True, width="stretch")
        render_exorcise(
            alert,
            ledger[ledger["source_ref"].isin(alert.source_refs)],
            action_for(alert),
            prefix="vf",
        )
        _render_live_panel(alert, ledger)


def _render_alerts(alerts: Sequence[Alert], ledger: pd.DataFrame, hallucinate: bool) -> None:
    """The alert list grouped critical, warning, info (REQ-VF-43)."""
    show_section("magnifier", "Alerts")
    if not alerts:
        st.write("No alerts: no bank fee was found in this statement.")
        return
    groups = group_alerts_by_severity(alerts)
    # Two cards with the same title show the amount of each in the heading (REQ-AS-42).
    headings = card_headings(alerts)
    for severity in SEVERITY_ORDER:
        if not groups[severity]:
            continue
        show_severity(severity)
        for alert in groups[severity]:
            _render_alert(alert, ledger, hallucinate, headings[alert.id])


def _render_quarantine(quarantine: Sequence[dict]) -> None:
    """Collapsible warning section; only rendered when something was quarantined."""
    if not quarantine:
        return
    with st.expander(f"⚠ Quarantined rows ({len(quarantine)})"):
        st.warning("These rows were not loaded. Fix them in the source file and upload it again.")
        for message in control_check_messages(quarantine):
            st.error(markdown_safe(message))
        st.dataframe(quarantine_table(quarantine), hide_index=True, width="stretch")


def _render_attribution(snapshot: FeeSnapshot | None, unavailable: str | None) -> None:
    """Footer, drawn once: the Banco de España credit while a snapshot is loaded, else why not."""
    if snapshot is None:
        if unavailable:
            st.caption(unavailable)
        return
    for line in peer_attribution_lines(snapshot):
        st.caption(line)


def main() -> None:
    """Render the vampire-fees page."""
    set_page("Vampire Fees", VAMPIRE)
    apply_theme(VAMPIRE, VAMPIRE_CSS)
    config = load_config(CONFIG_PATH)
    _init_state()
    _autoload_demo()
    snapshot, peer_unavailable = _load_snapshot(config)
    _prepare_peer_type(config, snapshot)
    uploaded = _render_sidebar(config, snapshot)
    _keep_widgets()

    show_masthead(VAMPIRE)
    st.title("Vampire Fees")
    st.caption(
        "Every figure comes from, or is computed by plain code from, cited rows of your "
        "statement. The LLM only explains."
    )

    source = _current_source(uploaded)
    if source is None:
        st.info(
            "Click Load demo data in the sidebar, or upload a bank statement (CSV or Norma 43)."
        )
        return

    name, data = source
    peers = (
        None
        if snapshot is None
        else peer_context_for(snapshot, st.session_state[PEER_TYPE_KEY], config)
    )
    pipeline = run_pipeline(
        name,
        data,
        vocabulary=load_vocabulary(config),
        cache=st.session_state[INGESTION_CACHE_KEY],
        peers=peers,
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
    _render_coffins(alerts, source_lines_of(ledger))
    _render_alerts(alerts, ledger, bool(st.session_state[HALLUCINATE_KEY]))
    _render_attribution(snapshot, peer_unavailable)


# Streamlit executes the script as __main__; importing the module (tests) renders nothing.
if __name__ == "__main__":
    main()
