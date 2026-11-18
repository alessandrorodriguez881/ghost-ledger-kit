"""Tests for the Norma 43 reader: records, mapping and row/header quarantine (RF2, RF3)."""

from __future__ import annotations

import datetime as dt
import io
from decimal import Decimal

import pytest
from n43_builders import (
    complement_23,
    currency_24,
    fixture_a,
    fixture_a_lines,
    header_11,
    join_lines,
    movement_22,
    n43_line,
    sepa_23_01,
    sepa_23_02,
    sepa_23_03,
    sepa_23_04,
    with_end,
    wrap_account,
)

from ledger_kit.ingestion.norma43_reader import parse_norma43
from ledger_kit.models import Transaction

D = Decimal
ACCOUNT = "999900010000000001"
NAME = "acct.n43"


def parse(data: str | bytes, name: str = NAME) -> tuple[list[Transaction], list[dict]]:
    """Parse text (UTF-8) or bytes the way an uploaded file would arrive."""
    raw = data.encode("utf-8") if isinstance(data, str) else data
    return parse_norma43(io.BytesIO(raw), source_file=name)


def fields(transaction: Transaction) -> dict:
    """Return the transaction's fields without the random id."""
    return transaction.model_dump(exclude={"id"})


def read_single(
    *complements: str,
    common: str = "04",
    key: str = "1",
    amount: str = "12.99",
    mode: str = "1",
) -> Transaction:
    """Read a one-movement file that passes every check and return its transaction."""
    movement = movement_22(common=common, key=key, amount=amount)
    amounts = {"debits": [amount]} if key == "1" else {"credits": [amount]}
    lines = with_end(wrap_account([movement, *complements], mode=mode, **amounts))
    transactions, quarantine = parse(join_lines(lines))
    assert quarantine == []
    assert len(transactions) == 1
    return transactions[0]


EXPECTED_FIXTURE_A = [
    {
        "date": dt.date(2026, 1, 5),
        "amount": D("12.99"),
        "flow": "debit",
        "currency": "EUR",
        "counterparty": "Taller Norte SL",
        "description": "Car repair",
        "iban": None,
        "source_file": NAME,
        "source_row": 2,
        "source_ref": "acct.n43:2",
        "source_line": 2,
        "tags": [f"account:{ACCOUNT}", "common_concept:04", "own_concept:000"],
    },
    {
        "date": dt.date(2026, 1, 28),
        "amount": D("2450.00"),
        "flow": "credit",
        "currency": "EUR",
        "counterparty": "Payroll and social security",
        "description": "Payroll and social security",
        "iban": None,
        "source_file": NAME,
        "source_row": 5,
        "source_ref": "acct.n43:5",
        "source_line": 5,
        "tags": [f"account:{ACCOUNT}", "common_concept:15", "own_concept:000"],
    },
]


# --- builders against the document -------------------------------------------------------------


def test_builders_reproduce_the_literal_lines_of_the_document() -> None:
    lines = [line.rstrip(" ") for line in fixture_a_lines()]
    trailer = "3399990001000000000100001000000000012990000100000000245000200000000743701978"
    assert lines[0] == "119999000100000000012601052601312000000005000009781TITULAR FICTICIO DEMO"
    assert lines[5] == trailer
    assert lines[6] == "88999999999999999999000006"
    assert all(len(line) == 80 for line in fixture_a_lines())


# --- normal case: Fixture A --------------------------------------------------------------------


def test_fixture_a_gives_the_two_expected_transactions() -> None:
    transactions, quarantine = parse(fixture_a())

    assert quarantine == []
    assert [fields(t) for t in transactions] == EXPECTED_FIXTURE_A


def test_transactions_have_exact_types() -> None:
    transactions, _ = parse(fixture_a())

    for transaction in transactions:
        assert isinstance(transaction.amount, Decimal)
        assert type(transaction.date) is dt.date
        assert transaction.id


