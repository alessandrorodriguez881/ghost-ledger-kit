# public-cpi — Requirements

## Overview

A price increase alone says little: 18 % sounds large, but it means more or less depending on what
prices did in the same months. `public-cpi` adds **one public, official, rarely used data source** to
the Zombie Subscriptions price-increase alert: the Spanish consumer price index (IPC) published by the
INE (Instituto Nacional de Estadística). The alert then says, in one short sentence, how the price
change compares with official inflation over the same months, for example *a subscription that rose
18,0 % while the CPI changed by 2,0 %*.

It adds a fetch script, a committed snapshot of the series, a small reader in `ledger_kit`, extra
fields in the `data` of the existing alert, one sentence on the card and in the fallback template, and
the INE attribution. It adds no detector, changes no threshold, no severity and no `source_refs`, and
the demo still gives 3 tombstones and 19 alerts (1 critical, 4 warning, 14 info). The CPI is
**decoration around an alert that already fired**; it never decides whether one fires (Finance Rule 8
spirit, product non-goal "the LLM may not raise, dismiss or modify alerts" applies to this data too).

Ids are `REQ-CPI-nn`. EARS keywords: *shall*, *when*, *while*, *where*, *if ... then*. Every example
gives a concrete input and the exact expected output. Values marked **(synthetic)** belong to a test
fixture and are not claims about the INE; values marked **(INE)** are the figures given by the
requester on 9 November 2026 and are pinned by the snapshot test.

## Source facts (checked on 9 November 2026 by the requester)

These were not re-verified by the author of this spec: the web fetch was denied in session 9a. The
two items marked **unverified** are the only places where the implementer must look at the real API
response before relying on a field name (see design §9 and Q2, Q3).

- Series **IPC290751**, named `Nacional. Índice general. Índice`, table 76125, monthly, index
  **base 2025** (2025 average = 100), classification ECOICOP v2, values with **three decimals**,
  e.g. `2026 M09` = `104.978` and `2026 M08` = `104.638`, status `Definitivo` **(INE)**.
- The old base-2021 series **IPC251852** stops in December 2025 and **must not be used**.
- Public JSON API: `https://servicios.ine.es/wstempus/js/ES/DATOS_SERIE/IPC290751`, parameter `nult`
  for the last *n* periods; each `Data` entry has `Fecha` (epoch milliseconds), `FK_Periodo` (month
  1 to 12), `Anyo` and `Valor`. The status field name (`T3_TipoDato` with `tip=A`) is **unverified**.
- Licence: the INE legal notice applies **CC BY 4.0** to its statistics, requires the attribution
  *Elaboración propia con datos extraídos del sitio web del INE: www.ine.es* for processed data, and
  forbids suggesting that the INE takes part in, sponsors or supports the reuse. The requester wrote
  the sentence without accents; the committed text uses the accented Spanish form (Q1).
- As of 9 November 2026 the latest published month is **2026-09**. October 2026 is normally published
  in mid-November, so the demo is built to behave correctly with or without it (REQ-CPI-21).

---

## 1 — Fetch script and snapshot

