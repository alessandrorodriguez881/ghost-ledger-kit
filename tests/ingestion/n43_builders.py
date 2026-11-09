"""Builders for Norma 43 test files (design 9).

Records are assembled from ``(start, end, value)`` fields with the 1-based, inclusive positions of
the AEB document, so no test counts columns by hand. Every record is 80 characters wide; use
``join_lines`` to write a file with the line ending and trailing-space handling a test needs.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from ledger_kit.utils.money import balance_after, implied_digits, sum_amounts

RECORD_LENGTH = 80
FileField = tuple[int, int, str]

FIXTURE_A_NAMES = (
    "header",
    "movement_1",
    "complement_1",
    "complement_2",
    "movement_2",
    "trailer",
    "end",
)


def n43_line(code: str, *fields: FileField) -> str:
    """Return an 80-character record with `code` at 1-2 and each (start, end, value) field."""
    if len(code) != 2:
        raise ValueError(f"record code must have two characters: {code!r}")
    chars = [" "] * RECORD_LENGTH
    chars[0:2] = list(code)
    for start, end, value in fields:
        width = end - start + 1
        if len(value) > width:
            raise ValueError(f"{value!r} does not fit positions {start}-{end}")
        chars[start - 1 : end] = list(value.ljust(width))
    return "".join(chars)


def cents(value: Decimal | str, width: int = 14) -> str:
    """Return a field text: a Decimal or a string with '.' becomes implied digits, else raw."""
    if isinstance(value, Decimal):
        return implied_digits(value, width)
    if "." in value:
        return implied_digits(Decimal(value), width)
    return value


def count(value: int | str, width: int = 5) -> str:
    """Return a record count field: an int is zero-padded, a string is used as given."""
    return str(value).zfill(width) if isinstance(value, int) else value


def header_11(
    *,
    bank: str = "9999",
    branch: str = "0001",
    account: str = "0000000001",
    start_date: str = "260105",
    end_date: str = "260131",
    balance_sign: str = "2",
    opening: Decimal | str = "5000.00",
    currency: str = "978",
    mode: str = "1",
    holder: str = "TITULAR FICTICIO DEMO",
) -> str:
    """Return a record 11 (account header)."""
    return n43_line(
        "11",
        (3, 6, bank),
        (7, 10, branch),
        (11, 20, account),
        (21, 26, start_date),
        (27, 32, end_date),
        (33, 33, balance_sign),
        (34, 47, cents(opening)),
        (48, 50, currency),
        (51, 51, mode),
        (52, 77, holder),
    )


def movement_22(
    *,
    branch: str = "0001",
    op_date: str = "260105",
    value_date: str | None = None,
    common: str = "04",
    own: str = "000",
    key: str = "1",
    amount: Decimal | str = "12.99",
    document: str = "0000000000",
    reference_1: str = "000000000000",
    reference_2: str = "",
) -> str:
    """Return a record 22 (movement); the value date defaults to the operation date."""
    return n43_line(
        "22",
        (7, 10, branch),
        (11, 16, op_date),
        (17, 22, op_date if value_date is None else value_date),
        (23, 24, common),
        (25, 27, own),
        (28, 28, key),
        (29, 42, cents(amount)),
        (43, 52, document),
        (53, 64, reference_1),
        (65, 80, reference_2),
    )


def complement_23(sequence: str, text: str) -> str:
    """Return a generic record 23: sequence at 3-4 and a 76-character text at 5-80."""
    return n43_line("23", (3, 4, sequence), (5, 80, text))


def sepa_23_01(scheme: str, creditor_name: str) -> str:
    """Return the SEPA record 23-01: scheme at 5-8 and creditor name at 9-78."""
    return n43_line("23", (3, 4, "01"), (5, 8, scheme), (9, 78, creditor_name))


def sepa_23_02(creditor_id: str, mandate: str) -> str:
    """Return the SEPA record 23-02: creditor id at 5-39 and mandate at 40-74."""
    return n43_line("23", (3, 4, "02"), (5, 39, creditor_id), (40, 74, mandate))


def sepa_23_03(remittance: str) -> str:
    """Return the SEPA record 23-03: remittance information at 13-80."""
    return n43_line("23", (3, 4, "03"), (13, 80, remittance))


def sepa_23_04(continuation: str) -> str:
    """Return the SEPA record 23-04: remittance continuation at 5-76."""
    return n43_line("23", (3, 4, "04"), (5, 76, continuation))


def currency_24(
    currency: str = "840", amount: Decimal | str = "15.00", sequence: str = "01"
) -> str:
    """Return a record 24 (original currency): numeric code at 5-7, amount at 8-21."""
    return n43_line("24", (3, 4, sequence), (5, 7, currency), (8, 21, cents(amount)))


def closing_33(
    *,
    bank: str = "9999",
    branch: str = "0001",
    account: str = "0000000001",
    debit_count: int | str = 1,
    debit_total: Decimal | str = "12.99",
    credit_count: int | str = 1,
    credit_total: Decimal | str = "2450.00",
    sign: str = "2",
    balance: Decimal | str = "7437.01",
    currency: str = "978",
) -> str:
    """Return a record 33 (account trailer)."""
    return n43_line(
        "33",
        (3, 6, bank),
        (7, 10, branch),
        (11, 20, account),
        (21, 25, count(debit_count)),
        (26, 39, cents(debit_total)),
        (40, 44, count(credit_count)),
        (45, 58, cents(credit_total)),
        (59, 59, sign),
        (60, 73, cents(balance)),
        (74, 76, currency),
    )


def end_88(record_count: int | str = 6, nines: str = "9" * 18) -> str:
    """Return a record 88 (end of file) with the count of the lines before it."""
    return n43_line("88", (3, 20, nines), (21, 26, count(record_count, width=6)))


def fixture_a_lines(**overrides: str) -> list[str]:
    """Return the seven 80-character lines of Fixture A.

    `overrides` replaces whole lines by name (see FIXTURE_A_NAMES): header, movement_1,
    complement_1, complement_2, movement_2, trailer, end.
    """
    unknown = set(overrides) - set(FIXTURE_A_NAMES)
    if unknown:
        raise ValueError(f"unknown fixture line names: {sorted(unknown)}")
    lines = {
        "header": header_11(),
        "movement_1": movement_22(),
        "complement_1": complement_23("01", "Taller Norte SL"),
        "complement_2": complement_23("02", "Car repair"),
        "movement_2": movement_22(op_date="260128", common="15", key="2", amount="2450.00"),
        "trailer": closing_33(),
        "end": end_88(6),
    }
    lines.update(overrides)
    return [lines[name] for name in FIXTURE_A_NAMES]


def join_lines(
    lines: Iterable[str],
    *,
    eol: str = "\n",
    strip: bool = True,
    final_eol: bool = True,
) -> str:
    """Join records into file text; `strip` removes each record's trailing spaces."""
    rendered = [line.rstrip(" ") if strip else line for line in lines]
    return eol.join(rendered) + (eol if final_eol else "")


