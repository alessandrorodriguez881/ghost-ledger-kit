# public-fees — Design

Covers `REQ-PF-01` to `REQ-PF-22`. Section numbers (§) are cited by `tasks.md`; decisions are `DN-PF-nn` (§12).
Nothing here adds a detector, a threshold that decides an alert, a severity, a title or a `source_refs` entry.
The author of this spec read `public-cpi`, `ine_cpi.py`, `data/public/README.md`, the Vampire Fees detector
`recurring_fee.py`, `detectors/utils.py`, `settings.py`, `config.toml`, `explain_support.py`, the first 450 lines
of `app.py` and the number guard of `explainer.py`; it ran nothing. Where this document says "read before
editing", the file was not read.

## 1 — Module map

New (package boundaries of `structure.md` hold: `ledger_kit` imports no app; apps import `ledger_kit` public
names):

| File | Role |
|---|---|
| `scripts/import_bde_fees.py` | **BLOCKED.** Reads the downloaded Excel, writes the snapshot (§4). Developer machine only |
| `data/public/bde_payment_account_fees.json` | The committed snapshot. **Does not exist yet** (§2.4) |
| `ledger_kit/public_data/bde_fees.py` | `FeeSnapshot`, `FeeDeclarations`, `FeeSnapshotError`, `load_fee_snapshot`, `validate_fee_snapshot`, constants (§3) |
| `tests/public_data/bde_builders.py` | Builders of **synthetic** snapshots `S12`, `S10` and a random-snapshot strategy |
| `tests/public_data/test_bde_fees_reader.py`, `test_bde_fees_validator.py`, `test_bde_fees_snapshot.py` | Reader, validator, committed snapshot (skipped while absent) |
| `tests/test_import_bde_fees.py` | Importer: pure mapping everywhere, workbook reading only with `openpyxl` (§4) |
| `apps/vampire_fees/tests/test_vf_recurring_fee_peers.py` | Detector with and without peers, properties |
| `apps/vampire_fees/tests/test_vf_peer_support.py` | Config, matching, template, card helpers, guard with peer fields |
| `apps/vampire_fees/tests/test_vf_peer_demo.py` | Headless `AppTest` of the demo with a synthetic snapshot |
| `tests/test_alert_id_peer_keys.py` | The alert id leaves out the `peer_*` keys; every demo id unchanged (PF0) |

Edited:

| File | Change |
|---|---|
| `ledger_kit/utils/money.py` | `median_amount` (§5) |
| `ledger_kit/models.py` | `ALERT_ID_EXCLUDED_PREFIX`; the alert id leaves out the `peer_*` keys of `data` (§6.3, DN-PF-17, task PF0) |
| `ledger_kit/public_data/__init__.py` | export the new public names |
| `apps/vampire_fees/detectors/utils.py` | `PEER_MIN_ACCOUNTS`, `PEER_MAX_DATE_GAP_DAYS`, `PeerService`, `build_peer_services`, `match_peer_service`, `PeerContext`, `peer_context_fields` (§6) |
| `apps/vampire_fees/detectors/recurring_fee.py` | merge the peer fields into `data` (§6.3) |
| `apps/vampire_fees/config.toml` | `[peer_fees]` and its two sub-tables (REQ-PF-09) |
| `apps/vampire_fees/explain_support.py` | `PEER_SENTENCE`, `RECURRING_FEE_WITH_PEERS_TEMPLATE`, `template_for` (§8) |
| `apps/vampire_fees/settings.py` | `load_peers`, `peer_type_options`, `default_peer_type`, `peer_source_line`, `peer_sentence_to_add`, `peer_attribution_lines`, `explanation_cache_key`, a `peers` argument of `run_pipeline` (§8, §9) |
| `apps/vampire_fees/app.py` | loader, select box, card lines, footer (§9) |
| `streamlit_app.py` | one conditional attribution caption on Home (§9) |
| `README.md`, `data/public/README.md`, `data/samples/README.md`, `.gitignore`, `pyproject.toml` | docs, `*.xlsx`/`*.xls` ignore, optional extra `import` (PF7, PF8) |
| `.kiro/steering/{finance-rules,structure,tech}.md` | last task only, after review (§11) |

`ledger_kit/explainer.py` is **not** edited: the format specs `money` and plain text already cover every
placeholder of the sentence (§7).

## 2 — The snapshot

### 2.1 Why our own format

The Excel layout is unknown (Source fact 6) and the BdE page offers no stable file. A snapshot in our own format
(REQ-PF-01) makes the reader, the detector, the tests and the docs independent of that layout; **only the
importer** knows it. If the BdE changes the Excel, the importer is fixed and the snapshot, the reader and every
test stay as they are (DN-PF-03).

### 2.2 Normalised shape (DN-PF-02)

The user asked for one row per declaration date, account type, entity, account, service and concept. A flat file
would repeat the entity and account names on every row (an estimate: 51 entities, 1 to 3 accounts each, 13
services, 1 to 4 concepts per service gives some thousands of rows per type, about 1 MB for one type and a few MB
for five). The snapshot therefore has two lists:

- `accounts`: one entry per **declaration** (date, type, entity code and name, account key and name), the
  identity of an account;
- `rows`: one entry per published cell, pointing to its declaration by (`account_type`, `account_key`), with
  `service_code`, `concept`, `text`, `amount`, `not_offered`.

Joining the two gives exactly the flat row of the request. The split also keeps an **account that has no row** (a
declaration whose services are all missing) countable, and lets the validator check names once. If the size of
the real file passes 5 MB, the snapshot is split by account type (one file per type, a list of paths in
`config.toml`); that is not needed for the first version. The first snapshot holds `CNO` and `COT`, plus `CDI` and
`CJO` if they were downloaded; `CBA` is not needed (decision Q5, DN-PF-22).

### 2.3 Fields and their reasons

