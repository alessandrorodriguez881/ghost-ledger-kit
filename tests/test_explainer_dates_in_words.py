"""Dates written in words go through the number guard like ISO dates (live-guard LG16 to LG19).

The second real run (`data/live_runs/2026-11-10_llama3.2-3b_run2.json`, one run, not a rate) showed
`llama3.2:3b` writing `July 31, 2026`; the old tokeniser read the parts as numbers. These tests pin
the new rule and replay the record through the guard. The alert and the cited rows of each record
are rebuilt from the committed demo files through each app's own `run_pipeline`. No network, no
model, no clock. All other data is synthetic (Finance Rule 5).
"""

import json
from dataclasses import dataclass
from datetime import date
from functools import cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import apps.phantom_invoices.detectors  # noqa: F401  (registers the pi.* detectors)
import apps.vampire_fees.detectors  # noqa: F401  (registers the vf.* detectors)
import apps.zombie_subscriptions.detectors  # noqa: F401  (registers the zs.* detectors)
from apps.phantom_invoices import explain_support as pi_support
from apps.phantom_invoices import settings as pi_settings
from apps.vampire_fees import explain_support as vf_support
from apps.vampire_fees import settings as vf_settings
from apps.zombie_subscriptions import explain_support as zs_support
from apps.zombie_subscriptions import settings as zs_settings
from apps.zombie_subscriptions.detectors.utils import normalise_alias_map, normalise_date_map
from ledger_kit.explainer import (
    Explanation,
    _allowed_dates,
    _passes_number_guard,
    _select_llm_columns,
    _tokenise,
    explain_with_meta,
)
from ledger_kit.models import Alert

ROOT = Path(__file__).resolve().parents[1]
RECORD_PATH = ROOT / "data" / "live_runs" / "2026-11-10_llama3.2-3b_run2.json"
RECORD = json.loads(RECORD_PATH.read_text(encoding="utf-8"))
RECORDS: dict[str, dict[str, Any]] = {r["id"]: r for r in RECORD["records"]}

# record id -> the dates the raw answer writes in words, in ISO form (read from the record)
WORDS_DATES: dict[str, set[date]] = {
    "Z1b": {date(2026, 7, 31)},
    "P1b": {date(2026, 10, 6)},
    "V1b": {date(2025, 6, 18), date(2026, 6, 30)},
    "V2b": {date(2026, 1, 5), date(2025, 12, 5)},
}
# no date in words at all: the verdict depends on the figures only
NO_WORDS_DATES = ("Z2b", "Z3b", "Z5b", "P2b", "P3b")
# every date part the old tokeniser could report as a number for Z6b (ISO dates in the answer)
Z6_DATE_PARTS = frozenset({"2026", "07", "7", "31", "09", "9", "08", "8"})


class _Client:
    """Answers every request with one fixed text; records the requests."""

    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.calls: list[dict] = []

    @property
    def chat(self) -> "_Client":
        return self

    @property
    def completions(self) -> "_Client":
        return self

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        message = SimpleNamespace(content=self.answer)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


# --- Rebuilding the alerts of the record from the committed demo files ---------------------------


@dataclass(frozen=True)
class _Case:
    """What the app hands to the explainer for one card."""

    alert: Alert
    rows: pd.DataFrame
    columns: tuple[str, ...] | None
    template: str


@cache
def _zombie() -> zs_settings.Pipeline:
    config = zs_settings.load_config(ROOT / "apps" / "zombie_subscriptions" / "config.toml")
    demo = zs_settings.demo_inputs(config, ROOT, "csv")
    return zs_settings.run_pipeline(
        demo.statement_name,
        demo.statement_bytes,
        aliases=normalise_alias_map(demo.aliases),
        cancellation_dates=normalise_date_map(demo.cancellation_dates),
    )


@cache
def _vampire() -> vf_settings.Pipeline:
    config = vf_settings.load_config(ROOT / "apps" / "vampire_fees" / "config.toml")
    demo = vf_settings.demo_inputs(config, ROOT)
    return vf_settings.run_pipeline(
        demo.statement_name,
        demo.statement_bytes,
        vocabulary=vf_settings.load_vocabulary(config),
    )


