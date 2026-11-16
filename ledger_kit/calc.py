"""The model asks, the kit computes: `[[calc: EXPRESSION]]` placeholders evaluated from an alert.

A model never does arithmetic. When a question needs a total, a sum, a difference or a share it
writes a placeholder; this module finds each one, checks it against a whitelist and computes it in
`Decimal` from the numeric fields of the alert. Nothing else can get in: a name must be a numeric
field of the alert, a constant must be a whole number of the question (digits, or English or
Spanish words), and the only operations are + - * / and a minus sign. Anything else rejects the
whole answer. Pure: no model call, no Streamlit, no I/O; the explainer decides what to do with the
outcome. `resolve_calculations` never raises.

Session 28b (A-MC-02, A-MC-03): a number written with a decimal point that equals the value of
exactly one numeric field is read as that field; and a sum may not add a field to the fields it is
made of.

Session 28c (A-MC-04, A-MC-05): on a card with no question a placeholder holds one field or one
figure equal to one field and no operator; and in one placeholder each field is used once, a figure
read as a field counting as that field.
"""

import ast
import itertools
import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Any

from ledger_kit.number_words import find_number_phrases
from ledger_kit.utils.money import (
    apply_sign,
    combine,
    format_amount,
    round_to_cents,
    sum_amounts,
)

# The reason the explainer records on an answer whose placeholder is not allowed
# (`Explanation.rejected_reason`); the offending parts are the rejected tokens.
REASON_CALC_NOT_ALLOWED: str = "calc_not_allowed"

# An expression longer than this is not read: three or four operands fit in far less, and it keeps
# the parser away from absurd input.
CALC_EXPRESSION_MAX_CHARS: int = 200
# Digits kept in every intermediate step; the result is rounded to cents at the end only.
CALC_PRECISION: int = 40
# A question integer longer than this is not a whole number worth reading (keeps `int()` small).
QUESTION_INTEGER_MAX_DIGITS: int = 9
# Double counting (A-MC-03): a field added to at least this many other fields whose values sum to
# it, all added in the same sum, is rejected. A part of value zero is no part.
DOUBLE_COUNT_MIN_PARTS: int = 2
# One placeholder uses each field at most this many times (A-MC-05): a field minus itself or the
# same field three times is no calculation.
FIELD_MAX_USES: int = 1
# What the number guard reads in place of a valid placeholder: letters only, so it is no figure.
GUARD_MARKER: str = "COMPUTED"
# Written right after a computed figure in the text shown to the user.
COMPUTED_MARK: str = "†"
# Currency of a computed amount when the alert data names none.
DEFAULT_CURRENCY: str = "EUR"
# A numeric field is shown as money when the fallback template formats it `:money`, or when a word
# of its name says it is an amount and no word says it is a count, a percentage or an index.
MONEY_NAME_PARTS: frozenset[str] = frozenset(
    {"cost", "amount", "total", "charged", "price", "fee", "fees"}
)
NOT_MONEY_NAME_PARTS: frozenset[str] = frozenset(
    {"percent", "pct", "count", "index", "series", "times", "number", "days", "months"}
)

_PLACEHOLDER_RE = re.compile(r"\[\[\s*calc\s*:(?P<expression>[^\[\]]*)\]\]", re.IGNORECASE)
_OPENING_RE = re.compile(r"\[\[\s*calc", re.IGNORECASE)
_PLAIN_NUMBER_RE = re.compile(r"-?[0-9]+(?:\.[0-9]+)?")
# A figure copied from the alert is written with a decimal point (`107.88`, `484.00`); a plain
# whole number is a count and has to come from the question (A-MC-02).
_DECIMAL_LITERAL_RE = re.compile(r"[0-9]+\.[0-9]+")
# A whole number of the question: not part of a decimal, a date or a longer number.
_QUESTION_INTEGER_RE = re.compile(
    r"(?<![0-9.,/-])[0-9]{1,"
    + str(QUESTION_INTEGER_MAX_DIGITS)
    + r"}(?![0-9]|[.,][0-9]|[/-][0-9])"
)
_CURRENCY_RE = re.compile(r"[A-Z]{3}")
_SYMBOLS = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/"}
_SHOWN_SYMBOLS = {"+": "+", "-": "-", "*": "x", "/": "/"}


