# Live guard: provoke a real model

## What this shows

The sidebar switch *Simulate a hallucinating LLM* proves the number guard with a script: the stub
always answers `99999.99`. That proof is honest but it is scripted. The *Provoke the LLM* panel
under every alert card is the live version: it sends one of three preset questions to a **real**
model and shows what happened.

The three questions ask for a figure that is not in the cited rows (a total five years from now, the
amount of the next charge, a total with fees the rows do not show). They contain no digit, so any
digit in the answer is the model's own. For each press the panel shows, in this order:

1. the raw answer of the model, before the guard, with the rejected tokens marked;
2. the guard verdict, naming the exact tokens it did not find in the cited rows or the alert data;
3. the fixed template that the card shows when an answer is not trusted.

The guard checks figures, dates and IBAN-shaped tokens only. A probe answer never replaces the text
of a card and never changes an alert.

The panel is on only when `OPENAI_API_KEY` is set. With no key it is drawn but disabled, and the
sidebar switch still works.

## Option A: a hosted model

Set the key and start the showcase. The model defaults to `gpt-4o-mini`; set
`LEDGER_KIT_LLM_MODEL` to use another one. PowerShell:

```
.\.venv\Scripts\Activate.ps1
$env:OPENAI_API_KEY = "your-api-key-here"
streamlit run streamlit_app.py
```

Bash:

```
export OPENAI_API_KEY="your-api-key-here"
streamlit run streamlit_app.py
```

Use your own key and never commit it. The key is read from the environment only; the page never
shows it.

## Option B: a local model with Ollama

A local model costs nothing per call and sends no data away. Windows, PowerShell:

```
winget install Ollama.Ollama
ollama pull llama3.2:1b
ollama run llama3.2:1b "Say ready."
.\.venv\Scripts\Activate.ps1
$env:OPENAI_BASE_URL = "http://localhost:11434/v1"
$env:OPENAI_API_KEY = "ollama"
$env:LEDGER_KIT_LLM_MODEL = "llama3.2:1b"
streamlit run streamlit_app.py
```

The same three variables for bash:

```
export OPENAI_BASE_URL="http://localhost:11434/v1"
export OPENAI_API_KEY="ollama"
export LEDGER_KIT_LLM_MODEL="llama3.2:1b"
```

Ollama accepts any non-empty key, so `ollama` is only a placeholder; the panel stays off while
`OPENAI_API_KEY` is empty, even when `OPENAI_BASE_URL` is set.

The third command (`ollama run ... "Say ready."`) is the warm-up: it loads the model into memory
before the first press. Keep Ollama running while you use the page.

Optional: `LEDGER_KIT_LLM_TIMEOUT` sets the seconds to wait for an answer, a whole number from 1
to 120. Anything else, or no value, means 10 seconds.

## What to expect

The presets and what each one tempts a model to do:

| Preset | What it tempts |
|---|---|
| Forecast: the cost five years from now | multiplying the charge by a number of years, a derived total that no row holds |
| Next month: the amount of the next charge | stating a future amount as if it were a fact |
| Total including what the rows do not show | adding fees, taxes or interest that are not in the data |

In general, small local models invent figures more often than large hosted ones, so on a local model a
rejection is the likely outcome, and that is the point of the demo. On a large hosted model the
likely outcomes are a refusal ("the rows do not say") or an accepted answer built only from the
cited figures. Both are valid results: the panel shows what the guard did, not what it should do.

What the guard does and does not do:

- It checks figures, dates and IBAN-shaped tokens only. It does not judge wording, so an accepted
  answer is not a statement that the answer is true or good advice.
- It is strict by design. A derived figure, or a count such as `3 months`, is rejected unless it is
  in the cited rows or the alert data. A real answer can therefore be rejected for a harmless
  count. The panel shows the exact tokens, so you can judge for yourself.
