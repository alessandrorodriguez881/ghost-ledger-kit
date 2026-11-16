"""The bridge between the Home page and the demo data of the three apps (REQ-HD-21, REQ-HD-23).

``ledger_kit`` may not import an app and the entry page imports only this module, so the one place
that runs the apps' own pipelines for Home is here. It does two things, both from the committed
demo files and no other input:

- ``tile_signatures``: for each app, the signature drawing of one real alert of the demo data,
  made by the functions of ``ledger_kit/ui/signatures.py`` from the same cited rows as the alert
  card, with the alert's ``source_refs`` as chips. The alert is the first one in the order the
  page lists them (``pick_alert``). Built once per process (``st.cache_data``).
- ``home_moment``: the recorded answer of ``replay.home_example()`` passed through today's number
  guard with the Phantom Invoices demo alert that the record names, exactly as a card replay does.
  What it returns is the guard's verdict, never a copy of a verdict stored in a file.

Nothing here reads the clock, calls a model or opens a connection. A drawing or a moment that
cannot be built is left out and Home renders without it.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path

import pandas as pd
import streamlit as st

import apps.phantom_invoices.detectors  # noqa: F401  (registers the pi.* detectors)
import apps.vampire_fees.detectors  # noqa: F401  (registers the vf.* detectors)
import apps.zombie_subscriptions.detectors  # noqa: F401  (registers the zs.* detectors)
from apps.phantom_invoices import explain_support as pi_support
from apps.phantom_invoices import settings as pi_settings
from apps.vampire_fees import settings as vf_settings
from apps.zombie_subscriptions import settings as zs_settings
from apps.zombie_subscriptions.detectors.utils import normalise_alias_map, normalise_date_map
from ledger_kit import replay
from ledger_kit.models import Alert
from ledger_kit.ui.landing import Moment
from ledger_kit.ui.reference_app import rows_for_refs
from ledger_kit.ui.signatures import (
    PHANTOM_CAPTION,
    TILE_WIDTH,
    VAMPIRE_CAPTION,
    ZOMBIE_CAPTION,
    bites_svg,
    heartbeat_svg,
    lantern_html,
    refs_chips_html,
    signature_block,
)
from ledger_kit.ui.theme import PHANTOM, VAMPIRE, ZOMBIE

ROOT = Path(__file__).resolve().parents[1]
ZOMBIE_CONFIG = ROOT / "apps" / "zombie_subscriptions" / "config.toml"
PHANTOM_CONFIG = ROOT / "apps" / "phantom_invoices" / "config.toml"
VAMPIRE_CONFIG = ROOT / "apps" / "vampire_fees" / "config.toml"

# The order in which every app page lists its alerts: critical first, then warning, then info.
SEVERITY_RANK: dict[str, int] = {"critical": 0, "warning": 1, "info": 2}

# A tile shows at most this many source-ref chips; the rest is one line with the computed count.
TILE_MAX_CHIPS: int = 3

# The lantern of the Phantom tile shows the source ref and at most this many compared columns:
# the tile is narrower than a table of three columns, so one compared column is what fits.
TILE_MAX_COMPARED: int = 1
# Columns of free text: only these may wrap, and only between words. Every other cell (number,
# amount, date, invoice number, source ref, IBAN) stays on one line.
TILE_TEXT_COLUMNS: frozenset[str] = frozenset({"supplier_name", "counterparty"})


def pick_alert(alerts: Iterable[Alert]) -> Alert | None:
    """Return the alert a tile draws: the first one in the order the page lists them.

    That is the first critical alert, else the first warning, else the first info, each in the
    order the detectors raised them; None when there is no alert.
    """
    return min(alerts, key=lambda alert: SEVERITY_RANK[alert.severity], default=None)


def tile_refs_html(refs: Sequence[str]) -> str:
    """Return the chips of a tile: at most ``TILE_MAX_CHIPS``, then one line for the rest.

    The line is ``and N more cited rows`` with N computed from the refs; the alert card keeps
    every chip. '' for no ref.
    """
    chips = refs_chips_html(refs[:TILE_MAX_CHIPS])
    more = len(refs) - TILE_MAX_CHIPS
    if more <= 0:
        return chips
    noun = "row" if more == 1 else "rows"
    return f'{chips}<div class="gl-tile-more">and {more} more cited {noun}</div>'


def _tile(drawing: str, alert: Alert) -> str:
    """Return the drawing of one tile with the chips of the alert's source refs; '' for none."""
    if not drawing:
        return ""
    refs = tile_refs_html(alert.source_refs)
    return f'{drawing}<div class="gl-tile-refs">{refs}</div>'


def _zombie_tile() -> str:
    """The heartbeat of the first alert of the Zombie demo, drawn as its card does."""
    config = zs_settings.load_config(ZOMBIE_CONFIG)
    demo = zs_settings.demo_inputs(config, ROOT, "csv")
    pipeline = zs_settings.run_pipeline(
        demo.statement_name,
        demo.statement_bytes,
        aliases=normalise_alias_map(demo.aliases),
        cancellation_dates=normalise_date_map(demo.cancellation_dates),
        cpi=zs_settings.load_cpi(config, ROOT),
    )
    alert = pick_alert(pipeline.alerts)
    if alert is None:
        return ""
    cited, _missing = rows_for_refs(pipeline.debit_ledger, alert.source_refs)
    drawing = heartbeat_svg(cited, alert.data.get("cancellation_date"), width=TILE_WIDTH)
    return _tile(signature_block(drawing, ZOMBIE_CAPTION), alert)


