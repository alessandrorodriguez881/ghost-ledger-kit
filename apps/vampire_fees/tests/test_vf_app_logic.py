"""Pure helpers and headless AppTest runs of the vampire-fees page (Task VF14).

The runs that load the demo read the committed files and FAIL LOUDLY until the human has run
`python scripts/generate_samples.py --mode vampire-demo` (human step H1).
"""

import importlib.util
import sys
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

import apps.vampire_fees.detectors  # noqa: F401  (registers the vf.* detectors)
from apps.vampire_fees import app as vf_app
from apps.vampire_fees.settings import (
    RULE_CSV,
    RULE_NORMA43,
    RULE_REFUNDS,
    CoffinView,
    load_config,
    load_vocabulary,
    markdown_safe,
    run_pipeline,
)
from ledger_kit.detectors import _restore_registry, _snapshot_registry, registered_names
from ledger_kit.ingestion.norma43_reader import control_check_messages

ROOT = Path(__file__).resolve().parents[3]
APP_PATH = str(ROOT / "apps" / "vampire_fees" / "app.py")
SCRIPT = ROOT / "scripts" / "generate_samples.py"
CONFIG_PATH = ROOT / "apps" / "vampire_fees" / "config.toml"
CSV_PATH = ROOT / "data" / "samples" / "vampire_demo_statement.csv"
N43_PATH = ROOT / "data" / "samples" / "vampire_demo_statement.n43"
TIMEOUT_SECONDS = 60

VF_DETECTORS = {"vf.recurring_fee", "vf.fee_increase", "vf.overdraft_cost", "vf.fee_summary"}
YEARLY_COSTS = ("78,00 EUR", "36,00 EUR", "30,00 EUR")
REJECTED_BADGE = "⚠️ LLM answer rejected: not found in the cited rows or the alert data: 99999.99"


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Snapshot and restore the registry; the vf detectors must stay in it."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)  # the app must use the template path
    assert VF_DETECTORS <= set(registered_names("vf"))
    snapshot = _snapshot_registry()
    try:
        yield
    finally:
        _restore_registry(snapshot)


def require_demo_files() -> None:
    """Fail loudly, with the command to run, when the committed demo files do not exist."""
    missing = [p.name for p in (CSV_PATH, N43_PATH) if not p.is_file()]
    assert not missing, (
        f"missing {missing}: run `python scripts/generate_samples.py --mode vampire-demo` "
        "(human step H1 of the vampire-fees tasks)"
    )


def _run() -> AppTest:
    """Run the app headless."""
    return AppTest.from_file(APP_PATH, default_timeout=TIMEOUT_SECONDS).run()


def _demo(demo_format: str = "CSV") -> AppTest:
    """Run the app, choose the demo format and click Load demo data."""
    require_demo_files()
    at = _run()
    at.radio(key="vf_demo_format").set_value(demo_format).run()
    at.button(key="vf_load_demo").click().run()
    return at


def _markdown(at: AppTest) -> list[str]:
    """Every markdown value of the page."""
    return [element.value for element in at.markdown]


def _coffins(at: AppTest) -> list[str]:
    """The HTML of every coffin card."""
    return [v for v in _markdown(at) if v.startswith('<div class="vf-coffin">')]


def _alert_titles(at: AppTest) -> list[str]:
    """The HTML of every alert title."""
    return [v for v in _markdown(at) if v.startswith('<div class="vf-alert-title">')]


def _badges(at: AppTest) -> list[str]:
    """The HTML of every guard badge."""
    return [v for v in _markdown(at) if v.startswith('<span class="vf-badge ')]


def _captions(at: AppTest) -> str:
    """All caption text of the page, joined."""
    return " ".join(element.value for element in at.caption)


def _metrics(at: AppTest) -> dict[str, str]:
    """{label: value} of every metric."""
    return {metric.label: metric.value for metric in at.metric}


# --- Pure helpers ---------------------------------------------------------------------------------


def make_view(**overrides: Any) -> CoffinView:
    """A coffin view with plain values."""
    values: dict[str, Any] = {
        "counterparty": "BANCO FICTICIO",
        "description": "Comisión mantenimiento cuenta",
        "interval": "every month",
        "current_amount": "6,50 EUR",
        "yearly_cost": "78,00 EUR",
        "source_refs": ("s.csv:1", "s.csv:2"),
    }
    values.update(overrides)
    return CoffinView(**values)


def test_coffin_html_shows_the_card_text() -> None:
    """The card names the counterparty, the description, the interval and the cost."""
    html_text = vf_app.coffin_html(make_view())
    assert html_text.startswith('<div class="vf-coffin">')
    for part in (
        "BANCO FICTICIO",
        "Comisión mantenimiento cuenta",
        "every month",
        "Now 6,50 EUR",
        "Drains 78,00 EUR a year",
    ):
        assert part in html_text


