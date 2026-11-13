"""Find numbers written in words (English and Spanish); standard library only.

`find_number_phrases` returns each number phrase of a text as written, with its offsets, its
integer value and how many number words it has. It does not decide anything: which phrases are
figures to check is the business of the number guard in `explainer.py`.

Words join only where the grammar allows it; anything else starts a new phrase. The words `and`
and `y` never start or end a phrase. Ordinals are not numbers: a phrase joined to an ordinal word
(`twenty-first`, `primero`) is skipped as a whole.
"""

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class NumberPhrase:
    """One number phrase: `text` exactly as written, `text == source[start:end]`."""

    text: str
    start: int
    end: int
    value: int
    word_count: int  # number words only: `and`/`y` are not counted, a leading `a` is


@dataclass(frozen=True)
class _Token:
    word: str  # folded (lower case, no accents); "" when the token is not made of letters only
    start: int
    end: int


_TOKEN_RE = re.compile(r"\w+")
_JOIN_RE = re.compile(r"[ \t\u00a0]+|-")  # what may stand between two words of one phrase

# --- English ---------------------------------------------------------------------------------

_EN_UNITS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
}
_EN_TEENS = {
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}
_EN_TENS = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_EN_SCALES = {"thousand": 1_000, "million": 1_000_000}
_EN_LOW = frozenset(_EN_UNITS) | frozenset(_EN_TEENS) | frozenset(_EN_TENS)
_EN_MULTIPLIERS = frozenset({"hundred", *_EN_SCALES})
_EN_WORDS = _EN_LOW | _EN_MULTIPLIERS | {"zero", "a"}
_EN_ORDINALS = frozenset(
    """first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth
    thirteenth fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth twentieth
    thirtieth fortieth fiftieth sixtieth seventieth eightieth ninetieth hundredth thousandth
    millionth""".split()
)

# --- Spanish ---------------------------------------------------------------------------------

_ES_UNITS = {
    "uno": 1,
    "un": 1,
    "una": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
}
# Ten to twenty-nine: one word each, nothing but a scale may follow.
_ES_TO_29 = {
    "diez": 10,
    "once": 11,
    "doce": 12,
    "trece": 13,
    "catorce": 14,
    "quince": 15,
    "dieciseis": 16,
    "diecisiete": 17,
    "dieciocho": 18,
    "diecinueve": 19,
    "veinte": 20,
    "veintiuno": 21,
    "veintiun": 21,
    "veintiuna": 21,
    "veintidos": 22,
    "veintitres": 23,
    "veinticuatro": 24,
    "veinticinco": 25,
    "veintiseis": 26,
    "veintisiete": 27,
    "veintiocho": 28,
    "veintinueve": 29,
}
_ES_TENS = {
    "treinta": 30,
    "cuarenta": 40,
    "cincuenta": 50,
    "sesenta": 60,
    "setenta": 70,
    "ochenta": 80,
    "noventa": 90,
}
_ES_HUNDREDS = {"cien": 100, "ciento": 100}
for _name, _value in (
    ("dosc", 200),
    ("tresc", 300),
    ("cuatroc", 400),
    ("quin", 500),
    ("seisc", 600),
    ("setec", 700),
    ("ochoc", 800),
    ("novec", 900),
):
    _ES_HUNDREDS[_name + "ientos"] = _value
    _ES_HUNDREDS[_name + "ientas"] = _value
_ES_PERCENT_WORDS = frozenset({"cien", "ciento"})  # right after "por": percent words, no number
_ES_MIL = "mil"
_ES_MILLION = 1_000_000
_ES_MILLIONS = frozenset({"millon", "millones"})
_ES_WORDS = (
    frozenset(_ES_UNITS)
    | frozenset(_ES_TO_29)
    | frozenset(_ES_TENS)
    | frozenset(_ES_HUNDREDS)
    | _ES_MILLIONS
    | {"cero", _ES_MIL}
)
_ES_ORDINAL_STEMS = (
    "segund cuart quint sext septim octav noven decim undecim duodecim vigesim trigesim "
    "cuadragesim quincuagesim sexagesim septuagesim octogesim nonagesim centesim milesim"
).split()
_ES_ORDINALS = frozenset(
    {"primer", "primero", "primera", "tercer", "tercero", "tercera"}
    | {stem + end for stem in _ES_ORDINAL_STEMS for end in ("o", "a")}
)

_ORDINALS = _EN_ORDINALS | _ES_ORDINALS
_CONNECTORS = frozenset({"and", "y"})

# Parser states. Open states take the next lower-order word of a group.
_OPEN, _UNIT, _ONES, _TEEN, _TEN, _HUND, _SCALE, _AND, _Y = range(9)
_OPEN_STATES = frozenset({_OPEN, _HUND, _SCALE, _AND})
_BIG = 10**9  # larger than any scale: the first scale of a phrase is always below it

_Parsed = tuple[int, int, int]  # (index after the last word, value, word count)


