"""Exorcise templates of Zombie Subscriptions: the action to take for each alert type (EX3).

Fixed texts in English and Spanish, filled by ``ledger_kit.actions`` from the alert data and the
cited rows; no language model. A text holds no digit, no month name and no deadline; the sender's
details are placeholders in square brackets. The CPI sentence of a price increase is the one the
card shows (``explain_support``), in the language of the draft.
"""

from collections.abc import Mapping

import pandas as pd

from apps.zombie_subscriptions.explain_support import (
    CPI_SENTENCE_LAG,
    cpi_sentence_template,
)
from ledger_kit.actions import ActionTemplate, fill, row_lines
from ledger_kit.models import Alert

# Spanish form of the interval names of the detectors; English keeps the name as it is.
INTERVAL_TEXT: dict[str, dict[str, str]] = {
    "en": {},
    "es": {
        "weekly": "semanal",
        "monthly": "mensual",
        "quarterly": "trimestral",
        "yearly": "anual",
    },
}

# The Spanish forms of the CPI sentence of the card: same placeholders, same figures.
CPI_SENTENCE_ES: str = (
    "El precio subió {price_change_percent:pct} mientras que el IPC de España (serie INE "
    "{cpi_series}) varió {cpi_change_percent:pct} entre {cpi_start_month} y {cpi_end_month}."
)
CPI_SENTENCE_LAG_ES: str = (
    "El precio subió {price_change_percent:pct} entre {price_start_month} y {price_end_month}, "
    "mientras que el IPC de España (serie INE {cpi_series}) varió {cpi_change_percent:pct} "
    "entre {cpi_start_month} y {cpi_end_month}, con el último mes publicado disponible."
)

CHARGES_AFTER_CANCELLATION = ActionTemplate(
    "refund_after_cancellation",
    {
        "en": (
            "Subject: Refund request: charges after cancellation\n\n"
            "Dear {counterparty},\n\n"
            "I cancelled my subscription on {cancellation_date}. You have charged me "
            "{post_cancellation_count:times} since then, totalling {total_charged_after:money}:\n"
            "{charge_lines}\n"
            "Please refund these charges and confirm in writing that my subscription is "
            "closed.\n\n"
            "[Your name]\n"
            "[Your customer number]\n\n"
            "---\n"
            "Request to my bank, to send only if the refund does not arrive:\n"
            "Dear [Bank name], please dispute the charges by {counterparty} listed above. They "
            "were made after I cancelled on {cancellation_date}. Please return the money to my "
            "account [Your account number].\n"
            "[Your name]"
        ),
        "es": (
            "Asunto: Solicitud de reembolso: cobros posteriores a la cancelación\n\n"
            "Estimados señores de {counterparty}:\n\n"
            "Cancelé mi suscripción el {cancellation_date}. Desde entonces me han cobrado "
            "{post_cancellation_count:times}, en total {total_charged_after:money}:\n"
            "{charge_lines}\n"
            "Les ruego que reembolsen estos cobros y que confirmen por escrito que mi "
            "suscripción está cancelada.\n\n"
            "[Su nombre]\n"
            "[Su número de cliente]\n\n"
            "---\n"
            "Solicitud a mi banco, solo si no llega el reembolso:\n"
            "Estimados señores de [Nombre del banco]: les pido que impugnen los cobros de "
            "{counterparty} indicados arriba. Se hicieron después de cancelar, el "
            "{cancellation_date}. Les ruego que devuelvan el dinero a mi cuenta "
            "[Su número de cuenta].\n"
            "[Su nombre]"
        ),
    },
)

DUPLICATE_SUBSCRIPTION = ActionTemplate(
    "cancel_duplicate_account",
    {
        "en": (
            "Subject: Request to cancel a duplicate account\n\n"
            "Dear customer service,\n\n"
            "I have {series_count} separate accounts for {canonical_name}: {account_names}. "
            "Together they cost {yearly_cost:money} per year. I need only one. Please cancel "
            "the duplicate account, stop its charges and confirm in writing which account "
            "stays active.\n\n"
            "[Your name]\n"
            "[Your customer number]"
        ),
        "es": (
            "Asunto: Solicitud de cancelación de una cuenta duplicada\n\n"
            "Estimados señores del servicio de atención al cliente:\n\n"
            "Tengo {series_count} cuentas distintas de {canonical_name}: {account_names}. "
            "Juntas cuestan {yearly_cost:money} al año. Solo necesito una. Les ruego que "
            "cancelen la cuenta duplicada, detengan sus cobros y confirmen por escrito qué "
            "cuenta sigue activa.\n\n"
            "[Su nombre]\n"
            "[Su número de cliente]"
        ),
    },
)

