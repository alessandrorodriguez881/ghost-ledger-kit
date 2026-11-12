# Tasks — cli-hooks

Test first: each task writes or extends tests before the code they check.

- [x] CH1 Spec: `requirements.md` (REQ-CH-01 to 17, AE-CH-01 to 12), `design.md`, `tasks.md`.
- [x] CH2 Tests first: `tests/test_cli_hooks.py` with a fake repo root, fake runner and fixed clock
  (REQ-CH-02 to 16, AE-CH-01 to 12). `tests/test_kiro_hooks.py` is a different file: it keeps
  checking the three IDE hook files.
- [x] CH3 `scripts/kiro_hooks.py`, standard library only: post-write, stop, state file, log
  (REQ-CH-01 to 15).
- [x] CH4 `.kiro/hooks/review-gate.json` with `lint-after-write` and `tests-on-stop`, written after
  CH3 (REQ-CH-16). The three `.kiro.hook` files stay unchanged.
- [x] CH5 `data/hook_runs/README.md` and the `.gitignore` lines `!data/hook_runs/` and
  `!data/hook_runs/**` next to `data/live_runs` (REQ-CH-17). `hook_log.jsonl` is not created by hand.
- [x] CH6 `.kiro/steering/update-kiro-usage.md`: only the hooks line changed. `README.md` untouched.
- [x] CH7 First verification by a developer with a shell: `python -m pytest -q tests/test_cli_hooks.py`,
  `python -m ruff check scripts/kiro_hooks.py tests/test_cli_hooks.py` and
  `python -m ruff format --check scripts/kiro_hooks.py tests/test_cli_hooks.py`. Fix what they report.
  Done in the review of session 20a: the new tests had replaced the existing
  `tests/test_kiro_hooks.py` (7 tests, the three IDE hook files); that file was restored from git and
  the new tests, unchanged, moved to `tests/test_cli_hooks.py`. Both files pass: 37 passed in 1.53 s.
  `ruff format --check` was clean; `ruff check` had one error, E501 on line 1 of
  `tests/test_cli_hooks.py` (module docstring, 102 characters), fixed in session 20b by rewrapping the
  docstring. The hooks loaded during session 20a itself once `.kiro/hooks/review-gate.json` existed
  (see CH8).
- [x] CH8 Record of Kiro calls. Filled from `data/hook_runs/hook_log.jsonl`, which was not edited.
  Session 20a wrote the spec, the script, the hook file and the tests in one call; session 20b made
  the fixes above and the README text.

| Call (date, prompt name) | post-write lines | stop line | result | Reviewer note |
|---|---|---|---|---|
| 12 Nov, session 20a (spec, script, hook file and tests in one call) | 12: 8 on the test file (ruff E501 each, ruff F821 in one), 4 skipped as not `.py` | 1: `ruff check .` and pytest, 2137 passed in 185.92 s, ruff E501 reported | post-write: fail on the 8 test-file runs, skipped on the other 4; stop: fail | The run that reported F821 (undefined name) on the test file was followed by a write of that file without it. The E501 was still reported by the last write and the stop run; fixed in session 20b. |
| 12 Nov, session 20c (the two README text fixes, after the stop hook of 20b reported the failing README test) | not read from the log | 1 from 20b: 1 failed, 1984 passed (`tests/test_readme.py::test_every_backticked_path_exists`, path `.kiro.hook`) | fix written; the run of 20c itself is not recorded here | The README test was not changed. Row filled from the report of the 20b stop line, not from a new reading of the log. |
| | | | | |
