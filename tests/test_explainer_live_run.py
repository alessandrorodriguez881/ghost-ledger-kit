"""The first real-model run replayed through the number guard (live-guard LG9 to LG14).

The record `data/live_runs/2026-11-10_llama3.2-3b.json` holds the raw answers of one run of
`llama3.2:3b` on the demo cards (one run, not a rate). The alert and the cited rows of each record
are rebuilt from the committed demo files through each app's own `run_pipeline`, then the raw answer
goes through `explain_with_meta` with a client that returns it. No network, no model, no clock.
All other data is synthetic (Finance Rule 5).
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
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
    LLM_MAX_TOKENS,
    Explanation,
    _passes_number_guard,
    _select_llm_columns,
    explain_with_meta,
    fill_fallback,
)
from ledger_kit.models import Alert

ROOT = Path(__file__).resolve().parents[1]
RECORD_PATH = ROOT / "data" / "live_runs" / "2026-11-10_llama3.2-3b.json"
RECORD = json.loads(RECORD_PATH.read_text(encoding="utf-8"))
RECORDS: dict[str, dict[str, Any]] = {r["id"]: r for r in RECORD["records"]}

ACCEPTED = ("Z1", "Z2", "Z3", "Z5", "P1", "P2")
# record id -> the token the guard must name
REJECTED = {"Z4": "539.4", "Z6": "80.91", "P3": "617.51", "V2": "$"}


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


def _find(alerts: Sequence[Alert], record: dict[str, Any]) -> Alert:
    for alert in alerts:
        if alert.id == record["alert_id"]:
            return alert
    pytest.fail(f"record {record['id']}: alert {record['alert_id']} not raised by the demo")


@cache
def _case(record_id: str) -> _Case:
    record = RECORDS[record_id]
    if record["app"] == "zombie_subscriptions":
        pipeline = _zombie()
        alert = _find(pipeline.alerts, record)
        ledger = pipeline.debit_ledger
        rows = ledger[ledger["source_ref"].isin(alert.source_refs)]
        return _Case(alert, rows, None, zs_support.template_for(alert))
    if record["app"] == "vampire_fees":
        pipeline = _vampire()
        alert = _find(pipeline.alerts, record)
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


# --- Tier 1: the record --------------------------------------------------------------------------


def test_record_has_the_eleven_documented_ids() -> None:
    assert list(RECORDS) == ["Z1", "Z2", "Z3", "Z4", "Z5", "Z6", "P1", "P2", "P3", "V1", "V2"]
    assert RECORD["settings"]["temperature"] == 0


@pytest.mark.parametrize("record_id", ACCEPTED)
def test_record_answer_is_accepted(record_id: str) -> None:
    result = _verdict(record_id)

    assert result.rejected_numbers == ()
    assert result.source == "llm"
    assert result.text == RECORDS[record_id]["raw_answer"]


@pytest.mark.parametrize(("record_id", "token"), sorted(REJECTED.items()))
def test_record_invention_is_rejected_naming_the_token(record_id: str, token: str) -> None:
    result = _verdict(record_id)
    case = _case(record_id)

    assert result.source == "fallback"
    assert token in result.rejected_numbers
    assert result.text == fill_fallback(case.template, case.alert)
    assert result.raw_answer == RECORDS[record_id]["raw_answer"]


def test_record_without_an_answer_is_recorded_as_no_answer() -> None:
    record = RECORDS["V1"]

    assert record["observed_source"] == "no_answer"
    assert record["raw_answer"] == ""
    result = _verdict("V1")
    assert result.source == "fallback"
    assert result.raw_answer == ""


def test_every_record_with_an_answer_was_observed_as_the_record_says() -> None:
    """The record keeps what the old guard did; the new verdicts above are what changed."""
    old_rejected = {r["id"] for r in RECORDS.values() if r["observed_source"] == "fallback"}
    assert old_rejected == {"Z1", "Z2", "Z4", "Z6", "P2", "P3"}


# --- Tier 2: one negative (and one positive) test per rule ---------------------------------------

REFS_B = ["bank.csv:181", "bank.csv:236", "bank.csv:292"]


def _alert(refs: Sequence[str] = REFS_B, data: dict | None = None) -> Alert:
    return Alert(
        detector="zs.recurring_charge",
        severity="warning",
        title="Charge",
        source_refs=list(refs),
        data={"yearly_cost": "107.88"} if data is None else data,
    )


def _rows(refs: Sequence[str] = REFS_B, currency: str | None = "EUR") -> pd.DataFrame:
    records = []
    for ref in refs:
        record: dict[str, Any] = {
            "date": date(2026, 8, 9),
            "amount": Decimal("8.99"),
            "flow": "debit",
            "counterparty": "GYMPLUS",
            "source_ref": ref,
        }
        if currency is not None:
            record["currency"] = currency
        records.append(record)
    return pd.DataFrame(records)


def _guard(
    text: str, alert: Alert | None = None, rows: pd.DataFrame | None = None
) -> tuple[bool, tuple[str, ...]]:
    return _passes_number_guard(text, alert or _alert(), _rows() if rows is None else rows)


@pytest.mark.parametrize(
    "text",
    [
        "The charges are in rows 181, 236, and 292 of bank.csv.",
        "See ROW 181 and Line 236, also lines 292.",
        "Rows 181, 236 or 292 hold the charges.",
        "Rows 181 and 236 & 292 hold the charges.",
    ],
)
def test_row_citation_of_a_cited_line_is_not_a_figure(text: str) -> None:
    assert _guard(text) == (True, ())


def test_ordinal_row_citation_of_a_cited_line_is_not_a_figure() -> None:
    refs = ["invoices.csv:8", "suppliers.csv:4"]
    alert, rows = _alert(refs, {}), _rows(refs)

    assert _guard("See the 8th row and the 4th Row.", alert, rows) == (True, ())
    assert _guard("See the 9th row.", alert, rows) == (False, ("9",))


def test_row_citation_of_a_line_that_is_not_cited_stays_rejected() -> None:
    assert _guard("See row 999.") == (False, ("999",))
    assert _guard("rows 181, 999") == (False, ("999",))
    assert _guard("See the 5th line.") == (False, ("5",))


def test_cited_line_number_outside_a_citation_stays_rejected() -> None:
    assert _guard("The cost is 181 EUR.") == (False, ("181",))
    assert _guard("It happened 181 times in rows 181.")[0] is False


def test_cited_line_number_is_allowed_when_the_data_holds_it() -> None:
    alert = _alert(data={"yearly_cost": "181"})
    assert _guard("The cost is 181 EUR.", alert) == (True, ())


@pytest.mark.parametrize(
    "text",
    [
        "The 3 debit transactions are listed.",
        "There are 3 charges.",
        "3 rows were read, 3 payments, 3 entries, 3 invoices and 3 times.",
        "Also 3 debit entries.",
    ],
)
def test_count_of_cited_rows_is_not_a_figure(text: str) -> None:
    assert _guard(text) == (True, ())


def test_count_of_rows_other_than_the_cited_number_stays_rejected() -> None:
    assert _guard("The 7 rows are listed.") == (False, ("7",))
    assert _guard("It ran for 3 months.") == (False, ("3",))
    assert _guard("It cost 3 EUR payments.") == (False, ("3",))
    assert _guard("It cost 3 EUR.") == (False, ("3",))


def test_list_markers_at_the_start_of_a_line_are_not_figures() -> None:
    assert _guard("1. The charge repeats.\n2) It is monthly.\n12. Done.") == (True, ())


def test_the_same_digits_in_the_middle_of_a_line_stay_rejected() -> None:
    assert _guard("The charge repeats. 5. It is monthly.") == (False, ("5",))
    assert _guard("List:\nsee 5) and 6.") == (False, ("5", "6"))


def test_start_of_line_decimals_and_long_numbers_are_not_markers() -> None:
    assert _guard("8.99 EUR is charged.") == (True, ())
    assert _guard("100. Charged.") == (False, ("100",))
    assert _guard("5.50 EUR is charged.") == (False, ("5.50",))
    assert _guard("1.Charged.") == (False, ("1",))


def test_currency_not_named_by_the_rows_is_rejected_like_a_number() -> None:
    alert = _alert(data={"yearly_cost": "78.00"})

    assert _guard("The fee is $78.00.", alert) == (False, ("$",))
    assert _guard("The fee is 78.00 GBP.", alert) == (False, ("GBP",))
    assert _guard("The fee is £78.00 or 78.00 ¥.", alert) == (False, ("£", "¥"))
    assert _guard("The fee is 78.00 USD.", alert) == (False, ("USD",))
    assert _guard("It is 999 GBP.", alert) == (False, ("999", "GBP"))


def test_currency_named_by_the_rows_is_accepted() -> None:
    assert _guard("The fee is €8.99 or 8.99 EUR.") == (True, ())
    assert _guard("The fee is 8.99 EUR, not a VAT or SEPA code.") == (True, ())


def test_dollar_sign_is_accepted_for_any_dollar_currency() -> None:
    rows = _rows(currency="CAD")
    assert _guard("The fee is $8.99 or 8.99 CAD.", rows=rows) == (True, ())
    assert _guard("The fee is 8.99 USD.", rows=rows) == (False, ("USD",))


def test_currency_check_is_skipped_when_no_currency_is_named() -> None:
    rows = _rows(currency=None)
    assert _guard("The fee is $8.99 or 8.99 GBP.", rows=rows) == (True, ())


def test_missing_currency_cells_name_no_currency() -> None:
    rows = _rows()
    rows["currency"] = [float("nan"), None, float("nan")]
    assert _guard("The fee is 8.99 EUR.", rows=rows) == (True, ())


def test_missing_currency_cell_does_not_hide_the_named_currency() -> None:
    rows = _rows()
    rows["currency"] = ["EUR", float("nan"), None]
    assert _guard("The fee is 8.99 GBP.", rows=rows) == (False, ("GBP",))
    assert _guard("The fee is 8.99 EUR.", rows=rows) == (True, ())


def test_currency_named_in_the_alert_data_counts() -> None:
    alert = _alert(data={"yearly_cost": "107.88", "currency": "USD"})
    rows = _rows(currency=None)

    assert _guard("The fee is $8.99.", alert, rows) == (True, ())
    assert _guard("The fee is €8.99.", alert, rows) == (False, ("€",))


def test_foreign_currency_rejects_through_explain_with_meta() -> None:
    client = _Client("The fee is 8.99 GBP (bank.csv:181).")
    result = explain_with_meta(
        _alert(["bank.csv:181"], {}),
        _rows(["bank.csv:181"]),
        fallback_template="{source_refs}",
        client=client,
    )

    assert result.source == "fallback"
    assert result.rejected_numbers == ("GBP",)
    assert result.text == "bank.csv:181"


def test_request_asks_for_short_prose_and_caps_the_length() -> None:
    client = _Client("Charged 8.99 EUR (bank.csv:181).")
    explain_with_meta(
        _alert(["bank.csv:181"], {}),
        _rows(["bank.csv:181"]),
        fallback_template="{source_refs}",
        client=client,
        question="What amount will be charged next month? Give the amount.",
    )
    (call,) = client.calls
    system = call["messages"][0]["content"]

    assert LLM_MAX_TOKENS == 200
    assert call["max_tokens"] == LLM_MAX_TOKENS
    assert call["temperature"] == 0
    assert "You must not invent any number, date, name, or amount." in system
    assert "Do not derive, round, or estimate any figure" in system
    assert "Cite at least one source reference from: ['bank.csv:181']." in system
    assert "at most three sentences" in system
    assert "no lists, no JSON, no repetition of the input" in system
    assert "source references exactly as given" in system


# --- Tier 3: property ----------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(
    record_id=st.sampled_from(ACCEPTED),
    amount=st.decimals(min_value=Decimal("10000"), max_value=Decimal("99999.99"), places=2),
    data=st.data(),
)
def test_invented_amount_inserted_anywhere_in_an_accepted_answer_is_rejected(
    record_id: str, amount: Decimal, data: st.DataObject
) -> None:
    case = _case(record_id)
    raw = RECORDS[record_id]["raw_answer"]
    position = data.draw(st.integers(min_value=0, max_value=len(raw)))
    invented = f"{amount:f}"
    mutated = raw[:position] + f" {invented} " + raw[position:]

    passed, rejected = _passes_number_guard(
        mutated, case.alert, _select_llm_columns(case.rows, case.columns), case.columns
    )

    assert not passed
    assert invented in rejected
