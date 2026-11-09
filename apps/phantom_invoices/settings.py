"""Load config.toml, read the demo inputs and run the whole pipeline (design sections 3 and 14).

Everything here works without Streamlit so it can be tested directly. No money is computed in
this module and nothing reads the system clock.
"""

from __future__ import annotations

import io
import tomllib
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from apps.phantom_invoices.detectors.utils import Reconciliation, reconcile, resolve_as_of
from apps.phantom_invoices.prepare import quarantine_multi_rate
from ledger_kit.detectors import DetectorResult, run_all
from ledger_kit.ingestion.csv_reader import parse_csv
from ledger_kit.ingestion.invoice_reader import parse_invoice
from ledger_kit.ingestion.normaliser import normalise
from ledger_kit.ingestion.supplier_reader import parse_suppliers


@dataclass(frozen=True)
class Source:
    """One input file: `name` becomes source_file (and so the source_ref prefix)."""

    name: str
    data: bytes


@dataclass(frozen=True)
class DemoInputs:
    """The three demo files and the optional demo `as_of` date."""

    invoices: Source
    suppliers: Source
    payments: Source
    as_of: date | None = None


@dataclass(frozen=True)
class Pipeline:
    """Everything the UI shows, computed once from the three inputs."""

    invoices: pd.DataFrame  # clean (multi-rate rows removed)
    suppliers: pd.DataFrame
    payments: pd.DataFrame
    quarantine: list[dict]  # ingestion quarantine + multi-rate records, each with "file_kind"
    as_of_used: date | None
    results: list[DetectorResult]
    reconciliation: Reconciliation


def load_config(path: Path) -> dict[str, Any]:
    """Read a TOML configuration file into a dict."""
    with Path(path).open("rb") as handle:
        return tomllib.load(handle)


def to_date(value: str | date) -> date:
    """Convert a TOML date string or a TOML date value to a datetime.date."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def _read_source(root: Path, relative: str) -> Source:
    """Read one demo file (path relative to `root`) as bytes."""
    path = Path(root) / relative
    return Source(name=path.name, data=path.read_bytes())


def demo_inputs(config: dict[str, Any], root: Path) -> DemoInputs:
    """Read the three files named by [demo] (relative to `root`) and the optional as_of."""
    demo = config["demo"]
    as_of = demo.get("as_of")
    return DemoInputs(
        invoices=_read_source(root, demo["invoices_path"]),
        suppliers=_read_source(root, demo["suppliers_path"]),
        payments=_read_source(root, demo["payments_path"]),
        as_of=None if as_of is None else to_date(as_of),
    )


def _tag(kind: str, records: list[dict]) -> list[dict]:
    """Return copies of the quarantine records with `file_kind` added; other keys unchanged."""
    return [{**record, "file_kind": kind} for record in records]


def run_pipeline(
    invoices: Source | None,
    suppliers: Source | None,
    payments: Source | None,
    as_of: date | None,
) -> Pipeline:
    """Parse, normalise, quarantine multi-rate invoices, run pi.* detectors and reconcile."""
    inv_list, inv_q = (
        ([], [])
        if invoices is None
        else parse_invoice(
            io.BytesIO(invoices.data),
            fmt="json" if invoices.name.lower().endswith(".json") else "csv",
            source_file=invoices.name,
        )
    )
    sup_list, sup_q = (
        ([], [])
        if suppliers is None
        else parse_suppliers(io.BytesIO(suppliers.data), source_file=suppliers.name)
    )
    pay_list, pay_q = (
        ([], [])
        if payments is None
        else parse_csv(io.BytesIO(payments.data), source_file=payments.name)
    )
    invoices_df, inv_n = normalise(inv_list, kind="invoice")
    suppliers_df, sup_n = normalise(sup_list, kind="supplier")
    payments_df, pay_n = normalise(pay_list, kind="transaction")
    clean, multi_rate = quarantine_multi_rate(invoices_df)

    context = {"suppliers": suppliers_df, "payments": payments_df, "as_of": as_of}
    as_of_used = resolve_as_of(clean, context)
    results = run_all(clean, namespace="pi", context=context)
    rec = reconcile(clean, suppliers_df, payments_df, as_of_used)
    quarantine = (
        _tag("invoices", inv_q + inv_n + multi_rate)
        + _tag("suppliers", sup_q + sup_n)
        + _tag("payments", pay_q + pay_n)
    )
    return Pipeline(clean, suppliers_df, payments_df, quarantine, as_of_used, results, rec)
