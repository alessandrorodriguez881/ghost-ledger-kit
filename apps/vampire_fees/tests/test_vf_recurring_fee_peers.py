"""Peer context of vf.recurring_fee (public-fees PF4: REQ-PF-11 to REQ-PF-14, REQ-PF-17, REQ-PF-22).

Every snapshot here is synthetic (built with tests/public_data/bde_builders.py), never a Banco de
España figure; nothing reads the committed snapshot. The existing test_vf_recurring_fee.py is not
edited: it keeps proving the behaviour without peers.
"""

import statistics
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from types import MappingProxyType
from typing import Any

import pandas as pd
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from apps.vampire_fees.detectors.recurring_fee import detect_recurring_fees
from apps.vampire_fees.detectors.utils import (
    PEER_MAX_DATE_GAP_DAYS,
    PEER_MIN_ACCOUNTS,
    PeerContext,
    classify_fee,
    peer_context_fields,
)
from apps.vampire_fees.tests.vf_builders import (
    CARD_DESCRIPTION,
    CUSTODY_DESCRIPTION,
    MAINTENANCE_DESCRIPTION,
    S10_AMOUNTS,
    S12_AMOUNTS,
    default_vocabulary,
    demo_card_ledger,
    demo_fee_ledger,
    demo_maintenance_ledger,
    demo_maintenance_rows,
    make_ledger,
    peer_context,
    peer_series_ledger_strategy,
    peer_services,
    peer_snapshot_dict_strategy,
    s10_snapshot_dict,
    s12_snapshot_dict,
    snapshot_dict_of,
)
from ledger_kit.detectors import loaded_source_refs
from ledger_kit.models import Alert
from ledger_kit.public_data import FeeSnapshot

VOCABULARY = default_vocabulary()
PROP = settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
ABSENT = object()

BASE_KEYS = (
    "counterparty",
    "description",
    "interval_type",
    "charge_count",
    "current_amount",
    "yearly_cost",
    "first_charge_date",
    "last_charge_date",
)
PEER_KEYS = (
    "peer_source",
    "peer_account_type",
    "peer_account_type_label",
    "peer_service",
    "peer_service_label",
    "peer_concept",
    "peer_declaration_date",
    "peer_account_count",
    "peer_not_offered_count",
    "peer_lower_count",
    "peer_zero_count",
    "peer_median_yearly",
    "peer_max_yearly",
)
MAINTENANCE_CONCEPT = "Comisión ANUAL total (euros)"
CARD_CONCEPT = "Comisión mantenimiento. ANUAL total (euros)"
# What each described fee is compared with: (service code, concept, label of config.toml).
COMPARED = {
    MAINTENANCE_DESCRIPTION: ("101", MAINTENANCE_CONCEPT, "account maintenance"),
    CARD_DESCRIPTION: ("401", CARD_CONCEPT, "debit card maintenance"),
}
s12 = s12_snapshot_dict
s10 = s10_snapshot_dict


def run(ledger: pd.DataFrame, peers: object = ABSENT) -> list[Alert]:
    """Run the detector; `peers` ABSENT leaves the key out of the context."""
    context: dict[str, Any] = {"vocabulary": VOCABULARY}
    if peers is not ABSENT:
        context["peers"] = peers
    return detect_recurring_fees(ledger, MappingProxyType(context))


def alert_of(alerts: list[Alert], description: str) -> Alert:
    """Return the one alert of the fee series with this description."""
    found = [a for a in alerts if a.data["description"] == description]
    assert len(found) == 1, description
    return found[0]


def peer_part(alert: Alert) -> dict[str, Any]:
    """Return the peer keys of an alert's data."""
    return {k: v for k, v in alert.data.items() if k.startswith("peer_")}


def base_part(alert: Alert) -> dict[str, Any]:
    """Return the data of an alert without its peer keys."""
    return {k: v for k, v in alert.data.items() if not k.startswith("peer_")}


def signature(alerts: list[Alert]) -> list[tuple[Any, ...]]:
    """Return (detector, severity, title, source_refs, id) of every alert, in order."""
    return [(a.detector, a.severity, a.title, tuple(a.source_refs), a.id) for a in alerts]


def maintenance_alert(peers: object) -> Alert:
    """Return the demo maintenance alert with the given peers context."""
    return alert_of(run(demo_maintenance_ledger(), peers), MAINTENANCE_DESCRIPTION)


