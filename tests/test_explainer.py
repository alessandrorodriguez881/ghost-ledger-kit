"""Tests for ledger_kit.explainer. No network calls: every LLM is a MockLLMClient."""

import json
import sys
import types
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import ledger_kit.explainer as explainer
from ledger_kit.explainer import (
    LLM_MAX_RETRIES,
    LLM_TIMEOUT_SECONDS,
    Explanation,
    _allowed_dates,
    _allowed_decimals,
    _passes_number_guard,
    _tokenise,
    explain,
    explain_with_meta,
    fill_fallback,
)
from ledger_kit.models import Alert

# Mod-97 valid, deliberately wrong national check digits (Finance Rule 5).
_FAKE_IBAN = "ES88 2100 0418 5602 0005 1332"

_NO_INVENTION = (
    "You must not invent any number, date, name, or amount. "
    "Every figure you mention must appear verbatim either in the source rows "
    "provided or in the structured fields of the alert (such as yearly_cost). "
    "Do not derive, round, or estimate any figure not explicitly present in "
    "those inputs."
)

_TEMPLATE = "Charge {monthly_cost:money} ({source_refs})"
_DEFAULT_KEYS = {"date", "amount", "flow", "currency", "counterparty", "source_ref"}


@dataclass
class _MockCompletion:
    content: str


@dataclass
class _MockChoice:
    message: _MockCompletion


@dataclass
class _MockResponse:
    choices: list[_MockChoice]


class MockLLMClient:
    """Configurable mock: responses=["text", None] (None simulates an API failure)."""

    def __init__(self, responses):
        self._responses = iter(responses)
        self.calls: list[dict] = []

    @property
    def chat(self):
        return self

    @property
    def completions(self):
        return self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        r = next(self._responses)
        if r is None:
            raise RuntimeError("simulated failure")
        return _MockResponse([_MockChoice(_MockCompletion(r))])


def _alert(data: dict | None = None, refs: list[str] | None = None) -> Alert:
    return Alert(
        detector="zs.recurring_charge",
        severity="warning",
        title="Recurring charge",
        source_refs=refs if refs is not None else ["bank.csv:0"],
        data=data if data is not None else {"monthly_cost": "12.99"},
    )


def _rows(ref: str = "bank.csv:0") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "id": "3f2b8c1e-0000-4000-8000-000000000000",
                "date": date(2026, 1, 15),
                "amount": Decimal("12.99"),
                "flow": "debit",
                "currency": "EUR",
                "counterparty": "Ana García",
                "description": "Monthly plan",
                "iban": _FAKE_IBAN,
                "source_ref": ref,
            }
        ]
    )


def _invoice_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "invoice_number": "FAC-ALFA",
                "issue_date": date(2026, 1, 15),
                "due_date": date(2026, 2, 14),
                "total": Decimal("1060.00"),
                "source_ref": "inv.csv:0",
            }
        ]
    )


_INVOICE_COLUMNS = ("invoice_number", "issue_date", "due_date", "total", "source_ref")


def _sent_messages(client: MockLLMClient) -> tuple[str, str]:
    system, user = client.calls[0]["messages"]
    return system["content"], user["content"]


def _sent_rows(client: MockLLMClient) -> list[dict]:
    _, user = _sent_messages(client)
    return json.loads(user.split("Source rows:\n", 1)[1])


# --- Fallback template --------------------------------------------------------------------


def test_explain_fallback_when_no_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = explain_with_meta(_alert(), _rows(), fallback_template=_TEMPLATE)
    assert result.source == "fallback"
    assert result.rejected_numbers == ()
    assert result.text == "Charge 12,99 EUR (bank.csv:0)"


def test_explain_money_placeholder_formats_amount() -> None:
    alert = _alert({"yearly_cost": "155.88"})
    assert fill_fallback("{yearly_cost:money}", alert) == "155,88 EUR"


def test_explain_plain_placeholder_inserts_as_string() -> None:
    alert = _alert({"charge_count": "12"})
    assert fill_fallback("{charge_count}", alert) == "12"


def test_explain_source_refs_placeholder() -> None:
    alert = _alert(refs=["bank.csv:0", "bank.csv:1"])
    assert fill_fallback("{source_refs}", alert) == "bank.csv:0, bank.csv:1"


def test_explain_unknown_placeholder_left_as_is() -> None:
    assert fill_fallback("x {unknown} y", _alert()) == "x {unknown} y"


