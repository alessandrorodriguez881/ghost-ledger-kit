"""Tests for find_series: Phases 1 and 3 with the acceptance guard (Task Z7) and the
Phase 2 extend-and-merge step (Task Z8)."""

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from apps.zombie_subscriptions.detectors import utils as zs
from ledger_kit.utils.money import round_to_cents

START = date(2026, 1, 5)
PRICES = ["10.00", "10.50", "12.99", "15.99", "50.00"]


def _rows_at(
    entries: list[tuple[int, str | Decimal]], counterparty: str = "CLOUDVAULT"
) -> list[dict]:
    """Build rows from (day offset from START, amount) pairs; source_row is the list index."""
    return [
        {
            "date": START + timedelta(days=offset),
            "amount": Decimal(amount),
            "counterparty": counterparty,
            "source_ref": f"t.csv:{i}",
            "source_row": i,
        }
        for i, (offset, amount) in enumerate(entries)
    ]


def _monthly(amounts: list[str] | list[Decimal]) -> list[dict]:
    """Build monthly rows (30-day gaps) with the given amounts."""
    return _rows_at([(30 * i, a) for i, a in enumerate(amounts)])


def _rows_of(series: zs.Series) -> list[int]:
    """Return the source_row numbers of a series."""
    return [r["source_row"] for r in series.rows]


# --- Tier 1: acceptance examples --------------------------------------------------------------


def test_zs_acceptance_e3_parallel_different_amounts_two_series(builders: SimpleNamespace) -> None:
    """E3: interleaved 2.99 / 0.99 monthly charges are two series, never merged."""
    series = zs.find_series(builders.rows_e3())
    assert [s.current_amount for s in series] == [Decimal("2.99"), Decimal("0.99")]
    for s in series:
        assert s.interval_type == "monthly"
        assert len(s.rows) == 3
        assert s.price_steps == []


def test_zs_acceptance_e4_parallel_same_amount_two_series(builders: SimpleNamespace) -> None:
    """E4: interleaved 10.99 charges split into the rows 0, 2, 4 and 1, 3, 5."""
    series = zs.find_series(builders.rows_e4())
    assert [_rows_of(s) for s in series] == [[0, 2, 4], [1, 3, 5]]
    assert all(s.current_amount == Decimal("10.99") for s in series)


def test_zs_acceptance_e6_two_supermarket_charges_no_series(builders: SimpleNamespace) -> None:
    """E6: two charges 30 days apart are below the monthly minimum."""
    assert zs.find_series(builders.rows_e6()) == []


def test_zs_acceptance_e7_weekly_varying_amounts_no_series(builders: SimpleNamespace) -> None:
    """E7: weekly grocery charges with varying amounts are not a subscription."""
    assert zs.find_series(builders.rows_e7()) == []


def test_zs_acceptance_e7b_weekly_shopping_no_series(builders: SimpleNamespace) -> None:
    """E7b: 26 weekly shopping charges give no series (quarterly pairs hit the span guard)."""
    assert zs.find_series(builders.rows_weekly_shopping()) == []


# --- Tier 1: basic series and the span guard --------------------------------------------------


def test_stable_monthly_series_found() -> None:
    """Three monthly charges of 12.99 are one stable monthly series."""
    series = zs.find_series(_monthly(["12.99"] * 3))
    assert len(series) == 1
    assert series[0].interval_type == "monthly"
    assert series[0].current_amount == Decimal("12.99")
    assert _rows_of(series[0]) == [0, 1, 2]


def test_stable_weekly_needs_four() -> None:
    """Weekly needs four charges: three give no series, four give one."""
    three = _rows_at([(7 * i, "5.00") for i in range(3)])
    four = _rows_at([(7 * i, "5.00") for i in range(4)])
    assert zs.find_series(three) == []
    found = zs.find_series(four)
    assert [s.interval_type for s in found] == ["weekly"]


def test_quarterly_pair_accepted_when_no_other_rows_in_span() -> None:
    """Two equal charges 91 days apart are a quarterly series when nothing lies between them."""
    series = zs.find_series(_rows_at([(0, "20.00"), (91, "20.00")]))
    assert [s.interval_type for s in series] == ["quarterly"]


def test_yearly_pair_accepted_when_no_other_rows_in_span() -> None:
    """Two equal charges 365 days apart are a yearly series when nothing lies between them."""
    series = zs.find_series(_rows_at([(0, "20.00"), (365, "20.00")]))
    assert [s.interval_type for s in series] == ["yearly"]


