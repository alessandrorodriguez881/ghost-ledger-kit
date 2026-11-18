"""Tests for the Facturae reader: mapping (RF4) and quarantine reasons (RF5)."""

from __future__ import annotations

import ast
import datetime as dt
import io
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from facturae_builders import (
    IBAN,
    facturae_bytes,
    facturae_doc,
    installment_xml,
    invoice_xml,
    seller_xml,
    tax_xml,
    withheld_tax_xml,
)
from hypothesis import given, settings
from hypothesis import strategies as st

import ledger_kit.ingestion.facturae_reader as facturae_reader
from ledger_kit.ingestion.facturae_reader import SUPPORTED_VERSIONS, parse_facturae
from ledger_kit.models import Invoice

D = Decimal
NAME = "aurora.xml"

# Example A of the requirements, verbatim apart from line breaks between elements.
EXAMPLE_A_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<fe:Facturae xmlns:fe="http://www.facturae.gob.es/formato/Versiones/Facturaev3_2_2.xml">
  <FileHeader><SchemaVersion>3.2.2</SchemaVersion></FileHeader>
  <Parties>
    <SellerParty>
      <TaxIdentification><PersonTypeCode>J</PersonTypeCode>
        <ResidenceTypeCode>R</ResidenceTypeCode>
        <TaxIdentificationNumber>B00000001</TaxIdentificationNumber></TaxIdentification>
      <LegalEntity><CorporateName>Suministros Ibéricos Aurora, S.L.</CorporateName></LegalEntity>
    </SellerParty>
  </Parties>
  <Invoices><Invoice>
    <InvoiceHeader><InvoiceNumber>F-2026-0310</InvoiceNumber></InvoiceHeader>
    <InvoiceIssueData><IssueDate>2026-10-06</IssueDate>
      <InvoiceCurrencyCode>EUR</InvoiceCurrencyCode></InvoiceIssueData>
    <TaxesOutputs><Tax><TaxTypeCode>01</TaxTypeCode><TaxRate>21.00</TaxRate>
      <TaxableBase><TotalAmount>400.00</TotalAmount></TaxableBase>
      <TaxAmount><TotalAmount>84.00</TotalAmount></TaxAmount></Tax></TaxesOutputs>
    <InvoiceTotals><TotalGrossAmountBeforeTaxes>400.00</TotalGrossAmountBeforeTaxes>
      <TotalTaxOutputs>84.00</TotalTaxOutputs><InvoiceTotal>484.00</InvoiceTotal></InvoiceTotals>
    <PaymentDetails><Installment><InstallmentDueDate>2026-11-05</InstallmentDueDate>
      <InstallmentAmount>484.00</InstallmentAmount><PaymentMeans>04</PaymentMeans>
      <AccountToBeCredited><IBAN>ES8821000418560200051332</IBAN></AccountToBeCredited>
    </Installment></PaymentDetails>
  </Invoice></Invoices>
</fe:Facturae>
"""

EXAMPLE_A = {
    "invoice_number": "F-2026-0310",
    "supplier_name": "Suministros Ibéricos Aurora, S.L.",
    "supplier_tax_id": "B00000001",
    "issue_date": dt.date(2026, 10, 6),
    "due_date": dt.date(2026, 11, 5),
    "due_date_is_default": False,
    "base_amount": D("400.00"),
    "vat_rate": D("21"),
    "vat_amount": D("84.00"),
    "surcharge_amount": D("0"),
    "withholding_amount": D("0"),
    "total": D("484.00"),
    "iban": "ES8821000418560200051332",
    "currency": "EUR",
    "source_file": "aurora.xml",
    "source_row": 1,
    "source_ref": "aurora.xml:1",
    "source_line": None,  # an XML invoice has a position, not a line
}


def parse(data: str | bytes, name: str = NAME) -> tuple[list[Invoice], list[dict]]:
    """Parse text (UTF-8) or bytes the way an uploaded file would arrive."""
    raw = data.encode("utf-8") if isinstance(data, str) else data
    return parse_facturae(io.BytesIO(raw), source_file=name)


def fields(invoice: Invoice) -> dict:
    """Return the invoice's fields as a plain dict."""
    return invoice.model_dump()


