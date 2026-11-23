# public-fees — Requirements

## Overview

Vampire Fees finds a recurring bank fee, for example an account maintenance fee of `6,50 EUR` a month
(`yearly_cost` `78.00` in the alert data). It cannot say whether that is a lot. `public-fees` adds
**one official public source**: the payment account fee comparator of the Banco de España (BdE), where every
Spanish bank declares the fees of its payment accounts. The `vf.recurring_fee` alert then says, in one
short sentence, how its yearly cost compares with the fees the banks declared to the BdE for the same
service and account type, for example *Of 12 payroll or pension accounts that declared an annual account
maintenance fee to the Banco de España on 2026-11-23, 9 charge less than this fee costs a year (78,00 EUR).
5 charge nothing; the median is 18,00 EUR and the highest 240,00 EUR.* (all numbers of this document are
**synthetic** unless marked BdE).

**Reviewer decisions of 23 November 2026** (Q1 to Q10, recorded at the end of `tasks.md`) are applied in this
document: the attribution text (Q1), no automated access to the BdE site (Q6), an alert id that leaves out the
`peer_*` keys (Q7), the two-sentence wording (Q9) and the two annual-total concepts only (Q10). **Amendment A1
(23 November 2026, end of `tasks.md`)** records the real Excel (Source fact 8) and the decisions D1 to D9 taken on
it (DN-PF-24 to DN-PF-32); it replaces Q5: the first snapshot holds `CNO` only (DN-PF-25).

It adds a committed snapshot in our own format, a reader in `ledger_kit/public_data/`, an importer script
(written against the real Excel, amendment A1), a word list in `config.toml` that matches an alert to a service,
extra fields in the `data` of the existing alert, one sentence on the card and in the fallback template,
an account type chosen in the app, and the BdE attribution. It adds no detector, no threshold that
decides an alert, and changes no severity, title or `source_refs`; the demo alert counts stay the same
with and without the snapshot. The comparison is **decoration around an alert that already fired**; it
never decides whether one fires (same rule as `public-cpi`, Finance Rule 8 spirit, Finance Rule 9).

**State of the repository when this spec was written: the snapshot does not exist and the Excel has not
been downloaded.** **Amendment A1:** the Excel files were exported by hand on 23 November 2026 and are kept
outside the repository; the importer (REQ-PF-04) is no longer blocked. The snapshot still does not exist until
the developer runs the importer (task PF9, a manual step). Without the snapshot the
app behaves exactly as today: no comparison, no placeholder number, nothing invented (REQ-PF-19).

Ids are `REQ-PF-nn`. EARS keywords: *shall*, *when*, *while*, *where*, *if ... then*. Every example gives a
concrete input and the exact expected output. Values marked **(synthetic)** belong to a test fixture and are
never presented as BdE data; values marked **(BdE)** are the facts given by the reviewer and pinned only
where the spec says so.

## Source facts (checked by the reviewer on 23 November 2026, licence on 15 November 2026)

1. **Tool.** Banco de España, *Comisiones y tipos de interés de los servicios financieros*, then
   *Comisiones de Cuentas de Pago*, then *Comparación entre entidades para una fecha y cuenta*. Start page
   `https://app.bde.es/csfwciu/csfwciuias/pub/InicioComisionesCuentasPago.html`. There is **no public API and
   no fixed file**: the user picks a date (*Fecha a comparar*, default today), one account type, the entities
   and the services, and the button *Exportar comparación a Excel* generates the Excel at that moment. On
   screen the tool shows a comparison only for at least 2 entities and at most 5 declarations; anything
   larger is Excel only.
2. **Account types** (code, published label): `CNO` Cuenta Nómina/Pensión; `CDI` Cuenta Digital; `CJO` Cuenta
   Joven; `CBA` Cuenta Básica; `COT` Otras Cuentas.
3. **Entities.** 51 entities had declared for `CNO` on 23 November 2026, each with a four-digit code and a
   name, for example `0049` BANCO SANTANDER, S.A.; `0182` BANCO BILBAO VIZCAYA ARGENTARIA, S.A.; `2100`
   CAIXABANK, S.A.; `1465` ING BANK N.V. SUCURSAL EN ESPAÑA. **One entity can have several declarations of the
   same account type; each declaration is one account with its own *Nombre de la cuenta*.** With 4 large banks
   and `CNO` the tool said there were more than 5 declarations.
4. **Services** (code, published label): `101` Mantenimiento de la cuenta; `201` Paquetes de servicios; `301`
   Transferencia; `302` Orden Permanente; `401` Emisión y mantenimiento de una tarjeta de débito; `402`
   Emisión y mantenimiento de una tarjeta de crédito; `403` Retirada efectivo a débito mediante tarjeta en
   cajero; `404` Retirada efectivo a crédito mediante tarjeta en cajero; `501` Descubierto expreso; `502`
   Descubierto tácito; `601` Negociación y compensación de cheques; `602` Devolución de cheques; `603`
   Servicios de alertas (SMS, email o similar).
5. **On-screen result** for 2 entities, `CNO`, 23 November 2026: columns *Servicio financiero*, *Concepto*,
   *Entidad A*, *Entidad B*; a legend maps each letter to the entity code and name. Rows seen: *Proveedor de la
   Cuenta* with concept *Nombre de la cuenta*; *Mantenimiento de la cuenta* with concepts *Periodicidad* (value
   `ANUAL`) and *Comisión anual total (euros)* (value `0,00`); *Emisión y mantenimiento de una tarjeta de
   débito* with *Marca comercial*, *Comisión de emisión (euros)*, *Comisión mantenimiento. Periodicidad.* and
   *Comisión mantenimiento. Anual total (euros)* (the Excel writes both with `ANUAL` in capitals, Source fact
   8, and the snapshot keeps the Excel spelling, DN-PF-28); *Descubierto expreso* and *Descubierto tácito*, each with
   *Apertura* (value `IMPORTE FIJO`), *Importe fijo (euros)*, *Tipo de interés nominal anual. Porcentaje (%)*
   and *Reclamación de posiciones deudoras (euros)*. Amounts use a decimal comma (`3,99`; `33,00`; `7,72`).
   **An asterisk means *No practicado*: the entity does not apply that service on that account.** Cell text
   can carry long runs of trailing spaces and padding characters. The page says that only the data the
   entities communicated to the BdE are shown.
6. **The Excel layout was not known when this spec was written.** It is now known (Source fact 8, amendment
   A1). Only the importer knows it; the rest of the spec still depends only on our own snapshot format.
7. **Licence** (BdE legal notice, *aviso legal*, checked on 15 November 2026): the information may be reused
   and used for calculations **if it is reproduced faithfully and the Banco de España is cited as the
   source**. The data keeps that condition and is **not** covered by the repository MIT licence. The reuse
   must not suggest that the BdE takes part in or endorses it.