- **`account_key`** is `"<entity_code>-<nn>"`, our ordinal in file order. The source gives no account id and one
  entity can have several accounts of the same type with, possibly, the same name (Source fact 3); the ordinal is
  stable within one snapshot, which is all a count needs. A re-import may renumber; nothing outside the
  snapshot stores a key. Decision Q8 confirms this: entity code plus the position of the account within that
  entity in file order, and the snapshot keeps `account_name` for display.
- **`declaration_date` on each account and on the top level**, equal by REQ-PF-02. Format 1 has one date; the
  duplication keeps the row granularity of the request and lets a future format carry several dates without
  changing the meaning of an account (the `snapshot_format` number is the switch).
- **`excel_files`**, one object per account type, because the tool exports one type per Excel (Source fact 1).
  Name, size in bytes and SHA-256 of the file **as downloaded** make the derivation checkable against the file
  the developer still has; the Excel itself is not committed (it is BdE data in a form we do not control and it
  could carry padding we would then have to review).
- **`text` and `amount`**: `text` is the published cell, trimmed (faithful reproduction, Source fact 7); `amount`
  exists only for euro amounts and is the string with a decimal point and two decimals; the reader and the guard
  never parse `text`. Percentages and names keep only `text`.
- **`not_offered`**: the asterisk of *No practicado*, kept as a flag with `text "*"`. It is not an amount; the
  sentence never counts it as `0.00` (DN-PF-06).
- **`licence_note`, `attribution`, `no_endorsement`** are constants of the reader module, copied into the file and
  checked equal on load (the CPI snapshot works the same way). The attribution is the text the reviewer decided on
  23 November 2026 (decision Q1): `Fuente: Banco de España, comparador de comisiones de cuentas de pago
  (declaraciones a fecha YYYY-MM-DD). Elaboración propia: recuento, mediana y máximo.` The date is the snapshot's
  `declaration_date`, so the module holds `ATTRIBUTION_TEMPLATE` with a `{declaration_date}` placeholder and
  `attribution_for(declaration_date)`; the validator compares the file's text with `attribution_for` of the file's
  own date. *Elaboración propia* labels the counts, the median and the maximum as our calculation, which the legal
  notice allows when the data is reproduced faithfully and the source is cited (DN-PF-21).

### 2.4 State today

The file does not exist. `DEFAULT_FEE_SNAPSHOT_PATH` points at it; `load_fee_snapshot` raises `FeeSnapshotError`
with `file not found`; the app turns that into the caption `Fee comparison unavailable: snapshot not found.`
(REQ-PF-19). Every test that needs the real file is `skipif(not exists)` (REQ-PF-03). The `.gitignore` already
allows `data/public/**`, so the day the file is written `git status` lists it.

### 2.5 Size, encoding, line endings

UTF-8, LF written by the importer. The reader accepts CRLF (`json` does). The file is validated, not compared
byte for byte, so no `.gitattributes` line is needed (same reasoning as the CPI snapshot, §3.4 of its design).

## 3 — The reader (REQ-PF-06 to REQ-PF-08)

```python
# ledger_kit/public_data/bde_fees.py   (stdlib only: json, re, datetime, decimal, pathlib, dataclasses)
DEFAULT_FEE_SNAPSHOT_PATH = Path(__file__).resolve().parents[2] / "data" / "public" / "bde_payment_account_fees.json"
SNAPSHOT_FORMAT = 1
ACCOUNT_TYPE_ORDER = ("CNO", "CDI", "CJO", "CBA", "COT")
ACCOUNT_TYPES: dict[str, AccountType]        # code -> published label, English phrase
SERVICES: dict[str, str]                      # the 13 codes -> published label
SOURCE, START_PAGE, LICENCE_NOTE, NO_ENDORSEMENT: str
ATTRIBUTION_TEMPLATE: str                     # decision Q1, with a {declaration_date} placeholder

def attribution_for(declaration_date: str) -> str: ...

class FeeSnapshotError(ValueError): ...

@dataclass(frozen=True)
class FeeDeclarations:
    account_type: str; service_code: str; concept: str; declaration_date: str
    account_count: int; amounts: tuple[Decimal, ...]; not_offered_count: int
    @property
    def without_amount_count(self) -> int: ...

class FeeSnapshot:     # immutable: dicts built once in from_dict
    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FeeSnapshot": ...   # validates
    def declarations(self, account_type: str, service_code: str, concept: str) -> FeeDeclarations | None: ...

def validate_fee_snapshot(data: Any) -> None: ...
def load_fee_snapshot(path: Path = DEFAULT_FEE_SNAPSHOT_PATH) -> FeeSnapshot: ...
```

- **Index.** `from_dict` builds, once, `account_type -> set of account_key` and `(account_type, service_code,
  concept) -> {account_key: (amount | None, not_offered)}`. `declarations` is then a dictionary lookup plus one
  sort of at most a few hundred `Decimal`. No module-level state; the app caches the loaded object (§9).
- **No arithmetic** (REQ-PF-08): `sorted(...)`, `len(...)`, counting. Money arithmetic (median) is
  `money.median_amount`, called from the vf support code (§6), so the rule "`money.py` is the only module for
  monetary arithmetic" holds.
- **Decimals.** `json.loads(text, parse_float=Decimal)` is used so that an accidental JSON number never becomes a
  `float`; the validator then rejects any non-string amount. `size_bytes` is a JSON integer.
- **Validator order** (so messages are stable): top-level keys, format, dates, constants, account types,
  `excel_files`, accounts (one pass), rows (one pass: account known, service known, keys, text, amount, flag,
  duplicate, order). Each check raises on the first failure with the message of REQ-PF-02.
- **Order check.** The expected row order is `(index of account_type in ACCOUNT_TYPE_ORDER, entity_code,
  account_key, service_code)` non-decreasing; ties keep file order (the concept order is the publication order and
  is not validated).
- **Errors.** `load_fee_snapshot` catches `FileNotFoundError` (`file not found`), `UnicodeDecodeError` (`not UTF-8
  text`), `OSError` (`strerror`), `json.JSONDecodeError` (`invalid JSON at line N`) and wraps
  `FeeSnapshotError` from the validator as `invalid snapshot <path>: <message>`, exactly the shape of
  `ine_cpi.load_snapshot`.
