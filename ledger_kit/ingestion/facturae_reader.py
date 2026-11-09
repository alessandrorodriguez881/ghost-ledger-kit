"""Facturae 3.2 / 3.2.1 / 3.2.2 reader: one Invoice per `Invoices/Invoice`, with quarantine.

Element paths follow the official schema `Facturaev3_2_2.xml` (verified in the session 8b review).
Elements are matched by local name along explicit paths, never searched, so a namespace prefix, a
qualified child or a `ds:Signature` block cannot change what is read. Untrusted XML is parsed only
with `defusedxml` (REQ-RF-18); this module imports no other XML parser.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import IO, Any

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import ParseError, fromstring

from ledger_kit.ingestion.csv_reader import IngestionResult, _read_source
from ledger_kit.ingestion.invoice_reader import DEFAULT_PAYMENT_TERM_DAYS
from ledger_kit.models import Invoice
from ledger_kit.utils.money import round_to_cents, sum_amounts

# Largest document the reader parses, in bytes; Streamlit's own upload limit is far larger.
MAX_FACTURAE_BYTES: int = 10 * 1024 * 1024
# Schema versions the reader supports (FileHeader/SchemaVersion).
SUPPORTED_VERSIONS: tuple[str, ...] = ("3.2", "3.2.1", "3.2.2")
# TaxTypeCode of the VAT (IVA) entries of TaxesOutputs and of the IRPF entries of TaxesWithheld.
VAT_TAX_CODE: str = "01"
WITHHOLDING_TAX_CODE: str = "04"
# An amount whose decimal exponent is larger than this (in either direction) is not a plausible
# figure; it is refused so that no later format or quantize call can blow up in memory.
MAX_AMOUNT_ADJUSTED: int = 24
# The order in which a missing required field is reported (REQ-RF-17).
REQUIRED_FIELDS: tuple[str, ...] = (
    "supplier_tax_id",
    "supplier_name",
    "invoice_number",
    "issue_date",
    "currency",
    "base_amount",
    "vat_rate",
    "vat_amount",
    "surcharge_amount",
    "total",
)
# The amounts rounded to cents at ingestion; the VAT rate is kept exact (DN-RF-11).
MONEY_FIELDS: tuple[str, ...] = (
    "base_amount",
    "vat_amount",
    "surcharge_amount",
    "withholding_amount",
    "total",
)

# The children of `Individual` that make up a person's name, joined by one space (DN-RF-13).
INDIVIDUAL_NAME_PARTS: tuple[str, ...] = ("Name", "FirstSurname", "SecondSurname")

_DATE_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}(Z|[+-][0-9]{2}:[0-9]{2})?")
_NUMBER_PATTERN = re.compile(r"[+-]?([0-9]+(\.[0-9]*)?|\.[0-9]+)([eE][+-]?[0-9]+)?")

# Parsed elements are only ever walked by local name, so their concrete type does not matter here.
Element = Any


def _local(tag: object) -> str:
    """Return the local name of an element tag (the part after `{namespace}`)."""
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _children(element: Element | None, name: str) -> list[Element]:
    """Return the direct children of `element` with the local name `name`."""
    if element is None:
        return []
    return [child for child in element if _local(child.tag) == name]


def _child(element: Element | None, *path: str) -> Element | None:
    """Follow `path` through the first matching child at each step; None when it is absent."""
    current = element
    for name in path:
        found = _children(current, name)
        if not found:
            return None
        current = found[0]
    return current


def _text(element: Element | None, *path: str) -> str | None:
    """Return the trimmed text at `path`, or None when the element is absent or blank."""
    node = _child(element, *path)
    if node is None:
        return None
    return (node.text or "").strip() or None


def _present(values: Iterable[str | None]) -> list[str]:
    """Keep the texts that are not None, in order."""
    return [value for value in values if value is not None]


def _amount(text: str) -> Decimal:
    """Read an `xs:double` text as an exact Decimal; raise InvalidOperation when unusable."""
    if _NUMBER_PATTERN.fullmatch(text) is None:
        raise InvalidOperation(text)
    value = Decimal(text)
    if value != 0 and abs(value.adjusted()) > MAX_AMOUNT_ADJUSTED:
        raise InvalidOperation(text)
    return value


def _canonical_rate(rate: Decimal) -> Decimal:
    """Write a rate without trailing zeros or exponent: 21.00 -> 21, 5.20 -> 5.2, 1E+1 -> 10."""
    if rate == 0:
        return Decimal("0")
    return Decimal(format(rate.normalize(), "f"))


def _xs_date(text: str) -> date:
    """Read an `xs:date` (a zone suffix is ignored); raise ValueError when it is not one."""
    if _DATE_PATTERN.fullmatch(text) is None:
        raise ValueError(text)
    return date.fromisoformat(text[:10])


def _record(source_file: str, source_row: int | None, reason: str, raw: object) -> dict:
    """Build a quarantine record."""
    return {"source_file": source_file, "source_row": source_row, "reason": reason, "raw": raw}


def _seller_name(seller: Element | None) -> str | None:
    """Return the seller's corporate name, else the joined parts of an individual's name."""
    corporate = _text(seller, "LegalEntity", "CorporateName")
    if corporate is not None:
        return corporate
    individual = _child(seller, "Individual")
    parts = _present(_text(individual, part) for part in INDIVIDUAL_NAME_PARTS)
    return " ".join(parts) or None


def _tax_problem(outputs: Sequence[Element], withheld: Sequence[Element]) -> str | None:
    """Return the quarantine reason for the invoice's taxes, or None when they can be read."""
    for tax in outputs:
        code = _text(tax, "TaxTypeCode") or ""
        if code != VAT_TAX_CODE:
            return f"unsupported_tax_type:{code}"
    if not outputs:
        return "missing_vat_tax"
    if len(outputs) > 1:
        return "multiple_vat_rates"
    for tax in withheld:
        code = _text(tax, "TaxTypeCode") or ""
        if code != WITHHOLDING_TAX_CODE:
            return f"unsupported_tax_type:{code}"
    return None


