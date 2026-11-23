"""Constants, text folding, vocabulary and fee helpers for the vampire-fees app (design 2 and 4)."""

import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, TypeVar

import pandas as pd

from ledger_kit.public_data import ACCOUNT_TYPES, SERVICES, FeeSnapshot
from ledger_kit.utils.money import median_amount, round_to_cents

T = TypeVar("T")

# --- Constants (design 2.1); every threshold that influences an alert lives here ----------------

# --- What is considered ---
# Only EUR rows are analysed: the explainer's ':money' format is EUR-only and amounts in
# different currencies are never added (DN-VF-07).
STATEMENT_CURRENCY: str = "EUR"
# Norma 43 common concepts accepted as fees: 16 stamp duty and brokerage, 17 interest, fees, taxes.
FEE_CONCEPTS: tuple[str, ...] = ("16", "17")
# Prefix of the tag the Norma 43 reader writes into Transaction.tags.
CONCEPT_TAG_PREFIX: str = "common_concept:"

# --- Recurring interval (days) ---
# Nominal length of a month, a quarter and a year.
MONTHLY_NOMINAL_DAYS: int = 30
QUARTERLY_NOMINAL_DAYS: int = 91
YEARLY_NOMINAL_DAYS: int = 365
# Slack around the nominal gap: calendar months are 28 to 31 days and bookings move with
# weekends and bank holidays; the three ranges never overlap, so the type is unambiguous.
MONTHLY_TOLERANCE_DAYS: int = 3
QUARTERLY_TOLERANCE_DAYS: int = 3
# A year is 365 or 366 days and annual fees are charged "in the month of the anniversary".
YEARLY_TOLERANCE_DAYS: int = 5
# Two monthly charges can be two one-off commissions a month apart; three make a series.
MIN_CHARGES_MONTHLY: int = 3
# A statement of one to two years shows one or two quarterly or yearly fees; the gap check is
# the guard against coincidence.
MIN_CHARGES_QUARTERLY: int = 2
MIN_CHARGES_YEARLY: int = 2
# Definition of the interval; yearly_cost = current_amount x periods per year.
PERIODS_PER_YEAR_MONTHLY: int = 12
PERIODS_PER_YEAR_QUARTERLY: int = 4
PERIODS_PER_YEAR_YEARLY: int = 1

# --- Severities and rises ---
# A fee costing 5.00 a month (60.00 a year) is worth a second look; below it the alert is info.
RECURRING_FEE_WARNING_YEARLY_COST: Decimal = Decimal("60.00")
# Smallest rise (5 %) that is not rounding noise of a percentage or index-linked fee.
FEE_INCREASE_MIN_RATIO: Decimal = Decimal("0.05")
# The new level "holds" when later charges stay within 2 % of it; a single spike is not a price.
FEE_STABLE_RATIO: Decimal = Decimal("0.02")
# A fee that rises by half or more is out of line with any inflation-linked update.
FEE_INCREASE_CRITICAL_RATIO: Decimal = Decimal("0.50")
# More than a year of a typical maintenance fee: the overdraft is then the biggest bank cost.
OVERDRAFT_CRITICAL_TOTAL: Decimal = Decimal("100.00")

# --- Summary ---
# Plain year, no leap-year correction: the equivalent is an annualisation.
DAYS_PER_YEAR: int = 365
# Under a quarter a fee cycle can be missing or doubled; a yearly figure would be a guess.
SUMMARY_MIN_SPAN_DAYS: int = 90
# About 16.67 EUR a month in bank fees: heavier than any single recurring fee of a normal account.
SUMMARY_WARNING_YEARLY_EQUIVALENT: Decimal = Decimal("200.00")

# --- Fee comparison with the Banco de España (public-fees); they decide no alert ----------------
# Fewest accounts with a declared amount for which the comparison sentence is shown (DN-PF-07).
PEER_MIN_ACCOUNTS: int = 10
# Most days between the last charge of the fee and the declaration date of the snapshot, in either
# direction; a fee run older than a year would be compared with another period (DN-PF-08).
PEER_MAX_DATE_GAP_DAYS: int = 365
# The source named by the `peer_source` field of an alert (REQ-PF-12).
PEER_SOURCE: str = "Banco de España, Comisiones de Cuentas de Pago"