@pytest.mark.parametrize("eol", ["\n", "\r\n", "\r"])
@pytest.mark.parametrize("strip", [True, False])
def test_line_endings_and_trailing_spaces_do_not_change_the_result(eol: str, strip: bool) -> None:
    transactions, quarantine = parse(fixture_a(eol=eol, strip=strip))

    assert quarantine == []
    assert [fields(t) for t in transactions] == EXPECTED_FIXTURE_A


def test_no_final_line_ending_gives_the_same_result() -> None:
    text = join_lines(fixture_a_lines(), final_eol=False)

    transactions, quarantine = parse(text)

    assert quarantine == []
    assert [fields(t) for t in transactions] == EXPECTED_FIXTURE_A


def test_other_unicode_separators_do_not_split_lines() -> None:
    """A Latin-1 \\x85 inside a text is a character, not a line break (DN-RF-04)."""
    lines = fixture_a_lines(complement_1=complement_23("01", "Taller\x85Norte SL"))

    transactions, quarantine = parse(join_lines(lines).encode("latin-1"))

    assert quarantine == []
    assert transactions[0].counterparty == "Taller Norte SL"
    assert [t.source_row for t in transactions] == [2, 5]


def test_latin_1_and_utf_8_names_decode_the_same() -> None:
    lines = fixture_a_lines(complement_1=complement_23("01", "Taller Niño SL"))
    text = join_lines(lines)

    from_latin_1, quarantine_latin_1 = parse(text.encode("latin-1"))
    from_utf_8, quarantine_utf_8 = parse(text.encode("utf-8"))
    from_bom, quarantine_bom = parse(b"\xef\xbb\xbf" + text.encode("utf-8"))

    assert quarantine_latin_1 == quarantine_utf_8 == quarantine_bom == []
    for transactions in (from_latin_1, from_utf_8, from_bom):
        assert transactions[0].counterparty == "Taller Niño SL"
        assert len(transactions) == 2


def test_bytes_with_a_latin_1_n_tilde_are_not_valid_utf_8() -> None:
    """The documented example: b'2301Taller Ni\\xf1o SL' decodes to 'Taller Niño SL'."""
    raw = b"2301Taller Ni\xf1o SL"
    with pytest.raises(UnicodeDecodeError):
        raw.decode("utf-8")
    text = join_lines(fixture_a_lines(complement_1=complement_23("01", "Taller Niño SL")))
    assert raw.decode("latin-1") in text


def test_str_source_with_a_bom_is_accepted() -> None:
    transactions, quarantine = parse_norma43(io.StringIO("\ufeff" + fixture_a()), source_file=NAME)

    assert quarantine == []
    assert len(transactions) == 2


def test_blank_lines_are_skipped_but_physical_numbering_is_kept() -> None:
    rendered = [line.rstrip(" ") for line in fixture_a_lines()]
    text = "\n\n".join(rendered) + "\n"

    transactions, quarantine = parse(text)

    assert quarantine == []
    assert [t.source_row for t in transactions] == [3, 9]
    assert [t.source_ref for t in transactions] == ["acct.n43:3", "acct.n43:9"]


def test_default_source_file_comes_from_the_stream_or_path(tmp_path) -> None:
    path = tmp_path / "statement.n43"
    path.write_bytes(fixture_a().encode("latin-1"))

    transactions, quarantine = parse_norma43(path)

    assert quarantine == []
    assert transactions[0].source_ref == "statement.n43:2"


# --- edge cases --------------------------------------------------------------------------------


@pytest.mark.parametrize("data", [b"", b"   ", b"\n\n \t\r\n"])
def test_empty_file_gives_nothing(data: bytes) -> None:
    assert parse(data) == ([], [])


def test_single_record_file_does_not_crash() -> None:
    transactions, quarantine = parse(join_lines([header_11()]))

    assert transactions == []
    assert [q["reason"] for q in quarantine] == [
        "control_check_failed:missing_end_of_account",
        "control_check_failed:record88_missing",
    ]


def test_zero_amount_is_a_valid_transaction() -> None:
    movement = movement_22(amount="0.00")
    lines = with_end(wrap_account([movement], debits=["0.00"]))

    transactions, quarantine = parse(join_lines(lines))

    assert quarantine == []
    assert transactions[0].amount == D("0.00")
    assert isinstance(transactions[0].amount, Decimal)


