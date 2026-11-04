"""Money helpers. Amounts are integers in minor units (paise/cents); never floats."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CURRENCY_SYMBOLS = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}
SUPPORTED_CURRENCIES = frozenset(CURRENCY_SYMBOLS)
MINOR_DIGITS = 2  # all four supported currencies use 2 decimal places


def to_minor(value: float | str | Decimal) -> int:
    """Convert a major-unit amount (e.g. 7350.5) to integer minor units (735050).

    Floats are converted through ``str`` so 7350.5 does not pick up binary noise.
    """
    if isinstance(value, bool):
        raise ValueError("boolean is not an amount")
    try:
        dec = value if isinstance(value, Decimal) else Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid amount: {value!r}") from exc
    if not dec.is_finite():
        raise ValueError(f"invalid amount: {value!r}")
    return int((dec * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def to_major(minor: int) -> Decimal:
    return (Decimal(minor) / 100).quantize(Decimal("0.01"))


def _group_indian(int_part: str) -> str:
    if len(int_part) <= 3:
        return int_part
    head, tail = int_part[:-3], int_part[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join(groups + [tail])


def _group_western(int_part: str) -> str:
    return f"{int(int_part):,}"


def format_amount(minor: int, currency: str, symbol: bool = True) -> str:
    """Format minor units for display. INR uses Indian grouping (₹1,18,000.00)."""
    negative = minor < 0
    minor = abs(minor)
    int_part, frac = divmod(minor, 100)
    grouped = _group_indian(str(int_part)) if currency == "INR" else _group_western(str(int_part))
    text = f"{grouped}.{frac:02d}"
    if symbol:
        text = f"{CURRENCY_SYMBOLS.get(currency, currency + ' ')}{text}"
    return f"-{text}" if negative else text


def tds_minor(subtotal_minor: int, rate_percent: int = 10) -> int:
    """TDS = rate% of the invoice subtotal (policy: 10% of subtotal for Indian customers)."""
    return int((Decimal(subtotal_minor) * rate_percent / 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
