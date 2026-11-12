"""Kiro CLI hooks of this repo: lint after each write, tests of the touched files on stop.

Run as ``python scripts/kiro_hooks.py EVENT`` with EVENT ``post-write`` or ``stop``. Kiro sends one
JSON object on stdin. Standard library only. Every run appends one line to
``data/hook_runs/hook_log.jsonl`` (repo-relative paths only, see ``data/hook_runs/README.md``).

Exit codes: 0 always, except ``post-write`` with a real ruff finding (1), so the agent sees the
findings on stderr and can fix the file. A failing ``stop`` hook would keep the agent looping.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# Time limit of each ruff call after a write, in seconds.
RUFF_TIMEOUT_SECONDS: int = 30
# Time limit of ``ruff check .`` on stop, in seconds (whole repo, so more than one file).
RUFF_STOP_TIMEOUT_SECONDS: int = 120
# Time limit of the pytest run on stop, in seconds (the hook itself allows 600).
PYTEST_TIMEOUT_SECONDS: int = 540
# Most lines of ruff findings sent to the agent on stderr.
MAX_FINDING_LINES: int = 40
# Most characters of the ``detail`` key of a log line.
MAX_DETAIL_CHARS: int = 200
# Name written to the log instead of a path outside the repo.
OUTSIDE_REPO: str = "outside-repo"
# Session name used when the payload carries none.
UNKNOWN_SESSION: str = "unknown"
# Subfolder of the system temp folder that holds the per-session state files.
STATE_SUBDIR: str = "ghost-ledger-hooks"
# Log file, relative to the repo root.
LOG_RELATIVE_PATH: str = "data/hook_runs/hook_log.jsonl"
# Top-level folders whose files make the shared tests run on stop.
SHARED_TEST_FOLDERS: frozenset[str] = frozenset({"ledger_kit", "scripts", "tests"})
# The exact keys of a log line.
LOG_KEYS: tuple[str, ...] = (
    "time",
    "event",
    "session",
    "file",
    "checks",
    "result",
    "detail",
    "seconds",
)

_RUFF_CODE = re.compile(r"^\s*(?:\S+:\d+:\d+:\s+)?([A-Z]{1,4}\d{2,4})\b", re.MULTILINE)
_PYTEST_SUMMARY = re.compile(
    r"\b\d+ (?:passed|failed|errors?|skipped|deselected|xfailed|xpassed)\b.* in [\d.]+s"
    r"|^no tests ran in [\d.]+s",
    re.IGNORECASE,
)
_FAILED_ID = re.compile(r"^(?:FAILED|ERROR) (\S+)", re.MULTILINE)


@dataclass(frozen=True)
class RunResult:
    """Return code and combined stdout and stderr of one command."""

    returncode: int
    output: str


Runner = Callable[[list[str], Path, int], RunResult]
Clock = Callable[[], datetime]


@dataclass(frozen=True)
class Outcome:
    """What main() prints and the exit code it ends with."""

    code: int
    stdout: str = ""
    stderr: str = ""


@dataclass
class Report:
    """What one run did; becomes the log line and the Outcome."""

    code: int = 0
    stdout: str = ""
    stderr: str = ""
    file: str | None = None
    checks: list[str] = field(default_factory=list)
    result: str = "skipped"
    detail: str = ""


def real_runner(argv: list[str], cwd: Path, timeout: int) -> RunResult:
    """Run a command in ``cwd``; raises ``subprocess.TimeoutExpired`` past ``timeout`` seconds."""
    done = subprocess.run(
        argv,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    return RunResult(done.returncode, (done.stdout or "") + (done.stderr or ""))


def repo_python(root: Path) -> str:
    """Return the repo interpreter (.venv), else the interpreter running this script."""
    if os.name == "nt":
        candidate = root / ".venv" / "Scripts" / "python.exe"
    else:
        candidate = root / ".venv" / "bin" / "python"
    return str(candidate) if candidate.is_file() else sys.executable


def default_state_dir() -> Path:
    """Return the folder of the session state files, under the system temp folder."""
    return Path(tempfile.gettempdir()) / STATE_SUBDIR


def safe_session(session_id: str) -> str:
    """Return ``session_id`` with every character outside letters, digits, - and _ replaced."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", session_id) or UNKNOWN_SESSION


def state_file(state_dir: Path, session_id: str) -> Path:
    """Return the state file of one session."""
    return state_dir / f"{safe_session(session_id)}.json"


