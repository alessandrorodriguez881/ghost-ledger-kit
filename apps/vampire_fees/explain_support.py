"""Fallback templates and the hallucinating stub client for the explanation layer (design 6).

The app never calls an LLM itself: it hands `ledger_kit.explainer.explain_with_meta` a template
per detector and, when the user asks for it, a stub client that invents a number.
The stub is copied from zombie_subscriptions because the library does not offer one (C1).
"""

from types import SimpleNamespace
from typing import Any, Self

from ledger_kit.models import Alert

# Fallback text per detector (REQ-VF-36). `{key:money}` is formatted with format_amount,
# `{key:pct}` as a percentage, `{key}` is plain text and `{source_refs}` is the comma-joined list
# of cited rows. Every placeholder is a key of Alert.data; no digit is written into a template.
TEMPLATES: dict[str, str] = {
    "vf.recurring_fee": (
        "{counterparty} charged you a {interval_type} fee of {current_amount:money} "
        "({description}), {charge_count} times between {first_charge_date} and "
        "{last_charge_date}, about {yearly_cost:money} per year. Source: {source_refs}."
    ),
    "vf.fee_increase": (
        "The {counterparty} fee ({description}) rose from {old_amount:money} to "
        "{new_amount:money} on {increase_date}, an increase of {increase_percent:pct}, "
        "adding {extra_cost_per_year:money} to the yearly cost. Source: {source_refs}."
    ),
    "vf.overdraft_cost": (
        "Your overdraft cost {total:money} between {first_charge_date} and {last_charge_date}: "
        "{interest_count} interest charges totalling {interest_total:money} and {fee_count} fees "
        "totalling {fee_total:money}. Source: {source_refs}."
    ),
    "vf.fee_summary": (
        "Between {first_date} and {last_date} ({span_days} days) your statement shows "
        "{fee_count} bank fees totalling {total_fees:money}, about {yearly_equivalent:money} "
        "per year. Source: {source_refs}."
    ),
}
# Variant for a statement shorter than SUMMARY_MIN_SPAN_DAYS: there is no yearly_equivalent key.
FEE_SUMMARY_NO_YEARLY_TEMPLATE: str = (
    "Between {first_date} and {last_date} ({span_days} days) your statement shows "
    "{fee_count} bank fees totalling {total_fees:money}. Source: {source_refs}."
)
# The comparison with the Banco de España declarations (public-fees REQ-PF-18): two short
# sentences that state counts, a median and a maximum, draw no conclusion and advise nothing
# (Finance Rule 8). Every placeholder is a peer_ key of Alert.data or `yearly_cost`; the date is
# ISO so the number guard reads it as a date. The wording is the reviewer's decision Q9.
PEER_SENTENCE: str = (
    "Of {peer_account_count} {peer_account_type_label} accounts that declared an annual "
    "{peer_service_label} fee to the Banco de España on {peer_declaration_date}, "
    "{peer_lower_count} charge less than this fee costs a year ({yearly_cost:money}). "
    "{peer_zero_count} charge nothing; the median is {peer_median_yearly:money} "
    "and the highest {peer_max_yearly:money}."
)
# Today's recurring-fee text with the comparison before `Source: {source_refs}.`, which stays the
# tail so that `chip_source_template` keeps rewriting the refs.
RECURRING_FEE_WITH_PEERS_TEMPLATE: str = (
    "{counterparty} charged you a {interval_type} fee of {current_amount:money} "
    "({description}), {charge_count} times between {first_charge_date} and "
    "{last_charge_date}, about {yearly_cost:money} per year. "
    + PEER_SENTENCE
    + " Source: {source_refs}."
)
# The one key that marks an alert carrying the peer fields (they appear together or not at all).
PEER_MARKER_KEY: str = "peer_median_yearly"


def template_for(alert: Alert) -> str:
    """Return the fallback template of an alert; the summary and peer variants follow its data."""
    if alert.detector == "vf.recurring_fee" and PEER_MARKER_KEY in alert.data:
        return RECURRING_FEE_WITH_PEERS_TEMPLATE
    if alert.detector == "vf.fee_summary" and "yearly_equivalent" not in alert.data:
        return FEE_SUMMARY_NO_YEARLY_TEMPLATE
    return TEMPLATES[alert.detector]


class HallucinatingStubClient:
    """OpenAI-shaped client whose answer always contains a number that is in no alert.

    Used by the "Simulate a hallucinating LLM" toggle to show the number guard at work.
    """

    INJECTED_NUMBER: str = "99999.99"  # absent from every real alert and ledger row

    @property
    def chat(self) -> Self:
        """Mirror `client.chat`."""
        return self

    @property
    def completions(self) -> Self:
        """Mirror `client.chat.completions`."""
        return self

    def create(self, *, messages: Any, **_kwargs: Any) -> SimpleNamespace:
        """Return a response whose text states the injected number."""
        fake_text = f"This fee costs you {self.INJECTED_NUMBER} EUR per year."
        message = SimpleNamespace(content=fake_text)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])