def test_fill_fallback_is_public() -> None:
    alert = _alert({"yearly_cost": "155.88", "n": 3})
    assert fill_fallback("{yearly_cost:money} ({n})", alert) == "155,88 EUR (3)"
    assert not hasattr(explainer, "_fill_fallback")


# --- Prompt and mock ----------------------------------------------------------------------


def test_build_prompt_includes_source_refs() -> None:
    alert = _alert(refs=["bank.csv:0", "bank.csv:1"])
    client = MockLLMClient(["Charge 12.99 EUR (bank.csv:0)"])
    explain(alert, _rows(), fallback_template=_TEMPLATE, client=client)
    system, _ = _sent_messages(client)
    assert "bank.csv:0" in system
    assert "bank.csv:1" in system


def test_build_prompt_includes_no_invention_instruction() -> None:
    client = MockLLMClient(["Charge 12.99 EUR (bank.csv:0)"])
    explain(_alert(), _rows(), fallback_template=_TEMPLATE, client=client)
    system, _ = _sent_messages(client)
    assert _NO_INVENTION in system
    assert client.calls[0]["temperature"] == 0


def test_mock_client_chat_completions_create_resolves() -> None:
    client = MockLLMClient(["x"])
    response = client.chat.completions.create(model="m")
    assert response.choices[0].message.content == "x"
    assert client.calls == [{"model": "m"}]


# --- explain_with_meta --------------------------------------------------------------------


def test_explain_with_meta_returns_explanation_dataclass() -> None:
    client = MockLLMClient(["Charge 12.99 EUR (bank.csv:0)"])
    result = explain_with_meta(_alert(), _rows(), fallback_template=_TEMPLATE, client=client)
    assert isinstance(result, Explanation)
    assert result.text
    assert result.source in ("llm", "fallback")
    assert isinstance(result.rejected_numbers, tuple)


def test_explain_with_meta_llm_source_on_success() -> None:
    client = MockLLMClient(["Charge 12.99 EUR (bank.csv:0)"])
    result = explain_with_meta(_alert(), _rows(), fallback_template=_TEMPLATE, client=client)
    assert result.source == "llm"
    assert result.rejected_numbers == ()
    assert result.text == "Charge 12.99 EUR (bank.csv:0)"
    assert len(client.calls) == LLM_MAX_RETRIES == 1


def _run(answer: str, alert: Alert | None = None, rows: pd.DataFrame | None = None) -> Explanation:
    return explain_with_meta(
        alert or _alert(),
        _rows() if rows is None else rows,
        fallback_template=_TEMPLATE,
        client=MockLLMClient([answer]),
    )


def test_explain_number_guard_european_format_passes() -> None:
    assert _run("Charged 12,99 EUR (bank.csv:0)").source == "llm"


def test_explain_number_guard_european_thousands_passes() -> None:
    alert = _alert({"monthly_cost": "12.99", "total": "1060.00"})
    assert _run("Total 1.060,00 EUR (bank.csv:0)", alert).source == "llm"


def test_explain_number_guard_two_amounts_in_one_sentence_pass() -> None:
    alert = _alert({"monthly_cost": "15.99", "yearly_cost": "191.88"})
    result = _run("15,99 EUR monthly, 191,88 EUR yearly (bank.csv:0)", alert)
    assert result.source == "llm"


def test_explain_number_guard_glued_allowed_number_passes() -> None:
    alert = _alert({"monthly_cost": "15.99"})
    assert _run("Charged 15.99EUR (bank.csv:0)", alert).source == "llm"


def test_explain_number_guard_rejects_made_up_number_equal_to_row_index() -> None:
    alert = _alert({"yearly_cost": "155.88"}, refs=["bank.csv:3"])
    rows = _rows("bank.csv:3")
    bad = _run("Charged 3 EUR (bank.csv:3)", alert, rows)
    assert bad.source == "fallback"
    assert bad.rejected_numbers == ("3",)
    good = _run("Yearly cost 155,88 EUR (bank.csv:3)", alert, rows)
    assert good.source == "llm"


def test_explain_number_guard_rejects_invented_number_glued_to_letters() -> None:
    result = _run("Charged 12.99 EUR, invoice F2026099 (bank.csv:0)")
    assert result.source == "fallback"
    assert "2026099" in result.rejected_numbers


def test_explain_number_guard_rejects_iban_shaped_token() -> None:
    result = _run("Paid to DE00 0000 0000 0000 0000 00 (bank.csv:0)")
    assert result.source == "fallback"
    assert result.text == "Charge 12,99 EUR (bank.csv:0)"


