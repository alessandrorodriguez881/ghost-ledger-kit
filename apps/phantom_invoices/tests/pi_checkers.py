"""Test-local checkers for IBANs and Spanish tax ids.

The app and ledger_kit never validate national check digits or tax-id control characters
(OD-PI-15, REQ-PI-58): only the tests do, to prove that the synthetic identifiers of Finance
Rule 5 are *deliberately wrong* in exactly that part and nowhere else. These functions are an
independent implementation, so they can cross-check the generator in scripts/generate_samples.py.
"""

import re

# Spanish national control-digit weights (Cuenta Corriente Cliente).
_DC_WEIGHTS = (1, 2, 4, 8, 5, 10, 9, 7, 3, 6)
_NIF_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"
_CIF_LETTERS = "JABCDEFGHI"
# First CIF letters whose control must be a digit / a letter; every other letter accepts both.
_CIF_DIGIT_ONLY = "ABEH"
_CIF_LETTER_ONLY = "KPQSNRW"

_NIF_RE = re.compile(r"^[0-9]{8}[A-Z]$")
_NIE_RE = re.compile(r"^[XYZ][0-9]{7}[A-Z]$")
_CIF_RE = re.compile(r"^[A-Z][0-9]{7}[0-9A-Z]$")


def mod97_remainder(compact_iban: str) -> int:
    """Return the ISO 13616 remainder of a compact IBAN (1 means the checksum is valid)."""
    rearranged = compact_iban[4:] + compact_iban[:4]
    return int("".join(str(int(ch, 36)) for ch in rearranged)) % 97


def iban_check_digits(country: str, bban: str) -> str:
    """Return the two ISO 13616 check digits for a country code and a BBAN."""
    numeric = "".join(str(int(ch, 36)) for ch in bban + country + "00")
    return f"{98 - int(numeric) % 97:02d}"


def _dc_digit(digits: str) -> int:
    """One Spanish national control digit for a 10-digit string."""
    total = sum(int(d) * w for d, w in zip(digits, _DC_WEIGHTS, strict=True))
    value = 11 - total % 11
    return {10: 1, 11: 0}.get(value, value)


def spanish_national_dc(bank: str, branch: str, account: str) -> str:
    """Return the correct national check digits: ('2100', '0418', '0200051332') -> '45'."""
    return f"{_dc_digit('00' + bank + branch)}{_dc_digit(account)}"


def spanish_national_dc_ok(compact_iban: str) -> bool:
    """True when the national check digits of a compact Spanish IBAN are the correct ones."""
    bban = compact_iban[4:]
    bank, branch, carried, account = bban[0:4], bban[4:8], bban[8:10], bban[10:20]
    return carried == spanish_national_dc(bank, branch, account)


def nif_letter(number: int) -> str:
    """Return the correct NIF control letter for a number: 1 -> 'R'."""
    return _NIF_LETTERS[number % 23]


def cif_control(body: str) -> tuple[str, str]:
    """Return the correct (digit, letter) CIF control pair for a letter plus 7 digits."""
    digits = body[1:8]
    odd = sum(sum(divmod(int(d) * 2, 10)) for d in digits[0::2])
    even = sum(int(d) for d in digits[1::2])
    value = (10 - (odd + even) % 10) % 10
    return str(value), _CIF_LETTERS[value]


def tax_id_control_ok(tax_id: str) -> bool:
    """True when the control character of a NIF, NIE or CIF is the correct one."""
    if _NIF_RE.fullmatch(tax_id):
        return tax_id[8] == nif_letter(int(tax_id[:8]))
    if _NIE_RE.fullmatch(tax_id):
        number = int(str("XYZ".index(tax_id[0])) + tax_id[1:8])
        return tax_id[8] == nif_letter(number)
    if _CIF_RE.fullmatch(tax_id):
        digit, letter = cif_control(tax_id)
        if tax_id[0] in _CIF_DIGIT_ONLY:
            return tax_id[8] == digit
        if tax_id[0] in _CIF_LETTER_ONLY:
            return tax_id[8] == letter
        return tax_id[8] in (digit, letter)
    return False
