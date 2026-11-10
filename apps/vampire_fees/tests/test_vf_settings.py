"""Tests for settings.py: config, vocabulary, demo inputs, pipeline and view models (Task VF11)."""

from datetime import date
from pathlib import Path

import pytest

from apps.vampire_fees.detectors.fee_summary import detect_fee_summary
from apps.vampire_fees.detectors.recurring_fee import detect_recurring_fees
from apps.vampire_fees.detectors.utils import EMPTY_VOCABULARY, FeeVocabulary
from apps.vampire_fees.settings import (
    BADGE_LLM,
    BADGE_REJECTED,
    BADGE_TEMPLATE,
    BADGE_UNAVAILABLE,
    DEMO_FORMATS,
    RULE_CSV,
    RULE_NORMA43,
    RULE_REFUNDS,
    DemoInputs,
    apply_demo,
    coffin_view,
    demo_inputs,
    group_alerts_by_severity,
    guard_badge,
    ingest_statement,
    load_config,
    load_vocabulary,
    markdown_safe,
    rule_sentences,
    run_pipeline,
    statement_caption,
    summary_view,
    vocabulary_lines,
)
from apps.vampire_fees.tests.vf_builders import (
    default_vocabulary,
    make_ledger,
    series_rows,
    summary_ledger,
)
from ledger_kit.explainer import Explanation
from ledger_kit.models import Alert

APP_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = APP_DIR / "config.toml"
VOCABULARY = default_vocabulary()

STATEMENT_CSV = (
    "date,amount,currency,counterparty,description,iban\n"
    "2026-01-02,100.00,EUR,Luna Estudio,Payroll,\n"
    "2026-01-05,-5.00,EUR,BANCO FICTICIO,Comisión mantenimiento cuenta,\n"
    "2026-01-09,-3.00,USD,BANCO FICTICIO,Comisión extranjera,\n"
    "2026-02-05,-5.00,EUR,BANCO FICTICIO,Comisión mantenimiento cuenta,\n"
    "2026-02-10,-20.00,EUR,Tienda Luna,Card purchase,\n"
    "2026-03-05,-5.00,EUR,BANCO FICTICIO,Comisión mantenimiento cuenta,\n"
).encode()


def write_config(tmp_path: Path, vocabulary_body: str) -> Path:
    """Write a config.toml with the given [vocabulary] body and return its path."""
    path = tmp_path / "config.toml"
    path.write_text(f"[vocabulary]\n{vocabulary_body}\n", encoding="utf-8")
    return path


VALID_BODY = (
    'fee = ["comision"]\noverdraft = ["descubierto"]\ninterest = ["intereses"]\n'
    'exclude = ["notaria"]'
)


# --- config and vocabulary ------------------------------------------------------------------------


def test_load_config_reads_the_committed_file() -> None:
    """The committed config has the four vocabulary keys and the two demo paths."""
    config = load_config(CONFIG_PATH)
    assert set(config["vocabulary"]) == {"fee", "overdraft", "interest", "exclude"}
    assert config["demo"]["csv_path"].endswith("vampire_demo_statement.csv")
    assert config["demo"]["n43_path"].endswith("vampire_demo_statement.n43")


def test_load_vocabulary_returns_the_default_vocabulary() -> None:
    """The committed config folds to the same vocabulary as the test default."""
    vocabulary = load_vocabulary(load_config(CONFIG_PATH))
    assert isinstance(vocabulary, FeeVocabulary)
    assert vocabulary == VOCABULARY


def test_load_vocabulary_of_a_small_config(tmp_path: Path) -> None:
    """A config with one phrase per key loads."""
    vocabulary = load_vocabulary(load_config(write_config(tmp_path, VALID_BODY)))
    assert vocabulary.fee == (("comision",),)


@pytest.mark.parametrize("key", ["fee", "overdraft", "interest", "exclude"])
def test_load_vocabulary_names_the_key_of_each_invalid_case(tmp_path: Path, key: str) -> None:
    """Missing, empty, non-string and letterless phrases raise ValueError naming the key."""
    valid = {
        "fee": '"comision"',
        "overdraft": '"descubierto"',
        "interest": '"intereses"',
        "exclude": '"notaria"',
    }

    def body(value: str | None) -> str:
        return "\n".join(
            f"{k} = [{value if k == key else v}]"
            for k, v in valid.items()
            if not (k == key and value is None)
        )

    for bad in (None, "", "1", '"--"', '""'):
        config = load_config(write_config(tmp_path, body(bad)))
        with pytest.raises(ValueError, match=key):
            load_vocabulary(config)


