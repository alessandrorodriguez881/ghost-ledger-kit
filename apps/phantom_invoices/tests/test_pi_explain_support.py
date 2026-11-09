"""Tests for explain_support.py: templates, explanation rows and the stub client (Task P15).

No test touches the network. The recording client below is a small test double with the same
shape as the ledger-core MockLLMClient (chat and completions are properties, create records the
keyword arguments); it is defined here because the ledger-core test double is not part of
ledger_kit.
"""

import json
import re
import sys
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from apps.phantom_invoices.detectors import run_pi_detectors
from apps.phantom_invoices.detectors.iban_change import VERIFY_BY_PHONE_MESSAGE
from apps.phantom_invoices.detectors.utils import is_missing
from apps.phantom_invoices.explain_support import (
    ROW_COLUMNS,
    SAME_DAY_TEMPLATES,
    TEMPLATES,
    HallucinatingStubClient,
    build_explain_rows,
    explain_alert,
    guard_badge,
    template_for,
)
from apps.phantom_invoices.tests.pi_builders import (
    format_iban,
    iban_for_supplier,
    make_invoices,
    make_payments,
    make_suppliers,
)
from ledger_kit.explainer import Explanation, explain_with_meta, fill_fallback
from ledger_kit.models import Alert
from ledger_kit.utils.money import format_amount

INJECTED = "99999.99"
FORBIDDEN_ROW_KEYS = frozenset({"iban", "supplier_tax_id", "tax_id", "id", "description"})
PLACEHOLDER = re.compile(r"[{}]")
MONEY_PLACEHOLDER = re.compile(r"\{(\w+):money\}")
ADVICE_WORDS = re.compile(r"\b(should|cancel|refuse|pay|ignore|dispute|contact|call)\b", re.I)

VARIANT_KEYS: list[tuple[str, str]] = [
    ("pi.duplicate_invoice", "same_number"),
    ("pi.duplicate_invoice", "near_identical_number"),
    ("pi.duplicate_invoice", "same_total_close_dates"),
    ("pi.iban_change", "invoice_iban_differs_from_master"),
    ("pi.iban_change", "payment_to_non_master_iban"),
    ("pi.iban_change", "iban_invalid"),
    ("pi.vat_error", "vat_amount_mismatch"),
    ("pi.vat_error", "total_mismatch"),
    ("pi.vat_error", "vat_rate_not_allowed"),
    ("pi.reconciliation", "invoice_overdue"),
    ("pi.reconciliation", "payment_without_invoice"),
]
SUPPLIER_NAMES = ["Inmuebles Valdemar, S.L.", "Luigi Rossi (Reformas)", "Sophie Dupont"]

DUPLICATE_VARIANTS: list[tuple[str, str]] = [
    ("pi.duplicate_invoice", "same_number"),
    ("pi.duplicate_invoice", "near_identical_number"),
    ("pi.duplicate_invoice", "same_total_close_dates"),
]
IBAN_CRITICAL_VARIANTS: list[tuple[str, str]] = [
    ("pi.iban_change", "invoice_iban_differs_from_master"),
    ("pi.iban_change", "payment_to_non_master_iban"),
]
ISSUE_DAY = "2026-10-06"


class _RecordingClient:
    """OpenAI-shaped client that records every call and returns a fixed answer or raises."""

    def __init__(self, answer: str = "", error: Exception | None = None) -> None:
        self._answer = answer
        self._error = error
        self.calls: list[dict[str, Any]] = []

    @property
    def chat(self) -> "_RecordingClient":
        """Mimic client.chat."""
        return self

    @property
    def completions(self) -> "_RecordingClient":
        """Mimic client.chat.completions."""
        return self

    def create(self, **kwargs: Any) -> SimpleNamespace:
        """Record the call; raise the configured error or return the canned answer."""
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        message = SimpleNamespace(content=self._answer)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


Case = tuple[Alert, pd.DataFrame, pd.DataFrame, pd.DataFrame]


