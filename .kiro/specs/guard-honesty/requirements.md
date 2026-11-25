# guard-honesty — Requirements

## Overview

A fresh jury found that the number guard (`_passes_number_guard` in `ledger_kit/explainer.py`) reads
digits only. On the GYMPLUS demo alert (`yearly_cost` 107.88, rows of 8.99):

| Text | Today |
|---|---|
| `Over five years you pay 540 euros.` | rejected (`540`) |
| `Over five years you pay five hundred and forty euros.` | **passes** |
| `GYMPLUS: quinientos cuarenta euros.` | **passes** |

The same figure is caught or missed depending on how it is written. `guard-honesty` closes that gap
in two sessions:

- **Part 1 (session 21a, this one)**: the guard also reads numbers written in words, English and
  Spanish; the highlight marks a rejected phrase; a regression net pins what today's guard does to
  every committed real-model answer.
- **Part 2 (session 21b, pending, no code in 21a)**: the Home example, the accepted-answer labels
  and the README say honestly what the guard now checks and what it does not.

The real model answers in `data/live_runs/*.json` use number words only for small counts (`five
years`, `six charges`, `three months`, `one of them`, `two separate invoices`) and none is next to a
currency or a percent word. The rule below is built so that these stay accepted.

It changes no detector, no threshold, no rule for digits, dates, IBANs or currencies, and no text
of a badge or of a verdict. Ids are `REQ-GH-nn`; acceptance examples are `AE-GH-nn`. EARS keywords:
*shall*, *when*, *while*, *where*, *if ... then*. All data is synthetic.

## Shared vocabulary

- **Number phrase**: a run of number words that reads as one number (`five hundred and forty`,
  `ninety-nine`, `quinientos cuarenta`, `five`).
- **Number word**: a word of the English or Spanish lists of REQ-GH-02 and REQ-GH-03. `and`, `y`
  and a leading `a` are joiners, not counted as number words except `a`, which stands for one.
- **Money word**: a currency or percent word of REQ-GH-07.
- **Allowed set**: `_allowed_decimals(alert, rows, row_columns)`, the values a model may quote.

---

## 1 — Library: `ledger_kit/number_words.py`

- **REQ-GH-01** The system shall provide `ledger_kit/number_words.py`, standard library only, with
  one public function `find_number_phrases(text)` that returns, in text order, one `NumberPhrase`
  for each number phrase of `text`: `text` exactly as written, `start` and `end` offsets
  (`text_in[start:end] == phrase.text`), `value` (an `int`) and `word_count` (how many number
  words it has).
  - AE-GH-01

    | Input text | Phrases (text, start, end, value, word_count) |
    |---|---|
    | `Pay ninety-nine euros.` | (`ninety-nine`, 4, 15, 99, 2) |
    | `no numbers here` | none |
    | `` (empty) | none |

- **REQ-GH-02** The parser shall read these English words: zero to nineteen; the tens twenty to
  ninety; `hundred`, `thousand`, `million`. A ten and a unit shall join with a hyphen or a space.
  The word `and` shall join only right after `hundred`, `thousand` or `million`, and only when a
  number word follows. A leading `a` before `hundred`, `thousand` or `million` shall count as one.
  - AE-GH-02

    | Input text | Verdict | Tokens (value) |
    |---|---|---|
    | `five hundred and forty` | one phrase | 540 |
    | `ninety-nine` | one phrase | 99 |
    | `ninety nine` | one phrase | 99 |
    | `a hundred` | one phrase | 100 |
    | `two thousand and five` | one phrase | 2005 |
    | `one million two hundred thousand` | one phrase | 1200000 |
    | `five and forty` | two phrases | 5, 40 |

- **REQ-GH-03** The parser shall read these Spanish words, with and without accents: `cero`, `uno`,
  `una`, `un`, `dos` to `quince`, `dieciséis` to `diecinueve`, `veinte`, `veintiuno` to
  `veintinueve`, `treinta` to `noventa`, `cien`, `ciento`, `doscientos` to `novecientos` and their
  feminine forms, `mil`, `millón`, `millones`. The word `y` shall join only a ten and a unit.
  - AE-GH-03

    | Input text | Verdict | Tokens (value) |
    |---|---|---|
    | `quinientos cuarenta` | one phrase | 540 |
    | `treinta y cinco` | one phrase | 35 |
    | `dieciséis` / `dieciseis` | one phrase each | 16 |
    | `veintidós`, `veintitres`, `veintiséis` | one phrase each | 22, 23, 26 |
    | `mil doscientos` | one phrase | 1200 |
    | `un millón doscientos mil` | one phrase | 1200000 |
    | `cinco y seis` | two phrases | 5, 6 |

