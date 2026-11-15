# Ghost Ledger Kit — Testing Strategy

## Guiding principles

1. **Every detector ships with tests.** A detector without tests is not considered complete, regardless of whether it "works" manually.
2. **Tests are the specification.** When a threshold constant changes, the test that encodes the business rule is updated first.
3. **No real data in tests.** All fixtures use synthetic or anonymised data (see `finance-rules.md` Rule 5 and 6).
4. **Tests are deterministic.** Tests must not depend on the current wall-clock time; freeze time with `freezegun` or pass dates explicitly.

---

## Required test tiers for every detector

Each detector module must have corresponding tests in all three tiers.

### Tier 1 — Normal-case tests

Verify that the detector fires correctly on a typical, well-formed input that should trigger it, and does not fire on a typical input that should not trigger it.

```
test_<detector>_fires_on_typical_input
test_<detector>_silent_on_clean_ledger
```

Rules:
- Use a minimal ledger fixture (3–10 rows) that isolates the detector's logic.
- Assert on the exact number of alerts returned.
- Assert that `Alert.source_refs` is non-empty and points to the correct rows.
- Assert that `Alert.detector` matches the detector's registered name.

### Tier 2 — Edge-case tests

Cover boundary conditions and malformed inputs.

Mandatory edge cases for every detector:
- **Empty ledger**: `detect_*(pd.DataFrame(), MappingProxyType({}))` must return an empty list, never raise. A detector that is documented to read `context` (e.g. payments with no invoice) may return alerts for an empty ledger when its context inputs are non-empty; it must still return `[]` when everything is empty and must never raise.
- **Single-row ledger**: must not crash; return value must be a list.
- **Amount boundary**: test both sides of every numeric threshold constant (e.g. `DUPLICATE_AMOUNT_TOLERANCE`).
- **Date boundary**: first and last day of a lookback window.
- **Duplicate `source_ref`**: two rows with the same `source_ref` — detector must handle gracefully.

Additional edge cases specific to each detector are listed in the detector's own docstring.

### Tier 3 — Property-based tests (Hypothesis)

At minimum one property-based test per detector. Properties to test include:

| Property | Description |
|---|---|
| No invention | `Alert.source_refs` is always a subset of the **union of all loaded inputs** (the ledger plus every DataFrame handed over in `context`, e.g. suppliers and payments), computed with `loaded_source_refs(ledger, context)`. |
| Idempotency | Running the detector twice on the same ledger returns the same alerts. |
| Empty input | For all randomly generated empty DataFrames, output is `[]`. |
| Amount non-negativity | No alert carries a data payload with a negative amount when all inputs are positive. |
| Source ref coverage | Every `source_ref` in `Alert.source_refs` resolves to a row of a loaded input (ledger or context frame). |

```python
from types import MappingProxyType

from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.extra.pandas import data_frames, column

from ledger_kit.detectors import loaded_source_refs

@given(ledger=data_frames([
    column("source_ref", elements=st.text(min_size=1)),
    column("amount", elements=st.decimals(min_value=0, max_value=1_000_000, places=2)),
    ...
]))
def test_source_refs_are_subset_of_input(ledger):
    context = MappingProxyType({})   # or {"suppliers": ..., "payments": ..., "as_of": ...}
    alerts = detect_*(ledger, context)
    all_refs = loaded_source_refs(ledger, context)   # union of ledger + context frames
    for alert in alerts:
        for ref in alert.source_refs:
            assert ref in all_refs, f"Alert cited {ref!r} which is not in any loaded input"
```

---

## Shared fixtures

Fixtures shared between tests live in `tests/conftest.py` (library tests) or `apps/<app_name>/tests/conftest.py` (app tests).

Standard fixtures to provide:

| Fixture name | Description |
|---|---|
| `empty_ledger` | `pd.DataFrame` with correct schema, zero rows |
| `single_row_ledger` | One valid `Transaction` row |
| `clean_ledger_10` | 10 rows with no anomalies for any detector |
| `ledger_with_duplicate_invoice` | Minimal fixture that triggers the duplicate-invoice detector |
| `ledger_with_iban_change` | Minimal fixture that triggers the IBAN-change detector |
| `ledger_with_zombie_sub` | Minimal fixture that triggers the dormant-subscription detector |

---

## Ingestion layer tests

The ingestion layer has its own test suite in `tests/ingestion/`.

Required tests:
- Parsing a well-formed bank-statement CSV produces the expected `Transaction` objects.
- Parsing a CSV with missing required fields quarantines the bad rows and returns the valid ones.
- `source_ref` is correctly assigned as `"{filename}:{row_index}"` (0-based).
- Parsing an empty file returns an empty list without raising.
- Amount columns are read as `Decimal`, not `float`.
- Date columns are parsed to `datetime.date`, not string.

---

## Explanation layer tests

The LLM explanation layer is tested with an injectable **`MockLLMClient`** (`chat` and `completions` are properties; `create` records each call's kwargs in `client.calls`) — never against the real API in CI.

Required tests:
- The system message sent to the client (`client.calls[0]["messages"]`) includes all `source_ref` values from the alert and the mandatory no-invention instruction verbatim.
- `explain(alert, rows, fallback_template=..., client=mock_client)` returns a non-empty string; `explain_with_meta` returns an `Explanation(text, source, rejected_numbers)`.
- With no API key and no client, the filled fallback template is returned (`source="fallback"`).
- A simulated LLM that returns a hallucinated amount, a made-up number equal to a cited row number, an invented number glued to letters, an unknown or malformed date, or an IBAN-shaped token is rejected by the number guard: the result is the fallback template with `source="fallback"` and the offending tokens in `Explanation.rejected_numbers`. No exception is raised (there is no `ExplanationIntegrityError`).
- European amounts in the answer (`12,99 EUR`, `1.060,00 EUR`) pass when the same value is allowed.
- An API error, timeout or missing `openai` package returns the fallback.

---

## Running tests

```bash
# All tests
pytest

# Specific app
pytest apps/zombie_subscriptions/tests/

# With Hypothesis verbose output
pytest --hypothesis-show-statistics

# Coverage (80% minimum enforced in CI)
pytest --cov=ledger_kit --cov=apps/zombie_subscriptions --cov=apps/phantom_invoices --cov=apps/vampire_fees --cov-fail-under=80
```

## CI requirements
- All three test tiers must pass before a PR is merged.
- Coverage must not drop below **80%** across the repository.
- `ruff check` and `ruff format --check` must pass with zero warnings.
- Hypothesis `max_examples` is set to 200 in CI via `settings(max_examples=200)` on each property test.
- The Hypothesis deadline is off (`deadline=None`) because timing on shared CI runners varies. The root `conftest.py` registers and loads the profile `ghost-ledger`, which covers `tests/` and every `apps/*/tests/`; `tests/test_hypothesis_profile.py` asserts it. `max_examples` stays 200 on each property test.
