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
- **IBANs**: use the reserved test IBAN range (e.g. `DE00 0000 0000 0000 0000 00`) or algorithmically invalid IBANs that cannot belong to a real account.
- **Email addresses**: use `@example.com` or `@test.invalid` domains only.
- **Tax/VAT numbers**: use structurally valid but numerically invalid values (e.g. Spanish NIF `00000000T`).
- **Phone numbers**: use `+34 000 000 000` or equivalent country-specific placeholder ranges.

The `ledger_kit/utils/anonymise.py` module provides helpers to strip or pseudonymise PII fields before any data leaves the ingestion layer for display or LLM calls.

---

## Rule 6 — Synthetic or public data only

- All files in `data/samples/` must be either:
  - **Synthetically generated** by a script in `data/generate/`, or
  - **Explicitly public-domain** with a licence reference in `data/samples/README.md`.
- Real bank statements, real invoices, or any file containing real personal or financial data must never be committed.
- `.gitignore` must block `data/real/` and loose `*.csv` / `*.pdf` files outside `data/samples/`.

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