def _fold(word: str) -> str:
    """Lower-case a word and drop its accents (dieciséis -> dieciseis)."""
    decomposed = unicodedata.normalize("NFD", word.lower())
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def _parse_english(toks: list[_Token], link: list[bool], i: int) -> _Parsed | None:
    """Read an English phrase that starts at token `i`; None when no phrase starts there."""
    n = len(toks)
    word = toks[i].word
    if word == "zero":
        return i + 1, 0, 1
    total = group = words = 0
    state, limit, j, last = _OPEN, _BIG, i, i
    if word == "a":  # "a hundred": a leading a before hundred, thousand or million is one
        if not (i + 1 < n and link[i] and toks[i + 1].word in _EN_MULTIPLIERS):
            return None
        group, state, words, j, last = 1, _UNIT, 1, i + 1, i + 1
    while j < n:
        if j > i and not link[j - 1]:
            break
        w = toks[j].word
        if w in _EN_UNITS and (state in _OPEN_STATES or state == _TEN):
            state = _UNIT if group == 0 else _ONES
            group += _EN_UNITS[w]
        elif w in _EN_TEENS and state in _OPEN_STATES:
            state = _TEEN if group == 0 else _ONES
            group += _EN_TEENS[w]
        elif w in _EN_TENS and state in _OPEN_STATES:
            state = _TEN
            group += _EN_TENS[w]
        elif w == "hundred" and state in (_UNIT, _TEEN):
            group *= 100
            state = _HUND
        elif (
            w in _EN_SCALES
            and state in (_UNIT, _ONES, _TEEN, _TEN, _HUND)
            and _EN_SCALES[w] < limit
        ):
            total += group * _EN_SCALES[w]
            group, state, limit = 0, _SCALE, _EN_SCALES[w]
        elif (
            w == "and"
            and state in (_HUND, _SCALE)
            and j + 1 < n
            and link[j]
            and toks[j + 1].word in _EN_LOW
        ):
            state = _AND  # joins only right after hundred, thousand or million
            j += 1
            continue
        else:
            break
        words += 1
        j += 1
        last = j
    return (last, total + group, words) if words else None


def _parse_spanish(toks: list[_Token], link: list[bool], i: int) -> _Parsed | None:
    """Read a Spanish phrase that starts at token `i`; None when no phrase starts there."""
    n = len(toks)
    if toks[i].word == "cero":
        return i + 1, 0, 1
    total = group = words = 0
    state, limit, j, last = _OPEN, _BIG, i, i
    while j < n:
        if j > i and not link[j - 1]:
            break
        w = toks[j].word
        if w in _ES_UNITS and state in (_OPEN, _HUND, _SCALE, _Y):
            state = _ONES
            group += _ES_UNITS[w]
        elif w in _ES_TO_29 and state in (_OPEN, _HUND, _SCALE):
            state = _ONES
            group += _ES_TO_29[w]
        elif w in _ES_TENS and state in (_OPEN, _HUND, _SCALE):
            state = _TEN
            group += _ES_TENS[w]
        elif w in _ES_HUNDREDS and state in (_OPEN, _SCALE):
            state = _HUND
            group += _ES_HUNDREDS[w]
        elif w == _ES_MIL and state in (_OPEN, _SCALE, _ONES, _TEN, _HUND) and 1_000 < limit:
            total += max(group, 1) * 1_000  # "mil" alone is 1000
            group, state, limit = 0, _SCALE, 1_000
        elif (
            w in _ES_MILLIONS
            and state in (_ONES, _TEN, _HUND)
            and group > 0
            and _ES_MILLION < limit
        ):
            total += group * _ES_MILLION
            group, state, limit = 0, _SCALE, _ES_MILLION
        elif w == "y" and state == _TEN and j + 1 < n and link[j] and toks[j + 1].word in _ES_UNITS:
            state = _Y  # y joins only a ten and a unit
            j += 1
            continue
        else:
            break
        words += 1
        j += 1
        last = j
    return (last, total + group, words) if words else None


def _tokens(text: str) -> tuple[list[_Token], list[bool]]:
    """Split `text` into words and say which neighbours are joined by a space or a hyphen."""
    toks = [
        _Token(_fold(m.group()) if m.group().isalpha() else "", m.start(), m.end())
        for m in _TOKEN_RE.finditer(text)
    ]
    link = [
        _JOIN_RE.fullmatch(text, toks[k].end, toks[k + 1].start) is not None
        for k in range(len(toks) - 1)
    ]
    return toks, link


def _touches_ordinal(toks: list[_Token], link: list[bool], first: int, after: int) -> bool:
    """True when an ordinal word is joined to the phrase of tokens [first, after)."""
    if first > 0 and link[first - 1] and toks[first - 1].word in _ORDINALS:
        return True
    if after < len(toks) and link[after - 1]:
        word = toks[after].word
        if word in _ORDINALS:
            return True
        return (
            word in _CONNECTORS
            and after + 1 < len(toks)
            and link[after]
            and toks[after + 1].word in _ORDINALS
        )
    return False


def find_number_phrases(text: str) -> list[NumberPhrase]:
    """Return the English and Spanish number phrases of `text`, in text order."""
    toks, link = _tokens(text)
    phrases: list[NumberPhrase] = []
    i = 0
    while i < len(toks):
        word = toks[i].word
        parsed = None
        if word in _EN_WORDS:
            parsed = _parse_english(toks, link, i)
        elif word in _ES_PERCENT_WORDS and i > 0 and link[i - 1] and toks[i - 1].word == "por":
            parsed = None  # "por ciento" / "por cien" are percent words, not a number
        elif word in _ES_WORDS:
            parsed = _parse_spanish(toks, link, i)
        if parsed is None:
            i += 1
            continue
        after, value, words = parsed
        if not _touches_ordinal(toks, link, i, after):
            start, end = toks[i].start, toks[after - 1].end
            phrases.append(NumberPhrase(text[start:end], start, end, value, words))
        i = after
    return phrases
