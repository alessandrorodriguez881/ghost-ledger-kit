# Ghost Ledger Kit — Finance Rules

These rules are binding on all code in this repository. Every rule applies to all layers (ingestion, detectors, explanation) unless the scope is explicitly narrowed.

---

## Rule 1 — Never invent a figure

**No layer may produce, infer, interpolate, or estimate a monetary amount, date, counterparty name, IBAN, VAT number, or any other financial datum that does not exist verbatim in the source data or as a deterministic computed field on an `Alert`.**

- Detectors may compute aggregates (sum, count, date difference, yearly cost) from source rows. Any such computed value must be stored as a named field in `Alert.data` (e.g. `yearly_cost`) and every source row that contributed to it must be listed in `Alert.source_refs`. The figure is then considered *attributed* and may be quoted by the LLM.
- If a required field is missing from the source, the row must be quarantined and flagged, not filled with a default or average value.
- The LLM explanation layer must include this constraint in its system prompt word-for-word: *"You must not invent any number, date, name, or amount. Every figure you mention must appear verbatim either in the source rows provided or in the structured fields of the alert (such as yearly_cost). Do not derive, round, or estimate any figure not explicitly present in those inputs."*

---

## Rule 2 — Always cite the source row

Every `Alert` must carry a non-empty `source_refs` list. Each entry is a `source_ref` string in the format `"{filename}:{row_index}"` that uniquely identifies the originating row in the source file.

- If a detector aggregates multiple rows, all contributing rows must appear in `source_refs`.
- The explanation layer must include at least one `source_ref` citation in every explanation it produces.
- The UI must display the `source_ref` values alongside each alert so users can verify them against the original file.

---

## Rule 3 — Round to cents

All monetary values are stored and displayed with exactly **two decimal places**.

- Use `decimal.Decimal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)` for all rounding operations.
- Rounding is applied at the **output boundary** (display, serialisation), not during intermediate calculations. Intermediate calculations retain full `Decimal` precision.
- Never truncate; always round half-up.

```python
from decimal import Decimal, ROUND_HALF_UP

def round_to_cents(amount: Decimal) -> Decimal:
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
```

---

## Rule 4 — European number format

All monetary amounts displayed in the UI or in generated text use **European locale formatting**:

| Component | Format | Example |
|---|---|---|
| Decimal separator | comma `,` | `1.234,56 €` |
| Thousands separator | full stop `.` | `1.234,56 €` |
| Currency symbol | ISO code or symbol, after the amount | `1.234,56 EUR` |
| Negative amounts | minus sign prefix | `-1.234,56 EUR` |

- The formatting helper lives in `ledger_kit/utils/money.py` and is the single point of truth for display formatting.
- Internal `Decimal` values are stored without locale formatting; formatting is applied at the presentation layer only.

```python
def format_amount(amount: Decimal, currency: str = "EUR") -> str:
    """Format a Decimal amount to European locale string, e.g. '1.234,56 EUR'."""
    rounded = round_to_cents(amount)
    # format with European separators
    ...
```

---

## Rule 5 — Anonymise personal data

No real personal data may appear in committed code, tests, fixtures, or sample data files.

- **Names**: use `Ana García`, `Luigi Rossi`, `Sophie Dupont`, or similar clearly fictional, culturally diverse names.
- **IBANs**: IBANs that must pass a checksum check (every app that validates IBANs, e.g. phantom-invoices) use a **valid ISO 13616 mod-97 checksum but deliberately wrong Spanish national check digits**, so they cannot be real accounts. Example: `ES88 2100 0418 5602 0005 1332` — mod-97 valid, national check digits `56` instead of the correct `45`. An IBAN with an **invalid** checksum is allowed only in a test that deliberately plants the checksum warning. The placeholder `DE00 0000 0000 0000 0000 00` remains valid for `scrub()` and for fixtures that never reach an IBAN validator.
- **Email addresses**: use `@example.com` or `@test.invalid` domains only.
- **Tax/VAT numbers**: Spanish tax ids (NIF/NIE/CIF) use a **wrong control character**, a different one per fictional supplier, so they cannot belong to a real person or company. Examples: CIF `B00000001`, `B00000002` (the correct control digit for `B0000000` is `0`); NIF `00000001T`, `00000002T` (the correct letter for 1 is `R`). Note that `00000000T` is **not** invalid — its letter is correct (0 mod 23 → `T`) — so it must not be used for this purpose. Avoid numbers that are multiples of 23 for NIFs (their correct letter is `T`).
- **Phone numbers**: use `+34 000 000 000` or equivalent country-specific placeholder ranges.

