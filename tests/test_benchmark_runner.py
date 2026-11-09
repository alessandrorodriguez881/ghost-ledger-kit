"""Tests of the benchmark runner pipelines and detector-error capture (Task BM5).

The runner must measure what the apps run: it calls the ``run_pipeline`` function of each app on
the written scenario files. These tests pin the two demo alert counts, the credit/debit split and
the capture of a detector that raises. They check plumbing only: no score is asserted anywhere
(REQ-BM-01). All data is synthetic; nothing reads the clock or the network.
"""

import importlib.util
import io
import json
import logging
import platform
import re
import sys
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

import apps.phantom_invoices.detectors  # noqa: F401  (registers the pi.* detectors)
import apps.zombie_subscriptions.detectors  # noqa: F401  (registers the zs.* detectors)
import apps.zombie_subscriptions.settings as zombie_settings
from ledger_kit.detectors import DetectorResult, registered_names
from ledger_kit.detectors import registry as registry_module
from ledger_kit.models import Alert

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
PHANTOM_DEMO = ROOT / "data" / "samples" / "phantom_demo"

# The two demo alert counts, copied from ZS_DEMO_ALERTS and PI_DEMO_ALERTS in
# tests/test_showcase_app.py (PI_DEMO_CRITICAL + PI_DEMO_WARNING = 3 + 6).
ZS_DEMO_ALERTS = 19
PI_DEMO_ALERTS = 9


def _load(name: str, filename: str) -> ModuleType:
    """Load a script of scripts/ by path under the given module name."""
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


gen: Any = _load("generate_benchmark", "generate_benchmark.py")
bm: Any = _load("benchmark_script", "benchmark.py")


@pytest.fixture(autouse=True)
def _keep_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both apps must be registered; a test that replaces a detector does so via monkeypatch."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert registered_names("zs") and registered_names("pi")


def _scenario(app: str, files: Mapping[str, str], context: Mapping[str, Any]) -> Any:
    """A hand-made scenario without labels."""
    return gen.Scenario(
        id="zs-demo" if app == "zombie" else "pi-demo",
        app=app,
        noise_only=False,
        files=dict(files),
        context=dict(context),
        labels=(),
        negatives=(),
        row_facts={},
    )


def _zombie_demo() -> Any:
    """The committed zombie demo statement with the demo aliases and cancellation dates."""
    config = zombie_settings.load_config(ROOT / "apps" / "zombie_subscriptions" / "config.toml")
    demo = zombie_settings.demo_inputs(config, ROOT)
    context = {
        "aliases": {name: list(keys) for name, keys in demo.aliases.items()},
        "cancellation_dates": {name: d.isoformat() for name, d in demo.cancellation_dates.items()},
    }
    text = demo.statement_bytes.decode("utf-8")
    return _scenario("zombie", {"statement.csv": text}, context)


def _phantom_demo() -> Any:
    """The committed phantom demo (CSV flavour); no as_of, so the data decides."""
    files = {
        name: (PHANTOM_DEMO / name).read_text(encoding="utf-8")
        for name in ("invoices.csv", "suppliers.csv", "payments.csv")
    }
    return _scenario("phantom", files, {})


def _types(alerts: list[Any]) -> set[str]:
    """The problem types of a list of alert records."""
    return {a.type for a in alerts}


# --- Tier 1: the demos --------------------------------------------------------------------------


def test_zombie_runner_on_the_demo_gives_the_demo_alerts() -> None:
    alerts = bm.run_zombie(_zombie_demo())

    assert len(alerts) == ZS_DEMO_ALERTS
    assert {a.scenario for a in alerts} == {"zs-demo"}


def test_phantom_runner_on_the_demo_gives_the_demo_alerts() -> None:
    alerts = bm.run_phantom(_phantom_demo())

    assert len(alerts) == PI_DEMO_ALERTS


def test_the_runner_calls_the_same_pipeline_function_as_the_zombie_app() -> None:
    assert bm.zombie_settings.run_pipeline is zombie_settings.run_pipeline


def test_a_six_month_salary_produces_no_alert() -> None:
    rows = "".join(
        f"2025-{month:02d}-28,2450.00,EUR,ACME PAYROLL,Payroll,\n" for month in range(1, 7)
    )
    text = "date,amount,currency,counterparty,description,iban\n" + rows

    alerts = bm.run_zombie(_scenario("zombie", {"statement.csv": text}, {}))

    assert alerts == []


def test_the_runner_hands_the_cancellation_context_to_the_detectors() -> None:
    builder = gen.Builder("zombie", 0)
    gen.z16_cancel_clear(builder, name="GYMPLUS", start=date(2025, 3, 1))
    planted = builder.scenario()
    without = _scenario("zombie", planted.files, {})

    with_context = bm.run_zombie(planted)
    no_context = bm.run_zombie(without)

    assert "zs.charges_after_cancellation" in _types(with_context)
    assert "zs.charges_after_cancellation" not in _types(no_context)


def test_the_runner_hands_as_of_to_the_phantom_pipeline() -> None:
    builder = gen.Builder("phantom", 0)
    gen.p13_overdue_clear(builder)
    scenario = builder.scenario()

    alerts = bm.run_phantom(scenario)

    assert "pi.reconciliation/invoice_overdue" in _types(alerts)


