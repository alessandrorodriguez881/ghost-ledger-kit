"""Seeded generator of synthetic sample data (Finance Rules 5 and 6).

Modes (``--mode``):

* ``samples`` (default): writes the five committed sample files of ledger-core Task 13 to
  ``data/samples/``. Their content is a fixed table, so it does not depend on the seed and the
  committed files are byte-identical to ``build_core_samples()`` (checked by a test).
* ``bank``: a random bank statement from ``--seed``, ``--rows`` and ``--dialect``; printed to
  stdout or written to ``--output``. Same arguments always give the same text.
* ``zombie-demo``: the demo statement of the zombie-subscriptions app
  (``data/samples/zombie_demo_statement.csv``, ~335 rows over 2026-05-01..2026-10-31). The
  planted subscriptions are fixed tables; ``--seed`` only drives the dates and amounts of the
  one-off shops, so the same seed always gives the same bytes.
* ``phantom-demo``: the demo of the phantom-invoices app
  (``data/samples/phantom_demo/{suppliers,invoices,payments}.csv``): 25 suppliers, 70 invoice
  rows, 62 payment rows. The 16 planted cases are literal tables; ``--seed`` only drives the
  amounts, dates and payment delays of the nine clean suppliers, so the same seed always gives
  the same bytes.

All data is synthetic: fictional names, IBANs with a valid ISO 13616 mod-97 checksum but wrong
Spanish national check digits, tax ids with a wrong control character, no e-mail or phone.
Money is never computed here: amounts are written as strings, VAT and totals come from
``ledger_kit.utils.money``.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import random
import sys
from collections.abc import Callable, Sequence
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import NamedTuple

# `python scripts/generate_samples.py` puts only scripts/ on sys.path: add the repository root.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ledger_kit.utils.money import format_as_european, net_total, percent_of  # noqa: E402

DEFAULT_SEED: int = 42
DEFAULT_OUT_DIR: Path = REPO_ROOT / "data" / "samples"

BANK_COLUMNS: tuple[str, ...] = (
    "date",
    "amount",
    "currency",
    "counterparty",
    "description",
    "iban",
)
INVOICE_COLUMNS: tuple[str, ...] = (
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
)
SUPPLIER_COLUMNS: tuple[str, ...] = ("supplier_name", "tax_id", "iban")

BANK_FILE = "bank_statement_sample.csv"
BANK_FILE_ES = "bank_statement_sample_es.csv"
INVOICE_CSV_FILE = "invoice_sample.csv"
INVOICE_JSON_FILE = "invoice_sample.json"
SUPPLIERS_FILE = "suppliers_sample.csv"
SAMPLE_FILES: tuple[str, ...] = (
    BANK_FILE,
    BANK_FILE_ES,
    INVOICE_CSV_FILE,
    INVOICE_JSON_FILE,
    SUPPLIERS_FILE,
)

# --- IBAN: valid ISO mod-97 checksum, deliberately wrong Spanish national check digits ---------
SPANISH_DC_WEIGHTS = (1, 2, 4, 8, 5, 10, 9, 7, 3, 6)


def _dc_digit(digits: str) -> int:
    """One Spanish national control digit for a 10-digit string."""
    total = sum(int(d) * w for d, w in zip(digits, SPANISH_DC_WEIGHTS, strict=True))
    d = 11 - total % 11
    return {10: 1, 11: 0}.get(d, d)


def correct_national_dc(bank: str, branch: str, account: str) -> str:
    """Correct Spanish control digits; ('2100','0418','0200051332') -> '45'."""
    return f"{_dc_digit('00' + bank + branch)}{_dc_digit(account)}"


def wrong_national_dc(bank: str, branch: str, account: str) -> str:
    """Always different from the correct pair: '45' -> '56'."""
    return f"{(int(correct_national_dc(bank, branch, account)) + 11) % 100:02d}"


def iban_check_digits(country: str, bban: str) -> str:
    """ISO 13616: 98 - (numeric(bban + country + '00') mod 97), two digits."""
    numeric = "".join(str(int(ch, 36)) for ch in bban + country + "00")
    return f"{98 - int(numeric) % 97:02d}"


def make_iban(bank: str, branch: str, account: str) -> str:
    """Compact Spanish IBAN with valid mod-97 and wrong national check digits."""
    bban = bank + branch + wrong_national_dc(bank, branch, account) + account
    return "ES" + iban_check_digits("ES", bban) + bban


def format_iban(compact: str) -> str:
    """Group an IBAN in blocks of four, e.g. 'ES88 2100 0418 5602 0005 1332'."""
    return " ".join(compact[i : i + 4] for i in range(0, len(compact), 4))


# --- tax ids: wrong control character, a different id per supplier ------------------------------
NIF_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"


def cif_control_digit(body: str) -> int:
    """Correct control digit of a type-B CIF body (7 digits)."""
    total = 0
    for pos, ch in enumerate(body, start=1):
        d = int(ch)
        if pos % 2 == 1:
            d *= 2
            d = d // 10 + d % 10
        total += d
    return (10 - total % 10) % 10


def make_cif(k: int) -> str:
    """Fictional type-B CIF number k with an always-wrong control digit."""
    body = f"{k:07d}"
    return f"B{body}{(cif_control_digit(body) + 1) % 10}"


def make_nif(k: int) -> str:
    """Fictional NIF number k (k-th number above 1000 that is no multiple of 23), wrong letter."""
    n = 1000
    remaining = k
    while remaining > 0:  # multiples of 23 are skipped: their correct letter is 'T'
        n += 1
        if n % 23 != 0:
            remaining -= 1
    return f"{n:08d}{NIF_LETTERS[(n % 23 + 1) % 23]}"


# Identifiers of the three sample suppliers. Account numbers follow the phantom-invoices
# scheme (bank/branch pair and account derived from k) so both samples agree on k = 1..3.
IBAN_A = make_iban("2100", "0418", "0200051332")  # the documented example, ES88 ...
IBAN_AURORA = make_iban("2100", "0418", "0007654321")  # k = 1
IBAN_VALDEMAR = make_iban("0049", "1500", "0015308642")  # k = 2


class Supplier(NamedTuple):
    """One fictional supplier of the sample data."""

    name: str
    tax_id: str
    iban: str  # compact, or "" for a supplier without a bank account in the master file


SUPPLIERS: tuple[Supplier, ...] = (
    Supplier("Suministros Ibéricos Aurora S.L.", make_cif(1), IBAN_AURORA),
    Supplier("Inmuebles Valdemar S.L.", make_cif(2), IBAN_VALDEMAR),
    Supplier("Ana García (Asesoría Fiscal)", make_nif(3), ""),
)


# --- csv helpers --------------------------------------------------------------------------------
def _csv_text(header: Sequence[str], rows: Sequence[Sequence[str]], delimiter: str = ",") -> str:
    """Render rows as CSV text with LF line endings (UTF-8 is applied when writing)."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, delimiter=delimiter, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue()


