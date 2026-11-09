"""Tests for the IBAN and tax-id generators of scripts/generate_samples.py (Task P8).

The generators produce the identifiers of Finance Rule 5: IBANs with a valid ISO 13616 mod-97
checksum but deliberately wrong Spanish national check digits, and tax ids with a wrong control
character. The independent checkers of pi_checkers.py confirm both properties.
"""

import importlib.util
import random
import re
import sys
from pathlib import Path
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from apps.phantom_invoices.tests.pi_builders import iban_for_supplier
from apps.phantom_invoices.tests.pi_checkers import (
    iban_check_digits,
    mod97_remainder,
    nif_letter,
    spanish_national_dc,
    spanish_national_dc_ok,
    tax_id_control_ok,
)

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "generate_samples.py"
DIGITS = "0123456789"
DOC_IBAN = "ES88 2100 0418 5602 0005 1332"
CIF_RE = re.compile(r"^B[0-9]{8}$")
NIF_RE = re.compile(r"^[0-9]{8}[A-Z]$")


def _load_generator() -> Any:
    """Load scripts/generate_samples.py by path (scripts/ is not a package)."""
    spec = importlib.util.spec_from_file_location("generate_samples_pi_identifiers", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["generate_samples_pi_identifiers"] = module
    spec.loader.exec_module(module)
    return module


gen = _load_generator()


# Tier 1: normal cases


def test_correct_national_dc_example() -> None:
    """The documented account has the correct national check digits 45."""
    assert gen.correct_national_dc("2100", "0418", "0200051332") == "45"
    assert spanish_national_dc("2100", "0418", "0200051332") == "45"


def test_wrong_national_dc_example() -> None:
    """The deliberately wrong pair for the documented account is 56."""
    assert gen.wrong_national_dc("2100", "0418", "0200051332") == "56"


def test_make_iban_reproduces_documented_example() -> None:
    """make_iban + format_iban give the IBAN of Finance Rule 5."""
    compact = gen.make_iban("2100", "0418", "0200051332")

    assert gen.format_iban(compact) == DOC_IBAN
    assert compact == DOC_IBAN.replace(" ", "")


def test_make_cif_and_make_nif_examples() -> None:
    """Every fictional tax id of the plan has a wrong control character."""
    assert gen.make_cif(1) == "B00000019"
    assert gen.make_nif(1) == "00001001J"
    for k in range(1, 26):
        cif = gen.make_cif(k)
        nif = gen.make_nif(k)
        assert CIF_RE.fullmatch(cif), cif
        assert NIF_RE.fullmatch(nif), nif
        assert not tax_id_control_ok(cif), cif
        assert not tax_id_control_ok(nif), nif


def test_checkers_accept_the_correct_control_character() -> None:
    """Guards the guard: the checker says yes to the right character and no to the generator's."""
    assert tax_id_control_ok("B00000018")  # the correct control digit of body 0000001
    assert not tax_id_control_ok("B00000019")
    assert tax_id_control_ok("00001001N")  # the correct letter for 1001 (1001 mod 23 = 12)
    assert not tax_id_control_ok("00001001J")
    assert nif_letter(12345678) == "Z"
    assert all(nif_letter(i) == gen.NIF_LETTERS[i] for i in range(23))


# Tier 2: edge cases


def test_every_generated_iban_is_mod97_valid_with_wrong_national_digits() -> None:
    """Master, alternative and unrelated-debit IBANs all satisfy Finance Rule 5."""
    for k in [*range(1, 26), *range(101, 111)]:
        for other in (False, True):
            compact = iban_for_supplier(k, other=other)
            assert len(compact) == 24
            assert compact.startswith("ES")
            assert mod97_remainder(compact) == 1, (k, other)
            assert not spanish_national_dc_ok(compact), (k, other)


def test_tax_ids_distinct_for_k_1_to_25() -> None:
    """Each supplier of the plan gets its own tax id."""
    cifs = {gen.make_cif(k) for k in range(1, 26)}
    nifs = {gen.make_nif(k) for k in range(1, 26)}

    assert len(cifs) == 25
    assert len(nifs) == 25
    assert cifs.isdisjoint(nifs)


def test_make_nif_skips_multiples_of_23() -> None:
    """k = 12 would give 1012 = 23 x 44 (correct letter T): it is skipped, k = 12 gives 1013."""
    assert gen.make_nif(12)[:8] == "00001013"
    assert gen.make_nif(13)[:8] == "00001014"
    for k in range(1, 500):
        nif = gen.make_nif(k)
        assert int(nif[:8]) % 23 != 0, nif
        assert nif != "00000000T"


def test_wrong_dc_never_equals_correct_dc() -> None:
    """For 200 random bank/branch/account triples the wrong pair differs from the right one."""
    rng = random.Random(20260101)
    for _ in range(200):
        bank = f"{rng.randrange(10**4):04d}"
        branch = f"{rng.randrange(10**4):04d}"
        account = f"{rng.randrange(10**10):010d}"
        correct = gen.correct_national_dc(bank, branch, account)
        wrong = gen.wrong_national_dc(bank, branch, account)
        assert len(correct) == len(wrong) == 2
        assert wrong != correct
        assert correct == spanish_national_dc(bank, branch, account)


# Tier 3: property-based tests


@settings(max_examples=200, deadline=None)
@given(
    bank=st.text(alphabet=DIGITS, min_size=4, max_size=4),
    branch=st.text(alphabet=DIGITS, min_size=4, max_size=4),
    account=st.text(alphabet=DIGITS, min_size=10, max_size=10),
)
def test_make_iban_valid_checksum_for_any_digits(bank: str, branch: str, account: str) -> None:
    """Whatever the digits, the generated IBAN passes the ISO 13616 mod-97 check."""
    compact = gen.make_iban(bank, branch, account)

    assert len(compact) == 24
    assert mod97_remainder(compact) == 1
    assert gen.iban_check_digits("ES", compact[4:]) == compact[2:4]
    assert iban_check_digits("ES", compact[4:]) == compact[2:4]


@settings(max_examples=200, deadline=None)
@given(
    bank=st.text(alphabet=DIGITS, min_size=4, max_size=4),
    branch=st.text(alphabet=DIGITS, min_size=4, max_size=4),
    account=st.text(alphabet=DIGITS, min_size=10, max_size=10),
)
def test_make_iban_national_digits_never_correct(bank: str, branch: str, account: str) -> None:
    """Whatever the digits, the national check digits carried by the IBAN are the wrong ones."""
    compact = gen.make_iban(bank, branch, account)

    assert compact[12:14] == gen.wrong_national_dc(bank, branch, account)
    assert compact[12:14] != spanish_national_dc(bank, branch, account)
    assert not spanish_national_dc_ok(compact)
