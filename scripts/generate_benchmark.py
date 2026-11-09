"""Seeded generator of the benchmark scenarios (benchmark spec, design section 2).

Each scenario is one synthetic bank statement (zombie) or one invoice set (phantom) with
ground-truth labels, planted problems, hard negatives that must stay silent, and background
noise. Scenario ``i`` of app ``a`` for seed ``s`` depends only on ``(s, a, i)``.

Independence (REQ-BM-02): this file imports the standard library and ``ledger_kit.utils.money``
only. It never imports a detector, an app, the ingestion layer or ``generate_samples.py``, and it
reads neither the clock nor the environment. Every boundary value is a literal written from the
requirements text (design section 2.6), not taken from the code it judges.

All names, IBANs and tax ids are fictional (Finance Rules 5 and 6): IBANs have a valid mod-97
checksum and deliberately wrong Spanish national check digits, tax ids a wrong control character.
"""

import csv
import io
import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from ledger_kit.utils.money import net_total, percent_of, round_to_cents

BENCHMARK_SEED: int = 2026
SCENARIOS_PER_APP: int = 200

# Coverage the schedule must reach at the default size (asserted by tests, REQ-BM-05, 06, 07).
MIN_LABELS_PER_TYPE: int = 20
MIN_LABELS_PER_CASE: int = 20
MIN_INSTANCES_PER_NEGATIVE: int = 15
MAX_STATEMENT_ROWS: int = 200

# Schedule (design 2.2): every fifth scenario is noise only, the others plant 3 cases and
# 2 hard negatives; a noise-only scenario holds 4 label-free hard negatives.
NOISE_ONLY_EVERY: int = 5
CASES_PER_SCENARIO: int = 3
NEGATIVES_PER_SCENARIO: int = 2
NOISE_ONLY_NEGATIVES: int = 4

APPS: tuple[str, ...] = ("zombie", "phantom")
APP_PREFIX: Mapping[str, str] = {"zombie": "zs", "phantom": "pi"}

# --- Problem types (REQ-BM-05): detector, or detector/variant ----------------------------------
RECURRING = "zs.recurring_charge"
PRICE_UP = "zs.price_increase"
DUPLICATE_SUB = "zs.duplicate_subscription"
TRIAL = "zs.free_trial_to_paid"
CANCELLED = "zs.charges_after_cancellation"
SAME_NUMBER = "pi.duplicate_invoice/same_number"
NEAR_NUMBER = "pi.duplicate_invoice/near_identical_number"
SAME_TOTAL = "pi.duplicate_invoice/same_total_close_dates"
IBAN_DIFFERS = "pi.iban_change/invoice_iban_differs_from_master"
PAYMENT_ELSEWHERE = "pi.iban_change/payment_to_non_master_iban"
IBAN_BAD = "pi.iban_change/iban_invalid"
VAT_WRONG = "pi.vat_error/vat_amount_mismatch"
TOTAL_WRONG = "pi.vat_error/total_mismatch"
RATE_WRONG = "pi.vat_error/vat_rate_not_allowed"
LATE = "pi.reconciliation/invoice_overdue"
NO_INVOICE = "pi.reconciliation/payment_without_invoice"

ZOMBIE_TYPES: tuple[str, ...] = (RECURRING, PRICE_UP, DUPLICATE_SUB, TRIAL, CANCELLED)
PHANTOM_TYPES: tuple[str, ...] = (
    SAME_NUMBER,
    NEAR_NUMBER,
    SAME_TOTAL,
    IBAN_DIFFERS,
    PAYMENT_ELSEWHERE,
    IBAN_BAD,
    VAT_WRONG,
    TOTAL_WRONG,
    RATE_WRONG,
    LATE,
    NO_INVOICE,
)
PROBLEM_TYPES: Mapping[str, tuple[str, ...]] = {"zombie": ZOMBIE_TYPES, "phantom": PHANTOM_TYPES}

# --- Files and columns (REQ-BM-04) -------------------------------------------------------------
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
SCENARIO_FILES: Mapping[str, tuple[str, ...]] = {
    "zombie": ("statement.csv",),
    "phantom": ("invoices.csv", "suppliers.csv", "payments.csv"),
}

# --- Windows (design 2.3) ----------------------------------------------------------------------
ZOMBIE_START: date = date(2025, 1, 1)
ZOMBIE_DAYS: int = 455  # two yearly charges (365 days apart) fit with room to spare
ZOMBIE_END: date = ZOMBIE_START + timedelta(days=ZOMBIE_DAYS - 1)  # the latest date of any row
# REQ-ZS-13a / REQ-ZS-17: only an *active* series can be a duplicate, and a monthly series is
# active when its last charge lies within 30 + 3 days of the latest date of the ledger. Every row
# of a zombie scenario lies in the window, so a series whose last charge is at most this many
# days before ZOMBIE_END is active whatever else the scenario holds. A literal from the
# requirement (30 days nominal, below the 33 of the requirement), not read from a detector.
ACTIVE_TAIL_DAYS: int = 30
PHANTOM_START: date = date(2025, 1, 1)
FIRST_AS_OF: date = date(2025, 10, 1)
AS_OF_SPREAD_DAYS: int = 30
PAYMENT_DELAY_RANGE: tuple[int, int] = (10, 40)  # days from issue to payment of a clean invoice
PAYMENT_RESERVE_DAYS: int = 45  # clean invoices are issued at least this long before as_of
TERM_DAYS: int = 30  # due date = issue date + this

# --- Name pools (design 2.8): invented, uppercase letters only for merchants -------------------
MERCHANT_STEMS: tuple[str, ...] = (
    "CLOUD",
    "PIXEL",
    "NOVA",
    "ZEN",
    "ORBIT",
    "LUMEN",
    "QUARTZ",
    "MAPLE",
    "EMBER",
    "TIDAL",
    "VELVET",
    "AMBER",
    "COBALT",
    "DELTA",
    "FJORD",
    "GLINT",
    "HALO",
    "IVORY",
    "JADE",
    "KITE",
    "LUNA",
    "MOSS",
    "NIMBUS",
    "OPAL",
)
MERCHANT_SUFFIXES: tuple[str, ...] = (
    "VAULT",
    "FLIX",
    "BEAT",
    "STREAM",
    "BOX",
    "HUB",
    "LABS",
    "DECK",
    "WORKS",
    "NEST",
    "PLAY",
    "FORGE",
)
COMPANY_FIRST: tuple[str, ...] = (
    "Suministros",
    "Transportes",
    "Graficas",
    "Limpiezas",
    "Maderas",
    "Ceramicas",
    "Talleres",
    "Distribuciones",
    "Conservas",
    "Almacenes",
    "Herrajes",
    "Cartonajes",
)
COMPANY_SECOND: tuple[str, ...] = (
    "Ibericos",
    "Hermanos",
    "Montealto",
    "Valdemar",
    "Brillante",
    "Riomar",
    "Altamira",
    "Costaverde",
    "Delduero",
    "Norte",
    "Levante",
    "Sierra",
)
PERSONS: tuple[str, ...] = (
    "Ana García",
    "Luigi Rossi",
    "Sophie Dupont",
    "Mateo Silva",
    "Ingrid Larsen",
    "Yusuf Demir",
    "Priya Nair",
    "Tomás Herrera",
)
TRADES: tuple[str, ...] = ("Asesoría Fiscal", "Mantenimiento", "Traducciones", "Diseño Gráfico")
PREFIX_LETTERS: str = "ABCDEFGHJKLMNPRSTUVWXYZ"
BANK_BRANCHES: tuple[tuple[str, str], ...] = (
    ("2100", "0418"),
    ("0049", "1500"),
    ("0182", "5900"),
    ("0081", "7000"),
    ("0075", "0001"),
)

# --- Hand-checked rounding table (design 2.7): base, rate text, VAT (half-up), total -----------
# Written as literals on purpose: a test recomputes it with the money helpers and compares.
ROUNDING_TABLE: tuple[tuple[str, str, str, str], ...] = (
    ("12.50", "21", "2.63", "15.13"),
    ("7.50", "21", "1.58", "9.08"),
    ("2.50", "21", "0.53", "3.03"),
    ("33.33", "21", "7.00", "40.33"),
    ("1250.10", "21.00", "262.52", "1512.62"),
    ("0.50", "21", "0.11", "0.61"),
    ("0.25", "10", "0.03", "0.28"),
)

# Rate mix of the clean background invoices of the phantom app.
RATE_CHOICES: tuple[int, ...] = (21, 21, 21, 10, 4, 0)


