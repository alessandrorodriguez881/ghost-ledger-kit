"""Headless tests of the demo with the committed INE CPI snapshot (public-cpi Task CPI9).

The expectations for the CPI figures are computed from the committed snapshot with the reader and
`money.py`, never hard-coded, so refreshing the snapshot (for example once 2026-10 is published)
changes no test (REQ-CPI-21). Nothing reads the clock or the network.
"""

import re
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import apps.zombie_subscriptions.detectors  # noqa: F401  (registers the zs.* detectors)
from apps.zombie_subscriptions import settings
from apps.zombie_subscriptions.settings import (
    CPI_UNAVAILABLE_INVALID,
    CPI_UNAVAILABLE_NOT_FOUND,
    attribution_lines,
    cpi_snapshot_path,
    cpi_unavailable_caption,
    load_config,
    load_cpi,
    read_cpi,
)
from ledger_kit.detectors import _restore_registry, _snapshot_registry, registered_names
from ledger_kit.public_data import CpiSeries, load_snapshot
from ledger_kit.utils.money import format_index, format_percent, percent_change, round_percent

ROOT = Path(__file__).resolve().parents[3]
APP_PATH = str(ROOT / "apps" / "zombie_subscriptions" / "app.py")
CONFIG_PATH = ROOT / "apps" / "zombie_subscriptions" / "config.toml"
SNAPSHOT_PATH = ROOT / "data" / "public" / "ine_cpi_ipc290751.json"
TIMEOUT_SECONDS = 60

DEMO_TOMBSTONES = 3
DEMO_ALERTS = 19
DEMO_SEVERITY_COUNTS = [1, 4, 14]  # critical, warning, info
CSV_FORMAT, REAL_FORMATS = "CSV", "Real formats"

# Price months of the two demo price steps (REQ-CPI-21): the first charge of each price level.
CLOUDVAULT = ("CLOUDVAULT", "2026-05", "2026-08", "30,0 %")
STREAMFLEX = ("STREAMFLEX INTL", "2026-05", "2026-10", "23,1 %")

SENTENCE_RE = re.compile(r"The price rose .*?\.(?= Source:|$)")


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Snapshot and restore the global detector registry; use the template path (no LLM)."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert registered_names("zs")
    snapshot = _snapshot_registry()
    try:
        yield
    finally:
        _restore_registry(snapshot)


@pytest.fixture(scope="module")
def snapshot() -> CpiSeries:
    """The committed snapshot, read by the library loader."""
    return load_snapshot(SNAPSHOT_PATH)


def _run() -> AppTest:
    """Run the app headless."""
    return AppTest.from_file(APP_PATH, default_timeout=TIMEOUT_SECONDS).run()


def _demo(fmt: str = CSV_FORMAT) -> AppTest:
    """Run the app, choose the demo format and click Load demo data."""
    at = _run()
    if fmt != CSV_FORMAT:
        at.radio(key="zs_demo_format").set_value(fmt).run()
    at.button(key="zs_load_demo").click().run()
    assert not at.exception
    return at


Card = list[tuple[str, str]]  # (element type, value) of one alert card, in page order


def _cards(at: AppTest) -> list[Card]:
    """The markdown and caption elements of every alert card, from its title to its expander."""
    cards: list[Card] = []
    current: Card | None = None
    for node in at.main:
        kind = getattr(node, "type", "")
        value = getattr(node, "value", None)
        is_title = kind == "markdown" and isinstance(value, str) and "zs-alert-title" in value
        if is_title and "<style" not in value and "background-color" not in value:
            current = []
            cards.append(current)
        if current is None:
            continue
        if kind == "expander":
            current = None
        elif kind in ("markdown", "caption") and isinstance(value, str):
            current.append((kind, value))
    return cards


def _price_cards(at: AppTest) -> list[Card]:
    """The cards of the zs.price_increase detector."""
    return [card for card in _cards(at) if any("`zs.price_increase`" in v for _k, v in card)]


def _card_of(at: AppTest, counterparty: str) -> Card:
    """The single price-increase card of one counterparty."""
    needle = f"The {counterparty} charge"
    [card] = [c for c in _price_cards(at) if any(needle in v for _k, v in c)]
    return card