@cache
def _phantom() -> pi_settings.Pipeline:
    config = pi_settings.load_config(ROOT / "apps" / "phantom_invoices" / "config.toml")
    demo = pi_settings.demo_inputs(config, ROOT)
    return pi_settings.run_pipeline(demo.invoices, demo.suppliers, demo.payments, demo.as_of)


def _find(alerts: list[Alert], record: dict[str, Any]) -> Alert:
    for alert in alerts:
        if alert.id == record["alert_id"]:
            return alert
    pytest.fail(f"record {record['id']}: alert {record['alert_id']} not raised by the demo")


@cache
def _case(record_id: str) -> _Case:
    record = RECORDS[record_id]
    if record["app"] == "zombie_subscriptions":
        pipeline = _zombie()
        alert = _find(list(pipeline.alerts), record)
        ledger = pipeline.debit_ledger
        rows = ledger[ledger["source_ref"].isin(alert.source_refs)]
        return _Case(alert, rows, None, zs_support.template_for(alert))
    if record["app"] == "vampire_fees":
        pipeline = _vampire()
        alert = _find(list(pipeline.alerts), record)
        rows = pipeline.ledger[pipeline.ledger["source_ref"].isin(alert.source_refs)]
        return _Case(alert, rows, None, vf_support.template_for(alert))
    pipeline = _phantom()
    alert = _find([a for result in pipeline.results for a in result.alerts], record)
    rows = pi_support.build_explain_rows(
        alert, pipeline.invoices, pipeline.suppliers, pipeline.payments
    )
    return _Case(alert, rows, tuple(pi_support.ROW_COLUMNS), pi_support.template_for(alert))


def _verdict(record_id: str) -> Explanation:
    """The record's raw answer through explain_with_meta, as the app would run it."""
    record = RECORDS[record_id]
    case = _case(record_id)
    return explain_with_meta(
        case.alert,
        case.rows,
        fallback_template=case.template,
        client=_Client(record["raw_answer"]),
        row_columns=case.columns,
        question=record["question"],
    )


def _allowed(record_id: str) -> set[date]:
    case = _case(record_id)
    return _allowed_dates(case.alert, _select_llm_columns(case.rows, case.columns), case.columns)


# --- Tier 1: the run2 record ---------------------------------------------------------------------


def test_record_has_the_eleven_documented_ids() -> None:
    ids = ["Z1b", "Z2b", "Z3b", "Z4b", "Z5b", "Z6b", "P1b", "P2b", "P3b", "V1b", "V2b"]
    assert list(RECORDS) == ids
    assert RECORD["settings"]["temperature"] == 0


@pytest.mark.parametrize("record_id", sorted(WORDS_DATES))
def test_record_dates_in_words_are_read_as_dates_not_as_numbers(record_id: str) -> None:
    case = _case(record_id)
    tokens = _tokenise(RECORDS[record_id]["raw_answer"], case.alert.source_refs)

    assert tokens.dates == WORDS_DATES[record_id]
    assert tokens.malformed_dates == ()
    # the day of a date in words is no longer read as a number (a year can be part of an
    # invoice number such as F-2026-0310, so only the days are checked)
    assert not {str(d.day) for d in WORDS_DATES[record_id]} & set(tokens.numbers)


@pytest.mark.parametrize("record_id", [*sorted(WORDS_DATES), *NO_WORDS_DATES])
def test_record_answer_is_accepted_when_every_date_it_writes_is_allowed(record_id: str) -> None:
    """Accepted only if each date in words is among the allowed dates; else rejected naming it."""
    result = _verdict(record_id)
    written = WORDS_DATES.get(record_id, set())
    unknown = sorted(d.isoformat() for d in written - _allowed(record_id))

    if unknown:
        # the model named a date that is neither in the alert data nor in the cited rows
        assert result.source == "fallback", f"{record_id}: date(s) {unknown} are not allowed"
        assert set(unknown) <= set(result.rejected_numbers), f"{record_id}: {unknown}"
    else:
        assert result.rejected_numbers == (), f"{record_id}: {result.rejected_numbers}"
        assert result.source == "llm"
        assert result.text == RECORDS[record_id]["raw_answer"]


