"""Helpers of the judge-path tests: real demo alerts and a small recorded run built from them.

The alerts and the cited rows come from each app's own ``run_pipeline`` on the committed demo
files, as in ``test_explainer_live_run.py``. The run file of the tests is written to a temporary
folder with the real alert ids, so no id is copied by hand. All data is synthetic.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import pandas as pd

import apps.phantom_invoices.detectors  # noqa: F401  (registers the pi.* detectors)
import apps.vampire_fees.detectors  # noqa: F401  (registers the vf.* detectors)
import apps.zombie_subscriptions.detectors  # noqa: F401  (registers the zs.* detectors)
from apps.phantom_invoices import explain_support as pi_support
from apps.phantom_invoices import settings as pi_settings
from apps.vampire_fees import explain_support as vf_support
from apps.vampire_fees import settings as vf_settings
from apps.zombie_subscriptions import explain_support as zs_support
from apps.zombie_subscriptions import settings as zs_settings
from apps.zombie_subscriptions.detectors.utils import normalise_alias_map, normalise_date_map
from ledger_kit.models import Alert

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "data" / "live_runs"
# The run the apps replay by default (16 Nov, with the placeholder rule).
REPLAY_RUN = RUNS / "2026-11-16_llama3.2-3b_calc2.json"
# The run of 11 Nov: the history that the guard specs cite (kept, pinned, no longer the replay).
COMMITTED_RUN = RUNS / "2026-11-11_llama3.2-3b_demo.json"
OLD_RUNS = (
    RUNS / "2026-11-10_llama3.2-3b.json",
    RUNS / "2026-11-10_llama3.2-3b_run2.json",
    RUNS / "2026-11-10_llama3.2-3b_run3.json",
)
Z1_ALERT_ID = "896d26e24ef956ad447d2c6e871526b92856a6eb6c67bc2f6649e757399fb6c0"

FIXTURE_MODEL = "testmodel:1b (Server 1.0, model id abc123)"
FIXTURE_MODEL_NAME = "testmodel:1b"
FIXTURE_DATE = "2026-11-11"
INVENTED = "98765.43"  # absent from every demo alert and row

SCRIPTS = {
    "zs": "apps/zombie_subscriptions/app.py",
    "pi": "apps/phantom_invoices/app.py",
    "vf": "apps/vampire_fees/app.py",
}


@dataclass(frozen=True)
class Case:
    """What an app hands to the explainer for one alert."""

    prefix: str
    alert: Alert
    rows: pd.DataFrame
    columns: tuple[str, ...] | None


@cache
def _zombie() -> zs_settings.Pipeline:
    """The zombie demo pipeline exactly as the page runs it, CPI context included."""
    config = zs_settings.load_config(ROOT / "apps" / "zombie_subscriptions" / "config.toml")
    demo = zs_settings.demo_inputs(config, ROOT, "csv")
    return zs_settings.run_pipeline(
        demo.statement_name,
        demo.statement_bytes,
        aliases=normalise_alias_map(demo.aliases),
        cancellation_dates=normalise_date_map(demo.cancellation_dates),
        cpi=zs_settings.load_cpi(config, ROOT),
    )


@cache
def _vampire() -> vf_settings.Pipeline:
    config = vf_settings.load_config(ROOT / "apps" / "vampire_fees" / "config.toml")
    demo = vf_settings.demo_inputs(config, ROOT)
    return vf_settings.run_pipeline(
        demo.statement_name,
        demo.statement_bytes,
        vocabulary=vf_settings.load_vocabulary(config),
    )


@cache
def _phantom() -> pi_settings.Pipeline:
    config = pi_settings.load_config(ROOT / "apps" / "phantom_invoices" / "config.toml")
    demo = pi_settings.demo_inputs(config, ROOT)
    return pi_settings.run_pipeline(demo.invoices, demo.suppliers, demo.payments, demo.as_of)


@cache
def cases_of(prefix: str) -> tuple[Case, ...]:
    """Every alert of one app's demo with the rows and the template its page would use."""
    if prefix == "zs":
        pipeline = _zombie()
        ledger = pipeline.debit_ledger
        return tuple(
            Case(prefix, a, ledger[ledger["source_ref"].isin(a.source_refs)], None)
            for a in pipeline.alerts
        )
    if prefix == "vf":
        pipeline_vf = _vampire()
        ledger_vf = pipeline_vf.ledger
        return tuple(
            Case(prefix, a, ledger_vf[ledger_vf["source_ref"].isin(a.source_refs)], None)
            for a in pipeline_vf.alerts
        )
    pipeline_pi = _phantom()
    alerts = [a for result in pipeline_pi.results for a in result.alerts]
    return tuple(
        Case(
            prefix,
            a,
            pi_support.build_explain_rows(
                a, pipeline_pi.invoices, pipeline_pi.suppliers, pipeline_pi.payments
            ),
            tuple(pi_support.ROW_COLUMNS),
        )
        for a in alerts
    )


