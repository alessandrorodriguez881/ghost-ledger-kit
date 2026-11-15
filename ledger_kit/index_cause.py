"""Finds a sentence that names the price index as the cause of the price change (REQ-GH-23).

Standard library only, no project import. The kit gives the consumer price index as context
around a price increase, never as its cause. The number guard reads figures, so it cannot see a
model turn that context into a cause; this check reads one sentence at a time.
"""

import re
import unicodedata

# The reason the explainer records on a rejected answer (`Explanation.rejected_reason`).
REASON_INDEX_AS_CAUSE: str = "price_index_as_cause"

# Words that name the price index, folded (lower case, no accents). `ipc` also covers a series id
# such as IPC290751. Whole words only.
INDEX_TERMS: tuple[str, ...] = (
    r"ipc\d*",
    r"cpi",
    r"consumer price index",
    r"price index",
    r"inflation",
    r"indice de precios",
    r"inflacion",
)
# Phrases that give a cause, folded. A space stands for any run of white space.
CAUSE_PHRASES: tuple[str, ...] = (
    "attributed",
    "attributable",
    "due to",
    "caused by",
    "because of",
    "driven by",
    "explained by",
    "a result of",
    "debido a",
    "causado por",
    "se debe a",
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
_INDEX_RE = re.compile(r"(?<!\w)(?:" + "|".join(INDEX_TERMS) + r")(?!\w)")


def _cause_pattern(phrase: str) -> str:
    """Regex of one cause phrase; a Spanish phrase ending in ` a` also reads `al`."""
    pattern = phrase.replace(" ", r"\s+")
    return pattern + "l?" if phrase.endswith(" a") else pattern


_CAUSE_RE = re.compile(
    r"(?<!\w)(?:" + "|".join(_cause_pattern(p) for p in CAUSE_PHRASES) + r")(?!\w)"
)


def _fold(text: str) -> str:
    """Lower case without accents, so `índice` and `indice` read the same."""
    decomposed = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def find_index_as_cause(text: str) -> tuple[str, ...]:
    """Return, in text order, each sentence of `text` that names the index and gives a cause."""
    found: list[str] = []
    for part in _SENTENCE_SPLIT.split(text):
        sentence = part.strip()
        folded = _fold(sentence)
        if _INDEX_RE.search(folded) and _CAUSE_RE.search(folded):
            found.append(sentence)
    return tuple(found)