def _text(card: Card) -> str:
    """All the text of a card."""
    return "\n".join(value for _kind, value in card)


def _containing(card: Card, needle: str) -> list[str]:
    """The elements of a card that contain `needle`."""
    return [value for _kind, value in card if needle in value]


def _captions(at: AppTest) -> list[str]:
    """Every caption of the page."""
    return [element.value for element in at.caption]


def _counts(at: AppTest) -> list[int]:
    """The metrics row: tombstones, then critical, warning and info alerts."""
    return [int(metric.value) for metric in at.metric]


def _cpi_percent(start: str, end: str, snapshot: CpiSeries) -> str:
    """The CPI change between two lookups of the snapshot, as the card shows it."""
    first, last = snapshot.lookup(start), snapshot.lookup(end)
    return format_percent(round_percent(percent_change(first.value, last.value)))


def _expectation(
    snapshot: CpiSeries, price_start: str, price_end: str, price_percent: str
) -> tuple[str, str] | None:
    """The (sentence, source line) a price card must show, or None when it must show neither.

    Written from REQ-CPI-06 and REQ-CPI-17/18 directly, not from the app's helpers.
    """
    start, end = snapshot.lookup(price_start), snapshot.lookup(price_end)
    if start is None or end is None or start.used == end.used:
        return None
    change = format_percent(round_percent(percent_change(start.value, end.value)))
    head = f"CPI source: INE series IPC290751 (base 2025 = 100), {start.used} = "
    line = f"{head}{format_index(start.value)}, {end.used} = {format_index(end.value)}"
    if start.is_fallback or end.is_fallback:
        sentence = (
            f"The price rose {price_percent} from {price_start} to {price_end}, while the "
            f"Spanish CPI (INE series IPC290751) changed by {change} from {start.used} to "
            f"{end.used}, using the latest published CPI month available."
        )
        line += f"; latest published month used; price months {price_start} and {price_end}"
    else:
        sentence = (
            f"The price rose {price_percent} while the Spanish CPI (INE series IPC290751) "
            f"changed by {change} from {start.used} to {end.used}."
        )
    return sentence, line


# --- the demo with the snapshot ---------------------------------------------------------------


def test_demo_counts_are_unchanged_with_the_snapshot_loaded() -> None:
    """The CPI is decoration: 3 tombstones and 19 alerts (1 critical, 4 warning, 14 info)."""
    at = _demo()

    assert _counts(at) == [DEMO_TOMBSTONES, *DEMO_SEVERITY_COUNTS]
    assert len(_cards(at)) == DEMO_ALERTS
    assert sum(DEMO_SEVERITY_COUNTS) == DEMO_ALERTS


@pytest.mark.parametrize("case", [CLOUDVAULT, STREAMFLEX], ids=["cloudvault", "streamflex"])
def test_price_card_carries_the_cpi_sentence_iff_the_snapshot_covers_its_months(
    snapshot: CpiSeries, case: tuple[str, str, str, str]
) -> None:
    """The sentence and the source line appear exactly when REQ-CPI-06 answers both months."""
    counterparty, price_start, price_end, price_percent = case
    expected = _expectation(snapshot, price_start, price_end, price_percent)
    card = _card_of(_demo(), counterparty)
    text = _text(card)

    assert price_percent in text
    if expected is None:
        assert "IPC290751" not in text
        assert _containing(card, "changed by") == []
        return
    sentence, line = expected
    assert sentence in text
    assert len(_containing(card, "changed by")) == 1  # the sentence is shown once
    assert _containing(card, "CPI source:") == [line]


def test_cloudvault_card_is_always_covered_and_shows_its_figures(snapshot: CpiSeries) -> None:
    """CLOUDVAULT goes from 2026-05 to 2026-08: both months are published exactly."""
    card = _card_of(_demo(), CLOUDVAULT[0])
    text = _text(card)
    cpi_change = _cpi_percent("2026-05", "2026-08", snapshot)

    assert "30,0 %" in text
    assert "IPC290751" in text
    assert "2026-05" in text and "2026-08" in text
    assert f"changed by {cpi_change} from 2026-05 to 2026-08." in text
    assert len(_containing(card, "changed by")) == 1


