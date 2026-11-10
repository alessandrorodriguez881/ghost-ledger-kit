"""Norma 43 demo, routers and equivalence with the CSV demo (Task VF13; REQ-VF-53).

The demo tests read the committed files and FAIL LOUDLY until the human has run
`python scripts/generate_samples.py --mode vampire-demo` (human step H1). The concept-only test
builds its own two-row statement and does not need the committed files.
"""

import importlib.util
import io
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from apps.vampire_fees.detectors.utils import EMPTY_VOCABULARY, extract_fees
from apps.vampire_fees.settings import load_config, load_vocabulary, run_pipeline
from apps.vampire_fees.tests.vf_builders import default_vocabulary
from ledger_kit.ingestion.normaliser import normalise
from ledger_kit.ingestion.sniffer import read_bank_statement, sniff_format
from ledger_kit.models import Alert

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "generate_samples.py"
CSV_PATH = ROOT / "data" / "samples" / "vampire_demo_statement.csv"
N43_PATH = ROOT / "data" / "samples" / "vampire_demo_statement.n43"
CONFIG_PATH = ROOT / "apps" / "vampire_fees" / "config.toml"


def require_committed_demo() -> None:
    """Fail loudly, with the command to run, when the committed demo files do not exist."""
    missing = [p.name for p in (CSV_PATH, N43_PATH) if not p.is_file()]
    assert not missing, (
        f"missing {missing}: run `python scripts/generate_samples.py --mode vampire-demo` "
        "(human step H1 of the vampire-fees tasks)"
    )


def load_generator() -> Any:
    """Load scripts/generate_samples.py by path (scripts/ is not a package)."""
    spec = importlib.util.spec_from_file_location("generate_samples_vf_rf", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["generate_samples_vf_rf"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def vocabulary() -> Any:
    """The vocabulary of the committed config.toml."""
    return load_vocabulary(load_config(CONFIG_PATH))


@pytest.fixture(scope="module")
def csv_run(vocabulary: Any) -> Any:
    """The pipeline on the committed CSV demo."""
    require_committed_demo()
    return run_pipeline(CSV_PATH.name, CSV_PATH.read_bytes(), vocabulary=vocabulary)


@pytest.fixture(scope="module")
def n43_run(vocabulary: Any) -> Any:
    """The pipeline on the committed Norma 43 demo."""
    require_committed_demo()
    return run_pipeline(N43_PATH.name, N43_PATH.read_bytes(), vocabulary=vocabulary)


def shape(alert: Alert) -> tuple[Any, ...]:
    """What REQ-VF-53 says must be equal: detector, severity, title, data, number of refs."""
    return (alert.detector, alert.severity, alert.title, alert.data, len(alert.source_refs))


# --- The two demos give the same alerts ---------------------------------------------------------


def test_sniffer_picks_the_reader_by_content() -> None:
    """The content, not the extension, tells CSV from Norma 43."""
    require_committed_demo()
    assert sniff_format(CSV_PATH.read_bytes()) == "csv"
    assert sniff_format(N43_PATH.read_bytes()) == "norma43"


def test_norma43_demo_reads_227_rows_without_quarantine(n43_run: Any) -> None:
    """Same row counts as the CSV demo; control checks pass (no quarantine)."""
    assert len(n43_run.ledger) == 227
    assert int((n43_run.ledger["flow"] == "debit").sum()) == 202
    assert n43_run.quarantine == []
    assert n43_run.skipped_currency == 0
    assert n43_run.kind == "norma43"


def test_csv_and_norma43_demos_give_equal_alerts(csv_run: Any, n43_run: Any) -> None:
    """REQ-VF-53: equal in detector, severity, title, data and number of refs."""
    assert len(csv_run.alerts) == len(n43_run.alerts) == 6
    assert [shape(a) for a in csv_run.alerts] == [shape(a) for a in n43_run.alerts]


def test_refs_and_ids_differ_only_by_file_name_and_row_index(csv_run: Any, n43_run: Any) -> None:
    """The refs name their own file; the alert ids differ with them."""
    for csv_alert, n43_alert in zip(csv_run.alerts, n43_run.alerts, strict=True):
        assert all(ref.startswith(CSV_PATH.name + ":") for ref in csv_alert.source_refs)
        assert all(ref.startswith(N43_PATH.name + ":") for ref in n43_alert.source_refs)
        assert csv_alert.id != n43_alert.id


def test_norma43_fee_rows_carry_the_bank_concept(n43_run: Any) -> None:
    """Fee rows are concept 17 (custody 16), as the generator writes them."""
    ledger = n43_run.ledger
    custody = ledger[ledger["description"] == "Comisión custodia valores"]
    assert len(custody) == 7
    assert all("common_concept:16" in tags for tags in custody["tags"])
    maintenance = ledger[ledger["description"] == "Comisión mantenimiento cuenta"]
    assert len(maintenance) == 22
    assert all("common_concept:17" in tags for tags in maintenance["tags"])


def test_every_demo_fee_is_recognised_by_its_words_too(n43_run: Any, vocabulary: Any) -> None:
    """REQ-VF-53: with concepts removed the same 45 fee rows are still found."""
    with_concepts = extract_fees(n43_run.ledger, vocabulary)
    stripped = n43_run.ledger.copy()
    stripped["tags"] = [[] for _ in range(len(stripped))]
    by_words = extract_fees(stripped, vocabulary)
    assert len(with_concepts) == len(by_words) == 45
    assert [f.source_ref for f in with_concepts] == [f.source_ref for f in by_words]


# --- The concept-only path (unit level, no committed file) --------------------------------------


def test_concept_17_alone_makes_a_fee_in_norma43_but_not_in_csv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A row whose words are not fee words is a fee through concept 17 only in Norma 43."""
    gen = load_generator()
    monkeypatch.setitem(gen.N43_CONCEPT_BY_DESCRIPTION, "TARJ 0042", "17")
    rows = [
        gen.BankRow(date(2026, 1, 2), "100.00", "Luminar Estudio S.L.", "Payroll", ""),
        gen.BankRow(date(2026, 1, 5), "-5.00", "BANCO FICTICIO", "TARJ 0042", ""),
    ]
    vocabulary = default_vocabulary()

    n43_bytes = gen.render_norma43(rows)
    transactions, quarantined = read_bank_statement(io.BytesIO(n43_bytes), source_file="t.n43")
    assert quarantined == []
    ledger, _ = normalise(transactions)
    fees = extract_fees(ledger, vocabulary)
    assert [fee.description for fee in fees] == ["TARJ 0042"]
    assert extract_fees(ledger, EMPTY_VOCABULARY) == fees

    csv_bytes = gen.render_bank_csv(rows, "plain").encode("utf-8")
    transactions, quarantined = read_bank_statement(io.BytesIO(csv_bytes), source_file="t.csv")
    assert quarantined == []
    ledger, _ = normalise(transactions)
    assert extract_fees(ledger, vocabulary) == []
