"""Checks .streamlit/config.toml: a theme and nothing else (showcase REQ-SC-06)."""

import re
import tomllib
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG = REPO_ROOT / ".streamlit" / "config.toml"
APP_SOURCES = (
    REPO_ROOT / "apps" / "phantom_invoices" / "flashlight.py",
    REPO_ROOT / "apps" / "phantom_invoices" / "app.py",
    # The shared look moved here in haunted-design: the palette is written in this module too.
    REPO_ROOT / "ledger_kit" / "ui" / "theme.py",
)

THEME_KEYS = {
    "base",
    "primaryColor",
    "backgroundColor",
    "secondaryBackgroundColor",
    "textColor",
}
COLOUR_KEYS = THEME_KEYS - {"base"}
HEX_COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")
SECRET_WORDS = re.compile(
    r"(api[_-]?key|token|secret|password|bearer|authorization|sk-[a-z0-9])", re.IGNORECASE
)


@pytest.fixture(scope="module")
def config() -> dict[str, Any]:
    """The parsed .streamlit/config.toml."""
    with CONFIG.open("rb") as handle:
        return tomllib.load(handle)


def test_config_parses_and_holds_only_the_theme_table(config: dict[str, Any]) -> None:
    """No [server], [browser], [global] or other table that could upset Community Cloud."""
    assert set(config) == {"theme"}
    assert isinstance(config["theme"], dict)


def test_theme_holds_only_known_flat_keys(config: dict[str, Any]) -> None:
    """Every theme key is a known one, every value a string (no nested table)."""
    theme = config["theme"]

    assert set(theme) <= THEME_KEYS
    assert {"base", "primaryColor", "backgroundColor", "textColor"} <= set(theme)
    assert all(isinstance(value, str) for value in theme.values())


def test_theme_is_dark_with_hex_colours(config: dict[str, Any]) -> None:
    """Base dark; the colours are six-digit hex codes."""
    theme = config["theme"]

    assert theme["base"] == "dark"
    for key in COLOUR_KEYS & set(theme):
        assert HEX_COLOUR.match(theme[key]), key


def test_theme_colours_come_from_the_existing_app_css(config: dict[str, Any]) -> None:
    """Background, text and accent are the colours the shared look and the phantom CSS use."""
    theme = config["theme"]
    css = "\n".join(path.read_text(encoding="utf-8") for path in APP_SOURCES).lower()

    assert theme["backgroundColor"].lower() == "#12101a"
    assert theme["primaryColor"].lower() == "#7cffb2"
    for key in COLOUR_KEYS & set(theme):
        assert theme[key].lower() in css, key


def test_config_file_has_no_secret() -> None:
    """No secret-looking word in the file; secrets stay in env vars and a git-ignored file."""
    assert SECRET_WORDS.search(CONFIG.read_text(encoding="utf-8")) is None
    assert not (REPO_ROOT / ".streamlit" / "secrets.toml").exists()
    assert ".streamlit/secrets.toml" in (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
