"""Download the Spanish CPI (INE series IPC290751, base 2025) and write the committed snapshot.

Run by the developer, never by an app, a test or CI (REQ-CPI-01)::

    python scripts/fetch_ine_cpi.py [--output PATH]

One request to the INE JSON API (``tip=A`` and ``date=20170101:<today>``) returns every month
from 2017-01 on. Each ``Data`` entry gives the month (``Anyo`` + ``T3_Periodo``), the status
(``T3_TipoDato``) and the value (``Valor``, a JSON number read as ``Decimal``, never as a float).
The snapshot is checked, written to a temporary file next to the target and renamed only after
success, so a failed run leaves the existing snapshot untouched.

Standard library only: this script does not import ``ledger_kit`` (DN-CPI-09), so it repeats
the snapshot rules of ``ledger_kit.public_data.ine_cpi.validate_snapshot`` in ``check_snapshot``;
a test runs the library validator on the output of ``build_snapshot`` so the two cannot drift.

The data is INE data under CC BY 4.0: "Elaboración propia con datos extraídos del sitio web del
INE: www.ine.es". The INE does not take part in, sponsor or support this reuse.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from collections.abc import Callable
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SERIES_CODE = "IPC290751"
OLD_SERIES_CODE = "IPC251852"  # base 2021, stops in 2025-12: must not be used
API_URL = "https://servicios.ine.es/wstempus/js/ES/DATOS_SERIE/IPC290751"
FIRST_MONTH = "2017-01"
FIRST_DATE_PARAM = "20170101"  # start of the `date=` range of the request
FETCH_TIMEOUT_SECONDS = 30
TABLE = 76125
BASE_YEAR = 2025
CLASSIFICATION = "ECOICOP v2"
PERIODICITY = "monthly"
LICENCE = "CC BY 4.0"
ATTRIBUTION = "Elaboración propia con datos extraídos del sitio web del INE: www.ine.es"
NO_ENDORSEMENT = "The INE does not take part in, sponsor or support this reuse."
USER_AGENT = "ghost-ledger-kit/fetch_ine_cpi (developer snapshot refresh)"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "data" / "public" / "ine_cpi_ipc290751.json"

SNAPSHOT_KEYS = (
    "series_code",
    "series_name",
    "table",
    "base_year",
    "classification",
    "periodicity",
    "api_url",
    "retrieved_on",
    "licence",
    "attribution",
    "no_endorsement",
    "first_month",
    "last_month",
    "values",
)
_PERIOD_RE = re.compile(r"^M(0[1-9]|1[0-2])$")
_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_VALUE_RE = re.compile(r"^\d+\.\d{3}$")
_THOUSANDTH = Decimal("0.001")

Opener = Callable[..., Any]


class FetchError(Exception):
    """A step of the download failed; the message becomes the line 'error: <message>'."""


def build_url(today: date) -> str:
    """Return the one request URL: every month from 2017-01 to `today`, friendly field names."""
    return f"{API_URL}?date={FIRST_DATE_PARAM}:{today:%Y%m%d}&tip=A"


def fetch_json(url: str, *, opener: Opener = urlopen, timeout: int = FETCH_TIMEOUT_SECONDS) -> Any:
    """GET `url` with `opener` and parse the body with Decimal floats; FetchError on failure."""
    request = Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    try:
        with opener(request, timeout=timeout) as response:
            body = response.read()
    except HTTPError as exc:  # an HTTPError is a URLError: catch it first
        raise FetchError(f"HTTP error {exc.code} from the INE API") from None
    except URLError as exc:
        raise FetchError(f"cannot reach the INE API: {exc.reason}") from None
    except TimeoutError:
        raise FetchError("cannot reach the INE API: timed out") from None
    except OSError as exc:
        raise FetchError(f"cannot reach the INE API: {exc}") from None
    try:
        return json.loads(body, parse_float=Decimal)
    except ValueError:  # JSONDecodeError and UnicodeDecodeError
        raise FetchError("the INE API did not return JSON") from None


def _value_text(raw: Any, month: str) -> str:
    """Return the value as a string with exactly three decimals; padding only, never rounding."""
    if isinstance(raw, bool) or raw is None:
        raise FetchError(f"no value for {month}")
    if isinstance(raw, float):
        raise FetchError(f"value for {month} was read as a binary float")
    try:
        value = raw if isinstance(raw, Decimal) else Decimal(str(raw).strip())
    except InvalidOperation:
        raise FetchError(f"value for {month} is not a number: {raw!r}") from None
    if not value.is_finite():
        raise FetchError(f"value for {month} is not a number: {raw!r}")
    padded = value.quantize(_THOUSANDTH)
    if padded != value:
        raise FetchError(f"value for {month} has more than three decimals: {value}")
    return str(padded)


def parse_points(payload: Any) -> list[tuple[str, str, str]]:
    """Return [(month, value text, status)] from 2017-01 on, as given by the API."""
    if not isinstance(payload, dict):
        raise FetchError("the INE API payload is not a JSON object")
    code = payload.get("COD")
    if code != SERIES_CODE:
        raise FetchError(f"unexpected series code {code!r} (expected {SERIES_CODE!r})")
    data = payload.get("Data")
    if not isinstance(data, list) or not data:
        raise FetchError("the INE API payload has no Data")
    points: list[tuple[str, str, str]] = []
    for entry in data:
        if not isinstance(entry, dict):
            raise FetchError("a Data entry is not a JSON object")
        year = entry.get("Anyo")
        if not isinstance(year, int) or isinstance(year, bool) or not 1000 <= year <= 9999:
            raise FetchError(f"unexpected year {year!r}")
        period = entry.get("T3_Periodo")
        match = _PERIOD_RE.match(period) if isinstance(period, str) else None
        if match is None:
            raise FetchError(f"unexpected period {period!r} in year {year}")
        month = f"{year:04d}-{match.group(1)}"
        if month < FIRST_MONTH:
            continue
        status = entry.get("T3_TipoDato")
        if not isinstance(status, str) or not status.strip():
            raise FetchError(f"no status for {month}")
        points.append((month, _value_text(entry.get("Valor"), month), status.strip()))
    return points


def build_snapshot(payload: Any, *, retrieved_on: date) -> dict[str, Any]:
    """Build and check the snapshot object (key order of REQ-CPI-02) from an API payload."""
    points = sorted(parse_points(payload))
    if not points:
        raise FetchError(f"the INE API returned no month from {FIRST_MONTH} on")
    if points[0][0] != FIRST_MONTH:
        raise FetchError(f"the series starts at {points[0][0]}, later than {FIRST_MONTH}")
    name = payload.get("Nombre")
    if not isinstance(name, str) or not name.strip():
        raise FetchError("the INE API payload has no series name")
    snapshot = {
        "series_code": SERIES_CODE,
        "series_name": name.strip(),
        "table": TABLE,
        "base_year": BASE_YEAR,
        "classification": CLASSIFICATION,
        "periodicity": PERIODICITY,
        "api_url": API_URL,
        "retrieved_on": retrieved_on.isoformat(),
        "licence": LICENCE,
        "attribution": ATTRIBUTION,
        "no_endorsement": NO_ENDORSEMENT,
        "first_month": points[0][0],
        "last_month": points[-1][0],
        "values": [{"month": m, "value": v, "status": s} for m, v, s in points],
    }
    check_snapshot(snapshot)
    return snapshot


def _next_month(month: str) -> str:
    """Return the month after a valid 'YYYY-MM'."""
    year, number = int(month[:4]), int(month[5:])
    return f"{year + number // 12:04d}-{number % 12 + 1:02d}"


def check_snapshot(snapshot: dict[str, Any]) -> None:
    """Repeat the rules of ledger_kit's validate_snapshot (REQ-CPI-03); FetchError on a breach."""
    if tuple(snapshot) != SNAPSHOT_KEYS:
        raise FetchError("the snapshot keys are not the expected ones")
    if snapshot["series_code"] == OLD_SERIES_CODE:
        message = f"series {OLD_SERIES_CODE} (base 2021) stops in 2025-12; use {SERIES_CODE}"
        raise FetchError(message)
    if snapshot["series_code"] != SERIES_CODE or snapshot["base_year"] != BASE_YEAR:
        raise FetchError("the snapshot is not series IPC290751, base 2025")
    values = snapshot["values"]
    if not values:
        raise FetchError("the snapshot has no values")
    previous = None
    for entry in values:
        month, value, status = entry["month"], entry["value"], entry["status"]
        if not _MONTH_RE.match(month):
            raise FetchError(f"invalid month {month!r} after {previous}")
        if previous is not None and month == previous:
            raise FetchError(f"repeated month {month}")
        if previous is not None and month != _next_month(previous):
            raise FetchError(f"gap after {previous}: next month is {month}")
        if not _VALUE_RE.match(value):
            raise FetchError(f"value at {month} does not have three decimals: {value!r}")
        if Decimal(value) <= 0:
            raise FetchError(f"non-positive value at {month}")
        if not status.strip():
            raise FetchError(f"empty status at {month}")
        previous = month
    if snapshot["first_month"] != values[0]["month"] or snapshot["last_month"] != previous:
        raise FetchError("first_month or last_month differs from the entries")


def write_snapshot(snapshot: dict[str, Any], path: Path) -> None:
    """Write UTF-8 JSON with LF and a final newline through a temporary file and os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n"
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="\n", dir=path.parent, suffix=".tmp", delete=False
    )
    try:
        with handle:
            handle.write(text)
        os.replace(handle.name, path)
    except BaseException:
        Path(handle.name).unlink(missing_ok=True)
        raise


def main(
    argv: list[str] | None = None, *, opener: Opener = urlopen, today: date | None = None
) -> int:
    """Download, check and write the snapshot; return 0 on success and 1 on any error."""
    parser = argparse.ArgumentParser(description="Refresh the committed INE CPI snapshot.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="snapshot path")
    args = parser.parse_args(argv)
    day = date.today() if today is None else today
    try:
        snapshot = build_snapshot(fetch_json(build_url(day), opener=opener), retrieved_on=day)
        write_snapshot(snapshot, args.output)
    except FetchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"error: cannot write {args.output}: {exc}", file=sys.stderr)
        return 1
    count = len(snapshot["values"])
    first, last = snapshot["first_month"], snapshot["last_month"]
    print(f"wrote {args.output}: {count} months, {first} to {last}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