# --- Records -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Label:
    """One planted problem: the rows that prove it, and rows kept only as context."""

    id: str
    scenario: str
    type: str
    rows: tuple[str, ...]
    context_rows: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Refuse a label that cites no row (REQ-BM-09)."""
        if not self.rows:
            raise ValueError(f"label {self.id} cites no row")


@dataclass(frozen=True)
class Negative:
    """One hard negative: rows that look like a problem and must not raise an alert."""

    id: str
    scenario: str
    kind: str
    rows: tuple[str, ...]


@dataclass(frozen=True)
class Scenario:
    """One synthetic input set with everything the runner needs to judge it."""

    id: str
    app: str
    noise_only: bool
    files: Mapping[str, str]
    context: Mapping[str, Any]
    labels: tuple[Label, ...]
    negatives: tuple[Negative, ...]
    row_facts: Mapping[str, tuple[str, str, str]]  # ref -> (date, amount, name or number)


@dataclass(frozen=True)
class CaseSpec:
    """One entry of a catalogue: an id, a name and the function that plants it."""

    id: str
    name: str
    run: Callable[["Builder"], None]
    label_free: bool = False


def seed_text(seed: int, app: str, index: int) -> str:
    """Return the text that seeds the random generator of one scenario (REQ-BM-03)."""
    return f"{seed}:{app}:{index}"


def scenario_id(app: str, index: int) -> str:
    """Return ``zs-0007`` or ``pi-0007`` for scenario ``index`` of ``app``."""
    return f"{APP_PREFIX[app]}-{index:04d}"


def natural(ref: str) -> tuple[str, int]:
    """Sort key of a source_ref: ``f.csv:9`` before ``f.csv:10``."""
    file, _sep, row = ref.rpartition(":")
    return (file, int(row)) if row.isdigit() else (ref, -1)


# --- Money text (no float anywhere) ------------------------------------------------------------


def cents(value: int) -> Decimal:
    """Return ``value`` hundredths as an exact two-decimal Decimal: 2000 -> 20.00."""
    return Decimal(value).scaleb(-2)


def money(amount: Decimal) -> str:
    """Return ``amount`` rounded half-up to cents as text with a dot decimal."""
    return f"{round_to_cents(amount):.2f}"


# --- Own identifier helpers (design 2.8; not shared with generate_samples.py) ------------------
DC_WEIGHTS: tuple[int, ...] = (1, 2, 4, 8, 5, 10, 9, 7, 3, 6)
NIF_LETTERS: str = "TRWAGMYFPDXBNJZSQVHLCKE"


def _dc_digit(digits: str) -> int:
    """One Spanish national control digit of a 10-digit string."""
    total = sum(int(d) * w for d, w in zip(digits, DC_WEIGHTS, strict=True))
    digit = 11 - total % 11
    return {10: 1, 11: 0}.get(digit, digit)


def make_iban(bank: str, branch: str, account: str) -> str:
    """Compact Spanish IBAN: valid mod-97 checksum, national check digits shifted by 11."""
    correct = int(f"{_dc_digit('00' + bank + branch)}{_dc_digit(account)}")
    bban = bank + branch + f"{(correct + 11) % 100:02d}" + account
    numeric = "".join(str(int(ch, 36)) for ch in bban + "ES" + "00")
    return "ES" + f"{98 - int(numeric) % 97:02d}" + bban


def format_iban(compact: str) -> str:
    """Group an IBAN in blocks of four."""
    return " ".join(compact[i : i + 4] for i in range(0, len(compact), 4))


def hyphenate_iban(compact: str) -> str:
    """Write an IBAN with hyphens: a malformed spelling (REQ-PI-23)."""
    return "-".join(compact[i : i + 4] for i in range(0, len(compact), 4))


def break_checksum(compact: str) -> str:
    """Change the last digit: still well formed, the mod-97 check no longer holds."""
    return compact[:-1] + str((int(compact[-1]) + 1) % 10)


def make_cif(k: int) -> str:
    """Fictional type-B CIF number k with an always-wrong control digit."""
    body = f"{k:07d}"
    total = 0
    for position, char in enumerate(body, start=1):
        digit = int(char)
        if position % 2 == 1:
            digit *= 2
            digit = digit // 10 + digit % 10
        total += digit
    return f"B{body}{((10 - total % 10) % 10 + 1) % 10}"


def make_nif(n: int) -> str:
    """Fictional NIF with an always-wrong control letter; ``n`` must not be a multiple of 23."""
    return f"{n:08d}{NIF_LETTERS[(n % 23 + 1) % 23]}"


# --- Row table ---------------------------------------------------------------------------------


class RowTable:
    """Collects rows per file; refs are fixed only after the final order is known (design 2.1).

    ``add`` returns a tag. ``resolve`` orders every file (by its order column, then insertion)
    and turns the position of each row into its ref ``"{file}:{index}"``. ``ref_of`` raises for
    a tag that was never added, so a label cannot cite a row that does not exist.
    """

    def __init__(self, files: Mapping[str, tuple[Sequence[str], str | None]]) -> None:
        """Declare the files as ``{name: (columns, order column or None)}``."""
        self._files = {name: (tuple(columns), order) for name, (columns, order) in files.items()}
        self._entries: dict[str, list[tuple[dict[str, str], tuple[str, str, str]]]] = {
            name: [] for name in files
        }
        self._refs: dict[str, str] = {}

    def add(self, file: str, cells: Mapping[str, str], fact: tuple[str, str, str]) -> str:
        """Add a row (missing columns stay empty) and return its tag."""
        entries = self._entries[file]
        tag = f"{file}#{len(entries)}"
        entries.append((dict(cells), fact))
        return tag

    def _order(self, file: str) -> list[int]:
        """Insertion indexes of ``file`` in final file order."""
        entries = self._entries[file]
        order_column = self._files[file][1]
        indexes = list(range(len(entries)))
        if order_column is None:
            return indexes
        return sorted(indexes, key=lambda i: (entries[i][0][order_column], i))

    def resolve(self) -> None:
        """Fix the file order and the ref of every row."""
        self._refs = {}
        for file in self._files:
            for position, index in enumerate(self._order(file)):
                self._refs[f"{file}#{index}"] = f"{file}:{position}"

    def ref_of(self, tag: str) -> str:
        """Return the ref of a tag; ValueError for a tag that was never added."""
        try:
            return self._refs[tag]
        except KeyError:
            raise ValueError(f"unknown row tag {tag!r}") from None

    def text(self, file: str) -> str:
        """Render one file as CSV with LF line endings."""
        columns = self._files[file][0]
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(columns)
        entries = self._entries[file]
        for index in self._order(file):
            cells = entries[index][0]
            writer.writerow([cells.get(column, "") for column in columns])
        return buffer.getvalue()

    def facts(self) -> dict[str, tuple[str, str, str]]:
        """Return ``ref -> (date, amount, name or number)`` for every row."""
        found: dict[str, tuple[str, str, str]] = {}
        for file, entries in self._entries.items():
            for index, (_cells, fact) in enumerate(entries):
                found[self._refs[f"{file}#{index}"]] = fact
        return found


@dataclass(frozen=True)
class Supplier:
    """A fictional supplier of the phantom app and its first master row."""

    name: str
    tax_id: str
    iban: str  # compact, as the master holds it
    prefix: str  # letters that start its invoice numbers
    master_tag: str

    @property
    def iban_text(self) -> str:
        """The IBAN grouped in blocks of four, as written in files."""
        return format_iban(self.iban)


# --- Builder -----------------------------------------------------------------------------------


class Builder:
    """Draws names, dates and amounts for one scenario and collects its rows and labels."""

    def __init__(self, app: str, index: int, seed: int = BENCHMARK_SEED) -> None:
        """Start an empty scenario; all randomness comes from ``seed_text(seed, app, index)``."""
        if app not in APPS:
            raise ValueError(f"unknown app {app!r}")
        self.app = app
        self.index = index
        self.id = scenario_id(app, index)
        self.noise_only = index % NOISE_ONLY_EVERY == 0
        self.rng = random.Random(seed_text(seed, app, index))
        self._used: set[str] = set()
        self._labels: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = []
        self._negatives: list[tuple[str, tuple[str, ...]]] = []
        self.as_of: date | None = None
        self.context: dict[str, Any]
        if app == "zombie":
            self.table = RowTable({"statement.csv": (BANK_COLUMNS, "date")})
            self.context = {"aliases": {}, "cancellation_dates": {}}
        else:
            self.table = RowTable(
                {
                    "invoices.csv": (INVOICE_COLUMNS, "issue_date"),
                    "suppliers.csv": (SUPPLIER_COLUMNS, None),
                    "payments.csv": (BANK_COLUMNS, "date"),
                }
            )
            self.context = {}
            self.set_as_of(FIRST_AS_OF + timedelta(days=self.rng.randrange(AS_OF_SPREAD_DAYS)))

    # -- labels and negatives

    def label(self, type_: str, rows: Sequence[str], context: Sequence[str] = ()) -> None:
        """Record a planted problem proved by the rows with these tags."""
        self._labels.append((type_, tuple(rows), tuple(context)))

    def negative(self, kind: str, rows: Sequence[str]) -> None:
        """Record a hard negative made of the rows with these tags."""
        self._negatives.append((kind, tuple(rows)))

    # -- random draws

    def _unique(self, draw: Callable[[], str]) -> str:
        """Draw until the text was not used in this scenario, then remember it."""
        while True:
            text = draw()
            if text not in self._used:
                self._used.add(text)
                return text

    def merchant(self) -> str:
        """A fresh invented merchant such as CLOUDVAULT."""
        rng = self.rng
        return self._unique(lambda: rng.choice(MERCHANT_STEMS) + rng.choice(MERCHANT_SUFFIXES))

    def amount(self, low_cents: int, high_cents: int) -> Decimal:
        """A random amount between the two bounds, both in hundredths."""
        return cents(self.rng.randint(low_cents, high_cents))

    def new_iban(self) -> str:
        """A fresh compact IBAN (valid checksum, wrong national digits)."""
        rng = self.rng

        def draw() -> str:
            bank, branch = rng.choice(BANK_BRANCHES)
            return make_iban(bank, branch, f"{rng.randrange(10**10):010d}")

        return self._unique(draw)

    # -- zombie rows

    def start(self, span_days: int) -> date:
        """A random start such that ``span_days`` later is still inside the zombie window."""
        return ZOMBIE_START + timedelta(days=self.rng.randrange(ZOMBIE_DAYS - span_days))

    def late_start(self, span_days: int, slack: int = 0) -> date:
        """A start such that the last row of the span is active at the end of the window.

        The first series of a case ends ``span_days`` after the start. Its last row falls
        between ``ACTIVE_TAIL_DAYS`` and ``slack`` days before ``ZOMBIE_END``; ``slack`` keeps
        room for a second series that ends ``slack`` days later (REQ-ZS-13a, REQ-ZS-17).
        """
        back = slack + self.rng.randrange(ACTIVE_TAIL_DAYS - slack + 1)
        return ZOMBIE_END - timedelta(days=back + span_days)

    def bank_row(
        self, file: str, day: date, signed: Decimal, name: str, description: str, iban: str = ""
    ) -> str:
        """Add one bank row (a debit when ``signed`` is negative) and return its tag."""
        cells = {
            "date": day.isoformat(),
            "amount": money(signed),
            "currency": "EUR",
            "counterparty": name,
            "description": description,
            "iban": iban,
        }
        return self.table.add(file, cells, (day.isoformat(), money(abs(signed)), name))

    def debit(self, day: date, amount: Decimal, name: str, description: str) -> str:
        """Add one debit to the zombie statement."""
        return self.bank_row("statement.csv", day, -amount, name, description)

    def credit(self, day: date, amount: Decimal, name: str, description: str) -> str:
        """Add one credit to the zombie statement."""
        return self.bank_row("statement.csv", day, amount, name, description)

    def series(
        self,
        name: str,
        days: Sequence[date],
        amounts: Sequence[Decimal],
        description: str = "Monthly subscription",
    ) -> list[str]:
        """Add one debit per day and amount; return their tags in that order."""
        return [self.debit(day, amount, name, description) for day, amount in zip(days, amounts)]

    # -- phantom rows

    def set_as_of(self, day: date) -> None:
        """Fix the ``as_of`` date of the scenario (it is part of the context)."""
        self.as_of = day
        self.context["as_of"] = day.isoformat()

    def issue_date(self, reserve: int = PAYMENT_RESERVE_DAYS) -> date:
        """A random issue date at least ``reserve`` days before ``as_of``."""
        assert self.as_of is not None
        last = self.as_of - timedelta(days=reserve)
        return PHANTOM_START + timedelta(days=self.rng.randrange((last - PHANTOM_START).days + 1))

    def _tax_id(self, person: bool) -> str:
        """A fresh fictional tax id with a wrong control character."""
        rng = self.rng

        def draw() -> str:
            if person:
                number = rng.randrange(10_000_000, 99_999_999)
                return make_nif(number if number % 23 else number + 1)
            return make_cif(rng.randrange(1, 9_999_999))

        return self._unique(draw)

    def supplier(
        self,
        *,
        person: bool | None = None,
        iban: str | None = None,
        master_text: str | None = None,
    ) -> Supplier:
        """A fresh supplier with its master row; ``master_text`` overrides the IBAN cell."""
        rng = self.rng
        as_person = rng.randrange(8) == 0 if person is None else person
        if as_person:
            name = self._unique(lambda: f"{rng.choice(PERSONS)} ({rng.choice(TRADES)})")
        else:
            name = self._unique(
                lambda: f"{rng.choice(COMPANY_FIRST)} {rng.choice(COMPANY_SECOND)}, S.L."
            )
        tax_id = self._tax_id(as_person)
        compact = iban or self.new_iban()
        prefix = "".join(rng.choice(PREFIX_LETTERS) for _ in range(3))
        text = format_iban(compact) if master_text is None else master_text
        tag = self.master_row(name, tax_id, text)
        return Supplier(name, tax_id, compact, prefix, tag)

    def master_row(self, name: str, tax_id: str, iban_text: str) -> str:
        """Add one row to the supplier master and return its tag."""
        cells = {"supplier_name": name, "tax_id": tax_id, "iban": iban_text}
        return self.table.add("suppliers.csv", cells, ("", "", name))

    def number(self, sup: Supplier) -> str:
        """A random invoice number such as ``QWE-0417``."""
        return f"{sup.prefix}-{self.rng.randint(1, 899):04d}"

    def payment(
        self,
        day: date,
        amount: Decimal,
        name: str,
        iban_text: str,
        description: str = "Supplier payment",
    ) -> str:
        """Add one debit to the payments file."""
        return self.bank_row("payments.csv", day, -amount, name, description, iban_text)

    def invoice(
        self,
        sup: Supplier,
        number: str,
        issue: date,
        base: Decimal,
        rate: Decimal,
        *,
        vat: Decimal | None = None,
        total: Decimal | None = None,
        rate_text: str | None = None,
        iban: str | None = None,
        paid: bool = True,
        pay_days: int | None = None,
        pay_total: Decimal | None = None,
        pay_iban: str | None = None,
    ) -> tuple[str, str | None]:
        """Add an invoice and (when ``paid``) its payment; return both tags.

        ``vat`` and ``total`` default to the correct values. ``iban`` overrides the invoice IBAN
        cell ("" means none); ``pay_iban`` overrides the IBAN of the payment.
        """
        vat_amount = percent_of(base, rate) if vat is None else vat
        total_amount = round_to_cents(net_total([base, vat_amount])) if total is None else total
        cells = {
            "invoice_number": number,
            "supplier_name": sup.name,
            "supplier_tax_id": sup.tax_id,
            "issue_date": issue.isoformat(),
            "due_date": (issue + timedelta(days=TERM_DAYS)).isoformat(),
            "base_amount": money(base),
            "vat_rate": str(rate) if rate_text is None else rate_text,
            "vat_amount": money(vat_amount),
            "total": money(total_amount),
            "currency": "EUR",
            "iban": sup.iban_text if iban is None else iban,
        }
        fact = (issue.isoformat(), money(total_amount), number)
        invoice_tag = self.table.add("invoices.csv", cells, fact)
        if not paid:
            return invoice_tag, None
        delay = self.rng.randint(*PAYMENT_DELAY_RANGE) if pay_days is None else pay_days
        paid_amount = total_amount if pay_total is None else pay_total
        pay_tag = self.payment(
            issue + timedelta(days=delay),
            paid_amount,
            sup.name,
            sup.iban_text if pay_iban is None else pay_iban,
        )
        return invoice_tag, pay_tag

    # -- result

    def _refs(self, tags: Sequence[str]) -> tuple[str, ...]:
        """Resolve tags to refs, without repeats, in natural order."""
        return tuple(sorted({self.table.ref_of(tag) for tag in tags}, key=natural))

    def scenario(self) -> Scenario:
        """Fix the file order and return the finished scenario."""
        self.table.resolve()
        labels = tuple(
            Label(f"{self.id}/L{k}", self.id, type_, self._refs(rows), self._refs(context))
            for k, (type_, rows, context) in enumerate(self._labels)
        )
        negatives = tuple(
            Negative(f"{self.id}/N{k}", self.id, kind, self._refs(rows))
            for k, (kind, rows) in enumerate(self._negatives)
        )
        files = {file: self.table.text(file) for file in SCENARIO_FILES[self.app]}
        return Scenario(
            id=self.id,
            app=self.app,
            noise_only=self.noise_only,
            files=files,
            context=_plain(self.context),
            labels=labels,
            negatives=negatives,
            row_facts=self.table.facts(),
        )


def _plain(value: Any) -> Any:
    """Copy a context made of dicts, lists and strings, so a scenario shares no state."""
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    return value


# --- Zombie helpers ----------------------------------------------------------------------------


def _days(start: date, count: int, gap: int) -> list[date]:
    """``count`` dates, ``gap`` days apart, from ``start``."""
    return [start + timedelta(days=gap * i) for i in range(count)]


def _days_from_gaps(start: date, gaps: Sequence[int]) -> list[date]:
    """``start`` followed by one date after each gap."""
    days = [start]
    for gap in gaps:
        days.append(days[-1] + timedelta(days=gap))
    return days


def _recurring(
    b: Builder,
    name: str | None,
    start: date | None,
    amount: Decimal | None,
    *,
    count: int,
    gap: int,
    description: str = "Monthly subscription",
) -> list[str]:
    """Plant one stable series and its recurring-charge label; return the row tags."""
    name = name or b.merchant()
    start = start or b.start((count - 1) * gap)
    amount = amount or b.amount(499, 4999)
    tags = b.series(name, _days(start, count, gap), [amount] * count, description)
    b.label(RECURRING, tags)
    return tags


def _price_case(
    b: Builder,
    name: str | None,
    start: date | None,
    before: Decimal,
    after: Decimal,
    *,
    price_label: bool,
    counts: tuple[int, int] = (3, 3),
) -> list[str]:
    """Plant a monthly series that steps from ``before`` to ``after``; return its row tags."""
    name = name or b.merchant()
    total = counts[0] + counts[1]
    start = start or b.start((total - 1) * 30)
    amounts = [before] * counts[0] + [after] * counts[1]
    tags = b.series(name, _days(start, total, 30), amounts)
    b.label(RECURRING, tags)
    if price_label:
        b.label(PRICE_UP, tags)
    return tags


def _parallel(
    b: Builder,
    names: tuple[str, str],
    start: date | None,
    amounts: tuple[Decimal, Decimal],
    *,
    duplicate: bool,
    count: int = 4,
) -> list[str]:
    """Plant two interleaved monthly series; return the tags of both.

    Both series end in the last ``ACTIVE_TAIL_DAYS`` days of the window, so both are active at
    the latest date of the ledger. REQ-ZS-17 counts active series only: a pair that ended months
    before the ledger does is not a duplicate subscription (design 2.4, D-BM-20).
    """
    span = (count - 1) * 30
    start = start or b.late_start(span, slack=15)
    tags_a = b.series(names[0], _days(start, count, 30), [amounts[0]] * count)
    tags_b = b.series(names[1], _days(start + timedelta(days=15), count, 30), [amounts[1]] * count)
    b.label(RECURRING, tags_a)
    b.label(RECURRING, tags_b)
    if duplicate:
        b.label(DUPLICATE_SUB, tags_a + tags_b)
    return tags_a + tags_b


def _trial_case(
    b: Builder,
    name: str | None,
    trial_day: date | None,
    price: Decimal | None,
    *,
    token: Decimal,
    lead: int,
    trial_label: bool,
) -> list[str]:
    """Plant a token debit ``lead`` days before six monthly charges; return all row tags."""
    name = name or b.merchant()
    trial_day = trial_day or b.start(lead + 150)
    price = price or b.amount(499, 1999)
    trial = b.debit(trial_day, token, name, "Free trial")
    charges = b.series(name, _days(trial_day + timedelta(days=lead), 6, 30), [price] * 6)
    b.label(RECURRING, charges)
    if trial_label:
        b.label(TRIAL, [trial, *charges])
    return [trial, *charges]


def _cancel_case(
    b: Builder,
    name: str | None,
    start: date | None,
    price: Decimal | None,
    *,
    count: int,
    anchor: int,
    offset: int,
) -> list[str]:
    """Plant ``count`` monthly charges and a cancellation date after charge ``anchor``.

    The date is ``offset`` days after that charge. Charges strictly after it get a
    charges-after-cancellation label (REQ-ZS-24).
    """
    name = name or b.merchant()
    start = start or b.start((count - 1) * 30)
    price = price or b.amount(499, 1999)
    days = _days(start, count, 30)
    tags = b.series(name, days, [price] * count)
    cancel = days[anchor] + timedelta(days=offset)
    b.context["cancellation_dates"][name] = cancel.isoformat()
    b.label(RECURRING, tags)
    after = [tag for tag, day in zip(tags, days) if day > cancel]
    if after:
        b.label(CANCELLED, after)
    return tags


# --- Zombie cases (design 2.4; REQ-ZS-10, 14, 20, 21, 24) --------------------------------------


def z01_monthly_clear(
    b: Builder, *, name: str | None = None, start: date | None = None, amount: Decimal | None = None
) -> None:
    """Six monthly debits of one amount, 30 days apart."""
    _recurring(b, name, start, amount, count=6, gap=30)


def z02_weekly_clear(
    b: Builder, *, name: str | None = None, start: date | None = None, amount: Decimal | None = None
) -> None:
    """Eight weekly debits."""
    _recurring(b, name, start, amount, count=8, gap=7, description="Weekly plan")


def z03_quarterly_clear(
    b: Builder, *, name: str | None = None, start: date | None = None, amount: Decimal | None = None
) -> None:
    """Three debits 91 days apart."""
    _recurring(b, name, start, amount, count=3, gap=91, description="Quarterly plan")


def z04_annual_pair(
    b: Builder, *, name: str | None = None, start: date | None = None, amount: Decimal | None = None
) -> None:
    """Two yearly charges 365 days apart: a series by REQ-ZS-10 (owner answer, D-BM-07)."""
    _recurring(b, name, start, amount, count=2, gap=365, description="Annual plan")


def z05_monthly_min(
    b: Builder, *, name: str | None = None, start: date | None = None, amount: Decimal | None = None
) -> None:
    """Exactly three monthly charges: the minimum of REQ-ZS-10."""
    _recurring(b, name, start, amount, count=3, gap=30)


def z06_weekly_min(
    b: Builder, *, name: str | None = None, start: date | None = None, amount: Decimal | None = None
) -> None:
    """Exactly four weekly charges: the minimum of REQ-ZS-10."""
    _recurring(b, name, start, amount, count=4, gap=7, description="Weekly plan")


def z07_monthly_gaps_27_33(
    b: Builder, *, name: str | None = None, start: date | None = None, amount: Decimal | None = None
) -> None:
    """Five debits whose gaps alternate 33 and 27 days: inside the 30 +/- 3 tolerance."""
    name = name or b.merchant()
    start = start or b.start(120)
    amount = amount or b.amount(499, 4999)
    days = _days_from_gaps(start, [33, 27, 33, 27])
    b.label(RECURRING, b.series(name, days, [amount] * 5))


def z08_price_clear(
    b: Builder, *, name: str | None = None, start: date | None = None, base: Decimal | None = None
) -> None:
    """Three charges, then three charges 20 % higher."""
    base = base or b.amount(1000, 6000)
    _price_case(b, name, start, base, base + percent_of(base, Decimal("20")), price_label=True)


def z09_price_plus7(
    b: Builder, *, name: str | None = None, start: date | None = None, base: Decimal | None = None
) -> None:
    """Three charges, then three charges 7 % higher (REQ-ZS-14: 7 % or more fires)."""
    base = base or b.amount(1000, 6000)
    _price_case(b, name, start, base, base + percent_of(base, Decimal("7")), price_label=True)


def z10_price_plus5(b: Builder, *, name: str | None = None, start: date | None = None) -> None:
    """3 x 20.00 then 3 x 21.00: exactly +5.00 %, labelled positive (owner answer, D-BM-19)."""
    _price_case(b, name, start, Decimal("20.00"), Decimal("21.00"), price_label=True)


def z11_duplicate_same_key(
    b: Builder, *, name: str | None = None, start: date | None = None, amount: Decimal | None = None
) -> None:
    """Two interleaved monthly series of one counterparty at one amount."""
    name = name or b.merchant()
    amount = amount or b.amount(499, 2999)
    _parallel(b, (name, name), start, (amount, amount), duplicate=True)


def z12_duplicate_alias(
    b: Builder, *, name: str | None = None, start: date | None = None, amount: Decimal | None = None
) -> None:
    """``NAME INTL 4412`` and ``NAMECOM`` at one amount, tied by an alias in the context."""
    stem = name or b.merchant()
    amount = amount or b.amount(499, 2999)
    keys = (f"{stem} INTL", f"{stem}COM")
    b.context["aliases"][stem.lower()] = list(keys)
    _parallel(b, (f"{stem} INTL 4412", f"{stem}COM"), start, (amount, amount), duplicate=True)


def z13_duplicate_within_ratio(
    b: Builder, *, name: str | None = None, start: date | None = None
) -> None:
    """One counterparty, two interleaved series at 10.00 and 10.80 (within 10 %)."""
    name = name or b.merchant()
    _parallel(b, (name, name), start, (Decimal("10.00"), Decimal("10.80")), duplicate=True)


def z14_trial_clear(
    b: Builder,
    *,
    name: str | None = None,
    trial_day: date | None = None,
    price: Decimal | None = None,
) -> None:
    """A 0.49 token 14 days before six monthly charges."""
    _trial_case(b, name, trial_day, price, token=Decimal("0.49"), lead=14, trial_label=True)


def z15_trial_edge(
    b: Builder,
    *,
    name: str | None = None,
    trial_day: date | None = None,
    price: Decimal | None = None,
) -> None:
    """A 1.00 token 35 days before six monthly charges: both limits of REQ-ZS-21."""
    _trial_case(b, name, trial_day, price, token=Decimal("1.00"), lead=35, trial_label=True)


def z16_cancel_clear(
    b: Builder, *, name: str | None = None, start: date | None = None, price: Decimal | None = None
) -> None:
    """Six monthly charges and a cancellation date 10 days after the third."""
    _cancel_case(b, name, start, price, count=6, anchor=2, offset=10)


def z17_cancel_edge(
    b: Builder, *, name: str | None = None, start: date | None = None, price: Decimal | None = None
) -> None:
    """Five monthly charges; the cancellation date is the day before the last charge."""
    _cancel_case(b, name, start, price, count=5, anchor=3, offset=29)


ZOMBIE_CASES: tuple[CaseSpec, ...] = (
    CaseSpec("Z01", "monthly_clear", z01_monthly_clear),
    CaseSpec("Z02", "weekly_clear", z02_weekly_clear),
    CaseSpec("Z03", "quarterly_clear", z03_quarterly_clear),
    CaseSpec("Z04", "annual_pair", z04_annual_pair),
    CaseSpec("Z05", "monthly_min", z05_monthly_min),
    CaseSpec("Z06", "weekly_min", z06_weekly_min),
    CaseSpec("Z07", "monthly_gaps_27_33", z07_monthly_gaps_27_33),
    CaseSpec("Z08", "price_clear", z08_price_clear),
    CaseSpec("Z09", "price_plus7", z09_price_plus7),
    CaseSpec("Z10", "price_plus5", z10_price_plus5),
    CaseSpec("Z11", "duplicate_same_key", z11_duplicate_same_key),
    CaseSpec("Z12", "duplicate_alias", z12_duplicate_alias),
    CaseSpec("Z13", "duplicate_within_ratio", z13_duplicate_within_ratio),
    CaseSpec("Z14", "trial_clear", z14_trial_clear),
    CaseSpec("Z15", "trial_edge", z15_trial_edge),
    CaseSpec("Z16", "cancel_clear", z16_cancel_clear),
    CaseSpec("Z17", "cancel_edge", z17_cancel_edge),
)


# --- Zombie hard negatives (design 2.5) --------------------------------------------------------


def nz01_weekly_groceries(
    b: Builder, *, name: str | None = None, start: date | None = None
) -> None:
    """26 weekly debits at one shop, amounts drawn once between 15.00 and 120.00."""
    name = name or b.merchant()
    start = start or b.start(25 * 7)
    amounts = [b.amount(1500, 12000) for _ in range(26)]
    tags = b.series(name, _days(start, 26, 7), amounts, "Groceries")
    b.negative("weekly_groceries_irregular", tags)


def nz02_fuel(b: Builder, *, name: str | None = None, start: date | None = None) -> None:
    """20 debits at one station, 5 to 12 days apart, amounts between 20.00 and 75.00."""
    name = name or b.merchant()
    gaps = [b.rng.randint(5, 12) for _ in range(19)]
    start = start or b.start(sum(gaps))
    amounts = [b.amount(2000, 7500) for _ in range(20)]
    tags = b.series(name, _days_from_gaps(start, gaps), amounts, "Fuel")
    b.negative("fuel_irregular", tags)


def nz03_single_annual(b: Builder, *, name: str | None = None, day: date | None = None) -> None:
    """One annual charge of 99.00 and nothing else from the merchant."""
    name = name or b.merchant()
    day = day or b.start(0)
    tag = b.debit(day, Decimal("99.00"), name, "Annual plan")
    b.negative("single_annual_charge", [tag])


def nz04_one_off_price_change(
    b: Builder, *, name: str | None = None, start: date | None = None
) -> None:
    """Two purchases at one shop 120 days apart: 129.00, then 149.00."""
    name = name or b.merchant()
    start = start or b.start(120)
    tags = [
        b.debit(start, Decimal("129.00"), name, "Purchase"),
        b.debit(start + timedelta(days=120), Decimal("149.00"), name, "Purchase"),
    ]
    b.negative("one_off_price_change", tags)


def nz05_salary(b: Builder, *, name: str | None = None, start: date | None = None) -> None:
    """Six monthly credits of one amount from one employer."""
    name = name or b.merchant()
    start = start or b.start(150)
    amount = b.amount(150_000, 320_000)
    tags = [b.credit(day, amount, name, "Payroll") for day in _days(start, 6, 30)]
    b.negative("salary_credits", tags)


def nz06_refunds(b: Builder) -> None:
    """Two or three one-off credits from shops."""
    tags = [
        b.credit(b.start(0), b.amount(500, 6000), b.merchant(), "Refund")
        for _ in range(b.rng.randint(2, 3))
    ]
    b.negative("refunds", tags)


def nz07_two_charges_only(
    b: Builder, *, name: str | None = None, start: date | None = None
) -> None:
    """Exactly two monthly debits: below the minimum of three (REQ-ZS-10)."""
    name = name or b.merchant()
    start = start or b.start(30)
    amount = b.amount(499, 4999)
    tags = b.series(name, _days(start, 2, 30), [amount] * 2)
    b.negative("two_charges_only", tags)


def nz08_gap_34_days(b: Builder, *, name: str | None = None, start: date | None = None) -> None:
    """Four debits 34 days apart: outside 30 +/- 3 and not quarterly."""
    name = name or b.merchant()
    start = start or b.start(102)
    amount = b.amount(499, 4999)
    tags = b.series(name, _days(start, 4, 34), [amount] * 4)
    b.negative("gap_34_days", tags)


def nz09_price_below_threshold(
    b: Builder, *, name: str | None = None, start: date | None = None
) -> None:
    """100.00 four times, then 103.90 twice (+3.90 %): a series, no price step."""
    tags = _price_case(
        b, name, start, Decimal("100.00"), Decimal("103.90"), price_label=False, counts=(4, 2)
    )
    b.negative("price_below_threshold", tags)


def nz10_price_decrease(b: Builder, *, name: str | None = None, start: date | None = None) -> None:
    """15.99 three times, then 12.99 three times: a decrease is not an increase."""
    tags = _price_case(b, name, start, Decimal("15.99"), Decimal("12.99"), price_label=False)
    b.negative("price_decrease", tags)


def nz11_trial_too_early(
    b: Builder, *, name: str | None = None, trial_day: date | None = None
) -> None:
    """A 1.00 token 36 days before a six-charge series: one day too early."""
    tags = _trial_case(b, name, trial_day, None, token=Decimal("1.00"), lead=36, trial_label=False)
    b.negative("trial_too_early", tags)


def nz12_trial_amount_above(
    b: Builder, *, name: str | None = None, trial_day: date | None = None
) -> None:
    """A 1.01 token 14 days before a six-charge series: one cent too high."""
    tags = _trial_case(b, name, trial_day, None, token=Decimal("1.01"), lead=14, trial_label=False)
    b.negative("trial_amount_above", tags)


def nz13_cancel_same_day(
    b: Builder, *, name: str | None = None, start: date | None = None, price: Decimal | None = None
) -> None:
    """The cancellation date is the date of the last charge: not strictly after it."""
    tags = _cancel_case(b, name, start, price, count=5, anchor=4, offset=0)
    b.negative("cancel_same_day", tags)


def nz14_parallel_amounts_differ(
    b: Builder, *, name: str | None = None, start: date | None = None
) -> None:
    """One counterparty, two interleaved series at 10.00 and 11.50 (more than 10 % apart)."""
    name = name or b.merchant()
    tags = _parallel(b, (name, name), start, (Decimal("10.00"), Decimal("11.50")), duplicate=False)
    b.negative("parallel_amounts_differ", tags)


ZOMBIE_NEGATIVES: tuple[CaseSpec, ...] = (
    CaseSpec("NZ01", "weekly_groceries_irregular", nz01_weekly_groceries, True),
    CaseSpec("NZ02", "fuel_irregular", nz02_fuel, True),
    CaseSpec("NZ03", "single_annual_charge", nz03_single_annual, True),
    CaseSpec("NZ04", "one_off_price_change", nz04_one_off_price_change, True),
    CaseSpec("NZ05", "salary_credits", nz05_salary, True),
    CaseSpec("NZ06", "refunds", nz06_refunds, True),
    CaseSpec("NZ07", "two_charges_only", nz07_two_charges_only, True),
    CaseSpec("NZ08", "gap_34_days", nz08_gap_34_days, True),
    CaseSpec("NZ09", "price_below_threshold", nz09_price_below_threshold),
    CaseSpec("NZ10", "price_decrease", nz10_price_decrease),
    CaseSpec("NZ11", "trial_too_early", nz11_trial_too_early),
    CaseSpec("NZ12", "trial_amount_above", nz12_trial_amount_above),
    CaseSpec("NZ13", "cancel_same_day", nz13_cancel_same_day),
    CaseSpec("NZ14", "parallel_amounts_differ", nz14_parallel_amounts_differ),
)


def zombie_noise(b: Builder) -> None:
    """15 to 40 one-off purchases, each at a merchant used once, and 2 to 4 transfers."""
    for _ in range(b.rng.randint(15, 40)):
        day = ZOMBIE_START + timedelta(days=b.rng.randrange(ZOMBIE_DAYS))
        b.debit(day, b.amount(500, 9000), b.merchant(), "Purchase")
    for person in b.rng.sample(PERSONS, b.rng.randint(2, 4)):
        day = ZOMBIE_START + timedelta(days=b.rng.randrange(ZOMBIE_DAYS))
        b.debit(day, b.amount(2000, 30000), person, "Transfer")


# --- Phantom helpers ---------------------------------------------------------------------------

RATE_21 = Decimal("21")


def _pair_of_invoices(
    b: Builder,
    sup: Supplier | None,
    issue: date | None,
    base: Decimal | None,
    numbers: tuple[str, str] | None,
    *,
    gap: int,
    reserve_extra: int = 0,
    second_total: Decimal | None = None,
) -> tuple[Supplier, list[str]]:
    """Two paid invoices of one supplier, ``gap`` days apart; return the supplier and tags.

    By default both carry the same total; ``second_total`` overrides the total of the second one
    (VAT and base stay equal, so the difference must stay inside the VAT-error tolerance).
    """
    sup = sup or b.supplier()
    issue = issue or b.issue_date(PAYMENT_RESERVE_DAYS + gap + reserve_extra)
    base = base or b.amount(8000, 180_000)
    first, second = numbers or (b.number(sup), b.number(sup))
    tag_a, _pay_a = b.invoice(sup, first, issue, base, RATE_21)
    tag_b, _pay_b = b.invoice(
        sup, second, issue + timedelta(days=gap), base, RATE_21, total=second_total
    )
    return sup, [tag_a, tag_b]


def _single(
    b: Builder,
    sup: Supplier | None,
    issue: date | None,
    base: Decimal | None,
    rate: Decimal,
    *,
    vat: Decimal | None = None,
    total: Decimal | None = None,
    rate_text: str | None = None,
) -> tuple[Supplier, str]:
    """One paid invoice with the given (possibly wrong) VAT amount and total."""
    sup = sup or b.supplier()
    issue = issue or b.issue_date()
    base = base or b.amount(8000, 180_000)
    tag, _pay = b.invoice(
        sup, b.number(sup), issue, base, rate, vat=vat, total=total, rate_text=rate_text
    )
    return sup, tag


def _unpaid(
    b: Builder,
    sup: Supplier | None,
    base: Decimal | None,
    *,
    days_after_due: int,
) -> str:
    """One unpaid invoice whose due date is ``days_after_due`` days before ``as_of``."""
    assert b.as_of is not None
    sup = sup or b.supplier()
    base = base or b.amount(8000, 180_000)
    due = b.as_of - timedelta(days=days_after_due)
    issue = due - timedelta(days=TERM_DAYS)
    tag, _pay = b.invoice(sup, b.number(sup), issue, base, RATE_21, paid=False)
    return tag


# --- Phantom cases (design 2.4; REQ-PI-18, 21, 24, 31, 33, 37, 38) -----------------------------


def p01_dup_same_number_clear(
    b: Builder,
    *,
    sup: Supplier | None = None,
    issue: date | None = None,
    base: Decimal | None = None,
) -> None:
    """The same supplier and number twice, 2 days apart, equal totals; both paid."""
    sup = sup or b.supplier()
    number = b.number(sup)
    _sup, tags = _pair_of_invoices(b, sup, issue, base, (number, number), gap=2)
    b.label(SAME_NUMBER, tags)


def p02_dup_same_number_179(
    b: Builder,
    *,
    sup: Supplier | None = None,
    issue: date | None = None,
    base: Decimal | None = None,
) -> None:
    """The same number 179 days apart: still inside the window of REQ-PI-18."""
    sup = sup or b.supplier()
    number = b.number(sup)
    _sup, tags = _pair_of_invoices(b, sup, issue, base, (number, number), gap=179)
    b.label(SAME_NUMBER, tags)


def p03_dup_near_identical(
    b: Builder,
    *,
    sup: Supplier | None = None,
    issue: date | None = None,
    base: Decimal | None = None,
    numbers: tuple[str, str] | None = None,
) -> None:
    """``F-2026-0042`` and ``F2026-042``: equal once leading zeros go, 20 days apart."""
    sup = sup or b.supplier()
    n = b.rng.randint(1, 899)
    numbers = numbers or (f"{sup.prefix}-2026-{n:04d}", f"{sup.prefix}2026-{n:03d}")
    _sup, tags = _pair_of_invoices(b, sup, issue, base, numbers, gap=20)
    b.label(NEAR_NUMBER, tags)


def p04_dup_total_6_days(
    b: Builder,
    *,
    sup: Supplier | None = None,
    issue: date | None = None,
    base: Decimal | None = None,
    numbers: tuple[str, str] | None = None,
) -> None:
    """Different numbers, the same total, 6 days apart (REQ-PI-21: under 7 days)."""
    sup = sup or b.supplier()
    n = b.rng.randint(1, 898)
    numbers = numbers or (f"{sup.prefix}-{n:04d}", f"{sup.prefix}-{n + 1:04d}")
    _sup, tags = _pair_of_invoices(b, sup, issue, base, numbers, gap=6)
    b.label(SAME_TOTAL, tags)


def p05_iban_invoice_differs(
    b: Builder,
    *,
    sup: Supplier | None = None,
    issue: date | None = None,
    base: Decimal | None = None,
) -> None:
    """The invoice names another valid account; the payment goes to the master account."""
    sup = sup or b.supplier()
    other = format_iban(b.new_iban())
    tag, _pay = b.invoice(
        sup,
        b.number(sup),
        issue or b.issue_date(),
        base or b.amount(8000, 180_000),
        RATE_21,
        iban=other,
    )
    b.label(IBAN_DIFFERS, [tag], [sup.master_tag])


def p06_iban_payment_non_master(
    b: Builder,
    *,
    sup: Supplier | None = None,
    issue: date | None = None,
    base: Decimal | None = None,
) -> None:
    """A normal invoice; the payment carries the supplier's name but another valid account."""
    sup = sup or b.supplier()
    _tag, pay = b.invoice(
        sup,
        b.number(sup),
        issue or b.issue_date(),
        base or b.amount(8000, 180_000),
        RATE_21,
        pay_iban=format_iban(b.new_iban()),
    )
    assert pay is not None
    b.label(PAYMENT_ELSEWHERE, [pay], [sup.master_tag])