def _missing_field(
    raw: dict[str, str | None], surcharge_declared: bool, withheld_texts: Sequence[str | None]
) -> str | None:
    """Return the reason for the first missing required field, or None when all are present."""
    for name in REQUIRED_FIELDS:
        if raw[name] is None and (name != "surcharge_amount" or surcharge_declared):
            return f"missing_field:{name}"
    if any(text is None for text in withheld_texts):
        return "missing_field:withholding_amount"
    return None


def _read_amounts(raw: dict[str, str | None], withheld_texts: Sequence[str | None]) -> dict:
    """Read the six amounts exactly; a surcharge that is not declared is zero."""
    surcharge = raw["surcharge_amount"]
    return {
        "base_amount": _amount(raw["base_amount"] or ""),
        "vat_rate": _amount(raw["vat_rate"] or ""),
        "vat_amount": _amount(raw["vat_amount"] or ""),
        "surcharge_amount": Decimal("0") if surcharge is None else _amount(surcharge),
        "withholding_amount": sum_amounts(_amount(text or "") for text in withheld_texts),
        "total": _amount(raw["total"] or ""),
    }


def _same_iban(left: str, right: str) -> bool:
    """Compare two IBAN texts after removing spaces and upper-casing."""
    return "".join(left.split()).upper() == "".join(right.split()).upper()


def _conflicting(ibans: Sequence[str]) -> bool:
    """True when the installments name more than one distinct IBAN."""
    return any(not _same_iban(ibans[0], other) for other in ibans[1:])


