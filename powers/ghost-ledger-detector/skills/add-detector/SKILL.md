---
name: add-detector
description: Add a new deterministic detector to the zombie-subscriptions (zs.), phantom-invoices (pi.) or vampire-fees (vf.) app of Ghost Ledger Kit, with its Alert contract, fallback template, three test tiers and verification commands.
---

# Add a detector to Ghost Ledger Kit

Use this when asked to add a detector to `apps/zombie_subscriptions/` (namespace `zs`),
`apps/phantom_invoices/` (namespace `pi`) or `apps/vampire_fees/` (namespace `vf`). Read one
existing detector of the target app first and
copy its shape: `apps/zombie_subscriptions/detectors/price_increase.py`,
`apps/phantom_invoices/detectors/vat_error.py` or `apps/vampire_fees/detectors/recurring_fee.py`. Do not edit anything under `ledger_kit/` for a new
detector, and never import one app from the other.

The product promise: detectors are plain deterministic Python, every figure is traceable to a
source row, and an LLM only ever words the explanation. Never invent a figure, date, name or IBAN.

## 1. Create the module and register it

- New file in the app's `detectors/` folder, `snake_case`: `apps/zombie_subscriptions/detectors/`,
  `apps/phantom_invoices/detectors/` or `apps/vampire_fees/detectors/`.
- Register with the namespaced decorator `ledger_kit.detectors.register`, e.g.
  `@register("zs.my_detector")`, `@register("pi.my_detector")` or `@register("vf.my_detector")`.
  The name must match
  `<namespace>.<detector>` in lowercase snake_case and be unique, otherwise `ValueError`.
- The package `__init__.py` calls `auto_discover`, which imports every module in the folder. Do not
  add manual imports.
- Signature, exactly: `(ledger: pd.DataFrame, context: Mapping[str, Any]) -> list[Alert]`.
  `context` is a read-only `MappingProxyType`.
- Pure function: no I/O, no clock (take `as_of` from context, as `pi.reconciliation` does), no
  mutation of the ledger or of `context`, no global state.
- An empty ledger returns `[]` and never raises. Only a detector documented to read `context`
  may return alerts for an empty ledger, and only when its context inputs are non-empty.
- Public functions and classes have type annotations and a one-line docstring. Line length is 100.

## 2. Named threshold constants

- Every number that decides whether an alert fires is a module-level `UPPER_SNAKE_CASE` constant
  at the top of the module, with a comment giving its business meaning (REQ-DET-06, Finance
  Rule 7). Example: `VAT_TOLERANCE` in `apps/phantom_invoices/detectors/vat_error.py`.
- No magic numbers inside conditions. Changing a threshold must be a one-line edit.
- Each constant is tested on both sides of the boundary (see section 6).

## 3. Money only through the money helpers

- All monetary arithmetic, rounding and formatting go through `ledger_kit.utils.money`:
  `ledger_kit.utils.money.round_to_cents`, `ledger_kit.utils.money.percent_of`,
  `ledger_kit.utils.money.within_tolerance`, `ledger_kit.utils.money.net_total`,
  `ledger_kit.utils.money.format_amount`. Use these instead of operators on `Decimal` (REQ-MON-03).
- Amounts are `Decimal`, never `float`. Rounding is half-up to two decimals and happens at the
  output boundary, not in intermediate steps.

## 4. The Alert contract

Build `ledger_kit.models.Alert` with these fields and leave `id` and `explanation` alone (the id
is a deterministic hash; the explanation is filled only by the explanation layer):

- `detector`: the registered name, identical to the string given to `register`.
- `severity`: one of `"info"`, `"warning"`, `"critical"`.
- `title`: short, human readable, states a fact and recommends no action.
- `source_refs`: non-empty list of `source_ref` strings, one per contributing row. Every entry
  must exist in a loaded input: the ledger or any DataFrame in `context`. Never fabricate one.
- `data`: JSON-native payload holding only `str`, `int` and `list[str]` values. Money is
  `str(round_to_cents(x))` (two decimals, e.g. `"121.00"`), dates are `date.isoformat()`, rates
  are `str(Decimal)`. IBANs only as `ledger_kit.utils.anonymise.mask_iban` output. Any figure the
  explanation may quote (for example `yearly_cost`) is stored here under a named key.
- Phantom-invoices alerts also carry a `variant` string in `data` (REQ-PI-13). The variant selects
  the fallback template.
- Return alerts in a deterministic order (`finish` in
  `apps/phantom_invoices/detectors/utils.py`, `sorted_source_refs` in
  `apps/zombie_subscriptions/detectors/utils.py`).

## 5. Label and fallback template

