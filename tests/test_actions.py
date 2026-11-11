"""Tests for the Exorcise mechanism: check_figures, ledger_kit/actions.py, the widget (EX1, EX2).

Tier 1: a template fills from the alert and the extras; the number guard checks a draft. Tier 2:
empty and odd inputs, a draft that cannot be built or is rejected is None plus one warning.
Tier 3 (Hypothesis): any cited rows give lines that pass the guard; an invented figure never does.
No model, no network, no clock; every figure and name is synthetic.
"""

import ast
import logging
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import streamlit as st
from hypothesis import given, settings
from hypothesis import strategies as st_h
from streamlit.testing.v1 import AppTest

from ledger_kit.actions import (
    DEFAULT_LANGUAGE,
    DISCLAIMER,
    EXPANDER_TITLE,
    LANGUAGES,
    UNAVAILABLE,
    ActionTemplate,
    build_draft,
    file_name,
    fill,
    row_lines,
    word_count,
)
from ledger_kit.explainer import check_figures, explain_with_meta
from ledger_kit.models import Alert
from ledger_kit.replay import ReplayClient

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = str(ROOT / "tests" / "exorcise_script.py")
WIDGET_SOURCE = ROOT / "ledger_kit" / "ui" / "exorcise.py"
TIMEOUT_SECONDS = 30
LOG = "ledger_kit.actions"


def _alert(count: Any = 2) -> Alert:
    return Alert(
        detector="zs.charges_after_cancellation",
        severity="critical",
        title="Charge after cancellation: GYMPLUS",
        source_refs=["s.csv:2", "s.csv:3"],
        data={
            "counterparty": "GYMPLUS",
            "cancellation_date": "2026-07-31",
            "post_cancellation_count": count,
            "total_charged_after": "17.98",
        },
    )


def _rows(*specs: tuple[str, date, str]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": day,
                "amount": Decimal(amount),
                "flow": "debit",
                "currency": "EUR",
                "counterparty": "GYMPLUS",
                "source_ref": ref,
            }
            for ref, day, amount in specs
        ]
    )


ROWS = _rows(("s.csv:2", date(2026, 8, 9), "8.99"), ("s.csv:3", date(2026, 9, 8), "8.99"))
TEXTS = {
    "en": "Since {cancellation_date} you charged {post_cancellation_count:times}, "
    "{total_charged_after:money}:\n{lines}",
    "es": "Desde {cancellation_date} cobraron {post_cancellation_count:times}, "
    "{total_charged_after:money}:\n{lines}",
}


def _template(texts: dict[str, str] | None = None) -> ActionTemplate:
    def extras(_alert_arg: Alert, rows: pd.DataFrame, _language: str) -> dict[str, str]:
        return {"lines": row_lines(rows)}

    return ActionTemplate("sample", texts or TEXTS, extras)


# --- Tier 1: fill and the format specs ------------------------------------------------------


def test_fill_uses_the_alert_data_the_extras_and_the_specs_in_english() -> None:
    text = fill(TEXTS["en"], _alert(), "en", {"lines": "L"})

    assert text == "Since 2026-07-31 you charged 2 times, 17,98 EUR:\nL"


def test_fill_writes_the_count_in_spanish() -> None:
    assert "cobraron 2 veces" in fill(TEXTS["es"], _alert(), "es", {"lines": "L"})
    assert "cobraron 1 vez," in fill(TEXTS["es"], _alert(1), "es", {"lines": "L"})
    assert "charged 1 time," in fill(TEXTS["en"], _alert(1), "en", {"lines": "L"})


def test_an_extra_wins_over_the_alert_data() -> None:
    assert fill("{counterparty}", _alert(), "en", {"counterparty": "OTHER"}) == "OTHER"


def test_the_percent_spec_uses_the_european_format() -> None:
    alert = Alert(
        detector="x.y", severity="info", title="t", source_refs=["f:1"], data={"rise": "5.0"}
    )

    assert fill("{rise:pct}", alert, "en") == "5,0 %"


