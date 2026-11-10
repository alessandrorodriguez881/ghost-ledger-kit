"""Dates without a year and row ranges go through the number guard (live-guard LG20 to LG24).

The third real run (`data/live_runs/2026-11-10_llama3.2-3b_run3.json`, one run, not a rate) showed
`llama3.2:3b` writing `August 9, September 8, and October 8, 2026` (a list that shares one year),
`August 9, September 8, and October 8` (no year at all) and `rows 9 to 312`. The old guard read the
days as numbers and the end of the range as a figure. These tests pin the new rules and replay the
record through the guard. The alert and the cited rows of each record are rebuilt from the
committed demo files through each app's own `run_pipeline`. No network, no model, no clock. All
other data is synthetic (Finance Rule 5).
"""

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from functools import cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest
from hypothesis import assume, given, settings
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
    _allowed_decimals,
    _cited_line_numbers,
    _passes_number_guard,
    _select_llm_columns,
    _tokenise,
    _without_non_figures,
    explain_with_meta,
)
from ledger_kit.models import Alert

ROOT = Path(__file__).resolve().parents[1]
RECORD_PATH = ROOT / "data" / "live_runs" / "2026-11-10_llama3.2-3b_run3.json"
RECORD = json.loads(RECORD_PATH.read_text(encoding="utf-8"))
RECORDS: dict[str, dict[str, Any]] = {r["id"]: r for r in RECORD["records"]}

MONTH_WORDS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)

# What each fixed record writes (read from the record): dates as (month, day, year or None),
# amounts as written, and the line numbers named as rows. The verdict is "accepted only if
# every one of them is allowed"; otherwise the record stays rejected and the test names the token.
WRITTEN: dict[str, dict[str, Any]] = {
    "Z1c": {
        "dates": [(8, 9, 2026), (9, 8, 2026), (10, 8, 2026)],
        "amounts": ("26.97", "8.99"),
        "lines": (),
    },
    "Z2c": {"dates": [], "amounts": ("10.99",), "lines": (9, 312)},
    "Z5c": {
        "dates": [(8, 9, None), (9, 8, None), (10, 8, None)],
        "amounts": ("8.99",),
        "lines": (),
    },
}
ACCEPTED_AS_BEFORE = ("P1c", "P2c", "P3c", "V1c", "V2c")


class _Client:
    """Answers every request with one fixed text."""

    def __init__(self, answer: str) -> None:
        self.answer = answer

    @property
    def chat(self) -> "_Client":
        return self

    @property
    def completions(self) -> "_Client":
        return self

    def create(self, **kwargs: Any) -> SimpleNamespace:
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


def _unknown_tokens(record_id: str) -> list[str]:
    """Every date, amount and row number the record writes that the data does not allow."""
    case = _case(record_id)
    written = WRITTEN[record_id]
    visible = _select_llm_columns(case.rows, case.columns)  # the columns the model was sent
    allowed_dates = _allowed_dates(case.alert, visible, case.columns)
    allowed_days = {(d.month, d.day) for d in allowed_dates}
    allowed_amounts = _allowed_decimals(case.alert, visible, case.columns)
    cited = _cited_line_numbers(case.alert)

    unknown: list[str] = []
    for month, day, year in written["dates"]:
        if year is None and (month, day) not in allowed_days:
            unknown.append(f"{MONTH_WORDS[month - 1]} {day}")
        elif year is not None and date(year, month, day) not in allowed_dates:
            unknown.append(date(year, month, day).isoformat())
    unknown += [a for a in written["amounts"] if Decimal(a) not in allowed_amounts]
    unknown += [str(n) for n in written["lines"] if n not in cited]
    return unknown


# --- Tier 1: the run3 record ---------------------------------------------------------------------


def test_record_has_the_eleven_documented_ids() -> None:
    ids = ["Z1c", "Z2c", "Z3c", "Z4c", "Z5c", "Z6c", "P1c", "P2c", "P3c", "V1c", "V2c"]
    assert list(RECORDS) == ids
    assert RECORD["settings"]["temperature"] == 0


