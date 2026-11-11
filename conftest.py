"""Root fixtures: keep every older test on the starting point it was written for.

judge-path adds two things that change what a page shows on its first run, with no key set: the
replay of a recorded run (``ledger_kit/replay.py``) and the demo that loads by itself
(``ledger_kit/ui/first_run.py``). Both are off for every test here. The tests of the feature turn
them on with the ``judge_path`` fixture of ``tests/judge_path_fixtures.py``, which patches the
same two names.
"""

from pathlib import Path

import pytest

from ledger_kit import replay
from ledger_kit.ui import first_run

NO_RUN_FILE = Path(__file__).resolve().parent / "data" / "live_runs" / "no-replay-in-tests.json"


@pytest.fixture(autouse=True)
def _judge_path_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the replay at a file that does not exist and switch the auto-load off."""
    monkeypatch.setattr(replay, "REPLAY_RUN_PATH", NO_RUN_FILE)
    monkeypatch.setattr(first_run, "AUTOLOAD_DEMO", False)
