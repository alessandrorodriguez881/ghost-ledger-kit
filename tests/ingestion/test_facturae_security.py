"""Security tests for the Facturae reader: hostile XML is quarantined, never expanded or fetched.

Each hostile document returns ``([], [record])`` at once. The tests patch nothing: if the reader
expanded an entity or fetched a URL, the billion-laughs file would hang and the others would
reach out; they only pass because the parser refuses the construct before using it.
"""

from __future__ import annotations

import ast
import io
from pathlib import Path

import pytest
from facturae_builders import facturae_bytes, facturae_doc

import ledger_kit.ingestion.facturae_reader as facturae_reader
from ledger_kit.ingestion.facturae_reader import MAX_FACTURAE_BYTES, parse_facturae
from ledger_kit.models import Invoice

NAME = "hostile.xml"
READER_SOURCE = Path(facturae_reader.__file__)


def billion_laughs(levels: int = 9, fanout: int = 10) -> bytes:
    """Return the classic exponential-entity document: `levels` nested entities of `fanout`."""
    entities = ['<!ENTITY lol0 "lol">']
    for level in range(1, levels + 1):
        references = f"&lol{level - 1};" * fanout
        entities.append(f'<!ENTITY lol{level} "{references}">')
    subset = "".join(entities)
    document = f'<?xml version="1.0"?><!DOCTYPE lolz [{subset}]><lolz>&lol{levels};</lolz>'
    return document.encode("utf-8")


def with_doctype(doctype: str) -> bytes:
    """Return Example A with `doctype` between the declaration and the root element."""
    body = facturae_doc(declaration=False)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{doctype}\n{body}'.encode()


def parse(data: bytes) -> tuple[list[Invoice], list[dict]]:
    """Parse bytes the way an uploaded file would arrive."""
    return parse_facturae(io.BytesIO(data), source_file=NAME)


def padded_to(size: int) -> bytes:
    """Return a valid Facturae document followed by blanks, exactly `size` bytes long."""
    document = facturae_bytes()
    return document + b" " * (size - len(document))


FORBIDDEN = [
    pytest.param(billion_laughs(), id="billion-laughs"),
    pytest.param(
        b'<?xml version="1.0"?><!DOCTYPE x SYSTEM "http://127.0.0.1/x.dtd"><Facturae/>',
        id="external-dtd",
    ),
    pytest.param(
        b'<!DOCTYPE x PUBLIC "-//X//EN" "http://127.0.0.1/x.dtd"><Facturae/>',
        id="external-dtd-public",
    ),
    pytest.param(
        b'<!DOCTYPE x [<!ENTITY a "b">]><Facturae>&a;</Facturae>',
        id="entity-only-dtd",
    ),
    pytest.param(
        b'<!DOCTYPE x [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><Facturae>&xxe;</Facturae>',
        id="file-url-entity",
    ),
    pytest.param(
        b'<!DOCTYPE x [<!ENTITY xxe SYSTEM "file:///C:/win.ini">]><Facturae>&xxe;</Facturae>',
        id="file-url-entity-windows",
    ),
    pytest.param(
        b'<!DOCTYPE x [<!ENTITY % p SYSTEM "http://127.0.0.1/p.dtd"> %p;]><Facturae/>',
        id="external-parameter-entity",
    ),
    pytest.param(
        with_doctype('<!DOCTYPE fe:Facturae SYSTEM "http://127.0.0.1/x.dtd">'),
        id="valid-invoice-with-external-dtd",
    ),
    pytest.param(
        with_doctype('<!DOCTYPE fe:Facturae [<!ENTITY a "b">]>'),
        id="valid-invoice-with-internal-dtd",
    ),
]


@pytest.mark.parametrize("document", FORBIDDEN)
def test_forbidden_constructs_are_quarantined(document: bytes) -> None:
    """A DTD, an entity or an external reference gives one `forbidden_xml_construct` record."""
    invoices, quarantine = parse(document)

    assert invoices == []
    assert quarantine == [
        {
            "source_file": NAME,
            "source_row": None,
            "source_line": None,
            "reason": "forbidden_xml_construct",
            "raw": "",
        }
    ]


def test_the_billion_laughs_document_is_refused_as_text_too() -> None:
    """The same payload as a text stream is refused the same way, without expansion."""
    text = billion_laughs().decode("utf-8")

    invoices, quarantine = parse_facturae(io.StringIO(text), source_file=NAME)

    assert invoices == []
    assert [record["reason"] for record in quarantine] == ["forbidden_xml_construct"]