- **REQ-GH-04** Words shall join only where REQ-GH-02 and REQ-GH-03 allow it; any other neighbour
  starts a new phrase. The words `and` and `y` shall never start or end a phrase. Only a single
  space (or tab) or a single hyphen shall stand between the words of one phrase: a comma, a line
  break or a dash shall not.
  - AE-GH-04

    | Input text | Verdict | Tokens (value) |
    |---|---|---|
    | `five and six` | two phrases | 5, 6 |
    | `el cinco` | one phrase | 5 |
    | `twenty, five` | two phrases | 20, 5 |
    | `two three` | two phrases | 2, 3 |
    | `and` | none | |

- **REQ-GH-05** Matching shall be case-insensitive and on whole words only. A phrase joined by a
  hyphen or a space to an ordinal word (`first` to `millionth`, `primero`, `segundo`, `vigésimo`
  and the like), also through an `and` or `y`, is not a number: the parser shall skip the whole
  phrase. A hyphenated word that is not an ordinal shall leave the number word alone.
  - AE-GH-05

    | Input text | Verdict | Tokens (value) |
    |---|---|---|
    | `Five Hundred And Forty` | one phrase | 540 |
    | `phone`, `seven5`, `ten_twenty` | none | |
    | `the twenty-first of August` | none | |
    | `el vigésimo primero` | none | |
    | `one-off` | one phrase `one` | 1 |

---

## 2 — The number guard

- **REQ-GH-06** *When* `_passes_number_guard` has read the digits of a text, it shall also read
  the number phrases of the same text (after the blanking of row citations, counts and list markers
  that the digits use) and shall check a phrase when its value is above ten or it has two or more
  number words.
  - AE-GH-06 (GYMPLUS, yearly cost 107.88, rows of 8.99)

    | Input text | Verdict | Tokens |
    |---|---|---|
    | `Over five years you pay five hundred and forty euros.` | rejected | `five hundred and forty` |
    | `GYMPLUS: quinientos cuarenta euros.` | rejected | `quinientos cuarenta` |
    | `It costs ninety-nine euros.` | rejected | `ninety-nine` |
    | `There were twelve charges.` | rejected | `twelve` |
    | `The total is twenty one.` | rejected | `twenty one` |

- **REQ-GH-07** A phrase of one number word worth ten or less shall be checked only when the next
  word or the word before it is a money word: `euro`, `euros`, `eur`, `€`, `dollar`, `dollars`,
  `dólar`, `dólares`, `usd`, `$`, `pound`, `pounds`, `libra`, `libras`, `gbp`, `£`, `cent`, `cents`,
  `céntimo`, `céntimos`, or a percent word: `percent`, `per cent`, `%`, `por ciento`.
  - AE-GH-07

    | Input text | Verdict | Tokens |
    |---|---|---|
    | `It was charged three times, one of them after you cancelled.` | accepted | |
    | `The rows show three months.` | accepted | |
    | `You pay five euros.` | rejected | `five` |
    | `You pay EUR five.` | rejected | `five` |
    | `Paga el cinco por ciento de interés.` | rejected | `cinco` |
    | `Interest is five per cent.` | rejected | `five` |

- **REQ-GH-08** The single word `once` shall be checked only when the next word or the word before
  it is a money word, because it is also an ordinary English word.
  - AE-GH-08

    | Input text | Verdict | Tokens |
    |---|---|---|
    | `GYMPLUS charged you once.` | accepted | |
    | `You paid once EUR.` | rejected | `once` |

- **REQ-GH-09** The value of a checked phrase shall be compared with the same allowed set as the
  digits. *Where* the alert data or a visible row cell holds number phrases, their values shall
  join the allowed set, so that a name such as `SEVEN ELEVEN` in a row never rejects itself.
  - AE-GH-09

    | Row counterparty | Input text | Verdict | Tokens |
    |---|---|---|---|
    | `SEVEN ELEVEN` | `SEVEN ELEVEN charged you 10.00 EUR.` | accepted | |
    | `SHOP` | `SEVEN ELEVEN charged you 10.00 EUR.` | rejected | `ELEVEN` |
    | (alert) | text with the `yearly_cost` in digits and `three charges` | accepted | |