# --- bank statements ----------------------------------------------------------------------------
class BankRow(NamedTuple):
    """One bank-statement row; `amount` is signed text with a dot decimal, "" iban = none."""

    day: date
    amount: str
    counterparty: str
    description: str
    iban: str  # written verbatim (spaced, compact or lower case)


# The committed bank sample: 3 credits and 7 debits, four rows with an IBAN in three spellings.
BANK_SAMPLE_ROWS: tuple[BankRow, ...] = (
    BankRow(date(2026, 1, 2), "2450.00", "Luminar Estudio S.L.", "Payroll January", ""),
    BankRow(
        date(2026, 1, 3),
        "-650.00",
        "Inmuebles Valdemar S.L.",
        "Rent January",
        format_iban(IBAN_VALDEMAR),
    ),
    BankRow(date(2026, 1, 5), "-54.32", "Supermercados Aurora", "Groceries", ""),
    BankRow(date(2026, 1, 9), "-12.99", "Streamly Plus", "Monthly subscription", ""),
    BankRow(date(2026, 1, 12), "120.00", "Ana García", "Transfer received", IBAN_A),
    BankRow(date(2026, 1, 15), "-1234.56", "Taller Mecánico Norte", "Car repair", ""),
    BankRow(
        date(2026, 1, 20),
        "-45.00",
        "Suministros Ibéricos Aurora S.L.",
        "Office supplies",
        format_iban(IBAN_AURORA),
    ),
    BankRow(date(2026, 1, 26), "-29.90", "Luigi Rossi", "Shared dinner", ""),
    BankRow(
        date(2026, 1, 28),
        "15.75",
        "Inmuebles Valdemar S.L.",
        "Rent adjustment refund",
        format_iban(IBAN_VALDEMAR).lower(),
    ),
    BankRow(date(2026, 1, 31), "-12.99", "Streamly Plus", "Monthly subscription", ""),
)


def render_bank_csv(rows: Sequence[BankRow], dialect: str = "plain") -> str:
    """Render bank rows as plain (comma, dot, ISO) or european (semicolon, comma, DD/MM/YYYY)."""
    if dialect not in ("plain", "european"):
        raise ValueError(f"unknown dialect {dialect!r}")
    european = dialect == "european"
    body = [
        [
            r.day.strftime("%d/%m/%Y") if european else r.day.isoformat(),
            format_as_european(Decimal(r.amount)) if european else r.amount,
            "EUR",
            r.counterparty,
            r.description,
            r.iban,
        ]
        for r in rows
    ]
    return _csv_text(BANK_COLUMNS, body, ";" if european else ",")


# Fictional pools for the random `bank` mode.
RANDOM_COUNTERPARTIES: tuple[str, ...] = (
    "Supermercados Aurora",
    "Streamly Plus",
    "Taller Mecánico Norte",
    "Luminar Estudio S.L.",
    "Ana García",
    "Luigi Rossi",
    "Sophie Dupont",
    "Café Estrella",
    "Farmacia Central Sur",
)
RANDOM_DESCRIPTIONS: tuple[str, ...] = (
    "Groceries",
    "Monthly subscription",
    "Car repair",
    "Payroll",
    "Transfer",
    "Refund",
    "Shared dinner",
)
RANDOM_IBANS: tuple[str, ...] = (IBAN_A, IBAN_AURORA, IBAN_VALDEMAR)
RANDOM_START_DATE: date = date(2026, 1, 1)
RANDOM_CREDIT_SHARE: float = 0.25  # probability that a row is a credit
RANDOM_IBAN_SHARE: float = 0.3  # probability that a row carries an IBAN
RANDOM_MAX_CENTS: int = 250_000  # largest amount: 2.500,00


def build_bank_rows(seed: int, rows: int) -> list[BankRow]:
    """Random but reproducible bank rows; randomness only from random.Random(seed)."""
    rng = random.Random(seed)
    day = RANDOM_START_DATE
    result: list[BankRow] = []
    for _ in range(rows):
        day += timedelta(days=rng.randint(0, 3))
        cents = rng.randint(100, RANDOM_MAX_CENTS)
        sign = "" if rng.random() < RANDOM_CREDIT_SHARE else "-"
        amount = f"{sign}{cents // 100}.{cents % 100:02d}"
        counterparty = rng.choice(RANDOM_COUNTERPARTIES)
        description = rng.choice(RANDOM_DESCRIPTIONS)
        iban = format_iban(rng.choice(RANDOM_IBANS)) if rng.random() < RANDOM_IBAN_SHARE else ""
        result.append(BankRow(day, amount, counterparty, description, iban))
    return result


def build_bank_statement(seed: int = DEFAULT_SEED, rows: int = 10, dialect: str = "plain") -> str:
    """Random bank-statement CSV text for `seed`, `rows` and `dialect`."""
    return render_bank_csv(build_bank_rows(seed, rows), dialect)


# --- invoices -----------------------------------------------------------------------------------
class InvoiceRow(NamedTuple):
    """Inputs of one sample invoice; VAT, surcharge, withholding and total are derived."""

    number: str
    supplier: int  # index into SUPPLIERS
    issue: date
    due: str  # ISO date or "" (the reader then applies issue + 30 days)
    base: str
    vat_rate: str
    surcharge_rate: str  # "" = none
    withholding_rate: str  # "" = none
    json_numbers: bool  # amounts as JSON numbers (True) or as strings (False)


