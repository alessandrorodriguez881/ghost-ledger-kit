"""Tests for the phantom-invoices demo generator (Tasks P18 and P19, design section 15).

The generator lives in scripts/generate_samples.py and is loaded by path (scripts/ is not a
package). The planted cases are checked against design sections 15.4 and 15.5 literally.
"""

import ast
import csv
import io
import re
from datetime import date, timedelta
from decimal import Decimal

import pytest

from apps.phantom_invoices.tests.pi_builders import SCRIPT, generator, iban_for_supplier
from apps.phantom_invoices.tests.pi_checkers import (
    mod97_remainder,
    spanish_national_dc_ok,
    tax_id_control_ok,
)
from ledger_kit.utils.money import net_total, percent_of

SEED = 42
UTF8_BOM = b"\xef\xbb\xbf"
TERM_DAYS = 30  # payment term of an invoice with a due date, and the default for the others
GRACE_DAYS = 15  # unpaid invoices count as overdue only after due date + this many days
PAYMENT_WINDOW_DAYS = 60  # a payment up to due date + 60 days still matches its invoice
LATEST_DATE = date(2026, 10, 30)
LAST_CREDIT_DATE = date(2026, 10, 28)

SUPPLIER_HEADER = ["supplier_name", "tax_id", "iban"]
INVOICE_HEADER = [
    "invoice_number",
    "supplier_name",
    "supplier_tax_id",
    "issue_date",
    "due_date",
    "base_amount",
    "vat_rate",
    "vat_amount",
    "surcharge_amount",
    "withholding_amount",
    "total",
    "currency",
    "iban",
]
PAYMENT_HEADER = ["date", "amount", "currency", "counterparty", "description", "iban"]
HEADERS = {
    "suppliers.csv": SUPPLIER_HEADER,
    "invoices.csv": INVOICE_HEADER,
    "payments.csv": PAYMENT_HEADER,
}
AMOUNT_COLUMNS = (
    "base_amount",
    "vat_amount",
    "surcharge_amount",
    "withholding_amount",
    "total",
)

# Position k (1-based) of every planted case in the supplier plan (design section 15.3).
CASE_K = {
    "P1": 1,
    "P2": 2,
    "P3": 3,
    "P4": 4,
    "P5": 5,
    "P6": 6,
    "P7": 7,
    "P8": 8,
    "P9": 9,
    "P10": 10,
    "P11": 11,
    "P12": 12,
    "NON_MASTER_PAYMENT": 13,
    "OVERDUE": 14,
    "OPEN_NOT_DUE": 15,
    "MULTI_RATE": 16,
}
PERSON_POSITIONS = {8, 9, 12, 19, 23}

