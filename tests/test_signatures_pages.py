"""Headless tests of the signatures on the three real pages (spec app-signatures, REQ-AS-01, 04).

``AppTest`` runs each app alone, clicks Load demo data and reads the markdown the cards write: the
number of ``gl-signature`` blocks equals the number of alert cards, each card draws badge,
signature and ``Source refs:`` in that order, and the refs show as chips. The root conftest keeps
the replay and the auto-load off, so the demo is loaded with the button. Nothing reads the network
or the clock; all data is synthetic.
"""

import html
import re
from collections.abc import Iterator

import pytest
from judge_path_support import ROOT, SCRIPTS, cases_of
from streamlit.testing.v1 import AppTest

from ledger_kit.detectors import _restore_registry, _snapshot_registry

TIMEOUT_SECONDS = 120
PREFIXES = sorted(SCRIPTS)
# The drawing of each app: heartbeat (Zombie), lantern (Phantom), bites (Vampire).
DRAWING = {"zs": "gl-heartbeat", "pi": "gl-lantern", "vf": "gl-bites"}
CHIP = re.compile(r'<span class="gl-ref-chip" title="([^"]*)">([^<]*)</span>')
# The demo files are CSV, so every chip reads "file · line N" (REQ-AS-25), never "row".
CHIP_TEXT = re.compile(r".+ \u00b7 line \d+")
# The title is the raw source_ref, then, when the line is known, "(line N of file)".
TITLE_LINE = re.compile(r" \(line \d+ of .+\)$")


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Snapshot and restore the detector registry; no key, so explanations are the templates."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    snapshot = _snapshot_registry()
    try:
        yield
    finally:
        _restore_registry(snapshot)


def _demo(prefix: str) -> AppTest:
    """Run one app alone and click Load demo data."""
    at = AppTest.from_file(str(ROOT / SCRIPTS[prefix]), default_timeout=TIMEOUT_SECONDS)
    at.run()
    at.button(key=f"{prefix}_load_demo").click().run()
    assert not at.exception
    return at


def _positions(values: list[str], start: str) -> list[int]:
    """Return the indexes of the markdown values that start with `start`."""
    return [index for index, value in enumerate(values) if value.startswith(start)]


@pytest.mark.parametrize("prefix", PREFIXES)
def test_every_alert_card_has_one_signature_of_its_app(prefix: str) -> None:
    at = _demo(prefix)
    values = [element.value for element in at.markdown]

    titles = _positions(values, f'<div class="{prefix}-alert-title">')
    signatures = _positions(values, '<div class="gl-signature">')

    assert len(titles) == len(cases_of(prefix)) > 0
    assert len(signatures) == len(titles)
    assert all(DRAWING[prefix] in values[index] for index in signatures)
    assert all(
        sum(other in values[index] for other in DRAWING.values()) == 1 for index in signatures
    )  # no card wears the drawing of another app


@pytest.mark.parametrize("prefix", PREFIXES)
def test_each_card_draws_badge_then_signature_then_source_refs(prefix: str) -> None:
    at = _demo(prefix)
    values = [element.value for element in at.markdown]

    titles = _positions(values, f'<div class="{prefix}-alert-title">')
    badges = _positions(values, f'<span class="{prefix}-badge ')
    signatures = _positions(values, '<div class="gl-signature">')
    refs = _positions(values, "**Source refs:**")

    assert len(titles) == len(badges) == len(signatures) == len(refs)
    for title, badge, signature, line in zip(titles, badges, signatures, refs, strict=True):
        assert title < badge < signature < line


@pytest.mark.parametrize("prefix", PREFIXES)
def test_the_refs_show_as_chips_in_the_order_of_the_alert(prefix: str) -> None:
    at = _demo(prefix)
    values = [element.value for element in at.markdown]

    lines = [values[index] for index in _positions(values, "**Source refs:**")]
    shown = [
        tuple(TITLE_LINE.sub("", html.unescape(title)) for title, _text in CHIP.findall(line))
        for line in lines
    ]

    assert sorted(shown) == sorted(tuple(case.alert.source_refs) for case in cases_of(prefix))
    for line in lines:
        assert line.startswith("**Source refs:** ")  # the label text is kept
        assert "`" not in line  # no inline code any more
        chips = CHIP.findall(line)
        assert chips and all(CHIP_TEXT.fullmatch(html.unescape(text)) for _title, text in chips)
        assert line.count('class="gl-ref-chip"') == len(chips)
        assert not re.search(r"\brow \d", html.unescape(line))  # no "row" next to a number


def test_each_page_ends_every_signature_with_the_caption_of_its_app() -> None:
    captions = {
        "zs": "Each dot is one cited charge.",
        "vf": "Each bite is one cited fee.",
        "pi": "Lit: the fields the detector compares. Each line is one cited row.",
    }
    for prefix in PREFIXES:
        at = _demo(prefix)
        values = [element.value for element in at.markdown]
        blocks = [v for v in values if v.startswith('<div class="gl-signature">')]

        assert blocks, prefix
        suffix = f'<div class="gl-signature-caption">{captions[prefix]}</div></div>'
        assert all(block.endswith(suffix) for block in blocks), prefix


def test_the_zombie_page_marks_the_cancelled_service_and_only_that_one() -> None:
    at = _demo("zs")
    values = [element.value for element in at.markdown]

    marked = [value for value in values if 'class="gl-tomb"' in value]

    assert len(marked) == 1
    assert "cancelled 2026-07-31" in marked[0] and "gl-dot-after" in marked[0]


def test_the_vampire_summary_card_has_one_bar_per_cited_fee_row() -> None:
    at = _demo("vf")
    values = [element.value for element in at.markdown]

    [summary] = [case for case in cases_of("vf") if case.alert.detector == "vf.fee_summary"]
    biggest = max(
        (value for value in values if value.startswith('<div class="gl-signature">')),
        key=lambda value: value.count('class="gl-fang"'),
    )

    assert biggest.count('class="gl-fang"') == len(summary.rows) == 45


def test_the_phantom_page_lights_the_compared_columns_in_its_lanterns() -> None:
    at = _demo("pi")
    values = [element.value for element in at.markdown]

    lanterns = [value for value in values if value.startswith('<div class="gl-signature">')]

    assert len(lanterns) == len(cases_of("pi"))
    assert all('class="gl-lit"' in value and 'class="gl-dim"' in value for value in lanterns)
    assert all("gl-lantern-wrap" in value for value in lanterns)