def test_explain_number_guard_rejects_malformed_date() -> None:
    result = _run("Charged on 31/02/2026 (bank.csv:0)")
    assert result.source == "fallback"
    assert "31/02/2026" in result.rejected_numbers


def test_tokenise_removes_dates_then_refs_then_numbers() -> None:
    tokens = _tokenise("on 2026-01-15, see bank.csv:3: 12,99 EUR and 15.99EUR", ["bank.csv:3"])
    assert tokens.dates == {date(2026, 1, 15)}
    assert tokens.numbers == ("12,99", "15.99")
    assert tokens.ibans == ()
    assert tokens.malformed_dates == ()


def test_allowed_decimals_excludes_row_numbers_and_date_parts() -> None:
    alert = _alert({"yearly_cost": "155.88"}, refs=["bank.csv:3"])
    allowed = _allowed_decimals(alert, _rows("bank.csv:3"))
    assert allowed == {Decimal("12.99"), Decimal("155.88")}
    for forbidden in (3, 2026, 1, 15):
        assert Decimal(forbidden) not in allowed


def test_explain_number_guard_rejects_hallucinated_number() -> None:
    result = _run("Charged 999.99 EUR (bank.csv:0)")
    assert result.source == "fallback"
    assert result.rejected_numbers == ("999.99",)


def test_explain_number_guard_passes_valid_response() -> None:
    assert _run("Charged 12.99 EUR (bank.csv:0)").source == "llm"


def test_explain_date_guard_rejects_hallucinated_date() -> None:
    result = _run("Charged 12.99 EUR on 2026-05-05 (bank.csv:0)")
    assert result.source == "fallback"
    assert result.rejected_numbers == ("2026-05-05",)


def test_explain_date_guard_passes_row_date() -> None:
    result = _run("Charged 12.99 EUR on 2026-01-15 (bank.csv:0)")
    assert result.source == "llm"
    assert _tokenise("2026-01-15").numbers == ()


# --- Failure paths ------------------------------------------------------------------------


def test_explain_fallback_on_api_error() -> None:
    client = MockLLMClient([None])
    result = explain_with_meta(_alert(), _rows(), fallback_template=_TEMPLATE, client=client)
    assert result.source == "fallback"
    assert result.text == "Charge 12,99 EUR (bank.csv:0)"
    assert len(client.calls) == 1


def test_explain_openai_import_error_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    monkeypatch.setitem(sys.modules, "openai", None)
    result = explain_with_meta(_alert(), _rows(), fallback_template=_TEMPLATE)
    assert result.source == "fallback"


def test_explain_openai_client_built_with_no_sdk_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    class FakeOpenAI(MockLLMClient):
        def __init__(self, **kwargs):
            captured.update(kwargs)
            super().__init__(["Charged 12.99 EUR (bank.csv:0)"])

    fake_module = types.ModuleType("openai")
    fake_module.OpenAI = FakeOpenAI  # type: ignore[attr-defined]
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    monkeypatch.setitem(sys.modules, "openai", fake_module)
    result = explain_with_meta(_alert(), _rows(), fallback_template=_TEMPLATE)
    assert captured["timeout"] == LLM_TIMEOUT_SECONDS
    assert captured["max_retries"] == 0
    assert result.source == "llm"


# --- Rows sent to the model ---------------------------------------------------------------


def test_explain_rows_json_has_iso_dates() -> None:
    client = MockLLMClient(["Charged 12.99 EUR (bank.csv:0)"])
    explain(_alert(), _rows(), fallback_template=_TEMPLATE, client=client)
    _, user = _sent_messages(client)
    assert "2026-01-15" in user
    assert "T00:00" not in user


def test_explain_only_safe_columns_sent() -> None:
    client = MockLLMClient(["Charged 12.99 EUR (bank.csv:0)"])
    explain(_alert(), _rows(), fallback_template=_TEMPLATE, client=client)
    (row,) = _sent_rows(client)
    assert "id" not in row
    assert "description" not in row
    assert "iban" not in row
    _, user = _sent_messages(client)
    assert _FAKE_IBAN not in user


