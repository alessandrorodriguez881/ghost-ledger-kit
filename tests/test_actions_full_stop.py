"""A value that ends with a full stop must not get a second one in a draft (session 18a)."""

import pandas as pd
import pytest

from ledger_kit.actions import ActionTemplate, build_draft, fill
from ledger_kit.models import Alert

SUPPLIER = "Transportes Hermanos Lage, S.L."
TEXTS = {
    "en": "Please check the invoice from {supplier_name}.",
    "es": "Revisen la factura de {supplier_name}.",
}


def _alert(name: str = SUPPLIER) -> Alert:
    return Alert(
        detector="pi.iban_change",
        severity="critical",
        title="t",
        source_refs=["f:1"],
        data={"supplier_name": name},
    )


@pytest.mark.parametrize("language", ["en", "es"])
def test_value_ending_in_a_full_stop_gets_no_second_one(language: str) -> None:
    text = fill(TEXTS[language], _alert(), language)

    assert text.endswith("Lage, S.L.")
    assert ".." not in text


@pytest.mark.parametrize("language", ["en", "es"])
def test_build_draft_shows_one_full_stop(language: str) -> None:
    template = ActionTemplate(name="t", texts=TEXTS)

    draft = build_draft(_alert(), pd.DataFrame(), template, language)

    assert draft is not None
    assert draft.endswith("S.L.")
    assert not draft.endswith("S.L..")


@pytest.mark.parametrize("language", ["en", "es"])
def test_value_without_a_full_stop_keeps_the_template_one(language: str) -> None:
    text = fill(TEXTS[language], _alert("Ana Garcia"), language)

    assert text.endswith("Ana Garcia.")


def test_an_ellipsis_in_a_template_is_left_alone() -> None:
    assert fill("Wait... {supplier_name}", _alert("X"), "en") == "Wait... X"
