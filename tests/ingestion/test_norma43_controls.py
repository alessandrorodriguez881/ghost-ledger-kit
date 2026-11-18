"""Tests for the Norma 43 control checks of records 33 and 88 (REQ-RF-10, REQ-RF-11)."""

from __future__ import annotations

import io
from decimal import Decimal

import pytest
from n43_builders import (
    closing_33,
    complement_23,
    end_88,
    fixture_a,
    fixture_a_lines,
    header_11,
    join_lines,
    movement_22,
    with_end,
    wrap_account,
)

from ledger_kit.ingestion.norma43_reader import (
    CONTROL_CHECK_FAILED_MESSAGE,
    check_block,
    control_check_messages,
    parse_norma43,
)
from ledger_kit.models import Transaction

D = Decimal
ACCOUNT = "999900010000000001"
NAME = "acct.n43"


def parse(data: str) -> tuple[list[Transaction], list[dict]]:
    """Parse text the way an uploaded file would arrive."""
    return parse_norma43(io.BytesIO(data.encode("utf-8")), source_file=NAME)


def block_record(row: int, check: str, declared: str | None, computed: str | None, line_33: int):
    """The expected block-level quarantine record."""
    return {
        "source_file": NAME,
        "source_row": row,
        "source_line": row,  # a Norma 43 row is the line of its record
        "reason": f"control_check_failed:{check}",
        "raw": {
            "account": ACCOUNT,
            "declared": declared,
            "computed": computed,
            "line_33": line_33,
        },
    }


def file_record(check: str, declared: str | None, computed: str) -> dict:
    """The expected file-level quarantine record of a record-88 failure."""
    return {
        "source_file": NAME,
        "source_row": None,
        "source_line": None,
        "reason": f"control_check_failed:{check}",
        "raw": {"declared": declared, "computed": computed},
    }


# --- passing and failing trailers --------------------------------------------------------------


def test_fixture_a_passes_every_check() -> None:
    transactions, quarantine = parse(fixture_a())

    assert quarantine == []
    assert len(transactions) == 2


def test_control_check_messages_has_one_plain_line_per_control_record() -> None:
    """The apps show this line for every control_check_failed record (RF9, RF10)."""
    _, block = parse(fixture_a(trailer=closing_33(debit_total="13.00")))
    other = {"source_file": "x.n43", "source_row": 2, "reason": "unparseable_date", "raw": "r"}

    assert control_check_messages([other, *block, other]) == [
        f"{NAME} (control_check_failed:debit_total): {CONTROL_CHECK_FAILED_MESSAGE}"
    ]
    assert control_check_messages([other]) == []
    assert control_check_messages([]) == []


def test_debit_total_failure_names_declared_and_computed() -> None:
    transactions, quarantine = parse(fixture_a(trailer=closing_33(debit_total="13.00")))

    assert transactions == []
    assert quarantine == [block_record(1, "debit_total", "13.00", "12.99", 6)]


def test_debit_total_off_by_one_cent_either_way_fails() -> None:
    for declared in ("12.98", "13.00"):
        _, quarantine = parse(fixture_a(trailer=closing_33(debit_total=declared)))
        assert quarantine == [block_record(1, "debit_total", declared, "12.99", 6)]


def test_exact_totals_pass() -> None:
    transactions, quarantine = parse(fixture_a(trailer=closing_33(debit_total="12.99")))

    assert quarantine == []
    assert len(transactions) == 2


def test_credit_total_failure() -> None:
    transactions, quarantine = parse(fixture_a(trailer=closing_33(credit_total="2449.99")))

    assert transactions == []
    assert quarantine == [block_record(1, "credit_total", "2449.99", "2450.00", 6)]


def test_debit_count_failure() -> None:
    transactions, quarantine = parse(fixture_a(trailer=closing_33(debit_count=2)))

    assert transactions == []
    assert quarantine == [block_record(1, "debit_count", "2", "1", 6)]


def test_credit_count_failure() -> None:
    transactions, quarantine = parse(fixture_a(trailer=closing_33(credit_count=0)))

    assert transactions == []
    assert quarantine == [block_record(1, "credit_count", "0", "1", 6)]


