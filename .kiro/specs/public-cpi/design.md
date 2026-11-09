# public-cpi — Design

Covers `REQ-CPI-01` to `REQ-CPI-21`. Section numbers (§) are cited by `tasks.md`; decisions are `DN-CPI-nn`
(§11). Nothing here adds a detector, changes a threshold, a severity or a `source_refs` list.

## 1 — Module map

New (package boundaries of `structure.md` hold: `ledger_kit` imports no app; the script imports no
project code):

| File | Role |
|---|---|
| `scripts/fetch_ine_cpi.py` | download, check and write the snapshot (§3); stdlib only |
| `data/public/ine_cpi_ipc290751.json` | the committed snapshot, written by the script, not by hand (§3) |
| `data/public/README.md` | licence reference, attribution, how to refresh (REQ-CPI-19) |
| `ledger_kit/public_data/__init__.py`, `ledger_kit/public_data/ine_cpi.py` | `CpiSeries`, `CpiPoint`, `SnapshotError`, `load_snapshot`, `validate_snapshot`, `month_key` (§4) |
| `tests/public_data/test_ine_cpi_reader.py`, `tests/public_data/test_ine_cpi_snapshot.py` | reader and committed-snapshot tests |
| `tests/test_fetch_ine_cpi.py` | script tests with a fake opener, no network |
| `apps/zombie_subscriptions/tests/test_zs_price_increase_cpi.py` | detector with and without CPI, properties |
| `apps/zombie_subscriptions/tests/test_zs_cpi_support.py` | template, card helpers, settings loader |
| `apps/zombie_subscriptions/tests/test_zs_cpi_demo.py` | headless AppTest of the demo with CPI |

Edited:

| File | Change |
|---|---|
| `ledger_kit/utils/money.py` | `PERCENT_DECIMALS`, `percent_change`, `round_percent`, `format_percent`, `format_index` (§2) |
| `ledger_kit/explainer.py` | `pct` and `idx` format specs in `_AlertFormatter.format_field` (§6.3); nothing else |
| `apps/zombie_subscriptions/detectors/utils.py` | `Series.step_index`, set in `_segment_by_price`; `cpi_context_fields` (§5) |
| `apps/zombie_subscriptions/detectors/price_increase.py` | merge the CPI fields into `data` (§5) |
| `apps/zombie_subscriptions/explain_support.py` | `CPI_SENTENCE`, `PRICE_INCREASE_WITH_CPI_TEMPLATE`, `template_for` (§7) |
| `apps/zombie_subscriptions/settings.py` | `load_cpi`, `cpi_source_line`, `cpi_sentence_to_add`, `attribution_lines` (§7, §8) |
| `apps/zombie_subscriptions/app.py`, `config.toml` | load the snapshot, pass it in `context`, render the card lines and the footer (§8) |
| `README.md`, `data/samples/README.md` | "Public data" section, pointer to `data/public/` (§8) |
| `.gitignore` | `!data/public/` and `!data/public/**` (§3.4) |
| `.kiro/steering/{finance-rules,structure,tech}.md` | last task only (§10) |

## 2 — Money helpers (REQ-CPI-08)

`money.py` is the single place for this arithmetic and formatting, next to `percent_of`.

```python
PERCENT_DECIMALS: int = 1  # one decimal for every percentage shown or stored by the alerts

def percent_change(old: Decimal, new: Decimal) -> Decimal: ...   # (new - old) / old * 100, ValueError if old <= 0
def round_percent(value: Decimal) -> Decimal: ...                # quantize(Decimal("0.1"), ROUND_HALF_UP)
def format_percent(value: Decimal) -> str: ...                   # "1.234,5 %"
def format_index(value: Decimal) -> str: ...                     # "104,978"
```

- `percent_change` works at the default `Decimal` context precision (28 digits): index values with three
  decimals and prices with two never lose a digit. Rounding happens once, in `round_percent`, at the output
  boundary (Finance Rule 3). Intermediate values are never rounded.
- `format_percent` rounds with `round_percent` first, then reuses `_group_thousands` and the sign handling of
  `_european_digits` (refactor the common digits routine to take the number of decimals; behaviour of
  `format_amount` is pinned by the existing `tests/test_money.py` and must not change).