- **REQ-CPI-01** The system shall provide `scripts/fetch_ine_cpi.py`, which uses **only the Python
  standard library** (`urllib.request`, `urllib.error`, `json`, `decimal`, `datetime`, `argparse`,
  `pathlib`), downloads series `IPC290751` from the API of the Source facts for the months from
  **2017-01** to the latest published month, and writes the snapshot of REQ-CPI-02 to
  `data/public/ine_cpi_ipc290751.json`. It shall be run by the developer, who commits the result; no
  app, test or CI step runs it. *When* any step fails (network error, HTTP error, timeout, payload
  without `Data`, series code other than `IPC290751`, a failed check of REQ-CPI-03, first month later
  than 2017-01), *then* the script shall print one line starting `error:` to stderr, exit with code 1
  and **leave any existing snapshot untouched** (the file is written to a temporary file in the same
  folder and renamed only after success). On success it prints one line
  `wrote <path>: <n> months, <first_month> to <last_month>` and exits 0.
  - Fake payload `{"COD": "IPC290751", "Nombre": "Nacional. Índice general. Índice", "Data": [...]}`
    with 117 contiguous months from 2017-01 to 2026-09 (synthetic) → snapshot with
    `"first_month": "2017-01"`, `"last_month": "2026-09"`, exit 0.
  - Payload with `"COD": "IPC251852"` → exit 1, stderr
    `error: unexpected series code 'IPC251852' (expected 'IPC290751')`, snapshot not touched.
  - Payload whose first month is `2018-03` → exit 1, stderr
    `error: the series starts at 2018-03, later than 2017-01`.
  - `urlopen` raising `URLError("timed out")` → exit 1, stderr `error: cannot reach the INE API: timed out`.

- **REQ-CPI-02** The snapshot shall be a UTF-8 JSON file (LF line endings, two-space indent, keys in
  the order below, `ensure_ascii=False`) with exactly these top-level keys:

  | Key | Content |
  |---|---|
  | `series_code` | `"IPC290751"` |
  | `series_name` | the series name as returned by the API (expected `Nacional. Índice general. Índice`) |
  | `table` | `76125` (integer) |
  | `base_year` | `2025` (integer; the index is 2025 average = 100) |
  | `classification` | `"ECOICOP v2"` |
  | `periodicity` | `"monthly"` |
  | `api_url` | `"https://servicios.ine.es/wstempus/js/ES/DATOS_SERIE/IPC290751"` |
  | `retrieved_on` | ISO date of the download, e.g. `"2026-11-09"` |
  | `licence` | `"CC BY 4.0"` |
  | `attribution` | `Elaboración propia con datos extraídos del sitio web del INE: www.ine.es` |
  | `no_endorsement` | `The INE does not take part in, sponsor or support this reuse.` |
  | `first_month`, `last_month` | `"2017-01"` and the latest month, `"YYYY-MM"` |
  | `values` | list, oldest first, of `{"month": "YYYY-MM", "value": "104.978", "status": "Definitivo"}` |

  Every `value` is a **string** with exactly three decimals, built from the JSON text with `Decimal`
  (`json.loads(..., parse_float=Decimal)`), never through `float`. `status` is copied from the API.
  `month` comes from `Anyo` and `FK_Periodo` (`Fecha` is not used: the epoch of a month start depends on
  the time zone). The script keeps every entry it receives from 2017-01 on, including provisional
  ones, and stores their status as received.
  - Entry `{"Anyo": 2026, "FK_Periodo": 9, "Valor": 104.978, ...}` with status `Definitivo` →
    `{"month": "2026-09", "value": "104.978", "status": "Definitivo"}`.
  - `"Valor": 104.9` → `"value": "104.900"` (padding is lossless); `"Valor": 104.9781` → script error
    `error: value for 2026-09 has more than three decimals: 104.9781` (no rounding, no guess).
  - An entry without a status → `error: no status for 2026-09` (the script never writes a status of
    its own).

- **REQ-CPI-03** The snapshot validator (one function in `ledger_kit/public_data/ine_cpi.py`, REQ-CPI-05,
  re-implemented in a few lines in the script, which must not import `ledger_kit`) shall reject:
  a missing or extra top-level key; `series_code` other than `IPC290751` (an explicit message for
  `IPC251852`); `base_year` other than 2025; a month that does not match `YYYY-MM`, repeats, is out of
  order or leaves a **gap** (the next month must follow the previous one); a value that is not a string of
  digits with exactly three decimals; a value that is zero or negative; an empty status; `first_month` or
  `last_month` that differs from the first and last entry.
  - Months `2019-04`, `2019-06` adjacent → `SnapshotError: gap after 2019-04: next month is 2019-06`.
  - `"value": "0.000"` at `2020-05` → `SnapshotError: non-positive value at 2020-05`.
  - `"value": "104.97"` → `SnapshotError: value at 2026-09 does not have three decimals: '104.97'`.
  - `"series_code": "IPC251852"` → `SnapshotError: series IPC251852 (base 2021) stops in 2025-12; use IPC290751`.

