"""Tests for settings.py and config.toml (Task Z17)."""

import string
from datetime import date, datetime
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from apps.zombie_subscriptions.detectors import utils
from apps.zombie_subscriptions.settings import (
    DemoInputs,
    demo_inputs,
    format_aliases_text,
    format_dates_text,
    load_config,
    parse_aliases_text,
    parse_dates_text,
    statement_caption,
    to_date,
)

APP_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = APP_DIR / "config.toml"

DEMO_CSV_TEXT = (
    "date,amount,currency,counterparty,description,iban\n"
    "2026-05-01,-1.00,EUR,CLOUDVAULT,Monthly subscription,\n"
)


def _write_config(tmp_path: Path, body: str) -> Path:
    """Write a TOML file plus the tiny demo CSV it points to; return the config path."""
    # write_bytes: Path.write_text would translate "\n" to CRLF on Windows.
    (tmp_path / "demo.csv").write_bytes(DEMO_CSV_TEXT.encode("utf-8"))
    path = tmp_path / "config.toml"
    path.write_text(body, encoding="utf-8")
    return path


# --- Tier 1 -----------------------------------------------------------------------------------


def test_load_config_reads_aliases_and_demo() -> None:
    """config.toml has an [aliases] table and a [demo] section with the three demo tables."""
    config = load_config(CONFIG_PATH)
    assert config["aliases"]["streaming"] == ["STREAMFLIX INTL", "STREAMFLIXCOM", "STREAMFLIX"]
    demo = config["demo"]
    assert demo["csv_path"] == "data/samples/zombie_demo_statement.csv"
    assert demo["n43_path"] == "data/samples/zombie_demo_statement.n43"
    assert demo["aliases"] == {"streaming": ["STREAMFLIX INTL", "STREAMFLIXCOM"]}
    assert set(demo["last_used_dates"]) == {"BEATSTREAM", "PHOTOBOX", "STASHCRATE"}
    assert set(demo["cancellation_dates"]) == {"GYMPLUS"}


def test_demo_dates_converted_with_fromisoformat(tmp_path: Path) -> None:
    """TOML date strings become datetime.date; real TOML dates are accepted too."""
    quoted = _write_config(
        tmp_path,
        '[demo]\ncsv_path = "demo.csv"\n'
        '[demo.last_used_dates]\nA = "2026-07-15"\n'
        '[demo.cancellation_dates]\nB = "2026-07-31"\n',
    )
    inputs = demo_inputs(load_config(quoted), tmp_path)
    assert inputs.last_used_dates == {"A": date(2026, 7, 15)}
    assert inputs.cancellation_dates == {"B": date(2026, 7, 31)}
    assert type(inputs.last_used_dates["A"]) is date

    native = _write_config(
        tmp_path,
        '[demo]\ncsv_path = "demo.csv"\n'
        "[demo.last_used_dates]\nA = 2026-07-15\n"
        "[demo.cancellation_dates]\nB = 2026-07-31\n",
    )
    inputs = demo_inputs(load_config(native), tmp_path)
    assert inputs.last_used_dates == {"A": date(2026, 7, 15)}
    assert inputs.cancellation_dates == {"B": date(2026, 7, 31)}


def test_demo_inputs_reads_statement_bytes_and_name(tmp_path: Path) -> None:
    """demo_inputs returns the statement bytes, its file name and the alias table."""
    path = _write_config(
        tmp_path,
        '[demo]\ncsv_path = "demo.csv"\n[demo.aliases]\nstreaming = ["A", "B"]\n',
    )
    inputs = demo_inputs(load_config(path), tmp_path)
    assert isinstance(inputs, DemoInputs)
    assert inputs.statement_bytes == DEMO_CSV_TEXT.encode("utf-8")
    assert inputs.statement_name == "demo.csv"
    assert inputs.aliases == {"streaming": ["A", "B"]}
    assert inputs.last_used_dates == {}
    assert inputs.cancellation_dates == {}


def test_demo_inputs_real_reads_the_n43_path_and_keeps_the_user_inputs(tmp_path: Path) -> None:
    """`real` reads n43_path; aliases and dates are the same for both formats (REQ-RF-25)."""
    (tmp_path / "demo.n43").write_bytes(b"11 not read here")
    path = _write_config(
        tmp_path,
        '[demo]\ncsv_path = "demo.csv"\nn43_path = "demo.n43"\n'
        '[demo.aliases]\nstreaming = ["A", "B"]\n[demo.last_used_dates]\nA = "2026-07-15"\n',
    )
    config = load_config(path)

    csv, real = demo_inputs(config, tmp_path), demo_inputs(config, tmp_path, "real")

    assert (real.statement_name, real.statement_bytes) == ("demo.n43", b"11 not read here")
    assert csv.statement_name == "demo.csv"
    assert (csv.aliases, csv.last_used_dates, csv.cancellation_dates) == (
        real.aliases,
        real.last_used_dates,
        real.cancellation_dates,
    )
    with pytest.raises(ValueError, match="unknown demo format"):
        demo_inputs(config, tmp_path, "pdf")  # type: ignore[arg-type]


def test_statement_caption_names_the_detected_format() -> None:
    """The line under the title says which format was read; unknown kinds are not named."""
    assert statement_caption("a.n43", "norma43", 3, 1) == (
        "a.n43 (Norma 43): 3 debit rows analysed, 1 quarantined"
    )
    assert statement_caption("a.csv", "csv", 0, 0) == (
        "a.csv (CSV): 0 debit rows analysed, 0 quarantined"
    )
    assert statement_caption("a.xml", "facturae", 0, 1).startswith("a.xml (Facturae XML): ")
    assert statement_caption("a.pdf", "unknown", 0, 1) == (
        "a.pdf: 0 debit rows analysed, 1 quarantined"
    )


