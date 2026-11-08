"""Tests for detector base types and the registry (design §4; REQ-DET, REQ-REG, REQ-TST-09)."""

import logging
import sys
import textwrap
from datetime import date
from decimal import Decimal
from types import MappingProxyType

import pandas as pd
import pytest

from ledger_kit.detectors import (
    DetectorError,
    DetectorResult,
    _clear_registry,
    _restore_registry,
    _snapshot_registry,
    auto_discover,
    loaded_source_refs,
    register,
    registered_names,
    run_all,
)
from ledger_kit.models import Alert

pytestmark = pytest.mark.usefixtures("isolated_registry")


@register("tfix.keep")
def _keep_detector(ledger: pd.DataFrame, context) -> list[Alert]:
    """Module-scope detector that must survive snapshot/clear/restore cycles."""
    return []


def _alert(name: str, ref: str = "t.csv:0", **data) -> Alert:
    """Build a minimal synthetic alert for a detector called `name`."""
    return Alert(
        detector=name,
        severity="info",
        title="t",
        source_refs=[ref],
        data=data or {"k": 1},
    )


def _ledger(*refs: str) -> pd.DataFrame:
    """Build a tiny ledger holding only a source_ref column."""
    return pd.DataFrame({"source_ref": list(refs)})


# --- register -------------------------------------------------------------------------------


def test_register_adds_detector():
    @register("ns.foo")
    def foo(ledger, context):
        return []

    assert "ns.foo" in registered_names()


def test_register_returns_the_function_unchanged():
    def foo(ledger, context):
        return []

    assert register("ns.same")(foo) is foo


def test_register_duplicate_name_raises():
    @register("ns.foo")
    def first(ledger, context):
        return []

    with pytest.raises(ValueError):

        @register("ns.foo")
        def second(ledger, context):
            return []


def test_register_invalid_name_no_dot_raises():
    with pytest.raises(ValueError):
        register("nodot")


def test_register_invalid_name_uppercase_raises():
    with pytest.raises(ValueError):
        register("NS.foo")


def test_register_invalid_name_empty_part_raises():
    with pytest.raises(ValueError):
        register(".foo")
    with pytest.raises(ValueError):
        register("ns.")


def test_invalid_name_is_not_added_to_registry():
    before = registered_names()
    with pytest.raises(ValueError):
        register("Bad.Name")
    assert registered_names() == before


# --- run_all --------------------------------------------------------------------------------


def test_run_all_empty_registry_returns_empty(empty_registry):
    assert run_all(_ledger("a:0")) == []


def test_run_all_calls_registered_detector():
    alert = _alert("rt1.one")

    @register("rt1.one")
    def one(ledger, context):
        return [alert]

    results = run_all(_ledger("t.csv:0"), namespace="rt1")
    assert results == [DetectorResult(name="rt1.one", alerts=[alert])]


def test_run_all_isolates_failing_detector(caplog):
    alert = _alert("rt2.good")

    @register("rt2.bad")
    def bad(ledger, context):
        raise RuntimeError("boom")

    @register("rt2.good")
    def good(ledger, context):
        return [alert]

    with caplog.at_level(logging.WARNING):
        results = run_all(_ledger("t.csv:0"), namespace="rt2")

    by_name = {r.name: r.alerts for r in results}
    assert by_name == {"rt2.bad": [], "rt2.good": [alert]}
    assert any("rt2.bad" in rec.getMessage() for rec in caplog.records)


def test_run_all_order_is_insertion_order():
    for name in ("rt3.c", "rt3.a", "rt3.b"):
        register(name)(lambda ledger, context: [])

    results = run_all(_ledger("t.csv:0"), namespace="rt3")
    assert [r.name for r in results] == ["rt3.c", "rt3.a", "rt3.b"]


def test_run_all_namespace_filter_excludes_other_ns():
    register("zs.a")(lambda ledger, context: [])
    register("pi.b")(lambda ledger, context: [])

    results = run_all(_ledger("t.csv:0"), namespace="zs")
    assert [r.name for r in results] == ["zs.a"]


