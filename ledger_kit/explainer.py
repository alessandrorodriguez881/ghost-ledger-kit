"""LLM explanation layer: the only module in ledger_kit that may call an LLM (design §4a)."""

import logging
import os
import re
import string
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal

import pandas as pd

from ledger_kit.models import Alert
from ledger_kit.utils.money import format_amount, format_index, format_percent

# Streamlit renders alerts synchronously: keep the LLM call short.
LLM_TIMEOUT_SECONDS: int = 10  # seconds before giving up
LLM_MAX_RETRIES: int = 1  # one attempt; callers cache per alert.id

# Default columns sent to the LLM (minimum data, Finance Rule 5 / REQ-EXP-11).
_LLM_ROW_COLUMNS = ("date", "amount", "flow", "currency", "counterparty", "source_ref")
# Dropped even if a caller lists them (defence in depth).
_NEVER_SENT_COLUMNS = frozenset({"id", "description", "iban"})

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Explanation:
    """Result of explain_with_meta(). `source` is 'llm' or 'fallback'."""

    text: str
    source: Literal["llm", "fallback"]
    rejected_numbers: tuple[str, ...]  # tokens the guard found and rejected


def explain(
    alert: Alert,
    rows: pd.DataFrame,
    *,
    fallback_template: str,
    client=None,
    row_columns: Sequence[str] | None = None,
) -> str:
    """Return a plain-English explanation for `alert` (guarded text only)."""
    return explain_with_meta(
        alert,
        rows,
        fallback_template=fallback_template,
        client=client,
        row_columns=row_columns,
    ).text


def explain_with_meta(
    alert: Alert,
    rows: pd.DataFrame,
    *,
    fallback_template: str,
    client=None,
    row_columns: Sequence[str] | None = None,
) -> Explanation:
    """Return an Explanation; falls back to the filled template on any error or rejection."""
    narrow_rows = _select_llm_columns(rows, row_columns)
    fallback = fill_fallback(fallback_template, alert)

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key and client is None:
        return Explanation(text=fallback, source="fallback", rejected_numbers=())

    raw = _call_llm(alert, narrow_rows, client=client)
    if raw is None:
        return Explanation(text=fallback, source="fallback", rejected_numbers=())

    ok, rejected = _passes_number_guard(raw, alert, narrow_rows, row_columns)
    if not ok:
        _log.warning("Number guard rejected LLM response for alert %s: %s", alert.id, rejected)
        return Explanation(text=fallback, source="fallback", rejected_numbers=rejected)

    return Explanation(text=raw, source="llm", rejected_numbers=())


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
_NUM_EU_RE = re.compile(r"(?<!\d)(?:\d{1,3}(?:\.\d{3})+|\d+),\d+(?!\d)")
_NUM_PLAIN_RE = re.compile(r"(?<!\d)\d+(?:\.\d+)?(?!\d)")


@dataclass(frozen=True)
class _Tokens:
    """Result of _tokenise(): everything numeric found in one string."""

    dates: frozenset[date]
    malformed_dates: tuple[str, ...]
    ibans: tuple[str, ...]
    numbers: tuple[str, ...]


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

    refs = sorted({r for r in known_refs if r}, key=len, reverse=True)
    if refs:
        ref_re = re.compile(r"(?<![\w.])(?:" + "|".join(re.escape(r) for r in refs) + r")(?!\d)")
        text = ref_re.sub(" ", text)

    for pattern in (_NUM_EU_RE, _NUM_PLAIN_RE):
        numbers.extend(pattern.findall(text))
        text = pattern.sub(" ", text)

    return _Tokens(frozenset(dates), tuple(malformed), ibans, tuple(numbers))


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
    tokens = _tokenise(text, alert.source_refs)
    if tokens.ibans:
        return False, tokens.ibans
    if tokens.malformed_dates:
        return False, tokens.malformed_dates
    bad_dates = tokens.dates - _allowed_dates(alert, rows, row_columns)
    if bad_dates:
        return False, tuple(sorted(d.isoformat() for d in bad_dates))

    allowed = _allowed_decimals(alert, rows, row_columns)
    rejected: list[str] = []
    for token in tokens.numbers:
        value = _parse_decimal(token)
        if value is not None and value not in allowed:
            rejected.append(token)
    if rejected:
        return False, tuple(rejected)
    return True, ()


# --- LLM call -----------------------------------------------------------------------------


def _call_llm(alert: Alert, rows: pd.DataFrame, *, client=None) -> str | None:
    """Call the LLM once; any failure returns None so the caller uses the fallback."""
    model = os.environ.get("LEDGER_KIT_LLM_MODEL", "gpt-4o-mini")
    system_prompt = (
        "You must not invent any number, date, name, or amount. "
        "Every figure you mention must appear verbatim either in the source rows "
        "provided or in the structured fields of the alert (such as yearly_cost). "
        "Do not derive, round, or estimate any figure not explicitly present in "
        "those inputs. "
        f"Cite at least one source reference from: {alert.source_refs}."
    )
    # pandas date_format="iso" would render date cells as "...T00:00:00.000", so every
    # date-holding column is mapped to plain ISO strings first (missing values stay None).
    rows = rows.copy()
    for col in rows.columns:
        if _is_date_column(rows[col]):
            rows[col] = rows[col].map(lambda d: d.isoformat() if isinstance(d, date) else None)
    rows_json = rows.to_json(orient="records", default_handler=str)
    user_content = f"Alert: {alert.model_dump_json()}\n\nSource rows:\n{rows_json}"

    for attempt in range(LLM_MAX_RETRIES):
        try:
            if client is None:
                import openai  # lazy + inside the try: the openai extra is optional

                client = openai.OpenAI(
                    base_url=os.environ.get("OPENAI_BASE_URL") or None,
                    api_key=os.environ["OPENAI_API_KEY"],
                    timeout=LLM_TIMEOUT_SECONDS,
                    max_retries=0,  # SDK default is 2; LLM_MAX_RETRIES is the only retry knob
                )
            response = client.chat.completions.create(
                model=model,
                temperature=0,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
            )
            return response.choices[0].message.content or None
        except Exception as exc:
            _log.warning("LLM call attempt %d/%d failed: %s", attempt + 1, LLM_MAX_RETRIES, exc)
    return None
