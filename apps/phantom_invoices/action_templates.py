"""Exorcise templates of Phantom Invoices: the action to take for each alert type (EX4).

Fixed texts in English and Spanish, filled by ``ledger_kit.actions`` from ``Alert.data``; no
language model. A text holds no digit, no month name and no deadline; the sender's details are
placeholders in square brackets. A full IBAN is never in ``Alert.data`` (the detectors keep only
the masked form), so a draft can show nothing else. The phone script of an IBAN change says to use
a contact already on file and never a phone number or e-mail address from the invoice or from the
message that announced the change.
"""

from collections.abc import Mapping
from decimal import Decimal

import pandas as pd

from ledger_kit.actions import ActionTemplate
from ledger_kit.models import Alert
from ledger_kit.utils.money import format_amount

# With exactly this many invoices on one date the span says "both" / "ambas", not "all" /
# "todas" (REQ-PI-72); three or more keep "all" / "todas".
PAIR_COUNT: int = 2

DUPLICATE_INVOICE_TEXTS: dict[str, str] = {
    "en": (
        "Subject: Duplicate invoice: please cancel it or issue a credit note\n\n"
        "Dear {supplier_name},\n\n"
        "We received {invoice_count} invoices that look like duplicates, {date_span}:\n"
        "{invoice_lines}\n"
        "Please cancel the duplicate or issue a credit note (factura rectificativa) for it, "
        "and confirm in writing which invoice remains payable. We will pay only that one.\n\n"
        "[Your name]\n"
        "[Company name]"
    ),
    "es": (
        "Asunto: Factura duplicada: anulación o factura rectificativa\n\n"
        "Estimados señores de {supplier_name}:\n\n"
        "Hemos recibido {invoice_count} facturas que parecen duplicadas, {date_span}:\n"
        "{invoice_lines}\n"
        "Les rogamos que anulen la duplicada o emitan una factura rectificativa, y que "
        "confirmen por escrito cuál queda pendiente de pago. Solo pagaremos esa.\n\n"
        "[Su nombre]\n"
        "[Nombre de la empresa]"
    ),
}

# The hold note and the phone script: the first sentence is the finding of the variant.
IBAN_FINDING: dict[str, dict[str, str]] = {
    "invoice_iban_differs_from_master": {
        "en": (
            "Invoice {invoice_number} from {supplier_name} names the account "
            "{invoice_iban_masked}. The account on file is {master_iban_masked}."
        ),
        "es": (
            "La factura {invoice_number} de {supplier_name} indica la cuenta "
            "{invoice_iban_masked}. La cuenta registrada es {master_iban_masked}."
        ),
    },
    "payment_to_non_master_iban": {
        "en": (
            "A payment of {payment_amount:money} on {payment_date} to {supplier_name} went to "
            "the account {payment_iban_masked}. The account on file is {master_iban_masked}."
        ),
        "es": (
            "Un pago de {payment_amount:money} el {payment_date} a {supplier_name} fue a la "
            "cuenta {payment_iban_masked}. La cuenta registrada es {master_iban_masked}."
        ),
    },
}
IBAN_BODY: dict[str, str] = {
    "en": (
        "\nHold every payment to {supplier_name} until the change is verified by phone and "
        "approved by [Approver name]. Date: [Date]\n\n"
        "PHONE SCRIPT\n"
        "Call a contact you already have on file for {supplier_name}. Never use a phone number "
        "or e-mail address from the invoice or from the message that announced the change.\n"
        'Say: "We received a request to change your bank account. Did you send it?"\n'
        "If yes, ask for the last four digits of the new account and note who confirmed.\n"
        "If no, do not pay and tell [Security contact]."
    ),
    "es": (
        "\nRetener todo pago a {supplier_name} hasta que el cambio se verifique por teléfono y "
        "lo apruebe [Nombre del aprobador]. Fecha: [Fecha]\n\n"
        "GUION TELEFÓNICO\n"
        "Llame a un contacto que ya tenga registrado de {supplier_name}. No use nunca un "
        "teléfono ni un correo que figure en la factura o en el mensaje que anunció el cambio.\n"
        'Diga: "Hemos recibido una solicitud de cambio de su cuenta bancaria. ¿La envió '
        'usted?"\n'
        "Si responde que sí, pida las últimas cuatro cifras de la nueva cuenta y anote quién "
        "lo confirmó.\n"
        "Si responde que no, no pague e informe a [Contacto de seguridad]."
    ),
}
IBAN_HEAD: dict[str, str] = {"en": "INTERNAL HOLD NOTE\n", "es": "NOTA INTERNA DE RETENCIÓN\n"}

