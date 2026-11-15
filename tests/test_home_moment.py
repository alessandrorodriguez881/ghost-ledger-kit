"""Home with one clear moment (haunted-design session 26, REQ-HD-16 to REQ-HD-23).

Tier 1: the moment (struck marks, stamp, fixed template, note), its CSS (CSS only, under three
seconds, played once, reduced motion), the expander that holds the moved text, and one drawing per
app tile. Tier 2: a file that cannot give the moment, a guard that no longer rejects, an alert
that is not found, a drawing that cannot be built. No model is called and no network is used;
every figure is synthetic or recorded.
"""

import ast
import html
import json
import re
import textwrap
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from defusedxml.ElementTree import fromstring
from judge_path_support import ROOT, _phantom, _vampire, _zombie, find_case, template_of
from streamlit.testing.v1 import AppTest

import streamlit_app
from apps import home_tiles
from ledger_kit import replay
from ledger_kit.explainer import Explanation, explain_with_meta
from ledger_kit.live_guard import MARK_STYLE, TRICK_QUESTIONS
from ledger_kit.models import Alert
from ledger_kit.replay import HOME_EXAMPLE_MARKS, Recording, ReplayClient
from ledger_kit.ui import landing, signatures, theme
from ledger_kit.ui.landing import Moment, moment_html, struck_marks, tile_html, tiles_html
from ledger_kit.ui.reference_app import rows_for_refs
from ledger_kit.ui.signatures import (
    PHANTOM_CAPTION,
    VAMPIRE_CAPTION,
    ZOMBIE_CAPTION,
    bites_svg,
    heartbeat_svg,
    lantern_html,
    refs_chips_html,
    signature_block,
)

ENTRY = str(ROOT / "streamlit_app.py")
TIMEOUT_SECONDS = 60
HOME_FILE = replay.DEFAULT_HOME_EXAMPLE_PATH
MARKUP = re.compile(r"<[^>]+>")
FIGURE = re.compile(r"\d+(?:[.,]\d+)*")
FORECAST = TRICK_QUESTIONS[0]
TEMPLATE = "Invoice A-1 appears twice. Source: invoices.csv:3, invoices.csv:7."
STRIKE_1 = f'<mark class="gl-strike gl-strike-1" style="{MARK_STYLE}">5%</mark>'
STRIKE_2 = f'<mark class="gl-strike gl-strike-2" style="{MARK_STYLE}">617.51</mark>'
TILE_START = '<div class="gl-card gl-tile '
SECTION_START = '<div class="gl-section" role="heading" aria-level="2">'


