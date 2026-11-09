"""Money helpers: the single point of truth for monetary arithmetic and formatting."""

from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation


def round_to_cents(amount: Decimal) -> Decimal:
    """Round to two decimal places using ROUND_HALF_UP (Finance Rule 3)."""
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _european_digits(amount: Decimal) -> str:
    """Return the signed European digit string for `amount`, e.g. '-1.234,56'."""
    rounded = round_to_cents(amount)
    sign = "-" if rounded < 0 else ""
    integer_part, _, frac_part = f"{abs(rounded):.2f}".partition(".")
    return f"{sign}{_group_thousands(integer_part)},{frac_part}"


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