- **REQ-GH-10** A rejected phrase shall be reported in `rejected_numbers` exactly as written, in
  text order together with the rejected digit tokens of the same text; the rejected currencies
  keep their place after them. *If* no phrase is rejected, the order of the digit tokens shall be
  what it is today.
  - AE-GH-10

    | Input text | Rejected tokens, in order |
    |---|---|
    | `You pay five hundred and forty euros, which is 539.40 EUR.` | `five hundred and forty`, `539.40` |
    | `You pay 539.40 EUR, which is five hundred and forty euros.` | `539.40`, `five hundred and forty` |

- **REQ-GH-11** The change shall live in `_passes_number_guard` and `_allowed_decimals`, so that
  `explain_with_meta`, `check_figures` (the Exorcise drafts and `scripts/ledger_scan.py`) and Night
  Watch get it with no other change. Every existing rule for digits, dates, IBANs and currencies
  shall stay as it is. Ordinals shall not be read (REQ-GH-05).
  - AE-GH-11

    | Input text | Verdict | Tokens |
    |---|---|---|
    | `Over five years you pay 540 euros.` | rejected | `540` |
    | `It happened on the twenty-first of August.` | accepted | |
    | `MUSICBOX costs 10.99 EUR every year.` | accepted (a limit, see below) | |

  **Documented limit, accepted on purpose**: the guard checks figures, not meaning. `MUSICBOX costs
  10.99 EUR every year.` is accepted because 10.99 is a figure of the rows, although the charge is
  monthly. The same holds for words: a figure of the rows written in words in a wrong sentence.

- **REQ-GH-12** *When* a rejected token is made only of letters, spaces and hyphens,
  `live_guard.highlight_segments` shall mark its occurrences in the raw answer as whole words and
  as one segment. The behaviour for tokens with digits shall not change.
  - AE-GH-12

    | Raw answer | Tokens | Flagged segments |
    |---|---|---|
    | `Over five years you pay five hundred and forty euros.` | `five hundred and forty` | `five hundred and forty` |
    | `A concession was made.` | `once` | none |
    | `It was charged once.` | `once` | `once` |
    | `Total 539.40 EUR, not 39.40.` | `39.40` | `39.40` |

- **REQ-GH-13** Every Exorcise draft of the three demos, in English and in Spanish, shall still
  pass `check_figures`.
  - AE-GH-13: for every alert of the Zombie, Phantom and Vampire demos that has a template and each
    language in `en`, `es`, `build_draft` returns a draft and `check_figures` returns `(True, ())`.

---

## 3 — Regression net

- **REQ-GH-14** For every record of every committed run file in `data/live_runs`, the system shall
  keep a test that runs `explain_with_meta` as the replay does and asserts the exact set of record
  ids that end on the fixed template. A change in these sets shall be explained in this spec, never
  just updated in the test. Every record's alert shall be found in today's demo.
  - AE-GH-14

    | Run file | Record ids that end on the fixed template |
    |---|---|
    | `2026-11-10_llama3.2-3b.json` | Z4, Z6, P3, V1, V2 |
    | `2026-11-10_llama3.2-3b_run2.json` | Z4b, Z6b |
    | `2026-11-10_llama3.2-3b_run3.json` | Z3c, Z4c |
    | `2026-11-11_llama3.2-3b_demo.json` | Z03, Z04, Z05, Z20, P27, V37 (Z04 and Z05 since session 25, REQ-GH-23) |

## 4 — Documentation

- **REQ-GH-15** `docs/live-guard.md` shall list number words among what the guard checks, with the
  rule of REQ-GH-06 to REQ-GH-08 in plain words and these limits: English and Spanish only;
  ordinals are not read; a small number in words with no money word next to it passes; an amount
  with cents in words (`ocho con noventa y nueve`) is rejected even when it is right. Nothing else
  in that file shall change.

- **REQ-GH-16** *When* `cien` or `ciento` stands right after the word `por` (joined by a space),
  the parser shall treat it as part of the percent words `por ciento` and `por cien`, not as a
  number: it gives no phrase. `cien por cien` gives one phrase, the first `cien` (100).
  - AE-GH-16: `Paga el cinco por ciento de interés.` and `Paga cinco por ciento.` are rejected with
    `cinco` alone; `por ciento` gives no phrase; `ciento veinte` is still 120.