def test_the_spanish_and_english_languages_are_offered_english_first() -> None:
    assert LANGUAGES == (("en", "English"), ("es", "Español"))
    assert DEFAULT_LANGUAGE == "en"
    assert set(DISCLAIMER) == set(UNAVAILABLE) == {"en", "es"}


# --- Tier 1: rows, file name, words -----------------------------------------------------------


def test_row_lines_write_date_and_european_amount_in_date_order() -> None:
    later_first = _rows(
        ("s.csv:3", date(2026, 9, 8), "1234.50"),
        ("s.csv:2", date(2026, 8, 9), "8.9"),
    )

    assert row_lines(later_first) == "2026-08-09: 8,90 EUR\n2026-09-08: 1.234,50 EUR"


def test_file_name_carries_detector_language_and_the_start_of_the_id() -> None:
    alert = _alert()

    assert file_name(alert, "en") == f"exorcise-zs-charges-after-cancellation-en-{alert.id[:8]}.txt"
    other = Alert(
        detector="pi.iban_change", severity="critical", title="t", source_refs=["f:1"], data={}
    )
    assert file_name(other, "es") == f"exorcise-pi-iban-change-es-{other.id[:8]}.txt"


def test_word_count_counts_pieces_between_spaces() -> None:
    assert word_count("a  b\nc\t d") == 4
    assert word_count("") == 0


# --- Tier 1: build_draft and the number guard -------------------------------------------------


@pytest.mark.parametrize("language", ["en", "es"])
def test_build_draft_fills_checks_and_is_the_same_on_every_run(language: str) -> None:
    first = build_draft(_alert(), ROWS, _template(), language)
    second = build_draft(_alert(), ROWS, _template(), language)

    assert first is not None and first == second
    assert "2026-08-09: 8,99 EUR" in first and "17,98 EUR" in first
    assert check_figures(first, _alert(), ROWS) == (True, ())


def test_check_figures_accepts_cited_figures_and_rejects_invented_ones() -> None:
    alert = _alert()

    assert check_figures("Charged 8,99 EUR on 2026-08-09.", alert, ROWS) == (True, ())
    passed, rejected = check_figures("It costs 98765,43 EUR.", alert, ROWS)
    assert not passed and rejected == ("98765,43",)
    assert not check_figures("Charged on 2026-12-25.", alert, ROWS)[0]
    assert not check_figures("Pay to ES88 2100 0418 5602 0005 1332 now.", alert, ROWS)[0]


@pytest.mark.parametrize("text", ["Charged 8,99 EUR on 2026-08-09.", "It costs 98765,43 EUR."])
def test_check_figures_agrees_with_the_guard_a_model_answer_goes_through(text: str) -> None:
    alert = _alert()
    meta = explain_with_meta(alert, ROWS, fallback_template="template", client=ReplayClient(text))

    assert (meta.source == "llm") is check_figures(text, alert, ROWS)[0]


# --- Tier 2: odd inputs and failures ------------------------------------------------------------


def test_row_lines_of_nothing_is_empty_and_one_row_is_one_line() -> None:
    assert row_lines(pd.DataFrame()) == ""
    assert row_lines(_rows(("s.csv:2", date(2026, 8, 9), "8.99"))) == "2026-08-09: 8,99 EUR"


def test_two_rows_with_the_same_source_ref_are_both_listed() -> None:
    twice = _rows(("s.csv:2", date(2026, 8, 9), "8.99"), ("s.csv:2", date(2026, 8, 9), "8.99"))

    assert row_lines(twice).count("\n") == 1


def test_a_row_without_a_date_cannot_be_listed() -> None:
    broken = ROWS.assign(date=[None, None])

    with pytest.raises(ValueError, match="date"):
        row_lines(broken)


