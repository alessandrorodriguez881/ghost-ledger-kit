"""Fallback templates and the hallucinating stub client for the explanation layer (design §9).

The app never calls an LLM itself: it hands `ledger_kit.explainer.explain_with_meta` a template
per detector and, when the user asks for it, a stub client that invents a number.
"""

from types import SimpleNamespace
from typing import Any, Self

# Fallback text per detector (REQ-ZS-34). `{key:money}` is formatted with format_amount,
# `{key}` is plain text and `{source_refs}` is the comma-joined list of cited rows.
TEMPLATES: dict[str, str] = {
    "zs.recurring_charge": (
        "You have been charged {charge_count} times by {counterparty} at a current price of "
        "{current_amount:money} ({interval_type}), totalling approximately {yearly_cost:money} "
        "per year. Source: {source_refs}."
    ),
    "zs.price_increase": (
        "The {counterparty} charge increased from {old_median_amount:money} to "
        "{new_amount:money}, adding {extra_cost_per_year:money} to your yearly cost. "
        "Source: {source_refs}."
    ),
    "zs.duplicate_subscription": (
        "You are paying for {canonical_name} through {series_count} separate accounts, "
        "totalling {yearly_cost:money} per year. Source: {source_refs}."
    ),
    "zs.free_trial_to_paid": (
        "Your {counterparty} free trial ({trial_amount:money}) converted to a paid subscription "
        "at {first_paid_amount:money}. Yearly cost: {yearly_cost:money}. Source: {source_refs}."
    ),
    "zs.charges_after_cancellation": (
        "{counterparty} charged you {post_cancellation_count} time(s) totalling "
        "{total_charged_after:money} after your cancellation on {cancellation_date}. "
        "Source: {source_refs}."
    ),
}


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
        fake_text = f"This subscription costs you {self.INJECTED_NUMBER} EUR per year."
        message = SimpleNamespace(content=fake_text)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])