def test_coffin_html_escapes_every_inserted_text() -> None:
    """REQ-VF-41: a <script> in a description or a counterparty is escaped."""
    html_text = vf_app.coffin_html(
        make_view(
            description="x<script>alert(1)</script>",
            counterparty='A&B "<b>"',
            interval="<i>",
            current_amount="<u>",
            yearly_cost="<s>",
        )
    )
    assert "<script>" not in html_text
    assert "&lt;script&gt;" in html_text
    for raw in ("<b>", "<i>", "<u>", "<s>"):
        assert raw not in html_text
    assert "A&amp;B" in html_text


def test_css_holds_the_vampire_accent_and_the_coffin_polygon() -> None:
    """REQ-VF-41 and design 8.3: red accents, blood-dark card and a clip-path polygon."""
    css = vf_app.VAMPIRE_CSS
    for part in ("#9b1c31", "#c2334d", "#2a0f16", "clip-path: polygon", ".vf-coffin"):
        assert part in css
    for kind in ("llm", "template", "unavailable", "rejected"):
        assert f".vf-badge-{kind}" in css


def test_session_keys_start_with_vf() -> None:
    """REQ-VF-47: every key constant of the page starts with vf_."""
    keys = [
        vf_app.LOAD_DEMO_KEY,
        vf_app.HALLUCINATE_KEY,
        vf_app.EXPLANATIONS_KEY,
        vf_app.DEMO_FORMAT_KEY,
        vf_app.UPLOAD_STATEMENT_KEY,
        vf_app.KEPT_KEY,
        vf_app.INGESTION_CACHE_KEY,
        *vf_app.WIDGET_KEYS,
    ]
    assert all(key.startswith("vf_") for key in keys)
    assert set(vf_app.WIDGET_KEYS) == {vf_app.HALLUCINATE_KEY, vf_app.DEMO_FORMAT_KEY}


def test_coffins_per_row_is_three() -> None:
    """REQ-VF-41: the cards are laid out three per row."""
    assert vf_app.COFFINS_PER_ROW == 3


# --- Empty state ----------------------------------------------------------------------------------


def test_empty_state_shows_the_title_the_hint_and_no_coffin() -> None:
    """REQ-VF-48: with no statement the page explains how to load one."""
    at = _run()
    assert not at.exception
    assert at.title[0].value == "Vampire Fees"
    assert any("Load demo data" in info.value for info in at.info)
    assert at.button(key="vf_load_demo").label == "Load demo data"
    assert at.toggle(key="vf_hallucinate").value is False
    assert at.radio(key="vf_demo_format").value == "CSV"
    assert _coffins(at) == [] and _alert_titles(at) == []


def test_the_page_injects_its_own_css_block() -> None:
    """The vampire CSS is one <style> block of the page."""
    css = [v for v in _markdown(_run()) if v.lstrip().startswith("<style>")]
    assert len(css) == 1 and "#9b1c31" in css[0]


def test_the_sidebar_lists_the_vocabulary_read_only() -> None:
    """REQ-VF-44: the phrases in use are shown in a read-only expander."""
    at = _run()
    sidebar_text = " ".join(element.value for element in at.sidebar.markdown)
    assert "comision" in sidebar_text and "notaria" in sidebar_text


# --- CSV demo -------------------------------------------------------------------------------------


def test_csv_demo_shows_three_coffins_and_six_alerts() -> None:
    """Design 7.3: three coffins, six alerts grouped critical, warning, info."""
    at = _demo("CSV")
    assert not at.exception
    coffins = _coffins(at)
    assert len(coffins) == 3
    for cost in YEARLY_COSTS:
        assert sum(f"Drains {cost} a year" in coffin for coffin in coffins) == 1
    assert len(_alert_titles(at)) == 6
    severities = [
        part.split("severity: ")[1]
        for part in (e.value for e in at.caption)
        if part.startswith("Detector: ")
    ]
    assert severities == ["critical", "warning", "warning", "warning", "info", "info"]
    assert not at.sidebar.error and not at.error


def test_csv_demo_caption_metrics_and_rule_sentence() -> None:
    """The caption counts the rows, the metrics come from the summary alert."""
    at = _demo("CSV")
    captions = _captions(at)
    assert "vampire_demo_statement.csv (CSV)" in captions
    assert "227 rows analysed (202 debit rows), 0 quarantined, 0 skipped for currency" in captions
    assert RULE_CSV in captions and RULE_REFUNDS in captions
    assert RULE_NORMA43 not in captions
    metrics = _metrics(at)
    assert metrics["Fees found"] == "45"
    assert metrics["Total fees"] == "379,25 EUR"
    assert metrics["Yearly equivalent"] == "207,54 EUR"


def test_demo_alerts_show_source_refs_and_european_amounts() -> None:
    """Every alert lists its source refs; the explanations are European."""
    at = _demo("CSV")
    markdown = _markdown(at)
    refs_lines = [v for v in markdown if v.startswith("**Source refs:**")]
    assert len(refs_lines) == len(_alert_titles(at)) == 6
    assert any("vampire_demo_statement.csv:" in v for v in markdown)
    assert any("379,25 EUR" in v for v in markdown)  # the summary explanation
    assert all("vf-badge-template" in badge for badge in _badges(at))
    assert len(_badges(at)) == 6


