"""LLM explanation layer: the only module in ledger_kit that may call an LLM (design §4a)."""

import logging
import os
import re
import string
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal

import pandas as pd

from ledger_kit.ingestion.iso4217 import NUMERIC_TO_ALPHA
from ledger_kit.models import Alert
from ledger_kit.utils.money import format_amount, format_index, format_percent

# Streamlit renders alerts synchronously: keep the LLM call short.
LLM_TIMEOUT_SECONDS: int = 10  # default seconds before giving up
LLM_TIMEOUT_MIN_SECONDS: int = 1  # smallest accepted LEDGER_KIT_LLM_TIMEOUT
LLM_TIMEOUT_MAX_SECONDS: int = 120  # largest accepted LEDGER_KIT_LLM_TIMEOUT
LLM_TIMEOUT_ENV: str = "LEDGER_KIT_LLM_TIMEOUT"  # optional override, whole seconds
LLM_MAX_RETRIES: int = 1  # one attempt; callers cache per alert.id
# Upper bound on the answer length: three plain sentences fit; long echoes of the input do not
# (a CPU-only local model is slow, a hosted one is paid per token).
LLM_MAX_TOKENS: int = 200

# Default columns sent to the LLM (minimum data, Finance Rule 5 / REQ-EXP-11).
_LLM_ROW_COLUMNS = ("date", "amount", "flow", "currency", "counterparty", "source_ref")
# Dropped even if a caller lists them (defence in depth).
_NEVER_SENT_COLUMNS = frozenset({"id", "description", "iban"})

_log = logging.getLogger(__name__)


def llm_timeout_seconds(env: Mapping[str, str] | None = None) -> int:
    """Return the effective call timeout: LEDGER_KIT_LLM_TIMEOUT if valid, else the default."""
    source = os.environ if env is None else env
    text = str(source.get(LLM_TIMEOUT_ENV, "")).strip()
    if text.isascii() and text.isdigit():
        value = int(text)
        if LLM_TIMEOUT_MIN_SECONDS <= value <= LLM_TIMEOUT_MAX_SECONDS:
            return value
    return LLM_TIMEOUT_SECONDS


@dataclass(frozen=True)
class Explanation:
    """Result of explain_with_meta(). `source` is 'llm' or 'fallback'."""

    text: str
    source: Literal["llm", "fallback"]
    rejected_numbers: tuple[str, ...]  # tokens the guard found and rejected
    # The model's text as received (accepted or rejected); "" when it did not answer.
    raw_answer: str = field(default="", compare=False, repr=False)


def explain(
    alert: Alert,
    rows: pd.DataFrame,
    *,
    fallback_template: str,
    client=None,
    row_columns: Sequence[str] | None = None,
    question: str | None = None,
) -> str:
    """Return a plain-English explanation for `alert` (guarded text only)."""
    return explain_with_meta(
        alert,
        rows,
        fallback_template=fallback_template,
        client=client,
        row_columns=row_columns,
        question=question,
    ).text


def explain_with_meta(
    alert: Alert,
    rows: pd.DataFrame,
    *,
    fallback_template: str,
    client=None,
    row_columns: Sequence[str] | None = None,
    question: str | None = None,
) -> Explanation:
    """Return an Explanation; falls back to the filled template on any error or rejection."""
    narrow_rows = _select_llm_columns(rows, row_columns)
    fallback = fill_fallback(fallback_template, alert)

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key and client is None:
        return Explanation(text=fallback, source="fallback", rejected_numbers=())

    raw = _call_llm(alert, narrow_rows, client=client, question=question)
    if raw is None:
        return Explanation(text=fallback, source="fallback", rejected_numbers=())

    ok, rejected = _passes_number_guard(raw, alert, narrow_rows, row_columns)
    if not ok:
        _log.warning("Number guard rejected LLM response for alert %s: %s", alert.id, rejected)
        return Explanation(
            text=fallback, source="fallback", rejected_numbers=rejected, raw_answer=raw
        )

    return Explanation(text=raw, source="llm", rejected_numbers=(), raw_answer=raw)


def _select_llm_columns(
    rows: pd.DataFrame, row_columns: Sequence[str] | None = None
) -> pd.DataFrame:
    """Return only the whitelisted columns that are present, in whitelist order."""
    wanted = _LLM_ROW_COLUMNS if row_columns is None else tuple(row_columns)
    present = [c for c in wanted if c in rows.columns and c not in _NEVER_SENT_COLUMNS]
    return rows[present]


