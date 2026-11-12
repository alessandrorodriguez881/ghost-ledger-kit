# Requirements — cli-hooks

Session 20a. Hooks that really run in the Kiro CLI build of this repo.

## Context

The three `.kiro/hooks/*.kiro.hook` files are IDE hooks. The repo is built through Kiro CLI V3
(`kiro_prompts/run_kiro.ps1` uses `--v3 --mode spec --trust-workspace`), which does not read them.
Kiro CLI V3 runs standalone workspace hooks from `.kiro/hooks/*.json` (format version v1). Checked in
a throwaway folder: SessionStart, UserPromptSubmit, PostToolUse (matcher `write`) and Stop fired.

Facts relied on:

- The command runs in the workspace root and receives one JSON object on stdin.
- Keys seen: `session_id`, `hook_event_name`, `cwd`. PostToolUse adds `tool_name` (`fs_write` seen),
  `tool_input` (for `fs_write`: `path`, absolute, and `text`) and `tool_response` (a string).
- Other write tools may use other `tool_input` keys: read `path`, else `file_path`, else no path.
- Exit 0: stdout is added to the agent context. Any other exit: stderr goes to the agent as a hook error.
- `timeout` is in seconds (default 60).

## Glossary

- Hook script: `scripts/kiro_hooks.py`, standard library only.
- Touched file: a repo-relative path recorded by `post-write` in the session state file.
- Session state file: `<tempdir>/ghost-ledger-hooks/<safe session_id>.json`, never inside the repo.
- Hook log: `data/hook_runs/hook_log.jsonl`, one JSON object per line.

## Requirements

### REQ-CH-01 — Entry point

The hook script shall run as `python scripts/kiro_hooks.py EVENT` with EVENT `post-write` or `stop`,
read one JSON object from stdin, and import only standard-library modules.

### REQ-CH-02 — Record the written path

When `post-write` receives a payload with a path in `tool_input` (`path`, else `file_path`), the hook
script shall record the repo-relative path with forward slashes in the session state file of that
`session_id`, once.

### REQ-CH-03 — State outside the repo

The hook script shall keep the session state file under `tempfile.gettempdir()`, subfolder
`ghost-ledger-hooks`, named after a safe form of `session_id` (characters other than letters, digits,
`-` and `_` replaced by `_`), and shall never create it inside the repo.

### REQ-CH-04 — Lint after write

When `post-write` receives a `.py` file inside the repo, the hook script shall run
`python -m ruff check FILE` and `python -m ruff format --check FILE` with the repo interpreter
(`.venv/Scripts/python.exe` on Windows, `.venv/bin/python` elsewhere, else `sys.executable`), each with
a 30 s time limit.

### REQ-CH-05 — Lint pass

If both ruff commands succeed, the hook script shall print `ruff OK on FILE` to stdout and exit 0.

### REQ-CH-06 — Lint fail

If a ruff command reports findings, the hook script shall print at most 40 lines of findings to stderr
and exit 1, so the agent sees them. This is the only nonzero exit of the script.

### REQ-CH-07 — Skip

If the path is not a `.py` file, lies outside the repo, or is missing, `post-write` shall run no
check, print a one-line skip message and exit 0.

### REQ-CH-08 — Stop target selection

When `stop` runs, the hook script shall choose pytest targets from the touched files: a file under
`apps/NAME/` adds `apps/NAME/tests`; a file under `ledger_kit/`, `scripts/` or `tests/` adds `tests`;
any other file adds nothing. Each target appears once, in a stable order (sorted).

### REQ-CH-09 — Stop checks

When `stop` runs, the hook script shall run `ruff check .` and, only if there are targets,
`python -m pytest -q -x -p no:cacheprovider TARGETS` with a 540 s limit.

### REQ-CH-10 — Stop never fails

The `stop` event shall always exit 0 and print a short summary: the ruff result, the last summary line
of pytest (passed and failed counts) and the first failing test id, if any.

### REQ-CH-11 — State cleanup

At the end of `stop`, the hook script shall remove the session state file.

### REQ-CH-12 — Log

Every `post-write` and `stop` run shall append one JSON line to `data/hook_runs/hook_log.jsonl` with
exactly the keys `time` (local clock, ISO, seconds), `event`, `session`, `file` (repo-relative,
post-write only, else null), `checks` (list of check names), `result` (`pass`, `fail`, `skipped` or
`error`), `detail` (at most 200 characters) and `seconds` (one decimal).

### REQ-CH-13 — No leaks

The hook script shall write no absolute path, user name, prompt text or file content to the log,
stdout or stderr. A path outside the repo is written as `outside-repo`.

### REQ-CH-14 — Robustness

If stdin is empty or not JSON, ruff or the `.venv` is missing, a command times out, or any unexpected
exception occurs, the hook script shall log `result` `error`, print a one-line message and exit 0.

