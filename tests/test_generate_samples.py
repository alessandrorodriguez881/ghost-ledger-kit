"""Tests for scripts/generate_samples.py and the committed files in data/samples/ (Task 13)."""

from __future__ import annotations

import csv
import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ledger_kit.ingestion.csv_reader import parse_csv
from ledger_kit.ingestion.invoice_reader import parse_invoice
from ledger_kit.ingestion.normaliser import (
    CANONICAL_COLUMNS,
    INVOICE_COLUMNS,
    SUPPLIER_COLUMNS,
    normalise,
)
from ledger_kit.ingestion.supplier_reader import parse_suppliers
from ledger_kit.utils.money import net_total, percent_of

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "generate_samples.py"
SAMPLES = ROOT / "data" / "samples"


def _load_generator():
    """Load scripts/generate_samples.py by path (scripts/ is not a package)."""
    spec = importlib.util.spec_from_file_location("generate_samples", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["generate_samples"] = module
    spec.loader.exec_module(module)
    return module


gen = _load_generator()

NIF_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"


# --- independent checkers (not shared with the generator) ---------------------------------------
def _clean_iban(text: str) -> str:
    """Remove whitespace and upper-case an IBAN."""
    return "".join(text.split()).upper()


def _mod97_valid(iban: str) -> bool:
    """ISO 13616 checksum: move 4 characters to the end, letters to numbers, mod 97 == 1."""
    rearranged = iban[4:] + iban[:4]
    return int("".join(str(int(ch, 36)) for ch in rearranged)) % 97 == 1


def _spanish_digit(digits: str) -> int:
    """One Spanish national control digit (weights 1 2 4 8 5 10 9 7 3 6)."""
    weights = (1, 2, 4, 8, 5, 10, 9, 7, 3, 6)
    remainder = 11 - sum(int(d) * w for d, w in zip(digits, weights, strict=True)) % 11
    return {11: 0, 10: 1}.get(remainder, remainder)


def _national_digits_are_correct(iban: str) -> bool:
    """True when the two national check digits inside a Spanish IBAN are the right ones."""
    bank, branch, check, account = iban[4:8], iban[8:12], iban[12:14], iban[14:]
    expected = f"{_spanish_digit('00' + bank + branch)}{_spanish_digit(account)}"
    return check == expected


def _tax_id_control_is_wrong(tax_id: str) -> bool:
    """True when the control character of a CIF (type B) or NIF is NOT the correct one."""
    if len(tax_id) == 9 and tax_id[0] == "B" and tax_id[1:].isdigit():
        body, control = tax_id[1:8], tax_id[8]
        total = 0
        for position, ch in enumerate(body, start=1):
            digit = int(ch)
            if position % 2 == 1:
                digit = sum(divmod(digit * 2, 10))
            total += digit
        correct = (10 - total % 10) % 10
        return control not in (str(correct), "JABCDEFGHI"[correct])
    if len(tax_id) == 9 and tax_id[:8].isdigit() and tax_id[8].isalpha():
        return tax_id[8] != NIF_LETTERS[int(tax_id[:8]) % 23]
    raise AssertionError(f"unrecognised tax id format: {tax_id!r}")


# --- reading the committed files ----------------------------------------------------------------
def _text(name: str) -> str:
    """Committed file as text with LF endings (tolerates a CRLF checkout)."""
    return (SAMPLES / name).read_bytes().decode("utf-8").replace("\r\n", "\n")


def _cells(name: str, column: str, delimiter: str = ",") -> list[str]:
    """Raw text of one column of a committed CSV file."""
    reader = csv.DictReader(io.StringIO(_text(name), newline=""), delimiter=delimiter)
    return [row[column] for row in reader]


def _all_ibans() -> list[str]:
    """Every non-empty IBAN text found in the five sample files."""
    found = _cells(gen.BANK_FILE, "iban") + _cells(gen.BANK_FILE_ES, "iban", ";")
    found += _cells(gen.INVOICE_CSV_FILE, "iban") + _cells(gen.SUPPLIERS_FILE, "iban")
    found += [rec["iban"] for rec in json.loads(_text(gen.INVOICE_JSON_FILE)) if "iban" in rec]
    return [value for value in found if value.strip()]


def _all_tax_ids() -> list[str]:
    """Every tax id text found in the invoice and supplier samples."""
    found = _cells(gen.INVOICE_CSV_FILE, "supplier_tax_id") + _cells(gen.SUPPLIERS_FILE, "tax_id")
    found += [rec["supplier_tax_id"] for rec in json.loads(_text(gen.INVOICE_JSON_FILE))]
    return found


def _ingest():
    """Parse all five committed files; returns {file name: (models, quarantine)}."""
    return {
        gen.BANK_FILE: parse_csv(SAMPLES / gen.BANK_FILE),
        gen.BANK_FILE_ES: parse_csv(SAMPLES / gen.BANK_FILE_ES),
        gen.INVOICE_CSV_FILE: parse_invoice(SAMPLES / gen.INVOICE_CSV_FILE),
        gen.INVOICE_JSON_FILE: parse_invoice(SAMPLES / gen.INVOICE_JSON_FILE),
        gen.SUPPLIERS_FILE: parse_suppliers(SAMPLES / gen.SUPPLIERS_FILE),
    }


def _without_source(invoice) -> dict:
    """Invoice fields minus the file-specific ones."""
    data = invoice.model_dump()
    for key in ("source_file", "source_ref", "source_line"):
        del data[key]
    return data


# --- Task 13 verify conditions ------------------------------------------------------------------
def test_committed_files_equal_generator_output():
    """Every committed sample is byte-identical to what the generator produces."""
    for name, text in gen.build_core_samples().items():
        committed = (SAMPLES / name).read_bytes().replace(b"\r\n", b"\n")
        assert committed == text.encode("utf-8"), f"{name} is stale; rerun generate_samples.py"


def test_exactly_the_five_documented_sample_files_are_generated():
    assert tuple(gen.build_core_samples()) == gen.SAMPLE_FILES


def test_all_sample_files_ingest_with_zero_quarantine():
    expected_counts = {
        gen.BANK_FILE: 10,
        gen.BANK_FILE_ES: 10,
        gen.INVOICE_CSV_FILE: 5,
        gen.INVOICE_JSON_FILE: 5,
        gen.SUPPLIERS_FILE: 3,
    }
    for name, (models, quarantined) in _ingest().items():
        assert quarantined == [], name
        assert len(models) == expected_counts[name], name


def test_normalise_accepts_every_sample():
    parsed = _ingest()
    for name in (gen.BANK_FILE, gen.BANK_FILE_ES):
        frame, quarantined = normalise(parsed[name][0])
        assert quarantined == []
        assert len(frame) == 10
        assert tuple(frame.columns) == CANONICAL_COLUMNS
    for name in (gen.INVOICE_CSV_FILE, gen.INVOICE_JSON_FILE):
        frame, quarantined = normalise(parsed[name][0])
        assert quarantined == []
        assert len(frame) == 5
        assert tuple(frame.columns) == INVOICE_COLUMNS
    frame, quarantined = normalise(parsed[gen.SUPPLIERS_FILE][0])
    assert quarantined == []
    assert len(frame) == 3
    assert tuple(frame.columns) == SUPPLIER_COLUMNS


def test_bank_ibans_read_equal_file_text():
    for name, delimiter in ((gen.BANK_FILE, ","), (gen.BANK_FILE_ES, ";")):
        cells = _cells(name, "iban", delimiter)
        transactions, _ = parse_csv(SAMPLES / name)
        assert [t.iban for t in transactions] == [c if c.strip() else None for c in cells]
        assert sum(1 for t in transactions if t.iban is not None) >= 3


def test_invoice_and_supplier_ibans_read_equal_file_text():
    suppliers, _ = parse_suppliers(SAMPLES / gen.SUPPLIERS_FILE)
    cells = _cells(gen.SUPPLIERS_FILE, "iban")
    assert [s.iban for s in suppliers] == [c if c.strip() else None for c in cells]
    invoices, _ = parse_invoice(SAMPLES / gen.INVOICE_CSV_FILE)
    cells = _cells(gen.INVOICE_CSV_FILE, "iban")
    assert [i.iban for i in invoices] == [c if c.strip() else None for c in cells]


def test_every_iban_is_mod97_valid_with_wrong_national_digits():
    ibans = _all_ibans()
    assert len(ibans) >= 10
    for text in ibans:
        iban = _clean_iban(text)
        assert iban.startswith("ES") and len(iban) == 24 and iban[2:].isdigit(), text
        assert _mod97_valid(iban), text
        assert not _national_digits_are_correct(iban), text


def test_every_tax_id_has_a_wrong_control_character():
    tax_ids = _all_tax_ids()
    assert len(tax_ids) == 5 + 3 + 5  # CSV invoices + suppliers + JSON invoices
    for tax_id in tax_ids:
        assert _tax_id_control_is_wrong(tax_id), tax_id
        assert tax_id != "00000000T"


def test_each_supplier_has_a_different_tax_id_and_invoices_use_only_those():
    suppliers, _ = parse_suppliers(SAMPLES / gen.SUPPLIERS_FILE)
    master = {s.tax_id for s in suppliers}
    assert len(master) == len(suppliers) == 3
    assert set(_all_tax_ids()) == master


def test_no_email_addresses_or_phone_numbers_in_samples():
    for name in gen.SAMPLE_FILES:
        text = _text(name)
        assert "@" not in text, name
        assert "+34" not in text, name


# --- sample content ------------------------------------------------------------------------------
def test_bank_sample_has_debits_and_credits_and_amounts_are_decimal():
    transactions, _ = parse_csv(SAMPLES / gen.BANK_FILE)
    assert {t.flow for t in transactions} == {"debit", "credit"}
    assert all(t.amount > 0 and t.amount.as_tuple().exponent == -2 for t in transactions)


def test_european_sample_parses_to_the_same_rows_as_the_plain_sample():
    plain, _ = parse_csv(SAMPLES / gen.BANK_FILE)
    european, _ = parse_csv(SAMPLES / gen.BANK_FILE_ES)
    fields = ("date", "amount", "flow", "currency", "counterparty", "description", "iban")
    assert [tuple(getattr(t, f) for f in fields) for t in plain] == [
        tuple(getattr(t, f) for f in fields) for t in european
    ]


def test_invoice_csv_and_json_hold_the_same_invoices():
    from_csv, _ = parse_invoice(SAMPLES / gen.INVOICE_CSV_FILE)
    from_json, _ = parse_invoice(SAMPLES / gen.INVOICE_JSON_FILE)
    assert [_without_source(i) for i in from_csv] == [_without_source(i) for i in from_json]


def test_invoice_sample_covers_optional_columns():
    invoices, _ = parse_invoice(SAMPLES / gen.INVOICE_CSV_FILE)
    assert [i.due_date_is_default for i in invoices].count(True) == 1
    with_both = [i for i in invoices if i.surcharge_amount > 0 and i.withholding_amount > 0]
    assert len(with_both) == 1
    assert any(i.iban is None for i in invoices)


def test_invoice_amounts_are_consistent():
    invoices, _ = parse_invoice(SAMPLES / gen.INVOICE_CSV_FILE)
    for invoice in invoices:
        assert invoice.vat_amount == percent_of(invoice.base_amount, invoice.vat_rate)
        expected = net_total(
            [invoice.base_amount, invoice.vat_amount, invoice.surcharge_amount],
            [invoice.withholding_amount],
        )
        assert invoice.total == expected, invoice.invoice_number


def test_invoice_json_mixes_string_and_numeric_amounts():
    records = json.loads(_text(gen.INVOICE_JSON_FILE))
    kinds = {type(rec["base_amount"]) for rec in records}
    assert str in kinds
    assert kinds & {int, float}


def test_suppliers_sample_has_one_empty_iban():
    suppliers, _ = parse_suppliers(SAMPLES / gen.SUPPLIERS_FILE)
    assert [s.iban is None for s in suppliers].count(True) == 1


# --- generator logic ------------------------------------------------------------------------------
def test_documented_iban_example_is_reproduced():
    assert gen.correct_national_dc("2100", "0418", "0200051332") == "45"
    assert gen.wrong_national_dc("2100", "0418", "0200051332") == "56"
    iban = gen.format_iban(gen.make_iban("2100", "0418", "0200051332"))
    assert iban == "ES88 2100 0418 5602 0005 1332"


def test_tax_id_helpers_never_produce_a_correct_control_character():
    for k in range(1, 60):
        assert _tax_id_control_is_wrong(gen.make_cif(k)), k
        assert _tax_id_control_is_wrong(gen.make_nif(k)), k
    assert gen.make_nif(12) == "00001013" + NIF_LETTERS[(1013 % 23 + 1) % 23]


def test_core_samples_do_not_depend_on_the_seed():
    assert gen.build_core_samples() == gen.build_core_samples()


@pytest.mark.parametrize("dialect", ["plain", "european"])
def test_bank_mode_fixed_seed_is_reproducible_and_ingests_cleanly(dialect):
    text = gen.build_bank_statement(42, 25, dialect)
    assert text == gen.build_bank_statement(42, 25, dialect)
    assert text != gen.build_bank_statement(43, 25, dialect)
    transactions, quarantined = parse_csv(io.StringIO(text), dialect=dialect, source_file="g.csv")
    assert quarantined == []
    assert len(transactions) == 25


def test_main_samples_mode_writes_the_five_files(tmp_path):
    assert gen.main(["--mode", "samples", "--out-dir", str(tmp_path)]) == 0
    for name, text in gen.build_core_samples().items():
        assert (tmp_path / name).read_bytes() == text.encode("utf-8")


def test_main_bank_mode_writes_output_file(tmp_path):
    target = tmp_path / "bank.csv"
    args = ["--mode", "bank", "--seed", "7", "--rows", "12", "--dialect", "european"]
    assert gen.main([*args, "--output", str(target)]) == 0
    assert target.read_bytes() == gen.build_bank_statement(7, 12, "european").encode("utf-8")


def test_phantom_demo_mode_is_implemented_by_the_phantom_invoices_spec(capsys, tmp_path):
    """phantom-demo is no longer a stub: it writes the demo files (Task P18, real formats RF7)."""
    assert gen.main(["--mode", "phantom-demo", "--out-dir", str(tmp_path)]) == 0
    demo = tmp_path / "phantom_demo"
    written = sorted(p.name for p in demo.iterdir())
    assert written == ["facturae", "invoices.csv", "payments.csv", "payments.n43", "suppliers.csv"]
    assert len(list((demo / "facturae").iterdir())) == 25
    assert "phantom_demo" in capsys.readouterr().out


def test_zombie_demo_mode_is_implemented_by_the_zombie_subscriptions_spec(capsys, tmp_path):
    """zombie-demo is no longer a stub: it writes the demo statement (Task Z19, RF7)."""
    assert gen.main(["--mode", "zombie-demo", "--out-dir", str(tmp_path)]) == 0
    written = sorted(p.name for p in tmp_path.iterdir())
    assert written == ["zombie_demo_statement.csv", "zombie_demo_statement.n43"]
    assert "zombie_demo_statement.csv" in capsys.readouterr().out


def test_vampire_demo_mode_is_implemented(capsys, tmp_path):
    """vampire-demo writes the demo statement as CSV and as Norma 43 (vampire-fees VF12)."""
    assert gen.main(["--mode", "vampire-demo", "--out-dir", str(tmp_path)]) == 0
    written = sorted(p.name for p in tmp_path.iterdir())
    assert written == ["vampire_demo_statement.csv", "vampire_demo_statement.n43"]
    assert "vampire_demo_statement.csv" in capsys.readouterr().out


def test_main_rejects_negative_rows(capsys):
    assert gen.main(["--mode", "bank", "--rows", "-1"]) == 2
    assert "--rows" in capsys.readouterr().err


# --- Tier 3: properties -------------------------------------------------------------------------
@settings(max_examples=200)
@given(
    seed=st.integers(min_value=0, max_value=2**32 - 1),
    rows=st.integers(min_value=0, max_value=30),
    dialect=st.sampled_from(["plain", "european"]),
)
def test_any_seed_gives_reproducible_clean_synthetic_statement(seed, rows, dialect):
    text = gen.build_bank_statement(seed, rows, dialect)
    assert text == gen.build_bank_statement(seed, rows, dialect)
    transactions, quarantined = parse_csv(io.StringIO(text), dialect=dialect, source_file="g.csv")
    assert quarantined == []
    assert len(transactions) == rows
    for transaction in transactions:
        assert transaction.amount.as_tuple().exponent == -2
        if transaction.iban is not None:
            iban = _clean_iban(transaction.iban)
            assert _mod97_valid(iban)
            assert not _national_digits_are_correct(iban)


@settings(max_examples=200)
@given(
    bank=st.text(alphabet="0123456789", min_size=4, max_size=4),
    branch=st.text(alphabet="0123456789", min_size=4, max_size=4),
    account=st.text(alphabet="0123456789", min_size=10, max_size=10),
)
def test_make_iban_is_mod97_valid_with_wrong_national_digits(bank, branch, account):
    iban = gen.make_iban(bank, branch, account)
    assert _mod97_valid(iban)
    assert not _national_digits_are_correct(iban)