def test_quarterly_pair_rejected_when_other_rows_in_span() -> None:
    """A row between two quarterly charges of the same key blocks the series."""
    assert zs.find_series(_rows_at([(0, "20.00"), (40, "55.00"), (91, "20.00")])) == []


def test_yearly_pair_rejected_when_other_rows_in_span() -> None:
    """A row between two yearly charges of the same key blocks the series."""
    assert zs.find_series(_rows_at([(0, "20.00"), (100, "33.00"), (365, "20.00")])) == []


def test_weekly_supermarket_key_makes_no_quarterly_series(builders: SimpleNamespace) -> None:
    """The E7b fixture plus a 27th row (a third 40.00 charge) still gives no series."""
    rows = builders.rows_weekly_shopping()
    extra_day = date(2026, 5, 4) + timedelta(days=7 * 26)
    rows.append(builders.debit_row("zs_fixture.csv:26", extra_day, "40.00", "FRESHCO"))
    assert zs.find_series(rows) == []


# --- Tier 2 -----------------------------------------------------------------------------------


def test_find_series_empty_and_single_row() -> None:
    """No rows and one row both give an empty list."""
    assert zs.find_series([]) == []
    assert zs.find_series(_monthly(["12.99"])) == []


def test_below_minimum_occurrences_no_series() -> None:
    """Two monthly charges and three weekly charges are below the minimums."""
    assert zs.find_series(_monthly(["12.99"] * 2)) == []
    assert zs.find_series(_rows_at([(7 * i, "5.00") for i in range(3)])) == []


@pytest.mark.parametrize(("gap", "found"), [(26, False), (27, True), (33, True), (34, False)])
def test_gap_tolerance_boundaries(gap: int, found: bool) -> None:
    """Monthly gaps of 27 and 33 days are series; 26 and 34 are not."""
    series = zs.find_series(_rows_at([(0, "9.99"), (gap, "9.99"), (2 * gap, "9.99")]))
    assert bool(series) is found


def test_duplicate_source_ref_does_not_crash() -> None:
    """A row repeated with the same source_ref is handled without error."""
    rows = _monthly(["12.99"] * 3)
    rows.append(dict(rows[1]))
    assert isinstance(zs.find_series(rows), list)


def test_interleaved_series_not_merged(builders: SimpleNamespace) -> None:
    """Calendar-overlapping series of the same key stay two series."""
    series = zs.find_series(builders.rows_e4())
    assert len(series) == 2
    assert all(len(s.rows) == 3 for s in series)


# --- Tier 3 (part 1) --------------------------------------------------------------------------

_STRUCTURED = st.lists(
    st.tuples(
        st.sampled_from([7, 30, 91, 365]),
        st.integers(min_value=-3, max_value=3),
        st.sampled_from(PRICES),
    ),
    max_size=15,
)


def _structured_rows(specs: list[tuple[int, int, str]]) -> list[dict]:
    """Build rows whose gaps are a nominal interval plus jitter; source_row is the index."""
    entries: list[tuple[int, str | Decimal]] = []
    offset = 0
    for gap, jitter, amount in specs:
        offset += gap + jitter
        entries.append((offset, amount))
    return _rows_at(entries)


def _step_cases() -> list[list[dict]]:
    """Return E1, E2 and downgrade style row lists for the order-invariance tests."""
    return [
        _monthly(["12.99"] * 5 + ["15.99"]),
        _monthly(["9.99"] * 3 + ["12.99"] * 3),
        _monthly(["14.99"] * 3 + ["9.99"] * 3),
        _monthly(["9.99"] + ["12.99"] * 5),
    ]


@settings(max_examples=200, deadline=None)
@given(specs=_STRUCTURED, data=st.data())
def test_find_series_row_order_invariant(
    specs: list[tuple[int, int, str]], data: st.DataObject
) -> None:
    """Shuffled input rows give identical series."""
    rows = _structured_rows(specs)
    shuffled = data.draw(st.permutations(rows))
    assert zs.find_series(list(shuffled)) == zs.find_series(rows)


