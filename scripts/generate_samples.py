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

Both demo modes also write the real-format twins of the same rows (real-formats design section 8):
a Norma 43 statement (``zombie_demo_statement.n43``, ``phantom_demo/payments.n43``; ISO-8859-1,
CRLF, 80-character records) and one Facturae 3.2.2 file per phantom supplier
(``phantom_demo/facturae/<kk>-<case>.xml``; UTF-8, LF). They are rendered from the very rows of
the CSV files, so the CSV bytes do not change.

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
import re
import sys
from collections.abc import Callable, Collection, Mapping, Sequence
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import NamedTuple
from xml.sax.saxutils import escape

# `python scripts/generate_samples.py` puts only scripts/ on sys.path: add the repository root.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ledger_kit.utils.money import (  # noqa: E402
    balance_after,
    format_as_european,
    implied_digits,
    net_total,
    percent_of,
    round_to_cents,
    sum_amounts,
)

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
    withholding_rate: str = "",
    due: str | None = None,
) -> dict[str, str]:
    """One invoice row as column -> text; VAT, surcharge and total come from the money helpers.

    `vat` overrides the computed VAT (the wrong amount of P7), `withholding` is written as given,
    `due=None` means issue + 30 days and `due=""` leaves the cell empty. The two rates are kept
    under extra keys (`surcharge_rate`, `withholding_rate`) that the CSV writer ignores: the
    Facturae writer needs a rate next to each amount and must not invert an amount into a rate.
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
        "surcharge_rate": surcharge_rate,
        "withholding_rate": withholding_rate,
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
        # P8: withholding 150.00 (15 %)
        _plant(
            "P8",
            "AG-2026-007",
            date(2026, 7, 1),
            "1000.00",
            "21",
            withholding="150.00",
            withholding_rate="15",
        ),
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


class PhantomDemoRows(NamedTuple):
    """The rows behind every phantom-demo file: invoice records and the sorted payments."""

    invoices: list[dict[str, str]]
    payments: list[BankRow]


def build_phantom_demo_rows(seed: int = DEFAULT_SEED) -> PhantomDemoRows:
    """The invoice records and sorted payments of the phantom demo for `seed`."""
    rng = random.Random(seed)
    clean_invoices, clean_payments = _clean_rows(rng)
    invoices = [*_planted_invoices(), *clean_invoices]
    payments = [*_planted_payments(), *_unrelated_payments(), *clean_payments]
    payments.sort(key=lambda r: (r.day, r.counterparty, Decimal(r.amount)))
    return PhantomDemoRows(invoices, payments)


def render_phantom_demo_csv(rows: PhantomDemoRows) -> dict[str, str]:
    """{"suppliers.csv": text, "invoices.csv": text, "payments.csv": text} for the given rows."""
    supplier_rows = [[s.name, s.tax_id, format_iban(s.iban)] for s in PHANTOM_SUPPLIERS]
    invoice_rows = [[r[column] for column in INVOICE_COLUMNS] for r in rows.invoices]
    return {
        "suppliers.csv": _csv_text(SUPPLIER_COLUMNS, supplier_rows),
        "invoices.csv": _csv_text(INVOICE_COLUMNS, invoice_rows),
        "payments.csv": render_bank_csv(rows.payments, "plain"),
    }


def build_phantom_demo(seed: int = DEFAULT_SEED) -> dict[str, str]:
    """{"suppliers.csv": text, "invoices.csv": text, "payments.csv": text} for `seed`."""
    return render_phantom_demo_csv(build_phantom_demo_rows(seed))


def write_phantom_demo(out_dir: Path, seed: int = DEFAULT_SEED) -> None:
    """Write the three demo files into `out_dir` as UTF-8 without BOM and LF line endings."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, text in build_phantom_demo(seed).items():
        (out_dir / name).write_bytes(text.encode("utf-8"))


# --- real formats: Norma 43 writer (real-formats design section 8.2) -----------------------------
ZOMBIE_DEMO_N43_FILE = "zombie_demo_statement.n43"
PHANTOM_PAYMENTS_N43_FILE = "payments.n43"
PHANTOM_FACTURAE_DIR = "facturae"