def test_record_invention_z4b_stays_rejected_naming_539_40() -> None:
    result = _verdict("Z4b")

    assert result.source == "fallback"
    assert "539.40" in result.rejected_numbers


def test_record_z6b_reports_no_date_part_as_a_number() -> None:
    """Nothing is asserted about the verdict: only that no date part is reported as a number."""
    result = _verdict("Z6b")

    assert not Z6_DATE_PARTS & set(result.rejected_numbers)


# --- Tier 2: the rule ----------------------------------------------------------------------------

MONTHS = (
    ("January", "Jan"),
    ("February", "Feb"),
    ("March", "Mar"),
    ("April", "Apr"),
    ("May", "May"),
    ("June", "Jun"),
    ("July", "Jul"),
    ("August", "Aug"),
    ("September", "Sep"),
    ("October", "Oct"),
    ("November", "Nov"),
    ("December", "Dec"),
)


def _alert(**data: str) -> Alert:
    return Alert(
        detector="zs.charges_after_cancellation",
        severity="critical",
        title="Charge",
        source_refs=["bank.csv:181"],
        data=data,
    )


def _guard(text: str, *allowed_iso: str) -> tuple[bool, tuple[str, ...]]:
    alert = _alert(**{f"date_{i}": iso for i, iso in enumerate(allowed_iso)})
    return _passes_number_guard(text, alert, pd.DataFrame())


@pytest.mark.parametrize(
    "text",
    [
        "June 18, 2025",
        "June 18 2025",
        "18 June 2025",
        "Jun 18, 2025",
        "Jun. 18, 2025",
        "June 18th, 2025",
        "18th June 2025",
        "18th Jun. 2025",
        "JUNE 18, 2025",
        "june 18 2025",
        "jUn. 18TH 2025",
    ],
)
def test_every_written_form_is_the_same_date(text: str) -> None:
    tokens = _tokenise(f"It was charged on {text}.")

    assert tokens.dates == {date(2025, 6, 18)}
    assert tokens.malformed_dates == ()
    assert tokens.numbers == ()
    assert _guard(f"It was charged on {text}.", "2025-06-18") == (True, ())


@pytest.mark.parametrize(("full", "short"), MONTHS)
def test_every_month_name_full_and_abbreviated(full: str, short: str) -> None:
    month = [m[0] for m in MONTHS].index(full) + 1
    for name in (full, short, short + ".", full.upper(), full.lower()):
        for text in (f"{name} 5, 2026", f"{name} 5 2026", f"5 {name} 2026"):
            assert _tokenise(text).dates == {date(2026, month, 5)}, text


def test_july_31_2027_is_rejected_when_only_2026_07_31_is_allowed() -> None:
    assert _guard("Cancelled on July 31, 2027.", "2026-07-31") == (False, ("2027-07-31",))


def test_31_july_2026_is_accepted_when_2026_07_31_is_allowed() -> None:
    assert _guard("Cancelled on 31 July 2026.", "2026-07-31") == (True, ())


def test_date_in_words_not_among_the_allowed_is_reported_in_iso_form() -> None:
    assert _guard("From 18 Jun. 2025 to June 30, 2026.", "2025-06-18") == (False, ("2026-06-30",))


def test_impossible_date_in_words_is_malformed_and_rejected() -> None:
    tokens = _tokenise("Charged on February 30, 2026.")

    assert tokens.malformed_dates == ("February 30, 2026",)
    assert tokens.dates == frozenset()
    assert tokens.numbers == ()
    assert _guard("Charged on February 30, 2026.", "2026-02-28") == (False, ("February 30, 2026",))


@pytest.mark.parametrize("text", ["February 29, 2027", "31 April 2026", "June 0, 2026"])
def test_other_impossible_dates_in_words_are_malformed(text: str) -> None:
    assert _tokenise(text).malformed_dates == (text,)