- **Public names** exported by `ledger_kit/public_data/__init__.py`: `FeeSnapshot`, `FeeDeclarations`,
  `FeeSnapshotError`, `load_fee_snapshot`, `DEFAULT_FEE_SNAPSHOT_PATH`, `ACCOUNT_TYPES`, `ACCOUNT_TYPE_ORDER`,
  `SERVICES`, `ATTRIBUTION_TEMPLATE`, `attribution_for`, `validate_fee_snapshot`. The existing CPI names are
  untouched. The Vampire app imports only these (it may import `ledger_kit` public names).

## 4 — The importer (REQ-PF-04, REQ-PF-05) — BLOCKED

### 4.1 What is known and what is not

Known: the services and their codes, the account types, that amounts use a decimal comma, that an asterisk means
*No practicado*, that text carries trailing spaces and padding, that the page lists *Proveedor de la Cuenta* as a
service-like row. **Not known**: file extension, sheet names, whether one sheet holds one entity, whether the
declaration date and the type are written in the file, how the multiple declarations of one entity are laid out,
whether amounts are text or numbers, which padding characters occur. The importer is written **after** the file
exists, and the open points are closed then by an amendment written before any importer code (decision Q4). The
Excel is exported **by hand**; there is no automated access to the Banco de España site, ever, and the importer
reads local files only (decision Q6, DN-PF-23).

### 4.2 Structure that does not depend on the layout

```python
def read_workbook(path: Path, account_type: str) -> list[Record]: ...   # the ONLY layout-aware function
def build_snapshot(records: Iterable[Record], meta: Meta) -> dict: ...   # pure: trimming, decimals, codes, keys, order
def file_facts(path: Path) -> dict: ...                                  # name, size_bytes, sha256 (hashlib, 1 MB chunks)
def write_snapshot(snapshot: dict, path: Path) -> None: ...              # temp file in the same folder, os.replace
def main(argv=None, *, today: date | None = None) -> int: ...
```

`Record` is a plain dataclass: account type, entity code, entity name, account name, service label, concept,
text. `build_snapshot` maps labels to codes (`SERVICES` of the library), trims, converts amounts with
`Decimal(text.replace(".", "").replace(",", "."))` after checking the text against `^\d{1,3}(\.\d{3})*,\d{2}$`
or `^\d+,\d{2}$` (a euro amount is recognised by its concept ending in `(euros)` **and** its text matching one of
the two forms; a euro concept with any other text such as `ND` becomes `amount null`, `not_offered false`, kept as
text), assigns `account_key` by order of first appearance of each declaration, sorts rows (REQ-PF-01), then calls
`validate_fee_snapshot`. Everything the tests need to pin (REQ-PF-05 examples) lives here, so it is tested with no
Excel and no `openpyxl`.

### 4.3 Library and where it runs

- **`openpyxl`**, `load_workbook(path, read_only=True, data_only=True)`, iterate rows with `iter_rows(values_only=True)`.
  It reads `.xlsx`. It reads cached values, never formulas, and never opens the network. It does not read `.xls`
  (the old binary format) and does not read an HTML table saved with the `.xls` extension; if the real file is one of
  those the task PF8 chooses again (a stdlib `html.parser` reader for an HTML table, `xlrd` for a binary `.xls`) and
  records the decision as an amendment. The API facts above are from the library's documented behaviour as the author
  remembers it; PF8 re-checks them against the pinned version before writing code.
- **Dependency placement** (DN-PF-04): an optional extra `import` in `pyproject.toml` with an exact pin, **not** in
  `requirements.txt`, because Community Cloud installs `requirements.txt` and the apps never need the library. Two
  tests keep this true (REQ-PF-22): no file under `ledger_kit/`, `apps/` or `streamlit_app.py` imports `openpyxl`, and
  `requirements.txt` does not name it.
- **Developer machine only.** The script is run by hand (`python scripts/import_bde_fees.py ...` in PowerShell, venv
  active). No app, no CI step and no test of the apps calls it. Its own tests use a tiny synthetic workbook created in
  `tmp_path`; they `importorskip("openpyxl")`, so CI without the extra stays green and the pure mapping tests still run.
- **Validator.** The importer imports `validate_fee_snapshot` from the library instead of repeating it (DN-PF-04),
  unlike `fetch_ine_cpi.py`, which had to run in a bare Python. This is a deliberate exception to "scripts import
  nothing from the project"; `structure.md` is updated to say so (PF10).
- **Time and files are injected**: `main(..., today=None)` reads the clock only when `today` is `None`; paths are
  parameters. No function below `main` reads the clock.

### 4.4 Errors and atomicity

One-line `error: ...` on stderr, exit 1, existing snapshot untouched: the temporary file is created with
`tempfile.NamedTemporaryFile(dir=path.parent, delete=False)` and renamed with `os.replace` only after
`validate_fee_snapshot` passes. On Windows the replace of an open file fails with `PermissionError`, mapped to
`error: cannot write <path>: <reason>`.

## 5 — Median (REQ-PF-15)

```python
def median_amount(values: Sequence[Decimal]) -> Decimal:
    """Return the median of `values`, rounded half-up to cents; ValueError when empty."""
    ordered = sorted(values)
    if not ordered: raise ValueError("median of no values")
    mid = len(ordered) // 2
    if len(ordered) % 2: return round_to_cents(ordered[mid])
    return round_to_cents((ordered[mid - 1] + ordered[mid]) / 2)
```

The sum of two two-decimal values is exact and the division by 2 yields at most three decimals, so the only
rounding is the one `round_to_cents` does at the output boundary (Finance Rule 3). A tie such as `12.005` rounds
up to `12.01`. The median is chosen over the mean because fee distributions have a large spike at `0.00` and a long
tail up to a few hundred euros: the mean would describe no real account. It is the only aggregate that is computed
from amounts; the maximum is one of the amounts, the counts are counts.

## 6 — The detector side

### 6.1 Constants (REQ-PF-14)

