"""End-to-end test: config.toml, the demo CSV and the detectors line up (Task Z20)."""

import importlib.util
import io
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

import apps.zombie_subscriptions.detectors  # noqa: F401  (registers the zs.* detectors)
from apps.zombie_subscriptions.detectors.utils import (
    compute_zombie_cost,
    normalise_alias_map,
    normalise_counterparty,
    normalise_date_map,
)
from apps.zombie_subscriptions.settings import DemoInputs, demo_inputs, load_config
from ledger_kit.detectors import run_all
from ledger_kit.ingestion.csv_reader import parse_csv
from ledger_kit.ingestion.normaliser import normalise
from ledger_kit.models import Alert, Transaction

ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = ROOT / "apps" / "zombie_subscriptions" / "config.toml"
SCRIPT = ROOT / "scripts" / "generate_samples.py"

FIVE_DETECTORS = {
    "zs.recurring_charge",
    "zs.price_increase",
    "zs.duplicate_subscription",
    "zs.free_trial_to_paid",
    "zs.charges_after_cancellation",
}


def _load_generator() -> Any:
    """Load scripts/generate_samples.py by path (scripts/ is not a package)."""
    spec = importlib.util.spec_from_file_location("generate_samples_e2e", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["generate_samples_e2e"] = module
    spec.loader.exec_module(module)
    return module


gen = _load_generator()


def _inputs() -> DemoInputs:
    """Return what the Load demo data button loads."""
    return demo_inputs(load_config(CONFIG_PATH), ROOT)


def _transactions(inputs: DemoInputs) -> list[Transaction]:
    """Parse the demo CSV; it must not quarantine anything."""
    source = io.BytesIO(inputs.csv_bytes)
    transactions, quarantined = parse_csv(source, source_file=inputs.csv_name)
    assert quarantined == []
    return transactions


def _debit_ledger(inputs: DemoInputs) -> pd.DataFrame:
    """Return the debit rows of the demo CSV as the app builds them."""
    frame, _ = normalise(_transactions(inputs))
    return frame[frame["flow"] == "debit"].reset_index(drop=True)


def _context(inputs: DemoInputs) -> dict[str, Any]:
    """Return the detector context with the user inputs normalised once, as the app does."""
    return {
        "aliases": normalise_alias_map(inputs.aliases),
        "cancellation_dates": normalise_date_map(inputs.cancellation_dates),
    }


def _alerts_by_detector(inputs: DemoInputs) -> dict[str, list[Alert]]:
    """Run every zs detector on the demo and group the alerts by detector name."""
    results = run_all(_debit_ledger(inputs), namespace="zs", context=_context(inputs))
    return {result.name: result.alerts for result in results}


def test_demo_config_keys_match_csv_normalised_keys() -> None:
    """Every alias member and every date-map key of [demo] is a normalised key of the CSV."""
    config = load_config(CONFIG_PATH)["demo"]
    csv_keys = {normalise_counterparty(t.counterparty) for t in _transactions(_inputs())}
    members = [member for keys in config["aliases"].values() for member in keys]
    configured = [*members, *config["last_used_dates"], *config["cancellation_dates"]]
    assert configured
    missing = [name for name in configured if normalise_counterparty(name) not in csv_keys]
    assert missing == []
    # The alias name is a canonical name, not a CSV key.
    assert normalise_counterparty("streaming") not in csv_keys


def test_demo_dates_parse_with_fromisoformat() -> None:
    """Every [demo] date is an ISO string inside the demo window and loads as datetime.date."""
    config = load_config(CONFIG_PATH)["demo"]
    raw = [*config["last_used_dates"].values(), *config["cancellation_dates"].values()]
    assert len(raw) >= 4
    parsed = [date.fromisoformat(value) for value in raw]
    assert all(date(2026, 5, 1) <= day <= date(2026, 10, 31) for day in parsed)
    inputs = _inputs()
    loaded = [*inputs.last_used_dates.values(), *inputs.cancellation_dates.values()]
    assert loaded == parsed
    assert all(type(day) is date for day in loaded)


def test_demo_triggers_all_five_detectors() -> None:
    """The demo makes each of the five zs detectors raise at least one alert."""
    by_detector = _alerts_by_detector(_inputs())
    assert set(by_detector) == FIVE_DETECTORS
    assert [name for name, alerts in by_detector.items() if not alerts] == []


def test_demo_alerts_are_the_planted_patterns() -> None:
    """The alerts name exactly the planted services (and nothing else)."""
    by_detector = _alerts_by_detector(_inputs())

    def names(detector: str, field: str) -> set[str]:
        return {a.data[field] for a in by_detector[detector]}

    assert names("zs.price_increase", "counterparty") == {"STREAMFLEX INTL", "CLOUDVAULT"}
    assert names("zs.duplicate_subscription", "canonical_name") == {"MUSICBOX", "STREAMING"}
    assert names("zs.free_trial_to_paid", "counterparty") == {"SECUREPASS"}
    [cancellation] = by_detector["zs.charges_after_cancellation"]
    assert cancellation.data["counterparty"] == "GYMPLUS"
    assert cancellation.data["post_cancellation_count"] == 3
    assert cancellation.data["total_charged_after"] == "26.97"
    assert cancellation.severity == "critical"


def test_demo_has_at_least_three_tombstones_with_nonzero_cost() -> None:
    """compute_zombie_cost gives three tombstones whose cost since last use is above zero."""
    inputs = _inputs()
    context = _context(inputs)
    results = compute_zombie_cost(
        _debit_ledger(inputs),
        normalise_date_map(inputs.last_used_dates),
        aliases=context["aliases"],
    )
    assert len([r for r in results if r.cost_since_last_used > 0]) >= 3
    assert {r.canonical_name: r.cost_since_last_used for r in results} == {
        "BEATSTREAM": Decimal("29.97"),
        "PHOTOBOX": Decimal("19.96"),
        "STASHCRATE": Decimal("8.97"),
    }
    assert all(r.yearly_cost > 0 for r in results)


def test_demo_noise_merchants_produce_no_alerts() -> None:
    """No alert cites a row of the shopping, one-off, transfer or payroll counterparties."""
    inputs = _inputs()
    ledger = _debit_ledger(inputs)
    noise_keys = {normalise_counterparty(name) for name in gen.zombie_noise_counterparties()}
    keys = ledger["counterparty"].map(normalise_counterparty)
    noise_refs = set(ledger.loc[keys.isin(noise_keys), "source_ref"])
    assert len(noise_refs) > 200
    cited = {
        ref
        for alerts in _alerts_by_detector(inputs).values()
        for alert in alerts
        for ref in alert.source_refs
    }
    assert cited
    assert cited & noise_refs == set()


def test_demo_alert_source_refs_exist_in_csv() -> None:
    """Every cited source_ref is a row of the demo CSV (Finance Rule 2)."""
    inputs = _inputs()
    ledger = _debit_ledger(inputs)
    known = set(ledger["source_ref"])
    for name, alerts in _alerts_by_detector(inputs).items():
        for alert in alerts:
            assert alert.source_refs, name
            assert set(alert.source_refs) <= known, name
            assert all(ref.startswith(f"{inputs.csv_name}:") for ref in alert.source_refs), name