def fixture_a(*, eol: str = "\n", strip: bool = True, **overrides: str) -> str:
    """Return Fixture A as file text (LF and trailing spaces removed by default)."""
    return join_lines(fixture_a_lines(**overrides), eol=eol, strip=strip)


def fixture_a_bytes(*, eol: str = "\n", strip: bool = True, **overrides: str) -> bytes:
    """Return Fixture A encoded as ISO-8859-1 bytes."""
    return fixture_a(eol=eol, strip=strip, **overrides).encode("latin-1")


def wrap_account(
    body: Iterable[str],
    *,
    debits: Iterable[Decimal | str] = (),
    credits: Iterable[Decimal | str] = (),
    mode: str = "1",
    opening: Decimal | str = "5000.00",
    account: str = "0000000001",
) -> list[str]:
    """Return record 11 + `body` + a matching record 33 (counts, totals and balance computed).

    `debits` and `credits` list the amounts of the 22 records in `body`, by key.
    """
    opening_value = Decimal(opening)
    debit_values = [Decimal(value) for value in debits]
    credit_values = [Decimal(value) for value in credits]
    closing = balance_after(opening_value, sum_amounts(credit_values), sum_amounts(debit_values))
    return [
        header_11(account=account, opening=opening_value, mode=mode),
        *body,
        closing_33(
            account=account,
            debit_count=len(debit_values),
            debit_total=sum_amounts(debit_values),
            credit_count=len(credit_values),
            credit_total=sum_amounts(credit_values),
            sign="2" if closing >= 0 else "1",
            balance=abs(closing),
        ),
    ]


def with_end(lines: list[str]) -> list[str]:
    """Append a record 88 that counts `lines` (every line before it)."""
    return [*lines, end_88(len(lines))]