# The exact dict of REQ-PF-12 for the demo maintenance series and S12.
EXPECTED_MAINTENANCE_DATA: dict[str, Any] = {
    "counterparty": "BANCO FICTICIO",
    "description": "Comisión mantenimiento cuenta",
    "interval_type": "monthly",
    "charge_count": 22,
    "current_amount": "6.50",
    "yearly_cost": "78.00",
    "first_charge_date": "2025-01-05",
    "last_charge_date": "2026-10-05",
    "peer_source": "Banco de España, Comisiones de Cuentas de Pago",
    "peer_account_type": "CNO",
    "peer_account_type_label": "payroll or pension",
    "peer_service": "101",
    "peer_service_label": "account maintenance",
    "peer_concept": "Comisión ANUAL total (euros)",
    "peer_declaration_date": "2026-11-23",
    "peer_account_count": 12,
    "peer_not_offered_count": 3,
    "peer_lower_count": 9,
    "peer_zero_count": 5,
    "peer_median_yearly": "18.00",
    "peer_max_yearly": "240.00",
}


# --- The constants (Finance Rule 7) ------------------------------------------------------------


def test_the_two_limits_are_named_constants() -> None:
    """REQ-PF-14: ten accounts with an amount, 365 days."""
    assert PEER_MIN_ACCOUNTS == 10
    assert PEER_MAX_DATE_GAP_DAYS == 365


# --- Tier 1 ------------------------------------------------------------------------------------


def test_maintenance_fee_with_s12_gets_the_dict_of_req_pf_12() -> None:
    """The exact data dict, keys in the order of the spec."""
    alert = maintenance_alert(peer_context(s12()))
    assert alert.data == EXPECTED_MAINTENANCE_DATA
    assert list(alert.data) == [*BASE_KEYS, *PEER_KEYS]
    assert alert.severity == "warning"
    assert len(alert.source_refs) == 22


def test_card_fee_with_s10_gets_its_peer_fields() -> None:
    """S10 and the yearly card fee: 8 of 10 charge less, median 6.00, highest 45.00."""
    alert = alert_of(run(demo_fee_ledger(), peer_context(s10())), CARD_DESCRIPTION)
    assert alert.data["yearly_cost"] == "30.00"
    assert alert.data["last_charge_date"] == "2026-02-16"
    assert peer_part(alert) == {
        "peer_source": "Banco de España, Comisiones de Cuentas de Pago",
        "peer_account_type": "CNO",
        "peer_account_type_label": "payroll or pension",
        "peer_service": "401",
        "peer_service_label": "debit card maintenance",
        "peer_concept": CARD_CONCEPT,
        "peer_declaration_date": "2026-11-23",
        "peer_account_count": 10,
        "peer_not_offered_count": 0,
        "peer_lower_count": 8,
        "peer_zero_count": 5,
        "peer_median_yearly": "6.00",
        "peer_max_yearly": "45.00",
    }
    assert list(peer_part(alert)) == list(PEER_KEYS)


def test_the_same_ledger_without_peers_has_the_eight_keys() -> None:
    """No `peers` key in the context, or None: today's eight-key dict."""
    for peers in (ABSENT, None):
        alert = maintenance_alert(peers)
        assert list(alert.data) == list(BASE_KEYS)
        assert alert.data == {k: EXPECTED_MAINTENANCE_DATA[k] for k in BASE_KEYS}


def test_a_peer_context_whose_services_do_not_match_adds_nothing() -> None:
    """The custody fee has no service: no peer key, with S12 or with S10."""
    ledger = demo_fee_ledger()
    for snapshot in (s12(), s10()):
        alert = alert_of(run(ledger, peer_context(snapshot)), CUSTODY_DESCRIPTION)
        assert peer_part(alert) == {}
        assert list(alert.data) == list(BASE_KEYS)


def test_a_fee_the_snapshot_cannot_answer_has_no_peer_keys() -> None:
    """S12 has service 101 only: the card fee gets nothing, the maintenance fee gets its fields."""
    alerts = run(demo_fee_ledger(), peer_context(s12()))
    assert peer_part(alert_of(alerts, CARD_DESCRIPTION)) == {}
    assert set(peer_part(alert_of(alerts, MAINTENANCE_DESCRIPTION))) == set(PEER_KEYS)


def test_peer_fields_are_added_once_the_alert_is_decided() -> None:
    """The peer fields follow the eight keys; severity, title and refs are the detector's own."""
    alert = maintenance_alert(peer_context(s12()))
    assert alert.title == "Recurring monthly fee: BANCO FICTICIO · Comisión mantenimiento cuenta"
    assert alert.detector == "vf.recurring_fee"
    assert alert.source_refs == [f"s.csv:{i}" for i in range(22)]