def test_largest_amount_is_exact() -> None:
    movement = movement_22(amount="999999999999.99")
    lines = with_end(wrap_account([movement], debits=["999999999999.99"], opening="0.00"))

    transactions, quarantine = parse(join_lines(lines))

    assert quarantine == []
    assert transactions[0].amount == D("999999999999.99")


def test_credit_amount_and_flow() -> None:
    transaction = read_single(key="2", amount="2450.00", common="15")

    assert transaction.flow == "credit"
    assert transaction.amount == D("2450.00")


def test_duplicate_movements_keep_distinct_source_refs() -> None:
    body = [movement_22(), movement_22()]
    lines = with_end(wrap_account(body, debits=["12.99", "12.99"]))

    transactions, quarantine = parse(join_lines(lines))

    assert quarantine == []
    assert [t.source_ref for t in transactions] == ["acct.n43:2", "acct.n43:3"]


def test_unknown_common_concept_uses_the_other_label() -> None:
    transaction = read_single(common="42")

    assert transaction.counterparty == "Other"
    assert transaction.description == "Other"
    assert "common_concept:42" in transaction.tags


# --- generic record 23 (REQ-RF-06) -------------------------------------------------------------


def test_generic_counterparty_and_description_split() -> None:
    transaction = read_single(
        complement_23("01", "Taller Norte SL"), complement_23("02", "Car repair")
    )

    assert transaction.counterparty == "Taller Norte SL"
    assert transaction.description == "Car repair"
    assert transaction.iban is None


def test_no_complement_falls_back_to_the_concept_label() -> None:
    transaction = read_single(common="15", key="2", amount="2450.00")

    assert transaction.counterparty == "Payroll and social security"
    assert transaction.description == "Payroll and social security"


def test_single_complement_gets_the_label_as_description() -> None:
    transaction = read_single(complement_23("01", "Streamly Plus"), common="12")

    assert transaction.counterparty == "Streamly Plus"
    assert transaction.description == "Credit and debit cards"


def test_more_complements_are_joined_into_the_description() -> None:
    transaction = read_single(
        complement_23("01", "Taller Norte SL"),
        complement_23("02", "Car repair"),
        complement_23("03", "Invoice 17"),
    )

    assert transaction.counterparty == "Taller Norte SL"
    assert transaction.description == "Car repair Invoice 17"


def test_iban_record_is_taken_out_of_the_texts() -> None:
    transaction = read_single(
        complement_23("01", "Transportes Hermanos Lage, S.L."),
        complement_23("02", "Supplier payment"),
        complement_23("03", "IBAN ES88 2100 0418 5602 0005 1332"),
    )

    assert transaction.counterparty == "Transportes Hermanos Lage, S.L."
    assert transaction.description == "Supplier payment"
    assert transaction.iban == "ES88 2100 0418 5602 0005 1332"


def test_iban_record_first_leaves_the_other_texts_in_order() -> None:
    transaction = read_single(
        complement_23("01", "IBAN ES88 2100 0418 5602 0005 1332"),
        complement_23("02", "Acme Demo SL"),
    )

    assert transaction.iban == "ES88 2100 0418 5602 0005 1332"
    assert transaction.counterparty == "Acme Demo SL"
    assert transaction.description == "Transfers"


def test_blank_runs_are_collapsed_in_texts() -> None:
    transaction = read_single(complement_23("01", "Ana   García"))

    assert transaction.counterparty == "Ana García"


def test_blank_complement_text_counts_as_no_text() -> None:
    transaction = read_single(complement_23("01", ""))

    assert transaction.counterparty == "Transfers"
    assert transaction.description == "Transfers"


def test_five_complements_are_the_maximum_and_all_are_used() -> None:
    texts = ["one", "two", "three", "four", "five"]
    transaction = read_single(*[complement_23(f"{i:02d}", t) for i, t in enumerate(texts, 1)])

    assert transaction.counterparty == "one"
    assert transaction.description == "two three four five"