IntervalName = Literal["monthly", "quarterly", "yearly"]


@dataclass(frozen=True)
class Interval:
    """One interval type: nominal gap, tolerance, minimum run length and periods per year."""

    name: IntervalName
    nominal_days: int
    tolerance_days: int
    min_charges: int
    periods_per_year: int


# Monthly, quarterly, yearly in this order (REQ-VF-16).
INTERVALS: tuple[Interval, ...] = (
    Interval(
        "monthly",
        MONTHLY_NOMINAL_DAYS,
        MONTHLY_TOLERANCE_DAYS,
        MIN_CHARGES_MONTHLY,
        PERIODS_PER_YEAR_MONTHLY,
    ),
    Interval(
        "quarterly",
        QUARTERLY_NOMINAL_DAYS,
        QUARTERLY_TOLERANCE_DAYS,
        MIN_CHARGES_QUARTERLY,
        PERIODS_PER_YEAR_QUARTERLY,
    ),
    Interval(
        "yearly",
        YEARLY_NOMINAL_DAYS,
        YEARLY_TOLERANCE_DAYS,
        MIN_CHARGES_YEARLY,
        PERIODS_PER_YEAR_YEARLY,
    ),
)

# Maximum folding passes: folding is repeated until the text stops changing.
_MAX_FOLD_PASSES = 4
VOCABULARY_KEYS: tuple[str, ...] = ("fee", "overdraft", "interest", "exclude")

Phrase = tuple[str, ...]


# --- Text folding and vocabulary (design 4.1) --------------------------------------------------


def _fold_once(text: str) -> str:
    """Apply NFKD, drop combining marks and case-fold once."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return stripped.casefold()


def _is_missing(value: object) -> bool:
    """Return True for None and for the NaN / NA markers of pandas."""
    if value is None:
        return True
    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        return False
    return bool(missing) if getattr(missing, "ndim", 0) == 0 else False


def fold_tokens(text: object) -> tuple[str, ...]:
    """Fold text (NFKD, no marks, case-folded, non-alphanumerics as spaces) and split it."""
    if isinstance(text, str):
        value = text
    elif _is_missing(text):
        return ()
    else:
        value = str(text)
    for _ in range(_MAX_FOLD_PASSES):
        folded = _fold_once(value)
        if folded == value:
            break
        value = folded
    cleaned = "".join(ch if ch.isalnum() else " " for ch in value)
    return tuple(cleaned.split())


@dataclass(frozen=True)
class FeeVocabulary:
    """Folded phrases of the four vocabulary keys; each phrase is a tuple of tokens."""

    fee: tuple[Phrase, ...]
    overdraft: tuple[Phrase, ...]
    interest: tuple[Phrase, ...]
    exclude: tuple[Phrase, ...]


EMPTY_VOCABULARY = FeeVocabulary((), (), (), ())


def build_vocabulary(table: Mapping[str, Any]) -> FeeVocabulary:
    """Fold every phrase of the four keys; ValueError naming the key when one is invalid."""
    folded: dict[str, tuple[Phrase, ...]] = {}
    for key in VOCABULARY_KEYS:
        if not isinstance(table, Mapping) or key not in table:
            raise ValueError(f"vocabulary key {key!r} is missing")
        raw = table[key]
        if not isinstance(raw, (list, tuple)) or not raw:
            raise ValueError(f"vocabulary key {key!r} must be a non-empty list of strings")
        phrases: list[Phrase] = []
        for item in raw:
            if not isinstance(item, str):
                raise ValueError(f"vocabulary key {key!r} holds a non-string: {item!r}")
            tokens = fold_tokens(item)
            if not tokens:
                raise ValueError(f"vocabulary key {key!r} holds a phrase with no letter: {item!r}")
            phrases.append(tokens)
        folded[key] = tuple(phrases)
    return FeeVocabulary(**folded)


def contains_phrase(tokens: Sequence[str], phrases: Sequence[Phrase]) -> bool:
    """Return True when any phrase appears as consecutive tokens."""
    for phrase in phrases:
        size = len(phrase)
        if size == 0 or size > len(tokens):
            continue
        for start in range(len(tokens) - size + 1):
            if tuple(tokens[start : start + size]) == tuple(phrase):
                return True
    return False


# --- Services of the fee comparison (public-fees design 6.2) ----------------------------------

# Only concepts that are an annual total are compared, so the sentence can say "annual".
ANNUAL_TOTAL_TOKENS: Phrase = ("anual", "total")


@dataclass(frozen=True)
class PeerService:
    """One compared Banco de España service of [peer_fees]; phrases are folded."""

    key: str  # the sub-table name, e.g. "maintenance"
    service_code: str  # e.g. "101"
    concept: str  # the published concept, verbatim
    label: str  # English words for the sentence
    words: tuple[Phrase, ...]
    exclude: tuple[Phrase, ...]


@dataclass(frozen=True)
class PeerContext:
    """The snapshot, the account type to compare with and the [peer_fees] services (no I/O)."""

    snapshot: FeeSnapshot
    account_type: str  # a Banco de España code such as "CNO"
    services: tuple[PeerService, ...]


def _peer_phrases(key: str, name: str, raw: object, *, required: bool) -> tuple[Phrase, ...]:
    """Fold the `name` list of the peer service `key`; ValueError naming the key."""
    if raw is None and not required:
        return ()
    if not isinstance(raw, (list, tuple)) or (required and not raw):
        raise ValueError(f"peer service {key!r}: {name} must be a non-empty list of strings")
    phrases: list[Phrase] = []
    for item in raw:
        if not isinstance(item, str):
            raise ValueError(f"peer service {key!r}: {name} holds a non-string: {item!r}")
        tokens = fold_tokens(item)
        if not any(ch.isalpha() for token in tokens for ch in token):
            raise ValueError(
                f"peer service {key!r}: {name} holds a phrase with no letter: {item!r}"
            )
        phrases.append(tokens)
    return tuple(phrases)


def _peer_text(key: str, name: str, value: object) -> str:
    """Return a non-empty text field of the peer service `key`; ValueError naming the key."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"peer service {key!r}: {name} is missing or empty")
    return value


