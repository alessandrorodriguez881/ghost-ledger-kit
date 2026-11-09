"""Benchmark runner: pipelines, matching and metrics (benchmark spec, design section 3).

It sends every generated scenario through the same public pipeline the apps run, matches the
alerts to the planted labels with one rule, and counts. It reports; it never passes or fails on
a score and it never changes a detector (REQ-BM-01, REQ-BM-22). Detectors are called only through
``run_all`` (inside the two ``run_pipeline`` functions).

This file holds the pure part (matching, ratios, metrics, attribution), the pipelines with the
detector-error capture, the aggregation into ``results.json``, the rendering of
``docs/benchmark.md`` and the command line (REQ-BM-13 to REQ-BM-17).
"""

import argparse
import json
import logging
import sys
from collections import Counter
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, TextIO

# `python scripts/benchmark.py` puts only scripts/ on sys.path: add the repository root too.
REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = Path(__file__).resolve().parent
for _path in (REPO_ROOT, SCRIPTS_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import generate_benchmark as gen  # noqa: E402

import apps.phantom_invoices.detectors  # noqa: E402,F401  (registers the pi.* detectors)
import apps.phantom_invoices.settings as phantom_settings  # noqa: E402
import apps.zombie_subscriptions.detectors  # noqa: E402,F401  (registers the zs.* detectors)
import apps.zombie_subscriptions.settings as zombie_settings  # noqa: E402
from apps.zombie_subscriptions.detectors.utils import (  # noqa: E402
    normalise_alias_map,
    normalise_date_map,
)
from ledger_kit.detectors import registered_names  # noqa: E402
from ledger_kit.detectors.base import DetectorResult  # noqa: E402

# The logger of the registry: `run_all` hides a detector exception and logs it here (REQ-BM-14).
REGISTRY_LOGGER = "ledger_kit.detectors.registry"

# Printed word for word in results.json and docs/benchmark.md (REQ-BM-12).
MATCHING_RULE = (
    "Within one scenario, alerts are visited in ascending order of (natural order of the first "
    "source_ref, type, source_refs). An alert is a true positive when a still-unmatched label of "
    "the same type exists whose rows share at least one source_ref with the alert; if several "
    "labels qualify, the one with the largest overlap wins, ties by label id. A matched label is "
    "consumed and cannot match a second alert. An alert that matches no label is a false "
    "positive; a label never matched is a false negative. Context rows never match."
)


# --- Records -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class AlertRecord:
    """One alert as the benchmark sees it: scenario, problem type and the rows it cites."""

    scenario: str
    type: str
    refs: tuple[str, ...]
    detector: str = ""


@dataclass(frozen=True)
class LabelRecord:
    """One planted problem; ``context_rows`` are listed but never used for matching."""

    id: str
    scenario: str
    type: str
    rows: tuple[str, ...]
    context_rows: tuple[str, ...] = ()


@dataclass(frozen=True)
class NegativeRecord:
    """One hard negative: rows that must stay silent."""

    id: str
    scenario: str
    kind: str
    rows: tuple[str, ...]


@dataclass(frozen=True)
class MatchResult:
    """Outcome of ``match``: matched pairs, unmatched alerts, unmatched labels."""

    tp: tuple[tuple[AlertRecord, LabelRecord], ...]
    fp: tuple[AlertRecord, ...]
    fn: tuple[LabelRecord, ...]


# --- Matching (REQ-BM-12) ----------------------------------------------------------------------


def natural(ref: str) -> tuple[str, int]:
    """Sort key of a source_ref: ``f.csv:9`` before ``f.csv:10``."""
    file, _sep, row = ref.rpartition(":")
    return (file, int(row)) if row.isdigit() else (ref, -1)


def id_key(identifier: str) -> tuple[str, str, int]:
    """Sort key of a label or negative id: ``zs-0001/L2`` before ``zs-0001/L10``."""
    head, _sep, tail = identifier.rpartition("/")
    digits = tail.lstrip("LN")
    if digits.isdigit():
        return (head, tail[: len(tail) - len(digits)], int(digits))
    return (identifier, "", -1)


def alert_sort_key(alert: AlertRecord) -> tuple[Any, ...]:
    """Visiting order of alerts: scenario, first ref (natural), type, all refs (natural)."""
    first = natural(alert.refs[0]) if alert.refs else ("", -1)
    return (alert.scenario, first, alert.type, tuple(natural(ref) for ref in alert.refs))


def match(alerts: Iterable[AlertRecord], labels: Iterable[LabelRecord]) -> MatchResult:
    """Match alerts to labels with the single rule of REQ-BM-12 (pure, no I/O)."""
    label_list = list(labels)
    by_scenario: dict[str, list[tuple[int, LabelRecord]]] = {}
    for position, label in enumerate(label_list):
        by_scenario.setdefault(label.scenario, []).append((position, label))

    consumed: set[int] = set()
    matched: list[tuple[AlertRecord, LabelRecord]] = []
    unmatched: list[AlertRecord] = []
    for alert in sorted(alerts, key=alert_sort_key):
        cited = set(alert.refs)
        best: tuple[tuple[int, tuple[str, str, int], int], int, LabelRecord] | None = None
        for position, label in by_scenario.get(alert.scenario, ()):
            if position in consumed or label.type != alert.type:
                continue
            overlap = len(cited & set(label.rows))
            if overlap == 0:
                continue
            key = (-overlap, id_key(label.id), position)
            if best is None or key < best[0]:
                best = (key, position, label)
        if best is None:
            unmatched.append(alert)
        else:
            consumed.add(best[1])
            matched.append((alert, best[2]))

    missed = sorted(
        (label for position, label in enumerate(label_list) if position not in consumed),
        key=lambda label: id_key(label.id),
    )
    return MatchResult(tuple(matched), tuple(unmatched), tuple(missed))


# --- Metrics (REQ-BM-13): Decimal, never float -------------------------------------------------


def ratio(numerator: int, denominator: int) -> str | None:
    """Return ``numerator / denominator`` with 4 places (half-up) as text; None without a base."""
    if denominator == 0:
        return None
    quotient = Decimal(numerator) / Decimal(denominator)
    return str(quotient.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def metrics(tp: int, alerts: int, labels: int) -> dict[str, Any]:
    """Counts and ratios of one group: ``fp = alerts - tp``, ``fn = labels - tp``."""
    return {
        "alerts": alerts,
        "fn": labels - tp,
        "fp": alerts - tp,
        "labels": labels,
        "precision": ratio(tp, alerts),
        "recall": ratio(tp, labels),
        "tp": tp,
    }


def noise_figures(
    alerts: Iterable[AlertRecord], noise_scenarios: Collection[str]
) -> dict[str, Any]:
    """Alerts raised on noise-only scenarios: how many, in how many scenarios, per scenario."""
    on_noise = [alert for alert in alerts if alert.scenario in noise_scenarios]
    return {
        "false_alarms_per_noise_scenario": ratio(len(on_noise), len(noise_scenarios)),
        "noise_only_alerts": len(on_noise),
        "noise_only_scenarios_with_alert": len({alert.scenario for alert in on_noise}),
    }


def hard_negative_of(
    alert: AlertRecord, negatives: Iterable[NegativeRecord]
) -> NegativeRecord | None:
    """The first hard negative (id order) of the alert's scenario that shares a ref with it."""
    cited = set(alert.refs)
    candidates = [
        negative
        for negative in negatives
        if negative.scenario == alert.scenario and cited & set(negative.rows)
    ]
    return min(candidates, key=lambda negative: id_key(negative.id), default=None)


def attribute_false_positives(
    false_positives: Iterable[AlertRecord], negatives: Iterable[NegativeRecord]
) -> dict[str, dict[str, int]]:
    """Per hard-negative kind: instances, instances hit by a false alarm, false alarms."""
    negative_list = list(negatives)
    stats = {
        kind: {"false_alarms": 0, "instances": 0, "instances_with_false_alarm": 0}
        for kind in sorted({negative.kind for negative in negative_list})
    }
    for negative in negative_list:
        stats[negative.kind]["instances"] += 1
    hit: set[str] = set()
    for alert in false_positives:
        negative = hard_negative_of(alert, negative_list)
        if negative is not None:
            stats[negative.kind]["false_alarms"] += 1
            hit.add(negative.id)
    for negative in negative_list:
        if negative.id in hit:
            stats[negative.kind]["instances_with_false_alarm"] += 1
            hit.discard(negative.id)
    return stats


# --- Pipelines (REQ-BM-11) ---------------------------------------------------------------------


def alert_type(detector: str, data: Mapping[str, Any]) -> str:
    """``detector`` when the alert data has no variant, else ``detector/variant`` (REQ-BM-05)."""
    variant = data.get("variant")
    return f"{detector}/{variant}" if variant else detector


def records_from_results(scenario: str, results: Iterable[DetectorResult]) -> list[AlertRecord]:
    """Turn the alerts of ``run_all`` results into plain records."""
    return [
        AlertRecord(
            scenario,
            alert_type(alert.detector, alert.data),
            tuple(alert.source_refs),
            alert.detector,
        )
        for result in results
        for alert in result.alerts
    ]


def run_zombie(scenario: gen.Scenario) -> list[AlertRecord]:
    """Run one zombie scenario through the page's own ``run_pipeline`` (D-BM-10)."""
    aliases = normalise_alias_map(scenario.context.get("aliases") or {})
    dates = {
        name: date.fromisoformat(text)
        for name, text in (scenario.context.get("cancellation_dates") or {}).items()
    }
    pipeline = zombie_settings.run_pipeline(
        "statement.csv",
        scenario.files["statement.csv"].encode("utf-8"),
        aliases=aliases,
        cancellation_dates=normalise_date_map(dates),
        cpi=None,  # the CPI context only decorates an alert that already fired (Finance Rule 9)
    )
    return records_from_results(scenario.id, pipeline.results)


def run_phantom(scenario: gen.Scenario) -> list[AlertRecord]:
    """Run one phantom scenario through the page's own ``run_pipeline``."""
    source = phantom_settings.Source
    as_of_text = scenario.context.get("as_of")
    pipeline = phantom_settings.run_pipeline(
        (source("invoices.csv", scenario.files["invoices.csv"].encode("utf-8")),),
        source("suppliers.csv", scenario.files["suppliers.csv"].encode("utf-8")),
        source("payments.csv", scenario.files["payments.csv"].encode("utf-8")),
        None if as_of_text is None else date.fromisoformat(as_of_text),
    )
    return records_from_results(scenario.id, pipeline.results)


# --- Detector errors (REQ-BM-14) ---------------------------------------------------------------


class DetectorErrorHandler(logging.Handler):
    """Collects the names of detectors that ``run_all`` caught raising an exception."""

    def __init__(self) -> None:
        """Listen for warnings only."""
        super().__init__(level=logging.WARNING)
        self.names: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        """Keep the detector name of a ``Detector '<name>' raised ...`` warning."""
        if record.getMessage().startswith("Detector '") and record.args:
            self.names.append(str(record.args[0]))


@dataclass
class RunOutcome:
    """Alerts of a run and, per detector, the number of scenarios in which it raised."""

    alerts: list[AlertRecord] = field(default_factory=list)
    errors: dict[str, int] = field(default_factory=dict)


def run_scenarios(scenarios: Iterable[gen.Scenario]) -> RunOutcome:
    """Run scenarios through their app's pipeline; count detector exceptions per scenario."""
    logger = logging.getLogger(REGISTRY_LOGGER)
    handler = DetectorErrorHandler()
    logger.addHandler(handler)
    outcome = RunOutcome()
    try:
        for scenario in scenarios:
            handler.names.clear()
            run = run_zombie if scenario.app == "zombie" else run_phantom
            outcome.alerts.extend(run(scenario))
            for name in sorted(set(handler.names)):
                outcome.errors[name] = outcome.errors.get(name, 0) + 1
    finally:
        logger.removeHandler(handler)
    outcome.errors = dict(sorted(outcome.errors.items()))
    return outcome


def report_errors(errors: Mapping[str, int], stream: TextIO | None = None) -> int:
    """Print one line per failing detector; return the exit code (1 if any, else 0)."""
    out = sys.stderr if stream is None else stream
    for name, count in sorted(errors.items()):
        print(f"detector {name} raised in {count} scenario(s); results not written", file=out)
    return 1 if errors else 0


# --- Conversion of generator records -----------------------------------------------------------


def label_records(scenarios: Iterable[gen.Scenario]) -> list[LabelRecord]:
    """The labels of the scenarios as plain records."""
    return [
        LabelRecord(label.id, label.scenario, label.type, label.rows, label.context_rows)
        for scenario in scenarios
        for label in scenario.labels
    ]


def negative_records(scenarios: Iterable[gen.Scenario]) -> list[NegativeRecord]:
    """The hard negatives of the scenarios as plain records."""
    return [
        NegativeRecord(negative.id, negative.scenario, negative.kind, negative.rows)
        for scenario in scenarios
        for negative in scenario.negatives
    ]


# --- Results (REQ-BM-13, REQ-BM-15) ------------------------------------------------------------

SCHEMA_VERSION = 1
APPS: tuple[str, ...] = ("zombie", "phantom")
APP_TITLES: Mapping[str, str] = {"zombie": "Zombie Subscriptions", "phantom": "Phantom Invoices"}

# Printed in results.json and docs/benchmark.md. Static text: no digit, so that every number of
# the document comes from the results (REQ-BM-16).
LIMITS: tuple[str, ...] = (
    "All data is synthetic and comes from `scripts/generate_benchmark.py`; real statements and "
    "invoices are messier.",
    "The labels were written by the project team that also wrote the detector requirements; a "
    "pattern nobody thought of is neither planted nor labelled.",
    "Boundary values follow our reading of the requirements; where a requirement is ambiguous "
    "the benchmark follows the documented behaviour.",
    "The shares of clean and planted scenarios and the number of cases per scenario are our "
    "choice; precision and recall describe this mix, not another one.",
    "Only plain-dialect CSV is benchmarked. The Norma bank-statement format, Facturae, European "
    "CSV and the CPI context are covered by other tests.",
    "VAT amounts and totals in the generator use the same money helpers as the detectors; "
    "rounding cases therefore also use hand-checked literal values.",
    "Payments dated after the matching window of the reconciliation are not benchmarked.",
)

# Where the committed files live, and the names used in messages and in an --out-dir.
RESULTS_FILE = REPO_ROOT / "data" / "benchmark" / "results.json"
DOC_FILE = REPO_ROOT / "docs" / "benchmark.md"
RESULTS_SHOWN = "data/benchmark/results.json"
DOC_SHOWN = "docs/benchmark.md"
OUT_RESULTS_NAME = "results.json"
OUT_DOC_NAME = "benchmark.md"


def detector_of(problem_type: str) -> str:
    """The detector name of a problem type (``detector`` or ``detector/variant``)."""
    return problem_type.split("/", 1)[0]


def _type_metrics(
    type_name: str,
    alerts: Sequence[AlertRecord],
    labels: Sequence[LabelRecord],
    matched: Sequence[tuple[AlertRecord, LabelRecord]],
) -> dict[str, Any]:
    """Counts and ratios of one problem type."""
    return metrics(
        sum(1 for _alert, label in matched if label.type == type_name),
        sum(1 for alert in alerts if alert.type == type_name),
        sum(1 for label in labels if label.type == type_name),
    )


def aggregate_app(
    app: str, scenarios: Sequence[gen.Scenario], outcome: RunOutcome, seed: int
) -> dict[str, Any]:
    """Match the alerts of one app to its labels and count (REQ-BM-12, REQ-BM-13, REQ-BM-15)."""
    alerts = outcome.alerts
    labels = label_records(scenarios)
    negatives = negative_records(scenarios)
    result = match(alerts, labels)
    noise_ids = {scenario.id for scenario in scenarios if scenario.noise_only}

    names = (
        set(registered_names(gen.APP_PREFIX[app]))
        | {alert.detector for alert in alerts}
        | {detector_of(label.type) for label in labels}
    )
    detectors: dict[str, Any] = {}
    for name in sorted(names):
        own = [alert for alert in alerts if alert.detector == name]
        entry = metrics(
            sum(1 for alert, _label in result.tp if alert.detector == name),
            len(own),
            sum(1 for label in labels if detector_of(label.type) == name),
        )
        entry.update(noise_figures(own, noise_ids))
        entry["seed"] = seed
        detectors[name] = entry

    catalogue = gen.PROBLEM_TYPES[app]
    seen_types = {alert.type for alert in alerts} | {label.type for label in labels}
    unknown = seen_types - set(catalogue)
    types = {
        name: _type_metrics(name, alerts, labels, result.tp)
        for name in sorted(set(catalogue) | unknown)
    }

    alerts_by = Counter(alert.scenario for alert in alerts)
    labels_by = Counter(label.scenario for label in labels)
    tp_by = Counter(alert.scenario for alert, _label in result.tp)
    detail = [
        {
            "alerts": alerts_by[scenario.id],
            "fn": labels_by[scenario.id] - tp_by[scenario.id],
            "fp": alerts_by[scenario.id] - tp_by[scenario.id],
            "id": scenario.id,
            "labels": labels_by[scenario.id],
            "noise_only": scenario.noise_only,
            "tp": tp_by[scenario.id],
        }
        for scenario in scenarios
    ]

    false_positives = []
    for alert in result.fp:
        negative = hard_negative_of(alert, negatives)
        false_positives.append(
            {
                "hard_negative": None if negative is None else negative.kind,
                "refs": list(alert.refs),
                "scenario": alert.scenario,
                "type": alert.type,
            }
        )
    misses = [
        {
            "label": label.id,
            "rows": list(label.rows),
            "scenario": label.scenario,
            "type": label.type,
        }
        for label in result.fn
    ]

    return {
        "detectors": detectors,
        "errors": dict(outcome.errors),
        "false_positives": false_positives,
        "hard_negatives": attribute_false_positives(result.fp, negatives),
        "misses": misses,
        "noise_only_scenarios": len(noise_ids),
        "scenarios": len(scenarios),
        "scenarios_detail": detail,
        "seed": seed,
        "totals": metrics(len(result.tp), len(alerts), len(labels)),
        "types": types,
    }


def run_benchmark(seed: int, count: int) -> tuple[dict[str, Any], dict[str, int]]:
    """Run both apps; return the results dict and the detector errors (name -> scenarios)."""
    apps: dict[str, Any] = {}
    errors: dict[str, int] = {}
    for app in APPS:
        scenarios = gen.build_scenarios(seed, app, count)
        outcome = run_scenarios(scenarios)
        apps[app] = aggregate_app(app, scenarios, outcome, seed)
        for name, number in outcome.errors.items():
            errors[name] = errors.get(name, 0) + number
    results = {
        "apps": apps,
        "limits": list(LIMITS),
        "matching_rule": MATCHING_RULE,
        "scenarios_per_app": count,
        "schema_version": SCHEMA_VERSION,
        "seed": seed,
    }
    return results, dict(sorted(errors.items()))


def dumps_results(results: Mapping[str, Any]) -> str:
    """The text of results.json: sorted keys, two-space indent, one final LF (REQ-BM-15)."""
    return json.dumps(results, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


# --- docs/benchmark.md (REQ-BM-16) -------------------------------------------------------------

GENERATED_NOTE = "> Generated by `python scripts/benchmark.py`. Do not edit this file."
DETECTOR_HEADER: tuple[str, ...] = (
    "Detector",
    "Planted",
    "Found",
    "Missed",
    "False alarms",
    "Precision",
    "Recall",
    "Clean scenarios with an alert",
)
NEGATIVE_HEADER: tuple[str, ...] = (
    "Hard negative",
    "Instances",
    "Instances with a false alarm",
    "False alarms",
)


def _cell(value: Any) -> str:
    """Text of one table cell: ``null`` is shown as ``n/a``."""
    return "n/a" if value is None else str(value)


def _table(header: Sequence[str], rows: Iterable[Sequence[Any]]) -> list[str]:
    """Markdown table lines."""
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    lines.extend("| " + " | ".join(_cell(value) for value in row) + " |" for row in rows)
    return lines


def render_markdown(results: Mapping[str, Any]) -> str:
    """Render docs/benchmark.md from the results dict only (pure, deterministic)."""
    lines = [
        GENERATED_NOTE,
        "",
        "# Benchmark",
        "",
        "Synthetic scenarios with planted problems and look-alike clean cases are sent through "
        "the same pipelines the apps run. The alerts are matched to the planted labels and "
        "counted. The numbers describe this synthetic mix; they are reported, never used as a "
        "pass mark.",
        "",
        f"Seed `{results['seed']}`, `{results['scenarios_per_app']}` scenarios per app.",
        "",
        "## Reproduce",
        "",
        "```",
        "python scripts/benchmark.py",
        "python scripts/benchmark.py --check",
        "python scripts/benchmark.py --export-scenarios DIR",
        "```",
        "",
        "The first command writes `data/benchmark/results.json` and this file. `--check` runs "
        "the benchmark again and compares the bytes with the committed files without writing. "
        "`--export-scenarios` writes every scenario with its labels for inspection.",
        "",
        "## Matching rule",
        "",
        str(results["matching_rule"]),
    ]
    for app in APPS:
        data = results["apps"][app]
        totals = data["totals"]
        lines += [
            "",
            f"## {APP_TITLES[app]}",
            "",
            f"Seed `{data['seed']}`. `{data['scenarios']}` scenarios, "
            f"`{data['noise_only_scenarios']}` of them without any planted problem. "
            f"Planted `{totals['labels']}`, alerts `{totals['alerts']}`, found `{totals['tp']}`, "
            f"missed `{totals['fn']}`, false alarms `{totals['fp']}`; precision "
            f"`{_cell(totals['precision'])}`, recall `{_cell(totals['recall'])}`.",
            "",
            "### Detectors",
            "",
        ]
        lines += _table(
            DETECTOR_HEADER,
            (
                (
                    name,
                    entry["labels"],
                    entry["tp"],
                    entry["fn"],
                    entry["fp"],
                    entry["precision"],
                    entry["recall"],
                    entry["noise_only_scenarios_with_alert"],
                )
                for name, entry in sorted(data["detectors"].items())
            ),
        )
        lines += ["", "### Hard negatives", ""]
        lines += _table(
            NEGATIVE_HEADER,
            (
                (kind, row["instances"], row["instances_with_false_alarm"], row["false_alarms"])
                for kind, row in sorted(data["hard_negatives"].items())
            ),
        )
    lines += ["", "## Limits", ""]
    lines += [f"- {limit}" for limit in results["limits"]]
    lines += [
        "",
        "## Follow-ups",
        "",
        "Findings and follow-up tasks are listed in `.kiro/specs/benchmark/design.md`.",
    ]
    return "\n".join(lines) + "\n"


# --- Command line (REQ-BM-17) ------------------------------------------------------------------

NEEDS_OUT_DIR = "--seed and --scenarios need --out-dir"
RUN_HINT = "run python scripts/benchmark.py"


def _write(path: Path, text: str) -> None:
    """Write UTF-8 text without any newline conversion."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def check_files(expected: Sequence[tuple[Path, str, str]], stream: TextIO | None = None) -> int:
    """Compare files with fresh text byte for byte; print one line per problem; 0 if equal."""
    out = sys.stderr if stream is None else stream
    code = 0
    for path, shown, text in expected:
        if not path.is_file():
            print(f"{shown} is missing; {RUN_HINT}", file=out)
            code = 1
        elif path.read_bytes() != text.encode("utf-8"):
            print(f"{shown} differs from a fresh run; {RUN_HINT}", file=out)
            code = 1
    return code


def export_scenarios(directory: Path, seed: int, count: int) -> int:
    """Write every scenario under ``directory/<scenario id>/``; return the number written."""
    written = 0
    for app in APPS:
        for scenario in gen.build_scenarios(seed, app, count):
            folder = directory / scenario.id
            for name, text in scenario.files.items():
                _write(folder / name, text)
            document = {
                "context": dict(scenario.context),
                "labels": [
                    {
                        "context_rows": list(label.context_rows),
                        "id": label.id,
                        "rows": list(label.rows),
                        "type": label.type,
                    }
                    for label in scenario.labels
                ],
                "negatives": [
                    {"id": negative.id, "kind": negative.kind, "rows": list(negative.rows)}
                    for negative in scenario.negatives
                ],
                "noise_only": scenario.noise_only,
                "scenario": scenario.id,
            }
            _write(folder / "labels.json", dumps_results(document))
            written += 1
    return written


def build_parser() -> argparse.ArgumentParser:
    """The argument parser of the command line."""
    parser = argparse.ArgumentParser(
        prog="benchmark.py", description="Run the synthetic benchmark of the detectors."
    )
    parser.add_argument("--check", action="store_true", help="compare with the files, no write")
    parser.add_argument("--export-scenarios", metavar="DIR", type=Path, default=None)
    parser.add_argument("--seed", type=int, default=None, help="needs --out-dir")
    parser.add_argument("--scenarios", type=int, default=None, help="needs --out-dir")
    parser.add_argument("--out-dir", metavar="DIR", type=Path, default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the benchmark; exit code 0 ok, 1 files differ or a detector raised, 2 usage."""
    args = build_parser().parse_args(argv)
    custom = args.seed is not None or args.scenarios is not None
    # --seed / --scenarios must never overwrite the committed files: they need --out-dir.
    # --export-scenarios writes only scenario files, so it may use them too.
    if custom and args.out_dir is None and args.export_scenarios is None:
        print(NEEDS_OUT_DIR, file=sys.stderr)
        return 2
    if args.export_scenarios is not None and args.check:
        print("--export-scenarios cannot be combined with --check", file=sys.stderr)
        return 2
    seed = gen.BENCHMARK_SEED if args.seed is None else args.seed
    count = gen.SCENARIOS_PER_APP if args.scenarios is None else args.scenarios
    if count < 1:
        print("--scenarios must be at least 1", file=sys.stderr)
        return 2

    if args.export_scenarios is not None:
        written = export_scenarios(args.export_scenarios, seed, count)
        print(f"wrote {written} scenario folders to {args.export_scenarios}")
        return 0

    results, errors = run_benchmark(seed, count)
    if errors:
        return report_errors(errors)
    results_text = dumps_results(results)
    doc_text = render_markdown(results)
    if args.out_dir is None:
        targets = [
            (RESULTS_FILE, RESULTS_SHOWN, results_text),
            (DOC_FILE, DOC_SHOWN, doc_text),
        ]
    else:
        out_results = args.out_dir / OUT_RESULTS_NAME
        out_doc = args.out_dir / OUT_DOC_NAME
        targets = [
            (out_results, str(out_results), results_text),
            (out_doc, str(out_doc), doc_text),
        ]
    if args.check:
        return check_files(targets)
    for path, shown, text in targets:
        _write(path, text)
        print(f"wrote {shown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