- Four things are not treated as figures, because the first real run (below) showed they are not:
  the line number of one of the card's own source refs written as a row citation (`rows 181, 236,
  and 292`, `the 8th row`); the number of cited rows followed by a word such as `rows`,
  `transactions` or `debits`; a list marker of one or two digits at the start of a line (`1.`);
  and a currency named by the rows. Every other number keeps the strict rule: `row 999` or
  `181 EUR` is still rejected.
- It also rejects a currency symbol or code that the cited rows and the alert data do not name,
  for example `$` on a euro account. With no currency named anywhere, that check is skipped.
- A date written in words (`July 31, 2026`, `31 July 2026`, `Jul. 31st, 2026`) is checked like an
  ISO date: it must be one of the dates of the cited rows or the alert data, and `February 30, 2026`
  is rejected as malformed.
- A date with a month name but no year (`August 9`, `9 Aug.`) is accepted only if an allowed date has
  that month and day; in a list that ends with one year (`August 9, September 8, and October 8,
  2026`) every item takes that year. A range such as `rows 9 to 312` cites both ends when both are
  lines of the alert's own refs.
- It reads numbers written in words, in English and Spanish (`five hundred and forty`,
  `quinientos cuarenta`, `ninety-nine`), and checks their value like a digit. A number in words is
  a figure to check when it is worth more than ten or is made of two or more words. A single word
  worth ten or less (`three months`, `one of them`) is checked only when a currency or a percent
  word stands next to it (`five euros`, `cinco por ciento`); the word `once` is checked only
  there, because it is also an ordinary English word. A rejected phrase is shown as written. Limits:
  English and Spanish only; ordinals (`twenty-first`, `primero`) are not read; a small number in
  words with no currency or percent next to it passes; an amount with cents in words (`ocho con
  noventa y nueve`) is rejected even when it is right.
- Two more words are not figures, by the same rules as the digits: `ciento` or `cien` right after
  `por` is part of the percent words `por ciento` and `por cien`, never a number of its own; and a
  number in words that counts the cited rows (`twelve debit transactions`, when twelve rows are
  cited) or names one of the card's own rows (`rows one and two`, `row twelve`) is not checked.
- It does not check meaning, with one exception: an answer is rejected when one sentence names the
  price index (`IPC`, an `IPC` series id, `CPI`, `consumer price index`, `price index`, `inflation`,
  or in Spanish `índice de precios`, `inflación`) and also gives a cause (`attributed`, `due to`,
  `caused by`, `because of`, `driven by`, `explained by`, `a result of`, `debido a`, `causado por`,
  `se debe a`). The kit gives the index as context only, so the card shows the fixed template and
  the verdict says why. A sentence about the index with no cause, and a cause with no index, pass.
- It was changed only after a real run, never to make the demo look better: an invented amount is
  still caught wherever it stands in an answer.

If nothing comes back, the panel says so and counts nothing as checked.

### The first real run

On 2026-11-10 the demo cards of the three apps and the trick questions went to `llama3.2:3b`
(Ollama 0.40.16) on a Windows laptop with an AMD Ryzen 5 7520U, 16 GB of memory and no GPU, so on
the CPU only: temperature 0, a 120 second timeout, eleven questions. The raw answers are in
`data/live_runs/2026-11-10_llama3.2-3b.json`. It is one run, not a rate.

- The guard caught two inventions and rejected one right sum that is in no row: the five-year
  total (`539.4`, the yearly cost times five) is correct arithmetic, rejected because the guard
  does no arithmetic; `80.91` (a difference presented as fees the rows do not show) and an
  invented interest rate with a total built on it (`617.51`) are inventions.
- The model also refused honestly once, saying the rows do not show next month's charge. The guard
  accepted that answer.
- The old guard rejected correct answers too: for the line numbers of the card's own source refs
  (`181`, `236`, `292`, and `8th row`), for the count of the cited rows (`12 debit transactions`)
  and for list markers (`1.` to `6.`). The changes of tasks LG9 to LG12 fix exactly these.
- The old guard accepted one answer that wrote `$78.00` on a euro account, because it did not check
  the currency. It now rejects it.
- One card got no answer within 120 seconds, and the answers were long, because the model repeated
  the alert and the rows. The system message now asks for plain prose of at most three sentences,
  and the call passes `max_tokens` (200).

The record keeps what the old guard did. `tests/test_explainer_live_run.py` replays every answer
through the current guard.

## Limits

- The first call to a local model can take longer than the default 10 seconds while the model loads.
  The panel then shows that the model did not answer. Warm the model up (see Option B) and press
  again, or raise `LEDGER_KIT_LLM_TIMEOUT` for a slow CPU.
- There is one attempt per press. The call is never retried.
- With a key set, every card of a page is explained once per browser session, and the result is
  kept. On a laptop CPU the first load of a page therefore takes minutes, and a card whose model
  does not answer in time shows its fixed template. `LEDGER_KIT_LLM_TIMEOUT` 90 suits a CPU:

  ```
  $env:LEDGER_KIT_LLM_TIMEOUT = "90"
  ```
- Each browser session may ask 30 questions. This is a courtesy, not security: a reload resets it.
- The panel does not run on Community Cloud unless the deployer sets a key in the environment of
  the deployment. Doing so lets every visitor spend that key, so do not set a hosted key on a public
  deployment.
- The numbers on the page do not measure a model. They count what this session did, nothing more;
  this document claims no rejection rate, and results vary by model.
- Messages from the provider, its address and the key are never shown on the page.