N43_RECORD_LENGTH = 80
N43_ENCODING = "iso-8859-1"  # the character set of the standard; other characters raise
N43_EOL = "\r\n"
N43_DEMO_ACCOUNT: tuple[str, str, str] = ("9999", "0001", "0000000001")  # bank, branch, account
N43_PHANTOM_ACCOUNT: tuple[str, str, str] = ("9999", "0001", "0000000002")
N43_HOLDER = "TITULAR FICTICIO DEMO"
N43_CURRENCY = "978"  # EUR (AEB Annex 2)
N43_OPENING_BALANCE = Decimal("50000.00")  # creditor; keeps the zombie closing balance creditor
# The phantom payments debit less than 98.000,00 more than they credit for any seed (45 clean
# payments of at most 2.177,99 plus the fixed ones), so this keeps its closing balance creditor.
N43_PHANTOM_OPENING_BALANCE = Decimal("100000.00")
N43_END_NINES = "9" * 18
N43_FIRST_YEAR = 2000  # dates are YYMMDD with the year 2000 + YY
N43_LAST_YEAR = 2099
N43_OWN_CONCEPT = "000"
N43_DOCUMENT = "0000000000"
N43_REFERENCE = "000000000000"
N43_INFORMATION_MODES: tuple[int, ...] = (1, 2, 3)
N43_SEPA_MODE = 3  # SEPA direct debits are only read in information mode 3
N43_SEPA_SCHEME = "CORE"
N43_SEPA_CONCEPT = "03"  # direct debits and bills
N43_SEPA_CREDITOR_PREFIX = "ES00ZZZ"  # check digits 00: never a real creditor identifier
N43_SEPA_CIF_BASE = 500  # creditor n uses make_cif(500 + n)
N43_SEPA_MANDATE_PREFIX = "MND"
N43_IBAN_PREFIX = "IBAN "  # a free record 23 starting with this carries the counterparty IBAN
N43_TRANSFER_PREFIX = "Transfer"
N43_TRANSFER_CONCEPT = "04"
N43_FALLBACK_CONCEPT = "99"
# Common concept (Annex 2) by exact description; other descriptions starting "Transfer" are 04.
N43_CONCEPT_BY_DESCRIPTION: dict[str, str] = {
    ZOMBIE_SUBSCRIPTION: "03",
    "Payroll": "15",
    PHANTOM_DEBIT_NOTE: "04",
    "Receipt": "04",
    "Card purchase": "12",
}


def n43_common_concept(description: str) -> str:
    """Common concept of a row: the table first, then 04 for any 'Transfer...', else 99."""
    if description in N43_CONCEPT_BY_DESCRIPTION:
        return N43_CONCEPT_BY_DESCRIPTION[description]
    if description.startswith(N43_TRANSFER_PREFIX):
        return N43_TRANSFER_CONCEPT
    return N43_FALLBACK_CONCEPT


def _n43_date(day: date) -> str:
    """YYMMDD of a day; a year outside 2000-2099 cannot be written."""
    if not N43_FIRST_YEAR <= day.year <= N43_LAST_YEAR:
        raise ValueError(f"year {day.year} cannot be written as YY")
    return f"{day.year % 100:02d}{day.month:02d}{day.day:02d}"


def _n43_record(code: str, *fields: tuple[int, int, str]) -> str:
    """An 80-character record: `code` at 1-2 and each (start, end, text) at its 1-based span."""
    chars = [" "] * N43_RECORD_LENGTH
    chars[0:2] = list(code)
    for start, end, text in fields:
        width = end - start + 1
        if len(text) > width:
            raise ValueError(f"{text!r} does not fit positions {start}-{end}")
        if not text.isprintable():
            raise ValueError(f"{text!r} holds a control or non-printable character")
        text.encode(N43_ENCODING)  # raises UnicodeEncodeError (a ValueError) beyond Latin-1
        chars[start - 1 : end] = list(text.ljust(width))
    return "".join(chars)


def _n43_sepa_identifiers(number: int) -> tuple[str, str]:
    """Creditor identifier and mandate of the SEPA counterparty `number` (1-based)."""
    creditor_id = f"{N43_SEPA_CREDITOR_PREFIX}{make_cif(N43_SEPA_CIF_BASE + number)}"
    return creditor_id, f"{N43_SEPA_MANDATE_PREFIX}{number:04d}"


