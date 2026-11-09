"""Ghost Ledger Kit showcase: the entry page of the Streamlit Community Cloud app.

Run with: ``streamlit run streamlit_app.py``

``st.navigation`` offers three pages: Home (written below) and the two apps, whose ``app.py``
files run unchanged as pages. Each app still works alone with
``streamlit run apps/<name>/app.py``. This file imports neither app (spec: showcase).

Facts checked in Streamlit 1.67: ``st.set_page_config`` may be called again by a page (the calls
are additive, the page's title wins); a file page runs as ``__main__``, so the guard at the bottom
of each app fires; both apps are named ``app.py``, so every page needs an explicit ``url_path``.
"""

from typing import NamedTuple

import streamlit as st


class PageSpec(NamedTuple):
    """One entry of the navigation menu."""

    title: str
    icon: str
    url_path: str  # explicit and unique: both app files are called app.py
    script: str | None  # path of an app's app.py relative to this file; None: Home, see home()


PAGES: tuple[PageSpec, ...] = (
    PageSpec("Home", "🎃", "home", None),
    PageSpec(
        "Zombie Subscriptions", "🪦", "zombie-subscriptions", "apps/zombie_subscriptions/app.py"
    ),
    PageSpec("Phantom Invoices", "👻", "phantom-invoices", "apps/phantom_invoices/app.py"),
)

HOME_TITLE = "👻 Ghost Ledger Kit"

PROMISE = (
    "**Financial apps that cannot make up a number.** Ghost Ledger Kit is a template with three "
    "layers; the two apps in the menu are built on it."
)

LAYERS = """
1. **Deterministic detectors find the figures.** Plain Python rules, no machine learning, read the
   files and raise the alerts.
2. **Every alert cites its source rows.** Each one lists the `file:row` of the lines it comes
   from, so every figure can be checked against the original file.
3. **The LLM only words the explanation.** It never raises, changes or dismisses an alert, and the
   number guard rejects any answer that contains a number, date or IBAN that is in neither the
   cited rows nor the alert itself. The app then shows a fixed template instead.
"""

TRY_IT = (
    "**Try it:** open an app, click *Load demo data* and switch on **Simulate a hallucinating "
    "LLM** in the sidebar. A stub model then invents a figure, 99999.99 EUR; the guard rejects it "
    "and the alert card shows a warning badge."
)

ZOMBIE_BLURB = (
    "**🪦 Zombie Subscriptions** is for individuals. It reads a bank statement and finds "
    "forgotten recurring charges, price increases, duplicates, trials that turned into payments "
    "and charges after a cancellation."
)

PHANTOM_BLURB = (
    "**👻 Phantom Invoices** is for small businesses. It reads invoices, a supplier master and "
    "bank payments and finds duplicate invoices, supplier IBAN changes, VAT errors and unpaid "
    "invoices."
)

SYNTHETIC_NOTE = (
    "All demo data in this showcase is synthetic: fictional names and merchants, and IBANs whose "
    "national check digits are deliberately wrong. Without an API key the explanations come from "
    "fixed templates; the number guard works the same way."
)

# Zombie Subscriptions compares price increases with a committed snapshot of the INE consumer
# price index (public-cpi). The same texts are in the snapshot, the README and the data/public
# README; tests/test_public_data_docs.py compares them. This file imports neither app.
INE_ATTRIBUTION = "Elaboración propia con datos extraídos del sitio web del INE: www.ine.es"
INE_LICENCE = "CC BY 4.0"
INE_NOTE = (
    "Official public data in Zombie Subscriptions (Spanish consumer price index): "
    f"{INE_ATTRIBUTION}. Licence {INE_LICENCE}."
)


def home() -> None:
    """Render the Home page: what the kit guarantees and what the two apps do."""
    st.title(HOME_TITLE)
    st.markdown(PROMISE)
    st.markdown(LAYERS)
    st.info(TRY_IT, icon="🔦")
    left, right = st.columns(2)
    left.markdown(ZOMBIE_BLURB)
    right.markdown(PHANTOM_BLURB)
    st.caption(SYNTHETIC_NOTE)
    st.caption(INE_NOTE)


def _page(spec: PageSpec) -> st.Page:
    """Build the st.Page of one spec; Home is the default page."""
    return st.Page(
        spec.script or home,
        title=spec.title,
        icon=spec.icon,
        url_path=spec.url_path,
        default=spec.script is None,
    )


def main() -> None:
    """Set the page defaults, build the menu and run the selected page."""
    st.set_page_config(page_title="Ghost Ledger Kit", page_icon="👻", layout="wide")
    st.navigation([_page(spec) for spec in PAGES]).run()


# Streamlit executes the script as __main__; importing the module (tests) renders nothing.
if __name__ == "__main__":
    main()
