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
| `scripts/import_bde_fees.py` | Reads the exported `.xls` files with `xlrd`, writes the snapshot (§4, amendment A1). Developer machine only |
| `data/public/bde_payment_account_fees.json` | The committed snapshot. **Does not exist yet** (§2.4) |
| `ledger_kit/public_data/bde_fees.py` | `FeeSnapshot`, `FeeDeclarations`, `FeeSnapshotError`, `load_fee_snapshot`, `validate_fee_snapshot`, constants (§3) |
| `tests/public_data/bde_builders.py` | Builders of **synthetic** snapshots `S12`, `S10` and a random-snapshot strategy |
| `tests/public_data/test_bde_fees_reader.py`, `test_bde_fees_validator.py`, `test_bde_fees_snapshot.py` | Reader, validator, committed snapshot (skipped while absent) |
| `tests/test_import_bde_fees.py` | Importer: `parse_grid` on synthetic grids, `build_snapshot` on synthetic records, `read_grid` with a fake `xlrd` in `sys.modules`, `main` exit codes and stderr lines (§4) |
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
| `README.md`, `data/public/README.md`, `data/samples/README.md`, `.gitignore`, `pyproject.toml` | docs, `*.xlsx`/`*.xls` ignore, optional extra `import` with `xlrd==2.0.1` (PF7, PF8) |
| `ledger_kit/public_data/bde_fees.py` (PF8) | `excel_files` may hold several entries per type; two entries with the same `sha256` are an error (DN-PF-26) |
| `tests/public_data/bde_builders.py`, `test_bde_fees_validator.py`, `test_bde_fees_snapshot.py`, `apps/vampire_fees/tests/test_vf_peer_support.py`, `apps/vampire_fees/config.toml` (PF8) | the Excel spelling of the two compared concepts (DN-PF-28); one hash per fixture file; the committed-file check requires `CNO` only (DN-PF-25) |
| `.kiro/steering/{finance-rules,structure,tech}.md` | last task only, after review (§11) |

`ledger_kit/explainer.py` is **not** edited: the format specs `money` and plain text already cover every
placeholder of the sentence (§7).

## 2 — The snapshot

### 2.1 Why our own format

The Excel layout was unknown when this design was written (Source fact 6; it is now Source fact 8) and the BdE
page offers no stable file. A snapshot in our own format
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
`config.toml`); that is not needed for the first version. **Amendment A1 (DN-PF-25, replaces DN-PF-22):** a type
enters the snapshot only when its files hold every entity the tool lists for it; the first snapshot holds `CNO`
only (51 entities, 92 accounts), and `COT` is left out until its missing parts are exported. Only the rows of
services `101` and `401` are stored (DN-PF-27), so the real file is far below 5 MB.

### 2.3 Fields and their reasons

- **`account_key`** is `"<entity_code>-<nn>"`, our ordinal in file order. The source gives no account id and one
  entity can have several accounts of the same type with, possibly, the same name (Source fact 3); the ordinal is
  stable within one snapshot, which is all a count needs. A re-import may renumber; nothing outside the
  snapshot stores a key. Decision Q8 confirms this: entity code plus the position of the account within that
  entity in file order, and the snapshot keeps `account_name` for display.
- **`declaration_date` on each account and on the top level**, equal by REQ-PF-02. Format 1 has one date; the
  duplication keeps the row granularity of the request and lets a future format carry several dates without
  changing the meaning of an account (the `snapshot_format` number is the switch).
- **`excel_files`**, one object per exported file, one or more per account type: the tool exports one type per
  Excel and refuses more than 238 declarations per export, so a large type needs several files (amendment A1,
  DN-PF-26). Every export is named `CompararEntidadesCCP.xls`, so names may repeat; the SHA-256 tells the files
  apart and two entries with the same hash are an error.
  Name, size in bytes and SHA-256 of the file **as downloaded** make the derivation checkable against the file
  the developer still has; the Excel itself is not committed (it is BdE data in a form we do not control and it
  could carry padding we would then have to review).
