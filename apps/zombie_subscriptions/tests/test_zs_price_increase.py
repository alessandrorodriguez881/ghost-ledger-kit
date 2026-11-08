"""Tests for the price-increase detector (Task Z11)."""

from datetime import date, timedelta
from decimal import Decimal
from types import MappingProxyType, SimpleNamespace

import pandas as pd
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from apps.zombie_subscriptions.detectors.price_increase import detect_price_increases
from apps.zombie_subscriptions.detectors.utils import find_series
from ledger_kit.detectors import loaded_source_refs
from ledger_kit.utils.money import round_to_cents

START = date(2026, 1, 5)
PROP = settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])


def _ctx(aliases: dict[str, list[str]] | None = None) -> MappingProxyType:
    """Build the read-only context the registry passes to a detector."""
    return MappingProxyType({"aliases": aliases})


def _rows_at(
    entries: list[tuple[int, str | Decimal]], counterparty: str = "CLOUDVAULT", first_row: int = 0
) -> list[dict]:
    """Build rows from (day offset from START, amount) pairs numbered from first_row."""
    return [
        {
            "date": START + timedelta(days=offset),
            "amount": Decimal(amount),
            "counterparty": counterparty,
            "source_ref": f"f.csv:{first_row + i}",
            "source_row": first_row + i,
        }
        for i, (offset, amount) in enumerate(entries)
    ]


def _monthly(
    amounts: list[str] | list[Decimal], counterparty: str = "CLOUDVAULT", first_row: int = 0
) -> list[dict]:
    """Build monthly rows (30-day gaps) with the given amounts."""
    return _rows_at([(30 * i, a) for i, a in enumerate(amounts)], counterparty, first_row)


def _stepped_amounts(base: int, pct: Decimal, k: int, noise_bps: list[int]) -> list[Decimal]:
    """Six amounts: `k` at `base`, the rest `pct` percent higher, each with noise in bps."""
    amounts = []
    for i, bps in enumerate(noise_bps):
        level = Decimal(base)
        if i >= k:
            level = level * (Decimal(1) + pct / Decimal(100))
        amounts.append(round_to_cents(level * (Decimal(1) + Decimal(bps) / Decimal(10000))))
    return amounts


_NO_NOISE = [0] * 6
_NOISE = st.lists(st.integers(min_value=-50, max_value=50), min_size=6, max_size=6)


def _amount(base_cents: int, bps: int) -> Decimal:
    """Return base_cents scaled by (1 + bps / 10000), as euros rounded to cents."""
    return round_to_cents(Decimal(base_cents * (10000 + bps)) / Decimal(1_000_000))


_STEP = st.tuples(st.integers(25, 35), st.integers(-15, 15))
_MERCHANTS = ["CLOUDVAULT", "STREAMFLEX INTL", "MUSICBOX", "GLOWBILL"]


@st.composite
def _ledger_rows(draw: st.DrawFn) -> list[dict]:
    """Random debit rows: one to three near-monthly streams, some with price changes."""
    rows: list[dict] = []
    for merchant in draw(st.lists(st.sampled_from(_MERCHANTS), min_size=1, max_size=3)):
        offset = draw(st.integers(min_value=0, max_value=60))
        base_cents = draw(st.integers(min_value=500, max_value=20000))
        entries = [(offset, _amount(base_cents, 0))]
        for gap, pct in draw(st.lists(_STEP, max_size=7)):
            offset += gap
            entries.append((offset, _amount(base_cents, pct * 100)))
        rows.extend(_rows_at(entries, merchant, first_row=len(rows)))
    return rows


# --- Tier 1 ------------------------------------------------------------------------------------


def test_zs_acceptance_e1_price_increase_alert(ledger_with_price_increase: pd.DataFrame) -> None:
    """E1: 12.99 -> 15.99 gives one warning with extra 36.00 and yearly cost 191.88."""
    (alert,) = detect_price_increases(ledger_with_price_increase, _ctx())
    assert alert.detector == "zs.price_increase"
    assert alert.severity == "warning"
    assert alert.title == "Price increase detected: STREAMFLEX INTL"
    assert alert.source_refs == [f"zs_fixture.csv:{i}" for i in range(6)]
    assert alert.data == {
        "counterparty": "STREAMFLEX INTL",
        "old_median_amount": "12.99",
        "new_amount": "15.99",
        "extra_cost_per_year": "36.00",
        "yearly_cost": "191.88",
        "interval_type": "monthly",
    }