def build(*, seller: str | None = None, **invoice_kwargs: Any) -> str:
    """Return a one-invoice document whose invoice and seller are overridden."""
    return facturae_doc(seller=seller, invoices=[invoice_xml(**invoice_kwargs)])


def read_one(**invoice_kwargs: Any) -> Invoice:
    """Read a one-invoice document that must give exactly one invoice and no quarantine."""
    invoices, quarantine = parse(build(**invoice_kwargs))
    assert quarantine == []
    assert len(invoices) == 1
    return invoices[0]


def quarantine_of(document: str | bytes) -> dict:
    """Read a document that must give no invoice and exactly one quarantine record."""
    invoices, quarantine = parse(document)
    assert invoices == []
    assert len(quarantine) == 1
    return quarantine[0]


# --- RF4: mapping ---------------------------------------------------------------------------


def test_example_a_text_gives_the_expected_invoice() -> None:
    """The document of the requirements gives the one expected Invoice and no quarantine."""
    invoices, quarantine = parse(EXAMPLE_A_XML)

    assert quarantine == []
    assert [fields(invoice) for invoice in invoices] == [EXAMPLE_A]


def test_builder_default_document_equals_example_a() -> None:
    """The test builder's default document reads the same as the literal Example A."""
    built, _ = parse(facturae_doc())
    literal, _ = parse(EXAMPLE_A_XML)

    assert [fields(i) for i in built] == [fields(i) for i in literal]


@pytest.mark.parametrize("version", SUPPORTED_VERSIONS)
def test_every_supported_version_reads_the_same(version: str) -> None:
    """Versions 3.2, 3.2.1 and 3.2.2 give the same invoice."""
    invoices, quarantine = parse(facturae_doc(version=version))

    assert quarantine == []
    assert [fields(i) for i in invoices] == [EXAMPLE_A]


def test_the_three_supported_versions_are_pinned() -> None:
    """Exactly 3.2, 3.2.1 and 3.2.2 are supported."""
    assert SUPPORTED_VERSIONS == ("3.2", "3.2.1", "3.2.2")


@pytest.mark.parametrize(
    "layout",
    [
        pytest.param({"prefix": "fe"}, id="unqualified-children"),
        pytest.param({"prefix": "fe", "qualified": True}, id="qualified-children"),
        pytest.param({"prefix": "ns3", "qualified": True}, id="other-prefix"),
        pytest.param({"prefix": None}, id="default-namespace"),
        pytest.param({"prefix": None, "namespace": False}, id="no-namespace"),
    ],
)
def test_prefixes_and_qualified_children_read_the_same(layout: dict) -> None:
    """Any prefix, qualified or unqualified children, or no namespace, read the same."""
    invoices, quarantine = parse(facturae_doc(**layout))

    assert quarantine == []
    assert [fields(i) for i in invoices] == [EXAMPLE_A]


def test_a_utf8_byte_order_mark_is_accepted() -> None:
    """A leading UTF-8 BOM does not stop the file from being read."""
    invoices, quarantine = parse(b"\xef\xbb\xbf" + facturae_bytes())

    assert quarantine == []
    assert [fields(i) for i in invoices] == [EXAMPLE_A]


def test_the_declared_encoding_is_honoured() -> None:
    """A file declared ISO-8859-1 and written in it keeps its accented name."""
    seller = seller_xml(name="Taller Niño, S.L.")
    document = facturae_bytes(encoding="ISO-8859-1", seller=seller)

    invoices, quarantine = parse(document)

    assert quarantine == []
    assert invoices[0].supplier_name == "Taller Niño, S.L."