@dataclass(frozen=True)
class Operand:
    """One field of the alert used by a calculation: its name, value and how it is shown."""

    name: str
    value: Decimal
    shown: str


@dataclass(frozen=True)
class Computation:
    """One calculation the kit made: what was asked, from which fields, and the result."""

    expression: str  # as the model wrote it, trimmed
    operands: tuple[Operand, ...]  # the fields used, in order of first use
    result: Decimal  # rounded half-up to two places
    shown: str  # the result as written in the text, without the mark
    formula: str  # e.g. "yearly_cost 107,88 EUR x 5 = 539,40 EUR"

    @property
    def line(self) -> str:
        """The one line of small text shown under the answer."""
        return f"{COMPUTED_MARK} computed by the kit: {self.formula}, from the alert fields."


@dataclass(frozen=True)
class CalcOutcome:
    """What the placeholders of one answer came to.

    `rejected` is empty when every placeholder is allowed; then `guard_text` is the answer with
    each placeholder replaced by GUARD_MARKER (what the number guard reads) and `text` the answer
    with each placeholder replaced by its marked result. When something is rejected both texts are
    the answer as received.
    """

    guard_text: str
    text: str
    computed: tuple[Computation, ...]
    rejected: tuple[str, ...]
    # One sentence per rejected part, in the same order: why the kit will not compute it.
    reasons: tuple[str, ...] = ()


class _Reject(Exception):
    """Internal: the part of an expression that is not allowed, and why in words."""

    def __init__(self, part: str, why: str = "") -> None:
        super().__init__(part)
        self.part = part
        self.why = why or f"{part} is not allowed"


# The reasons, in plain words (judge-path 30a). None holds `*` or `$`: they are shown in markdown.
WHY_NUMBER_NOT_IN_QUESTION: str = (
    "{part} is neither a field of the alert nor a number in the question"
)
WHY_UNKNOWN_FIELD: str = "{part} is not a numeric field of the alert"
WHY_FIGURE_NOT_A_FIELD: str = (
    "{part} is not a field of the alert, a whole number of the question or the value of one "
    "numeric field of the alert"
)
WHY_FIGURE_TWO_FIELDS: str = (
    "{part} is the value of more than one field of the alert, so it cannot be read as one field"
)
WHY_FIELD_REUSED: str = "{name} is used more than once"
WHY_FIELD_REUSED_AS_FIGURE: str = " ({figure} is its value, read as that field)"
WHY_OWN_PARTS: str = "a total is added to its own parts ({formula})"
WHY_OPERATION: str = (
    "{part} is not allowed: only fields of the alert, whole numbers of the question and the "
    "four operations (add, subtract, multiply, divide) are"
)
WHY_DIVISION_BY_ZERO: str = "{part} divides by zero"
WHY_NO_QUESTION: str = (
    "{part} is arithmetic, and a card with no question allows only one field of the alert"
)
WHY_UNREADABLE: str = "{part} is empty, too long or not an expression the kit can read"
WHY_UNDEFINED: str = "{part} cannot be computed (overflow or an undefined operation)"
WHY_UNCLOSED: str = "a calculation placeholder is not closed or not well formed"


@dataclass(frozen=True)
class _Value:
    value: Decimal
    money: bool
    text: str  # the formula of this subtree
    compound: bool = False  # a binary operation: gets parentheses inside another one


def numeric_fields(data: Mapping[str, Any]) -> dict[str, Decimal]:
    """The fields of `data` a calculation may name: Decimal or int values, or plain number text."""
    fields: dict[str, Decimal] = {}
    for name, value in data.items():
        if not isinstance(name, str) or isinstance(value, bool):
            continue
        number: Decimal | None = None
        if isinstance(value, Decimal):
            number = value
        elif isinstance(value, int):
            number = Decimal(value)
        elif isinstance(value, str) and _PLAIN_NUMBER_RE.fullmatch(value.strip()):
            number = Decimal(value.strip())
        if number is not None and number.is_finite():
            fields[name] = number
    return fields


