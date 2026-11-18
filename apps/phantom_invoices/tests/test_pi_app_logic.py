"""Tests of the phantom-invoices Streamlit app and its view-model helpers (Task P22).

The first half needs no Streamlit runtime (pure helpers and ``ast`` scans of app.py). The second
half drives the app headless with ``AppTest``. Everything uses the committed synthetic demo files
or fictional builders; nothing reads the system clock.
"""

import ast
import re
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

import apps.phantom_invoices.detectors  # noqa: F401  (registers the pi.* detectors)
from apps.phantom_invoices.detectors import LABELS
from apps.phantom_invoices.detectors.iban_change import (
    VERIFY_BY_PHONE_MESSAGE,
    detect_iban_changes,
)
from apps.phantom_invoices.detectors.utils import Reconciliation, reconcile
from apps.phantom_invoices.explain_support import (
    BADGE_REJECTED,
    BADGE_TEMPLATE,
    badge_kind,
    explanation_key,
)
from apps.phantom_invoices.settings import (
    DEFAULT_DUE_DATE_CAPTION,
    LAST4_CAPTION,
    LEDGER_COLUMNS,
    NO_FLASHLIGHT,
    STATUS_ICONS,
    UI_DEFAULT_AS_OF,
    DemoInputs,
    Source,
    alert_captions,
    apply_demo,
    as_of_note,
    cited_master_view,
    cited_payments_view,
    flashlight_options,
    group_alerts,
    input_notice,
    ledger_view,
    lit_refs_for,
    markdown_safe,
    ordered_alerts,
    pipeline_key,
    quarantine_view,
    reset_selected,
    severity_counts,
    status_icon,
    verification_message,
)
from apps.phantom_invoices.tests.pi_builders import (
    make_invoices,
    make_payments,
    make_suppliers,
    master_iban,
    supplier_record,
)
from ledger_kit.detectors import _restore_registry, _snapshot_registry, registered_names
from ledger_kit.explainer import Explanation
from ledger_kit.models import Alert
from ledger_kit.utils.anonymise import mask_iban
from ledger_kit.utils.money import format_amount

APP_PATH = Path(__file__).resolve().parents[1] / "app.py"
TIMEOUT_SECONDS = 60
PI_DETECTORS = {
    "pi.duplicate_invoice",
    "pi.iban_change",
    "pi.reconciliation",
    "pi.vat_error",
}
AMOUNT_COLUMNS = ("base_amount", "vat_amount", "surcharge_amount", "withholding_amount", "total")
DEMO_CRITICAL, DEMO_WARNING = 3, 6
DEMO_LEDGER_ROWS = 68  # 70 invoice rows minus the two multi-rate rows in quarantine
HTML_PREFIXES = ("<span", "<div", "<style")
IBAN_VARIANTS = ("invoice_iban_differs_from_master", "payment_to_non_master_iban")
NO_MESSAGE_VARIANTS = ("iban_invalid", "same_number", "vat_amount_mismatch", "invoice_overdue")


def _app_tree() -> ast.Module:
    """Parse app.py."""
    return ast.parse(APP_PATH.read_text(encoding="utf-8"))


def _alert(severity: str, index: int = 0, **data: object) -> Alert:
    """Build a minimal alert; `index` keeps the ids of alerts of one severity apart."""
    return Alert(
        detector="pi.vat_error",
        severity=severity,
        title=f"{severity} {index}",
        source_refs=[f"inv.csv:{index}"],
        data={"variant": "vat_amount_mismatch", "index": index, **data},
    )


def _with_data(alert: Alert, data: dict) -> Alert:
    """Return a copy of `alert` whose data payload is `data`."""
    return alert.model_copy(update={"data": data})


def _import_root(node: ast.stmt) -> set[str]:
    """Return the top-level package names a module-level import statement imports."""
    if isinstance(node, ast.ImportFrom):
        return {(node.module or "").split(".")[0]}
    if isinstance(node, ast.Import):
        return {alias.name.split(".")[0] for alias in node.names}
    return set()


# --- app.py structure ---------------------------------------------------------------------------