def test_the_draft_of_an_empty_ledger_holds_the_alert_figures_only() -> None:
    draft = build_draft(_alert(), pd.DataFrame(), _template(), "en")

    assert draft is not None and "Since 2026-07-31" in draft


@pytest.mark.parametrize(
    ("text", "why"),
    [
        ("Hello {no_such_key}", "no_such_key"),
        ("Hello {counterparty:money}", "GYMPLUS"),
        ("Hello {counterparty:nope}", "nope"),
        ("You owe 99999.99 EUR.", "99999.99"),
    ],
)
def test_a_draft_that_cannot_be_built_or_is_rejected_is_none_with_one_warning(
    text: str, why: str, caplog: pytest.LogCaptureFixture
) -> None:
    alert = _alert()
    template = ActionTemplate("sample", {"en": text, "es": text})
    with caplog.at_level(logging.WARNING, logger=LOG):
        draft = build_draft(alert, ROWS, template, "en")

    assert draft is None
    [record] = [r for r in caplog.records if r.name == LOG]
    assert alert.id in record.getMessage() and why in record.getMessage()


def test_a_missing_language_is_none_with_one_warning(caplog: pytest.LogCaptureFixture) -> None:
    template = ActionTemplate("sample", {"en": "Hello"})
    with caplog.at_level(logging.WARNING, logger=LOG):
        assert build_draft(_alert(), ROWS, template, "es") is None

    assert len([r for r in caplog.records if r.name == LOG]) == 1


# --- Tier 3: properties -------------------------------------------------------------------------

_DAYS = st_h.dates(min_value=date(2020, 1, 1), max_value=date(2030, 12, 31))
_AMOUNTS = st_h.decimals(min_value=Decimal("0.01"), max_value=Decimal("99999.99"), places=2)


@st_h.composite
def _cited(draw: Any) -> tuple[Alert, pd.DataFrame]:
    """An alert that cites 1 to 6 synthetic rows, with the rows."""
    specs = draw(st_h.lists(st_h.tuples(_DAYS, _AMOUNTS), min_size=1, max_size=6))
    refs = [f"f.csv:{index}" for index in range(len(specs))]
    rows = _rows(*[(ref, day, str(amount)) for ref, (day, amount) in zip(refs, specs, strict=True)])
    alert = Alert(
        detector="vf.recurring_fee", severity="info", title="t", source_refs=refs, data={}
    )
    return alert, rows


@settings(max_examples=200, deadline=None)
@given(case=_cited())
def test_the_lines_of_any_cited_rows_pass_the_guard_and_are_stable(
    case: tuple[Alert, pd.DataFrame],
) -> None:
    alert, rows = case
    lines = row_lines(rows)

    assert check_figures(lines, alert, rows) == (True, ())
    assert lines == row_lines(rows)
    assert len(lines.splitlines()) == len(rows)


@settings(max_examples=200, deadline=None)
@given(case=_cited(), cents=st_h.integers(min_value=10_000_000, max_value=99_999_999))
def test_a_figure_in_no_row_and_no_alert_is_always_rejected(
    case: tuple[Alert, pd.DataFrame], cents: int
) -> None:
    alert, rows = case
    invented = f"{Decimal(cents) / 100:.2f}"  # 100000.00 or more: no row amount reaches it

    passed, rejected = check_figures(f"{row_lines(rows)}\nPlus {invented} EUR.", alert, rows)

    assert not passed and invented in rejected


# --- Widget (EX2) -----------------------------------------------------------------------------


