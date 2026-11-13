"""Fallback templates, explanation rows and the hallucinating stub of App 2 (design section 12).

The app never builds a prompt or calls an LLM itself: it hands `explain_with_meta` the cited rows,
a fallback template per (detector, variant) and, when the user asks for it, a stub client that
invents a number. The filled fallback text comes from `ledger_kit.explainer.fill_fallback`; this
module defines no wrapper around it.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Self

import pandas as pd

from ledger_kit.explainer import Explanation, explain_with_meta
from ledger_kit.models import Alert

# Columns of the cited rows that may reach the LLM (REQ-PI-42). Never iban, supplier_tax_id,
# tax_id, id or description.
ROW_COLUMNS: tuple[str, ...] = (
    "invoice_number",
    "supplier_name",
    "issue_date",
    "due_date",
    "base_amount",
    "vat_rate",
    "vat_amount",
    "surcharge_amount",
    "withholding_amount",
    "total",
    "currency",
    "source_ref",
)

# Fallback text per (detector, variant) (REQ-PI-45). `{key:money}` is formatted with
# format_amount, `{key}` is plain text and `{source_refs}` is the comma-joined list of cited rows.
# Every placeholder is a field of Alert.data; the templates state facts and recommend nothing.
TEMPLATES: dict[tuple[str, str], str] = {
    ("pi.duplicate_invoice", "same_number"): (
        "Supplier {supplier_name} sent {invoice_count} invoices with the same invoice number, "
        "issued between {first_issue_date} and {last_issue_date}. Source: {source_refs}."
    ),
    ("pi.duplicate_invoice", "near_identical_number"): (
        "Supplier {supplier_name} has {invoice_count} invoices with near-identical numbers and "
        "the same total of {total:money}, issued {days_apart} days apart. Source: {source_refs}."
    ),
    ("pi.duplicate_invoice", "same_total_close_dates"): (
        "Supplier {supplier_name} has {invoice_count} invoices with the same total of "
        "{total:money}, issued {days_apart} days apart. Source: {source_refs}."
    ),
    ("pi.iban_change", "invoice_iban_differs_from_master"): (
        "Invoice {invoice_number} from {supplier_name} names the account {invoice_iban_masked}, "
        "which differs from the account {master_iban_masked} in the supplier master. "
        "Source: {source_refs}."
    ),
    ("pi.iban_change", "payment_to_non_master_iban"): (
        "A payment of {payment_amount:money} on {payment_date} to {supplier_name} went to the "
        "account {payment_iban_masked}, which differs from the account {master_iban_masked} in "
        "the supplier master. Source: {source_refs}."
    ),
    ("pi.iban_change", "iban_invalid"): (
        "The IBAN {iban_masked} on the {subject} {label} is not a valid IBAN (failed {reason} "
        "check). Source: {source_refs}."
    ),
    ("pi.vat_error", "vat_amount_mismatch"): (
        "Invoice {invoice_number} from {supplier_name} states VAT of {vat_amount:money}; "
        "{vat_rate} % of the base {base_amount:money} is {expected_vat_amount:money}. "
        "Source: {source_refs}."
    ),
    ("pi.vat_error", "total_mismatch"): (
        "Invoice {invoice_number} from {supplier_name} states a total of {total:money}; base "
        "{base_amount:money} plus VAT {vat_amount:money} plus surcharge {surcharge_amount:money} "
        "minus withholding {withholding_amount:money} is {expected_total:money}. "
        "Source: {source_refs}."
    ),
    ("pi.vat_error", "vat_rate_not_allowed"): (
        "Invoice {invoice_number} from {supplier_name} uses a VAT rate of {vat_rate} %, which is "
        "not one of the supported rates ({allowed_vat_rates}). Source: {source_refs}."
    ),
    ("pi.reconciliation", "invoice_overdue"): (
        "Invoice {invoice_number} from {supplier_name} for {total:money} was due on {due_date} "
        "and no matching payment was found as of {as_of}. Source: {source_refs}."
    ),
    ("pi.reconciliation", "payment_without_invoice"): (
        "A payment of {payment_amount:money} to {supplier_name} on {payment_date} could not be "
        "matched to any invoice. Source: {source_refs}."
    ),
}

# Wording used instead of the TEMPLATES entry when all invoices of a duplicate group share one
# issue date (first_issue_date == last_issue_date), so the text never reads "between D and D" or
# "0 days apart". Same placeholders rules as TEMPLATES; the keys are a subset of TEMPLATES.
SAME_DAY_TEMPLATES: dict[tuple[str, str], str] = {
    ("pi.duplicate_invoice", "same_number"): (
        "Supplier {supplier_name} sent {invoice_count} invoices with the same invoice number, "
        "all issued on {first_issue_date}. Source: {source_refs}."
    ),
    ("pi.duplicate_invoice", "near_identical_number"): (
        "Supplier {supplier_name} has {invoice_count} invoices with near-identical numbers and "
        "the same total of {total:money}, all issued on {first_issue_date}. "
        "Source: {source_refs}."
    ),
    ("pi.duplicate_invoice", "same_total_close_dates"): (
        "Supplier {supplier_name} has {invoice_count} invoices with the same total of "
        "{total:money}, all issued on {first_issue_date}. Source: {source_refs}."
    ),
}

# Guard-badge texts (REQ-PI-46).
BADGE_LLM: str = "🤖 ✓ LLM text · figures checked by the number guard; wording not checked"
BADGE_TEMPLATE: str = "📋 Template (no API key)"
BADGE_UNAVAILABLE: str = "📋 Template (LLM unavailable)"
BADGE_REJECTED: str = (
    "⚠️ LLM answer rejected: not found in the cited rows or the alert data: {numbers}"
)


def template_for(alert: Alert) -> str:
    """Return the fallback template of the alert's (detector, variant); KeyError if unknown.

    A duplicate-invoice alert whose invoices share one issue date gets the same-day wording.
    """
    variant = str(alert.data.get("variant", ""))
    key = (alert.detector, variant)
    first, last = alert.data.get("first_issue_date"), alert.data.get("last_issue_date")
    if key in SAME_DAY_TEMPLATES and first is not None and first == last:
        return SAME_DAY_TEMPLATES[key]
    try:
        return TEMPLATES[key]
    except KeyError:
        message = f"no fallback template for detector {alert.detector!r} and variant {variant!r}"
        raise KeyError(message) from None


def build_explain_rows(
    alert: Alert,
    invoices: pd.DataFrame,
    suppliers: pd.DataFrame,
    payments: pd.DataFrame,
) -> pd.DataFrame:
    """Return the rows cited by the alert, from whichever frame holds them, as ROW_COLUMNS.

    Payment rows contribute only `currency` and `source_ref`, master rows only `supplier_name`
    and `source_ref`; absent cells stay missing. Rows follow the order of `alert.source_refs`.
    """
    found: dict[str, dict] = {}
    for frame in (invoices, suppliers, payments):
        if not isinstance(frame, pd.DataFrame) or "source_ref" not in frame.columns:
            continue
        cols = [c for c in ROW_COLUMNS if c in frame.columns]
        for rec in frame[frame["source_ref"].isin(alert.source_refs)][cols].to_dict("records"):
            found.setdefault(rec["source_ref"], rec)
    records = [found[ref] for ref in alert.source_refs if ref in found]
    return pd.DataFrame(records, columns=list(ROW_COLUMNS))


def explain_alert(
    alert: Alert,
    invoices: pd.DataFrame,
    suppliers: pd.DataFrame,
    payments: pd.DataFrame,
    *,
    client: Any = None,
    question: str | None = None,
) -> Explanation:
    """Explain one alert from its cited rows; falls back to the filled template on any problem.

    `question` is the optional trick question of the live-guard panel; None leaves the call as is.
    """
    rows = build_explain_rows(alert, invoices, suppliers, payments)
    return explain_with_meta(
        alert,
        rows,
        fallback_template=template_for(alert),
        client=client,
        row_columns=ROW_COLUMNS,
        question=question,
    )


def guard_badge(meta: Explanation, api_key_present: bool) -> str:
    """Return the badge text of one explanation (same semantics as App 1, REQ-ZS-37)."""
    if meta.source == "llm":
        return BADGE_LLM
    if meta.rejected_numbers:
        return BADGE_REJECTED.format(numbers=", ".join(meta.rejected_numbers))
    return BADGE_UNAVAILABLE if api_key_present else BADGE_TEMPLATE


def badge_kind(meta: Explanation, api_key_present: bool) -> str:
    """Return the CSS kind of the badge: 'llm', 'rejected', 'unavailable' or 'template'."""
    if meta.source == "llm":
        return "llm"
    if meta.rejected_numbers:
        return "rejected"
    return "unavailable" if api_key_present else "template"


def explanation_key(alert: Alert, hallucinate: bool) -> tuple[str, str]:
    """Return the cache key of an explanation: the alert id and the client mode (REQ-PI-47)."""
    return alert.id, "hallucinate" if hallucinate else "real"


class HallucinatingStubClient:
    """OpenAI-shaped stub whose answer is the filled fallback plus a number in no alert.

    Used by the "Simulate a hallucinating LLM" toggle to show the number guard at work. It is a
    separate copy of App 1's stub because apps must not import each other.
    """

    INJECTED_NUMBER: str = "99999.99"  # absent from every real alert and ledger row

    def __init__(self, filled_fallback: str) -> None:
        """Remember the answer: the filled fallback followed by the foreign number."""
        self._text = f"{filled_fallback} Total exposure: {self.INJECTED_NUMBER} EUR."

    @property
    def chat(self) -> Self:
        """Mirror `client.chat`."""
        return self

    @property
    def completions(self) -> Self:
        """Mirror `client.chat.completions`."""
        return self

    def create(self, *, messages: Any, **_kwargs: Any) -> SimpleNamespace:
        """Return a response whose text is the stored answer."""
        message = SimpleNamespace(content=self._text)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])