def test_text_and_path_sources_are_read_like_bytes(tmp_path: Path) -> None:
    """A text stream, a path and a string path give the same invoice."""
    path = tmp_path / NAME
    path.write_bytes(EXAMPLE_A_XML.encode("utf-8"))

    from_text, _ = parse_facturae(io.StringIO(EXAMPLE_A_XML), source_file=NAME)
    from_path, _ = parse_facturae(path)
    from_name, _ = parse_facturae(str(path))

    assert [fields(i) for i in from_text] == [EXAMPLE_A]
    assert [fields(i) for i in from_path] == [EXAMPLE_A]
    assert [fields(i) for i in from_name] == [EXAMPLE_A]


@pytest.mark.parametrize(
    ("series", "number", "expected"),
    [
        (None, "F-2026-0310", "F-2026-0310"),
        ("A", "0042", "A0042"),
        (" A ", " 0042 ", "A0042"),
        ("", "0042", "0042"),
    ],
)
def test_invoice_number_is_series_then_number(
    series: str | None, number: str, expected: str
) -> None:
    """Series and number are joined with no separator; blanks are trimmed."""
    assert read_one(series=series, number=number).invoice_number == expected


@pytest.mark.parametrize(
    ("individual", "expected"),
    [
        (
            {"Name": "Ana", "FirstSurname": "García (Asesoría Fiscal)"},
            "Ana García (Asesoría Fiscal)",
        ),
        (
            {"Name": "Luigi", "FirstSurname": "Rossi", "SecondSurname": "Bianchi"},
            "Luigi Rossi Bianchi",
        ),
        ({"Name": "Sophie", "FirstSurname": " ", "SecondSurname": "Dupont"}, "Sophie Dupont"),
    ],
)
def test_individual_names_join_the_present_parts(individual: dict, expected: str) -> None:
    """An Individual's name parts are joined by one space; blank parts are skipped."""
    seller = seller_xml(name=None, individual=individual)

    assert read_one(seller=seller).supplier_name == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("400.004", "400.00"),
        ("400.005", "400.01"),
        ("0.125", "0.13"),
        ("1.0E2", "100.00"),
        ("84", "84.00"),
        ("0.1", "0.10"),
        ("0.12345678", "0.12"),
    ],
)
def test_amounts_are_rounded_half_up_to_cents(text: str, expected: str) -> None:
    """The base amount is rounded half-up to two places at ingestion."""
    assert str(read_one(taxes=[tax_xml(base=text)]).base_amount) == expected


def test_all_five_money_fields_are_rounded_and_the_rate_is_not() -> None:
    """Base, VAT, surcharge, withholding and total are rounded; the rate stays exact."""
    taxes = [
        tax_xml(
            rate="5.205",
            base="0.125",
            amount="0.125",
            surcharge_rate="5.2",
            surcharge_amount="0.125",
        )
    ]
    withheld = [withheld_tax_xml(amount="0.125")]
    invoice = read_one(taxes=taxes, withheld=withheld, total="0.125")

    assert str(invoice.base_amount) == "0.13"
    assert str(invoice.vat_amount) == "0.13"
    assert str(invoice.surcharge_amount) == "0.13"
    assert str(invoice.withholding_amount) == "0.13"
    assert str(invoice.total) == "0.13"
    assert str(invoice.vat_rate) == "5.205"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("21.00", "21"),
        ("21.00000000", "21"),
        ("5.20", "5.2"),
        ("0.00", "0"),
        ("10", "10"),
        ("1E+1", "10"),
    ],
)
def test_the_vat_rate_is_written_in_canonical_form(text: str, expected: str) -> None:
    """The rate has no trailing zeros and no exponent, like the CSV reader's."""
    assert str(read_one(taxes=[tax_xml(rate=text)]).vat_rate) == expected


def test_no_amount_goes_through_float() -> None:
    """0.1 + 0.2 style text stays exact, every amount is a Decimal."""
    taxes = [tax_xml(rate="0.1", base="0.1", amount="0.2")]
    invoice = read_one(taxes=taxes, total="0.3")

    assert invoice.base_amount + invoice.vat_amount == invoice.total == D("0.30")
    for name in ("base_amount", "vat_rate", "vat_amount", "surcharge_amount"):
        assert isinstance(getattr(invoice, name), Decimal)
    assert isinstance(invoice.withholding_amount, Decimal)
    assert isinstance(invoice.total, Decimal)
    assert invoice.vat_rate == D("0.1")