def _n43_complements(row: BankRow, sepa: tuple[str, str] | None) -> list[str]:
    """The record-23 lines of a row: SEPA direct debit, or free counterparty/description/IBAN."""
    if sepa is not None:
        creditor_id, mandate = sepa
        return [
            _n43_record("23", (3, 4, "01"), (5, 8, N43_SEPA_SCHEME), (9, 78, row.counterparty)),
            _n43_record("23", (3, 4, "02"), (5, 39, creditor_id), (40, 74, mandate)),
            _n43_record("23", (3, 4, "03"), (13, 80, row.description)),
        ]
    if not row.counterparty or not row.description:
        raise ValueError("counterparty and description must not be empty")
    texts = [row.counterparty, row.description]
    if row.iban:
        texts.append(N43_IBAN_PREFIX + row.iban)
    return [
        _n43_record("23", (3, 4, f"{number:02d}"), (5, 80, text))
        for number, text in enumerate(texts, start=1)
    ]


def render_norma43_lines(
    rows: Sequence[BankRow],
    *,
    account: tuple[str, str, str] = N43_DEMO_ACCOUNT,
    mode: int = 1,
    sepa_descriptions: Collection[str] = frozenset(),
    opening: Decimal = N43_OPENING_BALANCE,
) -> list[str]:
    """The 80-character records of a one-account file: 11, a 22 and its 23s per row, 33, 88."""
    if not rows:
        raise ValueError("a Norma 43 file needs at least one row")
    if mode not in N43_INFORMATION_MODES:
        raise ValueError(f"unknown information mode {mode!r}")
    if sepa_descriptions and mode != N43_SEPA_MODE:
        raise ValueError("SEPA direct debits need information mode 3")
    bank, branch, number = account
    days = [row.day for row in rows]
    header = _n43_record(
        "11",
        (3, 6, bank),
        (7, 10, branch),
        (11, 20, number),
        (21, 26, _n43_date(min(days))),
        (27, 32, _n43_date(max(days))),
        (33, 33, "2"),
        (34, 47, implied_digits(opening)),
        (48, 50, N43_CURRENCY),
        (51, 51, str(mode)),
        (52, 77, N43_HOLDER),
    )
    lines = [header]
    debits: list[Decimal] = []
    credits: list[Decimal] = []
    sepa_numbers: dict[str, int] = {}
    for row in rows:
        is_debit = row.amount.startswith("-")
        magnitude = Decimal(row.amount.removeprefix("-"))
        (debits if is_debit else credits).append(magnitude)
        concept = n43_common_concept(row.description)
        sepa: tuple[str, str] | None = None
        if row.description in sepa_descriptions:
            creditor_number = sepa_numbers.setdefault(row.counterparty, len(sepa_numbers) + 1)
            sepa = _n43_sepa_identifiers(creditor_number)
            concept = N43_SEPA_CONCEPT
        day = _n43_date(row.day)
        movement = _n43_record(
            "22",
            (7, 10, branch),
            (11, 16, day),
            (17, 22, day),
            (23, 24, concept),
            (25, 27, N43_OWN_CONCEPT),
            (28, 28, "1" if is_debit else "2"),
            (29, 42, implied_digits(magnitude)),
            (43, 52, N43_DOCUMENT),
            (53, 64, N43_REFERENCE),
        )
        lines.append(movement)
        lines.extend(_n43_complements(row, sepa))

    debit_total = sum_amounts(debits)
    credit_total = sum_amounts(credits)
    closing = balance_after(opening, credit_total, debit_total)
    trailer = _n43_record(
        "33",
        (3, 6, bank),
        (7, 10, branch),
        (11, 20, number),
        (21, 25, f"{len(debits):05d}"),
        (26, 39, implied_digits(debit_total)),
        (40, 44, f"{len(credits):05d}"),
        (45, 58, implied_digits(credit_total)),
        (59, 59, "2" if closing >= 0 else "1"),
        (60, 73, implied_digits(abs(closing))),
        (74, 76, N43_CURRENCY),
    )
    lines.append(trailer)
    lines.append(_n43_record("88", (3, 20, N43_END_NINES), (21, 26, f"{len(lines):06d}")))
    return lines


def render_norma43(
    rows: Sequence[BankRow],
    *,
    account: tuple[str, str, str] = N43_DEMO_ACCOUNT,
    mode: int = 1,
    sepa_descriptions: Collection[str] = frozenset(),
    opening: Decimal = N43_OPENING_BALANCE,
) -> bytes:
    """A one-account Norma 43 file: ISO-8859-1, CRLF after every record, rows in order."""
    lines = render_norma43_lines(
        rows, account=account, mode=mode, sepa_descriptions=sepa_descriptions, opening=opening
    )
    return (N43_EOL.join(lines) + N43_EOL).encode(N43_ENCODING)