class _AlertFormatter(string.Formatter):
    """string.Formatter that resolves {key} and {key:money} from alert.data."""

    def __init__(self, alert: Alert) -> None:
        super().__init__()
        self._data = alert.data
        self._refs = ", ".join(alert.source_refs)

    def get_value(self, key, args, kwargs):
        """Resolve a placeholder; unknown keys are left as '{key}'."""
        if key == "source_refs":
            return self._refs
        return self._data.get(key, "{" + str(key) + "}")

    def format_field(self, value, format_spec):
        """Format a resolved value: ':money' amounts, ':pct' percentages, ':idx' index values."""
        formatter = _FORMAT_SPECS.get(format_spec)
        if formatter is not None:
            try:
                return formatter(Decimal(str(value)))
            except (InvalidOperation, TypeError, ValueError):
                return str(value)
        return str(value)


# European display of the numeric format specs; a value that is not a number is shown as is.
_FORMAT_SPECS = {"money": format_amount, "pct": format_percent, "idx": format_index}


def fill_fallback(template: str, alert: Alert) -> str:
    """Fill the fallback template from the alert (public: apps call it directly)."""
    return _AlertFormatter(alert).vformat(template, [], {})


# --- Number guard -------------------------------------------------------------------------

_IBAN_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,3})?(?![A-Za-z0-9])"
)
_DATE_ISO_RE = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
_DATE_EU_RE = re.compile(r"(?<!\d)(\d{2})/(\d{2})/(\d{4})(?!\d)")
# English month names, full names before their three-letter forms (REQ-LG-28). The abbreviation
# may end in a dot; the name must not be part of a longer word.
_MONTH_NAMES: tuple[str, ...] = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)
_MONTH_NUMBER: dict[str, int] = {name[:3]: i for i, name in enumerate(_MONTH_NAMES, start=1)}
_MONTH = (
    r"(?<![A-Za-z])("
    + "|".join(_MONTH_NAMES)
    + "|"
    + "|".join(name[:3] for name in _MONTH_NAMES)
    + r")(?![A-Za-z])\.?"
)
_DAY = r"(?<![\d.,])(\d{1,2})(?:st|nd|rd|th)?(?!\d)"
_YEAR = r"(?<!\d)(\d{4})(?!\d|[.,]\d)"
# "June 18, 2025", "June 18 2025", "Jun. 18th, 2025"
_DATE_MDY = _MONTH + r"\s+" + _DAY + r",?\s+" + _YEAR
# "18 June 2025", "18th Jun. 2025"
_DATE_DMY = _DAY + r"\s+" + _MONTH + r",?\s+" + _YEAR
_DATE_MDY_RE = re.compile(_DATE_MDY, re.IGNORECASE)
_DATE_DMY_RE = re.compile(_DATE_DMY, re.IGNORECASE)
# A day of a partial date is not part of a decimal, a time or a code ("August 9.99" is no date).
_DAY_PARTIAL = _DAY + r"(?![.,]\d|[/:-]\d)"
# Partial dates, without a year (REQ-LG-34): "August 9", "9th Aug."
_DATE_MD_PART = _MONTH + r"\s+" + _DAY_PARTIAL
_DATE_DM_PART = _DAY_PARTIAL + r"\s+" + _MONTH
_DATE_MD_PART_RE = re.compile(_DATE_MD_PART, re.IGNORECASE)
_DATE_DM_PART_RE = re.compile(_DATE_DM_PART, re.IGNORECASE)
# Group numbers of _WORDS_ITEM_RE: MDY 1-3 (month, day, year), DMY 4-6 (day, month, year),
# month-day 7-8 (month, day), day-month 9-10 (day, month). Full forms come first.
_WORDS_ITEM_RE = re.compile(
    "|".join((_DATE_MDY, _DATE_DMY, _DATE_MD_PART, _DATE_DM_PART)), re.IGNORECASE
)
# What may stand between two dates of one list: ", ", ", and ", " and ", " & ".
_DATE_LIST_SEP_RE = re.compile(
    r"(?:,\s*(?:(?:and|or)\s+)?|\s+(?:and|or)\s+|\s*&\s*)", re.IGNORECASE
)
_NUM_EU_RE = re.compile(r"(?<!\d)(?:\d{1,3}(?:\.\d{3})+|\d+),\d+(?!\d)")
_NUM_PLAIN_RE = re.compile(r"(?<!\d)\d+(?:\.\d+)?(?!\d)")