- `format_index` keeps the **three** decimals of the snapshot (no rounding: the value already has exactly
  three), comma separator, grouping full stop for four digits or more.
- **Why one decimal** (DN-CPI-05): the sentence is a comparison of magnitudes (`30,0 %` against `0,9 %`);
  two decimals add false precision to an index published to three decimals and a rate of change computed over
  few months. One rule for both percentages: the price change and the CPI change are rounded identically, so
  neither looks more precise than the other. The index values are not rounded at all.
- **Why half-up and away from zero for negatives**: it is the rule of Finance Rule 3 (`ROUND_HALF_UP` of
  `Decimal.quantize` rounds half away from zero), so `-0.25` gives `-0.3`. A CPI can fall.

## 3 — Fetch script and snapshot (REQ-CPI-01 to REQ-CPI-04, REQ-CPI-20)

### 3.1 Script structure

```python
SERIES_CODE = "IPC290751"
API_URL = "https://servicios.ine.es/wstempus/js/ES/DATOS_SERIE/IPC290751"
FIRST_MONTH = "2017-01"
FETCH_LAST_PERIODS = 240            # `nult`: more than the 117+ months needed; entries before FIRST_MONTH are dropped
FETCH_TIMEOUT_SECONDS = 30
DEFAULT_OUTPUT = Path("data/public/ine_cpi_ipc290751.json")
ATTRIBUTION = "Elaboración propia con datos extraídos del sitio web del INE: www.ine.es"
NO_ENDORSEMENT = "The INE does not take part in, sponsor or support this reuse."
LICENCE = "CC BY 4.0"

class FetchError(Exception): ...                                   # one-line message, becomes "error: ..."
def build_url(last_periods: int = FETCH_LAST_PERIODS) -> str: ...   # f"{API_URL}?nult={n}&tip=A"
def fetch_json(url, *, opener=urlopen, timeout=FETCH_TIMEOUT_SECONDS) -> dict: ...
def parse_points(payload: dict) -> list[Point]: ...                 # month, Decimal value, status
def build_snapshot(payload: dict, *, retrieved_on: date) -> dict: ...
def check_snapshot(snapshot: dict) -> None: ...                     # REQ-CPI-03 in ~25 lines, raises FetchError
def write_snapshot(snapshot: dict, path: Path) -> None: ...         # temp file in the same folder, os.replace
def main(argv: list[str] | None = None, *, opener=urlopen, today: date | None = None) -> int: ...
```

- **Stdlib only** (REQ-CPI-01): `urllib.request.urlopen` with `timeout`, `urllib.error`, `json`, `decimal`,
  `argparse`, `os`, `pathlib`, `datetime`. The script does not import `ledger_kit` (its `__init__` pulls in
  pydantic), so it runs in a bare Python 3.12 before the venv exists. Its `check_snapshot` repeats the rules of
  `validate_snapshot` in a few lines; the committed-snapshot test runs the library validator on the result, so
  the two cannot drift silently (DN-CPI-09).
- **Time is injected**: `main(..., today=None)` reads `date.today()` only when `today` is None, and passes it to
  `build_snapshot(retrieved_on=...)`. Tests give a fixed date (testing rule 4); no function below `main` reads
  the clock.
- **Network is injected**: `fetch_json(..., opener=urlopen)`. Errors: `HTTPError` first, then `URLError`
  (an `HTTPError` is a `URLError`, so the order matters), then `TimeoutError`, then `json.JSONDecodeError`,
  each mapped to `FetchError("cannot reach the INE API: <reason>")` or `"HTTP error <code> from the INE API"`.
- **Decimals** (REQ-CPI-02): `json.loads(body, parse_float=Decimal)`. `Valor` may be a JSON number or a
  string; both go through `Decimal(str(...))`/`Decimal(text)`, never `float`. The value must equal its
  `quantize(Decimal("0.001"))` (padding allowed, rounding not); otherwise `FetchError`.
- **Month**: `f"{Anyo:04d}-{FK_Periodo:02d}"`, `FK_Periodo` in 1 to 12 only. `Fecha` is read for no purpose
  (DN-CPI-08).
- **Status**: taken from the entry, no default. **Unverified** (§9): with `tip=A` the INE API adds friendly
  names such as `T3_TipoDato` (expected text `Definitivo`); the first real run decides the field name. The
  script looks for the keys in the tuple `STATUS_KEYS = ("T3_TipoDato", "TipoDato")`, and fails with
  `error: no status for <month>` if none is present. It never writes `"Definitivo"` on its own.
