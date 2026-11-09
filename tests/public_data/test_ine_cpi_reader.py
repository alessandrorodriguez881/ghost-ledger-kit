"""Tests for ledger_kit.public_data.ine_cpi: lookups, validator and loader (REQ-CPI-03, 05-07)."""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from cpi_builders import snapshot_dict
from hypothesis import given, settings
from hypothesis import strategies as st

from ledger_kit.public_data import (
    CPI_MAX_LAG_MONTHS,
    CpiPoint,
    CpiSeries,
    SnapshotError,
    load_snapshot,
    month_key,
    validate_snapshot,
)

D = Decimal


# --- lookup (REQ-CPI-06) -------------------------------------------------------------------------


def test_lookup_exact_month(cpi_s_series: CpiSeries) -> None:
    assert cpi_s_series.lookup("2026-02") == CpiPoint(
        "2026-02", "2026-02", D("100.500"), "Definitivo", False
    )


def test_lookup_gap_falls_back_to_the_earlier_month(cpi_gapped_series: CpiSeries) -> None:
    point = cpi_gapped_series.lookup("2026-02")
    assert point == CpiPoint("2026-02", "2026-01", D("100.000"), "Definitivo", True)
    assert point.is_fallback is True
    assert point.used == "2026-01"


def test_lookup_accepts_a_date(cpi_s_series: CpiSeries) -> None:
    assert cpi_s_series.lookup(date(2026, 2, 17)) == cpi_s_series.lookup("2026-02")


def test_lookup_accepts_a_datetime_with_a_time_part(cpi_s_series: CpiSeries) -> None:
    assert cpi_s_series.lookup(datetime(2026, 2, 17, 23, 59)) == cpi_s_series.lookup("2026-02")


def test_lookup_before_the_first_month_is_none(cpi_s_series: CpiSeries) -> None:
    assert cpi_s_series.lookup("2025-12") is None


def test_lookup_one_month_after_the_last_uses_the_last(cpi_s_series: CpiSeries) -> None:
    assert CPI_MAX_LAG_MONTHS == 1
    assert cpi_s_series.lookup("2026-04") == CpiPoint(
        "2026-04", "2026-03", D("101.000"), "Definitivo", True
    )


def test_lookup_one_month_after_the_last_on_the_gapped_series(
    cpi_gapped_series: CpiSeries,
) -> None:
    assert cpi_gapped_series.lookup("2026-04") == CpiPoint(
        "2026-04", "2026-03", D("101.000"), "Definitivo", True
    )


def test_lookup_two_months_after_the_last_is_none(
    cpi_s_series: CpiSeries, cpi_gapped_series: CpiSeries
) -> None:
    assert cpi_s_series.lookup("2026-05") is None
    assert cpi_gapped_series.lookup("2026-05") is None
    assert cpi_s_series.lookup("2030-01") is None


def test_lookup_lag_crosses_a_year_boundary() -> None:
    series = CpiSeries.from_mapping({"2025-11": "99.000", "2025-12": "99.500"})
    assert series.lookup("2026-01").used == "2025-12"
    assert series.lookup("2026-02") is None


@pytest.mark.parametrize("bad", ["2026-13", "2026-9", "abc", "2026-00", "", None, 20260201, True])
def test_lookup_rejects_invalid_months(cpi_s_series: CpiSeries, bad: object) -> None:
    with pytest.raises(ValueError):
        cpi_s_series.lookup(bad)  # type: ignore[arg-type]


def test_one_month_series() -> None:
    series = CpiSeries.from_mapping({"2026-01": "100.000"})
    assert series.first_month == series.last_month == "2026-01"
    assert series.lookup("2026-01").is_fallback is False
    assert series.lookup("2026-02").used == "2026-01"
    assert series.lookup("2025-12") is None


def test_empty_series_answers_nothing() -> None:
    series = CpiSeries.from_mapping({})
    assert series.first_month is None
    assert series.last_month is None
    assert series.lookup("2026-01") is None


def test_value_is_the_snapshot_text(cpi_s_series: CpiSeries) -> None:
    assert str(cpi_s_series.lookup("2026-02").value) == "100.500"
    assert str(cpi_s_series.lookup("2026-01").value) == "100.000"


def test_month_key() -> None:
    assert month_key(date(2026, 2, 17)) == "2026-02"
    assert month_key(date(999, 12, 1)) == "0999-12"