@dataclass(frozen=True)
class _Tokens:
    """Result of _tokenise(): everything numeric found in one string."""

    dates: frozenset[date]
    malformed_dates: tuple[str, ...]
    ibans: tuple[str, ...]
    numbers: tuple[str, ...]
    # month-day dates written without a year anywhere: (as written, month, day)
    partial_dates: tuple[tuple[str, int, int], ...] = ()


def _words_parts(m: re.Match[str]) -> tuple[int, int]:
    """Month number and day of a _WORDS_ITEM_RE match (any of its four forms)."""
    if m.group(1) is not None:
        month, day = m.group(1), m.group(2)
    elif m.group(5) is not None:
        month, day = m.group(5), m.group(4)
    elif m.group(7) is not None:
        month, day = m.group(7), m.group(8)
    else:
        month, day = m.group(10), m.group(9)
    return _MONTH_NUMBER[month.lower()[:3]], int(day)


def _year_lists(text: str, dates: set[date], malformed: list[str]) -> str:
    """Give each partial date of a list the year of the dated item that ends the list.

    "August 9, September 8, and October 8, 2026": the first two items take 2026 and join `dates`
    (or `malformed` when the day does not exist); they are blanked. The last item is left for the
    full-date passes. A partial date with no dated item after it in its list is left untouched.
    """
    taken: list[re.Match[str]] = []
    pending: list[re.Match[str]] = []
    last_end: int | None = None
    for m in _WORDS_ITEM_RE.finditer(text):
        if last_end is not None and not _DATE_LIST_SEP_RE.fullmatch(text[last_end : m.start()]):
            pending = []  # something else stands between the items: not one list
        last_end = m.end()
        year = m.group(3) or m.group(6)
        if year is None:
            pending.append(m)
            continue
        for item in pending:
            month, day = _words_parts(item)
            try:
                dates.add(date(int(year), month, day))
            except ValueError:
                malformed.append(item.group(0).strip().rstrip("."))
        taken.extend(pending)
        pending = []
    for m in reversed(taken):
        text = text[: m.start()] + " " + text[m.end() :]
    return text


def _tokenise(text: str, known_refs: Iterable[str] = ()) -> _Tokens:
    """Split `text` into dates, IBANs and numbers; each match is removed before the next pass."""
    dates: set[date] = set()
    malformed: list[str] = []
    numbers: list[str] = []

    ibans = tuple(m.group(0) for m in _IBAN_RE.finditer(text))
    text = _IBAN_RE.sub(" ", text)

    def _date_sub(order: tuple[int, int, int]):
        def _sub(m: re.Match[str]) -> str:
            y, mo, d = (int(m.group(i)) for i in order)
            try:
                dates.add(date(y, mo, d))
            except ValueError:
                malformed.append(m.group(0))
            return " "

        return _sub

    text = _DATE_ISO_RE.sub(_date_sub((1, 2, 3)), text)
    text = _DATE_EU_RE.sub(_date_sub((3, 2, 1)), text)

    def _words_sub(day_group: int, month_group: int):
        def _sub(m: re.Match[str]) -> str:
            month = _MONTH_NUMBER[m.group(month_group).lower()[:3]]
            try:
                dates.add(date(int(m.group(3)), month, int(m.group(day_group))))
            except ValueError:
                malformed.append(m.group(0))
            return " "

        return _sub

    text = _year_lists(text, dates, malformed)
    text = _DATE_MDY_RE.sub(_words_sub(2, 1), text)
    text = _DATE_DMY_RE.sub(_words_sub(1, 2), text)

    refs = sorted({r for r in known_refs if r}, key=len, reverse=True)
    if refs:
        ref_re = re.compile(r"(?<![\w.])(?:" + "|".join(re.escape(r) for r in refs) + r")(?!\d)")
        text = ref_re.sub(" ", text)

    partial: list[tuple[str, int, int]] = []

    def _partial_sub(month_group: int, day_group: int):
        def _sub(m: re.Match[str]) -> str:
            month = _MONTH_NUMBER[m.group(month_group).lower()[:3]]
            partial.append((m.group(0).strip().rstrip("."), month, int(m.group(day_group))))
            return " "

        return _sub

    text = _DATE_MD_PART_RE.sub(_partial_sub(1, 2), text)
    text = _DATE_DM_PART_RE.sub(_partial_sub(2, 1), text)

    for pattern in (_NUM_EU_RE, _NUM_PLAIN_RE):
        numbers.extend(pattern.findall(text))
        text = pattern.sub(" ", text)

    return _Tokens(frozenset(dates), tuple(malformed), ibans, tuple(numbers), tuple(partial))


