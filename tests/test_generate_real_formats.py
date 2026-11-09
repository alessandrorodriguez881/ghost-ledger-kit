"""Tests for the Norma 43 and Facturae writers of scripts/generate_samples.py (Task RF7).

The generator is loaded by path (scripts/ is not a package). The committed-files tests at the
end fail until `python scripts/generate_samples.py --mode zombie-demo --seed 42` and
`--mode phantom-demo --seed 42` have been run and their output committed.
"""

from __future__ import annotations

import csv
import functools
import importlib.util
import io
import re
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, NamedTuple

import pytest
from defusedxml.ElementTree import fromstring

from ledger_kit.ingestion.facturae_reader import parse_facturae
from ledger_kit.ingestion.invoice_reader import parse_invoice
from ledger_kit.ingestion.norma43_reader import parse_norma43

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "generate_samples.py"
SAMPLES = ROOT / "data" / "samples"
PHANTOM_DIR = SAMPLES / "phantom_demo"
SEED = 42

# The 25 file names of REQ-RF-26, written out (not derived from the generator).
FACTURAE_NAMES: tuple[str, ...] = (
    "01-p1.xml",
    "02-p2.xml",
    "03-p3.xml",
    "04-p4.xml",
    "05-p5.xml",
    "06-p6.xml",
    "07-p7.xml",
    "08-p8.xml",
    "09-p9.xml",
    "10-p10.xml",
    "11-p11.xml",
    "12-p12.xml",
    "13-non-master-payment.xml",
    "14-overdue.xml",
    "15-open-not-due.xml",
    "16-multi-rate.xml",
    "17-c1.xml",
    "18-c2.xml",
    "19-c3.xml",
    "20-c4.xml",
    "21-c5.xml",
    "22-c6.xml",
    "23-c7.xml",
    "24-c8.xml",
    "25-c9.xml",
)
PERSON_FILES = frozenset({"08-p8.xml", "09-p9.xml", "12-p12.xml", "19-c3.xml", "23-c7.xml"})
MULTI_RATE_FILE = "16-multi-rate.xml"
WITHHOLDING_FILE = "08-p8.xml"
SURCHARGE_FILE = "11-p11.xml"
ZOMBIE_N43 = "zombie_demo_statement.n43"

# Element order of the official Facturaev3_2_2 schema for the elements the writer emits.
FILE_HEADER = ["SchemaVersion", "Modality", "InvoiceIssuerType", "Batch"]
BATCH = [
    "BatchIdentifier",
    "InvoicesCount",
    "TotalInvoicesAmount",
    "TotalOutstandingAmount",
    "TotalExecutableAmount",
    "InvoiceCurrencyCode",
]
TAX_IDENTIFICATION = ["PersonTypeCode", "ResidenceTypeCode", "TaxIdentificationNumber"]
ADDRESS = ["Address", "PostCode", "Town", "Province", "CountryCode"]
LEGAL_ENTITY = ["CorporateName", "AddressInSpain"]
INDIVIDUAL = ["Name", "FirstSurname", "AddressInSpain"]
INVOICE_ORDER = [
    "InvoiceHeader",
    "InvoiceIssueData",
    "TaxesOutputs",
    "TaxesWithheld",
    "InvoiceTotals",
    "Items",
    "PaymentDetails",
]
INVOICE_HEADER = ["InvoiceNumber", "InvoiceDocumentType", "InvoiceClass"]
ISSUE_DATA = ["IssueDate", "InvoiceCurrencyCode", "TaxCurrencyCode", "LanguageName"]
TAX = ["TaxTypeCode", "TaxRate", "TaxableBase", "TaxAmount"]
SURCHARGE_TAX = [*TAX, "EquivalenceSurcharge", "EquivalenceSurchargeAmount"]
INVOICE_TOTALS = [
    "TotalGrossAmount",
    "TotalGrossAmountBeforeTaxes",
    "TotalTaxOutputs",
    "TotalTaxesWithheld",
    "InvoiceTotal",
    "TotalOutstandingAmount",
    "TotalExecutableAmount",
]
INVOICE_LINE = [
    "ItemDescription",
    "Quantity",
    "UnitPriceWithoutTax",
    "TotalCost",
    "GrossAmount",
    "TaxesOutputs",
]
INSTALLMENT = ["InstallmentDueDate", "InstallmentAmount", "PaymentMeans"]
# Elements written with exactly two decimals (amounts, rates, the unit quantity).
TWO_DECIMAL_TAGS = frozenset(
    [
        "TotalAmount",
        "TaxRate",
        "EquivalenceSurcharge",
        "Quantity",
        "UnitPriceWithoutTax",
        "TotalCost",
        *INVOICE_TOTALS,
    ]
)