- **REQ-GH-17** A number phrase shall not be a figure where the digit rules of
  `_without_non_figures` blank an integer: the count of the cited rows followed by the words of
  `_COUNT_OF_ROWS_RE`, and a row citation after `row(s)` or `line(s)` whose value is a line of the
  alert's own refs (lists and ranges as for digits). The rules are reused, not copied. Ordinal
  words are never number phrases, so the ordinal-row rule needs no counterpart.
  - AE-GH-17: `twelve debit transactions` passes on an alert with 12 cited rows and is rejected
    (`twelve`) on an alert with 3; `Rows one and two.` and `Row twelve.` pass when lines 1, 2 and
    12 are cited; `Row fourteen.` is rejected.

## 5 — Part 2 (session 21b)

A fresh jury found that the Home example (`landing.example_html`, fed by
`replay.load_run().first_rejected_probe()`) shows the 2026-11-11 GYMPLUS answer `107.88 * 5 =
€539.40` as an invention. It is not one: the arithmetic is right, and the guard rejects it only
because 539.40 is in no cited row (the guard does no arithmetic). A real invention by the same
model is record P3 of `data/live_runs/2026-11-10_llama3.2-3b.json` (duplicate invoice F-2026-0310,
the five-year question): `Assuming a constant interest rate of 5% per annum (which is a common
rate for invoices), we can calculate the total cost.` and `So, the total cost in five years will
be approximately €617.51.` No row and no alert field holds an interest rate. Today's guard rejects
P3 with `5` and `617.51` among the tokens (`tests/test_recorded_verdicts.py` pins it).

- **REQ-GH-20** The Home example shall be record P3 of the 2026-11-10 file (`replay.home_example()`,
  constants `DEFAULT_HOME_EXAMPLE_PATH`, `HOME_EXAMPLE_PATH` read at call time, `HOME_EXAMPLE_ID`
  = `P3`, `HOME_EXAMPLE_MARKS` = `5%`, `617.51`). `home_example` shall return a `Recording`
  with the model name and date of that file, and `None` (never an exception) when the file, the
  model, the date or the record is missing or malformed. The cards and the Provoke panel shall
  keep replaying the 2026-11-11 file. `landing.example_html(recording)` shall return `''` when the
  recording is `None`, when its question is not a preset or when a mark is not in its raw answer;
  otherwise it shall show the label, the preset question, the two sentences with the marks
  highlighted, a line saying that no cited row and no alert field holds an interest rate and the
  word `rejected`, and a smaller line (`gl-example-note`) saying that the guard does no
  arithmetic and why the GYMPLUS sum is rejected too.
  - AE-GH-20

    | Call | Result |
    |---|---|
    | `home_example()` on the committed file | P3, model `llama3.2:3b`, date `2026-11-10` |
    | today's guard on that raw answer | fallback; `617.51` and `5` among the rejected tokens |
    | `example_html(home_example())` | label, question, two `<mark>`, `<b>rejected</b>`, note line |
    | `example_html(None)`; a recording without a mark | `''` |
    | `example_html(home_example())`, second mark | the last sentence with 617.51 (`So, the total cost in five years will be approximately €617.51.`), not `A = 617.51`; the first sentence for `5%` |
    | missing or malformed file | `None` |
    | GYMPLUS forecast probe of 2026-11-11 | holds `539.40`; rejected now; `Decimal("107.88") * 5 == Decimal("539.40")` |

- **REQ-GH-21** The labels next to accepted answers shall not claim more than the guard checks:
  `VERDICT_ACCEPTED`, `NOTE_GUARD_SCOPE` (`live_guard.py`), `BADGE_LLM` (the three apps) and
  `BADGE_ACCEPTED` (`replay.py`) shall each say that figures are checked and wording is not
  checked, in the exact texts of the session 21b request.
  - AE-GH-21: each of the four texts contains `figures checked` (case-insensitive) and
    `wording not checked`; `NOTE_GUARD_SCOPE` says the guard does not judge wording and does no
    arithmetic.

- **REQ-GH-22** The README shall say the same as the Home page and the docs: line 3, step 1 and
  step 4 of the judge path, the sentence of the one promise, a section `## What the guard does not
  check` (meaning, arithmetic, number words, an accepted answer is not a statement that it is
  true) and a Decisions row for 13 Nov. `docs/live-guard.md` shall say two inventions and one
  right sum that is in no row. The README shall no longer contain `inventing 539.40`,
  `can never introduce a figure` or `traceable to an exact row`.
  - AE-GH-22: `MUSICBOX costs 10.99 EUR every year` is in the new section as the meaning example.

## 6 — Part 3 (session 25): the price index is context, not a cause

