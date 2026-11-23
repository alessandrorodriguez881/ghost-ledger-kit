"""The fee comparison on the Vampire Fees page (public-fees PF6, REQ-PF-13 and REQ-PF-19 to 21).

The settings helpers are called directly; the page runs headless with ``AppTest``. Every snapshot
here is synthetic (built by vf_builders.py from tests/public_data/bde_builders.py) and written to
``tmp_path``; the config is patched to point at it, as test_zs_cpi_demo.py does for the CPI. One
test loads the committed snapshot to check that the alert counts and the recorded answers of
``data/live_runs/`` stay as they are without it (decision Q7); it pins no figure of it. Nothing
reads the clock or the network.
"""

import json
import re
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

import apps.vampire_fees.detectors  # noqa: F401  (registers the vf.* detectors)
from apps.vampire_fees import settings
from apps.vampire_fees.detectors.utils import PeerContext
from apps.vampire_fees.explain_support import PEER_SENTENCE
from apps.vampire_fees.settings import (
    PEER_UNAVAILABLE_INVALID,
    PEER_UNAVAILABLE_NOT_FOUND,
    default_peer_type,
    demo_inputs,
    explanation_cache_key,
    load_peers,
    load_vocabulary,
    peer_attribution_lines,
    peer_status,
    peer_type_label,
    peer_type_options,
    peer_unavailable_caption,
    run_pipeline,
)
from apps.vampire_fees.tests.vf_builders import (
    CARD_DESCRIPTION,
    CUSTODY_DESCRIPTION,
    MAINTENANCE_DESCRIPTION,
    cdi_cot_snapshot_dict,
    cno_cot_snapshot_dict,
    cno_only_snapshot_dict,
)
from ledger_kit import replay
from ledger_kit.detectors import _restore_registry, _snapshot_registry, registered_names
from ledger_kit.explainer import fill_fallback
from ledger_kit.models import Alert
from ledger_kit.public_data import DEFAULT_FEE_SNAPSHOT_PATH, FeeSnapshot
from ledger_kit.utils.money import format_amount

ROOT = Path(__file__).resolve().parents[3]
APP_PATH = str(ROOT / "apps" / "vampire_fees" / "app.py")
CONFIG_PATH = ROOT / "apps" / "vampire_fees" / "config.toml"
TIMEOUT_SECONDS = 60
VF_DETECTORS = {"vf.recurring_fee", "vf.fee_increase", "vf.overdraft_cost", "vf.fee_summary"}
DEMO_ALERTS = 6  # the six alerts of test_vf_demo_e2e.py
MAINTENANCE_CONCEPT = "Comisión ANUAL total (euros)"
CARD_CONCEPT = "Comisión mantenimiento. ANUAL total (euros)"
MAINTENANCE_COST = Decimal("78.00")  # yearly_cost of the demo maintenance fee
CARD_COST = Decimal("30.00")  # yearly_cost of the demo debit-card fee
MAINTENANCE_SOURCE_LINE = (
    "Comparison source: Banco de España, Comisiones de Cuentas de Pago, account type CNO "
    "(payroll or pension), service 101 (account maintenance), declared 2026-11-23; 3 accounts "
    "show an asterisk (no fee is charged or the service is not offered)."
)
SENTENCE_RE = re.compile(r"Of \d+ .*? and the highest [\d.,]+ EUR\.")
LESS_THAN = "charge less than this fee costs a year"
REAL_LOAD_CONFIG = settings.load_config
FIXTURE_MODEL_NAME = "testmodel:1b"


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Snapshot and restore the registry; no key, so explanations are the templates."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    assert VF_DETECTORS <= set(registered_names("vf"))
    snapshot = _snapshot_registry()
    try:
        yield
    finally:
        _restore_registry(snapshot)


# --- helpers ----------------------------------------------------------------------------------