def test_series_is_immutable(cpi_s_series: CpiSeries) -> None:
    with pytest.raises(AttributeError):
        cpi_s_series.series_code = "X"  # type: ignore[misc]


def test_from_mapping_rejects_an_invalid_month() -> None:
    with pytest.raises(ValueError):
        CpiSeries.from_mapping({"2026-1": "100.000"})


def test_series_metadata_defaults(cpi_s_series: CpiSeries) -> None:
    assert cpi_s_series.series_code == "IPC290751"
    assert cpi_s_series.base_year == 2025
    assert cpi_s_series.licence == "CC BY 4.0"


# --- validator (REQ-CPI-03) ----------------------------------------------------------------------


def test_valid_snapshot_passes() -> None:
    validate_snapshot(snapshot_dict())


def _with_entry(target: str, /, **changes: object) -> dict:
    data = snapshot_dict()
    for entry in data["values"]:
        if entry["month"] == target:
            entry.update(changes)
    return data


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (
            snapshot_dict({"2019-04": "100.000", "2019-06": "100.500"}),
            "gap after 2019-04: next month is 2019-06",
        ),
        (
            snapshot_dict({"2020-04": "100.000", "2020-05": "0.000"}),
            "non-positive value at 2020-05",
        ),
        (
            snapshot_dict({"2026-08": "104.638", "2026-09": "104.97"}),
            "value at 2026-09 does not have three decimals: '104.97'",
        ),
        (
            snapshot_dict(series_code="IPC251852"),
            "series IPC251852 (base 2021) stops in 2025-12; use IPC290751",
        ),
        (snapshot_dict(series_code="IPC999999"), "unexpected series code 'IPC999999'"),
        (snapshot_dict(base_year=2021), "base year 2021 is not 2025"),
        (snapshot_dict(base_year=True), "base year True is not 2025"),
        (snapshot_dict(first_month="2025-12"), "first_month '2025-12' differs"),
        (snapshot_dict(last_month="2026-04"), "last_month '2026-04' differs"),
        (snapshot_dict(extra="x"), "unexpected key 'extra'"),
        (snapshot_dict({}), "the snapshot has no values"),
        (_with_entry("2026-02", status=""), "empty status at 2026-02"),
        (_with_entry("2026-02", status="  "), "empty status at 2026-02"),
        (_with_entry("2026-02", value=100.5), "value at 2026-02 does not have three decimals"),
        (_with_entry("2026-02", value="-1.000"), "value at 2026-02 does not have three decimals"),
        (_with_entry("2026-02", month="2026-2"), "invalid month '2026-2'"),
    ],
)
def test_validator_rejections(data: dict, message: str) -> None:
    with pytest.raises(SnapshotError) as info:
        validate_snapshot(data)
    assert message in str(info.value)


def test_validator_rejects_a_missing_key() -> None:
    data = snapshot_dict()
    del data["licence"]
    with pytest.raises(SnapshotError, match="missing key 'licence'"):
        validate_snapshot(data)


def test_validator_rejects_a_repeated_month() -> None:
    data = snapshot_dict()
    data["values"].insert(1, dict(data["values"][0]))
    with pytest.raises(SnapshotError, match="repeated month 2026-01"):
        validate_snapshot(data)


def test_validator_rejects_months_out_of_order() -> None:
    data = snapshot_dict()
    data["values"][0], data["values"][1] = data["values"][1], data["values"][0]
    data["first_month"], data["last_month"] = "2026-02", "2026-03"
    with pytest.raises(SnapshotError, match="out of order"):
        validate_snapshot(data)


def test_validator_rejects_an_entry_with_extra_keys() -> None:
    data = _with_entry("2026-01", note="x")
    with pytest.raises(SnapshotError, match="must have exactly"):
        validate_snapshot(data)


def test_validator_rejects_a_non_object() -> None:
    with pytest.raises(SnapshotError, match="not a JSON object"):
        validate_snapshot([])


def test_snapshot_error_is_a_value_error() -> None:
    assert issubclass(SnapshotError, ValueError)


# --- loader (REQ-CPI-05) -------------------------------------------------------------------------