- **Atomic write**: `tempfile.NamedTemporaryFile(dir=path.parent, delete=False)` then `os.replace`; JSON dumped
  with `indent=2, ensure_ascii=False`, `"\n"` newlines, `encoding="utf-8"`, key order as in REQ-CPI-02, final
  newline. A failed run leaves the old file as it was (REQ-CPI-01).
- **Command line**: `python scripts/fetch_ine_cpi.py [--output PATH]`. No other option: the start month, the
  series and the URL are constants, not knobs (a knob would let a developer commit a different series).

### 3.2 Snapshot file

Layout and key order are in REQ-CPI-02. An abridged example (**synthetic months shown only to illustrate the
shape**; the real file has every month from 2017-01):

```json
{
  "series_code": "IPC290751",
  "series_name": "Nacional. Índice general. Índice",
  "table": 76125,
  "base_year": 2025,
  "classification": "ECOICOP v2",
  "periodicity": "monthly",
  "api_url": "https://servicios.ine.es/wstempus/js/ES/DATOS_SERIE/IPC290751",
  "retrieved_on": "2026-11-09",
  "licence": "CC BY 4.0",
  "attribution": "Elaboración propia con datos extraídos del sitio web del INE: www.ine.es",
  "no_endorsement": "The INE does not take part in, sponsor or support this reuse.",
  "first_month": "2017-01",
  "last_month": "2026-09",
  "values": [
    {"month": "2017-01", "value": "...", "status": "..."},
    {"month": "2026-08", "value": "104.638", "status": "Definitivo"},
    {"month": "2026-09", "value": "104.978", "status": "Definitivo"}
  ]
}
```

### 3.3 Size and shape

About 117 entries, 100 bytes each: roughly 12 KB. Months are a list (not a map) so the file reads in order and
the validator checks contiguity by walking it once.

### 3.4 Repository rules

- `.gitignore` ends with `*.json` and `!data/samples/**` today; **`data/public/*.json` would be ignored**. Add
  `!data/public/` and `!data/public/**` next to the samples exceptions (REQ-CPI-20). A text test of
  `.gitignore` pins the two lines (same style as `test_pi_gitattributes.py`).
- `data/public/` holds only official public data under an open licence, with its licence reference in
  `data/public/README.md`. Finance Rule 6 (samples only synthetic or public-domain) is widened for this folder
  in the steering task (§10); the data contains no personal data and no user figure.
- Line endings: the script writes LF explicitly, the reader opens the file with `encoding="utf-8"` and
  accepts CRLF (`json` does), so a Windows checkout with `autocrlf` still loads. The file is validated, not
  byte-compared, so no `.gitattributes` line is needed.

## 4 — Reader (REQ-CPI-05 to REQ-CPI-07)

```python
# ledger_kit/public_data/ine_cpi.py   (stdlib only: json, datetime, decimal, pathlib, dataclasses)
DEFAULT_SNAPSHOT_PATH = Path(__file__).resolve().parents[2] / "data" / "public" / "ine_cpi_ipc290751.json"
SERIES_CODE = "IPC290751"; BASE_YEAR = 2025; FIRST_SNAPSHOT_MONTH = "2017-01"

class SnapshotError(ValueError): ...

@dataclass(frozen=True)
class CpiPoint:
    requested: str      # "YYYY-MM" asked for
    used: str           # "YYYY-MM" answered
    value: Decimal      # three decimals, verbatim from the snapshot
    status: str
    is_fallback: bool   # used != requested

class CpiSeries:        # immutable: private tuple of months + dict month -> (Decimal, status)
    @classmethod
    def from_mapping(cls, values: Mapping[str, str | Decimal], *, status="Definitivo", **meta) -> "CpiSeries": ...
    def lookup(self, month: str | date) -> CpiPoint | None: ...

def month_key(day: date) -> str: ...            # f"{day.year:04d}-{day.month:02d}"
def validate_snapshot(data: dict) -> None: ...  # REQ-CPI-03, raises SnapshotError
def load_snapshot(path: Path = DEFAULT_SNAPSHOT_PATH) -> CpiSeries: ...
```