# --- Tier 1: records ----------------------------------------------------------------------------


def test_alert_type_follows_the_variant() -> None:
    with_variant = bm.alert_type("pi.vat_error", {"variant": "total_mismatch"})

    assert with_variant == "pi.vat_error/total_mismatch"
    assert bm.alert_type("zs.price_increase", {}) == "zs.price_increase"
    assert bm.alert_type("zs.price_increase", {"variant": ""}) == "zs.price_increase"


def test_records_from_results_keep_scenario_type_refs_and_detector() -> None:
    alert = Alert(
        detector="pi.vat_error",
        severity="warning",
        title="t",
        source_refs=["invoices.csv:2", "invoices.csv:10"],
        data={"variant": "total_mismatch"},
    )
    other = Alert(
        detector="pi.iban_change",
        severity="critical",
        title="t",
        source_refs=["payments.csv:0"],
        data={},
    )
    results = [
        DetectorResult(name="pi.vat_error", alerts=[alert]),
        DetectorResult(name="pi.iban_change", alerts=[other]),
        DetectorResult(name="pi.empty", alerts=[]),
    ]

    records = bm.records_from_results("pi-0001", results)

    assert records == [
        bm.AlertRecord(
            "pi-0001",
            "pi.vat_error/total_mismatch",
            ("invoices.csv:2", "invoices.csv:10"),
            "pi.vat_error",
        ),
        bm.AlertRecord("pi-0001", "pi.iban_change", ("payments.csv:0",), "pi.iban_change"),
    ]


def test_label_and_negative_records_copy_the_generator_records() -> None:
    scenarios = gen.build_scenarios(gen.BENCHMARK_SEED, "zombie", 3)

    labels = bm.label_records(scenarios)
    negatives = bm.negative_records(scenarios)

    assert len(labels) == sum(len(s.labels) for s in scenarios)
    assert len(negatives) == sum(len(s.negatives) for s in scenarios)
    assert labels[0] == bm.LabelRecord(
        scenarios[1].labels[0].id,
        scenarios[1].id,
        scenarios[1].labels[0].type,
        scenarios[1].labels[0].rows,
        scenarios[1].labels[0].context_rows,
    )


# --- Tier 1: the whole run ----------------------------------------------------------------------


@pytest.mark.parametrize("app", ["zombie", "phantom"])
def test_every_cited_ref_is_a_row_of_its_scenario(app: str) -> None:
    scenarios = gen.build_scenarios(gen.BENCHMARK_SEED, app, 10)

    outcome = bm.run_scenarios(scenarios)

    facts = {s.id: set(s.row_facts) for s in scenarios}
    assert outcome.errors == {}
    assert {a.scenario for a in outcome.alerts} <= set(facts)
    for record in outcome.alerts:
        assert record.refs, record
        assert set(record.refs) <= facts[record.scenario], record


def test_a_noise_only_zombie_scenario_runs_without_error() -> None:
    scenario = gen.build_scenario(gen.BENCHMARK_SEED, "zombie", 0)

    outcome = bm.run_scenarios([scenario])

    assert scenario.noise_only and outcome.errors == {}


# --- Tier 1/2: detector errors (REQ-BM-14) -------------------------------------------------------


def _boom(ledger: Any, context: Any) -> list[Any]:
    """A detector that always raises."""
    raise ValueError("boom")


