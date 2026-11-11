"""The proof of Exorcise over the three demos: every alert, both languages (EX6, REQ-EX-12).

For each alert of the Zombie, Phantom and Vampire demos: a draft exists exactly for the alert types
that have a template, the number guard passes it, it is under 150 words, it holds the figures of
the alert as the card writes them, and it holds no IBAN-shaped token and none of the full IBANs of
the demo files. Nothing here calls a model or the network; the data is the synthetic demo data.
"""

import csv
import re
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

import pytest
from judge_path_support import Case, cases_of

from apps.phantom_invoices.action_templates import action_for as phantom_action
from apps.vampire_fees.action_templates import action_for as vampire_action
from apps.zombie_subscriptions.action_templates import action_for as zombie_action
from ledger_kit.actions import MAX_DRAFT_WORDS, build_draft, row_lines, word_count
from ledger_kit.explainer import check_figures
from ledger_kit.models import Alert
from ledger_kit.utils.money import format_amount

ROOT = Path(__file__).resolve().parents[1]
PHANTOM_DEMO = ROOT / "data" / "samples" / "phantom_demo"
LANGUAGES = ("en", "es")
PREFIXES = ("zs", "pi", "vf")

ACTION_FOR: dict[str, Callable[[Alert], object]] = {
    "zs": zombie_action,
    "pi": phantom_action,
    "vf": vampire_action,
}
# The alert types that have a template, written here independently of the app modules.
TYPES_WITH_TEMPLATE = {
    "zs": {
        ("zs.charges_after_cancellation", None),
        ("zs.duplicate_subscription", None),
        ("zs.price_increase", None),
        ("zs.free_trial_to_paid", None),
        ("zs.recurring_charge", None),
    },
    "pi": {
        ("pi.duplicate_invoice", "same_number"),
        ("pi.duplicate_invoice", "near_identical_number"),
        ("pi.duplicate_invoice", "same_total_close_dates"),
        ("pi.iban_change", "invoice_iban_differs_from_master"),
        ("pi.iban_change", "payment_to_non_master_iban"),
        ("pi.vat_error", "vat_amount_mismatch"),
        ("pi.vat_error", "total_mismatch"),
    },
    "vf": {
        ("vf.recurring_fee", None),
        ("vf.fee_increase", None),
        ("vf.overdraft_cost", None),
    },
}
IBAN_SHAPED = re.compile(r"[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,}")
CASES = [case for prefix in PREFIXES for case in cases_of(prefix)]

# Per alert type: the data keys whose amount, and whose text, a draft must hold as the card does.
MONEY_KEYS: dict[str, tuple[str, ...]] = {
    "zs.charges_after_cancellation": ("total_charged_after",),
    "zs.duplicate_subscription": ("yearly_cost",),
    "zs.price_increase": ("old_median_amount", "new_amount", "extra_cost_per_year"),
    "zs.free_trial_to_paid": ("trial_amount", "first_paid_amount"),
    "zs.recurring_charge": ("current_amount", "yearly_cost"),
    "vf.recurring_fee": ("yearly_cost",),
    "vf.fee_increase": ("old_amount", "new_amount", "extra_cost_per_year"),
    "vf.overdraft_cost": ("total", "interest_total", "fee_total"),
}
TEXT_KEYS: dict[str, tuple[str, ...]] = {
    "zs.charges_after_cancellation": ("cancellation_date",),
    "zs.duplicate_subscription": ("canonical_name",),
    "vf.recurring_fee": ("first_charge_date", "last_charge_date"),
    "vf.fee_increase": ("increase_date",),
}
ROW_LISTED = {
    "zs.charges_after_cancellation",
    "vf.recurring_fee",
    "vf.fee_increase",
    "vf.overdraft_cost",
}


def _id(case: Case) -> str:
    variant = case.alert.data.get("variant", "")
    return f"{case.prefix}-{case.alert.detector}-{variant}-{case.alert.id[:6]}"


def _has_template(case: Case) -> bool:
    variant = case.alert.data.get("variant") if case.prefix == "pi" else None
    return (case.alert.detector, variant) in TYPES_WITH_TEMPLATE[case.prefix]


def _money(value: object) -> str:
    return format_amount(Decimal(str(value)))


