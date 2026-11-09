"""The CPI context of zs.price_increase (public-cpi CPI6: REQ-CPI-09 to REQ-CPI-13, REQ-CPI-15).

Every CPI series here is **synthetic** (made-up index values, not INE figures). The existing
test_zs_price_increase.py is not edited: it keeps proving the behaviour without CPI.
"""

from datetime import date, timedelta
from decimal import Decimal
from types import MappingProxyType, SimpleNamespace
from typing import Any

import pandas as pd
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from apps.zombie_subscriptions.detectors.price_increase import detect_price_increases
from ledger_kit.detectors import loaded_source_refs
from ledger_kit.models import Alert
from ledger_kit.public_data import CpiSeries
from ledger_kit.utils.money import round_to_cents

PROP = settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])

BASE_KEYS = (
    "counterparty",
    "old_median_amount",
    "new_amount",
    "extra_cost_per_year",
    "yearly_cost",
    "interval_type",
)
CPI_KEYS = (
    "price_start_month",
    "price_end_month",
    "price_change_percent",
    "cpi_series",
    "cpi_base_year",
    "cpi_start_month",
    "cpi_end_month",
    "cpi_start_index",
    "cpi_end_index",
    "cpi_change_percent",
)

# Synthetic series C and G of REQ-CPI-11 / REQ-CPI-13.
SERIES_C = CpiSeries.from_mapping(
    {
        "2026-01": "100.000",
        "2026-02": "100.500",
        "2026-03": "101.000",
        "2026-04": "102.000",
        "2026-05": "102.500",
        "2026-06": "103.000",
    }
)
SERIES_G = CpiSeries.from_mapping({"2026-01": "100.000", "2026-03": "101.000"})
# A synthetic series that does not cover 2026 at all.
SERIES_2024 = CpiSeries.from_mapping({"2024-01": "90.000", "2024-02": "90.500"})


def _ctx(cpi: Any = None, *, with_cpi_key: bool = True) -> MappingProxyType:
    """Build the read-only context the registry passes to a detector."""
    context: dict[str, Any] = {"aliases": None}
    if with_cpi_key:
        context["cpi"] = cpi
    return MappingProxyType(context)


def _rows(
    start: date,
    amounts: list[str] | list[Decimal],
    *,
    step_days: int = 30,
    counterparty: str = "CLOUDVAULT",
    first_row: int = 0,
) -> list[dict]:
    """Rows `step_days` apart from `start`, cited as f.csv:<n>."""
    return [
        {
            "date": start + timedelta(days=step_days * i),
            "amount": Decimal(a),
            "counterparty": counterparty,
            "source_ref": f"f.csv:{first_row + i}",
            "source_row": first_row + i,
        }
        for i, a in enumerate(amounts)
    ]