8. **The exported Excel** (read by the reviewer on 23 November 2026 from three exported files; row and column
   numbers are 0-based, as `xlrd` gives them; facts F1 to F8 of amendment A1):
   - **Format.** A real binary `.xls` (OLE2, BIFF8, Excel 97-2003), not `.xlsx` and not an HTML table. One sheet,
     `CompararEntidadesCCP`. Every export has the same file name, `CompararEntidadesCCP.xls`, so each one is kept
     in its own folder. `xlrd` 2.0.1 reads them and prints a harmless warning about the file size not being a
     multiple of the sector size.
   - **Above the table.** A cell `Fecha: 23/11/2026   8:06:35` (when the file was generated); the cell
     `CSF - Comisiones y tipos de interés de los servicios financieros`; the title `COMPARACIÓN ENTRE
     ENTIDADES. COMISIONES DE CUENTAS DE PAGOS CUENTA NÓMINA/PENSIÓN`, ending with the account type label in
     capitals (`OTRAS CUENTAS` for `COT`); a cell `Fecha de referencia: 23-11-2026` (the declaration date,
     `DD-MM-YYYY`).
   - **Header.** The row whose column 0 is `SERVICIOS` holds each service label in the first column of its
     block; the next row holds the concept labels, and its column 0 is `CONCEPTOS`, a line break and `(*) No se
     cobra comisión/no se ofrece el servicio`. A block runs from its label column to the column before the next
     non-empty label; a column with an empty concept inside a block is a blank spacer. Blocks, in order:
     *Proveedor de la Cuenta* (*Nombre de la cuenta*); *Mantenimiento de la cuenta* (*Periodicidad*,
     *Comisión ANUAL total (euros)*); *Emisión y mantenimiento de una tarjeta de débito* (*Marca comercial*,
     *Comisión de emisión (euros)*, *Comisión mantenimiento. Periodicidad.*, *Comisión mantenimiento. ANUAL
     total (euros)*); then *Retirada efectivo a débito mediante tarjeta en cajero*, *Descubierto expreso* and
     *Descubierto tácito*. The cash-machine block has a variable number of sub-groups whose concepts repeat, so
     every later column moves (60, 58 and 54 columns in the three files): **columns are found by header text,
     never by position.**
   - **Data.** One row per account (declaration) from the row after the concept row to the last row. Column 0
     (entity code, four-digit text) and column 2 (entity name) are filled only on the first account of each
     entity; the next accounts leave them empty and belong to the entity above. Column 5 is a running number
     stored as a number cell, the only number cell. No merged cells. Up to 20 accounts per entity.
   - **Cells.** Every value cell is text. Amounts use a decimal comma and two decimals (`240,00`, `0,00`); no
     thousands separator was seen. A lone asterisk is the asterisk. Text cells carry trailing spaces only.
   - **Asterisk legend.** `(*) No se cobra comisión/no se ofrece el servicio` (no fee is charged, or the
     service is not offered); on screen it said *No practicado*.
   - **Exported on 23 November 2026.** `CNO` with all entities: **51 entities, 92 accounts (BdE)**, the whole
     list the tool offers for `CNO`. `COT` is **incomplete**: the tool refuses an export of more than 238
     declarations and a captcha stopped the downloads; 22 banks (114 accounts) and 28 of the 58 savings banks
     and credit cooperatives (136 accounts) were exported, the rest is missing. No entity appears in two `COT`
     files.

Facts that this spec deduces from the code, not from the BdE: the committed demo statement
(`data/samples/vampire_demo_statement.csv`) has a monthly `BANCO FICTICIO` / `Comisión mantenimiento cuenta`
series (22 charges from 2025-01-05 to 2026-10-05, last amount `6.50`, `yearly_cost` `78.00`) and a yearly
`Comisión anual tarjeta débito` series (`30.00` on 2025-02-14 and 2026-02-16, `yearly_cost` `30.00`).

---

## 1 — The snapshot

- **REQ-PF-01** The system shall define a committed snapshot `data/public/bde_payment_account_fees.json`, a
  UTF-8 JSON file (LF line endings, two-space indent, keys in the order below, `ensure_ascii=False`, final
  newline) in **our own format**, written by `scripts/import_bde_fees.py` (REQ-PF-04) and never by hand. **The
  file does not exist when this spec is written** (REQ-PF-03). Top-level keys, exactly:

  | Key | Content |
  |---|---|
  | `snapshot_format` | `1` (integer) |
  | `source` | `Banco de España, Comisiones y tipos de interés de los servicios financieros, Comisiones de Cuentas de Pago, Comparación entre entidades para una fecha y cuenta` |
  | `start_page` | `https://app.bde.es/csfwciu/csfwciuias/pub/InicioComisionesCuentasPago.html` |
  | `retrieved_on` | ISO date on which the Excel was generated, the date of the `Fecha:` cell above the table, e.g. `"2026-11-23"` (DN-PF-30) |
  | `declaration_date` | ISO date entered as *Fecha a comparar*, the date of the `Fecha de referencia:` cell; **one date per snapshot** (format 1) |
  | `account_types` | list of the account type codes included, in the fixed order `CNO`, `CDI`, `CJO`, `CBA`, `COT`; a type is included only when its files hold every entity the tool lists for it (DN-PF-25) |
  | `licence_note` | `The Banco de España legal notice allows reuse and use for calculations if the information is reproduced faithfully and the Banco de España is cited as the source. The data keeps that condition and is not covered by the repository MIT licence.` |
  | `attribution` | `Fuente: Banco de España, comparador de comisiones de cuentas de pago (declaraciones a fecha YYYY-MM-DD). Elaboración propia: recuento, mediana y máximo.` with `YYYY-MM-DD` replaced by `declaration_date`, i.e. `attribution_for(declaration_date)` (decision Q1) |
  | `no_endorsement` | `The Banco de España does not take part in, endorse or support this reuse.` |
  | `excel_files` | list, one object per exported file, **one or more per account type** (amendment A1, DN-PF-26), in type order and, within a type, in the order the files were given: `{"account_type": "CNO", "name": "<file name>", "size_bytes": <int>, "sha256": "<64 lowercase hex>"}`; names may repeat (every export is `CompararEntidadesCCP.xls`), hashes may not |
  | `accounts` | list of declarations, see below |
  | `rows` | list of published cells, see below |

  Each entry of `accounts` is one **declaration** (one account of one entity), exactly these keys:
  `account_type`, `declaration_date`, `entity_code` (four digits), `entity_name` (as published, trimmed),
  `account_key`, `account_name` (the published *Nombre de la cuenta*, trimmed). `account_key` is
  `"<entity_code>-<nn>"`, `nn` the two-digit ordinal (from `01`) of the declaration of that entity and account
  type in the order of the Excel (the files of a type taken in the order given; an entity is in one file only,
  DN-PF-26); it is our own key, because the source gives no account id, and it is stable
  within one snapshot; `account_name` is kept for display (DN-PF-02, decision Q8).

  Each entry of `rows` is one published cell for **one declaration date, account type, entity, account,
  service and concept** (the declaration date, type, entity and account are the `accounts` entry named by
  `account_type` + `account_key`), exactly these keys: `account_type`, `account_key`, `service_code` (one of
  the 13 of Source fact 4), `concept` (the published concept, trimmed), `text` (the published cell text,
  trimmed), `amount` (a string with exactly two decimals and a decimal **point**, e.g. `"6.50"`, **only** when
  the concept is a euro amount and the cell holds one; otherwise `null`) and `not_offered` (`true` when the
  cell is the asterisk, whose legend in the Excel is `(*) No se cobra comisión/no se ofrece el servicio`, else
  `false`; DN-PF-06). **Only the rows of services `101` and `401` are stored, with all their concepts**
  (amendment A1, DN-PF-27): the cash-machine block repeats concept names and overdraft is a non-goal. Names,
  brands and periodicities keep their `text` and have `amount: null`. The *Proveedor
  de la Cuenta* row is not stored as a row: its text is `account_name`. An empty cell is not stored as a row.
  - Row `{"account_type": "CNO", "account_key": "0049-01", "service_code": "101", "concept": "Comisión anual
    total (euros)", "text": "0,00", "amount": "0.00", "not_offered": false}` **(synthetic)**: amount `0.00`.
  - Row with `"text": "*"`, `"amount": null`, `"not_offered": true`: the entity does not apply that service.
  - Row `{... "concept": "Periodicidad", "text": "ANUAL", "amount": null, "not_offered": false}`.
  - Rows are ordered by account type (fixed order), `entity_code`, `account_key`, `service_code`, then in the
    order the concepts are published; no two rows share (`account_type`, `account_key`, `service_code`,
    `concept`).

