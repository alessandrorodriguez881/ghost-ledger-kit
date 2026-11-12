# Design — cli-hooks

## Overview

Kiro CLI V3 starts `python scripts/kiro_hooks.py EVENT` from the workspace root and writes one JSON
object on stdin. Two hooks in `.kiro/hooks/review-gate.json` call it:

| Hook | Trigger | Matcher | Command | Timeout |
|---|---|---|---|---|
| lint-after-write | PostToolUse | write | `python scripts/kiro_hooks.py post-write` | 60 |
| tests-on-stop | Stop | none | `python scripts/kiro_hooks.py stop` | 600 |

The hooks are not part of the three-layer pipeline (ingestion, detectors, explanation). They touch no
financial data, no model and no network. Exit 0 puts stdout into the agent context; a nonzero exit
sends stderr to the agent as a hook error (REQ-CH-06 only).

## Flow

```
stdin JSON -> handle(event, raw, root, clock, runner, state_dir)
                |-- json.loads -> payload (dict) -> session
                |-- post_write(...)  -> Report
                |-- stop(...)        -> Report
                |-- any exception    -> Report(result="error", detail=exception class name)
                `-- write_log(root, one line) -> Outcome(code, stdout, stderr)
```

`main()` only reads stdin, builds `root` from `__file__`, passes `datetime.now` and `real_runner`, and
prints the Outcome.

## Units (scripts/kiro_hooks.py)

| Function | Role | Requirement |
|---|---|---|
| `extract_path(payload)` | `tool_input.path`, else `file_path`, else None | REQ-CH-02 |
| `relative_to_repo(raw, root)` | repo-relative, forward slashes, or `outside-repo` | REQ-CH-02, 07, 13 |
| `safe_session`, `state_file`, `read_state`, `record_touched` | per-session state under the temp folder | REQ-CH-02, 03 |
| `repo_python(root)` | `.venv/Scripts/python.exe` or `.venv/bin/python`, else `sys.executable` | REQ-CH-04 |
| `post_write(...)` | record, skip or lint; builds the Report | REQ-CH-04 to 07 |
| `select_targets(files)` | touched files to sorted, unique pytest targets | REQ-CH-08 |
| `stop(...)` | `ruff check .`, pytest on targets, summary, state removal in `finally` | REQ-CH-09 to 11 |
| `ruff_codes`, `pytest_summary`, `first_failing_test` | parse command output | REQ-CH-10, 12 |
| `scrub(text, root)` | replace the repo root with `.` and the home folder with `~` | REQ-CH-13 |
| `write_log(root, line)` | append one JSON line; write failure ignored | REQ-CH-12 |
| `handle(...)`, `main()` | wiring and the catch-all | REQ-CH-14, 15 |

Types: `Runner = Callable[[argv, cwd, timeout_seconds], RunResult]`, `Clock = Callable[[], datetime]`.
`RunResult` is the return code plus combined stdout and stderr. The real runner is `subprocess.run`
with a timeout; a timeout raises `subprocess.TimeoutExpired`, which `handle` turns into `error`.

## Decisions

- Threshold constants are named at the top of the module (Finance Rule 7 spirit): ruff timeouts, the
  540 s pytest limit, 40 finding lines, 200 detail characters.
- Interpreter: `.venv` if present, else `sys.executable`. A missing `.venv` is therefore not an error
  by itself; ruff missing from the chosen interpreter (`No module named ruff`, or a return code other
  than 0 or 1) is logged as `error` and does not fail the write.
- ruff return code 1 is a finding; any other nonzero code is an `error`. pytest return codes 0 and 5
  (no tests collected) count as pass, 1 as fail, others as error.
- Both ruff commands always run after a `.py` write so the agent sees check and format findings at once.
  Paths passed to ruff are repo-relative with the repo root as working directory.
- Log `detail` and exception handling never use exception messages (they can hold paths); only the
  exception class name is logged. Command output is passed through `scrub` before it is logged or
  printed.
- Stop result: `error` if any check errored, else `fail` if any failed, else `pass`.
- Files outside the repo are not recorded in the state file; `.md` files are (they select no target).
- Only a real ruff finding in post-write exits 1. Stop always exits 0 so the agent does not loop.

## Files

| File | Purpose |
|---|---|
| `scripts/kiro_hooks.py` | the hook script |
| `.kiro/hooks/review-gate.json` | the two CLI hooks (`.kiro.hook` IDE files stay unchanged) |
| `data/hook_runs/README.md` | what the log is; the log itself is written only by the hooks |
| `.gitignore` | `!data/hook_runs/` and `!data/hook_runs/**` after the `data/live_runs` lines |
| `tests/test_cli_hooks.py` | tests with a fake root, runner and clock |
| `.kiro/steering/update-kiro-usage.md` | the hooks line lists `*.json` (CLI and IDE) and `*.kiro.hook` (IDE only) |

## Testing

`tests/test_cli_hooks.py` loads the script by path, builds payloads from the keys in the acceptance
examples, uses `tmp_path` for the repo root and the state folder, a fixed clock and a fake runner. No
real ruff or pytest runs, no network. It also checks the JSON config and that the script imports only
standard-library modules. The repo test suite is not property-based for this script (it is tooling, not
a detector).

`tests/test_kiro_hooks.py` is a different file and keeps checking the three IDE hook files.

## Not verifiable here

The author had no shell. The tests and the real hooks were not run in that session; the first run of
`pytest tests/test_cli_hooks.py` and `ruff check` / `ruff format --check` on the new files is part of
task CH7, and real Kiro calls fill the log (task CH8).
