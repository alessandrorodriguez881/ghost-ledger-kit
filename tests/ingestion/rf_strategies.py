"""Hypothesis strategies and builders for the real-formats properties (RF8, design 9.1).

The writers live in scripts/generate_samples.py and are loaded by path (scripts/ is not a
package). Every text, name, tax id and IBAN here is synthetic (Finance Rule 5).

Two limits are deliberate and documented:

* Texts use ASCII punctuation, letters and digits plus the Latin-1 letters U+00C0..U+00FF. The
  characters U+0080..U+00BF are left out because, as ISO-8859-1 bytes, they are UTF-8
  continuation bytes: a Latin-1 file could then happen to be valid UTF-8 and the reader's
  "UTF-8, else Latin-1" rule (DN-RF-02) would decode it the other way.
* Amounts stay below 100 000 000 000,00 and a file has at most eight rows, so the 14-digit
  totals of a record 33 can hold the sums.
"""

from __future__ import annotations

import importlib.util
import string
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from hypothesis import strategies as st

from ledger_kit.utils.money import net_total, percent_of

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "generate_samples.py"


def _load_generator() -> Any:
    """Load scripts/generate_samples.py by path (scripts/ is not a package)."""
    spec = importlib.util.spec_from_file_location("generate_samples_rf8", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["generate_samples_rf8"] = module
    spec.loader.exec_module(module)
    return module


generator = _load_generator()

FIRST_DAY = date(2000, 1, 1)
LAST_DAY = date(2099, 12, 31)
# Series are planted up to 150 days after their first charge, so they start a little earlier.
LAST_SERIES_START = date(2098, 12, 31)
CENTS_LIMIT = 10**13  # amounts up to 99 999 999 999,99
SERIES_CENTS_LIMIT = 10**6  # planted subscription charges up to 10 000,00
MAX_ROWS = 8
INVOICE_CENTS_LIMIT = 10**11  # base amounts up to 1 000 000 000,00
MAX_INVOICES = 5
MONTH_DAYS = 30
ASCII_SYMBOLS = "".join(chr(code) for code in range(0x21, 0x7F))  # printable, no blank
LATIN1_LETTERS = "".join(chr(code) for code in range(0xC0, 0x100))
WORD_ALPHABET = ASCII_SYMBOLS + LATIN1_LETTERS
NUMBER_ALPHABET = string.ascii_letters + string.digits + "-/."
VAT_RATES = ["0", "4", "5.2", "10", "21"]
SURCHARGE_RATES = ["0.5", "1.4", "5.2"]
WITHHOLDING_RATES = ["7", "15", "19"]
ENCODINGS = ["latin-1", "utf-8", "utf-8-sig"]
LINE_ENDINGS = ["\r\n", "\n", "\r"]


def cents_text(cents: int) -> str:
    """Write a non-negative number of cents as an amount with two decimals."""
    return f"{cents // 100}.{cents % 100:02d}"


def _not_iban(text: str) -> bool:
    """True unless the text would be read as the counterparty IBAN record of a Norma 43 file."""
    return not text.startswith("IBAN ")


def _signed(pair: tuple[bool, str]) -> str:
    """Prefix an amount text with '-' when the flag is set (a debit)."""
    negative, amount = pair
    return ("-" if negative else "") + amount


# --- texts, amounts, dates ---------------------------------------------------------------------
words = st.text(alphabet=WORD_ALPHABET, min_size=1, max_size=12)
texts = st.lists(words, min_size=1, max_size=4).map(" ".join).filter(_not_iban)
person_names = st.lists(words, min_size=2, max_size=4).map(" ".join)
invoice_numbers = st.text(alphabet=NUMBER_ALPHABET, min_size=1, max_size=20)
tax_ids = st.from_regex(r"[A-Z][0-9]{8}", fullmatch=True)
days = st.dates(min_value=FIRST_DAY, max_value=LAST_DAY)
amounts = st.integers(min_value=0, max_value=CENTS_LIMIT - 1).map(cents_text)
signed_amounts = st.tuples(st.booleans(), amounts).map(_signed)
ibans = st.one_of(
    st.just(""),
    st.from_regex(r"[A-Z]{2}[0-9]{2}( [A-Z0-9]{4}){1,6}", fullmatch=True),
)

# --- Norma 43 ----------------------------------------------------------------------------------
bank_rows = st.builds(
    generator.BankRow,
    day=days,
    amount=signed_amounts,
    counterparty=texts,
    description=texts,
    iban=ibans,
)
statements = st.lists(bank_rows, min_size=1, max_size=MAX_ROWS)


@st.composite
def subscription_statements(draw: st.DrawFn) -> list[Any]:
    """Rows with planted monthly series (so detectors have something to find) plus noise."""
    rows: list[Any] = []
    for _ in range(draw(st.integers(min_value=1, max_value=3))):
        counterparty = draw(texts)
        cents = draw(st.integers(min_value=1, max_value=SERIES_CENTS_LIMIT))
        start = draw(st.dates(min_value=FIRST_DAY, max_value=LAST_SERIES_START))
        for month in range(draw(st.integers(min_value=3, max_value=6))):
            day = start + timedelta(days=MONTH_DAYS * month)
            amount = "-" + cents_text(cents)
            rows.append(generator.BankRow(day, amount, counterparty, "Monthly subscription", ""))
    rows.extend(draw(st.lists(bank_rows, max_size=6)))
    return rows


@dataclass(frozen=True)
class Layout:
    """How a Norma 43 file is laid out on disk: line ending, trailing blanks, encoding."""

    eol: str
    strip: bool
    final_eol: bool
    encoding: str


layouts = st.builds(
    Layout,
    eol=st.sampled_from(LINE_ENDINGS),
    strip=st.booleans(),
    final_eol=st.booleans(),
    encoding=st.sampled_from(ENCODINGS),
)


def render_with_layout(lines: list[str], layout: Layout) -> bytes:
    """Join 80-character records with the layout's line ending, blanks and encoding."""
    rendered = [line.rstrip(" ") if layout.strip else line for line in lines]
    text = layout.eol.join(rendered) + (layout.eol if layout.final_eol else "")
    return text.encode(layout.encoding)


# --- Facturae ----------------------------------------------------------------------------------
parties = st.one_of(
    st.builds(generator.FacturaeParty, name=texts, tax_id=tax_ids, person=st.just(False)),
    st.builds(generator.FacturaeParty, name=person_names, tax_id=tax_ids, person=st.just(True)),
)


@st.composite
def invoice_records(draw: st.DrawFn, number: str) -> dict[str, str]:
    """One invoice record with consistent VAT, surcharge, withholding and total."""
    base = Decimal(cents_text(draw(st.integers(min_value=0, max_value=INVOICE_CENTS_LIMIT))))
    rate = draw(st.sampled_from(VAT_RATES))
    vat = percent_of(base, Decimal(rate))
    surcharge_rate = draw(st.one_of(st.just(""), st.sampled_from(SURCHARGE_RATES)))
    surcharge = percent_of(base, Decimal(surcharge_rate)) if surcharge_rate else None
    withholding_rate = draw(st.one_of(st.just(""), st.sampled_from(WITHHOLDING_RATES)))
    withholding = percent_of(base, Decimal(withholding_rate)) if withholding_rate else None
    additions = [base, vat] + ([surcharge] if surcharge is not None else [])
    total = net_total(additions, [withholding] if withholding is not None else [])
    due = draw(st.one_of(st.just(""), days.map(date.isoformat)))
    return {
        "invoice_number": number,
        "issue_date": draw(days).isoformat(),
        "due_date": due,
        "base_amount": str(base),
        "vat_rate": rate,
        "vat_amount": str(vat),
        "surcharge_amount": "" if surcharge is None else str(surcharge),
        "surcharge_rate": surcharge_rate,
        "withholding_amount": "" if withholding is None else str(withholding),
        "withholding_rate": withholding_rate,
        "total": str(total),
        "currency": "EUR",
        "iban": draw(ibans),
    }


@st.composite
def invoice_files(draw: st.DrawFn) -> tuple[Any, list[dict[str, str]]]:
    """A supplier and one to five invoice records with distinct numbers."""
    party = draw(parties)
    numbers = draw(st.lists(invoice_numbers, min_size=1, max_size=MAX_INVOICES, unique=True))
    return party, [draw(invoice_records(number)) for number in numbers]


# --- arbitrary and damaged input ---------------------------------------------------------------
@st.composite
def damaged_documents(draw: st.DrawFn) -> bytes:
    """A valid Norma 43 or Facturae file, cut short or with one byte replaced."""
    if draw(st.booleans()):
        lines = generator.render_norma43_lines(draw(statements))
        data = render_with_layout(lines, draw(layouts))
    else:
        party, records = draw(invoice_files())
        data = generator.render_facturae(party, records)
    position = draw(st.integers(min_value=0, max_value=len(data) - 1))
    if draw(st.booleans()):
        return data[:position]
    replacement = draw(st.integers(min_value=0, max_value=255))
    return data[:position] + bytes([replacement]) + data[position + 1 :]


arbitrary_input = st.one_of(
    st.binary(max_size=2000),
    st.binary(max_size=500).map(lambda tail: b"<fe:Facturae>" + tail),
    st.binary(max_size=500).map(lambda tail: b"11" + tail),
    st.text(alphabet="0123456789 \r\n", max_size=400).map(lambda text: text.encode("ascii")),
    damaged_documents(),
)