def p07_iban_invalid_format(
    b: Builder,
    *,
    sup: Supplier | None = None,
    issue: date | None = None,
    base: Decimal | None = None,
) -> None:
    """The invoice IBAN is written with hyphens: malformed (REQ-PI-23)."""
    sup = sup or b.supplier()
    tag, _pay = b.invoice(
        sup,
        b.number(sup),
        issue or b.issue_date(),
        base or b.amount(8000, 180_000),
        RATE_21,
        iban=hyphenate_iban(sup.iban),
    )
    b.label(IBAN_BAD, [tag])


def p08_iban_invalid_checksum(
    b: Builder,
    *,
    sup: Supplier | None = None,
    issue: date | None = None,
    base: Decimal | None = None,
) -> None:
    """The invoice IBAN is well formed but its mod-97 check fails."""
    sup = sup or b.supplier()
    tag, _pay = b.invoice(
        sup,
        b.number(sup),
        issue or b.issue_date(),
        base or b.amount(8000, 180_000),
        RATE_21,
        iban=format_iban(break_checksum(sup.iban)),
    )
    b.label(IBAN_BAD, [tag])


def p09_iban_invalid_master(b: Builder, *, sup: Supplier | None = None) -> None:
    """The supplier master holds an IBAN whose mod-97 check fails; no invoice, no payment."""
    if sup is None:
        compact = b.new_iban()
        sup = b.supplier(iban=compact, master_text=format_iban(break_checksum(compact)))
    b.label(IBAN_BAD, [sup.master_tag])


