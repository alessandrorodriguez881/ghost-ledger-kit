"""End-to-end test of the CSV demo, pinned to the literal table of design 7.3 (Task VF13).

These tests read the committed demo files. They FAIL LOUDLY until the human has run
`python scripts/generate_samples.py --mode vampire-demo` (human step H1): the agent that wrote
them cannot run the generator.
"""

import csv
import importlib.util
import io
import sys
from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from apps.vampire_fees.settings import (
    group_alerts_by_severity,
    load_config,
    load_vocabulary,
    run_pipeline,
)
from ledger_kit.models import Alert

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "generate_samples.py"
CSV_PATH = ROOT / "data" / "samples" / "vampire_demo_statement.csv"
N43_PATH = ROOT / "data" / "samples" / "vampire_demo_statement.n43"
CONFIG_PATH = ROOT / "apps" / "vampire_fees" / "config.toml"

# Descriptions of the 45 fee rows (A, B, C, D, E, F of design 7.2).
FEE_DESCRIPTIONS = frozenset(
    {
        "Comisión mantenimiento cuenta",
        "Comisión custodia valores",
        "Comisión anual tarjeta débito",
        "Intereses deudores",
        "Comisión por descubierto",
        "Comisión transferencia inmediata",
        "Comisión emisión cheque",
        "Commission foreign payment",
    }
)
OVERDRAFT_DESCRIPTIONS = frozenset({"Intereses deudores", "Comisión por descubierto"})


def require_committed_demo() -> None:
    """Fail loudly, with the command to run, when the committed demo files do not exist."""
    missing = [p.name for p in (CSV_PATH, N43_PATH) if not p.is_file()]
    assert not missing, (
        f"missing {missing}: run `python scripts/generate_samples.py --mode vampire-demo` "
        "(human step H1 of the vampire-fees tasks)"
    )