def _figures(alert: Alert) -> list[str]:
    """The figures that a draft of this alert type must hold, written as the card writes them."""
    d, name = alert.data, alert.detector
    if name == "pi.duplicate_invoice":
        return [_money(total) for total in d["totals"]] + list(d["invoice_numbers"])
    if name == "pi.iban_change":
        new_account = d.get("invoice_iban_masked", d.get("payment_iban_masked"))
        return [d["master_iban_masked"], new_account]
    if name == "pi.vat_error":
        keys = ("vat_amount", "expected_vat_amount", "base_amount")
        if d["variant"] == "total_mismatch":
            keys = ("total", "expected_total", "base_amount", "vat_amount")
        return [_money(d[key]) for key in keys]
    return [_money(d[key]) for key in MONEY_KEYS[name]] + [
        str(d[key]) for key in TEXT_KEYS.get(name, ())
    ]


def _demo_ibans() -> set[str]:
    """Every full IBAN of the phantom demo files, spaces removed."""
    found: set[str] = set()
    for name in ("suppliers.csv", "invoices.csv", "payments.csv"):
        with (PHANTOM_DEMO / name).open(encoding="utf-8", newline="") as handle:
            found |= {
                row["iban"].replace(" ", "").upper()
                for row in csv.DictReader(handle)
                if row.get("iban")
            }
    return found


def _draft(case: Case, language: str) -> str | None:
    template = ACTION_FOR[case.prefix](case.alert)
    assert template is not None
    return build_draft(case.alert, case.rows, template, language, row_columns=case.columns)


def test_the_three_demos_are_not_empty() -> None:
    assert {case.prefix for case in CASES} == set(PREFIXES)
    assert len(cases_of("zs")) == 19 and len(cases_of("vf")) == 6


@pytest.mark.parametrize("case", CASES, ids=_id)
def test_a_template_exists_exactly_for_the_alert_types_that_have_one(case: Case) -> None:
    template = ACTION_FOR[case.prefix](case.alert)

    assert (template is not None) is _has_template(case)


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("case", [c for c in CASES if _has_template(c)], ids=_id)
def test_every_demo_draft_passes_the_guard_and_is_short(case: Case, language: str) -> None:
    draft = _draft(case, language)

    assert draft is not None, f"{_id(case)} {language}: the draft was rejected"
    assert check_figures(draft, case.alert, case.rows, case.columns) == (True, ())
    words = word_count(draft)
    assert words < MAX_DRAFT_WORDS, f"{_id(case)} {language}: {words} words"
    assert "{" not in draft and "}" not in draft  # no placeholder left unfilled
    assert re.search(r"\[[^\]]+\]", draft)  # the sender's details are placeholders


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("case", [c for c in CASES if _has_template(c)], ids=_id)
def test_every_demo_draft_holds_the_figures_of_its_alert(case: Case, language: str) -> None:
    draft = _draft(case, language)

    assert draft is not None
    for figure in _figures(case.alert):
        assert figure in draft, f"{_id(case)} {language}: {figure!r} is not in the draft"
    if case.alert.detector in ROW_LISTED:
        for line in row_lines(case.rows).splitlines():  # each cited charge or fee row
            assert line in draft


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("case", [c for c in CASES if _has_template(c)], ids=_id)
def test_no_demo_draft_holds_an_iban(case: Case, language: str) -> None:
    draft = _draft(case, language)
    squashed = (draft or "").replace(" ", "").upper()

    assert draft is not None and not IBAN_SHAPED.search(draft)
    assert not [iban for iban in _demo_ibans() if iban in squashed]


def test_the_zombie_price_increase_with_cpi_carries_the_cards_sentence_in_both_languages() -> None:
    with_cpi = [
        case
        for case in cases_of("zs")
        if case.alert.detector == "zs.price_increase" and "cpi_change_percent" in case.alert.data
    ]
    if not with_cpi:
        pytest.skip("no price increase with CPI context in the zombie demo")
    markers = {"en": "Spanish CPI (INE series", "es": "IPC de España (serie INE"}

    for case in with_cpi:
        for language, marker in markers.items():
            draft = _draft(case, language)
            assert draft is not None and marker in draft
            assert case.alert.data["cpi_series"] in draft


@pytest.mark.parametrize("language", LANGUAGES)
def test_drafts_of_one_alert_are_the_same_on_every_run(language: str) -> None:
    for case in (c for c in CASES if _has_template(c)):
        assert _draft(case, language) == _draft(case, language)