`PEER_MIN_ACCOUNTS = 10` and `PEER_MAX_DATE_GAP_DAYS = 365` sit at the top of `detectors/utils.py` with a comment
for each, next to the other vf constants (Finance Rule 7). They do not decide whether an alert fires; they decide
whether the decoration is stated (REQ-PF-13).

**Why 10** (DN-PF-07). The tool itself treats 2 to 5 declarations as a screen comparison; a median and a maximum of
that few accounts describe those accounts, not "the Spanish banks". The only count the source facts give is 51
entities for `CNO`, so a real snapshot is far above 10 and the limit never blocks real data; it blocks a partial
snapshot (a type with a few declarations, a fixture, a damaged import) from producing a sentence that sounds like a
market statement. Ten is the smallest round number at which the 9-versus-10 boundary can be tested with a readable
fixture (`S10`). The count is of accounts **with an amount**: accounts that do not offer the service do not make the
sample bigger. The reviewer kept 10 (decision Q3).

**Why 365** (DN-PF-08). A yearly fee run (`YEARLY_NOMINAL_DAYS = 365`) has its last charge up to a year old and is
still the current fee; older than that, the series is stale and a comparison with today's declarations would mix
periods (Finance Rule 9: "if a public figure cannot be stated honestly for the period, the alert carries none").
The gap is measured in both directions because a statement can be newer than the snapshot (the declared fees may
have changed since) as well as older. The date is on the card, so the reader can see it. The reviewer kept 365
(decision Q3).

### 6.2 Matching (REQ-PF-09, REQ-PF-10)

```python
@dataclass(frozen=True)
class PeerService:
    key: str                   # "maintenance", "debit_card": the sub-table name
    service_code: str          # "101"
    concept: str               # published concept, verbatim
    label: str                 # English words for the sentence
    words: tuple[Phrase, ...]  # folded
    exclude: tuple[Phrase, ...]

@dataclass(frozen=True)
class PeerContext:
    snapshot: FeeSnapshot
    account_type: str
    services: tuple[PeerService, ...]

def build_peer_services(table: Mapping[str, Any]) -> tuple[PeerService, ...]: ...
def match_peer_service(fee: Fee, services: Sequence[PeerService]) -> PeerService | None: ...
```

`match_peer_service` uses `fee.counterparty` and `fee.description` (the two fields `classify_fee` reads) through
`fold_tokens` and `contains_phrase`, the same functions the vocabulary uses, so accents and case do not matter and a
phrase matches whole words only (`tarjeta debito` does not match `tarjeta debitos`; add the plural to the config if
needed). The algorithm is the four steps of REQ-PF-10. The ambiguity step comes **before** the exclusion step on
purpose: a text naming two services must not be reduced to one by an exclusion (`Cuota de mantenimiento de la cuenta
y tarjeta de débito` would otherwise be compared with debit cards only). Fail-safe direction everywhere: when in doubt
there is no comparison.

Why words and not Norma 43 concepts: a CSV has no bank concept and the common concepts 16 and 17 mean "any fee"
(`FEE_CONCEPTS`), so only the description tells the service. Why the plain words `tarjeta` and `card` are not debit
words: a credit card fee compared with debit-card maintenance would be the wrong comparison, and the text rarely says
which one.

`build_peer_services` is called once by the app from the `[peer_fees]` table; a bad table raises `ValueError` naming
the key (REQ-PF-09). `load_config` keeps returning the plain dict; the sub-tables are the dict values whose value is
a `dict` (`maintenance`, `debit_card`), so a third service is a new sub-table, not new code.

### 6.3 `peer_context_fields` and the detector

```python
def peer_context_fields(last: Fee, cost: Decimal, peers: object) -> dict[str, Any]:
    """Return the peer keys of REQ-PF-12 for a fee run, or {} when REQ-PF-14 says they cannot be stated."""
```

Steps: `peers` must be a `PeerContext` (`isinstance`, else `{}`); `service = match_peer_service(last, peers.services)`,
`None` → `{}`; `found = peers.snapshot.declarations(peers.account_type, service.service_code, service.concept)`,
`None` → `{}`; `len(found.amounts) < PEER_MIN_ACCOUNTS` → `{}`; `abs((last.date - date.fromisoformat(found.declaration_date)).days)
> PEER_MAX_DATE_GAP_DAYS` → `{}`; else the dict of REQ-PF-12 in that order: `lower = sum(1 for a in found.amounts if a < cost)`,
`zero = sum(1 for a in found.amounts if a == 0)`, `median = median_amount(found.amounts)`, `maximum = found.amounts[-1]`
(the list is sorted). `cost` is the `yearly_cost` Decimal the detector already computes, **not** the string, so the
comparison is exact. Amounts are `Decimal` with two decimals, so `a == 0` is `Decimal("0.00") == 0`. The strings use
`str(...)`: `str(Decimal("18.00"))` is `"18.00"`.

`recurring_fee.py` changes by two lines:

```python
peers = context.get("peers")
...
data = {...the eight existing keys...}
data.update(peer_context_fields(last, cost, peers))
alert = Alert(..., data=data)
```

The run, the interval, the severity (`cost >= RECURRING_FEE_WARNING_YEARLY_COST`), the title and `sorted_refs(run)` are
untouched. **The alert id does not change** when peer fields appear (decision Q7, DN-PF-17): every key that
`peer_context_fields` returns starts with `peer_`, and `ledger_kit/models.py` leaves every top-level `data` key with
the prefix `ALERT_ID_EXCLUDED_PREFIX = "peer_"` out of the id hash (one documented rule, one constant, task PF0).
No alert has a `peer_` key before this work, so every existing id, and every recorded answer in `data/live_runs/`
that the demo replays by alert id, is unchanged. The existing tests do not assert a literal vf id (to confirm in PF4
by searching for 64-hex literals before editing).

