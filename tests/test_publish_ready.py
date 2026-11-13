"""Text checks of the publish-readiness files (REQ-SC-13, REQ-SC-14, REQ-SC-15).

The files are read as plain text: no YAML library is used and no workflow is run.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG = REPO_ROOT / ".streamlit" / "config.toml"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
TESTS_YML = WORKFLOWS / "tests.yml"
AWAKE_YML = WORKFLOWS / "keep-demo-awake.yml"

SECRET_WORDS = re.compile(r"secret", re.IGNORECASE)
WAKE_UP_BUTTON = "Yes, get this app back up!"


def _read(path: Path) -> str:
    """The text of a repository file."""
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def tests_yml() -> str:
    """Text of the tests workflow."""
    return _read(TESTS_YML)


@pytest.fixture(scope="module")
def awake_yml() -> str:
    """Text of the keep-demo-awake workflow."""
    return _read(AWAKE_YML)


def test_config_turns_off_usage_statistics() -> None:
    """REQ-SC-13: the [browser] table holds gatherUsageStats = false."""
    text = _read(CONFIG)

    assert re.search(r"^\[browser\]\s*$", text, re.MULTILINE)
    assert re.search(r"^gatherUsageStats\s*=\s*false\s*$", text, re.MULTILINE)


def test_tests_workflow_is_named_tests_and_runs_on_push_and_pull_request(tests_yml: str) -> None:
    """REQ-SC-14: name tests, triggers push and pull_request."""
    assert re.search(r"^name:\s*tests\s*$", tests_yml, re.MULTILINE)
    on_block = re.search(r"^on:\s*\n((?:[ \t]+.*\n|\n)+)", tests_yml, re.MULTILINE)
    assert on_block, "no on: block"
    assert re.search(r"^[ \t]+push:", on_block.group(1), re.MULTILINE)
    assert re.search(r"^[ \t]+pull_request:", on_block.group(1), re.MULTILINE)


def test_tests_workflow_uses_python_312_on_ubuntu_with_a_time_limit(tests_yml: str) -> None:
    """REQ-SC-14: ubuntu-latest, Python 3.12, pip cache, 60 minutes, the two official actions."""
    assert "runs-on: ubuntu-latest" in tests_yml
    assert "timeout-minutes: 60" in tests_yml
    assert "actions/checkout@v4" in tests_yml
    assert "actions/setup-python@v5" in tests_yml
    assert re.search(r"python-version:\s*[\"']?3\.12[\"']?\s*$", tests_yml, re.MULTILINE)
    assert re.search(r"cache:\s*pip\s*$", tests_yml, re.MULTILINE)


def test_tests_workflow_installs_requirements_and_runs_ruff_and_pytest(tests_yml: str) -> None:
    """REQ-SC-14: the commands are the ones a developer runs."""
    assert "pip install -r requirements.txt" in tests_yml
    assert re.search(r"run:\s*ruff check \.\s*$", tests_yml, re.MULTILINE)
    assert re.search(r"run:\s*ruff format --check \.\s*$", tests_yml, re.MULTILINE)
    pytest_run = re.search(r"run:\s*(python -m pytest .*)$", tests_yml, re.MULTILINE)
    assert pytest_run, "no python -m pytest step"
    command = pytest_run.group(1)
    for option in (
        "--cov=ledger_kit",
        "--cov=apps/zombie_subscriptions",
        "--cov=apps/phantom_invoices",
        "--cov=apps/vampire_fees",
        "--cov-fail-under=80",
    ):
        assert option in command, option
    assert tests_yml.index("pip install") < tests_yml.index("ruff check .")
    assert tests_yml.index("ruff check .") < tests_yml.index("ruff format --check .")
    assert tests_yml.index("ruff format --check .") < tests_yml.index("python -m pytest")


def test_tests_workflow_has_no_deploy_step(tests_yml: str) -> None:
    """REQ-SC-14: nothing is published from the workflow."""
    lowered = tests_yml.lower()
    for word in ("deploy", "publish", "twine", "docker push", "git push"):
        assert word not in lowered, word


def test_neither_workflow_mentions_secrets(tests_yml: str, awake_yml: str) -> None:
    """REQ-SC-14, REQ-SC-15: no secret, no secrets context, no token."""
    for text in (tests_yml, awake_yml):
        assert SECRET_WORDS.search(text) is None
        assert "GITHUB_TOKEN" not in text
        assert "api_key" not in text.lower()


def test_awake_workflow_has_the_schedule_and_manual_trigger(awake_yml: str) -> None:
    """REQ-SC-15: cron quoted, and workflow_dispatch."""
    assert 'cron: "17 */6 * * *"' in awake_yml
    assert re.search(r"^[ \t]+workflow_dispatch:", awake_yml, re.MULTILINE)
    assert "timeout-minutes: 10" in awake_yml


def test_awake_workflow_demo_url_is_empty_and_skips_with_a_message(awake_yml: str) -> None:
    """REQ-SC-15: an empty DEMO_URL prints No public URL yet; later steps need a URL."""
    assert re.search(r"^[ \t]+DEMO_URL:\s*(\"\"|'')\s*$", awake_yml, re.MULTILINE)
    assert "No public URL yet" in awake_yml
    assert awake_yml.index("No public URL yet") < awake_yml.index("actions/setup-python@v5")
    assert awake_yml.count("if: env.DEMO_URL != ''") >= 3


def test_awake_workflow_installs_playwright_and_presses_the_wake_up_button(awake_yml: str) -> None:
    """REQ-SC-15: pinned playwright, Chromium, Python 3.12 and the button name."""
    assert "pip install playwright==1.48.0" in awake_yml
    assert "python -m playwright install --with-deps chromium" in awake_yml
    assert re.search(r"python-version:\s*[\"']?3\.12[\"']?\s*$", awake_yml, re.MULTILINE)
    assert WAKE_UP_BUTTON in awake_yml
    assert "timeout=120000" in awake_yml
    assert "wait_for_timeout(90000)" in awake_yml