@pytest.mark.parametrize("record_id", sorted(WRITTEN))
def test_record_answer_is_accepted_only_if_everything_it_writes_is_allowed(
    record_id: str,
) -> None:
    """Accepted when each date, amount and row number is allowed; else rejected naming them."""
    result = _verdict(record_id)
    unknown = _unknown_tokens(record_id)

    if unknown:
        # the model named something that is neither in the alert data nor in the cited rows
        assert result.source == "fallback", f"{record_id}: {unknown} are not allowed"
        assert result.rejected_numbers, f"{record_id}: rejected with no token, expected {unknown}"
    else:
        assert result.rejected_numbers == (), f"{record_id}: {result.rejected_numbers}"
        assert result.source == "llm"
        assert result.text == RECORDS[record_id]["raw_answer"]


def test_record_z1c_list_shares_the_year_and_its_days_are_no_numbers() -> None:
    case = _case("Z1c")
    tokens = _tokenise(RECORDS["Z1c"]["raw_answer"], case.alert.source_refs)

    assert tokens.dates == {date(2026, 8, 9), date(2026, 9, 8), date(2026, 10, 8)}
    assert tokens.partial_dates == ()
    assert not {"9", "8"} & set(tokens.numbers)


def test_record_z5c_partial_dates_are_read_and_their_days_are_no_numbers() -> None:
    case = _case("Z5c")
    tokens = _tokenise(RECORDS["Z5c"]["raw_answer"], case.alert.source_refs)

    assert tokens.dates == frozenset()
    assert [written for written, _, _ in tokens.partial_dates] == [
        "August 9",
        "September 8",
        "October 8",
    ]
    assert not {"9", "8"} & set(tokens.numbers)


def test_record_z2c_range_ends_are_blanked_as_citations() -> None:
    case = _case("Z2c")
    text = _without_non_figures(RECORDS["Z2c"]["raw_answer"], case.alert)
    tokens = _tokenise(text, case.alert.source_refs)

    assert not {"9", "312"} & set(tokens.numbers)


@pytest.mark.parametrize("record_id", ACCEPTED_AS_BEFORE)
def test_record_answers_accepted_before_stay_accepted(record_id: str) -> None:
    result = _verdict(record_id)

    assert result.rejected_numbers == (), f"{record_id}: {result.rejected_numbers}"
    assert result.source == "llm"
    assert result.text == RECORDS[record_id]["raw_answer"]


def test_record_z3c_stays_rejected_with_the_dollar_sign() -> None:
    result = _verdict("Z3c")

    assert result.source == "fallback"
    assert "$" in result.rejected_numbers


def test_record_z4c_stays_rejected_with_539_40() -> None:
    result = _verdict("Z4c")

    assert result.source == "fallback"
    assert "539.40" in result.rejected_numbers


def test_record_z6c_keeps_the_verdict_it_has_today() -> None:
    result = _verdict("Z6c")
    record = RECORDS["Z6c"]

    assert result.source == record["observed_source"]
    assert list(result.rejected_numbers) == record["observed_rejected"]


# --- Tier 2: the rules ---------------------------------------------------------------------------


def _alert(*refs: str, **data: str) -> Alert:
    return Alert(
        detector="zs.charges_after_cancellation",
        severity="critical",
        title="Charge",
        source_refs=list(refs) or ["bank.csv:181"],
        data=data,
    )


def _guard(text: str, *allowed_iso: str) -> tuple[bool, tuple[str, ...]]:
    alert = _alert(**{f"date_{i}": iso for i, iso in enumerate(allowed_iso)})
    return _passes_number_guard(text, alert, pd.DataFrame())


ALL_2026 = ("2026-08-09", "2026-09-08", "2026-10-08")


@pytest.mark.parametrize(
    "text",
    [
        "August 9, September 8, and October 8, 2026",
        "August 9, September 8, October 8, 2026",
        "August 9, September 8 and October 8, 2026",
        "August 9, September 8 & October 8 2026",
        "9 August, 8 September, and 8 October 2026",
        "9th Aug., 8th Sep. and 8th Oct. 2026",
        "AUGUST 9, SEPTEMBER 8, AND OCTOBER 8, 2026",
    ],
)
def test_a_list_ending_with_one_year_gives_every_item_that_year(text: str) -> None:
    tokens = _tokenise(f"They occurred on {text}.")

    assert tokens.dates == {date(2026, 8, 9), date(2026, 9, 8), date(2026, 10, 8)}
    assert tokens.partial_dates == ()
    assert tokens.malformed_dates == ()
    assert tokens.numbers == ()
    assert _guard(f"They occurred on {text}.", *ALL_2026) == (True, ())