Rule 9 compliance, point by point: figures are named fields with scope fields; never in `source_refs`; context
around an alert that already fired (the fields are added after the severity is decided and cannot change it);
silent when the period is not honest (REQ-PF-14); attribution shown once on the page (REQ-PF-19); app, tests and
explanation layer read the committed file only. The one point beyond today's wording is the **aggregates**
(DN-PF-01): Rule 9 says values are "copied verbatim from the snapshot" and percentages are computed from fields in
`data`. A count, a median and a maximum over several snapshot rows are neither. They are admitted as deterministic
computed fields (Finance Rule 1 allows counts and aggregates of source rows as named fields), with the rows
identified by the scope fields instead of by `source_refs`. The reviewer approved this on 23 November 2026
(decision Q1): the legal notice allows reuse and calculations with the data if it is reproduced faithfully and the
source is cited, so the aggregates are allowed when labelled *Elaboración propia* (the attribution says so); PF10
adds the one sentence of §11 to Rule 9.

## 7 — The number guard (REQ-PF-16)

What `_passes_number_guard` does with the new fields, read from `explainer.py`:

- `_allowed_decimals` adds every number tokenised from `str(v)` for every value in `alert.data`. Integers (`12`, `3`,
  `9`, `5`, `22`) and amount strings (`"78.00"`, `"18.00"`, `"240.00"`) become allowed `Decimal`s, compared by value, so
  `18` and `18,00` both pass and `18,50` does not. `peer_service` (`"101"`) adds 101.
- `_tokenise` removes ISO dates (`YYYY-MM-DD`) and `dd/mm/yyyy` dates before it reads numbers, so
  `peer_declaration_date` `2026-11-23` becomes an allowed **date**, not three allowed numbers; a model text with
  `2026-11-24` is rejected as a date (`rejected_numbers == ("2026-11-24",)`), and `23-11-2026` (dashes, day first) is not
  a date pattern, so its `23`, `11` and `2026` are read as numbers and rejected unless they are allowed elsewhere. This is
  why the sentence uses the ISO form (DN-PF-13).