def test_app_py_first_lines_bootstrap_sys_path() -> None:
    """The path bootstrap of the zombie app precedes the first ledger_kit or apps import."""
    tree = _app_tree()
    bootstrap = [
        index
        for index, node in enumerate(tree.body)
        if isinstance(node, ast.If) and "sys.path.insert(0, str(_ROOT))" in ast.unparse(node)
    ]
    local_imports = [
        index for index, node in enumerate(tree.body) if _import_root(node) & {"apps", "ledger_kit"}
    ]

    assert len(bootstrap) == 1
    assert local_imports
    assert bootstrap[0] < min(local_imports)
    assert "_ROOT = Path(__file__).resolve().parents[2]" in ast.unparse(tree)


def test_app_uses_on_click_for_load_demo() -> None:
    """Load demo data is attached with on_click; no widget key is written under an `if` button."""
    tree = _app_tree()
    buttons = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and ast.unparse(node.func) == "st.sidebar.button"
    ]
    load = [
        call
        for call in buttons
        if call.args
        and isinstance(call.args[0], ast.Constant)
        and call.args[0].value == "Load demo data"
    ]

    assert len(load) == 1
    assert {kw.arg: ast.unparse(kw.value) for kw in load[0].keywords}["on_click"] == "load_demo"
    assert any(isinstance(n, ast.FunctionDef) and n.name == "load_demo" for n in tree.body)
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        tests_a_button = any(
            isinstance(call, ast.Call) and ast.unparse(call.func).endswith("button")
            for call in ast.walk(node.test)
        )
        if not tests_a_button:
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Assign):
                for target in inner.targets:
                    assert "session_state" not in ast.unparse(target)


def test_ui_default_as_of_is_only_a_widget_seed() -> None:
    """UI_DEFAULT_AS_OF only seeds the date widget; a detector gets an as_of only when ticked."""
    tree = _app_tree()
    uses = [n for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id == "UI_DEFAULT_AS_OF"]
    seeding = [
        call
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and ast.unparse(call.func) == "st.session_state.setdefault"
        and any(isinstance(arg, ast.Name) and arg.id == "UI_DEFAULT_AS_OF" for arg in call.args)
    ]

    assert UI_DEFAULT_AS_OF == date(2026, 1, 1)
    assert len(uses) == 1 and len(seeding) == 1
    assert isinstance(seeding[0].args[0], ast.Constant)
    assert seeding[0].args[0].value == "as_of_date"
    assert "as_of = st.session_state['as_of_date'] if fixed else None" in ast.unparse(tree)


def test_explanation_cache_key_is_alert_id_and_client_mode() -> None:
    """Explanations are cached by (alert.id, client mode) and the app uses that key."""
    alert = _alert("critical")

    assert explanation_key(alert, False) == (alert.id, "real")
    assert explanation_key(alert, True) == (alert.id, "hallucinate")
    assert explanation_key(alert, True) != explanation_key(alert, False)
    app_source = ast.unparse(_app_tree())
    assert "key = explanation_key(alert, hallucinate)" in app_source
    assert "cache[key]" in app_source


# --- pure view-model helpers --------------------------------------------------------------------


def test_all_amounts_in_ledger_view_use_format_amount_and_iban_masked_and_no_tax_id_column():
    """Every amount is a European string, the IBAN is masked and no tax id is shown."""
    iban = master_iban(1)
    invoices = make_invoices(
        [
            {
                "base_amount": Decimal("1234.56"),
                "surcharge_amount": Decimal("5.20"),
                "withholding_amount": Decimal("10.00"),
                "iban": iban,
            }
        ]
    )
    rec = reconcile(invoices, make_suppliers([{}]), make_payments([]), None)

    view = ledger_view(invoices, rec)

    assert list(view.columns) == list(LEDGER_COLUMNS)
    assert "supplier_tax_id" not in view.columns and "tax_id" not in view.columns
    for column in AMOUNT_COLUMNS:
        assert view.at[0, column] == format_amount(invoices.at[0, column], "EUR")
    assert view.at[0, "base_amount"] == "1.234,56 EUR"
    assert view.at[0, "iban"] == mask_iban(iban) == "****" + iban[-4:]
    shown = " ".join(str(value) for value in view.iloc[0])
    assert iban not in shown and "".join(iban.split()) not in shown
    assert supplier_record(1)["tax_id"] not in shown
    assert view.at[0, "vat_rate"] == "21 %"