TWO_DECIMALS = re.compile(r"\d+\.\d{2}")
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _load_generator() -> Any:
    """Load scripts/generate_samples.py by path (scripts/ is not a package)."""
    spec = importlib.util.spec_from_file_location("generate_samples_rf7", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["generate_samples_rf7"] = module
    spec.loader.exec_module(module)
    return module


gen = _load_generator()


# --- helpers ------------------------------------------------------------------------------------
def _records(data: bytes) -> list[str]:
    """The lines of a Norma 43 file; the file must end with CRLF."""
    text = data.decode("iso-8859-1")
    assert text.endswith("\r\n")
    return text[:-2].split("\r\n")


def _span(line: str, start: int, end: int) -> str:
    """The 1-based, inclusive span of a record, as the AEB document writes positions."""
    return line[start - 1 : end]


def _yymmdd(day: date) -> str:
    """A date as the YYMMDD text of a record."""
    return f"{day.year % 100:02d}{day.month:02d}{day.day:02d}"


def _amount(digits: str) -> Decimal:
    """A 14-digit field with two implied decimals."""
    assert len(digits) == 14 and digits.isdigit(), digits
    return Decimal(int(digits)).scaleb(-2)


def _movements(lines: list[str]) -> list[tuple[str, list[str]]]:
    """Each record 22 with the record 23 lines that follow it."""
    groups: list[tuple[str, list[str]]] = []
    for line in lines:
        if line.startswith("22"):
            groups.append((line, []))
        elif line.startswith("23"):
            groups[-1][1].append(line)
    return groups


def _magnitude(row: Any) -> Decimal:
    """The absolute amount of a bank row."""
    return Decimal(row.amount.removeprefix("-"))


def _is_debit(row: Any) -> bool:
    """True when the bank row is a debit (negative amount text)."""
    return row.amount.startswith("-")


def _transaction_fields(transaction: Any) -> tuple[Any, ...]:
    """The fields of a Transaction that a bank row determines."""
    return (
        transaction.date,
        transaction.amount,
        transaction.flow,
        transaction.counterparty,
        transaction.description,
        transaction.iban,
    )


def _children(element: Any) -> list[str]:
    """The tags of the children of an element, in order."""
    return [child.tag for child in element]


def _compact(iban: str) -> str:
    """An IBAN without spaces or hyphens, upper-cased."""
    return re.sub(r"[\s-]", "", iban).upper()


def _csv_rows(text: str) -> list[dict[str, str]]:
    """The rows of a CSV text as dicts."""
    return list(csv.DictReader(io.StringIO(text, newline="")))


def _cif_control_ok(tax_id: str) -> bool:
    """True when the control character of a type-B CIF is the correct one."""
    total = 0
    for position, char in enumerate(tax_id[1:8], start=1):
        digit = int(char)
        if position % 2 == 1:
            digit = sum(divmod(digit * 2, 10))
        total += digit
    correct = (10 - total % 10) % 10
    return tax_id[8] in (str(correct), "JABCDEFGHI"[correct])


def _invoice_elements(root: Any) -> list[Any]:
    """The Invoice elements of a parsed Facturae file."""
    return list(root.find("Invoices"))


def _demo_record(**overrides: str) -> dict[str, str]:
    """One consistent invoice record (100,00 at 21 %) with the given overrides."""
    record = {
        "invoice_number": "T-001",
        "issue_date": "2026-06-01",
        "due_date": "2026-07-01",
        "base_amount": "100.00",
        "vat_rate": "21",
        "vat_amount": "21.00",
        "surcharge_amount": "",
        "surcharge_rate": "",
        "withholding_amount": "",
        "withholding_rate": "",
        "total": "121.00",
        "currency": "EUR",
        "iban": "",
    }
    record.update(overrides)
    return record


def _row(amount: str = "-10.00", **overrides: Any) -> Any:
    """One bank row for the writer tests."""
    values: dict[str, Any] = {
        "day": date(2026, 3, 4),
        "amount": amount,
        "counterparty": "Tienda Ficticia",
        "description": "Groceries",
        "iban": "",
    }
    values.update(overrides)
    return gen.BankRow(**values)


class N43Case(NamedTuple):
    """One generated Norma 43 file with the rows it was rendered from."""

    name: str
    rows: list[Any]
    data: bytes
    mode: str
    opening: Decimal


@pytest.fixture(scope="module", params=["zombie", "phantom"])
def n43(request: pytest.FixtureRequest) -> N43Case:
    """The zombie and the phantom Norma 43 files of seed 42."""
    if request.param == "zombie":
        rows = gen.build_zombie_demo_rows(SEED)
        data = gen.build_zombie_demo_n43(SEED)
        return N43Case("zombie", rows, data, "3", gen.N43_OPENING_BALANCE)
    rows = gen.build_phantom_demo_rows(SEED).payments
    data = gen.build_phantom_payments_n43(SEED)
    return N43Case("phantom", rows, data, "1", gen.N43_PHANTOM_OPENING_BALANCE)


@pytest.fixture(scope="module")
def facturae_files() -> dict[str, bytes]:
    """The 25 Facturae files of seed 42, by file name."""
    return gen.build_phantom_facturae(SEED)


@pytest.fixture(scope="module")
def facturae_roots(facturae_files: dict[str, bytes]) -> dict[str, Any]:
    """The parsed Facturae files, by file name."""
    return {name: fromstring(data) for name, data in facturae_files.items()}


SELLER = gen.FacturaeParty("Proveedor Ficticio Uno, S.L.", gen.make_cif(701), False)


# --- the CSV side is untouched ------------------------------------------------------------------
def test_csv_renderer_gives_the_same_text_as_build_phantom_demo():
    rows = gen.build_phantom_demo_rows(SEED)
    assert gen.render_phantom_demo_csv(rows) == gen.build_phantom_demo(SEED)


def test_invoice_records_keep_the_rates_outside_the_csv_columns():
    invoices = gen.build_phantom_demo_rows(SEED).invoices
    extra = {"surcharge_rate", "withholding_rate"}
    assert all(extra <= set(record) for record in invoices)
    assert not extra & set(gen.INVOICE_COLUMNS)
    withheld = [(r["withholding_amount"], r["withholding_rate"]) for r in invoices]
    assert [pair for pair in withheld if pair[0]] == [("150.00", "15")]
    assert all(rate == "" for amount, rate in withheld if not amount)
    surcharged = [(r["surcharge_amount"], r["surcharge_rate"]) for r in invoices]
    assert [pair for pair in surcharged if pair[0]] == [("5.20", "5.2")]


# --- determinism --------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "builder",
    [
        "build_zombie_demo_n43",
        "build_phantom_payments_n43",
        "build_phantom_facturae",
        "build_zombie_demo_real",
        "build_phantom_demo_real",
    ],
)
def test_builders_are_deterministic_for_a_seed_and_differ_for_another(builder):
    build = getattr(gen, builder)
    assert build(SEED) == build(SEED)
    assert build(SEED) != build(SEED + 1)