def test_to_date_accepts_strings_and_dates() -> None:
    """to_date parses ISO strings and passes dates through (datetimes become dates)."""
    assert to_date("2026-07-15") == date(2026, 7, 15)
    assert to_date(date(2026, 7, 15)) == date(2026, 7, 15)
    converted = to_date(datetime(2026, 7, 15, 12, 30))
    assert converted == date(2026, 7, 15)
    assert type(converted) is date


def test_parse_aliases_text_roundtrip() -> None:
    """The sidebar alias text parses into {name: [members]}."""
    text = "streaming = STREAMFLIX INTL, STREAMFLIXCOM\nmusic = BEATSTREAM"
    parsed = parse_aliases_text(text)
    assert parsed == {"streaming": ["STREAMFLIX INTL", "STREAMFLIXCOM"], "music": ["BEATSTREAM"]}
    assert format_aliases_text(parsed) == text


def test_parse_dates_text_roundtrip() -> None:
    """The sidebar date text parses into {name: date}."""
    text = "BEATSTREAM = 2026-07-15\nPHOTOBOX = 2026-06-20"
    parsed = parse_dates_text(text)
    assert parsed == {"BEATSTREAM": date(2026, 7, 15), "PHOTOBOX": date(2026, 6, 20)}
    assert format_dates_text(parsed) == text


def test_parse_dates_text_rejects_bad_date_with_clear_error() -> None:
    """A bad date raises ValueError naming the service and the expected format."""
    with pytest.raises(ValueError, match=r"BEATSTREAM.*YYYY-MM-DD"):
        parse_dates_text("BEATSTREAM = 2026-13-45")
    with pytest.raises(ValueError, match="PHOTOBOX"):
        parse_dates_text("PHOTOBOX = next tuesday")


def test_parse_rejects_line_without_equals_sign() -> None:
    """A line without '=' is reported instead of being silently dropped."""
    with pytest.raises(ValueError, match="BEATSTREAM 2026-07-15"):
        parse_dates_text("BEATSTREAM 2026-07-15")
    with pytest.raises(ValueError, match="streaming STREAMFLIX"):
        parse_aliases_text("streaming STREAMFLIX")


# --- Tier 2 -----------------------------------------------------------------------------------


def test_parse_empty_text_returns_empty_dict() -> None:
    """Empty and whitespace-only text give an empty dict."""
    assert parse_aliases_text("") == {}
    assert parse_dates_text("") == {}
    assert parse_aliases_text("  \n \t\n") == {}
    assert parse_dates_text("  \n \t\n") == {}


def test_parse_ignores_blank_lines_and_whitespace() -> None:
    """Blank lines, surrounding spaces and empty members are ignored."""
    assert parse_aliases_text("\n  streaming =  A ,, B  \n\n") == {"streaming": ["A", "B"]}
    assert parse_dates_text("\n  BEATSTREAM  =  2026-07-15 \n\n") == {
        "BEATSTREAM": date(2026, 7, 15)
    }


def test_config_contains_no_threshold_constants() -> None:
    """REQ-ZS-42: config.toml names none of the threshold constants of detectors/utils.py."""
    text = CONFIG_PATH.read_text(encoding="utf-8")
    constant_names = [name for name in dir(utils) if name.isupper()]
    assert constant_names
    assert [name for name in constant_names if name in text] == []


def test_demo_section_has_at_least_3_last_used_and_1_cancellation() -> None:
    """REQ-ZS-44: three last-used dates and one cancellation date, all valid ISO dates."""
    demo = load_config(CONFIG_PATH)["demo"]
    last_used = {name: to_date(value) for name, value in demo["last_used_dates"].items()}
    cancellation = {name: to_date(value) for name, value in demo["cancellation_dates"].items()}
    assert len(last_used) >= 3
    assert len(cancellation) >= 1
    assert all(type(d) is date for d in [*last_used.values(), *cancellation.values()])


def test_config_has_no_real_brand_names() -> None:
    """Finance Rule 5: the config uses fictional brands only."""
    text = CONFIG_PATH.read_text(encoding="utf-8").upper()
    for brand in ("SPOTIFY", "ADOBE", "DROPBOX", "NETFLIX"):
        assert brand not in text


# --- Tier 3 -----------------------------------------------------------------------------------

_NAME = (
    st.text(alphabet=string.ascii_uppercase + string.digits + " ", min_size=1, max_size=12)
    .map(str.strip)
    .filter(bool)
)
_ALIAS_MAPS = st.dictionaries(_NAME, st.lists(_NAME, min_size=1, max_size=4), max_size=5)
_DATE_MAPS = st.dictionaries(
    _NAME, st.dates(min_value=date(2000, 1, 1), max_value=date(2100, 12, 31)), max_size=5
)


@settings(max_examples=200, deadline=None)
@given(aliases=_ALIAS_MAPS)
def test_format_then_parse_is_identity_for_alias_maps(aliases: dict[str, list[str]]) -> None:
    """parse_aliases_text(format_aliases_text(x)) == x."""
    assert parse_aliases_text(format_aliases_text(aliases)) == aliases


@settings(max_examples=200, deadline=None)
@given(dates=_DATE_MAPS)
def test_format_then_parse_is_identity_for_date_maps(dates: dict[str, date]) -> None:
    """parse_dates_text(format_dates_text(x)) == x."""
    assert parse_dates_text(format_dates_text(dates)) == dates