def test_ledger_view_of_empty_and_unusable_rows() -> None:
    """An empty frame gives a header-only view; missing cells give empty strings."""
    empty = Reconciliation({}, {}, [], {})
    assert ledger_view(make_invoices([]), empty).empty

    missing = {"base_amount": None, "vat_rate": None, "vat_amount": None, "total": None}
    invoices = make_invoices([{**missing, "due_date": None}])
    row = ledger_view(invoices, empty).iloc[0]

    assert row["status"] == ""
    assert (row["base_amount"], row["vat_rate"], row["total"], row["due_date"]) == ("", "", "", "")


def test_ledger_view_marks_an_assumed_due_date() -> None:
    """A defaulted due date is shown with a mark; the caption explains it."""
    invoices = make_invoices([{"due_date_is_default": True}, {"due_date_is_default": False}])

    view = ledger_view(invoices, Reconciliation({}, {}, [], {}))

    assert view.at[0, "due_date"] == "2026-03-31 (assumed)"
    assert view.at[1, "due_date"] == "2026-03-31"


def test_status_column_icons() -> None:
    """matched, open_not_due and overdue get their icon; a row that is not usable stays blank."""
    invoices = make_invoices([{}, {}, {}, {}])
    buckets = {"inv.csv:0": "matched", "inv.csv:1": "open_not_due", "inv.csv:2": "overdue"}

    view = ledger_view(invoices, Reconciliation(buckets, {}, [], {}))

    assert list(view["status"]) == [
        STATUS_ICONS["matched"],
        STATUS_ICONS["open_not_due"],
        STATUS_ICONS["overdue"],
        "",
    ]
    assert STATUS_ICONS["matched"] == "✅" and STATUS_ICONS["overdue"] == "💀"
    assert STATUS_ICONS["open_not_due"].startswith("\U0001f56f")  # candle
    assert status_icon(None) == status_icon("unknown") == ""


def test_alerts_grouped_critical_then_warning() -> None:
    """Alerts are grouped and ordered critical first, then warning, input order kept."""
    alerts = [
        _alert("warning", 0),
        _alert("critical", 1),
        _alert("warning", 2),
        _alert("critical", 3),
    ]

    groups = group_alerts(alerts)

    assert list(groups) == ["critical", "warning", "info"]
    assert [a.title for a in groups["critical"]] == ["critical 1", "critical 3"]
    assert [a.title for a in ordered_alerts(alerts)] == [
        "critical 1",
        "critical 3",
        "warning 0",
        "warning 2",
    ]
    assert severity_counts(alerts) == {"critical": 2, "warning": 2, "info": 0}
    assert group_alerts([])["warning"] == []


def test_captions_for_last4_identical_and_default_due_date() -> None:
    """The two captions of REQ-PI-49 appear exactly when their flag is true."""
    last4 = "The last four characters match; the difference is elsewhere in the IBAN."
    due = "Due date assumed: issue date plus the default payment term."
    assert LAST4_CAPTION == last4
    assert DEFAULT_DUE_DATE_CAPTION == due

    assert alert_captions(_alert("critical", last4_identical=True)) == [last4]
    assert alert_captions(_alert("critical", last4_identical=False)) == []
    assert alert_captions(_alert("warning", due_date_is_default=True)) == [due]
    both = _alert("warning", last4_identical=True, due_date_is_default=True)
    assert alert_captions(both) == [last4, due]
    assert alert_captions(_alert("warning")) == []


def test_verification_message_shown_only_for_the_two_critical_iban_variants(
    ledger_with_iban_change,
) -> None:
    """The verify-by-phone message is returned verbatim for the two critical variants only."""
    scenario = ledger_with_iban_change
    [real] = detect_iban_changes(scenario.invoices, scenario.context())
    assert real.data["variant"] == IBAN_VARIANTS[0]
    assert verification_message(real) == VERIFY_BY_PHONE_MESSAGE

    for variant in IBAN_VARIANTS:
        data = {"variant": variant, "verification_message": "Call them."}
        assert verification_message(_with_data(_alert("critical"), data)) == "Call them."
    for variant in NO_MESSAGE_VARIANTS:
        data = {"variant": variant, "verification_message": "Call them."}
        assert verification_message(_with_data(_alert("warning"), data)) is None
    without = {"variant": IBAN_VARIANTS[1]}
    assert verification_message(_with_data(_alert("critical"), without)) is None