- `lookup` algorithm: normalise the input to `(year, month)` (strings by regex `^\d{4}-(0[1-9]|1[0-2])$`;
  `date`/`datetime` by attribute; anything else `ValueError`). If the key is past `last_month` or before
  `first_month` return `None`. Otherwise `bisect_right` on the sorted month list gives the latest published month
  at or before the key. Equal → `is_fallback=False`; else `True`. Because a loaded snapshot is contiguous, a
  fallback can only occur on a series built by `from_mapping`; it is kept in the contract because the
  requirement asks for it and because a future refresh could carry a withheld month.
- The reader never computes a percent: that is `money.percent_change`, called by the detector support code
  (§5) so all ratio arithmetic stays in `money.py`.
- Only public names are exported from `ledger_kit/public_data/__init__.py`: `CpiSeries`, `CpiPoint`,
  `SnapshotError`, `load_snapshot`, `month_key`, `DEFAULT_SNAPSHOT_PATH`. The phantom app, which must use only
  public names of `ledger_kit`, is unaffected.
- `from_mapping` exists so tests build series in one line without files and so the gap case is testable
  (DN-CPI-04: contiguity is a property of the committed file, enforced by `load_snapshot`, not of the
  in-memory object).
- Caching: `load_snapshot` is a plain function; the app caches its result (§8). No module-level state.

## 5 — Price-increase detector (REQ-CPI-09 to REQ-CPI-13)

### 5.1 `Series.step_index`

`Series` (a plain dataclass in `detectors/utils.py`) has `rows` and `price_steps` but not **where** the step
happened. Branch 2 of `_segment_by_price` already knows it: the loop variable `p` is the first index of the
new level (`pre = amounts[:p]`, `post = amounts[p:]`). The change:

```python
@dataclass
class Series:
    ...
    price_steps: list[tuple[Decimal, Decimal]]
    step_index: int | None = None   # index in `rows` of the first charge of the new price level

# in _segment_by_price: splits.append((a, b, p)); if len(splits) == 1: a, b, p = splits[0]
#   return _make_series(run, interval, b, [(a, b)], step_index=p)
```

`_make_series` gets an optional `step_index` argument defaulting to `None`. A series has at most one step
(branch 2 accepts exactly one split), and `_extend_once` / `_merge_once` rebuild series through
`_segment_by_price`, so `step_index` is always consistent with `rows`. `1 <= step_index <= len(rows) - 1`
whenever `price_steps` is non-empty.

This changes no condition, no comparison and no threshold, so no alert appears or disappears. Existing tests
construct `Series` only through the functions (no direct `Series(` call in the test folder at the time of this
spec), and the new field is last with a default, so none changes. Task CPI5 pins this with a test that runs
`find_series` on every existing price-step fixture and asserts the old results unchanged plus the new index.

### 5.2 `cpi_context_fields`

```python
def cpi_context_fields(series: Series, old: Decimal, new: Decimal, cpi: Any) -> dict[str, str]:
    """Return the CPI keys of REQ-CPI-11, or {} when REQ-CPI-13 says they cannot be stated."""
```

Steps: `lookup = getattr(cpi, "lookup", None)`; none → `{}`. `start_day = series.rows[0]["date"]`,
`end_day = series.rows[series.step_index]["date"]`; `month_key` of each; equal months → `{}`. Two lookups; any
`None` → `{}`; used months equal → `{}`. Then build the dict with `str(point.value)` (three decimals, as read),
`str(round_percent(percent_change(old, new)))` and `str(round_percent(percent_change(start.value, end.value)))`.
`str(Decimal("18.0"))` is `"18.0"`: the quantum keeps the trailing zero. The `old`/`new` passed are the rounded
medians `price_steps` already hold, the same values that `PRICE_INCREASE_MIN_RATIO` is tested on.

`price_increase.py` becomes:

```python
cpi = context.get("cpi")
...
data = {... six existing keys ...}
data.update(cpi_context_fields(series, old, new, cpi))
alerts.append(Alert(..., data=data))
```

The test `if (new - old) / old < PRICE_INCREASE_MIN_RATIO: continue` and every line above it are untouched.
`Alert.id` is the hash of `detector + sorted source_refs + data`, so the id changes when CPI keys are added
(DN-CPI-07); nothing in the repository asserts a literal id (checked: no 64-hex literal in the zs tests).

