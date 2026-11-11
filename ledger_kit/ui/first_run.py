"""First run of a session (judge-path): decide whether an app loads its demo by itself.

Pure module: no Streamlit. Each app passes its session state (a mapping), its own prefixed
"already done" key, and whether a source is already loaded.
"""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

# Switch of the feature. The tests of the pages that exist since before judge-path turn it off in
# the root conftest.py so that they keep starting from an empty page; it is True in production.
AUTOLOAD_DEMO: bool = True


def should_autoload(state: MutableMapping[str, Any], done_key: str, has_source: bool) -> bool:
    """Return True once per session when nothing is loaded; the first call marks the session.

    A later run, a visit to another page (plain session keys survive it), an upload or a source
    that is already loaded never triggers it again.
    """
    if state.get(done_key):
        return False
    state[done_key] = True
    return AUTOLOAD_DEMO and not has_source