# --- SEPA direct debit (REQ-RF-07) -------------------------------------------------------------


def sepa_lines() -> list[str]:
    """The record-23 lines of the REQ-RF-07 example."""
    return [
        sepa_23_01("CORE", "STREAMFLEX INTL 4412"),
        sepa_23_02("ES00ZZZB00000001", "MND0001"),
        sepa_23_03("Monthly subscription"),
    ]


def test_sepa_layout_in_mode_3_for_concept_03() -> None:
    transaction = read_single(*sepa_lines(), common="03", mode="3")

    assert transaction.counterparty == "STREAMFLEX INTL 4412"
    assert transaction.description == "Monthly subscription"
    assert transaction.tags == [
        f"account:{ACCOUNT}",
        "common_concept:03",
        "own_concept:000",
        "scheme:CORE",
        "creditor_id:ES00ZZZB00000001",
        "mandate:MND0001",
    ]
    assert transaction.iban is None


def test_sepa_line_literals_put_the_mandate_at_position_40() -> None:
    line = sepa_lines()[1].rstrip(" ")

    assert line == "2302ES00ZZZB00000001" + " " * 19 + "MND0001"
    assert sepa_lines()[2].rstrip(" ") == "2303" + " " * 8 + "Monthly subscription"


def test_the_same_lines_in_mode_1_are_read_generically() -> None:
    transaction = read_single(*sepa_lines(), common="03", mode="1")

    assert transaction.counterparty == "CORESTREAMFLEX INTL 4412"
    assert not any(tag.startswith("scheme:") for tag in transaction.tags)


def test_b2b_scheme() -> None:
    transaction = read_single(
        sepa_23_01("B2B", "BUSINESS PARTNER 77"),
        sepa_23_02("ES00ZZZB00000002", "MND2"),
        sepa_23_03("Rent"),
        common="03",
        mode="3",
    )

    assert "scheme:B2B" in transaction.tags
    assert transaction.counterparty == "BUSINESS PARTNER 77"
    assert transaction.description == "Rent"


def test_mode_3_with_another_concept_is_generic() -> None:
    transaction = read_single(*sepa_lines(), common="04", mode="3")

    assert transaction.counterparty == "CORESTREAMFLEX INTL 4412"
    assert not any(tag.startswith("scheme:") for tag in transaction.tags)


def test_mode_3_concept_03_without_core_or_b2b_is_generic() -> None:
    transaction = read_single(complement_23("01", "Utility Co"), common="03", mode="3")

    assert transaction.counterparty == "Utility Co"
    assert transaction.description == "Direct debits and bills"
    assert not any(tag.startswith("scheme:") for tag in transaction.tags)


def test_sepa_blank_creditor_and_remittance_fall_back_to_the_label() -> None:
    transaction = read_single(sepa_23_01("CORE", ""), common="03", mode="3")

    assert transaction.counterparty == "Direct debits and bills"
    assert transaction.description == "Direct debits and bills"
    assert transaction.tags[-1] == "scheme:CORE"


def test_sepa_tags_only_when_not_blank() -> None:
    transaction = read_single(
        sepa_23_01("CORE", "CREDITOR"), sepa_23_02("", "MND9"), common="03", mode="3"
    )

    assert not any(tag.startswith("creditor_id:") for tag in transaction.tags)
    assert "mandate:MND9" in transaction.tags


def test_sepa_remittance_continues_in_record_04() -> None:
    first = "X" * 68
    transaction = read_single(
        sepa_23_01("CORE", "CREDITOR"),
        sepa_23_02("ES00ZZZB00000001", "MND1"),
        sepa_23_03(first),
        sepa_23_04("YZ"),
        common="03",
        mode="3",
    )

    assert transaction.description == first + "YZ"


# --- record 24 (REQ-RF-08) ---------------------------------------------------------------------