### 5.3 Why in `data` and why only together

`Alert.data` is the one structured channel the explanation layer, the guard and the UI already read. A flat dict
of strings is what `fill_fallback`, the guard (`str(v)` tokenised) and `model_dump_json` already handle; no new
type crosses the layers. Keys appear together or not at all (REQ-CPI-13) so a template either has everything
it names or none of it, and `template_for` can test a single key (`"cpi_change_percent" in alert.data`).

## 6 — Provenance of the CPI figures: how the promise holds (REQ-CPI-14, REQ-CPI-15)

### 6.1 The question

Finance Rule 1: no layer may produce a figure that does not exist *verbatim in the source data or as a
deterministic computed field on an Alert*. Rule 2: every `Alert` cites the source rows. The INE index values are
neither rows of the user's file nor computed from them.

### 6.2 Decision (DN-CPI-01)

The snapshot is a **second declared source**, and its figures enter the alert through the second clause of
Rule 1: they are **named fields of `Alert.data`**, produced by a deterministic function of (a) the cited ledger
rows and (b) a versioned, validated, committed file. Concretely:

1. **Verbatim.** `cpi_start_index` and `cpi_end_index` are the snapshot strings, not computed.
2. **Computed and attributed.** `cpi_change_percent` and `price_change_percent` are computed by `money.py`
   from fields that are themselves in `data` (`cpi_*_index`, `old_median_amount`, `new_amount`), so any reader
   can recompute them from the alert alone. The price inputs come from rows listed in `source_refs`.
3. **Cited.** The source is named *inside the alert* by `cpi_series` (`IPC290751`), `cpi_start_month`,
   `cpi_end_month` and `cpi_base_year`, and *on the card* by the source line and the footer attribution
   (REQ-CPI-18, REQ-CPI-19). Series code plus month identify one entry of the committed file exactly, the same
   way `file:row` identifies one row of a statement.
4. **No pseudo `source_ref`.** `source_refs` stays a list of ledger rows. Adding `"ine_cpi_ipc290751.json:2026-04"`
   to it would (a) break the UI, which resolves every ref to a dataframe row (`rows_for_refs`), (b) break the
   property `source_refs ⊆ loaded_source_refs(ledger, context)` that the testing steering makes mandatory, and
   (c) hide the distinction between *what the user's file says* and *what the INE says*. Keeping two kinds of
   citation visibly separate is the point.

### 6.3 What the guard does (no change)

`_allowed_decimals` adds every number tokenised from `str(v)` for each value of `alert.data`, so the CPI
figures are admitted without touching the guard, and every other number is still rejected (REQ-CPI-14
examples). Two notes, both accepted:

- `Decimal("2") == Decimal("2.0")`, so the LLM may write `2 %` or `2,0 %`; it may not write `2,04 %`.
- Month strings such as `2026-04` tokenise to `2026` and `04`, so the integers 1 to 12 (when a month appears
  in `data`) and 2025/2026 become admitted numbers. This **widens the allowed set slightly** (an invented
  "4" would pass) and cannot be avoided without removing the months from `data`, which would remove the
  citation. The cost is accepted: the guard is a net against invented *figures of money and percentages*, and
  the same weakness already exists for the digits of `counterparty` and `interval_type`. Recorded as a known
  limitation in Q4.
- The system prompt is unchanged (Finance Rule 1 demands it word for word); its text already allows "structured
  fields of the alert". The explainer sends the whole alert as JSON, so the LLM sees the CPI fields.
- `loaded_source_refs` ignores non-DataFrame context values, so `context["cpi"]` adds no ref: the property
  holds by construction, and a test pins it (REQ-CPI-15).

### 6.4 Formatter specs

`_AlertFormatter.format_field` gains two branches next to `money`: `pct` → `format_percent(Decimal(str(value)))`
and `idx` → `format_index(Decimal(str(value)))`, each falling back to `str(value)` on `InvalidOperation` or
`TypeError`, exactly as `money` does. The unknown-key behaviour (`{key}` kept) is unchanged.

## 7 — Template and card (REQ-CPI-16 to REQ-CPI-18)

### 7.1 Templates