@pytest.fixture
def home_file(monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the Home example at the committed file (the root conftest points it nowhere)."""
    monkeypatch.setattr(replay, "HOME_EXAMPLE_PATH", HOME_FILE)
    return HOME_FILE


def _recording() -> Recording:
    recording = replay.home_example(HOME_FILE)
    assert recording is not None
    return recording


def _moment(rejected: tuple[str, ...] = ("617.51", "5"), template: str = TEMPLATE) -> Moment:
    return Moment(_recording(), rejected, template)


def _text(markup: str) -> str:
    """The words of a block of markup: tags cut out, entities decoded."""
    return html.unescape(MARKUP.sub(" ", markup))


def _markdown(at: AppTest) -> list[str]:
    return [element.value for element in at.markdown]


def _starting(at: AppTest, prefix: str) -> list[str]:
    return [value for value in _markdown(at) if value.startswith(prefix)]


def _home() -> AppTest:
    at = AppTest.from_file(ENTRY, default_timeout=TIMEOUT_SECONDS).run()
    assert not at.exception
    return at


def _alert(severity: str, number: int) -> Alert:
    return Alert(
        detector="zs.test",
        severity=severity,
        title=f"alert {number}",
        source_refs=[f"s.csv:{number}"],
        data={"n": number},
    )


# --- struck marks --------------------------------------------------------------------------------


def test_the_marks_are_the_rate_and_the_total() -> None:
    assert HOME_EXAMPLE_MARKS == ("5%", "617.51")


@pytest.mark.parametrize(
    ("rejected", "expected"),
    [
        (("617.51", "5"), ("5%", "617.51")),
        (("5", "617.51"), ("5%", "617.51")),
        (("617.51",), ("617.51",)),
        (("5",), ("5%",)),
        (("15", "6175"), ()),
        ((), ()),
    ],
)
def test_a_mark_is_struck_when_the_guard_rejected_its_number(
    rejected: tuple[str, ...], expected: tuple[str, ...]
) -> None:
    assert struck_marks(rejected) == expected


# --- the moment: struck marks, stamp, fixed template, note (REQ-HD-17) ---------------------------


def test_the_moment_has_two_struck_marks_the_stamp_the_template_and_the_note() -> None:
    block = moment_html(_moment())

    assert block.startswith('<div class="gl-moment">') and block.endswith("</div>")
    assert STRIKE_1 in block and STRIKE_2 in block
    assert block.count('class="gl-strike ') == 2 and block.count("<mark") == 2
    assert (
        '<div class="gl-stamp"><b>Rejected by the number guard.</b> '
        "Struck out: 5%, 617.51. Not in any cited row or alert field.</div>"
    ) in block
    assert f'<div class="gl-moment-template">{TEMPLATE}</div>' in block
    assert '<div class="gl-label">Fixed template shown instead</div>' in block
    assert (
        '<div class="gl-moment-label">One recorded answer of llama3.2:3b, 2026-11-10. '
        "No model is called.</div>"
    ) in block
    assert f'<div class="gl-moment-q">Question: {FORECAST.text}</div>' in block
    assert '<div class="gl-moment-note">A recorded answer: no model is called.' in block


def test_the_parts_come_in_the_order_the_animation_plays_them() -> None:
    block = moment_html(_moment())
    parts = (
        "gl-moment-label",
        "gl-moment-q",
        "gl-moment-answer",
        STRIKE_1,
        STRIKE_2,
        "gl-stamp",
        "gl-moment-after",
        "gl-moment-template",
        "gl-moment-note",
    )
    order = [block.index(part) for part in parts]

    assert order == sorted(order)


def test_the_answer_is_quoted_as_the_model_wrote_it() -> None:
    recording = _recording()
    block = moment_html(_moment())
    rate = html.escape(recording.sentence_with("5%") or "").replace("5%", STRIKE_1)
    total = html.escape(recording.last_sentence_with("617.51") or "").replace("617.51", STRIKE_2)

    assert f"“{rate}”" in block
    assert f"“{total}”" in block
    assert "interest rate of " + STRIKE_1 in block
    assert "approximately €" + STRIKE_2 in block


def test_a_single_struck_figure_strikes_only_that_one() -> None:
    block = moment_html(_moment(rejected=("617.51",)))

    assert STRIKE_2 in block and STRIKE_1 not in block
    assert "Struck out: 617.51." in block


def test_the_moment_is_one_well_formed_line_and_escapes_the_template() -> None:
    block = moment_html(_moment(template="<b>x</b> & y\n\nz"))

    assert "\n" not in block
    assert "&lt;b&gt;x&lt;/b&gt; &amp; y z" in block
    assert "<b>x</b>" not in block
    fromstring(block)


def test_the_moment_writes_no_figure_of_its_own() -> None:
    recording = _recording()
    block = moment_html(_moment())
    allowed = f"{recording.raw_answer} {TEMPLATE} {recording.model_name} {recording.date}"

    figures = FIGURE.findall(_text(block))
    assert figures  # the check below is not vacuous
    assert [f for f in figures if f not in allowed] == []
    literals = landing.MOMENT_STAMP + landing.MOMENT_TEMPLATE_LABEL + landing.MOMENT_NOTE
    assert re.search(r"\d", literals) is None


def _without_question(moment: Moment) -> Moment:
    return replace(moment, recording=replace(moment.recording, question_id=None))


def _not_a_preset(moment: Moment) -> Moment:
    return replace(moment, recording=replace(moment.recording, question_id="not-a-preset"))


def _nothing_said(moment: Moment) -> Moment:
    return replace(moment, recording=replace(moment.recording, raw_answer="Nothing here."))


def _without_the_rate(moment: Moment) -> Moment:
    answer = moment.recording.raw_answer.replace("5%", "x")
    return replace(moment, recording=replace(moment.recording, raw_answer=answer))


def _nothing_rejected(moment: Moment) -> Moment:
    return replace(moment, rejected=())


def _another_figure_rejected(moment: Moment) -> Moment:
    return replace(moment, rejected=("999.99",))


def _no_template(moment: Moment) -> Moment:
    return replace(moment, template="")


def _blank_template(moment: Moment) -> Moment:
    return replace(moment, template="  \n ")


@pytest.mark.parametrize(
    "change",
    [
        _without_question,
        _not_a_preset,
        _nothing_said,
        _without_the_rate,
        _nothing_rejected,
        _another_figure_rejected,
        _no_template,
        _blank_template,
    ],
)
def test_a_recording_that_cannot_carry_the_moment_gives_no_markup(change: Any) -> None:
    assert moment_html(change(_moment())) == ""


def test_no_moment_without_a_moment() -> None:
    assert moment_html(None) == ""


def test_the_example_block_of_the_earlier_session_is_still_there() -> None:
    assert landing.example_html(_recording()).startswith('<div class="gl-example">')
    assert "107.88 × 5 = 539.40" in landing.EXAMPLE_NOTE  # the note Home no longer prints


# --- the CSS: CSS only, under three seconds, once, reduced motion (REQ-HD-18) --------------------

ANIMATION = re.compile(r"animation: (gl-\w+) ([\d.]+)s [\w-]+ ([\d.]+)s (\d+) both;")
STRIKE_TWO_DELAY = re.compile(r"gl-strike-2::after \{ animation-delay: ([\d.]+)s; \}")


def test_the_moment_css_has_three_timed_animations_and_no_other_technology() -> None:
    css = theme.MOMENT_CSS
    found = ANIMATION.findall(css)

    assert [name for name, *_rest in found] == ["gl-strike", "gl-stamp", "gl-fade"]
    assert css.count("@keyframes") == 3
    for forbidden in ("<script", "url(", "@import", "transition", "javascript"):
        assert forbidden not in css.lower()
    assert max(len(line) for line in css.splitlines()) <= 100


def test_the_moment_ends_within_three_seconds_and_starts_after_about_one() -> None:
    strike, stamp, fade = ANIMATION.findall(theme.MOMENT_CSS)
    [second_strike_delay] = STRIKE_TWO_DELAY.findall(theme.MOMENT_CSS)
    def ms(seconds: str) -> int:
        """Whole milliseconds, so sums and comparisons carry no floating point error."""
        return round(float(seconds) * 1000)

    strike_len, strike_delay = ms(strike[1]), ms(strike[2])
    stamp_len, stamp_delay = ms(stamp[1]), ms(stamp[2])
    fade_len, fade_delay = ms(fade[1]), ms(fade[2])
    last_strike_start = ms(second_strike_delay)

    ends = [strike_delay + strike_len, last_strike_start + strike_len]
    ends += [stamp_delay + stamp_len, fade_delay + fade_len]
    assert max(ends) <= 3000
    assert 800 <= strike_delay <= 1200  # "after about one second"
    assert strike_delay < last_strike_start
    # the stamp starts when the last strike is done, the template when the stamp is done
    assert stamp_delay >= last_strike_start + strike_len
    assert fade_delay >= stamp_delay + stamp_len
    assert fade_len > 0


def test_every_animation_plays_once() -> None:
    found = ANIMATION.findall(theme.MOMENT_CSS)

    assert len(found) == 3
    assert all(count == "1" for _name, _len, _delay, count in found)
    assert "infinite" not in theme.MOMENT_CSS


def test_the_reduced_motion_rule_shows_the_final_state_at_once() -> None:
    css = theme.MOMENT_CSS
    rule = css[css.index("@media (prefers-reduced-motion: reduce)") :]

    assert rule.count("animation: none;") == 1
    for selector in ("gl-strike::after", "gl-stamp", "gl-moment-after"):
        assert selector in rule


def test_the_base_style_of_each_piece_is_its_final_state() -> None:
    """Only a keyframe names the hidden state, so no animation (or none at all) shows the end."""
    for line in theme.MOMENT_CSS.splitlines():
        if "opacity: 0;" in line or "scaleX(0)" in line:
            assert line.startswith("@keyframes"), line


def test_the_moment_css_is_in_the_home_style_block_only() -> None:
    moment = theme.MOMENT_CSS.strip("\n")

    assert moment in theme.theme_css(theme.KIT)
    for accent in (theme.BENCHMARK, theme.ZOMBIE, theme.PHANTOM, theme.VAMPIRE):
        assert moment not in theme.theme_css(accent)
    assert "@keyframes" not in theme.BASE_CSS


def test_home_adds_no_javascript_or_component() -> None:
    for name in ("streamlit_app.py", "apps/home_tiles.py"):
        source = (ROOT / name).read_text(encoding="utf-8")
        assert "components" not in source and "<script" not in source


# --- the page: the moment on Home (REQ-HD-16, 17, 19) --------------------------------------------


def _verdict_of_the_recording() -> Explanation:
    """Today's guard on the recorded text, by the route the tests of the example use."""
    recording = _recording()
    case = find_case(recording.alert_id)
    assert case is not None
    return explain_with_meta(
        case.alert,
        case.rows,
        fallback_template=template_of(case),
        client=ReplayClient(recording.raw_answer),
        row_columns=case.columns,
        question=recording.question_text,
    )


def test_home_moment_is_todays_verdict_on_the_recorded_text(home_file: Path) -> None:
    verdict = _verdict_of_the_recording()
    moment = home_tiles.home_moment()

    assert verdict.source == "fallback"
    assert moment is not None
    assert moment.recording == _recording()
    assert moment.rejected == tuple(verdict.rejected_numbers)
    assert "617.51" in moment.rejected and "5" in moment.rejected
    assert moment.template == verdict.text


def test_home_shows_the_moment_with_the_struck_marks_the_stamp_and_the_template(
    home_file: Path,
) -> None:
    [block] = _starting(_home(), '<div class="gl-moment">')
    template = " ".join(_verdict_of_the_recording().text.split())

    assert STRIKE_1 in block and STRIKE_2 in block
    assert "<b>Rejected by the number guard.</b> Struck out: 5%, 617.51." in block
    assert f'<div class="gl-moment-template">{html.escape(template)}</div>' in block
    assert "No model is called." in block and "A recorded answer: no model is called." in block
    assert "gl-example" not in block


def test_every_figure_of_the_moment_is_in_the_recording_or_the_alert(home_file: Path) -> None:
    recording = _recording()
    case = find_case(recording.alert_id)
    assert case is not None
    allowed = " ".join(
        [
            recording.raw_answer,
            _verdict_of_the_recording().text,
            f"{recording.model_name} {recording.date}",
            *case.alert.source_refs,
            json.dumps(case.alert.data, default=str),
        ]
    )
    [block] = _starting(_home(), '<div class="gl-moment">')

    figures = FIGURE.findall(_text(block))
    assert len(figures) >= 4
    assert [f for f in figures if f not in allowed] == []


def test_the_page_style_block_carries_the_moment_and_the_reduced_motion_rule(
    home_file: Path,
) -> None:
    [style] = [v for v in _markdown(_home()) if v.lstrip().startswith("<style>")]

    assert theme.MOMENT_CSS.strip("\n") in style
    assert "@media (prefers-reduced-motion: reduce)" in style
    assert style.count("<style") == 1


def test_home_without_the_example_file_has_no_moment_and_still_renders() -> None:
    assert home_tiles.home_moment() is None  # the root conftest points the example nowhere
    at = _home()

    assert not _starting(at, '<div class="gl-moment">')
    assert len(_starting(at, '<div class="gl-grid gl-tiles">')) == 1
    assert len(_starting(at, '<div class="gl-grid gl-proof">')) == 1


def _write_example(tmp_path: Path, **changes: str) -> Path:
    """The committed Home example file with record P3 changed; written to tmp_path."""
    document = json.loads(HOME_FILE.read_text(encoding="utf-8"))
    for record in document["records"]:
        if record.get("id") == "P3":
            record.update(changes)
    path = tmp_path / "example.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "changes",
    [{"raw_answer": "The rows do not say."}, {"alert_id": "no-such-alert"}],
    ids=["guard-accepts", "alert-not-found"],
)
def test_no_moment_when_the_guard_does_not_reject_or_the_alert_is_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, changes: dict[str, str]
) -> None:
    monkeypatch.setattr(replay, "HOME_EXAMPLE_PATH", _write_example(tmp_path, **changes))

    assert home_tiles.home_moment() is None
    assert not _starting(_home(), '<div class="gl-moment">')


