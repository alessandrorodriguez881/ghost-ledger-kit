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
- It is strict by design. A derived figure, a list number such as `1.`, or a count such as
  `3 months` is rejected unless it is in the cited rows or the alert data. A real answer can
  therefore be rejected for a harmless count. The panel shows the exact tokens, so you can judge
  for yourself.
- It is not changed for the demo. Loosening it would defeat the demo.

If nothing comes back, the panel says so and counts nothing as checked.

## Limits

- The first call to a local model can take longer than the default 10 seconds while the model loads.
  The panel then shows that the model did not answer. Warm the model up (see Option B) and press
  again, or raise `LEDGER_KIT_LLM_TIMEOUT` for a slow CPU.
- There is one attempt per press. The call is never retried.
- Each browser session may ask 30 questions. This is a courtesy, not security: a reload resets it.
- The panel does not run on Community Cloud unless the deployer sets a key in the environment of
  the deployment. Doing so lets every visitor spend that key, so do not set a hosted key on a public
  deployment.
- The numbers on the page do not measure a model. They count what this session did, nothing more;
  this document claims no rejection rate, and results vary by model.
- Messages from the provider, its address and the key are never shown on the page.