PRICE_INCREASE = ActionTemplate(
    "keep_old_price_or_cancel",
    {
        "en": (
            "Subject: Price increase: keep my previous price or cancel\n\n"
            "Dear {counterparty},\n\n"
            "Your {interval_text} charge rose from {old_median_amount:money} to "
            "{new_amount:money}, adding {extra_cost_per_year:money} to my yearly cost."
            "{cpi_sentence}\n"
            "Please keep my previous price of {old_median_amount:money}. If you cannot, please "
            "cancel my subscription and confirm the cancellation in writing.\n\n"
            "[Your name]\n"
            "[Your customer number]"
        ),
        "es": (
            "Asunto: Subida de precio: mantener mi precio anterior o cancelar\n\n"
            "Estimados señores de {counterparty}:\n\n"
            "Su cobro {interval_text} subió de {old_median_amount:money} a {new_amount:money}, "
            "lo que añade {extra_cost_per_year:money} a mi coste anual.{cpi_sentence}\n"
            "Les ruego que mantengan mi precio anterior de {old_median_amount:money}. Si no es "
            "posible, cancelen mi suscripción y confirmen la cancelación por escrito.\n\n"
            "[Su nombre]\n"
            "[Su número de cliente]"
        ),
    },
)

FREE_TRIAL_TO_PAID = ActionTemplate(
    "cancel_after_trial",
    {
        "en": (
            "Subject: Request to cancel my subscription\n\n"
            "Dear {counterparty},\n\n"
            "My free trial ({trial_amount:money}) became a paid subscription at "
            "{first_paid_amount:money}. I do not want to continue. Please cancel my "
            "subscription now, make no further charges and confirm the cancellation in "
            "writing.\n\n"
            "[Your name]\n"
            "[Your customer number]"
        ),
        "es": (
            "Asunto: Solicitud de cancelación de mi suscripción\n\n"
            "Estimados señores de {counterparty}:\n\n"
            "Mi prueba gratuita ({trial_amount:money}) pasó a ser una suscripción de pago de "
            "{first_paid_amount:money}. No quiero continuar. Les ruego que cancelen mi "
            "suscripción ahora, no hagan más cobros y confirmen la cancelación por "
            "escrito.\n\n"
            "[Su nombre]\n"
            "[Su número de cliente]"
        ),
    },
)

RECURRING_CHARGE = ActionTemplate(
    "cancel_subscription",
    {
        "en": (
            "Subject: Request to cancel my subscription\n\n"
            "Dear {counterparty},\n\n"
            "I am charged {current_amount:money} ({interval_text}), about {yearly_cost:money} "
            "per year. I want to cancel. Please cancel my subscription, make no further "
            "charges and confirm the end date in writing.\n\n"
            "[Your name]\n"
            "[Your customer number]"
        ),
        "es": (
            "Asunto: Solicitud de cancelación de mi suscripción\n\n"
            "Estimados señores de {counterparty}:\n\n"
            "Me cobran {current_amount:money} ({interval_text}), unos {yearly_cost:money} al "
            "año. Quiero cancelar. Les ruego que cancelen mi suscripción, no hagan más cobros "
            "y confirmen por escrito la fecha de fin.\n\n"
            "[Su nombre]\n"
            "[Su número de cliente]"
        ),
    },
)


def _cpi_sentence(alert: Alert, language: str) -> str:
    """Return ' ' plus the CPI sentence of the card in this language, or '' without CPI keys."""
    english = cpi_sentence_template(alert)
    if english is None:
        return ""
    if language == "es":
        template = CPI_SENTENCE_LAG_ES if english is CPI_SENTENCE_LAG else CPI_SENTENCE_ES
    else:
        template = english
    return " " + fill(template, alert, language)


def zombie_extras(alert: Alert, rows: pd.DataFrame, language: str) -> Mapping[str, str]:
    """Return the computed placeholders of every zombie template for this alert and language."""
    data = alert.data
    interval = str(data.get("interval_type", ""))
    names = data.get("series_counterparties") or []
    listed = alert.detector == "zs.charges_after_cancellation"
    return {
        "charge_lines": row_lines(rows) if listed else "",
        "interval_text": INTERVAL_TEXT[language].get(interval, interval),
        "account_names": ", ".join(str(name) for name in names),
        "cpi_sentence": _cpi_sentence(alert, language),
    }


_WITH_EXTRAS: dict[str, ActionTemplate] = {
    "zs.charges_after_cancellation": CHARGES_AFTER_CANCELLATION,
    "zs.duplicate_subscription": DUPLICATE_SUBSCRIPTION,
    "zs.price_increase": PRICE_INCREASE,
    "zs.free_trial_to_paid": FREE_TRIAL_TO_PAID,
    "zs.recurring_charge": RECURRING_CHARGE,
}

# Every template gets the same computed placeholders; a template uses the ones it names.
TEMPLATES: dict[str, ActionTemplate] = {
    detector: ActionTemplate(template.name, template.texts, zombie_extras)
    for detector, template in _WITH_EXTRAS.items()
}


def action_for(alert: Alert) -> ActionTemplate | None:
    """Return the Exorcise template of an alert type, or None when the type has none."""
    return TEMPLATES.get(alert.detector)