- **`text` and `amount`**: `text` is the published cell, trimmed (faithful reproduction, Source fact 7); `amount`
  exists only for euro amounts and is the string with a decimal point and two decimals; the reader and the guard
  never parse `text`. Percentages and names keep only `text`.
- **`not_offered`**: the asterisk, kept as a flag with `text "*"`. Its legend in the Excel is `(*) No se cobra
  comisión/no se ofrece el servicio` (on screen: *No practicado*). It is never counted as `0.00` nor as an
  amount (DN-PF-06, DN-PF-29).
- **`licence_note`, `attribution`, `no_endorsement`** are constants of the reader module, copied into the file and
  checked equal on load (the CPI snapshot works the same way). The attribution is the text the reviewer decided on
  23 November 2026 (decision Q1): `Fuente: Banco de España, comparador de comisiones de cuentas de pago
  (declaraciones a fecha YYYY-MM-DD). Elaboración propia: recuento, mediana y máximo.` The date is the snapshot's
  `declaration_date`, so the module holds `ATTRIBUTION_TEMPLATE` with a `{declaration_date}` placeholder and
  `attribution_for(declaration_date)`; the validator compares the file's text with `attribution_for` of the file's
  own date. *Elaboración propia* labels the counts, the median and the maximum as our calculation, which the legal
  notice allows when the data is reproduced faithfully and the source is cited (DN-PF-21).

### 2.4 State today

The file does not exist. The Excel files were exported on 23 November 2026 and are kept outside the repository;
the snapshot is written when the developer runs the importer (PF9). `DEFAULT_FEE_SNAPSHOT_PATH` points at it; `load_fee_snapshot` raises `FeeSnapshotError`
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

## 4 — The importer (REQ-PF-04, REQ-PF-05) — amended by A1

### 4.1 What is known

Everything Q4 asked is now known (Source fact 8, facts F1 to F8 of amendment A1): the file is a binary `.xls`
(BIFF8) with one sheet; the generation date, the title (with the account type) and the declaration date are
written above the table; the table has a `SERVICIOS` row of service labels and a `CONCEPTOS` row of concept
labels; blocks are found by header text because the cash-machine block moves every later column; an entity
with several accounts fills its code and name on its first account only; every value cell is text; the only
padding is trailing spaces; entity codes are four-digit text. The Excel is exported **by hand**; there is no
automated access to the Banco de España site, ever, and the importer reads local files only (decision Q6,
DN-PF-23).

### 4.2 Structure (DN-PF-31)

```python
class GridCell(NamedTuple):            # one cell as text; `number` marks a number cell
    text: str
    number: bool = False
Grid = tuple[tuple[GridCell, ...], ...]

@dataclass(frozen=True)
class Cell:                            # one published value of a kept block
    service_label: str; concept: str; text: str
@dataclass(frozen=True)
class Record:                          # one account (declaration) with its cells, in file order
    account_type: str; entity_code: str; entity_name: str; account_name: str
    cells: tuple[Cell, ...]
@dataclass(frozen=True)
class ParsedFile:
    account_type: str; declaration_date: str; retrieved_on: str; title: str
    records: tuple[Record, ...]
@dataclass(frozen=True)
class Meta:
    declaration_date: str; retrieved_on: str; excel_files: tuple[Mapping[str, Any], ...]

def read_grid(path: Path) -> Grid: ...                            # the ONLY function that imports xlrd
def parse_grid(grid: Grid, account_type: str) -> ParsedFile: ...  # pure; the ONLY one that knows the layout
def build_snapshot(records: Iterable[Record], meta: Meta) -> dict: ...  # pure: trimming, decimals, codes, keys, order
def file_facts(path: Path, account_type: str) -> dict: ...        # account_type, name, size_bytes, sha256
def write_snapshot(snapshot: dict, path: Path) -> None: ...       # temp file in the same folder, os.replace
def main(argv: Sequence[str] | None = None) -> int: ...           # reads no clock
```