# --- the expander How it works (REQ-HD-20) -------------------------------------------------------


def _inside(at: AppTest) -> list[tuple[str, str]]:
    """The elements inside the How it works expander, in order, as (type, value)."""
    [expander] = [e for e in at.expander if e.label == streamlit_app.HOW_IT_WORKS]
    return [
        (child.type, str(getattr(child, "value", "")))
        for _index, child in sorted(expander.children.items())
    ]


def test_the_expander_is_closed_and_named_how_it_works() -> None:
    source = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
    calls = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and ast.unparse(node.func).endswith("expander")
        and node.args
        and ast.unparse(node.args[0]) == "HOW_IT_WORKS"
    ]

    assert streamlit_app.HOW_IT_WORKS == "How it works"
    [call] = calls
    assert {kw.arg: ast.literal_eval(kw.value) for kw in call.keywords} == {"expanded": False}
    assert [e.label for e in _home().expander] == ["How it works"]


def test_the_expander_holds_the_moved_blocks_in_order_with_their_words_unchanged() -> None:
    inside = _inside(_home())
    values = [value for _type, value in inside]
    link = next(
        i
        for i, (kind, value) in enumerate(inside)
        if kind == "page_link" or value == streamlit_app.START_HERE_FALLBACK
    )
    heading = next(
        i
        for i, value in enumerate(values)
        if value.startswith(SECTION_START) and "How a figure" in value
    )
    layers = textwrap.dedent(streamlit_app.LAYERS).strip()

    positions = [
        values.index(landing.story_html(streamlit_app.STORY)),
        link,
        heading,
        values.index(landing.diagram_html()),
        values.index(layers),
        values.index(streamlit_app.TRY_IT),
        values.index(streamlit_app.SYNTHETIC_NOTE),
        values.index(streamlit_app.INE_NOTE),
    ]
    assert positions == sorted(positions)
    assert len(set(positions)) == len(positions)