def _vampire_tile() -> str:
    """The bites of the first alert of the Vampire Fees demo, drawn as its card does."""
    config = vf_settings.load_config(VAMPIRE_CONFIG)
    demo = vf_settings.demo_inputs(config, ROOT)
    pipeline = vf_settings.run_pipeline(
        demo.statement_name,
        demo.statement_bytes,
        vocabulary=vf_settings.load_vocabulary(config),
    )
    alert = pick_alert(pipeline.alerts)
    if alert is None:
        return ""
    cited, _missing = rows_for_refs(pipeline.ledger, alert.source_refs)
    # No date labels on the tile: at tile width they would be far smaller than the tile text.
    return _tile(signature_block(bites_svg(cited, labels=False), VAMPIRE_CAPTION), alert)


@st.cache_resource(show_spinner=False)
def _phantom_pipeline() -> pi_settings.Pipeline:
    """Run the Phantom Invoices demo once per process; the moment and the tile both read it."""
    config = pi_settings.load_config(PHANTOM_CONFIG)
    demo = pi_settings.demo_inputs(config, ROOT)
    return pi_settings.run_pipeline(demo.invoices, demo.suppliers, demo.payments, demo.as_of)


def _phantom_alerts(pipeline: pi_settings.Pipeline) -> list[Alert]:
    """The alerts of the Phantom Invoices page in the order it lists them."""
    found = (alert for result in pipeline.results for alert in result.alerts)
    return pi_settings.ordered_alerts(found)


def tile_lantern_columns(alert: Alert, view: pd.DataFrame) -> list[str]:
    """Return the columns of the tile lantern: the source ref and the first compared column.

    The compared columns are the first ``TILE_MAX_COMPARED`` of the detector's lantern columns
    (``lantern_lit_columns``) that the view of this alert holds, in the order of the mapping. A
    detector that is not in the mapping gives the first of the columns the view shows after the
    row names. Nothing is hand-picked per detector.
    """
    present = [str(column) for column in view.columns]
    lit = pi_settings.lantern_lit_columns(alert)
    if lit is None:
        candidates = [name for name in present if name not in pi_settings.LANTERN_NAMING]
    else:
        candidates = [name for name in lit if name in present]
    return ["source_ref", *candidates[:TILE_MAX_COMPARED]]


def _phantom_tile() -> str:
    """The lantern of the first alert of the Phantom Invoices demo, drawn as its card does.

    The tile is narrow, so its table keeps the source ref and one compared column.
    """
    pipeline = _phantom_pipeline()
    alert = pick_alert(_phantom_alerts(pipeline))
    if alert is None:
        return ""
    view = pi_settings.lantern_view(alert, pipeline)
    columns = tile_lantern_columns(alert, view)
    lit = pi_settings.lantern_lit_columns(alert)
    lantern = lantern_html(
        view[columns], lit, text_columns=[c for c in columns if c in TILE_TEXT_COLUMNS]
    )
    return _tile(signature_block(lantern, PHANTOM_CAPTION), alert)


@st.cache_data(show_spinner=False)
def tile_signatures() -> dict[str, str]:
    """Return the drawing of each app tile by accent key; built once per process.

    A drawing that cannot be built is '' (the tile shows none) and never stops Home.
    """
    builders = (
        (ZOMBIE.key, _zombie_tile),
        (PHANTOM.key, _phantom_tile),
        (VAMPIRE.key, _vampire_tile),
    )
    drawings: dict[str, str] = {}
    for key, build in builders:
        try:
            drawings[key] = build()
        except Exception:  # a drawing that cannot be made must never take Home down
            drawings[key] = ""
    return drawings


def home_moment() -> Moment | None:
    """Return the moment of Home, or None when the recorded example cannot be shown honestly.

    The recording is ``replay.home_example()``; the alert is the Phantom Invoices demo alert it
    names. The recorded text goes through the same call as a card replay, so ``rejected`` and
    ``template`` are today's verdict. None when the file is off, the alert is not found, or the
    guard accepts the answer. Not cached: the example path is read at call time.
    """
    recording = replay.home_example()
    if recording is None or recording.question_text is None:
        return None
    try:
        pipeline = _phantom_pipeline()
        alert = next((a for a in _phantom_alerts(pipeline) if a.id == recording.alert_id), None)
        if alert is None:
            return None
        explanation = pi_support.explain_alert(
            alert,
            pipeline.invoices,
            pipeline.suppliers,
            pipeline.payments,
            client=replay.ReplayClient(recording.raw_answer),
            question=recording.question_text,
        )
    except Exception:  # a moment that cannot be built must never take Home down
        return None
    if explanation.source != "fallback":
        return None
    return Moment(recording, tuple(explanation.rejected_numbers), explanation.text)
