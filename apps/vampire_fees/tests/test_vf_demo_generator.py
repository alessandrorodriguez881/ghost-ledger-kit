"""Tests for the vampire-demo mode of scripts/generate_samples.py (Task VF12)."""

import importlib.util
import io
import sys
from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from apps.vampire_fees.detectors.utils import contains_phrase, fold_tokens
from apps.vampire_fees.tests.vf_builders import default_vocabulary
from ledger_kit.ingestion.sniffer import read_bank_statement

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "generate_samples.py"
SAMPLES = ROOT / "data" / "samples"
BANK = "BANCO FICTICIO"


def _load_generator() -> Any:
    """Load scripts/generate_samples.py by path (scripts/ is not a package)."""
    spec = importlib.util.spec_from_file_location("generate_samples_vf", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["generate_samples_vf"] = module
    spec.loader.exec_module(module)
    return module


gen = _load_generator()

# Planted rows of design 7.2, restated here as (day, signed amount, counterparty, description).
Planted = tuple[date, str, str, str]


def _expected_planted() -> list[Planted]:
    """The planted table of design 7.2, written independently of the generator."""
    rows: list[Planted] = []
    fee = "Comisión mantenimiento cuenta"
    rows += [(date(2025, m, 5), "-5.00", BANK, fee) for m in range(1, 13)]
    rows += [(date(2026, m, 5), "-6.50", BANK, fee) for m in range(1, 11)]
    for d in ("2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31"):
        rows.append((date.fromisoformat(d), "-9.00", BANK, "Comisión custodia valores"))
    for d in ("2026-03-31", "2026-06-30", "2026-09-30"):
        rows.append((date.fromisoformat(d), "-9.00", BANK, "Comisión custodia valores"))
    for d in ("2025-02-14", "2026-02-16"):
        rows.append((date.fromisoformat(d), "-30.00", BANK, "Comisión anual tarjeta débito"))
    interest = (
        ("2025-06-30", "-12.40"),
        ("2025-09-30", "-7.85"),
        ("2026-03-31", "-22.10"),
        ("2026-06-30", "-18.65"),
    )
    rows += [(date.fromisoformat(d), a, BANK, "Intereses deudores") for d, a in interest]
    for d in ("2025-06-18", "2026-03-20", "2026-06-15"):
        rows.append((date.fromisoformat(d), "-15.00", BANK, "Comisión por descubierto"))
    for d in ("2025-04-09", "2025-07-22", "2026-02-03", "2026-08-27"):
        rows.append((date.fromisoformat(d), "-1.50", BANK, "Comisión transferencia inmediata"))
    for d in ("2025-05-02", "2025-06-01"):
        rows.append((date.fromisoformat(d), "-4.00", BANK, "Comisión emisión cheque"))
    rows.append((date(2025, 10, 14), "-11.25", BANK, "Commission foreign payment"))
    rows.append((date(2025, 8, 19), "-23.40", "Feelgood Market", "Card purchase"))
    rows.append((date(2025, 4, 10), "1.50", BANK, "Devolución comisión transferencia"))
    rows.append((date(2026, 6, 30), "0.84", BANK, "Abono intereses"))
    rows.append(
        (date(2026, 4, 17), "-412.60", "Notaría Ana García", "Transferencia gastos escritura")
    )
    months = [(2025 + i // 12, i % 12 + 1) for i in range(22)]
    rows += [
        (date(y, m, 10), "-9.99", "STREAMFLIX INTL", "Monthly subscription") for y, m in months
    ]
    rows += [(date(y, m, 28), "1850.00", "Luminar Estudio S.L.", "Payroll") for y, m in months]
    rows.append((date(2025, 1, 2), "800.00", "Ahorro Ana García", "Transfer from savings"))
    rows.append((date(2026, 10, 30), "-19.90", "Papelería Azul", "Card purchase"))
    return rows


def _as_tuples(rows: list[Any]) -> list[Planted]:
    """BankRow list as plain tuples."""
    return [(r.day, r.amount, r.counterparty, r.description) for r in rows]


# --- Tier 1 -------------------------------------------------------------------------------------


def test_demo_has_227_rows_25_credits_202_debits() -> None:
    """Design 7.2 row counts."""
    rows = gen.build_vampire_demo_rows(42)
    assert len(rows) == 227
    assert sum(1 for r in rows if not r.amount.startswith("-")) == 25
    assert sum(1 for r in rows if r.amount.startswith("-")) == 202


def test_demo_runs_from_the_first_to_the_last_planted_day() -> None:
    """First row 2025-01-02, last row 2026-10-30."""
    rows = gen.build_vampire_demo_rows(42)
    assert rows[0].day == date(2025, 1, 2) == gen.VAMPIRE_DEMO_START
    assert rows[-1].day == date(2026, 10, 30) == gen.VAMPIRE_DEMO_END
    assert min(r.day for r in rows) == date(2025, 1, 2)
    assert max(r.day for r in rows) == date(2026, 10, 30)


def test_planted_table_is_present_exactly() -> None:
    """Every planted row of design 7.2 is present, with the right multiplicity."""
    expected = _expected_planted()
    assert len(expected) == 95
    planted = _as_tuples(gen.build_vampire_planted_rows())
    assert Counter(planted) == Counter(expected)
    demo = Counter(_as_tuples(gen.build_vampire_demo_rows(42)))
    assert not (Counter(expected) - demo)


def test_planted_fee_rows_are_45() -> None:
    """The planted fees (A, B, C, D, E, F) are 45 rows totalling 379.25."""
    fee_words = ("Comisión", "Commission", "Intereses deudores")
    fees = [t for t in _expected_planted() if t[3].startswith(fee_words) and t[1].startswith("-")]
    assert len(fees) == 45
    assert sum((Decimal(t[1]) for t in fees), Decimal(0)) == Decimal("-379.25")


# --- Tier 2 -------------------------------------------------------------------------------------


def test_same_seed_same_bytes() -> None:
    """Determinism of both renderings."""
    assert gen.build_vampire_demo_csv(42) == gen.build_vampire_demo_csv(42)
    assert gen.build_vampire_demo_n43(42) == gen.build_vampire_demo_n43(42)


def test_another_seed_changes_only_the_noise() -> None:
    """The planted rows are identical for every seed; the noise rows are card purchases."""
    noise_42 = _as_tuples(gen.build_vampire_noise_rows(42))
    noise_43 = _as_tuples(gen.build_vampire_noise_rows(43))
    assert noise_42 != noise_43
    assert len(noise_42) == len(noise_43) == 132
    assert {t[3] for t in noise_42 + noise_43} == {"Card purchase"}
    rest_42 = Counter(_as_tuples(gen.build_vampire_demo_rows(42))) - Counter(noise_42)
    rest_43 = Counter(_as_tuples(gen.build_vampire_demo_rows(43))) - Counter(noise_43)
    assert rest_42 == rest_43 == Counter(_expected_planted())


@pytest.mark.parametrize("seed", range(21))
def test_noise_shop_names_hold_no_vocabulary_phrase(seed: int) -> None:
    """No noise shop (counterparty or description) matches any vocabulary phrase."""
    vocabulary = default_vocabulary()
    phrases = vocabulary.fee + vocabulary.overdraft + vocabulary.interest + vocabulary.exclude
    for row in gen.build_vampire_noise_rows(seed):
        assert not contains_phrase(fold_tokens(row.counterparty), phrases), row
        assert not contains_phrase(fold_tokens(row.description), phrases), row


def test_noise_amounts_are_two_decimal_debits_in_range() -> None:
    """Noise amounts are built from integer cents: -3.00 to -95.00, two decimals."""
    for row in gen.build_vampire_noise_rows(42):
        assert row.amount.startswith("-")
        whole, _, cents = row.amount.removeprefix("-").partition(".")
        assert len(cents) == 2 and 3 <= int(whole) <= 95
        assert gen.VAMPIRE_NOISE_DAYS[0] <= row.day.day <= gen.VAMPIRE_NOISE_DAYS[1]


def test_csv_is_plain_bank_csv_that_the_reader_accepts() -> None:
    """The CSV has the bank columns and reads as 227 transactions without quarantine."""
    text = gen.build_vampire_demo_csv(42)
    assert text.splitlines()[0] == "date,amount,currency,counterparty,description,iban"
    transactions, quarantined = read_bank_statement(io.BytesIO(text.encode("utf-8")))
    assert quarantined == []
    assert len(transactions) == 227


def test_n43_reads_as_227_transactions_without_quarantine() -> None:
    """The Norma 43 file passes the reader and its control checks."""
    transactions, quarantined = read_bank_statement(io.BytesIO(gen.build_vampire_demo_n43(42)))
    assert quarantined == []
    assert len(transactions) == 227


def test_n43_concepts_of_the_fee_descriptions() -> None:
    """17 for the fee descriptions, 16 for custody, 04 for the notary transfer."""
    transactions, _ = read_bank_statement(io.BytesIO(gen.build_vampire_demo_n43(42)))
    concepts: dict[str, set[str]] = {}
    for tx in transactions:
        tags = [t for t in tx.tags if t.startswith("common_concept:")]
        concepts.setdefault(tx.description, set()).update(t.split(":")[1] for t in tags)
    seventeen = (
        "Comisión mantenimiento cuenta",
        "Comisión anual tarjeta débito",
        "Comisión por descubierto",
        "Intereses deudores",
        "Comisión transferencia inmediata",
        "Comisión emisión cheque",
        "Commission foreign payment",
        "Devolución comisión transferencia",
        "Abono intereses",
    )
    for description in seventeen:
        assert concepts[description] == {"17"}, description
    assert concepts["Comisión custodia valores"] == {"16"}
    assert concepts["Transferencia gastos escritura"] == {"04"}
    assert concepts["Transfer from savings"] == {"04"}
    assert concepts["Card purchase"] == {"12"}
    assert concepts["Payroll"] == {"15"}
    assert concepts["Monthly subscription"] == {"03"}


def test_main_writes_both_files(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The mode writes the CSV and the Norma 43 file into --out-dir and prints their paths."""
    assert gen.main(["--mode", "vampire-demo", "--out-dir", str(tmp_path)]) == 0
    csv_path = tmp_path / gen.VAMPIRE_DEMO_FILE
    n43_path = tmp_path / gen.VAMPIRE_DEMO_N43_FILE
    assert csv_path.read_bytes() == gen.build_vampire_demo_csv(42).encode("utf-8")
    assert n43_path.read_bytes() == gen.build_vampire_demo_n43(42)
    out = capsys.readouterr().out
    assert "vampire_demo_statement.csv" in out and "vampire_demo_statement.n43" in out


def test_main_seed_changes_the_written_noise(tmp_path: Path) -> None:
    """--seed reaches the builder."""
    assert gen.main(["--mode", "vampire-demo", "--seed", "7", "--out-dir", str(tmp_path)]) == 0
    assert (tmp_path / gen.VAMPIRE_DEMO_FILE).read_bytes() == gen.build_vampire_demo_csv(7).encode(
        "utf-8"
    )


def test_existing_demo_modes_are_unchanged() -> None:
    """The zombie demo bytes still equal the committed files (existing output unchanged)."""
    committed_csv = (SAMPLES / "zombie_demo_statement.csv").read_bytes()
    committed_n43 = (SAMPLES / "zombie_demo_statement.n43").read_bytes()
    assert gen.build_zombie_demo_csv(42).encode("utf-8") == committed_csv
    assert gen.build_zombie_demo_n43(42) == committed_n43


def test_no_iban_and_only_fictional_names_in_the_demo() -> None:
    """REQ-VF-54: no IBAN column value and a fixed allow-list of counterparties."""
    rows = gen.build_vampire_demo_rows(42)
    assert all(row.iban == "" for row in rows)
    allowed = {
        BANK,
        "Feelgood Market",
        "Notaría Ana García",
        "STREAMFLIX INTL",
        "Luminar Estudio S.L.",
        "Ahorro Ana García",
        "Mercado Central Demo",
        "Café del Puerto",
        "Tienda Luna",
        "Farmacia Sol",
        "Gasolinera Norte",
        "Papelería Azul",
        "Librería Poniente",
    }
    assert {row.counterparty for row in rows} <= allowed