- **REQ-PF-02** The snapshot validator (one function `validate_fee_snapshot` in
  `ledger_kit/public_data/bde_fees.py`, REQ-PF-06) shall raise `FeeSnapshotError` (a `ValueError` subclass),
  with a one-line message, for each of: a missing or extra top-level key; `snapshot_format` other than `1`; a
  date that is not a real `YYYY-MM-DD` date; `retrieved_on` before `declaration_date`; `source`,
  `start_page`, `licence_note` or `no_endorsement` different from the constants of the module, or
  `attribution` different from `attribution_for(declaration_date)`;
  `account_types` empty, with an unknown code, repeated or out of the fixed order; an account type without any
  account; `excel_files` with no entry for an account type or an entry for a type not in `account_types`, two
  entries with the same `sha256` (amendment A1, DN-PF-26), a `name` that is empty or
  contains a path separator, a `size_bytes` that is not a positive integer, a `sha256` that is not 64
  lowercase hex digits; an account with an extra or missing key, a `declaration_date` different from the
  snapshot's, an `entity_code` that is not four digits, an `account_key` that does not match
  `^\d{4}-\d{2}$` and start with its `entity_code`, an empty `entity_name` or `account_name`, an
  `entity_code` that appears with two names, a repeated (`account_type`, `account_key`); a row that names an
  unknown account or an unknown service code, has an extra or missing key, a `concept` that is empty, a text
  with leading or trailing whitespace (including `\u00a0`), an `amount` that is not `^\d+\.\d{2}$`, an
  `amount` together with `not_offered: true`, a repeated key, or is out of order.
  - `"snapshot_format": 2` → `FeeSnapshotError: unsupported snapshot_format 2 (expected 1)`.
  - `"declaration_date": "23-11-2026"` → `FeeSnapshotError: invalid declaration_date '23-11-2026' (expected YYYY-MM-DD)`.
  - `"retrieved_on": "2026-11-20"` with `declaration_date` `"2026-11-23"` → `FeeSnapshotError: retrieved_on 2026-11-20 is before declaration_date 2026-11-23`.
  - Account `{"entity_code": "0049", "account_key": "0182-01", ...}` → `FeeSnapshotError: account_key '0182-01' does not start with entity_code '0049'`.
  - Row amount `"6,5"` → `FeeSnapshotError: amount '6,5' of CNO 0049-01 service 101 is not a decimal with two places`.
  - Row amount `"-1.00"` → same message shape (a fee is never negative).
  - Row with `not_offered: true` and `amount: "0.00"` → `FeeSnapshotError: not_offered row with an amount: CNO 0049-01 service 101`.
  - Row `service_code: "999"` → `FeeSnapshotError: unknown service code '999'`.
  - Two rows with the same key → `FeeSnapshotError: duplicate row: CNO 0049-01 service 101 concept 'Comisión ANUAL total (euros)'`.
  - `excel_files[0].sha256` of 63 digits → `FeeSnapshotError: invalid sha256 for CNO: expected 64 lowercase hex digits`.
  - Two `CNO` entries with different hashes → valid; with the same hash → `FeeSnapshotError: excel_files has two entries with the same sha256 (CNO)`.
  The validator performs no I/O and no arithmetic.

- **REQ-PF-03** *While* `data/public/bde_payment_account_fees.json` does not exist, no code, test or document shall
  assume it does. Tests that read the **committed** snapshot are marked `skipif(not exists)` with the reason
  `snapshot not committed yet (PF9 is blocked)`; task PF9 removes those marks. *When* the file exists, it shall
  pass REQ-PF-02 and these pinned checks: `account_types` contains `CNO` (amendment A1, DN-PF-25, which replaces
  decision Q5: a type enters only when its files hold every entity the tool lists for it, so the first snapshot
  holds `CNO` only and `COT` is left out until its missing parts are exported); every `declaration_date` equals the
  top-level one; `licence_note` and `no_endorsement` equal the constants and `attribution` equals
  `attribution_for(declaration_date)`; the file contains no
  personal data (account names are product names, entity names are the published company names). *If* the
  declaration date is `2026-11-23`, *then* the number of distinct `entity_code` of `CNO` is **51 (BdE)**.
  Pinned figures of fees are **not** written in any test: fee amounts are not pinned, so a refreshed snapshot
  breaks nothing (the demo tests compute their expectations from the snapshot, REQ-PF-21).

## 2 — The importer

