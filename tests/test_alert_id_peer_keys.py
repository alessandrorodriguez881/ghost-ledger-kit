"""The alert id leaves out the `peer_*` data keys (DN-PF-17, Q7 of public-fees).

Tier 1: an alert with peer fields has the same id as the same alert without them. Tier 2: the rule
is one prefix, only for top-level keys, and every other key still changes the id. Tier 3: every
alert of the three demos has no `peer_` key today and keeps the id that the old formula (the whole
`data`) gives; Hypothesis checks the same on random data. All data is synthetic.
"""

import hashlib
import json
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from judge_path_support import SCRIPTS, Z1_ALERT_ID, cases_of, find_case

from ledger_kit.models import ALERT_ID_EXCLUDED_PREFIX, Alert, _json_default

PEER_FIELDS = {
    "peer_source": "Banco de España, Comisiones de Cuentas de Pago",
    "peer_account_type": "CNO",
    "peer_median_yearly": "18.00",
    "peer_account_count": 12,
}


def _alert(data: dict) -> Alert:
    """Build a synthetic alert with the given data."""
    return Alert(
        detector="vf.recurring_fee",
        severity="warning",
        title="Recurring fee",
        source_refs=["s.csv:1", "s.csv:2"],
        data=data,
    )


def _old_id(alert: Alert) -> str:
    """Recompute the id with the formula before the change: the whole `data` is hashed."""
    payload = json.dumps(
        {"detector": alert.detector, "source_refs": sorted(alert.source_refs), "data": alert.data},
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def test_prefix_constant_is_peer_underscore() -> None:
    assert ALERT_ID_EXCLUDED_PREFIX == "peer_"


def test_alert_with_peer_fields_has_the_same_id_as_without() -> None:
    base = {"yearly_cost": "78.00", "charge_count": 22}
    assert _alert({**base, **PEER_FIELDS}).id == _alert(base).id


def test_peer_fields_stay_in_data() -> None:
    alert = _alert({"yearly_cost": "78.00", **PEER_FIELDS})
    assert alert.data["peer_median_yearly"] == "18.00"


def test_a_different_peer_value_gives_the_same_id() -> None:
    first = _alert({"yearly_cost": "78.00", "peer_median_yearly": "18.00"})
    second = _alert({"yearly_cost": "78.00", "peer_median_yearly": "19.00"})
    assert first.id == second.id


def test_peer_decimal_value_is_ignored_too() -> None:
    first = _alert({"yearly_cost": "78.00", "peer_max_yearly": Decimal("240.00")})
    assert first.id == _alert({"yearly_cost": "78.00"}).id


def test_other_keys_still_change_the_id() -> None:
    assert _alert({"yearly_cost": "78.00"}).id != _alert({"yearly_cost": "79.00"}).id


@pytest.mark.parametrize("key", ["peer", "peers", "xpeer_a", "Peer_a", "yearly_peer_cost"])
def test_only_the_exact_prefix_is_excluded(key: str) -> None:
    with_key = _alert({"yearly_cost": "78.00", key: "x"})
    assert with_key.id != _alert({"yearly_cost": "78.00"}).id


def test_only_top_level_keys_are_excluded() -> None:
    nested = _alert({"yearly_cost": "78.00", "extra": {"peer_a": 1}})
    assert nested.id != _alert({"yearly_cost": "78.00", "extra": {}}).id


def test_alert_with_only_peer_fields_has_the_id_of_empty_data() -> None:
    assert _alert(dict(PEER_FIELDS)).id == _alert({}).id


def test_explicit_id_is_still_kept_with_peer_fields() -> None:
    alert = Alert(
        id="custom-id",
        detector="vf.recurring_fee",
        severity="info",
        title="t",
        source_refs=["s.csv:1"],
        data=dict(PEER_FIELDS),
    )
    assert alert.id == "custom-id"


@pytest.mark.parametrize("prefix", sorted(SCRIPTS))
def test_no_demo_alert_has_a_peer_key_and_every_id_is_unchanged(prefix: str) -> None:
    cases = cases_of(prefix)
    assert cases, f"no demo alert for {prefix}"
    for case in cases:
        alert = case.alert
        assert not [k for k in alert.data if str(k).startswith(ALERT_ID_EXCLUDED_PREFIX)]
        assert alert.id == _old_id(alert)


def test_the_pinned_zombie_alert_is_still_found_by_its_id() -> None:
    assert find_case(Z1_ALERT_ID) is not None


_VALUES = st.one_of(st.integers(), st.text(max_size=8), st.decimals(allow_nan=False, places=2))
_BASE_KEYS = st.text(alphabet="abcdefg_", min_size=1, max_size=8).filter(
    lambda key: not key.startswith(ALERT_ID_EXCLUDED_PREFIX)
)
_PEER_KEYS = st.text(alphabet="abcdefg_", max_size=8).map(lambda s: ALERT_ID_EXCLUDED_PREFIX + s)


@settings(max_examples=200, deadline=None)
@given(
    base=st.dictionaries(_BASE_KEYS, _VALUES, max_size=5),
    peers=st.dictionaries(_PEER_KEYS, _VALUES, max_size=5),
)
def test_peer_keys_never_change_the_id_and_without_them_the_old_formula_holds(
    base: dict, peers: dict
) -> None:
    assert _alert({**base, **peers}).id == _alert(base).id
    assert _alert(base).id == _old_id(_alert(base))