- **REQ-CPI-04** The tests of the script and of the snapshot shall **never touch the network**. The script
  takes the opener as a parameter (`fetch_json(url, *, opener=urlopen, timeout=...)`); tests pass a
  fake. A test module that exercises the script blocks `socket.socket.connect` with a fixture that
  fails the test if it is called. The committed snapshot is validated by REQ-CPI-03 and by the pinned
  checks of REQ-CPI-20.

---

## 2 — Reader in `ledger_kit`

- **REQ-CPI-05** The system shall provide `ledger_kit/public_data/ine_cpi.py` (stdlib only; imports no
  app and no pandas) with `load_snapshot(path=DEFAULT_SNAPSHOT_PATH) -> CpiSeries`, which reads the file,
  applies REQ-CPI-03 and returns an immutable `CpiSeries`. *If* the file is missing, unreadable or invalid,
  *then* it shall raise `SnapshotError` (a `ValueError` subclass) with a one-line message naming the
  file; it never returns a partial series. `CpiSeries` exposes `series_code`, `series_name`, `base_year`,
  `first_month`, `last_month`, `retrieved_on`, `licence`, `attribution`, `no_endorsement`, and
  `lookup(month)`. A `CpiSeries` can also be built from a mapping of month to value (tests,
  **no contiguity required**; the snapshot file is where contiguity is enforced).
  - `load_snapshot(Path("missing.json"))` → `SnapshotError: cannot read missing.json: file not found`.

- **REQ-CPI-06** `CpiSeries.lookup(month)` shall accept a `"YYYY-MM"` string or a `datetime.date` and
  return `CpiPoint(requested, used, value, status, is_fallback)` or `None`:
  1. a published month equal to the requested month → that month, `is_fallback=False`;
  2. the requested month is inside `[first_month, last_month]` but not published (a gap) → the **latest
     published month before it**, `is_fallback=True` (the caller can say which month it used);
  3. the requested month is before `first_month` → `None`;
  4. the requested month is after `last_month` → `None` (**no extrapolation**: a later month is never
     answered with an older value; see DN-CPI-03);
  5. anything that is not a valid month → `ValueError` (`"2026-13"`, `"2026-9"`, `"abc"`, a `datetime`
     with a time part is accepted as its date).
  `value` is the `Decimal` read from the snapshot string, three decimals, never rounded, never
  interpolated, never computed.
  Using the **synthetic** series `S` = {2026-01: 100.000, 2026-02: 100.500, 2026-03: 101.000} and the
  gapped series `G` = {2026-01: 100.000, 2026-03: 101.000}:
  - `S.lookup("2026-02")` → `CpiPoint("2026-02", "2026-02", Decimal("100.500"), "Definitivo", False)`.
  - `G.lookup("2026-02")` → `CpiPoint("2026-02", "2026-01", Decimal("100.000"), "Definitivo", True)`.
  - `S.lookup(date(2026, 2, 17))` equals `S.lookup("2026-02")`.
  - `S.lookup("2025-12")` → `None`; `S.lookup("2026-04")` → `None`; `G.lookup("2026-04")` → `None`.
  - `S.lookup("2026-13")` → `ValueError`.

- **REQ-CPI-07** *While* the reader answers a lookup it shall never return a month later than the
  requested month, never return a value that is not in the series, and never raise for a month that is
  merely out of range. The reader performs no arithmetic other than month comparison.
  - Property (Hypothesis): for any series and any requested month, `lookup` is `None` or
    `used <= requested`, `value` equals the series entry of `used`, and `used` is published.