def _duplicate_alert(variant: str, first: str, last: str) -> Alert:
    """Build a duplicate-invoice alert whose invoices were issued on `first` and `last`."""
    days = (date.fromisoformat(last) - date.fromisoformat(first)).days
    return Alert(
        detector="pi.duplicate_invoice",
        severity="warning",
        title="Possible duplicate invoice",
        source_refs=["inv.csv:0", "inv.csv:1"],
        data={
            "variant": variant,
            "supplier_name": "Sophie Dupont",
            "invoice_count": 2,
            "total": "121.00",
            "first_issue_date": first,
            "last_issue_date": last,
            "days_apart": days,
        },
    )


def _expected_template(alert: Alert) -> str:
    """The template template_for must pick: the same-day wording when the dates are equal."""
    key = (alert.detector, alert.data["variant"])
    same_day = alert.data.get("first_issue_date") == alert.data.get("last_issue_date")
    if key in SAME_DAY_TEMPLATES and same_day:
        return SAME_DAY_TEMPLATES[key]
    return TEMPLATES[key]


def _pick(
    invoices: pd.DataFrame, suppliers: pd.DataFrame, payments: pd.DataFrame, variant: str
) -> Case:
    """Run the four detectors and return the single alert of `variant` with its three frames."""
    alerts = [
        alert
        for result in run_pi_detectors(invoices, suppliers, payments)
        for alert in result.alerts
        if alert.data["variant"] == variant
    ]
    assert len(alerts) == 1, variant
    return alerts[0], invoices, suppliers, payments


@pytest.fixture(scope="module")
def cases() -> dict[tuple[str, str], Case]:
    """One real alert per (detector, variant), each with the frames it came from."""
    other = format_iban(iban_for_supplier(1, other=True))
    no_suppliers, no_payments = make_suppliers([]), make_payments([])
    master = make_suppliers([{}])
    found: dict[tuple[str, str], Case] = {}

    def add(detector: str, case: Case) -> None:
        found[(detector, case[0].data["variant"])] = case

    same = make_invoices([{"invoice_number": "F-2026-0042"}] * 2)
    add("pi.duplicate_invoice", _pick(same, no_suppliers, no_payments, "same_number"))
    near = make_invoices(
        [
            {"invoice_number": "F-2026-0042", "issue_date": date(2026, 3, 1)},
            {"invoice_number": "F2026-042", "issue_date": date(2026, 3, 4)},
        ]
    )
    add("pi.duplicate_invoice", _pick(near, no_suppliers, no_payments, "near_identical_number"))
    close = make_invoices(
        [
            {"invoice_number": "AAA-1", "issue_date": date(2026, 3, 1)},
            {"invoice_number": "ZZZ-9", "issue_date": date(2026, 3, 4)},
        ]
    )
    add("pi.duplicate_invoice", _pick(close, no_suppliers, no_payments, "same_total_close_dates"))

    differs = make_invoices([{"iban": other}])
    add("pi.iban_change", _pick(differs, master, no_payments, "invoice_iban_differs_from_master"))
    to_other = make_payments([{"iban": other}])
    add(
        "pi.iban_change",
        _pick(make_invoices([]), master, to_other, "payment_to_non_master_iban"),
    )
    hyphenated = make_suppliers([{"iban": "ES88-2100-0418-5602-0005-1332"}])
    add("pi.iban_change", _pick(make_invoices([]), hyphenated, no_payments, "iban_invalid"))

    vat = make_invoices([{"vat_amount": Decimal("12.10")}])
    add("pi.vat_error", _pick(vat, no_suppliers, no_payments, "vat_amount_mismatch"))
    total = make_invoices([{"total": Decimal("130.00")}])
    add("pi.vat_error", _pick(total, no_suppliers, no_payments, "total_mismatch"))
    rate = make_invoices([{"vat_rate": Decimal("20")}])
    add("pi.vat_error", _pick(rate, no_suppliers, no_payments, "vat_rate_not_allowed"))

    unpaid = make_invoices([{"issue_date": date(2026, 1, 10)}])
    later = make_payments([{"counterparty": "Comercio Local Ficticio", "date": date(2026, 4, 15)}])
    add("pi.reconciliation", _pick(unpaid, master, later, "invoice_overdue"))
    twice = make_payments([{"date": date(2026, 3, 15)}, {"date": date(2026, 3, 20)}])
    add(
        "pi.reconciliation",
        _pick(make_invoices([{}]), master, twice, "payment_without_invoice"),
    )
    return found


