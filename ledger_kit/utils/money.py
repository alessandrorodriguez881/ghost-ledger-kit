"""Money helpers: the single point of truth for monetary arithmetic and formatting."""

from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# One decimal for every percentage shown or stored by the alerts (REQ-CPI-08, DN-CPI-05).
PERCENT_DECIMALS: int = 1
_PERCENT_QUANTUM: Decimal = Decimal(1).scaleb(-PERCENT_DECIMALS)  # Decimal("0.1")


def round_to_cents(amount: Decimal) -> Decimal:
    """Round to two decimal places using ROUND_HALF_UP (Finance Rule 3)."""
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _european_number(value: Decimal, places: int) -> str:
    """Return the signed European digit string of an already rounded `value` with `places`."""
    sign = "-" if value < 0 else ""
    integer_part, _, frac_part = f"{abs(value):.{places}f}".partition(".")
    grouped = _group_thousands(integer_part)
    return f"{sign}{grouped},{frac_part}" if places else f"{sign}{grouped}"


def _european_digits(amount: Decimal) -> str:
    """Return the signed European digit string for `amount`, e.g. '-1.234,56'."""
    return _european_number(round_to_cents(amount), 2)


def format_amount(amount: Decimal, currency: str = "EUR") -> str:
    """Format to European locale string, e.g. '1.234,56 EUR' (Finance Rule 4)."""
    return f"{_european_digits(amount)} {currency}"


def format_as_european(amount: Decimal) -> str:
    """Format a Decimal as a bare European amount string without currency code."""
    return _european_digits(amount)


def _group_thousands(integer_str: str) -> str:
    """Insert European thousands separator (full stop) every three digits."""
    s = integer_str[::-1]
    chunks = [s[i : i + 3] for i in range(0, len(s), 3)]
    return ".".join(chunks)[::-1]


def percent_of(base: Decimal, rate: Decimal) -> Decimal:
    """Return base x rate / 100 rounded half-up to cents; `rate` 21 means 21 %."""
    return round_to_cents(base * rate / Decimal(100))


def percent_change(old: Decimal, new: Decimal) -> Decimal:
    """Return (new - old) / old x 100 at full Decimal precision; ValueError when old <= 0."""
    if old <= 0:
        raise ValueError(f"percent_change needs a positive old value, got {old}")
    return (new - old) / old * Decimal(100)


def round_percent(value: Decimal) -> Decimal:
    """Round a percentage to PERCENT_DECIMALS (one) decimal, ROUND_HALF_UP (the one rule)."""
    return value.quantize(_PERCENT_QUANTUM, rounding=ROUND_HALF_UP)


def format_percent(value: Decimal) -> str:
    """Format a percentage the European way after round_percent, e.g. '1.234,5 %'."""
    return f"{_european_number(round_percent(value), PERCENT_DECIMALS)} %"


def format_index(value: Decimal) -> str:
    """Show an index value with its three decimals and a decimal comma, e.g. '104,978'."""
    return _european_number(value, 3)


def scale_to(value: Decimal, maximum: Decimal, size: int) -> int:
    """Return value / maximum x size as a whole number, rounded half-up (a drawing length).

    It is for the height of a bar, never shown as a figure. Zero when `maximum` is not positive
    or `value` is negative; never more than `size`.
    """
    if maximum <= 0 or value <= 0:
        return 0
    scaled = (value / maximum * size).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return min(int(scaled), size)


def within_tolerance(a: Decimal, b: Decimal, tol: Decimal) -> bool:
    """Return True when abs(a - b) <= tol (inclusive); raise ValueError for negative tol."""
    if tol < 0:
        raise ValueError("tol must be >= 0")
    return abs(a - b) <= tol


def net_total(additions: Iterable[Decimal], subtractions: Iterable[Decimal] = ()) -> Decimal:
    """Return sum(additions) - sum(subtractions), unrounded."""
    return sum(additions, Decimal(0)) - sum(subtractions, Decimal(0))


def sum_amounts(values: Iterable[Decimal]) -> Decimal:
    """Return the exact sum of `values`, unrounded; Decimal('0') when there are none."""
    return sum(values, Decimal(0))


def balance_after(opening: Decimal, credits: Decimal, debits: Decimal) -> Decimal:
    """Return opening + credits - debits, unrounded; `opening` already carries its sign."""
    return opening + credits - debits


def combine(operator: str, left: Decimal, right: Decimal) -> Decimal:
    """Return `left operator right` for one of + - * /, unrounded (the calc module's one step).

    Raises ValueError for any other operator and ZeroDivisionError for a division by zero.
    """
    if operator == "+":
        return left + right
    if operator == "-":
        return left - right
    if operator == "*":
        return left * right
    if operator == "/":
        if right == 0:
            raise ZeroDivisionError("division by zero")
        return left / right
    raise ValueError(f"unsupported operator: {operator!r}")


def apply_sign(amount: Decimal, negative: bool) -> Decimal:
    """Return -amount when `negative` is true, otherwise amount."""
    return -amount if negative else amount


def decimal_from_implied(digits: str, places: int = 2) -> Decimal:
    """Read a digit string with `places` implied decimals, e.g. '00000000001299' -> 12.99.

    The value is built from the text, so no context rounding is involved. Raises ValueError on an
    empty or non-digit string (ASCII digits only) or a negative `places`.
    """
    if places < 0:
        raise ValueError("places must be >= 0")
    if not digits or not digits.isascii() or not digits.isdigit():
        raise ValueError(f"not a digit string: {digits!r}")
    if places == 0:
        return Decimal(digits)
    padded = digits.rjust(places + 1, "0")
    return Decimal(f"{padded[:-places]}.{padded[-places:]}")


def implied_digits(amount: Decimal, width: int = 14) -> str:
    """Write `amount` as a zero-padded digit string with two implied decimals.

    Rounds half-up to cents first. Raises ValueError for a negative amount, a non-finite one, or one
    that needs more than `width` digits.
    """
    if not amount.is_finite():
        raise ValueError("amount must be finite")
    try:
        rounded = round_to_cents(amount)
    except InvalidOperation as exc:
        raise ValueError("amount is too large") from exc
    if rounded < 0:
        raise ValueError("amount must be >= 0")
    text = "".join(str(d) for d in rounded.as_tuple().digits).lstrip("0") or "0"
    if len(text) > width:
        raise ValueError(f"amount needs more than {width} digits")
    return text.rjust(width, "0")
