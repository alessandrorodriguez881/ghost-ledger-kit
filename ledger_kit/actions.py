"""Exorcise (spec exorcise): turn an alert into the draft of the real action to take.

A draft is a fixed template filled from ``Alert.data``, the cited rows and a few computed lines
(``extras``). No language model is involved, so it works without a key and cannot invent a figure.
As a second line of defence ``build_draft`` runs the draft through the number guard
(``explainer.check_figures``): a draft that cites a figure, date or IBAN that the alert and its
rows do not hold is not returned, and the reason is logged.

The module is pure: no Streamlit, no I/O, no clock, no model. Amounts are only formatted with
``ledger_kit/utils/money.py``; nothing is computed here.
"""

from __future__ import annotations

import logging
import re
import string
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import pandas as pd

from ledger_kit.explainer import check_figures
from ledger_kit.models import Alert
from ledger_kit.utils.money import format_amount, format_percent

_log = logging.getLogger(__name__)

# (code, label) of the languages of a draft, English first (the default).
LANGUAGES: tuple[tuple[str, str], ...] = (("en", "English"), ("es", "Español"))
DEFAULT_LANGUAGE: str = "en"
# A draft is short: this is what the demo test proves for every demo alert (REQ-EX-09).
MAX_DRAFT_WORDS: int = 150
# Used when a cited row names no currency (the pipelines keep one currency per statement).
DEFAULT_CURRENCY: str = "EUR"

# Exactly two full stops in a row: a value ending in "." followed by the template's own ".".
_DOUBLE_STOP: re.Pattern[str] = re.compile(r"(?<!\.)\.\.(?!\.)")

EXPANDER_TITLE: str = "Exorcise: prepare the action"
LANGUAGE_LABEL: str = "Language"
DRAFT_LABEL: dict[str, str] = {"en": "Draft", "es": "Borrador"}
DOWNLOAD_LABEL: dict[str, str] = {"en": "Download .txt", "es": "Descargar .txt"}
DISCLAIMER: dict[str, str] = {
    "en": "This is a draft to review, not legal advice.",
    "es": "Este es un borrador para revisar, no es asesoramiento legal.",
}
UNAVAILABLE: dict[str, str] = {
    "en": (
        "This draft is not available: a figure in it could not be checked against the cited rows."
    ),
    "es": (
        "Este borrador no está disponible: no se pudo comprobar una cifra con las filas citadas."
    ),
}

# Computed lines of one template: (alert, cited rows, language) -> {placeholder: text}.
Extras = Callable[[Alert, pd.DataFrame, str], Mapping[str, str]]


@dataclass(frozen=True)
class ActionTemplate:
    """The fixed texts of one alert type, one per language, and the lines computed for them."""

    name: str
    texts: Mapping[str, str]  # language code -> text with {placeholders}
    extras: Extras | None = None


def _times(count: Decimal, language: str) -> str:
    """Write a whole count as '1 time' / '3 times' (or '1 vez' / '3 veces'); else as text."""
    if count != count.to_integral_value():
        return str(count)
    number = int(count)
    if language == "es":
        return f"{number} vez" if number == 1 else f"{number} veces"
    return f"{number} time" if number == 1 else f"{number} times"


class _Formatter(string.Formatter):
    """Resolve {key} from the extras, then from Alert.data; {key:money|pct|times} format it."""

    def __init__(self, alert: Alert, extras: Mapping[str, str], language: str) -> None:
        super().__init__()
        self._data = alert.data
        self._extras = extras
        self._language = language

    def get_value(self, key: Any, args: Any, kwargs: Any) -> Any:
        """Return the value of a placeholder; an unknown one is a KeyError."""
        if not isinstance(key, str):
            raise KeyError(key)
        if key in self._extras:
            return self._extras[key]
        if key in self._data:
            return self._data[key]
        raise KeyError(key)

    def format_field(self, value: Any, format_spec: str) -> str:
        """Format a resolved value; a non-number under a number spec is an error."""
        if not format_spec:
            return str(value)
        if format_spec not in ("money", "pct", "times"):
            raise ValueError(f"unknown format spec {format_spec!r}")
        try:
            number = Decimal(str(value))
        except InvalidOperation:
            raise ValueError(f"{value!r} is not a number for the spec {format_spec!r}") from None
        if format_spec == "money":
            return format_amount(number)
        if format_spec == "pct":
            return format_percent(number)
        return _times(number, self._language)