def test_the_seed_free_parts_do_not_move_with_the_seed():
    first = gen.build_phantom_facturae(SEED)
    other = gen.build_phantom_facturae(SEED + 1)
    planted = [name for name in FACTURAE_NAMES if int(name[:2]) <= 16]
    assert all(first[name] == other[name] for name in planted)
    assert all(first[name] != other[name] for name in FACTURAE_NAMES if name not in planted)


def test_real_builders_return_the_documented_paths():
    assert list(gen.build_zombie_demo_real(SEED)) == [ZOMBIE_N43]
    phantom = gen.build_phantom_demo_real(SEED)
    assert list(phantom) == ["payments.n43", *[f"facturae/{name}" for name in FACTURAE_NAMES]]


# --- Norma 43: bytes and records ----------------------------------------------------------------
def test_n43_bytes_are_latin_1_with_crlf_and_80_character_records(n43):
    data = n43.data
    assert data.count(b"\r\n") == data.count(b"\n") == data.count(b"\r")
    with pytest.raises(UnicodeDecodeError):
        data.decode("utf-8")  # accents are single Latin-1 bytes, not UTF-8
    assert data.decode("iso-8859-1").encode("iso-8859-1") == data
    lines = _records(data)
    assert {len(line) for line in lines} == {80}
    assert lines[0][:2] == "11" and lines[-2][:2] == "33" and lines[-1][:2] == "88"
    assert {line[:2] for line in lines} == {"11", "22", "23", "33", "88"}


def test_n43_has_one_22_per_row_in_csv_order(n43):
    movements = _movements(_records(n43.data))
    assert len(movements) == len(n43.rows)
    for (line, _), row in zip(movements, n43.rows, strict=True):
        assert _span(line, 11, 16) == _span(line, 17, 22) == _yymmdd(row.day)
        assert _span(line, 28, 28) == ("1" if _is_debit(row) else "2")
        assert _amount(_span(line, 29, 42)) == _magnitude(row)


def test_n43_trailer_counts_and_totals_equal_the_rows(n43):
    lines = _records(n43.data)
    trailer = lines[-2]
    debits = [_magnitude(row) for row in n43.rows if _is_debit(row)]
    credits = [_magnitude(row) for row in n43.rows if not _is_debit(row)]
    assert int(_span(trailer, 21, 25)) == len(debits)
    assert _amount(_span(trailer, 26, 39)) == sum(debits)
    assert int(_span(trailer, 40, 44)) == len(credits)
    assert _amount(_span(trailer, 45, 58)) == sum(credits)
    closing = n43.opening + sum(credits) - sum(debits)
    assert _span(trailer, 59, 59) == "2"  # the closing balance is creditor
    assert _amount(_span(trailer, 60, 73)) == closing
    assert closing > 0
    assert _span(trailer, 3, 20) == _span(lines[0], 3, 20)
    assert _span(trailer, 74, 76) == "978"


def test_n43_header_and_end_record(n43):
    lines = _records(n43.data)
    header = lines[0]
    days = [row.day for row in n43.rows]
    assert _span(header, 3, 6) == "9999"  # the demo bank code
    assert _span(header, 33, 33) == "2"
    assert _amount(_span(header, 34, 47)) == n43.opening
    assert _span(header, 48, 50) == "978"
    assert _span(header, 51, 51) == n43.mode
    assert _span(header, 52, 77).strip() == "TITULAR FICTICIO DEMO"
    assert _span(header, 21, 26) == _yymmdd(min(days))
    assert _span(header, 27, 32) == _yymmdd(max(days))
    end = lines[-1]
    assert _span(end, 3, 20) == "9" * 18
    assert int(_span(end, 21, 26)) == len(lines) - 1


@pytest.mark.parametrize("seed", range(10))
def test_closing_balances_are_creditor_for_any_seed(seed):
    for data in (gen.build_zombie_demo_n43(seed), gen.build_phantom_payments_n43(seed)):
        assert _span(_records(data)[-2], 59, 59) == "2"


