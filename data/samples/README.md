# Sample data

Every file in this directory is **synthetically generated**. None is derived from a real bank
statement, invoice or person (Finance Rules 5 and 6). There are no public-domain files here, so
no third-party licence applies.

## Generation script

All files are produced by [`scripts/generate_samples.py`](../../scripts/generate_samples.py):

```
python scripts/generate_samples.py --mode samples
```

The five files below have fixed content (it does not depend on the seed), so regenerating them
gives byte-identical output. `tests/test_generate_samples.py` fails if a committed file differs
from the generator. Files are UTF-8 without BOM, with LF line endings.

| File | Content |
|---|---|
| `bank_statement_sample.csv` | 10 bank rows, plain dialect (comma, dot decimal, ISO dates), 3 credits and 7 debits; 4 rows carry an `iban` in three spellings (spaced, compact, lower case) |
| `bank_statement_sample_es.csv` | the same 10 rows, European dialect (semicolon, comma decimal, `DD/MM/YYYY`) |
| `invoice_sample.csv` | 5 invoices (REQ-ING-30): one without `due_date`, one with `surcharge_amount` and `withholding_amount`, one without `iban` |
| `invoice_sample.json` | the same 5 invoices as a JSON array; amounts are numbers in three invoices and strings in two |
| `suppliers_sample.csv` | 3 suppliers (`supplier_name,tax_id,iban`), one with an empty `iban` |

## Random statements

`--mode bank` writes a random but reproducible bank statement from a seed. It is not committed:

```
python scripts/generate_samples.py --mode bank --seed 42 --rows 50 --dialect european --output statement.csv
```

`--mode zombie-demo` writes the demo statement of the zombie-subscriptions app (see below).
`--mode phantom-demo` writes the demo files of the phantom-invoices app (see below).

## Zombie-subscriptions demo statement

```
python scripts/generate_samples.py --mode zombie-demo --seed 42
```

writes `zombie_demo_statement.csv`: 335 rows (debits and payroll credits), plain dialect,
2026-05-01 to 2026-10-31. It is committed and byte-identical to the generator output for seed 42
(`apps/zombie_subscriptions/tests/test_zs_demo_generator.py` fails if it is stale). Everything is
synthetic; every merchant is a fictional brand and person names (`Ana García`, `Luigi Rossi`,
`Sophie Dupont`, `Marta Ferreira`) appear only on transfer rows.

| Content | Counterparty (raw text) |
|---|---|
| Price step 12.99 → 15.99 (5 + 1 monthly charges) | `STREAMFLEX INTL 4412` |
| Price step 9.99 → 12.99 (3 + 3 monthly charges) | `CLOUDVAULT` |
| Two parallel series, different amounts | `GLOWBILL` |
| Two parallel series, same amount | `MUSICBOX` |
| One service, two spellings (aliased to `streaming`) | `STREAMFLIX INTL 7731`, `STREAMFLIXCOM` |
| 0.49 trial, then monthly 14.99 fourteen days later | `SECUREPASS` |
| Monthly 8.99, three charges after the 2026-07-31 cancellation | `GYMPLUS` |
| Zombie candidates with a last-used date | `BEATSTREAM P2A3B4C5`, `PHOTOBOX`, `STASHCRATE` |
| Weekly shopping built so that no series forms (9 merchants) | `FRESHCO`, `SUPERMART`, … |
| Twelve single purchases, four transfers, six payroll credits | various |

`--seed` only changes the dates and amounts of the twelve single purchases.

## Phantom-invoices demo (`phantom_demo/`)

```
python scripts/generate_samples.py --mode phantom-demo --seed 42
```

writes `phantom_demo/suppliers.csv`, `phantom_demo/invoices.csv` and `phantom_demo/payments.csv`
(plain dialect: comma, dot decimal, ISO dates; negative amounts are debits). The files are
**synthetic, no real data**: fictional suppliers and customers, no real invoice, bank statement or
person (Finance Rules 5 and 6). They are committed and byte-identical to the generator output for
seed 42 (`apps/phantom_invoices/tests/test_pi_demo_data.py` fails if they are stale).
`.gitattributes` marks them `-text`, so a Windows checkout does not rewrite the line endings.

| File | Content |
|---|---|
| `suppliers.csv` | 25 fictional suppliers (`supplier_name,tax_id,iban`): 16 planted cases and 9 clean ones |
| `invoices.csv` | 70 invoice rows: 25 planted rows and 45 clean ones (five monthly invoices per clean supplier) |
| `payments.csv` | 62 bank rows: payments of the clean and some planted invoices, 3 credits, 4 unrelated debits |

The planted cases are literal tables (duplicate invoice, monthly rent, near-identical numbers,
IBAN spellings, changed IBAN, VAT error, withholding, double payment, same total on close dates,
surcharge, invalid IBAN, payment to a non-master IBAN, overdue, open, multi-rate invoice). `--seed`
only changes the amounts, dates and payment delays of the nine clean suppliers. The latest date in
the data is 2026-10-30.

## How the identifiers are made safe

- **Names**: fictional (`Ana García`, `Luigi Rossi`, brands such as `Streamly Plus`).
- **IBANs**: valid ISO 13616 mod-97 checksum but deliberately wrong Spanish national check
  digits, for example `ES88 2100 0418 5602 0005 1332` (national digits `56` instead of `45`), so
  they cannot be real accounts.
- **Tax ids**: a wrong control character, a different id per supplier (`B00000019`,
  `B00000027`, `00001003S`). The phantom demo follows the same rule for its 25 suppliers.
- No e-mail addresses and no phone numbers.
