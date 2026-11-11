# kiro_prompts

The saved prompts that built this repository, and the script that sent them. This folder holds the saved prompts, not all of them: the first calls (the ledger-core spec and most of the zombie-subscriptions spec) were sent as inline text and not saved as files, which is why only two `z` files exist. Each `.txt` file is the exact text of one call to Kiro CLI (spec mode), plus `run_kiro.ps1`. Kiro's output logs are not kept.

Claude Code, the AI coding assistant named in Who did what in the main README, drafted these prompts and sent them to Kiro CLI on the author's account, one call per file. After each call the tests were run and any failure went back to Kiro in the next prompt.

## How to read the names

In build order:

- `p` files (`p6`, `p10`, `p14`, `p18`, `p22`): the phantom-invoices spec. The number is the first task of the batch the call implements, so `p6` does tasks P6 to P9. Each one also ticks the boxes of the batch checked before it in `tasks.md`.
- `z` files (`z21`, `z9_fix`): the zombie-subscriptions spec, with the same task numbering. Only these two zombie calls were saved.
- `s` files (from `s5a` to the latest `s` file in the folder): later work, numbered by session. The letter orders the calls inside a session (`s9a` to `s9d`). Examples: `s5a` the Kiro hooks, `s6a` the showcase page, `s9a` to `s9d` the INE CPI data, `s10a` the benchmark spec, `s18a` the README rewrite.
- `_fix` files (`p6_fix`, `z9_fix`, `s5b_fix`, `s7a_fix`): a retry of the call with the same number after it failed. They give the failing test or error and ask for the smallest change.

## Prompts contain no double quotes

PowerShell 5.1 splits a command-line argument at a double quote. `run_kiro.ps1` joins the file into one argument and throws `double quote in prompt` if it finds one, so the prompts use none.

## Rerun one call

From PowerShell, in any folder:

```powershell
.\kiro_prompts\run_kiro.ps1 -Name s16a
```

`-Name` is the file name without `.txt`. Optional switches:

- `-ExtraTools`: comma-separated tool ids (for example MCP tools) added to the trusted list.
- `-Agent`: run the call with a workspace custom agent from `.kiro/agents`, for example `ghost-ledger-builder`.

The script writes Kiro's answer to `<Name>_out.txt` here (ignored by git), then runs ruff and pytest. A rerun calls the model again and edits the files, so expect a different result and review `git status` first.

## One edit to the script

Its `Set-Location` line used the absolute path of the author's local clone; it now goes to the repository root. Nothing else was changed.