def test_a_raising_phantom_detector_is_counted_per_scenario(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(registry_module._REGISTRY, "pi.vat_error", _boom)
    scenarios = gen.build_scenarios(gen.BENCHMARK_SEED, "phantom", 3)

    outcome = bm.run_scenarios(scenarios)

    assert outcome.errors == {"pi.vat_error": 3}


def test_a_raising_zombie_detector_is_counted_per_scenario(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(registry_module._REGISTRY, "zs.price_increase", _boom)
    scenarios = gen.build_scenarios(gen.BENCHMARK_SEED, "zombie", 2)

    outcome = bm.run_scenarios(scenarios)

    assert outcome.errors == {"zs.price_increase": 2}


def test_the_other_detectors_still_run_when_one_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    clean = bm.run_scenarios(gen.build_scenarios(gen.BENCHMARK_SEED, "phantom", 3))
    monkeypatch.setitem(registry_module._REGISTRY, "pi.vat_error", _boom)

    broken = bm.run_scenarios(gen.build_scenarios(gen.BENCHMARK_SEED, "phantom", 3))

    kept = [a for a in clean.alerts if a.detector != "pi.vat_error"]
    assert broken.alerts == kept


def test_errors_exit_with_code_1_and_name_the_detector() -> None:
    stream = io.StringIO()

    code = bm.report_errors({"pi.vat_error": 3}, stream)

    assert code == 1
    assert stream.getvalue() == (
        "detector pi.vat_error raised in 3 scenario(s); results not written\n"
    )


def test_no_error_exits_with_code_0_and_prints_nothing() -> None:
    stream = io.StringIO()

    assert bm.report_errors({}, stream) == 0
    assert stream.getvalue() == ""


def test_a_clean_run_reports_an_empty_error_dict() -> None:
    outcome = bm.run_scenarios(gen.build_scenarios(gen.BENCHMARK_SEED, "phantom", 2))

    assert outcome.errors == {}


def test_the_log_handler_is_removed_after_a_run() -> None:
    logger = logging.getLogger(bm.REGISTRY_LOGGER)
    before = list(logger.handlers)

    bm.run_scenarios(gen.build_scenarios(gen.BENCHMARK_SEED, "zombie", 1))

    assert logger.handlers == before


def test_the_log_handler_is_removed_when_a_pipeline_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(scenario: Any) -> list[Any]:
        raise RuntimeError("pipeline failure")

    monkeypatch.setattr(bm, "run_zombie", fail)
    logger = logging.getLogger(bm.REGISTRY_LOGGER)
    before = list(logger.handlers)

    with pytest.raises(RuntimeError, match="pipeline failure"):
        bm.run_scenarios(gen.build_scenarios(gen.BENCHMARK_SEED, "zombie", 1))

    assert logger.handlers == before


def test_only_detector_warnings_are_counted() -> None:
    handler = bm.DetectorErrorHandler()
    logger = logging.getLogger("test_benchmark_runner.fake_registry")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        logger.warning("Detector '%s' raised %s: %s", "zs.x", "ValueError", "boom")
        logger.warning("something else happened: %s", "zs.y")
        logger.info("Detector '%s' raised %s: %s", "zs.z", "ValueError", "info is ignored")
    finally:
        logger.removeHandler(handler)

    assert handler.names == ["zs.x"]


def test_errors_are_sorted_by_detector_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(registry_module._REGISTRY, "pi.vat_error", _boom)
    monkeypatch.setitem(registry_module._REGISTRY, "pi.duplicate_invoice", _boom)

    outcome = bm.run_scenarios(gen.build_scenarios(gen.BENCHMARK_SEED, "phantom", 1))

    assert list(outcome.errors) == ["pi.duplicate_invoice", "pi.vat_error"]


# --- Task BM6: results, documentation, command line --------------------------------------------

REDUCED = 10  # scenarios per app of the reduced runs; indices 0 and 5 are noise only
TOP_LEVEL_KEYS = [
    "apps",
    "limits",
    "matching_rule",
    "scenarios_per_app",
    "schema_version",
    "seed",
]
APP_KEYS = {
    "detectors",
    "errors",
    "false_positives",
    "hard_negatives",
    "misses",
    "noise_only_scenarios",
    "scenarios",
    "scenarios_detail",
    "seed",
    "totals",
    "types",
}
DETECTOR_KEYS = {
    "alerts",
    "false_alarms_per_noise_scenario",
    "fn",
    "fp",
    "labels",
    "noise_only_alerts",
    "noise_only_scenarios_with_alert",
    "precision",
    "recall",
    "seed",
    "tp",
}
GENERATED_FIRST_LINE = "> Generated by `python scripts/benchmark.py`. Do not edit this file."


@pytest.fixture(scope="module")
def reduced() -> dict[str, Any]:
    """One reduced run (10 scenarios per app) at the committed seed, shared by the tests."""
    results, errors = bm.run_benchmark(gen.BENCHMARK_SEED, REDUCED)
    assert errors == {}
    return results


def _digit_runs(value: Any) -> set[str]:
    """Every run of digits in the keys and values of a nested structure."""
    if isinstance(value, Mapping):
        found: set[str] = set()
        for key, item in value.items():
            found |= _digit_runs(key) | _digit_runs(item)
        return found
    if isinstance(value, list | tuple):
        return set().union(*(_digit_runs(item) for item in value)) if value else set()
    return set(re.findall(r"\d+", str(value)))


def _detector(
    labels: int, tp: int, alerts: int, precision: str | None, recall: str | None
) -> dict[str, Any]:
    """A hand-made per-detector entry of the results."""
    return {
        "alerts": alerts,
        "false_alarms_per_noise_scenario": "0.2500",
        "fn": labels - tp,
        "fp": alerts - tp,
        "labels": labels,
        "noise_only_alerts": 3,
        "noise_only_scenarios_with_alert": 2,
        "precision": precision,
        "recall": recall,
        "seed": 5,
        "tp": tp,
    }


def _handmade_app(seed: int) -> dict[str, Any]:
    """A hand-made app block with distinctive numbers and one ``null`` ratio."""
    return {
        "detectors": {
            "zs.price_increase": _detector(10, 7, 9, "0.7778", "0.7000"),
            "zs.recurring_charge": _detector(0, 0, 0, None, None),
        },
        "errors": {},
        "false_positives": [],
        "hard_negatives": {
            "weekly_groceries_irregular": {
                "false_alarms": 4,
                "instances": 15,
                "instances_with_false_alarm": 2,
            }
        },
        "misses": [],
        "noise_only_scenarios": 40,
        "scenarios": 200,
        "scenarios_detail": [],
        "seed": seed,
        "totals": {
            "alerts": 9,
            "fn": 3,
            "fp": 2,
            "labels": 10,
            "precision": "0.7778",
            "recall": "0.7000",
            "tp": 7,
        },
        "types": {},
    }


def _handmade_results(seed: int = 2026, count: int = 200, limits: int = 6) -> dict[str, Any]:
    """A hand-made results dict; ``limits`` strings without digits."""
    names = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta"]
    return {
        "apps": {"zombie": _handmade_app(seed), "phantom": _handmade_app(seed)},
        "limits": [f"{name} limit" for name in names[:limits]],
        "matching_rule": bm.MATCHING_RULE,
        "scenarios_per_app": count,
        "schema_version": 1,
        "seed": seed,
    }


def _committed_bytes() -> list[bytes | None]:
    """The committed results and documentation bytes, None where a file does not exist yet."""
    paths = (bm.RESULTS_FILE, bm.DOC_FILE)
    return [path.read_bytes() if path.is_file() else None for path in paths]


# --- Tier 1: aggregation ------------------------------------------------------------------------


def _hand_scenario(scenario_id: str, noise_only: bool, labels: tuple, negatives: tuple) -> Any:
    """A scenario with labels and hard negatives but no files."""
    return gen.Scenario(
        id=scenario_id,
        app="zombie",
        noise_only=noise_only,
        files={},
        context={},
        labels=labels,
        negatives=negatives,
        row_facts={},
    )


def test_aggregate_app_counts_a_hand_made_run() -> None:
    price, recurring = "zs.price_increase", "zs.recurring_charge"
    scenarios = [
        _hand_scenario("zs-t0", True, (), ()),
        _hand_scenario(
            "zs-t1",
            False,
            (
                gen.Label("zs-t1/L1", "zs-t1", price, ("statement.csv:1",)),
                gen.Label("zs-t1/L2", "zs-t1", gen.TRIAL, ("statement.csv:7",)),
            ),
            (gen.Negative("zs-t1/N1", "zs-t1", "k", ("statement.csv:5",)),),
        ),
    ]
    outcome = bm.RunOutcome(
        alerts=[
            bm.AlertRecord("zs-t1", price, ("statement.csv:1",), price),
            bm.AlertRecord("zs-t1", recurring, ("statement.csv:5",), recurring),
            bm.AlertRecord("zs-t0", price, ("statement.csv:2",), price),
        ]
    )

    data = bm.aggregate_app("zombie", scenarios, outcome, 9)

    assert set(data) == APP_KEYS
    assert data["totals"] == {
        "alerts": 3,
        "fn": 1,
        "fp": 2,
        "labels": 2,
        "precision": "0.3333",
        "recall": "0.5000",
        "tp": 1,
    }
    assert data["detectors"][price] == {
        "alerts": 2,
        "false_alarms_per_noise_scenario": "1.0000",
        "fn": 0,
        "fp": 1,
        "labels": 1,
        "noise_only_alerts": 1,
        "noise_only_scenarios_with_alert": 1,
        "precision": "0.5000",
        "recall": "1.0000",
        "seed": 9,
        "tp": 1,
    }
    assert data["detectors"][recurring]["recall"] is None
    assert data["detectors"][recurring]["precision"] == "0.0000"
    assert data["types"][price]["tp"] == 1 and data["types"][gen.TRIAL]["fn"] == 1
    assert set(data["types"]) == set(gen.PROBLEM_TYPES["zombie"])
    assert data["hard_negatives"] == {
        "k": {"false_alarms": 1, "instances": 1, "instances_with_false_alarm": 1}
    }
    assert data["false_positives"] == [
        {
            "hard_negative": None,
            "refs": ["statement.csv:2"],
            "scenario": "zs-t0",
            "type": price,
        },
        {
            "hard_negative": "k",
            "refs": ["statement.csv:5"],
            "scenario": "zs-t1",
            "type": recurring,
        },
    ]
    assert data["misses"] == [
        {
            "label": "zs-t1/L2",
            "rows": ["statement.csv:7"],
            "scenario": "zs-t1",
            "type": gen.TRIAL,
        }
    ]
    assert data["scenarios_detail"] == [
        {"alerts": 1, "fn": 0, "fp": 1, "id": "zs-t0", "labels": 0, "noise_only": True, "tp": 0},
        {"alerts": 2, "fn": 1, "fp": 1, "id": "zs-t1", "labels": 2, "noise_only": False, "tp": 1},
    ]
    assert (data["scenarios"], data["noise_only_scenarios"], data["seed"]) == (2, 1, 9)


def test_an_alert_type_outside_the_catalogue_is_a_false_positive_with_zero_labels() -> None:
    scenarios = [_hand_scenario("zs-t1", False, (), ())]
    alert = bm.AlertRecord("zs-t1", "zs.invented/x", ("statement.csv:1",), "zs.invented")
    outcome = bm.RunOutcome(alerts=[alert])

    data = bm.aggregate_app("zombie", scenarios, outcome, 1)

    assert data["types"]["zs.invented/x"]["labels"] == 0
    assert data["types"]["zs.invented/x"]["fp"] == 1
    assert data["detectors"]["zs.invented"]["alerts"] == 1
    assert data["totals"]["fp"] == 1


# --- Tier 1: the results of a reduced run -------------------------------------------------------


def test_the_results_have_the_top_level_keys_in_order(reduced: dict[str, Any]) -> None:
    loaded = json.loads(bm.dumps_results(reduced))

    assert list(loaded) == TOP_LEVEL_KEYS
    assert loaded["schema_version"] == 1
    assert loaded["seed"] == gen.BENCHMARK_SEED
    assert loaded["scenarios_per_app"] == REDUCED
    assert loaded["matching_rule"] == bm.MATCHING_RULE
    assert loaded["limits"] == list(bm.LIMITS) and len(bm.LIMITS) == 7
    assert list(loaded["apps"]) == ["phantom", "zombie"]  # sorted keys


@pytest.mark.parametrize(("app", "prefix"), [("zombie", "zs"), ("phantom", "pi")])
def test_each_app_block_has_the_schema_and_conserves_counts(
    reduced: dict[str, Any], app: str, prefix: str
) -> None:
    data = reduced["apps"][app]
    totals = data["totals"]

    assert set(data) == APP_KEYS
    assert set(data["detectors"]) == set(registered_names(prefix))
    assert all(set(entry) == DETECTOR_KEYS for entry in data["detectors"].values())
    assert set(gen.PROBLEM_TYPES[app]) <= set(data["types"])
    assert (data["scenarios"], data["seed"]) == (REDUCED, gen.BENCHMARK_SEED)
    assert data["noise_only_scenarios"] == 2
    assert data["errors"] == {}
    assert totals["tp"] + totals["fn"] == totals["labels"]
    assert totals["tp"] + totals["fp"] == totals["alerts"]
    for group in ("detectors", "types"):
        for field_name in ("alerts", "labels", "tp"):
            assert sum(e[field_name] for e in data[group].values()) == totals[field_name]
    detail = data["scenarios_detail"]
    assert [row["id"] for row in detail] == [f"{prefix}-{i:04d}" for i in range(REDUCED)]
    for field_name in ("alerts", "labels", "tp", "fp", "fn"):
        assert sum(row[field_name] for row in detail) == totals[field_name]
    assert len(data["false_positives"]) == totals["fp"]
    assert len(data["misses"]) == totals["fn"]
    assert sum(r["false_alarms"] for r in data["hard_negatives"].values()) <= totals["fp"]


def test_every_detector_carries_the_run_seed(reduced: dict[str, Any]) -> None:
    detectors = reduced["apps"]["zombie"]["detectors"]

    assert detectors["zs.price_increase"]["seed"] == reduced["seed"]


def test_the_serialised_results_follow_the_byte_rules(reduced: dict[str, Any]) -> None:
    text = bm.dumps_results(reduced)
    raw = text.encode("utf-8")

    assert text == json.dumps(reduced, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert b"\r" not in raw
    assert text.endswith("}\n")


@pytest.mark.parametrize("which", ["results", "markdown"])
def test_the_outputs_hold_no_date_time_path_or_machine_name(
    reduced: dict[str, Any], which: str
) -> None:
    body = bm.dumps_results(reduced) if which == "results" else bm.render_markdown(reduced)

    assert str(ROOT) not in body and ROOT.as_posix() not in body
    assert not re.search(r"\d{4}-\d{2}-\d{2}", body)
    assert not re.search(r"\d{2}:\d{2}(:\d{2})?", body)
    node = platform.node()
    if len(node) >= 4:
        assert node not in body


def test_a_reduced_run_twice_gives_equal_bytes(reduced: dict[str, Any]) -> None:
    again, errors = bm.run_benchmark(gen.BENCHMARK_SEED, REDUCED)

    assert errors == {}
    assert bm.dumps_results(again) == bm.dumps_results(reduced)
    assert bm.render_markdown(again) == bm.render_markdown(reduced)


def test_another_seed_gives_other_bytes(reduced: dict[str, Any]) -> None:
    other, errors = bm.run_benchmark(gen.BENCHMARK_SEED + 1, REDUCED)

    assert errors == {}
    assert bm.dumps_results(other) != bm.dumps_results(reduced)
    assert bm.render_markdown(other) != bm.render_markdown(reduced)


# --- Tier 1/2: render_markdown from a hand-made dict --------------------------------------------


def test_static_texts_hold_no_digit() -> None:
    static = [*bm.LIMITS, bm.MATCHING_RULE, bm.GENERATED_NOTE, *bm.APP_TITLES.values()]
    static += [*bm.DETECTOR_HEADER, *bm.NEGATIVE_HEADER]

    assert [text for text in static if re.search(r"\d", text)] == []


def test_the_document_starts_with_the_generated_note_and_ends_with_lf() -> None:
    doc = bm.render_markdown(_handmade_results())

    assert doc.splitlines()[0] == GENERATED_FIRST_LINE
    assert doc.endswith("\n") and not doc.endswith("\n\n")
    assert "\r" not in doc
    assert bm.MATCHING_RULE in doc
    assert "python scripts/benchmark.py --check" in doc


def test_rendering_the_same_dict_twice_gives_identical_text() -> None:
    results = _handmade_results()

    assert bm.render_markdown(results) == bm.render_markdown(results)


def test_six_limits_render_six_list_items_under_limits() -> None:
    results = _handmade_results(limits=6)

    doc = bm.render_markdown(results)

    section = doc.split("## Limits\n", 1)[1].split("\n## ", 1)[0]
    items = [line for line in section.splitlines() if line.startswith("- ")]
    assert items == [f"- {limit}" for limit in results["limits"]]
    assert len(items) == 6


def test_every_integer_of_the_document_is_in_the_results() -> None:
    results = _handmade_results()

    doc = bm.render_markdown(results)

    assert set(re.findall(r"\d+", doc)) <= _digit_runs(results)


def test_ratios_are_the_stored_strings_and_null_is_na() -> None:
    doc = bm.render_markdown(_handmade_results())

    assert "| zs.price_increase | 10 | 7 | 3 | 2 | 0.7778 | 0.7000 | 2 |" in doc
    assert "| zs.recurring_charge | 0 | 0 | 0 | 0 | n/a | n/a | 2 |" in doc
    assert "None" not in doc and "null" not in doc
    assert "| weekly_groceries_irregular | 15 | 2 | 4 |" in doc


def test_each_app_has_a_section_with_its_seed_and_counts() -> None:
    doc = bm.render_markdown(_handmade_results(seed=31337, count=200))

    assert doc.index("## Zombie Subscriptions") < doc.index("## Phantom Invoices")
    assert "Seed `31337`, `200` scenarios per app." in doc
    assert doc.count("Seed `31337`. `200` scenarios, `40` of them") == 2


# --- Tier 1/2: command line ---------------------------------------------------------------------


USAGE_FLAGS = [["--seed", "7"], ["--scenarios", "10"], ["--check", "--seed", "7"]]


@pytest.mark.parametrize("flags", USAGE_FLAGS)
def test_seed_or_scenarios_without_out_dir_is_a_usage_error(
    flags: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[tuple[int, int]] = []
    monkeypatch.setattr(bm, "run_benchmark", lambda seed, count: calls.append((seed, count)))

    code = bm.main(flags)

    assert code == 2
    assert capsys.readouterr().err.strip() == "--seed and --scenarios need --out-dir"
    assert calls == []


def test_zero_scenarios_is_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = bm.main(["--scenarios", "0", "--out-dir", str(tmp_path)])

    assert code == 2
    assert "at least 1" in capsys.readouterr().err


def test_out_dir_writes_both_files_and_leaves_the_committed_files_alone(tmp_path: Path) -> None:
    before = _committed_bytes()
    out = tmp_path / "out"

    code = bm.main(["--seed", "7", "--scenarios", str(REDUCED), "--out-dir", str(out)])

    assert code == 0
    loaded = json.loads((out / "results.json").read_bytes().decode("utf-8"))
    assert (loaded["seed"], loaded["scenarios_per_app"]) == (7, REDUCED)
    doc = (out / "benchmark.md").read_bytes().decode("utf-8")
    assert doc.splitlines()[0] == GENERATED_FIRST_LINE
    assert "Seed `7`, `10` scenarios per app." in doc
    assert _committed_bytes() == before


def test_a_default_run_uses_the_committed_seed_count_and_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[int, int]] = []

    def fake(seed: int, count: int) -> tuple[dict[str, Any], dict[str, int]]:
        calls.append((seed, count))
        return _handmade_results(seed, count), {}

    monkeypatch.setattr(bm, "run_benchmark", fake)
    monkeypatch.setattr(bm, "RESULTS_FILE", tmp_path / "data" / "results.json")
    monkeypatch.setattr(bm, "DOC_FILE", tmp_path / "docs" / "benchmark.md")

    code = bm.main([])

    assert code == 0
    assert calls == [(gen.BENCHMARK_SEED, gen.SCENARIOS_PER_APP)]
    expected = _handmade_results(gen.BENCHMARK_SEED, gen.SCENARIOS_PER_APP)
    results_bytes = (tmp_path / "data" / "results.json").read_bytes()
    doc_bytes = (tmp_path / "docs" / "benchmark.md").read_bytes()
    assert results_bytes == bm.dumps_results(expected).encode("utf-8")
    assert doc_bytes == bm.render_markdown(expected).encode("utf-8")


def _fake_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the real run by the hand-made results of the same seed and count."""
    monkeypatch.setattr(
        bm, "run_benchmark", lambda seed, count: (_handmade_results(seed, count), {})
    )


def test_check_exits_0_when_the_bytes_are_equal_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_run(monkeypatch)
    flags = ["--seed", "7", "--scenarios", "10", "--out-dir", str(tmp_path)]
    assert bm.main(flags) == 0
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}

    assert bm.main([*flags, "--check"]) == 0

    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


def test_check_exits_1_when_one_byte_of_results_differs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _fake_run(monkeypatch)
    flags = ["--seed", "7", "--scenarios", "10", "--out-dir", str(tmp_path)]
    bm.main(flags)
    target = tmp_path / "results.json"
    original = target.read_bytes()
    edited = original.replace(b'"seed": 7', b'"seed": 8', 1)
    assert edited != original
    target.write_bytes(edited)
    capsys.readouterr()

    code = bm.main([*flags, "--check"])

    err = capsys.readouterr().err
    assert code == 1
    assert f"{target} differs from a fresh run; run python scripts/benchmark.py" in err
    assert "benchmark.md" not in err
    assert target.read_bytes() == edited  # --check never writes


def test_check_exits_1_when_the_document_differs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _fake_run(monkeypatch)
    flags = ["--seed", "7", "--scenarios", "10", "--out-dir", str(tmp_path)]
    bm.main(flags)
    document = tmp_path / "benchmark.md"
    document.write_bytes(document.read_bytes() + b"x")
    capsys.readouterr()

    code = bm.main([*flags, "--check"])

    err = capsys.readouterr().err
    assert code == 1
    assert f"{document} differs from a fresh run; run python scripts/benchmark.py" in err


def test_check_with_missing_committed_files_says_so_instead_of_failing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _fake_run(monkeypatch)
    monkeypatch.setattr(bm, "RESULTS_FILE", tmp_path / "none" / "results.json")
    monkeypatch.setattr(bm, "DOC_FILE", tmp_path / "none" / "benchmark.md")

    code = bm.main(["--check"])

    err = capsys.readouterr().err
    assert code == 1
    assert "data/benchmark/results.json is missing; run python scripts/benchmark.py" in err
    assert "docs/benchmark.md is missing; run python scripts/benchmark.py" in err
    assert not (tmp_path / "none").exists()


def test_check_message_for_the_committed_files_names_the_repository_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _fake_run(monkeypatch)
    results_file, doc_file = tmp_path / "results.json", tmp_path / "benchmark.md"
    monkeypatch.setattr(bm, "RESULTS_FILE", results_file)
    monkeypatch.setattr(bm, "DOC_FILE", doc_file)
    results_file.write_bytes(b"{}\n")
    doc_file.write_bytes(b"old\n")

    code = bm.main(["--check"])

    err = capsys.readouterr().err
    assert code == 1
    for shown in ("data/benchmark/results.json", "docs/benchmark.md"):
        assert f"{shown} differs from a fresh run; run python scripts/benchmark.py" in err


def test_a_detector_error_exits_1_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setitem(registry_module._REGISTRY, "pi.vat_error", _boom)
    out = tmp_path / "out"

    code = bm.main(["--seed", "7", "--scenarios", "3", "--out-dir", str(out)])

    assert code == 1
    assert (
        "detector pi.vat_error raised in 3 scenario(s); results not written"
        in capsys.readouterr().err
    )
    assert not out.exists()


def test_export_scenarios_writes_the_files_and_the_labels_of_every_scenario(
    tmp_path: Path,
) -> None:
    target = tmp_path / "x"

    code = bm.main(["--export-scenarios", str(target), "--scenarios", str(REDUCED)])

    assert code == 0
    assert len(list(target.iterdir())) == 2 * REDUCED
    zombie = gen.build_scenarios(gen.BENCHMARK_SEED, "zombie", REDUCED)[0]
    assert zombie.id == "zs-0000"
    statement = target / "zs-0000" / "statement.csv"
    assert statement.read_bytes() == zombie.files["statement.csv"].encode("utf-8")
    for name in ("invoices.csv", "suppliers.csv", "payments.csv", "labels.json"):
        assert (target / "pi-0000" / name).is_file()
    labels = json.loads((target / "pi-0001" / "labels.json").read_bytes().decode("utf-8"))
    planted = gen.build_scenarios(gen.BENCHMARK_SEED, "phantom", REDUCED)[1]
    assert [item["id"] for item in labels["labels"]] == [item.id for item in planted.labels]
    assert not (target / "results.json").exists()


def test_export_scenarios_cannot_be_combined_with_check(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = bm.main(["--export-scenarios", str(tmp_path / "x"), "--check"])

    assert code == 2
    assert "cannot be combined" in capsys.readouterr().err
    assert not (tmp_path / "x").exists()


# --- Task BM7: the committed files equal a fresh full run (REQ-BM-18, REQ-BM-19) ----------------

# Run time of the first full run, measured by the author on a laptop: about 17 seconds for both
# apps at 200 scenarios each. That is below the 45 second limit of REQ-BM-18, so
# SCENARIOS_PER_APP stays 200. The number is a note here and in tasks.md; no file the benchmark
# writes contains it.
FIRST_FULL_RUN_SECONDS = 17

REPO_GITATTRIBUTES = ROOT / ".gitattributes"
REPO_GITIGNORE = ROOT / ".gitignore"
BENCHMARK_ATTRIBUTE_LINES = ("data/benchmark/*.json -text", "docs/benchmark.md -text")


@pytest.fixture(scope="module")
def full_run() -> tuple[dict[str, Any], str, str]:
    """One full run at the committed seed and count: the results dict and the two texts."""
    results, errors = bm.run_benchmark(gen.BENCHMARK_SEED, gen.SCENARIOS_PER_APP)
    assert errors == {}
    return results, bm.dumps_results(results), bm.render_markdown(results)


def _first_difference(shown: str, committed: bytes, fresh: str) -> str | None:
    """None when the bytes are equal, else a message that names the first differing line."""
    if committed == fresh.encode("utf-8"):
        return None
    old = committed.decode("utf-8", errors="replace").split("\n")
    new = fresh.split("\n")
    for number in range(max(len(old), len(new))):
        left = old[number] if number < len(old) else "<end of file>"
        right = new[number] if number < len(new) else "<end of file>"
        if left != right:
            return f"{shown} line {number + 1}: committed {left!r}, fresh {right!r}"
    return f"{shown} differs"  # pragma: no cover  (equal lines, unequal bytes is not reachable)


def test_first_difference_names_the_first_differing_line() -> None:
    committed = b'{\n  "a": 1,\n  "b": 2\n}\n'

    assert _first_difference("x.json", committed, '{\n  "a": 1,\n  "b": 2\n}\n') is None
    message = _first_difference("x.json", committed, '{\n  "a": 1,\n  "b": 3\n}\n')
    assert message == "x.json line 3: committed '  \"b\": 2', fresh '  \"b\": 3'"
    short = _first_difference("x.json", committed, '{\n  "a": 1,\n')
    assert short is not None and short.startswith("x.json line 3:")


def test_the_committed_results_equal_a_fresh_full_run(
    full_run: tuple[dict[str, Any], str, str],
) -> None:
    _results, results_text, _doc_text = full_run
    assert bm.RESULTS_FILE.is_file(), f"{bm.RESULTS_SHOWN} is missing; {bm.RUN_HINT}"

    message = _first_difference(bm.RESULTS_SHOWN, bm.RESULTS_FILE.read_bytes(), results_text)

    assert message is None, f"{message}; {bm.RUN_HINT}"


def test_the_committed_document_equals_a_fresh_full_run(
    full_run: tuple[dict[str, Any], str, str],
) -> None:
    _results, _results_text, doc_text = full_run
    assert bm.DOC_FILE.is_file(), f"{bm.DOC_SHOWN} is missing; {bm.RUN_HINT}"

    message = _first_difference(bm.DOC_SHOWN, bm.DOC_FILE.read_bytes(), doc_text)

    assert message is None, f"{message}; {bm.RUN_HINT}"


def test_the_committed_results_state_the_committed_seed_and_count() -> None:
    loaded = json.loads(bm.RESULTS_FILE.read_bytes().decode("utf-8"))

    assert loaded["schema_version"] == bm.SCHEMA_VERSION
    assert loaded["seed"] == gen.BENCHMARK_SEED
    assert loaded["scenarios_per_app"] == gen.SCENARIOS_PER_APP
    assert gen.SCENARIOS_PER_APP % 20 == 0  # REQ-BM-18: a multiple of 20
    for app in ("zombie", "phantom"):
        assert loaded["apps"][app]["scenarios"] == gen.SCENARIOS_PER_APP
        assert loaded["apps"][app]["seed"] == gen.BENCHMARK_SEED
        assert loaded["apps"][app]["errors"] == {}


def test_the_committed_files_have_no_carriage_return() -> None:
    for path in (bm.RESULTS_FILE, bm.DOC_FILE):
        assert b"\r" not in path.read_bytes(), f"{path.name} has CR characters"


def test_gitattributes_marks_the_benchmark_outputs_as_not_text() -> None:
    lines = [line.strip() for line in REPO_GITATTRIBUTES.read_text(encoding="utf-8").splitlines()]

    for line in BENCHMARK_ATTRIBUTE_LINES:
        assert line in lines


def test_gitignore_allows_the_benchmark_folder_after_the_json_rule() -> None:
    lines = [line.strip() for line in REPO_GITIGNORE.read_text(encoding="utf-8").splitlines()]

    assert "*.json" in lines
    for line in ("!data/benchmark/", "!data/benchmark/**"):
        assert line in lines
        assert lines.index(line) > lines.index("*.json")


# --- Task BM9: every error of the committed results is a Follow-up (REQ-BM-22) ------------------

DESIGN = ROOT / ".kiro" / "specs" / "benchmark" / "design.md"
INDEX_LINE = re.compile(r"^- (Hard-negative kinds|Miss types|Scenario ids): (.*)$", re.MULTILINE)


def _coverage_index() -> dict[str, set[str]]:
    """The names listed in the coverage index of section 8 of the benchmark design."""
    text = DESIGN.read_text(encoding="utf-8")
    section = text.split("\n## 8 Follow-ups", 1)[1].split("\n## 9 ", 1)[0]
    index = section.split("Coverage index", 1)[1]
    return {
        label: set(re.findall(r"`([^`]+)`", names)) for label, names in INDEX_LINE.findall(index)
    }


def test_the_coverage_index_has_its_three_lines() -> None:
    index = _coverage_index()

    assert set(index) == {"Hard-negative kinds", "Miss types", "Scenario ids"}
    kinds = index["Hard-negative kinds"]
    assert {"fuel_irregular", "weekly_groceries_irregular", "two_legit_ibans"} <= kinds
    assert "zs.duplicate_subscription" in index["Miss types"]


def test_every_false_positive_and_miss_of_the_committed_results_is_a_follow_up() -> None:
    index = _coverage_index()
    loaded = json.loads(bm.RESULTS_FILE.read_bytes().decode("utf-8"))
    unnamed: list[str] = []

    for app, data in loaded["apps"].items():
        for fp in data["false_positives"]:
            named = fp["hard_negative"] in index["Hard-negative kinds"] or (
                fp["scenario"] in index["Scenario ids"]
            )
            if not named:
                unnamed.append(f"{app} false positive {fp['scenario']} {fp['type']}")
        for miss in data["misses"]:
            named = miss["type"] in index["Miss types"] or miss["scenario"] in index["Scenario ids"]
            if not named:
                unnamed.append(f"{app} miss {miss['label']} {miss['type']}")

    message = "add a Follow-up row and a coverage index entry: " + "; ".join(unnamed[:5])
    assert unnamed == [], message
