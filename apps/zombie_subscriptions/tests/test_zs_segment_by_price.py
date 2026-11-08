"""Tests for is_level and _segment_by_price (Task Z6), table-driven over amount lists."""

from datetime import date, timedelta
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from apps.zombie_subscriptions.detectors import utils as zs
from ledger_kit.utils.money import round_to_cents

START = date(2026, 1, 5)
MONTHLY = zs.INTERVALS_BY_NAME["monthly"]


def _run(amounts: list[str] | list[Decimal]) -> list[dict]:
    """Build a monthly cadence run (30-day gaps) with the given amounts."""
    return [
        {
            "date": START + timedelta(days=30 * i),
            "amount": Decimal(a),
            "counterparty": "CLOUDVAULT",
            "source_ref": f"t.csv:{i}",
            "source_row": i,
        }
        for i, a in enumerate(amounts)
    ]


def _segment(amounts: list[str] | list[Decimal]) -> zs.Series | None:
    """Segment a monthly run built from `amounts`."""
    return zs._segment_by_price(_run(amounts), MONTHLY)


def _step(old: str, new: str) -> tuple[Decimal, Decimal]:
    """Return a (old, new) price step tuple of Decimals."""
    return (Decimal(old), Decimal(new))


# --- Tier 1: Branch 1 -------------------------------------------------------------------------


def test_stable_run_is_one_series_no_steps() -> None:
    """Five equal charges are one stable series with no price steps."""
    series = _segment(["12.99"] * 5)
    assert series is not None
    assert series.interval_type == "monthly"
    assert series.nominal_days == 30
    assert series.current_amount == Decimal("12.99")
    assert series.price_steps == []
    assert len(series.rows) == 5


def test_two_percent_boundary() -> None:
    """Amounts exactly 2% from the median are a level; just above are not."""
    exact = [Decimal("98.00"), Decimal("100.00"), Decimal("102.00")]
    above = [Decimal("97.99"), Decimal("100.00"), Decimal("102.01")]
    assert zs.is_level(exact) is True
    assert zs.is_level(above) is False
    series = _segment(["98.00", "100.00", "102.00"])
    assert series is not None
    assert series.price_steps == []
    assert series.current_amount == Decimal("100.00")


# --- Tier 1: Branch 2 -------------------------------------------------------------------------


def test_step_up_recorded() -> None:
    """Three 9.99 then three 12.99 record the step (9.99, 12.99)."""
    series = _segment(["9.99"] * 3 + ["12.99"] * 3)
    assert series is not None
    assert series.price_steps == [_step("9.99", "12.99")]
    assert series.current_amount == Decimal("12.99")


def test_step_down_recorded() -> None:
    """A downward step is recorded as well."""
    series = _segment(["14.99"] * 3 + ["9.99"] * 3)
    assert series is not None
    assert series.price_steps == [_step("14.99", "9.99")]
    assert series.current_amount == Decimal("9.99")


def test_step_between_5_and_10_pct_is_recorded() -> None:
    """12.99 x 3 then 13.79 x 3 (+6.2%) records a step although it is within 10%."""
    series = _segment(["12.99"] * 3 + ["13.79"] * 3)
    assert series is not None
    assert series.price_steps == [_step("12.99", "13.79")]
    assert series.current_amount == Decimal("13.79")


def test_final_single_row_after_enough_rows_is_step() -> None:
    """E1: 12.99 x 5 then 15.99 is a step, the lone last row is the new price."""
    series = _segment(["12.99"] * 5 + ["15.99"])
    assert series is not None
    assert series.price_steps == [_step("12.99", "15.99")]
    assert series.current_amount == Decimal("15.99")


def test_first_single_row_before_enough_rows_is_step() -> None:
    """One 12.99 followed by 15.99 x 5 is a step found at the start of the run."""
    series = _segment(["12.99"] + ["15.99"] * 5)
    assert series is not None
    assert series.price_steps == [_step("12.99", "15.99")]
    assert series.current_amount == Decimal("15.99")


# --- Tier 1: shopping guards ------------------------------------------------------------------


def test_stray_low_amount_is_not_a_new_price() -> None:
    """12.99 x 4 then a stray 4.99 (-62%) is not a series."""
    assert _segment(["12.99"] * 4 + ["4.99"]) is None


def test_single_row_side_needs_interval_minimum() -> None:
    """Monthly 12.99 x 2 then 15.99: the long side has 2 rows, below the minimum of 3."""
    assert _segment(["12.99"] * 2 + ["15.99"]) is None


def test_trial_amount_before_series_is_not_a_step() -> None:
    """A 0.49 trial charge before 14.99 x 3 (+2959%) is not a step."""
    assert _segment(["0.49"] + ["14.99"] * 3) is None


def test_two_row_run_must_be_one_level() -> None:
    """A 2-row run is a series only when both amounts form one level."""
    assert _segment(["10.00", "10.90"]) is None
    assert _segment(["10.00", "10.10"]) is not None