INVOICE_ROWS: tuple[InvoiceRow, ...] = (
    InvoiceRow("AUR-2026-001", 0, date(2026, 1, 10), "2026-02-09", "1000.00", "21", "", "", True),
    InvoiceRow("AUR-2026-002", 0, date(2026, 2, 10), "", "450.50", "21", "", "", False),
    InvoiceRow("VAL-2026-003", 1, date(2026, 1, 5), "2026-01-20", "800.00", "21", "", "", True),
    InvoiceRow(
        "ASE-2026-007",
        2,
        date(2026, 2, 1),
        "2026-02-15",
        "200.00",
        "21",
        "5.2",
        "15",
        False,
    ),
    InvoiceRow("VAL-2026-004", 1, date(2026, 3, 5), "2026-03-20", "1234.56", "10", "", "", True),
)


def invoice_fields(row: InvoiceRow) -> dict[str, str]:
    """All invoice fields as strings; "" marks an absent optional value."""
    supplier = SUPPLIERS[row.supplier]
    base = Decimal(row.base)
    vat = percent_of(base, Decimal(row.vat_rate))
    surcharge = percent_of(base, Decimal(row.surcharge_rate)) if row.surcharge_rate else None
    withholding = percent_of(base, Decimal(row.withholding_rate)) if row.withholding_rate else None
    additions = [base, vat] + ([surcharge] if surcharge is not None else [])
    total = net_total(additions, [withholding] if withholding is not None else [])
    return {
        "invoice_number": row.number,
        "supplier_name": supplier.name,
        "supplier_tax_id": supplier.tax_id,
        "issue_date": row.issue.isoformat(),
        "due_date": row.due,
        "base_amount": row.base,
        "vat_rate": row.vat_rate,
        "vat_amount": str(vat),
        "surcharge_amount": "" if surcharge is None else str(surcharge),
        "withholding_amount": "" if withholding is None else str(withholding),
        "total": str(total),
        "currency": "EUR",
        "iban": format_iban(supplier.iban),
    }


def build_invoice_csv() -> str:
    """The invoice sample as plain-dialect CSV."""
    body = [[invoice_fields(r)[c] for c in INVOICE_COLUMNS] for r in INVOICE_ROWS]
    return _csv_text(INVOICE_COLUMNS, body)


class _Number(NamedTuple):
    """A JSON number written exactly as this text (no float round trip)."""

    text: str


_JSON_AMOUNT_KEYS = frozenset(
    {"base_amount", "vat_rate", "vat_amount", "surcharge_amount", "withholding_amount", "total"}
)


def _json_value(value: str | _Number) -> str:
    """JSON text of one value: numbers verbatim, strings escaped (non-ASCII kept)."""
    if isinstance(value, _Number):
        return value.text
    return json.dumps(value, ensure_ascii=False)


def build_invoice_json() -> str:
    """The same invoices as a JSON array; amounts are numbers or strings per `json_numbers`."""
    records: list[list[tuple[str, str | _Number]]] = []
    for row in INVOICE_ROWS:
        fields = invoice_fields(row)
        record: list[tuple[str, str | _Number]] = []
        for column in INVOICE_COLUMNS:
            value = fields[column]
            if value == "":
                continue  # optional value absent: omit the key
            if row.json_numbers and column in _JSON_AMOUNT_KEYS:
                record.append((column, _Number(value)))
            else:
                record.append((column, value))
        records.append(record)

    lines = ["["]
    for i, record in enumerate(records):
        lines.append("  {")
        for j, (key, value) in enumerate(record):
            comma = "," if j < len(record) - 1 else ""
            lines.append(f"    {json.dumps(key)}: {_json_value(value)}{comma}")
        lines.append("  }" + ("," if i < len(records) - 1 else ""))
    lines.append("]")
    return "\n".join(lines) + "\n"


def build_suppliers_csv() -> str:
    """The supplier-master sample (one supplier without an IBAN)."""
    body = [[s.name, s.tax_id, format_iban(s.iban) if s.iban else ""] for s in SUPPLIERS]
    return _csv_text(SUPPLIER_COLUMNS, body)


# --- committed samples --------------------------------------------------------------------------
def build_core_samples() -> dict[str, str]:
    """File name -> text of the five sample files (fixed content; no randomness)."""
    return {
        BANK_FILE: render_bank_csv(BANK_SAMPLE_ROWS, "plain"),
        BANK_FILE_ES: render_bank_csv(BANK_SAMPLE_ROWS, "european"),
        INVOICE_CSV_FILE: build_invoice_csv(),
        INVOICE_JSON_FILE: build_invoice_json(),
        SUPPLIERS_FILE: build_suppliers_csv(),
    }