def test_n43_files_read_back_to_the_csv_rows(n43):
    transactions, quarantined = parse_norma43(io.BytesIO(n43.data), source_file="f.n43")
    assert quarantined == []
    got = [_transaction_fields(t) for t in transactions]
    expected = [
        (
            row.day,
            _magnitude(row),
            "debit" if _is_debit(row) else "credit",
            row.counterparty,
            row.description,
            row.iban or None,
        )
        for row in n43.rows
    ]
    assert got == expected


def test_zombie_subscription_rows_are_sepa_direct_debits():
    rows = gen.build_zombie_demo_rows(SEED)
    movements = _movements(_records(gen.build_zombie_demo_n43(SEED)))
    creditors: dict[str, str] = {}
    mandates: dict[str, str] = {}
    sepa_rows = 0
    for (line, complements), row in zip(movements, rows, strict=True):
        if row.description != "Monthly subscription":
            assert _span(line, 23, 24) != "03"
            assert [_span(c, 3, 4) for c in complements] == ["01", "02"]
            continue
        sepa_rows += 1
        assert _span(line, 23, 24) == "03"
        assert [_span(c, 3, 4) for c in complements] == ["01", "02", "03"]
        assert _span(complements[0], 5, 8) == "CORE"
        assert _span(complements[0], 9, 78).strip() == row.counterparty
        creditor = _span(complements[1], 5, 39).strip()
        mandate = _span(complements[1], 40, 74).strip()
        assert re.fullmatch(r"ES00ZZZB\d{8}", creditor)
        assert re.fullmatch(r"MND\d{4}", mandate)
        assert _span(complements[2], 13, 80).strip() == "Monthly subscription"
        # one creditor identifier and mandate per counterparty, numbered by first appearance
        assert creditors.setdefault(row.counterparty, creditor) == creditor
        assert mandates.setdefault(row.counterparty, mandate) == mandate
    assert sepa_rows > 50
    assert len(set(creditors.values())) == len(creditors) > 5
    assert list(mandates.values()) == [f"MND{n:04d}" for n in range(1, len(mandates) + 1)]


def test_phantom_payment_ibans_sit_in_a_free_record_23():
    rows = gen.build_phantom_demo_rows(SEED).payments
    movements = _movements(_records(gen.build_phantom_payments_n43(SEED)))
    with_iban = 0
    for (line, complements), row in zip(movements, rows, strict=True):
        texts = [_span(c, 5, 80).strip() for c in complements]
        assert texts[:2] == [row.counterparty, row.description]
        assert _span(line, 23, 24) in {"04", "12"}
        if row.iban:
            with_iban += 1
            assert texts[2] == f"IBAN {row.iban}"
        assert len(texts) == (3 if row.iban else 2)
    assert with_iban > 40


def test_concept_table():
    assert gen.n43_common_concept("Monthly subscription") == "03"
    assert gen.n43_common_concept("Payroll") == "15"
    assert gen.n43_common_concept("Supplier payment") == "04"
    assert gen.n43_common_concept("Receipt") == "04"
    assert gen.n43_common_concept("Transfer sent: shared dinner") == "04"
    assert gen.n43_common_concept("Card purchase") == "12"
    assert gen.n43_common_concept("Groceries") == "99"


# --- Norma 43: writer edge cases ----------------------------------------------------------------
def test_rows_keep_the_order_given():
    rows = [_row(day=date(2026, 5, 1)), _row(day=date(2026, 1, 1)), _row(day=date(2026, 3, 1))]
    movements = _movements(gen.render_norma43_lines(rows))
    assert [_span(line, 11, 16) for line, _ in movements] == ["260501", "260101", "260301"]


def test_a_debtor_closing_balance_is_written_with_sign_1_and_read_back():
    data = gen.render_norma43([_row("-80.00")], opening=Decimal("50.00"))
    trailer = _records(data)[-2]
    assert _span(trailer, 59, 59) == "1"
    assert _amount(_span(trailer, 60, 73)) == Decimal("30.00")
    transactions, quarantined = parse_norma43(io.BytesIO(data), source_file="d.n43")
    assert quarantined == [] and len(transactions) == 1


@pytest.mark.parametrize(
    ("rows", "options"),
    [
        ([], {}),
        ([_row(counterparty="x" * 77)], {}),
        ([_row(description="Ω")], {}),
        ([_row(description="two\nlines")], {}),
        ([_row(counterparty="")], {}),
        ([_row(day=date(1999, 12, 31))], {}),
        ([_row(day=date(2100, 1, 1))], {}),
        ([_row()], {"mode": 4}),
        ([_row()], {"sepa_descriptions": {"Groceries"}}),
        ([_row()], {"opening": Decimal("-1.00")}),
        ([_row("-10000000000000.00")], {}),
    ],
)
def test_writer_refuses_what_cannot_be_written_exactly(rows, options):
    with pytest.raises(ValueError):
        gen.render_norma43(rows, **options)


