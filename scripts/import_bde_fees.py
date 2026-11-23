"""Import the Banco de España fee comparator Excel into the committed snapshot (public-fees PF8).

Developer machine only: run by hand, it reads local files only and never the network or the
clock (decision Q6, DN-PF-30). The input is the binary .xls the owner exported by hand in the
comparator (amendment A1). `read_grid` is the only function that imports xlrd (optional extra
`import`), `parse_grid` is the only one that knows the layout of the file, and `build_snapshot`
holds the conversion rules. The snapshot is checked with the library validator before it
replaces the committed file; on any failure one `error:` line is printed and the old file stays.

Example (PowerShell, repository root, venv active with the extra `import` installed):

    python scripts/import_bde_fees.py --declaration-date 2026-11-23
        --excel CNO=<folder>/CompararEntidadesCCP.xls --expect-entities CNO=51
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import re
import sys
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any, NamedTuple, NoReturn

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ledger_kit.public_data.bde_fees import (  # noqa: E402
    ACCOUNT_TYPE_ORDER,
    ACCOUNT_TYPES,
    LICENCE_NOTE,
    NO_ENDORSEMENT,
    SERVICES,
    SNAPSHOT_FORMAT,
    SOURCE,
    START_PAGE,
    FeeSnapshotError,
    attribution_for,
    validate_fee_snapshot,
)

DEFAULT_OUTPUT: Path = REPO_ROOT / "data" / "public" / "bde_payment_account_fees.json"

# Services whose rows are stored: the two compared services (decision Q10, DN-PF-27).
KEPT_SERVICES: tuple[str, ...] = ("101", "401")
# The compared concept each kept block must hold, spelled as the Excel writes it (DN-PF-28).
COMPARED_CONCEPTS: Mapping[str, str] = MappingProxyType(
    {
        "101": "Comisión ANUAL total (euros)",
        "401": "Comisión mantenimiento. ANUAL total (euros)",
    }
)
# Layout texts of the exported file (Source fact 8, facts F2 to F4 of amendment A1).
HEADER_LABEL: str = "SERVICIOS"
CONCEPT_LABEL: str = "CONCEPTOS"
ASTERISK_LEGEND: str = "(*) No se cobra comisión/no se ofrece el servicio"
TITLE_PREFIX: str = "COMPARACIÓN ENTRE ENTIDADES"
PROVIDER_LABEL: str = "Proveedor de la Cuenta"
ACCOUNT_NAME_CONCEPT: str = "Nombre de la cuenta"
# A lone asterisk: no fee is charged or the service is not offered (DN-PF-06, DN-PF-29).
ASTERISK: str = "*"
# A concept whose name ends like this holds a euro amount.
EURO_CONCEPT_SUFFIX: str = "(euros)"
# Size of the chunks read to hash an Excel file.
HASH_CHUNK_BYTES: int = 1024 * 1024

_GENERATED_RE = re.compile(r"^Fecha:\s*(\d{2})/(\d{2})/(\d{4})(?:\s+\d{1,2}:\d{2}:\d{2})?$")
_REFERENCE_RE = re.compile(r"^Fecha de referencia:\s*(\d{2})-(\d{2})-(\d{4})$")
_ENTITY_RE = re.compile(r"^\d{4}$")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_COUNT_RE = re.compile(r"^[1-9]\d*$")
# A euro amount as published: decimal comma, two decimals, optional thousands full stops.
_AMOUNT_RE = re.compile(r"^(?:\d{1,3}(?:\.\d{3})+|\d+),\d{2}$")
_LONG_AMOUNT_RE = re.compile(r"^(?:\d{1,3}(?:\.\d{3})+|\d+),\d{3,}$")
# A text made only of digits, full stops, commas and a sign: it must then be a valid amount.
_NUMBERISH_RE = re.compile(r"^[-+]?[\d.,]*\d[\d.,]*$")


class ImporterError(Exception):
    """One step of the import failed; the message is the one-line reason."""


class GridCell(NamedTuple):
    """One cell of the sheet as text; `number` marks a number cell (DN-PF-31)."""

    text: str
    number: bool = False


Grid = tuple[tuple[GridCell, ...], ...]


@dataclass(frozen=True)
class Cell:
    """One published value of a kept block: service label, concept and the cell text."""

    service_label: str
    concept: str
    text: str


@dataclass(frozen=True)
class Record:
    """One account (declaration) of one file with its cells of the kept blocks."""

    account_type: str
    entity_code: str
    entity_name: str
    account_name: str
    cells: tuple[Cell, ...]


@dataclass(frozen=True)
class ParsedFile:
    """What parse_grid reads from one file: its type, dates, title and records."""

    account_type: str
    declaration_date: str
    retrieved_on: str
    title: str
    records: tuple[Record, ...]


@dataclass(frozen=True)
class Meta:
    """The snapshot facts that are not records: the two dates and the Excel file entries."""

    declaration_date: str
    retrieved_on: str
    excel_files: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class _Block:
    """One block of the header: its label, service code, columns and non-empty concepts."""

    label: str
    code: str | None
    start: int
    end: int
    concepts: tuple[tuple[int, str], ...]


# --- Reading the .xls (the only xlrd code) ---


def read_grid(path: Path) -> Grid:
    """Return sheet 0 of the .xls at `path` with every cell as text; the only user of xlrd."""
    path = Path(path)
    if not path.is_file():
        raise ImporterError(f"cannot read {path}: file not found")
    try:
        import xlrd
    except ImportError:
        hint = 'xlrd is not installed (pip install -e ".[import]")'
        raise ImporterError(f"cannot read {path}: {hint}") from None
    try:
        # The size warning of xlrd (Source fact 8) goes to this buffer and does not stop us.
        book = xlrd.open_workbook(str(path), logfile=io.StringIO())
        sheet = book.sheet_by_index(0)
        return tuple(
            tuple(_grid_cell(xlrd, sheet, row, col, path) for col in range(sheet.ncols))
            for row in range(sheet.nrows)
        )
    except ImporterError:
        raise
    except Exception as exc:  # xlrd raises its own errors and stdlib ones for a damaged file
        raise ImporterError(f"cannot read {path}: {exc}") from None


def _grid_cell(xlrd: Any, sheet: Any, row: int, col: int, path: Path) -> GridCell:
    """Return one cell as text: text as written, empty as '', a whole number as its digits."""
    kind = sheet.cell_type(row, col)
    value = sheet.cell_value(row, col)
    if kind in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
        return GridCell("")
    if kind == xlrd.XL_CELL_TEXT:
        return GridCell(str(value))
    if kind == xlrd.XL_CELL_NUMBER and value == int(value):
        return GridCell(str(int(value)), number=True)
    where = f"cell at row {row} column {col}"
    raise ImporterError(f"cannot read {path}: {where} is not text or a whole number")


# --- The layout of one file (pure) ---


def _cell(grid: Grid, row: int, col: int) -> GridCell:
    """Return the cell at (row, col), an empty one outside the grid."""
    if row >= len(grid) or col >= len(grid[row]):
        return GridCell("")
    return grid[row][col]


def _header_row(grid: Grid, where: str) -> int:
    """Return the one row whose column 0 is SERVICIOS."""
    rows = [r for r, line in enumerate(grid) if line and line[0].text.strip() == HEADER_LABEL]
    if not rows:
        raise ImporterError(f"no {HEADER_LABEL} header row in {where}")
    if len(rows) > 1:
        raise ImporterError(f"two {HEADER_LABEL} header rows in {where}")
    return rows[0]


def _check_concept_row(grid: Grid, row: int, where: str) -> None:
    """Check that column 0 of the concept row is CONCEPTOS with the asterisk legend."""
    first = _cell(grid, row, 0).text.strip()
    if not first.startswith(CONCEPT_LABEL):
        row_text = f"the row after {HEADER_LABEL} does not start with {CONCEPT_LABEL}"
        raise ImporterError(f"{row_text} in {where}")
    if ASTERISK_LEGEND not in " ".join(first.split()):
        raise ImporterError(f"the asterisk legend {ASTERISK_LEGEND!r} is missing in {where}")


def _one_date(matches: list[re.Match[str]], label: str, where: str) -> str:
    """Return the ISO date of the one cell that matched `label`."""
    if not matches:
        raise ImporterError(f"no '{label}' cell above the table of {where}")
    if len(matches) > 1:
        raise ImporterError(f"two '{label}' cells above the table of {where}")
    day, month, year = matches[0].groups()
    try:
        return date(int(year), int(month), int(day)).isoformat()
    except ValueError:
        raise ImporterError(f"invalid date in '{matches[0].group(0)}' of {where}") from None


def _above_table(grid: Grid, header: int, account_type: str, where: str) -> tuple[str, str, str]:
    """Return retrieved_on, declaration_date and the title found above the header row."""
    generated: list[re.Match[str]] = []
    reference: list[re.Match[str]] = []
    titles: list[str] = []
    for line in grid[:header]:
        for cell in line:
            text = cell.text.strip()
            if match := _GENERATED_RE.match(text):
                generated.append(match)
            elif match := _REFERENCE_RE.match(text):
                reference.append(match)
            elif text.startswith(TITLE_PREFIX):
                titles.append(text)
    retrieved_on = _one_date(generated, "Fecha:", where)
    declaration_date = _one_date(reference, "Fecha de referencia:", where)
    if not titles:
        raise ImporterError(f"no title starting with '{TITLE_PREFIX}' in {where}")
    if len(titles) > 1:
        raise ImporterError(f"two titles starting with '{TITLE_PREFIX}' in {where}")
    title = titles[0]
    named = [c for c in ACCOUNT_TYPE_ORDER if title.endswith(ACCOUNT_TYPES[c].label.upper())]
    if not named:
        raise ImporterError(f"the title of {where} names no known account type: {title!r}")
    if named[0] != account_type:
        names = f"names account type {named[0]}, not {account_type}"
        raise ImporterError(f"the title of {where} {names}")
    return retrieved_on, declaration_date, title


def _blocks(grid: Grid, header: int, account_type: str, where: str) -> list[_Block]:
    """Return the blocks of the header row, found by their label text (never by position)."""
    width = max(len(line) for line in grid)
    labels = [(c, t) for c in range(1, width) if (t := _cell(grid, header, c).text.strip())]
    by_label = {label: code for code, label in SERVICES.items()}
    blocks: list[_Block] = []
    seen: set[str] = set()
    for index, (start, label) in enumerate(labels):
        if label in seen:
            raise ImporterError(f"service label {label!r} appears twice in {where}")
        seen.add(label)
        code = None
        if label != PROVIDER_LABEL:
            code = by_label.get(label)
            if code is None:
                raise ImporterError(f"unknown service label {label!r} in {account_type} file")
        end = labels[index + 1][0] if index + 1 < len(labels) else width
        columns = range(start, end)
        concepts = tuple((c, t) for c in columns if (t := _cell(grid, header + 1, c).text.strip()))
        blocks.append(_Block(label, code, start, end, concepts))
    return blocks


def _check_concepts(block: _Block, name: str, where: str) -> None:
    """Reject a block that holds one concept twice."""
    names = [concept for _, concept in block.concepts]
    for concept in names:
        if names.count(concept) > 1:
            raise ImporterError(f"concept {concept!r} appears twice in {name} of {where}")


def _kept_blocks(blocks: list[_Block], where: str) -> tuple[_Block, int, dict[str, _Block]]:
    """Return the provider block, its account-name column and the kept service blocks."""
    providers = [b for b in blocks if b.label == PROVIDER_LABEL]
    columns = [c for b in providers for c, t in b.concepts if t == ACCOUNT_NAME_CONCEPT]
    if not columns:
        block = f"'{PROVIDER_LABEL}' block with '{ACCOUNT_NAME_CONCEPT}'"
        raise ImporterError(f"no {block} in {where}")
    provider = providers[0]
    _check_concepts(provider, f"'{PROVIDER_LABEL}'", where)
    kept: dict[str, _Block] = {}
    for code in KEPT_SERVICES:
        found = [b for b in blocks if b.code == code]
        if not found:
            raise ImporterError(f"no block for service {code} in {where}")
        block = found[0]
        _check_concepts(block, f"service {code}", where)
        if COMPARED_CONCEPTS[code] not in [t for _, t in block.concepts]:
            concept = COMPARED_CONCEPTS[code]
            raise ImporterError(f"service {code} of {where} has no concept {concept!r}")
        kept[code] = block
    return provider, columns[0], kept


def _check_no_number(grid: Grid, row: int, blocks: Iterable[_Block], where: str) -> None:
    """Reject a number cell inside the provider block or a kept block (DN-PF-31: no guess)."""
    for block in blocks:
        name = f"service {block.code}" if block.code else f"'{block.label}'"
        for col in range(block.start, block.end):
            if _cell(grid, row, col).number:
                raise ImporterError(f"number cell at row {row} column {col} in {name} of {where}")


def _records(
    grid: Grid,
    first: int,
    provider: _Block,
    name_col: int,
    kept: Mapping[str, _Block],
    account_type: str,
    where: str,
) -> tuple[Record, ...]:
    """Return one record per account row; an account without entity cells joins the one above."""
    records: list[Record] = []
    seen: set[str] = set()
    entity: tuple[str, str] | None = None
    for row in range(first, len(grid)):
        if all(not cell.text.strip() for cell in grid[row]):
            continue
        _check_no_number(grid, row, [provider, *kept.values()], where)
        code = _cell(grid, row, 0).text.strip()
        name = _cell(grid, row, 2).text.strip()
        if code:
            if not _ENTITY_RE.match(code):
                raise ImporterError(f"invalid entity code {code!r} at row {row} of {where}")
            if not name:
                raise ImporterError(f"entity {code} at row {row} of {where} has no name")
            if code in seen:
                raise ImporterError(f"entity {code} appears twice in {where}")
            seen.add(code)
            entity = (code, name)
        elif name:
            raise ImporterError(f"account at row {row} of {where} has an entity name but no code")
        elif entity is None:
            raise ImporterError(f"account at row {row} of {where} has no entity")
        account_name = _cell(grid, row, name_col).text.strip()
        if not account_name:
            raise ImporterError(f"account at row {row} of {where} has no {ACCOUNT_NAME_CONCEPT!r}")
        cells = [
            Cell(block.label, concept, _cell(grid, row, col).text)
            for block in kept.values()
            for col, concept in block.concepts
            if _cell(grid, row, col).text.strip()
        ]
        records.append(Record(account_type, entity[0], entity[1], account_name, tuple(cells)))
    if not records:
        raise ImporterError(f"no account in {where}")
    return tuple(records)


def parse_grid(grid: Grid, account_type: str) -> ParsedFile:
    """Return the dates, the title and the records of one exported file (pure, Source fact 8)."""
    where = f"the {account_type} file"
    header = _header_row(grid, where)
    _check_concept_row(grid, header + 1, where)
    retrieved_on, declaration_date, title = _above_table(grid, header, account_type, where)
    blocks = _blocks(grid, header, account_type, where)
    provider, name_col, kept = _kept_blocks(blocks, where)
    records = _records(grid, header + 2, provider, name_col, kept, account_type, where)
    return ParsedFile(account_type, declaration_date, retrieved_on, title, records)


# --- The snapshot (pure) ---


def _rank(account_type: str) -> int:
    """Return the position of a type in the fixed order (unknown types last)."""
    if account_type in ACCOUNT_TYPE_ORDER:
        return ACCOUNT_TYPE_ORDER.index(account_type)
    return len(ACCOUNT_TYPE_ORDER)


def _amount(text: str, where: str) -> str:
    """Return the snapshot amount of a published euro text, built with Decimal from text."""
    if _AMOUNT_RE.match(text):
        return str(Decimal(text.replace(".", "").replace(",", ".")))
    if _LONG_AMOUNT_RE.match(text):
        raise ImporterError(f"amount {text!r} of {where} has more than two decimals")
    raise ImporterError(f"amount {text!r} of {where} is not a euro amount with two decimals")


def _row(account_type: str, key: str, code: str, concept: str, text: str) -> dict[str, Any]:
    """Return one snapshot row; an asterisk is not_offered, a euro text becomes an amount."""
    amount: str | None = None
    not_offered = text == ASTERISK
    if not not_offered and concept.endswith(EURO_CONCEPT_SUFFIX) and _NUMBERISH_RE.match(text):
        amount = _amount(text, f"{account_type} {key} service {code}")
    return {
        "account_type": account_type,
        "account_key": key,
        "service_code": code,
        "concept": concept,
        "text": text,
        "amount": amount,
        "not_offered": not_offered,
    }


def build_snapshot(records: Iterable[Record], meta: Meta) -> dict[str, Any]:
    """Return the validated snapshot of REQ-PF-01 built from the records (pure)."""
    by_label = {label: code for code, label in SERVICES.items()}
    counters: dict[tuple[str, str], int] = {}
    accounts: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for record in records:
        account_type = record.account_type
        if account_type not in ACCOUNT_TYPES:
            raise ImporterError(f"unknown account type {account_type!r}")
        entity_code = record.entity_code.strip()
        if not _ENTITY_RE.match(entity_code):
            raise ImporterError(f"invalid entity code {entity_code!r} in {account_type} file")
        number = counters.get((account_type, entity_code), 0) + 1
        counters[(account_type, entity_code)] = number
        key = f"{entity_code}-{number:02d}"
        accounts.append(
            {
                "account_type": account_type,
                "declaration_date": meta.declaration_date,
                "entity_code": entity_code,
                "entity_name": record.entity_name.strip(),
                "account_key": key,
                "account_name": record.account_name.strip(),
            }
        )
        seen: set[tuple[str, str]] = set()
        for cell in record.cells:
            label = cell.service_label.strip()
            code = by_label.get(label)
            if code is None:
                raise ImporterError(f"unknown service label {label!r} in {account_type} file")
            concept = cell.concept.strip()
            if (code, concept) in seen:
                where = f"{account_type} {key} service {code}"
                raise ImporterError(f"duplicate concept {concept!r} of {where}")
            seen.add((code, concept))
            rows.append(_row(account_type, key, code, concept, cell.text.strip()))
    if not accounts:
        raise ImporterError("no account to import")
    accounts.sort(key=lambda a: (_rank(a["account_type"]), a["entity_code"], a["account_key"]))
    entity_of = {(a["account_type"], a["account_key"]): a["entity_code"] for a in accounts}

    def position(row: dict[str, Any]) -> tuple[int, str, str, str]:
        code, key = row["account_type"], row["account_key"]
        return (_rank(code), entity_of[(code, key)], key, row["service_code"])

    rows.sort(key=position)
    present = {a["account_type"] for a in accounts}
    files = sorted((dict(e) for e in meta.excel_files), key=lambda e: _rank(e["account_type"]))
    snapshot: dict[str, Any] = {
        "snapshot_format": SNAPSHOT_FORMAT,
        "source": SOURCE,
        "start_page": START_PAGE,
        "retrieved_on": meta.retrieved_on,
        "declaration_date": meta.declaration_date,
        "account_types": [code for code in ACCOUNT_TYPE_ORDER if code in present],
        "licence_note": LICENCE_NOTE,
        "attribution": attribution_for(meta.declaration_date),
        "no_endorsement": NO_ENDORSEMENT,
        "excel_files": files,
        "accounts": accounts,
        "rows": rows,
    }
    try:
        validate_fee_snapshot(snapshot)
    except FeeSnapshotError as exc:
        raise ImporterError(f"snapshot check failed: {exc}") from None
    return snapshot


# --- Files ---


def file_facts(path: Path, account_type: str) -> dict[str, Any]:
    """Return the excel_files entry of one file: type, base name, size and SHA-256."""
    path = Path(path)
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(HASH_CHUNK_BYTES):
                digest.update(chunk)
                size += len(chunk)
    except OSError as exc:
        raise ImporterError(f"cannot read {path}: {exc.strerror or exc}") from None
    return {
        "account_type": account_type,
        "name": path.name,
        "size_bytes": size,
        "sha256": digest.hexdigest(),
    }


def write_snapshot(snapshot: Mapping[str, Any], path: Path) -> None:
    """Write UTF-8 JSON (LF, final newline) through a temporary file renamed on success."""
    path = Path(path)
    text = json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n"
    temporary: str | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as handle:
            temporary = handle.name
            handle.write(text.encode("utf-8"))
        os.replace(temporary, path)
    except OSError as exc:
        if temporary is not None:
            with contextlib.suppress(OSError):
                os.remove(temporary)
        raise ImporterError(f"cannot write {path}: {exc.strerror or exc}") from None


# --- Command line ---


class _Parser(argparse.ArgumentParser):
    """An argument parser whose errors become one `error:` line and exit code 1."""

    def error(self, message: str) -> NoReturn:
        """Raise the importer error instead of printing the usage and exiting with 2."""
        raise ImporterError(message)


def _parser() -> _Parser:
    """Return the command-line parser of REQ-PF-04."""
    parser = _Parser(
        prog="import_bde_fees.py",
        description="Write data/public/bde_payment_account_fees.json from exported BdE files.",
    )
    parser.add_argument("--declaration-date", required=True, help="cross-check, YYYY-MM-DD")
    parser.add_argument(
        "--excel", action="append", required=True, metavar="TYPE=PATH", help="one exported file"
    )
    parser.add_argument(
        "--expect-entities",
        action="append",
        default=[],
        metavar="TYPE=N",
        help="entities the tool lists for TYPE",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="snapshot path")
    return parser


def _excel_pairs(values: Sequence[str]) -> list[tuple[str, Path]]:
    """Return the (type, path) pairs of --excel in the order given."""
    pairs: list[tuple[str, Path]] = []
    for value in values:
        code, sep, raw = value.partition("=")
        code = code.strip()
        if not sep or not raw.strip():
            raise ImporterError(f"invalid --excel {value!r} (expected TYPE=PATH)")
        if code not in ACCOUNT_TYPES:
            raise ImporterError(f"unknown account type {code!r} in --excel {value!r}")
        pairs.append((code, Path(raw.strip())))
    return pairs


def _expected_counts(values: Sequence[str], types: Sequence[str]) -> dict[str, int]:
    """Return --expect-entities as type -> count; one value for every type given (DN-PF-25)."""
    counts: dict[str, int] = {}
    for value in values:
        code, sep, raw = value.partition("=")
        code = code.strip()
        if not sep or not _COUNT_RE.match(raw.strip()):
            hint = "expected TYPE=N, N a positive whole number"
            raise ImporterError(f"invalid --expect-entities {value!r} ({hint})")
        if code not in ACCOUNT_TYPES:
            raise ImporterError(f"unknown account type {code!r} in --expect-entities {value!r}")
        if code in counts:
            raise ImporterError(f"--expect-entities is given twice for {code}")
        counts[code] = int(raw.strip())
    for code in types:
        if code not in counts:
            raise ImporterError(f"--expect-entities is missing for {code}")
    for code in counts:
        if code not in types:
            raise ImporterError(f"--expect-entities names {code}, which has no --excel file")
    return counts


def _declaration_date(value: str) -> str:
    """Return the --declaration-date value after checking it is a real ISO date."""
    try:
        if _ISO_DATE_RE.match(value):
            return date.fromisoformat(value).isoformat()
    except ValueError:
        pass
    raise ImporterError(f"invalid --declaration-date {value!r} (expected YYYY-MM-DD)")


def _cross_check(files: Sequence[tuple[Path, ParsedFile, dict[str, Any]]]) -> tuple[str, str]:
    """Check one pair of dates for all files, no repeated hash and no entity in two files."""
    first = files[0][1]
    for _, parsed, _ in files:
        if parsed.declaration_date != first.declaration_date:
            dates = f"{first.declaration_date} and {parsed.declaration_date}"
            raise ImporterError(f"the files give two declaration dates: {dates}")
        if parsed.retrieved_on != first.retrieved_on:
            dates = f"{first.retrieved_on} and {parsed.retrieved_on}"
            raise ImporterError(f"the files give two generation dates: {dates}")
    hashes: dict[str, Path] = {}
    for path, _, facts in files:
        if facts["sha256"] in hashes:
            raise ImporterError(f"{path} has the same SHA-256 as {hashes[facts['sha256']]}")
        hashes[facts["sha256"]] = path
    owners: dict[tuple[str, str], Path] = {}
    for path, parsed, _ in files:
        for record in parsed.records:
            owner = owners.setdefault((parsed.account_type, record.entity_code), path)
            if owner != path:
                code, entity = parsed.account_type, record.entity_code
                raise ImporterError(f"entity {entity} is in two {code} files: {owner} and {path}")
    return first.declaration_date, first.retrieved_on


def _run(argv: Sequence[str] | None) -> str:
    """Run the import and return the success line; ImporterError on any failure."""
    args = _parser().parse_args(argv)
    declared = _declaration_date(args.declaration_date)
    pairs = _excel_pairs(args.excel)
    types = [code for code in ACCOUNT_TYPE_ORDER if any(code == c for c, _ in pairs)]
    expected = _expected_counts(args.expect_entities, types)
    files: list[tuple[Path, ParsedFile, dict[str, Any]]] = []
    for code, path in pairs:
        parsed = parse_grid(read_grid(path), code)
        files.append((path, parsed, file_facts(path, code)))
    declaration_date, retrieved_on = _cross_check(files)
    if declared != declaration_date:
        raise ImporterError(
            f"--declaration-date {declared} differs from the date of the files ({declaration_date})"
        )
    for code in types:
        of_type = [p for _, p, _ in files if p.account_type == code]
        entities = {r.entity_code for p in of_type for r in p.records}
        if len(entities) != expected[code]:
            count = f"{len(entities)} entities, expected {expected[code]}"
            raise ImporterError(f"the {code} files hold {count}")
    meta = Meta(declaration_date, retrieved_on, tuple(facts for _, _, facts in files))
    records = [record for _, parsed, _ in files for record in parsed.records]
    snapshot = build_snapshot(records, meta)
    write_snapshot(snapshot, args.output)
    accounts, rows = len(snapshot["accounts"]), len(snapshot["rows"])
    kinds = ", ".join(snapshot["account_types"])
    return f"wrote {args.output}: {accounts} accounts, {rows} rows, types {kinds}"


def main(argv: Sequence[str] | None = None) -> int:
    """Import the exported files; print one line and return 0, or one error line and 1."""
    try:
        line = _run(argv)
    except ImporterError as exc:
        print(f"error: {' '.join(str(exc).split())}", file=sys.stderr)
        return 1
    print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