def test_zs_acceptance_e2_price_increase_alert(builders: SimpleNamespace) -> None:
    """E2: 9.99 -> 12.99 gives one warning with extra 36.00 and yearly cost 155.88."""
    (alert,) = detect_price_increases(builders.to_frame(builders.rows_e2()), _ctx())
    assert alert.data["old_median_amount"] == "9.99"
    assert alert.data["new_amount"] == "12.99"
    assert alert.data["extra_cost_per_year"] == "36.00"
    assert alert.data["yearly_cost"] == "155.88"


def test_downgrade_never_alerts(builders: SimpleNamespace) -> None:
    """A step from 14.99 down to 9.99 raises no price-increase alert."""
    assert detect_price_increases(builders.to_frame(builders.rows_downgrade()), _ctx()) == []


def test_price_increase_silent_on_clean_ledger(clean_ledger_10: pd.DataFrame) -> None:
    """Ten unrelated one-off purchases give no alert."""
    assert detect_price_increases(clean_ledger_10, _ctx()) == []


def test_step_between_5_and_10_pct_alerts() -> None:
    """12.99 x 3 then 13.79 x 3 (+6.2%) is one price bucket but still a recorded step."""
    ledger = pd.DataFrame(_monthly(["12.99"] * 3 + ["13.79"] * 3))
    (alert,) = detect_price_increases(ledger, _ctx())
    assert alert.data["old_median_amount"] == "12.99"
    assert alert.data["new_amount"] == "13.79"
    assert alert.data["extra_cost_per_year"] == "9.60"
    assert alert.data["yearly_cost"] == "165.48"


def test_e7b_no_price_increase_alerts(ledger_with_weekly_shopping: pd.DataFrame) -> None:
    """E7b: 26 weekly shopping charges give no price-increase alert."""
    assert detect_price_increases(ledger_with_weekly_shopping, _ctx()) == []


# --- Tier 2 ------------------------------------------------------------------------------------


def test_empty_ledger_returns_empty_list(empty_ledger: pd.DataFrame) -> None:
    """An empty ledger gives [] and never raises."""
    assert detect_price_increases(empty_ledger, MappingProxyType({})) == []
    assert detect_price_increases(pd.DataFrame(), MappingProxyType({})) == []


def test_single_row_returns_list(single_row_ledger: pd.DataFrame) -> None:
    """A one-row ledger returns a list."""
    result = detect_price_increases(single_row_ledger, _ctx())
    assert isinstance(result, list)
    assert result == []


def test_threshold_boundary_exactly_5pct_fires() -> None:
    """A step from 20.00 to 21.00 is exactly 5% and fires."""
    ledger = pd.DataFrame(_monthly(["20.00"] * 3 + ["21.00"] * 3))
    (alert,) = detect_price_increases(ledger, _ctx())
    assert alert.data["new_amount"] == "21.00"


def test_just_below_5pct_does_not() -> None:
    """A step from 20.00 to 20.99 is 4.95%: recorded as a step, but no alert."""
    ledger = pd.DataFrame(_monthly(["20.00"] * 3 + ["20.99"] * 3))
    assert detect_price_increases(ledger, _ctx()) == []


def test_ratio_computed_from_rounded_medians() -> None:
    """A raw median of 20.995 rounds to 21.00 first, so the ratio is exactly 5%."""
    ledger = pd.DataFrame(_monthly(["20.00"] * 3 + ["20.995"] * 3))
    (alert,) = detect_price_increases(ledger, _ctx())
    assert alert.data["old_median_amount"] == "20.00"
    assert alert.data["new_amount"] == "21.00"
    assert alert.data["extra_cost_per_year"] == "12.00"


def test_duplicate_source_ref_handled(ledger_with_price_increase: pd.DataFrame) -> None:
    """A row repeated with the same source_ref does not crash and is cited once."""
    doubled = pd.concat([ledger_with_price_increase, ledger_with_price_increase.iloc[[0]]])
    alerts = detect_price_increases(doubled, _ctx())
    assert isinstance(alerts, list)
    for alert in alerts:
        assert len(alert.source_refs) == len(set(alert.source_refs))