def test_the_reader_source_never_calls_float() -> None:
    """The module does not mention `float` as a name anywhere."""
    tree = ast.parse(Path(facturae_reader.__file__).read_text(encoding="utf-8"))

    assert [n for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id == "float"] == []


def test_one_installment_gives_its_due_date_and_iban() -> None:
    """A single installment sets the due date and the IBAN; the date is not a default."""
    invoice = read_one(installments=[installment_xml(due="2026-11-05", iban=IBAN)])

    assert invoice.due_date == dt.date(2026, 11, 5)
    assert invoice.due_date_is_default is False
    assert invoice.iban == IBAN


def test_without_payment_details_the_due_date_is_the_default_term() -> None:
    """No installment: issue date plus 30 days, flagged as default, no IBAN."""
    invoice = read_one(installments=[])

    assert invoice.due_date == dt.date(2026, 11, 5)
    assert invoice.due_date_is_default is True
    assert invoice.iban is None


@pytest.mark.parametrize("order", [("2026-11-05", "2026-12-05"), ("2026-12-05", "2026-11-05")])
def test_several_installments_use_the_latest_due_date(order: tuple[str, str]) -> None:
    """The latest InstallmentDueDate wins, whatever the order."""
    installments = [installment_xml(due=due) for due in order]

    invoice = read_one(installments=installments)

    assert invoice.due_date == dt.date(2026, 12, 5)
    assert invoice.due_date_is_default is False


def test_installments_without_a_due_date_keep_the_default_but_read_the_iban() -> None:
    """An installment with no due date leaves the default term; its IBAN is still read."""
    invoice = read_one(installments=[installment_xml(due=None)])

    assert invoice.due_date == dt.date(2026, 11, 5)
    assert invoice.due_date_is_default is True
    assert invoice.iban == IBAN


@pytest.mark.parametrize("suffix", ["Z", "+01:00", "-05:00"])
def test_a_zone_suffix_on_dates_is_ignored(suffix: str) -> None:
    """`xs:date` zone suffixes are dropped from the issue and the due date."""
    invoice = read_one(
        issue_date=f"2026-10-06{suffix}",
        installments=[installment_xml(due=f"2026-11-05{suffix}")],
    )

    assert invoice.issue_date == dt.date(2026, 10, 6)
    assert invoice.due_date == dt.date(2026, 11, 5)


def test_the_iban_is_kept_verbatim() -> None:
    """The IBAN text is not normalised: spaces and case stay as written."""
    iban = "es88 2100 0418 5602 0005 1332"

    assert read_one(installments=[installment_xml(iban=iban)]).iban == iban


def test_the_first_non_blank_iban_is_used() -> None:
    """A blank IBAN is skipped; the first non-blank one is taken."""
    installments = [
        installment_xml(due="2026-11-05", iban="   "),
        installment_xml(due="2026-12-05", iban=IBAN),
    ]

    assert read_one(installments=installments).iban == IBAN


def test_the_same_iban_written_differently_is_not_a_conflict() -> None:
    """Spaces and case do not make two installments' IBANs conflict; the first is kept."""
    spaced = "es88 2100 0418 5602 0005 1332"
    installments = [installment_xml(iban=spaced), installment_xml(due="2026-12-05", iban=IBAN)]

    assert read_one(installments=installments).iban == spaced


def test_an_account_number_is_not_an_iban() -> None:
    """A domestic AccountNumber is ignored; no IBAN is invented from it."""
    installment = installment_xml(iban=None, account_number="21000418450200051332")

    invoice = read_one(installments=[installment])

    assert invoice.iban is None
    assert invoice.due_date == dt.date(2026, 11, 5)
    assert invoice.due_date_is_default is False