def test_two_items_and_a_year_is_a_list_too() -> None:
    tokens = _tokenise("On August 9 and September 8, 2026.")

    assert tokens.dates == {date(2026, 8, 9), date(2026, 9, 8)}
    assert tokens.numbers == ()


def test_a_list_year_that_is_not_allowed_rejects_every_item_in_iso_form() -> None:
    result = _guard("On August 9 and September 8, 2025.", "2026-08-09", "2026-09-08")

    assert result == (False, ("2025-08-09", "2025-09-08"))


def test_one_unknown_item_of_a_list_is_named() -> None:
    result = _guard("On August 9, September 9, and October 8, 2026.", *ALL_2026)

    assert result == (False, ("2026-09-09",))


def test_a_list_item_that_does_not_exist_is_malformed_as_written() -> None:
    tokens = _tokenise("On February 30, March 8, 2026.")

    assert tokens.malformed_dates == ("February 30",)
    assert tokens.dates == {date(2026, 3, 8)}
    assert _guard("On February 30, March 8, 2026.", "2026-03-08") == (False, ("February 30",))


def test_items_with_a_year_of_their_own_keep_it() -> None:
    tokens = _tokenise("On August 9, 2025, and October 8, 2026.")

    assert tokens.dates == {date(2025, 8, 9), date(2026, 10, 8)}
    assert tokens.partial_dates == ()


def test_something_else_between_the_items_is_not_one_list() -> None:
    """The year of the last date does not reach a partial date in another sentence."""
    result = _guard("It began on August 9. Later, on October 8, 2026.", "2026-10-08")

    assert result == (False, ("August 9",))


@pytest.mark.parametrize(
    "text", ["August 9", "Aug 9", "Aug. 9", "August 9th", "9 August", "9th Aug.", "AUGUST 9"]
)
def test_a_partial_date_is_accepted_when_an_allowed_date_has_that_month_and_day(
    text: str,
) -> None:
    tokens = _tokenise(f"It was charged on {text}.")

    assert tokens.numbers == ()
    assert tokens.dates == frozenset()
    assert len(tokens.partial_dates) == 1
    assert _guard(f"It was charged on {text}.", "2026-08-09") == (True, ())
    assert _guard(f"It was charged on {text}.", "2025-08-09") == (True, ())


def test_august_10_without_a_year_is_rejected_when_only_2026_08_09_is_allowed() -> None:
    assert _guard("It was charged on August 10.", "2026-08-09") == (False, ("August 10",))


def test_a_rejected_partial_date_is_reported_as_written_once() -> None:
    assert _guard("On 10 August and again on 10 August.", "2026-08-09") == (False, ("10 August",))
    assert _guard("On 10th Aug. Then more.", "2026-08-09") == (False, ("10th Aug",))


def test_a_partial_date_that_cannot_exist_is_rejected() -> None:
    assert _guard("On February 30.", "2026-02-28") == (False, ("February 30",))


def test_the_day_of_a_partial_date_is_never_a_number() -> None:
    tokens = _tokenise("Charged on August 9 and 8 September.")

    assert tokens.numbers == ()
    assert tokens.partial_dates == (("August 9", 8, 9), ("8 September", 9, 8))


@pytest.mark.parametrize("text", ["in June", "June 2026", "in June 2026", "Marching 5", "Mayor 5"])
def test_a_month_name_alone_stays_as_before(text: str) -> None:
    tokens = _tokenise(text)

    assert tokens.partial_dates == ()
    assert tokens.dates == frozenset()


def test_a_day_that_is_part_of_a_decimal_or_code_is_no_partial_date() -> None:
    tokens = _tokenise("It cost August 9.99 and June 5,50 and May 3/4.")

    assert tokens.partial_dates == ()
    assert "9.99" in tokens.numbers


def test_a_partial_date_hides_no_invented_amount() -> None:
    assert _guard("On August 9 you pay 539.40.", "2026-08-09") == (False, ("539.40",))


def test_full_dates_and_partial_dates_in_one_answer_are_each_judged() -> None:
    result = _guard("From 2026-08-09 to September 8 and on October 8, 2026.", *ALL_2026)

    assert result == (True, ())