# (number, issue, due, base, rate, vat, total) of the planted invoices.
INVOICE_KEYS = (
    "invoice_number",
    "issue_date",
    "due_date",
    "base_amount",
    "vat_rate",
    "vat_amount",
    "total",
)
P1_ROW = ("F-2026-0310", "2026-10-06", "2026-11-05", "400.00", "21", "84.00", "484.00")
P2_ROWS = [
    ("ALQ-2026-01", "2026-08-03", "2026-09-02", "600.00", "21", "126.00", "726.00"),
    ("ALQ-2026-02", "2026-09-02", "2026-10-02", "600.00", "21", "126.00", "726.00"),
    ("ALQ-2026-03", "2026-10-02", "2026-11-01", "600.00", "21", "126.00", "726.00"),
]
P3_ROWS = [
    ("F-2026-0042", "2026-10-01", "2026-10-31", "200.00", "21", "42.00", "242.00"),
    ("F2026-042", "2026-10-04", "2026-11-03", "200.00", "21", "42.00", "242.00"),
]
P4_ROW = ("L-2026-118", "2026-07-06", "2026-08-05", "150.00", "21", "31.50", "181.50")
P5_ROW = ("T-2026-077", "2026-10-09", "2026-11-08", "300.00", "21", "63.00", "363.00")
P6_ROW = ("MO-2026-031", "2026-06-10", "2026-07-10", "100.00", "21", "21.00", "121.00")
P7_ROW = ("IR-2026-044", "2026-10-13", "2026-11-12", "100.00", "21", "12.10", "112.10")
P8_ROW = ("AG-2026-007", "2026-07-01", "2026-07-31", "1000.00", "21", "210.00", "1060.00")
P9_ROW = ("R-2026-009", "2026-07-14", "2026-08-13", "500.00", "21", "105.00", "605.00")
P10_ROWS = [
    ("FAC-0101", "2026-09-18", "2026-10-18", "75.00", "21", "15.75", "90.75"),
    ("FAC-0102", "2026-09-24", "2026-10-24", "75.00", "21", "15.75", "90.75"),
    ("FAC-0103", "2026-10-01", "2026-10-31", "75.00", "21", "15.75", "90.75"),
    ("FAC-0104", "2026-10-09", "2026-11-08", "75.00", "21", "15.75", "90.75"),
]
P11_ROW = ("CM-2026-052", "2026-08-12", "2026-09-11", "100.00", "21", "21.00", "126.20")
P12_ROWS = [
    ("TR-2026-014", "2026-10-07", "2026-11-06", "50.00", "21", "10.50", "60.50"),
    ("TR-2026-015", "2026-10-14", "2026-11-13", "100.00", "21", "21.00", "121.00"),
]
NON_MASTER_ROW = ("MD-2026-210", "2026-08-18", "2026-09-17", "1000.00", "21", "210.00", "1210.00")
OVERDUE_ROW = ("CR-2026-051", "2026-08-20", "2026-09-19", "700.00", "21", "147.00", "847.00")
OPEN_ROW = ("CS-2026-033", "2026-10-12", "2026-11-11", "250.00", "21", "52.50", "302.50")
MULTI_ROWS = [
    ("OB-2026-008", "2026-09-30", "2026-10-30", "800.00", "21", "168.00", "968.00"),
    ("OB-2026-008", "2026-09-30", "2026-10-30", "200.00", "10", "20.00", "220.00"),
]


# --- helpers ------------------------------------------------------------------------------------
def _parse(text: str) -> list[dict[str, str]]:
    """Parse CSV text into one dict per data row."""
    return list(csv.DictReader(io.StringIO(text, newline="")))


def _compact(iban: str) -> str:
    """Remove spaces and hyphens and upper-case an IBAN cell."""
    return re.sub(r"[\s-]", "", iban).upper()


def _spaced(k: int, *, other: bool = False) -> str:
    """The IBAN of supplier k (independent implementation) in groups of four."""
    compact = iban_for_supplier(k, other=other)
    return " ".join(compact[i : i + 4] for i in range(0, len(compact), 4))


def _tax(case: str) -> str:
    """The tax id the generator assigns to a planted case."""
    return generator.PHANTOM_CASES[case]


def _name(suppliers: list[dict[str, str]], case: str) -> str:
    """The supplier name of a planted case, read from suppliers.csv."""
    return next(s["supplier_name"] for s in suppliers if s["tax_id"] == _tax(case))


def _case_invoices(invoices: list[dict[str, str]], case: str) -> list[dict[str, str]]:
    """The invoice rows of one planted case, in file order."""
    return [row for row in invoices if row["supplier_tax_id"] == _tax(case)]


def _case_payments(
    suppliers: list[dict[str, str]], payments: list[dict[str, str]], case: str
) -> list[tuple[str, str, str]]:
    """(date, amount, iban) of the payments to the supplier of a planted case."""
    name = _name(suppliers, case)
    return [(p["date"], p["amount"], p["iban"]) for p in payments if p["counterparty"] == name]


def _tuples(rows: list[dict[str, str]]) -> list[tuple[str, ...]]:
    """The INVOICE_KEYS cells of each row."""
    return [tuple(row[key] for key in INVOICE_KEYS) for row in rows]