def _ledger(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


SIX_ROWS = _rows(date(2026, 1, 5), ["100.00"] * 3 + ["118.00"] * 3)
BASE_DATA = {
    "counterparty": "CLOUDVAULT",
    "old_median_amount": "100.00",
    "new_amount": "118.00",
    "extra_cost_per_year": "216.00",
    "yearly_cost": "1416.00",
    "interval_type": "monthly",
}


def _only(alerts: list[Alert]) -> Alert:
    assert len(alerts) == 1, alerts
    return alerts[0]


def _has_no_cpi_keys(alert: Alert) -> bool:
    return not any(key in alert.data for key in CPI_KEYS)


# --- Tier 1 ------------------------------------------------------------------------------------


def test_price_increase_cpi_fires_with_the_exact_dict() -> None:
    """REQ-CPI-11: 18 % against 2 % from 2026-01 to 2026-04 with series C."""
    alert = _only(detect_price_increases(_ledger(SIX_ROWS), _ctx(SERIES_C)))
    assert alert.detector == "zs.price_increase"
    assert alert.source_refs == [f"f.csv:{i}" for i in range(6)]
    assert alert.data == {
        **BASE_DATA,
        "price_start_month": "2026-01",
        "price_end_month": "2026-04",
        "price_change_percent": "18.0",
        "cpi_series": "IPC290751",
        "cpi_base_year": "2025",
        "cpi_start_month": "2026-01",
        "cpi_end_month": "2026-04",
        "cpi_start_index": "100.000",
        "cpi_end_index": "102.000",
        "cpi_change_percent": "2.0",
    }
    assert list(alert.data) == [*BASE_KEYS, *CPI_KEYS]


def test_without_cpi_the_alert_is_todays() -> None:
    """REQ-CPI-09: no `cpi` key, or `cpi` None, gives exactly the six-key dict and the same id."""
    without_key = _only(detect_price_increases(_ledger(SIX_ROWS), _ctx(with_cpi_key=False)))
    with_none = _only(detect_price_increases(_ledger(SIX_ROWS), _ctx(None)))
    assert without_key.data == BASE_DATA
    assert with_none.data == BASE_DATA
    assert without_key.id == with_none.id


def test_e1_with_a_series_that_does_not_cover_2026(
    ledger_with_price_increase: pd.DataFrame,
) -> None:
    """E1 with a CPI series of 2024 only: no CPI keys, alert identical to the no-CPI one."""
    plain = _only(detect_price_increases(ledger_with_price_increase, _ctx(with_cpi_key=False)))
    with_cpi = _only(detect_price_increases(ledger_with_price_increase, _ctx(SERIES_2024)))
    assert with_cpi.data == plain.data
    assert with_cpi.id == plain.id


def test_cpi_changes_the_id_but_not_the_identity() -> None:
    """DN-CPI-07: the id hashes data, so it changes; the rest of the alert does not."""
    plain = _only(detect_price_increases(_ledger(SIX_ROWS), _ctx()))
    with_cpi = _only(detect_price_increases(_ledger(SIX_ROWS), _ctx(SERIES_C)))
    assert with_cpi.id != plain.id
    assert _identity(with_cpi) == _identity(plain)


def test_source_refs_cite_ledger_rows_only() -> None:
    """REQ-CPI-15: no pseudo reference to the INE in source_refs."""
    alert = _only(detect_price_increases(_ledger(SIX_ROWS), _ctx(SERIES_C)))
    assert alert.source_refs == [f"f.csv:{i}" for i in range(6)]
    assert not any("ine" in ref.lower() or "IPC" in ref for ref in alert.source_refs)


# --- Tier 2: REQ-CPI-13 --------------------------------------------------------------------------


def test_price_start_before_the_series_gives_no_cpi_keys() -> None:
    """Rows from 2025-12-05: the start month is before 2026-01."""
    rows = _rows(date(2025, 12, 5), ["100.00"] * 3 + ["118.00"] * 3)
    alert = _only(detect_price_increases(_ledger(rows), _ctx(SERIES_C)))
    assert _has_no_cpi_keys(alert)
    assert alert.data["new_amount"] == "118.00"


def test_step_two_months_after_the_series_gives_no_cpi_keys() -> None:
    """First new row in 2026-08, two months after the last month 2026-06."""
    rows = _rows(date(2026, 5, 10), ["100.00"] * 3 + ["118.00"] * 3)
    assert rows[3]["date"] == date(2026, 8, 8)
    alert = _only(detect_price_increases(_ledger(rows), _ctx(SERIES_C)))
    assert _has_no_cpi_keys(alert)


def test_step_one_month_after_the_series_uses_the_last_month() -> None:
    """First new row in 2026-07: CPI end month 2026-06 (CPI_MAX_LAG_MONTHS), months differ."""
    rows = _rows(date(2026, 4, 10), ["100.00"] * 3 + ["118.00"] * 3)
    assert rows[3]["date"] == date(2026, 7, 9)
    alert = _only(detect_price_increases(_ledger(rows), _ctx(SERIES_C)))
    assert alert.data["price_start_month"] == "2026-04"
    assert alert.data["price_end_month"] == "2026-07"
    assert alert.data["cpi_start_month"] == "2026-04"
    assert alert.data["cpi_end_month"] == "2026-06"
    assert alert.data["cpi_start_index"] == "102.000"
    assert alert.data["cpi_end_index"] == "103.000"
    assert alert.data["cpi_change_percent"] == "1.0"  # 0.98039... rounded half-up


def test_weekly_step_within_one_month_gives_no_cpi_keys() -> None:
    """Weekly 10.00, 10.00, 12.00, 12.00 in January 2026: a zero-length span."""
    rows = _rows(date(2026, 1, 5), ["10.00", "10.00", "12.00", "12.00"], step_days=7)
    alert = _only(detect_price_increases(_ledger(rows), _ctx(SERIES_C)))
    assert alert.data["interval_type"] == "weekly"
    assert _has_no_cpi_keys(alert)


def test_gap_fallback_keeps_the_keys_with_differing_months() -> None:
    """Series G, step from 2026-02 to 2026-03: the CPI start month falls back to 2026-01."""
    rows = _rows(date(2026, 2, 1), ["100.00"] + ["118.00"] * 3)
    alert = _only(detect_price_increases(_ledger(rows), _ctx(SERIES_G)))
    assert alert.data["price_start_month"] == "2026-02"
    assert alert.data["price_end_month"] == "2026-03"
    assert alert.data["cpi_start_month"] == "2026-01"
    assert alert.data["cpi_end_month"] == "2026-03"
    assert alert.data["cpi_change_percent"] == "1.0"


def test_fallback_that_collapses_the_span_gives_no_cpi_keys() -> None:
    """Both price months answered by the same CPI month: no comparison."""
    series = CpiSeries.from_mapping({"2026-01": "100.000", "2026-06": "103.000"})
    alert = _only(detect_price_increases(_ledger(SIX_ROWS), _ctx(series)))
    assert _has_no_cpi_keys(alert)


def test_cpi_that_is_not_a_series_gives_no_cpi_keys() -> None:
    """An object without `lookup` (or without a series code) is ignored, never an error."""
    for cpi in (object(), "IPC290751", SimpleNamespace(series_code="IPC290751", base_year=2025)):
        alert = _only(detect_price_increases(_ledger(SIX_ROWS), _ctx(cpi)))
        assert alert.data == BASE_DATA


def test_empty_ledger_with_cpi(empty_ledger: pd.DataFrame) -> None:
    assert detect_price_increases(empty_ledger, _ctx(SERIES_C)) == []
    assert detect_price_increases(pd.DataFrame(), _ctx(SERIES_C)) == []


def test_single_row_ledger_with_cpi(single_row_ledger: pd.DataFrame) -> None:
    result = detect_price_increases(single_row_ledger, _ctx(SERIES_C))
    assert isinstance(result, list)
    assert result == []


def test_threshold_boundaries_unchanged_with_cpi() -> None:
    """Exactly 5 % fires and 4,95 % does not, with or without CPI."""
    fires = _ledger(_rows(date(2026, 1, 5), ["20.00"] * 3 + ["21.00"] * 3))
    silent = _ledger(_rows(date(2026, 1, 5), ["20.00"] * 3 + ["20.99"] * 3))
    alert = _only(detect_price_increases(fires, _ctx(SERIES_C)))
    plain = _only(detect_price_increases(fires, _ctx()))
    assert alert.data["price_change_percent"] == "5.0"
    assert {k: alert.data[k] for k in BASE_KEYS} == plain.data
    assert detect_price_increases(silent, _ctx(SERIES_C)) == []


def test_duplicate_source_ref_with_cpi() -> None:
    """A repeated row does not crash; refs are cited once."""
    ledger = _ledger([*SIX_ROWS, dict(SIX_ROWS[0])])
    alerts = detect_price_increases(ledger, _ctx(SERIES_C))
    assert isinstance(alerts, list)
    for alert in alerts:
        assert len(alert.source_refs) == len(set(alert.source_refs))


def test_detector_is_idempotent_with_cpi() -> None:
    first = detect_price_increases(_ledger(SIX_ROWS), _ctx(SERIES_C))
    second = detect_price_increases(_ledger(SIX_ROWS), _ctx(SERIES_C))
    assert first == second


# --- Tier 3 ------------------------------------------------------------------------------------

_STEP = st.tuples(st.integers(25, 35), st.integers(-15, 15))
_MERCHANTS = ["CLOUDVAULT", "STREAMFLEX INTL", "MUSICBOX", "GLOWBILL"]


def _amount(base_cents: int, bps: int) -> Decimal:
    return round_to_cents(Decimal(base_cents * (10000 + bps)) / Decimal(1_000_000))


@st.composite
def _ledger_rows(draw: st.DrawFn) -> list[dict]:
    """One to three near-monthly streams in 2026, some with price changes."""
    rows: list[dict] = []
    start = date(2026, 1, 5)
    for merchant in draw(st.lists(st.sampled_from(_MERCHANTS), min_size=1, max_size=3)):
        offset = draw(st.integers(min_value=0, max_value=60))
        base_cents = draw(st.integers(min_value=500, max_value=20000))
        entries = [(offset, _amount(base_cents, 0))]
        for gap, pct in draw(st.lists(_STEP, max_size=7)):
            offset += gap
            entries.append((offset, _amount(base_cents, pct * 100)))
        for offset_days, amount in entries:
            index = len(rows)
            rows.append(
                {
                    "date": start + timedelta(days=offset_days),
                    "amount": amount,
                    "counterparty": merchant,
                    "source_ref": f"f.csv:{index}",
                    "source_row": index,
                }
            )
    return rows


def _month_text(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


_CPI_MONTHS = st.one_of(
    st.builds(_month_text, st.just(2025), st.integers(10, 12)),
    st.builds(_month_text, st.just(2026), st.integers(1, 12)),
)
_CPI_VALUES = st.decimals(min_value=Decimal("50"), max_value=Decimal("150"), places=3).map(str)
_CPI_SERIES = st.dictionaries(_CPI_MONTHS, _CPI_VALUES, max_size=15).map(CpiSeries.from_mapping)


def _identity(alert: Alert) -> tuple:
    return (alert.detector, alert.severity, alert.title, alert.source_refs)


@PROP
@given(rows=_ledger_rows(), cpi=_CPI_SERIES)
def test_cpi_never_changes_which_alerts_fire(rows: list[dict], cpi: CpiSeries) -> None:
    """REQ-CPI-12: same alerts, same order, same base data, CPI keys all or none."""
    ledger = _ledger(rows)
    plain = detect_price_increases(ledger, _ctx())
    with_cpi = detect_price_increases(ledger, _ctx(cpi))
    assert [_identity(a) for a in with_cpi] == [_identity(a) for a in plain]
    for a, b in zip(with_cpi, plain, strict=True):
        assert {k: a.data[k] for k in BASE_KEYS} == b.data
        present = [key in a.data for key in CPI_KEYS]
        assert all(present) or not any(present)
        if all(present):
            assert a.data["cpi_start_month"] <= a.data["price_start_month"]
            assert a.data["cpi_end_month"] <= a.data["price_end_month"]
            assert a.data["cpi_start_month"] != a.data["cpi_end_month"]


@PROP
@given(rows=_ledger_rows(), cpi=_CPI_SERIES)
def test_source_refs_subset_of_loaded_inputs_with_cpi(rows: list[dict], cpi: CpiSeries) -> None:
    """No invention: the CPI in context adds no ref, and every cited ref is a ledger row."""
    ledger = _ledger(rows)
    context = _ctx(cpi)
    known = loaded_source_refs(ledger, context)
    assert known == loaded_source_refs(ledger, _ctx())
    for alert in detect_price_increases(ledger, context):
        assert alert.source_refs
        assert set(alert.source_refs) <= known


@PROP
@given(rows=_ledger_rows(), cpi=_CPI_SERIES)
def test_detector_with_cpi_is_idempotent(rows: list[dict], cpi: CpiSeries) -> None:
    ledger = _ledger(rows)
    assert detect_price_increases(ledger, _ctx(cpi)) == detect_price_increases(ledger, _ctx(cpi))