def question_integers(question: str | None) -> frozenset[int]:
    """The whole numbers a question contains, in digits or in English or Spanish words."""
    if not question:
        return frozenset()
    found = {int(m.group(0)) for m in _QUESTION_INTEGER_RE.finditer(question)}
    found.update(phrase.value for phrase in find_number_phrases(question))
    return frozenset(found)


def _is_money(name: str, money_fields: frozenset[str]) -> bool:
    """True when the field is an amount: formatted `:money` in the template, or named like one."""
    if name in money_fields:
        return True
    parts = set(name.lower().split("_"))
    return bool(parts & MONEY_NAME_PARTS) and not parts & NOT_MONEY_NAME_PARTS


def _currency(data: Mapping[str, Any]) -> str:
    """The currency code of the alert data when it names one, else the default."""
    value = data.get("currency")
    if isinstance(value, str) and _CURRENCY_RE.fullmatch(value):
        return value
    return DEFAULT_CURRENCY


def _plain(value: Decimal) -> str:
    """A number that is not an amount, with a decimal comma: `5`, `0,25`."""
    if value == 0:
        return "0"
    return format(value.normalize(), "f").replace(".", ",")


class _Evaluator:
    """Walks one parsed expression; only whitelisted nodes are read, everything else is rejected."""

    def __init__(
        self,
        source: str,
        fields: Mapping[str, Decimal],
        constants: frozenset[int],
        money_fields: frozenset[str],
        currency: str,
    ) -> None:
        self._source = source
        self._fields = fields
        self._constants = constants
        self._money_fields = money_fields
        self._currency = currency
        self.operands: dict[str, Operand] = {}
        # How many times each field is used in the expression (a figure read as a field counts).
        self.uses: dict[str, int] = {}
        # The figure (as written) that was read as a field, by field name (for the reason words).
        self.figures: dict[str, str] = {}
        # The field each leaf of the tree was read as (a name, or a figure equal to one field).
        self._leaf_fields: dict[ast.AST, str] = {}

    def _part(self, node: ast.AST) -> str:
        """The source text of a node (its type name when it cannot be cut out)."""
        return ast.get_source_segment(self._source, node) or type(node).__name__

    def show_result(self, value: _Value) -> str:
        """The result as written in the text: rounded to cents, an amount with its currency."""
        rounded = round_to_cents(value.value)
        if value.money:
            return format_amount(rounded, self._currency)
        return _plain(rounded)

    def visit(self, node: ast.AST) -> _Value:
        """Evaluate one node of the whitelist; raise _Reject with the offending part."""
        if isinstance(node, ast.BinOp):
            return self._binary(node)
        if isinstance(node, ast.UnaryOp):
            if not isinstance(node.op, ast.USub):
                raise self._not_allowed(node)
            inner = self.visit(node.operand)
            text = f"({inner.text})" if inner.compound else inner.text
            return _Value(apply_sign(inner.value, True), inner.money, "-" + text)
        if isinstance(node, ast.Name):
            return self._field(node)
        if isinstance(node, ast.Constant):
            return self._constant(node)
        raise self._not_allowed(node)

    def _not_allowed(self, node: ast.AST) -> _Reject:
        """The rejection of a node that is not on the whitelist (an operator, a call...)."""
        part = self._part(node)
        return _Reject(part, WHY_OPERATION.format(part=part))

    def _constant(self, node: ast.Constant) -> _Value:
        """A whole number of the question, or a decimal figure that is one numeric field."""
        if type(node.value) is int:
            if node.value not in self._constants:
                raise _Reject(str(node.value), WHY_NUMBER_NOT_IN_QUESTION.format(part=node.value))
            return _Value(Decimal(node.value), False, str(node.value))
        text = self._part(node)
        if type(node.value) is float and _DECIMAL_LITERAL_RE.fullmatch(text):
            literal = Decimal(text)
            names = [name for name, value in self._fields.items() if value == literal]
            if len(names) == 1:
                self.figures.setdefault(names[0], text)
                return self._use_field(names[0], node)
            if names:  # two fields with the same value: ambiguous, rejected
                raise _Reject(text, WHY_FIGURE_TWO_FIELDS.format(part=text))
        raise _Reject(text, WHY_FIGURE_NOT_A_FIELD.format(part=text))

    def _field(self, node: ast.Name) -> _Value:
        """A numeric field of the alert."""
        if node.id not in self._fields:
            raise _Reject(node.id, WHY_UNKNOWN_FIELD.format(part=node.id))
        return self._use_field(node.id, node)

    def _use_field(self, name: str, node: ast.AST) -> _Value:
        """Use the field `name` at `node` (a name, or a figure read as that field)."""
        value = self._fields[name]
        money = _is_money(name, self._money_fields)
        shown = format_amount(value, self._currency) if money else _plain(value)
        self.operands.setdefault(name, Operand(name, value, shown))
        self._leaf_fields[node] = name
        self.uses[name] = self.uses.get(name, 0) + 1
        return _Value(value, money, f"{name} {shown}")

    def reuse_rejection(self) -> tuple[str, str] | None:
        """The first field used more than once as (token, reason in words), else None."""
        for name, count in self.uses.items():
            if count > FIELD_MAX_USES:
                why = WHY_FIELD_REUSED.format(name=name)
                if name in self.figures:
                    why += WHY_FIELD_REUSED_AS_FIGURE.format(figure=self.figures[name])
                return f"{name} used more than once", why
        return None

    def reused_field(self) -> str | None:
        """The first field used more than once, as `name used more than once`, else None."""
        found = self.reuse_rejection()
        return None if found is None else found[0]

    def double_count(self, tree: ast.AST) -> str | None:
        """The first sum that adds a field to fields it is made of, as `total = a + b`, else None.

        It looks at each sum (a chain of `+`, parentheses included) for a field leaf whose value
        equals the sum of DOUBLE_COUNT_MIN_PARTS or more other field leaves of the same sum. It
        catches this one pattern, not every reasoning error.
        """
        for node in ast.walk(tree):
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
                found = self._double_count_in(self._sum_leaves(node))
                if found is not None:
                    return found
        return None

    def _sum_leaves(self, node: ast.AST) -> list[ast.AST]:
        """The terms of a chain of `+`, in order."""
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return self._sum_leaves(node.left) + self._sum_leaves(node.right)
        return [node]

    def _double_count_in(self, leaves: list[ast.AST]) -> str | None:
        """Look for a field of one sum that equals the sum of other fields of the same sum."""
        named: dict[str, Decimal] = {}
        for leaf in leaves:
            name = self._leaf_fields.get(leaf)
            if name is not None:
                named.setdefault(name, self._fields[name])
        for total, value in named.items():
            parts = [(name, part) for name, part in named.items() if name != total and part != 0]
            for size in range(DOUBLE_COUNT_MIN_PARTS, len(parts) + 1):
                for combo in itertools.combinations(parts, size):
                    if sum_amounts(part for _name, part in combo) == value:
                        return f"{total} = " + " + ".join(name for name, _part in combo)
        return None

    def _binary(self, node: ast.BinOp) -> _Value:
        """One of + - * /; any other operator (a power, a modulo, a shift) is rejected."""
        symbol = _SYMBOLS.get(type(node.op))
        if symbol is None:
            raise self._not_allowed(node)
        left, right = self.visit(node.left), self.visit(node.right)
        if symbol == "/" and right.value == 0:
            part = self._part(node)
            raise _Reject(part, WHY_DIVISION_BY_ZERO.format(part=part))
        value = combine(symbol, left.value, right.value)
        if symbol in "+-":
            money = left.money or right.money
        elif symbol == "*":
            money = left.money != right.money  # an amount times a count; two amounts are no amount
        else:
            money = left.money and not right.money  # an amount over a count; a share is no amount
        lhs = f"({left.text})" if left.compound else left.text
        rhs = f"({right.text})" if right.compound else right.text
        return _Value(value, money, f"{lhs} {_SHOWN_SYMBOLS[symbol]} {rhs}", compound=True)


