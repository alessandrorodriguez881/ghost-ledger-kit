"""Checks of docs/live-guard.md, the How it works paragraph and .env.example (live-guard LG7)."""

import re
from pathlib import Path

import pytest

import ledger_kit.live_guard as live_guard
from ledger_kit.explainer import LLM_TIMEOUT_ENV

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC = REPO_ROOT / "docs" / "live-guard.md"
README = REPO_ROOT / "README.md"
HOW_IT_WORKS = REPO_ROOT / "docs" / "how-it-works.md"
MOVED_DOCS = tuple(
    REPO_ROOT / "docs" / name
    for name in ("how-it-works.md", "real-formats.md", "public-data.md", "developing.md")
)
ENV_EXAMPLE = REPO_ROOT / ".env.example"

SECTIONS = (
    "What this shows",
    "Option A: a hosted model",
    "Option B: a local model with Ollama",
    "What to expect",
    "Limits",
)
OLLAMA_COMMANDS = (
    "winget install Ollama.Ollama",
    "ollama pull llama3.2:1b",
    'ollama run llama3.2:1b "Say ready."',
    r".\.venv\Scripts\Activate.ps1",
    '$env:OPENAI_BASE_URL = "http://localhost:11434/v1"',
    '$env:OPENAI_API_KEY = "ollama"',
    '$env:LEDGER_KIT_LLM_MODEL = "llama3.2:1b"',
    "streamlit run streamlit_app.py",
)
BASH_COMMANDS = (
    'export OPENAI_BASE_URL="http://localhost:11434/v1"',
    'export OPENAI_API_KEY="ollama"',
    'export LEDGER_KIT_LLM_MODEL="llama3.2:1b"',
)
REQUIRED_PHRASES = (
    "small local models",
    "does not judge wording",
    "10 seconds",
    "warm",
    "figures, dates and IBAN-shaped tokens",
    "3 months",
    "any non-empty key",
)
ENV_NAME = re.compile(r"\b(?:OPENAI|LEDGER_KIT)_[A-Z_]+\b")
KEY_LIKE = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}")
KEY_ASSIGNMENT = re.compile(r"OPENAI_API_KEY\s*[=:]\s*\"?([^\s\"']+)")
PLACEHOLDER_KEYS = {"ollama", "your-api-key-here", "your-key"}


@pytest.fixture(scope="module")
def doc() -> str:
    """The text of docs/live-guard.md."""
    return DOC.read_text(encoding="utf-8")


def test_doc_has_the_five_sections_in_order(doc: str) -> None:
    headings = re.findall(r"^## (.+?)\s*$", doc, re.MULTILINE)
    assert tuple(headings) == SECTIONS


@pytest.mark.parametrize("command", [*OLLAMA_COMMANDS, *BASH_COMMANDS])
def test_doc_contains_every_command_line_verbatim(doc: str, command: str) -> None:
    assert command in doc.splitlines()


def test_ollama_commands_come_in_the_documented_order(doc: str) -> None:
    lines = doc.splitlines()
    position = -1
    for command in OLLAMA_COMMANDS:
        position = lines.index(command, position + 1)


@pytest.mark.parametrize("phrase", REQUIRED_PHRASES)
def test_doc_states_the_honest_limits(doc: str, phrase: str) -> None:
    assert phrase in doc


def test_readme_paragraph_states_the_same_limits_and_links_the_doc() -> None:
    assert "`docs/live-guard.md`" in README.read_text(encoding="utf-8")
    text = HOW_IT_WORKS.read_text(encoding="utf-8")
    assert "`docs/live-guard.md`" in text
    assert "Provoke the LLM" in text
    for phrase in ("small local models", "does not judge wording", "10 seconds", "warm"):
        assert phrase in text


def test_doc_claims_no_rejection_rate(doc: str) -> None:
    assert "results vary by model" in doc
    assert not re.search(r"\d+\s?%", doc)


def test_env_var_names_in_the_doc_are_the_names_the_code_reads(doc: str) -> None:
    source = Path(live_guard.__file__).read_text(encoding="utf-8")
    read_by_code = set(re.findall(r'"((?:OPENAI|LEDGER_KIT)_[A-Z_]+)"', source))
    read_by_code.add(LLM_TIMEOUT_ENV)

    assert set(ENV_NAME.findall(doc)) == read_by_code
    assert read_by_code == {
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "LEDGER_KIT_LLM_MODEL",
        "LEDGER_KIT_LLM_TIMEOUT",
    }


@pytest.mark.parametrize("path", [DOC, README, *MOVED_DOCS, ENV_EXAMPLE], ids=lambda p: p.name)
def test_no_real_looking_key_anywhere(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert not KEY_LIKE.search(text)
    assert {m.group(1) for m in KEY_ASSIGNMENT.finditer(text)} <= PLACEHOLDER_KEYS


def test_env_example_keeps_its_line_and_adds_commented_ones() -> None:
    lines = ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
    assert "OPENAI_API_KEY=your-api-key-here" in lines
    assert "# OPENAI_BASE_URL=http://localhost:11434/v1" in lines
    assert "# LEDGER_KIT_LLM_MODEL=llama3.2:1b" in lines
    assert "# LEDGER_KIT_LLM_TIMEOUT=10" in lines
    assert not [line for line in lines if line.startswith(("OPENAI_BASE_URL", "LEDGER_KIT"))]