def test_one_row_each_side_not_a_step() -> None:
    """Two rows at clearly different prices are not a step."""
    assert _segment(["10.00", "15.00"]) is None


def test_edge_step_beyond_50pct_rejected() -> None:
    """A single-row edge step of +50% is accepted, +51% is rejected."""
    accepted = _segment(["10.00"] * 5 + ["15.00"])
    assert accepted is not None
    assert accepted.price_steps == [_step("10.00", "15.00")]
    assert _segment(["10.00"] * 5 + ["15.10"]) is None


def test_two_valid_splits_is_ambiguous_falls_to_branch3() -> None:
    """Two valid splits record no step; the run is a variable bill at the median."""
    series = _segment(["100.00", "100.00", "104.00", "104.00", "108.00", "108.00"])
    assert series is not None
    assert series.price_steps == []
    assert series.current_amount == Decimal("104.00")


# --- Tier 1: Branch 3 -------------------------------------------------------------------------


def test_variable_bill_within_10pct_uses_median() -> None:
    """Amounts within +/-4% of 50.00 with no step are one variable-bill series."""
    series = _segment(["48.00", "52.00", "50.00", "49.00", "51.00", "50.00"])
    assert series is not None
    assert series.price_steps == []
    assert series.current_amount == Decimal("50.00")


def test_amounts_beyond_10pct_of_median_rejected() -> None:
    """The E7 weekly grocery amounts are not a subscription."""
    assert _segment(["35.00", "90.00", "210.00", "60.00", "150.00", "120.00"]) is None


# --- Tier 2 -----------------------------------------------------------------------------------


def test_step_ratio_uses_rounded_medians() -> None:
    """The recorded step holds the medians rounded half-up: 20.005 -> 20.01."""
    series = _segment(["20.00", "20.01", "21.01", "21.01"])
    assert series is not None
    assert series.price_steps == [_step("20.01", "21.01")]
    assert series.current_amount == Decimal("21.01")


def test_equal_rounded_medians_not_a_step() -> None:
    """A level run with sub-cent differences records no step."""
    series = _segment(["10.00", "10.01", "10.01", "10.01"])
    assert series is not None
    assert series.price_steps == []


def test_run_of_one_row() -> None:
    """A single row is a stable level of its own amount."""
    series = _segment(["12.99"])
    assert series is not None
    assert series.current_amount == Decimal("12.99")
    assert series.price_steps == []


def test_current_amount_rounded_half_up() -> None:
    """A median of 10.005 is stored as 10.01."""
    series = _segment(["10.00", "10.01"])
    assert series is not None
    assert series.current_amount == Decimal("10.01")


# --- Tier 3 -----------------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(
    base_cents=st.integers(min_value=1000, max_value=50000),
    noise=st.lists(st.integers(min_value=-50, max_value=50), min_size=2, max_size=12),
)
def test_noise_within_half_percent_of_one_level_is_stable(
    base_cents: int, noise: list[int]
) -> None:
    """Noise of +/-0.5% around one price never produces a step."""
    base = Decimal(base_cents) / Decimal(100)
    factors = [Decimal(1) + Decimal(bps) / Decimal(10000) for bps in noise]
    amounts = [round_to_cents(base * f) for f in factors]
    series = _segment(amounts)
    assert series is not None
    assert series.price_steps == []
    assert len(series.rows) == len(amounts)


@settings(max_examples=200, deadline=None)
@given(cents=st.lists(st.integers(min_value=1, max_value=100000), min_size=1, max_size=8))
def test_segment_result_rows_equal_input_rows(cents: list[int]) -> None:
    """A segmented series holds exactly the rows of the run, and steps differ."""
    run = _run([Decimal(c) / Decimal(100) for c in cents])
    series = zs._segment_by_price(run, MONTHLY)
    if series is not None:
        assert series.rows == run
        assert all(old != new for old, new in series.price_steps)


@settings(max_examples=200, deadline=None)
@given(
    base=st.integers(min_value=20, max_value=500),
    pct=st.integers(min_value=7, max_value=45),
    k=st.integers(min_value=1, max_value=5),
)
def test_current_amount_is_median_of_last_level(base: int, pct: int, k: int) -> None:
    """For a noise-free step at position k of 6, current_amount is the new price."""
    old = round_to_cents(Decimal(base))
    new = round_to_cents(Decimal(base) * (Decimal(1) + Decimal(pct) / Decimal(100)))
    series = _segment([old] * k + [new] * (6 - k))
    assert series is not None
    assert series.current_amount == new
    assert series.price_steps == [(old, new)]


def test_edge_exception_uses_interval_minimum() -> None:
    """A quarterly run (minimum 2) accepts a final single row after only 2 rows."""
    quarterly = zs.INTERVALS_BY_NAME["quarterly"]
    series = zs._segment_by_price(_run(["10.00", "10.00", "12.00"]), quarterly)
    assert series is not None
    assert series.interval_type == "quarterly"
    assert series.price_steps == [_step("10.00", "12.00")]