- `find_period_mismatches` reads field names: a name containing `yearly` or `per_year` is a yearly figure, and
  `interval_type` `monthly` makes `current_amount` a monthly one. `peer_median_yearly` and `peer_max_yearly` are therefore
  yearly figures, so `240,00 EUR per month` is rejected (`period_mismatch`). Counts have no stated period and are never
  period-checked. A value that appears in two fields with different periods, or in a field with no stated period, is
  skipped by that check (the guard's own rule), which only makes it more permissive.
- **No change to the guard is needed**, to the system prompt, or to `row_columns`. The smallest conceivable change
  (a new format spec) is also not needed: `{peer_median_yearly:money}` uses the existing `money` spec, counts and dates
  are plain text.
- Known limits, accepted (DN-PF-12): `101`/`401` become allowed numbers; the integers in the counts become allowed
  numbers for every text of that alert (the existing weakness of `charge_count` and the digits of `description`); the guard
  checks figures, not wording, so a model could still describe the comparison loosely (Finance Rule 8 is enforced by the
  fixed sentence on the card, not by the guard, as in `public-cpi` DN-CPI-12).

## 8 — Template and card helpers (REQ-PF-18, REQ-PF-19)

```python
PEER_SENTENCE = (
    "Of {peer_account_count} {peer_account_type_label} accounts that declared an annual {peer_service_label} "
    "fee to the Banco de España on {peer_declaration_date}, {peer_lower_count} charge less than this fee costs "
    "a year ({yearly_cost:money}). {peer_zero_count} charge nothing; the median is {peer_median_yearly:money} "
    "and the highest {peer_max_yearly:money}."
)
RECURRING_FEE_WITH_PEERS_TEMPLATE = (
    "{counterparty} charged you a {interval_type} fee of {current_amount:money} ({description}), "
    "{charge_count} times between {first_charge_date} and {last_charge_date}, about {yearly_cost:money} "
    "per year. " + PEER_SENTENCE + " Source: {source_refs}."
)
def template_for(alert: Alert) -> str:   # existing function, one more branch
    if alert.detector == "vf.recurring_fee" and "peer_median_yearly" in alert.data:
        return RECURRING_FEE_WITH_PEERS_TEMPLATE
    ...existing summary branch...
    return TEMPLATES[alert.detector]
```

The first half of the template repeats today's `TEMPLATES["vf.recurring_fee"]`; a test asserts the two start with the
same text so they cannot drift. The keys appear together or not at all, so a single key test is enough (as in
`public-cpi` §5.3). "No digit is written into a template" (existing rule) holds: `charge nothing` is a word, and the
sentence reads true for a zero count.

**Wording choices** (decision Q9: two short sentences instead of a nested one). *Accounts*, not *banks*: one entity
can have several declarations (Source fact 3), so the counts are of declarations (DN-PF-06). *Less than this fee
costs a year* is strict, matches `peer_lower_count` and says which figure is compared (the yearly cost of the fee,
shown in brackets). The zero count is its own short sentence, which reads more easily than the former nested
*of which N charge nothing*. *Declared to the Banco de España* is what the data is (the page says that only the data
the entities communicated are shown). No comparative about the user (no *above*, *below*, *expensive*), no advice
(Finance Rule 8). A test scans the sentences for the words `above`, `below`, `too`, `expensive`, `should`, `cheaper`,
`switch`.

**Card helpers** (pure, in `settings.py`, testable without Streamlit):

```python
def peer_source_line(alert: Alert) -> str | None
def peer_sentence_to_add(alert: Alert, explanation: Explanation) -> str | None   # fill_fallback(PEER_SENTENCE, alert) unless present or no keys
def peer_attribution_lines(snapshot: FeeSnapshot) -> list[str]
```

`_render_alert` of `app.py` (read before editing; the first 450 lines were read and the function is below that) calls
the first two after the explanation and the guard badge: the sentence as `st.caption` when returned, then the source line
as `st.caption`. The text is shown through `markdown_safe` (`settings.markdown_safe`, already in the app): the entity-free
strings are ours, but `peer_account_type_label` and `peer_service_label` come from the config. No `unsafe_allow_html` is
added. The comparison is thus visible whatever the model writes, and the model cannot remove it (same reasoning as
`public-cpi` DN-CPI-12). The `chip_source_template` helper rewrites the `Source: {source_refs}.` tail of a template; the
new template keeps that tail exactly (read `ledger_kit/ui/signatures.py` before editing to confirm what it matches).

## 9 — App wiring and attribution (REQ-PF-19, REQ-PF-20)

- `settings.load_peers(config, root, account_type) -> PeerContext | None` loads
  `Path(root) / config["peer_fees"]["snapshot_path"]` with `load_fee_snapshot`, builds the services with
  `build_peer_services`, returns the context; `FeeSnapshotError` → `None`. A separate `peer_status(config, root) ->
  Literal["ok","missing","invalid"]` lets the app pick the caption text without parsing a message.
- `run_pipeline(name, data, *, vocabulary, cache=None, peers=None)` builds
  `context = {"vocabulary": vocabulary}` and adds `"peers": peers` only when it is not `None`, so every existing call and
  test is byte-identical. `run_all` copies the mapping shallowly, so the object reaches the detector unchanged (verified
  in `public-cpi` §8 for `registry.py`; re-confirmed in PF6).
- `app.py`: `_load_snapshot()` wrapped in `st.cache_resource` (immutable object); `_render_sidebar` draws the select box
  `Compare my fees with` (key `vf_peer_type`, in `WIDGET_KEYS`) when a snapshot is loaded; options and initial value come
  from `peer_type_options(snapshot)` and `default_peer_type(snapshot, config default)` (pure, REQ-PF-20). The sidebar
  function today returns the uploaded file; it will also leave the chosen type in session state, and the code that calls
  `run_pipeline` passes `peers=PeerContext(snapshot, st.session_state[PEER_TYPE_KEY], services)`.
- The footer `_render_attribution(snapshot)` writes `peer_attribution_lines(snapshot)` as `st.caption` **once**, while a
  snapshot is loaded (the data is on the page even when no card uses it, as for the CPI). Missing or invalid snapshot:
  the caption of REQ-PF-19 instead, no footer, no select box.
- `streamlit_app.py` Home: one `st.caption` with the attribution **only when `load_fee_snapshot` succeeds**
  (DN-PF-16; the CPI Home caption is unconditional because its snapshot is committed, this one is not yet). A test in
  `tests/test_showcase_app.py` covers both states.
- The alert-id cache `EXPLANATIONS_KEY` keyed `(alert.id, mode)` **does need a change**: the id no longer includes
  the peer fields (decision Q7), so a new account type or a new snapshot would otherwise reuse an explanation that
  holds the comparison of the previous type. `settings.explanation_cache_key(alert, mode)` returns
  `(alert.id, mode, peer_items)`, where `peer_items` is the tuple of the `(key, value)` pairs of `alert.data` whose
  key starts with `ALERT_ID_EXCLUDED_PREFIX`, in `data` order (`()` for an alert without them); the Vampire app uses
  it instead of `(alert.id, mode)`. The other apps are not touched.
- **Recorded model runs.** `replay.card_recording(alert.id)` and `replay.probe_recording(alert.id, ...)` look recordings
  up by alert id, and `data/live_runs/` holds recorded answers for `vf.recurring_fee` alerts (decision Q7). Because the
  id leaves out the `peer_*` keys, those recordings are found with and without the snapshot; the recorded text goes
  through today's guard with the alert as it is (peer fields included), and the card supplies the comparison when the
  recorded text lacks it (`peer_sentence_to_add`). Nothing is re-recorded.
- **Phantom Invoices and Zombie Subscriptions** get nothing. The Exorcise draft of Vampire Fees (`action_templates.py`,
  `check_figures`) is unchanged (non-goal).

## 10 — Test plan (testing.md tiers)

The reader and the importer are not detectors, so the normal / edge / property split is used for them; the detector
tiers apply to `vf.recurring_fee`.

| Module | Tier 1 (normal) | Tier 2 (edge) | Tier 3 (Hypothesis, `max_examples=200`) |
|---|---|---|---|
| `money.median_amount` | REQ-PF-15 examples | empty, one value, even count, half-up tie, unsorted input unchanged | result within `[min, max]`, two decimals |
| `bde_fees` validator | `S12` and `S10` pass | each rejection of REQ-PF-02 with its message | a generated valid snapshot passes; deleting a key or an account referenced by a row fails |
| `bde_fees` reader | REQ-PF-07 examples | unknown type or service (`ValueError`), type absent (`None`), no rows, only asterisks, repeated amounts, a file missing / invalid JSON / invalid | `amounts` sorted; `len + not_offered + without == account_count`; every amount is a row |
| importer `build_snapshot` | REQ-PF-05 examples | unknown label, `3,999`, duplicate declaration, padding `\u00a0`, asterisk with spaces | round trip: `validate_fee_snapshot(build_snapshot(records))` passes for generated records |
| importer `main` | tiny synthetic workbook → file | missing file, failed check leaves old file byte-identical, `today` injected | — |
| `build_peer_services`, `match_peer_service` | REQ-PF-10 table | bad table (each message of REQ-PF-09), empty sub-tables, accents and case, plural not matched | folded matching is insensitive to case and accents; two services never both returned |
| `vf.recurring_fee` + peers | REQ-PF-12 dict (`S12`) and `S10`; no `peers` → eight-key dict | every REQ-PF-14 case (9 vs 10 amounts, gap 365 vs 366, wrong type, empty services, plain dict); empty and single-row ledgers; duplicate `source_ref` | REQ-PF-13 agreement property; `source_refs ⊆ loaded_source_refs`; idempotency; figures equal an independent recomputation |
| guard with peer fields | REQ-PF-16 accepted text | `13`, `250,00`, `18,50`, `2026-11-24`, `18 EUR`, `per month` | text made only of numbers of `data` accepted; plus one number outside rejected |
| templates / card helpers | REQ-PF-18/19 examples | alert without keys, model text with and without sentence, zero counts | the card never shows the sentence twice |
| demo `AppTest` | counts unchanged; both cards; custody card without | no snapshot file; invalid snapshot; type `COT` with 8 amounts; snapshot only `CDI` | — |
| documents and boundaries | attribution texts equal everywhere | no `openpyxl` import in `ledger_kit/`, `apps/`, `streamlit_app.py`; not in `requirements.txt` | — |

Fixtures are **synthetic** and live in `tests/public_data/bde_builders.py` (library) and are re-exported by
`apps/vampire_fees/tests/conftest.py`: `synthetic_s12_snapshot` (REQ-PF-07), `synthetic_s10_snapshot` (REQ-PF-12),
`synthetic_snapshot_cdi_only`, `synthetic_snapshot_cno_cot` (with `COT` at 8 amounts). Entities are `9901 BANCO
FICTICIO`, `9902 Caja Demo`, ...; no name or amount of a real declaration appears. The demo test writes a snapshot built
by the builder to `tmp_path` and points `snapshot_path` at it by patching the loaded config (same technique as
`public-cpi` CPI9). The committed-snapshot test is the only one that reads `data/public/`. No test reads the clock or the
network; the fee dates are given explicitly, the importer's `today` is a parameter.

## 11 — Documentation and steering (PF7, PF10)

- `data/public/README.md`: a second section for `bde_payment_account_fees.json`: source and start page, how the Excel is
  generated (by hand, with the owner's approval, one per account type), what is recorded (name, size, SHA-256), licence
  condition (faithful reproduction, citation), attribution, non-endorsement, **"the file does not exist yet"** until PF9,
  and the importer command. The first line of the file ("only place where data is neither synthetic nor generated by a
  script of this project") stays true.
- Root `README.md`: a short paragraph in the existing "Public data" section (read `tests/test_readme.py` first), with the
  sentence of REQ-PF-19 about the snapshot.
- Steering, **approved by the reviewer on 23 November 2026** (decision Q1; these files bind every later session):
  `finance-rules.md` Rule 6 (`data/public/` also holds the BdE snapshot) and Rule 9, widened by **one sentence**:
  *"Aggregates of the rows of one public snapshot (a count, a median, a maximum) may appear as named fields of
  `Alert.data` when the source's licence allows calculations with its data, the attribution labels them as our own
  work (Elaboración propia), the source, scope and date are fields of the same alert, their `data` keys start with
  `peer_` (left out of the alert id), and a test recomputes them from the snapshot."*; `structure.md` (the new files
  above, and that `import_bde_fees.py` may import the library validator and reads local files only); `tech.md` (the
  BdE comparator row: no API, no automated access, Excel exported by hand, `openpyxl` only in the optional extra
  `import`, never at run time; the alert id note). Keep `test_pi_structure_steering.py` green: read it first.

## 12 — Decisions

| Id | Decision | Reason |
|---|---|---|
| DN-PF-01 | Peer aggregates (count, median, maximum) are named fields of `Alert.data` with scope fields (`peer_account_type`, `peer_service`, `peer_concept`, `peer_declaration_date`); never in `source_refs`; Finance Rule 9 is widened to allow them by one sentence (§11), approved with decision Q1, applied in PF10 | Rule 1 allows aggregates as named fields; Rule 9 today names verbatim values and percentages only. A pseudo `source_ref` would break the UI resolver and `loaded_source_refs` (as DN-CPI-01) |
| DN-PF-02 | The snapshot has `accounts` and `rows`, joined by (`account_type`, `account_key`) | Same information as the flat row requested, no repeated names, accounts without rows stay countable, names are validated once |
| DN-PF-03 | Our own snapshot format; only the importer reads the Excel | The layout is unknown (Source fact 6); the reader, detector and tests must not depend on it |
| DN-PF-04 | The importer imports the library validator and uses `openpyxl` from an optional extra; the Excel files are not committed; name, size and SHA-256 are recorded | It needs the developer venv anyway; Community Cloud installs `requirements.txt` only; the hash makes the derivation checkable |
| DN-PF-05 | The reader sorts amounts ascending and does no arithmetic; the median is `money.median_amount` | `money.py` is the only module for monetary arithmetic; sorted output makes the maximum and the median trivial and testable |
| DN-PF-06 | Counts are of accounts (declarations) that declared an amount; accounts that do not offer the service are reported separately and never counted as `0.00` | One entity can have several accounts (Source fact 3); an asterisk and a declared `0,00` are different statements |
| DN-PF-07 | `PEER_MIN_ACCOUNTS = 10`, counted on accounts with an amount | See §6.1; kept by the reviewer (decision Q3) |
| DN-PF-08 | `PEER_MAX_DATE_GAP_DAYS = 365`, both directions | See §6.1; Finance Rule 9 "honest for the period"; kept by the reviewer (decision Q3) |
| DN-PF-09 | Matching by words in `config.toml`; two services matching → none; an exclusion word → none; no word → none | Fail-safe direction; a CSV has no bank concept; wrong comparison is worse than none |
| DN-PF-10 | One context key `"peers"` holding a `PeerContext` | The detector stays a pure function of `(ledger, context)`; one object keeps the three inputs consistent (all or nothing) |
| DN-PF-11 | Only concepts whose name says *Anual total* are compared; the peer amount fields end in `_yearly` | The sentence says "annual" truthfully; the guard's period check then covers the figures |
| DN-PF-12 | The service code (`101`, `401`) and the counts become allowed numbers; accepted | Same kind of widening as DN-CPI-18; removing the code would remove the citation |
| DN-PF-13 | The declaration date is shown in ISO form | The guard recognises ISO and `dd/mm/yyyy` dates only; `23-11-2026` would be rejected as numbers |
| DN-PF-14 | Default account type `CNO`, a select box among the types present | See REQ-PF-20; `CNO` is the default of the Banco de España tool itself (decision Q2); the type is always named in the sentence |
| DN-PF-15 | The comparison is fixed, neutral and written as two short sentences: the lower count against the yearly cost, then the zero count, the median and the highest (decision Q9); the card supplies it when the model drops it | Finance Rule 8; the comparison must not depend on the wording of a model |
| DN-PF-16 | Attribution on the Vampire page and on Home only while a snapshot loads; README and `data/public/README.md` always | Attribution belongs where the data is shown; with no snapshot a credit would be false |
| DN-PF-17 | **Replaced on 23 November 2026 (decision Q7).** Alert ids do **not** change when peer fields are added: `_deterministic_alert_id` leaves out every top-level `data` key that starts with `ALERT_ID_EXCLUDED_PREFIX = "peer_"`; the Vampire explanation cache key gains the peer fields (§9). The former decision ("ids change") is withdrawn | `data/live_runs/` holds recorded model answers for `vf.recurring_fee` alerts that the demo replays by alert id; no alert has a `peer_` key today, so no existing id changes |
| DN-PF-18 | The Exorcise drafts do not quote the comparison | A complaint letter that cites a median is a financial argument; out of scope (Finance Rule 8) |
| DN-PF-19 | No snapshot: no select box, no keys, a caption, no placeholder | Nothing may be invented (Finance Rule 1) |
| DN-PF-20 | `.gitignore` ignores `*.xlsx` and `*.xls` | An export must never be committed by accident |
| DN-PF-21 | The attribution is `attribution_for(declaration_date)`: `Fuente: Banco de España, comparador de comisiones de cuentas de pago (declaraciones a fecha YYYY-MM-DD). Elaboración propia: recuento, mediana y máximo.`, shown once on the page (decision Q1) | The legal notice allows calculations when the data is reproduced faithfully and the source is cited; *Elaboración propia* labels the aggregates as ours |
| DN-PF-22 | First snapshot: `CNO` and `COT` required, `CDI` and `CJO` if downloaded, `CBA` not needed; the validator accepts any non-empty set, the committed-file check requires `CNO` and `COT` (decision Q5) | `CNO` is the default; `COT` is the closest type to a plain current account |
| DN-PF-23 | No automated access to the Banco de España site, ever; the export is manual and the importer reads local files only (decision Q6) | The BdE terms for automated access were not checked, and a file-based importer needs none |

## 13 — Risks

1. **The Excel is not `.xlsx`, or is laid out in a way that does not fit `Record`.** The importer task is blocked and
   written against the real file; the rest of the work does not depend on it. Mitigation: PF8 starts by reading the real
   file and writes an amendment to this spec before code.
2. **The same account listed twice** in the Excel (one declaration per entity and per date, but several rows per
   service). `account_key` is assigned by first appearance; a duplicate declaration would inflate counts. Mitigation: the
   importer rejects two declarations with the same entity code, account name and identical cells, and the real-file
   review looks at the entities with more than one account.
3. **Comparability.** The user's `yearly_cost` is the last charge times the periods per year; the BdE concept is the
   annual total of the service as the entity declares it. They can differ in what they include (waivers for a payroll
   account, a fee that is free above a balance). The sentence says only what the entities declared; the card says the
   comparison is context; Finance Rule 8 forbids a conclusion. Only the two annual-total concepts are compared;
   fees with a waiver condition are a non-goal (decision Q10).
4. **Entities with several accounts weigh more** than entities with one (the count is of declarations). The sentence says
   *accounts*, never *banks*.
5. **A stale snapshot.** The declaration date is in the sentence and `PEER_MAX_DATE_GAP_DAYS` stops a comparison across
   more than a year; the developer refreshes the snapshot by running the importer on a new Excel.
6. **Recorded model runs keyed by alert id** (§9): closed by decision Q7, the id leaves out the `peer_*` keys.
7. **Size of the file** (§2.2): split by type if the real file is larger than 5 MB.
8. **Guard widening** by the service code and the counts (§7, DN-PF-12).
9. **Licence wording.** Closed by decision Q1: the aggregates are labelled *Elaboración propia* in the attribution.

## 14 — Former open questions

All ten questions were answered by the reviewer on 23 November 2026. The answers are recorded in the section
*Decisions on the former open questions* at the end of `tasks.md` and in the table of §12 (DN-PF-01, -02, -03, -07,
-08, -11, -14, -15, -17, -21, -22, -23). The questions as they were asked are kept below for the record.

- **Q1 — Attribution and faithfulness.** Is the wording of `attribution` acceptable, and is it allowed to publish counts,
  a median and a maximum computed from the declared figures while citing the BdE as the source ("reproduced faithfully")?
  Do you approve the Rule 9 widening for aggregates (DN-PF-01)? If the answer to the first part is no, the sentence can be
  reduced to counts and the maximum (verbatim values) and the median dropped.
- **Q2 — Default account type.** Is `CNO` the right default, or should the default be `COT` (*Otras Cuentas*), the closest
  type to a plain current account?
- **Q3 — The two limits.** `PEER_MIN_ACCOUNTS = 10` and `PEER_MAX_DATE_GAP_DAYS = 365`: keep, or change?
- **Q4 — The Excel.** Once it exists: extension and library; whether the declaration date and the account type are in the
  file; the padding characters; how entities with several accounts are laid out; whether amounts are text or numbers; whether
  the entity code is shown with its leading zeros.
- **Q5 — Which types in the first snapshot.** Only `CNO` (one export) or all five (five exports and a larger file)? The
  select box adapts to what is present.
- **Q6 — Export permission.** The owner approves generating the Excel by hand in the tool; the BdE terms for any automated
  access were not checked and the importer never accesses the site.
- **Q7 — Recorded runs.** Does `data/live_runs/` hold answers for `vf.recurring_fee` alerts? If yes, should they be
  re-recorded once the snapshot is committed?
- **Q8 — Account identity.** Is the file order a stable enough basis for `account_key`, or does the real file give an
  identifier worth keeping?
- **Q9 — Wording.** Is "charge less than 78,00 EUR, of which 5 charge nothing" the clearest neutral form, or should the
  sentence list the three figures separately?
- **Q10 — Comparability.** Should the sentence restrict itself to maintenance fees declared as a fixed annual total
  (the two concepts of REQ-PF-09), as the first version does, or should a later version also compare fees with a
  waiver condition?