@pytest.fixture
def downloads(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Wrap st.download_button; AppTest has no typed element for it, so record every call."""
    seen: list[dict[str, Any]] = []
    original = st.download_button

    def spy(*args: Any, **kwargs: Any) -> Any:
        label, data = (args + (None, None))[:2]
        seen.append({"label": label, "data": data, **kwargs})
        return original(*args, **kwargs)

    monkeypatch.setattr(st, "download_button", spy)
    return seen


def _run(mode: str = "ok") -> AppTest:
    at = AppTest.from_file(SCRIPT, default_timeout=TIMEOUT_SECONDS)
    at.session_state["ex_mode"] = mode
    at.run()
    assert not at.exception
    return at


def _alert_id(at: AppTest) -> str:
    return str(at.session_state["ex_alert_id"])


def test_the_expander_is_titled_collapsed_and_holds_the_english_draft() -> None:
    at = _run()
    alert_id = _alert_id(at)

    assert [e.label for e in at.expander] == [EXPANDER_TITLE] == ["Exorcise: prepare the action"]
    radio = at.radio(key=f"zs_ex_lang_{alert_id}")
    assert list(radio.options) == ["English", "Español"] and radio.value == "English"
    area = at.text_area(key=f"zs_ex_text_{alert_id}_en")
    assert area.disabled and "2026-08-09: 8,99 EUR" in area.value
    assert DISCLAIMER["en"] in [c.value for c in at.caption]
    assert DISCLAIMER["en"] == "This is a draft to review, not legal advice."


def test_the_expander_is_drawn_collapsed() -> None:
    calls = [
        node
        for node in ast.walk(ast.parse(WIDGET_SOURCE.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "expander"
    ]

    [call] = calls
    assert {kw.arg: ast.literal_eval(kw.value) for kw in call.keywords} == {"expanded": False}


def test_switching_the_language_changes_the_draft_the_caption_and_the_download(
    downloads: list[dict[str, Any]],
) -> None:
    at = _run()
    alert_id = _alert_id(at)

    at.radio(key=f"zs_ex_lang_{alert_id}").set_value("Español").run()

    assert not at.exception
    assert "cobraron 2 veces" in at.text_area(key=f"zs_ex_text_{alert_id}_es").value
    assert DISCLAIMER["es"] in [c.value for c in at.caption]
    assert DISCLAIMER["en"] not in [c.value for c in at.caption]
    last = downloads[-1]
    assert last["file_name"].endswith(f"-es-{alert_id[:8]}.txt")
    assert "cobraron 2 veces" in last["data"]


def test_the_download_has_the_file_name_the_mime_and_the_text_of_the_draft(
    downloads: list[dict[str, Any]],
) -> None:
    at = _run()
    alert_id = _alert_id(at)

    [call] = downloads
    assert call["file_name"] == f"exorcise-zs-charges-after-cancellation-en-{alert_id[:8]}.txt"
    assert call["mime"] == "text/plain" and call["on_click"] == "ignore"
    assert call["key"] == f"zs_ex_dl_{alert_id}_en"
    assert call["data"] == at.text_area(key=f"zs_ex_text_{alert_id}_en").value


def test_no_template_draws_no_expander_and_no_widget(downloads: list[dict[str, Any]]) -> None:
    at = _run("none")

    assert len(at.expander) == 0 and len(at.radio) == 0 and len(at.text_area) == 0
    assert downloads == []


def test_a_rejected_draft_shows_the_message_and_no_text_and_no_download(
    downloads: list[dict[str, Any]], caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger=LOG):
        at = _run("broken")

    assert [i.value for i in at.info] == [UNAVAILABLE["en"]]
    assert len(at.text_area) == 0 and downloads == []
    assert any("99999.99" in r.getMessage() for r in caplog.records)
    assert UNAVAILABLE["en"].startswith("This draft is not available:")


def test_the_widget_keys_carry_the_prefix_and_never_the_live_guard_marker(
    downloads: list[dict[str, Any]],
) -> None:
    at = _run()
    alert_id = _alert_id(at)

    keys = [at.radio[0].key, at.text_area[0].key, downloads[0]["key"]]
    assert keys == [
        f"zs_ex_lang_{alert_id}",
        f"zs_ex_text_{alert_id}_en",
        f"zs_ex_dl_{alert_id}_en",
    ]
    assert not any("_lg_" in key for key in keys)