def test_sepa_creditor_name_and_remittance_are_never_truncated():
    long_name = _row(counterparty="x" * 71)
    with pytest.raises(ValueError):
        gen.render_norma43([long_name], mode=3, sepa_descriptions={"Groceries"})
    with pytest.raises(ValueError):
        too_long = "y" * 69
        gen.render_norma43([_row(description=too_long)], mode=3, sepa_descriptions={too_long})
    fits = "y" * 68
    row = _row(counterparty="x" * 70, description=fits)
    gen.render_norma43([row], mode=3, sepa_descriptions={fits})


# --- Facturae: files ----------------------------------------------------------------------------
def test_there_are_25_facturae_files_named_per_the_requirement(facturae_files):
    assert tuple(facturae_files) == FACTURAE_NAMES
    assert [gen.facturae_file_name(s) for s in gen.PHANTOM_SUPPLIERS] == list(FACTURAE_NAMES)


def test_facturae_bytes_are_utf_8_lf_with_one_declaration(facturae_files):
    for name, data in facturae_files.items():
        text = data.decode("utf-8")
        assert text.startswith('<?xml version="1.0" encoding="UTF-8"?>\n'), name
        assert text.count("<?xml") == 1, name
        assert "\r" not in text and text.endswith("</fe:Facturae>\n"), name
    assert "Gráficas Montealto" in facturae_files["03-p3.xml"].decode("utf-8")


def test_facturae_root_declares_the_322_namespace(facturae_roots):
    ns = "http://www.facturae.gob.es/formato/Versiones/Facturaev3_2_2.xml"
    for name, root in facturae_roots.items():
        assert root.tag == f"{{{ns}}}Facturae", name
        assert _children(root) == ["FileHeader", "Parties", "Invoices"], name
        assert root.find("FileHeader/SchemaVersion").text == "3.2.2", name


def test_modality_batch_count_and_batch_totals(facturae_roots):
    for name, root in facturae_roots.items():
        invoices = _invoice_elements(root)
        batch = root.find("FileHeader/Batch")
        assert _children(root.find("FileHeader")) == FILE_HEADER, name
        assert _children(batch) == BATCH, name
        assert int(batch.find("InvoicesCount").text) == len(invoices), name
        expected = "I" if len(invoices) == 1 else "L"
        assert root.find("FileHeader/Modality").text == expected, name
        total = sum(Decimal(i.find("InvoiceTotals/InvoiceTotal").text) for i in invoices)
        for tag in ("TotalInvoicesAmount", "TotalOutstandingAmount", "TotalExecutableAmount"):
            assert Decimal(batch.find(f"{tag}/TotalAmount").text) == total, (name, tag)
    batches = {n for n, r in facturae_roots.items() if len(_invoice_elements(r)) > 1}
    assert {"01-p1.xml", "02-p2.xml", "17-c1.xml"} <= batches
    assert "06-p6.xml" not in batches and MULTI_RATE_FILE not in batches


def test_parties_have_tax_identification_and_address_in_schema_order(facturae_roots):
    people = set()
    for name, root in facturae_roots.items():
        parties = root.find("Parties")
        assert _children(parties) == ["SellerParty", "BuyerParty"], name
        for party in parties:
            assert _children(party)[0] == "TaxIdentification", name
            assert _children(party.find("TaxIdentification")) == TAX_IDENTIFICATION, name
            identity = party[1]
            if identity.tag == "Individual":
                assert _children(identity) == INDIVIDUAL, name
                if party.tag == "SellerParty":
                    people.add(name)
            else:
                assert identity.tag == "LegalEntity", name
                assert _children(identity) == LEGAL_ENTITY, name
            address = identity.find("AddressInSpain")
            assert _children(address) == ADDRESS, name
            assert address.find("CountryCode").text == "ESP", name
            assert re.fullmatch(r"\d{5}", address.find("PostCode").text), name
    assert people == PERSON_FILES


def test_invoice_children_follow_the_schema_order(facturae_roots):
    mandatory = ("InvoiceHeader", "InvoiceIssueData", "TaxesOutputs", "InvoiceTotals", "Items")
    for name, root in facturae_roots.items():
        for invoice in _invoice_elements(root):
            tags = _children(invoice)
            assert tags == [t for t in INVOICE_ORDER if t in tags], name
            assert all(tag in tags for tag in mandatory), name
            assert _children(invoice.find("InvoiceHeader")) == INVOICE_HEADER, name
            assert _children(invoice.find("InvoiceIssueData")) == ISSUE_DATA, name
            assert _children(invoice.find("InvoiceTotals")) == INVOICE_TOTALS, name


def test_every_invoice_line_is_complete_and_matches_a_tax_entry(facturae_roots):
    for name, root in facturae_roots.items():
        for invoice in _invoice_elements(root):
            taxes = list(invoice.find("TaxesOutputs"))
            lines = list(invoice.find("Items"))
            assert len(lines) == len(taxes) >= 1, name
            for line, tax in zip(lines, taxes, strict=True):
                assert line.tag == "InvoiceLine"
                assert _children(line) == INVOICE_LINE, name
                base = tax.find("TaxableBase/TotalAmount").text
                for tag in ("UnitPriceWithoutTax", "TotalCost", "GrossAmount"):
                    assert line.find(tag).text == base, name
                line_tax = line.find("TaxesOutputs/Tax")
                assert line_tax.find("TaxRate").text == tax.find("TaxRate").text, name
                assert line_tax.find("TaxableBase/TotalAmount").text == base, name


