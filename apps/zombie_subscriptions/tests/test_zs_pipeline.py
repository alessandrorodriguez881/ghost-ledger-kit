"""Tests of the public ``run_pipeline`` of the zombie app (amendment A-ZS-01, task ZSA1).

The function holds the read, normalise, debit-filter and detector steps that ``app.py`` ran
inline. The benchmark runner calls the same function, so these tests pin that it behaves as the
app did: same alert counts on the demo, debit rows only, quarantine returned, parse cache used.
All data is synthetic (Finance Rule 5); nothing here reads the system clock.
"""

from pathlib import Path
from typing import Any

import pytest

import apps.zombie_subscriptions.detectors  # noqa: F401  (registers the zs.* detectors)
from apps.zombie_subscriptions import settings
from apps.zombie_subscriptions.app import _ingest
from apps.zombie_subscriptions.detectors.utils import normalise_alias_map, normalise_date_map
from apps.zombie_subscriptions.settings import (
    DEMO_FORMATS,
    DemoInputs,
    Pipeline,
    demo_inputs,
    ingest_statement,
    load_config,
    run_pipeline,
)
from ledger_kit.detectors import registered_names

ROOT = Path(__file__).resolve().parents[3]
CONFIG = load_config(ROOT / "apps" / "zombie_subscriptions" / "config.toml")
DEMO_ALERTS = 19  # same figure as ZS_DEMO_ALERTS in tests/test_showcase_app.py
HEADER = "date,amount,currency,counterparty,description,iban\n"


def _demo(option: str) -> DemoInputs:
    """The demo inputs of a radio option."""
    return demo_inputs(CONFIG, ROOT, DEMO_FORMATS[option])


def _run_demo(option: str, **kwargs: Any) -> Pipeline:
    """Run the pipeline on a demo the way the app does."""
    demo = _demo(option)
    return run_pipeline(
        demo.statement_name,
        demo.statement_bytes,
        aliases=normalise_alias_map(demo.aliases),
        cancellation_dates=normalise_date_map(demo.cancellation_dates),
        **kwargs,
    )


def _statement(*rows: str) -> bytes:
    """A plain-dialect CSV statement with the given data rows."""
    return (HEADER + "".join(row + "\n" for row in rows)).encode("utf-8")


def _run(data: bytes, **kwargs: Any) -> Pipeline:
    """Run the pipeline with empty user inputs."""
    return run_pipeline("s.csv", data, aliases={}, cancellation_dates={}, **kwargs)


# --- Tier 1: the demo -------------------------------------------------------------------------


def test_run_pipeline_on_csv_demo_gives_the_demo_alerts() -> None:
    pipeline = _run_demo("CSV")

    assert len(pipeline.alerts) == DEMO_ALERTS
    assert {result.name for result in pipeline.results} == set(registered_names("zs"))


def test_run_pipeline_real_formats_demo_gives_the_same_alert_count() -> None:
    assert len(_run_demo("Real formats").alerts) == DEMO_ALERTS


def test_alerts_are_the_alerts_of_the_results_in_result_order() -> None:
    pipeline = _run_demo("CSV")

    expected = [alert for result in pipeline.results for alert in result.alerts]

    assert pipeline.alerts == expected


def test_run_pipeline_uses_only_zs_detectors() -> None:
    pipeline = _run_demo("CSV")

    assert all(result.name.startswith("zs.") for result in pipeline.results)


# --- Tier 2: edge cases -----------------------------------------------------------------------


def test_credits_are_not_in_the_debit_ledger() -> None:
    data = _statement(
        "2025-01-02,2450.00,EUR,ACME PAYROLL,Salary,",
        "2025-01-03,-12.50,EUR,CAFE ONE,Coffee,",
    )

    pipeline = _run(data)

    assert len(pipeline.ledger) == 2
    assert list(pipeline.debit_ledger["flow"]) == ["debit"]
    assert list(pipeline.debit_ledger.index) == [0]


def test_a_bad_row_is_returned_in_the_quarantine() -> None:
    data = _statement(
        "2025-01-03,-12.50,EUR,CAFE ONE,Coffee,",
        "not-a-date,-5.00,EUR,CAFE TWO,Tea,",
    )

    pipeline = _run(data)

    assert len(pipeline.quarantine) == 1
    assert len(pipeline.debit_ledger) == 1


def test_empty_statement_gives_empty_pipeline() -> None:
    pipeline = _run(b"")

    assert pipeline.alerts == []
    assert pipeline.debit_ledger.empty
    assert pipeline.quarantine == []


def test_header_only_statement_does_not_raise() -> None:
    pipeline = _run(_statement())

    assert pipeline.alerts == []


def test_cache_avoids_a_second_read(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    original = settings.read_bank_statement

    def counting(*args: Any, **kwargs: Any) -> Any:
        calls.append("read")
        return original(*args, **kwargs)

    monkeypatch.setattr(settings, "read_bank_statement", counting)
    data = _statement("2025-01-03,-12.50,EUR,CAFE ONE,Coffee,")
    cache: dict[str, Any] = {}

    first = _run(data, cache=cache)
    second = _run(data, cache=cache)

    assert calls == ["read"]
    assert len(cache) == 1
    assert first.debit_ledger.equals(second.debit_ledger)


def test_without_cache_every_call_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    original = settings.read_bank_statement

    def counting(*args: Any, **kwargs: Any) -> Any:
        calls.append("read")
        return original(*args, **kwargs)

    monkeypatch.setattr(settings, "read_bank_statement", counting)
    data = _statement("2025-01-03,-12.50,EUR,CAFE ONE,Coffee,")

    _run(data)
    _run(data)

    assert calls == ["read", "read"]


def test_app_ingest_is_ingest_statement() -> None:
    data = _statement("2025-01-03,-12.50,EUR,CAFE ONE,Coffee,")

    ledger_app, quarantine_app = _ingest("s.csv", data, {})
    ledger, quarantine = ingest_statement("s.csv", data)

    # ``id`` is a random uuid4 per Transaction by design: compare without it.
    assert len(ledger_app) == len(ledger) > 0
    for frame in (ledger_app, ledger):
        assert frame["id"].map(bool).all()
    assert ledger_app.drop(columns=["id"]).equals(ledger.drop(columns=["id"]))
    assert quarantine_app == quarantine


def test_cpi_defaults_to_none_in_the_context(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Any] = []

    def spy(ledger: Any, *, namespace: Any = None, context: Any = None) -> list:
        seen.append(dict(context))
        return []

    monkeypatch.setattr(settings, "run_all", spy)

    _run(_statement("2025-01-03,-12.50,EUR,CAFE ONE,Coffee,"))

    assert seen == [{"aliases": {}, "cancellation_dates": {}, "cpi": None}]