def test_load_vocabulary_without_a_table(tmp_path: Path) -> None:
    """A config without [vocabulary] raises ValueError naming the table."""
    path = tmp_path / "config.toml"
    path.write_text("[demo]\ncsv_path = 'x'\n", encoding="utf-8")
    with pytest.raises(ValueError, match="vocabulary"):
        load_vocabulary(load_config(path))


def test_vocabulary_lines_lists_each_key() -> None:
    """The read-only expander shows one line per key with its phrases."""
    lines = vocabulary_lines(load_config(CONFIG_PATH)["vocabulary"])
    assert [line.split(":")[0] for line in lines] == ["fee", "overdraft", "interest", "exclude"]
    assert "comision" in lines[0] and "notaria" in lines[3]


# --- demo inputs ---------------------------------------------------------------------------------


def test_demo_inputs_read_the_paths_of_the_demo_table(tmp_path: Path) -> None:
    """csv and n43 read their own path (synthetic bytes, not the committed demo)."""
    (tmp_path / "a.csv").write_bytes(b"csv-bytes")
    (tmp_path / "b.n43").write_bytes(b"n43-bytes")
    config = {"demo": {"csv_path": "a.csv", "n43_path": "b.n43"}}
    csv = demo_inputs(config, tmp_path, "csv")
    n43 = demo_inputs(config, tmp_path, "n43")
    assert csv == DemoInputs(b"csv-bytes", "a.csv")
    assert n43 == DemoInputs(b"n43-bytes", "b.n43")


def test_demo_inputs_unknown_format_raises(tmp_path: Path) -> None:
    """An unknown format is a ValueError."""
    with pytest.raises(ValueError, match="xml"):
        demo_inputs({"demo": {}}, tmp_path, "xml")


def test_demo_formats_radio_options() -> None:
    """The radio offers CSV and Norma 43."""
    assert DEMO_FORMATS == {"CSV": "csv", "Norma 43": "n43"}


def test_apply_demo_sets_source_and_flag() -> None:
    """apply_demo writes the vf_ keys only."""
    state: dict = {}
    apply_demo(state, DemoInputs(b"x", "demo.csv"))
    assert state == {"vf_source": ("demo", b"x", "demo.csv"), "vf_demo_loaded": True}


# --- pipeline -----------------------------------------------------------------------------------


def test_ingest_statement_caches_by_hash() -> None:
    """The second call with the same bytes and name reads nothing again."""
    cache: dict = {}
    first = ingest_statement("s.csv", STATEMENT_CSV, cache)
    assert len(cache) == 1
    second = ingest_statement("s.csv", STATEMENT_CSV, cache)
    assert len(cache) == 1
    assert first[0].equals(second[0]) and first[1] == second[1]
    ingest_statement("other.csv", STATEMENT_CSV, cache)
    assert len(cache) == 2


def test_run_pipeline_keeps_credits_counts_skipped_and_runs_vf_only() -> None:
    """The ledger has debits and credits; the USD row is skipped; alerts are vf.* only."""
    pipeline = run_pipeline("s.csv", STATEMENT_CSV, vocabulary=VOCABULARY)
    assert set(pipeline.ledger["flow"]) == {"debit", "credit"}
    assert len(pipeline.ledger) == 6
    assert pipeline.skipped_currency == 1
    assert pipeline.kind == "csv"
    assert pipeline.quarantine == []
    detectors = {alert.detector for alert in pipeline.alerts}
    assert detectors == {"vf.recurring_fee", "vf.fee_summary"}


def test_run_pipeline_without_vocabulary_finds_no_fee_in_a_csv() -> None:
    """With the empty vocabulary a CSV has no concept and no word: no alert."""
    pipeline = run_pipeline("s.csv", STATEMENT_CSV, vocabulary=EMPTY_VOCABULARY)
    assert pipeline.alerts == []


def test_run_pipeline_of_unsupported_content_is_quarantined() -> None:
    """Content that is neither CSV nor Norma 43 is quarantined and gives no alert."""
    pipeline = run_pipeline("x.xml", b"<root/>", vocabulary=VOCABULARY)
    assert pipeline.alerts == [] and len(pipeline.quarantine) == 1


# --- view models ------------------------------------------------------------------------------