def test_a_surcharge_is_read_and_defaults_to_zero() -> None:
    """The equivalence surcharge amount is read when declared and is zero otherwise."""
    taxes = [tax_xml(surcharge_rate="5.20", surcharge_amount="20.80")]

    assert read_one(taxes=taxes).surcharge_amount == D("20.80")
    assert read_one().surcharge_amount == D("0")


def test_withholdings_of_type_04_are_summed() -> None:
    """Two IRPF taxes are added; none gives zero."""
    withheld = [withheld_tax_xml(amount="60.00"), withheld_tax_xml(amount="15.50")]

    assert read_one(withheld=withheld).withholding_amount == D("75.50")
    assert read_one(withheld=[withheld_tax_xml(amount="60.00")]).withholding_amount == D("60.00")
    assert read_one(withheld=[]).withholding_amount == D("0")


def test_several_invoices_get_positions_as_source_rows() -> None:
    """The n-th Invoice element is `file:n`, with source_row n, in document order."""
    numbers = ["A-1", "A-2", "A-3"]
    document = facturae_doc(invoices=[invoice_xml(number=n) for n in numbers])

    invoices, quarantine = parse(document)

    assert quarantine == []
    assert [i.invoice_number for i in invoices] == numbers
    assert [i.source_ref for i in invoices] == [f"{NAME}:1", f"{NAME}:2", f"{NAME}:3"]
    assert [i.source_row for i in invoices] == [1, 2, 3]


def test_the_file_name_is_taken_from_the_path_by_default(tmp_path: Path) -> None:
    """Without `source_file`, the file name of the path names the rows."""
    path = tmp_path / "supplier-9.xml"
    path.write_bytes(facturae_bytes())

    invoices, _ = parse_facturae(path)

    assert invoices[0].source_ref == "supplier-9.xml:1"


def test_a_signature_child_changes_nothing() -> None:
    """A ds:Signature under the root, even one that imitates invoice data, is never read."""
    decoy = (
        "<ds:Signature><ds:SignedInfo><ds:Reference URI=''/></ds:SignedInfo>"
        "<ds:SignatureValue>AAAA</ds:SignatureValue><ds:Object>"
        "<Invoices><Invoice><InvoiceTotals><InvoiceTotal>999.00</InvoiceTotal></InvoiceTotals>"
        "</Invoice></Invoices></ds:Object></ds:Signature>"
    )

    signed, quarantine = parse(facturae_doc(signature=decoy))

    assert quarantine == []
    assert [fields(i) for i in signed] == [EXAMPLE_A]


# --- RF5: invoice-level quarantine ----------------------------------------------------------

MISSING_FIELDS = [
    pytest.param("supplier_tax_id", {"seller": seller_xml(tax_id=None)}, id="supplier_tax_id"),
    pytest.param("supplier_name", {"seller": seller_xml(name=None)}, id="supplier_name"),
    pytest.param("invoice_number", {"number": None}, id="invoice_number"),
    pytest.param("issue_date", {"issue_date": None}, id="issue_date"),
    pytest.param("currency", {"currency": None}, id="currency"),
    pytest.param("base_amount", {"taxes": [tax_xml(base=None)]}, id="base_amount"),
    pytest.param("vat_rate", {"taxes": [tax_xml(rate=None)]}, id="vat_rate"),
    pytest.param("vat_amount", {"taxes": [tax_xml(amount=None)]}, id="vat_amount"),
    pytest.param(
        "surcharge_amount",
        {"taxes": [tax_xml(surcharge_rate="5.20", surcharge_amount=None)]},
        id="surcharge_amount",
    ),
    pytest.param("total", {"total": None}, id="total"),
    pytest.param(
        "withholding_amount",
        {"withheld": [withheld_tax_xml(amount=None)]},
        id="withholding_amount",
    ),
]


