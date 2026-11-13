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
    | `2026-11-11_llama3.2-3b_demo.json` | Z03, Z20, P27, V37 |

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

## Out of scope

Other languages; ordinals; fractions and decimals in words (`three point five`); amounts with
cents in words; changing the badge, verdict or Home texts, `README.md`, `ledger_kit/replay.py`
(all part 2).
