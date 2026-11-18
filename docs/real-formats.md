# Real Spanish formats

Back to the [README](../README.md).

## Real Spanish formats

All three apps read the formats Spanish banks and invoicing software actually produce, not only CSV. The two readers live in `ledger_kit/ingestion/`, and the router in `sniffer.py` picks the reader from the file content.

| Format | Reader | What it does | Safety |
|---|---|---|---|
| Norma 43 bank statements (AEB Cuaderno 43) | `norma43_reader.py` | Fixed-width records 11, 22, 23, 24, 33 and 88; amounts are `Decimal`; the counts and totals of the closing record are checked, and a failed check is shown, not hidden. | Bad movements are quarantined with a reason. |
| Facturae 3.2, 3.2.1 and 3.2.2 e-invoices (XML) | `facturae_reader.py` | Each invoice becomes one canonical invoice, with taxes, withholdings and installments read from the schema paths; several files are merged in file-name order. | XML is parsed only with `defusedxml` (DTDs and entities refused). Digital signatures (`.xsig`) are read but **not verified**, and the page says so. A multi-rate invoice is quarantined. |

- **IBAN convention.** Norma 43 has no counterparty IBAN field, so the reader takes an IBAN only from a 23 record whose text starts with `IBAN `. A file without such records still loads, and the page says the payment-side IBAN checks are skipped.
- **Demo format choice.** Zombie Subscriptions and Phantom Invoices have a *Demo format* radio, `CSV` or `Real formats`. `Real formats` loads `data/samples/zombie_demo_statement.n43`, or `payments.n43` plus the 25 Facturae files in `data/samples/phantom_demo/facturae/`, and gives the same alerts as the CSV demo (same detectors, severities and figures; only the `source_refs` differ). Tests prove it: `test_zs_real_formats.py` and `test_pi_real_formats.py` in the app `tests/` folders. Vampire Fees has `test_vf_real_formats.py` for its Norma 43 demo.
- **Where a citation points.** A chip reads `file · line N` for a CSV file (the line of the file where the record starts, the header being line 1) and for a Norma 43 file (the line of the record 22), so the line a person finds in an editor is the one the page shows. A Facturae invoice has a position and not a line, so its chip reads `file · invoice N`. The internal key `file:N` (`source_ref`) is unchanged and stays in the chip title.
- **What was checked, and by whom.** The reviewer compared the Norma 43 layouts with the AEB document and the Facturae paths with the official schema, and validated all 25 sample Facturae files once against the official `Facturaev3_2_2` XSD (25 of 25 valid). That check is not part of CI.