```python
CPI_SENTENCE = (
    "The price rose {price_change_percent:pct} while the Spanish CPI (INE series {cpi_series}) "
    "changed by {cpi_change_percent:pct} from {cpi_start_month} to {cpi_end_month}."
)
PRICE_INCREASE_WITH_CPI_TEMPLATE = (
    "The {counterparty} charge increased from {old_median_amount:money} to {new_amount:money}, "
    "adding {extra_cost_per_year:money} to your yearly cost. " + CPI_SENTENCE + " Source: {source_refs}."
)
def template_for(alert: Alert) -> str:
    """Fallback template of an alert: the CPI variant only for a price increase with CPI keys."""
```

`TEMPLATES` is not edited, so `test_templates_cover_every_registered_zs_detector` holds. The app replaces
`TEMPLATES[alert.detector]` by `template_for(alert)`. One sentence, neutral, no verb like "exceeds",
"beats" or "above" (Finance Rule 8: no conclusion; the reader compares). "changed by" (not "rose") for the CPI
because it can fall.

### 7.2 Card helpers (pure, in `settings.py`, testable without Streamlit)

```python
def cpi_source_line(alert: Alert) -> str | None
   # "CPI source: INE series IPC290751 (base 2025 = 100), 2026-01 = 100,000, 2026-04 = 102,000"
def cpi_sentence_to_add(alert: Alert, explanation: Explanation) -> str | None
   # fill_fallback(CPI_SENTENCE, alert) unless the explanation text already contains it, or no CPI keys
def attribution_lines(cpi: CpiSeries) -> list[str]
   # [attribution, "Licence: CC BY 4.0 · series IPC290751 · retrieved 2026-11-09", no_endorsement]
```

`_render_alert` calls the first two after `st.write(explanation.text)` and the guard badge: the sentence (when
returned) as `st.caption`, then the source line as `st.caption`. In the default no-key demo the explanation is
the filled template, which contains the sentence, so the card shows it exactly once, plus the source line.
With an accepted LLM text that dropped the sentence, the caption supplies it. The comparison is therefore
visible on the card **whatever the LLM writes**, and the LLM can never remove it (REQ-CPI-18).

HTML safety: both helpers return plain text shown with `st.caption`/`st.write`, not `unsafe_allow_html`; the
`markdown_safe` helper is applied to dynamic text (all of it is from our own constants and the snapshot, but
the series name comes from a file). No `unsafe_allow_html` is added.

## 8 — App wiring and attribution (REQ-CPI-18, REQ-CPI-19, REQ-CPI-21)