def test_tax_entries_are_in_schema_order(facturae_roots):
    for name, root in facturae_roots.items():
        expected = SURCHARGE_TAX if name == SURCHARGE_FILE else TAX
        for invoice in _invoice_elements(root):
            assert all(_children(tax) == expected for tax in invoice.find("TaxesOutputs")), name
            withheld = invoice.find("TaxesWithheld")
            if withheld is not None:
                assert all(_children(tax) == TAX for tax in withheld), name


def test_installments_carry_due_date_amount_means_and_account(facturae_roots):
    seen = 0
    for name, root in facturae_roots.items():
        for invoice in _invoice_elements(root):
            payment = invoice.find("PaymentDetails")
            if payment is None:
                continue
            seen += 1
            assert _children(payment) == ["Installment"], name
            installment = payment[0]
            tags = _children(installment)
            assert tags[:3] == INSTALLMENT, name
            assert tags[3:] in ([], ["AccountToBeCredited"]), name
            assert installment.find("PaymentMeans").text == "04", name
            total = invoice.find("InvoiceTotals/InvoiceTotal").text
            assert installment.find("InstallmentAmount").text == total, name
    assert seen > 40


def test_values_use_the_schema_formats(facturae_roots):
    for name, root in facturae_roots.items():
        for element in root.iter():
            if len(element):
                continue
            text = (element.text or "").strip()
            if element.tag in TWO_DECIMAL_TAGS:
                assert TWO_DECIMALS.fullmatch(text), (name, element.tag, text)
            if element.tag in {"IssueDate", "InstallmentDueDate"}:
                assert ISO_DATE.fullmatch(text), (name, element.tag, text)
                date.fromisoformat(text)


def test_only_the_p8_file_has_withholding(facturae_roots):
    with_withholding = {
        name
        for name, root in facturae_roots.items()
        if any(i.find("TaxesWithheld") is not None for i in _invoice_elements(root))
    }
    assert with_withholding == {WITHHOLDING_FILE}
    invoice = _invoice_elements(facturae_roots[WITHHOLDING_FILE])[0]
    tax = invoice.find("TaxesWithheld/Tax")
    assert tax.find("TaxTypeCode").text == "04"
    assert tax.find("TaxRate").text == "15.00"
    assert tax.find("TaxAmount/TotalAmount").text == "150.00"
    assert invoice.find("InvoiceTotals/TotalTaxesWithheld").text == "150.00"
    for name, root in facturae_roots.items():
        if name != WITHHOLDING_FILE:
            for other in _invoice_elements(root):
                assert other.find("InvoiceTotals/TotalTaxesWithheld").text == "0.00", name


def test_only_the_multi_rate_file_has_two_tax_entries(facturae_roots):
    counts = {
        name: [len(list(i.find("TaxesOutputs"))) for i in _invoice_elements(root)]
        for name, root in facturae_roots.items()
    }
    assert {name for name, c in counts.items() if 2 in c} == {MULTI_RATE_FILE}
    assert counts[MULTI_RATE_FILE] == [2]
    assert all(max(c) <= 2 for c in counts.values())
    invoice = _invoice_elements(facturae_roots[MULTI_RATE_FILE])[0]
    rates = [tax.find("TaxRate").text for tax in invoice.find("TaxesOutputs")]
    assert rates == ["21.00", "10.00"]


def test_only_the_p11_file_has_a_surcharge(facturae_roots):
    with_surcharge = {
        name
        for name, root in facturae_roots.items()
        if root.find(".//EquivalenceSurcharge") is not None
    }
    assert with_surcharge == {SURCHARGE_FILE}
    tax = facturae_roots[SURCHARGE_FILE].find(".//Invoice/TaxesOutputs/Tax")
    assert tax.find("EquivalenceSurcharge").text == "5.20"
    assert tax.find("EquivalenceSurchargeAmount/TotalAmount").text == "5.20"


def test_the_duplicate_invoice_stays_two_invoices(facturae_roots):
    invoices = _invoice_elements(facturae_roots["01-p1.xml"])
    numbers = [i.find("InvoiceHeader/InvoiceNumber").text for i in invoices]
    assert numbers == ["F-2026-0310", "F-2026-0310"]


def test_facturae_files_read_back_to_the_csv_invoices(facturae_files):
    csv_bytes = gen.build_phantom_demo(SEED)["invoices.csv"].encode("utf-8")
    parsed, csv_quarantine = parse_invoice(io.BytesIO(csv_bytes), fmt="csv", source_file="i.csv")
    assert csv_quarantine == []
    multi_tax_id = gen.PHANTOM_CASES["MULTI_RATE"]
    expected = [invoice for invoice in parsed if invoice.supplier_tax_id != multi_tax_id]

    got = []
    quarantined = []
    for name, data in facturae_files.items():
        invoices, bad = parse_facturae(io.BytesIO(data), source_file=name)
        got.extend(invoices)
        quarantined.extend(bad)
    reasons = [(r["source_file"], r["source_row"], r["reason"]) for r in quarantined]
    assert reasons == [(MULTI_RATE_FILE, 1, "multiple_vat_rates")]
    assert len(got) == len(expected) == 68

    fields = (
        "invoice_number",
        "supplier_name",
        "supplier_tax_id",
        "issue_date",
        "due_date",
        "due_date_is_default",
        "base_amount",
        "vat_rate",
        "vat_amount",
        "surcharge_amount",
        "withholding_amount",
        "total",
        "currency",
    )
    for read, wanted in zip(got, expected, strict=True):
        assert [getattr(read, f) for f in fields] == [getattr(wanted, f) for f in fields]
        # DN-RF-20: the schema cannot express an IBAN without an installment due date
        assert read.iban == (None if wanted.due_date_is_default else wanted.iban)