def test_explain_row_columns_parameter_selects_columns() -> None:
    client = MockLLMClient(["Total 1.060,00 EUR (inv.csv:0)"])
    alert = _alert({"total": "1060.00"}, refs=["inv.csv:0"])
    explain(
        alert,
        _invoice_rows(),
        fallback_template="{source_refs}",
        client=client,
        row_columns=("invoice_number", "total", "source_ref"),
    )
    (row,) = _sent_rows(client)
    assert set(row) == {"invoice_number", "total", "source_ref"}


def test_explain_default_row_columns_unchanged() -> None:
    client = MockLLMClient(["Charged 12.99 EUR (bank.csv:0)"])
    explain(_alert(), _rows(), fallback_template=_TEMPLATE, client=client, row_columns=None)
    (row,) = _sent_rows(client)
    assert set(row) == _DEFAULT_KEYS


def test_explain_invoice_date_columns_sent_as_iso_and_guarded() -> None:
    alert = _alert({"total": "1060.00"}, refs=["inv.csv:0"])
    rows = _invoice_rows()

    def run(answer: str) -> tuple[Explanation, MockLLMClient]:
        client = MockLLMClient([answer])
        result = explain_with_meta(
            alert,
            rows,
            fallback_template="{source_refs}",
            client=client,
            row_columns=_INVOICE_COLUMNS,
        )
        return result, client

    good, client = run("Total 1.060,00 EUR due 2026-02-14 (inv.csv:0)")
    _, user = _sent_messages(client)
    assert "2026-01-15" in user
    assert "2026-02-14" in user
    assert "T00:00" not in user
    assert good.source == "llm"

    bad, _ = run("Total 1.060,00 EUR due 2026-03-01 (inv.csv:0)")
    assert bad.source == "fallback"
    assert bad.rejected_numbers == ("2026-03-01",)

    assert _allowed_decimals(alert, rows) == {Decimal("1060.00")}


def test_explain_iban_column_never_sent_even_if_listed() -> None:
    client = MockLLMClient(["Charged 12.99 EUR (bank.csv:0)"])
    explain(
        _alert(),
        _rows(),
        fallback_template=_TEMPLATE,
        client=client,
        row_columns=("id", "description", "iban", "amount", "source_ref"),
    )
    (row,) = _sent_rows(client)
    assert set(row) == {"amount", "source_ref"}
    _, user = _sent_messages(client)
    assert _FAKE_IBAN not in user
    assert "Monthly plan" not in user


def test_explain_masked_iban_in_alert_data_passes_guard() -> None:
    alert = _alert({"monthly_cost": "12.99", "iban_masked": "****1332"})
    assert _run("Account ****1332 charged 12.99 EUR (bank.csv:0)", alert).source == "llm"
    bad = _run(f"Account {_FAKE_IBAN} charged 12.99 EUR (bank.csv:0)", alert)
    assert bad.source == "fallback"


def test_allowed_dates_collects_every_date_column() -> None:
    alert = _alert({}, refs=["inv.csv:0"])
    rows = _invoice_rows()
    assert _allowed_dates(alert, rows) == {date(2026, 1, 15), date(2026, 2, 14)}
    allowed = _allowed_decimals(alert, rows)
    for part in (2026, 1, 15, 2, 14):
        assert Decimal(part) not in allowed


# --- Property tests -----------------------------------------------------------------------


@settings(max_examples=200)
@given(
    foreign=st.decimals(min_value=Decimal("10000"), max_value=Decimal("99999"), places=2),
)
def test_number_guard_any_foreign_decimal_triggers_fallback(foreign: Decimal) -> None:
    alert = _alert({"monthly_cost": "15.99", "yearly_cost": "191.88"})
    answer = f"Charged 15.99 EUR, 191.88 EUR yearly and {foreign:f} EUR (bank.csv:0)"
    result = explain_with_meta(
        alert, _rows(), fallback_template=_TEMPLATE, client=MockLLMClient([answer])
    )
    assert result.source == "fallback"
    assert f"{foreign:f}" in result.rejected_numbers


@settings(max_examples=200)
@given(
    first=st.decimals(min_value=Decimal("0"), max_value=Decimal("1000000"), places=2),
    second=st.decimals(min_value=Decimal("0"), max_value=Decimal("1000000"), places=2),
)
def test_number_guard_all_data_values_pass(first: Decimal, second: Decimal) -> None:
    alert = _alert({"monthly_cost": f"{first:f}", "yearly_cost": f"{second:f}"})
    answer = f"Charged {first:f} EUR and {second:f} EUR yearly (bank.csv:0)"
    ok, rejected = _passes_number_guard(answer, alert, _rows())
    assert ok, rejected