def _write(tmp_path: Path, data: object, name: str = "cpi.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def test_load_snapshot_of_a_tiny_valid_file(tmp_path: Path) -> None:
    series = load_snapshot(_write(tmp_path, snapshot_dict()))
    assert series.series_code == "IPC290751"
    assert series.series_name == "Nacional. Índice general. Índice"
    assert series.base_year == 2025
    assert (series.first_month, series.last_month) == ("2026-01", "2026-03")
    assert series.retrieved_on == "2026-11-09"
    assert series.licence == "CC BY 4.0"
    assert series.attribution.startswith("Elaboración propia")
    assert series.no_endorsement.startswith("The INE does not take part")
    assert series.lookup("2026-02").value == D("100.500")


def test_load_snapshot_accepts_crlf(tmp_path: Path) -> None:
    path = tmp_path / "crlf.json"
    text = json.dumps(snapshot_dict(), ensure_ascii=False, indent=2).replace("\n", "\r\n")
    path.write_bytes(text.encode("utf-8"))
    assert load_snapshot(path).last_month == "2026-03"


def test_load_snapshot_missing_file() -> None:
    with pytest.raises(SnapshotError) as info:
        load_snapshot(Path("missing.json"))
    assert str(info.value) == "cannot read missing.json: file not found"


def test_load_snapshot_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(SnapshotError, match="invalid JSON"):
        load_snapshot(path)


def test_load_snapshot_not_utf8(tmp_path: Path) -> None:
    path = tmp_path / "latin1.json"
    path.write_bytes('{"a": "Índice"}'.encode("latin-1"))
    with pytest.raises(SnapshotError, match="not UTF-8"):
        load_snapshot(path)


def test_load_snapshot_names_the_file_on_an_invalid_snapshot(tmp_path: Path) -> None:
    path = _write(tmp_path, snapshot_dict({"2019-04": "100.000", "2019-06": "100.500"}))
    with pytest.raises(SnapshotError) as info:
        load_snapshot(path)
    assert str(path) in str(info.value)
    assert "gap after 2019-04: next month is 2019-06" in str(info.value)
    assert "\n" not in str(info.value)


# --- properties (REQ-CPI-07) ---------------------------------------------------------------------


def _month_text(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


_MONTHS = st.builds(_month_text, st.integers(2015, 2028), st.integers(1, 12))
_VALUES = st.decimals(min_value=D("1"), max_value=D("999"), places=3).map(str)


@settings(max_examples=200)
@given(mapping=st.dictionaries(_MONTHS, _VALUES, max_size=30), requested=_MONTHS)
def test_lookup_never_answers_a_later_month(mapping: dict[str, str], requested: str) -> None:
    series = CpiSeries.from_mapping(mapping)
    point = series.lookup(requested)
    if point is None:
        return
    assert point.requested == requested
    assert point.used <= requested
    assert point.used in mapping
    assert point.value == D(mapping[point.used])
    assert point.is_fallback is (point.used != requested)
    # Only a gap or the one-month lag after the last month may fall back.
    if requested > series.last_month:
        assert point.used == series.last_month


@settings(max_examples=200)
@given(mapping=st.dictionaries(_MONTHS, _VALUES, min_size=1, max_size=30), requested=_MONTHS)
def test_lookup_none_only_outside_the_answerable_range(
    mapping: dict[str, str], requested: str
) -> None:
    series = CpiSeries.from_mapping(mapping)
    point = series.lookup(requested)
    year, month = (int(part) for part in series.last_month.split("-"))
    after_lag = f"{year + month // 12:04d}-{month % 12 + 1:02d}"
    answerable = series.first_month <= requested <= after_lag
    assert (point is not None) is answerable


@settings(max_examples=200)
@given(start=st.integers(2017 * 12, 2030 * 12), length=st.integers(1, 40), drop=st.data())
def test_contiguous_snapshot_passes_and_dropping_an_interior_month_fails(
    start: int, length: int, drop: st.DataObject
) -> None:
    months = [f"{(start + i) // 12:04d}-{(start + i) % 12 + 1:02d}" for i in range(length)]
    values = {m: f"{100 + i}.000" for i, m in enumerate(months)}
    validate_snapshot(snapshot_dict(values))
    if length >= 3:
        index = drop.draw(st.integers(1, length - 2))
        del values[months[index]]
        with pytest.raises(SnapshotError, match="gap after"):
            validate_snapshot(snapshot_dict(values))
