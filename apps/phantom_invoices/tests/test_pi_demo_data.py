"""Tests for the committed phantom demo files in data/samples/phantom_demo/ (Task P21).

The files are written by ``python scripts/generate_samples.py --mode phantom-demo --seed 42``;
these tests fail until they exist and equal the generator output byte for byte.
"""

import csv
import io
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from apps.phantom_invoices.prepare import MULTI_RATE_REASON, quarantine_multi_rate
from apps.phantom_invoices.tests.pi_builders import generator
from apps.phantom_invoices.tests.pi_checkers import (
    mod97_remainder,
    spanish_national_dc_ok,
    tax_id_control_ok,
)
from ledger_kit.ingestion.csv_reader import parse_csv
from ledger_kit.ingestion.invoice_reader import parse_invoice
from ledger_kit.ingestion.normaliser import normalise
from ledger_kit.ingestion.supplier_reader import parse_suppliers

SEED = 42
REPO_ROOT = Path(__file__).resolve().parents[3]
DEMO_DIR = REPO_ROOT / "data" / "samples" / "phantom_demo"
NAMES = ("suppliers.csv", "invoices.csv", "payments.csv")
UTF8_BOM = b"\xef\xbb\xbf"


def _committed(name: str) -> bytes:
    """The bytes of one committed demo file."""
    return (DEMO_DIR / name).read_bytes()


def _rows(name: str) -> list[dict[str, str]]:
    """One dict per data row of a committed demo file."""
    text = _committed(name).decode("utf-8")
    return list(csv.DictReader(io.StringIO(text, newline="")))


@pytest.mark.parametrize("name", NAMES)
def test_committed_files_equal_generator_output(name):
    expected = generator.build_phantom_demo(SEED)[name].encode("utf-8")
    assert _committed(name) == expected


@pytest.mark.parametrize("name", NAMES)
def test_committed_files_have_lf_line_endings_and_no_bom(name):
    data = _committed(name)
    assert not data.startswith(UTF8_BOM)
    assert b"\r" not in data
    assert data.endswith(b"\n")


def test_regenerating_into_tmp_path_twice_is_byte_identical(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    generator.write_phantom_demo(first, SEED)
    generator.write_phantom_demo(second, SEED)
    expected = generator.build_phantom_demo(SEED)
    for name in NAMES:
        assert (first / name).read_bytes() == (second / name).read_bytes()
        assert (first / name).read_bytes() == expected[name].encode("utf-8")


def test_committed_files_parse_with_ledger_core_readers_and_zero_quarantine_except_multi_rate():
    invoices, invoice_q = parse_invoice(
        io.BytesIO(_committed("invoices.csv")), fmt="csv", source_file="invoices.csv"
    )
    suppliers, supplier_q = parse_suppliers(
        io.BytesIO(_committed("suppliers.csv")), source_file="suppliers.csv"
    )
    payments, payment_q = parse_csv(
        io.BytesIO(_committed("payments.csv")), source_file="payments.csv"
    )
    assert invoice_q == [] and supplier_q == [] and payment_q == []
    assert (len(invoices), len(suppliers), len(payments)) == (70, 25, 62)

    invoice_frame, invoice_n = normalise(invoices, kind="invoice")
    _, supplier_n = normalise(suppliers, kind="supplier")
    _, payment_n = normalise(payments, kind="transaction")
    assert invoice_n == [] and supplier_n == [] and payment_n == []

    clean, quarantined = quarantine_multi_rate(invoice_frame)
    assert len(clean) == 68
    assert len(quarantined) == 2
    assert {record["reason"] for record in quarantined} == {MULTI_RATE_REASON}
    assert {record["raw"]["invoice_number"] for record in quarantined} == {"OB-2026-008"}


def test_identifier_rules_on_committed_files():
    seen = 0
    for name in NAMES:
        text = _committed(name).decode("utf-8")
        assert "@" not in text and "+" not in text, name
        assert not re.search(r"\b\d{3}[ -]\d{3}[ -]\d{3}\b", text), name
        for row in _rows(name):
            cell = row["iban"]
            if cell == "":
                continue
            compact = re.sub(r"[\s-]", "", cell).upper()
            assert mod97_remainder(compact) == 1, (name, cell)
            assert not spanish_national_dc_ok(compact), (name, cell)
            seen += 1
    assert seen > 100

    tax_ids = [row["tax_id"] for row in _rows("suppliers.csv")]
    assert len(tax_ids) == len(set(tax_ids)) == 25
    assert all(not tax_id_control_ok(tax_id) for tax_id in tax_ids)
    assert {row["supplier_tax_id"] for row in _rows("invoices.csv")} <= set(tax_ids)


@pytest.mark.parametrize("name", NAMES)
def test_gitignore_still_allows_data_samples_phantom_demo(name):
    if shutil.which("git") is None:
        pytest.skip("git is not on PATH")
    if not (REPO_ROOT / ".git").exists():
        pytest.skip("the project folder is not a git repository")
    path = f"data/samples/phantom_demo/{name}"
    result = subprocess.run(
        ["git", "check-ignore", "-q", "--", path],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, f"{path} is ignored by .gitignore (exit {result.returncode})"