def _check_invoices(
    rows: list[dict[str, str]],
    expected: list[tuple[str, ...]],
    *,
    iban: str | list[str],
    surcharge: str = "",
    withholding: str = "",
) -> None:
    """Assert numbers, dates, amounts, surcharge, withholding, currency and IBAN spelling."""
    assert _tuples(rows) == expected
    ibans = iban if isinstance(iban, list) else [iban] * len(rows)
    assert [row["iban"] for row in rows] == ibans
    for row in rows:
        assert row["surcharge_amount"] == surcharge
        assert row["withholding_amount"] == withholding
        assert row["currency"] == "EUR"


@pytest.fixture(scope="module")
def demo() -> dict[str, str]:
    """The demo files for the default seed."""
    return generator.build_phantom_demo(SEED)


@pytest.fixture(scope="module")
def suppliers(demo: dict[str, str]) -> list[dict[str, str]]:
    """Parsed suppliers.csv."""
    return _parse(demo["suppliers.csv"])


@pytest.fixture(scope="module")
def invoices(demo: dict[str, str]) -> list[dict[str, str]]:
    """Parsed invoices.csv."""
    return _parse(demo["invoices.csv"])


@pytest.fixture(scope="module")
def payments(demo: dict[str, str]) -> list[dict[str, str]]:
    """Parsed payments.csv."""
    return _parse(demo["payments.csv"])


def _clean_rows(invoices: list[dict[str, str]], tax_id: str) -> list[dict[str, str]]:
    """The invoice rows of one clean supplier, in file order."""
    return [row for row in invoices if row["supplier_tax_id"] == tax_id]


# --- P18: determinism, formats, identifiers, clean suppliers, payments ---------------------------
def test_build_phantom_demo_is_deterministic():
    first = generator.build_phantom_demo(SEED)
    assert first == generator.build_phantom_demo(SEED)
    other = generator.build_phantom_demo(SEED + 1)
    assert other["suppliers.csv"] == first["suppliers.csv"]  # identifiers are seed-independent
    assert other["invoices.csv"] != first["invoices.csv"]
    assert other["payments.csv"] != first["payments.csv"]

    clean_tax = set(generator.CLEAN_SUPPLIERS)
    clean_names = {
        s["supplier_name"] for s in _parse(first["suppliers.csv"]) if s["tax_id"] in clean_tax
    }

    def planted(texts: dict[str, str]) -> tuple[list, list]:
        rows = [r for r in _parse(texts["invoices.csv"]) if r["supplier_tax_id"] not in clean_tax]
        pays = [r for r in _parse(texts["payments.csv"]) if r["counterparty"] not in clean_names]
        return rows, pays

    assert planted(other) == planted(first)


def test_files_are_plain_dialect_with_documented_columns(demo):
    assert set(demo) == set(HEADERS)
    for name, text in demo.items():
        assert not text.startswith("\ufeff")
        assert text.encode("utf-8")[:3] != UTF8_BOM
        assert "\r" not in text
        assert text.endswith("\n")
        assert text.splitlines()[0] == ",".join(HEADERS[name])
        table = list(csv.reader(io.StringIO(text, newline="")))
        assert table[0] == HEADERS[name]
        assert all(len(row) == len(HEADERS[name]) for row in table)


def test_amounts_use_dot_decimal_and_dates_are_iso(demo, suppliers, invoices, payments):
    amount = re.compile(r"-?\d+\.\d{2}")
    rate = re.compile(r"\d+(\.\d+)?")
    for row in invoices:
        for column in AMOUNT_COLUMNS:
            assert row[column] == "" or amount.fullmatch(row[column]), (row, column)
        assert rate.fullmatch(row["vat_rate"])
        date.fromisoformat(row["issue_date"])
        assert row["due_date"] == "" or date.fromisoformat(row["due_date"])
    for row in payments:
        assert amount.fullmatch(row["amount"])
        assert row["currency"] == "EUR"
        date.fromisoformat(row["date"])
    for row in suppliers:
        assert row["iban"] == "" or re.fullmatch(r"ES\d{2}( \d{4}){5}", row["iban"])
    assert ";" not in demo["invoices.csv"] + demo["payments.csv"] + demo["suppliers.csv"]