def test_notice_states_which_checks_need_which_file() -> None:
    """REQ-PI-04: the notice names each file, its check, and what is missing."""
    both_missing = input_notice(False, False)

    assert "Invoices" in both_missing and "duplicate" in both_missing and "VAT" in both_missing
    assert "Supplier master" in both_missing and "Poltergeist IBAN" in both_missing
    assert "only malformed IBANs are reported" in both_missing
    assert "Bank payments" in both_missing and "reconciliation" in both_missing
    assert "no invoice can be matched" in both_missing
    assert "Not loaded: supplier master and bank payments." in both_missing
    assert "Not loaded: bank payments." in input_notice(True, False)
    assert "Not loaded: supplier master." in input_notice(False, True)
    assert "Not loaded" not in input_notice(True, True)


def test_selected_alert_reset_when_not_in_options() -> None:
    """A selection that is no longer an option falls back to NO_FLASHLIGHT."""
    alerts = [_alert("critical", 0), _alert("warning", 1)]
    options = flashlight_options(alerts)

    assert options == [NO_FLASHLIGHT, alerts[0].id, alerts[1].id]
    assert reset_selected(alerts[1].id, options) == alerts[1].id
    assert reset_selected("deadbeef", options) == NO_FLASHLIGHT
    assert reset_selected(None, options) == NO_FLASHLIGHT
    assert reset_selected(NO_FLASHLIGHT, options) == NO_FLASHLIGHT
    assert flashlight_options([alerts[0], alerts[0]]) == [NO_FLASHLIGHT, alerts[0].id]


def test_flashlight_lights_the_refs_of_the_selected_alert_only() -> None:
    """lit_refs_for returns the source_refs of the selected alert; no selection lights nothing."""
    alerts = [_alert("critical", 0), _alert("warning", 1)]

    assert lit_refs_for(alerts[1].id, alerts) == ("inv.csv:1",)
    assert lit_refs_for(NO_FLASHLIGHT, alerts) == ()
    assert lit_refs_for("deadbeef", alerts) == ()


def test_cited_views_hide_tax_ids_and_mask_ibans() -> None:
    """Cited master and payment rows show European amounts and masked IBANs, no tax id."""
    suppliers = make_suppliers([{}, {}])
    payments = make_payments([{"iban": master_iban(1)}, {}])

    master = cited_master_view(suppliers, ["sup.csv:1", "inv.csv:0"])
    paid = cited_payments_view(payments, ["pay.csv:0"])

    assert list(master["source_ref"]) == ["sup.csv:1"]
    assert "tax_id" not in master.columns
    assert list(master["iban"]) == [mask_iban(master_iban(2))]
    assert list(paid["source_ref"]) == ["pay.csv:0"]
    assert list(paid["amount"]) == ["121,00 EUR"]
    assert list(paid["iban"]) == [mask_iban(master_iban(1))]
    assert cited_master_view(None, ["sup.csv:0"]).empty
    assert cited_payments_view(make_payments([]), ["pay.csv:0"]).empty


def test_pipeline_key_depends_on_names_bytes_and_as_of() -> None:
    """The cache key changes with any input byte, file name or as_of value."""
    a, b = Source("a.csv", b"1"), Source("b.csv", b"2")
    base = pipeline_key(a, b, None, None)

    assert base == pipeline_key(Source("a.csv", b"1"), Source("b.csv", b"2"), None, None)
    assert base != pipeline_key(Source("a.csv", b"1x"), b, None, None)
    assert base != pipeline_key(Source("c.csv", b"1"), b, None, None)
    assert base != pipeline_key(a, b, None, date(2026, 1, 1))
    assert base != pipeline_key(a, b, b, None)
    assert pipeline_key(None, None, None, None) != pipeline_key(a, None, None, None)
    assert pipeline_key(a, b, None, None) == pipeline_key((a,), b, None, None)  # one file


