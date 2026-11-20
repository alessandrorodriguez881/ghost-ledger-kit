"""Zombie subscriptions: a Halloween graveyard of forgotten recurring charges (design §7, §8).

Run with: ``streamlit run apps/zombie_subscriptions/app.py``

Pipeline: ingest (ledger_kit) -> debit rows -> five deterministic zs.* detectors -> tombstones
and alerts. The LLM only writes the explanation text, and its numbers are checked by the guard.
"""

import html
import os
import sys
from collections.abc import Callable, Mapping, MutableMapping, Sequence
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
from apps.zombie_subscriptions.action_templates import action_for  # noqa: E402
from apps.zombie_subscriptions.detectors.utils import (  # noqa: E402
    compute_zombie_cost,
    normalise_alias_map,
    normalise_date_map,
)
from apps.zombie_subscriptions.explain_support import (  # noqa: E402
    HallucinatingStubClient,
    template_for,
)
from apps.zombie_subscriptions.settings import (  # noqa: E402
    DEMO_FORMATS,
    SEVERITY_ORDER,
    apply_demo,
    attribution_lines,
    cpi_sentence_to_add,
    cpi_snapshot_path,
    cpi_source_line,
    cpi_unavailable_caption,
    demo_inputs,
    group_alerts_by_severity,
    guard_badge,
    ingest_statement,
    ledger_currency,
    load_config,
    markdown_safe,
    parse_aliases_text,
    parse_dates_text,
    read_cpi,
    run_pipeline,
    statement_caption,
    tombstone_view,
)
from ledger_kit import replay  # noqa: E402
from ledger_kit.explainer import Explanation, explain_with_meta, fill_fallback  # noqa: E402
from ledger_kit.ingestion.norma43_reader import control_check_messages  # noqa: E402
from ledger_kit.ingestion.sniffer import sniff_format  # noqa: E402
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
from ledger_kit.public_data import CpiSeries  # noqa: E402
from ledger_kit.ui.exorcise import render_exorcise  # noqa: E402
from ledger_kit.ui.first_run import should_autoload  # noqa: E402
from ledger_kit.ui.icons import icon  # noqa: E402
from ledger_kit.ui.reference_app import (  # noqa: E402
    count_by_severity,
    format_for_display,
    quarantine_table,
    rows_for_refs,
)
from ledger_kit.ui.signatures import (  # noqa: E402
    ZOMBIE_CAPTION,
    answer_row_note,
    heartbeat_svg,
    ref_with_line_markdown,
    refs_chips_html,
    signature_block,
    source_lines_of,
)
from ledger_kit.ui.theme import (  # noqa: E402
    ZOMBIE,
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

# Session-state keys carry the app prefix `zs_` where the name could clash with the other app of
# the showcase (REQ-SC-04); the phantom app uses `pi_`.
LOAD_DEMO_KEY = "zs_load_demo"
HALLUCINATE_KEY = "zs_hallucinate"
EXPLANATIONS_KEY = "zs_explanations"
DEMO_FORMAT_KEY = "zs_demo_format"
UPLOAD_STATEMENT_KEY = "zs_upload_statement"
# Plain session key (not a widget): the demo was already loaded by itself once in this session.
AUTOLOAD_KEY = "zs_autoloaded"
# Live-guard panel: plain session values (probe results and the counter), not widgets.
LG_RESULTS_KEY = "zs_lg_results"
LG_COUNTS_KEY = "zs_lg_counts"
# Widget state is dropped when a run does not render the widget (the user visited another page of
# the showcase). The widget values are copied to a plain key after the sidebar is drawn and put
# back before the widgets are built (REQ-SC-05).
WIDGET_KEYS: tuple[str, ...] = (
    "aliases_text",
    "last_used_text",
    "cancel_text",
    HALLUCINATE_KEY,
    DEMO_FORMAT_KEY,
)
KEPT_KEY = "zs_kept"

# Tombstones per row of the graveyard.
TOMBSTONES_PER_ROW: int = 3

_T = TypeVar("_T")

# Halloween graveyard theme (REQ-ZS-35). The colours, the card box and the badges come from the
# shared theme (ledger_kit/ui/theme.py, accent: moss green); only tombstone details stay here.
ZOMBIE_CSS = """
.zs-tombstone .zs-rip svg { flex: none; }
"""


def load_demo() -> None:
    """on_click callback of Load demo data: pre-fill the widget keys before the rerun.

    It runs before the script reruns and builds any widget, so writing the widget keys is
    allowed here (and would raise StreamlitWidgetAlreadyInstantiatedError in an `if` body).
    """
    apply_demo(
        st.session_state,
        demo_inputs(
            load_config(CONFIG_PATH), ROOT, DEMO_FORMATS[st.session_state[DEMO_FORMAT_KEY]]
        ),
    )


def _autoload_demo() -> None:
    """First run of a session with nothing loaded: load the CSV demo as the button would.

    Runs before any widget is built, so the widget keys may be written here. The button stays.
    """
    if should_autoload(st.session_state, AUTOLOAD_KEY, bool(st.session_state.get("source"))):
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
    for key in ("aliases_text", "last_used_text", "cancel_text"):
        st.session_state.setdefault(key, "")
    st.session_state.setdefault(HALLUCINATE_KEY, False)
    st.session_state.setdefault(DEMO_FORMAT_KEY, next(iter(DEMO_FORMATS)))
    st.session_state.setdefault("demo_loaded", False)
    st.session_state.setdefault("ingestion_cache", {})
    st.session_state.setdefault(EXPLANATIONS_KEY, {})
    st.session_state.setdefault(LG_RESULTS_KEY, {})
    st.session_state.setdefault(LG_COUNTS_KEY, Counts(0, 0, 0))


def _render_sidebar() -> Any:
    """Draw the sidebar widgets and return the uploaded file (None when there is none)."""
    with st.sidebar:
        st.header("Controls")
        st.radio(
            "Demo format",
            list(DEMO_FORMATS),
            key=DEMO_FORMAT_KEY,
            horizontal=True,
            help="CSV: the CSV demo statement. Real formats: the same statement as Norma 43.",
        )
        st.button("Load demo data", key=LOAD_DEMO_KEY, on_click=load_demo)
        # Developer inputs: one collapsed expander, the widget keys are unchanged.
        with st.expander("Advanced inputs", expanded=False):
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
        return st.file_uploader(
            "Bank statement (.csv or Norma 43)",
            type=["csv", "n43", "txt", "aeb", "csb43"],
            key=UPLOAD_STATEMENT_KEY,
        )


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
    """Read one statement (CSV or Norma 43; parsing cached by hash); return ledger, quarantine.

    The content picks the reader, not the file extension (REQ-RF-20). The page itself calls
    `run_pipeline`; this wrapper stays for the tests of the ingestion step.
    """
    return ingest_statement(name, data, cache)


def _card_recording(alert: Alert, hallucinate: bool) -> replay.Recording | None:
    """Return the recorded card answer to replay, or None.

    None while the stub is on (it wins), while a key is set (live calls) and when the alert has
    no recording or the run file is off.
    """
    if hallucinate or os.environ.get("OPENAI_API_KEY", ""):
        return None
    return replay.card_recording(alert.id)


def _explain(alert: Alert, ledger: pd.DataFrame, hallucinate: bool) -> Explanation:
    """Explain one alert; cached per (alert.id, client mode) across reruns (design §7).

    The mode is `replay` when a recorded answer goes through the guard instead of a live call.
    """
    cache = st.session_state[EXPLANATIONS_KEY]
    recording = _card_recording(alert, hallucinate)
    client: Any = None
    if hallucinate:
        mode, client = "hallucinate", HallucinatingStubClient()
    elif recording is not None:
        mode, client = "replay", replay.ReplayClient(recording.raw_answer)
    else:
        mode = "real"
    key = (alert.id, mode)
    if key not in cache:
        rows = ledger[ledger["source_ref"].isin(alert.source_refs)]
        cache[key] = explain_with_meta(
            alert, rows, fallback_template=template_for(alert), client=client
        )
    return cache[key]


@st.cache_resource(show_spinner=False)
def _cached_cpi(path: str, stamp: int) -> CpiSeries | None:
    """Load the CPI snapshot once per (path, modification time); the object is immutable.

    `stamp` is only part of the cache key, so a refreshed or newly added file is picked up.
    """
    return read_cpi(Path(path))


def _load_cpi() -> tuple[CpiSeries | None, str]:
    """Return the CPI series (None when unavailable) and the caption to show when it is None."""
    path = cpi_snapshot_path(load_config(CONFIG_PATH), ROOT)
    caption = cpi_unavailable_caption(path)
    if path is None:
        return None, caption
    stamp = path.stat().st_mtime_ns if path.is_file() else -1
    return _cached_cpi(str(path), stamp), caption


def _refs_markdown(refs: Sequence[str], lines: Mapping[str, int] | None = None) -> str:
    """Return the source refs as inline code, comma separated, each with its line when known."""
    return ", ".join(ref_with_line_markdown(ref, lines) for ref in refs)


def _render_summary(alerts: Sequence[Alert], tombstones: int) -> None:
    """Metrics row: tombstones and alerts per severity."""
    counts = count_by_severity(alerts)
    columns = st.columns(len(SEVERITY_ORDER) + 1)
    columns[0].metric("tombstones", tombstones)
    for column, severity in zip(columns[1:], SEVERITY_ORDER, strict=True):
        column.metric(severity, counts[severity])


def _tombstone_line(label: str, value: str) -> str:
    """Return one 'label: value' line of a tombstone; the value is escaped."""
    return f'<div class="zs-line">{label}: <b class="zs-amber">{html.escape(value)}</b></div>'


def _tombstone_html(name: str, died_on: str, cost_since: str, yearly_cost: str) -> str:
    """Return the HTML of one tombstone card; every value is escaped."""
    parts = [
        '<div class="zs-tombstone">',
        f'<div class="zs-rip">{icon("tombstone", size=20, decorative=True)}R.I.P.</div>',
        f'<div class="zs-name">{html.escape(name)}</div>',
        _tombstone_line("Died on", died_on),
        _tombstone_line("Cost since then", cost_since),
        _tombstone_line("Yearly cost", yearly_cost),
        "</div>",
    ]
    return "".join(parts)


def _render_graveyard(
    zombies: Sequence[Any], currency: str, lines: Mapping[str, int] | None = None
) -> None:
    """One tombstone per zombie service, with its yearly cost and collapsible source refs."""
    show_section("tombstone", "The graveyard")
    if not zombies:
        st.caption(
            "Add last-used dates under Advanced inputs in the sidebar to bury a subscription here."
        )
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
                        st.markdown(_refs_markdown(view.source_refs, lines))
                    else:
                        st.caption("No charge after the last-used date.")


def _render_cpi_lines(alert: Alert, explanation: Explanation) -> None:
    """Under the explanation: the CPI sentence when the text lacks it, then the CPI source line.

    Both come from the alert data, so the comparison is shown whatever the LLM wrote and never
    twice (REQ-CPI-18). An alert without CPI keys shows neither.
    """
    sentence = cpi_sentence_to_add(alert, explanation)
    if sentence is not None:
        st.caption(sentence)
    source_line = cpi_source_line(alert)
    if source_line is not None:
        st.caption(source_line)


def _ask_model(alert: Alert, ledger: pd.DataFrame, question: TrickQuestion) -> None:
    """on_click of Ask the model: one real call, or the replay of a recorded answer.

    With a key set the call is today's. With no key and a recording, the recorded text goes
    through the same call and the same guard; no model is called (DN-LG-07, DN-JP-06).
    """
    rows = ledger[ledger["source_ref"].isin(alert.source_refs)]
    template = template_for(alert)
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
    st.write(result.template_text)


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
        # Not written as `st.radio(`: test_zs_real_formats pins the sidebar radio as the only one.
        pick_question = st.radio
        label = pick_question(
            "Trick question",
            labels,
            key=f"zs_lg_q_{alert.id}",
            disabled=not (status.enabled or replayable),
            label_visibility="collapsed",
        )
        question = TRICK_QUESTIONS[labels.index(label)]
        recorded = None if run is None else run.probe(alert.id, question.id)
        can_ask = status.enabled or recorded is not None
        st.button(
            ask_label(live=status.enabled, replayable=replayable),
            key=f"zs_lg_ask_{alert.id}",
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
    """Draw the heartbeat of the cited rows; draw nothing when no row can be drawn."""
    cited, _missing = rows_for_refs(ledger, alert.source_refs)
    drawing = signature_block(
        heartbeat_svg(cited, alert.data.get("cancellation_date")), ZOMBIE_CAPTION
    )
    if drawing:
        st.markdown(drawing, unsafe_allow_html=True)


def _render_alert(alert: Alert, ledger: pd.DataFrame, hallucinate: bool) -> None:
    """One alert card: title, detector, explanation, guard badge, refs and cited rows."""
    explanation = _explain(alert, ledger, hallucinate)
    recording = _card_recording(alert, hallucinate)
    if recording is not None:
        badge_kind, badge_label = replay.card_badge(recording, explanation)
    else:
        badge = guard_badge(explanation, has_api_key=bool(os.environ.get("OPENAI_API_KEY", "")))
        badge_kind, badge_label = badge.kind, badge.label
    # The container key only carries the severity into the CSS: a critical card glows.
    with st.container(border=True, key=card_key("zs", alert.severity, alert.id)):
        title = f"{severity_marker(alert.severity)}{html.escape(alert.title)}"
        st.markdown(f'<div class="zs-alert-title">{title}</div>', unsafe_allow_html=True)
        st.caption(f"Detector: `{alert.detector}` · severity: {alert.severity}")
        st.write(explanation.text)
        for line in computed_lines(explanation.computed):
            st.caption(line)
        _render_row_note(explanation, alert, source_lines_of(ledger))
        st.markdown(
            f'<span class="zs-badge zs-badge-{badge_kind}">{html.escape(badge_label)}</span>',
            unsafe_allow_html=True,
        )
        _render_signature(alert, ledger)
        _render_cpi_lines(alert, explanation)
        st.markdown(
            "**Source refs:** " + refs_chips_html(alert.source_refs, source_lines_of(ledger)),
            unsafe_allow_html=True,
        )
        with st.expander(f"Source rows ({len(alert.source_refs)})"):
            cited, _missing = rows_for_refs(ledger, alert.source_refs)
            st.dataframe(format_for_display(cited), hide_index=True, width="stretch")
        render_exorcise(
            alert,
            ledger[ledger["source_ref"].isin(alert.source_refs)],
            action_for(alert),
            prefix="zs",
        )
        _render_live_panel(alert, ledger)


def _render_alerts(alerts: Sequence[Alert], ledger: pd.DataFrame, hallucinate: bool) -> None:
    """The alert list grouped critical, warning, info (REQ-ZS-37)."""
    show_section("magnifier", "Alerts")
    if not alerts:
        st.write("No alerts: nothing in this statement looks like a zombie.")
        return
    groups = group_alerts_by_severity(alerts)
    for severity in SEVERITY_ORDER:
        if not groups[severity]:
            continue
        show_severity(severity)
        for alert in groups[severity]:
            _render_alert(alert, ledger, hallucinate)


def _render_attribution(cpi: CpiSeries | None, unavailable: str) -> None:
    """Footer, drawn once: the INE attribution while a snapshot is loaded, else why it is not."""
    if cpi is None:
        st.caption(unavailable)
        return
    for line in attribution_lines(cpi):
        st.caption(line)


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
    """Render the zombie-subscriptions page."""
    set_page("Zombie Subscriptions", ZOMBIE)
    apply_theme(ZOMBIE, ZOMBIE_CSS)
    _init_state()
    _autoload_demo()
    uploaded = _render_sidebar()
    _keep_widgets()

    show_masthead(ZOMBIE)
    st.title("Zombie Subscriptions")
    st.caption("Every figure comes from a cited row of your statement. The LLM only explains.")

    source = _current_source(uploaded)
    if source is None:
        st.info(
            "Click Load demo data in the sidebar, or upload a bank statement (CSV or Norma 43)."
        )
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
    cpi, cpi_unavailable = _load_cpi()
    pipeline = run_pipeline(
        name,
        data,
        aliases=aliases,
        cancellation_dates=cancellation_dates,
        cpi=cpi,
        cache=st.session_state["ingestion_cache"],
    )
    debit_ledger, quarantine = pipeline.debit_ledger, pipeline.quarantine
    st.caption(statement_caption(name, sniff_format(data), len(debit_ledger), len(quarantine)))

    alerts = pipeline.alerts
    zombies = compute_zombie_cost(debit_ledger, last_used_dates, aliases=aliases)

    _render_summary(alerts, len(zombies))
    _render_quarantine(quarantine)
    _render_graveyard(zombies, ledger_currency(debit_ledger), source_lines_of(debit_ledger))
    _render_alerts(alerts, debit_ledger, bool(st.session_state[HALLUCINATE_KEY]))
    _render_attribution(cpi, cpi_unavailable)


# Streamlit executes the script as __main__; importing the module (tests) renders nothing.
if __name__ == "__main__":
    main()