def test_streamflex_card_follows_the_snapshot_range(snapshot: CpiSeries) -> None:
    """STREAMFLEX INTL ends in 2026-10: plain sentence if published, lag sentence at 2026-09."""
    card = _card_of(_demo(), STREAMFLEX[0])
    text = _text(card)

    if snapshot.last_month == "2026-09":
        assert "using the latest published CPI month available." in text
        assert "from 2026-05 to 2026-09" in text
        assert "price months 2026-05 and 2026-10" in text
        assert f"changed by {_cpi_percent('2026-05', '2026-10', snapshot)}" in text
    elif snapshot.last_month >= "2026-10":
        assert "using the latest published CPI month available." not in text
        assert "from 2026-05 to 2026-10" in text


def test_only_covered_price_cards_mention_the_cpi() -> None:
    """No recurring, duplicate, trial or cancellation card mentions the series."""
    at = _demo()
    price_cards = _price_cards(at)

    for card in _cards(at):
        if card not in price_cards:
            assert "IPC290751" not in _text(card)
            assert "CPI source" not in _text(card)
    mentioning = [card for card in price_cards if "IPC290751" in _text(card)]
    assert mentioning, "at least the CLOUDVAULT card carries the CPI"
    for card in mentioning:
        assert len(_containing(card, "CPI source:")) == 1
        assert len(_containing(card, "changed by")) == 1


def test_footer_shows_the_attribution_once(snapshot: CpiSeries) -> None:
    """The three attribution lines appear once on the page, from the snapshot itself."""
    at = _demo()
    captions = _captions(at)

    lines = attribution_lines(snapshot)
    assert len(lines) == 3
    for line in lines:
        assert captions.count(line) == 1
    every_text = [*captions, *(m.value for m in at.markdown)]
    assert sum(snapshot.attribution in value for value in every_text) == 1
    assert sum(snapshot.no_endorsement in value for value in every_text) == 1
    assert not any(CPI_UNAVAILABLE_NOT_FOUND in value for value in captions)


def test_footer_is_absent_before_the_demo_is_loaded() -> None:
    """With no statement the page draws no alerts, hence no attribution."""
    at = _run()

    assert not at.exception
    assert not any("Elaboración propia" in value for value in _captions(at))


def test_hallucinating_llm_still_rejected_and_the_card_keeps_the_cpi_sentence() -> None:
    """The stub's invented figure is rejected; the sentence on the card comes from the alert."""
    at = _demo()

    at.toggle(key="zs_hallucinate").set_value(True).run()

    assert not at.exception
    badges = [m.value for m in at.markdown if m.value.startswith('<span class="zs-badge ')]
    assert len(badges) == DEMO_ALERTS
    assert all("zs-badge-rejected" in b and "99999.99" in b for b in badges)
    card = _card_of(at, CLOUDVAULT[0])
    assert len(_containing(card, "changed by")) == 1
    assert _counts(at) == [DEMO_TOMBSTONES, *DEMO_SEVERITY_COUNTS]


def test_norma43_demo_gives_the_same_cpi_lines_as_the_csv_demo() -> None:
    """Months come from row dates, identical in both formats (REQ-CPI-21)."""
    csv_run = _demo(CSV_FORMAT)
    n43_run = _demo(REAL_FORMATS)

    assert _counts(n43_run) == _counts(csv_run) == [DEMO_TOMBSTONES, *DEMO_SEVERITY_COUNTS]

    def cpi_lines(at: AppTest) -> list[str]:
        """The CPI source lines and the CPI sentences of the price cards."""
        found: list[str] = []
        for card in _price_cards(at):
            found += _containing(card, "CPI source:")
            found += [m.group(0) for m in SENTENCE_RE.finditer(_text(card))]
        return found

    assert cpi_lines(csv_run), "the demo must carry at least one CPI line"
    assert cpi_lines(n43_run) == cpi_lines(csv_run)