The `ledger_kit/utils/anonymise.py` module provides helpers to strip or pseudonymise PII fields before any data leaves the ingestion layer for display or LLM calls.

---

## Rule 6 — Synthetic or public data only

- All files in `data/samples/` must be either:
  - **Synthetically generated** by a script in `data/generate/`, or
  - **Explicitly public-domain** with a licence reference in `data/samples/README.md`.
- `data/public/` holds **official public data under an open licence**, each file with its licence reference and the required attribution in `data/public/README.md`. It is written by a developer-run script from an official source, never edited by hand, and never contains personal data. It also holds the Banco de España payment-account fee snapshot (`bde_payment_account_fees.json`), reused under the licence condition of faithful reproduction with the source cited; its attribution is in `data/public/README.md`, and `scripts/import_bde_fees.py` writes it from Excel files that the developer exported by hand and that are never committed.
- `data/benchmark/` holds the **generated output of the benchmark** (`results.json`), computed from synthetic scenarios that `scripts/generate_benchmark.py` makes from a seed. It is written by `python scripts/benchmark.py`, never edited by hand, and never contains personal data or a real file.
- Real bank statements, real invoices, or any file containing real personal or financial data must never be committed.
- `.gitignore` must block `data/real/` and loose `*.csv` / `*.json` / `*.pdf` files outside `data/samples/`, `data/public/` and `data/benchmark/`.

---

## Rule 7 — Detector threshold transparency

All numeric thresholds that influence whether an alert fires are named constants, not magic numbers.

```python
# Good
DUPLICATE_AMOUNT_TOLERANCE: Decimal = Decimal("0.01")  # cents
IBAN_CHANGE_LOOKBACK_DAYS: int = 365

# Bad
if abs(a.amount - b.amount) < 0.01:  # magic number
```

Constants are defined at the top of each detector module and documented with a comment explaining their business meaning. Changing a threshold is a one-line edit, not a search-and-replace.

---

## Rule 8 — No financial conclusions from the LLM

The LLM explanation layer must not:
- Decide whether an alert is a true positive or false positive.
- Add severity levels, scores, or risk classifications not present in the `Alert` object.
- Reference amounts, dates, or names that do not appear verbatim in the `source_refs` rows or in the named fields of the `Alert.data` payload passed to it.
- Recommend specific financial actions (e.g. "cancel this subscription", "refuse this invoice").

Permitted LLM outputs: a plain-language explanation of what the detector found, citing the source rows, and phrased neutrally for the user to act on.

---

## Rule 9 — Public reference data

A figure from a committed public snapshot (`data/public/`, for example the INE consumer price index) is not a row of the user's file, so it enters an alert only under these conditions:

- It appears only as a **named field of `Alert.data`**, together with its series code and period (for example `cpi_series`, `cpi_start_month`, `cpi_end_month`, `cpi_start_index`). Values are copied verbatim from the snapshot; any percentage is computed in `ledger_kit/utils/money.py` from fields that are themselves in `data`.
- It **never appears in `source_refs`**, which stay the `source_ref` values of rows of the user's own files. A pseudo reference to a public file is not allowed.
- It is **context around an alert that already fired**: it never decides whether an alert fires, and it changes no severity, title or `source_refs`. If a public figure cannot be stated honestly for the period (month not covered, zero-length span), the alert carries none of the public-data fields.
- Wherever a public figure is shown, the **attribution required by its licence is shown once on the same page**, with the licence name and the statement that the source does not take part in, sponsor or support the reuse. Wording must not imply endorsement.
- Apps, tests and the explanation layer read the committed file only; they never download it. Only a developer-run script does.
- Aggregates of the rows of one public snapshot (a count, a median, a maximum) may appear as named fields of `Alert.data` when the source's licence allows calculations with its data, the attribution labels them as our own work (Elaboración propia), the source, scope and date are fields of the same alert, their `data` keys start with `peer_` (left out of the alert id), and a test recomputes them from the snapshot.
- The top-level `peer_` keys of `Alert.data` are left out of the alert id (`ALERT_ID_EXCLUDED_PREFIX` in `ledger_kit/models.py`), so adding public context to an alert never changes its id; they stay in `data` and are still subject to every other condition of this rule.
