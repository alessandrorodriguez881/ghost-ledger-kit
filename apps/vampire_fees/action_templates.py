"""Exorcise templates of Vampire Fees: the complaint to the bank for each fee alert type (EX5).

One fixed complaint in English and Spanish, filled by ``ledger_kit.actions`` from the alert data
and the cited fee rows; no language model. It is addressed to the customer service department of
the bank (Servicio de Atención al Cliente), lists every cited fee row, asks to waive or refund the
fees, and ends with one line about the Banco de España complaints service. It names no deadline and
no article of any law; the text holds no digit and no month name, and the sender's details are
placeholders in square brackets. ``vf.fee_summary`` has no template.
"""

from collections.abc import Mapping

import pandas as pd

from ledger_kit.actions import ActionTemplate, fill, row_lines
from ledger_kit.models import Alert

BANK_PLACEHOLDER: str = "[Bank name]"

COMPLAINT_EN: str = (
    "To: Customer Service Department (Servicio de Atención al Cliente), {bank}\n"
    "Subject: Bank fee complaint\n\n"
    "I complain about these fees on [Your account number]:\n"
    "{fee_lines}\n"
    "{summary}\n"
    "Please waive and refund these fees. Reply in writing.\n\n"
    "[Your name]\n"
    "[Your ID number]\n\n"
    "If this is not resolved, I can go to the Banco de España complaints service."
)
COMPLAINT_ES: str = (
    "A la atención de: Servicio de Atención al Cliente, {bank}\n"
    "Asunto: Reclamación de comisiones\n\n"
    "Reclamo estas comisiones en mi cuenta [Su número de cuenta]:\n"
    "{fee_lines}\n"
    "{summary}\n"
    "Les pido anular y reintegrar estas comisiones. Respondan por escrito.\n\n"
    "[Su nombre]\n"
    "[Su DNI/NIE]\n\n"
    "Si no se resuelve, puedo acudir al Servicio de Reclamaciones del Banco de España."
)

# The sentence about the figures of the alert, per detector and language.
SUMMARY: dict[str, dict[str, str]] = {
    "vf.recurring_fee": {
        "en": (
            "{description}: charged {charge_count:times} between {first_charge_date} and "
            "{last_charge_date}, about {yearly_cost:money} per year."
        ),
        "es": (
            "{description}: cobrada {charge_count:times} entre {first_charge_date} y "
            "{last_charge_date}, unos {yearly_cost:money} al año."
        ),
    },
    "vf.fee_increase": {
        "en": (
            "The fee ({description}) rose from {old_amount:money} to {new_amount:money} on "
            "{increase_date}, an increase of {increase_percent:pct}, adding "
            "{extra_cost_per_year:money} per year."
        ),
        "es": (
            "La comisión ({description}) subió de {old_amount:money} a {new_amount:money} el "
            "{increase_date}, un aumento del {increase_percent:pct}, lo que añade "
            "{extra_cost_per_year:money} al año."
        ),
    },
    "vf.overdraft_cost": {
        "en": (
            "Overdraft interest was charged {interest_count:times} ({interest_total:money}) and "
            "overdraft fees {fee_count:times} ({fee_total:money}), in total {total:money}."
        ),
        "es": (
            "Los intereses por descubierto se cobraron {interest_count:times} "
            "({interest_total:money}) y las comisiones por descubierto {fee_count:times} "
            "({fee_total:money}), en total {total:money}."
        ),
    },
}


def bank_name(alert: Alert, rows: pd.DataFrame) -> str:
    """Return the bank to address: the alert's counterparty, else a cited row's, else a stub."""
    name = alert.data.get("counterparty")
    if isinstance(name, str) and name.strip():
        return name.strip()
    if "counterparty" in rows.columns:
        for cell in rows["counterparty"]:
            if isinstance(cell, str) and cell.strip():
                return cell.strip()
    return BANK_PLACEHOLDER


def vampire_extras(alert: Alert, rows: pd.DataFrame, language: str) -> Mapping[str, str]:
    """Return the bank, one 'date: amount' line per cited fee row and the sentence of figures."""
    return {
        "bank": bank_name(alert, rows),
        "fee_lines": row_lines(rows),
        "summary": fill(SUMMARY[alert.detector][language], alert, language),
    }


TEMPLATES: dict[str, ActionTemplate] = {
    detector: ActionTemplate(
        "complain_to_bank", {"en": COMPLAINT_EN, "es": COMPLAINT_ES}, vampire_extras
    )
    for detector in SUMMARY
}


def action_for(alert: Alert) -> ActionTemplate | None:
    """Return the Exorcise template of an alert type, or None when the type has none."""
    return TEMPLATES.get(alert.detector)