def test_leap_day_in_words_is_a_date() -> None:
    assert _tokenise("February 29, 2028").dates == {date(2028, 2, 29)}


def test_a_bare_month_name_is_not_a_date_and_leaves_numbers_untouched() -> None:
    tokens = _tokenise("It ran in June for 12 times.")

    assert tokens.dates == frozenset()
    assert tokens.malformed_dates == ()
    assert tokens.numbers == ("12",)
    assert _guard("It was charged in June.") == (True, ())
    assert _guard("It ran in June for 12 times.") == (False, ("12",))


@pytest.mark.parametrize("text", ["in June 2026", "June 18", "18 June", "June 18, 25"])
def test_month_without_day_and_year_together_is_not_a_date(text: str) -> None:
    tokens = _tokenise(text)

    assert tokens.dates == frozenset()
    assert tokens.malformed_dates == ()


def test_month_name_inside_a_longer_word_is_not_a_month() -> None:
    assert _tokenise("Marching 5 2026 and Mayor 5 2026").dates == frozenset()


def test_amounts_next_to_a_date_in_words_keep_the_strict_rule() -> None:
    text = "Paid 8.99 EUR on June 18, 2025 and 777.77 EUR."

    assert _guard(text.replace(" EUR", ""), "2025-06-18")[1] == ("8.99", "777.77")
    assert _tokenise(text).numbers == ("8.99", "777.77")


def test_iso_and_european_dates_are_unchanged() -> None:
    assert _tokenise("2026-07-31 and 31/07/2026").dates == {date(2026, 7, 31)}
    assert _tokenise("2026-02-30").malformed_dates == ("2026-02-30",)


def test_date_in_words_in_the_alert_data_is_an_allowed_date() -> None:
    alert = _alert(cancelled="July 31, 2026")

    assert _passes_number_guard("Cancelled on 2026-07-31.", alert, pd.DataFrame()) == (True, ())


def test_date_in_words_never_hides_an_invented_amount() -> None:
    assert _guard("On July 31, 2026 you pay 539.40.", "2026-07-31") == (False, ("539.40",))


def test_system_message_asks_for_iso_dates_and_keeps_every_other_sentence() -> None:
    client = _Client("Charged (bank.csv:181).")
    explain_with_meta(
        _alert(),
        pd.DataFrame({"source_ref": ["bank.csv:181"]}),
        fallback_template="{source_refs}",
        client=client,
    )
    (call,) = client.calls
    system = call["messages"][0]["content"]

    assert "Write every date exactly as given, in YYYY-MM-DD form." in system
    assert "You must not invent any number, date, name, or amount." in system
    assert "Cite at least one source reference from: ['bank.csv:181']." in system
    assert "at most three sentences" in system
    assert "no lists, no JSON, no repetition of the input" in system
    assert "Write source references exactly as given." in system


# --- Tier 3: property ----------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(
    day=st.dates(min_value=date(1000, 1, 1), max_value=date(9999, 12, 31)),
    form=st.sampled_from(("mdy_comma", "mdy", "dmy")),
    full=st.booleans(),
    dot=st.booleans(),
    ordinal=st.sampled_from(("", "st", "nd", "rd", "th")),
    case=st.sampled_from((str.lower, str.upper, str.title)),
)
def test_any_written_date_is_read_back_exactly(
    day: date, form: str, full: bool, dot: bool, ordinal: str, case: Any
) -> None:
    full_name, short = MONTHS[day.month - 1]
    name = case(full_name if full else short + ("." if dot else ""))
    number = f"{day.day}{ordinal}"
    text = {
        "mdy_comma": f"{name} {number}, {day.year:04d}",
        "mdy": f"{name} {number} {day.year:04d}",
        "dmy": f"{number} {name} {day.year:04d}",
    }[form]

    tokens = _tokenise(f"Charged on {text}.")

    assert tokens.dates == {day}
    assert tokens.malformed_dates == ()
    assert tokens.numbers == ()