def build_peer_services(table: Mapping[str, Any]) -> tuple[PeerService, ...]:
    """Fold the sub-tables of [peer_fees] into services; ValueError naming the key when invalid."""
    if not isinstance(table, Mapping):
        raise ValueError("peer_fees must be a table")
    default = table.get("default_account_type")
    if default is not None and (not isinstance(default, str) or default not in ACCOUNT_TYPES):
        raise ValueError(
            f"peer_fees: default_account_type {default!r} is not a Banco de España account type"
        )
    services: list[PeerService] = []
    for key, sub in table.items():
        if not isinstance(sub, Mapping):
            continue
        code = sub.get("service")
        if not isinstance(code, str) or code not in SERVICES:
            raise ValueError(f"peer service {key!r}: {code} is not a Banco de España service code")
        concept = _peer_text(key, "concept", sub.get("concept"))
        if not contains_phrase(fold_tokens(concept), (ANNUAL_TOTAL_TOKENS,)):
            raise ValueError(f"peer service {key!r}: concept must be an annual total")
        label = _peer_text(key, "label", sub.get("label"))
        words = _peer_phrases(key, "words", sub.get("words"), required=True)
        exclude = _peer_phrases(key, "exclude", sub.get("exclude"), required=False)
        services.append(PeerService(key, code, concept, label, words, exclude))
    return tuple(services)


def concept_of(tags: object) -> str | None:
    """Return the cc of the first 'common_concept:<cc>' tag; None for no tags, None or NaN."""
    if isinstance(tags, str) or not hasattr(tags, "__iter__"):
        return None
    for tag in tags:  # type: ignore[attr-defined]
        if isinstance(tag, str) and tag.startswith(CONCEPT_TAG_PREFIX):
            concept = tag[len(CONCEPT_TAG_PREFIX) :].strip()
            if concept:
                return concept
    return None


def series_key(counterparty: object, description: object) -> str:
    """Return '<counterparty tokens>|<description tokens>' with digit-bearing tokens dropped."""

    def keep(text: object) -> str:
        return " ".join(t for t in fold_tokens(text) if not any(ch.isdigit() for ch in t))

    return f"{keep(counterparty)}|{keep(description)}"


# --- Classification and extraction (design 4.2) ---------------------------------------------------