def test_twenty_five_suppliers_sixteen_cases_nine_clean(suppliers):
    assert set(generator.PHANTOM_CASES) == set(CASE_K)
    assert len(generator.PHANTOM_CASES) == 16
    assert len(generator.CLEAN_SUPPLIERS) == 9
    assert len(set(generator.CLEAN_SUPPLIERS)) == 9
    assert not set(generator.CLEAN_SUPPLIERS) & set(generator.PHANTOM_CASES.values())
    assert 20 <= len(suppliers) <= 26


def test_every_iban_valid_mod97_with_wrong_national_digits(demo):
    seen = 0
    for name, text in demo.items():
        for row in _parse(text):
            cell = row["iban"]
            if cell == "":
                continue
            compact = _compact(cell)
            assert compact.startswith("ES") and len(compact) == 24, (name, cell)
            assert mod97_remainder(compact) == 1, (name, cell)
            assert not spanish_national_dc_ok(compact), (name, cell)
            seen += 1
    assert seen > 100


def test_every_tax_id_has_wrong_control_character_all_distinct(suppliers, invoices):
    tax_ids = [s["tax_id"] for s in suppliers]
    assert len(tax_ids) == len(set(tax_ids))
    assert "00000000T" not in tax_ids
    for tax_id in tax_ids:
        assert not tax_id_control_ok(tax_id), tax_id
    assert {row["supplier_tax_id"] for row in invoices} <= set(tax_ids)
    persons = {
        k for k, tax_id in enumerate(tax_ids, start=1) if re.fullmatch(r"\d{8}[A-Z]", tax_id)
    }
    assert persons == PERSON_POSITIONS


def test_no_email_or_phone_in_any_file(demo):
    for name, text in demo.items():
        assert "@" not in text, name
        assert "+" not in text, name
        assert not re.search(r"\b\d{3}[ -]\d{3}[ -]\d{3}\b", text), name


def test_clean_suppliers_have_five_monthly_invoices_with_distinct_totals(invoices):
    for j, tax_id in enumerate(generator.CLEAN_SUPPLIERS):
        rows = _clean_rows(invoices, tax_id)
        assert len(rows) == 5
        issues = [date.fromisoformat(row["issue_date"]) for row in rows]
        assert [d.month for d in issues] == [5, 6, 7, 8, 9]
        assert [d.day for d in issues] == [3 + (j * 5 + m * 3) % 20 for m in range(5)]
        numbers = [row["invoice_number"] for row in rows]
        assert [n[2:] for n in numbers] == [f"-2026-{m + 1:03d}" for m in range(5)]
        assert len({n[:2] for n in numbers}) == 1
        totals = [row["total"] for row in rows]
        assert len(set(totals)) == 5


def test_clean_invoice_amounts_built_with_money_helpers(invoices):
    clean = set(generator.CLEAN_SUPPLIERS)
    rows = [row for row in invoices if row["supplier_tax_id"] in clean]
    assert len(rows) == 45
    for row in rows:
        base = Decimal(row["base_amount"])
        assert 80 <= base < 1800
        assert row["vat_rate"] in {"21", "10", "4", "0"}
        vat = percent_of(base, Decimal(row["vat_rate"]))
        assert row["vat_amount"] == str(vat)
        assert row["total"] == str(net_total([base, vat]))
        assert row["surcharge_amount"] == "" and row["withholding_amount"] == ""


def test_clean_invoice_iban_cell_cycles_empty_master_compact_lower(suppliers, invoices):
    master = {s["tax_id"]: s["iban"] for s in suppliers}
    for j, tax_id in enumerate(generator.CLEAN_SUPPLIERS):
        for m, row in enumerate(_clean_rows(invoices, tax_id)):
            styles = ["", master[tax_id], _compact(master[tax_id]).lower()]
            assert row["iban"] == styles[(j + m) % 3]


