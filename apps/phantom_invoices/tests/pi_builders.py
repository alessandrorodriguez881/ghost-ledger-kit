"""Builders and fictional identifiers for the phantom-invoices tests (synthetic data only).

Every identifier follows Finance Rule 5 and comes from scripts/generate_samples.py (loaded by path,
because scripts/ is not a package): IBANs with a valid ISO 13616 checksum but wrong Spanish
national check digits, tax ids with a wrong control character. Dates are fixed literals; nothing
here reads the system clock. tests/conftest.py re-exports these names.
"""

import importlib.util
import sys
import uuid
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any, NamedTuple

import pandas as pd

from ledger_kit.ingestion.invoice_reader import DEFAULT_PAYMENT_TERM_DAYS
from ledger_kit.ingestion.normaliser import (
    CANONICAL_COLUMNS,
    INVOICE_COLUMNS,
    SUPPLIER_COLUMNS,
    Kind,
    normalise,
)
from ledger_kit.utils.money import net_total, percent_of

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "generate_samples.py"

INVOICE_FILE = "inv.csv"
SUPPLIER_FILE = "sup.csv"
PAYMENT_FILE = "pay.csv"
DEFAULT_ISSUE_DATE: date = date(2026, 3, 1)
ZERO = Decimal("0")

# Bank/branch pairs of the generator plan (design section 15.3): supplier k uses BANKS[(k-1) % 4].
BANKS: tuple[tuple[str, str], ...] = (
    ("2100", "0418"),
    ("0049", "1500"),
    ("0182", "5900"),
    ("0081", "7000"),
)
ACCOUNT_MULTIPLIER: int = 7_654_321
OTHER_ACCOUNT_OFFSET: int = 1_111_111

# Fictional suppliers; the first three agree with the committed sample data.
SUPPLIER_NAMES: dict[int, str] = {
    1: "Suministros Ibéricos Aurora, S.L.",
    2: "Inmuebles Valdemar, S.L.",
    3: "Ana García (Asesoría Fiscal)",
}
PERSON_SUPPLIERS: frozenset[int] = frozenset({3})  # identified by a NIF, not a CIF