def build_zombie_demo_n43(seed: int = DEFAULT_SEED) -> bytes:
    """The zombie demo statement as Norma 43: mode 3, 'Monthly subscription' as SEPA debits."""
    return render_norma43(
        build_zombie_demo_rows(seed),
        mode=N43_SEPA_MODE,
        sepa_descriptions=frozenset({ZOMBIE_SUBSCRIPTION}),
    )


def build_phantom_payments_n43(seed: int = DEFAULT_SEED) -> bytes:
    """The phantom demo payments as Norma 43: mode 1, the IBAN in a free record 23."""
    return render_norma43(
        build_phantom_demo_rows(seed).payments,
        account=N43_PHANTOM_ACCOUNT,
        opening=N43_PHANTOM_OPENING_BALANCE,
    )


# --- real formats: Facturae 3.2.2 writer (real-formats design section 8.3) ----------------------
FACTURAE_NAMESPACE = "http://www.facturae.gob.es/formato/Versiones/Facturaev3_2_2.xml"
DSIG_NAMESPACE = "http://www.w3.org/2000/09/xmldsig#"
FACTURAE_VERSION = "3.2.2"
FACTURAE_ISSUER_TYPE = "EM"  # the issuer itself (emisor) sends the file
FACTURAE_DOCUMENT_TYPE = "FC"  # complete invoice
FACTURAE_INVOICE_CLASS = "OO"  # original
FACTURAE_LANGUAGE = "es"
FACTURAE_VAT_CODE = "01"  # IVA
FACTURAE_IRPF_CODE = "04"  # IRPF (withholding)
FACTURAE_PAYMENT_MEANS = "04"  # transfer
FACTURAE_PERSON_CODE = "F"  # natural person; companies use "J"
FACTURAE_COMPANY_CODE = "J"
FACTURAE_RESIDENCE_CODE = "R"  # resident in Spain
FACTURAE_QUANTITY = "1.00"
FACTURAE_LINE_DESCRIPTION = "Synthetic demo goods and services"
# One fictional address for every party: post code 00000 and a made-up town exist nowhere.
FACTURAE_POST_CODE = "00000"
FACTURAE_TOWN = "Ciudad Ficticia"
FACTURAE_PROVINCE = "Provincia Ficticia"
FACTURAE_COUNTRY = "ESP"
FACTURAE_SELLER_STREET = "Calle Ficticia 1"
FACTURAE_BUYER_STREET = "Calle Ficticia 2"
FACTURAE_BUYER_CIF_NUMBER = 900
FACTURAE_INDENT = "  "

_AMOUNT_TEXT = re.compile(r"\d+\.\d{2}")
_RATE_TEXT = re.compile(r"\d+(\.\d{1,2})?")
_CURRENCY_TEXT = re.compile(r"[A-Z]{3}")


class FacturaeParty(NamedTuple):
    """A seller or buyer: a company (CorporateName) or a person (Name + FirstSurname)."""

    name: str
    tax_id: str
    person: bool


FACTURAE_BUYER = FacturaeParty(
    "Compradora Ficticia Demo, S.L.", make_cif(FACTURAE_BUYER_CIF_NUMBER), False
)

Xml = list[str]  # the lines of an element, relative indentation only


def _el(name: str, text: str) -> Xml:
    """A leaf element on one line; the text is XML-escaped."""
    return [f"<{name}>{escape(text)}</{name}>"]


def _wrap(name: str, *children: Xml) -> Xml:
    """An element holding `children`, each line indented one level."""
    lines = [f"<{name}>"]
    for child in children:
        lines.extend(f"{FACTURAE_INDENT}{line}" for line in child)
    lines.append(f"</{name}>")
    return lines


def _amount_el(name: str, text: str) -> Xml:
    """An `AmountType` element: ``<name><TotalAmount>text</TotalAmount></name>``."""
    return _wrap(name, _el("TotalAmount", text))


def _amount_text(value: str) -> str:
    """`value` when it is a non-negative amount with exactly two decimals, else ValueError."""
    if _AMOUNT_TEXT.fullmatch(value) is None:
        raise ValueError(f"not an amount with two decimals: {value!r}")
    return value