def test_every_clean_invoice_paid_by_exact_total_inside_window_to_master_iban(
    suppliers, invoices, payments
):
    master = {s["tax_id"]: _compact(s["iban"]) for s in suppliers}
    names = {s["tax_id"]: s["supplier_name"] for s in suppliers}
    for tax_id in generator.CLEAN_SUPPLIERS:
        for row in _clean_rows(invoices, tax_id):
            matches = [
                p
                for p in payments
                if p["counterparty"] == names[tax_id] and p["amount"] == f"-{row['total']}"
            ]
            assert len(matches) == 1, row["invoice_number"]
            issue = date.fromisoformat(row["issue_date"])
            due = date.fromisoformat(row["due_date"]) if row["due_date"] else None
            due = due or issue + timedelta(days=TERM_DAYS)
            paid = date.fromisoformat(matches[0]["date"])
            assert issue <= paid <= due + timedelta(days=PAYMENT_WINDOW_DAYS)
            assert _compact(matches[0]["iban"]) == master[tax_id]


def test_latest_date_in_data_is_demo_latest_date(suppliers, invoices, payments):
    assert generator.DEMO_LATEST_DATE == LATEST_DATE
    days = [date.fromisoformat(row["issue_date"]) for row in invoices]
    days += [date.fromisoformat(row["date"]) for row in payments]
    assert max(days) == LATEST_DATE
    last_tax_id = generator.CLEAN_SUPPLIERS[-1]
    last_name = next(s["supplier_name"] for s in suppliers if s["tax_id"] == last_tax_id)
    last_invoice = _clean_rows(invoices, last_tax_id)[-1]
    on_latest = [p for p in payments if p["date"] == LATEST_DATE.isoformat()]
    assert len(on_latest) == 1
    assert on_latest[0]["counterparty"] == last_name
    assert on_latest[0]["amount"] == f"-{last_invoice['total']}"


def test_payments_sorted_by_date_counterparty_amount(payments):
    keys = [(p["date"], p["counterparty"], Decimal(p["amount"])) for p in payments]
    assert keys == sorted(keys)


def test_payments_have_three_credits_and_four_unrelated_debits(suppliers, payments):
    names = {s["supplier_name"] for s in suppliers}
    master_ibans = {_compact(s["iban"]) for s in suppliers}
    credits = [p for p in payments if Decimal(p["amount"]) > 0]
    assert len(credits) == 3
    assert all(date.fromisoformat(p["date"]) <= LAST_CREDIT_DATE for p in credits)
    unrelated = [p for p in payments if p["counterparty"] not in names and p not in credits]
    assert len(unrelated) == 4
    for payment in unrelated:
        assert Decimal(payment["amount"]) < 0
        assert payment["iban"] != "" and _compact(payment["iban"]) not in master_ibans


def test_generator_uses_only_random_random_with_seed():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    clock_names = {"now", "today", "utcnow"}
    seeded = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        assert node.func.attr not in clock_names, ast.dump(node)
        owner = node.func.value
        if isinstance(owner, ast.Name) and owner.id == "random":
            assert node.func.attr == "Random", ast.dump(node)
            assert len(node.args) == 1, ast.dump(node)
            seeded += 1
    assert seeded >= 1
    for statement in tree.body:
        if isinstance(statement, ast.FunctionDef | ast.ClassDef):
            continue
        for node in ast.walk(statement):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                owner = node.func.value
                assert not (isinstance(owner, ast.Name) and owner.id == "random")


# --- P19: sizes and the planted cases ------------------------------------------------------------
def test_demo_sizes(suppliers, invoices, payments):
    planted_tax = set(generator.PHANTOM_CASES.values())
    assert len(invoices) == 70
    assert sum(row["supplier_tax_id"] in planted_tax for row in invoices) == 25
    assert len(suppliers) == 25
    assert len(payments) == 62


def test_each_phantom_case_has_a_dedicated_supplier_tax_id(suppliers):
    cases = generator.PHANTOM_CASES
    assert len(set(cases.values())) == 16
    assert set(cases.values()) <= {s["tax_id"] for s in suppliers}
    for case, k in CASE_K.items():
        assert suppliers[k - 1]["tax_id"] == cases[case], case
    assert [s["tax_id"] for s in suppliers[16:]] == list(generator.CLEAN_SUPPLIERS)


def test_planted_p1(suppliers, invoices, payments):
    rows = _case_invoices(invoices, "P1")
    _check_invoices(rows, [P1_ROW, P1_ROW], iban=_spaced(1))
    assert rows[0] == rows[1]
    assert _case_payments(suppliers, payments, "P1") == []