@pytest.mark.parametrize(
    ("overrides", "declared"),
    [
        ({"account": "0000000009"}, "999900010000000009"),
        ({"branch": "0002"}, "999900020000000001"),
        ({"bank": "9998"}, "999800010000000001"),
    ],
)
def test_account_mismatch(overrides: dict, declared: str) -> None:
    transactions, quarantine = parse(fixture_a(trailer=closing_33(**overrides)))

    assert transactions == []
    assert quarantine == [block_record(1, "account_mismatch", declared, ACCOUNT, 6)]


def test_balance_failure() -> None:
    transactions, quarantine = parse(fixture_a(trailer=closing_33(balance="7437.00")))

    assert transactions == []
    assert quarantine == [block_record(1, "balance", "7437.00", "7437.01", 6)]


def test_balance_debtor_opening_and_debtor_closing_pass() -> None:
    lines = fixture_a_lines(
        header=header_11(balance_sign="1", opening="5000.00"),
        trailer=closing_33(sign="1", balance="2562.99"),
    )

    transactions, quarantine = parse(join_lines(lines))

    assert quarantine == []
    assert len(transactions) == 2


def test_balance_debtor_opening_with_creditor_closing_sign_fails() -> None:
    lines = fixture_a_lines(
        header=header_11(balance_sign="1", opening="5000.00"),
        trailer=closing_33(sign="2", balance="2562.99"),
    )

    transactions, quarantine = parse(join_lines(lines))

    assert transactions == []
    assert quarantine == [block_record(1, "balance", "2562.99", "-2562.99", 6)]


def test_balance_that_crosses_zero_passes() -> None:
    body = [movement_22(amount="150.00")]
    lines = with_end(wrap_account(body, debits=["150.00"], opening="100.00"))

    transactions, quarantine = parse(join_lines(lines))

    assert quarantine == []
    assert len(transactions) == 1
    assert lines[-2][58] == "1"


def test_balance_with_unreadable_closing_sign_fails() -> None:
    transactions, quarantine = parse(fixture_a(trailer=closing_33(sign="3")))

    assert transactions == []
    assert quarantine[0]["reason"] == "control_check_failed:balance"
    assert quarantine[0]["raw"]["declared"] == "300000000743701"
    assert quarantine[0]["raw"]["computed"] == "7437.01"


def test_unreadable_total_fails_with_the_raw_text() -> None:
    transactions, quarantine = parse(fixture_a(trailer=closing_33(debit_total="0000000000A299")))

    assert transactions == []
    assert quarantine == [block_record(1, "debit_total", "0000000000A299", "12.99", 6)]


def test_unreadable_count_fails_with_the_raw_text() -> None:
    _, quarantine = parse(fixture_a(trailer=closing_33(debit_count="0000X")))

    assert quarantine == [block_record(1, "debit_count", "0000X", "1", 6)]


def test_the_first_failing_check_is_the_one_named() -> None:
    trailer = closing_33(debit_count=2, debit_total="99.99", credit_total="1.00", balance="1.00")

    _, quarantine = parse(fixture_a(trailer=trailer))

    assert [q["reason"] for q in quarantine] == ["control_check_failed:debit_count"]


def test_check_order_is_the_documented_one() -> None:
    changes = [
        ("account_mismatch", {"account": "0000000009"}),
        ("debit_count", {"debit_count": 9}),
        ("debit_total", {"debit_total": "1.00"}),
        ("credit_count", {"credit_count": 9}),
        ("credit_total", {"credit_total": "1.00"}),
        ("balance", {"balance": "1.00"}),
    ]
    for index, (check, _) in enumerate(changes):
        # Break this check and every later one: the first of them must be the one named.
        overrides: dict = {}
        for _, change in changes[index:]:
            overrides.update(change)
        _, quarantine = parse(fixture_a(trailer=closing_33(**overrides)))
        assert [q["reason"] for q in quarantine] == [f"control_check_failed:{check}"]


# --- unverifiable movements --------------------------------------------------------------------