def _build_invoice(
    invoice: Element, seller: Element | None, position: int, file_name: str
) -> Invoice | dict:
    """Build one Invoice from an `Invoices/Invoice` element, or return a quarantine record."""
    outputs = _children(_child(invoice, "TaxesOutputs"), "Tax")
    withheld = _children(_child(invoice, "TaxesWithheld"), "Tax")
    vat = next((tax for tax in outputs if _text(tax, "TaxTypeCode") == VAT_TAX_CODE), None)
    header = _child(invoice, "InvoiceHeader")
    series = _text(header, "InvoiceSeriesCode")
    number = _text(header, "InvoiceNumber")
    raw: dict[str, str | None] = {
        "supplier_tax_id": _text(seller, "TaxIdentification", "TaxIdentificationNumber"),
        "supplier_name": _seller_name(seller),
        "invoice_number": None if number is None else (series or "") + number,
        "issue_date": _text(invoice, "InvoiceIssueData", "IssueDate"),
        "currency": _text(invoice, "InvoiceIssueData", "InvoiceCurrencyCode"),
        "base_amount": _text(vat, "TaxableBase", "TotalAmount"),
        "vat_rate": _text(vat, "TaxRate"),
        "vat_amount": _text(vat, "TaxAmount", "TotalAmount"),
        "surcharge_amount": _text(vat, "EquivalenceSurchargeAmount", "TotalAmount"),
        "total": _text(invoice, "InvoiceTotals", "InvoiceTotal"),
    }

    def fail(reason: str) -> dict:
        """Quarantine this invoice with the strings that were read."""
        return _record(file_name, position, reason, dict(raw))

    problem = _tax_problem(outputs, withheld)
    if problem is not None:
        return fail(problem)

    withheld_texts = [_text(tax, "TaxAmount", "TotalAmount") for tax in withheld]
    surcharge_declared = _text(vat, "EquivalenceSurcharge") is not None
    problem = _missing_field(raw, surcharge_declared, withheld_texts)
    if problem is not None:
        return fail(problem)

    installments = _children(_child(invoice, "PaymentDetails"), "Installment")
    due_texts = _present(_text(item, "InstallmentDueDate") for item in installments)
    ibans = _present(_text(item, "AccountToBeCredited", "IBAN") for item in installments)
    try:
        issue_date = _xs_date(raw["issue_date"] or "")
        due_dates = [_xs_date(text) for text in due_texts]
    except ValueError:
        return fail("unparseable_date")
    try:
        amounts = _read_amounts(raw, withheld_texts)
    except InvalidOperation:
        return fail("unparseable_amount")
    if _conflicting(ibans):
        return fail("conflicting_iban")
    if any(value < 0 for value in amounts.values()):
        return fail("negative_amount")
    try:
        money = {name: round_to_cents(amounts[name]) for name in MONEY_FIELDS}
    except InvalidOperation:
        return fail("unparseable_amount")

    if due_dates:
        due_date = max(due_dates)
    else:
        try:
            due_date = issue_date + timedelta(days=DEFAULT_PAYMENT_TERM_DAYS)
        except OverflowError:
            return fail("unparseable_date")

    return Invoice(
        invoice_number=raw["invoice_number"] or "",
        supplier_name=raw["supplier_name"] or "",
        supplier_tax_id=raw["supplier_tax_id"] or "",
        issue_date=issue_date,
        due_date=due_date,
        due_date_is_default=not due_dates,
        vat_rate=_canonical_rate(amounts["vat_rate"]),
        iban=ibans[0] if ibans else None,
        currency=raw["currency"] or "",
        source_file=file_name,
        source_row=position,
        source_ref=f"{file_name}:{position}",
        **money,
    )


def parse_facturae(
    source: Path | str | IO[str] | IO[bytes],
    *,
    source_file: str | None = None,
) -> IngestionResult[Invoice]:
    """Parse a Facturae file; returns (invoices, quarantined), never raises on bad input."""
    content, default_name = _read_source(source)
    file_name = source_file or default_name

    if isinstance(content, str):
        size = len(content.encode("utf-8", "replace"))
    else:
        size = len(content)
    if size > MAX_FACTURAE_BYTES:
        return [], [_record(file_name, None, "file_too_large", "")]
    if not content.strip():
        return [], []

    try:
        root = fromstring(content, forbid_dtd=True)
    except DefusedXmlException:
        return [], [_record(file_name, None, "forbidden_xml_construct", "")]
    except (ParseError, ValueError, RecursionError):
        return [], [_record(file_name, None, "invalid_xml", "")]

    if _local(root.tag) != "Facturae":
        return [], [_record(file_name, None, "not_facturae", "")]
    version = _text(root, "FileHeader", "SchemaVersion")
    if version not in SUPPORTED_VERSIONS:
        return [], [_record(file_name, None, f"unsupported_version:{version or ''}", "")]
    elements = _children(_child(root, "Invoices"), "Invoice")
    if not elements:
        return [], [_record(file_name, None, "no_invoices", "")]

    seller = _child(root, "Parties", "SellerParty")
    invoices: list[Invoice] = []
    quarantined: list[dict] = []
    for position, element in enumerate(elements, start=1):
        result = _build_invoice(element, seller, position, file_name)
        if isinstance(result, Invoice):
            invoices.append(result)
        else:
            quarantined.append(result)
    return invoices, quarantined