def test_pipeline_key_ignores_selection_order_and_covers_every_invoice_file() -> None:
    """REQ-RF-21: the key hashes the file count, then each name and content in name order."""
    a, b = Source("01-a.xml", b"1"), Source("02-b.xml", b"2")
    key = pipeline_key((a, b), None, None, None)

    assert key == pipeline_key((b, a), None, None, None)
    assert key != pipeline_key((a,), None, None, None)  # a file less
    assert key != pipeline_key((a, Source("02-b.xml", b"2x")), None, None, None)
    assert key != pipeline_key((a, Source("03-b.xml", b"2")), None, None, None)
    assert key != pipeline_key((a, b, b), None, None, None)  # a repeated name counts


def test_apply_demo_prefills_widget_keys_and_sources() -> None:
    """apply_demo writes the sources and resets the widget keys; as_of only when configured."""
    sources = [Source(name, name.encode()) for name in ("i.csv", "s.csv", "p.csv")]
    invoices = (sources[0],)
    state: dict[str, Any] = {
        "pi_hallucinate": True,
        "selected_alert": "x",
        "as_of_date": date(2020, 5, 5),
    }

    apply_demo(state, DemoInputs(invoices, sources[1], sources[2]))

    expected = {"invoices": invoices, "suppliers": sources[1], "payments": sources[2]}
    assert state["sources"] == expected
    assert state["use_as_of"] is False and state["pi_hallucinate"] is False
    assert state["selected_alert"] == NO_FLASHLIGHT
    assert state["as_of_date"] == date(2020, 5, 5)  # untouched without a demo as_of

    apply_demo(state, DemoInputs(invoices, sources[1], sources[2], as_of=date(2026, 10, 30)))

    assert state["use_as_of"] is True and state["as_of_date"] == date(2026, 10, 30)


def test_as_of_note_and_markdown_safe_and_quarantine_view() -> None:
    """The as-of line, the markdown escaping and the quarantine table."""
    assert "2026-10-30" in as_of_note(date(2026, 10, 30), False)
    assert "defaults to the latest date in the data" in as_of_note(date(2026, 10, 30), False)
    assert "fixed in the sidebar" in as_of_note(date(2026, 1, 1), True)
    assert "No as-of date" in as_of_note(None, False)
    assert markdown_safe("****1332 a_b `c` $5") == "\\*\\*\\*\\*1332 a\\_b \\`c\\` \\$5"
    assert markdown_safe("1.210,00 EUR") == "1.210,00 EUR"

    record = {
        "source_file": "i.csv",
        "source_row": 3,
        "source_line": 5,
        "reason": "r",
        "raw": {"a": "1"},
    }
    table = quarantine_view([record])
    assert list(table.columns) == ["file", "line", "reason", "raw"]
    assert table.iloc[0].tolist() == ["i.csv", "5", "r", "{'a': '1'}"]
    # a record about the whole file or an XML invoice has no line: the cell is empty
    for lineless in ({**record, "source_line": None}, {"source_file": "x.xml", "reason": "r"}):
        assert quarantine_view([lineless]).iloc[0]["line"] == ""
    assert quarantine_view([]).empty


def test_badge_kind_matches_the_badge_semantics() -> None:
    """The CSS kind follows the three badge cases plus the key-present-with-error case."""
    llm = Explanation("t", "llm", ())
    rejected = Explanation("t", "fallback", ("99999.99",))
    fallback = Explanation("t", "fallback", ())

    assert badge_kind(llm, False) == "llm"
    assert badge_kind(rejected, True) == "rejected"
    assert badge_kind(fallback, False) == "template"
    assert badge_kind(fallback, True) == "unavailable"


# --- AppTest: the app headless ------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Snapshot and restore the global detector registry; the pi detectors must stay in it."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)  # the app must use the template path
    assert PI_DETECTORS <= set(registered_names("pi"))
    snapshot = _snapshot_registry()
    try:
        yield
    finally:
        _restore_registry(snapshot)


def _run() -> AppTest:
    """Run the app headless."""
    return AppTest.from_file(str(APP_PATH), default_timeout=TIMEOUT_SECONDS).run()