def test_nothing_of_the_moved_text_is_left_above_the_expander() -> None:
    at = _home()
    layers = textwrap.dedent(streamlit_app.LAYERS).strip()
    outside = [str(getattr(child, "value", "")) for child in at.main.children.values()]

    for moved in (streamlit_app.TRY_IT, streamlit_app.SYNTHETIC_NOTE, streamlit_app.INE_NOTE):
        assert moved not in outside
    assert layers not in outside
    assert not any(v.startswith('<div class="gl-story">') for v in outside)
    assert not any(v.startswith('<div class="gl-diagram">') for v in outside)
    attribution = streamlit_app.INE_ATTRIBUTION
    assert sum(attribution in caption.value for caption in at.caption) == 1


# --- one drawing per tile (REQ-HD-21, 22) --------------------------------------------------------


def test_pick_alert_takes_the_first_critical_else_the_first_in_page_order() -> None:
    info, warning_1, warning_2 = _alert("info", 1), _alert("warning", 2), _alert("warning", 3)
    critical_1, critical_2 = _alert("critical", 4), _alert("critical", 5)

    assert home_tiles.pick_alert([info, warning_1, critical_1, critical_2]) == critical_1
    assert home_tiles.pick_alert([info, warning_1, warning_2]) == warning_1
    assert home_tiles.pick_alert([info]) == info
    assert home_tiles.pick_alert([]) is None


