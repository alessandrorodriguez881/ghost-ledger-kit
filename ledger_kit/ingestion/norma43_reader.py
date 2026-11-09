"""Norma 43 (AEB Cuaderno 43) bank-statement reader: fixed-width records, control checks.

Layouts follow AEB, "Serie normas y procedimientos bancarios n.º 43", June 2012 (Annex 1 records
11, 22, 23, 24, 33 and 88; Annex 2 concept and currency tables; Annex 4 section 2 SEPA direct
debits), verified in the session 8b review. Positions are written 1-based and inclusive, as in the
document, and converted once by `_cut`.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import IO

from ledger_kit.ingestion.csv_reader import IngestionResult, _read_source
from ledger_kit.ingestion.iso4217 import NUMERIC_TO_ALPHA
from ledger_kit.models import Transaction
from ledger_kit.utils.money import (
    apply_sign,
    balance_after,
    decimal_from_implied,
    round_to_cents,
    sum_amounts,
)

# Width of every record; shorter lines are right-padded with spaces before slicing.
RECORD_LENGTH = 80
# A movement (record 22) takes at most this many record-23 complements (sequence 01..05).
MAX_COMPLEMENTS = 5
# Operation and value dates are YYMMDD; the year is YEAR_BASE + YY.
YEAR_BASE = 2000
# Encodings tried in order when the source is bytes (BOM-aware UTF-8, then ISO-8859-1).
N43_ENCODINGS: tuple[str, ...] = ("utf-8-sig", "latin-1")
# Schemes that mark a SEPA direct-debit complement (Annex 4 section 2).
SEPA_SCHEMES: tuple[str, ...] = ("CORE", "B2B")
# SEPA direct debits are read only in information mode 3 with this common concept.
SEPA_INFORMATION_MODE = "3"
SEPA_COMMON_CONCEPT = "03"
# A free record-23 text that starts with this prefix carries the counterparty IBAN (DN-RF-03).
IBAN_PREFIX = "IBAN "
# Label used for a common concept the Annex 2 table does not list.
OTHER_CONCEPT_LABEL = "Other"
# Annex 2 common-concept labels.
CONCEPT_LABELS: dict[str, str] = {
    "01": "Cheques and withdrawals",
    "02": "Deposits",
    "03": "Direct debits and bills",
    "04": "Transfers",
    "05": "Loan repayments",
    "06": "Bill remittances",
    "07": "Securities subscriptions",
    "08": "Dividends and coupons",
    "09": "Stock operations",
    "10": "Fuel cheques",
    "11": "ATM",
    "12": "Credit and debit cards",
    "13": "Foreign operations",
    "14": "Returns and unpaid items",
    "15": "Payroll and social security",
    "16": "Stamp duty and brokerage",
    "17": "Interest, fees and taxes",
    "98": "Cancellations and corrections",
    "99": "Other",
}
# Record 88 positions 3-20 hold this many nines.
END_NINES = "9" * 18
# Record separators: CRLF, CR or LF only, never the other Unicode separators (DN-RF-04).
LINE_SPLIT = re.compile(r"\r\n|\r|\n")
# Shown by the apps for every `control_check_failed:*` record (REQ-RF-10, DN-RF-27).
CONTROL_CHECK_FAILED_MESSAGE = (
    "This bank file is incomplete or was edited: its totals do not match its movements. "
    "Download a fresh export from your bank and load it again."
)

Span = tuple[int, int]

HEADER_SPANS: dict[str, Span] = {
    "bank": (3, 6),
    "branch": (7, 10),
    "account": (11, 20),
    "start_date": (21, 26),
    "end_date": (27, 32),
    "balance_sign": (33, 33),
    "opening_balance": (34, 47),
    "currency": (48, 50),
    "information_mode": (51, 51),
}
MOVEMENT_SPANS: dict[str, Span] = {
    "operation_date": (11, 16),
    "value_date": (17, 22),
    "common_concept": (23, 24),
    "own_concept": (25, 27),
    "dc_key": (28, 28),
    "amount": (29, 42),
}
COMPLEMENT_SPANS: dict[str, Span] = {"sequence": (3, 4), "text": (5, 80)}
SEPA_SPANS: dict[str, Span] = {
    "scheme": (5, 8),
    "creditor_name": (9, 78),
    "creditor_id": (5, 39),
    "mandate": (40, 74),
    "remittance": (13, 80),
    "continuation": (5, 76),
}
CURRENCY_SPANS: dict[str, Span] = {"sequence": (3, 4), "currency": (5, 7), "amount": (8, 21)}
TRAILER_SPANS: dict[str, Span] = {
    "account": (3, 20),
    "debit_count": (21, 25),
    "debit_total": (26, 39),
    "credit_count": (40, 44),
    "credit_total": (45, 58),
    "closing_sign": (59, 59),
    "closing_balance": (60, 73),
}
END_SPANS: dict[str, Span] = {"nines": (3, 20), "count": (21, 26)}

_DEBTOR = "1"
_CREDITOR = "2"
_DEBIT_KEY = "1"
_CREDIT_KEY = "2"


def _cut(line: str, span: Span) -> str:
    """Return the 1-based, inclusive `span` of an 80-character record."""
    start, end = span
    return line[start - 1 : end]


def _is_digits(text: str, length: int) -> bool:
    """True when `text` is exactly `length` ASCII digits."""
    return len(text) == length and text.isascii() and text.isdigit()


def _yymmdd(text: str) -> date | None:
    """Parse YYMMDD (year = YEAR_BASE + YY); None when malformed or an impossible date."""
    if not _is_digits(text, 6):
        return None
    try:
        return date(YEAR_BASE + int(text[0:2]), int(text[2:4]), int(text[4:6]))
    except ValueError:
        return None


def _collapse(text: str) -> str:
    """Collapse whitespace runs to one space and trim."""
    return " ".join(text.split())


def _money_text(value: Decimal) -> str:
    """Render an amount with exactly two decimals for the quarantine tables."""
    return format(round_to_cents(value), "f")


def _decode(content: str | bytes) -> str:
    """Decode bytes with the fallback chain (ISO-8859-1 never fails); drop a leading BOM."""
    if isinstance(content, str):
        return content.removeprefix("\ufeff")
    for encoding in N43_ENCODINGS:
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("latin-1")


def _record(source_file: str, source_row: int | None, reason: str, raw: object) -> dict:
    """Build a quarantine record."""
    return {"source_file": source_file, "source_row": source_row, "reason": reason, "raw": raw}


def check_block(
    *,
    account: str,
    opening: Decimal,
    debits: Sequence[Decimal],
    credits: Sequence[Decimal],
    line33: str,
    unverifiable: bool = False,
) -> tuple[str, str, str] | None:
    """Run the control checks of REQ-RF-10 in order; return (check, declared, computed) or None.

    `opening` is the signed opening balance (debtor negative). `line33` is the 80-character record.
    """
    declared_account = _cut(line33, TRAILER_SPANS["account"])
    if declared_account != account:
        return "account_mismatch", declared_account, account

    debit_text = _cut(line33, TRAILER_SPANS["debit_count"])
    if not _is_digits(debit_text, 5) or int(debit_text) != len(debits):
        return "debit_count", _count_text(debit_text), str(len(debits))

    debit_total = sum_amounts(debits)
    declared_debits = _declared_amount(_cut(line33, TRAILER_SPANS["debit_total"]))
    if declared_debits is None or declared_debits != debit_total:
        text = _cut(line33, TRAILER_SPANS["debit_total"]).strip()
        return "debit_total", _money_or(declared_debits, text), _money_text(debit_total)

    credit_text = _cut(line33, TRAILER_SPANS["credit_count"])
    if not _is_digits(credit_text, 5) or int(credit_text) != len(credits):
        return "credit_count", _count_text(credit_text), str(len(credits))

    credit_total = sum_amounts(credits)
    declared_credits = _declared_amount(_cut(line33, TRAILER_SPANS["credit_total"]))
    if declared_credits is None or declared_credits != credit_total:
        text = _cut(line33, TRAILER_SPANS["credit_total"]).strip()
        return "credit_total", _money_or(declared_credits, text), _money_text(credit_total)

    computed = balance_after(opening, credit_total, debit_total)
    sign = _cut(line33, TRAILER_SPANS["closing_sign"])
    closing = _declared_amount(_cut(line33, TRAILER_SPANS["closing_balance"]))
    if sign not in (_DEBTOR, _CREDITOR) or closing is None:
        raw = (sign + _cut(line33, TRAILER_SPANS["closing_balance"])).strip()
        return "balance", raw, _money_text(computed)
    declared = apply_sign(closing, sign == _DEBTOR)
    if declared != computed:
        return "balance", _money_text(declared), _money_text(computed)

    if unverifiable:
        return "unverifiable_movement", "", ""
    return None


def _count_text(text: str) -> str:
    """Declared count as plain digits ('00002' -> '2'); the raw trimmed text when unreadable."""
    return str(int(text)) if _is_digits(text, 5) else text.strip()


def _declared_amount(text: str) -> Decimal | None:
    """Read a 14-digit amount field; None when it is not 14 digits."""
    if not _is_digits(text, 14):
        return None
    return decimal_from_implied(text)


def _money_or(value: Decimal | None, fallback: str) -> str:
    """Two-decimal text of `value`, or the raw `fallback` text when it could not be read."""
    return fallback if value is None else _money_text(value)


@dataclass
class _Block:
    """One account block: header fields, committed transactions and control-sum inputs."""

    line_no: int
    account: str | None = None
    currency: str = ""
    mode: str = ""
    opening: Decimal = Decimal("0")
    rejected_reason: str | None = None
    dropped_lines: int = 0
    transactions: list[Transaction] = field(default_factory=list)
    debits: list[Decimal] = field(default_factory=list)
    credits: list[Decimal] = field(default_factory=list)
    unverifiable: bool = False


@dataclass
class _Movement:
    """A pending record 22 with its attached complements."""

    line_no: int
    line: str
    block: _Block | None
    reason: str | None = None
    key: str = ""
    amount: Decimal | None = None
    operation_date: date | None = None
    raw_lines: list[str] = field(default_factory=list)
    complements: list[str] = field(default_factory=list)
    currency_lines: list[str] = field(default_factory=list)


class _Parser:
    """Line-by-line state machine behind `parse_norma43`."""

    def __init__(self, source_file: str) -> None:
        self.source_file = source_file
        self.valid: list[Transaction] = []
        self.quarantine: list[dict] = []
        self.block: _Block | None = None
        self.movement: _Movement | None = None
        self.record_count = 0
        self.end_record: str | None = None

    # -- driver ---------------------------------------------------------------------------------

    def feed(self, number: int, raw: str) -> None:
        """Process one physical line; blank lines are skipped (the caller keeps the numbering)."""
        if not raw.strip(" \t"):
            return
        line = raw.rstrip(" ")
        if self.end_record is not None:
            self._row(number, "record_after_end_of_file", [line])
            return
        if len(line) > RECORD_LENGTH:
            self.record_count += 1
            self._too_long(number, line)
            return
        padded = line.ljust(RECORD_LENGTH)
        code = padded[0:2]
        if code == "88":
            self._end_of_file(number, padded)
            return
        self.record_count += 1
        if self.block is not None and self.block.rejected_reason and code not in ("11", "33"):
            self.block.dropped_lines += 1
            return
        if code == "11":
            self._account_header(number, padded)
        elif code == "22":
            self._movement(number, line, padded)
        elif code == "23":
            self._complement(number, line, padded)
        elif code == "24":
            self._currency(number, line, padded)
        elif code == "33":
            self._trailer(number, line, padded)
        else:
            self._row(number, f"unknown_record_code:{code.strip() or code}", [line])

    def finish(self) -> IngestionResult[Transaction]:
        """Close the file: apply the record-88 checks and return (transactions, quarantine)."""
        if self.end_record is None:
            self._finish_movement()
            self._close_without_trailer()
            self._file_record("record88_missing", None, str(self.record_count))
        else:
            self._check_end_record(self.end_record)
        return self.valid, self.quarantine

    # -- helpers --------------------------------------------------------------------------------

    def _row(self, number: int, reason: str, lines: list[str]) -> None:
        """Quarantine one stray line or movement at row level."""
        self.quarantine.append(_record(self.source_file, number, reason, "\n".join(lines)))

    def _file_record(self, check: str, declared: str | None, computed: str) -> None:
        """Quarantine the whole file for a record-88 problem and drop every transaction."""
        self.valid = []
        raw = {"declared": declared, "computed": computed}
        self.quarantine.append(
            _record(self.source_file, None, f"control_check_failed:{check}", raw)
        )

    def _too_long(self, number: int, line: str) -> None:
        """Quarantine a line wider than RECORD_LENGTH; the record is dropped."""
        block = self.block
        if block is not None and block.rejected_reason:
            block.dropped_lines += 1
            return
        if block is not None and line.startswith("22"):
            block.unverifiable = True
        self._row(number, "line_too_long", [line])

    # -- record 11 ------------------------------------------------------------------------------

    def _account_header(self, number: int, padded: str) -> None:
        """Open an account block from a record 11, or reject it."""
        self._finish_movement()
        self._close_without_trailer()
        block = _Block(line_no=number)
        self.block = block

        bank = _cut(padded, HEADER_SPANS["bank"])
        branch = _cut(padded, HEADER_SPANS["branch"])
        number_text = _cut(padded, HEADER_SPANS["account"])
        account_ok = _is_digits(bank, 4) and _is_digits(branch, 4) and _is_digits(number_text, 10)
        if account_ok:
            block.account = bank + branch + number_text

        sign = _cut(padded, HEADER_SPANS["balance_sign"])
        opening_text = _cut(padded, HEADER_SPANS["opening_balance"])
        numeric_currency = _cut(padded, HEADER_SPANS["currency"])
        mode = _cut(padded, HEADER_SPANS["information_mode"])

        if not account_ok:
            block.rejected_reason = "bad_account_header:account"
        elif _yymmdd(_cut(padded, HEADER_SPANS["start_date"])) is None:
            block.rejected_reason = "bad_account_header:start_date"
        elif _yymmdd(_cut(padded, HEADER_SPANS["end_date"])) is None:
            block.rejected_reason = "bad_account_header:end_date"
        elif sign not in (_DEBTOR, _CREDITOR):
            block.rejected_reason = "bad_account_header:balance_sign"
        elif not _is_digits(opening_text, 14):
            block.rejected_reason = "bad_account_header:opening_balance"
        elif numeric_currency not in NUMERIC_TO_ALPHA:
            block.rejected_reason = "unknown_currency_code"
        elif mode not in ("1", "2", "3"):
            block.rejected_reason = "bad_account_header:information_mode"
        else:
            block.currency = NUMERIC_TO_ALPHA[numeric_currency]
            block.mode = mode
            block.opening = apply_sign(decimal_from_implied(opening_text), sign == _DEBTOR)

    def _close_without_trailer(self) -> None:
        """Close the open block when the next 11, the 88 or the end of file arrives first."""
        block = self.block
        if block is None:
            return
        self.block = None
        if block.rejected_reason:
            self._rejected_record(block)
            return
        raw = {"account": block.account, "declared": None, "computed": None, "line_33": None}
        self.quarantine.append(
            _record(
                self.source_file,
                block.line_no,
                "control_check_failed:missing_end_of_account",
                raw,
            )
        )

    def _rejected_record(self, block: _Block) -> None:
        """Emit the block record of a block rejected for its header."""
        raw: dict[str, object] = {}
        if block.account is not None:
            raw["account"] = block.account
        raw["dropped_lines"] = block.dropped_lines
        self.quarantine.append(
            _record(self.source_file, block.line_no, block.rejected_reason or "", raw)
        )

    # -- record 22 ------------------------------------------------------------------------------

    def _movement(self, number: int, line: str, padded: str) -> None:
        """Start a movement from a record 22; row-level problems are decided here."""
        self._finish_movement()
        block = self.block
        if block is None:
            self.movement = _Movement(
                number, padded, None, "movement_without_account_header", raw_lines=[line]
            )
            return

        key = _cut(padded, MOVEMENT_SPANS["dc_key"])
        amount: Decimal | None = None
        amount_text = _cut(padded, MOVEMENT_SPANS["amount"])
        if _is_digits(amount_text, 14):
            amount = decimal_from_implied(amount_text)
        # The key and amount are read first so that a bad date still counts in the control sums.
        if key in (_DEBIT_KEY, _CREDIT_KEY) and amount is not None:
            (block.debits if key == _DEBIT_KEY else block.credits).append(amount)
        else:
            block.unverifiable = True

        operation_date = _yymmdd(_cut(padded, MOVEMENT_SPANS["operation_date"]))
        reason: str | None = None
        if not (
            _is_digits(_cut(padded, MOVEMENT_SPANS["common_concept"]), 2)
            and _is_digits(_cut(padded, MOVEMENT_SPANS["own_concept"]), 3)
        ):
            reason = "bad_concept_code"
        elif key not in (_DEBIT_KEY, _CREDIT_KEY):
            reason = "bad_dc_key"
        elif amount is None:
            reason = "non_digit_amount"
        elif operation_date is None:
            reason = "bad_date:operation_date"
        elif _yymmdd(_cut(padded, MOVEMENT_SPANS["value_date"])) is None:
            reason = "bad_date:value_date"

        self.movement = _Movement(
            number,
            padded,
            block,
            reason,
            key=key,
            amount=amount,
            operation_date=operation_date,
            raw_lines=[line],
        )

    def _finish_movement(self) -> None:
        """Turn the pending movement into a transaction or a row-level quarantine record."""
        movement = self.movement
        if movement is None:
            return
        self.movement = None
        reason = movement.reason
        if reason is None and self._currency_problem(movement):
            reason = "bad_currency_equivalence"
        if reason is not None or movement.block is None:
            self._row(movement.line_no, reason or "", movement.raw_lines)
            return
        movement.block.transactions.append(self._transaction(movement, movement.block))

    # -- records 23 and 24 ----------------------------------------------------------------------

    def _complement(self, number: int, line: str, padded: str) -> None:
        """Attach a record 23 to the pending movement."""
        movement = self.movement
        if movement is None:
            self._row(number, "complement_without_movement", [line])
            return
        if movement.reason is not None:
            movement.raw_lines.append(line)
            return
        if len(movement.complements) >= MAX_COMPLEMENTS:
            self._row(number, "too_many_complements", [line])
            return
        expected = f"{len(movement.complements) + 1:02d}"
        if _cut(padded, COMPLEMENT_SPANS["sequence"]) != expected:
            self._row(number, "bad_complement_sequence", [line])
            return
        movement.complements.append(padded)
        movement.raw_lines.append(line)

    def _currency(self, number: int, line: str, padded: str) -> None:
        """Attach a record 24 to the pending movement."""
        movement = self.movement
        if movement is None:
            self._row(number, "complement_without_movement", [line])
            return
        movement.raw_lines.append(line)
        if movement.reason is None:
            movement.currency_lines.append(padded)

    @staticmethod
    def _currency_problem(movement: _Movement) -> bool:
        """True when the movement's record 24 is malformed or repeated."""
        if not movement.currency_lines:
            return False
        if len(movement.currency_lines) > 1:
            return True
        line = movement.currency_lines[0]
        return not (
            _cut(line, CURRENCY_SPANS["sequence"]) == "01"
            and _is_digits(_cut(line, CURRENCY_SPANS["currency"]), 3)
            and _is_digits(_cut(line, CURRENCY_SPANS["amount"]), 14)
        )

    # -- movement to transaction ----------------------------------------------------------------

    def _transaction(self, movement: _Movement, block: _Block) -> Transaction:
        """Map a valid movement and its complements to a Transaction (REQ-RF-05 to REQ-RF-08)."""
        line = movement.line
        common = _cut(line, MOVEMENT_SPANS["common_concept"])
        own = _cut(line, MOVEMENT_SPANS["own_concept"])
        label = CONCEPT_LABELS.get(common, OTHER_CONCEPT_LABEL)
        tags = [f"account:{block.account}", f"common_concept:{common}", f"own_concept:{own}"]
        iban: str | None = None

        if self._is_sepa(movement, block, common):
            counterparty, description, sepa_tags = self._sepa(movement, label)
            tags.extend(sepa_tags)
        else:
            counterparty, description, iban = self._generic(movement, label)

        if movement.currency_lines:
            tags.extend(self._original_currency_tags(movement.currency_lines[0]))

        assert movement.amount is not None and movement.operation_date is not None
        return Transaction(
            date=movement.operation_date,
            amount=movement.amount,
            flow="debit" if movement.key == _DEBIT_KEY else "credit",
            currency=block.currency,
            counterparty=counterparty,
            description=description,
            iban=iban,
            source_file=self.source_file,
            source_row=movement.line_no,
            source_ref=f"{self.source_file}:{movement.line_no}",
            tags=tags,
        )

    @staticmethod
    def _is_sepa(movement: _Movement, block: _Block, common: str) -> bool:
        """True for a direct debit in information mode 3 whose 23-01 carries CORE or B2B."""
        if block.mode != SEPA_INFORMATION_MODE or common != SEPA_COMMON_CONCEPT:
            return False
        if not movement.complements:
            return False
        return _cut(movement.complements[0], SEPA_SPANS["scheme"]).strip() in SEPA_SCHEMES

    @staticmethod
    def _sepa(movement: _Movement, label: str) -> tuple[str, str, list[str]]:
        """Read the Annex 4 section 2 layout: counterparty, description and tags."""
        by_sequence = {_cut(c, COMPLEMENT_SPANS["sequence"]): c for c in movement.complements}
        first = movement.complements[0]
        scheme = _cut(first, SEPA_SPANS["scheme"]).strip()
        creditor = _collapse(_cut(first, SEPA_SPANS["creditor_name"]))
        creditor_id = ""
        mandate = ""
        if "02" in by_sequence:
            creditor_id = _collapse(_cut(by_sequence["02"], SEPA_SPANS["creditor_id"]))
            mandate = _collapse(_cut(by_sequence["02"], SEPA_SPANS["mandate"]))
        remittance = ""
        if "03" in by_sequence:
            remittance = _cut(by_sequence["03"], SEPA_SPANS["remittance"])
        if "04" in by_sequence:
            remittance += _cut(by_sequence["04"], SEPA_SPANS["continuation"])

        tags = [f"scheme:{scheme}"]
        if creditor_id:
            tags.append(f"creditor_id:{creditor_id}")
        if mandate:
            tags.append(f"mandate:{mandate}")
        return creditor or label, _collapse(remittance) or label, tags

    @staticmethod
    def _generic(movement: _Movement, label: str) -> tuple[str, str, str | None]:
        """Read free record-23 texts: counterparty, description and the IBAN record."""
        texts = [_collapse(_cut(c, COMPLEMENT_SPANS["text"])) for c in movement.complements]
        iban: str | None = None
        remaining: list[str] = []
        for text in texts:
            if text.startswith(IBAN_PREFIX):
                if iban is None:
                    iban = text[len(IBAN_PREFIX) :]
            elif text:
                remaining.append(text)
        if not remaining:
            return label, label, iban
        if len(remaining) == 1:
            return remaining[0], label, iban
        return remaining[0], " ".join(remaining[1:]), iban

    @staticmethod
    def _original_currency_tags(line: str) -> list[str]:
        """Tags for a valid record 24: known code -> alphabetic, else the digits as read."""
        numeric = _cut(line, CURRENCY_SPANS["currency"])
        amount = decimal_from_implied(_cut(line, CURRENCY_SPANS["amount"]))
        alpha = NUMERIC_TO_ALPHA.get(numeric)
        code_tag = f"original_currency:{alpha}" if alpha else f"original_currency_code:{numeric}"
        return [code_tag, f"original_amount:{amount}"]

    # -- record 33 ------------------------------------------------------------------------------

    def _trailer(self, number: int, line: str, padded: str) -> None:
        """Close the block with its record 33 and run the control checks."""
        self._finish_movement()
        block = self.block
        if block is None:
            self._row(number, "trailer_without_account_header", [line])
            return
        self.block = None
        if block.rejected_reason:
            block.dropped_lines += 1
            self._rejected_record(block)
            return
        assert block.account is not None
        failure = check_block(
            account=block.account,
            opening=block.opening,
            debits=block.debits,
            credits=block.credits,
            line33=padded,
            unverifiable=block.unverifiable,
        )
        if failure is None:
            self.valid.extend(block.transactions)
            return
        check, declared, computed = failure
        raw = {
            "account": block.account,
            "declared": declared,
            "computed": computed,
            "line_33": number,
        }
        self.quarantine.append(
            _record(self.source_file, block.line_no, f"control_check_failed:{check}", raw)
        )

    # -- record 88 ------------------------------------------------------------------------------

    def _end_of_file(self, number: int, padded: str) -> None:
        """Remember the record 88; it is checked in `finish` once the whole file is known."""
        self._finish_movement()
        self._close_without_trailer()
        self.end_record = padded

    def _check_end_record(self, padded: str) -> None:
        """Check positions 3-20 (eighteen nines) and 21-26 (lines before the 88)."""
        nines = _cut(padded, END_SPANS["nines"])
        count_text = _cut(padded, END_SPANS["count"])
        if nines != END_NINES or not _is_digits(count_text, 6):
            expected = "88" + END_NINES + f"{self.record_count:06d}"
            self._file_record("record88_format", padded.rstrip(" "), expected)
        elif int(count_text) != self.record_count:
            self._file_record("record88_count", str(int(count_text)), str(self.record_count))


def parse_norma43(
    source: Path | str | IO[str] | IO[bytes],
    *,
    source_file: str | None = None,
) -> IngestionResult[Transaction]:
    """Parse a Norma 43 statement; returns (transactions, quarantined), never raises on bad input."""
    content, default_name = _read_source(source)
    file_name = source_file or default_name
    text = _decode(content)
    if not text.strip():
        return [], []

    parser = _Parser(file_name)
    for number, raw in enumerate(LINE_SPLIT.split(text), start=1):
        parser.feed(number, raw)
    return parser.finish()