def _demo() -> AppTest:
    """Run the app and click Load demo data."""
    at = _run()
    at.button(key="pi_load_demo").click().run()
    return at


def _markdown(at: AppTest) -> list[str]:
    """Every markdown value of the page."""
    return [element.value for element in at.markdown]


def _badges(at: AppTest) -> list[str]:
    """The HTML of every guard badge."""
    return [v for v in _markdown(at) if v.startswith('<span class="pi-badge ')]


def _explanation_texts(at: AppTest) -> list[str]:
    """The markdown values that are explanation text (no badge, table or style HTML)."""
    return [v for v in _markdown(at) if not v.startswith(HTML_PREFIXES)]


def _ledger_html(at: AppTest) -> str:
    """The HTML of the haunted ledger (the table with the invoice_number column)."""
    tables = [
        v
        for v in _markdown(at)
        if v.startswith('<div class="ledger-wrap">') and "<th>invoice_number</th>" in v
    ]
    assert len(tables) == 1
    return tables[0]


def _pipeline(at: AppTest) -> Any:
    """The one cached Pipeline of the run."""
    [pipeline] = at.session_state["pipeline_cache"].values()
    return pipeline


def _alerts(at: AppTest) -> list[Alert]:
    """Every alert of the cached pipeline."""
    return [alert for result in _pipeline(at).results for alert in result.alerts]


def _modes(at: AppTest) -> set[str]:
    """The client modes present in the explanation cache."""
    return {mode for _, mode in at.session_state["pi_explanations"]}


def test_app_starts_without_exception() -> None:
    """With no data the page shows the title, the hint and the demo button, and no alert."""
    at = _run()

    assert not at.exception
    assert at.title[0].value == "Phantom Invoices"
    assert any("Load demo data" in info.value for info in at.info)
    assert at.sidebar.button[0].label == "Load demo data"
    assert at.toggle(key="pi_hallucinate").value is False
    assert at.checkbox(key="use_as_of").value is False
    assert len(at.metric) == 0 and _badges(at) == []


def test_app_has_the_haunted_theme() -> None:
    """The candle-lit theme is injected once as CSS, with no external resource."""
    css = [v for v in _markdown(_run()) if v.lstrip().startswith("<style>")]

    assert len(css) == 1
    assert "#12101a" in css[0] and "#7cffb2" in css[0] and "opacity: 0.25" in css[0]
    assert "http" not in css[0] and "@import" not in css[0]


def test_load_demo_click_shows_all_four_detector_labels_without_widget_error() -> None:
    """Load demo data pre-fills the keys through on_click and shows the 9 alerts of 4 detectors."""
    at = _demo()

    assert not at.exception  # no StreamlitWidgetAlreadyInstantiatedError
    assert not at.sidebar.error
    assert {m.label.split()[-1]: m.value for m in at.metric} == {
        "critical": str(DEMO_CRITICAL),
        "warning": str(DEMO_WARNING),
    }
    captions = " ".join(element.value for element in at.caption)
    for name, label in LABELS.items():
        assert f"{label} · `{name}`" in captions
    assert len(_alerts(at)) == DEMO_CRITICAL + DEMO_WARNING
    assert len(_badges(at)) == len(_alerts(at))
    assert len(_pipeline(at).quarantine) == 2
    assert at.session_state["selected_alert"] == NO_FLASHLIGHT
    assert at.session_state["use_as_of"] is False
    assert "2026-10-30" in captions and "defaults to the latest date in the data" in captions


def test_alert_cards_show_refs_badge_and_the_verbatim_verification_message() -> None:
    """Every card has refs and a badge; the two critical IBAN alerts show the phone message."""
    at = _demo()

    refs_lines = [v for v in _markdown(at) if v.startswith("**Source refs:**")]
    assert len(refs_lines) == len(_alerts(at))
    assert all(f'pi-badge-template">{BADGE_TEMPLATE}</span>' in b for b in _badges(at))
    phone = [w.value for w in at.warning if w.value == VERIFY_BY_PHONE_MESSAGE]
    iban_alerts = [a for a in _alerts(at) if verification_message(a) is not None]
    assert len(iban_alerts) == 2 and len(phone) == 2
    # REQ-SC-08: the message is shown once per card, in the phone box and nowhere else.
    shown = [*_markdown(at), *(w.value for w in at.warning), *(c.value for c in at.caption)]
    assert sum(VERIFY_BY_PHONE_MESSAGE in value for value in shown) == 2
    assert not any("by phone" in value for value in _markdown(at))
    text = " ".join(_explanation_texts(at))
    assert "12,10 EUR" in text and "21,00 EUR" in text  # the VAT alert, European amounts
    # REQ-SC-07: invoices issued on one date read "issued on <date>", never "between D and D".
    assert re.search(r"issued between (\S+) and \1\b", text) is None
    assert "issued on 2026-10-06" in text