# Row ranges: refs of lines 9 and 312.
RANGE_REFS = ("bank.csv:9", "bank.csv:312")


def _range_guard(text: str) -> tuple[bool, tuple[str, ...]]:
    return _passes_number_guard(text, _alert(*RANGE_REFS), pd.DataFrame())


@pytest.mark.parametrize(
    "text",
    [
        "rows 9 to 312",
        "rows 9 through 312",
        "rows 9-312",
        "rows 9\u2013312",
        "rows 9 - 312",
        "lines 9 to 312",
        "Rows 9 TO 312",
        "row 9 to 312",
    ],
)
def test_a_range_between_two_cited_lines_cites_both_ends(text: str) -> None:
    assert _range_guard(f"See {text} of bank.csv.") == (True, ())


def test_a_range_in_a_list_cites_both_ends() -> None:
    assert _range_guard("See rows 9 to 312, 9 and 312.") == (True, ())


def test_rows_9_to_999_keeps_999_rejected() -> None:
    assert _range_guard("See rows 9 to 999.") == (False, ("999",))
    assert _range_guard("See rows 9-999.") == (False, ("999",))


def test_a_range_that_does_not_start_at_a_cited_line_keeps_the_strict_rule() -> None:
    assert _range_guard("See rows 999 to 312.") == (False, ("999", "312"))
    assert _range_guard("See rows 5 to 312.") == (False, ("5", "312"))


def test_a_range_without_the_keyword_is_no_citation() -> None:
    assert _range_guard("It cost 9 to 312 EUR.") == (False, ("9", "312"))


def test_a_date_after_rows_is_not_read_as_a_range() -> None:
    assert _range_guard("See rows 2026-08-09.") == (False, ("2026-08-09",))


def test_the_ordinary_citations_are_unchanged() -> None:
    alert = _alert("bank.csv:181", "bank.csv:236", "bank.csv:292")

    assert _passes_number_guard("See rows 181, 236, and 292.", alert, pd.DataFrame()) == (True, ())
    assert _passes_number_guard("See row 999.", alert, pd.DataFrame()) == (False, ("999",))
    assert _passes_number_guard("See rows 181, 999.", alert, pd.DataFrame()) == (False, ("999",))


# --- Tier 3: properties --------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(
    first=st.integers(min_value=1, max_value=10**6),
    last=st.integers(min_value=1, max_value=10**6),
    other=st.integers(min_value=1, max_value=10**6),
    word=st.sampled_from(("to", "through", "-", "\u2013")),
)
def test_a_range_is_a_citation_only_between_two_cited_lines(
    first: int, last: int, other: int, word: str
) -> None:
    assume(len({first, last, other}) == 3)
    alert = _alert(f"bank.csv:{first}", f"bank.csv:{last}")
    glue = f" {word} " if word.isalpha() else word

    accepted = _passes_number_guard(f"See rows {first}{glue}{last}.", alert, pd.DataFrame())
    rejected = _passes_number_guard(f"See rows {first}{glue}{other}.", alert, pd.DataFrame())

    assert accepted == (True, ())
    assert rejected == (False, (str(other),))


@settings(max_examples=200, deadline=None)
@given(
    day=st.dates(min_value=date(2000, 1, 1), max_value=date(2000, 12, 31)),
    other=st.dates(min_value=date(2000, 1, 1), max_value=date(2000, 12, 31)),
    form=st.sampled_from(("md", "dm")),
    full=st.booleans(),
    ordinal=st.sampled_from(("", "th")),
    case=st.sampled_from((str.lower, str.upper, str.title)),
)
def test_a_partial_date_is_judged_by_month_and_day_alone(
    day: date, other: date, form: str, full: bool, ordinal: str, case: Any
) -> None:
    assume((other.month, other.day) != (day.month, day.day))
    name = case(MONTH_WORDS[day.month - 1] if full else MONTH_WORDS[day.month - 1][:3])
    number = f"{day.day}{ordinal}"
    text = f"Charged on {name} {number}." if form == "md" else f"Charged on {number} {name}."

    tokens = _tokenise(text)
    assert tokens.numbers == ()
    assert len(tokens.partial_dates) == 1

    # the same month and day in another year is enough; another month or day is not
    assert _guard(text, date(2024, day.month, day.day).isoformat()) == (True, ())
    assert _guard(text, other.isoformat())[0] is False