- **REQ-CPI-08** The system shall provide in `ledger_kit/utils/money.py` (the only place for this
  arithmetic) `percent_change(old, new) -> Decimal` = `(new - old) / old * 100` at full `Decimal`
  precision, `round_percent(value) -> Decimal` (the **one rounding rule**: quantize to **one decimal**
  `Decimal("0.1")` with `ROUND_HALF_UP`, constant `PERCENT_DECIMALS = 1`) and
  `format_percent(value) -> str` (European format, comma, thousands full stop, a space and `%`).
  `percent_change` raises `ValueError` for `old <= 0`. Rounding is applied at the output boundary (the
  alert `data`), never to the inputs of a ratio.
  - `percent_change(Decimal("100.00"), Decimal("118.00"))` → `Decimal("18")`;
    `round_percent(...)` → `Decimal("18.0")`.
  - `percent_change(Decimal("100.000"), Decimal("102.000"))` → `Decimal("2")` → `Decimal("2.0")`.
  - `percent_change(Decimal("9.99"), Decimal("12.99"))` → `30.03003...` → `Decimal("30.0")`.
  - `percent_change(Decimal("12.99"), Decimal("15.99"))` → `23.09469...` → `Decimal("23.1")`.
  - `percent_change(Decimal("104.638"), Decimal("104.978"))` **(INE)** → `0.32493...` → `Decimal("0.3")`.
  - Half-up on the boundary: `percent_change(400, 401)` = `0.25` → `0.3`; `percent_change(400, 399)` =
    `-0.25` → `-0.3` (half away from zero, as `round_to_cents` does for negatives).
  - `format_percent(Decimal("30.0"))` → `"30,0 %"`; `Decimal("-0.3")` → `"-0,3 %"`;
    `Decimal("1234.5")` → `"1.234,5 %"`; `Decimal("0.0")` → `"0,0 %"`.
  - `percent_change(Decimal("0"), Decimal("1"))` → `ValueError`.
  - `format_index(value) -> str` shall show an index value with its three decimals and a decimal
    **comma**: `format_index(Decimal("104.978"))` → `"104,978"`, `Decimal("100.000")` → `"100,000"`.
    The snapshot and `Alert.data` keep the dot form (`"104.978"`); only the display changes, because
    `100.000` read with European separators means one hundred thousand (Finance Rule 4).

---

## 3 — CPI context in `zs.price_increase`

- **REQ-CPI-09** *When* `context["cpi"]` is a `CpiSeries`, the detector `zs.price_increase` shall add the
  CPI fields of REQ-CPI-11 to the `data` of an alert it **already decided to emit**. *When* `context` has
  no `"cpi"` key or its value is `None`, the alert shall be **identical** to today's (same `data`
  keys and values, same `id`). The detector stays a pure function: it receives the series through
  `context` and does no I/O; the app loads the snapshot (design §8, REQ-CPI-19).
  - With the ledger of the existing test `test_zs_acceptance_e1_price_increase_alert` and no `cpi` in
    `context`, `alert.data` equals exactly the six-key dict that test asserts today.

- **REQ-CPI-10** The two months compared shall be those of the **price change itself**: the month of the
  first charge of the old price level (`series.rows[0]`) and the month of the first charge of the new
  price level (`series.rows[step_index]`, where `Series.step_index` is the index at which the series
  changed level). Both rows are among the alert's `source_refs`, so the span can be checked against the
  cited rows. The CPI is looked up (REQ-CPI-06) for those two months.
  - Six monthly rows (30-day gaps from 2026-01-05) at `100.00`, `100.00`, `100.00`, `118.00`, `118.00`,
    `118.00` → dates 2026-01-05, 2026-02-04, 2026-03-06, 2026-04-05, …; `price_start_month` is
    `2026-01` (first old row) and `price_end_month` is `2026-04` (first new row).