def extract_path(payload: dict) -> str | None:
    """Return the written path of a PostToolUse payload: ``path``, else ``file_path``, else None."""
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    for key in ("path", "file_path"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def relative_to_repo(raw: str, root: Path) -> str:
    """Return ``raw`` repo-relative with forward slashes, or ``OUTSIDE_REPO``."""
    path = Path(raw)
    if not path.is_absolute():
        path = root / path
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        return OUTSIDE_REPO


def scrub(text: str, root: Path) -> str:
    """Replace the repo root and the home folder in ``text`` so no absolute path leaves."""
    out = text
    for prefix, name in ((root, "."), (root.resolve(), "."), (Path.home(), "~")):
        for form in (str(prefix), prefix.as_posix()):
            if form and form not in (".", "/"):
                out = out.replace(form, name)
    return out


def select_targets(files: list[str]) -> list[str]:
    """Return the pytest targets of the touched files: each once, sorted."""
    targets: set[str] = set()
    for item in files:
        parts = item.split("/")
        if parts[0] == "apps" and len(parts) >= 3:
            targets.add(f"apps/{parts[1]}/tests")
        elif parts[0] in SHARED_TEST_FOLDERS and len(parts) >= 2:
            targets.add("tests")
    return sorted(targets)


def ruff_codes(output: str) -> list[str]:
    """Return the ruff error codes in ``output``, each once, in order of appearance."""
    seen: list[str] = []
    for code in _RUFF_CODE.findall(output):
        if code not in seen:
            seen.append(code)
    return seen


def pytest_summary(output: str) -> str:
    """Return the last summary line pytest printed, or an empty string."""
    for line in reversed(output.splitlines()):
        if _PYTEST_SUMMARY.search(line):
            return line.strip().strip("=").strip()
    return ""


def first_failing_test(output: str) -> str:
    """Return the id of the first failing test in ``output``, or an empty string."""
    match = _FAILED_ID.search(output)
    return match.group(1) if match else ""


def read_state(state_dir: Path, session_id: str) -> list[str]:
    """Return the touched files of a session; an unreadable state file counts as empty."""
    try:
        data = json.loads(state_file(state_dir, session_id).read_text(encoding="utf-8"))
        files = data.get("files", [])
        return [f for f in files if isinstance(f, str)]
    except (OSError, ValueError, AttributeError):
        return []


def record_touched(state_dir: Path, session_id: str, rel: str) -> None:
    """Add ``rel`` to the state file of the session, once."""
    files = read_state(state_dir, session_id)
    if rel not in files:
        files.append(rel)
    state_dir.mkdir(parents=True, exist_ok=True)
    state_file(state_dir, session_id).write_text(json.dumps({"files": files}), encoding="utf-8")


def _limited(text: str, limit: int) -> str:
    """Cut ``text`` to ``limit`` characters."""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def post_write(
    payload: dict, root: Path, runner: Runner, state_dir: Path, session_id: str
) -> Report:
    """Record the written path and lint it with ruff when it is a .py file inside the repo."""
    raw = extract_path(payload)
    if raw is None:
        return Report(stdout="kiro_hooks: skipped, no path in tool_input", detail="no path")
    rel = relative_to_repo(raw, root)
    if rel == OUTSIDE_REPO:
        return Report(
            stdout="kiro_hooks: skipped, path outside the repo",
            file=OUTSIDE_REPO,
            detail="path outside the repo",
        )
    record_touched(state_dir, session_id, rel)
    if not rel.endswith(".py"):
        return Report(
            stdout=f"kiro_hooks: skipped, {rel} is not a .py file",
            file=rel,
            detail="not a .py file",
        )
    python = repo_python(root)
    commands = {
        "ruff check": [python, "-m", "ruff", "check", rel],
        "ruff format --check": [python, "-m", "ruff", "format", "--check", rel],
    }
    outputs: list[str] = []
    failed = False
    for name, argv in commands.items():
        done = runner(argv, root, RUFF_TIMEOUT_SECONDS)
        if "No module named ruff" in done.output or done.returncode not in (0, 1):
            return Report(
                stdout="kiro_hooks post-write: error, ruff is not usable",
                file=rel,
                checks=list(commands),
                result="error",
                detail=f"{name} returned {done.returncode}",
            )
        if done.returncode == 1:
            failed = True
            outputs.append(done.output)
    if not failed:
        return Report(stdout=f"ruff OK on {rel}", file=rel, checks=list(commands), result="pass")
    joined = scrub("\n".join(outputs), root)
    lines = [line for line in joined.splitlines() if line.strip()][:MAX_FINDING_LINES]
    codes = ruff_codes(joined)
    detail = "ruff: " + (", ".join(codes) if codes else "format check failed")
    return Report(
        code=1,
        stderr="\n".join(lines),
        file=rel,
        checks=list(commands),
        result="fail",
        detail=detail,
    )


def stop(payload: dict, root: Path, runner: Runner, state_dir: Path, session_id: str) -> Report:
    """Run ruff on the repo and pytest on the targets of the touched files; never fails."""
    del payload
    try:
        files = read_state(state_dir, session_id)
        targets = select_targets(files)
        python = repo_python(root)
        checks = ["ruff check ."]
        details: list[str] = []
        lines: list[str] = []
        results: list[str] = []

        lint = runner([python, "-m", "ruff", "check", "."], root, RUFF_STOP_TIMEOUT_SECONDS)
        if "No module named ruff" in lint.output or lint.returncode not in (0, 1):
            results.append("error")
            lines.append("ruff check .: error, ruff is not usable")
            details.append(f"ruff returned {lint.returncode}")
        elif lint.returncode == 0:
            results.append("pass")
            lines.append("ruff check .: OK")
        else:
            codes = ruff_codes(lint.output)
            results.append("fail")
            lines.append("ruff check .: findings " + (", ".join(codes) or "reported"))
            details.append("ruff: " + ", ".join(codes))

        if targets:
            checks.append("pytest")
            argv = [python, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", *targets]
            test = runner(argv, root, PYTEST_TIMEOUT_SECONDS)
            summary = scrub(pytest_summary(test.output), root)
            if test.returncode in (0, 5):
                results.append("pass")
            elif test.returncode == 1:
                results.append("fail")
            else:
                results.append("error")
            lines.append(f"pytest ({' '.join(targets)}): {summary or 'no summary line'}")
            if summary:
                details.append(summary)
            else:
                details.append(f"pytest returned {test.returncode}")
            failing = first_failing_test(scrub(test.output, root))
            if failing:
                lines.append(f"first failing test: {failing}")
        else:
            lines.append("pytest: not run, no touched code file")
            details.append("no pytest targets")

        result = "error" if "error" in results else "fail" if "fail" in results else "pass"
        return Report(
            stdout="\n".join(lines),
            checks=checks,
            result=result,
            detail="; ".join(details),
        )
    finally:
        try:
            state_file(state_dir, session_id).unlink(missing_ok=True)
        except OSError:
            pass


def write_log(root: Path, line: dict) -> None:
    """Append one JSON line to the hook log; a failure to write is ignored."""
    try:
        log = root / LOG_RELATIVE_PATH
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(line, ensure_ascii=False) + "\n")
    except OSError:
        pass


def handle(
    event: str,
    raw_stdin: str,
    root: Path,
    clock: Clock,
    runner: Runner,
    state_dir: Path | None = None,
) -> Outcome:
    """Run one hook event on the stdin text, log it and return what to print and the exit code."""
    started = clock()
    folder = state_dir if state_dir is not None else default_state_dir()
    session = UNKNOWN_SESSION
    try:
        payload = json.loads(raw_stdin)
        if not isinstance(payload, dict):
            raise ValueError("payload is not an object")
        session = str(payload.get("session_id") or UNKNOWN_SESSION)
        if event == "post-write":
            report = post_write(payload, root, runner, folder, session)
        elif event == "stop":
            report = stop(payload, root, runner, folder, session)
        else:
            raise ValueError("unknown event")
    except Exception as exc:  # a hook must never crash the agent
        name = type(exc).__name__
        report = Report(
            stdout=f"kiro_hooks {event}: error ({name}), nothing was checked",
            result="error",
            detail=name,
        )
    finished = clock()
    write_log(
        root,
        {
            "time": started.isoformat(timespec="seconds"),
            "event": event,
            "session": session,
            "file": report.file if event == "post-write" else None,
            "checks": report.checks,
            "result": report.result,
            "detail": _limited(scrub(report.detail, root), MAX_DETAIL_CHARS),
            "seconds": round((finished - started).total_seconds(), 1),
        },
    )
    return Outcome(report.code, report.stdout, report.stderr)


def main(argv: list[str] | None = None) -> int:
    """Wire stdin, the real clock and the real runner to ``handle``; return the exit code."""
    args = sys.argv[1:] if argv is None else argv
    event = args[0] if args else "unknown"
    try:
        raw = sys.stdin.read()
    except (OSError, ValueError):
        raw = ""
    root = Path(__file__).resolve().parents[1]
    outcome = handle(event, raw, root, datetime.now, real_runner)
    if outcome.stdout:
        print(outcome.stdout)
    if outcome.stderr:
        print(outcome.stderr, file=sys.stderr)
    return outcome.code


if __name__ == "__main__":
    sys.exit(main())