- **`read_grid`** imports `xlrd` inside the function, opens the file with `xlrd.open_workbook(path,
  logfile=<a StringIO>)` (the size warning of F1 goes to that buffer and does not stop the import) and reads
  sheet 0: a text cell as written, an empty or blank cell as `""`, a number cell whose value is whole as
  `GridCell(str(int(value)), number=True)`; a number that is not whole, a date, a boolean or an error cell is
  the error `cannot read <path>: cell at row R column C is not text or a whole number`. A missing file is
  `cannot read <path>: file not found`; `xlrd` missing is `cannot read <path>: xlrd is not installed (pip
  install -e ".[import]")`; any error of `xlrd` is `cannot read <path>: <message>`.
- **`parse_grid`** (all row and column numbers 0-based):
  1. the header row is the one row whose column 0, trimmed, is `SERVICIOS`; the concept row is the next one,
     its column 0 starts with `CONCEPTOS` and, whitespace collapsed, contains the asterisk legend
     `(*) No se cobra comisión/no se ofrece el servicio`;
  2. in the rows above the header, exactly one cell matches each of `Fecha: DD/MM/YYYY [H:MM:SS]`
     (`retrieved_on`), `Fecha de referencia: DD-MM-YYYY` (`declaration_date`) and a title starting with
     `COMPARACIÓN ENTRE ENTIDADES`; the title ends with the label of one account type in capitals
     (`ACCOUNT_TYPES[code].label.upper()`), which must equal `account_type`;
  3. from column 1 of the header row, each non-empty label starts a block that runs to the column before the
     next non-empty label (the last one to the end of the row); `Proveedor de la Cuenta` is the provider block;
     every other label must be one of `SERVICES` and appear once; columns whose concept is empty are spacers;
  4. kept blocks are `KEPT_SERVICES = ("101", "401")`; each must exist, hold its `COMPARED_CONCEPTS` entry and
     hold no concept twice; the provider block must hold `Nombre de la cuenta`; other blocks are not read
     beyond their label (DN-PF-27);
  5. every row after the concept row that is not wholly empty is one account; a non-empty column 0 starts a
     new entity (four digits, a non-empty column 2); an empty column 0 with an empty column 2 belongs to the
     entity above; an entity that appears twice is an error; the account name is the provider cell; a number
     cell in a kept block or the provider block is an error; the record keeps the non-empty cells of the kept
     blocks with their service label and concept, in column order.
- **`build_snapshot`** trims every text, maps labels to codes, converts amounts (a euro concept, ending in
  `(euros)`, whose text is made of digits, dots and commas must match `^\d{1,3}(\.\d{3})+,\d{2}$` or
  `^\d+,\d{2}$`, more than two decimals is the error of REQ-PF-04 and any other such text is `amount '<text>'
  of <type> <key> service <code> is not a euro amount with two decimals`; `Decimal(text.replace(".",
  "").replace(",", "."))`), keeps other texts, numbers the accounts within each entity in record order
  (`account_key`), sorts accounts and rows (REQ-PF-01), adds the constants and `excel_files` of `meta`, then
  calls `validate_fee_snapshot`; a `FeeSnapshotError` becomes `snapshot check failed: <message>`.
- **`main`** parses the command line (an `argparse` parser whose `error` raises the importer's error, so a wrong
  command line is one `error:` line and exit 1), checks `--declaration-date` and the `TYPE=PATH` / `TYPE=N`
  pairs, reads and parses each file in the order given, then checks across files: one declaration date and one
  generation date for all files, `--declaration-date` equal to it, no two files with the same SHA-256, no
  entity in two files of one type, and the number of distinct entities of each type equal to its
  `--expect-entities` (DN-PF-25, DN-PF-26, DN-PF-30). It builds, validates and writes the snapshot.

### 4.3 Library and where it runs