- **REQ-PF-04** (amended by A1: no longer blocked; the Excel was exported by hand on 23 November 2026). The
  system shall provide `scripts/import_bde_fees.py`, the **only** piece of the repository that reads the layout
  of the BdE Excel. It runs **on the developer machine only**: no app, test run of the apps, CI step or Streamlit
  Community Cloud run ever calls it. It **reads local files only** and never accesses the Banco de España site;
  the Excel is exported by hand in the tool (decision Q6: no automated access, ever). It reads the binary `.xls`
  with **`xlrd` 2.0.1** (DN-PF-24); `xlrd` shall not be added to `requirements.txt` (that file is what Community
  Cloud installs) but to an optional extra `import` of `pyproject.toml` with an **exact pin**
  (`xlrd==2.0.1`), and it is imported only inside `read_grid` (DN-PF-31). Command line, PowerShell:
  ```powershell
  python scripts/import_bde_fees.py --declaration-date 2026-11-23 --excel CNO=<folder>\CompararEntidadesCCP.xls [--excel TYPE=PATH ...] --expect-entities CNO=51 [--expect-entities TYPE=N ...] [--output data\public\bde_payment_account_fees.json]
  ```
  `--excel TYPE=PATH` may be repeated, also for one type (an export of more than 238 declarations is refused by
  the tool, so one type can need several files, DN-PF-26). `--expect-entities TYPE=N` is given **once for every
  type given**, `N` the number of entities the tool showed for that type with all entities selected; the import
  fails unless the files of that type hold exactly `N` distinct entities (DN-PF-25). `--declaration-date` is
  required and is a cross-check: it must equal the declaration date of the files. There is no
  `--retrieved-on`: both dates come from the files and `main` reads no clock (DN-PF-30). The account type in the
  title row of each file must equal the `TYPE` given with it. Every file must give the same declaration date and
  the same generation date. An entity found in two files of one type, and two files with the same SHA-256, are
  errors. The script computes `size_bytes` and `sha256` (`hashlib`) of each file **as downloaded**, stores `name`
  as the base name, builds the snapshot of
  REQ-PF-01, **validates it with `validate_fee_snapshot`** (the importer needs the developer venv anyway, so it
  imports the library validator instead of repeating it, DN-PF-04) and writes it to a temporary file in the same
  folder, renamed only after success. *When* any step fails (file missing, unreadable, a layout check of
  REQ-PF-05, an unknown service label, an amount with more than two decimals, a duplicate key, a cross-check
  above, a failed check), *then* it prints one line
  starting `error:` to stderr, exits with code 1 and **leaves any existing snapshot untouched**. A wrong command
  line is reported the same way (one `error:` line, exit 1). On success it
  prints `wrote <path>: <n> accounts, <m> rows, types <codes>` (codes joined by `, `) and exits 0. The Excel
  files are **not committed** (REQ-PF-21); the snapshot records their name, size and SHA-256 so the derivation
  can be checked against the file the developer still has. The harmless `xlrd` warning about the file size
  (Source fact 8) does not stop the import.
  - Exit 1, stderr `error: cannot read C:\missing.xls: file not found`, snapshot untouched, for a missing file.
  - Exit 1, stderr `error: unknown service label 'Servicio inventado' in CNO file`, for a service the table of
    Source fact 4 does not list.
  - Exit 1, stderr `error: amount '3,999' of CNO 9991-01 service 101 has more than two decimals`.
  - Exit 1, stderr `error: the title of the CNO file names account type COT, not CNO`.
  - Exit 1, stderr `error: the files give two declaration dates: 2026-11-23 and 2026-11-22`.
  - Exit 1, stderr `error: --declaration-date 2026-11-24 differs from the date of the files (2026-11-23)`.
  - Exit 1, stderr `error: entity 9991 is in two COT files: <path 1> and <path 2>`.
  - Exit 1, stderr `error: the CNO files hold 2 entities, expected 51`;
    `error: --expect-entities is missing for CNO`.
  - Exit 1, stderr `error: <path 2> has the same SHA-256 as <path 1>`.

- **REQ-PF-05** (amended by A1). The importer has three parts (DN-PF-31):
  `read_grid(path)` is the **only** function that imports `xlrd`; it opens sheet 0 and returns every cell as
  text (a text cell as written, an empty cell as `""`, a number cell whose value is whole as its integer text,
  flagged as a number cell); any other cell (a number that is not whole, a date, a boolean, an error) is an
  error, no guess. `parse_grid(grid, account_type)` is **pure** and is the only function that knows the layout
  of Source fact 8: it finds the `Fecha:` cell, the `Fecha de referencia:` cell and the title above the
  `SERVICIOS` row (exactly one of each), checks that the title names `account_type` and that column 0 of the
  concept row holds the asterisk legend, finds the blocks by header text (never by position), checks every
  service label against `SERVICES` (an unknown label is an error, no guess; *Proveedor de la Cuenta* is not a
  service, its *Nombre de la cuenta* becomes `account_name`), keeps the blocks of services `101` and `401`
  only, each of which must exist, contain its compared concept (`Comisión ANUAL total (euros)`,
  `Comisión mantenimiento. ANUAL total (euros)`) and no concept twice, rejects a number cell inside a kept
  block or the provider block, assigns an account row with empty columns 0 and 2 to the entity above, rejects
  an entity that appears twice, and returns the two dates, the title and the records (one record per account,
  with its non-empty cells of the kept blocks). `build_snapshot(records, meta)` is **pure** and holds the
  conversion rules: every cell text is **trimmed** (`str.strip`, which removes spaces and `\u00a0`; the real
  files carry trailing spaces only) before it is stored; a euro amount (concept ending in `(euros)`) published
  as `1.234,56` or `3,99` becomes `"1234.56"` or `"3.99"` through `Decimal` built from text, **never through
  `float`**, with no rounding (more than two decimals is an error; any other text made of digits, dots and
  commas is an error; a text such as `ND` is kept as text with `amount: null`); the asterisk sets
  `not_offered: true`, `text: "*"`, `amount: null`; a published service label is mapped to its code by the
  table of Source fact 4; an entity code is four-digit text as published (no padding: the real files show four
  digits); the importer invents no value, fills no missing cell with a default or an average, and drops no
  declaration (an empty cell is not a row; the account still counts). The tests of the three parts need no
  `.xls` file and no real `xlrd` (a fake module in `sys.modules`, REQ-PF-22).
  - `3,99` → `"3.99"`; `33,00` → `"33.00"`; `1.234,56` → `"1234.56"`; `0,00` → `"0.00"` **(synthetic cells)**.
  - `"*" + 40 trailing spaces` → `text "*"`, `not_offered: true`.
  - `"  Mantenimiento de la cuenta\u00a0  "` → label `Mantenimiento de la cuenta` → service `101`.
  - A kept block without its compared concept → `error: service 101 of the CNO file has no concept
    'Comisión ANUAL total (euros)'`; a number cell in it → `error: number cell at row 14 column 10 in service
    101 of the CNO file`.

## 3 — The reader

- **REQ-PF-06** The system shall provide `ledger_kit/public_data/bde_fees.py` (**stdlib only**, imports no app
  and no pandas, like `ine_cpi.py`) with `load_fee_snapshot(path=DEFAULT_FEE_SNAPSHOT_PATH) -> FeeSnapshot`,
  which reads the file with `json.loads(..., parse_float=Decimal)`, applies `validate_fee_snapshot` and returns
  an immutable `FeeSnapshot`. *If* the file is missing, unreadable or invalid, *then* it shall raise
  `FeeSnapshotError` with a one-line message naming the file; it never returns a partial snapshot.
  `FeeSnapshot` exposes `source`, `start_page`, `retrieved_on`, `declaration_date`, `account_types`,
  `licence_note`, `attribution`, `no_endorsement`, `excel_files` and `declarations(...)` (REQ-PF-07).
  `FeeSnapshot.from_dict(data)` validates a dict and builds the object without a file (tests). The module also
  holds the constants `ACCOUNT_TYPES` (code → published label and the English phrase used in sentences:
  `CNO` → `Cuenta Nómina/Pensión`, `payroll or pension`; `CDI` → `Cuenta Digital`, `digital`; `CJO` → `Cuenta
  Joven`, `youth`; `CBA` → `Cuenta Básica`, `basic`; `COT` → `Otras Cuentas`, `other`), `ACCOUNT_TYPE_ORDER`,
  `SERVICES` (the 13 codes with their published labels), the texts `SOURCE`, `START_PAGE`, `LICENCE_NOTE`,
  `NO_ENDORSEMENT`, `ATTRIBUTION_TEMPLATE` (the text of decision Q1 with a `{declaration_date}` placeholder) and
  `attribution_for(declaration_date) -> str`, which fills it. Public names are exported from
  `ledger_kit/public_data/__init__.py`.
  - `attribution_for("2026-11-23")` → `Fuente: Banco de España, comparador de comisiones de cuentas de pago
    (declaraciones a fecha 2026-11-23). Elaboración propia: recuento, mediana y máximo.`
  - `load_fee_snapshot(Path("missing.json"))` → `FeeSnapshotError: cannot read missing.json: file not found`.
  - A file with invalid JSON → `FeeSnapshotError: cannot read <path>: invalid JSON at line 3`.
  - A file that fails REQ-PF-02 → `FeeSnapshotError: invalid snapshot <path>: <message of REQ-PF-02>`.