A fresh jury of 14 Nov found that the README promises the CPI sentence of `zs.price_increase` is
context, not a verdict, while two real model answers of
`data/live_runs/2026-11-11_llama3.2-3b_demo.json` turn the official context into a cause, and
today's guard accepts both because it checks figures and every figure in them is allowed:

- **Z04** (CLOUDVAULT): `The price change is attributed to the IPC290751 CPI series, which is
  based on the 2025 base year.`
- **Z05** (STREAMFLEX INTL): `The price change is attributed to the CPI series IPC290751, which
  started in May 2026.`

Every committed run file was searched: these are the only two answers that name the index next to
a cause word.

- **REQ-GH-23** *If* one sentence of a model answer names the price index and also gives a cause
  phrase, *then* `explain_with_meta` shall reject the answer exactly like an answer with an
  invented figure: `source` is `fallback`, the text is the filled fixed template, `raw_answer`
  keeps the model's text, `rejected_numbers` holds each offending sentence as written, in text
  order, and `rejected_reason` is `price_index_as_cause`. For a rejection by a figure, a date,
  an IBAN or a currency, `rejected_reason` shall stay empty.
  - **Index terms** (any case, with or without accents, whole words): `IPC`, any IPC series id
    such as `IPC290751`, `CPI`, `consumer price index`, `price index`, `inflation`, `índice de
    precios`, `inflación`.
  - **Cause phrases** (same rules): `attributed`, `attributable`, `due to`, `caused by`, `because
    of`, `driven by`, `explained by`, `a result of`, `debido a`, `causado por`, `se debe a`
    (`debido al` and `se debe al` read as the same phrases).
  - A sentence ends at `.`, `!` or `?` followed by white space, or at a line break.
  - The check shall not reject: a sentence about the index with no cause phrase, a cause phrase
    with no index in the same sentence, and the kit's own fixed CPI sentences
    (`CPI_SENTENCE` and `CPI_SENTENCE_LAG` of the zombie app), which say `changed by`.
  - The Provoke panel (`live_guard.verdict_line`) and the replay badge (`replay.card_badge`) shall
    say why the card fell back (the answer names the price index as the cause of the price
    change) and show the sentence; the highlight marks it in the raw answer. The text of every
    other badge and verdict stays as it is.
  - The check is in `explain_with_meta`, after the number guard, not in `_passes_number_guard`:
    `check_figures` (the Exorcise drafts, `scripts/ledger_scan.py`) and Night Watch are not changed.
  - Documented limit: it reads one sentence at a time and a fixed list of words; a cause written
    in other words, or across two sentences, is not seen. The guard still does not check meaning.
  - AE-GH-23

    | Text | Verdict | Tokens |
    |---|---|---|
    | the Z04 sentence above | rejected | the sentence |
    | the Z05 sentence above | rejected | the sentence |
    | `The increase is due to inflation.` | rejected | the sentence |
    | `El aumento se debe a la inflación.` | rejected | the sentence |
    | `The CPI gives context for these months.` | accepted | |
    | `The price rose because the plan changed.` | accepted | |
    | the fixed CPI sentence of a filled template | accepted | |

## 7 — Amendment A-GH-01 (session s50): a year on its own is said as a year

A reviewer found a rejection reason that is not true. On the CSV demo the Vampire Fees card *Bank
fees on this statement* (record V37 of `data/live_runs/2026-11-16_llama3.2-3b_calc2.json`) said
`rejected (not found in the cited rows or the alert data: 2025, 2026)`, while the cited rows and
the fixed template both hold those years (`Between 2025-01-02 and 2026-10-30`); the Phantom card
of record P27 said the same for `24, 2026`. `scripts/ledger_scan.py check` with `These charges
started in 2026` is rejected, while `2026-05-08` passes.

What the guard does with dates today (read in `_tokenise` and `_passes_number_guard`, pinned by
`tests/test_guard_year_wording.py`; no rule changes in this amendment):

| Form | Example | Today |
|---|---|---|
| ISO date | `2026-05-08` | parsed to a date; accepted when it is a date cell of a visible row or a date of the alert data, else rejected as `2026-05-09` |
| DD/MM/YYYY | `08/05/2026` | same as ISO |
| English month, day and year | `June 18, 2025`, `18 June 2025` | same as ISO |
| English month and day, no year | `June 18` | matched by month and day to the allowed dates |
| Year on its own | `in 2026` | a plain number token `2026`: rejected unless the value 2026 is a number of the rows or the alert data (an invoice number such as `F-2026-0310` holds it) |
| Month and year | `June 2026` | the same: `June` is not a date without a day, `2026` is a plain number |
| Spanish month name | `18 de junio de 2025` | not read as a date: `18` and `2025` are plain numbers, each rejected unless it is a number of the data |

