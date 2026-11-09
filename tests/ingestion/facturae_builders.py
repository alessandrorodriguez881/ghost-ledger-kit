"""Builders for Facturae test documents: Example A of the requirements, with overrides.

Every builder returns text. A parameter set to ``None`` leaves that element out, so a test can
build a document that lacks exactly one field. Expected values are written in the tests, not here.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

NAMESPACES = {
    "3.2": "http://www.facturae.gob.es/formato/Versiones/Facturaev3_2.xml",
    "3.2.1": "http://www.facturae.gob.es/formato/Versiones/Facturaev3_2_1.xml",
    "3.2.2": "http://www.facturae.gob.es/formato/Versiones/Facturaev3_2_2.xml",
}
SIGNATURE_NAMESPACE = "http://www.w3.org/2000/09/xmldsig#"
# Mod-97 valid, deliberately wrong Spanish national check digits (Finance Rule 5).
IBAN = "ES8821000418560200051332"
SELLER_NAME = "Suministros Ibéricos Aurora, S.L."
SELLER_TAX_ID = "B00000001"


def element(name: str, value: str | None) -> str:
    """Return ``<name>value</name>``, or an empty string when `value` is None."""
    return "" if value is None else f"<{name}>{value}</{name}>"


def amount_element(name: str, value: str | None) -> str:
    """Return ``<name><TotalAmount>value</TotalAmount></name>``, or '' when `value` is None."""
    return "" if value is None else f"<{name}><TotalAmount>{value}</TotalAmount></{name}>"


def tax_xml(
    *,
    code: str | None = "01",
    rate: str | None = "21.00",
    base: str | None = "400.00",
    amount: str | None = "84.00",
    surcharge_rate: str | None = None,
    surcharge_amount: str | None = None,
) -> str:
    """Return one ``Tax`` element in schema order (tax type, rate, base, amount, surcharge)."""
    parts = (
        element("TaxTypeCode", code),
        element("TaxRate", rate),
        amount_element("TaxableBase", base),
        amount_element("TaxAmount", amount),
        element("EquivalenceSurcharge", surcharge_rate),
        amount_element("EquivalenceSurchargeAmount", surcharge_amount),
    )
    return "<Tax>" + "".join(parts) + "</Tax>"


def withheld_tax_xml(*, amount: str | None = "60.00", rate: str | None = "15.00") -> str:
    """Return one IRPF (code 04) ``Tax`` element for ``TaxesWithheld``."""
    return tax_xml(code="04", rate=rate, base="400.00", amount=amount)


def installment_xml(
    *,
    due: str | None = "2026-11-05",
    iban: str | None = IBAN,
    account_number: str | None = None,
    amount: str | None = "484.00",
) -> str:
    """Return one ``Installment``; its credited account is an IBAN and/or a domestic number."""
    credited = element("IBAN", iban) + element("AccountNumber", account_number)
    account = f"<AccountToBeCredited>{credited}</AccountToBeCredited>" if credited else ""
    parts = (
        element("InstallmentDueDate", due),
        element("InstallmentAmount", amount),
        element("PaymentMeans", "04"),
        account,
    )
    return "<Installment>" + "".join(parts) + "</Installment>"


def seller_xml(
    *,
    tax_id: str | None = SELLER_TAX_ID,
    name: str | None = SELLER_NAME,
    individual: Mapping[str, str] | None = None,
) -> str:
    """Return ``SellerParty``: a legal entity, or an individual when `individual` is given."""
    identification = "<TaxIdentification><PersonTypeCode>J</PersonTypeCode>"
    identification += "<ResidenceTypeCode>R</ResidenceTypeCode>"
    identification += element("TaxIdentificationNumber", tax_id) + "</TaxIdentification>"
    if individual is not None:
        party = "<Individual>" + "".join(element(k, v) for k, v in individual.items())
        party += "</Individual>"
    elif name is not None:
        party = "<LegalEntity>" + element("CorporateName", name) + "</LegalEntity>"
    else:
        party = ""
    return f"<SellerParty>{identification}{party}</SellerParty>"


def invoice_xml(
    *,
    series: str | None = None,
    number: str | None = "F-2026-0310",
    issue_date: str | None = "2026-10-06",
    currency: str | None = "EUR",
    taxes: Sequence[str] | None = None,
    withheld: Sequence[str] | None = None,
    total: str | None = "484.00",
    installments: Sequence[str] | None = None,
) -> str:
    """Return one ``Invoice``; `taxes` and `installments` default to Example A, [] leaves none."""
    tax_list = [tax_xml()] if taxes is None else list(taxes)
    installment_list = [installment_xml()] if installments is None else list(installments)
    header = "<InvoiceHeader>"
    header += element("InvoiceSeriesCode", series) + element("InvoiceNumber", number)
    header += "</InvoiceHeader>"
    issue = "<InvoiceIssueData>"
    issue += element("IssueDate", issue_date) + element("InvoiceCurrencyCode", currency)
    issue += "</InvoiceIssueData>"
    outputs = "<TaxesOutputs>" + "".join(tax_list) + "</TaxesOutputs>"
    withheld_xml = ""
    if withheld is not None:
        withheld_xml = "<TaxesWithheld>" + "".join(withheld) + "</TaxesWithheld>"
    totals = "<InvoiceTotals><TotalGrossAmountBeforeTaxes>400.00</TotalGrossAmountBeforeTaxes>"
    totals += "<TotalTaxOutputs>84.00</TotalTaxOutputs>" + element("InvoiceTotal", total)
    totals += "</InvoiceTotals>"
    payment = ""
    if installment_list:
        payment = "<PaymentDetails>" + "".join(installment_list) + "</PaymentDetails>"
    body = header + issue + outputs + withheld_xml + totals + payment
    return f"<Invoice>{body}</Invoice>"


def facturae_doc(
    *,
    invoices: Sequence[str] | None = None,
    seller: str | None = None,
    version: str | None = "3.2.2",
    prefix: str | None = "fe",
    namespace: bool = True,
    qualified: bool = False,
    signature: str | None = None,
    root: str = "Facturae",
    declaration: bool = True,
    encoding: str = "UTF-8",
) -> str:
    """Return a Facturae document (Example A by default).

    `prefix` names the root's namespace prefix (None = default namespace); `namespace=False` drops
    the namespace entirely and is only meaningful with ``prefix=None``. `qualified` puts the prefix
    on every child element too. `signature` is placed as the last child of the root.
    """
    version_xml = element("SchemaVersion", version)
    invoice_list = [invoice_xml()] if invoices is None else list(invoices)
    parties = "<Parties>" + (seller_xml() if seller is None else seller) + "</Parties>"
    body = f"<FileHeader>{version_xml}</FileHeader>{parties}"
    body += "<Invoices>" + "".join(invoice_list) + "</Invoices>"
    if qualified and prefix is not None:
        body = re.sub(r"<(/?)([A-Za-z_])", rf"<\1{prefix}:\2", body)

    namespace_uri = NAMESPACES.get(version or "3.2.2", NAMESPACES["3.2.2"])
    tag = root if prefix is None else f"{prefix}:{root}"
    if prefix is not None:
        declared = f' xmlns:{prefix}="{namespace_uri}"'
    elif namespace:
        declared = f' xmlns="{namespace_uri}"'
    else:
        declared = ""
    declared += f' xmlns:ds="{SIGNATURE_NAMESPACE}"'
    head = f'<?xml version="1.0" encoding="{encoding}"?>\n' if declaration else ""
    return f"{head}<{tag}{declared}>{body}{signature or ''}</{tag}>\n"


def facturae_bytes(*, encoding: str = "UTF-8", **kwargs: Any) -> bytes:
    """Return `facturae_doc(**kwargs)` encoded with `encoding` (also named in the declaration)."""
    return facturae_doc(encoding=encoding, **kwargs).encode(encoding)