- **`xlrd` 2.0.1** (DN-PF-24): `openpyxl` cannot read `.xls`; `xlrd` 2.x reads exactly the old binary format
  and nothing else, never evaluates formulas and never opens the network. The reviewer confirmed it reads the
  three real files.
- **Dependency placement** (DN-PF-04): an optional extra `import = ["xlrd==2.0.1"]` in `pyproject.toml`,
  **not** in `requirements.txt`, because Community Cloud installs `requirements.txt` and the apps never need
  the library. Tests keep this true (REQ-PF-22): no file under `ledger_kit/`, `apps/` or `streamlit_app.py`
  imports `xlrd`, `requirements.txt` does not name it, and in the script the only `import xlrd` is inside
  `read_grid`.
- **Developer machine only.** The script is run by hand (`python scripts/import_bde_fees.py ...` in PowerShell,
  venv active, extra `import` installed). No app, no CI step and no test of the apps calls it. Its own tests
  build synthetic grids and records in memory and replace `xlrd` by a fake module in `sys.modules`, so they run in
  CI, where the extra is not installed (`.github/workflows/tests.yml` installs `requirements.txt` only).
- **Validator.** The importer imports `validate_fee_snapshot` from the library instead of repeating it (DN-PF-04),
  unlike `fetch_ine_cpi.py`, which had to run in a bare Python. This is a deliberate exception to "scripts import
  nothing from the project"; `structure.md` is updated to say so (PF10). The script puts the repository root on
  `sys.path` at its top, as the apps do, so `python scripts/import_bde_fees.py` works from the root.
- **No clock** (DN-PF-30): both dates come from the files; no function of the script reads the clock.

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
  `Compare my fees with` (key `vf_peer_type`, in `WIDGET_KEYS`) when a snapshot with **two or more** account types
  is loaded (with one type, no select box and that type is used, DN-PF-32); options and initial value come
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
| importer `parse_grid`, `build_snapshot` | a synthetic grid in the layout of Source fact 8 (two entities, one with three accounts, a cash-machine block with repeated concepts, trailing spaces, an asterisk, `1.234,56`); REQ-PF-05 examples | each layout error of §4.2, unknown label, `3,999`, title type mismatch, a kept block without its compared concept, a number cell in a kept block | round trip: `validate_fee_snapshot(build_snapshot(records))` passes for generated records |
| importer `read_grid`, `main` | a fake `xlrd` in `sys.modules` → grid → file | missing file, `xlrd` missing, a non-whole number cell, dates that differ between files, an entity in two files, a wrong `--expect-entities` count, the same SHA-256 twice, a failed run leaves the old file byte-identical | — |
| `build_peer_services`, `match_peer_service` | REQ-PF-10 table | bad table (each message of REQ-PF-09), empty sub-tables, accents and case, plural not matched | folded matching is insensitive to case and accents; two services never both returned |
| `vf.recurring_fee` + peers | REQ-PF-12 dict (`S12`) and `S10`; no `peers` → eight-key dict | every REQ-PF-14 case (9 vs 10 amounts, gap 365 vs 366, wrong type, empty services, plain dict); empty and single-row ledgers; duplicate `source_ref` | REQ-PF-13 agreement property; `source_refs ⊆ loaded_source_refs`; idempotency; figures equal an independent recomputation |
| guard with peer fields | REQ-PF-16 accepted text | `13`, `250,00`, `18,50`, `2026-11-24`, `18 EUR`, `per month` | text made only of numbers of `data` accepted; plus one number outside rejected |
| templates / card helpers | REQ-PF-18/19 examples | alert without keys, model text with and without sentence, zero counts | the card never shows the sentence twice |
| demo `AppTest` | counts unchanged; both cards; custody card without | no snapshot file; invalid snapshot; type `COT` with 8 amounts; snapshot only `CDI` | — |
| documents and boundaries | attribution texts equal everywhere | no `xlrd` import in `ledger_kit/`, `apps/`, `streamlit_app.py`; not in `requirements.txt` | — |

