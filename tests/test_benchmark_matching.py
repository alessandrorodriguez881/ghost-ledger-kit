"""Tests of the matching rule, the ratios and the metrics of the benchmark (Task BM1).

``scripts/`` is not a package, so the runner is loaded by path. Everything here is pure: plain
records in, plain records out; no pipeline, no clock, no network. Labels and alerts are hand-made
(REQ-BM-12, REQ-BM-13); every identifier is synthetic.
"""

import importlib.util
import random
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "benchmark.py"


def _load_script() -> ModuleType:
    """Load scripts/benchmark.py by path (scripts/ is not a package)."""
    spec = importlib.util.spec_from_file_location("benchmark_script", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["benchmark_script"] = module
    spec.loader.exec_module(module)
    return module


bm = _load_script()


def alert(scenario: str, type_: str, *refs: str) -> Any:
    """An alert record."""
    return bm.AlertRecord(scenario, type_, tuple(refs), "d.x")


def label(
    id_: str,
    scenario: str,
    type_: str,
    rows: list[str],
    context: tuple[str, ...] = (),
) -> Any:
    """A label record."""
    return bm.LabelRecord(id_, scenario, type_, tuple(rows), context)


def counts(result: Any) -> tuple[int, int, int]:
    """(tp, fp, fn) of a match result."""
    return len(result.tp), len(result.fp), len(result.fn)


# --- Tier 1: the hand-made sets of REQ-BM-12 ---------------------------------------------------


def test_alert_on_the_rows_of_a_label_of_its_type_is_a_true_positive() -> None:
    alerts = [alert("s", "t", "inv.csv:3")]
    labels = [label("s/L0", "s", "t", ["inv.csv:3"])]

    assert counts(bm.match(alerts, labels)) == (1, 0, 0)


def test_same_rows_but_another_type_is_a_miss_and_a_false_alarm() -> None:
    alerts = [alert("s", "vat_error/total_mismatch", "inv.csv:3")]
    labels = [label("s/L0", "s", "vat_error/vat_amount_mismatch", ["inv.csv:3"])]

    assert counts(bm.match(alerts, labels)) == (0, 1, 1)


def test_one_label_takes_one_alert_the_second_is_a_false_positive() -> None:
    alerts = [alert("s", "dup", "inv.csv:4"), alert("s", "dup", "inv.csv:3")]
    labels = [label("s/L0", "s", "dup", ["inv.csv:3", "inv.csv:4"])]

    assert counts(bm.match(alerts, labels)) == (1, 1, 0)


def test_a_label_of_another_scenario_does_not_match() -> None:
    alerts = [alert("B", "t", "x.csv:1")]
    labels = [label("A/L0", "A", "t", ["x.csv:1"])]

    assert counts(bm.match(alerts, labels)) == (0, 1, 1)


def test_context_rows_never_match() -> None:
    alerts = [alert("s", "t", "s.csv:0")]
    labels = [label("s/L0", "s", "t", ["x.csv:1"], context=("s.csv:0",))]

    assert counts(bm.match(alerts, labels)) == (0, 1, 1)


def test_equal_overlap_goes_to_the_lower_label_id() -> None:
    l1 = label("s/L1", "s", "t", ["f.csv:1", "f.csv:2"])
    l2 = label("s/L2", "s", "t", ["f.csv:2"])

    result = bm.match([alert("s", "t", "f.csv:2")], [l2, l1])

    assert result.tp == ((alert("s", "t", "f.csv:2"), l1),)
    assert result.fn == (l2,)
    assert result.fp == ()


def test_the_largest_overlap_wins_over_the_lower_id() -> None:
    small = label("s/L1", "s", "t", ["f.csv:1"])
    large = label("s/L2", "s", "t", ["f.csv:1", "f.csv:2"])

    result = bm.match([alert("s", "t", "f.csv:1", "f.csv:2")], [small, large])

    assert result.tp[0][1] is large
    assert result.fn == (small,)


def test_label_ids_are_compared_by_number_not_by_text() -> None:
    first = label("s/L2", "s", "t", ["f.csv:1"])
    second = label("s/L10", "s", "t", ["f.csv:1"])

    result = bm.match([alert("s", "t", "f.csv:1")], [second, first])

    assert result.tp[0][1] is first


def test_no_alerts_and_one_label_is_a_miss() -> None:
    labels = [label("s/L0", "s", "t", ["f.csv:0"])]

    assert counts(bm.match([], labels)) == (0, 0, 1)


def test_one_alert_and_no_label_is_a_false_positive() -> None:
    assert counts(bm.match([alert("s", "t", "f.csv:0")], [])) == (0, 1, 0)


def test_natural_order_puts_row_9_before_row_10() -> None:
    assert bm.natural("f.csv:9") < bm.natural("f.csv:10")
    assert sorted(["f.csv:10", "f.csv:9"], key=bm.natural) == ["f.csv:9", "f.csv:10"]


def test_alerts_are_visited_in_natural_order() -> None:
    labels = [label("s/L0", "s", "t", ["f.csv:9", "f.csv:10"])]
    first_visited = alert("s", "t", "f.csv:9", "f.csv:10")
    second_visited = alert("s", "t", "f.csv:10")

    result = bm.match([second_visited, first_visited], labels)

    assert result.tp[0][0] == first_visited
    assert result.fp == (second_visited,)


def test_an_alert_without_refs_is_a_false_positive_and_does_not_raise() -> None:
    labels = [label("s/L0", "s", "t", ["f.csv:0"])]

    assert counts(bm.match([alert("s", "t")], labels)) == (0, 1, 1)


def test_unparseable_ref_rows_sort_by_text() -> None:
    assert bm.natural("weird") == ("weird", -1)
    assert bm.natural("f.csv:x") == ("f.csv:x", -1)


# --- Tier 1: ratios and metrics (REQ-BM-13) ----------------------------------------------------


def test_ratio_examples() -> None:
    assert bm.ratio(7, 9) == "0.7778"
    assert bm.ratio(7, 10) == "0.7000"
    assert bm.ratio(2, 3) == "0.6667"
    assert bm.ratio(1, 3) == "0.3333"
    assert bm.ratio(5, 5) == "1.0000"
    assert bm.ratio(0, 5) == "0.0000"


def test_ratio_without_denominator_is_none() -> None:
    assert bm.ratio(0, 0) is None
    assert bm.ratio(3, 0) is None


def test_ratio_rounds_half_up() -> None:
    assert bm.ratio(1, 8) == "0.1250"
    assert bm.ratio(1, 16) == "0.0625"
    assert bm.ratio(1, 32) == "0.0313"  # 0.03125 rounds up, not to even


def test_metrics_of_a_group() -> None:
    expected = {
        "alerts": 9,
        "fn": 3,
        "fp": 2,
        "labels": 10,
        "precision": "0.7778",
        "recall": "0.7000",
        "tp": 7,
    }

    assert bm.metrics(tp=7, alerts=9, labels=10) == expected


def test_metrics_with_no_alerts_and_no_labels_has_null_ratios() -> None:
    result = bm.metrics(tp=0, alerts=0, labels=0)

    assert result["precision"] is None and result["recall"] is None
    assert (result["fp"], result["fn"]) == (0, 0)


def test_noise_only_figures() -> None:
    noise = {f"n-{k}" for k in range(40)}
    alerts = [alert("n-0", "t", "f:0")] * 2 + [alert(f"n-{k}", "t", "f:0") for k in (1, 2, 3)]
    alerts.append(alert("n-3", "t", "f:1"))
    alerts.append(alert("planted-1", "t", "f:0"))  # not a noise-only scenario

    figures = bm.noise_figures(alerts, noise)

    assert figures == {
        "false_alarms_per_noise_scenario": "0.1500",
        "noise_only_alerts": 6,
        "noise_only_scenarios_with_alert": 4,
    }


def test_noise_figures_without_noise_scenarios() -> None:
    figures = bm.noise_figures([alert("s", "t", "f:0")], set())

    assert figures["false_alarms_per_noise_scenario"] is None
    assert figures["noise_only_alerts"] == 0


# --- Tier 1: hard-negative attribution ---------------------------------------------------------


def _negatives() -> list[Any]:
    rows = tuple(f"statement.csv:{k}" for k in range(5, 31))
    salary_rows = ("statement.csv:40", "statement.csv:41")
    return [
        bm.NegativeRecord("s/N0", "s", "weekly_groceries_irregular", rows),
        bm.NegativeRecord("s/N1", "s", "salary_credits", salary_rows),
        bm.NegativeRecord("t/N0", "t", "weekly_groceries_irregular", rows),
    ]


def test_a_false_alarm_is_attributed_to_the_hard_negative_it_cites() -> None:
    stats = bm.attribute_false_positives([alert("s", "t", "statement.csv:12")], _negatives())

    assert stats["weekly_groceries_irregular"] == {
        "false_alarms": 1,
        "instances": 2,
        "instances_with_false_alarm": 1,
    }
    assert stats["salary_credits"] == {
        "false_alarms": 0,
        "instances": 1,
        "instances_with_false_alarm": 0,
    }


def test_two_false_alarms_on_one_instance_count_one_instance() -> None:
    alerts = [alert("s", "t", "statement.csv:12"), alert("s", "u", "statement.csv:13")]

    stats = bm.attribute_false_positives(alerts, _negatives())

    assert stats["weekly_groceries_irregular"]["false_alarms"] == 2
    assert stats["weekly_groceries_irregular"]["instances_with_false_alarm"] == 1


def test_an_alert_citing_no_hard_negative_is_not_attributed() -> None:
    negatives = _negatives()
    stray = alert("s", "t", "statement.csv:99")

    stats = bm.attribute_false_positives([stray], negatives)

    assert bm.hard_negative_of(stray, negatives) is None
    assert sum(entry["false_alarms"] for entry in stats.values()) == 0


def test_an_alert_citing_two_hard_negatives_goes_to_the_first_id() -> None:
    negatives = [
        bm.NegativeRecord("s/N1", "s", "kind_b", ("f.csv:1",)),
        bm.NegativeRecord("s/N0", "s", "kind_a", ("f.csv:1",)),
    ]

    found = bm.hard_negative_of(alert("s", "t", "f.csv:1"), negatives)

    assert found is not None and found.id == "s/N0"


def test_a_hard_negative_of_another_scenario_is_ignored() -> None:
    negatives = [bm.NegativeRecord("t/N0", "t", "kind_a", ("f.csv:1",))]

    assert bm.hard_negative_of(alert("s", "t", "f.csv:1"), negatives) is None


# --- Tier 2: edge cases ------------------------------------------------------------------------


def test_empty_input_gives_zeros() -> None:
    assert counts(bm.match([], [])) == (0, 0, 0)


def test_single_alert_and_single_label_return_tuples() -> None:
    result = bm.match([alert("s", "t", "f:0")], [label("s/L0", "s", "t", ["f:0"])])

    assert isinstance(result.tp, tuple) and isinstance(result.fp, tuple)
    assert isinstance(result.fn, tuple)


def test_duplicate_identical_alerts_match_one_label_once() -> None:
    alerts = [alert("s", "t", "f.csv:1"), alert("s", "t", "f.csv:1")]
    labels = [label("s/L0", "s", "t", ["f.csv:1"])]

    assert counts(bm.match(alerts, labels)) == (1, 1, 0)


def test_the_matching_rule_is_one_paragraph_that_names_context_rows() -> None:
    assert "\n" not in bm.MATCHING_RULE
    assert "context rows never match" in bm.MATCHING_RULE.lower()


# --- Tier 3: properties ------------------------------------------------------------------------

SCENARIOS = st.sampled_from(["s1", "s2", "s3"])
TYPES = st.sampled_from(["t1", "t2"])
REFS = st.lists(
    st.integers(min_value=0, max_value=6).map(lambda n: f"f.csv:{n}"),
    min_size=1,
    max_size=4,
    unique=True,
)


@st.composite
def worlds(draw: Any) -> tuple[list[Any], list[Any]]:
    """Random alerts and labels; label ids are unique."""
    alerts = []
    for _ in range(draw(st.integers(min_value=0, max_value=8))):
        alerts.append(bm.AlertRecord(draw(SCENARIOS), draw(TYPES), tuple(draw(REFS)), "d.x"))
    labels = []
    for k in range(draw(st.integers(min_value=0, max_value=8))):
        scenario = draw(SCENARIOS)
        rows = tuple(draw(REFS))
        labels.append(bm.LabelRecord(f"{scenario}/L{k}", scenario, draw(TYPES), rows, ()))
    return alerts, labels


@settings(max_examples=200, deadline=None)
@given(world=worlds())
def test_counts_are_conserved(world: Any) -> None:
    alerts, labels = world

    result = bm.match(alerts, labels)

    assert len(result.tp) + len(result.fn) == len(labels)
    assert len(result.tp) + len(result.fp) == len(alerts)


@settings(max_examples=200, deadline=None)
@given(world=worlds(), seed=st.integers(min_value=0, max_value=10_000))
def test_order_of_alerts_and_labels_does_not_change_the_counts(world: Any, seed: int) -> None:
    alerts, labels = world
    shuffled_alerts, shuffled_labels = list(alerts), list(labels)
    rng = random.Random(seed)
    rng.shuffle(shuffled_alerts)
    rng.shuffle(shuffled_labels)

    assert counts(bm.match(alerts, labels)) == counts(bm.match(shuffled_alerts, shuffled_labels))


@settings(max_examples=200, deadline=None)
@given(world=worlds())
def test_matched_pairs_share_scenario_type_and_a_ref(world: Any) -> None:
    alerts, labels = world

    for matched_alert, matched_label in bm.match(alerts, labels).tp:
        assert matched_alert.scenario == matched_label.scenario
        assert matched_alert.type == matched_label.type
        assert set(matched_alert.refs) & set(matched_label.rows)


@settings(max_examples=200, deadline=None)
@given(world=worlds())
def test_a_label_is_used_at_most_once(world: Any) -> None:
    alerts, labels = world

    result = bm.match(alerts, labels)

    used = [matched_label.id for _alert, matched_label in result.tp]
    assert len(used) == len(set(used))
    assert len(result.tp) <= min(len(alerts), len(labels))


@settings(max_examples=200, deadline=None)
@given(world=worlds())
def test_match_is_idempotent(world: Any) -> None:
    alerts, labels = world

    assert bm.match(alerts, labels) == bm.match(alerts, labels)


@settings(max_examples=200, deadline=None)
@given(world=worlds())
def test_context_rows_never_change_the_result(world: Any) -> None:
    alerts, labels = world
    with_context = [
        bm.LabelRecord(item.id, item.scenario, item.type, item.rows, ("f.csv:0", "f.csv:1"))
        for item in labels
    ]

    assert counts(bm.match(alerts, labels)) == counts(bm.match(alerts, with_context))


@settings(max_examples=200, deadline=None)
@given(tp=st.integers(min_value=0, max_value=50), extra=st.integers(min_value=0, max_value=50))
def test_ratio_is_between_zero_and_one(tp: int, extra: int) -> None:
    value = bm.ratio(tp, tp + extra)

    if tp + extra == 0:
        assert value is None
    else:
        assert value is not None and "0.0000" <= value <= "1.0000"
