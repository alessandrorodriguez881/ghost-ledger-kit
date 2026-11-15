"""The Hypothesis profile loaded by the root conftest has no deadline."""

from hypothesis import given, settings
from hypothesis import strategies as st


def test_loaded_profile_has_no_deadline() -> None:
    """Timing on shared runners varies, so the loaded profile must not set a deadline."""
    assert settings().deadline is None


@settings(max_examples=5)
@given(value=st.integers())
def test_test_settings_keep_no_deadline(value: int) -> None:
    """A test that sets only max_examples still inherits the no-deadline profile."""
    assert settings.default.deadline is None
    assert isinstance(value, int)
