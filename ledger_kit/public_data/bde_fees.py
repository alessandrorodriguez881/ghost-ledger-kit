"""Reader of the committed Banco de España payment-account fee snapshot; stdlib only.

The snapshot `data/public/bde_payment_account_fees.json` is in our own format (REQ-PF-01), written
by `scripts/import_bde_fees.py` from an Excel exported by hand in the BdE comparator; nothing here
touches the network or the clock. The reader performs no arithmetic: it validates, sorts and counts
(REQ-PF-08). The median is computed by `ledger_kit.utils.money.median_amount`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any

DEFAULT_FEE_SNAPSHOT_PATH: Path = (
    Path(__file__).resolve().parents[2] / "data" / "public" / "bde_payment_account_fees.json"
)
# The only snapshot format this reader understands (one declaration date per file).
SNAPSHOT_FORMAT: int = 1

SOURCE: str = (
    "Banco de España, Comisiones y tipos de interés de los servicios financieros, Comisiones de "
    "Cuentas de Pago, Comparación entre entidades para una fecha y cuenta"
)
START_PAGE: str = "https://app.bde.es/csfwciu/csfwciuias/pub/InicioComisionesCuentasPago.html"
LICENCE_NOTE: str = (
    "The Banco de España legal notice allows reuse and use for calculations if the information is "
    "reproduced faithfully and the Banco de España is cited as the source. The data keeps that "
    "condition and is not covered by the repository MIT licence."
)
# Decision Q1 of 23 November 2026; the placeholder is the snapshot's declaration date.
ATTRIBUTION_TEMPLATE: str = (
    "Fuente: Banco de España, comparador de comisiones de cuentas de pago (declaraciones a fecha "
    "{declaration_date}). Elaboración propia: recuento, mediana y máximo."
)
NO_ENDORSEMENT: str = "The Banco de España does not take part in, endorse or support this reuse."


@dataclass(frozen=True)
class AccountType:
    """One BdE account type: the published label and the English phrase used in sentences."""

    label: str
    phrase: str


# The fixed order of the account types in a snapshot (REQ-PF-01).
ACCOUNT_TYPE_ORDER: tuple[str, ...] = ("CNO", "CDI", "CJO", "CBA", "COT")
ACCOUNT_TYPES: Mapping[str, AccountType] = MappingProxyType(
    {
        "CNO": AccountType("Cuenta Nómina/Pensión", "payroll or pension"),
        "CDI": AccountType("Cuenta Digital", "digital"),
        "CJO": AccountType("Cuenta Joven", "youth"),
        "CBA": AccountType("Cuenta Básica", "basic"),
        "COT": AccountType("Otras Cuentas", "other"),
    }
)
# The 13 services of the comparator with their published labels (Source fact 4).
SERVICES: Mapping[str, str] = MappingProxyType(
    {
        "101": "Mantenimiento de la cuenta",
        "201": "Paquetes de servicios",
        "301": "Transferencia",
        "302": "Orden Permanente",
        "401": "Emisión y mantenimiento de una tarjeta de débito",
        "402": "Emisión y mantenimiento de una tarjeta de crédito",
        "403": "Retirada efectivo a débito mediante tarjeta en cajero",
        "404": "Retirada efectivo a crédito mediante tarjeta en cajero",
        "501": "Descubierto expreso",
        "502": "Descubierto tácito",
        "601": "Negociación y compensación de cheques",
        "602": "Devolución de cheques",
        "603": "Servicios de alertas (SMS, email o similar)",
    }
)

# Keys of the snapshot, of an Excel file entry, of an account and of a row, in file order.
SNAPSHOT_KEYS: tuple[str, ...] = (
    "snapshot_format",
    "source",
    "start_page",
    "retrieved_on",
    "declaration_date",
    "account_types",
    "licence_note",
    "attribution",
    "no_endorsement",
    "excel_files",
    "accounts",
    "rows",
)
EXCEL_FILE_KEYS: tuple[str, ...] = ("account_type", "name", "size_bytes", "sha256")
ACCOUNT_KEYS: tuple[str, ...] = (
    "account_type",
    "declaration_date",
    "entity_code",
    "entity_name",
    "account_key",
    "account_name",
)
ROW_KEYS: tuple[str, ...] = (
    "account_type",
    "account_key",
    "service_code",
    "concept",
    "text",
    "amount",
    "not_offered",
)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ENTITY_RE = re.compile(r"^\d{4}$")
_ACCOUNT_KEY_RE = re.compile(r"^\d{4}-\d{2}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_AMOUNT_RE = re.compile(r"^\d+\.\d{2}$")


class FeeSnapshotError(ValueError):
    """The fee snapshot is missing, unreadable or invalid (one-line message)."""


def attribution_for(declaration_date: str) -> str:
    """Return the attribution text of decision Q1 for one declaration date."""
    return ATTRIBUTION_TEMPLATE.format(declaration_date=declaration_date)


@dataclass(frozen=True)
class FeeDeclarations:
    """Answer of FeeSnapshot.declarations: the amounts declared by the accounts of one type."""

    account_type: str
    service_code: str
    concept: str
    declaration_date: str
    account_count: int  # accounts (declarations) of the type
    amounts: tuple[Decimal, ...]  # one per account with an amount, sorted ascending
    not_offered_count: int  # accounts whose cell is the asterisk of "No practicado"

    @property
    def without_amount_count(self) -> int:
        """Accounts with neither an amount nor the asterisk for this service and concept."""
        return self.account_count - len(self.amounts) - self.not_offered_count


# --- Validation (REQ-PF-02) -------------------------------------------------------------------


def _is_int(value: Any) -> bool:
    """Return True for a JSON integer (a bool is not one)."""
    return isinstance(value, int) and not isinstance(value, bool)


def _rank(account_type: str) -> int:
    """Return the position of a known account type in ACCOUNT_TYPE_ORDER."""
    return ACCOUNT_TYPE_ORDER.index(account_type)


def _check_date(key: str, value: Any) -> date:
    """Return the date of a 'YYYY-MM-DD' string; FeeSnapshotError otherwise."""
    if isinstance(value, str) and _DATE_RE.match(value):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise FeeSnapshotError(f"invalid {key} {value!r} (expected YYYY-MM-DD)")


def _check_top_level(data: Any) -> None:
    """Check the top-level keys, the format, the dates and the constant texts."""
    if not isinstance(data, dict):
        raise FeeSnapshotError("the snapshot is not a JSON object")
    missing = [key for key in SNAPSHOT_KEYS if key not in data]
    if missing:
        raise FeeSnapshotError(f"missing key {missing[0]!r}")
    extra = sorted(str(key) for key in data if key not in SNAPSHOT_KEYS)
    if extra:
        raise FeeSnapshotError(f"unexpected key {extra[0]!r}")
    fmt = data["snapshot_format"]
    if not _is_int(fmt) or fmt != SNAPSHOT_FORMAT:
        shown = fmt if _is_int(fmt) else repr(fmt)
        raise FeeSnapshotError(f"unsupported snapshot_format {shown} (expected {SNAPSHOT_FORMAT})")
    declared = _check_date("declaration_date", data["declaration_date"])
    retrieved = _check_date("retrieved_on", data["retrieved_on"])
    if retrieved < declared:
        raise FeeSnapshotError(
            f"retrieved_on {data['retrieved_on']} is before declaration_date "
            f"{data['declaration_date']}"
        )
    constants = {
        "source": SOURCE,
        "start_page": START_PAGE,
        "licence_note": LICENCE_NOTE,
        "no_endorsement": NO_ENDORSEMENT,
    }
    for key, expected in constants.items():
        if data[key] != expected:
            raise FeeSnapshotError(f"{key} differs from the constant of bde_fees.py")
    if data["attribution"] != attribution_for(data["declaration_date"]):
        raise FeeSnapshotError(
            f"attribution differs from attribution_for('{data['declaration_date']}')"
        )


def _check_account_types(types: Any) -> tuple[str, ...]:
    """Check `account_types`: non-empty, known codes, no repeat, fixed order."""
    if not isinstance(types, list) or not types:
        raise FeeSnapshotError("account_types must be a non-empty list")
    previous: str | None = None
    seen: set[str] = set()
    for code in types:
        if not isinstance(code, str) or code not in ACCOUNT_TYPES:
            raise FeeSnapshotError(f"unknown account type {code!r}")
        if code in seen:
            raise FeeSnapshotError(f"repeated account type {code}")
        if previous is not None and _rank(code) < _rank(previous):
            raise FeeSnapshotError(f"account types out of order: {code} after {previous}")
        seen.add(code)
        previous = code
    return tuple(types)


def _check_excel_files(files: Any, types: tuple[str, ...]) -> None:
    """Check `excel_files`: one well-formed entry or more per account type, no repeated hash."""
    if not isinstance(files, list):
        raise FeeSnapshotError("excel_files must be a list")
    seen: set[str] = set()
    hashes: set[str] = set()
    for entry in files:
        if not isinstance(entry, dict) or set(entry) != set(EXCEL_FILE_KEYS):
            raise FeeSnapshotError(f"excel_files entry must have exactly {list(EXCEL_FILE_KEYS)}")
        code = entry["account_type"]
        if code not in types:
            raise FeeSnapshotError(f"excel_files names unknown account type {code!r}")
        seen.add(code)
        name = entry["name"]
        if not isinstance(name, str) or not name or "/" in name or "\\" in name:
            raise FeeSnapshotError(f"invalid excel file name for {code}: {name!r}")
        size = entry["size_bytes"]
        if not _is_int(size) or size <= 0:
            raise FeeSnapshotError(f"invalid size_bytes for {code}: expected a positive integer")
        sha = entry["sha256"]
        if not isinstance(sha, str) or not _SHA256_RE.match(sha):
            raise FeeSnapshotError(f"invalid sha256 for {code}: expected 64 lowercase hex digits")
        # Every export is named alike (amendment A1, DN-PF-26): the hash tells the files apart.
        if sha in hashes:
            raise FeeSnapshotError(f"excel_files has two entries with the same sha256 ({code})")
        hashes.add(sha)
    for code in types:
        if code not in seen:
            raise FeeSnapshotError(f"excel_files has no entry for {code}")


def _check_accounts(
    accounts: Any, types: tuple[str, ...], declaration_date: str
) -> dict[tuple[str, str], str]:
    """Check `accounts`; return (account_type, account_key) -> entity_code."""
    if not isinstance(accounts, list):
        raise FeeSnapshotError("accounts must be a list")
    known: dict[tuple[str, str], str] = {}
    names: dict[str, str] = {}
    for index, account in enumerate(accounts):
        if not isinstance(account, dict) or set(account) != set(ACCOUNT_KEYS):
            raise FeeSnapshotError(f"account {index} must have exactly {list(ACCOUNT_KEYS)}")
        code = account["account_type"]
        if code not in types:
            raise FeeSnapshotError(f"account {index} has unknown account type {code!r}")
        entity = account["entity_code"]
        if not isinstance(entity, str) or not _ENTITY_RE.match(entity):
            raise FeeSnapshotError(f"invalid entity_code {entity!r} (expected four digits)")
        key = account["account_key"]
        if not isinstance(key, str) or not _ACCOUNT_KEY_RE.match(key):
            raise FeeSnapshotError(f"invalid account_key {key!r} (expected NNNN-NN)")
        if not key.startswith(f"{entity}-"):
            raise FeeSnapshotError(
                f"account_key {key!r} does not start with entity_code {entity!r}"
            )
        if account["declaration_date"] != declaration_date:
            raise FeeSnapshotError(
                f"account {code} {key} has declaration_date {account['declaration_date']!r} "
                f"(expected {declaration_date})"
            )
        for name_key in ("entity_name", "account_name"):
            value = account[name_key]
            if not isinstance(value, str) or not value.strip():
                raise FeeSnapshotError(f"empty {name_key} for {code} {key}")
        entity_name = account["entity_name"]
        if names.setdefault(entity, entity_name) != entity_name:
            raise FeeSnapshotError(f"entity_code {entity} appears with two names")
        if (code, key) in known:
            raise FeeSnapshotError(f"repeated account: {code} {key}")
        known[(code, key)] = entity
    present = {code for code, _ in known}
    for code in types:
        if code not in present:
            raise FeeSnapshotError(f"account type {code} has no account")
    return known


def _check_rows(rows: Any, known: Mapping[tuple[str, str], str]) -> None:
    """Check `rows`: known account and service, exact keys, trimmed texts, amounts, order."""
    if not isinstance(rows, list):
        raise FeeSnapshotError("rows must be a list")
    seen: set[tuple[str, str, str, str]] = set()
    previous: tuple[int, str, str, str] | None = None
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != set(ROW_KEYS):
            raise FeeSnapshotError(f"row {index} must have exactly {list(ROW_KEYS)}")
        code, key, service = row["account_type"], row["account_key"], row["service_code"]
        if not isinstance(code, str) or not isinstance(key, str) or (code, key) not in known:
            raise FeeSnapshotError(f"row {index} names unknown account {code} {key}")
        if not isinstance(service, str) or service not in SERVICES:
            raise FeeSnapshotError(f"unknown service code {service!r}")
        where = f"{code} {key} service {service}"
        concept = row["concept"]
        if not isinstance(concept, str) or not concept:
            raise FeeSnapshotError(f"empty concept: {where}")
        for text_key in ("concept", "text"):
            value = row[text_key]
            if not isinstance(value, str):
                raise FeeSnapshotError(f"{text_key} of {where} is not a string")
            if value != value.strip():
                raise FeeSnapshotError(f"{text_key} of {where} has leading or trailing whitespace")
        amount = row["amount"]
        if amount is not None and (not isinstance(amount, str) or not _AMOUNT_RE.match(amount)):
            raise FeeSnapshotError(f"amount '{amount}' of {where} is not a decimal with two places")
        flag = row["not_offered"]
        if not isinstance(flag, bool):
            raise FeeSnapshotError(f"not_offered of {where} is not true or false")
        if flag and amount is not None:
            raise FeeSnapshotError(f"not_offered row with an amount: {where}")
        identity = (code, key, service, concept)
        if identity in seen:
            raise FeeSnapshotError(f"duplicate row: {where} concept {concept!r}")
        seen.add(identity)
        position = (_rank(code), known[(code, key)], key, service)
        if previous is not None and position < previous:
            raise FeeSnapshotError(f"rows out of order: {where} after row {index - 1}")
        previous = position


def validate_fee_snapshot(data: Any) -> None:
    """Raise FeeSnapshotError unless `data` is a valid fee snapshot (REQ-PF-02); no I/O."""
    _check_top_level(data)
    types = _check_account_types(data["account_types"])
    _check_excel_files(data["excel_files"], types)
    known = _check_accounts(data["accounts"], types, data["declaration_date"])
    _check_rows(data["rows"], known)


# --- The snapshot object (REQ-PF-06, REQ-PF-07) -----------------------------------------------

_Cell = tuple[Decimal | None, bool]


@dataclass(frozen=True)
class FeeSnapshot:
    """An immutable, validated fee snapshot; `declarations` answers one type, service, concept."""

    source: str
    start_page: str
    retrieved_on: str
    declaration_date: str
    account_types: tuple[str, ...]
    licence_note: str
    attribution: str
    no_endorsement: str
    excel_files: tuple[Mapping[str, Any], ...]
    _accounts: Mapping[str, tuple[str, ...]] = field(repr=False, compare=False)
    _cells: Mapping[tuple[str, str, str], Mapping[str, _Cell]] = field(repr=False, compare=False)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> FeeSnapshot:
        """Validate a snapshot object and build the immutable snapshot (no file needed)."""
        validate_fee_snapshot(data)
        accounts: dict[str, list[str]] = {}
        for account in data["accounts"]:
            accounts.setdefault(account["account_type"], []).append(account["account_key"])
        cells: dict[tuple[str, str, str], dict[str, _Cell]] = {}
        for row in data["rows"]:
            amount = None if row["amount"] is None else Decimal(row["amount"])
            index = (row["account_type"], row["service_code"], row["concept"])
            cells.setdefault(index, {})[row["account_key"]] = (amount, row["not_offered"])
        return cls(
            source=data["source"],
            start_page=data["start_page"],
            retrieved_on=data["retrieved_on"],
            declaration_date=data["declaration_date"],
            account_types=tuple(data["account_types"]),
            licence_note=data["licence_note"],
            attribution=data["attribution"],
            no_endorsement=data["no_endorsement"],
            excel_files=tuple(MappingProxyType(dict(e)) for e in data["excel_files"]),
            _accounts=MappingProxyType({k: tuple(v) for k, v in accounts.items()}),
            _cells=MappingProxyType({k: MappingProxyType(v) for k, v in cells.items()}),
        )

    def declarations(
        self, account_type: str, service_code: str, concept: str
    ) -> FeeDeclarations | None:
        """Return the declared amounts of one type, service and concept; None if type absent."""
        if account_type not in ACCOUNT_TYPES:
            raise ValueError(f"unknown account type {account_type!r}")
        if service_code not in SERVICES:
            raise ValueError(f"unknown service code {service_code!r}")
        if not isinstance(concept, str) or not concept:
            raise ValueError("concept must be a non-empty string")
        if account_type not in self.account_types:
            return None
        keys = self._accounts.get(account_type, ())
        cells = self._cells.get((account_type, service_code, concept), {})
        amounts = sorted(
            amount for key in keys if (amount := cells.get(key, (None, False))[0]) is not None
        )
        not_offered = sum(1 for key in keys if cells.get(key, (None, False))[1])
        return FeeDeclarations(
            account_type=account_type,
            service_code=service_code,
            concept=concept,
            declaration_date=self.declaration_date,
            account_count=len(keys),
            amounts=tuple(amounts),
            not_offered_count=not_offered,
        )


def load_fee_snapshot(path: Path = DEFAULT_FEE_SNAPSHOT_PATH) -> FeeSnapshot:
    """Read, validate and return the snapshot at `path`; FeeSnapshotError naming the file."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise FeeSnapshotError(f"cannot read {path}: file not found") from None
    except UnicodeDecodeError:
        raise FeeSnapshotError(f"cannot read {path}: not UTF-8 text") from None
    except OSError as exc:
        raise FeeSnapshotError(f"cannot read {path}: {exc.strerror or exc}") from None
    try:
        data = json.loads(text, parse_float=Decimal)
    except json.JSONDecodeError as exc:
        raise FeeSnapshotError(f"cannot read {path}: invalid JSON at line {exc.lineno}") from None
    try:
        return FeeSnapshot.from_dict(data)
    except FeeSnapshotError as exc:
        raise FeeSnapshotError(f"invalid snapshot {path}: {exc}") from None
