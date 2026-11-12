"""Tests of scripts/kiro_hooks.py with a fake repo root, runner and clock
(no real ruff or pytest).
"""

from __future__ import annotations

import ast
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "kiro_hooks.py"

_spec = importlib.util.spec_from_file_location("kiro_hooks", SCRIPT)
assert _spec is not None and _spec.loader is not None
hooks = importlib.util.module_from_spec(_spec)
sys.modules["kiro_hooks"] = hooks
_spec.loader.exec_module(hooks)

NOW = datetime(2026, 11, 10, 12, 0, 0)
FINDINGS = "\n".join(f"ledger_kit/a.py:{i}:1: F401 unused import" for i in range(1, 61))
PYTEST_FAIL = "FAILED tests/test_x.py::test_y - assert 1 == 2\n1 failed, 3 passed in 0.5s\n"


def clock() -> datetime:
    """Fixed clock."""
    return NOW


class FakeRunner:
    """Records every call; answers with ``answer(argv)`` or raises ``error``."""

    def __init__(self, answer=None, error: Exception | None = None) -> None:
        self.answer = answer
        self.error = error
        self.calls: list[tuple[list[str], Path, int]] = []

    def __call__(self, argv, cwd, timeout):
        self.calls.append((list(argv), cwd, timeout))
        if self.error is not None:
            raise self.error
        if self.answer is not None:
            return self.answer(argv)
        return hooks.RunResult(0, "")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A fake repo root."""
    folder = tmp_path / "repo"
    folder.mkdir()
    return folder


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    """A state folder outside the fake repo."""
    return tmp_path / "state"


def write_payload(path, session: str = "s-1", root: Path | None = None) -> dict:
    """A PostToolUse payload of an fs_write call."""
    return {
        "session_id": session,
        "hook_event_name": "PostToolUse",
        "cwd": str(root or ""),
        "tool_name": "fs_write",
        "tool_input": {"path": str(path), "text": "x = 1\n"},
        "tool_response": "ok",
    }


def stop_payload(session: str = "s-1", root: Path | None = None) -> dict:
    """A Stop payload."""
    return {"session_id": session, "hook_event_name": "Stop", "cwd": str(root or "")}


def run(event, payload, root, runner, state_dir):
    """Run handle() on a payload dict."""
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    return hooks.handle(event, raw, root, clock, runner, state_dir)


def log_lines(root: Path) -> list[dict]:
    """Parse the log of the fake repo."""
    text = (root / hooks.LOG_RELATIVE_PATH).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


def assert_no_absolute_path(text: str, tmp_path: Path) -> None:
    """The text holds neither the temp folder nor a drive or system folder path."""
    escaped = json.dumps(str(tmp_path))[1:-1]
    for form in (str(tmp_path), tmp_path.as_posix(), escaped):
        assert form not in text
    assert not re.search(r"[A-Za-z]:[\\/]", text)
    assert not re.search(r"(?<![\w.])/(?:home|Users|tmp|var)/", text)


def ruff_answer(argv):
    """Fake ruff: ``check`` reports findings, ``format`` passes."""
    if "check" in argv and "format" not in argv:
        return hooks.RunResult(1, FINDINGS)
    return hooks.RunResult(0, "")


def stop_answer(argv):
    """Fake stop run: ruff passes, pytest fails."""
    if "pytest" in argv:
        return hooks.RunResult(1, PYTEST_FAIL)
    return hooks.RunResult(0, "All checks passed!")


# --- post-write ---------------------------------------------------------------------------------


def test_post_write_passes_on_clean_py_file(root, state_dir):
    runner = FakeRunner()
    out = run("post-write", write_payload(root / "ledger_kit" / "a.py"), root, runner, state_dir)
    assert out.code == 0
    assert out.stdout == "ruff OK on ledger_kit/a.py"
    assert out.stderr == ""
    assert [c[0][3] for c in runner.calls] == ["check", "format"]
    assert all(c[1] == root and c[2] == hooks.RUFF_TIMEOUT_SECONDS for c in runner.calls)
    assert all(c[0][1:3] == ["-m", "ruff"] for c in runner.calls)
    assert runner.calls[0][0][-1] == "ledger_kit/a.py"
    assert runner.calls[1][0][-2:] == ["--check", "ledger_kit/a.py"]
    assert hooks.read_state(state_dir, "s-1") == ["ledger_kit/a.py"]
    (line,) = log_lines(root)
    assert line["result"] == "pass"
    assert line["file"] == "ledger_kit/a.py"
    assert line["checks"] == ["ruff check", "ruff format --check"]


def test_post_write_fails_with_findings_on_stderr(root, state_dir):
    runner = FakeRunner(ruff_answer)
    out = run("post-write", write_payload(root / "ledger_kit" / "a.py"), root, runner, state_dir)
    assert out.code == 1
    assert out.stdout == ""
    assert "F401" in out.stderr
    assert 0 < len(out.stderr.splitlines()) <= hooks.MAX_FINDING_LINES
    (line,) = log_lines(root)
    assert line["result"] == "fail"
    assert line["detail"] == "ruff: F401"


def test_post_write_markdown_is_skipped(root, state_dir):
    runner = FakeRunner()
    out = run("post-write", write_payload(root / "docs" / "x.md", "s-2"), root, runner, state_dir)
    assert out.code == 0
    assert "\n" not in out.stdout and out.stdout
    assert runner.calls == []
    assert hooks.read_state(state_dir, "s-2") == ["docs/x.md"]
    (line,) = log_lines(root)
    assert line["result"] == "skipped"
    assert line["file"] == "docs/x.md"


def test_post_write_path_outside_repo_is_logged_as_outside_repo(root, state_dir, tmp_path):
    runner = FakeRunner()
    outside = tmp_path / "elsewhere" / "x.py"
    out = run("post-write", write_payload(outside, "s-3"), root, runner, state_dir)
    assert out.code == 0
    assert runner.calls == []
    assert hooks.read_state(state_dir, "s-3") == []
    (line,) = log_lines(root)
    assert line["file"] == hooks.OUTSIDE_REPO == "outside-repo"
    assert line["result"] == "skipped"
    assert "elsewhere" not in json.dumps(line)
    assert "elsewhere" not in out.stdout


def test_post_write_without_path_is_skipped(root, state_dir):
    payload = write_payload("unused", "s-4")
    payload["tool_name"] = "other_write"
    payload["tool_input"] = {}
    runner = FakeRunner()
    out = run("post-write", payload, root, runner, state_dir)
    assert out.code == 0
    assert runner.calls == []
    (line,) = log_lines(root)
    assert line["file"] is None
    assert line["result"] == "skipped"


def test_post_write_reads_file_path_when_path_is_missing(root, state_dir):
    payload = write_payload("unused")
    payload["tool_input"] = {"file_path": str(root / "scripts" / "b.py")}
    out = run("post-write", payload, root, FakeRunner(), state_dir)
    assert out.stdout == "ruff OK on scripts/b.py"


@pytest.mark.parametrize("raw", ["not json", "", "[1, 2]"])
def test_bad_stdin_is_logged_as_error_and_exits_zero(root, state_dir, raw):
    runner = FakeRunner()
    out = run("post-write", raw, root, runner, state_dir)
    assert out.code == 0
    assert out.stdout and "\n" not in out.stdout
    assert runner.calls == []
    (line,) = log_lines(root)
    assert line["result"] == "error"
    assert line["session"] == "unknown"


def test_runner_timeout_is_an_error_and_exits_zero(root, state_dir):
    runner = FakeRunner(error=subprocess.TimeoutExpired(cmd="ruff", timeout=30))
    out = run("post-write", write_payload(root / "ledger_kit" / "a.py"), root, runner, state_dir)
    assert out.code == 0
    assert out.stdout and "\n" not in out.stdout
    (line,) = log_lines(root)
    assert line["result"] == "error"
    assert line["detail"] == "TimeoutExpired"


def test_missing_ruff_is_an_error_not_a_finding(root, state_dir):
    runner = FakeRunner(lambda argv: hooks.RunResult(1, "No module named ruff"))
    out = run("post-write", write_payload(root / "ledger_kit" / "a.py"), root, runner, state_dir)
    assert out.code == 0
    assert out.stderr == ""
    assert log_lines(root)[0]["result"] == "error"


def test_unknown_event_is_an_error_and_exits_zero(root, state_dir):
    out = run("sideways", stop_payload(), root, FakeRunner(), state_dir)
    assert out.code == 0
    assert log_lines(root)[0]["result"] == "error"


# --- stop ---------------------------------------------------------------------------------------


def test_stop_without_touched_files_skips_pytest(root, state_dir):
    runner = FakeRunner()
    out = run("stop", stop_payload("s-5"), root, runner, state_dir)
    assert out.code == 0
    assert len(runner.calls) == 1
    assert runner.calls[0][0][-3:] == ["ruff", "check", "."]
    (line,) = log_lines(root)
    assert line["event"] == "stop"
    assert line["file"] is None
    assert line["checks"] == ["ruff check ."]
    assert line["result"] == "pass"


def test_select_targets_picks_each_folder_once_in_stable_order():
    files = [
        "apps/zombie_subscriptions/a.py",
        "apps/zombie_subscriptions/detectors/b.py",
        "apps/vampire_fees/c.py",
        "ledger_kit/d.py",
        "scripts/e.py",
        "tests/f.py",
        "docs/g.md",
        "README.md",
        ".kiro/specs/x/tasks.md",
        "data/samples/h.csv",
    ]
    expected = ["apps/vampire_fees/tests", "apps/zombie_subscriptions/tests", "tests"]
    assert hooks.select_targets(files) == expected
    assert hooks.select_targets(list(reversed(files))) == expected
    assert hooks.select_targets(["docs/g.md", "README.md"]) == []


def test_stop_runs_pytest_on_the_targets_of_the_touched_files(root, state_dir):
    touched = ["apps/zombie_subscriptions/a.py", "ledger_kit/c.py", "scripts/d.py", "docs/f.md"]
    for name in touched:
        run("post-write", write_payload(root / name), root, FakeRunner(), state_dir)
    runner = FakeRunner()
    out = run("stop", stop_payload(), root, runner, state_dir)
    assert out.code == 0
    argv = runner.calls[1][0]
    assert argv[1:7] == ["-m", "pytest", "-q", "-x", "-p", "no:cacheprovider"]
    assert argv[7:] == ["apps/zombie_subscriptions/tests", "tests"]
    assert runner.calls[1][2] == hooks.PYTEST_TIMEOUT_SECONDS
    assert log_lines(root)[-1]["checks"] == ["ruff check .", "pytest"]


def test_stop_exits_zero_even_when_pytest_fails(root, state_dir):
    run("post-write", write_payload(root / "tests" / "e.py"), root, FakeRunner(), state_dir)
    out = run("stop", stop_payload(), root, FakeRunner(stop_answer), state_dir)
    assert out.code == 0
    assert "ruff check .: OK" in out.stdout
    assert "1 failed, 3 passed in 0.5s" in out.stdout
    assert "tests/test_x.py::test_y" in out.stdout
    line = log_lines(root)[-1]
    assert line["result"] == "fail"
    assert "1 failed, 3 passed" in line["detail"]


def test_stop_exits_zero_when_the_runner_times_out(root, state_dir):
    run("post-write", write_payload(root / "tests" / "e.py"), root, FakeRunner(), state_dir)
    runner = FakeRunner(error=subprocess.TimeoutExpired(cmd="x", timeout=540))
    out = run("stop", stop_payload(), root, runner, state_dir)
    assert out.code == 0
    assert log_lines(root)[-1]["result"] == "error"


def test_state_file_is_removed_after_stop_and_lives_outside_the_repo(root, state_dir):
    run("post-write", write_payload(root / "tests" / "e.py", "s/6"), root, FakeRunner(), state_dir)
    state = hooks.state_file(state_dir, "s/6")
    assert state.name == "s_6.json"
    assert state.is_file()
    assert root not in state.parents
    run("stop", stop_payload("s/6"), root, FakeRunner(), state_dir)
    assert not state.exists()


def test_safe_session_and_default_state_dir():
    assert hooks.safe_session("a/b:c d") == "a_b_c_d"
    assert hooks.safe_session("ok-1_x") == "ok-1_x"
    assert hooks.default_state_dir() == Path(tempfile.gettempdir()) / "ghost-ledger-hooks"


def test_pytest_summary_and_first_failing_test():
    assert hooks.pytest_summary(PYTEST_FAIL) == "1 failed, 3 passed in 0.5s"
    assert hooks.pytest_summary("12 passed in 1.20s\n") == "12 passed in 1.20s"
    assert hooks.pytest_summary("nothing useful") == ""
    assert hooks.first_failing_test(PYTEST_FAIL) == "tests/test_x.py::test_y"
    assert hooks.first_failing_test("12 passed in 1.20s") == ""


def test_repo_python_prefers_the_venv_and_falls_back(root):
    assert hooks.repo_python(root) == sys.executable
    sub = ("Scripts", "python.exe") if sys.platform == "win32" else ("bin", "python")
    venv = root / ".venv" / sub[0] / sub[1]
    venv.parent.mkdir(parents=True)
    venv.write_text("", encoding="utf-8")
    assert hooks.repo_python(root) == str(venv)


# --- log ----------------------------------------------------------------------------------------


def test_every_log_line_has_exactly_the_documented_keys_and_no_absolute_path(
    root, state_dir, tmp_path
):
    outside = tmp_path / "elsewhere" / "x.py"
    run("post-write", write_payload(root / "ledger_kit" / "a.py"), root, FakeRunner(), state_dir)
    py_payload = write_payload(root / "ledger_kit" / "a.py")
    run("post-write", py_payload, root, FakeRunner(ruff_answer), state_dir)
    run("post-write", write_payload(root / "docs" / "x.md"), root, FakeRunner(), state_dir)
    run("post-write", write_payload(outside), root, FakeRunner(), state_dir)
    run("post-write", "not json", root, FakeRunner(), state_dir)
    run("stop", stop_payload(), root, FakeRunner(stop_answer), state_dir)
    text = (root / hooks.LOG_RELATIVE_PATH).read_text(encoding="utf-8")
    lines = log_lines(root)
    assert len(lines) == 6
    for line in lines:
        assert list(line) == list(hooks.LOG_KEYS)
        assert line["event"] in {"post-write", "stop"}
        assert line["result"] in {"pass", "fail", "skipped", "error"}
        assert isinstance(line["checks"], list)
        assert isinstance(line["seconds"], float)
        assert len(line["detail"]) <= hooks.MAX_DETAIL_CHARS
        datetime.fromisoformat(line["time"])
        assert line["time"] == "2026-11-10T12:00:00"
    assert_no_absolute_path(text, tmp_path)


def test_scrub_removes_the_repo_root_from_findings(root, state_dir, tmp_path):
    def answer(argv):
        if "check" in argv and "format" not in argv:
            return hooks.RunResult(1, f"{root.as_posix()}/ledger_kit/a.py:1:1: F401 unused\n")
        return hooks.RunResult(0, "")

    payload = write_payload(root / "ledger_kit" / "a.py")
    out = run("post-write", payload, root, FakeRunner(answer), state_dir)
    assert out.code == 1
    assert_no_absolute_path(out.stderr, tmp_path)


def test_seconds_is_the_duration_with_one_decimal(root, state_dir):
    times = iter([NOW, NOW + timedelta(seconds=1.26)])
    out = hooks.handle("post-write", "not json", root, lambda: next(times), FakeRunner(), state_dir)
    assert out.code == 0
    assert log_lines(root)[0]["seconds"] == 1.3


def test_detail_is_cut_to_200_characters(root, state_dir):
    long_summary = "5 passed, " + "x" * 400 + " in 1.0s\n"
    runner = FakeRunner(lambda argv: hooks.RunResult(0, long_summary if "pytest" in argv else ""))
    run("post-write", write_payload(root / "tests" / "e.py"), root, FakeRunner(), state_dir)
    run("stop", stop_payload(), root, runner, state_dir)
    assert len(log_lines(root)[-1]["detail"]) <= hooks.MAX_DETAIL_CHARS


# --- configuration and imports -------------------------------------------------------------------


def test_review_gate_json_has_the_two_hooks():
    data = json.loads((REPO / ".kiro" / "hooks" / "review-gate.json").read_text(encoding="utf-8"))
    assert data["version"] == "v1"
    by_name = {h["name"]: h for h in data["hooks"]}
    assert set(by_name) == {"lint-after-write", "tests-on-stop"}
    lint = by_name["lint-after-write"]
    assert lint["trigger"] == "PostToolUse"
    assert lint["matcher"] == "write"
    assert lint["action"] == {
        "type": "command",
        "command": "python scripts/kiro_hooks.py post-write",
    }
    assert lint["timeout"] == 60
    tests = by_name["tests-on-stop"]
    assert tests["trigger"] == "Stop"
    assert "matcher" not in tests
    assert tests["action"] == {"type": "command", "command": "python scripts/kiro_hooks.py stop"}
    assert tests["timeout"] == 600


def test_the_ide_hook_files_are_still_there():
    assert len(list((REPO / ".kiro" / "hooks").glob("*.kiro.hook"))) == 3


def test_script_imports_only_the_standard_library():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    assert names
    assert names <= set(sys.stdlib_module_names)
