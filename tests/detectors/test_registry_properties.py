"""Tier 3 property tests for the registry (REQ-TST-01, REQ-TST-09, REQ-TST-10).

Detectors are registered once at module scope: registering inside an @given body would
raise the duplicate-name ValueError on the second example, and a function-scoped fixture
would trip Hypothesis's function_scoped_fixture health check.
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

import pandas as pd
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from hypothesis.extra.pandas import column, data_frames, range_indexes

from ledger_kit.detectors import loaded_source_refs, register, registered_names, run_all
from ledger_kit.models import Alert

CALLS: list[str] = []
PROBES: list[tuple[bool, bool]] = []

_PROFILE = settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)


@register("tprop.trivial")
def _trivial(ledger: pd.DataFrame, context: Mapping[str, Any]) -> list[Alert]:
    """Cite the first ledger ref, plus the first ref of a context payments frame if any."""
    if ledger.empty or "source_ref" not in ledger.columns:
        return []
    refs = [str(ledger["source_ref"].iloc[0])]
    payments = context.get("payments")
    if isinstance(payments, pd.DataFrame) and not payments.empty:
        refs.append(str(payments["source_ref"].iloc[0]))
    return [
        Alert(
            detector="tprop.trivial",
            severity="info",
            title="trivial",
            source_refs=refs,
            data={"rows": len(ledger)},
        )
    ]


@register("tprop_zs.a")
def _zs_a(ledger: pd.DataFrame, context: Mapping[str, Any]) -> list[Alert]:
    """Record that the zs namespace detector ran."""
    CALLS.append("tprop_zs.a")
    return []


@register("tprop_pi.b")
def _pi_b(ledger: pd.DataFrame, context: Mapping[str, Any]) -> list[Alert]:
    """Record that the pi namespace detector ran."""
    CALLS.append("tprop_pi.b")
    return []


@register("tprop_ctx.probe")
def _ctx_probe(ledger: pd.DataFrame, context: Mapping[str, Any]) -> list[Alert]:
    """Record whether the received context is a proxy that rejects mutation."""
    try:
        context["__probe__"] = 1  # type: ignore[index]
        rejected = False
    except TypeError:
        rejected = True
    PROBES.append((isinstance(context, MappingProxyType), rejected))
    return []


_REFS = st.text(alphabet="abcdefgh:0123456789.", min_size=1, max_size=8)

_LEDGERS = data_frames(
    [column("source_ref", elements=_REFS, dtype=object)],
    index=range_indexes(min_size=0, max_size=8),
)
_NON_EMPTY_LEDGERS = data_frames(
    [column("source_ref", elements=_REFS, dtype=object)],
    index=range_indexes(min_size=1, max_size=8),
)
_EMPTY_LEDGERS = data_frames(
    [column("source_ref", elements=_REFS, dtype=object)],
    index=range_indexes(min_size=0, max_size=0),
)
_CONTEXTS = st.one_of(
    st.just({}),
    st.builds(lambda frame: {"payments": frame}, _LEDGERS),
)


@_PROFILE
@given(ledger=_LEDGERS, context=_CONTEXTS)
def test_source_refs_are_subset_of_input(ledger, context):
    """No invention: every cited ref exists in a loaded input (ledger or context frame)."""
    known = loaded_source_refs(ledger, context)
    for result in run_all(ledger, namespace="tprop", context=context):
        for alert in result.alerts:
            assert alert.source_refs
            for ref in alert.source_refs:
                assert ref in known, f"Alert cited {ref!r} which is not in any loaded input"


@_PROFILE
@given(ledger=_NON_EMPTY_LEDGERS, context=_CONTEXTS)
def test_trivial_detector_alerts_on_non_empty_ledger(ledger, context):
    """The property above is not vacuous: a non-empty ledger yields exactly one alert."""
    results = run_all(ledger, namespace="tprop", context=context)
    assert [len(r.alerts) for r in results] == [1]


@_PROFILE
@given(ledger=_LEDGERS, context=_CONTEXTS)
def test_run_all_idempotent(ledger, context):
    """Running the same ledger twice gives structurally identical results."""
    first = run_all(ledger, namespace="tprop", context=context)
    second = run_all(ledger, namespace="tprop", context=context)
    assert first == second


@_PROFILE
@given(ledger=_EMPTY_LEDGERS)
def test_run_all_empty_input_always_empty(ledger):
    """A zero-row ledger (and empty context) produces no alerts."""
    assert len(ledger) == 0
    for result in run_all(ledger, namespace="tprop"):
        assert result.alerts == []


@_PROFILE
@given(ledger=_LEDGERS)
def test_namespace_filter_never_calls_other_ns(ledger):
    """Filtering on tprop_zs never runs the tprop_pi detector."""
    CALLS.clear()
    run_all(ledger, namespace="tprop_zs")
    assert CALLS == ["tprop_zs.a"]


@_PROFILE
@given(context=st.dictionaries(st.text(min_size=1, max_size=5), st.integers(), max_size=4))
def test_context_is_immutable_proxy(context):
    """The detector always receives a MappingProxyType that rejects item assignment."""
    PROBES.clear()
    run_all(pd.DataFrame(), namespace="tprop_ctx", context=context)
    assert PROBES == [(True, True)]
    assert "__probe__" not in context


def test_module_scope_registration_is_not_duplicated():
    """Each tprop* detector is registered exactly once after many Hypothesis examples."""
    names = registered_names()
    for expected in ("tprop.trivial", "tprop_zs.a", "tprop_pi.b", "tprop_ctx.probe"):
        assert names.count(expected) == 1
    assert registered_names("tprop") == ["tprop.trivial"]