def p10a_vat_clear(
    b: Builder,
    *,
    sup: Supplier | None = None,
    issue: date | None = None,
    base: Decimal | None = None,
) -> None:
    """Stated VAT is 12.1 % of the base instead of 21 %; the total follows the stated VAT."""
    base = base or b.amount(10_000, 180_000)
    vat = percent_of(base, Decimal("12.1"))
    _sup, tag = _single(b, sup, issue, base, RATE_21, vat=vat, total=net_total([base, vat]))
    b.label(VAT_WRONG, [tag])


def p10b_vat_off_2_cents(
    b: Builder,
    *,
    sup: Supplier | None = None,
    issue: date | None = None,
    base: Decimal | None = None,
) -> None:
    """Stated VAT is 0.02 above the correct amount; the total follows the stated VAT."""
    base = base or b.amount(8000, 180_000)
    vat = percent_of(base, RATE_21) + Decimal("0.02")
    _sup, tag = _single(b, sup, issue, base, RATE_21, vat=vat, total=net_total([base, vat]))
    b.label(VAT_WRONG, [tag])


def p11a_total_clear(
    b: Builder,
    *,
    sup: Supplier | None = None,
    issue: date | None = None,
    base: Decimal | None = None,
) -> None:
    """The stated total is 10.00 above base plus VAT."""
    base = base or b.amount(8000, 180_000)
    total = net_total([base, percent_of(base, RATE_21), Decimal("10.00")])
    _sup, tag = _single(b, sup, issue, base, RATE_21, total=total)
    b.label(TOTAL_WRONG, [tag])