VAT_AMOUNT_TEXTS: dict[str, str] = {
    "en": (
        "Subject: Request for a corrected invoice {invoice_number}\n\n"
        "Dear {supplier_name},\n\n"
        "Invoice {invoice_number} states VAT of {vat_amount:money}, but {vat_rate} % of the "
        "base {base_amount:money} is {expected_vat_amount:money}. Please issue a corrected "
        "invoice (factura rectificativa) and confirm in writing. We will hold payment until we "
        "receive it.\n\n"
        "[Your name]\n"
        "[Company name]"
    ),
    "es": (
        "Asunto: Solicitud de factura rectificativa {invoice_number}\n\n"
        "Estimados señores de {supplier_name}:\n\n"
        "La factura {invoice_number} indica un IVA de {vat_amount:money}, pero el {vat_rate} % "
        "de la base {base_amount:money} es {expected_vat_amount:money}. Les rogamos que "
        "emitan una factura rectificativa y lo confirmen por escrito. Retendremos el pago "
        "hasta recibirla.\n\n"
        "[Su nombre]\n"
        "[Nombre de la empresa]"
    ),
}
TOTAL_MISMATCH_TEXTS: dict[str, str] = {
    "en": (
        "Subject: Request for a corrected invoice {invoice_number}\n\n"
        "Dear {supplier_name},\n\n"
        "Invoice {invoice_number} states a total of {total:money}, but base {base_amount:money} "
        "plus VAT {vat_amount:money} plus surcharge {surcharge_amount:money} minus withholding "
        "{withholding_amount:money} is {expected_total:money}. Please issue a corrected invoice "
        "(factura rectificativa) and confirm in writing. We will hold payment until we receive "
        "it.\n\n"
        "[Your name]\n"
        "[Company name]"
    ),
    "es": (
        "Asunto: Solicitud de factura rectificativa {invoice_number}\n\n"
        "Estimados señores de {supplier_name}:\n\n"
        "La factura {invoice_number} indica un total de {total:money}, pero la base "
        "{base_amount:money} más IVA {vat_amount:money} más recargo {surcharge_amount:money} "
        "menos retención {withholding_amount:money} es {expected_total:money}. Les rogamos que "
        "emitan una factura rectificativa y lo confirmen por escrito. Retendremos el pago "
        "hasta recibirla.\n\n"
        "[Su nombre]\n"
        "[Nombre de la empresa]"
    ),
}


def _span(alert: Alert, language: str) -> str:
    """Return 'issued between D and D', or 'all issued on D' ('both' for two invoices).

    Spanish forms for 'es': 'todas emitidas el D', 'ambas emitidas el D' (REQ-PI-72).
    """
    first, last = alert.data.get("first_issue_date"), alert.data.get("last_issue_date")
    if first == last:
        pair = _invoice_count(alert) == PAIR_COUNT
        if language == "es":
            return f"{'ambas' if pair else 'todas'} emitidas el {first}"
        return f"{'both' if pair else 'all'} issued on {first}"
    if language == "es":
        return f"emitidas entre {first} y {last}"
    return f"issued between {first} and {last}"


def _invoice_count(alert: Alert) -> int | None:
    """Return `invoice_count` of a duplicate group, else the number of its invoice numbers."""
    count = alert.data.get("invoice_count")
    if isinstance(count, int) and not isinstance(count, bool):
        return count
    numbers = alert.data.get("invoice_numbers")
    return len(numbers) if isinstance(numbers, list) else None


def invoice_extras(alert: Alert, _rows: pd.DataFrame, language: str) -> Mapping[str, str]:
    """Return the date span and one 'number: total' line per invoice of a duplicate group."""
    numbers = alert.data.get("invoice_numbers") or []
    totals = alert.data.get("totals") or []
    lines = [
        f"{number}: {format_amount(Decimal(str(total)))}"
        for number, total in zip(numbers, totals, strict=True)
    ]
    return {"date_span": _span(alert, language), "invoice_lines": "\n".join(lines)}


def _iban_texts(variant: str) -> dict[str, str]:
    """Return the hold note and phone script of one IBAN variant, per language."""
    return {
        language: IBAN_HEAD[language] + IBAN_FINDING[variant][language] + IBAN_BODY[language]
        for language in IBAN_HEAD
    }


TEMPLATES: dict[tuple[str, str], ActionTemplate] = {
    ("pi.duplicate_invoice", variant): ActionTemplate(
        "ask_credit_note", DUPLICATE_INVOICE_TEXTS, invoice_extras
    )
    for variant in ("same_number", "near_identical_number", "same_total_close_dates")
}
TEMPLATES |= {
    ("pi.iban_change", variant): ActionTemplate("hold_and_verify_by_phone", _iban_texts(variant))
    for variant in IBAN_FINDING
}
TEMPLATES |= {
    ("pi.vat_error", "vat_amount_mismatch"): ActionTemplate(
        "request_corrected_invoice", VAT_AMOUNT_TEXTS
    ),
    ("pi.vat_error", "total_mismatch"): ActionTemplate(
        "request_corrected_invoice", TOTAL_MISMATCH_TEXTS
    ),
}


def action_for(alert: Alert) -> ActionTemplate | None:
    """Return the Exorcise template of an alert type, or None when the type has none."""
    return TEMPLATES.get((alert.detector, str(alert.data.get("variant", ""))))