def test_run_all_namespace_filter_requires_dot_boundary():
    register("zs.a")(lambda ledger, context: [])
    register("zsx.b")(lambda ledger, context: [])

    assert [r.name for r in run_all(_ledger("t.csv:0"), namespace="zs")] == ["zs.a"]


def test_run_all_namespace_filter_none_runs_all():
    register("zs.a")(lambda ledger, context: [])
    register("pi.b")(lambda ledger, context: [])

    names = [r.name for r in run_all(_ledger("t.csv:0"), namespace=None)]
    assert "zs.a" in names and "pi.b" in names
    assert names == registered_names()


def test_run_all_context_passed_as_mapping_proxy():
    seen = []

    @register("rt4.probe")
    def probe(ledger, context):
        seen.append(context)
        return []

    run_all(_ledger("t.csv:0"), namespace="rt4", context={"aliases": {"x": "y"}})

    assert len(seen) == 1
    assert isinstance(seen[0], MappingProxyType)
    with pytest.raises(TypeError):
        seen[0]["new_key"] = 1


def test_run_all_empty_context_when_none_passed():
    seen = []

    @register("rt5.probe")
    def probe(ledger, context):
        seen.append(context)
        return []

    run_all(_ledger("t.csv:0"), namespace="rt5")

    assert isinstance(seen[0], MappingProxyType)
    assert dict(seen[0]) == {}


def test_run_all_context_values_accessible():
    @register("rt6.reader")
    def reader(ledger, context):
        return [_alert("rt6.reader", alias=context["aliases"]["x"])]

    results = run_all(_ledger("t.csv:0"), namespace="rt6", context={"aliases": {"x": "y"}})

    assert results[0].alerts[0].data == {"alias": "y"}


def test_run_all_does_not_mutate_callers_context():
    context = {"aliases": {}}
    run_all(_ledger("t.csv:0"), namespace="nothing", context=context)
    assert context == {"aliases": {}}


def test_registered_names_namespace_filter():
    register("zs.a")(lambda ledger, context: [])
    register("pi.b")(lambda ledger, context: [])
    register("zs.c")(lambda ledger, context: [])

    assert registered_names(namespace="zs") == ["zs.a", "zs.c"]


# --- auto_discover --------------------------------------------------------------------------


def _make_package(tmp_path, monkeypatch, pkg: str, modules: dict[str, str]) -> None:
    """Write a throw-away package to tmp_path and put it on sys.path."""
    root = tmp_path / pkg
    root.mkdir()
    (root / "__init__.py").write_text("")
    for module_name, body in modules.items():
        (root / f"{module_name}.py").write_text(textwrap.dedent(body))
    monkeypatch.syspath_prepend(str(tmp_path))


def _forget_package(pkg: str) -> None:
    """Drop the throw-away package and its submodules from sys.modules."""
    for key in [k for k in sys.modules if k == pkg or k.startswith(pkg + ".")]:
        del sys.modules[key]


def test_auto_discover_sorted_order(tmp_path, monkeypatch):
    pkg = "adpkg_sorted"
    body = """
        from ledger_kit.detectors import register

        @register("{name}")
        def detect(ledger, context):
            return []
    """
    _make_package(
        tmp_path,
        monkeypatch,
        pkg,
        {
            "mod_b": body.format(name="ad1.b"),
            "mod_c": body.format(name="ad1.c"),
            "mod_a": body.format(name="ad1.a"),
        },
    )
    try:
        auto_discover(pkg)
    finally:
        _forget_package(pkg)

    assert registered_names("ad1") == ["ad1.a", "ad1.b", "ad1.c"]


def test_auto_discover_does_not_double_register(tmp_path, monkeypatch):
    pkg = "adpkg_twice"
    _make_package(
        tmp_path,
        monkeypatch,
        pkg,
        {
            "mod_a": """
                from ledger_kit.detectors import register

                @register("ad2.a")
                def detect(ledger, context):
                    return []
            """
        },
    )
    try:
        auto_discover(pkg)
        auto_discover(pkg)
    finally:
        _forget_package(pkg)

    assert registered_names("ad2") == ["ad2.a"]