def write_core_samples(out_dir: Path = DEFAULT_OUT_DIR) -> list[Path]:
    """Write the five sample files as UTF-8 without BOM and LF line endings."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, text in build_core_samples().items():
        path = out_dir / name
        path.write_bytes(text.encode("utf-8"))
        written.append(path)
    return written


# --- zombie-subscriptions demo (design section 10) ----------------------------------------------
ZOMBIE_DEMO_FILE = "zombie_demo_statement.csv"
ZOMBIE_DEMO_START: date = date(2026, 5, 1)
ZOMBIE_DEMO_END: date = date(2026, 10, 31)
ZOMBIE_MONTH_DAYS = 30  # planted subscriptions are charged every 30 days
ZOMBIE_SUBSCRIPTION = "Monthly subscription"
ZOMBIE_SALARY_COUNTERPARTY = "Luminar Estudio S.L."
ZOMBIE_SALARY_AMOUNT = "2450.00"

# E7b weekly shopping (zombie-subscriptions design section 4.8): 26 weekly charges whose amount is
# round_to_cents(base x 1.11^k) with k = (5 i + shift) mod 13. The 13 levels are more than 10%
# apart and each occurs exactly twice, 91 days apart, so no recurring series can form. The levels
# are written out (money arithmetic stays in ledger_kit.utils.money); a test recomputes them.
E7B_WEEKS = 26
E7B_LEVEL_COUNT = 13
E7B_LEVEL_STEP = 5
E7B_LEVELS: dict[str, tuple[str, ...]] = {
    "40.00": (
        "40.00",
        "44.40",
        "49.28",
        "54.71",
        "60.72",
        "67.40",
        "74.82",
        "83.05",
        "92.18",
        "102.32",
        "113.58",
        "126.07",
        "139.94",
    ),
    "5.00": (
        "5.00",
        "5.55",
        "6.16",
        "6.84",
        "7.59",
        "8.43",
        "9.35",
        "10.38",
        "11.52",
        "12.79",
        "14.20",
        "15.76",
        "17.49",
    ),
}


class WeeklyMerchant(NamedTuple):
    """A fictional merchant paid every week with E7b-shaped amounts."""

    name: str
    description: str
    base: str  # key of E7B_LEVELS
    shift: int  # offset into the level table
    start: date  # date of the first of the E7B_WEEKS charges


ZOMBIE_WEEKLY_MERCHANTS: tuple[WeeklyMerchant, ...] = (
    WeeklyMerchant("FRESHCO", "Groceries", "40.00", 0, date(2026, 5, 4)),
    WeeklyMerchant("SUPERMART", "Groceries", "40.00", 3, date(2026, 5, 5)),
    WeeklyMerchant("FUELSTOP", "Fuel", "40.00", 7, date(2026, 5, 6)),
    WeeklyMerchant("HARDWAREHUB", "Home supplies", "40.00", 11, date(2026, 5, 7)),
    WeeklyMerchant("GARDENPOINT", "Garden supplies", "40.00", 5, date(2026, 5, 6)),
    WeeklyMerchant("PHARMAPOINT", "Pharmacy", "5.00", 9, date(2026, 5, 8)),
    WeeklyMerchant("CAFELUNA", "Coffee", "5.00", 4, date(2026, 5, 9)),
    WeeklyMerchant("BAKERYONE", "Bakery", "5.00", 0, date(2026, 5, 3)),
    WeeklyMerchant("BOOKNOOK", "Stationery", "5.00", 2, date(2026, 5, 4)),
)

# Shops visited once in the six months (one row each, so no series can form).
ZOMBIE_ONE_OFF_MERCHANTS: tuple[tuple[str, str], ...] = (
    ("TOYBARN", "Toys"),
    ("TALLER NORTE", "Car repair"),
    ("OPTICA ESTRELLA", "Glasses"),
    ("LIBRERIA LUNA", "Books"),
    ("FLORISTERIA SOL", "Flowers"),
    ("CERRAJERIA RAPIDA", "Locksmith"),
    ("PAPELERIA CENTRAL", "Stationery"),
    ("TINTORERIA AZUL", "Dry cleaning"),
    ("MUEBLES VALDEMAR", "Furniture"),
    ("ELECTRO PUNTO", "Appliances"),
    ("CLINICA DENTAL ALBA", "Dentist"),
    ("VETERINARIA PATAS", "Vet"),
)

# Person names (Finance Rule 5) appear only on transfer rows.
ZOMBIE_TRANSFERS: tuple[BankRow, ...] = (
    BankRow(date(2026, 6, 14), "-29.90", "Luigi Rossi", "Transfer sent: shared dinner", ""),
    BankRow(date(2026, 7, 22), "-120.00", "Ana García", "Transfer sent", ""),
    BankRow(date(2026, 8, 19), "-60.00", "Marta Ferreira", "Transfer sent", ""),
    BankRow(date(2026, 9, 3), "-75.00", "Sophie Dupont", "Transfer sent", ""),
)
ZOMBIE_PERSON_COUNTERPARTIES: tuple[str, ...] = tuple(r.counterparty for r in ZOMBIE_TRANSFERS)

ONE_OFF_MIN_CENTS = 500
ONE_OFF_MAX_CENTS = 9000


def _monthly_rows(
    counterparty: str, start: date, amounts: Sequence[str], description: str = ZOMBIE_SUBSCRIPTION
) -> list[BankRow]:
    """Debit rows 30 days apart starting at `start`, one per amount."""
    return [
        BankRow(
            start + timedelta(days=ZOMBIE_MONTH_DAYS * i),
            f"-{amount}",
            counterparty,
            description,
            "",
        )
        for i, amount in enumerate(amounts)
    ]


def build_zombie_planted_rows() -> list[BankRow]:
    """The planted subscription patterns E1-E5, free trial, cancellation and zombies."""
    rows: list[BankRow] = []
    # E1: price step 12.99 -> 15.99 on the sixth charge.
    rows += _monthly_rows("STREAMFLEX INTL 4412", date(2026, 5, 7), ["12.99"] * 5 + ["15.99"])
    # E2: price step 9.99 -> 12.99 after three charges.
    rows += _monthly_rows("CLOUDVAULT", date(2026, 5, 12), ["9.99"] * 3 + ["12.99"] * 3)
    # E3: two parallel series with different amounts (no duplicate alert).
    rows += _monthly_rows("GLOWBILL", date(2026, 5, 9), ["2.99"] * 6)
    rows += _monthly_rows("GLOWBILL", date(2026, 5, 23), ["0.99"] * 6)
    # E4: two parallel series with the same amount (duplicate alert).
    rows += _monthly_rows("MUSICBOX", date(2026, 5, 8), ["10.99"] * 6)
    rows += _monthly_rows("MUSICBOX", date(2026, 5, 22), ["10.99"] * 6)
    # E5: one service under two counterparty spellings, aliased to "streaming" in config.toml.
    rows += _monthly_rows("STREAMFLIX INTL 7731", date(2026, 5, 10), ["14.99"] * 6)
    rows += _monthly_rows("STREAMFLIXCOM", date(2026, 5, 20), ["14.99"] * 6)
    # Free trial: 0.49 fourteen days before the first of six 14.99 charges.
    rows.append(BankRow(date(2026, 5, 8), "-0.49", "SECUREPASS", "Trial activation", ""))
    rows += _monthly_rows("SECUREPASS", date(2026, 5, 22), ["14.99"] * 6)
    # Charges after cancellation: cancelled 2026-07-31, still charged on Aug 9, Sep 8, Oct 8.
    rows += _monthly_rows("GYMPLUS", date(2026, 5, 11), ["8.99"] * 6)
    # Zombie candidates: monthly charges, each with a last-used date in config.toml.
    rows += _monthly_rows("BEATSTREAM P2A3B4C5", date(2026, 5, 14), ["9.99"] * 6)
    rows += _monthly_rows("PHOTOBOX", date(2026, 5, 16), ["4.99"] * 6)
    rows += _monthly_rows("STASHCRATE", date(2026, 5, 18), ["2.99"] * 6)
    return rows


def build_zombie_weekly_rows() -> list[BankRow]:
    """Weekly shopping with E7b-shaped amounts for every merchant of ZOMBIE_WEEKLY_MERCHANTS."""
    rows: list[BankRow] = []
    for merchant in ZOMBIE_WEEKLY_MERCHANTS:
        levels = E7B_LEVELS[merchant.base]
        for week in range(E7B_WEEKS):
            level = levels[(E7B_LEVEL_STEP * week + merchant.shift) % E7B_LEVEL_COUNT]
            day = merchant.start + timedelta(days=7 * week)
            rows.append(BankRow(day, f"-{level}", merchant.name, merchant.description, ""))
    return rows


def build_zombie_salary_rows() -> list[BankRow]:
    """One payroll credit on the 28th of each month of the demo window."""
    return [
        BankRow(
            date(2026, month, 28),
            ZOMBIE_SALARY_AMOUNT,
            ZOMBIE_SALARY_COUNTERPARTY,
            "Payroll",
            "",
        )
        for month in range(5, 11)
    ]


def build_zombie_one_off_rows(seed: int) -> list[BankRow]:
    """One purchase per ZOMBIE_ONE_OFF_MERCHANTS entry; the date and amount come from `seed`."""
    rng = random.Random(seed)
    span_days = (ZOMBIE_DEMO_END - ZOMBIE_DEMO_START).days
    rows: list[BankRow] = []
    for name, description in ZOMBIE_ONE_OFF_MERCHANTS:
        day = ZOMBIE_DEMO_START + timedelta(days=rng.randint(0, span_days))
        cents = rng.randint(ONE_OFF_MIN_CENTS, ONE_OFF_MAX_CENTS)
        rows.append(BankRow(day, f"-{cents // 100}.{cents % 100:02d}", name, description, ""))
    return rows


def zombie_noise_counterparties() -> tuple[str, ...]:
    """Counterparties of the demo that are not subscriptions (shopping, shops, people, payroll)."""
    return (
        *(m.name for m in ZOMBIE_WEEKLY_MERCHANTS),
        *(name for name, _ in ZOMBIE_ONE_OFF_MERCHANTS),
        *ZOMBIE_PERSON_COUNTERPARTIES,
        ZOMBIE_SALARY_COUNTERPARTY,
    )


def build_zombie_demo_rows(seed: int = DEFAULT_SEED) -> list[BankRow]:
    """All demo rows in date order (stable: rows of one day keep their construction order)."""
    rows = [
        *build_zombie_planted_rows(),
        *build_zombie_weekly_rows(),
        *build_zombie_salary_rows(),
        *ZOMBIE_TRANSFERS,
        *build_zombie_one_off_rows(seed),
    ]
    return sorted(rows, key=lambda r: r.day)


def build_zombie_demo_csv(seed: int = DEFAULT_SEED) -> str:
    """The zombie demo statement as plain-dialect CSV text."""
    return render_bank_csv(build_zombie_demo_rows(seed), "plain")


# --- phantom-invoices demo (phantom-invoices design section 15) ---------------------------------
PHANTOM_DEMO_DIR = "phantom_demo"
PHANTOM_FILES: tuple[str, ...] = ("suppliers.csv", "invoices.csv", "payments.csv")
DEMO_LATEST_DATE: date = date(2026, 10, 30)  # the date of one clean payment: the default as_of
PHANTOM_PAYMENT_CAP: date = date(2026, 10, 29)  # no other payment is dated later than this
PHANTOM_TERM_DAYS = 30  # payment term of every invoice with a due date (and the reader default)
PHANTOM_CLEAN_INVOICES = 5  # monthly invoices (May to September) of each clean supplier
PHANTOM_CLEAN_VAT_RATES: tuple[int, ...] = (21, 21, 21, 10, 4, 0)  # drawn with rng.choice
PHANTOM_BASE_RANGE: tuple[int, int] = (80, 1800)  # integer part of a clean base amount
PHANTOM_DELAY_RANGE: tuple[int, int] = (10, 40)  # days from issue to payment (clean invoice)
PHANTOM_NO_DUE_DATE_MODULUS = 4  # clean invoice (j, m) has no due date when (j + m) % 4 == 0
PHANTOM_IBAN_STYLES: tuple[str, ...] = ("", "master", "compact_lower")  # cycled by (j + m) % 3
PHANTOM_DEBIT_NOTE = "Supplier payment"

# Bank and branch of supplier k: BANKS[(k - 1) % 4]; the master account is derived from k alone,
# so every IBAN is seed-independent.
BANKS: tuple[tuple[str, str], ...] = (
    ("2100", "0418"),
    ("0049", "1500"),
    ("0182", "5900"),
    ("0081", "7000"),
)
PHANTOM_ACCOUNT_MULTIPLIER = 7_654_321
PHANTOM_OTHER_ACCOUNT_OFFSET = 1_111_111  # second valid account (P5 invoice, non-master payment)
PHANTOM_UNRELATED_FIRST_K = 100  # unrelated debit counterparty i uses k = 100 + i


class PlanEntry(NamedTuple):
    """One line of the supplier plan; `code` is the invoice-number prefix of a clean supplier."""

    case: str
    name: str
    person: bool  # persons get a NIF, companies a CIF
    code: str  # "" for the 16 planted cases


# Position k (1-based) in this table drives every identifier of the supplier.
PHANTOM_PLAN: tuple[PlanEntry, ...] = (
    PlanEntry("P1", "Suministros Ibéricos Aurora, S.L.", False, ""),
    PlanEntry("P2", "Inmuebles Valdemar, S.L.", False, ""),
    PlanEntry("P3", "Gráficas Montealto, S.L.", False, ""),
    PlanEntry("P4", "Limpiezas Brillante Norte, S.L.", False, ""),
    PlanEntry("P5", "Transportes Hermanos Lage, S.L.", False, ""),
    PlanEntry("P6", "Material de Oficina Sierra Clara, S.L.", False, ""),
    PlanEntry("P7", "Informática Rioja Sur, S.L.", False, ""),
    PlanEntry("P8", "Ana García (Asesoría Fiscal)", True, ""),
    PlanEntry("P9", "Luigi Rossi (Reformas)", True, ""),
    PlanEntry("P10", "Distribuciones Costa Azul, S.L.", False, ""),
    PlanEntry("P11", "Comercial Minorista Pérez, S.L.", False, ""),
    PlanEntry("P12", "Sophie Dupont (Traducciones)", True, ""),
    PlanEntry("NON_MASTER_PAYMENT", "Mantenimientos Delta Ibérica, S.L.", False, ""),
    PlanEntry("OVERDUE", "Carpintería Roble Viejo, S.L.", False, ""),
    PlanEntry("OPEN_NOT_DUE", "Catering Sabores del Sur, S.L.", False, ""),
    PlanEntry("MULTI_RATE", "Obras y Reformas Atlántico, S.L.", False, ""),
    PlanEntry("C1", "Electricidad Luminar, S.L.", False, "EL"),
    PlanEntry("C2", "Agua y Gas Cantábrico, S.L.", False, "AC"),
    PlanEntry("C3", "Yusuf Demir (Mantenimiento)", True, "YD"),
    PlanEntry("C4", "Seguros Faro Mediterráneo, S.L.", False, "SF"),
    PlanEntry("C5", "Software Colmena, S.L.", False, "SC"),
    PlanEntry("C6", "Papeles del Duero, S.L.", False, "PD"),
    PlanEntry("C7", "Mei Chen (Diseño)", True, "MC"),
    PlanEntry("C8", "Gestoría Tres Cantos, S.L.", False, "GT"),
    PlanEntry("C9", "Jardinería Verde Mar, S.L.", False, "JV"),
)


class PhantomSupplier(NamedTuple):
    """A fictional supplier of the phantom demo with its derived identifiers."""

    k: int
    case: str
    name: str
    code: str
    tax_id: str
    iban: str  # compact master IBAN
    other_iban: str  # compact second valid account (P5 invoice, non-master payment)


def phantom_iban(k: int, *, other: bool = False) -> str:
    """Compact IBAN of supplier k (valid mod-97, wrong national digits); `other` = 2nd account."""
    bank, branch = BANKS[(k - 1) % len(BANKS)]
    offset = PHANTOM_OTHER_ACCOUNT_OFFSET if other else 0
    return make_iban(bank, branch, f"{(k * PHANTOM_ACCOUNT_MULTIPLIER + offset) % 10**10:010d}")


def _phantom_suppliers() -> tuple[PhantomSupplier, ...]:
    """The 25 suppliers of PHANTOM_PLAN with their identifiers."""
    suppliers: list[PhantomSupplier] = []
    for k, entry in enumerate(PHANTOM_PLAN, start=1):
        suppliers.append(
            PhantomSupplier(
                k,
                entry.case,
                entry.name,
                entry.code,
                make_nif(k) if entry.person else make_cif(k),
                phantom_iban(k),
                phantom_iban(k, other=True),
            )
        )
    return tuple(suppliers)


PHANTOM_SUPPLIERS: tuple[PhantomSupplier, ...] = _phantom_suppliers()
_BY_CASE: dict[str, PhantomSupplier] = {s.case: s for s in PHANTOM_SUPPLIERS}
PHANTOM_CASES: dict[str, str] = {s.case: s.tax_id for s in PHANTOM_SUPPLIERS if not s.code}
CLEAN_SUPPLIERS: tuple[str, ...] = tuple(s.tax_id for s in PHANTOM_SUPPLIERS if s.code)


def _iban_cell(supplier: PhantomSupplier, style: str) -> str:
    """Spell a supplier IBAN in one of the styles the demo uses."""
    spaced = format_iban(supplier.iban)
    spellings = {
        "": "",
        "master": spaced,
        "other": format_iban(supplier.other_iban),
        "lower": spaced.lower(),
        "compact_lower": supplier.iban.lower(),
        "hyphen": spaced.replace(" ", "-"),
    }
    return spellings[style]


def _invoice_record(
    supplier: PhantomSupplier,
    number: str,
    issue: date,
    base: str,
    rate: str,
    *,
    iban: str = "master",
    vat: str = "",
    surcharge_rate: str = "",
    withholding: str = "",
    due: str | None = None,
) -> dict[str, str]:
    """One invoice row as column -> text; VAT, surcharge and total come from the money helpers.

    `vat` overrides the computed VAT (the wrong amount of P7), `withholding` is written as given,
    `due=None` means issue + 30 days and `due=""` leaves the cell empty.
    """
    base_amount = Decimal(base)
    vat_amount = Decimal(vat) if vat else percent_of(base_amount, Decimal(rate))
    surcharge = percent_of(base_amount, Decimal(surcharge_rate)) if surcharge_rate else None
    held = Decimal(withholding) if withholding else None
    additions = [base_amount, vat_amount] + ([surcharge] if surcharge is not None else [])
    total = net_total(additions, [held] if held is not None else [])
    due_text = (issue + timedelta(days=PHANTOM_TERM_DAYS)).isoformat() if due is None else due
    return {
        "invoice_number": number,
        "supplier_name": supplier.name,
        "supplier_tax_id": supplier.tax_id,
        "issue_date": issue.isoformat(),
        "due_date": due_text,
        "base_amount": base,
        "vat_rate": rate,
        "vat_amount": str(vat_amount),
        "surcharge_amount": "" if surcharge is None else str(surcharge),
        "withholding_amount": "" if held is None else str(held),
        "total": str(total),
        "currency": "EUR",
        "iban": _iban_cell(supplier, iban),
    }


def _plant(case: str, number: str, issue: date, base: str, rate: str, **kwargs: str) -> dict:
    """One planted invoice row of the supplier of `case` (no randomness)."""
    return _invoice_record(_BY_CASE[case], number, issue, base, rate, **kwargs)


def _planted_invoices() -> list[dict[str, str]]:
    """The 25 literal invoice rows of the 16 planted cases (design sections 15.4 and 15.5)."""
    return [
        # P1: the same invoice twice
        _plant("P1", "F-2026-0310", date(2026, 10, 6), "400.00", "21"),
        _plant("P1", "F-2026-0310", date(2026, 10, 6), "400.00", "21"),
        # P2: monthly rent, no alert
        _plant("P2", "ALQ-2026-01", date(2026, 8, 3), "600.00", "21"),
        _plant("P2", "ALQ-2026-02", date(2026, 9, 2), "600.00", "21"),
        _plant("P2", "ALQ-2026-03", date(2026, 10, 2), "600.00", "21"),
        # P3: near-identical numbers
        _plant("P3", "F-2026-0042", date(2026, 10, 1), "200.00", "21"),
        _plant("P3", "F2026-042", date(2026, 10, 4), "200.00", "21"),
        # P4: invoice IBAN in lower case with spaces, same account as the master
        _plant("P4", "L-2026-118", date(2026, 7, 6), "150.00", "21", iban="lower"),
        # P5: invoice IBAN is a different valid account
        _plant("P5", "T-2026-077", date(2026, 10, 9), "300.00", "21", iban="other"),
        # P6: correct invoice
        _plant("P6", "MO-2026-031", date(2026, 6, 10), "100.00", "21"),
        # P7: VAT amount 12.10 instead of 21.00
        _plant("P7", "IR-2026-044", date(2026, 10, 13), "100.00", "21", vat="12.10"),
        # P8: withholding 150.00
        _plant("P8", "AG-2026-007", date(2026, 7, 1), "1000.00", "21", withholding="150.00"),
        # P9: paid twice
        _plant("P9", "R-2026-009", date(2026, 7, 14), "500.00", "21"),
        # P10: same total on four dates 6, 7 and 8 days apart
        _plant("P10", "FAC-0101", date(2026, 9, 18), "75.00", "21"),
        _plant("P10", "FAC-0102", date(2026, 9, 24), "75.00", "21"),
        _plant("P10", "FAC-0103", date(2026, 10, 1), "75.00", "21"),
        _plant("P10", "FAC-0104", date(2026, 10, 9), "75.00", "21"),
        # P11: surcharge 5.2 %
        _plant("P11", "CM-2026-052", date(2026, 8, 12), "100.00", "21", surcharge_rate="5.2"),
        # P12: hyphenated IBAN, then no IBAN
        _plant("P12", "TR-2026-014", date(2026, 10, 7), "50.00", "21", iban="hyphen"),
        _plant("P12", "TR-2026-015", date(2026, 10, 14), "100.00", "21", iban=""),
        # (a) invoice later paid to a non-master IBAN
        _plant("NON_MASTER_PAYMENT", "MD-2026-210", date(2026, 8, 18), "1000.00", "21"),
        # (b) overdue, unpaid
        _plant("OVERDUE", "CR-2026-051", date(2026, 8, 20), "700.00", "21"),
        # (c) open, not yet due
        _plant("OPEN_NOT_DUE", "CS-2026-033", date(2026, 10, 12), "250.00", "21"),
        # (d) two VAT rates on one invoice: both rows are quarantined by the app
        _plant("MULTI_RATE", "OB-2026-008", date(2026, 9, 30), "800.00", "21"),
        _plant("MULTI_RATE", "OB-2026-008", date(2026, 9, 30), "200.00", "10"),
    ]


def _debit(case: str, day: date, amount: str, *, other: bool = False) -> BankRow:
    """A debit (negative amount) to the supplier of `case`, to its master or its other IBAN."""
    supplier = _BY_CASE[case]
    iban = format_iban(supplier.other_iban if other else supplier.iban)
    return BankRow(day, f"-{amount}", supplier.name, PHANTOM_DEBIT_NOTE, iban)


def _planted_payments() -> list[BankRow]:
    """The 10 literal payments of the planted cases."""
    return [
        _debit("P2", date(2026, 8, 5), "726.00"),
        _debit("P2", date(2026, 9, 4), "726.00"),
        _debit("P2", date(2026, 10, 5), "726.00"),
        _debit("P4", date(2026, 8, 4), "181.50"),
        _debit("P6", date(2026, 7, 8), "121.00"),
        _debit("P8", date(2026, 7, 30), "1060.00"),
        _debit("P9", date(2026, 8, 10), "605.00"),
        _debit("P9", date(2026, 8, 12), "605.00"),
        _debit("P11", date(2026, 9, 9), "126.20"),
        _debit("NON_MASTER_PAYMENT", date(2026, 9, 14), "1210.00", other=True),
    ]


# Customer receipts (credits): ignored by every detector.
PHANTOM_CREDITS: tuple[BankRow, ...] = (
    BankRow(date(2026, 6, 15), "2400.00", "Cliente Ficticio Alba, S.L.", "Receipt", ""),
    BankRow(date(2026, 8, 31), "1850.50", "Cliente Ficticio Brisa, S.L.", "Receipt", ""),
    BankRow(date(2026, 10, 28), "3120.00", "Cliente Ficticio Cometa, S.L.", "Receipt", ""),
)
# Debits to counterparties that are no supplier of the master (IBANs outside the master).
PHANTOM_UNRELATED_DEBITS: tuple[tuple[date, str, str], ...] = (
    (date(2026, 7, 21), "-48.30", "Papelería La Esquina"),
    (date(2026, 8, 26), "-212.00", "Ferretería Monte Alto"),
    (date(2026, 9, 30), "-95.75", "Taxi Ciudad Jardín"),
    (date(2026, 10, 21), "-310.40", "Cafetería Plaza Nueva"),
)


def _unrelated_payments() -> list[BankRow]:
    """The three credits and the four unrelated debits (literal rows)."""
    rows = list(PHANTOM_CREDITS)
    for i, (day, amount, name) in enumerate(PHANTOM_UNRELATED_DEBITS):
        iban = format_iban(phantom_iban(PHANTOM_UNRELATED_FIRST_K + i))
        rows.append(BankRow(day, amount, name, "Card purchase", iban))
    return rows


def _clean_rows(rng: random.Random) -> tuple[list[dict[str, str]], list[BankRow]]:
    """The 45 invoices and 45 payments of the nine clean suppliers; the only use of `rng`.

    Fixed draw order, per supplier j and invoice m: base integer part, base cents, VAT rate
    (these three are redrawn until the total is new for the supplier), then the payment delay.
    """
    invoices: list[dict[str, str]] = []
    payments: list[BankRow] = []
    clean = [s for s in PHANTOM_SUPPLIERS if s.code]
    for j, supplier in enumerate(clean):
        totals: set[str] = set()
        for m in range(PHANTOM_CLEAN_INVOICES):
            issue = date(2026, 5 + m, 3 + (j * 5 + m * 3) % 20)
            while True:
                base = f"{rng.randrange(*PHANTOM_BASE_RANGE)}.{rng.randrange(100):02d}"
                rate = str(rng.choice(PHANTOM_CLEAN_VAT_RATES))
                no_due = (j + m) % PHANTOM_NO_DUE_DATE_MODULUS == 0
                record = _invoice_record(
                    supplier,
                    f"{supplier.code}-2026-{m + 1:03d}",
                    issue,
                    base,
                    rate,
                    iban=PHANTOM_IBAN_STYLES[(j + m) % len(PHANTOM_IBAN_STYLES)],
                    due="" if no_due else None,
                )
                if record["total"] not in totals:
                    break
            totals.add(record["total"])
            delay = rng.randrange(*PHANTOM_DELAY_RANGE)
            paid = min(issue + timedelta(days=delay), PHANTOM_PAYMENT_CAP)
            if j == len(clean) - 1 and m == PHANTOM_CLEAN_INVOICES - 1:
                paid = DEMO_LATEST_DATE
            iban = format_iban(supplier.iban)
            payments.append(
                BankRow(paid, f"-{record['total']}", supplier.name, PHANTOM_DEBIT_NOTE, iban)
            )
            invoices.append(record)
    return invoices, payments


def build_phantom_demo(seed: int = DEFAULT_SEED) -> dict[str, str]:
    """{"suppliers.csv": text, "invoices.csv": text, "payments.csv": text} for `seed`."""
    rng = random.Random(seed)
    clean_invoices, clean_payments = _clean_rows(rng)
    invoices = [*_planted_invoices(), *clean_invoices]
    payments = [*_planted_payments(), *_unrelated_payments(), *clean_payments]
    payments.sort(key=lambda r: (r.day, r.counterparty, Decimal(r.amount)))
    supplier_rows = [[s.name, s.tax_id, format_iban(s.iban)] for s in PHANTOM_SUPPLIERS]
    invoice_rows = [[r[column] for column in INVOICE_COLUMNS] for r in invoices]
    return {
        "suppliers.csv": _csv_text(SUPPLIER_COLUMNS, supplier_rows),
        "invoices.csv": _csv_text(INVOICE_COLUMNS, invoice_rows),
        "payments.csv": render_bank_csv(payments, "plain"),
    }


def write_phantom_demo(out_dir: Path, seed: int = DEFAULT_SEED) -> None:
    """Write the three demo files into `out_dir` as UTF-8 without BOM and LF line endings."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, text in build_phantom_demo(seed).items():
        (out_dir / name).write_bytes(text.encode("utf-8"))