def _compute(
    expression: str,
    fields: Mapping[str, Decimal],
    constants: frozenset[int],
    money_fields: frozenset[str],
    currency: str,
    arithmetic: bool = True,
) -> Computation:
    """Parse and evaluate one expression; raise _Reject with the offending part.

    `arithmetic` is False on a card with no question: only one field, or one figure equal to one
    field, is accepted (A-MC-04).
    """
    source = expression.strip()
    if not source or len(source) > CALC_EXPRESSION_MAX_CHARS:
        part = source[:CALC_EXPRESSION_MAX_CHARS] or "(empty)"
        raise _Reject(part, WHY_UNREADABLE.format(part=part))
    try:
        tree = ast.parse(source, mode="eval")
    except (SyntaxError, ValueError, RecursionError, MemoryError) as exc:
        raise _Reject(source, WHY_UNREADABLE.format(part=source)) from exc
    evaluator = _Evaluator(source, fields, constants, money_fields, currency)
    try:
        with localcontext() as context:
            context.prec = CALC_PRECISION
            value = evaluator.visit(tree.body)
            double = evaluator.double_count(tree.body)
            if double is not None:
                raise _Reject(double, WHY_OWN_PARTS.format(formula=double))
            if not arithmetic and not isinstance(tree.body, ast.Name | ast.Constant):
                raise _Reject(source, WHY_NO_QUESTION.format(part=source))
            reused = evaluator.reuse_rejection()
            if reused is not None:
                raise _Reject(*reused)
            result = round_to_cents(value.value)
            shown = evaluator.show_result(value)
    except ArithmeticError as exc:  # overflow, an undefined operation: nothing is computed
        raise _Reject(source, WHY_UNDEFINED.format(part=source)) from exc
    formula = f"{value.text} = {shown}"
    return Computation(source, tuple(evaluator.operands.values()), result, shown, formula)