# --- snapshot / clear / restore -------------------------------------------------------------


def test_clear_registry_removes_all():
    _clear_registry()
    assert registered_names() == []


def test_snapshot_restore_roundtrip():
    def tmp_fn(ledger, context):
        return []

    register("ns.tmp")(tmp_fn)
    snapshot = _snapshot_registry()
    register("ns.other")(lambda ledger, context: [])

    _restore_registry(snapshot)

    assert registered_names() == list(snapshot)
    assert "ns.other" not in registered_names()
    assert snapshot["ns.tmp"] is tmp_fn


def test_clear_then_restore_keeps_preexisting_detectors():
    assert "tfix.keep" in registered_names()
    snapshot = _snapshot_registry()
    _clear_registry()
    assert "tfix.keep" not in registered_names()

    _restore_registry(snapshot)

    assert "tfix.keep" in registered_names()


# --- detector contract ----------------------------------------------------------------------


def test_run_all_empty_ledger():
    @register("rt7.ledger_only")
    def ledger_only(ledger, context):
        return [] if ledger.empty else [_alert("rt7.ledger_only")]

    for result in run_all(pd.DataFrame(), context={}):
        assert result.alerts == [], result.name


# --- loaded_source_refs ---------------------------------------------------------------------


def test_loaded_source_refs_is_union_of_ledger_and_context_frames():
    context = {
        "payments": _ledger("p:0"),
        "suppliers": _ledger("s:0"),
        "as_of": date(2026, 1, 15),
    }

    assert loaded_source_refs(_ledger("a:0"), context) == frozenset({"a:0", "p:0", "s:0"})


def test_loaded_source_refs_tolerates_missing_column_and_non_frames():
    context = {"no_ref": pd.DataFrame({"amount": [1]}), "nothing": None, "n": 3}

    assert loaded_source_refs(pd.DataFrame(), context) == frozenset()
    assert loaded_source_refs(_ledger("a:0"), context) == frozenset({"a:0"})


def test_loaded_source_refs_ignores_missing_values():
    ledger = pd.DataFrame({"source_ref": ["a:0", None]})

    assert loaded_source_refs(ledger, MappingProxyType({})) == frozenset({"a:0"})


def test_detector_error_carries_name_and_cause():
    cause = ValueError("bad")
    error = DetectorError("ns.foo", cause)

    assert error.name == "ns.foo"
    assert error.cause is cause
    assert "ns.foo" in str(error) and "bad" in str(error)


# --- context-reading detectors and Alert payloads -------------------------------------------


def test_context_reading_detector_may_alert_on_empty_ledger():
    @register("rt8.payments")
    def payments_without_invoice(ledger, context):
        payments = context.get("payments")
        if payments is None or payments.empty:
            return []
        return [_alert("rt8.payments", ref=str(payments["source_ref"].iloc[0]))]

    with_payments = run_all(
        pd.DataFrame(), namespace="rt8", context={"payments": _ledger("pay.csv:0")}
    )
    without_payments = run_all(pd.DataFrame(), namespace="rt8", context={})
    empty_payments = run_all(
        pd.DataFrame(), namespace="rt8", context={"payments": pd.DataFrame()}
    )

    assert [len(r.alerts) for r in with_payments] == [1]
    assert with_payments[0].alerts[0].source_refs == ["pay.csv:0"]
    assert [r.alerts for r in without_payments] == [[]]
    assert [r.alerts for r in empty_payments] == [[]]


def test_run_all_keeps_alerts_with_decimal_and_date_data():
    @register("rt9.rich")
    def rich(ledger, context):
        return [
            Alert(
                detector="rt9.rich",
                severity="warning",
                title="t",
                source_refs=["t.csv:0"],
                data={"yearly_cost": Decimal("155.88"), "last": date(2026, 1, 15)},
            )
        ]

    results = run_all(_ledger("t.csv:0"), namespace="rt9")

    assert len(results[0].alerts) == 1
    assert results[0].alerts[0].data["yearly_cost"] == Decimal("155.88")