def _parse_decimal(token: str) -> Decimal | None:
    """Parse a number token (European or plain) to Decimal; None on failure."""
    try:
        cleaned = token.replace(".", "").replace(",", ".") if "," in token else token
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _is_date_column(series: pd.Series) -> bool:
    """True when the column holds datetime.date cells (any column name)."""
    return any(isinstance(v, date) for v in series)


def _visible_rows(rows: pd.DataFrame, row_columns: Sequence[str] | None) -> pd.DataFrame:
    """Rows as the LLM sees them: the explicit selection, else everything except never-sent."""
    if row_columns is not None:
        return _select_llm_columns(rows, row_columns)
    return rows[[c for c in rows.columns if c not in _NEVER_SENT_COLUMNS]]


def _allowed_decimals(
    alert: Alert, rows: pd.DataFrame, row_columns: Sequence[str] | None = None
) -> set[Decimal]:
    """Build the set of Decimal values the LLM is permitted to use (visible columns only)."""
    rows = _visible_rows(rows, row_columns)
    refs = list(alert.source_refs)
    if "source_ref" in rows.columns:
        refs += [str(r) for r in rows["source_ref"]]

    allowed: set[Decimal] = set()

    def _add(text: str) -> None:
        for token in _tokenise(text, refs).numbers:
            value = _parse_decimal(token)
            if value is not None:
                allowed.add(value)

    for v in alert.data.values():
        _add(str(v))

    for col in rows.columns:
        if _is_date_column(rows[col]):  # date parts are handled by _allowed_dates
            continue
        for cell in rows[col]:
            _add(str(cell))

    return allowed


def _allowed_dates(
    alert: Alert, rows: pd.DataFrame, row_columns: Sequence[str] | None = None
) -> set[date]:
    """Build the set of dates the LLM may mention (visible date cells + Alert.data)."""
    rows = _visible_rows(rows, row_columns)
    dates: set[date] = set()
    for col in rows.columns:
        for cell in rows[col]:
            if isinstance(cell, date):
                dates.add(cell)
    for v in alert.data.values():
        if isinstance(v, date):
            dates.add(v)
        else:
            dates |= _tokenise(str(v)).dates
    return dates


def _passes_number_guard(
    text: str,
    alert: Alert,
    rows: pd.DataFrame,
    row_columns: Sequence[str] | None = None,
) -> tuple[bool, tuple[str, ...]]:
    """Check LLM text; return (passed, rejected_tokens)."""
    tokens = _tokenise(_without_non_figures(text, alert), alert.source_refs)
    if tokens.ibans:
        return False, tokens.ibans
    if tokens.malformed_dates:
        return False, tokens.malformed_dates
    allowed_dates = _allowed_dates(alert, rows, row_columns)
    bad_dates = [d.isoformat() for d in sorted(tokens.dates - allowed_dates)]
    # A date with no year anywhere is judged by month and day alone (REQ-LG-36).
    allowed_days = {(d.month, d.day) for d in allowed_dates}
    unknown_partial = (
        written for written, month, day in tokens.partial_dates if (month, day) not in allowed_days
    )
    bad_dates += dict.fromkeys(unknown_partial)
    if bad_dates:
        return False, tuple(bad_dates)

    allowed = _allowed_decimals(alert, rows, row_columns)
    rejected: list[str] = []
    for token in tokens.numbers:
        value = _parse_decimal(token)
        if value is not None and value not in allowed:
            rejected.append(token)
    rejected.extend(_foreign_currencies(text, alert, _visible_rows(rows, row_columns)))
    if rejected:
        return False, tuple(rejected)
    return True, ()


# --- Numbers that are not figures (row citations, counts of cited rows, list markers) -----------