def template_of(case: Case) -> str:
    """The fixed fallback template the app of `case` uses for its alert."""
    support = {"zs": zs_support, "pi": pi_support, "vf": vf_support}[case.prefix]
    return support.template_for(case.alert)


def find_case(alert_id: str) -> Case | None:
    """Return the demo case whose alert has this id, searching the three apps."""
    for prefix in SCRIPTS:
        for case in cases_of(prefix):
            if case.alert.id == alert_id:
                return case
    return None


def escape_for(prefix: str) -> Callable[[str], str]:
    """The function an app applies to the explanation text before it shows it."""
    return pi_settings.markdown_safe if prefix == "pi" else (lambda text: text)


# --- the small recorded run of the tests --------------------------------------------------------


def card_record(case: Case, text: str) -> dict[str, Any]:
    """One card record in the shape of the 2026-11-11 file."""
    return {
        "id": f"{case.prefix}-card",
        "kind": "card",
        "alert_id": case.alert.id,
        "question_id": None,
        "question": None,
        "raw_answer": text,
        "observed_source": "llm",
        "observed_rejected": [],
    }


def probe_record(case: Case, question_id: str, text: str, rejected: list[str]) -> dict[str, Any]:
    """One probe record; `rejected` is what the guard of the recording day is said to have found."""
    return {
        "id": f"{case.prefix}-{question_id}",
        "kind": "probe",
        "alert_id": case.alert.id,
        "question_id": question_id,
        "question": "text of the question",
        "raw_answer": text,
        "observed_source": "fallback" if rejected else "llm",
        "observed_rejected": rejected,
    }


def accepted_text(case: Case) -> str:
    """A figure-free answer that cites the first row: the guard accepts it."""
    return f"This alert points to {case.alert.source_refs[0]}."


def rejected_text(case: Case) -> str:
    """An answer with a figure that is in no row and no alert: the guard rejects it."""
    return f"This alert points to {case.alert.source_refs[0]}. It will cost {INVENTED} EUR."


def run_document() -> dict[str, Any]:
    """The run file of the tests: for each app, two cards and two probes on real alert ids.

    Alert 0 has an accepted card, a rejected probe `forecast` and an accepted probe `next_month`
    (and no probe `with_fees`); alert 1 has a card the guard rejects.
    """
    records: list[dict[str, Any]] = []
    for prefix in SCRIPTS:
        first, second = cases_of(prefix)[:2]
        records.append(card_record(first, accepted_text(first)))
        records.append(card_record(second, rejected_text(second)))
        records.append(
            probe_record(first, "forecast", f"Over five years: {INVENTED} EUR.", [INVENTED])
        )
        records.append(probe_record(first, "next_month", accepted_text(first), []))
    return {
        "what": "judge-path test run (synthetic)",
        "date": FIXTURE_DATE,
        "model": FIXTURE_MODEL,
        "records": records,
    }


def write_run(path: Path, document: dict[str, Any] | None = None) -> Path:
    """Write the run file of the tests (or `document`) to `path` and return the path."""
    path.write_text(json.dumps(document or run_document(), indent=2), encoding="utf-8")
    return path