# --- Tier 2: every REQ-PF-14 case ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("count", "expected"), [(PEER_MIN_ACCOUNTS, True), (PEER_MIN_ACCOUNTS - 1, False)]
)
def test_ten_amounts_are_enough_nine_are_not(count: int, expected: bool) -> None:
    """The boundary of PEER_MIN_ACCOUNTS (the accounts WITH an amount)."""
    snapshot = snapshot_dict_of([f"{10 * i}.00" for i in range(count)])
    alert = maintenance_alert(peer_context(snapshot))
    assert bool(peer_part(alert)) is expected


def test_accounts_without_the_service_do_not_make_the_sample_bigger() -> None:
    """Nine amounts and five asterisks are still nine amounts: no comparison."""
    snapshot = snapshot_dict_of([f"{10 * i}.00" for i in range(9)], maintenance_asterisks=5)
    assert peer_part(maintenance_alert(peer_context(snapshot))) == {}


@pytest.mark.parametrize(
    ("declaration_date", "expected"),
    [
        ("2027-02-16", True),  # 365 days after the last charge (2026-02-16)
        ("2027-02-17", False),  # 366
        ("2025-02-16", True),  # 365 days before it
        ("2025-02-15", False),  # 366 days before it
        ("2026-11-23", True),  # 280
        ("2027-03-01", False),  # 378
    ],
)
def test_the_date_gap_boundary_in_both_directions(declaration_date: str, expected: bool) -> None:
    """Whole days between the last charge and the declaration date, either way round."""
    snapshot = snapshot_dict_of(card=S10_AMOUNTS, declaration_date=declaration_date)
    alert = alert_of(run(demo_card_ledger(), peer_context(snapshot)), CARD_DESCRIPTION)
    assert bool(peer_part(alert)) is expected


def test_a_stale_card_fee_has_none_while_the_maintenance_fee_still_has_them() -> None:
    """Declaration date 2027-03-01: card gap 378, maintenance gap 147."""
    snapshot = snapshot_dict_of(S12_AMOUNTS, S10_AMOUNTS, declaration_date="2027-03-01")
    alerts = run(demo_fee_ledger(), peer_context(snapshot))
    assert peer_part(alert_of(alerts, CARD_DESCRIPTION)) == {}
    assert set(peer_part(alert_of(alerts, MAINTENANCE_DESCRIPTION))) == set(PEER_KEYS)


def test_an_account_type_the_snapshot_does_not_hold_gives_none() -> None:
    """CDI with a snapshot that holds CNO only."""
    assert peer_part(maintenance_alert(peer_context(s12(), account_type="CDI"))) == {}


def test_a_peer_context_with_no_services_gives_none() -> None:
    """An empty `services` tuple: nothing is matched."""
    context = PeerContext(FeeSnapshot.from_dict(s12()), "CNO", ())
    assert peer_part(maintenance_alert(context)) == {}


def test_peers_that_is_a_plain_dict_or_none_gives_none() -> None:
    """Only a PeerContext counts."""
    plain = {"snapshot": FeeSnapshot.from_dict(s12()), "account_type": "CNO", "services": ()}
    for peers in (plain, None, "CNO", 3):
        assert peer_part(maintenance_alert(peers)) == {}


def test_a_snapshot_where_every_account_is_an_asterisk_gives_none() -> None:
    """No amount at all: len(amounts) == 0, no comparison (and no median of nothing)."""
    snapshot = snapshot_dict_of(maintenance_asterisks=12)
    found = FeeSnapshot.from_dict(snapshot).declarations("CNO", "101", MAINTENANCE_CONCEPT)
    assert found is not None and len(found.amounts) == 0 and found.not_offered_count == 12
    assert peer_part(maintenance_alert(peer_context(snapshot))) == {}


def test_a_yearly_cost_equal_to_an_amount_is_not_counted_as_lower() -> None:
    """78.00 equals the 78.00 account: 9 lower. 78.12 counts it (10); 77.88 does not (9)."""
    for monthly, lower in (("6.50", 9), ("6.51", 10), ("6.49", 9)):
        rows = demo_maintenance_rows()
        for row in rows:
            row["amount"] = Decimal(monthly)
        alert = alert_of(run(make_ledger(rows), peer_context(s12())), MAINTENANCE_DESCRIPTION)
        assert alert.data["peer_lower_count"] == lower, monthly


def test_an_amount_of_zero_is_counted_as_lower_and_as_zero() -> None:
    """A declared 0.00 is a declared amount: it is in both counts; the asterisks are in neither."""
    data = peer_part(maintenance_alert(peer_context(s12())))
    assert data["peer_zero_count"] == 5
    assert data["peer_lower_count"] >= data["peer_zero_count"]
    assert data["peer_account_count"] == 12  # the three asterisks are not counted
    assert data["peer_not_offered_count"] == 3