- **REQ-PF-07** `FeeSnapshot.declarations(account_type, service_code, concept)` shall return
  `FeeDeclarations(account_type, service_code, concept, declaration_date, account_count, amounts,
  not_offered_count)` or `None`:
  1. `account_type` not one of the five codes, `service_code` not one of the 13, or `concept` empty →
     `ValueError`;
  2. a valid account type that is **not in the snapshot** → `None`;
  3. otherwise `account_count` is the number of declarations (accounts) of that type; `amounts` is a tuple of
     the `Decimal` amounts of the rows with that service and concept, **one per account, sorted ascending**
     (repeated values kept: two accounts at `0.00` give two entries); `not_offered_count` is the number of
     accounts whose row for that service and concept has `not_offered: true`; `declaration_date` is the
     snapshot's. An account with no row for that service and concept, or with a row that is neither an amount
     nor `not_offered`, is in neither list; `FeeDeclarations.without_amount_count` is `account_count -
     len(amounts) - not_offered_count`.
  Synthetic snapshot `S12` (declaration date `2026-11-23`, type `CNO` only, 15 accounts: 12 with the amounts
  `0.00, 0.00, 0.00, 0.00, 0.00, 12.00, 24.00, 36.00, 60.00, 78.00, 96.00, 240.00` for service `101`, concept
  `Comisión ANUAL total (euros)`, and 3 with the asterisk):
  - `declarations("CNO", "101", "Comisión ANUAL total (euros)")` → `account_count=15`, `amounts` equal to the twelve
    values above in that order, `not_offered_count=3`, `declaration_date="2026-11-23"`, `without_amount_count=0`.
  - `declarations("CDI", "101", "Comisión ANUAL total (euros)")` → `None` (type not in the snapshot).
  - `declarations("CNO", "301", "Comisión ANUAL total (euros)")` → `account_count=15`, `amounts=()`,
    `not_offered_count=0`, `without_amount_count=15`.
  - `declarations("XXX", "101", "Comisión ANUAL total (euros)")` → `ValueError`; `declarations("CNO", "999", "x")`
    → `ValueError`.

- **REQ-PF-08** *While* the reader answers it shall perform **no arithmetic**: it sorts, counts and compares
  nothing else; every amount it returns is a `Decimal` built from a snapshot string and equals it
  (`str(amount)` is the stored string); it never reads the network or the clock.
  - Property (Hypothesis, `max_examples=200`): for any valid generated snapshot, `len(amounts) +
    not_offered_count + without_amount_count == account_count`; `amounts` is sorted; every amount appears as
    a row of the snapshot.

## 4 — Matching an alert to a service

- **REQ-PF-09** The system shall add to `apps/vampire_fees/config.toml` a `[peer_fees]` table with
  `snapshot_path = "data/public/bde_payment_account_fees.json"`, `default_account_type = "CNO"`, and one
  sub-table per compared service with `service`, `concept`, `label`, `words` and `exclude`. No threshold lives
  in it (the two limits of REQ-PF-14 are named constants, as for every other detector limit). The two
  sub-tables of the first version, written as such in the file:
  ```toml
  [peer_fees]
  snapshot_path = "data/public/bde_payment_account_fees.json"
  default_account_type = "CNO"

  [peer_fees.maintenance]
  service = "101"
  concept = "Comisión ANUAL total (euros)"
  label = "account maintenance"
  words = ["mantenimiento cuenta", "mantenimiento de cuenta", "mantenimiento de la cuenta",
           "account maintenance"]
  exclude = ["tarjeta", "card", "descubierto", "overdraft"]

  [peer_fees.debit_card]
  service = "401"
  concept = "Comisión mantenimiento. ANUAL total (euros)"
  label = "debit card maintenance"
  words = ["tarjeta debito", "tarjeta de debito", "debit card"]
  exclude = ["credito", "credit"]
  ```
  A loader `build_peer_services(table)` (in `apps/vampire_fees/detectors/utils.py`, next to `build_vocabulary`)
  folds the phrases with `fold_tokens` and raises `ValueError` naming the key when: `service` is not one of the
  13 codes; `concept`, `label` or `words` is missing or empty; a phrase has no letter; the folded concept does
  not contain the consecutive tokens `anual total` (**only annual totals are compared**, so the sentence can say
  "annual" truthfully, DN-PF-11); `default_account_type` is not one of the five codes.
  - `service = "999"` → `ValueError: peer service 'maintenance': 999 is not a Banco de España service code`.
  - `concept = "Periodicidad"` → `ValueError: peer service 'maintenance': concept must be an annual total`.
  - A `[peer_fees]` table with no sub-table → no service: no alert ever gets a comparison (not an error).

- **REQ-PF-10** *When* an alert of `vf.recurring_fee` is built, the match shall use the **last fee row of the
  run** (`last.counterparty`, `last.description`, the same two texts `classify_fee` reads), folded as in
  `fold_tokens`, and `contains_phrase` for every phrase:
  1. the services whose `words` match either text are collected (`exclude` is **not** consulted yet);
  2. two or more → **no comparison** (the text names two services; a bundle is not compared);
  3. exactly one, and one of its `exclude` phrases matches either text → no comparison;
  4. exactly one → that service; none → no comparison.
  Overdraft, ATM and transfer fees, card fees that do not say *debit*, credit cards, packages and custody have no
  service and get no comparison (**non-goals for now**).
  - `BANCO FICTICIO` / `Comisión mantenimiento cuenta` → service `101`, concept `Comisión ANUAL total (euros)`.
  - `BANCO FICTICIO` / `Comisión anual tarjeta débito` → service `401`, concept `Comisión mantenimiento. ANUAL total (euros)`.
  - `Comisión mantenimiento tarjeta débito` → `401` (the maintenance words need `cuenta`).
  - `Cuota de mantenimiento de la cuenta y tarjeta de débito` → both services match → no comparison.
  - `Comisión tarjeta de crédito` → none match → no comparison. `Debit card credit card fee` → `401` matches,
    `credit` is excluded → no comparison.
  - `Comisión custodia valores`, `Comisión por descubierto`, `Comisión transferencia inmediata` → no comparison.
  - `Comisión mantenimiento cuenta` with the counterparty `Tarjeta Azul S.L.` → `exclude` word `tarjeta` →
    no comparison (a fail-safe: the counterparty is read too).

## 5 — Peer context in `vf.recurring_fee`

- **REQ-PF-11** *When* `context["peers"]` is a `PeerContext(snapshot, account_type, services)` (a frozen
  dataclass in `apps/vampire_fees/detectors/utils.py`; `snapshot` a `FeeSnapshot`, `account_type` a code,
  `services` the result of `build_peer_services`), the detector `vf.recurring_fee` shall add the peer fields of
  REQ-PF-12 to the `data` of an alert it **already decided to emit**. *When* `context` has no `"peers"` key or
  its value is `None`, the alert shall be **identical** to today's (same `data` keys and values, same `id`).
  *When* the peer fields are added, the `id` shall still be the same as without them: every peer key starts with
  `peer_`, and the alert id leaves out every `data` key that starts with `ALERT_ID_EXCLUDED_PREFIX` (`"peer_"`,
  `ledger_kit/models.py`), because `data/live_runs/` holds recorded answers that the demo replays by alert id
  (decision Q7, DN-PF-17). The
  detector stays a pure function: the app loads the snapshot (REQ-PF-19); the detector does no I/O. The other
  three `vf.*` detectors are not touched.
  - With the ledger of the existing recurring-fee tests and no `peers` in `context`, `alert.data` equals the
    eight-key dict those tests assert today.