# --- Facturae: writer ---------------------------------------------------------------------------
def test_one_invoice_is_modality_i_and_a_batch_is_modality_l():
    one = fromstring(gen.render_facturae(SELLER, [_demo_record()]))
    assert one.find("FileHeader/Modality").text == "I"
    assert one.find("FileHeader/Batch/InvoicesCount").text == "1"
    batch = [_demo_record(), _demo_record(invoice_number="T-002")]
    many = fromstring(gen.render_facturae(SELLER, batch))
    assert many.find("FileHeader/Modality").text == "L"
    assert many.find("FileHeader/Batch/InvoicesCount").text == "2"


def test_batch_totals_are_the_sum_of_the_invoice_totals():
    second = _demo_record(invoice_number="T-002", base_amount="50.00", vat_amount="10.50")
    second["total"] = "60.50"
    third = _demo_record(invoice_number="T-003", base_amount="10.00", vat_amount="2.10")
    third["total"] = "12.10"
    root = fromstring(gen.render_facturae(SELLER, [_demo_record(), second, third]))
    for tag in ("TotalInvoicesAmount", "TotalOutstandingAmount", "TotalExecutableAmount"):
        assert root.find(f"FileHeader/Batch/{tag}/TotalAmount").text == "193.60"


def test_records_of_one_number_and_date_with_different_rates_share_an_invoice():
    first = _demo_record(invoice_number="M-1", base_amount="800.00", vat_amount="168.00")
    first["total"] = "968.00"
    second = _demo_record(invoice_number="M-1", base_amount="200.00", vat_amount="20.00")
    second["vat_rate"] = "10"
    second["total"] = "220.00"
    root = fromstring(gen.render_facturae(SELLER, [first, second]))
    invoices = _invoice_elements(root)
    assert len(invoices) == 1
    invoice = invoices[0]
    assert [t.find("TaxRate").text for t in invoice.find("TaxesOutputs")] == ["21.00", "10.00"]
    assert invoice.find("InvoiceTotals/TotalGrossAmount").text == "1000.00"
    assert invoice.find("InvoiceTotals/TotalTaxOutputs").text == "188.00"
    assert invoice.find("InvoiceTotals/InvoiceTotal").text == "1188.00"
    assert len(list(invoice.find("Items"))) == 2


def test_records_with_the_same_number_date_and_rate_stay_separate_invoices():
    groups = gen.facturae_invoice_groups([_demo_record(), _demo_record()])
    assert [len(group) for group in groups] == [1, 1]


def test_rates_are_written_with_two_decimals():
    surcharge = _demo_record(vat_rate="4", surcharge_amount="0.52", surcharge_rate="0.5")
    root = fromstring(gen.render_facturae(SELLER, [surcharge]))
    tax = root.find("Invoices/Invoice/TaxesOutputs/Tax")
    assert tax.find("TaxRate").text == "4.00"
    assert tax.find("EquivalenceSurcharge").text == "0.50"
    five = fromstring(gen.render_facturae(SELLER, [_demo_record(vat_rate="5.2")]))
    assert five.find("Invoices/Invoice/TaxesOutputs/Tax/TaxRate").text == "5.20"


def test_a_row_without_due_date_has_no_payment_details_and_no_iban():
    record = _demo_record(due_date="", iban="ES88 2100 0418 5602 0005 1332")
    root = fromstring(gen.render_facturae(SELLER, [record]))
    assert root.find("Invoices/Invoice/PaymentDetails") is None
    assert root.find(".//IBAN") is None


def test_the_iban_is_written_as_the_row_holds_it():
    record = _demo_record(iban="es88-2100-0418-5602-0005-1332")
    root = fromstring(gen.render_facturae(SELLER, [record]))
    assert root.find(".//AccountToBeCredited/IBAN").text == "es88-2100-0418-5602-0005-1332"


def test_text_is_xml_escaped_and_a_person_is_split_into_name_and_surname():
    seller = gen.FacturaeParty("Ana García & Hijos", gen.make_nif(5), True)
    root = fromstring(gen.render_facturae(seller, [_demo_record(invoice_number="A&B<1>")]))
    assert root.find("Parties/SellerParty/Individual/Name").text == "Ana"
    assert root.find("Parties/SellerParty/Individual/FirstSurname").text == "García & Hijos"
    assert root.find("Parties/SellerParty/TaxIdentification/PersonTypeCode").text == "F"
    assert root.find("Invoices/Invoice/InvoiceHeader/InvoiceNumber").text == "A&B<1>"
    company = fromstring(gen.render_facturae(SELLER, [_demo_record()]))
    assert company.find("Parties/SellerParty/TaxIdentification/PersonTypeCode").text == "J"


