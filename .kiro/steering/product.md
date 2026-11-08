# Ghost Ledger Kit — Product

## Kiroween 2026 · Skeleton Crew category

Ghost Ledger Kit is a **developer template** for building financial agent applications that are incapable of fabricating numbers. The template enforces a strict three-layer pipeline so that any app built on it inherits the same safety contract by construction.

## Core promise

> An LLM touches the explanation layer only. Every figure that appears in any output is traceable to an exact row in the source data.

## The three layers

### 1 · Ingestion layer
Reads real-world financial documents (bank-statement CSVs, invoice files) and produces a single normalised ledger. Responsibilities:
- Parse heterogeneous CSV schemas and invoice formats into a canonical `Transaction` schema.
- Validate required fields (date, amount, currency, counterparty, source_file, source_row).
- Reject or quarantine rows that fail validation instead of silently coercing them.
- Attach a `source_ref` to every row: `{file}:{row_index}` so any downstream step can cite it.

### 2 · Deterministic detector layer
Plain Python functions — no machine learning, no probabilistic scoring — that read the normalised ledger and emit typed `Alert` objects. Responsibilities:
- Each detector is a pure function: `(ledger: DataFrame, context: Mapping[str, Any]) -> list[Alert]`, where `context` is a read-only `MappingProxyType` supplied by `run_all` (detectors that need no user input ignore it).
- Every `Alert` carries the `source_ref` of the row(s) that triggered it.
- All business thresholds (amount limits, frequency windows, tolerance margins) are explicit constants in code, not hidden inside a model.
- Detectors are covered by normal-case, edge-case, and property-based tests before they ship.

### 3 · Explanation layer
An LLM receives an `Alert` and the referenced source rows and writes a human-readable explanation. Responsibilities:
- The LLM is given only the data it needs: the alert type, the literal source rows, and a prompt that forbids invention.
- The system prompt instructs the model to cite the `source_ref` in its explanation.
- The explanation is decorative; it never feeds back into alert logic.

## Applications built on the template

### zombie-subscriptions
**Audience:** individuals managing personal finances.
**Problem:** recurring charges for subscriptions or services that have not been actively used for a configurable period.
**Key detectors:** recurring-charge detector, last-use gap detector, dormant-subscription classifier.

### phantom-invoices
**Audience:** small and medium enterprises (SMEs) and their accountants.
**Problem:** duplicate invoices, sudden supplier IBAN changes, VAT calculation errors.
**Key detectors:** duplicate-invoice detector, IBAN-change detector, VAT-error detector.

## Non-goals
- The template does not provide a general-purpose chatbot or open-ended financial advisor.
- The template does not connect to live banking APIs (ingestion is file-based).
- The LLM layer is not permitted to raise, dismiss, or modify alerts.
