"""Tests for scripts/fetch_ine_cpi.py with a fake opener; the network is never touched.

Every payload here is **synthetic** (values made up for the test, not INE figures); its shape
is the real one of the INE API with ``tip=A`` (REQ-CPI-02 source facts).
"""

from __future__ import annotations

import ast
import importlib.util
import io
import json
import re
import socket
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from ledger_kit.public_data.ine_cpi import validate_snapshot

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "fetch_ine_cpi.py"
TODAY = date(2026, 11, 9)
ATTRIBUTION = "Elaboración propia con datos extraídos del sitio web del INE: www.ine.es"
NO_ENDORSEMENT = "The INE does not take part in, sponsor or support this reuse."


def _load_script():
    """Load scripts/fetch_ine_cpi.py by path (scripts/ is not a package)."""
    spec = importlib.util.spec_from_file_location("fetch_ine_cpi", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["fetch_ine_cpi"] = module
    spec.loader.exec_module(module)
    return module


fetch = _load_script()


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail the test if anything tries to open a socket connection (REQ-CPI-04)."""

    def _blocked(*_args: Any, **_kwargs: Any) -> None:
        pytest.fail("a test of fetch_ine_cpi tried to touch the network")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked)


# --- synthetic payloads ---------------------------------------------------------------------------


def _months(first: str, count: int) -> list[tuple[int, int]]:
    year, month = int(first[:4]), int(first[5:])
    out = []
    for _ in range(count):
        out.append((year, month))
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return out


def _entry(year: int, month: int, valor: Any, status: str | None = "Definitivo") -> dict:
    entry: dict[str, Any] = {
        "Fecha": f"{year:04d}-{month:02d}-01T00:00:00.000+02:00",
        "T3_Periodo": f"M{month:02d}",
        "Anyo": year,
        "Valor": valor,
    }
    if status is not None:
        entry["T3_TipoDato"] = status
    return entry


def _payload(first: str = "2017-01", count: int = 117, **overrides: Any) -> dict:
    data = [
        _entry(y, m, Decimal("80.000") + Decimal("0.250") * i)  # synthetic, three decimals
        for i, (y, m) in enumerate(_months(first, count))
    ]
    payload: dict[str, Any] = {
        "COD": "IPC290751",
        "Nombre": "Nacional. Índice general. Índice ",  # trailing space, as the real API
        "T3_Unidad": "Índice",
        "T3_Escala": " ",
        "Data": data,
    }
    payload.update(overrides)
    return payload


def _json_body(payload: dict) -> bytes:
    """Serialise the payload with every Decimal as a JSON number (as the INE sends `Valor`)."""
    text = json.dumps(payload, ensure_ascii=False, default=lambda o: f"@@{o}@@")
    return re.sub(r'"@@(.*?)@@"', r"\1", text).encode("utf-8")


class _Response(io.BytesIO):
    """Context-manager response with .read(), like urlopen's."""


class FakeOpener:
    """Record the request and answer with a fixed body or raise a fixed exception."""

    def __init__(self, body: bytes | None = None, exc: BaseException | None = None) -> None:
        self.body, self.exc, self.calls = body, exc, []

    def __call__(self, request: Any, *, timeout: int) -> _Response:
        self.calls.append((request, timeout))
        if self.exc is not None:
            raise self.exc
        return _Response(self.body)


def _run(tmp_path: Path, opener: FakeOpener, capsys: pytest.CaptureFixture[str]):
    out = tmp_path / "public" / "cpi.json"
    code = fetch.main(["--output", str(out)], opener=opener, today=TODAY)
    captured = capsys.readouterr()
    return code, out, captured.out, captured.err


# --- success path ------------------------------------------------------------------------------


def test_success_writes_the_snapshot(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    opener = FakeOpener(_json_body(_payload()))
    code, out, stdout, stderr = _run(tmp_path, opener, capsys)
    assert code == 0
    assert stderr == ""
    assert stdout == f"wrote {out}: 117 months, 2017-01 to 2026-09\n"
    data = json.loads(out.read_text(encoding="utf-8"))
    assert list(data) == list(fetch.SNAPSHOT_KEYS)
    assert data["series_code"] == "IPC290751"
    assert data["series_name"] == "Nacional. Índice general. Índice"
    assert data["table"] == 76125
    assert data["base_year"] == 2025
    assert data["retrieved_on"] == "2026-11-09"
    assert data["licence"] == "CC BY 4.0"
    assert data["attribution"] == ATTRIBUTION
    assert data["no_endorsement"] == NO_ENDORSEMENT
    assert (data["first_month"], data["last_month"]) == ("2017-01", "2026-09")
    assert data["values"][0] == {"month": "2017-01", "value": "80.000", "status": "Definitivo"}
    assert data["values"][1]["value"] == "80.250"
    assert all(isinstance(v["value"], str) for v in data["values"])
    validate_snapshot(data)


def test_request_url_timeout_and_headers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    opener = FakeOpener(_json_body(_payload()))
    _run(tmp_path, opener, capsys)
    [(request, timeout)] = opener.calls
    assert request.full_url == fetch.build_url(TODAY)
    assert timeout == fetch.FETCH_TIMEOUT_SECONDS
    assert request.get_header("Accept") == "application/json"


def test_build_url() -> None:
    url = fetch.build_url(date(2026, 11, 9))
    assert url.startswith("https://servicios.ine.es/wstempus/js/ES/DATOS_SERIE/IPC290751?")
    assert url.endswith("?date=20170101:20261109&tip=A")


def test_output_is_utf8_with_lf_and_final_newline(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _code, out, _stdout, _stderr = _run(tmp_path, FakeOpener(_json_body(_payload())), capsys)
    raw = out.read_bytes()
    assert b"\r\n" not in raw
    assert raw.endswith(b"}\n")
    assert "Índice".encode() in raw  # ensure_ascii=False
    assert raw.decode("utf-8").startswith('{\n  "series_code": "IPC290751",\n')


def test_no_temporary_file_is_left(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _code, out, _stdout, _stderr = _run(tmp_path, FakeOpener(_json_body(_payload())), capsys)
    assert sorted(p.name for p in out.parent.iterdir()) == ["cpi.json"]


def test_value_is_padded_to_three_decimals() -> None:
    payload = _payload(count=2)
    payload["Data"][1]["Valor"] = Decimal("104.9")
    snapshot = fetch.build_snapshot(payload, retrieved_on=TODAY)
    assert snapshot["values"][1]["value"] == "104.900"


def test_integer_and_string_values_are_read_as_decimal() -> None:
    payload = _payload(count=2)
    payload["Data"][0]["Valor"] = 105
    payload["Data"][1]["Valor"] = "104.978"
    snapshot = fetch.build_snapshot(payload, retrieved_on=TODAY)
    assert [v["value"] for v in snapshot["values"]] == ["105.000", "104.978"]


def test_json_number_is_parsed_without_float() -> None:
    opener = FakeOpener(b'{"COD": "IPC290751", "Data": [{"Valor": 104.978}]}')
    payload = fetch.fetch_json("https://example.invalid", opener=opener)
    assert payload["Data"][0]["Valor"] == Decimal("104.978")
    assert isinstance(payload["Data"][0]["Valor"], Decimal)


def test_entries_before_2017_are_dropped() -> None:
    payload = _payload(first="2016-11", count=5)
    snapshot = fetch.build_snapshot(payload, retrieved_on=TODAY)
    assert [v["month"] for v in snapshot["values"]] == ["2017-01", "2017-02", "2017-03"]


def test_provisional_status_is_kept_as_received() -> None:
    payload = _payload(count=3)
    payload["Data"][2]["T3_TipoDato"] = "Provisional"
    snapshot = fetch.build_snapshot(payload, retrieved_on=TODAY)
    assert snapshot["values"][2]["status"] == "Provisional"


# --- error paths -------------------------------------------------------------------------------


def _assert_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], opener: FakeOpener, line: str
) -> None:
    code, out, stdout, stderr = _run(tmp_path, opener, capsys)
    assert code == 1
    assert stdout == ""
    assert stderr == f"error: {line}\n"
    assert not out.exists()


def test_old_series_code_leaves_the_existing_file_untouched(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "public" / "cpi.json"
    out.parent.mkdir()
    out.write_bytes(b'{"keep": "me"}\r\n')
    opener = FakeOpener(_json_body(_payload(COD="IPC251852")))
    code = fetch.main(["--output", str(out)], opener=opener, today=TODAY)
    stderr = capsys.readouterr().err
    assert code == 1
    assert stderr == "error: unexpected series code 'IPC251852' (expected 'IPC290751')\n"
    assert out.read_bytes() == b'{"keep": "me"}\r\n'
    assert sorted(p.name for p in out.parent.iterdir()) == ["cpi.json"]


def test_series_starting_late(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    opener = FakeOpener(_json_body(_payload(first="2018-03", count=10)))
    _assert_error(tmp_path, capsys, opener, "the series starts at 2018-03, later than 2017-01")


def test_more_than_three_decimals(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    payload = _payload(count=117)
    payload["Data"][-1]["Valor"] = Decimal("104.9781")
    line = "value for 2026-09 has more than three decimals: 104.9781"
    _assert_error(tmp_path, capsys, FakeOpener(_json_body(payload)), line)


def test_missing_status(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    payload = _payload(count=117)
    del payload["Data"][-1]["T3_TipoDato"]
    _assert_error(tmp_path, capsys, FakeOpener(_json_body(payload)), "no status for 2026-09")


def test_empty_status(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    payload = _payload(count=3)
    payload["Data"][1]["T3_TipoDato"] = " "
    _assert_error(tmp_path, capsys, FakeOpener(_json_body(payload)), "no status for 2017-02")


def test_unknown_period(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    payload = _payload(count=3)
    payload["Data"][1]["T3_Periodo"] = "M13"
    line = "unexpected period 'M13' in year 2017"
    _assert_error(tmp_path, capsys, FakeOpener(_json_body(payload)), line)


def test_payload_without_data(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    payload = _payload()
    del payload["Data"]
    line = "the INE API payload has no Data"
    _assert_error(tmp_path, capsys, FakeOpener(_json_body(payload)), line)


def test_gap_in_the_payload(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    payload = _payload(count=5)
    del payload["Data"][2]
    line = "gap after 2017-02: next month is 2017-04"
    _assert_error(tmp_path, capsys, FakeOpener(_json_body(payload)), line)


def test_non_positive_value(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    payload = _payload(count=3)
    payload["Data"][1]["Valor"] = Decimal("0")
    line = "non-positive value at 2017-02"
    _assert_error(tmp_path, capsys, FakeOpener(_json_body(payload)), line)


def test_url_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    opener = FakeOpener(exc=URLError("timed out"))
    _assert_error(tmp_path, capsys, opener, "cannot reach the INE API: timed out")


def test_http_error_is_caught_before_url_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exc = HTTPError("https://example.invalid", 404, "Not Found", hdrs=None, fp=None)
    _assert_error(tmp_path, capsys, FakeOpener(exc=exc), "HTTP error 404 from the INE API")


def test_timeout_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    opener = FakeOpener(exc=TimeoutError())
    _assert_error(tmp_path, capsys, opener, "cannot reach the INE API: timed out")


def test_body_that_is_not_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    opener = FakeOpener(b"<html>maintenance</html>")
    _assert_error(tmp_path, capsys, opener, "the INE API did not return JSON")


def test_check_snapshot_rejects_the_old_series() -> None:
    snapshot = fetch.build_snapshot(_payload(count=2), retrieved_on=TODAY)
    snapshot["series_code"] = "IPC251852"
    with pytest.raises(fetch.FetchError, match="IPC251852 \\(base 2021\\) stops in 2025-12"):
        fetch.check_snapshot(snapshot)


def test_check_snapshot_rejects_a_repeated_month() -> None:
    payload = _payload(count=2)
    payload["Data"].append(dict(payload["Data"][1]))
    with pytest.raises(fetch.FetchError, match="repeated month 2017-02"):
        fetch.build_snapshot(payload, retrieved_on=TODAY)


# --- hygiene -----------------------------------------------------------------------------------


def test_script_imports_only_the_standard_library() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0
            roots.add(node.module.split(".")[0])
    roots.discard("__future__")
    assert roots, "the scan found no import"
    assert roots <= set(sys.stdlib_module_names), roots - set(sys.stdlib_module_names)
    assert "ledger_kit" not in roots


def test_script_never_uses_float_or_reads_the_clock_below_main() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name != "main":
            source = ast.unparse(node)
            assert "float(" not in source, node.name
            assert ".today(" not in source and ".now(" not in source, node.name


# --- drift guard (DN-CPI-09) -------------------------------------------------------------------


@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
@given(
    values=st.lists(
        st.decimals(min_value=Decimal("0.001"), max_value=Decimal("999.999"), places=3),
        min_size=1,
        max_size=150,
    ),
    lead=st.integers(0, 3),
)
def test_build_snapshot_output_passes_the_library_validator(
    values: list[Decimal], lead: int
) -> None:
    data = [_entry(2016, 12 - i, Decimal("50.000")) for i in range(lead)]  # dropped (pre-2017)
    data += [_entry(y, m, v) for (y, m), v in zip(_months("2017-01", len(values)), values)]
    payload = _payload(count=1)
    payload["Data"] = data
    snapshot = fetch.build_snapshot(payload, retrieved_on=TODAY)
    validate_snapshot(snapshot)
    assert len(snapshot["values"]) == len(values)
    assert snapshot["first_month"] == "2017-01"