def fill(
    template: str, alert: Alert, language: str, extras: Mapping[str, str] | None = None
) -> str:
    """Fill a template; KeyError for an unknown placeholder, ValueError for a bad spec.

    A value that already ends with a full stop (``S.L.``) followed by the template's own full
    stop gives one full stop, not two. A run of three or more dots (an ellipsis) is left alone.
    """
    text = _Formatter(alert, extras or {}, language).vformat(template, (), {})
    return _DOUBLE_STOP.sub(".", text)


def _as_date(cell: Any) -> date | None:
    """Return the calendar date of a cell, or None when it holds none."""
    if isinstance(cell, datetime):
        return cell.date()
    return cell if isinstance(cell, date) else None


def _as_currency(cell: Any) -> str:
    """Return the currency code of a cell, or the default when the cell names none."""
    if isinstance(cell, str) and cell.strip():
        return cell.strip().upper()
    return DEFAULT_CURRENCY


def row_lines(rows: pd.DataFrame) -> str:
    """Write one 'date: amount' line per cited row, in date order; '' when there is no row.

    The date is ISO text and the amount the European text of the card. A row without a date or
    without an amount cannot be cited, so it raises ValueError (the draft is then not shown)
    rather than leave a row out of a list that says it is complete.
    """
    if rows.empty:
        return ""
    cited: list[tuple[date, str]] = []
    for record in rows.to_dict("records"):
        day = _as_date(record.get("date"))
        if day is None:
            raise ValueError(f"row {record.get('source_ref')!r} has no date")
        try:
            amount = Decimal(str(record.get("amount")))
        except InvalidOperation:
            raise ValueError(f"row {record.get('source_ref')!r} has no amount") from None
        currency = _as_currency(record.get("currency"))
        cited.append((day, f"{day.isoformat()}: {format_amount(amount, currency)}"))
    cited.sort(key=lambda item: item[0])  # stable: the frame order breaks ties
    return "\n".join(line for _day, line in cited)


def file_name(alert: Alert, language: str) -> str:
    """Return the download name: exorcise-<detector>-<language>-<first 8 of the alert id>.txt."""
    slug = alert.detector.replace(".", "-").replace("_", "-")
    return f"exorcise-{slug}-{language}-{alert.id[:8]}.txt"


def word_count(text: str) -> int:
    """Count the pieces of a text between spaces (REQ-EX-09)."""
    return len(text.split())


def build_draft(
    alert: Alert,
    rows: pd.DataFrame,
    template: ActionTemplate,
    language: str,
    *,
    row_columns: tuple[str, ...] | None = None,
) -> str | None:
    """Return the checked draft, or None (with one warning) when it cannot be shown.

    The draft is None when the template lacks the language or a placeholder, when a value is not
    a number where a number is needed, or when the number guard rejects a figure, a date or an
    IBAN-shaped token of the text. It never raises for those reasons.
    """
    try:
        text = template.texts[language]
        extras = {} if template.extras is None else template.extras(alert, rows, language)
        draft = fill(text, alert, language, extras).strip()
    except (KeyError, ValueError, ArithmeticError) as error:
        _log.warning(
            "Exorcise draft not built for alert %s (%s, %s): %r",
            alert.id,
            template.name,
            language,
            error,
        )
        return None
    passed, rejected = check_figures(draft, alert, rows, row_columns)
    if not passed:
        _log.warning(
            "Exorcise draft rejected by the number guard for alert %s (%s, %s): %s",
            alert.id,
            template.name,
            language,
            ", ".join(rejected),
        )
        return None
    return draft