### REQ-CH-15 — Testable logic

The logic shall live in functions that take the payload, the repo root, a clock and a command runner;
`main()` shall only wire stdin, the real clock and the real runner.

### REQ-CH-16 — Hook configuration

`.kiro/hooks/review-gate.json` shall be valid JSON with `version` `v1` and two hooks:
`lint-after-write` (PostToolUse, matcher `write`, command `python scripts/kiro_hooks.py post-write`,
timeout 60) and `tests-on-stop` (Stop, command `python scripts/kiro_hooks.py stop`, timeout 600).
The three `.kiro.hook` files shall stay unchanged.

### REQ-CH-17 — Log documentation and tracking

`data/hook_runs/README.md` shall describe the log and its keys and say that the hooks write it and
nobody edits it by hand; `.gitignore` shall track `data/hook_runs/`. The log file is not created by hand.

## Acceptance examples

Payload tables list the stdin keys and values (`/fake/repo` stands for a `tmp_path` root).

### AE-CH-01 — fs_write on a clean .py file (REQ-CH-02, 04, 05, 12)

| Key | Value |
|---|---|
| hook_event_name | PostToolUse |
| session_id | s-1 |
| cwd | the repo root |
| tool_name | fs_write |
| tool_input.path | ROOT/ledger_kit/a.py |
| tool_input.text | any text |
| tool_response | ok |

Both fake ruff runs return code 0. Result: exit 0; stdout `ruff OK on ledger_kit/a.py`; state file lists
`ledger_kit/a.py`; log line has result `pass`, checks `["ruff check", "ruff format --check"]`.

### AE-CH-02 — fs_write on a .py file with findings (REQ-CH-06)

Same payload as AE-CH-01. The fake `ruff check` returns code 1 with output lines such as
`ledger_kit/a.py:1:1: F401 unused import`. Result: exit 1; stderr holds the findings (at most 40
lines); stdout empty; log result `fail`, detail holds the error codes (`F401`).

### AE-CH-03 — Markdown file (REQ-CH-07)

| Key | Value |
|---|---|
| hook_event_name | PostToolUse |
| session_id | s-2 |
| tool_name | fs_write |
| tool_input.path | ROOT/docs/x.md |

Result: exit 0; one-line skip message; the runner is never called; log result `skipped`; the path is
still recorded as touched.

### AE-CH-04 — Path outside the repo (REQ-CH-07, 13)

| Key | Value |
|---|---|
| session_id | s-3 |
| tool_name | fs_write |
| tool_input.path | an absolute path in another folder, ending in `.py` |

Result: exit 0; log `file` is `outside-repo`; result `skipped`; the other folder's name is nowhere in the log.

### AE-CH-05 — No path (REQ-CH-07)

| Key | Value |
|---|---|
| session_id | s-4 |
| tool_name | other_write |
| tool_input | `{}` (no `path`, no `file_path`) |

Result: exit 0; skip message; log `file` null, result `skipped`.

### AE-CH-06 — Bad stdin (REQ-CH-14)

Stdin is `not json`, or empty. Result: exit 0; one-line message; log result `error`, session `unknown`.

### AE-CH-07 — Timeout (REQ-CH-14)

Payload as AE-CH-01; the fake runner raises a timeout. Result: exit 0; log result `error`.

### AE-CH-08 — Stop without touched files (REQ-CH-09)

| Key | Value |
|---|---|
| hook_event_name | Stop |
| session_id | s-5 |
| cwd | the repo root |

No state file. Result: exit 0; only `ruff check .` runs; pytest is not called; log result `pass` (per
ruff), checks `["ruff check ."]`.

### AE-CH-09 — Stop target selection (REQ-CH-08)

Touched files `apps/zombie_subscriptions/a.py`, `apps/zombie_subscriptions/b.py`, `ledger_kit/c.py`,
`scripts/d.py`, `tests/e.py`, `docs/f.md`. Targets: `apps/zombie_subscriptions/tests`, `tests` (each once).

### AE-CH-10 — Stop with failing pytest (REQ-CH-10, 11)

Touched file `tests/e.py`; the fake pytest returns code 1 with a `FAILED tests/test_x.py::test_y` line
and the summary `1 failed, 3 passed in 0.5s`. Result: exit 0; stdout holds the ruff result, the summary
line and `tests/test_x.py::test_y`; log result `fail`; state file removed.

### AE-CH-11 — Log shape (REQ-CH-12, 13)

Every line of the log parses as JSON with exactly the eight keys time, event, session, file, checks,
result, detail, seconds, and contains no absolute path.

### AE-CH-12 — Configuration (REQ-CH-16)

`review-gate.json` parses, `version` is `v1`, and the two hooks match REQ-CH-16 exactly.
