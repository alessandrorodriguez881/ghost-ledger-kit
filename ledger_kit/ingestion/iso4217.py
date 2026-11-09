"""ISO 4217 numeric-to-alphabetic currency codes used by Norma 43 (AEB Cuaderno 43)."""

# Source: AEB, "Serie normas y procedimientos bancarios n.º 43", Informacion normalizada de cuenta
# corriente, June 2012, Annex 2 (currency table). Exactly these eleven codes, verified against that
# document in the session 8b review; no other code is added from memory. A record 11 with another
# code is rejected (`unknown_currency_code`); a record 24 with another code keeps the movement and is
# tagged `original_currency_code:<NNN>`.
NUMERIC_TO_ALPHA: dict[str, str] = {
    "978": "EUR",
    "840": "USD",
    "826": "GBP",
    "756": "CHF",
    "752": "SEK",
    "578": "NOK",
    "554": "NZD",
    "392": "JPY",
    "208": "DKK",
    "124": "CAD",
    "036": "AUD",
}