- **REQ-PF-12** The peer fields are added **only together**, in this order after the existing eight keys
  (`counterparty`, `description`, `interval_type`, `charge_count`, `current_amount`, `yearly_cost`,
  `first_charge_date`, `last_charge_date`). Texts and amounts are strings, counts are integers (as
  `charge_count` is):

  | Key | Content |
  |---|---|
  | `peer_source` | `Banco de España, Comisiones de Cuentas de Pago` (constant) |
  | `peer_account_type` | the code, e.g. `CNO` |
  | `peer_account_type_label` | the English phrase of `ACCOUNT_TYPES`, e.g. `payroll or pension` |
  | `peer_service` | the service code, e.g. `101` |
  | `peer_service_label` | `label` of the matched service in `config.toml`, e.g. `account maintenance` |
  | `peer_concept` | the concept, verbatim from the config (equals the published one) |
  | `peer_declaration_date` | the snapshot's `declaration_date`, ISO |
  | `peer_account_count` | the number of accounts **with an amount** (`len(amounts)`) |
  | `peer_not_offered_count` | accounts that do not offer the service (`not_offered_count`) |
  | `peer_lower_count` | accounts whose amount is **strictly less than** `yearly_cost` |
  | `peer_zero_count` | accounts whose amount equals `0.00` |
  | `peer_median_yearly` | `median_amount(amounts)` (REQ-PF-15), two decimals |
  | `peer_max_yearly` | `max(amounts)` as a string, two decimals, verbatim from the snapshot |

  The names ending in `_yearly` are deliberate: the guard reads a field name containing `yearly` as a yearly
  figure (REQ-PF-16). Accounts that do not offer the service are **never** counted as `0.00`: `0.00` is a declared
  amount, an asterisk is a different statement.
  Worked example with the synthetic snapshot `S12` of REQ-PF-07 and the demo maintenance series
  (counterparty `BANCO FICTICIO`, `yearly_cost` `78.00`): `alert.data` equals
  ```
  {"counterparty": "BANCO FICTICIO", "description": "Comisión mantenimiento cuenta",
   "interval_type": "monthly", "charge_count": 22, "current_amount": "6.50", "yearly_cost": "78.00",
   "first_charge_date": "2025-01-05", "last_charge_date": "2026-10-05",
   "peer_source": "Banco de España, Comisiones de Cuentas de Pago", "peer_account_type": "CNO",
   "peer_account_type_label": "payroll or pension", "peer_service": "101",
   "peer_service_label": "account maintenance", "peer_concept": "Comisión ANUAL total (euros)",
   "peer_declaration_date": "2026-11-23", "peer_account_count": 12, "peer_not_offered_count": 3,
   "peer_lower_count": 9, "peer_zero_count": 5, "peer_median_yearly": "18.00",
   "peer_max_yearly": "240.00"}
  ```
  `peer_lower_count` is 9: the five `0.00` and the `12.00`, `24.00`, `36.00`, `60.00`; the account at `78.00`
  equals `yearly_cost` and is not counted. `peer_median_yearly` is `18.00`: twelve amounts, the sixth and seventh
  are `12.00` and `24.00`, `(12.00 + 24.00) / 2`.
  A second synthetic fixture `S10` (service `401`, concept `Comisión mantenimiento. ANUAL total (euros)`, ten
  accounts `0.00` ×5, `12.00`, `18.00`, `24.00`, `30.00`, `45.00`) with the demo card fee (`yearly_cost`
  `30.00`) gives `peer_account_count` 10, `peer_lower_count` 8, `peer_zero_count` 5, `peer_median_yearly`
  `6.00` (fifth and sixth `0.00` and `12.00`), `peer_max_yearly` `45.00`.

- **REQ-PF-13** The peer context shall **not** change which alerts fire, their order, `severity`, `title`,
  `source_refs`, or the eight existing `data` keys of any `vf.recurring_fee` alert, and shall not touch any other
  detector. With and without `peers` in `context`, the list of `(detector, severity, title, source_refs, id)` of
  every alert is equal; the ids are equal because the id leaves out the `peer_*` keys (decision Q7, DN-PF-17).
  - Demo statement with a synthetic snapshot: the counts pinned today by `test_vf_demo_e2e.py` (six alerts: one
    critical, three warning, two info) are the same as without the snapshot.
  - Property (Hypothesis, `max_examples=200`): for random ledgers and a random snapshot, alerts with and without
    `peers` agree on `(detector, severity, title, source_refs, id)` and on the eight base `data` keys.

- **REQ-PF-14** The peer fields shall be present only *if* the comparison can be stated honestly (Finance Rule 9),
  using two named constants at the top of `apps/vampire_fees/detectors/utils.py`:
  ```python
  # Fewest accounts with a declared amount for which the sentence is shown (DN-PF-07).
  PEER_MIN_ACCOUNTS: int = 10
  # Most days between the last charge of the fee and the declaration date of the snapshot (DN-PF-08).
  PEER_MAX_DATE_GAP_DAYS: int = 365
  ```
  *If* any of these holds, *then* the alert carries **none** of the keys of REQ-PF-12 (no partial context, no
  zero, no placeholder): `context["peers"]` is not a `PeerContext`; the match of REQ-PF-10 finds no service;
  `declarations(...)` returns `None` (account type not in the snapshot); `len(amounts) < PEER_MIN_ACCOUNTS`;
  `abs(last_charge_date - declaration_date) > PEER_MAX_DATE_GAP_DAYS` days. The gap is measured in whole days
  between the alert's `last_charge_date` and the snapshot's `declaration_date`, **in both directions**.
  - 10 amounts → fields present; 9 amounts → none. (`S10` has exactly 10.)
  - Last charge `2026-02-16`, declaration date `2027-02-16` (gap 365 days) → fields present; declaration date
    `2027-02-17` (gap 366) → none.
  - Demo card fee (last charge `2026-02-16`) with declaration date `2026-11-23` (gap 280) → fields present; with
    `2027-03-01` (gap 378) → none, while the demo maintenance fee (last charge `2026-10-05`, gap 147) still has them.
  - Demo maintenance fee with the account type `CDI` and a snapshot that holds only `CNO` → none.
  - A `PeerContext` whose `services` is empty → none. `peers` that is a plain `dict` → none.