@pytest.mark.parametrize(
    ("party", "records"),
    [
        (SELLER, []),
        (SELLER, [_demo_record(base_amount="100")]),
        (SELLER, [_demo_record(base_amount="-1.00")]),
        (SELLER, [_demo_record(vat_rate="21.123")]),
        (SELLER, [_demo_record(vat_rate="")]),
        (SELLER, [_demo_record(issue_date="06/01/2026")]),
        (SELLER, [_demo_record(due_date="tomorrow")]),
        (SELLER, [_demo_record(currency="euro")]),
        (SELLER, [_demo_record(), _demo_record(invoice_number="T-2", currency="USD")]),
        (SELLER, [_demo_record(surcharge_amount="5.20")]),
        (SELLER, [_demo_record(withholding_amount="15.00")]),
        (gen.FacturaeParty("Mononimo", "00000001R", True), [_demo_record()]),
    ],
)
def test_facturae_writer_refuses_what_the_schema_formats_cannot_hold(party, records):
    with pytest.raises(ValueError):
        gen.render_facturae(party, records)


# --- synthetic data only ------------------------------------------------------------------------
def test_ibans_and_tax_ids_come_from_the_generators_own_functions(n43, facturae_roots):
    demo = gen.build_phantom_demo(SEED)
    csv_ibans = set()
    for text in demo.values():
        csv_ibans.update(_compact(row["iban"]) for row in _csv_rows(text) if row["iban"])
    tax_ids = {row["tax_id"] for row in _csv_rows(demo["suppliers.csv"])}

    n43_ibans = set()
    for line in _records(n43.data):
        text = _span(line, 5, 80).strip() if line.startswith("23") else ""
        if text.startswith("IBAN "):
            n43_ibans.add(_compact(text.removeprefix("IBAN ")))
    assert n43_ibans <= csv_ibans

    xml_ibans = set()
    xml_tax_ids = set()
    for root in facturae_roots.values():
        xml_ibans.update(_compact(e.text) for e in root.iter("IBAN"))
        xml_tax_ids.update(e.text for e in root.iter("TaxIdentificationNumber"))
    assert xml_ibans <= csv_ibans
    assert xml_tax_ids == tax_ids | {gen.FACTURAE_BUYER.tax_id}


def test_the_buyer_is_fictional_with_a_wrong_control_character():
    buyer = gen.FACTURAE_BUYER
    assert "Ficticia" in buyer.name
    assert buyer.tax_id not in {s.tax_id for s in gen.PHANTOM_SUPPLIERS}
    assert not _cif_control_ok(buyer.tax_id)


def test_no_email_phone_or_real_looking_creditor_in_the_real_format_files(n43, facturae_files):
    texts = [n43.data.decode("iso-8859-1")]
    texts += [data.decode("utf-8") for data in facturae_files.values()]
    for text in texts:
        assert "@" not in text
        assert not re.search(r"\+\d", text)
        assert not re.search(r"\b\d{3}[ -]\d{3}[ -]\d{3}\b", text)
    for creditor in re.findall(r"ES\d{2}ZZZ\w+", texts[0]):
        assert creditor.startswith("ES00ZZZ")


# --- the committed files (fail until the generator has been run and its output committed) ------
COMMITTED: dict[str, Path] = {
    ZOMBIE_N43: SAMPLES / ZOMBIE_N43,
    "payments.n43": PHANTOM_DIR / "payments.n43",
    **{f"facturae/{name}": PHANTOM_DIR / "facturae" / name for name in FACTURAE_NAMES},
}


@functools.cache
def _expected_bytes() -> dict[str, bytes]:
    """The generator output for seed 42 by relative name (zombie and phantom together)."""
    expected = dict(gen.build_zombie_demo_real(SEED))
    expected.update(gen.build_phantom_demo_real(SEED))
    return expected


@pytest.mark.parametrize("name", list(COMMITTED))
def test_committed_real_format_files_equal_the_generator_output_byte_for_byte(name):
    """Fails until the generator has been run with --seed 42 for both demo modes."""
    path = COMMITTED[name]
    assert path.is_file(), f"{path} is missing; run the generator and commit its output"
    assert path.read_bytes() == _expected_bytes()[name], f"{name} is stale; rerun the generator"


def test_the_committed_facturae_folder_holds_exactly_the_generated_files():
    folder = PHANTOM_DIR / "facturae"
    assert folder.is_dir(), f"{folder} is missing; run the generator and commit its output"
    assert sorted(p.name for p in folder.iterdir()) == sorted(FACTURAE_NAMES)


def test_regenerating_into_a_temporary_folder_is_byte_identical(tmp_path):
    expected = _expected_bytes()
    for target in (tmp_path / "a", tmp_path / "b"):
        base = ["--seed", str(SEED), "--out-dir", str(target)]
        assert gen.main(["--mode", "zombie-demo", *base]) == 0
        assert gen.main(["--mode", "phantom-demo", *base]) == 0
        written = {ZOMBIE_N43: target / ZOMBIE_N43}
        for name in expected:
            if name != ZOMBIE_N43:
                written[name] = target / "phantom_demo" / name
        for name, path in written.items():
            assert path.read_bytes() == expected[name], name