def _rate_text(value: str) -> str:
    """A rate with exactly two decimals ('21' -> '21.00', '5.2' -> '5.20'), else ValueError."""
    if _RATE_TEXT.fullmatch(value) is None:
        raise ValueError(f"not a rate with at most two decimals: {value!r}")
    whole, _, fraction = value.partition(".")
    return f"{whole}.{fraction.ljust(2, '0')}"


def _two_places(value: Decimal) -> str:
    """A sum written with exactly two decimals (round-half-up, plain notation)."""
    return format(round_to_cents(value), "f")


def _sum_of(group: Sequence[Mapping[str, str]], key: str) -> Decimal:
    """Exact sum of the amounts under `key` of the records that have one."""
    return sum_amounts(Decimal(_amount_text(record[key])) for record in group if record.get(key))


def _invoice_key(record: Mapping[str, str]) -> tuple[str, str]:
    """The (number, issue date) pair that identifies an invoice in a file."""
    return record["invoice_number"], record["issue_date"]


def facturae_invoice_groups(
    records: Sequence[Mapping[str, str]],
) -> list[list[Mapping[str, str]]]:
    """Group records into invoices: same number and issue date, all rates different, share one.

    A repeated invoice (same number, date and rate) stays a separate invoice, like a duplicate.
    """
    groups: list[list[Mapping[str, str]]] = []
    for record in records:
        key = _invoice_key(record)
        for group in groups:
            rates = {item["vat_rate"] for item in group}
            if _invoice_key(group[0]) == key and record["vat_rate"] not in rates:
                group.append(record)
                break
        else:
            groups.append([record])
    return groups


def facturae_file_name(supplier: PhantomSupplier) -> str:
    """`<kk>-<case>.xml`: the two-digit position, the case lower-cased with '_' as '-'."""
    return f"{supplier.k:02d}-{supplier.case.lower().replace('_', '-')}.xml"


def _facturae_address(street: str) -> Xml:
    """AddressInSpain in schema order: Address, PostCode, Town, Province, CountryCode."""
    return _wrap(
        "AddressInSpain",
        _el("Address", street),
        _el("PostCode", FACTURAE_POST_CODE),
        _el("Town", FACTURAE_TOWN),
        _el("Province", FACTURAE_PROVINCE),
        _el("CountryCode", FACTURAE_COUNTRY),
    )


def _facturae_party(tag: str, party: FacturaeParty, street: str) -> Xml:
    """SellerParty or BuyerParty: TaxIdentification, then LegalEntity or Individual."""
    person_code = FACTURAE_PERSON_CODE if party.person else FACTURAE_COMPANY_CODE
    identification = _wrap(
        "TaxIdentification",
        _el("PersonTypeCode", person_code),
        _el("ResidenceTypeCode", FACTURAE_RESIDENCE_CODE),
        _el("TaxIdentificationNumber", party.tax_id),
    )
    address = _facturae_address(street)
    if party.person:
        name, _, surname = party.name.partition(" ")
        if not name or not surname.strip():
            raise ValueError(f"a person needs a name and a surname: {party.name!r}")
        identity = _wrap("Individual", _el("Name", name), _el("FirstSurname", surname), address)
    else:
        identity = _wrap("LegalEntity", _el("CorporateName", party.name), address)
    return _wrap(tag, identification, identity)


def _facturae_tax(record: Mapping[str, str]) -> Xml:
    """One TaxesOutputs/Tax: type, rate, base, amount and, when present, the surcharge."""
    children = [
        _el("TaxTypeCode", FACTURAE_VAT_CODE),
        _el("TaxRate", _rate_text(record["vat_rate"])),
        _amount_el("TaxableBase", _amount_text(record["base_amount"])),
        _amount_el("TaxAmount", _amount_text(record["vat_amount"])),
    ]
    if record.get("surcharge_amount"):
        rate = record.get("surcharge_rate", "")
        if not rate:
            raise ValueError("a surcharge amount needs its surcharge rate")
        surcharge = _amount_text(record["surcharge_amount"])
        children.append(_el("EquivalenceSurcharge", _rate_text(rate)))
        children.append(_amount_el("EquivalenceSurchargeAmount", surcharge))
    return _wrap("Tax", *children)


