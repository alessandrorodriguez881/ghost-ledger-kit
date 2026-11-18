"""Normaliser: merge model lists of one kind into the canonical DataFrame."""

from __future__ import annotations

from typing import Any, Literal

import pandas as pd

from ledger_kit.models import Invoice, Supplier, Transaction

Kind = Literal["transaction", "invoice", "supplier"]
NormaliseResult = tuple[pd.DataFrame, list[dict]]

# Canonical column order per kind (REQ-ING-13 and REQ-ING-34).
CANONICAL_COLUMNS: tuple[str, ...] = (
    "id",
    "date",
    "amount",
    "flow",
    "currency",
    "counterparty",
    "description",
    "iban",
    "source_file",
    "source_row",
    "source_ref",
    "source_line",
    "tags",
)
INVOICE_COLUMNS: tuple[str, ...] = (
    "invoice_number",
    "supplier_name",
    "supplier_tax_id",
    "issue_date",
    "due_date",
    "due_date_is_default",
    "base_amount",
    "vat_rate",
    "vat_amount",
    "surcharge_amount",
    "withholding_amount",
    "total",
    "iban",
    "currency",
    "source_file",
    "source_row",
    "source_ref",
    "source_line",
)
SUPPLIER_COLUMNS: tuple[str, ...] = (
    "supplier_name",
    "tax_id",
    "iban",
    "source_file",
    "source_row",
    "source_ref",
    "source_line",
)

COLUMNS: dict[Kind, tuple[str, ...]] = {
    "transaction": CANONICAL_COLUMNS,
    "invoice": INVOICE_COLUMNS,
    "supplier": SUPPLIER_COLUMNS,
}

_MODEL_TYPES: dict[type, Kind] = {
    Transaction: "transaction",
    Invoice: "invoice",
    Supplier: "supplier",
}

# Columns allowed to be null; every other canonical column is required.
_OPTIONAL_COLUMNS: frozenset[str] = frozenset({"iban", "tags", "source_line"})

_DEFAULT_KIND: Kind = "transaction"


def _kind_of(model: Any) -> Kind:
    """Return the kind of a model instance; TypeError for unsupported objects."""
    kind = _MODEL_TYPES.get(type(model))
    if kind is None:
        raise TypeError(f"cannot normalise object of type {type(model).__name__}")
    return kind


def _resolve_kind(models: list[Any], kind: Kind | None) -> Kind:
    """Infer the kind from the models, check it against `kind`, or fall back to a default."""
    inferred = {_kind_of(m) for m in models}
    if len(inferred) > 1:
        raise ValueError(f"cannot mix kinds in one normalise() call: {sorted(inferred)}")
    if inferred:
        found = next(iter(inferred))
        if kind is not None and kind != found:
            raise ValueError(f"kind={kind!r} disagrees with the inferred kind {found!r}")
        return found
    return kind if kind is not None else _DEFAULT_KIND


def _missing_field(record: dict[str, Any], columns: tuple[str, ...]) -> str | None:
    """Return the first required column whose value is None, or None when all are set."""
    for column in columns:
        if column not in _OPTIONAL_COLUMNS and record.get(column) is None:
            return column
    return None


def normalise(
    *sources: list[Transaction] | list[Invoice] | list[Supplier],
    kind: Kind | None = None,
) -> NormaliseResult:
    """Merge model lists of ONE kind into a canonical DataFrame. Returns (frame, quarantined)."""
    models = [model for source in sources for model in source]
    resolved = _resolve_kind(models, kind)
    columns = COLUMNS[resolved]

    records: list[dict[str, Any]] = []
    quarantined: list[dict] = []
    for model in models:
        record = model.model_dump()
        missing = _missing_field(record, columns)
        if missing is not None:
            quarantined.append(
                {
                    "source_file": record.get("source_file"),
                    "source_row": record.get("source_row"),
                    "reason": f"missing_field:{missing}",
                    "raw": record,
                }
            )
            continue
        records.append(record)

    frame = pd.DataFrame(records, columns=list(columns))
    frame["source_row"] = frame["source_row"].astype("int64")
    frame["source_line"] = frame["source_line"].astype("Int64")
    return frame, quarantined