def test_coffin_view_reads_alert_data_and_formats_money() -> None:
    """The coffin shows 78,00 EUR a year and keeps the refs; nothing is computed."""
    entries = [(date.fromisoformat(d), "6.50") for d in ("2026-01-05", "2026-02-05", "2026-03-05")]
    ledger = make_ledger(series_rows(entries))
    alert = detect_recurring_fees(ledger, {"vocabulary": VOCABULARY})[0]
    view = coffin_view(alert)
    assert view.counterparty == "BANCO FICTICIO"
    assert view.description == "Comisión mantenimiento cuenta"
    assert view.interval == "every month"
    assert view.current_amount == "6,50 EUR"
    assert view.yearly_cost == "78,00 EUR"
    assert view.source_refs == tuple(alert.source_refs)


@pytest.mark.parametrize(
    ("interval", "label"),
    [("monthly", "every month"), ("quarterly", "every quarter"), ("yearly", "every year")],
)
def test_coffin_interval_labels(interval: str, label: str) -> None:
    """The three interval labels."""
    alert = Alert(
        detector="vf.recurring_fee",
        severity="info",
        title="t",
        source_refs=["s.csv:1"],
        data={
            "counterparty": "BANCO FICTICIO",
            "description": "Comisión",
            "interval_type": interval,
            "current_amount": "9.00",
            "yearly_cost": "36.00",
        },
    )
    assert coffin_view(alert).interval == label


def test_summary_view_with_and_without_yearly_equivalent() -> None:
    """The metrics read the summary alert; a missing yearly figure shows n/a."""
    long_alert = detect_fee_summary(summary_ledger(), {"vocabulary": VOCABULARY})[0]
    short_alert = detect_fee_summary(summary_ledger(date(2026, 3, 30)), {"vocabulary": VOCABULARY})[
        0
    ]
    with_yearly = summary_view([long_alert])
    without = summary_view([short_alert])
    assert with_yearly is not None and without is not None
    assert (with_yearly.fee_count, with_yearly.total_fees) == ("2", "30,00 EUR")
    assert with_yearly.yearly_equivalent == "121,67 EUR"
    assert without.yearly_equivalent == "n/a"
    assert summary_view([]) is None


def test_statement_caption_and_rule_sentences() -> None:
    """The caption names file, format and counts; the rule sentence depends on the format."""
    caption = statement_caption("s.csv", "csv", 227, 202, 0, 3)
    assert caption == (
        "s.csv (CSV): 227 rows analysed (202 debit rows), 0 quarantined, 3 skipped for currency"
    )
    assert statement_caption("s.n43", "norma43", 1, 1, 0, 0).startswith("s.n43 (Norma 43)")
    assert rule_sentences("csv") == [RULE_CSV, RULE_REFUNDS]
    assert rule_sentences("norma43") == [RULE_NORMA43, RULE_REFUNDS]
    assert rule_sentences("unknown") == [RULE_REFUNDS]
    assert RULE_CSV == "A CSV has no bank concept: fees are recognised by words only."
    assert RULE_NORMA43 == "Bank concepts 16 and 17 are fees; other rows are recognised by words."
    assert RULE_REFUNDS == "Refunds are not subtracted."


def test_guard_badge_for_the_four_cases() -> None:
    """llm, rejected, unavailable (key set) and template (no key)."""
    llm = Explanation(text="t", source="llm", rejected_numbers=())
    rejected = Explanation(text="t", source="fallback", rejected_numbers=("99999.99",))
    plain = Explanation(text="t", source="fallback", rejected_numbers=())
    assert guard_badge(llm, has_api_key=True).label == BADGE_LLM
    badge = guard_badge(rejected, has_api_key=True)
    assert badge.kind == "rejected"
    assert badge.label == BADGE_REJECTED.format(numbers="99999.99")
    assert badge.label == "⚠️ LLM answer rejected: invented number 99999.99"
    assert guard_badge(plain, has_api_key=True).label == BADGE_UNAVAILABLE
    assert guard_badge(plain, has_api_key=False).label == BADGE_TEMPLATE


def test_group_alerts_by_severity_keeps_order_and_all_keys() -> None:
    """Every severity is present; alerts keep their input order inside a severity."""

    def alert(title: str, severity: str) -> Alert:
        return Alert(
            detector="vf.fee_summary", severity=severity, title=title, source_refs=["s:1"], data={}
        )

    groups = group_alerts_by_severity(
        [alert("a", "info"), alert("b", "critical"), alert("c", "info")]
    )
    assert list(groups) == ["critical", "warning", "info"]
    assert [a.title for a in groups["info"]] == ["a", "c"]
    assert groups["warning"] == []


def test_markdown_safe_escapes_markup() -> None:
    """Markdown characters are escaped so a description is shown literally."""
    assert markdown_safe("a*b_c`d") == "a\\*b\\_c\\`d"
    assert markdown_safe("plain text") == "plain text"