@pytest.mark.parametrize(("name", "overrides"), MISSING_FIELDS)
def test_each_missing_required_field_is_quarantined(name: str, overrides: dict) -> None:
    """A missing required field quarantines that invoice with `missing_field:<name>`."""
    record = quarantine_of(build(**overrides))

    assert record["source_file"] == NAME
    assert record["source_row"] == 1
    assert record["reason"] == f"missing_field:{name}"
    assert isinstance(record["raw"], dict)


def test_a_blank_text_counts_as_missing() -> None:
    """Whitespace-only text is a missing field, like an absent element."""
    assert quarantine_of(build(number="   "))["reason"] == "missing_field:invoice_number"


def test_a_number_made_only_of_a_series_is_missing() -> None:
    """A series with no number does not make an invoice number."""
    record = quarantine_of(build(series="A", number=None))

    assert record["reason"] == "missing_field:invoice_number"


def test_the_raw_of_a_record_holds_the_strings_that_were_read() -> None:
    """The quarantine record's raw names what was read, with None for what was absent."""
    raw = quarantine_of(build(total=None))["raw"]

    assert raw["invoice_number"] == "F-2026-0310"
    assert raw["supplier_name"] == "Suministros Ibéricos Aurora, S.L."
    assert raw["base_amount"] == "400.00"
    assert raw["total"] is None


def test_a_missing_tax_amount_is_not_computed() -> None:
    """TaxAmount absent: the reader quarantines instead of deriving 21% of the base."""
    record = quarantine_of(build(taxes=[tax_xml(amount=None)]))

    assert record["reason"] == "missing_field:vat_amount"


def test_no_vat_tax_is_quarantined() -> None:
    """An invoice with no TaxesOutputs entry is `missing_vat_tax`."""
    assert quarantine_of(build(taxes=[]))["reason"] == "missing_vat_tax"


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        pytest.param({"taxes": [tax_xml(code="03")]}, "unsupported_tax_type:03", id="igic"),
        pytest.param(
            {"taxes": [tax_xml(), tax_xml(code="03")]},
            "unsupported_tax_type:03",
            id="vat-and-igic",
        ),
        pytest.param(
            {"withheld": [tax_xml(code="01")]}, "unsupported_tax_type:01", id="withheld-not-04"
        ),
    ],
)
def test_unsupported_tax_types_are_quarantined(overrides: dict, reason: str) -> None:
    """A tax type other than 01 (outputs) or 04 (withheld) is never dropped silently."""
    assert quarantine_of(build(**overrides))["reason"] == reason


def test_two_vat_taxes_quarantine_only_that_invoice() -> None:
    """The third invoice has two IVA rates: it alone is `multiple_vat_rates`, at row 3."""
    multi = [tax_xml(rate="21.00", base="800.00", amount="168.00"), tax_xml(rate="10.00")]
    document = facturae_doc(
        invoices=[invoice_xml(number="A-1"), invoice_xml(number="A-2"), invoice_xml(taxes=multi)]
    )

    invoices, quarantine = parse(document)

    assert [i.source_ref for i in invoices] == [f"{NAME}:1", f"{NAME}:2"]
    assert len(quarantine) == 1
    assert quarantine[0]["source_row"] == 3
    assert quarantine[0]["reason"] == "multiple_vat_rates"


@pytest.mark.parametrize(
    "text",
    ["06/10/2026", "2026-13-45", "2026-02-30", "2026-10-06T10:00:00", "today"],
)
def test_an_unparseable_issue_date_is_quarantined(text: str) -> None:
    """Anything that is not an `xs:date` is `unparseable_date`."""
    assert quarantine_of(build(issue_date=text))["reason"] == "unparseable_date"


def test_an_unparseable_due_date_is_quarantined() -> None:
    """An installment due date that is not an `xs:date` quarantines the invoice."""
    record = quarantine_of(build(installments=[installment_xml(due="05/11/2026")]))

    assert record["reason"] == "unparseable_date"