def test_record_24_adds_the_original_currency_tags() -> None:
    transaction = read_single(currency_24("840", "15.00"), common="12", amount="13.78")

    assert transaction.tags == [
        f"account:{ACCOUNT}",
        "common_concept:12",
        "own_concept:000",
        "original_currency:USD",
        "original_amount:15.00",
    ]
    assert transaction.amount == D("13.78")
    assert transaction.currency == "EUR"


@pytest.mark.parametrize(
    ("numeric", "alpha"),
    [
        ("978", "EUR"),
        ("840", "USD"),
        ("826", "GBP"),
        ("756", "CHF"),
        ("752", "SEK"),
        ("578", "NOK"),
        ("554", "NZD"),
        ("392", "JPY"),
        ("208", "DKK"),
        ("124", "CAD"),
        ("036", "AUD"),
    ],
)
def test_record_24_known_codes_give_the_alphabetic_code(numeric: str, alpha: str) -> None:
    transaction = read_single(currency_24(numeric, "1.00"))

    assert f"original_currency:{alpha}" in transaction.tags


def test_record_24_unknown_code_keeps_the_movement_and_the_digits() -> None:
    transaction = read_single(currency_24("999", "15.00"), common="12", amount="13.78")

    assert transaction.tags[-2:] == ["original_currency_code:999", "original_amount:15.00"]
    assert not any(tag.startswith("original_currency:") for tag in transaction.tags)
    assert transaction.amount == D("13.78")


def test_record_24_after_generic_texts_keeps_the_texts() -> None:
    transaction = read_single(complement_23("01", "Shop Abroad"), currency_24("840", "20.00"))

    assert transaction.counterparty == "Shop Abroad"
    assert transaction.tags[-2:] == ["original_currency:USD", "original_amount:20.00"]


# --- several accounts in one file --------------------------------------------------------------


def test_two_accounts_in_one_file_have_distinct_account_tags() -> None:
    first = wrap_account([movement_22(), complement_23("01", "Taller Norte SL")], debits=["12.99"])
    second = wrap_account(
        [movement_22(op_date="260128", common="15", key="2", amount="50.00")],
        credits=["50.00"],
        opening="100.00",
        account="0000000002",
    )
    lines = with_end([*first, *second])

    transactions, quarantine = parse(join_lines(lines))

    assert quarantine == []
    assert [t.tags[0] for t in transactions] == [
        "account:999900010000000001",
        "account:999900010000000002",
    ]
    assert [t.source_row for t in transactions] == [2, 6]
    assert [t.amount for t in transactions] == [D("12.99"), D("50.00")]


# --- header quarantine (REQ-RF-04) -------------------------------------------------------------


def test_header_gives_account_currency_and_signed_opening_balance() -> None:
    """The opening balance only shows through the control check: a debtor sign flips it."""
    movement = movement_22(key="2", amount="2450.00")
    creditor = wrap_account([movement], credits=["2450.00"], opening="5000.00")
    debtor = [header_11(balance_sign="1", opening="5000.00"), *creditor[1:]]

    ok, _ = parse(join_lines(with_end(creditor)))
    bad, quarantine = parse(join_lines(with_end(debtor)))

    assert len(ok) == 1
    assert bad == []
    assert quarantine[0]["reason"] == "control_check_failed:balance"


@pytest.mark.parametrize(
    ("overrides", "reason", "has_account"),
    [
        ({"currency": "000"}, "unknown_currency_code", True),
        ({"currency": "999"}, "unknown_currency_code", True),
        ({"currency": "EUR"}, "unknown_currency_code", True),
        ({"balance_sign": "3"}, "bad_account_header:balance_sign", True),
        ({"balance_sign": " "}, "bad_account_header:balance_sign", True),
        ({"start_date": "261340"}, "bad_account_header:start_date", True),
        ({"start_date": "26AB01"}, "bad_account_header:start_date", True),
        ({"end_date": "260230"}, "bad_account_header:end_date", True),
        ({"opening": "0000000A500000"}, "bad_account_header:opening_balance", True),
        ({"mode": "4"}, "bad_account_header:information_mode", True),
        ({"mode": " "}, "bad_account_header:information_mode", True),
        ({"account": "000000000A"}, "bad_account_header:account", False),
        ({"bank": "99 9"}, "bad_account_header:account", False),
    ],
)
def test_bad_header_rejects_the_block(overrides: dict, reason: str, has_account: bool) -> None:
    lines = fixture_a_lines(header=header_11(**overrides))

    transactions, quarantine = parse(join_lines(lines))

    expected_raw: dict = {"dropped_lines": 5}
    if has_account:
        expected_raw = {"account": ACCOUNT, "dropped_lines": 5}
    assert transactions == []
    assert quarantine == [
        {
            "source_file": NAME,
            "source_row": 1,
            "source_line": 1,
            "reason": reason,
            "raw": expected_raw,
        }
    ]