def p11b_total_off_2_cents(
    b: Builder,
    *,
    sup: Supplier | None = None,
    issue: date | None = None,
    base: Decimal | None = None,
) -> None:
    """The stated total is 0.02 above base plus VAT."""
    base = base or b.amount(8000, 180_000)
    total = net_total([base, percent_of(base, RATE_21), Decimal("0.02")])
    _sup, tag = _single(b, sup, issue, base, RATE_21, total=total)
    b.label(TOTAL_WRONG, [tag])


def p12_rate_not_allowed(
    b: Builder,
    *,
    sup: Supplier | None = None,
    issue: date | None = None,
    base: Decimal | None = None,
) -> None:
    """Rate 20: VAT and total are consistent with it, but 20 is not an allowed rate."""
    _sup, tag = _single(b, sup, issue, base, Decimal("20"))
    b.label(RATE_WRONG, [tag])


def p13_overdue_clear(
    b: Builder, *, sup: Supplier | None = None, base: Decimal | None = None
) -> None:
    """An unpaid invoice 40 days past its due date."""
    b.label(LATE, [_unpaid(b, sup, base, days_after_due=40)])


def p14_overdue_16(b: Builder, *, sup: Supplier | None = None, base: Decimal | None = None) -> None:
    """An unpaid invoice 16 days past its due date: the first day over the limit."""
    b.label(LATE, [_unpaid(b, sup, base, days_after_due=16)])