Phantom-invoices (`pi`):
- Add the entry to `apps.phantom_invoices.detectors.LABELS` (name to display string).
- Add one template per variant to `apps.phantom_invoices.explain_support.TEMPLATES`, keyed
  `(detector, variant)`.

Zombie-subscriptions (`zs`) has no `LABELS`. Add one template to
`apps.zombie_subscriptions.explain_support.TEMPLATES`, keyed by detector name. Vampire-fees (`vf`)
works the same way: one template in `apps.vampire_fees.explain_support.TEMPLATES`, keyed by
detector name.

Template rules (the number guard in `ledger_kit.explainer` rejects any number it cannot find in
`Alert.data` or the cited rows, so a template that breaks them would be rejected too):
- Placeholders are `{key}`, `{key:money}` (European format, key must hold a decimal string) and
  `{source_refs}`. Every placeholder must be a key of `Alert.data` (an unknown key stays literally
  as `{key}`).
- Every number or date in the filled text comes from `Alert.data`. Do not hard-code digits, do not
  derive or round anything, no recommendations or severity talk (Finance Rule 8).
- The filled template always cites `{source_refs}`.
- Verify with `ledger_kit.explainer.fill_fallback` and `ledger_kit.explainer.explain_with_meta`: a
  stub client answering with the filled template must come back with `source == "llm"` and no
  `rejected_numbers` (see `test_guard_accepts_a_sentence_restating_only_alert_data`).

## 6. Tests: three tiers, deterministic, synthetic

Create `test_zs_<module>.py` in `apps/zombie_subscriptions/tests/`, `test_pi_<module>.py` in
`apps/phantom_invoices/tests/` or `test_vf_<module>.py` in `apps/vampire_fees/tests/`. Reuse that folder's `conftest.py` (and for pi the builders in
`apps/phantom_invoices/tests/pi_builders.py`). Synthetic data only: fictional names, `@example.com`
addresses, and IBANs and tax ids as described in Finance Rule 5. Never read the wall clock; pass
dates explicitly or use `freezegun`.

- Tier 1, normal: `test_<detector>_fires_on_typical_input` (assert the exact alert count,
  non-empty `source_refs` pointing at the right rows, and `Alert.detector` equal to the registered
  name) and `test_<detector>_silent_on_clean_ledger`.
- Tier 2, edge: empty ledger `pd.DataFrame()` with `MappingProxyType({})` returns `[]`; single-row
  ledger returns a list; both sides of every threshold constant; first and last day of any
  window; two rows with the same `source_ref`.
- Tier 3, property-based with Hypothesis, each test decorated `@settings(max_examples=200)`:
  - no invention: every `source_ref` of every alert is in
    `ledger_kit.detectors.loaded_source_refs(ledger, context)`, the union of the ledger and all
    context frames;
  - idempotency: two runs give equal alerts;
  - empty input gives `[]`;
  - no negative amount in `data` when all inputs are positive.
- Hypothesis tests do not use function-scoped fixtures and do not call `register` in the body.
  Tests that need isolation use the `_snapshot_registry` and `_restore_registry` helpers, never
  `_clear_registry`.

## 7. Keep the existing contract tests in step

Adding a detector changes counts that other tests pin exactly. Update them in the same change:
- zs: `EXPECTED_NAMES` in `apps/zombie_subscriptions/tests/test_zs_registry.py` and the detector
  set in `apps/zombie_subscriptions/tests/test_zs_explain_support.py`.
- pi: `EXPECTED_NAMES` in `apps/phantom_invoices/tests/test_pi_registry.py`, the template count in
  `apps/phantom_invoices/tests/test_pi_explain_support.py`, and the expected file list in
  `apps/phantom_invoices/tests/test_pi_structure_steering.py`.
- vf: `EXPECTED_NAMES` in `apps/vampire_fees/tests/test_vf_registry.py` and the template check in
  `apps/vampire_fees/tests/test_vf_explain_support.py`.
- Add the new module and test file to the layout tree in `.kiro/steering/structure.md`.

## 8. Verify (from the repository root, venv active)

```
ruff check .
ruff format --check .
pytest apps/zombie_subscriptions/tests/test_zs_<module>.py
pytest apps/phantom_invoices/tests/test_pi_<module>.py
pytest apps/vampire_fees/tests/test_vf_<module>.py
pytest
```

Run the module test of the app you changed, then the full `pytest`. CI also requires coverage of
at least 80 % (`pytest --cov=ledger_kit --cov=apps/zombie_subscriptions
--cov=apps/phantom_invoices --cov=apps/vampire_fees --cov-fail-under=80`). Fix every failure before reporting done.