def test_unreadable_amount_that_the_trailer_still_counts_fails_the_debit_count() -> None:
    lines = fixture_a_lines(movement_1=movement_22(amount="0000000000A299"))

    transactions, quarantine = parse(join_lines(lines))

    assert transactions == []
    assert [q["reason"] for q in quarantine] == [
        "non_digit_amount",
        "control_check_failed:debit_count",
    ]


def test_unreadable_amount_the_trailer_does_not_count_fails_as_unverifiable() -> None:
    movement = movement_22(amount="0000000000A299")
    lines = with_end(wrap_account([movement]))

    transactions, quarantine = parse(join_lines(lines))

    assert transactions == []
    assert quarantine[1] == block_record(1, "unverifiable_movement", "", "", 3)


def test_over_long_movement_line_makes_the_block_unverifiable() -> None:
    long_movement = movement_22() + "X"
    lines = with_end(wrap_account([long_movement]))

    transactions, quarantine = parse(join_lines(lines))

    assert transactions == []
    assert [q["reason"] for q in quarantine] == [
        "line_too_long",
        "control_check_failed:unverifiable_movement",
    ]


# --- missing record 33 -------------------------------------------------------------------------


def test_missing_trailer_at_the_end_of_the_block() -> None:
    lines = with_end([*fixture_a_lines()[:5]])

    transactions, quarantine = parse(join_lines(lines))

    assert transactions == []
    assert quarantine == [block_record(1, "missing_end_of_account", None, None, None)]


def test_missing_trailer_before_the_next_header() -> None:
    first = fixture_a_lines()[:5]
    second = wrap_account(
        [movement_22(op_date="260128", common="15", key="2", amount="50.00")],
        credits=["50.00"],
        account="0000000002",
    )

    transactions, quarantine = parse(join_lines(with_end([*first, *second])))

    assert [t.tags[0] for t in transactions] == ["account:999900010000000002"]
    assert quarantine == [block_record(1, "missing_end_of_account", None, None, None)]


def test_missing_trailer_without_end_of_file() -> None:
    lines = fixture_a_lines()[:5]

    transactions, quarantine = parse(join_lines(lines))

    assert transactions == []
    assert [q["reason"] for q in quarantine] == [
        "control_check_failed:missing_end_of_account",
        "control_check_failed:record88_missing",
    ]


# --- two blocks --------------------------------------------------------------------------------


def two_blocks(second_trailer_credit_count: int) -> str:
    """Block 1 is Fixture A; block 2 has one credit and a configurable declared credit count."""
    first = fixture_a_lines()[:6]
    second = wrap_account(
        [movement_22(op_date="260128", common="15", key="2", amount="50.00")],
        credits=["50.00"],
        account="0000000002",
    )
    second[-1] = closing_33(
        account="0000000002",
        debit_count=0,
        debit_total="0.00",
        credit_count=second_trailer_credit_count,
        credit_total="50.00",
        sign="2",
        balance="5050.00",
    )
    return join_lines(with_end([*first, *second]))


def test_two_blocks_both_valid() -> None:
    transactions, quarantine = parse(two_blocks(1))

    assert quarantine == []
    assert len(transactions) == 3


def test_only_the_failing_block_is_dropped() -> None:
    transactions, quarantine = parse(two_blocks(2))

    assert [t.source_ref for t in transactions] == ["acct.n43:2", "acct.n43:5"]
    assert len(quarantine) == 1
    record = quarantine[0]
    assert record["source_row"] == 7
    assert record["reason"] == "control_check_failed:credit_count"
    assert record["raw"] == {
        "account": "999900010000000002",
        "declared": "2",
        "computed": "1",
        "line_33": 9,
    }


# --- record 88 ---------------------------------------------------------------------------------


def test_record_88_with_the_right_count_passes() -> None:
    assert fixture_a_lines()[6].rstrip(" ") == "88999999999999999999000006"

    transactions, quarantine = parse(fixture_a())

    assert quarantine == []
    assert len(transactions) == 2


def test_record_88_count_too_high() -> None:
    transactions, quarantine = parse(fixture_a(end=end_88(7)))

    assert transactions == []
    assert quarantine == [file_record("record88_count", "7", "6")]