def test_the_picked_alert_is_the_first_one_each_page_lists() -> None:
    zombie, vampire, phantom = _zombie(), _vampire(), _phantom()
    zombie_groups = home_tiles.zs_settings.group_alerts_by_severity(zombie.alerts)
    vampire_groups = home_tiles.vf_settings.group_alerts_by_severity(vampire.alerts)
    phantom_listed = home_tiles.pi_settings.ordered_alerts(
        alert for result in phantom.results for alert in result.alerts
    )
    zombie_listed = [alert for group in zombie_groups.values() for alert in group]
    vampire_listed = [alert for group in vampire_groups.values() for alert in group]

    assert home_tiles.pick_alert(zombie.alerts) == zombie_listed[0]
    assert home_tiles.pick_alert(vampire.alerts) == vampire_listed[0]
    assert home_tiles.pick_alert(phantom_listed) == phantom_listed[0]


def test_a_tile_without_a_drawing_is_the_tile_of_before() -> None:
    tile = landing.TILES[0]

    assert tile_html(tile) == tile_html(tile, "")
    assert tiles_html() == tiles_html(drawings={}) == tiles_html(drawings=None)
    assert "gl-signature" not in tiles_html()


def test_a_drawing_sits_between_the_purpose_and_the_numbers_of_its_own_tile() -> None:
    drawing = '<div class="gl-signature">x</div>'
    markup = tiles_html(drawings={"phantom": drawing})
    tiles = markup.split(TILE_START)[1:]

    assert fromstring(markup).attrib["class"] == "gl-grid gl-tiles"
    assert [drawing in tile for tile in tiles] == [False, True, False]
    phantom = tiles[1]
    assert phantom.index("gl-note") < phantom.index(drawing) < phantom.index("gl-stats")
    for tile in landing.TILES:  # title, colour class and one line stay
        assert f"gl-tile-{tile.accent.key}" in markup and tile.purpose in markup


