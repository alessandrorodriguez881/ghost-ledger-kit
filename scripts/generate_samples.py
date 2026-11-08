"""Seeded generator of synthetic sample data (Finance Rules 5 and 6).

Modes (``--mode``):

* ``samples`` (default): writes the five committed sample files of ledger-core Task 13 to
  ``data/samples/``. Their content is a fixed table, so it does not depend on the seed and the
  committed files are byte-identical to ``build_core_samples()`` (checked by a test).
* ``bank``: a random bank statement from ``--seed``, ``--rows`` and ``--dialect``; printed to
  stdout or written to ``--output``. Same arguments always give the same text.
* ``zombie-demo`` / ``phantom-demo``: reserved for the zombie-subscriptions and phantom-invoices
  specs. They are stubs here (see ``run_zombie_demo`` / ``run_phantom_demo``); each spec replaces
  its handler in ``MODE_HANDLERS`` and leaves the other modes untouched.

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
    """Fictional NIF number k with the letter after the correct one."""
    n = 1000 + k
    while n % 23 == 0:  # their correct letter is 'T'
        n += 1
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


# --- demo modes owned by the app specs (stubs) --------------------------------------------------
def run_zombie_demo(args: argparse.Namespace) -> int:
    """Stub for zombie-subscriptions (data/samples/zombie_demo_statement.csv, ~300-400 rows)."""
    raise NotImplementedError(
        "--mode zombie-demo is specified in .kiro/specs/zombie-subscriptions (design section 10); "
        "implement it there and register it in MODE_HANDLERS."
    )


def run_phantom_demo(args: argparse.Namespace) -> int:
    """Stub for phantom-invoices (data/samples/phantom_demo/{suppliers,invoices,payments}.csv)."""
    raise NotImplementedError(
        "--mode phantom-demo is specified in .kiro/specs/phantom-invoices (design section 15); "
        "implement it there and register it in MODE_HANDLERS."
    )


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
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="random seed (bank mode)")
    parser.add_argument("--rows", type=int, default=10, help="number of rows (bank mode)")
    parser.add_argument("--dialect", choices=("plain", "european"), default="plain")
    parser.add_argument("--output", help="bank mode: file to write instead of stdout")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="samples mode: directory")
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
