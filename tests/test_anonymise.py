"""Tests for ledger_kit.utils.anonymise."""

import re
from datetime import date
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from ledger_kit.models import Transaction
from ledger_kit.utils.anonymise import mask_iban, scrub

# Same pattern as design §4a.4 (explainer._IBAN_RE); copied here because the explainer
# module is implemented in a later task.
_IBAN_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,3})?(?![A-Za-z0-9])"
)

_FAKE_IBAN = "ES88 2100 0418 5602 0005 1332"


def _tx(iban: str | None = _FAKE_IBAN) -> Transaction:
    return Transaction(
        date=date(2026, 1, 15),
        amount=Decimal("12.99"),
        flow="debit",
        currency="EUR",
        counterparty="Ana García",
        description="Monthly plan",
        iban=iban,
        source_file="bank.csv",
        source_row=0,
        source_ref="bank.csv:0",
        tags=["x"],
    )


def test_scrub_replaces_counterparty() -> None:
    assert scrub(_tx()).counterparty == "REDACTED"


def test_scrub_replaces_iban_when_present() -> None:
    assert scrub(_tx()).iban == "DE00000000000000000000"


def test_scrub_iban_none_stays_none() -> None:
    assert scrub(_tx(iban=None)).iban is None


def test_scrub_returns_new_instance() -> None:
    original = _tx()
    assert scrub(original) is not original
    assert original.counterparty == "Ana García"
    assert original.iban == _FAKE_IBAN


def test_scrub_other_fields_unchanged() -> None:
    original = _tx()
    result = scrub(original)
    changed = {"counterparty", "iban"}
    for name in Transaction.model_fields:
        if name not in changed:
            assert getattr(result, name) == getattr(original, name)


def test_mask_iban_last_four() -> None:
    assert mask_iban("ES88 2100 0418 5602 0005 1332") == "****1332"


def test_mask_iban_cleans_spaces_case_and_nbsp() -> None:
    assert mask_iban("es88\u00a02100 0418 5602 0005 1332") == "****1332"


def test_mask_iban_short_value_reveals_nothing() -> None:
    for value in ("", "AB", "1234"):
        assert mask_iban(value) == "****"


@settings(max_examples=200)
@given(value=st.text(min_size=5, max_size=34))
def test_mask_iban_never_contains_full_value_and_is_not_iban_shaped(value: str) -> None:
    masked = mask_iban(value)
    assert len(masked) == 8 or masked == "****"
    assert masked.startswith("****")
    assert _IBAN_RE.search(masked) is None
    cleaned = "".join(value.split()).upper()
    if len(cleaned) > 4:
        assert len(masked) == 8
        assert masked != cleaned
