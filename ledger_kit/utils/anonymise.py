"""PII utilities: scrub transactions and mask IBANs."""

from __future__ import annotations

from ledger_kit.models import Transaction

_COUNTERPARTY_PLACEHOLDER = "REDACTED"
_IBAN_PLACEHOLDER = "DE00000000000000000000"


def scrub(transaction: Transaction) -> Transaction:
    """Return a copy of `transaction` with counterparty and IBAN replaced by placeholders."""
    return transaction.model_copy(
        update={
            "counterparty": _COUNTERPARTY_PLACEHOLDER,
            "iban": _IBAN_PLACEHOLDER if transaction.iban is not None else None,
        }
    )


def mask_iban(iban: str) -> str:
    """Return '****' plus the last 4 characters of the cleaned IBAN ('****' if too short)."""
    cleaned = "".join(iban.split()).upper()
    return "****" + cleaned[-4:] if len(cleaned) > 4 else "****"