- **REQ-CPI-11** The CPI fields are added **only together**, all strings, in this order after the existing
  six keys:

  | Key | Content |
  |---|---|
  | `price_start_month`, `price_end_month` | months of the two cited rows, `YYYY-MM` |
  | `price_change_percent` | `round_percent(percent_change(old_median_amount, new_amount))` |
  | `cpi_series` | `"IPC290751"` (the series' code) |
  | `cpi_base_year` | `"2025"` |
  | `cpi_start_month`, `cpi_end_month` | months **used** by the lookups (equal to the price months unless a lookup fell back) |
  | `cpi_start_index`, `cpi_end_index` | the two index values, three decimals, verbatim from the snapshot |
  | `cpi_change_percent` | `round_percent(percent_change(cpi_start_index, cpi_end_index))` computed from the **unrounded** index values |

  Worked example with the **synthetic** series `C` = {2026-01: 100.000, 2026-02: 100.500, 2026-03: 101.000,
  2026-04: 102.000, 2026-05: 102.500, 2026-06: 103.000} and the six rows of REQ-CPI-10, counterparty
  `CLOUDVAULT`: `alert.data` equals
  ```
  {"counterparty": "CLOUDVAULT", "old_median_amount": "100.00", "new_amount": "118.00",
   "extra_cost_per_year": "216.00", "yearly_cost": "1416.00", "interval_type": "monthly",
   "price_start_month": "2026-01", "price_end_month": "2026-04", "price_change_percent": "18.0",
   "cpi_series": "IPC290751", "cpi_base_year": "2025",
   "cpi_start_month": "2026-01", "cpi_end_month": "2026-04",
   "cpi_start_index": "100.000", "cpi_end_index": "102.000", "cpi_change_percent": "2.0"}
  ```
  The price change uses the **rounded medians** the detector already compares against
  `PRICE_INCREASE_MIN_RATIO`, so the percentage and the alert's own amounts agree.

- **REQ-CPI-12** The CPI context shall **not** change which alerts fire, their order, `severity`, `title`,
  `source_refs`, or the six existing `data` keys. With `cpi` in `context` and without it, the list of
  `(detector, severity, title, source_refs)` of every alert is equal; the ids differ (the id hashes
  `data`, DN-CPI-07).
  - Demo statement with the demo CPI snapshot: 3 tombstones and 19 alerts: 1 critical, 4 warning,
    14 info; the same as without CPI.
  - Property (Hypothesis, `max_examples=200`): for random monthly ledgers, alerts with a random CPI
    series and alerts without one agree on `(detector, severity, title, source_refs)` and on the six
    base `data` keys.

- **REQ-CPI-13** *If* a CPI figure cannot be stated honestly, *then* the alert shall carry **none** of the
  keys of REQ-CPI-11 (no partial context, no zero, no placeholder): when either lookup returns `None`;
  when `price_start_month == price_end_month` (a zero-length span, e.g. a weekly series that changes
  price within one month); when the two **used** CPI months are equal (a fallback collapsed the span);
  when `context["cpi"]` is not a `CpiSeries`-like object with `lookup`.
  - Series **C**, rows 2025-12-05 … (price start in 2025-12, before `2026-01`) → no CPI keys, alert
    otherwise unchanged.
  - Series **C**, rows with a step whose first new row is dated 2026-07 → no CPI keys (after the range).
  - Weekly rows 2026-01-05 and 2026-01-12 at `10.00`, 2026-01-19 and 2026-01-26 at `12.00` → the
    price-increase alert has no CPI keys (both months are `2026-01`).
  - Gapped series `G` = {2026-01: 100.000, 2026-03: 101.000} with a step from 2026-02 to 2026-03:
    `cpi_start_month` is `2026-01` (fallback), `price_start_month` is `2026-02`, the keys are present
    and the two months visibly differ.

---

## 4 — The no-invented-number promise

- **REQ-CPI-14** The CPI figures are **not rows of the user's file**; they shall be admitted as
  *attributed figures of the alert*: each is a named field of `Alert.data` (Finance Rule 1, "deterministic
  computed field on an Alert"), and the field set names its source (`cpi_series`, `cpi_start_month`,
  `cpi_end_month`, `cpi_base_year`). Consequently the unchanged number guard accepts them (it admits
  every number found in `Alert.data`) and still rejects any other. The system prompt is **not** changed
  (Finance Rule 1 requires it word for word); the LLM receives the CPI fields because it receives the
  whole alert as JSON.
  - Alert of REQ-CPI-11; LLM text `The price rose 18,0 % while the Spanish CPI changed by 2,0 % from
    2026-01 to 2026-04 (index 100.000 to 102.000). Source: f.csv:0.` → `Explanation.source == "llm"`.
  - Same text with `2,5 %` for the CPI → guard rejects, `Explanation.source == "fallback"`,
    `rejected_numbers == ("2,5",)`, text is the filled template.
  - Same text with an invented index `103.000` → rejected, `rejected_numbers == ("103.000",)`.
  - The CPI change in the text rounded differently (`2 %`) is accepted because `Decimal("2") ==
    Decimal("2.0")`; `2,04 %` is rejected.

- **REQ-CPI-15** `Alert.source_refs` shall still contain only `source_ref` values of loaded ledger rows
  (the rows that make the price series). No pseudo reference to the INE is added to it, so the UI can
  resolve every entry to a row and `loaded_source_refs(ledger, context)` keeps its meaning: the
  `CpiSeries` in `context` is not a `DataFrame` and contributes nothing, and every alert's `source_refs`
  remains a subset of it. The INE source is cited by **series code and month inside `data`** and
  displayed on the card (REQ-CPI-18).
  - Property (existing, extended): `set(alert.source_refs) <= loaded_source_refs(ledger, context)` with
    `context["cpi"]` set.
  - Example: the alert of REQ-CPI-11 has `source_refs == ["f.csv:0", ..., "f.csv:5"]` and no entry
    mentioning `ine` or `IPC`.

---

## 5 — Presentation and attribution

- **REQ-CPI-16** The explainer's template formatter shall support the format spec `pct`:
  `{price_change_percent:pct}` renders `format_percent(Decimal(value))`; a value that is not a number is
  rendered as is. `fill_fallback` stays public and its behaviour for `money` and plain fields is
  unchanged.
  - `fill_fallback("{x:pct}", alert)` with `data["x"] == "18.0"` → `"18,0 %"`; with `"-0.3"` → `"-0,3 %"`;
    with `"n/a"` → `"n/a"`.

- **REQ-CPI-17** *When* an alert of `zs.price_increase` has the CPI keys, the fallback template shall
  contain **one sentence** with the comparison; otherwise the template is today's text. `explain_support`
  shall provide `template_for(alert) -> str` choosing between them (`TEMPLATES` itself is unchanged: its
  keys still equal the registered `zs.*` detectors). The sentence is neutral: it states the two figures
  and the months and draws no conclusion and gives no advice (Finance Rule 8).
  - Sentence: `The price rose {price_change_percent:pct} while the Spanish CPI (INE series
    {cpi_series}) changed by {cpi_change_percent:pct} from {cpi_start_month} to {cpi_end_month}.`
  - Template with CPI for the alert of REQ-CPI-11 fills to: `The CLOUDVAULT charge increased from
    100,00 EUR to 118,00 EUR, adding 216,00 EUR to your yearly cost. The price rose 18,0 % while the
    Spanish CPI (INE series IPC290751) changed by 2,0 % from 2026-01 to 2026-04. Source: f.csv:0, f.csv:1,
    f.csv:2, f.csv:3, f.csv:4, f.csv:5.`
  - The same alert without CPI keys fills to today's text, with no mention of CPI.

- **REQ-CPI-18** The Zombie Subscriptions price-increase card shall show, under the explanation text and
  above the source rows: (a) a source line naming the series, the months used and the two index values in `format_index` form
  (`CPI source: INE series IPC290751 (base 2025 = 100), 2026-01 = 100,000, 2026-04 = 102,000`); (b) the
  comparison sentence **once**: when the displayed explanation already contains the sentence (fallback
  template) the card adds nothing; when the explanation is LLM text that lacks it, the card adds the
  sentence as a caption. A card whose alert has no CPI keys shows neither.
  - Fallback card for the alert of REQ-CPI-11 → exactly one element containing `changed by 2,0 %`, plus
    the source line.
  - LLM-accepted text that omits the sentence → the sentence appears as a caption, once.

- **REQ-CPI-19** The Zombie Subscriptions page shall show, once, below the alerts and only *while* a CPI
  snapshot is loaded, the snapshot's `attribution` text verbatim, its `licence`, the series code and
  `retrieved_on`, and the `no_endorsement` text. The root `README.md` shall carry the same attribution
  and non-endorsement text in a short "Public data" section, and `data/public/README.md` shall give the
  licence reference (Finance Rule 6). Phantom Invoices does not use the CPI and carries no attribution.
  The wording shall not imply that the INE takes part in, sponsors or supports the app.
  - Page text contains `Elaboración propia con datos extraídos del sitio web del INE: www.ine.es` and
    `CC BY 4.0` and `The INE does not take part in, sponsor or support this reuse.`
  - A test compares the three texts in README, `data/public/README.md` and the snapshot: they are equal.
  - Without a snapshot (file missing) the page shows `CPI context unavailable: snapshot not found.` as a
    caption, no attribution, and the alerts have no CPI keys.

---

## 6 — Demo, repository and steering

- **REQ-CPI-20** The committed snapshot shall pass REQ-CPI-03 and the pinned checks: `first_month ==
  "2017-01"`; `last_month >= "2026-09"`; month `2026-08` has value `104.638` and `2026-09` has value
  `104.978`, both status `Definitivo` **(INE)**; `licence == "CC BY 4.0"`; `attribution` and
  `no_endorsement` equal the texts of REQ-CPI-02; `retrieved_on` is an ISO date not before
  `2026-11-09`. `.gitignore` shall allow `data/public/` (today `*.json` is ignored outside
  `data/samples/`, so the snapshot would never be committed); the sample README and the structure steering
  document the new folder.
  - `.gitignore` contains the lines `!data/public/` and `!data/public/**` after `*.json`.

- **REQ-CPI-21** The demo shall behave correctly whatever the last published month is. The headless run
  of the app with **Load demo data** shall show 3 tombstones and 19 alerts (1 critical, 4 warning,
  14 info), and every price-increase card shall carry the CPI sentence **if and only if** the snapshot
  covers both of its months. Demo facts: `CLOUDVAULT` goes from `9.99` (first charge 2026-05-12) to
  `12.99` (first new charge 2026-08-10): price months `2026-05` and `2026-08`, `price_change_percent`
  `30.0`, always covered; `STREAMFLEX INTL` goes from `12.99` (first charge 2026-05-07) to `15.99`
  (first new charge 2026-10-04): months `2026-05` and `2026-10`, `price_change_percent` `23.1`,
  covered only once the snapshot reaches `2026-10`.
  - With the snapshot of 9 November 2026 (last month 2026-09): the `CLOUDVAULT` card shows `30,0 %` and
    its CPI sentence; the `STREAMFLEX INTL` card has no CPI sentence.
  - After the developer refreshes the snapshot with 2026-10 included, both cards show it; no test
    changes (the expectation is computed from the snapshot, not hard-coded).

## Non-goals

- No other statistic (food, energy, per-subscription ECOICOP groups), no forecast, no seasonal
  adjustment, no regional series.
- No network access from the app, the tests or the explanation layer; the snapshot is the only input.
- No CPI use in `zs.recurring_charge`, the other zs detectors or Phantom Invoices.
- No "above inflation" label, score or severity change, and no advice (Finance Rule 8).
- No PDF, no Excel, no INE web scraping: only the JSON API.