def _rows(case: Case) -> pd.DataFrame:
    """Return the explanation rows of a case."""
    alert, invoices, suppliers, payments = case
    return build_explain_rows(alert, invoices, suppliers, payments)


def _llm_says(case: Case, text: str) -> tuple[Explanation, _RecordingClient]:
    """Explain a case with a client whose answer is `text`."""
    alert, invoices, suppliers, payments = case
    client = _RecordingClient(text)
    return explain_alert(alert, invoices, suppliers, payments, client=client), client


# Tier 1: normal cases


def test_templates_cover_every_variant() -> None:
    """TEMPLATES has exactly the 11 (detector, variant) keys of design section 12.4."""
    assert len(TEMPLATES) == 11
    assert set(TEMPLATES) == set(VARIANT_KEYS)


def test_every_variant_has_a_real_alert(cases: dict[tuple[str, str], Case]) -> None:
    """The case builder produces one real alert for each of the 11 variants."""
    assert set(cases) == set(VARIANT_KEYS)


@pytest.mark.parametrize("key", VARIANT_KEYS)
def test_every_template_fills_from_a_real_alert(
    cases: dict[tuple[str, str], Case], key: tuple[str, str]
) -> None:
    """No placeholder is left, amounts are European, and a cited source_ref is present."""
    alert = cases[key][0]
    template = template_for(alert)

    text = fill_fallback(template, alert)

    assert template == _expected_template(alert)
    assert PLACEHOLDER.search(text) is None, text
    assert any(ref in text for ref in alert.source_refs)
    for field in MONEY_PLACEHOLDER.findall(template):
        assert format_amount(Decimal(str(alert.data[field]))) in text


def test_row_columns_reach_the_client(cases: dict[tuple[str, str], Case]) -> None:
    """The rows sent to the client hold ROW_COLUMNS only: no iban, tax id, id or description."""
    case = cases[("pi.iban_change", "invoice_iban_differs_from_master")]
    filled = fill_fallback(template_for(case[0]), case[0])

    meta, client = _llm_says(case, filled)

    assert meta.source == "llm"
    user_content = client.calls[0]["messages"][1]["content"]
    sent = json.loads(user_content.split("Source rows:\n", 1)[1])
    keys = {key for row in sent for key in row}
    assert keys <= set(ROW_COLUMNS)
    assert keys.isdisjoint(FORBIDDEN_ROW_KEYS)
    assert {row["source_ref"] for row in sent} == set(case[0].source_refs)


@pytest.mark.parametrize("key", VARIANT_KEYS)
def test_guard_accepts_a_sentence_restating_only_alert_data(
    cases: dict[tuple[str, str], Case], key: tuple[str, str]
) -> None:
    """The filled template, as an LLM answer, passes the number guard for every variant."""
    case = cases[key]
    filled = fill_fallback(template_for(case[0]), case[0])

    meta, _ = _llm_says(case, filled)

    assert meta.source == "llm", (key, meta.rejected_numbers)
    assert meta.text == filled
    assert meta.rejected_numbers == ()


def test_build_explain_rows_takes_rows_from_all_three_frames() -> None:
    """Payment rows give only currency/source_ref, master rows only supplier_name/source_ref."""
    invoices, suppliers, payments = make_invoices([{}]), make_suppliers([{}]), make_payments([{}])
    refs = ["pay.csv:0", "inv.csv:0", "sup.csv:0"]
    alert = Alert(
        detector="pi.reconciliation",
        severity="warning",
        title="t",
        source_refs=refs,
        data={"variant": "payment_without_invoice"},
    )

    rows = build_explain_rows(alert, invoices, suppliers, payments)

    assert list(rows.columns) == list(ROW_COLUMNS)
    assert list(rows["source_ref"]) == refs
    pay, inv, sup = rows.to_dict("records")
    assert pay["currency"] == "EUR"
    assert all(is_missing(pay[c]) for c in ROW_COLUMNS if c not in ("currency", "source_ref"))
    assert inv["invoice_number"] == "F-2026-0001"
    assert inv["total"] == Decimal("121.00")
    assert sup["supplier_name"] == "Suministros Ibéricos Aurora, S.L."
    assert all(is_missing(sup[c]) for c in ROW_COLUMNS if c not in ("supplier_name", "source_ref"))