# A whole integer: not part of a longer number, a date, a ref or a hyphenated code.
_INT = r"(?<![\d.,:/-])\d+(?!\d|[.,]\d|[/-]\d)"
# "rows 181, 236, and 292": a list of integers after the keyword. A range of two integers
# ("9 to 312", "9 through 312", "9-312" with a hyphen or an en dash) is one member of the list
# (REQ-LG-37).
_CITE_SEPARATOR = r"(?:,\s+(?:(?:and|or)\s+)?|\s+(?:and|or)\s+|\s*&\s*)"
_RANGE_SEPARATOR = r"(?:\s+(?:to|through)\s+|\s*[-\u2013]\s*)"
_RANGE_START = r"(?<![\d.,:/-])(\d+)(?!\d|[.,]\d)"
_RANGE_END = r"(\d+)(?!\d|[.,]\d|[/-]\d)"
_CITE_ITEM = "(?:" + _RANGE_START + _RANGE_SEPARATOR + _RANGE_END + "|" + _INT + ")"
_ROW_CITATION_RE = re.compile(
    r"\b(?:rows?|lines?)\s+(" + _CITE_ITEM + "(?:" + _CITE_SEPARATOR + _CITE_ITEM + ")*)",
    re.IGNORECASE,
)
# One member of the list above: groups 1 and 2 are the ends of a range, group 3 a single integer.
_CITE_ITEM_RE = re.compile(
    _RANGE_START + _RANGE_SEPARATOR + _RANGE_END + "|(" + _INT + ")", re.IGNORECASE
)
# "the 8th row": an ordinal right before row or line.
_ORDINAL_ROW_RE = re.compile(
    r"(?<![\w.,:/-])(\d+)(?:st|nd|rd|th)\s+(?:rows?|lines?)\b", re.IGNORECASE
)
# "12 debit transactions": the count of cited rows, one optional adjective (not an ISO code).
_COUNT_NOUN = r"(?:rows?|transactions?|charges?|payments?|debits?|entr(?:y|ies)|invoices?|times?)"
_COUNT_OF_ROWS_RE = re.compile(
    "(" + _INT + r")(\s+(?:(?!(?-i:[A-Z]{3}\b))[A-Za-z]+\s+)?" + _COUNT_NOUN + r"\b)",
    re.IGNORECASE,
)
# "1. " or "2) " at the start of a line: a list marker of one or two digits.
_LIST_MARKER_RE = re.compile(r"^\d{1,2}[.)](?= )", re.MULTILINE)
_MAX_INT_DIGITS = 9  # longer integers are never row numbers or counts


def _as_int(token: str) -> int | None:
    """Return the integer value of a short digit string, else None."""
    return int(token) if token.isascii() and 0 < len(token) <= _MAX_INT_DIGITS else None


def _cited_line_numbers(alert: Alert) -> frozenset[int]:
    """Line numbers of the alert's own source refs ('file.csv:181' gives 181)."""
    numbers = (_as_int(ref.rpartition(":")[2]) for ref in alert.source_refs)
    return frozenset(n for n in numbers if n is not None)


def _without_non_figures(text: str, alert: Alert) -> str:
    """Blank out the numbers that cite a row, count the cited rows or number a list.

    Only the three exact forms are blanked; every other number keeps the strict rule.
    """
    lines = _cited_line_numbers(alert)
    cited_count = len(alert.source_refs)

    def _blank_cited(match: re.Match[str]) -> str:
        return " " if _as_int(match.group(0)) in lines else match.group(0)

    def _blank_item(match: re.Match[str]) -> str:
        if match.group(3) is not None:  # a single integer: judged on its own
            return _blank_cited(match)
        start, end = _as_int(match.group(1)), _as_int(match.group(2))
        if start in lines and end in lines:  # a range between two cited lines: both are citations
            return " "
        # Any other range keeps today's rule: only its first number, right after the keyword or a
        # separator, is a citation when it is a cited line; the end is a figure like any other.
        if start in lines:
            return " " + match.group(0)[match.end(1) - match.start(0) :]
        return match.group(0)

    def _row_citation(match: re.Match[str]) -> str:
        head = match.group(0)[: match.start(1) - match.start(0)]
        return head + _CITE_ITEM_RE.sub(_blank_item, match.group(1))

    def _ordinal_row(match: re.Match[str]) -> str:
        if _as_int(match.group(1)) not in lines:
            return match.group(0)
        return " " + match.group(0)[len(match.group(1)) :]

    def _count(match: re.Match[str]) -> str:
        return " " + match.group(2) if _as_int(match.group(1)) == cited_count else match.group(0)

    text = _ROW_CITATION_RE.sub(_row_citation, text)
    text = _ORDINAL_ROW_RE.sub(_ordinal_row, text)
    if cited_count:
        text = _COUNT_OF_ROWS_RE.sub(_count, text)
    return _LIST_MARKER_RE.sub("", text)


# --- Currency ------------------------------------------------------------------------------