- **REQ-PF-15** The system shall provide in `ledger_kit/utils/money.py` (the only place for monetary arithmetic)
  `median_amount(values: Sequence[Decimal]) -> Decimal`: the middle value of the sorted values, or for an even
  count the mean of the two middle values, **rounded half-up to cents at the output** (Finance Rule 3; the sum is
  exact, the division happens once). It raises `ValueError` for an empty sequence. It does not mutate its input.
  - `[Decimal("0.00")] * 5 + [12.00, 24.00, 36.00, 60.00, 78.00, 96.00, 240.00]` (twelve `Decimal`) → `Decimal("18.00")`.
  - `[Decimal("1.00"), Decimal("2.00"), Decimal("4.00")]` → `Decimal("2.00")`; the same list reversed → `Decimal("2.00")`.
  - `[Decimal("12.00"), Decimal("12.01")]` → `12.005` → `Decimal("12.01")` (half-up).
  - `[Decimal("0.00"), Decimal("0.01")]` → `Decimal("0.01")`.
  - `[Decimal("7.50")]` → `Decimal("7.50")`. `[]` → `ValueError`.
  - Property (Hypothesis): the result lies between `min` and `max` of the values and has exactly two decimals.

## 6 — The no-invented-number promise

- **REQ-PF-16** The peer figures are **not rows of the user's file**; they shall be admitted as *attributed fields
  of the alert*: each is a named field of `Alert.data` (Finance Rule 1), the field set names its source and
  its scope (`peer_source`, `peer_account_type`, `peer_service`, `peer_concept`, `peer_declaration_date`), and the
  figures are fully determined by the committed snapshot and these fields (a test recomputes every figure from
  the snapshot, REQ-PF-22). Consequently the **unchanged** number guard admits them (it admits every number found
  in `str(v)` for every value of `alert.data`, and every date found in it) and still rejects any other number or
  date. The system prompt is **not** changed (Finance Rule 1 demands it word for word); the model receives the
  fields because it receives the whole alert as JSON. `peer_max_yearly` is a value copied verbatim; the counts and
  the median are **aggregates of public rows** that are not themselves in `data`: this is a widening of
  Finance Rule 9, approved by the reviewer on 23 November 2026 because the legal notice allows calculations with
  the data when it is reproduced faithfully and the source is cited, provided the figures are labelled
  *Elaboración propia* (decision Q1, DN-PF-01); it is the reason a test recomputes them.
  Three effects of the unchanged guard are accepted: the date `2026-11-23` is a date token, so only that date is
  allowed, not its digits; the service code `101` (or `401`) becomes an allowed number (a small widening like
  DN-CPI-18); and, because the names end in `_yearly`, a figure equal to one of them next to a period word such
  as `per month` is rejected by the period check (`rejected_reason == "period_mismatch"`).
  - Alert of REQ-PF-12 (`S12`); model text `Of 12 payroll or pension accounts that declared an annual account
    maintenance fee on 2026-11-23, 9 charge less than 78,00 EUR, 5 charge nothing, the median is 18,00 EUR and
    the highest is 240,00 EUR. Source: s.csv:0.` → `Explanation.source == "llm"`.
  - The same text with `13 payroll` → rejected, `rejected_numbers == ("13",)`, `source == "fallback"`, text is the
    filled template. With `the highest is 250,00 EUR` → `("250,00",)`. With `the median is 18,50 EUR` →
    `("18,50",)`. With the date `2026-11-24` → `("2026-11-24",)`. With `18 EUR` instead of `18,00 EUR` → accepted
    (`Decimal("18") == Decimal("18.00")`).
  - The same text with `the highest is 240,00 EUR per month` → rejected by the period check, `rejected_reason ==
    "period_mismatch"`, `rejected_numbers == ("240,00", "per month")`.
  - The system message sent to the client still contains the mandatory sentence verbatim and the alert JSON
    contains `peer_median_yearly`.

- **REQ-PF-17** `Alert.source_refs` shall still contain only `source_ref` values of loaded ledger rows (the rows
  of the fee series). **No pseudo reference to the BdE is added** (Finance Rule 9); `context["peers"]` is not a
  `DataFrame`, so `loaded_source_refs(ledger, context)` is unchanged and every `source_refs` stays a subset of
  it. The BdE source is cited by the `peer_*` fields inside `data` and displayed on the card (REQ-PF-19).
  - Property (existing, extended): `set(alert.source_refs) <= loaded_source_refs(ledger, context)` with
    `context["peers"]` set.
  - Example: the alert of REQ-PF-12 has `source_refs` equal to the 22 rows of the series and no entry containing
    `bde` or `BdE`.

## 7 — Presentation and attribution

- **REQ-PF-18** *When* an alert of `vf.recurring_fee` has the peer keys, the fallback template shall contain
  the comparison in **two short sentences** (decision Q9: two sentences instead of a nested one); otherwise the
  template is today's text. `explain_support` shall provide
  `PEER_SENTENCE` (the two sentences, one constant), `RECURRING_FEE_WITH_PEERS_TEMPLATE` (today's recurring-fee template with the sentence before
  `Source: {source_refs}.`, which stays the tail so `chip_source_template` keeps working) and extend
  `template_for(alert)` to choose between them (`TEMPLATES` itself is unchanged: its keys still equal the
  registered `vf.*` detectors). No digit is written in a template. The sentence is neutral: it states figures and
  a date, draws no conclusion and gives no advice (Finance Rule 8); it never says *above*, *below*, *too*,
  *expensive* or *should*.
  - `PEER_SENTENCE`: `Of {peer_account_count} {peer_account_type_label} accounts that declared an annual
    {peer_service_label} fee to the Banco de España on {peer_declaration_date}, {peer_lower_count} charge less
    than this fee costs a year ({yearly_cost:money}). {peer_zero_count} charge nothing; the median is
    {peer_median_yearly:money} and the highest {peer_max_yearly:money}.`
  - Template with peers for the alert of REQ-PF-12 fills to: `BANCO FICTICIO charged you a monthly fee of 6,50
    EUR (Comisión mantenimiento cuenta), 22 times between 2025-01-05 and 2026-10-05, about 78,00 EUR per year.
    Of 12 payroll or pension accounts that declared an annual account maintenance fee to the Banco de España on
    2026-11-23, 9 charge less than this fee costs a year (78,00 EUR). 5 charge nothing; the median is 18,00 EUR
    and the highest 240,00 EUR. Source: <refs>.`
  - Alert with `peer_lower_count` 0 and `peer_zero_count` 0 fills `0 charge less than this fee costs a year
    (...). 0 charge nothing` (true, and shown as it is).
  - The same alert without peer keys fills to today's text, with no mention of the BdE.
  - The date is the ISO form because the guard recognises ISO and `dd/mm/yyyy` dates only; `23-11-2026` would be
    read as three numbers and rejected (DN-PF-13).