def test_hallucinating_stub_is_rejected_by_number_guard(
    cases: dict[tuple[str, str], Case],
) -> None:
    """The stub's foreign number is rejected for every variant; the filled template is used."""
    for key in VARIANT_KEYS:
        alert, invoices, suppliers, payments = cases[key]
        filled = fill_fallback(template_for(alert), alert)

        meta = explain_with_meta(
            alert,
            build_explain_rows(alert, invoices, suppliers, payments),
            fallback_template=template_for(alert),
            client=HallucinatingStubClient(filled),
            row_columns=ROW_COLUMNS,
        )

        assert meta.source == "fallback", key
        assert meta.rejected_numbers == (INJECTED,), key
        assert meta.text == filled, key


def test_guard_badge_three_plus_one_texts() -> None:
    """The four badge texts (DN-8)."""
    llm = Explanation("x", "llm", ())
    plain = Explanation("x", "fallback", ())
    rejected = Explanation("x", "fallback", (INJECTED,))

    assert guard_badge(llm, True) == "🤖 ✓ LLM text verified by number guard"
    assert guard_badge(plain, False) == "📋 Template (no API key)"
    assert guard_badge(rejected, True) == f"⚠️ LLM answer rejected: invented number {INJECTED}"
    assert guard_badge(plain, True) == "📋 Template (LLM unavailable)"


def test_stub_shape_matches_mock_client() -> None:
    """chat and completions are properties; create returns choices[0].message.content."""
    assert isinstance(HallucinatingStubClient.chat, property)
    assert isinstance(HallucinatingStubClient.completions, property)
    stub = HallucinatingStubClient("Filled text.")

    assert stub.chat is stub
    assert stub.chat.completions is stub
    response = stub.chat.completions.create(model="m", temperature=0, messages=[])
    content = response.choices[0].message.content
    assert content == f"Filled text. Total exposure: {INJECTED} EUR."
    assert HallucinatingStubClient.INJECTED_NUMBER == INJECTED


# Wording polish (REQ-SC-07, REQ-SC-08, REQ-SC-09)


def test_same_day_templates_cover_the_three_duplicate_variants() -> None:
    """SAME_DAY_TEMPLATES refines exactly the duplicate variants; TEMPLATES keeps its 11 keys."""
    assert set(SAME_DAY_TEMPLATES) == set(DUPLICATE_VARIANTS)
    assert set(SAME_DAY_TEMPLATES) <= set(TEMPLATES)
    for key, template in SAME_DAY_TEMPLATES.items():
        assert "{first_issue_date}" in template, key
        assert "{last_issue_date}" not in template, key
        assert "between" not in template and "days_apart" not in template, key


@pytest.mark.parametrize("key", DUPLICATE_VARIANTS)
def test_duplicates_issued_on_one_date_read_issued_on(key: tuple[str, str]) -> None:
    """Equal issue dates give 'issued on <date>', never 'between D and D' or '0 days apart'."""
    alert = _duplicate_alert(key[1], ISSUE_DAY, ISSUE_DAY)

    text = fill_fallback(template_for(alert), alert)

    assert f"issued on {ISSUE_DAY}" in text
    assert "between" not in text
    assert "0 days apart" not in text
    assert PLACEHOLDER.search(text) is None, text
    assert "inv.csv:0" in text and "inv.csv:1" in text


def test_duplicates_issued_on_different_dates_keep_the_range_wording() -> None:
    """Different issue dates keep 'between D1 and D2' (same_number) and 'N days apart'."""
    same_number = _duplicate_alert("same_number", ISSUE_DAY, "2026-10-09")
    near = _duplicate_alert("near_identical_number", ISSUE_DAY, "2026-10-09")
    close = _duplicate_alert("same_total_close_dates", ISSUE_DAY, "2026-10-09")

    assert "issued between 2026-10-06 and 2026-10-09" in fill_fallback(
        template_for(same_number), same_number
    )
    for alert in (near, close):
        text = fill_fallback(template_for(alert), alert)
        assert "issued 3 days apart" in text
        assert "issued on" not in text