def test_rejected_block_does_not_stop_the_next_block() -> None:
    rejected = fixture_a_lines(header=header_11(currency="000"))[:6]
    good = wrap_account(
        [movement_22(op_date="260128", common="15", key="2", amount="50.00")],
        credits=["50.00"],
        account="0000000002",
    )
    lines = with_end([*rejected, *good])

    transactions, quarantine = parse(join_lines(lines))

    assert [q["reason"] for q in quarantine] == ["unknown_currency_code"]
    assert quarantine[0]["source_row"] == 1
    assert [t.source_row for t in transactions] == [8]
    assert transactions[0].tags[0] == "account:999900010000000002"


def test_rejected_block_without_trailer_counts_lines_up_to_the_next_header() -> None:
    first = [header_11(currency="000"), movement_22(), complement_23("01", "Taller")]
    second = wrap_account([movement_22()], debits=["12.99"], account="0000000002")
    lines = with_end([*first, *second])

    transactions, quarantine = parse(join_lines(lines))

    assert quarantine == [
        {
            "source_file": NAME,
            "source_row": 1,
            "source_line": 1,
            "reason": "unknown_currency_code",
            "raw": {"account": ACCOUNT, "dropped_lines": 2},
        }
    ]
    assert len(transactions) == 1


# --- row-level quarantine (REQ-RF-09) ----------------------------------------------------------


def row(number: int, reason: str, *lines: str) -> dict:
    """The expected row-level quarantine record."""
    raw = "\n".join(line.rstrip(" ") for line in lines)
    return {
        "source_file": NAME,
        "source_row": number,
        "source_line": number,
        "reason": reason,
        "raw": raw,
    }


def test_line_too_long_quarantines_the_line_only() -> None:
    long_line = complement_23("01", "A" * 76) + "B"
    lines = with_end(wrap_account([movement_22(), long_line], debits=["12.99"]))

    transactions, quarantine = parse(join_lines(lines))

    assert len(transactions) == 1
    assert quarantine == [row(3, "line_too_long", long_line)]


def test_trailing_spaces_beyond_80_are_not_too_long() -> None:
    lines = with_end(wrap_account([movement_22()], debits=["12.99"]))
    text = join_lines([line + "      " for line in lines], strip=False)

    transactions, quarantine = parse(text)

    assert quarantine == []
    assert len(transactions) == 1


def test_unknown_record_code() -> None:
    lines = with_end(["55 anything", *wrap_account([movement_22()], debits=["12.99"])])

    transactions, quarantine = parse(join_lines(lines))

    assert len(transactions) == 1
    assert quarantine == [row(1, "unknown_record_code:55", "55 anything")]


def test_movement_without_account_header_at_the_start() -> None:
    stray = movement_22(op_date="260110", amount="7.00")
    lines = with_end([stray, *wrap_account([movement_22()], debits=["12.99"])])

    transactions, quarantine = parse(join_lines(lines))

    assert [t.source_row for t in transactions] == [3]
    assert quarantine == [row(1, "movement_without_account_header", stray)]


def test_movement_after_the_trailer_is_without_header_and_takes_its_complements() -> None:
    block = wrap_account([movement_22()], debits=["12.99"])
    stray = movement_22(op_date="260110", amount="7.00")
    note = complement_23("01", "Late")
    lines = with_end([*block, stray, note])

    transactions, quarantine = parse(join_lines(lines))

    assert len(transactions) == 1
    assert quarantine == [row(4, "movement_without_account_header", stray, note)]