def test_two_steps_in_one_service_each_reported() -> None:
    """Two keys of one aliased service, each with a step, give two alerts under one name."""
    first = _monthly(["9.99"] * 3 + ["12.99"] * 3, "CLOUDVAULT", first_row=0)
    second = _monthly(["12.99"] * 3 + ["15.99"] * 3, "STREAMFLEX INTL", first_row=10)
    aliases = {"STREAMING": ["CLOUDVAULT", "STREAMFLEX INTL"]}
    alerts = detect_price_increases(pd.DataFrame([*first, *second]), _ctx(aliases))
    assert [a.data["counterparty"] for a in alerts] == ["STREAMING", "STREAMING"]
    assert [a.data["new_amount"] for a in alerts] == ["12.99", "15.99"]


# --- Tier 3 ------------------------------------------------------------------------------------


@PROP
@given(
    base=st.integers(min_value=20, max_value=500),
    pct=st.integers(min_value=7, max_value=45),
    k=st.integers(min_value=1, max_value=5),
    noise=_NOISE,
)
def test_price_step_above_5pct_always_fires(base: int, pct: int, k: int, noise: list[int]) -> None:
    """With +/-0.5% noise an upward step of 7-45% at any of k = 1..5 gives exactly one alert."""
    amounts = _stepped_amounts(base, Decimal(pct), k, noise)
    alerts = detect_price_increases(pd.DataFrame(_monthly(amounts)), _ctx())
    assert len(alerts) == 1
    assert Decimal(alerts[0].data["new_amount"]) > Decimal(alerts[0].data["old_median_amount"])


@PROP
@given(
    base=st.integers(min_value=20, max_value=500),
    k=st.integers(min_value=1, max_value=5),
)
def test_price_step_exactly_5pct_fires(base: int, k: int) -> None:
    """A noise-free step of exactly 5% at any of k = 1..5 gives one alert."""
    amounts = _stepped_amounts(base, Decimal(5), k, _NO_NOISE)
    alerts = detect_price_increases(pd.DataFrame(_monthly(amounts)), _ctx())
    assert len(alerts) == 1
    assert alerts[0].data["old_median_amount"] == str(amounts[0])
    assert alerts[0].data["new_amount"] == str(amounts[-1])


@PROP
@given(
    base=st.integers(min_value=100, max_value=500),
    tenths=st.integers(min_value=-39, max_value=39),
    k=st.integers(min_value=1, max_value=5),
    noise=_NOISE,
)
def test_price_step_below_5pct_never_fires(
    base: int, tenths: int, k: int, noise: list[int]
) -> None:
    """With +/-0.5% noise a step of at most 3.9% (up or down) never fires."""
    amounts = _stepped_amounts(base, Decimal(tenths) / Decimal(10), k, noise)
    assert detect_price_increases(pd.DataFrame(_monthly(amounts)), _ctx()) == []


@PROP
@given(
    base=st.integers(min_value=20, max_value=500),
    noise=_NOISE,
)
def test_stable_series_never_fires_price_increase(base: int, noise: list[int]) -> None:
    """Noise within +/-0.5% around one level never fires."""
    amounts = _stepped_amounts(base, Decimal(0), 6, noise)
    assert detect_price_increases(pd.DataFrame(_monthly(amounts)), _ctx()) == []


@PROP
@given(
    base=st.integers(min_value=20, max_value=500),
    pct=st.integers(min_value=5, max_value=50),
    k=st.integers(min_value=1, max_value=5),
)
def test_early_step_fires_exactly_once(base: int, pct: int, k: int) -> None:
    """A noise-free step of 5-50% at any of k = 1..5 gives one series and one alert."""
    rows = _monthly(_stepped_amounts(base, Decimal(pct), k, _NO_NOISE))
    assert len(find_series(rows)) == 1
    assert len(detect_price_increases(pd.DataFrame(rows), _ctx())) == 1


@PROP
@given(rows=_ledger_rows())
def test_source_refs_subset_of_input(rows: list[dict]) -> None:
    """No invention: every cited source_ref belongs to a loaded input."""
    ledger = pd.DataFrame(rows)
    context = _ctx()
    known = loaded_source_refs(ledger, context)
    for alert in detect_price_increases(ledger, context):
        assert alert.source_refs
        assert set(alert.source_refs) <= known
