"""Record one real-model run of the three CSV demos, in the format the replay mode reads.

Spec: ``.kiro/specs/model-computes/``, requirements group 7. The scope is the scope of
``data/live_runs/2026-11-11_llama3.2-3b_demo.json``: the CSV demo of each app (Zombie
Subscriptions with the INE CPI context as on its page, Phantom Invoices, Vampire Fees), every
alert card once, plus the three trick questions of ``ledger_kit/live_guard.py`` on the first
critical card of each app. Cards are taken in page order (most severe first, ties in pipeline
order); record ids are a letter per app (Z, P, V) and a two-digit number counted over the whole
run, as in that file.

Each record is asked exactly as the apps ask it: ``explain_with_meta`` with the real client, the
app's fallback template, its row columns and, for a probe, the question. Endpoint, key, model and
timeout come from the same environment variables as the apps (``OPENAI_BASE_URL``,
``OPENAI_API_KEY``, ``LEDGER_KIT_LLM_MODEL``, ``LEDGER_KIT_LLM_TIMEOUT``); temperature 0 and one
attempt with no retry, as in ``ledger_kit/explainer.py``. The raw answer is written exactly as
received, with the seconds it took and the verdict of the guard of today (``observed_*``). The
file is written only at the end, so a failed run leaves nothing half-written.

Run it with the kit's own Python (``.venv\\Scripts\\python.exe`` on Windows), for example with a
local model through Ollama and the variables of ``docs/live-guard.md`` set::

    python scripts/record_live_run.py --out data/live_runs/NEW.json --machine "laptop, CPU"

``--out`` is required and must not exist: the script never overwrites a file. ``--machine`` is
written into ``machine`` and ``--tag`` into ``guard_version`` (for example the commit of the kit).
``--dry-run`` lists every record it would ask (id, app, alert id, title, question) and calls
nothing. A recording is one run of one model: raw answers, not a rate.
"""

import argparse
import json
import os
import platform
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from functools import cache
from pathlib import Path
from typing import Any, TextIO

# `python scripts/record_live_run.py` puts only scripts/ on sys.path: add the repository root too.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd  # noqa: E402

import apps.phantom_invoices.detectors  # noqa: E402,F401  (registers the pi.* detectors)
import apps.phantom_invoices.explain_support as pi_support  # noqa: E402
import apps.phantom_invoices.settings as pi_settings  # noqa: E402
import apps.vampire_fees.detectors  # noqa: E402,F401  (registers the vf.* detectors)
import apps.vampire_fees.explain_support as vf_support  # noqa: E402
import apps.vampire_fees.settings as vf_settings  # noqa: E402
import apps.zombie_subscriptions.detectors  # noqa: E402,F401  (registers the zs.* detectors)
import apps.zombie_subscriptions.explain_support as zs_support  # noqa: E402
import apps.zombie_subscriptions.settings as zs_settings  # noqa: E402
from apps.zombie_subscriptions.detectors.utils import (  # noqa: E402
    normalise_alias_map,
    normalise_date_map,
)
from ledger_kit.explainer import Explanation, explain_with_meta, llm_timeout_seconds  # noqa: E402
from ledger_kit.live_guard import TRICK_QUESTIONS, TrickQuestion, live_status  # noqa: E402
from ledger_kit.models import Alert  # noqa: E402

# The `app` field of a record, and the letter its id starts with; also the order of the run.
APP_ZOMBIE: str = "zombie_subscriptions"
APP_PHANTOM: str = "phantom_invoices"
APP_VAMPIRE: str = "vampire_fees"
APP_ORDER: tuple[str, ...] = (APP_ZOMBIE, APP_PHANTOM, APP_VAMPIRE)
ID_PREFIX: dict[str, str] = {APP_ZOMBIE: "Z", APP_PHANTOM: "P", APP_VAMPIRE: "V"}
ID_DIGITS: int = 2  # Z01, P23, V43

# Card order on the page: most severe first; ties keep the order of the pipeline.
SEVERITY_ORDER: tuple[str, ...] = ("critical", "warning", "info")
# The trick questions are asked on the first card of this severity of each app.
PROBE_SEVERITY: str = "critical"

# `observed_reason` when the guard of the kit names none: an accepted answer has "", a figure
# not found in the cited rows or the alert data has REASON_NOT_FOUND, no answer REASON_NO_ANSWER.
REASON_NOT_FOUND: str = "figure_not_found"
REASON_NO_ANSWER: str = "no_answer"

# The seconds of a record are written with one decimal, as in the 11 Nov file.
SECONDS_DIGITS: int = 1
# Written into `guard_version` and `machine` when the arguments give nothing.
NOT_GIVEN: str = "not given"

# Exit codes: 0 the run (or the dry run) finished, 2 refused before asking anything.
EXIT_OK: int = 0
EXIT_REFUSED: int = 2