def test_real_same_number_alert_with_one_issue_date_reads_issued_on(
    cases: dict[tuple[str, str], Case],
) -> None:
    """The detector's own same_number alert (both invoices on one day) uses the new wording."""
    alert = cases[("pi.duplicate_invoice", "same_number")][0]
    assert alert.data["first_issue_date"] == alert.data["last_issue_date"]

    text = fill_fallback(template_for(alert), alert)

    assert f"issued on {alert.data['first_issue_date']}" in text
    assert "between" not in text


@pytest.mark.parametrize("key", DUPLICATE_VARIANTS)
def test_guard_accepts_the_same_day_wording_and_rejects_a_foreign_date(
    key: tuple[str, str],
) -> None:
    """The same-day sentence passes the guard; an extra date that is in no field is rejected."""
    alert = _duplicate_alert(key[1], ISSUE_DAY, ISSUE_DAY)
    case: Case = (alert, make_invoices([{}, {}]), make_suppliers([]), make_payments([]))
    filled = fill_fallback(template_for(alert), alert)

    accepted, _ = _llm_says(case, filled)
    rejected, _ = _llm_says(case, f"{filled} Reminded on 1999-01-01.")

    assert accepted.source == "llm" and accepted.text == filled
    assert rejected.source == "fallback"
    assert rejected.rejected_numbers == ("1999-01-01",)
    assert rejected.text == filled


@pytest.mark.parametrize("key", IBAN_CRITICAL_VARIANTS)
def test_critical_iban_templates_do_not_repeat_the_verification_message(
    cases: dict[tuple[str, str], Case], key: tuple[str, str]
) -> None:
    """The phone box carries the message; the explanation text of the card does not."""
    alert = cases[key][0]
    text = fill_fallback(template_for(alert), alert)

    assert "{verification_message}" not in TEMPLATES[key]
    assert alert.data["verification_message"] == VERIFY_BY_PHONE_MESSAGE  # the box still has it
    assert VERIFY_BY_PHONE_MESSAGE not in text
    assert "by phone" not in text
    assert any(ref in text for ref in alert.source_refs)
    assert PLACEHOLDER.search(text) is None, text


# Tier 2: edge cases


def test_guard_rejects_hallucinated_amount(cases: dict[tuple[str, str], Case]) -> None:
    """An amount that is in no row and no alert field is rejected."""
    case = cases[("pi.vat_error", "total_mismatch")]
    filled = fill_fallback(template_for(case[0]), case[0])

    meta, _ = _llm_says(case, f"{filled} The exposure is 424,20 EUR.")

    assert meta.source == "fallback"
    assert meta.rejected_numbers == ("424,20",)
    assert meta.text == filled


def test_guard_rejects_uncited_date(cases: dict[tuple[str, str], Case]) -> None:
    """A date that is in no row and no alert field is rejected."""
    case = cases[("pi.reconciliation", "invoice_overdue")]
    filled = fill_fallback(template_for(case[0]), case[0])

    meta, _ = _llm_says(case, f"{filled} It was first reminded on 1999-01-01.")

    assert meta.source == "fallback"
    assert meta.rejected_numbers == ("1999-01-01",)


def test_guard_rejects_iban_shaped_token(cases: dict[tuple[str, str], Case]) -> None:
    """A full IBAN in the answer is rejected."""
    case = cases[("pi.iban_change", "payment_to_non_master_iban")]
    filled = fill_fallback(template_for(case[0]), case[0])

    meta, _ = _llm_says(case, f"{filled} Account ES88 2100 0418 5602 0005 1332.")

    assert meta.source == "fallback"
    assert any(token.startswith("ES88") for token in meta.rejected_numbers)
    assert meta.text == filled