def test_trailer_without_account_header() -> None:
    lines = with_end([fixture_a_lines()[5]])

    transactions, quarantine = parse(join_lines(lines))

    assert transactions == []
    assert [(q["source_row"], q["reason"]) for q in quarantine] == [
        (1, "trailer_without_account_header")
    ]


def test_complement_without_movement() -> None:
    stray_23 = complement_23("01", "Orphan")
    stray_24 = currency_24()
    lines = with_end([stray_23, stray_24, *wrap_account([movement_22()], debits=["12.99"])])

    transactions, quarantine = parse(join_lines(lines))

    assert len(transactions) == 1
    assert quarantine == [
        row(1, "complement_without_movement", stray_23),
        row(2, "complement_without_movement", stray_24),
    ]


def test_complement_after_the_trailer_is_without_movement() -> None:
    late = complement_23("01", "Late")
    lines = with_end([*wrap_account([movement_22()], debits=["12.99"]), late])

    transactions, quarantine = parse(join_lines(lines))

    assert len(transactions) == 1
    assert quarantine == [row(4, "complement_without_movement", late)]


def test_sixth_complement_is_quarantined_and_the_movement_stays_valid() -> None:
    complements = [complement_23(f"{i:02d}", f"text {i}") for i in range(1, 6)]
    sixth = complement_23("06", "text 6")
    lines = with_end(wrap_account([movement_22(), *complements, sixth], debits=["12.99"]))

    transactions, quarantine = parse(join_lines(lines))

    assert len(transactions) == 1
    assert transactions[0].description == "text 2 text 3 text 4 text 5"
    assert quarantine == [row(8, "too_many_complements", sixth)]


@pytest.mark.parametrize("sequence", ["00", "03", "02", "AB", "  "])
def test_bad_complement_sequence(sequence: str) -> None:
    wrong = complement_23(sequence, "wrong")
    lines = with_end(wrap_account([movement_22(), wrong], debits=["12.99"]))

    transactions, quarantine = parse(join_lines(lines))

    assert len(transactions) == 1
    assert transactions[0].counterparty == "Transfers"
    assert quarantine == [row(3, "bad_complement_sequence", wrong)]


def test_bad_operation_date_takes_its_complements_and_still_counts_in_the_sums() -> None:
    lines = fixture_a_lines(movement_1=movement_22(op_date="261340"))

    transactions, quarantine = parse(join_lines(lines))

    assert [fields(t) for t in transactions] == [EXPECTED_FIXTURE_A[1]]
    assert quarantine == [
        row(2, "bad_date:operation_date", lines[1], lines[2], lines[3]),
    ]


@pytest.mark.parametrize("bad", ["261340", "260230", "26AB05", "      ", "261301", "26010 "])
def test_bad_operation_dates(bad: str) -> None:
    movement = movement_22(op_date=bad, value_date="260105")
    lines = with_end(wrap_account([movement], debits=["12.99"]))

    transactions, quarantine = parse(join_lines(lines))

    assert transactions == []
    assert quarantine == [row(2, "bad_date:operation_date", movement)]


def test_bad_value_date() -> None:
    movement = movement_22(op_date="260105", value_date="260132")
    lines = with_end(wrap_account([movement], debits=["12.99"]))

    transactions, quarantine = parse(join_lines(lines))

    assert transactions == []
    assert quarantine == [row(2, "bad_date:value_date", movement)]


def test_leap_day_is_a_valid_date() -> None:
    movement = movement_22(op_date="280229")
    lines = with_end(wrap_account([movement], debits=["12.99"]))

    transactions, quarantine = parse(join_lines(lines))

    assert quarantine == []
    assert transactions[0].date == dt.date(2028, 2, 29)


def test_bad_concept_code_is_row_level_and_counted() -> None:
    movement = movement_22(common="A4")
    lines = with_end(wrap_account([movement], debits=["12.99"]))

    transactions, quarantine = parse(join_lines(lines))

    assert transactions == []
    assert quarantine == [row(2, "bad_concept_code", movement)]