RUN_WHAT: str = (
    "Full real-model run of the three CSV demos: every alert card once, plus the three trick "
    "questions on the first critical card of each app. Recorded for the replay mode with "
    "scripts/record_live_run.py."
)
RUN_NOTE: str = (
    "Raw answers exactly as received. observed_* is the verdict of the guard of the kit that "
    "recorded them (observed_reason: why it rejected, empty when accepted; observed_calcs: the "
    "calculations the kit made, empty when none). One run, not a rate."
)
DEMO_SETTING: str = "CSV, CPI context as on the page"

ZS_CONFIG: Path = REPO_ROOT / "apps" / "zombie_subscriptions" / "config.toml"
PI_CONFIG: Path = REPO_ROOT / "apps" / "phantom_invoices" / "config.toml"
VF_CONFIG: Path = REPO_ROOT / "apps" / "vampire_fees" / "config.toml"


@dataclass(frozen=True)
class Card:
    """What an app hands to the explainer for one alert card."""

    app: str
    alert: Alert
    rows: pd.DataFrame
    columns: tuple[str, ...] | None
    template: str


@dataclass(frozen=True)
class Planned:
    """One record of the run: a card, or a trick question on a card."""

    id: str
    card: Card
    question: TrickQuestion | None

    @property
    def kind(self) -> str:
        """`probe` for a trick question, else `card`."""
        return "card" if self.question is None else "probe"


def _page_order(alerts: Sequence[Alert]) -> list[Alert]:
    """The alerts in page order: most severe first, ties in pipeline order (a stable sort)."""
    return sorted(alerts, key=lambda a: SEVERITY_ORDER.index(a.severity))


@cache
def _zombie_cards() -> tuple[Card, ...]:
    """The zombie CSV demo as its page runs it, CPI context included."""
    config = zs_settings.load_config(ZS_CONFIG)
    demo = zs_settings.demo_inputs(config, REPO_ROOT, "csv")
    pipeline = zs_settings.run_pipeline(
        demo.statement_name,
        demo.statement_bytes,
        aliases=normalise_alias_map(demo.aliases),
        cancellation_dates=normalise_date_map(demo.cancellation_dates),
        cpi=zs_settings.load_cpi(config, REPO_ROOT),
    )
    ledger = pipeline.debit_ledger
    return tuple(
        Card(
            APP_ZOMBIE,
            alert,
            ledger[ledger["source_ref"].isin(alert.source_refs)],
            None,
            zs_support.template_for(alert),
        )
        for alert in _page_order(pipeline.alerts)
    )


@cache
def _phantom_cards() -> tuple[Card, ...]:
    """The phantom CSV demo as its page runs it."""
    config = pi_settings.load_config(PI_CONFIG)
    demo = pi_settings.demo_inputs(config, REPO_ROOT)
    pipeline = pi_settings.run_pipeline(demo.invoices, demo.suppliers, demo.payments, demo.as_of)
    alerts = [alert for result in pipeline.results for alert in result.alerts]
    return tuple(
        Card(
            APP_PHANTOM,
            alert,
            pi_support.build_explain_rows(
                alert, pipeline.invoices, pipeline.suppliers, pipeline.payments
            ),
            tuple(pi_support.ROW_COLUMNS),
            pi_support.template_for(alert),
        )
        for alert in _page_order(alerts)
    )


@cache
def _vampire_cards() -> tuple[Card, ...]:
    """The vampire CSV demo as its page runs it."""
    config = vf_settings.load_config(VF_CONFIG)
    demo = vf_settings.demo_inputs(config, REPO_ROOT)
    pipeline = vf_settings.run_pipeline(
        demo.statement_name,
        demo.statement_bytes,
        vocabulary=vf_settings.load_vocabulary(config),
    )
    ledger = pipeline.ledger
    return tuple(
        Card(
            APP_VAMPIRE,
            alert,
            ledger[ledger["source_ref"].isin(alert.source_refs)],
            None,
            vf_support.template_for(alert),
        )
        for alert in _page_order(pipeline.alerts)
    )


def demo_cards() -> dict[str, tuple[Card, ...]]:
    """Every card of the three CSV demos, per app, in page order."""
    return {
        APP_ZOMBIE: _zombie_cards(),
        APP_PHANTOM: _phantom_cards(),
        APP_VAMPIRE: _vampire_cards(),
    }


def plan(cards: Mapping[str, Sequence[Card]] | None = None) -> list[Planned]:
    """The records of a run: per app every card, then the trick questions on its first critical."""
    cards = demo_cards() if cards is None else cards
    planned: list[Planned] = []
    for app in APP_ORDER:
        app_cards = list(cards.get(app, ()))
        asks: list[tuple[Card, TrickQuestion | None]] = [(card, None) for card in app_cards]
        first = next((c for c in app_cards if c.alert.severity == PROBE_SEVERITY), None)
        if first is not None:
            asks.extend((first, question) for question in TRICK_QUESTIONS)
        for card, question in asks:
            number = f"{len(planned) + 1:0{ID_DIGITS}d}"
            planned.append(Planned(ID_PREFIX[app] + number, card, question))
    return planned