# --- the snapshot is not available -------------------------------------------------------------


def _patch_snapshot_path(monkeypatch: pytest.MonkeyPatch, path: str) -> None:
    """Make every load_config call of the app report another [cpi] snapshot_path."""
    real: Callable[[Path], dict] = settings.load_config

    def patched(config_path: Path) -> dict:
        config = real(config_path)
        config["cpi"] = {"snapshot_path": path}
        return config

    monkeypatch.setattr(settings, "load_config", patched)


def test_missing_snapshot_shows_a_caption_and_no_cpi(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing file: the caption, no attribution, no CPI on any card, still 19 alerts."""
    _patch_snapshot_path(monkeypatch, "data/public/does_not_exist.json")

    at = _demo()

    assert _counts(at) == [DEMO_TOMBSTONES, *DEMO_SEVERITY_COUNTS]
    assert len(_cards(at)) == DEMO_ALERTS
    assert _captions(at).count(CPI_UNAVAILABLE_NOT_FOUND) == 1
    assert CPI_UNAVAILABLE_NOT_FOUND == "CPI context unavailable: snapshot not found."
    everything = " ".join([*_captions(at), *(m.value for m in at.markdown)])
    assert "Elaboración propia" not in everything
    assert "IPC290751" not in everything
    assert "changed by" not in everything
    card = _card_of(at, CLOUDVAULT[0])
    assert "30,0 %" not in _text(card)  # today's text: no percentage without CPI


def test_invalid_snapshot_shows_the_invalid_caption(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A file that fails validation does not take the page down and is not called 'not found'."""
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    _patch_snapshot_path(monkeypatch, str(broken))

    at = _demo()

    assert not at.exception
    assert _captions(at).count(CPI_UNAVAILABLE_INVALID) == 1
    assert len(_cards(at)) == DEMO_ALERTS
    assert "IPC290751" not in " ".join(_captions(at))


# --- settings helpers --------------------------------------------------------------------------


def test_config_points_at_the_committed_snapshot() -> None:
    """[cpi] snapshot_path names the committed file, relative to the repository root."""
    config = load_config(CONFIG_PATH)

    assert config["cpi"]["snapshot_path"] == "data/public/ine_cpi_ipc290751.json"
    assert cpi_snapshot_path(config, ROOT) == SNAPSHOT_PATH
    assert "thresholds" not in config["cpi"]


def test_load_cpi_reads_the_committed_snapshot(snapshot: CpiSeries) -> None:
    """load_cpi returns the same series as the library loader."""
    series = load_cpi(load_config(CONFIG_PATH), ROOT)

    assert series is not None
    assert series.entries == snapshot.entries
    assert series.retrieved_on == snapshot.retrieved_on


def test_load_cpi_without_a_cpi_section_is_none() -> None:
    """No [cpi] table, or an empty path: no series."""
    assert load_cpi({}, ROOT) is None
    assert load_cpi({"cpi": {}}, ROOT) is None
    assert load_cpi({"cpi": {"snapshot_path": ""}}, ROOT) is None
    assert cpi_snapshot_path({}, ROOT) is None


def test_read_cpi_never_raises(tmp_path: Path) -> None:
    """A missing, unreadable-as-JSON or invalid file gives None, not an exception."""
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    invalid = tmp_path / "invalid.json"
    invalid.write_text("[]", encoding="utf-8")

    assert read_cpi(tmp_path / "missing.json") is None
    assert read_cpi(broken) is None
    assert read_cpi(invalid) is None
    assert read_cpi(SNAPSHOT_PATH) is not None


def test_unavailable_caption_tells_missing_from_invalid(tmp_path: Path) -> None:
    """'not found' only when there is no file; 'invalid' when the file exists but fails."""
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")

    assert cpi_unavailable_caption(None) == CPI_UNAVAILABLE_NOT_FOUND
    assert cpi_unavailable_caption(tmp_path / "missing.json") == CPI_UNAVAILABLE_NOT_FOUND
    assert cpi_unavailable_caption(broken) == CPI_UNAVAILABLE_INVALID