def _facturae_withheld(record: Mapping[str, str]) -> Xml:
    """One TaxesWithheld/Tax (IRPF): type, rate, base and amount."""
    rate = record.get("withholding_rate", "")
    if not rate:
        raise ValueError("a withholding amount needs its withholding rate")
    return _wrap(
        "Tax",
        _el("TaxTypeCode", FACTURAE_IRPF_CODE),
        _el("TaxRate", _rate_text(rate)),
        _amount_el("TaxableBase", _amount_text(record["base_amount"])),
        _amount_el("TaxAmount", _amount_text(record["withholding_amount"])),
    )


def _facturae_line(record: Mapping[str, str]) -> Xml:
    """One InvoiceLine for one tax entry: a single unit priced at the taxable base."""
    base = _amount_text(record["base_amount"])
    return _wrap(
        "InvoiceLine",
        _el("ItemDescription", FACTURAE_LINE_DESCRIPTION),
        _el("Quantity", FACTURAE_QUANTITY),
        _el("UnitPriceWithoutTax", base),
        _el("TotalCost", base),
        _el("GrossAmount", base),
        _wrap("TaxesOutputs", _facturae_tax(record)),
    )


def _facturae_payment(first: Mapping[str, str], total: str) -> Xml:
    """PaymentDetails with one transfer installment; the IBAN is written as the row holds it."""
    date.fromisoformat(first["due_date"])
    children = [
        _el("InstallmentDueDate", first["due_date"]),
        _el("InstallmentAmount", total),
        _el("PaymentMeans", FACTURAE_PAYMENT_MEANS),
    ]
    if first.get("iban"):
        children.append(_wrap("AccountToBeCredited", _el("IBAN", first["iban"])))
    return _wrap("PaymentDetails", _wrap("Installment", *children))


def _facturae_invoice(group: Sequence[Mapping[str, str]]) -> Xml:
    """One Invoice in schema order; an invoice with several rates has one Tax per rate."""
    first = group[0]
    date.fromisoformat(first["issue_date"])
    if _CURRENCY_TEXT.fullmatch(first["currency"]) is None:
        raise ValueError(f"not a currency code: {first['currency']!r}")
    gross = _two_places(_sum_of(group, "base_amount"))
    tax_sum = sum_amounts([_sum_of(group, "vat_amount"), _sum_of(group, "surcharge_amount")])
    withheld_total = _two_places(_sum_of(group, "withholding_amount"))
    total = _two_places(_sum_of(group, "total"))
    withheld = [record for record in group if record.get("withholding_amount")]

    header = _wrap(
        "InvoiceHeader",
        _el("InvoiceNumber", first["invoice_number"]),
        _el("InvoiceDocumentType", FACTURAE_DOCUMENT_TYPE),
        _el("InvoiceClass", FACTURAE_INVOICE_CLASS),
    )
    issue_data = _wrap(
        "InvoiceIssueData",
        _el("IssueDate", first["issue_date"]),
        _el("InvoiceCurrencyCode", first["currency"]),
        _el("TaxCurrencyCode", first["currency"]),
        _el("LanguageName", FACTURAE_LANGUAGE),
    )
    totals = _wrap(
        "InvoiceTotals",
        _el("TotalGrossAmount", gross),
        _el("TotalGrossAmountBeforeTaxes", gross),
        _el("TotalTaxOutputs", _two_places(tax_sum)),
        _el("TotalTaxesWithheld", withheld_total),
        _el("InvoiceTotal", total),
        _el("TotalOutstandingAmount", total),
        _el("TotalExecutableAmount", total),
    )
    children = [header, issue_data, _wrap("TaxesOutputs", *map(_facturae_tax, group))]
    if withheld:
        children.append(_wrap("TaxesWithheld", *map(_facturae_withheld, withheld)))
    children.append(totals)
    children.append(_wrap("Items", *map(_facturae_line, group)))
    if first.get("due_date"):
        children.append(_facturae_payment(first, total))
    return _wrap("Invoice", *children)