_CURRENCY_CODES = frozenset(NUMERIC_TO_ALPHA.values())  # the codes iso4217.py knows
_DOLLAR_CODES = frozenset({"USD", "CAD", "AUD", "NZD"})  # codes written with a dollar sign
_SYMBOL_CODES: dict[str, frozenset[str]] = {
    "€": frozenset({"EUR"}),
    "$": _DOLLAR_CODES,
    "£": frozenset({"GBP"}),
    "¥": frozenset({"JPY"}),
}
_CURRENCY_TOKEN_RE = re.compile(
    "[" + re.escape("".join(_SYMBOL_CODES)) + r"]|(?<![A-Za-z])[A-Z]{3}(?![A-Za-z])"
)


def _named_currencies(alert: Alert, rows: pd.DataFrame) -> tuple[set[str], set[str]]:
    """Currency codes and symbols named by the alert data and the `currency` column of the rows."""
    codes: set[str] = set()
    symbols: set[str] = set()

    def _scan(text: str) -> None:
        for token in _CURRENCY_TOKEN_RE.findall(text):
            if token in _SYMBOL_CODES:
                symbols.add(token)
            elif token in _CURRENCY_CODES:
                codes.add(token)

    for value in alert.data.values():
        _scan(str(value))
    if "currency" in rows.columns:
        for cell in rows["currency"]:
            if cell is None or (not isinstance(cell, str) and pd.isna(cell)):
                continue  # a missing cell names no currency
            text = str(cell).strip().upper()
            if not text:
                continue
            if text in _CURRENCY_CODES:
                codes.add(text)
            _scan(str(cell))
    return codes, symbols


def _foreign_currencies(text: str, alert: Alert, rows: pd.DataFrame) -> list[str]:
    """Currency symbols and ISO codes in `text` that the rows and the alert data do not name.

    With no currency named anywhere the check is skipped (nothing to compare with).
    """
    codes, symbols = _named_currencies(alert, rows)
    if not codes and not symbols:
        return []
    foreign: list[str] = []
    for token in _CURRENCY_TOKEN_RE.findall(text):
        if token in _SYMBOL_CODES:
            named = token in symbols or bool(codes & _SYMBOL_CODES[token])
        elif token in _CURRENCY_CODES:
            named = token in codes or any(token in _SYMBOL_CODES[s] for s in symbols)
        else:
            continue  # three capital letters that are not a currency
        if not named and token not in foreign:
            foreign.append(token)
    return foreign


# --- LLM call -----------------------------------------------------------------------------


def _call_llm(
    alert: Alert, rows: pd.DataFrame, *, client=None, question: str | None = None
) -> str | None:
    """Call the LLM once; any failure returns None so the caller uses the fallback."""
    model = os.environ.get("LEDGER_KIT_LLM_MODEL", "gpt-4o-mini")
    system_prompt = (
        "You must not invent any number, date, name, or amount. "
        "Every figure you mention must appear verbatim either in the source rows "
        "provided or in the structured fields of the alert (such as yearly_cost). "
        "Do not derive, round, or estimate any figure not explicitly present in "
        "those inputs. "
        f"Cite at least one source reference from: {alert.source_refs}. "
        "Answer in plain prose of at most three sentences: no lists, no JSON, no repetition "
        "of the input. Write source references exactly as given. "
        "Write every date exactly as given, in YYYY-MM-DD form."
    )
    # pandas date_format="iso" would render date cells as "...T00:00:00.000", so every
    # date-holding column is mapped to plain ISO strings first (missing values stay None).
    rows = rows.copy()
    for col in rows.columns:
        if _is_date_column(rows[col]):
            rows[col] = rows[col].map(lambda d: d.isoformat() if isinstance(d, date) else None)
    rows_json = rows.to_json(orient="records", default_handler=str)
    user_content = f"Alert: {alert.model_dump_json()}\n\nSource rows:\n{rows_json}"
    if question:
        user_content += "\n\nQuestion from the user: " + question

    for attempt in range(LLM_MAX_RETRIES):
        try:
            if client is None:
                import openai  # lazy + inside the try: the openai extra is optional

                client = openai.OpenAI(
                    base_url=os.environ.get("OPENAI_BASE_URL") or None,
                    api_key=os.environ["OPENAI_API_KEY"],
                    timeout=llm_timeout_seconds(),
                    max_retries=0,  # SDK default is 2; LLM_MAX_RETRIES is the only retry knob
                )
            response = client.chat.completions.create(
                model=model,
                temperature=0,
                max_tokens=LLM_MAX_TOKENS,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
            )
            return response.choices[0].message.content or None
        except Exception as exc:
            _log.warning("LLM call attempt %d/%d failed: %s", attempt + 1, LLM_MAX_RETRIES, exc)
    return None