def load_generator() -> Any:
    """Load scripts/generate_samples.py by path (scripts/ is not a package)."""
    spec = importlib.util.spec_from_file_location("generate_samples_vf_e2e", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["generate_samples_vf_e2e"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def vocabulary() -> Any:
    """The vocabulary of the committed config.toml."""
    return load_vocabulary(load_config(CONFIG_PATH))


@pytest.fixture(scope="module")
def csv_rows() -> list[dict[str, str]]:
    """The data rows of the committed CSV, in file order (index = CSV source_row)."""
    require_committed_demo()
    text = CSV_PATH.read_text(encoding="utf-8")
    return list(csv.DictReader(io.StringIO(text)))


@pytest.fixture(scope="module")
def pipeline(vocabulary: Any, csv_rows: list[dict[str, str]]) -> Any:
    """The pipeline run on the committed CSV demo."""
    return run_pipeline(CSV_PATH.name, CSV_PATH.read_bytes(), vocabulary=vocabulary)


def refs_where(rows: list[dict[str, str]], predicate: Any) -> list[str]:
    """Expected refs: rows that satisfy `predicate`, ordered by (date, index), as file:index."""
    picked = [(row["date"], i) for i, row in enumerate(rows) if predicate(row)]
    return [f"{CSV_PATH.name}:{i}" for _, i in sorted(picked)]


def find(alerts: list[Alert], detector: str, **data: Any) -> Alert:
    """Return the only alert of `detector` whose data holds the given items."""
    found = [
        a
        for a in alerts
        if a.detector == detector and all(a.data.get(k) == v for k, v in data.items())
    ]
    assert len(found) == 1, (detector, data, [a.data for a in alerts if a.detector == detector])
    return found[0]


# --- Row counts ---------------------------------------------------------------------------------


def test_rows_read_debits_quarantine_and_skipped(pipeline: Any) -> None:
    """227 rows read, 202 debits, 25 credits, 0 quarantined, none skipped for currency."""
    ledger = pipeline.ledger
    assert len(ledger) == 227
    assert int((ledger["flow"] == "debit").sum()) == 202
    assert int((ledger["flow"] == "credit").sum()) == 25
    assert pipeline.quarantine == []
    assert pipeline.skipped_currency == 0
    assert pipeline.kind == "csv"


def test_six_alerts_one_critical_three_warning_two_info(pipeline: Any) -> None:
    """Design 7.3: 6 alerts split 1 / 3 / 2."""
    assert len(pipeline.alerts) == 6
    groups = group_alerts_by_severity(pipeline.alerts)
    assert {severity: len(items) for severity, items in groups.items()} == {
        "critical": 1,
        "warning": 3,
        "info": 2,
    }


# --- The six alerts, literally ------------------------------------------------------------------


def test_alert_1_recurring_maintenance_fee(pipeline: Any, csv_rows: list[dict[str, str]]) -> None:
    """Row 1 of 7.3: monthly 22 charges, 6.50, 78.00 a year, warning."""
    alert = find(pipeline.alerts, "vf.recurring_fee", interval_type="monthly")
    assert alert.severity == "warning"
    assert alert.data == {
        "counterparty": "BANCO FICTICIO",
        "description": "Comisión mantenimiento cuenta",
        "interval_type": "monthly",
        "charge_count": 22,
        "current_amount": "6.50",
        "yearly_cost": "78.00",
        "first_charge_date": "2025-01-05",
        "last_charge_date": "2026-10-05",
    }
    expected = refs_where(csv_rows, lambda r: r["description"] == "Comisión mantenimiento cuenta")
    assert len(expected) == 22
    assert alert.source_refs == expected


def test_alert_2_recurring_custody_fee(pipeline: Any, csv_rows: list[dict[str, str]]) -> None:
    """Row 2: quarterly 7 charges, 9.00, 36.00 a year, info."""
    alert = find(pipeline.alerts, "vf.recurring_fee", interval_type="quarterly")
    assert alert.severity == "info"
    assert alert.data == {
        "counterparty": "BANCO FICTICIO",
        "description": "Comisión custodia valores",
        "interval_type": "quarterly",
        "charge_count": 7,
        "current_amount": "9.00",
        "yearly_cost": "36.00",
        "first_charge_date": "2025-03-31",
        "last_charge_date": "2026-09-30",
    }
    expected = refs_where(csv_rows, lambda r: r["description"] == "Comisión custodia valores")
    assert alert.source_refs == expected and len(expected) == 7


def test_alert_3_recurring_card_fee(pipeline: Any, csv_rows: list[dict[str, str]]) -> None:
    """Row 3: yearly 2 charges, 30.00, info."""
    alert = find(pipeline.alerts, "vf.recurring_fee", interval_type="yearly")
    assert alert.severity == "info"
    assert alert.data == {
        "counterparty": "BANCO FICTICIO",
        "description": "Comisión anual tarjeta débito",
        "interval_type": "yearly",
        "charge_count": 2,
        "current_amount": "30.00",
        "yearly_cost": "30.00",
        "first_charge_date": "2025-02-14",
        "last_charge_date": "2026-02-16",
    }
    expected = refs_where(csv_rows, lambda r: r["description"] == "Comisión anual tarjeta débito")
    assert alert.source_refs == expected and len(expected) == 2


def test_alert_4_fee_increase(pipeline: Any, csv_rows: list[dict[str, str]]) -> None:
    """Row 4: 5.00 to 6.50 on 2026-01-05, +30.0 %, 18.00 more a year, warning, two refs."""
    alert = find(pipeline.alerts, "vf.fee_increase")
    assert alert.severity == "warning"
    assert alert.data == {
        "counterparty": "BANCO FICTICIO",
        "description": "Comisión mantenimiento cuenta",
        "interval_type": "monthly",
        "old_amount": "5.00",
        "new_amount": "6.50",
        "increase_percent": "30.0",
        "increase_date": "2026-01-05",
        "old_charge_date": "2025-12-05",
        "extra_cost_per_year": "18.00",
        "yearly_cost": "78.00",
    }
    expected = refs_where(
        csv_rows,
        lambda r: (
            r["description"] == "Comisión mantenimiento cuenta"
            and r["date"] in ("2025-12-05", "2026-01-05")
        ),
    )
    assert alert.source_refs == expected and len(expected) == 2


def test_alert_5_overdraft_cost(pipeline: Any, csv_rows: list[dict[str, str]]) -> None:
    """Row 5: 4 interest charges 61.00, 3 fees 45.00, total 106.00, critical, 7 refs."""
    alert = find(pipeline.alerts, "vf.overdraft_cost")
    assert alert.severity == "critical"
    assert alert.title == "Overdraft cost on this statement"
    assert alert.data == {
        "interest_count": 4,
        "interest_total": "61.00",
        "fee_count": 3,
        "fee_total": "45.00",
        "total": "106.00",
        "first_charge_date": "2025-06-18",
        "last_charge_date": "2026-06-30",
    }
    expected = refs_where(csv_rows, lambda r: r["description"] in OVERDRAFT_DESCRIPTIONS)
    assert alert.source_refs == expected and len(expected) == 7


def test_alert_6_fee_summary(pipeline: Any, csv_rows: list[dict[str, str]]) -> None:
    """Row 6: 45 fees, 379.25, 667 days, 207.54 a year, warning, 45 refs."""
    alert = find(pipeline.alerts, "vf.fee_summary")
    assert alert.severity == "warning"
    assert alert.title == "Bank fees on this statement"
    assert alert.data == {
        "fee_count": 45,
        "total_fees": "379.25",
        "first_date": "2025-01-02",
        "last_date": "2026-10-30",
        "span_days": 667,
        "yearly_equivalent": "207.54",
    }
    expected = refs_where(
        csv_rows, lambda r: r["description"] in FEE_DESCRIPTIONS and r["amount"].startswith("-")
    )
    assert alert.source_refs == expected and len(expected) == 45


def test_span_days_is_the_calendar_distance_plus_one() -> None:
    """The 667 of design 7.3 is (2026-10-30 - 2025-01-02).days + 1, checked independently."""
    assert (date(2026, 10, 30) - date(2025, 1, 2)).days + 1 == 667


# --- Plain Decimal sums, independent of the detectors -------------------------------------------


def test_plain_decimal_sums_of_the_csv(csv_rows: list[dict[str, str]]) -> None:
    """The arithmetic of design 7.3 recomputed from the file with Decimal."""

    def total(description: str) -> Decimal:
        return -sum(
            (Decimal(r["amount"]) for r in csv_rows if r["description"] == description),
            Decimal(0),
        )

    maintenance = total("Comisión mantenimiento cuenta")
    custody = total("Comisión custodia valores")
    card = total("Comisión anual tarjeta débito")
    overdraft = total("Intereses deudores") + total("Comisión por descubierto")
    assert maintenance == Decimal("125.00")
    assert custody == Decimal("63.00")
    assert card == Decimal("60.00")
    assert overdraft == Decimal("106.00")
    assert total("Comisión transferencia inmediata") == Decimal("6.00")
    assert total("Comisión emisión cheque") == Decimal("8.00")
    assert total("Commission foreign payment") == Decimal("11.25")
    everything = maintenance + custody + card + overdraft + Decimal("6.00") + Decimal("8.00")
    assert everything + Decimal("11.25") == Decimal("379.25")
    assert (Decimal("379.25") * 365 / 667).quantize(Decimal("0.01")) == Decimal("207.54")


# --- Hard negatives -----------------------------------------------------------------------------


def test_hard_negatives_are_cited_by_no_alert(
    pipeline: Any, csv_rows: list[dict[str, str]]
) -> None:
    """H1 to H4 and the monthly subscription S raise no fee alert and no fee row."""
    negatives = set(
        refs_where(
            csv_rows,
            lambda r: (
                r["counterparty"] == "Feelgood Market"
                or r["description"]
                in (
                    "Devolución comisión transferencia",
                    "Abono intereses",
                    "Transferencia gastos escritura",
                    "Monthly subscription",
                )
            ),
        )
    )
    assert len(negatives) == 1 + 1 + 1 + 1 + 22
    cited = {ref for alert in pipeline.alerts for ref in alert.source_refs}
    assert not (negatives & cited)


def test_irregular_and_short_fee_series_are_in_the_summary_only(
    pipeline: Any, csv_rows: list[dict[str, str]]
) -> None:
    """E1 (four irregular) and E2 (two 30 days apart) are cited by the summary alone."""
    one_offs = set(
        refs_where(
            csv_rows,
            lambda r: (
                r["description"] in ("Comisión transferencia inmediata", "Comisión emisión cheque")
            ),
        )
    )
    assert len(one_offs) == 6
    citing = Counter()
    for alert in pipeline.alerts:
        if one_offs & set(alert.source_refs):
            citing[alert.detector] += 1
    assert citing == Counter({"vf.fee_summary": 1})


# --- The committed files are what the generator writes ------------------------------------------


def test_committed_files_equal_a_fresh_generator_run() -> None:
    """The CSV and the Norma 43 file are byte-identical to the generator output for seed 42."""
    require_committed_demo()
    gen = load_generator()
    assert CSV_PATH.read_bytes() == gen.build_vampire_demo_csv(42).encode("utf-8")
    assert N43_PATH.read_bytes() == gen.build_vampire_demo_n43(42)