def p15_payment_without_invoice(
    b: Builder,
    *,
    sup: Supplier | None = None,
    day: date | None = None,
    amount: Decimal | None = None,
) -> None:
    """A debit to a master supplier's name and account with no invoice."""
    assert b.as_of is not None
    sup = sup or b.supplier()
    day = day or PHANTOM_START + timedelta(days=b.rng.randrange((b.as_of - PHANTOM_START).days))
    tag = b.payment(day, amount or b.amount(5000, 200_000), sup.name, sup.iban_text)
    b.label(NO_INVOICE, [tag])


PHANTOM_CASES: tuple[CaseSpec, ...] = (
    CaseSpec("P01", "dup_same_number_clear", p01_dup_same_number_clear),
    CaseSpec("P02", "dup_same_number_179", p02_dup_same_number_179),
    CaseSpec("P03", "dup_near_identical", p03_dup_near_identical),
    CaseSpec("P04", "dup_total_6_days", p04_dup_total_6_days),
    CaseSpec("P05", "iban_invoice_differs", p05_iban_invoice_differs),
    CaseSpec("P06", "iban_payment_non_master", p06_iban_payment_non_master),
    CaseSpec("P07", "iban_invalid_format", p07_iban_invalid_format),
    CaseSpec("P08", "iban_invalid_checksum", p08_iban_invalid_checksum),
    CaseSpec("P09", "iban_invalid_master", p09_iban_invalid_master),
    CaseSpec("P10a", "vat_clear", p10a_vat_clear),
    CaseSpec("P10b", "vat_off_2_cents", p10b_vat_off_2_cents),
    CaseSpec("P11a", "total_clear", p11a_total_clear),
    CaseSpec("P11b", "total_off_2_cents", p11b_total_off_2_cents),
    CaseSpec("P12", "rate_not_allowed", p12_rate_not_allowed),
    CaseSpec("P13", "overdue_clear", p13_overdue_clear),
    CaseSpec("P14", "overdue_16", p14_overdue_16),
    CaseSpec("P15", "payment_without_invoice", p15_payment_without_invoice),
)