- **REQ-GH-24** *When* a figure rejection (empty `rejected_reason`) holds a token that is a plain
  whole number of `YEAR_DIGITS` (4) ASCII digits from `YEAR_MIN` (1900) to `YEAR_MAX` (2099), with
  no separator, decimal part, currency or percent sign (`live_guard.is_year_alone`), the badge
  (`rejection_clause`, `rejection_reason_text`, and through them `replay.card_badge` and the
  apps' `guard_badge`) shall say `a year on its own is not matched to the dates of the rows:
  YEARS` (`BADGE_YEAR_ALONE`) for those tokens, and the Provoke verdict (`verdict_line`) shall say
  `A year on its own is not matched to the dates of the rows: ` (`VERDICT_YEAR_ALONE`) with the
  tokens in backticks. Every other token shall keep the words `not found in the cited rows or the
  alert data`. *If* both kinds are rejected, *then* the badge shall give both phrases, the other
  figures first, in one parenthesis separated by `; `, and the verdict two sentences. A
  calculation, a price index, a period or a currency rejection shall keep its own words.
  - AE-GH-24

    | Rejected tokens | Badge clause |
    |---|---|
    | `2025`, `2026` (V37) | ` (a year on its own is not matched to the dates of the rows: 2025, 2026)` |
    | `24`, `2026` (P27) | ` (not found in the cited rows or the alert data: 24; a year on its own is not matched to the dates of the rows: 2026)` |
    | `98765.43`, `2026.00`, `2100`, `1899` | ` (not found in the cited rows or the alert data: ...)`, as before |
    | `$` (Z03) | the currency sentence, as before |

- **REQ-GH-25** The amendment shall change words only. The outcome of every record of
  `2026-11-16_llama3.2-3b_calc2.json` (source, rejected tokens, reason) shall be pinned as a
  literal list and shall be the same before and after: 43 records, 33 accepted, 10 on the fixed
  template (Z03, Z04, Z05, Z22, P27, P32, V37, V41, V42, V43). The README section `What the guard
  does not check` shall gain a **Dates** bullet with the findings above, and its **Meaning** bullet
  the V35 example: the answer calls `€61.00` the critical overdraft cost and gives a total of
  `€106.00`; 61.00 is `interest_total` and 106.00 is `total` (`interest_total` + `fee_total`), both
  in the alert data, so the guard accepts it.

## 8 — Amendment A-GH-02 (session s52): a number in words is shown as the answer wrote it

The gate-2 execution review of 25 Nov saw a badge that showed a rejected number in words glued,
`twohundredandsixty-four`, where the answer wrote `two hundred and sixty-four`.

- **REQ-GH-26** *When* a rejected token is made only of letters, spaces and hyphens (a number in
  words, a currency code) and the model's answer is known, the card badge of the three apps
  (`guard_badge`, through `rejection_reason_text`), the replay badge (`replay.card_badge`, through
  `rejection_clause`), the Provoke verdict (`verdict_line`) and the highlight
  (`highlight_segments`) shall show the token as the answer wrote it: its letters are looked up in
  the answer as whole words, case as written, with any white space or none between two letters,
  and the first match is shown with each run of white space as one space
  (`live_guard.shown_token`). A token not found in the answer, a token with a digit or a sign, and
  the tokens of a calculation or a price-index rejection are shown as before. `rejected_numbers`,
  every rule of the guard, every recorded run and every pinned verdict stay as they are: only the
  words shown change.
  - AE-GH-26

    | Rejected token | Answer | Shown |
    |---|---|---|
    | `twohundredandsixty-four` | `SHOP charges two hundred and sixty-four euros.` | `two hundred and sixty-four` |
    | `twohundredandsixty-four` | `two  hundred` + line break + `and` + tab + `sixty-four` | `two hundred and sixty-four` |
    | `two hundred and sixty-four` | the first answer | `two hundred and sixty-four` (the guard's own token) |
    | `539.40`, `2026-05-09`, `$` | any | unchanged |
    | `once` | `A concession was made.` | `once` (no whole word, unchanged) |

## Out of scope

Other languages; ordinals; fractions and decimals in words (`three point five`); amounts with
cents in words; changing the badge, verdict or Home texts, `README.md`, `ledger_kit/replay.py`
(all part 2).