- `config.toml` gains `[cpi]` with `snapshot_path = "data/public/ine_cpi_ipc290751.json"` (a path, not a
  threshold; the file's own rule "no thresholds" holds).
- `settings.load_cpi(config, root) -> CpiSeries | None`: `load_snapshot(Path(root) / path)`; `SnapshotError`
  → `None` (the page then shows the caption of REQ-CPI-19 and the alerts have no CPI keys). A broken snapshot
  must not take the whole page down, but it must not pass silently in the repository either: the snapshot tests
  (REQ-CPI-20) fail loudly in CI.
- `app.py`: `_load_cpi()` wrapped in `st.cache_resource` (the object is immutable and shared); `context =
  {"aliases": ..., "cancellation_dates": ..., "cpi": cpi}`; `run_all` copies the mapping shallowly (verified in
  `registry.py`: `MappingProxyType(dict(context))`), so the object reaches the detector unchanged. After
  `_render_alerts`, a footer `_render_attribution(cpi)` writes `attribution_lines(cpi)` as `st.caption` once.
  The footer is drawn whenever `cpi` is loaded, not only when a card uses it: the data is on the page.
- `_explain` uses `template_for(alert)`; the cache key `(alert.id, mode)` stays valid because the id includes
  the CPI keys (a changed snapshot gives different ids, hence no stale explanation).
- **Phantom Invoices** gets nothing: it shows no CPI figure, so an attribution there would be false
  (DN-CPI-06). The showcase Home page (`streamlit_app.py`) is not touched either; if the reviewer wants a data
  credit there, it is one `st.caption` (Q5).
- **README**: a "Public data" section with the attribution, the licence, the non-endorsement sentence, how the
  snapshot is refreshed (`python scripts/fetch_ine_cpi.py`) and why the apps never call the network.
  `tests/test_readme.py` pins the required headings (`REQUIRED_HEADINGS`); the new section must be added to
  that list or placed under an existing heading, and the test is read before editing (task CPI10).
- **Streamlit Community Cloud** needs the snapshot in the repository, hence §3.4.

## 9 — Library notes and unverified API points

### 9.1 context7 (Python 3.12 standard library, `/python/cpython/v3.12.16`)

What the documentation says, and how the design uses it:

- `urllib.request.urlopen(url, data=None, *, cafile=None, capath=None, cadefault=False, context=None)` has
  **no `timeout` in the signature shown by this docs snippet**, while the same page documents an optional
  `timeout` parameter that applies to blocking operations "for HTTP, HTTPS and FTP"; the function raises
  `URLError` on protocol errors. The design passes `timeout=` by keyword to `urlopen`, which every supported
  Python 3 accepts, and `main` lets the fake opener in tests accept the same keyword. The returned object is a
  context manager (`with opener(request, timeout=...) as response:`) with `.status`, `.headers` and `.read()`.
- The how-to catches `HTTPError` **before** `URLError` because `HTTPError` is a subclass: used in §3.1.
- `json.loads` has `parse_float` ("called with the string of every JSON float", default `float(num_str)`,
  usable with `decimal.Decimal`) and `parse_int`: used so that `104.978` never exists as a binary float.
  Integers are read as `int` and converted with `Decimal(str(...))`.
- Proxy settings from `*_proxy` environment variables are honoured by default: a developer behind a proxy
  needs no code change.

The snippet does not show `Request(headers=...)`; the design sets `Accept: application/json` and a `User-Agent`
naming the project through `urllib.request.Request(url, headers={...})`, which is the documented `Request`
constructor. Nothing else from the library is needed.

### 9.2 Not verified in this session (web fetch was denied)

1. **Status field of the API response** (REQ-CPI-02): `T3_TipoDato` with `tip=A` is the author's reading of the
   INE API conventions, not a checked fact. The script is written so that a wrong guess fails with
   `error: no status for <month>` instead of writing something invented. Q2.
2. **Exact wording of the attribution** and the URL of the legal notice (Q1).
3. **Whether `nult` plus `tip=A` can be combined** in one query; the INE documents both parameters, but the
   combination was not run. If it fails, the fallback is two requests (one for values, one for metadata) and
   the status is then read from the field the plain response has. Q3.

## 10 — Test plan (testing.md tiers)

The reader and the script are not detectors, so the detector tiers apply to `zs.price_increase` and the
equivalent normal/edge/property split is used for the new modules.

| Module | Tier 1 (normal) | Tier 2 (edge) | Tier 3 (Hypothesis, `max_examples=200`) |
|---|---|---|---|
| `money` percent helpers | the REQ-CPI-08 examples | `old <= 0`, half-up at ±0.25, 0.0, large numbers | `round_percent(percent_change(a, b))` is within 0.05 of the exact value; sign follows `new - old` |
| `ine_cpi` reader | exact month, fallback, before, after | invalid month strings, `date`/`datetime`, single-month series, empty mapping | never a month later than requested; `value` always an entry of the series |
| snapshot validator | the committed file passes | each rejection of REQ-CPI-03 (gap, zero, two decimals, old series, base year) | a generated contiguous series passes; deleting any interior month fails |
| fetch script | fake payload → file; atomic write | each error path, existing file untouched, value with 4 decimals, no status | round trip: `validate_snapshot(build_snapshot(payload))` passes for generated payloads |
| `zs.price_increase` + CPI | REQ-CPI-11 example; no `cpi` → old dict | REQ-CPI-13 cases | alerts with a random CPI series agree on `(detector, severity, title, source_refs)` and base `data` with the ones without; `source_refs ⊆ loaded_source_refs` |
| guard with CPI | accepts REQ-CPI-14 text | `2,5`, `103.000`, `2,04`, `2 %` | any text whose numbers are all in `data` is accepted; adding one number outside it is rejected |
| templates / card helpers | REQ-CPI-17/18 examples | alert without CPI, LLM text with/without sentence | the card never shows the sentence twice |
| demo AppTest | counts and cards of REQ-CPI-21 | snapshot without 2026-10; snapshot missing | — |

Fixtures: `cpi_c_series` (series C), `cpi_gapped_series` (G), `rows_with_cpi_step` (six monthly rows
100.00/118.00 from 2026-01-05). All **synthetic**; the demo test is the only one that uses the real snapshot
and it computes its expectation from it with the reader and `money` (no hard-coded index, apart from the two
pinned **(INE)** figures in the snapshot test).

No test reads the clock or the network. `freezegun` is not needed: nothing under test reads time; the script's
`today` is a parameter.

## 11 — Decisions

| Id | Decision | Reason |
|---|---|---|
| DN-CPI-01 | CPI figures are named fields of `Alert.data` with series code and month; `source_refs` keeps ledger rows only (§6) | Rule 1 allows attributed computed fields; a pseudo ref would break the UI resolver and the `loaded_source_refs` property, and would blur user data versus INE data |
| DN-CPI-02 | Compare over the span from the first charge of the old price to the first charge of the new price | It is the interval over which the customer held the old price while the index moved; both endpoints are cited rows; it needs no assumption about "12 months" the data may not cover. A shorter span (last old to first new charge) would compare a 25 % rise with one month of CPI and say nothing |
| DN-CPI-03 | A month after the last published one gives **no** CPI context (`None`), never the latest value | The request forbids extrapolation; using September for October would compare periods of different length while the sentence claims "from X to Y". Cost: a price step in the newest month gets no sentence until the INE publishes it (visible in the demo for `STREAMFLEX INTL`, REQ-CPI-21). A stale-by-one-month mode would be a two-line change (`CPI_MAX_LAG_MONTHS`) if the reviewer prefers it (Q6) |
| DN-CPI-04 | Gaps are tolerated by `CpiSeries` (fallback to the earlier month, flagged) but forbidden in the committed snapshot | The request asks for the fallback and for contiguous months; both can hold because they apply to different objects |
| DN-CPI-05 | One rounding rule: one decimal, half-up, for both percentages; index values never rounded | Matches Finance Rule 3 style, avoids false precision, one rule to document |
| DN-CPI-06 | Attribution in Zombie page, README and `data/public/README.md`; none in Phantom Invoices | Attribution belongs where the processed data is shown; a credit in an app that does not use it would be misleading |
| DN-CPI-07 | Alert ids change when CPI keys are added | The id hashes `data`; the CPI is part of what the alert says. No stored id exists to migrate |
| DN-CPI-08 | Month from `Anyo` and `FK_Periodo`, not from `Fecha` | `Fecha` epoch of a month start depends on the zone (a CET midnight is the previous day in UTC); the two integer fields are unambiguous |
| DN-CPI-09 | The script duplicates the validator in a few lines instead of importing `ledger_kit` | "Standard library only" and no dependency on the venv; the committed-file test applies the library validator, so drift is caught |
| DN-CPI-10 | CPI passed through `context["cpi"]`, loaded by the app | Detectors stay pure functions `(ledger, context)`; no I/O or global state in them |
| DN-CPI-11 | `Series.step_index` added instead of recomputing the split in the detector | One source of truth for where the step is; recomputing would duplicate `_segment_by_price` and could disagree after an extend/merge |
| DN-CPI-12 | The card shows the sentence itself when the LLM text lacks it | The comparison is deterministic data; it must not depend on the wording of an LLM |
| DN-CPI-13 | Index values shown with a decimal comma (`100,000`) | Finance Rule 4: `100.000` reads as one hundred thousand in European format |
| DN-CPI-14 | No "above/below inflation" wording or flag | Finance Rule 8: no conclusion, no advice; also keeps the CPI from becoming a hidden severity input |

## 12 — Risks

1. **`Series.step_index` touches the core of the detector.** Mitigation: it is a new field with a default and one
   changed `append`; CPI5 runs every existing price-step fixture before and after and asserts equality of the
   old fields.
2. **Snapshot ignored by git.** Mitigation: the `.gitignore` exception and its test (CPI4).
3. **API field names wrong on the first real run.** Mitigation: the script fails loudly, writes nothing, and
   prints which month lacks a status (§9.2).
4. **The October row appearing mid-judging** changes the demo cards. Mitigation: REQ-CPI-21's
   expectation is computed from the snapshot.
5. **Guard widening by month digits** (§6.3).

## 13 — Open questions for the reviewer

Listed in `tasks.md` (end of file) so they travel with the task list.