def _load_generator() -> Any:
    """Load scripts/generate_samples.py by path (scripts/ is not a package)."""
    spec = importlib.util.spec_from_file_location("generate_samples_pi_builders", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["generate_samples_pi_builders"] = module
    spec.loader.exec_module(module)
    return module


generator = _load_generator()
make_test_iban = generator.make_iban
format_iban = generator.format_iban


def iban_for_supplier(k: int, *, other: bool = False) -> str:
    """Return the compact IBAN of fictional supplier k; `other` is a second valid account."""
    bank, branch = BANKS[(k - 1) % len(BANKS)]
    offset = OTHER_ACCOUNT_OFFSET if other else 0
    account = f"{(k * ACCOUNT_MULTIPLIER + offset) % 10**10:010d}"
    return make_test_iban(bank, branch, account)


def master_iban(k: int) -> str:
    """Return the master IBAN of supplier k written in groups of four, as in suppliers.csv."""
    return format_iban(iban_for_supplier(k))


def supplier_record(k: int) -> dict[str, str]:
    """Return name, tax id and spaced master IBAN of fictional supplier k."""
    name = SUPPLIER_NAMES.get(k, f"Proveedor Ficticio {k}, S.L.")
    if k in PERSON_SUPPLIERS:
        tax_id = generator.make_nif(k)
    else:
        tax_id = generator.make_cif(k)
    return {"supplier_name": name, "tax_id": tax_id, "iban": master_iban(k)}


def _to_frame(records: list[dict[str, Any]], kind: Kind, columns: tuple[str, ...]) -> pd.DataFrame:
    """Build a canonical frame; zero rows give the normaliser's empty frame of that kind."""
    if not records:
        frame, _ = normalise(kind=kind)
        return frame
    frame = pd.DataFrame(records, columns=list(columns))
    frame["source_row"] = frame["source_row"].astype("int64")
    return frame


def _derive_vat(base: Any, rate: Any) -> Decimal | None:
    """Return percent_of(base, rate), or None when either cell is not a Decimal."""
    if isinstance(base, Decimal) and isinstance(rate, Decimal):
        return percent_of(base, rate)
    return None


def _derive_total(record: Mapping[str, Any]) -> Decimal | None:
    """Return net_total(base + VAT + surcharge, withholding), or None for a non-Decimal cell."""
    additions = [record[key] for key in ("base_amount", "vat_amount", "surcharge_amount")]
    withholding = record["withholding_amount"]
    if all(isinstance(value, Decimal) for value in (*additions, withholding)):
        return net_total(additions, [withholding])
    return None


def _invoice_record(index: int, spec: Mapping[str, Any]) -> dict[str, Any]:
    """Return one invoice record: defaults, then `spec`, then derived VAT and total."""
    values = dict(spec)
    supplier = supplier_record(values.pop("supplier", 1))
    issue = values.get("issue_date", DEFAULT_ISSUE_DATE)
    due = None
    if isinstance(issue, date):
        due = issue + timedelta(days=DEFAULT_PAYMENT_TERM_DAYS)
    record: dict[str, Any] = {
        "invoice_number": f"F-2026-{index + 1:04d}",
        "supplier_name": supplier["supplier_name"],
        "supplier_tax_id": supplier["tax_id"],
        "issue_date": issue,
        "due_date": due,
        "due_date_is_default": False,
        "base_amount": Decimal("100.00"),
        "vat_rate": Decimal("21"),
        "surcharge_amount": ZERO,
        "withholding_amount": ZERO,
        "iban": None,
        "currency": "EUR",
        "source_file": INVOICE_FILE,
        "source_row": index,
        "source_ref": f"{INVOICE_FILE}:{index}",
    }
    record.update(values)
    if "vat_amount" not in values:
        record["vat_amount"] = _derive_vat(record["base_amount"], record["vat_rate"])
    if "total" not in values:
        record["total"] = _derive_total(record)
    return record


def make_invoices(rows: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    """Build an invoice frame with all INVOICE_COLUMNS from partial row dicts.

    Defaults: supplier 1, EUR, rate 21, base 100.00, no surcharge or withholding, no IBAN, issue
    date 2026-03-01 and due date 30 days later; `vat_amount` (percent_of) and `total` (net_total)
    are derived from the final values unless given; source_ref is 'inv.csv:<position>'. The extra
    key `supplier` (an int k) selects the fictional supplier whose name and tax id are used.
    """
    records = [_invoice_record(index, spec) for index, spec in enumerate(rows)]
    return _to_frame(records, "invoice", INVOICE_COLUMNS)


def _supplier_row(index: int, spec: Mapping[str, Any]) -> dict[str, Any]:
    """Return one supplier-master record; the master of supplier k is the default."""
    values = dict(spec)
    supplier = supplier_record(values.pop("supplier", index + 1))
    record: dict[str, Any] = {
        "supplier_name": supplier["supplier_name"],
        "tax_id": supplier["tax_id"],
        "iban": supplier["iban"],
        "source_file": SUPPLIER_FILE,
        "source_row": index,
        "source_ref": f"{SUPPLIER_FILE}:{index}",
    }
    record.update(values)
    return record


def make_suppliers(rows: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    """Build a supplier-master frame with all SUPPLIER_COLUMNS; source_ref is 'sup.csv:<i>'.

    Row i describes fictional supplier i + 1 unless the key `supplier` says otherwise.
    """
    records = [_supplier_row(index, spec) for index, spec in enumerate(rows)]
    return _to_frame(records, "supplier", SUPPLIER_COLUMNS)


def _payment_record(index: int, spec: Mapping[str, Any]) -> dict[str, Any]:
    """Return one bank-payment record: a debit of 121.00 EUR to supplier 1 unless overridden."""
    values = dict(spec)
    supplier = supplier_record(values.pop("supplier", 1))
    record: dict[str, Any] = {
        "id": str(uuid.UUID(int=index + 1)),
        "date": DEFAULT_ISSUE_DATE,
        "amount": Decimal("121.00"),
        "flow": "debit",
        "currency": "EUR",
        "counterparty": supplier["supplier_name"],
        "description": "Synthetic payment",
        "iban": None,
        "source_file": PAYMENT_FILE,
        "source_row": index,
        "source_ref": f"{PAYMENT_FILE}:{index}",
        "tags": [],
    }
    record.update(values)
    return record


def make_payments(rows: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    """Build a bank-payment frame with all CANONICAL_COLUMNS; source_ref is 'pay.csv:<i>'.

    The amount is positive and `flow` says the direction. The key `supplier` (an int k) selects
    the counterparty name.
    """
    records = [_payment_record(index, spec) for index, spec in enumerate(rows)]
    return _to_frame(records, "transaction", CANONICAL_COLUMNS)


def ctx(
    suppliers: pd.DataFrame | None = None,
    payments: pd.DataFrame | None = None,
    as_of: date | None = None,
) -> MappingProxyType:
    """Return the read-only detector context; missing frames are empty frames with columns."""
    if suppliers is None:
        suppliers = make_suppliers([])
    if payments is None:
        payments = make_payments([])
    return MappingProxyType({"suppliers": suppliers, "payments": payments, "as_of": as_of})


class Scenario(NamedTuple):
    """Everything a detector needs for one planted situation."""

    invoices: pd.DataFrame
    suppliers: pd.DataFrame
    payments: pd.DataFrame
    as_of: date | None = None

    def context(self) -> MappingProxyType:
        """Return the detector context of this scenario."""
        return ctx(self.suppliers, self.payments, self.as_of)