def _expected_drawings() -> dict[str, tuple[str, Alert]]:
    """The drawing each page would make for the alert its tile must pick, by the pages' calls."""
    zombie = _zombie()
    zombie_alert = home_tiles.pick_alert(zombie.alerts)
    assert zombie_alert is not None
    cited, _missing = rows_for_refs(zombie.debit_ledger, zombie_alert.source_refs)
    heartbeat = heartbeat_svg(
        cited, zombie_alert.data.get("cancellation_date"), width=signatures.TILE_WIDTH
    )

    vampire = _vampire()
    vampire_alert = home_tiles.pick_alert(vampire.alerts)
    assert vampire_alert is not None
    cited, _missing = rows_for_refs(vampire.ledger, vampire_alert.source_refs)
    bites = bites_svg(cited)

    phantom = _phantom()
    settings = home_tiles.pi_settings
    phantom_alert = home_tiles.pick_alert(
        settings.ordered_alerts(alert for result in phantom.results for alert in result.alerts)
    )
    assert phantom_alert is not None
    # The Phantom tile is specified to show the tile variant: the source ref plus the first two
    # lantern columns, with only the free-text columns allowed to wrap.
    view = settings.lantern_view(phantom_alert, phantom)
    columns = home_tiles.tile_lantern_columns(phantom_alert, view)
    lantern = lantern_html(
        view[columns],
        settings.lantern_lit_columns(phantom_alert),
        text_columns=[c for c in columns if c in home_tiles.TILE_TEXT_COLUMNS],
    )
    return {
        "zombie": (signature_block(heartbeat, ZOMBIE_CAPTION), zombie_alert),
        "phantom": (signature_block(lantern, PHANTOM_CAPTION), phantom_alert),
        "vampire": (signature_block(bites, VAMPIRE_CAPTION), vampire_alert),
    }