# --- demo modes owned by the app specs ----------------------------------------------------------
def run_zombie_demo(args: argparse.Namespace) -> int:
    """Write data/samples/zombie_demo_statement.csv (or into --out-dir) for --seed."""
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / ZOMBIE_DEMO_FILE
    path.write_bytes(build_zombie_demo_csv(args.seed).encode("utf-8"))
    print(f"wrote {path}")
    return 0


def run_phantom_demo(args: argparse.Namespace) -> int:
    """Write the three phantom-demo CSV files into <out-dir>/phantom_demo for --seed."""
    out_dir = Path(args.out_dir) / PHANTOM_DEMO_DIR
    write_phantom_demo(out_dir, args.seed)
    for name in PHANTOM_FILES:
        print(f"wrote {out_dir / name}")
    return 0


def run_samples(args: argparse.Namespace) -> int:
    """Write the committed sample files."""
    for path in write_core_samples(Path(args.out_dir)):
        print(f"wrote {path}")
    return 0


def run_bank(args: argparse.Namespace) -> int:
    """Print or write a random bank statement."""
    text = build_bank_statement(args.seed, args.rows, args.dialect)
    if args.output:
        Path(args.output).write_bytes(text.encode("utf-8"))
        print(f"wrote {args.output}")
    else:
        sys.stdout.write(text)
    return 0


MODE_HANDLERS: dict[str, Callable[[argparse.Namespace], int]] = {
    "samples": run_samples,
    "bank": run_bank,
    "zombie-demo": run_zombie_demo,
    "phantom-demo": run_phantom_demo,
}


def build_parser() -> argparse.ArgumentParser:
    """Command-line parser."""
    parser = argparse.ArgumentParser(description="Generate synthetic sample data.")
    parser.add_argument("--mode", choices=sorted(MODE_HANDLERS), default="samples")
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help="random seed (bank, zombie-demo and phantom-demo modes)",
    )
    parser.add_argument("--rows", type=int, default=10, help="number of rows (bank mode)")
    parser.add_argument("--dialect", choices=("plain", "european"), default="plain")
    parser.add_argument("--output", help="bank mode: file to write instead of stdout")
    parser.add_argument(
        "--out-dir",
        default=str(DEFAULT_OUT_DIR),
        help="samples, zombie-demo and phantom-demo modes: directory",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the selected mode; returns the process exit code."""
    args = build_parser().parse_args(argv)
    if args.rows < 0:
        print("error: --rows must be >= 0", file=sys.stderr)
        return 2
    try:
        return MODE_HANDLERS[args.mode](args)
    except NotImplementedError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