def test_empty_and_single_row_ledgers_with_peers_give_a_list(
    empty_ledger: pd.DataFrame, single_row_ledger: pd.DataFrame
) -> None:
    """Never raises; an empty list."""
    peers = peer_context(s12())
    assert run(empty_ledger, peers) == []
    assert run(single_row_ledger, peers) == []
    assert run(pd.DataFrame(), peers) == []


def test_a_duplicate_source_ref_is_handled_with_peers() -> None:
    """Two rows with one source_ref count once; the alert is the same with and without peers."""
    rows = demo_maintenance_rows()
    rows[21]["source_ref"] = rows[20]["source_ref"]
    ledger = make_ledger(rows)
    with_peers = run(ledger, peer_context(s12()))
    without = run(ledger)
    assert len(with_peers) == len(without) == 1
    assert with_peers[0].data["charge_count"] == 21
    assert signature(with_peers) == signature(without)


def test_severity_title_source_refs_and_id_are_the_same_with_and_without_peers() -> None:
    """REQ-PF-13 and decision Q7: the id leaves out the peer_ keys."""
    ledger = demo_fee_ledger()
    peers = peer_context(snapshot_dict_of(S12_AMOUNTS, S10_AMOUNTS, maintenance_asterisks=3))
    with_peers, without = run(ledger, peers), run(ledger)
    assert signature(with_peers) == signature(without)
    assert [base_part(a) for a in with_peers] == [a.data for a in without]
    assert any(peer_part(a) for a in with_peers)
    assert all(len(a.id) == 64 for a in with_peers)


def test_peer_fields_never_cite_a_public_row() -> None:
    """REQ-PF-17: source_refs are the rows of the series, no pseudo reference to the BdE."""
    alert = maintenance_alert(peer_context(s12()))
    assert all(ref.startswith("s.csv:") for ref in alert.source_refs)
    assert not any("bde" in ref.lower() for ref in alert.source_refs)
    ledger = demo_maintenance_ledger()
    context = MappingProxyType({"vocabulary": VOCABULARY, "peers": peer_context(s12())})
    assert set(alert.source_refs) <= loaded_source_refs(ledger, context)
    assert loaded_source_refs(ledger, context) == loaded_source_refs(
        ledger, MappingProxyType({"vocabulary": VOCABULARY})
    )


# --- peer_context_fields itself -------------------------------------------------------------------


def _last_fee(ledger: pd.DataFrame):
    """Return the Fee of the last row of a ledger (classified by the default vocabulary)."""
    record = ledger.to_dict("records")[-1]
    fee = classify_fee(record, VOCABULARY)
    assert fee is not None
    return fee


def test_peer_context_fields_returns_only_peer_keys_in_order() -> None:
    """Every key starts with peer_ (so the alert id is kept), in the order of REQ-PF-12."""
    fee = _last_fee(demo_maintenance_ledger())
    fields = peer_context_fields(fee, Decimal("78.00"), peer_context(s12()))
    assert list(fields) == list(PEER_KEYS)
    assert all(key.startswith("peer_") for key in fields)
    assert all(isinstance(value, (str, int)) for value in fields.values())


def test_peer_context_fields_is_empty_when_it_cannot_be_stated() -> None:
    """Not a PeerContext, no matching service, no amounts: {}."""
    fee = _last_fee(demo_maintenance_ledger())
    assert peer_context_fields(fee, Decimal("78.00"), None) == {}
    assert peer_context_fields(fee, Decimal("78.00"), {"snapshot": 1}) == {}
    assert peer_context_fields(fee, Decimal("78.00"), peer_context(s10())) == {}
    custody = _last_fee(demo_fee_ledger())
    assert custody.description == CUSTODY_DESCRIPTION
    assert peer_context_fields(custody, Decimal("60.00"), peer_context(s12())) == {}


def test_peer_context_is_frozen() -> None:
    """The context is an immutable value (the detector must not be able to change it)."""
    context = peer_context(s12())
    assert context.services == peer_services()
    with pytest.raises(AttributeError):
        context.account_type = "COT"  # type: ignore[misc]


# --- Tier 3: properties -------------------------------------------------------------------------


