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

`--mode zombie-demo` and `--mode phantom-demo` belong to the zombie-subscriptions and
phantom-invoices specs; they print a "not implemented" message until those specs add them.

## How the identifiers are made safe

- **Names**: fictional (`Ana García`, `Luigi Rossi`, brands such as `Streamly Plus`).
- **IBANs**: valid ISO 13616 mod-97 checksum but deliberately wrong Spanish national check
  digits, for example `ES88 2100 0418 5602 0005 1332` (national digits `56` instead of `45`), so
  they cannot be real accounts.
- **Tax ids**: a wrong control character, a different id per supplier (`B00000019`,
  `B00000027`, `00001003S`).
- No e-mail addresses and no phone numbers.