- **REQ-PF-19** The Vampire Fees alert card shall show, under the explanation text and above the source rows:
  (a) the comparison sentences **once**: *when* the displayed explanation already contains them (fallback
  template) the card adds nothing; *when* it is accepted model text that lacks them, the card adds them as a
  caption; (b) a source line `Comparison source: Banco de España, Comisiones de Cuentas de Pago, account type
  CNO (payroll or pension), service 101 (account maintenance), declared 2026-11-23; 3 accounts do not offer this
  service.` A card whose alert has no peer keys shows neither. The page shall show, **once**, below the alerts and
  only *while* a snapshot is loaded, the snapshot's `attribution` (decision Q1: shown **once on the page**; with
  `S12` it reads `Fuente: Banco de España, comparador de comisiones de cuentas de pago (declaraciones a fecha
  2026-11-23). Elaboración propia: recuento, mediana y máximo.`), a line `Licence: see the Banco de España legal
  notice · retrieved 2026-11-23 · declarations of 2026-11-23`, its `licence_note` and its `no_endorsement`
  verbatim. The showcase Home page (`streamlit_app.py`) shall carry the one-line `attribution` as a caption, **only
  while the snapshot loads** (Home presents the Vampire app; with no snapshot it shows no data and no credit).
  Phantom Invoices and Zombie Subscriptions carry nothing.
  *If* the file is missing, *then* the page shows `Fee comparison unavailable: snapshot not found.` as a caption,
  no attribution, no selector (REQ-PF-20), and the alerts have no peer keys; *if* it exists but is invalid, the
  caption is `Fee comparison unavailable: snapshot invalid.` (the detail is for CI, which fails on the committed
  file). The root `README.md` shall carry a short "Public data" paragraph for the BdE comparison with the
  attribution and the non-endorsement text and the sentence `The fee comparison appears once the snapshot
  data/public/bde_payment_account_fees.json is committed; without it the app shows no comparison.`;
  `data/public/README.md` shall describe the snapshot, say it is BdE data that keeps its condition and is not
  covered by the repository MIT licence, how it is made (`scripts/import_bde_fees.py`, by the developer, from an
  Excel generated with the owner's approval and not committed), and that the file does not exist yet.
  The wording shall not imply that the BdE takes part in, sponsors or supports the app.
  - Fallback card for the alert of REQ-PF-12 → exactly one element containing `charge less than this fee costs a
    year (78,00 EUR)`, plus the source line.
  - Accepted model text without the sentences → the sentences appear once as a caption.
  - A test compares the attribution, licence note and non-endorsement of the module constants, the README, `data/public/README.md` and (when it exists) the snapshot: all equal (while no snapshot exists, the documents carry `attribution_for("YYYY-MM-DD")`).

## 8 — The account type of the comparison

- **REQ-PF-20** The Vampire Fees sidebar shall offer, *while* a snapshot is loaded, a select box
  `Compare my fees with` (session key `vf_peer_type`, added to `WIDGET_KEYS` so it survives a visit to another
  page) whose options are the account types **present in the snapshot**, in the fixed order, shown as
  `CNO · Cuenta Nómina/Pensión`. The initial value is `default_account_type` of `config.toml` (`CNO`) *if* the
  snapshot has it, otherwise the first present type in the fixed order. Changing it reruns the pipeline with
  another `PeerContext`; the alert id does **not** change (decision Q7), so the explanation cache key of the
  Vampire app is `(alert.id, mode, peer fields)` (`explanation_cache_key`, design §9) and a new type or a new
  snapshot never reuses a stale explanation. **Amended by A1 (DN-PF-32):** with a single type present the
  select box is **not** shown and the source line of REQ-PF-19 names the type; with two or more types the
  select box is shown.
  **Why `CNO` is the default** (DN-PF-14, decision Q2): it is the default of the Banco de España tool itself;
  it is the only type for which the source facts give a size (51 entities
  had declared on 23 November 2026), so it is the best-supported sample; it is the type of the account that
  receives a salary or a pension, the most common account of a person who uploads a statement; and the sentence
  always names the type, so the reader sees what is compared and can change it. The choice is a convenience, not
  a claim that the user's account is of that type.
  - Snapshot with `CNO` and `COT`: options `CNO · Cuenta Nómina/Pensión`, `COT · Otras Cuentas`; initial `CNO`.
  - Snapshot with `CDI` and `COT` only: initial `CDI`.
  - Snapshot with `CNO` only (the first real snapshot): no select box; the comparison uses `CNO` and the source
    line says `account type CNO (payroll or pension)`.
  - Select `COT` on the demo with a snapshot where `COT` has 8 amounts for service `101` → no peer keys on the
    maintenance card (fewer than `PEER_MIN_ACCOUNTS`); the sidebar still lists `COT`.

## 9 — Repository, demo and tests

- **REQ-PF-21** `.gitignore` shall keep allowing `data/public/` (already done for the CPI) and shall **ignore the
  downloaded Excel files** (`*.xlsx`, `*.xls`) everywhere, so an export is never committed by accident.
  `data/public/README.md`, `data/samples/README.md` (pointer line), the root `README.md` and the steering files
  (`finance-rules.md` Rules 6 and 9, `structure.md`, `tech.md`) are updated in the last task. The demo shall
  behave correctly with and without the snapshot: the headless run of the Vampire Fees app with **Load demo data**
  shows the same alert counts; the maintenance and the debit-card cards carry the sentence **if and only if** the
  snapshot answers them under REQ-PF-14 (the expectation is computed in the test from the snapshot with the reader
  and `money`, never hard-coded); the custody fee card never has it; no other detector's card mentions the BdE.

- **REQ-PF-22** *Tests.* Every fixture that holds fee amounts is built in the test folder, is marked **(synthetic)**
  in its name or docstring (`synthetic_s12_snapshot`, `synthetic_s10_snapshot`) and is never described as BdE
  data; the entity names in fixtures are fictional (`BANCO FICTICIO`, `Caja Demo`), the codes are the placeholder
  range `9901` to `9999`. No test reads the network, the clock or an Excel file: the importer tests of task PF8
  use **synthetic grids** and synthetic records only (invented entities such as `9991 BANCO FICTICIO`, never a
  row copied from the real files) and test `read_grid` with a **fake `xlrd` module placed in `sys.modules`** (no
  `.xls` file in the repository, no `xlwt`), so they run in CI without the extra (amendment A1). The tests of the reader, the validator, the detector, the template, the
  card, the guard, the app and the documents are written first; every figure of REQ-PF-12 is also **recomputed**
  by a test from the synthetic snapshot with a second, independent code path (counting with `sum(...)`,
  `statistics.median` over `Decimal` and half-up rounding written in the test). A text test scans `ledger_kit/`,
  `apps/` and `streamlit_app.py` and fails when any file imports `xlrd`; another fails when `requirements.txt`
  names it (DN-PF-24).

## Non-goals

- No new detector, no new threshold that decides an alert, no severity, title or `source_refs` change.
- No comparison for overdraft, ATM withdrawals, transfers, cheques, alerts, packages, credit cards or custody
  (services other than `101` and `401`); no comparison for `vf.fee_increase`, `vf.overdraft_cost` or
  `vf.fee_summary`.
- No ranking of banks, no list of entities in the sentence, no "your bank is more expensive" wording, no advice
  and no recommendation to change bank (Finance Rule 8).
- No network access from the app, the tests, the explanation layer, the importer or CI; no scraping of the BdE
  page and no automated access to the Banco de España site, ever (decision Q6); the Excel is exported by hand and
  the importer reads a local file the developer downloaded.
- Only the two annual-total concepts are compared (`101` *Comisión ANUAL total (euros)*, `401` *Comisión
  mantenimiento. Anual total (euros)*); fees with a waiver condition are not compared (decision Q10).
- No interest rates or percentages from the BdE; no date other than the one declaration date of the snapshot; no
  history of several declaration dates (format 1).
- No change to the Exorcise drafts: the complaint to the bank does not quote the comparison.
- No change to the number guard, the system prompt or the CPI work. The one change outside the fee work is the
  alert id rule of decision Q7 (`peer_*` keys left out of the hash), which changes no existing id.