Fixtures are **synthetic** and live in `tests/public_data/bde_builders.py` (library) and are re-exported by
`apps/vampire_fees/tests/conftest.py`: `synthetic_s12_snapshot` (REQ-PF-07), `synthetic_s10_snapshot` (REQ-PF-12),
`synthetic_snapshot_cdi_only`, `synthetic_snapshot_cno_cot` (with `COT` at 8 amounts). Entities are `9901 BANCO
FICTICIO`, `9902 Caja Demo`, ...; no name or amount of a real declaration appears. The demo test writes a snapshot built
by the builder to `tmp_path` and points `snapshot_path` at it by patching the loaded config (same technique as
`public-cpi` CPI9). The committed-snapshot test is the only one that reads `data/public/`. No test reads the clock or the
network; the fee dates are given explicitly, and the importer takes its dates from the files (DN-PF-30).

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
  BdE comparator row: no API, no automated access, Excel exported by hand, `xlrd` only in the optional extra
  `import`, never at run time; the alert id note). Keep `test_pi_structure_steering.py` green: read it first.

## 12 — Decisions

| Id | Decision | Reason |
|---|---|---|
| DN-PF-01 | Peer aggregates (count, median, maximum) are named fields of `Alert.data` with scope fields (`peer_account_type`, `peer_service`, `peer_concept`, `peer_declaration_date`); never in `source_refs`; Finance Rule 9 is widened to allow them by one sentence (§11), approved with decision Q1, applied in PF10 | Rule 1 allows aggregates as named fields; Rule 9 today names verbatim values and percentages only. A pseudo `source_ref` would break the UI resolver and `loaded_source_refs` (as DN-CPI-01) |
| DN-PF-02 | The snapshot has `accounts` and `rows`, joined by (`account_type`, `account_key`) | Same information as the flat row requested, no repeated names, accounts without rows stay countable, names are validated once |
| DN-PF-03 | Our own snapshot format; only the importer reads the Excel | The layout is unknown (Source fact 6); the reader, detector and tests must not depend on it |
| DN-PF-04 | The importer imports the library validator and uses `xlrd` 2.0.1 from an optional extra (amended by A1, DN-PF-24: `openpyxl` cannot read `.xls`); the Excel files are not committed; name, size and SHA-256 are recorded | It needs the developer venv anyway; Community Cloud installs `requirements.txt` only; the hash makes the derivation checkable |
| DN-PF-05 | The reader sorts amounts ascending and does no arithmetic; the median is `money.median_amount` | `money.py` is the only module for monetary arithmetic; sorted output makes the maximum and the median trivial and testable |
| DN-PF-06 | Counts are of accounts (declarations) that declared an amount; accounts with the asterisk are reported separately and an asterisk is **never** counted as `0.00` nor as an amount. The Excel legend of the asterisk is `(*) No se cobra comisión/no se ofrece el servicio`: it joins two meanings (no fee charged, or service not offered) and the kit does not guess which one applies (amended by A1, DN-PF-29) | One entity can have several accounts (Source fact 3); an asterisk and a declared `0,00` are different statements |
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
| DN-PF-22 | **Replaced on 23 November 2026 by DN-PF-25 (amendment A1).** Former text: first snapshot `CNO` and `COT` required, `CDI` and `CJO` if downloaded, `CBA` not needed (decision Q5) | `COT` could not be exported completely (Source fact 8) |
| DN-PF-23 | No automated access to the Banco de España site, ever; the export is manual and the importer reads local files only (decision Q6) | The BdE terms for automated access were not checked, and a file-based importer needs none |
| DN-PF-24 | (A1, D1) The importer reads the `.xls` with `xlrd==2.0.1`, exact pin, in the optional extra `import` of `pyproject.toml`; it replaces `openpyxl` everywhere in this spec. Never in `requirements.txt`; never imported under `ledger_kit/`, `apps/` or by `streamlit_app.py` | The real file is BIFF8 `.xls` (Source fact 8), which `openpyxl` cannot read; `xlrd` 2.x reads only that format |
| DN-PF-25 | (A1, D2, replaces Q5 and DN-PF-22) An account type enters the snapshot only when its files hold every entity the tool lists for that type. `--expect-entities TYPE=N` is given once for every type; the import fails unless the files of that type hold exactly `N` distinct entities. The first snapshot holds `CNO` only (51 entities); `COT` is left out until its missing parts are exported; the pinned check of the committed file requires `CNO`, not `COT` | A partial type would make the counts, the median and the maximum describe an arbitrary subset while the sentence names the whole type |
| DN-PF-26 | (A1, D3) Several files per type: `--excel TYPE=PATH` may repeat for one type; `excel_files` holds one entry per file, each with its own `name`, `size_bytes` and `sha256` (two entries with the same `sha256` are an error); an entity found in two files of one type is an error; account keys are numbered within the entity in file order, the files of a type taken in the order given | The tool refuses exports of more than 238 declarations; every export has the same file name |
| DN-PF-27 | (A1, D4) The snapshot keeps the rows of services `101` and `401` only, with all their concepts. The cash-machine and overdraft blocks are not stored, but their labels are still checked against `SERVICES` (an unknown label is the error of REQ-PF-04). *Proveedor de la Cuenta* is not a service: its *Nombre de la cuenta* is `account_name`. A kept block must contain its compared concept and no concept twice | The two compared services (Q10); the cash-machine block repeats concept names, so a row key would not be unique; overdraft is a non-goal |
| DN-PF-28 | (A1, D5) Concepts are stored verbatim as the Excel writes them: `Comisión ANUAL total (euros)` and `Comisión mantenimiento. ANUAL total (euros)`. `config.toml` `[peer_fees]` and every example, builder and fixture use that spelling | Faithful reproduction (Source fact 7); the config concept must equal the stored one for `declarations(...)` to find it |
| DN-PF-29 | (A1, D6) `not_offered` keeps its name and still records the asterisk; DN-PF-06 quotes the Excel legend and says an asterisk is never counted as `0.00` nor as an amount; the sentence counts only accounts with a declared amount | The legend joins two meanings and the kit does not guess which one applies |
| DN-PF-30 | (A1, D7) Dates come from the files, never from the clock: `declaration_date` from the `Fecha de referencia:` cell, `retrieved_on` from the date of the `Fecha:` cell; every file must give the same two dates. `--declaration-date` stays required as a cross-check and must equal the files' date; `--retrieved-on` is removed; `main` reads no clock. The account type in the title row must equal the `TYPE` given with the file | The file states both dates and its type; a cross-check catches a file given under the wrong type or date |
| DN-PF-31 | (A1, D8) `read_grid(path)` is the only function that imports `xlrd` (sheet 0, every cell as text: a text cell as written, a whole number cell as its integer text); `parse_grid(grid, account_type)` is pure and is the only function that knows the layout, returning the dates, the title and the records; `build_snapshot` stays as designed. A number cell inside a kept block is an error | The layout is tested on synthetic grids without a real `.xls`; no number cell was seen in a kept block, so none is guessed |
| DN-PF-32 | (A1, D9) With a single account type in the snapshot the app shows no select box and the source line names the type; with two or more, the select box of REQ-PF-20 is shown | A select box with one option is noise; the type is always named |

## 13 — Risks

1. **The Excel is not `.xlsx`, or is laid out in a way that does not fit `Record`.** Closed by amendment A1: the
   file is a binary `.xls` read with `xlrd` (DN-PF-24) and the layout is known (Source fact 8). Remaining risk: the
   BdE changes the layout; `parse_grid` then fails with one `error:` line instead of writing a wrong snapshot.
2. **The same account listed twice** in the Excel. `account_key` is assigned by position; a duplicate declaration
   would inflate counts. Mitigation: an entity that appears twice in a file or in two files of one type is an
   error (DN-PF-26), the entity count is checked against `--expect-entities` (DN-PF-25), and the developer checks
   three entities by eye against the BdE page (PF9).
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
