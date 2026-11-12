# Hook runs

`hook_log.jsonl` is the log of the Kiro CLI hooks defined in `.kiro/hooks/review-gate.json` and run
by `scripts/kiro_hooks.py`. The hooks write it during real Kiro calls: one line after each file the
agent writes (`post-write`) and one when the agent stops (`stop`). Nobody edits it by hand, and it is
not created by hand; if the file is missing, no hook has run yet.

One JSON object per line, with exactly these keys:

| Key | Meaning |
|---|---|
| `time` | Local clock, ISO format, seconds (for example `2026-11-10T12:00:00`). |
| `event` | `post-write` or `stop`. |
| `session` | The `session_id` Kiro sent, or `unknown`. |
| `file` | Repo-relative path with forward slashes (`post-write` only), `outside-repo` for a path outside the repo, else `null`. |
| `checks` | The checks that ran: `ruff check`, `ruff format --check`, `ruff check .`, `pytest`. |
| `result` | `pass`, `fail`, `skipped` or `error`. |
| `detail` | At most 200 characters: the pytest summary line, the ruff error codes, or the skip reason. |
| `seconds` | Duration of the run, one decimal. |

The log holds no absolute path, user name, prompt text or file content. It contains no financial data.