def render_facturae(
    supplier: FacturaeParty,
    records: Sequence[Mapping[str, str]],
    *,
    buyer: FacturaeParty = FACTURAE_BUYER,
) -> bytes:
    """A Facturae 3.2.2 file (UTF-8, LF) with every invoice of `records` for one supplier.

    Modality is I for one invoice and L for a batch of several. The Batch totals are the sums of
    the invoice totals, computed with `sum_amounts`. The element order follows the official
    schema; children are unqualified, as in real files. Nothing is parsed or validated here.
    """
    groups = facturae_invoice_groups(records)
    if not groups:
        raise ValueError("a Facturae file needs at least one invoice")
    currencies = {record["currency"] for record in records}
    if len(currencies) != 1:
        raise ValueError("a Facturae batch has one currency")
    currency = next(iter(currencies))
    batch_total = _two_places(sum_amounts(_sum_of(group, "total") for group in groups))
    batch = _wrap(
        "Batch",
        _el("BatchIdentifier", supplier.tax_id + groups[0][0]["invoice_number"]),
        _el("InvoicesCount", str(len(groups))),
        _amount_el("TotalInvoicesAmount", batch_total),
        _amount_el("TotalOutstandingAmount", batch_total),
        _amount_el("TotalExecutableAmount", batch_total),
        _el("InvoiceCurrencyCode", currency),
    )
    header = _wrap(
        "FileHeader",
        _el("SchemaVersion", FACTURAE_VERSION),
        _el("Modality", "I" if len(groups) == 1 else "L"),
        _el("InvoiceIssuerType", FACTURAE_ISSUER_TYPE),
        batch,
    )
    parties = _wrap(
        "Parties",
        _facturae_party("SellerParty", supplier, FACTURAE_SELLER_STREET),
        _facturae_party("BuyerParty", buyer, FACTURAE_BUYER_STREET),
    )
    invoices = _wrap("Invoices", *map(_facturae_invoice, groups))
    root = _wrap("Facturae", header, parties, invoices)
    root[0] = f'<fe:Facturae xmlns:ds="{DSIG_NAMESPACE}" xmlns:fe="{FACTURAE_NAMESPACE}">'
    root[-1] = "</fe:Facturae>"
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', *root]
    return ("\n".join(lines) + "\n").encode("utf-8")


def build_phantom_facturae(seed: int = DEFAULT_SEED) -> dict[str, bytes]:
    """{file name: bytes}: one Facturae file per phantom supplier."""
    invoices = build_phantom_demo_rows(seed).invoices
    files: dict[str, bytes] = {}
    for supplier in PHANTOM_SUPPLIERS:
        records = [row for row in invoices if row["supplier_tax_id"] == supplier.tax_id]
        party = FacturaeParty(supplier.name, supplier.tax_id, PHANTOM_PLAN[supplier.k - 1].person)
        files[facturae_file_name(supplier)] = render_facturae(party, records)
    return files


# --- real formats: wiring (real-formats design section 8.4) -------------------------------------
def build_zombie_demo_real(seed: int = DEFAULT_SEED) -> dict[str, bytes]:
    """{file name: bytes} of the zombie demo's real-format files (relative to data/samples)."""
    return {ZOMBIE_DEMO_N43_FILE: build_zombie_demo_n43(seed)}


def build_phantom_demo_real(seed: int = DEFAULT_SEED) -> dict[str, bytes]:
    """{path relative to phantom_demo: bytes} of the phantom demo's real-format files."""
    files = {PHANTOM_PAYMENTS_N43_FILE: build_phantom_payments_n43(seed)}
    for name, data in build_phantom_facturae(seed).items():
        files[f"{PHANTOM_FACTURAE_DIR}/{name}"] = data
    return files


def write_real_files(out_dir: Path, files: Mapping[str, bytes]) -> list[Path]:
    """Write `files` (relative path -> bytes) under `out_dir`; return the written paths."""
    written: list[Path] = []
    for relative, data in files.items():
        path = out_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        written.append(path)
    return written


# --- demo modes owned by the app specs ----------------------------------------------------------
def run_zombie_demo(args: argparse.Namespace) -> int:
    """Write the zombie demo statement as CSV and as Norma 43 (or into --out-dir) for --seed."""
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / ZOMBIE_DEMO_FILE
    path.write_bytes(build_zombie_demo_csv(args.seed).encode("utf-8"))
    print(f"wrote {path}")
    for written in write_real_files(out_dir, build_zombie_demo_real(args.seed)):
        print(f"wrote {written}")
    return 0


def run_phantom_demo(args: argparse.Namespace) -> int:
    """Write the phantom-demo CSV, Norma 43 and Facturae files into <out-dir>/phantom_demo."""
    out_dir = Path(args.out_dir) / PHANTOM_DEMO_DIR
    write_phantom_demo(out_dir, args.seed)
    for name in PHANTOM_FILES:
        print(f"wrote {out_dir / name}")
    for written in write_real_files(out_dir, build_phantom_demo_real(args.seed)):
        print(f"wrote {written}")
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