@pytest.mark.parametrize(
    "text",
    ["12,5", "NaN", "INF", "-Infinity", "abc", "1_000", "0x10", "1E999"],
)
def test_unparseable_amounts_are_quarantined(text: str) -> None:
    """Locale commas, non-finite values, junk and absurd exponents are `unparseable_amount`."""
    assert quarantine_of(build(taxes=[tax_xml(base=text)]))["reason"] == "unparseable_amount"


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"taxes": [tax_xml(rate="abc")]}, id="rate"),
        pytest.param({"taxes": [tax_xml(amount="abc")]}, id="vat_amount"),
        pytest.param(
            {"taxes": [tax_xml(surcharge_rate="5.2", surcharge_amount="abc")]}, id="surcharge"
        ),
        pytest.param({"withheld": [withheld_tax_xml(amount="abc")]}, id="withholding"),
        pytest.param({"total": "NaN"}, id="total"),
    ],
)
def test_every_amount_field_can_be_unparseable(overrides: dict) -> None:
    """Each of the six amounts reports `unparseable_amount` when it is not a number."""
    assert quarantine_of(build(**overrides))["reason"] == "unparseable_amount"


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"taxes": [tax_xml(base="-1.00")]}, id="base"),
        pytest.param({"taxes": [tax_xml(rate="-21.00")]}, id="rate"),
        pytest.param({"taxes": [tax_xml(amount="-1.00")]}, id="vat_amount"),
        pytest.param(
            {"taxes": [tax_xml(surcharge_rate="5.2", surcharge_amount="-1.00")]}, id="surcharge"
        ),
        pytest.param({"withheld": [withheld_tax_xml(amount="-1.00")]}, id="withholding"),
        pytest.param({"total": "-484.00"}, id="total"),
        pytest.param({"taxes": [tax_xml(base="-0.004")]}, id="negative-before-rounding"),
    ],
)
def test_a_negative_amount_is_quarantined(overrides: dict) -> None:
    """Any of the six amounts below zero, as read, is `negative_amount`."""
    assert quarantine_of(build(**overrides))["reason"] == "negative_amount"


def test_two_different_ibans_are_a_conflict() -> None:
    """Two installments naming different IBANs quarantine the invoice."""
    installments = [
        installment_xml(due="2026-11-05", iban=IBAN),
        installment_xml(due="2026-12-05", iban="ES0000000000000000000000"),
    ]

    assert quarantine_of(build(installments=installments))["reason"] == "conflicting_iban"


def test_one_bad_invoice_does_not_stop_the_others() -> None:
    """Three invoices, the middle one without a total: rows 1 and 3 are read."""
    document = facturae_doc(
        invoices=[
            invoice_xml(number="A-1"),
            invoice_xml(number="A-2", total=None),
            invoice_xml(number="A-3"),
        ]
    )

    invoices, quarantine = parse(document)

    assert [i.source_ref for i in invoices] == [f"{NAME}:1", f"{NAME}:3"]
    assert len(quarantine) == 1
    assert quarantine[0]["source_row"] == 2
    assert quarantine[0]["reason"] == "missing_field:total"
    assert quarantine[0]["raw"]["invoice_number"] == "A-2"


# --- RF5: file-level quarantine -------------------------------------------------------------

FILE_LEVEL = [
    pytest.param(b"<Facturae><unclosed>", "invalid_xml", id="unclosed"),
    pytest.param(b"not xml at all", "invalid_xml", id="not-xml"),
    pytest.param(b"<Order/>", "not_facturae", id="other-root"),
    pytest.param(
        b"<Facturae><FileHeader><SchemaVersion>3.1</SchemaVersion></FileHeader></Facturae>",
        "unsupported_version:3.1",
        id="version-3.1",
    ),
    pytest.param(
        b"<Facturae><FileHeader/></Facturae>", "unsupported_version:", id="no-version-text"
    ),
    pytest.param(b"<Facturae/>", "unsupported_version:", id="no-header"),
    pytest.param(facturae_bytes(invoices=[]), "no_invoices", id="empty-invoices"),
    pytest.param(
        b"<Facturae><FileHeader><SchemaVersion>3.2.2</SchemaVersion></FileHeader></Facturae>",
        "no_invoices",
        id="no-invoices-element",
    ),
    pytest.param(
        b'<?xml version="1.0" encoding="UTF-8"?>\xff<Facturae/>', "invalid_xml", id="bad-bytes"
    ),
]