def _with_chips(drawing: str, alert: Alert) -> str:
    """The drawing, then at most three chips and one computed line for the rest of the refs."""
    refs = alert.source_refs
    more = len(refs) - 3
    rest = ""
    if more > 0:
        noun = "row" if more == 1 else "rows"
        rest = f'<div class="gl-tile-more">and {more} more cited {noun}</div>'
    return f'{drawing}<div class="gl-tile-refs">{refs_chips_html(refs[:3])}{rest}</div>'


def test_each_tile_has_the_drawing_its_app_makes_for_one_real_alert() -> None:
    drawings = home_tiles.tile_signatures()

    assert set(drawings) == {"zombie", "phantom", "vampire"}
    for key, (drawing, alert) in _expected_drawings().items():
        assert drawing, key
        assert drawings[key] == _with_chips(drawing, alert)
    assert "gl-heartbeat" in drawings["zombie"] and "gl-tomb" in drawings["zombie"]
    assert "gl-lantern" in drawings["phantom"] and "gl-lit" in drawings["phantom"]
    assert "gl-bites" in drawings["vampire"] and "gl-fang" in drawings["vampire"]


def test_the_tiles_of_the_demos_with_a_critical_alert_draw_a_critical_one() -> None:
    expected = _expected_drawings()

    assert expected["zombie"][1].severity == "critical"
    assert expected["phantom"][1].severity == "critical"


def test_home_puts_each_drawing_in_its_own_tile() -> None:
    [markup] = _starting(_home(), '<div class="gl-grid gl-tiles">')
    pieces = markup.split(TILE_START)[1:]
    tiles = dict(zip(("zombie", "phantom", "vampire"), pieces, strict=True))

    for key, (drawing, alert) in _expected_drawings().items():
        assert tiles[key].startswith(f"gl-tile-{key}")
        assert _with_chips(drawing, alert) in tiles[key]
    assert "gl-heartbeat" in tiles["zombie"] and "gl-heartbeat" not in tiles["vampire"]
    assert "gl-bites" in tiles["vampire"] and "gl-bites" not in tiles["phantom"]
    assert "gl-lantern" in tiles["phantom"] and "gl-lantern" not in tiles["zombie"]
    for tile in landing.TILES:  # the title, the line and the demo numbers are kept
        assert tile.accent.title in markup and tile.purpose in markup
        assert all(figure in markup for figure, _label in tile.stats)


def test_a_drawing_that_cannot_be_built_leaves_that_tile_without_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken() -> str:
        raise RuntimeError("no drawing")

    home_tiles.tile_signatures.clear()
    monkeypatch.setattr(home_tiles, "_vampire_tile", broken)
    try:
        at = _home()
    finally:
        home_tiles.tile_signatures.clear()

    [markup] = _starting(at, '<div class="gl-grid gl-tiles">')
    assert "gl-bites" not in markup
    assert "gl-heartbeat" in markup and "gl-lantern" in markup


def test_the_tile_drawings_are_built_once_per_process(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    original = home_tiles.zs_settings.run_pipeline

    def counting(*args: Any, **kwargs: Any) -> Any:
        calls.append("zombie")
        return original(*args, **kwargs)

    home_tiles.tile_signatures.clear()
    monkeypatch.setattr(home_tiles.zs_settings, "run_pipeline", counting)
    try:
        at = _home()
        at.run()
        assert not at.exception
    finally:
        home_tiles.tile_signatures.clear()

    assert calls == ["zombie"]