def test_planted_p2(suppliers, invoices, payments):
    rows = _case_invoices(invoices, "P2")
    _check_invoices(rows, P2_ROWS, iban=_spaced(2))
    expected = [
        ("2026-08-05", "-726.00", _spaced(2)),
        ("2026-09-04", "-726.00", _spaced(2)),
        ("2026-10-05", "-726.00", _spaced(2)),
    ]
    assert _case_payments(suppliers, payments, "P2") == expected


def test_planted_p3(suppliers, invoices, payments):
    rows = _case_invoices(invoices, "P3")
    _check_invoices(rows, P3_ROWS, iban=_spaced(3))
    assert _case_payments(suppliers, payments, "P3") == []


def test_planted_p4(suppliers, invoices, payments):
    rows = _case_invoices(invoices, "P4")
    _check_invoices(rows, [P4_ROW], iban=_spaced(4).lower())
    assert _case_payments(suppliers, payments, "P4") == [("2026-08-04", "-181.50", _spaced(4))]


def test_planted_p5(suppliers, invoices, payments):
    rows = _case_invoices(invoices, "P5")
    _check_invoices(rows, [P5_ROW], iban=_spaced(5, other=True))
    assert _spaced(5, other=True) != _spaced(5)
    assert _case_payments(suppliers, payments, "P5") == []


def test_planted_p6(suppliers, invoices, payments):
    rows = _case_invoices(invoices, "P6")
    _check_invoices(rows, [P6_ROW], iban=_spaced(6))
    assert _case_payments(suppliers, payments, "P6") == [("2026-07-08", "-121.00", _spaced(6))]


def test_planted_p7(suppliers, invoices, payments):
    rows = _case_invoices(invoices, "P7")
    _check_invoices(rows, [P7_ROW], iban=_spaced(7))
    assert Decimal(rows[0]["vat_amount"]) != percent_of(Decimal("100.00"), Decimal("21"))
    assert _case_payments(suppliers, payments, "P7") == []


def test_planted_p8(suppliers, invoices, payments):
    rows = _case_invoices(invoices, "P8")
    _check_invoices(rows, [P8_ROW], iban=_spaced(8), withholding="150.00")
    assert _case_payments(suppliers, payments, "P8") == [("2026-07-30", "-1060.00", _spaced(8))]


def test_planted_p9(suppliers, invoices, payments):
    rows = _case_invoices(invoices, "P9")
    _check_invoices(rows, [P9_ROW], iban=_spaced(9))
    expected = [("2026-08-10", "-605.00", _spaced(9)), ("2026-08-12", "-605.00", _spaced(9))]
    assert _case_payments(suppliers, payments, "P9") == expected


def test_planted_p10(suppliers, invoices, payments):
    rows = _case_invoices(invoices, "P10")
    _check_invoices(rows, P10_ROWS, iban=_spaced(10))
    issues = [date.fromisoformat(row["issue_date"]) for row in rows]
    assert [(b - a).days for a, b in zip(issues, issues[1:], strict=False)] == [6, 7, 8]
    assert _case_payments(suppliers, payments, "P10") == []


def test_planted_p11(suppliers, invoices, payments):
    rows = _case_invoices(invoices, "P11")
    _check_invoices(rows, [P11_ROW], iban=_spaced(11), surcharge="5.20")
    assert _case_payments(suppliers, payments, "P11") == [("2026-09-09", "-126.20", _spaced(11))]


def test_planted_p12(suppliers, invoices, payments):
    rows = _case_invoices(invoices, "P12")
    hyphenated = _spaced(12).replace(" ", "-")
    _check_invoices(rows, P12_ROWS, iban=[hyphenated, ""])
    assert _case_payments(suppliers, payments, "P12") == []


def test_planted_non_master_payment(suppliers, invoices, payments):
    rows = _case_invoices(invoices, "NON_MASTER_PAYMENT")
    _check_invoices(rows, [NON_MASTER_ROW], iban=_spaced(13))
    expected = [("2026-09-14", "-1210.00", _spaced(13, other=True))]
    assert _case_payments(suppliers, payments, "NON_MASTER_PAYMENT") == expected