@settings(max_examples=200, deadline=None)
@given(specs=_STRUCTURED)
def test_series_rows_are_subset_and_disjoint(specs: list[tuple[int, int, str]]) -> None:
    """Every series row comes from the input and no row is in two series."""
    rows = _structured_rows(specs)
    input_refs = {r["source_ref"] for r in rows}
    cited = [r["source_ref"] for s in zs.find_series(rows) for r in s.rows]
    assert set(cited) <= input_refs
    assert len(cited) == len(set(cited))


@settings(max_examples=200, deadline=None)
@given(specs=_STRUCTURED)
def test_series_rows_are_date_sorted(specs: list[tuple[int, int, str]]) -> None:
    """The rows of each series are ordered by date_key."""
    for s in zs.find_series(_structured_rows(specs)):
        assert s.rows == sorted(s.rows, key=zs.date_key)


# --- Task Z8, Tier 1: acceptance (Phase 2 extend and merge) -----------------------------------


def test_zs_acceptance_e1_step_change_detected(builders: SimpleNamespace) -> None:
    """E1: 5 x 12.99 then 15.99 is one series of six rows with the step recorded."""
    series = zs.find_series(builders.rows_e1())
    assert len(series) == 1
    assert len(series[0].rows) == 6
    assert series[0].current_amount == Decimal("15.99")
    assert series[0].price_steps == [(Decimal("12.99"), Decimal("15.99"))]


def test_zs_acceptance_e2_step_change_two_levels_merged(builders: SimpleNamespace) -> None:
    """E2: 3 x 9.99 then 3 x 12.99 are merged into one series with one step."""
    series = zs.find_series(builders.rows_e2())
    assert len(series) == 1
    assert len(series[0].rows) == 6
    assert series[0].price_steps == [(Decimal("9.99"), Decimal("12.99"))]


def test_downgrade_merged_with_downward_step(builders: SimpleNamespace) -> None:
    """A downgrade is merged into one series that records the downward step."""
    series = zs.find_series(builders.rows_downgrade())
    assert len(series) == 1
    assert series[0].price_steps == [(Decimal("14.99"), Decimal("9.99"))]
    assert series[0].current_amount == Decimal("9.99")


# --- Task Z8, Tier 1: backward extension ------------------------------------------------------


def test_early_step_first_charge() -> None:
    """One 9.99 then five 12.99: backward extension finds the early step."""
    series = zs.find_series(_monthly(["9.99"] + ["12.99"] * 5))
    assert len(series) == 1
    assert len(series[0].rows) == 6
    assert series[0].price_steps == [(Decimal("9.99"), Decimal("12.99"))]


def test_early_step_second_charge() -> None:
    """Two 9.99 then four 12.99: two backward extensions find the early step."""
    series = zs.find_series(_monthly(["9.99"] * 2 + ["12.99"] * 4))
    assert len(series) == 1
    assert len(series[0].rows) == 6
    assert series[0].price_steps == [(Decimal("9.99"), Decimal("12.99"))]


def test_step_within_one_bucket_found() -> None:
    """12.99 x 3 then 13.79 x 3 share one price bucket and the step is still recorded."""
    series = zs.find_series(_monthly(["12.99"] * 3 + ["13.79"] * 3))
    assert len(series) == 1
    assert series[0].price_steps == [(Decimal("12.99"), Decimal("13.79"))]


# --- Task Z8, Tier 1: guards ------------------------------------------------------------------


def test_trial_charge_28_days_before_series_not_absorbed() -> None:
    """A 0.49 trial 28 days before 14.99 x 3 stays outside the series."""
    entries = [(0, "0.49"), (28, "14.99"), (58, "14.99"), (88, "14.99")]
    series = zs.find_series(_rows_at(entries))
    assert len(series) == 1
    assert _rows_of(series[0]) == [1, 2, 3]
    assert series[0].price_steps == []


def test_stray_row_on_cadence_with_implausible_price_not_absorbed() -> None:
    """12.99 x 4 followed on cadence by a 4.99 row: the 4.99 row is not absorbed."""
    series = zs.find_series(_monthly(["12.99"] * 4 + ["4.99"]))
    assert len(series) == 1
    assert _rows_of(series[0]) == [0, 1, 2, 3]


# --- Task Z8, Tier 2 --------------------------------------------------------------------------