# --- Phantom hard negatives (design 2.5): all label-free ---------------------------------------


def np01_same_number_two_suppliers(
    b: Builder, *, issue: date | None = None, number: str | None = None
) -> None:
    """Two suppliers use the same invoice number in the same month; each is paid."""
    issue = issue or b.issue_date()
    number = number or f"INV-{b.rng.randint(1, 899):04d}"
    first, second = b.supplier(), b.supplier()
    tag_a, _ = b.invoice(first, number, issue, b.amount(8000, 180_000), RATE_21)
    day = issue + timedelta(days=b.rng.randint(0, 3))
    tag_b, _ = b.invoice(second, number, day, b.amount(8000, 180_000), RATE_21)
    b.negative("same_number_two_suppliers", [tag_a, tag_b])


def np02_same_amount_other_months(
    b: Builder, *, sup: Supplier | None = None, issue: date | None = None
) -> None:
    """One supplier bills the same total twice, 28 to 35 days apart; each is paid."""
    sup = sup or b.supplier()
    gap = b.rng.randint(28, 35)
    issue = issue or b.issue_date(PAYMENT_RESERVE_DAYS + gap)
    base = b.amount(8000, 180_000)
    tag_a, _ = b.invoice(sup, f"{sup.prefix}-01", issue, base, RATE_21)
    tag_b, _ = b.invoice(sup, f"{sup.prefix}-02", issue + timedelta(days=gap), base, RATE_21)
    b.negative("same_amount_other_months", [tag_a, tag_b])


def np03_two_legit_ibans(
    b: Builder, *, sup: Supplier | None = None, issue: date | None = None
) -> None:
    """The master holds two valid accounts of one supplier; invoices use the second one."""
    sup = sup or b.supplier()
    second = b.new_iban()
    second_tag = b.master_row(sup.name, sup.tax_id, format_iban(second))
    issue = issue or b.issue_date(PAYMENT_RESERVE_DAYS + 30)
    tags = []
    for k in range(2):
        tag, pay = b.invoice(
            sup,
            f"{sup.prefix}-{k + 1:04d}",
            issue + timedelta(days=30 * k),
            b.amount(8000, 180_000),
            RATE_21,
            iban=format_iban(second),
            pay_iban=format_iban(second),
        )
        tags.append(tag)
        assert pay is not None
        tags.append(pay)
    b.negative("two_legit_ibans", [sup.master_tag, second_tag, *tags])


def np04_paid_late_in_full(
    b: Builder, *, sup: Supplier | None = None, issue: date | None = None
) -> None:
    """Paid in full 30 days after the due date."""
    sup = sup or b.supplier()
    issue = issue or b.issue_date(PAYMENT_RESERVE_DAYS + 20)
    tag, pay = b.invoice(
        sup, b.number(sup), issue, b.amount(8000, 180_000), RATE_21, pay_days=TERM_DAYS + 30
    )
    assert pay is not None
    b.negative("paid_late_in_full", [tag, pay])


def np05_paid_on_last_matching_day(
    b: Builder, *, sup: Supplier | None = None, issue: date | None = None
) -> None:
    """Paid exactly 60 days after the due date (REQ-PI-37)."""
    sup = sup or b.supplier()
    issue = issue or b.issue_date(PAYMENT_RESERVE_DAYS + 50)
    tag, pay = b.invoice(
        sup, b.number(sup), issue, b.amount(8000, 180_000), RATE_21, pay_days=TERM_DAYS + 60
    )
    assert pay is not None
    b.negative("paid_on_last_matching_day", [tag, pay])