# --- Norma 43 demo --------------------------------------------------------------------------------


def test_norma43_demo_gives_the_same_coffins_and_alerts() -> None:
    """The Norma 43 demo shows the same figures and its own rule sentence."""
    at = _demo("Norma 43")
    assert not at.exception
    coffins = _coffins(at)
    assert len(coffins) == 3
    for cost in YEARLY_COSTS:
        assert sum(f"Drains {cost} a year" in coffin for coffin in coffins) == 1
    assert len(_alert_titles(at)) == 6
    captions = _captions(at)
    assert "vampire_demo_statement.n43 (Norma 43)" in captions
    assert RULE_NORMA43 in captions and RULE_REFUNDS in captions
    assert RULE_CSV not in captions
    assert _metrics(at)["Total fees"] == "379,25 EUR"


# --- Hallucination switch -------------------------------------------------------------------------


def test_hallucination_toggle_rejects_the_invented_number() -> None:
    """The stub invents 99999.99: every card shows the rejected badge and the template."""
    at = _demo("CSV")
    at.toggle(key="vf_hallucinate").set_value(True).run()
    assert not at.exception
    badges = _badges(at)
    assert len(badges) == len(_alert_titles(at)) == 6
    for badge in badges:
        assert "vf-badge-rejected" in badge and REJECTED_BADGE in badge
    explanations = [v for v in _markdown(at) if not v.startswith(("<span", "<div", "<style"))]
    assert not any("99999.99" in value for value in explanations)
    assert any("379,25 EUR" in value for value in explanations)  # the filled template

    at.toggle(key="vf_hallucinate").set_value(False).run()
    assert not at.exception
    assert all("vf-badge-template" in badge for badge in _badges(at))


# --- Quarantine and control checks ----------------------------------------------------------------


def _load_generator() -> Any:
    """Load scripts/generate_samples.py by path (scripts/ is not a package)."""
    spec = importlib.util.spec_from_file_location("generate_samples_vf_app", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["generate_samples_vf_app"] = module
    spec.loader.exec_module(module)
    return module


def _control_failed_norma43() -> bytes:
    """A small Norma 43 file whose closing record claims 99 debits (a failed control check)."""
    gen = _load_generator()
    rows = [
        gen.BankRow(date(2026, 1, 2), "100.00", "Luminar Estudio S.L.", "Payroll", ""),
        gen.BankRow(date(2026, 1, 5), "-5.00", "BANCO FICTICIO", "Comisión mantenimiento", ""),
    ]
    lines = gen.render_norma43(rows).decode("iso-8859-1").split("\r\n")
    closing = next(i for i, line in enumerate(lines) if line.startswith("33"))
    lines[closing] = lines[closing][:20] + "00099" + lines[closing][25:]
    return "\r\n".join(lines).encode("iso-8859-1")


def test_a_failed_control_check_is_shown_as_an_error() -> None:
    """REQ-VF-46: the message of control_check_messages is shown, in the quarantine section."""
    data = _control_failed_norma43()
    vocabulary = load_vocabulary(load_config(CONFIG_PATH))
    messages = control_check_messages(
        run_pipeline("bad.n43", data, vocabulary=vocabulary).quarantine
    )
    assert messages, "the corrupted closing record should fail a control check"

    at = AppTest.from_file(APP_PATH, default_timeout=TIMEOUT_SECONDS)
    at.session_state["vf_source"] = ("upload", data, "bad.n43")
    at.run()

    assert not at.exception
    shown = [error.value for error in at.error]
    for message in messages:
        assert markdown_safe(message) in shown
    assert any("Quarantined rows" in expander.label for expander in at.expander)


def test_unsupported_content_is_quarantined_and_the_page_survives() -> None:
    """Content that is neither CSV nor Norma 43 shows the quarantine and no coffin."""
    at = AppTest.from_file(APP_PATH, default_timeout=TIMEOUT_SECONDS)
    at.session_state["vf_source"] = ("upload", b"<root/>", "x.xml")
    at.run()
    assert not at.exception
    assert _coffins(at) == []
    assert any("Quarantined rows" in expander.label for expander in at.expander)


# --- Session state --------------------------------------------------------------------------------


def test_every_session_state_key_starts_with_vf() -> None:
    """REQ-VF-47: the page uses no key outside the vf_ prefix."""
    at = _run()
    filtered = getattr(at.session_state, "filtered_state", None)
    if filtered is None:
        pytest.skip("this Streamlit version does not expose filtered_state")
    assert [key for key in filtered if not str(key).startswith("vf_")] == []
    assert "vf_hallucinate" in filtered and "vf_demo_format" in filtered