def _write(tmp_path: Path, document: dict[str, Any], name: str = "fees.json") -> Path:
    """Write a synthetic snapshot to `tmp_path` and return its path."""
    path = tmp_path / name
    path.write_text(json.dumps(document, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path


def _point_config_at(monkeypatch: pytest.MonkeyPatch, path: Path | str) -> None:
    """Make every load_config call of the app report another [peer_fees] snapshot_path."""

    def patched(config_path: Path) -> dict:
        config = REAL_LOAD_CONFIG(config_path)
        config["peer_fees"] = {**config["peer_fees"], "snapshot_path": str(path)}
        return config

    monkeypatch.setattr(settings, "load_config", patched)


def _config(path: Path | str) -> dict[str, Any]:
    """The committed config with [peer_fees] snapshot_path pointing at `path`."""
    config = REAL_LOAD_CONFIG(CONFIG_PATH)
    config["peer_fees"] = {**config["peer_fees"], "snapshot_path": str(path)}
    return config


def _demo(fmt: str = "CSV") -> AppTest:
    """Run the app, choose the demo format and click Load demo data."""
    at = AppTest.from_file(APP_PATH, default_timeout=TIMEOUT_SECONDS).run()
    if fmt != "CSV":
        at.radio(key="vf_demo_format").set_value(fmt).run()
    at.button(key="vf_load_demo").click().run()
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
        is_title = isinstance(value, str) and value.startswith('<div class="vf-alert-title">')
        if kind == "markdown" and is_title:
            current = []
            cards.append(current)
        if current is None:
            continue
        if kind == "expander":
            current = None
        elif kind in ("markdown", "caption") and isinstance(value, str):
            current.append((kind, value))
    return cards


def _text(card: Card) -> str:
    """All the text of a card."""
    return "\n".join(value for _kind, value in card)


def _containing(card: Card, needle: str) -> list[str]:
    """The elements of a card that contain `needle`."""
    return [value for _kind, value in card if needle in value]


def _detector(card: Card) -> str:
    """The detector named by the caption of a card."""
    [caption] = [v for k, v in card if k == "caption" and v.startswith("Detector: ")]
    return caption.split("`")[1]


def _fee_card(at: AppTest, description: str) -> Card:
    """The single vf.recurring_fee card of the fee with this description."""
    found = [
        card
        for card in _cards(at)
        if _detector(card) == "vf.recurring_fee" and f"({description})" in _text(card)
    ]
    assert len(found) == 1, description
    return found[0]


def _severities(at: AppTest) -> list[str]:
    """The severity of every alert card, in page order."""
    captions = [element.value for element in at.caption]
    return [value.split("severity: ")[1] for value in captions if value.startswith("Detector: ")]


def _captions(at: AppTest) -> list[str]:
    """Every caption of the page."""
    return [c.value for c in at.caption]


def _everything(at: AppTest) -> str:
    """Every caption and markdown value of the page, joined."""
    return "\n".join([*_captions(at), *(m.value for m in at.markdown)])


def _badges(at: AppTest) -> list[str]:
    """The HTML of every guard badge."""
    return [m.value for m in at.markdown if m.value.startswith('<span class="vf-badge ')]


def _less_than(snapshot: FeeSnapshot, service: str, concept: str, cost: Decimal) -> str:
    """The comparison clause a card must show, computed from the snapshot with the reader."""
    found = snapshot.declarations("CNO", service, concept)
    assert found is not None
    lower = sum(1 for amount in found.amounts if amount < cost)
    return f"{lower} {LESS_THAN} ({format_amount(cost)})"


def _demo_alerts(peers: PeerContext | None, fmt: str = "csv") -> list[Alert]:
    """The alerts of the demo statement through the settings pipeline."""
    config = REAL_LOAD_CONFIG(CONFIG_PATH)
    demo = demo_inputs(config, ROOT, fmt)
    pipeline = run_pipeline(
        demo.statement_name,
        demo.statement_bytes,
        vocabulary=load_vocabulary(config),
        peers=peers,
    )
    return pipeline.alerts


# --- settings helpers (pure) ------------------------------------------------------------------


def test_type_options_follow_the_snapshot_in_the_fixed_order() -> None:
    """REQ-PF-20: CNO and COT shown as code and published label; initial CNO."""
    snapshot = FeeSnapshot.from_dict(cno_cot_snapshot_dict())

    assert peer_type_options(snapshot) == ("CNO", "COT")
    assert [peer_type_label(code) for code in peer_type_options(snapshot)] == [
        "CNO · Cuenta Nómina/Pensión",
        "COT · Otras Cuentas",
    ]
    assert default_peer_type(snapshot, "CNO") == "CNO"


def test_the_default_type_falls_back_to_the_first_present_type() -> None:
    """A snapshot with CDI and COT only starts at CDI; an absent default is never chosen."""
    cdi_cot = FeeSnapshot.from_dict(cdi_cot_snapshot_dict())
    cno_cot = FeeSnapshot.from_dict(cno_cot_snapshot_dict())

    assert peer_type_options(cdi_cot) == ("CDI", "COT")
    assert default_peer_type(cdi_cot, "CNO") == "CDI"
    assert default_peer_type(cno_cot, "CJO") == "CNO"
    assert default_peer_type(cno_cot, None) == "CNO"
    assert default_peer_type(cno_cot, "COT") == "COT"


def test_a_cno_only_snapshot_has_one_option() -> None:
    """The shape of the first real snapshot (DN-PF-32): one type, so no select box."""
    snapshot = FeeSnapshot.from_dict(cno_only_snapshot_dict())

    assert peer_type_options(snapshot) == ("CNO",)
    assert default_peer_type(snapshot, "CNO") == "CNO"


def test_peer_status_tells_ok_missing_and_invalid(tmp_path: Path) -> None:
    """'missing' only when there is no file; 'invalid' when it exists but fails."""
    good = _write(tmp_path, cno_only_snapshot_dict())
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    wrong = _write(tmp_path, {**cno_only_snapshot_dict(), "snapshot_format": 2}, "wrong.json")

    assert peer_status(_config(good), ROOT) == "ok"
    assert peer_status(_config(tmp_path / "missing.json"), ROOT) == "missing"
    assert peer_status(_config(broken), ROOT) == "invalid"
    assert peer_status(_config(wrong), ROOT) == "invalid"
    assert peer_status({}, ROOT) == "missing"
    assert peer_unavailable_caption("ok") is None
    assert peer_unavailable_caption("missing") == PEER_UNAVAILABLE_NOT_FOUND
    assert peer_unavailable_caption("invalid") == PEER_UNAVAILABLE_INVALID
    assert PEER_UNAVAILABLE_NOT_FOUND == "Fee comparison unavailable: snapshot not found."
    assert PEER_UNAVAILABLE_INVALID == "Fee comparison unavailable: snapshot invalid."


def test_load_peers_is_none_for_a_missing_or_an_invalid_file(tmp_path: Path) -> None:
    """No snapshot, no context: the detector then adds no peer field (DN-PF-19)."""
    broken = tmp_path / "broken.json"
    broken.write_text("[]", encoding="utf-8")

    assert load_peers(_config(tmp_path / "missing.json"), ROOT, "CNO") is None
    assert load_peers(_config(broken), ROOT, "CNO") is None


def test_load_peers_builds_the_context_of_the_config(tmp_path: Path) -> None:
    """The snapshot of the path, the type asked for and the two services of [peer_fees]."""
    path = _write(tmp_path, cno_cot_snapshot_dict())

    peers = load_peers(_config(path), ROOT, "COT")

    assert isinstance(peers, PeerContext)
    assert peers.account_type == "COT"
    assert peers.snapshot.account_types == ("CNO", "COT")
    assert [service.service_code for service in peers.services] == ["101", "401"]


def test_run_pipeline_without_peers_is_todays_run() -> None:
    """peers=None gives the same alerts, data and ids as a call without the argument."""
    config = REAL_LOAD_CONFIG(CONFIG_PATH)
    demo = demo_inputs(config, ROOT)
    vocabulary = load_vocabulary(config)

    before = run_pipeline(demo.statement_name, demo.statement_bytes, vocabulary=vocabulary)
    after = _demo_alerts(None)

    assert [(a.id, a.data) for a in after] == [(a.id, a.data) for a in before.alerts]
    assert not any(key.startswith("peer_") for a in after for key in a.data)


def test_run_pipeline_with_peers_adds_the_fields_and_keeps_every_id() -> None:
    """Decision Q7: the peer fields reach the two compared fees; no id changes."""
    snapshot = FeeSnapshot.from_dict(cno_only_snapshot_dict())
    peers = PeerContext(snapshot, "CNO", settings.peer_services_of(REAL_LOAD_CONFIG(CONFIG_PATH)))

    plain, compared = _demo_alerts(None), _demo_alerts(peers)

    assert [a.id for a in compared] == [a.id for a in plain]
    assert [(a.detector, a.severity, a.title, a.source_refs) for a in compared] == [
        (a.detector, a.severity, a.title, a.source_refs) for a in plain
    ]
    with_keys = {a.data["description"] for a in compared if "peer_median_yearly" in a.data}
    assert with_keys == {MAINTENANCE_DESCRIPTION, CARD_DESCRIPTION}
    for before, after in zip(plain, compared, strict=True):
        base = {k: v for k, v in after.data.items() if not k.startswith("peer_")}
        assert base == before.data


def test_the_explanation_cache_key_carries_the_peer_fields() -> None:
    """Same id, other comparison: another key. No peer field: (id, mode, ())."""
    data = {"counterparty": "BANCO FICTICIO", "yearly_cost": "78.00"}
    plain = Alert(
        detector="vf.recurring_fee",
        severity="info",
        title="t",
        source_refs=["s.csv:0"],
        data=data,
    )
    cno = plain.model_copy(update={"data": {**data, "peer_account_type": "CNO"}})
    cot = plain.model_copy(update={"data": {**data, "peer_account_type": "COT"}})
    cno_items = (("peer_account_type", "CNO"),)

    assert explanation_cache_key(plain, "real") == (plain.id, "real", ())
    assert explanation_cache_key(cno, "real") == (plain.id, "real", cno_items)
    assert explanation_cache_key(cno, "real") != explanation_cache_key(cot, "real")
    assert explanation_cache_key(cno, "real") != explanation_cache_key(cno, "replay")


# --- the demo with a synthetic CNO + COT snapshot ---------------------------------------------


@pytest.fixture
def cno_cot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FeeSnapshot:
    """Point the app at a synthetic snapshot with CNO (S12, S10) and COT (8 amounts for 101)."""
    document = cno_cot_snapshot_dict()
    _point_config_at(monkeypatch, _write(tmp_path, document))
    return FeeSnapshot.from_dict(document)


def test_alert_counts_are_the_same_with_and_without_the_snapshot(
    cno_cot: FeeSnapshot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """REQ-PF-13: the comparison is context; the six alerts keep their severities."""
    with_snapshot = _demo()
    _point_config_at(monkeypatch, tmp_path / "missing.json")
    without = _demo()

    assert _severities(with_snapshot) == _severities(without)
    assert len(_cards(with_snapshot)) == len(_cards(without)) == DEMO_ALERTS
    assert [m.value for m in with_snapshot.metric] == [m.value for m in without.metric]


def test_the_maintenance_card_shows_the_sentence_once_and_its_source_line(
    cno_cot: FeeSnapshot,
) -> None:
    """The fallback text holds the sentence, so the card adds nothing; the source line follows."""
    expected = _less_than(cno_cot, "101", MAINTENANCE_CONCEPT, MAINTENANCE_COST)
    assert expected == f"9 {LESS_THAN} (78,00 EUR)"

    card = _fee_card(_demo(), MAINTENANCE_DESCRIPTION)

    assert len(_containing(card, expected)) == 1
    assert _containing(card, "Comparison source:") == [MAINTENANCE_SOURCE_LINE]


def test_the_debit_card_card_shows_its_own_comparison(cno_cot: FeeSnapshot) -> None:
    """Service 401 with S10: eight declared fees are lower than 30,00 EUR a year."""
    expected = _less_than(cno_cot, "401", CARD_CONCEPT, CARD_COST)
    assert expected == f"8 {LESS_THAN} (30,00 EUR)"

    card = _fee_card(_demo(), CARD_DESCRIPTION)

    assert len(_containing(card, expected)) == 1
    [line] = _containing(card, "Comparison source:")
    assert "account type CNO (payroll or pension), service 401 (debit card maintenance)" in line


def test_the_custody_card_and_the_other_detectors_never_mention_the_bank_of_spain(
    cno_cot: FeeSnapshot,
) -> None:
    """Only the two compared fees carry a comparison (REQ-PF-21)."""
    at = _demo()

    custody = _fee_card(at, CUSTODY_DESCRIPTION)
    assert LESS_THAN not in _text(custody)
    assert "Comparison source" not in _text(custody)
    others = [card for card in _cards(at) if _detector(card) != "vf.recurring_fee"]
    assert len(others) == 3
    for card in [*others, custody]:
        assert "Banco de España" not in _text(card)


def test_the_footer_holds_the_attribution_once(cno_cot: FeeSnapshot) -> None:
    """REQ-PF-19: attribution, licence line, licence note and non-endorsement, once each."""
    at = _demo()
    captions = _captions(at)

    lines = peer_attribution_lines(cno_cot)
    assert len(lines) == 4
    for line in lines:
        assert captions.count(line) == 1, line
    assert lines[1] == (
        "Licence: see the Banco de España legal notice · retrieved 2026-11-23 · "
        "declarations of 2026-11-23"
    )
    assert _everything(at).count(cno_cot.attribution) == 1
    assert _everything(at).count(cno_cot.no_endorsement) == 1
    assert PEER_UNAVAILABLE_NOT_FOUND not in captions


def test_the_select_box_lists_the_types_and_starts_at_cno(cno_cot: FeeSnapshot) -> None:
    """REQ-PF-20: two types in the snapshot, so the select box is drawn in the sidebar."""
    at = _demo()

    box = at.selectbox(key="vf_peer_type")
    assert box.label == "Compare my fees with"
    assert list(box.options) == ["CNO · Cuenta Nómina/Pensión", "COT · Otras Cuentas"]
    assert box.value == "CNO"


def test_selecting_cot_drops_the_comparison_and_shows_no_cached_cno_text(
    cno_cot: FeeSnapshot,
) -> None:
    """COT has eight amounts for 101 (fewer than PEER_MIN_ACCOUNTS): no peer keys any more."""
    at = _demo()
    assert _containing(_fee_card(at, MAINTENANCE_DESCRIPTION), LESS_THAN)

    at.selectbox(key="vf_peer_type").set_value("COT").run()

    assert not at.exception
    for description in (MAINTENANCE_DESCRIPTION, CARD_DESCRIPTION):
        card = _fee_card(at, description)
        assert LESS_THAN not in _text(card)
        assert "Comparison source" not in _text(card)
        assert "Banco de España" not in _text(card)
    assert at.selectbox(key="vf_peer_type").value == "COT"
    assert "COT · Otras Cuentas" in list(at.selectbox(key="vf_peer_type").options)
    assert len(_cards(at)) == DEMO_ALERTS


def test_the_hallucinating_stub_is_rejected_and_the_card_keeps_the_sentence(
    cno_cot: FeeSnapshot,
) -> None:
    """The stub's figure is rejected; the template shown holds the comparison once."""
    at = _demo()

    at.toggle(key="vf_hallucinate").set_value(True).run()

    assert not at.exception
    badges = _badges(at)
    assert len(badges) == DEMO_ALERTS
    assert all("vf-badge-rejected" in b and "99999.99" in b for b in badges)
    card = _fee_card(at, MAINTENANCE_DESCRIPTION)
    assert len(_containing(card, f"9 {LESS_THAN} (78,00 EUR)")) == 1
    assert len(_containing(card, "Comparison source:")) == 1


def test_a_recorded_recurring_fee_answer_is_replayed_with_the_snapshot_loaded(
    cno_cot: FeeSnapshot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Decision Q7: the id leaves out the peer fields, so the recording is still found.

    The recorded text lacks the comparison, so the card adds the sentence as a caption, once.
    """
    [maintenance] = [
        a
        for a in _demo_alerts(None)
        if a.detector == "vf.recurring_fee" and a.data["description"] == MAINTENANCE_DESCRIPTION
    ]
    text = f"This alert points to {maintenance.source_refs[0]}."
    run = {
        "date": "2026-11-11",
        "model": f"{FIXTURE_MODEL_NAME} (synthetic test run)",
        "records": [
            {
                "id": "vf-card",
                "kind": "card",
                "alert_id": maintenance.id,
                "question_id": None,
                "question": None,
                "raw_answer": text,
                "observed_source": "llm",
                "observed_rejected": [],
            }
        ],
    }
    run_path = tmp_path / "run.json"
    run_path.write_text(json.dumps(run), encoding="utf-8")
    monkeypatch.setattr(replay, "REPLAY_RUN_PATH", run_path)

    at = _demo()

    replayed = [b for b in _badges(at) if f"Recorded answer of {FIXTURE_MODEL_NAME}" in b]
    assert len(replayed) == 1 and "vf-badge-llm" in replayed[0]
    [card] = [c for c in _cards(at) if text in _text(c)]
    assert _detector(card) == "vf.recurring_fee"
    peers = PeerContext(cno_cot, "CNO", settings.peer_services_of(REAL_LOAD_CONFIG(CONFIG_PATH)))
    [compared] = [a for a in _demo_alerts(peers) if a.id == maintenance.id]
    sentence = fill_fallback(PEER_SENTENCE, compared)
    assert _containing(card, sentence) == [sentence]
    assert len(_containing(card, LESS_THAN)) == 1
    assert _containing(card, "Comparison source:") == [MAINTENANCE_SOURCE_LINE]


def test_the_norma43_demo_gives_the_same_peer_lines_as_the_csv_demo(
    cno_cot: FeeSnapshot,
) -> None:
    """The dates come from the rows, identical in both formats (REQ-PF-21)."""
    csv_run, n43_run = _demo("CSV"), _demo("Norma 43")

    def peer_lines(at: AppTest) -> list[str]:
        """The source lines and the comparison sentences of every card."""
        found: list[str] = []
        for card in _cards(at):
            found += _containing(card, "Comparison source:")
            found += [m.group(0) for m in SENTENCE_RE.finditer(_text(card))]
        return found

    assert len(peer_lines(csv_run)) == 4  # two cards, each a sentence and a source line
    assert peer_lines(n43_run) == peer_lines(csv_run)
    assert _severities(n43_run) == _severities(csv_run)


# --- one account type only (the shape of the first real snapshot) ------------------------------


def test_a_cno_only_snapshot_draws_no_select_box_and_names_the_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DN-PF-32: with one type there is nothing to choose; the source line names CNO."""
    _point_config_at(monkeypatch, _write(tmp_path, cno_only_snapshot_dict()))

    at = _demo()

    assert not [box for box in at.selectbox if box.key == "vf_peer_type"]
    card = _fee_card(at, MAINTENANCE_DESCRIPTION)
    assert len(_containing(card, f"9 {LESS_THAN} (78,00 EUR)")) == 1
    [line] = _containing(card, "Comparison source:")
    assert "account type CNO (payroll or pension)" in line
    assert at.session_state["vf_peer_type"] == "CNO"


# --- the snapshot is not available ------------------------------------------------------------


def test_a_missing_snapshot_shows_the_caption_and_todays_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No file: the caption once, no footer, no select box, no comparison; six alerts."""
    _point_config_at(monkeypatch, tmp_path / "missing.json")

    at = _demo()

    assert _captions(at).count(PEER_UNAVAILABLE_NOT_FOUND) == 1
    assert not [box for box in at.selectbox if box.key == "vf_peer_type"]
    everything = _everything(at)
    assert "Elaboración propia" not in everything
    assert "comparador de comisiones" not in everything
    assert "Comparison source" not in everything
    assert LESS_THAN not in everything
    assert len(_cards(at)) == DEMO_ALERTS
    assert _severities(at) == ["critical", "warning", "warning", "warning", "info", "info"]


def test_an_invalid_snapshot_shows_the_invalid_caption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A file that fails validation does not take the page down and is not 'not found'."""
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    _point_config_at(monkeypatch, broken)

    at = _demo()

    assert _captions(at).count(PEER_UNAVAILABLE_INVALID) == 1
    assert PEER_UNAVAILABLE_NOT_FOUND not in _captions(at)
    assert LESS_THAN not in _everything(at)
    assert len(_cards(at)) == DEMO_ALERTS


# --- the committed snapshot (decision Q7) -----------------------------------------------------


def _recorded_badges(at: AppTest, model_name: str) -> int:
    """How many guard badges say that a recorded answer of `model_name` was replayed."""
    return sum(f"Recorded answer of {model_name}" in badge for badge in _badges(at))


def test_the_committed_snapshot_keeps_the_counts_and_the_recorded_answers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With the committed snapshot: same alerts and ids, and data/live_runs/ is still replayed.

    No figure of the committed snapshot is pinned; the counts come from the run without it.
    """
    assert DEFAULT_FEE_SNAPSHOT_PATH.is_file()
    config = REAL_LOAD_CONFIG(CONFIG_PATH)
    peers = load_peers(config, ROOT, "CNO")
    assert peers is not None and "CNO" in peers.snapshot.account_types
    plain, compared = _demo_alerts(None), _demo_alerts(peers)
    assert [a.id for a in compared] == [a.id for a in plain]

    run = replay.load_run(replay.DEFAULT_REPLAY_RUN_PATH)
    assert run is not None
    recorded = [a for a in compared if run.card(a.id) is not None]
    assert any(a.detector == "vf.recurring_fee" for a in recorded)
    monkeypatch.setattr(replay, "REPLAY_RUN_PATH", replay.DEFAULT_REPLAY_RUN_PATH)

    with_snapshot = _demo()
    _point_config_at(monkeypatch, tmp_path / "missing.json")
    without = _demo()

    assert _severities(with_snapshot) == _severities(without)
    assert len(_cards(with_snapshot)) == len(_cards(without)) == DEMO_ALERTS
    assert _recorded_badges(with_snapshot, run.model_name) == len(recorded)
    assert _recorded_badges(without, run.model_name) == len(recorded)