def test_hallucination_toggle_shows_warning_badge_with_99999_99() -> None:
    """The stub LLM invents 99999.99: every explanation falls back and shows the warning badge."""
    at = _demo()
    assert _modes(at) == {"real"}

    at.toggle(key="pi_hallucinate").set_value(True).run()

    assert not at.exception
    badges = _badges(at)
    expected = BADGE_REJECTED.format(numbers="99999.99")
    assert len(badges) == DEMO_CRITICAL + DEMO_WARNING
    for badge in badges:
        assert "pi-badge-rejected" in badge and expected in badge
    assert not any("99999.99" in value for value in _explanation_texts(at))
    assert _modes(at) == {"real", "hallucinate"}

    at.toggle(key="pi_hallucinate").set_value(False).run()

    assert not at.exception
    assert all("pi-badge-template" in badge for badge in _badges(at))


def test_selecting_an_alert_lights_only_its_source_refs() -> None:
    """The flashlight lights the cited invoice rows, dims every other row and shows cited rows."""
    at = _demo()
    before = _ledger_html(at)
    assert 'class="ledger"' in before and "has-lit" not in before and 'class="dim"' not in before
    assert before.count('<tr class="">') == DEMO_LEDGER_ROWS

    duplicate = next(a for a in _alerts(at) if a.data["variant"] == "same_number")
    at.radio(key="selected_alert").set_value(duplicate.id).run()

    assert not at.exception
    after = _ledger_html(at)
    lit = re.findall(r'<tr class="lit"><td>([^<]*)</td>', after)
    assert 'class="ledger has-lit"' in after
    assert set(lit) == set(duplicate.source_refs) and len(lit) == 2
    assert after.count('<tr class="dim">') == DEMO_LEDGER_ROWS - 2

    poltergeist = next(a for a in _alerts(at) if a.data["variant"] == IBAN_VARIANTS[0])
    at.radio(key="selected_alert").set_value(poltergeist.id).run()

    assert not at.exception
    lit = re.findall(r'<tr class="lit"><td>([^<]*)</td>', _ledger_html(at))
    invoice_ref = next(r for r in poltergeist.source_refs if r.startswith("invoices.csv"))
    supplier_ref = next(r for r in poltergeist.source_refs if r.startswith("suppliers.csv"))
    assert lit == [invoice_ref]
    cited = [v for v in _markdown(at) if f"<td>{supplier_ref}</td>" in v]
    assert len(cited) == 1 and '<tr class="lit">' in cited[0]
    assert "****" in cited[0]  # the master IBAN is masked


def test_as_of_defaults_to_the_data_and_is_fixed_only_when_ticked() -> None:
    """DN-11: UI_DEFAULT_AS_OF reaches the pipeline only after the box is ticked."""
    at = _demo()
    assert _pipeline(at).as_of_used == date(2026, 10, 30)

    at.checkbox(key="use_as_of").check().run()

    assert not at.exception
    used = {p.as_of_used for p in at.session_state["pipeline_cache"].values()}
    assert used == {date(2026, 10, 30), UI_DEFAULT_AS_OF}
    captions = " ".join(c.value for c in at.caption)
    assert "As-of date in use: 2026-01-01 (fixed in the sidebar)." in captions


def test_pi_detectors_stay_registered_after_the_app_ran() -> None:
    """Running the app neither drops nor duplicates the pi detectors in the registry."""
    _demo()

    names = registered_names("pi")
    assert set(names) == PI_DETECTORS
    assert len(names) == len(PI_DETECTORS)