@pytest.mark.parametrize(("gap", "absorbed"), [(33, True), (34, False)])
def test_extension_tolerance_boundaries_forward(gap: int, absorbed: bool) -> None:
    """A row 33 days after the last charge extends the series; 34 days does not."""
    entries = [(0, "12.99"), (30, "12.99"), (60, "12.99"), (60 + gap, "15.99")]
    series = zs.find_series(_rows_at(entries))
    assert len(series) == 1
    assert len(series[0].rows) == (4 if absorbed else 3)


@pytest.mark.parametrize(("gap", "absorbed"), [(33, True), (34, False)])
def test_extension_tolerance_boundaries_backward(gap: int, absorbed: bool) -> None:
    """A row 33 days before the first charge extends the series; 34 days does not."""
    entries = [(0, "9.99"), (gap, "12.99"), (gap + 30, "12.99"), (gap + 60, "12.99")]
    series = zs.find_series(_rows_at(entries))
    assert len(series) == 1
    assert len(series[0].rows) == (4 if absorbed else 3)


def test_extension_picks_closest_candidate() -> None:
    """Of two forward candidates the one nearest to the expected date is taken."""
    entries = [(0, "12.99"), (30, "12.99"), (60, "12.99"), (89, "15.99"), (93, "15.99")]
    series = zs.find_series(_rows_at(entries))
    assert len(series) == 1
    assert _rows_of(series[0]) == [0, 1, 2, 3]


def test_phase2_terminates_on_many_rows() -> None:
    """A 200-row ledger with one price step finishes and gives one series."""
    series = zs.find_series(_monthly(["12.99"] * 100 + ["15.99"] * 100))
    assert len(series) == 1
    assert len(series[0].rows) == 200
    assert series[0].price_steps == [(Decimal("12.99"), Decimal("15.99"))]


# --- Task Z8, Tier 3 --------------------------------------------------------------------------


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


@settings(max_examples=200, deadline=None)
@given(
    base=st.integers(min_value=20, max_value=500),
    pct=st.integers(min_value=5, max_value=50),
    k=st.integers(min_value=1, max_value=5),
)
def test_step_at_every_position_found_once(base: int, pct: int, k: int) -> None:
    """A noise-free step of 5-50% at any of k = 1..5 gives exactly one series, one step."""
    amounts = _stepped_amounts(base, Decimal(pct), k, _NO_NOISE)
    series = zs.find_series(_monthly(amounts))
    assert len(series) == 1
    assert len(series[0].rows) == 6
    assert series[0].price_steps == [(amounts[0], amounts[-1])]
    assert series[0].current_amount == amounts[-1]


@settings(max_examples=200, deadline=None)
@given(
    base=st.integers(min_value=20, max_value=500),
    pct=st.integers(min_value=7, max_value=45),
    k=st.integers(min_value=1, max_value=5),
    noise=_NOISE,
)
def test_noisy_step_found_once(base: int, pct: int, k: int, noise: list[int]) -> None:
    """With +/-0.5% noise a step of 7-45% still gives one series with one recorded step."""
    amounts = _stepped_amounts(base, Decimal(pct), k, noise)
    series = zs.find_series(_monthly(amounts))
    assert len(series) == 1
    assert len(series[0].rows) == 6
    assert len(series[0].price_steps) == 1
    old, new = series[0].price_steps[0]
    assert new > old


@settings(max_examples=200, deadline=None)
@given(
    base=st.integers(min_value=100, max_value=500),
    tenths=st.integers(min_value=-39, max_value=39),
    k=st.integers(min_value=1, max_value=5),
    noise=_NOISE,
)
def test_step_of_at_most_3_9_pct_stays_one_series_below_5_pct(
    base: int, tenths: int, k: int, noise: list[int]
) -> None:
    """With +/-0.5% noise a step of at most 3.9% (up or down) never reaches a 5% step."""
    amounts = _stepped_amounts(base, Decimal(tenths) / Decimal(10), k, noise)
    series = zs.find_series(_monthly(amounts))
    assert len(series) == 1
    assert len(series[0].rows) == 6
    for old, new in series[0].price_steps:
        assert abs(new - old) < Decimal("0.05") * old


@settings(max_examples=200, deadline=None)
@given(case=st.sampled_from(_step_cases()), data=st.data())
def test_row_order_invariant_with_steps(case: list[dict], data: st.DataObject) -> None:
    """Shuffled rows of a step-change ledger give the same series."""
    shuffled = data.draw(st.permutations(case))
    assert zs.find_series(list(shuffled)) == zs.find_series(case)
