"""Canonical Pydantic models: Transaction, Invoice, Supplier and Alert."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

_INVOICE_AMOUNT_FIELDS = (
    "base_amount",
    "vat_rate",
    "vat_amount",
    "surcharge_amount",
    "withholding_amount",
    "total",
)


class Transaction(BaseModel):
    """A single normalised bank-statement row; `amount` is positive, direction is `flow`."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    date: dt.date
    amount: Decimal
    flow: Literal["debit", "credit"]
    currency: str
    counterparty: str
    description: str
    iban: str | None = None
    source_file: str
    source_row: int
    source_ref: str
    source_line: int | None = None  # 1-based line of the file where the record starts, header = 1
    tags: list[str] = []

    model_config = {"frozen": True}

    @field_validator("amount")
    @classmethod
    def _amount_non_negative(cls, value: Decimal) -> Decimal:
        """Reject negative amounts; the sign is carried by `flow`."""
        if value < 0:
            raise ValueError("amount must be >= 0; direction is encoded in flow")
        return value


class Invoice(BaseModel):
    """A supplier invoice row, addressed by `source_ref` (no id field)."""

    invoice_number: str
    supplier_name: str
    supplier_tax_id: str
    issue_date: dt.date
    due_date: dt.date
    due_date_is_default: bool = False
    base_amount: Decimal
    vat_rate: Decimal
    vat_amount: Decimal
    surcharge_amount: Decimal = Decimal("0")
    withholding_amount: Decimal = Decimal("0")
    total: Decimal
    iban: str | None = None
    currency: str
    source_file: str
    source_row: int
    source_ref: str
    source_line: int | None = None  # 1-based line of the file where the record starts, header = 1

    model_config = {"frozen": True}

    @field_validator(*_INVOICE_AMOUNT_FIELDS)
    @classmethod
    def _amounts_non_negative(cls, value: Decimal) -> Decimal:
        """Reject negative values in any of the six amount fields."""
        if value < 0:
            raise ValueError("amount fields must be >= 0")
        return value


class Supplier(BaseModel):
    """A supplier-master row; identifiers are stored exactly as read."""

    supplier_name: str
    tax_id: str
    iban: str | None = None
    source_file: str
    source_row: int
    source_ref: str
    source_line: int | None = None  # 1-based line of the file where the record starts, header = 1

    model_config = {"frozen": True}


def _json_default(value: Any) -> Any:
    """Convert numpy scalars to Python values and everything else to str for json.dumps."""
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return item()
        except (TypeError, ValueError):
            pass
    return str(value)


def _deterministic_alert_id(detector: str, source_refs: list[str], data: dict) -> str:
    """Compute a deterministic sha256 id from the alert identity fields."""
    payload = json.dumps(
        {"detector": detector, "source_refs": sorted(source_refs), "data": data},
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


class Alert(BaseModel):
    """A detector finding; `explanation` is filled only by the explanation layer."""

    id: str = Field(default="")
    detector: str
    severity: Literal["info", "warning", "critical"]
    title: str
    source_refs: list[str]
    data: dict
    explanation: str = ""

    model_config = {"frozen": True}

    @model_validator(mode="before")
    @classmethod
    def _set_deterministic_id(cls, values: Any) -> Any:
        """Fill `id` deterministically when absent; leave missing fields to field validation."""
        if isinstance(values, dict) and not values.get("id"):
            if all(k in values for k in ("detector", "source_refs", "data")):
                try:
                    alert_id = _deterministic_alert_id(
                        values["detector"], values["source_refs"], values["data"]
                    )
                except (TypeError, AttributeError):
                    # Malformed field types: let field validation report them.
                    return values
                values = {**values, "id": alert_id}
        return values

    @field_validator("source_refs")
    @classmethod
    def _source_refs_non_empty(cls, value: list[str]) -> list[str]:
        """Every alert must cite at least one source row."""
        if len(value) < 1:
            raise ValueError("source_refs must contain at least one entry")
        return value