def test_planted_overdue(suppliers, invoices, payments):
    rows = _case_invoices(invoices, "OVERDUE")
    _check_invoices(rows, [OVERDUE_ROW], iban=_spaced(14))
    assert _case_payments(suppliers, payments, "OVERDUE") == []
    due = date.fromisoformat(OVERDUE_ROW[2])
    assert (LATEST_DATE - due).days == 41
    assert LATEST_DATE > due + timedelta(days=GRACE_DAYS)


def test_planted_open_not_due(suppliers, invoices, payments):
    rows = _case_invoices(invoices, "OPEN_NOT_DUE")
    _check_invoices(rows, [OPEN_ROW], iban=_spaced(15))
    assert _case_payments(suppliers, payments, "OPEN_NOT_DUE") == []
    assert date.fromisoformat(OPEN_ROW[2]) > LATEST_DATE


def test_planted_multi_rate(suppliers, invoices, payments):
    rows = _case_invoices(invoices, "MULTI_RATE")
    _check_invoices(rows, MULTI_ROWS, iban=_spaced(16))
    assert _case_payments(suppliers, payments, "MULTI_RATE") == []
    assert {row["invoice_number"] for row in rows} == {"OB-2026-008"}
    assert {row["vat_rate"] for row in rows} == {"21", "10"}


def test_clean_invoices_without_due_date(invoices):
    empty = 0
    for j, tax_id in enumerate(generator.CLEAN_SUPPLIERS):
        for m, row in enumerate(_clean_rows(invoices, tax_id)):
            assert (row["due_date"] == "") == ((j + m) % 4 == 0), (j, m)
            if row["due_date"]:
                issue = date.fromisoformat(row["issue_date"])
                assert row["due_date"] == (issue + timedelta(days=TERM_DAYS)).isoformat()
            empty += row["due_date"] == ""
    assert empty == sum((j + m) % 4 == 0 for j in range(9) for m in range(5))


def test_p12_hyphenated_iban_derived_from_supplier_valid_iban(suppliers, invoices):
    row = _case_invoices(invoices, "P12")[0]
    master = next(s["iban"] for s in suppliers if s["tax_id"] == _tax("P12"))
    assert "-" in row["iban"] and " " not in row["iban"]
    assert row["iban"] == master.replace(" ", "-")
    assert _compact(row["iban"]) == iban_for_supplier(12)
    assert mod97_remainder(_compact(row["iban"])) == 1


def test_p4_invoice_iban_lowercase_with_spaces(suppliers, invoices):
    row = _case_invoices(invoices, "P4")[0]
    master = next(s["iban"] for s in suppliers if s["tax_id"] == _tax("P4"))
    assert row["iban"] == row["iban"].lower() != row["iban"].upper()
    assert " " in row["iban"]
    assert row["iban"].upper() == master


def test_no_planted_invoice_besides_the_overdue_one_is_past_its_grace_period(invoices, payments):
    planted_tax = set(generator.PHANTOM_CASES.values())
    paid = {(p["counterparty"], p["amount"]) for p in payments}
    grace = timedelta(days=TERM_DAYS + GRACE_DAYS)
    checked = 0
    for row in invoices:
        tax_id = row["supplier_tax_id"]
        if tax_id not in planted_tax or tax_id == _tax("OVERDUE"):
            continue
        if (row["supplier_name"], f"-{row['total']}") in paid:
            continue
        assert date.fromisoformat(row["issue_date"]) + grace >= LATEST_DATE, row["invoice_number"]
        checked += 1
    assert checked > 0
    overdue = _case_invoices(invoices, "OVERDUE")[0]
    assert date.fromisoformat(overdue["issue_date"]) + grace < LATEST_DATE


def test_two_thirds_of_invoices_are_clean(invoices):
    clean = sum(row["supplier_tax_id"] in set(generator.CLEAN_SUPPLIERS) for row in invoices)
    assert 6 * len(invoices) <= 10 * clean <= 7 * len(invoices)
