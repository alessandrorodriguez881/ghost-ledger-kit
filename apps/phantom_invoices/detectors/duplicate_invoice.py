"""Duplicate-invoice detector: the same invoice sent twice, exactly or almost (design section 7).

Pure function of the invoice frame; the context is ignored. Money is only compared through
`within_tolerance` and formatted through `round_to_cents` (REQ-MON-03).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

import pandas as pd

from apps.phantom_invoices.detectors.utils import (
    as_date,
    as_decimal,
    as_text,
    finish,
    load_rows,
    n1_key,
    n2_key,
    source_ref_key,
    supplier_label,
    tax_key,
)
from ledger_kit.detectors import register
from ledger_kit.models import Alert
from ledger_kit.utils.money import round_to_cents, within_tolerance

# Same supplier, same total, different numbers: suspicious when issued fewer than this many days
# apart (rule C).
DUPLICATE_WINDOW_DAYS: int = 7
# Same supplier, same number: suspicious only when issued fewer than this many days apart (rule A);
# an annual numbering restart is further apart (OD-PI-07).
SAME_NUMBER_WINDOW_DAYS: int = 180
# "Same total" means equal to the cent.
DUPLICATE_TOTAL_TOLERANCE: Decimal = Decimal("0.00")

# Strength of each rule: A (same number) > B (near-identical number) > C (same total, close dates).
VARIANT_RANK: dict[str, int] = {
    "same_number": 3,
    "near_identical_number": 2,
    "same_total_close_dates": 1,
}
VARIANT_BY_RANK: dict[int, str] = {rank: variant for variant, rank in VARIANT_RANK.items()}


@dataclass(frozen=True)
class _Inv:
    """The fields of one usable invoice row that the duplicate rules read."""

    ref: str
    number: str  # as written
    n1: str
    n2: str
    tax: str  # tax_key of the supplier
    name: str  # supplier label
    issue: date
    total: Decimal
    currency: str | None
    rate: Decimal | None  # vat_rate; None when missing


def _usable(row: dict) -> _Inv | None:
    """Return the row as an _Inv, or None when it is not usable (REQ-PI-17)."""
    ref = as_text(row.get("source_ref"))
    number = as_text(row.get("invoice_number"))
    tax = tax_key(as_text(row.get("supplier_tax_id")) or "")
    issue = as_date(row.get("issue_date"))
    total = as_decimal(row.get("total"))
    if ref is None or number is None or not tax or issue is None or total is None:
        return None
    n1 = n1_key(number)
    if not n1:
        return None
    return _Inv(
        ref,
        number,
        n1,
        n2_key(number),
        tax,
        supplier_label(row, ref),
        issue,
        total,
        as_text(row.get("currency")),
        as_decimal(row.get("vat_rate")),
    )


def _drop_multi_rate(members: list[_Inv]) -> list[_Inv]:
    """Drop every row of a supplier+N1 group that holds more than one distinct vat_rate."""
    rates: dict[str, set[Decimal]] = {}
    for member in members:
        if member.rate is not None:
            rates.setdefault(member.n1, set()).add(member.rate)
    return [m for m in members if len(rates.get(m.n1, ())) <= 1]


def _pair_variant(a: _Inv, b: _Inv) -> str | None:
    """Return the rule that relates two invoices of one supplier, or None. No similarity score."""
    if a.currency != b.currency:  # REQ-PI-05
        return None
    days = abs((a.issue - b.issue).days)
    if a.n1 == b.n1:  # rule A is the only rule for equal N1
        return "same_number" if days < SAME_NUMBER_WINDOW_DAYS else None
    if not within_tolerance(a.total, b.total, DUPLICATE_TOTAL_TOLERANCE):
        return None
    if a.n2 == b.n2:  # rule B: no date window
        return "near_identical_number"
    return "same_total_close_dates" if days < DUPLICATE_WINDOW_DAYS else None  # rule C


def _groups(members: list[_Inv]) -> list[tuple[list[_Inv], int]]:
    """Return connected groups of two or more related invoices, each with its highest rank."""
    count = len(members)
    parent = list(range(count))
    top = [0] * count  # highest rank per root

    def find(i: int) -> int:
        """Return the root of i, compressing the path."""
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(count):
        for j in range(i + 1, count):
            rank = VARIANT_RANK.get(_pair_variant(members[i], members[j]) or "", 0)
            if rank == 0:
                continue
            root_i, root_j = find(i), find(j)
            best = max(rank, top[root_i], top[root_j])
            parent[root_j] = root_i
            top[root_i] = best
    by_root: dict[int, list[_Inv]] = {}
    for i in range(count):
        by_root.setdefault(find(i), []).append(members[i])
    return [(group, top[root]) for root, group in by_root.items() if len(group) > 1]


def _alert(group: list[_Inv], rank: int) -> Alert:
    """Build the single alert of one group (members in natural source_ref order)."""
    members = sorted(group, key=lambda m: source_ref_key(m.ref))
    first = members[0]
    variant = VARIANT_BY_RANK[rank]
    first_day = min(m.issue for m in members)
    last_day = max(m.issue for m in members)
    prefix = "Duplicate invoice" if variant == "same_number" else "Possible duplicate invoice"
    return Alert(
        detector="pi.duplicate_invoice",
        severity="critical" if variant == "same_number" else "warning",
        title=f"{prefix}: {first.number} ({first.name})",
        source_refs=[m.ref for m in members],
        data={
            "variant": variant,
            "supplier_name": first.name,
            "invoice_count": len(members),
            "invoice_numbers": [m.number for m in members],
            "totals": [str(round_to_cents(m.total)) for m in members],
            "total": str(round_to_cents(first.total)),
            "first_issue_date": first_day.isoformat(),
            "last_issue_date": last_day.isoformat(),
            "days_apart": (last_day - first_day).days,
        },
    )


@register("pi.duplicate_invoice")
def detect_duplicate_invoices(ledger: pd.DataFrame, context: Mapping[str, Any]) -> list[Alert]:
    """Flag invoices that look like the same invoice sent twice."""
    usable = [u for u in (_usable(r) for r in load_rows(ledger, "issue_date")) if u is not None]
    by_supplier: dict[str, list[_Inv]] = {}
    for inv in usable:
        by_supplier.setdefault(inv.tax, []).append(inv)
    alerts: list[Alert] = []
    for tax in sorted(by_supplier):
        members = _drop_multi_rate(by_supplier[tax])
        if len(members) < 2:
            continue
        for group, rank in _groups(members):
            alerts.append(_alert(group, rank))
    return finish(alerts)