@dataclass(frozen=True)
class Fee:
    """One fee row accepted by the classifier."""

    source_ref: str
    source_row: int
    date: date
    amount: Decimal
    counterparty: str
    description: str
    kind: Literal["overdraft", "other"]
    overdraft_interest: bool
    key: str


def _text(value: object) -> str:
    """Return the raw text of a cell; empty for a missing value."""
    if isinstance(value, str):
        return value
    return "" if _is_missing(value) else str(value)


def _as_date(value: object) -> date:
    """Return a datetime.date from a date or a pandas Timestamp."""
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise TypeError(f"not a date: {value!r}")


def _as_decimal(value: object) -> Decimal:
    """Return a Decimal from a Decimal or from its text; never through float."""
    return value if isinstance(value, Decimal) else Decimal(str(value))


def classify_fee(row: Mapping[str, Any], vocabulary: FeeVocabulary) -> Fee | None:
    """Return the Fee of a debit EUR row accepted by the concept or vocabulary rule, else None."""
    if row.get("flow") != "debit" or row.get("currency") != STATEMENT_CURRENCY:
        return None
    counterparty = _text(row.get("counterparty"))
    description = _text(row.get("description"))
    fields = (fold_tokens(counterparty), fold_tokens(description))
    by_concept = concept_of(row.get("tags")) in FEE_CONCEPTS
    if not by_concept:
        if any(contains_phrase(tokens, vocabulary.exclude) for tokens in fields):
            return None
        words = vocabulary.fee + vocabulary.overdraft
        if not any(contains_phrase(tokens, words) for tokens in fields):
            return None
    is_overdraft = any(contains_phrase(tokens, vocabulary.overdraft) for tokens in fields)
    has_interest = any(contains_phrase(tokens, vocabulary.interest) for tokens in fields)
    return Fee(
        source_ref=str(row["source_ref"]),
        source_row=int(row["source_row"]),
        date=_as_date(row["date"]),
        amount=_as_decimal(row["amount"]),
        counterparty=counterparty,
        description=description,
        kind="overdraft" if is_overdraft else "other",
        overdraft_interest=is_overdraft and has_interest,
        key=series_key(counterparty, description),
    )


def match_peer_service(fee: Fee, services: Sequence[PeerService]) -> PeerService | None:
    """Return the one service whose words the fee names (REQ-PF-10), else None (fail-safe).

    Two or more services named, an exclusion word of the one service, or no service: None.
    """
    fields = (fold_tokens(fee.counterparty), fold_tokens(fee.description))
    named = [s for s in services if any(contains_phrase(t, s.words) for t in fields)]
    if len(named) != 1:
        return None
    service = named[0]
    if any(contains_phrase(tokens, service.exclude) for tokens in fields):
        return None
    return service


def peer_context_fields(last: Fee, cost: Decimal, peers: object) -> dict[str, Any]:
    """Return the peer keys of REQ-PF-12 for a fee run, or {} when REQ-PF-14 says no.

    `last` is the last fee of the run and `cost` its yearly cost as a Decimal (the exact value, not
    its display string). Every key starts with "peer_", so the alert id does not change.
    """
    if not isinstance(peers, PeerContext) or peers.account_type not in ACCOUNT_TYPES:
        return {}
    service = match_peer_service(last, peers.services)
    if service is None:
        return {}
    found = peers.snapshot.declarations(peers.account_type, service.service_code, service.concept)
    if found is None or len(found.amounts) < PEER_MIN_ACCOUNTS:
        return {}
    gap = abs((last.date - date.fromisoformat(found.declaration_date)).days)
    if gap > PEER_MAX_DATE_GAP_DAYS:
        return {}
    amounts = found.amounts  # sorted ascending, Decimal, two places
    return {
        "peer_source": PEER_SOURCE,
        "peer_account_type": peers.account_type,
        "peer_account_type_label": ACCOUNT_TYPES[peers.account_type].phrase,
        "peer_service": service.service_code,
        "peer_service_label": service.label,
        "peer_concept": service.concept,
        "peer_declaration_date": found.declaration_date,
        "peer_account_count": len(amounts),
        "peer_not_offered_count": found.not_offered_count,
        "peer_lower_count": sum(1 for amount in amounts if amount < cost),
        "peer_zero_count": sum(1 for amount in amounts if amount == 0),
        "peer_median_yearly": str(median_amount(amounts)),
        "peer_max_yearly": str(amounts[-1]),
    }