def test_the_billion_laughs_record_does_not_carry_the_payload() -> None:
    """The quarantine record stays tiny: nothing of the document is echoed back."""
    _, quarantine = parse(billion_laughs())

    assert len(repr(quarantine)) < 500


MALFORMED = [
    pytest.param(b"<Facturae><unclosed>", id="unclosed"),
    pytest.param(b"<a><b></a></b>", id="mismatched-tags"),
    pytest.param(b"not xml at all", id="plain-text"),
    pytest.param(b'<?xml version="1.0" encoding="UTF-8"?>\xff<Facturae/>', id="invalid-utf8"),
    pytest.param(b"\x00\x01\x02\x03", id="binary-junk"),
    pytest.param(b"<" * 50, id="only-brackets"),
]


@pytest.mark.parametrize("document", MALFORMED)
def test_malformed_documents_are_invalid_xml(document: bytes) -> None:
    """Anything that is not well-formed XML is one `invalid_xml` record."""
    invoices, quarantine = parse(document)

    assert invoices == []
    assert [record["reason"] for record in quarantine] == ["invalid_xml"]
    assert quarantine[0]["source_row"] is None


def test_a_declaration_with_an_unknown_encoding_is_invalid_xml() -> None:
    """An encoding name Python does not know (Hypothesis found `ATF-8`) is `invalid_xml`."""
    document = facturae_doc(declaration=False)
    data = f'<?xml version="1.0" encoding="ATF-8"?>\n{document}'.encode()

    invoices, quarantine = parse(data)

    assert invoices == []
    assert quarantine == [
        {
            "source_file": NAME,
            "source_row": None,
            "source_line": None,
            "reason": "invalid_xml",
            "raw": "",
        }
    ]


def test_deeply_nested_elements_do_not_raise() -> None:
    """Thousands of nested elements give a result, never an exception."""
    depth = 5_000
    document = b"<Facturae>" + b"<a>" * depth + b"</a>" * depth + b"</Facturae>"

    invoices, quarantine = parse(document)

    assert invoices == []
    assert len(quarantine) == 1


def test_a_document_over_the_size_cap_is_refused_before_parsing() -> None:
    """One byte over MAX_FACTURAE_BYTES is `file_too_large`, even if it is a valid document."""
    invoices, quarantine = parse(padded_to(MAX_FACTURAE_BYTES + 1))

    assert invoices == []
    assert quarantine == [
        {
            "source_file": NAME,
            "source_row": None,
            "source_line": None,
            "reason": "file_too_large",
            "raw": "",
        }
    ]


def test_a_document_exactly_at_the_size_cap_is_read() -> None:
    """MAX_FACTURAE_BYTES itself is allowed; only larger documents are refused."""
    invoices, quarantine = parse(padded_to(MAX_FACTURAE_BYTES))

    assert quarantine == []
    assert len(invoices) == 1


def test_the_size_cap_is_ten_mebibytes() -> None:
    """The cap is the 10 MiB of the design."""
    assert MAX_FACTURAE_BYTES == 10 * 1024 * 1024


def test_an_oversize_text_source_is_refused_too() -> None:
    """The cap counts the UTF-8 size of a text source."""
    text = "<" + "x" * MAX_FACTURAE_BYTES

    _, quarantine = parse_facturae(io.StringIO(text), source_file=NAME)

    assert [record["reason"] for record in quarantine] == ["file_too_large"]


def _imported_modules(source: str) -> list[str]:
    """Return every module name imported anywhere in `source`."""
    modules: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.append(node.module)
    return modules


def test_the_reader_imports_xml_only_from_defusedxml() -> None:
    """No `xml`, `lxml` or other XML parser is imported; the XML imports are defusedxml's."""
    modules = _imported_modules(READER_SOURCE.read_text(encoding="utf-8"))

    xml_modules = [m for m in modules if m.split(".")[0] in {"xml", "lxml", "defusedxml"}]
    assert xml_modules
    assert {m.split(".")[0] for m in xml_modules} == {"defusedxml"}
    assert "defusedxml.ElementTree" in modules


def test_the_reader_forbids_dtds_explicitly() -> None:
    """`forbid_dtd=True` is passed (the library default is False); nothing relaxes the rest."""
    source = READER_SOURCE.read_text(encoding="utf-8")

    assert "forbid_dtd=True" in source
    assert "forbid_entities=False" not in source
    assert "forbid_external=False" not in source
