"""Fallback templates and the hallucinating stub client for the explanation layer (design §9).

The app never calls an LLM itself: it hands `ledger_kit.explainer.explain_with_meta` a template
per detector and, when the user asks for it, a stub client that invents a number.
"""

from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any, Self

from ledger_kit.models import Alert

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
        "{counterparty} charged you {post_cancellation_count:times} totalling "
        "{total_charged_after:money} after your cancellation on {cancellation_date}. "
        "Source: {source_refs}."
    ),
}

# --- CPI comparison of a price increase (public-cpi REQ-CPI-17) --------------------------------
# One neutral sentence: it states both figures and their months and draws no conclusion
# (Finance Rule 8). "changed by" for the CPI because an index can fall.
CPI_SENTENCE: str = (
    "The price rose {price_change_percent:pct} while the Spanish CPI (INE series {cpi_series}) "
    "changed by {cpi_change_percent:pct} from {cpi_start_month} to {cpi_end_month}."
)
# Variant used when a CPI month differs from the price month it answers (the one-month lag of
# CPI_MAX_LAG_MONTHS, or a gap fallback): both pairs of months are named.
CPI_SENTENCE_LAG: str = (
    "The price rose {price_change_percent:pct} from {price_start_month} to {price_end_month}, "
    "while the Spanish CPI (INE series {cpi_series}) changed by {cpi_change_percent:pct} from "
    "{cpi_start_month} to {cpi_end_month}, using the latest published CPI month available."
)
_PRICE_INCREASE_HEAD: str = (
    "The {counterparty} charge increased from {old_median_amount:money} to "
    "{new_amount:money}, adding {extra_cost_per_year:money} to your yearly cost. "
)
PRICE_INCREASE_WITH_CPI_TEMPLATE: str = (
    _PRICE_INCREASE_HEAD + CPI_SENTENCE + " Source: {source_refs}."
)
PRICE_INCREASE_WITH_CPI_LAG_TEMPLATE: str = (
    _PRICE_INCREASE_HEAD + CPI_SENTENCE_LAG + " Source: {source_refs}."
)


def has_cpi_context(data: Mapping[str, Any]) -> bool:
    """True when the alert data carries the CPI keys (they are always added together)."""
    return "cpi_change_percent" in data


def cpi_uses_lag(data: Mapping[str, Any]) -> bool:
    """True when a CPI month used differs from the price month it answers."""
    return data.get("cpi_start_month") != data.get("price_start_month") or data.get(
        "cpi_end_month"
    ) != data.get("price_end_month")


def cpi_sentence_template(alert: Alert) -> str | None:
    """The CPI sentence template of a price-increase alert with CPI keys, else None."""
    if alert.detector != "zs.price_increase" or not has_cpi_context(alert.data):
        return None
    return CPI_SENTENCE_LAG if cpi_uses_lag(alert.data) else CPI_SENTENCE


def template_for(alert: Alert) -> str:
    """Fallback template of an alert; the CPI variants only for a price increase with CPI."""
    sentence = cpi_sentence_template(alert)
    if sentence is None:
        return TEMPLATES[alert.detector]
    if sentence is CPI_SENTENCE_LAG:
        return PRICE_INCREASE_WITH_CPI_LAG_TEMPLATE
    return PRICE_INCREASE_WITH_CPI_TEMPLATE


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