def test_record_88_count_too_low_by_one() -> None:
    transactions, quarantine = parse(fixture_a(end=end_88(5)))

    assert transactions == []
    assert quarantine == [file_record("record88_count", "5", "6")]


def test_record_88_missing() -> None:
    lines = fixture_a_lines()[:6]

    transactions, quarantine = parse(join_lines(lines))

    assert transactions == []
    assert quarantine == [file_record("record88_missing", None, "6")]


@pytest.mark.parametrize(
    "end",
    [
        end_88(6, nines="9" * 17 + "8"),
        end_88("0000A6"),
        end_88("6"),
        end_88(6, nines="9" * 17),
    ],
)
def test_record_88_malformed(end: str) -> None:
    transactions, quarantine = parse(fixture_a(end=end))

    expected = "88" + "9" * 18 + "000006"
    assert transactions == []
    assert quarantine == [file_record("record88_format", end.rstrip(" "), expected)]


def test_record_88_failure_keeps_row_and_block_records() -> None:
    lines = fixture_a_lines(
        movement_1=movement_22(op_date="261340"),
        trailer=closing_33(credit_count=2),
        end=end_88(9),
    )

    transactions, quarantine = parse(join_lines(lines))

    assert transactions == []
    assert [q["reason"] for q in quarantine] == [
        "bad_date:operation_date",
        "control_check_failed:credit_count",
        "control_check_failed:record88_count",
    ]


def test_record_88_failure_discards_the_valid_blocks_too() -> None:
    first = fixture_a_lines()[:6]
    second = wrap_account(
        [movement_22(op_date="260128", common="15", key="2", amount="50.00")],
        credits=["50.00"],
        account="0000000002",
    )

    transactions, quarantine = parse(join_lines([*first, *second, end_88(99)]))

    assert transactions == []
    assert [q["reason"] for q in quarantine] == ["control_check_failed:record88_count"]


def test_record_88_counts_every_record_kind_including_quarantined_lines() -> None:
    stray = complement_23("01", "Orphan")
    junk = "55 junk"
    body = wrap_account([movement_22()], debits=["12.99"])
    lines = [stray, junk, *body]

    transactions, quarantine = parse(join_lines([*lines, end_88(len(lines))]))

    assert len(transactions) == 1
    assert [q["reason"] for q in quarantine] == [
        "complement_without_movement",
        "unknown_record_code:55",
    ]


def test_record_88_does_not_count_blank_lines() -> None:
    text = "\n".join(line.rstrip(" ") for line in fixture_a_lines()[:6])
    text += "\n\n\n" + fixture_a_lines()[6].rstrip(" ") + "\n"

    transactions, quarantine = parse(text)

    assert quarantine == []
    assert len(transactions) == 2


# --- the check function and the message --------------------------------------------------------


def test_check_block_is_pure_and_returns_none_on_success() -> None:
    line33 = closing_33()
    kwargs = {
        "account": ACCOUNT,
        "opening": D("5000.00"),
        "debits": [D("12.99")],
        "credits": [D("2450.00")],
        "line33": line33,
    }

    assert check_block(**kwargs) is None
    assert check_block(**kwargs) is None
    assert kwargs["debits"] == [D("12.99")]


def test_check_block_reports_the_first_failure() -> None:
    result = check_block(
        account=ACCOUNT,
        opening=D("5000.00"),
        debits=[D("13.00")],
        credits=[D("2450.00")],
        line33=closing_33(),
    )

    assert result == ("debit_total", "12.99", "13.00")


def test_check_block_unverifiable_comes_last() -> None:
    kwargs = {
        "account": ACCOUNT,
        "opening": D("5000.00"),
        "debits": [D("12.99")],
        "credits": [D("2450.00")],
        "line33": closing_33(),
    }

    assert check_block(**kwargs, unverifiable=True) == ("unverifiable_movement", "", "")
    assert check_block(**{**kwargs, "debits": []}, unverifiable=True)[0] == "debit_count"


def test_control_check_message_is_plain_and_asks_for_a_fresh_export() -> None:
    message = CONTROL_CHECK_FAILED_MESSAGE.lower()

    assert "incomplete or was edited" in message
    assert "fresh export" in message
    assert "control_check_failed" not in message