def np06_rounding_half_cent(
    b: Builder, *, sup: Supplier | None = None, issue: date | None = None
) -> None:
    """The seven invoices of the golden rounding table, each paid; one rate is written 21.00."""
    sup = sup or b.supplier()
    issue = issue or b.issue_date(PAYMENT_RESERVE_DAYS + 60)
    tags: list[str] = []
    for k, (base, rate, vat, total) in enumerate(ROUNDING_TABLE):
        tag, pay = b.invoice(
            sup,
            f"{sup.prefix}-{k + 1:04d}",
            issue + timedelta(days=10 * k),
            Decimal(base),
            Decimal(rate),
            vat=Decimal(vat),
            total=Decimal(total),
            rate_text=rate,
        )
        assert pay is not None
        tags += [tag, pay]
    b.negative("rounding_half_cent", tags)


def np07_numbering_restart_180(
    b: Builder, *, sup: Supplier | None = None, issue: date | None = None
) -> None:
    """The same number 180 days apart (an annual restart); both paid."""
    sup = sup or b.supplier()
    number = b.number(sup)
    _sup, tags = _pair_of_invoices(b, sup, issue, None, (number, number), gap=180)
    b.negative("numbering_restart_180", tags)


def np08_same_total_7_days_apart(
    b: Builder,
    *,
    sup: Supplier | None = None,
    issue: date | None = None,
    base: Decimal | None = None,
    numbers: tuple[str, str] | None = None,
) -> None:
    """Different numbers, the same total, 7 days apart (REQ-PI-21: not under 7); both paid."""
    sup = sup or b.supplier()
    n = b.rng.randint(1, 898)
    numbers = numbers or (f"{sup.prefix}-{n:04d}", f"{sup.prefix}-{n + 1:04d}")
    _sup, tags = _pair_of_invoices(b, sup, issue, base, numbers, gap=7)
    b.negative("same_total_7_days_apart", tags)


def np09_vat_off_by_one_cent(
    b: Builder,
    *,
    sup: Supplier | None = None,
    issue: date | None = None,
    base: Decimal | None = None,
) -> None:
    """VAT and total are 0.01 above the correct amounts: inside the tolerance."""
    base = base or b.amount(8000, 180_000)
    vat = percent_of(base, RATE_21) + Decimal("0.01")
    _sup, tag = _single(b, sup, issue, base, RATE_21, vat=vat, total=net_total([base, vat]))
    b.negative("vat_off_by_one_cent", [tag])


def np10_open_at_due_plus_15(b: Builder, *, sup: Supplier | None = None) -> None:
    """An unpaid invoice exactly 15 days past its due date: not yet overdue."""
    b.negative("open_at_due_plus_15", [_unpaid(b, sup, None, days_after_due=15)])


def np11_near_number_totals_differ(
    b: Builder,
    *,
    sup: Supplier | None = None,
    issue: date | None = None,
    base: Decimal | None = None,
    numbers: tuple[str, str] | None = None,
) -> None:
    """``F-2026-0042`` and ``F2026-042`` with totals 0.01 apart; both paid."""
    sup = sup or b.supplier()
    base = base or b.amount(8000, 180_000)
    n = b.rng.randint(1, 899)
    numbers = numbers or (f"{sup.prefix}-2026-{n:04d}", f"{sup.prefix}2026-{n:03d}")
    total = round_to_cents(net_total([base, percent_of(base, RATE_21)]))
    _sup, tags = _pair_of_invoices(
        b, sup, issue, base, numbers, gap=20, second_total=total + Decimal("0.01")
    )
    b.negative("near_number_totals_differ", tags)


def np12_iban_spelling_variant(
    b: Builder, *, sup: Supplier | None = None, issue: date | None = None
) -> None:
    """The invoice IBAN is the master IBAN in lower case with spaces."""
    sup = sup or b.supplier()
    tag, pay = b.invoice(
        sup,
        b.number(sup),
        issue or b.issue_date(),
        b.amount(8000, 180_000),
        RATE_21,
        iban=sup.iban_text.lower(),
    )
    assert pay is not None
    b.negative("iban_spelling_variant", [tag, pay])


def np13_non_supplier_payments(b: Builder) -> None:
    """A customer credit and debits to people who are not suppliers, on other accounts."""
    assert b.as_of is not None
    span = (b.as_of - PHANTOM_START).days
    tags = [
        b.bank_row(
            "payments.csv",
            PHANTOM_START + timedelta(days=b.rng.randrange(span)),
            b.amount(10_000, 300_000),
            "Cliente Alfa Obras",
            "Customer payment",
            format_iban(b.new_iban()),
        )
    ]
    for person in b.rng.sample(PERSONS, b.rng.randint(1, 2)):
        tags.append(
            b.bank_row(
                "payments.csv",
                PHANTOM_START + timedelta(days=b.rng.randrange(span)),
                -b.amount(2000, 50_000),
                person,
                "Transfer",
                format_iban(b.new_iban()),
            )
        )
    b.negative("non_supplier_payments", tags)


def np14_missing_iban(
    b: Builder, *, sup: Supplier | None = None, issue: date | None = None
) -> None:
    """An invoice without an IBAN, paid normally."""
    sup = sup or b.supplier()
    tag, pay = b.invoice(
        sup, b.number(sup), issue or b.issue_date(), b.amount(8000, 180_000), RATE_21, iban=""
    )
    assert pay is not None
    b.negative("missing_iban", [tag, pay])


PHANTOM_NEGATIVES: tuple[CaseSpec, ...] = (
    CaseSpec("NP01", "same_number_two_suppliers", np01_same_number_two_suppliers, True),
    CaseSpec("NP02", "same_amount_other_months", np02_same_amount_other_months, True),
    CaseSpec("NP03", "two_legit_ibans", np03_two_legit_ibans, True),
    CaseSpec("NP04", "paid_late_in_full", np04_paid_late_in_full, True),
    CaseSpec("NP05", "paid_on_last_matching_day", np05_paid_on_last_matching_day, True),
    CaseSpec("NP06", "rounding_half_cent", np06_rounding_half_cent, True),
    CaseSpec("NP07", "numbering_restart_180", np07_numbering_restart_180, True),
    CaseSpec("NP08", "same_total_7_days_apart", np08_same_total_7_days_apart, True),
    CaseSpec("NP09", "vat_off_by_one_cent", np09_vat_off_by_one_cent, True),
    CaseSpec("NP10", "open_at_due_plus_15", np10_open_at_due_plus_15, True),
    CaseSpec("NP11", "near_number_totals_differ", np11_near_number_totals_differ, True),
    CaseSpec("NP12", "iban_spelling_variant", np12_iban_spelling_variant, True),
    CaseSpec("NP13", "non_supplier_payments", np13_non_supplier_payments, True),
    CaseSpec("NP14", "missing_iban", np14_missing_iban, True),
)


def phantom_noise(b: Builder) -> None:
    """2 to 5 clean suppliers with 3 to 5 monthly invoices each, all paid in full."""
    for _ in range(b.rng.randint(2, 5)):
        sup = b.supplier()
        count = b.rng.randint(3, 5)
        first = b.issue_date(PAYMENT_RESERVE_DAYS + 30 * (count - 1))
        for k in range(count):
            b.invoice(
                sup,
                f"{sup.prefix}-{k + 1:04d}",
                first + timedelta(days=30 * k),
                b.amount(8000, 180_000),
                Decimal(b.rng.choice(RATE_CHOICES)),
            )


# --- Catalogue and schedule --------------------------------------------------------------------

CATALOGUE: Mapping[str, tuple[tuple[CaseSpec, ...], tuple[CaseSpec, ...]]] = {
    "zombie": (ZOMBIE_CASES, ZOMBIE_NEGATIVES),
    "phantom": (PHANTOM_CASES, PHANTOM_NEGATIVES),
}


def build_scenario(seed: int, app: str, index: int) -> Scenario:
    """Build scenario ``index`` of ``app``; it depends on ``(seed, app, index)`` only."""
    builder = Builder(app, index, seed)
    cases, negatives = CATALOGUE[app]
    if builder.noise_only:
        free = [spec for spec in negatives if spec.label_free]
        q = index // NOISE_ONLY_EVERY
        for j in range(NOISE_ONLY_NEGATIVES):
            free[(NOISE_ONLY_NEGATIVES * q + j) % len(free)].run(builder)
    else:
        p = index - index // NOISE_ONLY_EVERY - 1
        for j in range(CASES_PER_SCENARIO):
            cases[(CASES_PER_SCENARIO * p + j) % len(cases)].run(builder)
        for j in range(NEGATIVES_PER_SCENARIO):
            negatives[(NEGATIVES_PER_SCENARIO * p + j) % len(negatives)].run(builder)
    if app == "zombie":
        zombie_noise(builder)
    else:
        phantom_noise(builder)
    return builder.scenario()


def build_scenarios(seed: int, app: str, count: int) -> list[Scenario]:
    """Build scenarios ``0 .. count - 1`` of ``app``."""
    return [build_scenario(seed, app, index) for index in range(count)]