def test_no_api_key_returns_fallback_without_network(
    cases: dict[tuple[str, str], Case], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without a key and without a client the filled template is returned (REQ-PI-44)."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setitem(sys.modules, "openai", None)  # any import of the SDK would fail
    alert, invoices, suppliers, payments = cases[("pi.vat_error", "vat_amount_mismatch")]

    meta = explain_alert(alert, invoices, suppliers, payments)

    assert meta.source == "fallback"
    assert meta.rejected_numbers == ()
    assert meta.text == fill_fallback(template_for(alert), alert)


def test_api_error_returns_fallback(cases: dict[tuple[str, str], Case]) -> None:
    """A client that raises gives the filled template, after a single attempt."""
    alert, invoices, suppliers, payments = cases[("pi.duplicate_invoice", "same_number")]
    client = _RecordingClient(error=RuntimeError("simulated timeout"))

    meta = explain_alert(alert, invoices, suppliers, payments, client=client)

    assert meta.source == "fallback"
    assert meta.rejected_numbers == ()
    assert meta.text == fill_fallback(template_for(alert), alert)
    assert len(client.calls) == 1


def test_template_for_unknown_variant_raises_keyerror_with_clear_message() -> None:
    """An alert whose variant has no template raises a KeyError that names it."""
    alert = Alert(
        detector="pi.vat_error",
        severity="info",
        title="t",
        source_refs=["inv.csv:0"],
        data={"variant": "no_such_variant"},
    )
    no_variant = alert.model_copy(update={"data": {}})

    with pytest.raises(KeyError, match="no_such_variant"):
        template_for(alert)
    with pytest.raises(KeyError, match="pi.vat_error"):
        template_for(no_variant)


def test_build_explain_rows_empty_and_non_frame_inputs() -> None:
    """Empty frames, None and frames without source_ref give an empty frame with ROW_COLUMNS."""
    alert = Alert(
        detector="pi.vat_error",
        severity="warning",
        title="t",
        source_refs=["inv.csv:0"],
        data={"variant": "total_mismatch"},
    )

    for frames in (
        (pd.DataFrame(), pd.DataFrame(), pd.DataFrame()),
        (None, None, None),
        (pd.DataFrame({"x": [1]}), "text", 5),
        (make_invoices([]), make_suppliers([]), make_payments([])),
    ):
        rows = build_explain_rows(alert, *frames)  # type: ignore[arg-type]
        assert rows.empty
        assert list(rows.columns) == list(ROW_COLUMNS)


def test_templates_recommend_no_action() -> None:
    """Templates state facts only (Finance Rule 8)."""
    for key, template in TEMPLATES.items():
        assert ADVICE_WORDS.search(template) is None, key


def test_allowed_vat_rates_string_tokenises_as_four_numbers(
    cases: dict[tuple[str, str], Case],
) -> None:
    """'21, 10, 4, 0' is four numbers for the guard: it passes, while '21,10' is one invented."""
    case = cases[("pi.vat_error", "vat_rate_not_allowed")]
    filled = fill_fallback(template_for(case[0]), case[0])
    assert "(21, 10, 4, 0)" in filled

    accepted, _ = _llm_says(case, f"{filled} Supported rates: 21, 10, 4, 0.")
    rejected, _ = _llm_says(case, f"{filled} Supported rates: 21,10.")

    assert accepted.source == "llm"
    assert rejected.source == "fallback"
    assert rejected.rejected_numbers == ("21,10",)


def test_injected_number_not_in_any_alert(cases: dict[tuple[str, str], Case]) -> None:
    """The stub's number is in no alert payload, title or cited row, so the guard must fire."""
    for key, case in cases.items():
        assert INJECTED not in str(case[0].data), key
        assert INJECTED not in case[0].title, key
        assert INJECTED not in _rows(case).to_string(), key


# Tier 3: property-based tests


@settings(max_examples=200, deadline=None)
@given(
    total=st.decimals(
        min_value=Decimal("0.01"), max_value=Decimal("1000000"), places=2, allow_nan=False
    ),
    days=st.integers(min_value=0, max_value=6),
    count=st.integers(min_value=2, max_value=5),
    name=st.sampled_from(SUPPLIER_NAMES),
)
def test_guard_accepts_any_alert_data_sentence(
    total: Decimal, days: int, count: int, name: str
) -> None:
    """A sentence made only of alert data and cited cells always passes the guard."""
    alert = Alert(
        detector="pi.duplicate_invoice",
        severity="warning",
        title="Possible duplicate invoice",
        source_refs=["inv.csv:0", "inv.csv:1"],
        data={
            "variant": "same_total_close_dates",
            "supplier_name": name,
            "invoice_count": count,
            "total": str(total),
            "days_apart": days,
        },
    )
    invoices = make_invoices([{}, {}])
    filled = fill_fallback(template_for(alert), alert)
    client = _RecordingClient(filled)

    meta = explain_alert(alert, invoices, make_suppliers([]), make_payments([]), client=client)

    assert meta.source == "llm"
    assert meta.text == filled