def resolve_calculations(
    answer: str,
    data: Mapping[str, Any],
    *,
    question: str | None = None,
    money_fields: frozenset[str] = frozenset(),
) -> CalcOutcome:
    """Find and compute every `[[calc: EXPRESSION]]` of `answer`; never raises.

    `data` is `Alert.data`; `question` is the user's question (the source of the constants);
    `money_fields` are the fields the fallback template formats as amounts. An answer with no
    placeholder comes back unchanged.
    """
    matches = list(_PLACEHOLDER_RE.finditer(answer))
    stray = _OPENING_RE.search(_PLACEHOLDER_RE.sub(" ", answer))
    if not matches and stray is None:
        return CalcOutcome(answer, answer, (), ())
    fields = numeric_fields(data)
    constants = question_integers(question)
    currency = _currency(data)
    computed: list[Computation] = []
    rejected: list[str] = []
    reasons: list[str] = []
    for match in matches:
        try:
            computed.append(
                _compute(
                    match.group("expression"),
                    fields,
                    constants,
                    money_fields,
                    currency,
                    arithmetic=bool(question),
                )
            )
        except _Reject as reject:
            if reject.part not in rejected:
                rejected.append(reject.part)
                reasons.append(reject.why)
    if stray is not None and stray.group(0) not in rejected:
        rejected.append(stray.group(0))  # a placeholder that is not closed or not well formed
        reasons.append(WHY_UNCLOSED)
    if rejected:
        return CalcOutcome(answer, answer, (), tuple(rejected), tuple(reasons))
    guard_text, text, position = [], [], 0
    for match, computation in zip(matches, computed, strict=True):
        between = answer[position : match.start()]
        guard_text.extend((between, GUARD_MARKER))
        text.extend((between, computation.shown + COMPUTED_MARK))
        position = match.end()
    tail = answer[position:]
    guard_text.append(tail)
    text.append(tail)
    return CalcOutcome("".join(guard_text), "".join(text), tuple(computed), ())