def test_bad_own_concept_code() -> None:
    movement = movement_22(own="0X0")
    lines = with_end(wrap_account([movement], debits=["12.99"]))

    _, quarantine = parse(join_lines(lines))

    assert quarantine == [row(2, "bad_concept_code", movement)]


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"key": "3"}, "bad_dc_key"),
        ({"key": " "}, "bad_dc_key"),
        ({"amount": "0000000000A299"}, "non_digit_amount"),
        ({"amount": "000000000012 9"}, "non_digit_amount"),
        ({"amount": "00000000-12990"}, "non_digit_amount"),
    ],
)
def test_unreadable_key_or_amount_is_quarantined_and_fails_the_block(
    overrides: dict, reason: str
) -> None:
    movement = movement_22(**overrides)
    lines = with_end(wrap_account([movement]))

    transactions, quarantine = parse(join_lines(lines))

    assert transactions == []
    assert [q["reason"] for q in quarantine] == [
        reason,
        "control_check_failed:unverifiable_movement",
    ]
    assert quarantine[0] == row(2, reason, movement)


@pytest.mark.parametrize(
    "currency_line",
    [
        n43_line("24", (3, 4, "01"), (5, 7, "8A0"), (8, 21, "00000000001500")),
        n43_line("24", (3, 4, "01"), (5, 7, "84"), (8, 21, "00000000001500")),
        n43_line("24", (3, 4, "01"), (5, 7, "840"), (8, 21, "0000000000150X")),
        n43_line("24", (3, 4, "01"), (5, 7, "840")),
        n43_line("24", (3, 4, "02"), (5, 7, "840"), (8, 21, "00000000001500")),
    ],
)
def test_malformed_record_24_quarantines_the_movement(currency_line: str) -> None:
    movement = movement_22(common="12", amount="13.78")
    lines = with_end(wrap_account([movement, currency_line], debits=["13.78"]))

    transactions, quarantine = parse(join_lines(lines))

    assert transactions == []
    assert quarantine == [row(2, "bad_currency_equivalence", movement, currency_line)]


def test_repeated_record_24_quarantines_the_movement() -> None:
    movement = movement_22(common="12", amount="13.78")
    first, second = currency_24("840", "15.00"), currency_24("826", "12.00")
    lines = with_end(wrap_account([movement, first, second], debits=["13.78"]))

    transactions, quarantine = parse(join_lines(lines))

    assert transactions == []
    assert quarantine == [row(2, "bad_currency_equivalence", movement, first, second)]


def test_record_24_with_an_unknown_code_is_not_quarantined() -> None:
    movement = movement_22(common="12", amount="13.78")
    lines = with_end(wrap_account([movement, currency_24("999", "15.00")], debits=["13.78"]))

    transactions, quarantine = parse(join_lines(lines))

    assert quarantine == []
    assert len(transactions) == 1


def test_record_after_end_of_file_is_quarantined_and_the_rest_is_kept() -> None:
    lines = [*fixture_a_lines(), "trailing garbage"]

    transactions, quarantine = parse(join_lines(lines))

    assert [fields(t) for t in transactions] == EXPECTED_FIXTURE_A
    assert quarantine == [row(8, "record_after_end_of_file", "trailing garbage")]


def test_blank_lines_after_the_end_of_file_are_ignored() -> None:
    text = fixture_a() + "\n\n   \n"

    transactions, quarantine = parse(text)

    assert quarantine == []
    assert len(transactions) == 2


def test_a_bad_row_does_not_stop_the_good_rows() -> None:
    bad = movement_22(op_date="261340")
    good = movement_22(op_date="260110", amount="7.00")
    lines = with_end(wrap_account([bad, good], debits=["12.99", "7.00"]))

    transactions, quarantine = parse(join_lines(lines))

    assert [t.amount for t in transactions] == [D("7.00")]
    assert [q["reason"] for q in quarantine] == ["bad_date:operation_date"]