@pytest.mark.parametrize(("document", "reason"), FILE_LEVEL)
def test_file_level_reasons(document: bytes, reason: str) -> None:
    """Each whole-file problem gives no invoice and one record with `source_row` None."""
    invoices, quarantine = parse(document)

    assert invoices == []
    assert quarantine == [
        {
            "source_file": NAME,
            "source_row": None,
            "source_line": None,
            "reason": reason,
            "raw": "",
        }
    ]


def test_a_truncated_document_is_invalid_xml() -> None:
    """A real document cut in the middle is `invalid_xml`, not a partial read."""
    document = facturae_bytes()

    record = quarantine_of(document[: len(document) // 2])

    assert record["reason"] == "invalid_xml"


@pytest.mark.parametrize("document", [b"", b"   \r\n\t ", "", " \n"])
def test_an_empty_file_gives_nothing(document: str | bytes) -> None:
    """An empty or blank file is `([], [])`, like the other readers."""
    assert parse(document) == ([], [])


# --- Tier 3: properties ---------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(data=st.binary())
def test_arbitrary_bytes_never_raise(data: bytes) -> None:
    """Whatever the bytes, the reader returns two lists and does not raise."""
    invoices, quarantine = parse_facturae(io.BytesIO(data), source_file=NAME)

    assert isinstance(invoices, list)
    assert isinstance(quarantine, list)


@settings(max_examples=200, deadline=None)
@given(cut=st.integers(min_value=0, max_value=len(facturae_bytes())))
def test_a_truncated_document_never_raises_nor_invents_an_invoice(cut: int) -> None:
    """Any prefix of a valid file returns lists, and no invoice unless the root is closed."""
    document = facturae_bytes()

    invoices, quarantine = parse(document[:cut])

    assert isinstance(quarantine, list)
    if cut < len(document.rstrip()):
        assert invoices == []


@settings(max_examples=200, deadline=None)
@given(blank=st.text(alphabet=" \t\r\n", max_size=20))
def test_blank_input_gives_nothing(blank: str) -> None:
    """Empty and whitespace-only files give `([], [])`."""
    assert parse(blank) == ([], [])


@settings(max_examples=200, deadline=None)
@given(
    count=st.integers(min_value=1, max_value=6),
    bad=st.sets(st.integers(min_value=1, max_value=6)),
)
def test_every_invoice_is_returned_or_quarantined_exactly_once(count: int, bad: set[int]) -> None:
    """No invention: refs are `file:n` for n in 1..count, and each n appears exactly once."""
    positions = set(range(1, count + 1))
    invoices_xml = [
        invoice_xml(number=f"F-{n}", total=None if n in bad else "484.00")
        for n in sorted(positions)
    ]

    returned, quarantined = parse(facturae_doc(invoices=invoices_xml))

    assert {i.source_ref for i in returned} == {f"{NAME}:{n}" for n in positions - bad}
    assert {r["source_row"] for r in quarantined} == positions & bad
    assert len(returned) + len(quarantined) == count
    assert all(i.invoice_number == f"F-{i.source_row}" for i in returned)
    assert all(i.base_amount >= 0 and i.vat_amount >= 0 and i.total >= 0 for i in returned)


@settings(max_examples=200, deadline=None)
@given(count=st.integers(min_value=1, max_value=4))
def test_parsing_twice_gives_the_same_result(count: int) -> None:
    """Idempotency: the same bytes give equal invoices and equal quarantine."""
    document = facturae_bytes(invoices=[invoice_xml(number=f"F-{n}") for n in range(count)])

    first = parse(document)
    second = parse(document)

    assert [fields(i) for i in first[0]] == [fields(i) for i in second[0]]
    assert first[1] == second[1]