def expected_fields(
    raw: dict[str, Any], description: str, cost: Decimal, last_charge: str
) -> dict[str, Any]:
    """Recompute REQ-PF-12 from the raw snapshot with a second, independent code path.

    Written in the test on purpose: `sum(...)` counts, `statistics.median` over Decimal and a
    half-up quantize, none of the code under test.
    """
    if description not in COMPARED:
        return {}
    service, concept, label = COMPARED[description]
    cells = [
        r
        for r in raw["rows"]
        if r["account_type"] == "CNO" and r["service_code"] == service and r["concept"] == concept
    ]
    amounts = sorted(Decimal(r["amount"]) for r in cells if r["amount"] is not None)
    gap = abs((date.fromisoformat(last_charge) - date.fromisoformat(raw["declaration_date"])).days)
    if len(amounts) < 10 or gap > 365:
        return {}
    median = Decimal(statistics.median(amounts)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {
        "peer_source": "Banco de España, Comisiones de Cuentas de Pago",
        "peer_account_type": "CNO",
        "peer_account_type_label": "payroll or pension",
        "peer_service": service,
        "peer_service_label": label,
        "peer_concept": concept,
        "peer_declaration_date": raw["declaration_date"],
        "peer_account_count": len(amounts),
        "peer_not_offered_count": sum(1 for r in cells if r["not_offered"]),
        "peer_lower_count": sum(1 for a in amounts if a < cost),
        "peer_zero_count": sum(1 for a in amounts if a == 0),
        "peer_median_yearly": str(median),
        "peer_max_yearly": str(max(amounts)),
    }


@PROP
@given(ledger=peer_series_ledger_strategy(), raw=peer_snapshot_dict_strategy())
def test_peers_change_nothing_but_the_peer_keys_and_they_are_recomputable(
    ledger: pd.DataFrame, raw: dict[str, Any]
) -> None:
    """REQ-PF-13 (ids included) and REQ-PF-22: with and without peers the alerts agree on
    (detector, severity, title, source_refs, id) and the eight base keys; the peer keys are
    all there or none, and equal an independent recomputation."""
    with_peers = run(ledger, peer_context(raw))
    without = run(ledger)
    assert signature(with_peers) == signature(without)
    assert [base_part(a) for a in with_peers] == [a.data for a in without]
    for alert in with_peers:
        found = peer_part(alert)
        assert set(found) in (set(), set(PEER_KEYS))
        assert list(found) in ([], list(PEER_KEYS))
        assert found == expected_fields(
            raw,
            alert.data["description"],
            Decimal(alert.data["yearly_cost"]),
            alert.data["last_charge_date"],
        )
        assert not any("bde" in ref.lower() for ref in alert.source_refs)


@PROP
@given(ledger=peer_series_ledger_strategy(), raw=peer_snapshot_dict_strategy())
def test_source_refs_stay_a_subset_of_the_loaded_refs_with_peers(
    ledger: pd.DataFrame, raw: dict[str, Any]
) -> None:
    """No invention: with context['peers'] set every cited ref belongs to a loaded row."""
    context = MappingProxyType({"vocabulary": VOCABULARY, "peers": peer_context(raw)})
    loaded = loaded_source_refs(ledger, context)
    for alert in detect_recurring_fees(ledger, context):
        assert alert.source_refs
        assert set(alert.source_refs) <= loaded


@PROP
@given(ledger=peer_series_ledger_strategy(), raw=peer_snapshot_dict_strategy())
def test_the_detector_with_peers_is_idempotent(ledger: pd.DataFrame, raw: dict[str, Any]) -> None:
    """Two runs on the same input return equal alerts, peer keys included."""
    peers = peer_context(raw)
    assert run(ledger, peers) == run(ledger, peers)


@PROP
@given(raw=peer_snapshot_dict_strategy())
def test_an_empty_ledger_gives_no_alert_whatever_the_snapshot(raw: dict[str, Any]) -> None:
    """Empty input gives [] with any peers context."""
    assert run(pd.DataFrame(), peer_context(raw)) == []
    assert run(make_ledger([]), peer_context(raw)) == []


@PROP
@given(
    ledger=peer_series_ledger_strategy(),
    raw=peer_snapshot_dict_strategy(),
    account_type=st.sampled_from(("CNO", "CDI", "COT")),
)
def test_peer_amounts_are_never_negative_and_counts_fit_the_sample(
    ledger: pd.DataFrame, raw: dict[str, Any], account_type: str
) -> None:
    """Amount non-negativity and sane counts, for any account type asked."""
    for alert in run(ledger, peer_context(raw, account_type)):
        found = peer_part(alert)
        if not found:
            continue
        assert account_type == "CNO"
        assert Decimal(found["peer_median_yearly"]) >= 0
        assert Decimal(found["peer_max_yearly"]) >= Decimal(found["peer_median_yearly"])
        assert found["peer_zero_count"] <= found["peer_lower_count"]
        assert found["peer_lower_count"] <= found["peer_account_count"]
        assert found["peer_account_count"] >= PEER_MIN_ACCOUNTS