def observed_reason(meta: Explanation) -> str:
    """Why the guard rejected the answer; "" when it was accepted."""
    if meta.source == "llm":
        return ""
    if meta.rejected_reason:
        return meta.rejected_reason
    if meta.raw_answer == "":
        return REASON_NO_ANSWER
    return REASON_NOT_FOUND


def observed_calcs(meta: Explanation) -> list[dict[str, str]]:
    """The calculations the kit made for the answer (empty when none)."""
    return [
        {"expression": c.expression, "formula": c.formula, "result": str(c.result)}
        for c in meta.computed
    ]


def ask(planned: Planned, *, client: Any = None) -> Explanation:
    """Ask one record exactly as the app does; `client=None` is the real client of the explainer."""
    card = planned.card
    return explain_with_meta(
        card.alert,
        card.rows,
        fallback_template=card.template,
        client=client,
        row_columns=card.columns,
        question=None if planned.question is None else planned.question.text,
    )


def record(planned: Planned, meta: Explanation, seconds: float) -> dict[str, Any]:
    """One record of the file, in the field order of the 11 Nov file plus the two new fields."""
    alert = planned.card.alert
    question = planned.question
    return {
        "id": planned.id,
        "app": planned.card.app,
        "kind": planned.kind,
        "alert_id": alert.id,
        "detector": alert.detector,
        "severity": alert.severity,
        "title": alert.title,
        "source_refs": list(alert.source_refs),
        "question_id": None if question is None else question.id,
        "question": None if question is None else question.text,
        "seconds": round(seconds, SECONDS_DIGITS),
        "observed_source": meta.source,
        "observed_rejected": list(meta.rejected_numbers),
        "observed_reason": observed_reason(meta),
        "observed_calcs": observed_calcs(meta),
        "raw_answer": meta.raw_answer,
    }


def run_document(
    records: list[dict[str, Any]], *, today: date, machine: str, tag: str
) -> dict[str, Any]:
    """The whole file: the top-level fields of the 11 Nov file and the records."""
    return {
        "what": RUN_WHAT,
        "date": today.isoformat(),
        "model": live_status(os.environ).model,
        "machine": machine or NOT_GIVEN,
        "settings": {
            "temperature": 0,
            "LEDGER_KIT_LLM_TIMEOUT": llm_timeout_seconds(),
            "retries": 0,
            "demo": DEMO_SETTING,
        },
        "guard_version": tag or NOT_GIVEN,
        "note": RUN_NOTE,
        "python": platform.python_version(),
        "records": records,
    }


def _parser() -> argparse.ArgumentParser:
    """The command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Record one real-model run of the three CSV demos for the replay mode."
    )
    parser.add_argument("--out", required=True, type=Path, help="new JSON file to write")
    parser.add_argument("--machine", default="", help="free text written into `machine`")
    parser.add_argument(
        "--tag", default="", help="free text written into `guard_version`, e.g. a commit"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="list the records it would ask; call nothing"
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    client: Any = None,
    clock: Callable[[], float] = time.perf_counter,
    today: date | None = None,
    out: TextIO | None = None,
) -> int:
    """Run the command; `client` replaces the real client (tests only). Returns the exit code."""
    args = _parser().parse_args(argv)
    stream = sys.stdout if out is None else out
    target: Path = args.out

    if args.dry_run:
        planned = plan()
        for item in planned:
            question = "" if item.question is None else item.question.text
            stream.write(
                f"{item.id}\t{item.card.app}\t{item.card.alert.id}\t{item.card.alert.title}"
                f"\t{question}\n"
            )
        stream.write(f"{len(planned)} records would be asked; nothing was called.\n")
        return EXIT_OK

    if target.exists():
        stream.write(f"Refused: {target} already exists; nothing was asked or written.\n")
        return EXIT_REFUSED
    if not target.parent.is_dir():
        stream.write(f"Refused: the folder of {target} does not exist; nothing was asked.\n")
        return EXIT_REFUSED
    if client is None and not os.environ.get("OPENAI_API_KEY"):
        stream.write(
            "Refused: OPENAI_API_KEY is not set (any non-empty value for a local server); "
            "nothing was asked.\n"
        )
        return EXIT_REFUSED

    planned = plan()
    records: list[dict[str, Any]] = []
    for item in planned:
        start = clock()
        meta = ask(item, client=client)
        seconds = clock() - start
        records.append(record(item, meta, seconds))
        question_id = "-" if item.question is None else item.question.id
        stream.write(
            f"{item.id} {item.card.app} {item.kind} {question_id}: {meta.source} "
            f"({round(seconds, SECONDS_DIGITS)} s)\n"
        )
        stream.flush()

    document = run_document(
        records, today=date.today() if today is None else today, machine=args.machine, tag=args.tag
    )
    text = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    try:
        with target.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    except FileExistsError:
        stream.write(f"Refused: {target} appeared during the run; nothing was written.\n")
        return EXIT_REFUSED
    stream.write(f"{len(records)} records written to {target}.\n")
    return EXIT_OK


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    sys.exit(main())