def _unique_records(ledger: pd.DataFrame) -> list[dict[str, Any]]:
    """Return the ledger rows as dicts, keeping the first row of each source_ref (REQ-VF-14)."""
    if ledger.empty:
        return []
    seen: set[str] = set()
    records: list[dict[str, Any]] = []
    for record in ledger.to_dict("records"):
        ref = str(record["source_ref"])
        if ref not in seen:
            seen.add(ref)
            records.append(record)
    return records


def extract_fees(ledger: pd.DataFrame, vocabulary: FeeVocabulary) -> list[Fee]:
    """Return the fee rows ordered by (date, source_row); the first of a duplicate source_ref."""
    fees = [fee for rec in _unique_records(ledger) if (fee := classify_fee(rec, vocabulary))]
    return sorted(fees, key=lambda fee: (fee.date, fee.source_row))


def skipped_currency_rows(ledger: pd.DataFrame) -> int:
    """Return the number of rows whose currency is not STATEMENT_CURRENCY (REQ-VF-06)."""
    return sum(1 for rec in _unique_records(ledger) if rec.get("currency") != STATEMENT_CURRENCY)


def statement_span(ledger: pd.DataFrame) -> tuple[date, date] | None:
    """Return the first and last date of the EUR rows, credits included; None without rows."""
    days = [
        _as_date(rec["date"])
        for rec in _unique_records(ledger)
        if rec.get("currency") == STATEMENT_CURRENCY
    ]
    return (min(days), max(days)) if days else None


def sorted_refs(fees: Iterable[Fee]) -> list[str]:
    """Return the source_refs of `fees` ordered by (date, source_row), without duplicates."""
    seen: set[str] = set()
    refs: list[str] = []
    for fee in sorted(fees, key=lambda f: (f.date, f.source_row)):
        if fee.source_ref not in seen:
            seen.add(fee.source_ref)
            refs.append(fee.source_ref)
    return refs


# --- Series and runs (design 4.3) ---------------------------------------------------------


def classify_gap(days: int) -> Interval | None:
    """Return the interval whose nominal gap is within its tolerance of `days`, else None."""
    for interval in INTERVALS:
        if abs(days - interval.nominal_days) <= interval.tolerance_days:
            return interval
    return None


def find_run(rows: Sequence[Fee]) -> tuple[Interval, list[Fee]] | None:
    """Return the interval and the longest regular suffix of `rows`, or None.

    `rows` are ordered by (date, source_row). The interval is the one that matches the last gap;
    the run extends backwards while the gaps match the same interval. None when there are fewer
    than two rows, the last gap matches nothing or the run is shorter than the interval minimum.
    """
    if len(rows) < 2:
        return None
    interval = classify_gap((rows[-1].date - rows[-2].date).days)
    if interval is None:
        return None
    start = len(rows) - 2
    while start > 0 and classify_gap((rows[start].date - rows[start - 1].date).days) == interval:
        start -= 1
    run = list(rows[start:])
    return (interval, run) if len(run) >= interval.min_charges else None


def yearly_cost(amount: Decimal, interval: Interval) -> Decimal:
    """Return round_to_cents(amount x periods per year)."""
    return round_to_cents(amount * interval.periods_per_year)


def recurring_runs(fees: Iterable[Fee]) -> list[tuple[Interval, list[Fee]]]:
    """Return the run of every series of 'other' fees, series ordered by their key.

    Overdraft fees take no part (DN-VF-08). Each series is the fees sharing a series_key.
    """
    groups: dict[str, list[Fee]] = {}
    for fee in sorted(fees, key=lambda f: (f.date, f.source_row)):
        if fee.kind == "other":
            groups.setdefault(fee.key, []).append(fee)
    runs = [find_run(group) for _, group in sorted(groups.items())]
    return [run for run in runs if run is not None]


def in_first_row_order(entries: Iterable[tuple[Fee, T]]) -> list[T]:
    """Return the items ordered by the (date, source_row) of their first fee, then by title."""
    ordered = sorted(
        entries,
        key=lambda entry: (entry[0].date, entry[0].source_row, getattr(entry[1], "title", "")),
    )
    return [item for _, item in ordered]
